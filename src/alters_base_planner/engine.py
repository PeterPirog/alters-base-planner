from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from time import monotonic

from ortools.sat.python import cp_model

from .base import builtin_base
from .catalog import MODULE_BY_KEY, MODULES
from .distance import evaluate_distances, weighted_modified_manhattan_lower_bound
from .integrated_hard_solver import solve_fixed_layout_infrastructure
from .models import (
    BaseGeometry,
    ModuleInstance,
    ModulePlacement,
    PlanRequest,
    PlanResult,
    expand_instances,
    footprint_cells,
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    x: int
    y: int
    cells: frozenset[tuple[int, int]]
    search_cost: int


def _candidate_positions(instance: ModuleInstance, base: BaseGeometry) -> list[_Candidate]:
    """Enumerate legal non-SOLVER positions; ``search_cost`` only orders candidates."""

    spec = instance.spec
    cx = (base.width - 1) / 2
    cy = (base.height - 1) / 2
    result: list[_Candidate] = []
    mean_world_port_offset = sum(
        spec.height - 1 - port.cell_y for port in spec.ports
    ) / len(spec.ports)
    for y in range(base.height - spec.height + 1):
        for x in range(base.width - spec.width + 1):
            cells = footprint_cells(x, y, spec.width, spec.height)
            if not cells <= base.buildable_cells:
                continue
            px = x + (spec.width - 1) / 2
            py = y + mean_world_port_offset
            distance = abs(px - cx) + 0.35 * abs(py - cy)
            search_cost = int(100 * max(spec.visit_weight, 0.05) * distance)
            result.append(_Candidate(x, y, cells, search_cost))
    return result


def _validate_utility_geometry(
    base: BaseGeometry,
    rooms: list[ModulePlacement],
    utilities: list[ModulePlacement],
) -> None:
    """Fail fast if selected SOLVER modules violate physical occupancy constraints."""

    room_cells = set().union(*(room.cells for room in rooms)) if rooms else set()
    utility_cells: set[tuple[int, int]] = set()
    seen_anchors: set[tuple[int, int]] = set()

    for utility in utilities:
        spec = MODULE_BY_KEY.get(utility.module_key)
        if spec is None or spec.authority.value != "solver":
            raise AssertionError(
                f"Selected infrastructure {utility.instance_id} is not a SOLVER module"
            )
        if (utility.width, utility.height) != (spec.width, spec.height):
            raise AssertionError(
                f"Selected utility {utility.instance_id} footprint does not match its ModuleSpec"
            )
        anchor = (utility.x, utility.y)
        if anchor in seen_anchors:
            raise AssertionError(f"Duplicate selected utility anchor at {anchor}")
        seen_anchors.add(anchor)
        if not utility.cells <= base.buildable_cells:
            raise AssertionError(f"Selected utility lies outside buildable Base cells: {anchor}")
        if utility.cells & room_cells:
            raise AssertionError(f"Selected utility overlaps a room at {anchor}")
        overlap = utility.cells & utility_cells
        if overlap:
            raise AssertionError(
                f"Selected utility modules overlap at cells {sorted(overlap)}; anchor={anchor}"
            )
        utility_cells.update(utility.cells)


def _mass_metrics(
    base: BaseGeometry,
    rooms: list[ModulePlacement],
    utilities: list[ModulePlacement],
) -> tuple[int, int, int, int, bool, dict[str, int]]:
    room_mass = sum(MODULE_BY_KEY[room.module_key].mass for room in rooms)
    utility_mass = sum(MODULE_BY_KEY[utility.module_key].mass for utility in utilities)
    total_mass = room_mass + utility_mass
    margin = base.organics_capacity - total_mass

    counts = Counter(module.module_key for module in (*rooms, *utilities))
    mass_breakdown = {
        key: count * MODULE_BY_KEY[key].mass for key, count in sorted(counts.items())
    }
    return room_mass, utility_mass, total_mass, margin, margin >= 0, mass_breakdown


def _candidate_rank(result: PlanResult) -> tuple[float, int, int, int]:
    return (
        float(result.weighted_distance_score or 0.0),
        result.total_mass,
        result.elevator_module_count,
        result.corridor_count,
    )


def _add_identical_instance_symmetry_breaking(
    model: cp_model.CpModel,
    instances: list[ModuleInstance],
    vars_by_instance: dict[str, list[cp_model.IntVar]],
) -> None:
    """Remove pure label permutations between identical module instances."""

    groups: dict[str, list[ModuleInstance]] = {}
    for instance in instances:
        groups.setdefault(instance.spec.key, []).append(instance)

    for group in groups.values():
        if len(group) < 2:
            continue
        for left, right in zip(group, group[1:], strict=False):
            left_vars = vars_by_instance[left.instance_id]
            right_vars = vars_by_instance[right.instance_id]
            if len(left_vars) != len(right_vars):
                raise AssertionError("Identical module instances must have identical candidates")
            left_rank = sum(index * var for index, var in enumerate(left_vars))
            right_rank = sum(index * var for index, var in enumerate(right_vars))
            model.add(left_rank < right_rank)


def _finalize_search_diagnostics(
    result: PlanResult,
    *,
    attempts: int,
    connected_candidates: int,
    manhattan_pruned: int,
    started_at: float,
    time_limit_reached: bool,
    search_exhausted: bool,
) -> None:
    result.attempts = attempts
    result.connected_candidates_examined = connected_candidates
    result.manhattan_pruned_count = manhattan_pruned
    result.search_time_s = monotonic() - started_at
    result.time_limit_reached = time_limit_reached
    result.search_exhausted = search_exhausted


def solve_plan(request: PlanRequest, base: BaseGeometry | None = None) -> PlanResult:
    """Search room packings with an exact Corridor/Elevator hard-feasibility subproblem.

    Stage 2 uses an exact decomposition for hard feasibility:

    1. the master CP-SAT model enumerates legal SYSTEM/PLAYER room packings;
    2. a separate CP-SAT subproblem decides Corridor/Elevator selection and proves rooted
       connectivity for each fixed packing;
    3. the exact graph evaluator computes distances and gameplay objective ``F`` for the
       infrastructure witness returned by the hard-feasibility subproblem.

    This removes the greedy post-router from correctness. Global objective optimality is still
    not claimed because Stage 3 must optimize true ``F`` over infrastructure alternatives,
    rather than evaluating only one hard-feasible infrastructure witness per room packing.
    """

    started_at = monotonic()
    if base is not None and base.tier != request.tier:
        raise ValueError(
            f"PlanRequest tier {request.tier} does not match supplied BaseGeometry tier {base.tier}"
        )
    base = base or builtin_base(request.tier)
    instances = expand_instances(MODULES, request.room_counts)
    model = cp_model.CpModel()
    candidates: dict[str, list[_Candidate]] = {}
    vars_by_instance: dict[str, list[cp_model.IntVar]] = {}
    cell_vars: dict[tuple[int, int], list[cp_model.IntVar]] = {}

    candidate_order_terms = []
    for instance in instances:
        candidate_list = _candidate_positions(instance, base)
        if not candidate_list:
            result = PlanResult(
                status="INFEASIBLE",
                base=base,
                message=f"No legal position for {instance.spec.name}",
            )
            _finalize_search_diagnostics(
                result,
                attempts=0,
                connected_candidates=0,
                manhattan_pruned=0,
                started_at=started_at,
                time_limit_reached=False,
                search_exhausted=True,
            )
            return result
        candidates[instance.instance_id] = candidate_list
        variables = [
            model.new_bool_var(f"p_{instance.instance_id}_{idx}")
            for idx in range(len(candidate_list))
        ]
        vars_by_instance[instance.instance_id] = variables
        model.add_exactly_one(variables)
        for var, position in zip(variables, candidate_list, strict=True):
            for cell in position.cells:
                cell_vars.setdefault(cell, []).append(var)
            candidate_order_terms.append(position.search_cost * var)

    for variables in cell_vars.values():
        model.add_at_most_one(variables)

    _add_identical_instance_symmetry_breaking(model, instances, vars_by_instance)
    model.minimize(sum(candidate_order_terms))

    validation_error = model.validate()
    if validation_error:
        raise RuntimeError(f"Invalid generated CP-SAT placement model: {validation_error}")

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 8

    best_result: PlanResult | None = None
    connected_candidates = 0
    manhattan_pruned = 0
    room_packings_examined = 0
    time_limit_reached = False
    search_exhausted = False
    attempt_limit_reached = False
    deadline = started_at + float(request.time_limit_s)

    for _ in range(request.max_layout_attempts):
        remaining = deadline - monotonic()
        if remaining <= 0:
            time_limit_reached = True
            break

        solver.parameters.max_time_in_seconds = max(0.001, remaining)
        status = solver.solve(model)

        if status == cp_model.MODEL_INVALID:
            raise RuntimeError("CP-SAT rejected the generated placement model as invalid")
        if status == cp_model.UNKNOWN:
            time_limit_reached = True
            break
        if status == cp_model.INFEASIBLE:
            search_exhausted = True
            break
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise RuntimeError(f"Unexpected CP-SAT status: {status}")

        room_packings_examined += 1
        rooms: list[ModulePlacement] = []
        chosen_vars: list[cp_model.IntVar] = []
        for instance in instances:
            for idx, var in enumerate(vars_by_instance[instance.instance_id]):
                if solver.value(var):
                    position = candidates[instance.instance_id][idx]
                    rooms.append(
                        ModulePlacement(
                            instance_id=instance.instance_id,
                            module_key=instance.spec.key,
                            x=position.x,
                            y=position.y,
                            width=instance.spec.width,
                            height=instance.spec.height,
                        )
                    )
                    chosen_vars.append(var)
                    break

        if len(chosen_vars) != len(instances):
            raise AssertionError("CP-SAT solution did not select exactly one placement per module")

        manhattan_lb = weighted_modified_manhattan_lower_bound(rooms)
        if (
            best_result is not None
            and best_result.weighted_distance_score is not None
            and manhattan_lb > best_result.weighted_distance_score + 1e-12
        ):
            manhattan_pruned += 1
            model.add(sum(chosen_vars) <= len(chosen_vars) - 1)
            continue

        remaining = deadline - monotonic()
        if remaining <= 0:
            time_limit_reached = True
            break

        infrastructure_result = solve_fixed_layout_infrastructure(
            base,
            tuple(rooms),
            time_limit_s=remaining,
        )
        if infrastructure_result.status == "TIME_LIMIT":
            time_limit_reached = True
            break
        if infrastructure_result.status == "INFEASIBLE":
            model.add(sum(chosen_vars) <= len(chosen_vars) - 1)
            continue
        if infrastructure_result.status != "FEASIBLE":
            raise AssertionError(
                f"Unexpected infrastructure feasibility status: {infrastructure_result.status}"
            )

        utilities = list(infrastructure_result.utilities)
        _validate_utility_geometry(base, rooms, utilities)
        try:
            distance_metrics = evaluate_distances(rooms, utilities)
        except ValueError as exc:
            raise AssertionError(
                "Exact hard-feasibility subproblem returned a network rejected by the exact "
                "distance/connectivity evaluator"
            ) from exc

        connected_candidates += 1
        room_mass, utility_mass, total_mass, margin, travel_ok, breakdown = _mass_metrics(
            base, rooms, utilities
        )
        room_usage_weights = {
            room.instance_id: MODULE_BY_KEY[room.module_key].visit_weight for room in rooms
        }
        message = (
            f"Exact hard-feasible connected candidate. Objective "
            f"{distance_metrics.weighted_score:.4f}; modified-Manhattan lower bound "
            f"{distance_metrics.weighted_manhattan_lower_bound:.4f}; Elevator modules "
            f"{distance_metrics.elevator_module_count}; Corridors "
            f"{distance_metrics.corridor_count}; Base Mass {total_mass}; journey requires "
            f"{total_mass} Organics; tank capacity {base.organics_capacity}. "
            f"Travel at full tank: {'YES' if travel_ok else 'NO'}."
        )
        candidate_result = PlanResult(
            status="FEASIBLE",
            base=base,
            modules=[*rooms, *utilities],
            objective_value=distance_metrics.weighted_score,
            attempts=room_packings_examined,
            message=message,
            room_mass=room_mass,
            utility_mass=utility_mass,
            total_mass=total_mass,
            organics_required_for_journey=total_mass,
            organics_capacity_margin=margin,
            travel_feasible_at_full_tank=travel_ok,
            mass_breakdown=breakdown,
            elevator_module_count=distance_metrics.elevator_module_count,
            elevator_shaft_count=distance_metrics.elevator_shaft_count,
            corridor_count=distance_metrics.corridor_count,
            weighted_distance_score=distance_metrics.weighted_score,
            normalized_weighted_distance=distance_metrics.normalized_weighted_distance,
            modified_manhattan_lower_bound=distance_metrics.weighted_manhattan_lower_bound,
            pairwise_distances=distance_metrics.pairwise_distances,
            pairwise_contributions=distance_metrics.pairwise_contributions,
            room_usage_weights=room_usage_weights,
            global_objective_optimum_proven=False,
        )
        if best_result is None or _candidate_rank(candidate_result) < _candidate_rank(best_result):
            best_result = candidate_result

        model.add(sum(chosen_vars) <= len(chosen_vars) - 1)
        if infrastructure_result.time_limit_reached:
            time_limit_reached = True
            break
    else:
        attempt_limit_reached = True

    if monotonic() >= deadline and not search_exhausted:
        time_limit_reached = True

    if best_result is not None:
        _finalize_search_diagnostics(
            best_result,
            attempts=room_packings_examined,
            connected_candidates=connected_candidates,
            manhattan_pruned=manhattan_pruned,
            started_at=started_at,
            time_limit_reached=time_limit_reached,
            search_exhausted=search_exhausted,
        )
        if search_exhausted:
            stop_reason = "room-packing search exhausted"
        elif time_limit_reached:
            stop_reason = f"global {request.time_limit_s:g}s search budget reached"
        elif attempt_limit_reached:
            stop_reason = f"{request.max_layout_attempts} layout-attempt limit reached"
        else:
            stop_reason = "search stopped"
        best_result.message += (
            f" Best objective among {connected_candidates} connected candidates examined from "
            f"{room_packings_examined} unique room packings; {manhattan_pruned} additional "
            "packings pruned by the admissible explicit-port modified-Manhattan lower bound; "
            f"{stop_reason}. Identical-module label permutations are symmetry-broken. "
            "Corridor/Elevator hard feasibility is solved exactly for each examined fixed room "
            "packing. Mass is a tie-breaker only. Global objective optimality remains unproven "
            "until true F is optimized over infrastructure alternatives rather than evaluated "
            "for one hard-feasible infrastructure witness per room packing."
        )
        return best_result

    if time_limit_reached:
        result = PlanResult(
            status="TIME_LIMIT",
            base=base,
            attempts=room_packings_examined,
            message=(
                f"No connected layout was found within the global {request.time_limit_s:g}s "
                f"search budget after examining {room_packings_examined} unique room packings."
            ),
        )
    elif search_exhausted and room_packings_examined == 0:
        result = PlanResult(
            status="INFEASIBLE",
            base=base,
            message="No feasible SYSTEM/PLAYER module packing exists for the selected Base",
        )
    else:
        reason = (
            "the complete room-packing search was exhausted"
            if search_exhausted
            else f"the {request.max_layout_attempts} layout-attempt limit was reached"
        )
        result = PlanResult(
            status="NO_CONNECTED_LAYOUT",
            base=base,
            attempts=room_packings_examined,
            message=(
                "SYSTEM/PLAYER module packings were physically feasible, but the exact "
                "Corridor/Elevator hard-feasibility subproblem found no connected layout before "
                f"{reason}."
            ),
        )

    _finalize_search_diagnostics(
        result,
        attempts=room_packings_examined,
        connected_candidates=connected_candidates,
        manhattan_pruned=manhattan_pruned,
        started_at=started_at,
        time_limit_reached=time_limit_reached,
        search_exhausted=search_exhausted,
    )
    return result
