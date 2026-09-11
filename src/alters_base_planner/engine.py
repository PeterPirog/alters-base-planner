from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from time import monotonic

from ortools.sat.python import cp_model

from .base import builtin_base
from .catalog import MODULE_BY_KEY, MODULES
from .fixed_flow_objective_solver import solve_fixed_layout_flow_objective
from .models import (
    BaseGeometry,
    ModuleInstance,
    ModulePlacement,
    PlacementAuthority,
    PlanRequest,
    PlanResult,
    expand_instances,
    footprint_cells,
)
from .objective import ScaledObjective, build_scaled_objective, scaled_modified_manhattan_lower_bound


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
        if spec is None or spec.authority is not PlacementAuthority.SOLVER:
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


def _candidate_rank(result: PlanResult) -> tuple[int, int, int, int]:
    if result.scaled_objective_value is None:
        raise AssertionError("Cannot rank a candidate without an exact scaled objective value")
    return (
        result.scaled_objective_value,
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
    fixed_objective_optima_proven: int,
    manhattan_pruned: int,
    started_at: float,
    time_limit_reached: bool,
    search_exhausted: bool,
) -> None:
    result.attempts = attempts
    result.connected_candidates_examined = connected_candidates
    result.fixed_objective_optima_proven = fixed_objective_optima_proven
    result.manhattan_pruned_count = manhattan_pruned
    result.search_time_s = monotonic() - started_at
    result.time_limit_reached = time_limit_reached
    result.search_exhausted = search_exhausted


def _validate_master_instances(
    instances: list[ModuleInstance],
    *,
    root_instance_id: str,
) -> None:
    if not instances:
        raise ValueError("Exact decomposition requires at least one non-SOLVER module instance")
    instance_ids = [instance.instance_id for instance in instances]
    if len(instance_ids) != len(set(instance_ids)):
        raise ValueError("Module instance IDs must be unique")
    if any(instance.spec.authority is PlacementAuthority.SOLVER for instance in instances):
        raise ValueError("SOLVER modules must not be supplied to the room-packing master")
    root = next((instance for instance in instances if instance.instance_id == root_instance_id), None)
    if root is None or root.spec.key != "airlock":
        raise ValueError("Exact decomposition root instance must identify the Airlock")
    if sum(instance.spec.key == "airlock" for instance in instances) != 1:
        raise ValueError("Exact decomposition requires exactly one Airlock instance")


def _solve_instances(
    base: BaseGeometry,
    instances: list[ModuleInstance],
    *,
    time_limit_s: float,
    max_layout_attempts: int,
    root_instance_id: str = "airlock-1",
    started_at: float | None = None,
) -> PlanResult:
    """Exact objective decomposition over a supplied non-SOLVER instance set.

    This internal entry point is also used by tiny known-optimum tests. Production `solve_plan()`
    supplies the canonical SYSTEM/PLAYER instance set produced by `expand_instances()`.
    """

    _validate_master_instances(instances, root_instance_id=root_instance_id)
    if time_limit_s <= 0:
        raise ValueError("time_limit_s must be positive")
    if max_layout_attempts <= 0:
        raise ValueError("max_layout_attempts must be positive")

    started_at = monotonic() if started_at is None else started_at
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
                fixed_objective_optima_proven=0,
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
    common_objective: ScaledObjective | None = None
    connected_candidates = 0
    fixed_objective_optima_proven = 0
    manhattan_pruned = 0
    room_packings_examined = 0
    time_limit_reached = False
    search_exhausted = False
    attempt_limit_reached = False
    all_fixed_objectives_resolved = True
    deadline = started_at + float(time_limit_s)

    for _ in range(max_layout_attempts):
        remaining = deadline - monotonic()
        if remaining <= 0:
            time_limit_reached = True
            all_fixed_objectives_resolved = False
            break

        solver.parameters.max_time_in_seconds = max(0.001, remaining)
        status = solver.solve(model)

        if status == cp_model.MODEL_INVALID:
            raise RuntimeError("CP-SAT rejected the generated placement model as invalid")
        if status == cp_model.UNKNOWN:
            time_limit_reached = True
            all_fixed_objectives_resolved = False
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

        objective = build_scaled_objective(rooms)
        if common_objective is None:
            common_objective = objective
        elif objective != common_objective:
            raise AssertionError(
                "Objective coefficients changed across room packings for one planning request"
            )

        scaled_lower_bound = scaled_modified_manhattan_lower_bound(rooms, objective)
        if best_result is not None:
            incumbent = best_result.scaled_objective_value
            if incumbent is None:
                raise AssertionError("Incumbent is missing its exact scaled objective")
            if scaled_lower_bound > incumbent:
                manhattan_pruned += 1
                model.add(sum(chosen_vars) <= len(chosen_vars) - 1)
                continue

        remaining = deadline - monotonic()
        if remaining <= 0:
            time_limit_reached = True
            all_fixed_objectives_resolved = False
            break

        fixed_result = solve_fixed_layout_flow_objective(
            base,
            tuple(rooms),
            time_limit_s=remaining,
            root_instance_id=root_instance_id,
        )
        if fixed_result.status == "TIME_LIMIT":
            time_limit_reached = True
            all_fixed_objectives_resolved = False
            break
        if fixed_result.status == "INFEASIBLE":
            model.add(sum(chosen_vars) <= len(chosen_vars) - 1)
            continue
        if fixed_result.status not in {"OPTIMAL", "FEASIBLE"}:
            raise AssertionError(f"Unexpected fixed objective status: {fixed_result.status}")
        if fixed_result.distance_metrics is None:
            raise AssertionError("Fixed objective solver returned a candidate without distances")
        if fixed_result.objective_scale != objective.scale:
            raise AssertionError(
                "Fixed objective solver and master use different exact objective scales"
            )

        utilities = list(fixed_result.utilities)
        _validate_utility_geometry(base, rooms, utilities)
        distance_metrics = fixed_result.distance_metrics
        exact_scaled_score = objective.scaled_score(distance_metrics.pairwise_distances)
        if scaled_lower_bound > exact_scaled_score:
            raise AssertionError(
                "Exact objective fell below the scaled modified-Manhattan lower bound: "
                f"exact={exact_scaled_score}, lower_bound={scaled_lower_bound}"
            )

        if fixed_result.scaled_objective_value is not None:
            if fixed_result.scaled_objective_value != exact_scaled_score:
                raise AssertionError(
                    "Fixed objective solver scaled score disagrees with exact Dijkstra distances"
                )

        fixed_proven = (
            fixed_result.status == "OPTIMAL" and fixed_result.lexicographic_optimum_proven
        )
        if fixed_result.status == "OPTIMAL" and not fixed_proven:
            raise AssertionError("OPTIMAL fixed objective result lacks lexicographic proof")
        if fixed_proven:
            fixed_objective_optima_proven += 1
        else:
            all_fixed_objectives_resolved = False

        exact_score = objective.unscaled_score(exact_scaled_score)
        exact_lower_bound = objective.unscaled_score(scaled_lower_bound)
        if abs(exact_score - distance_metrics.weighted_score) > 1e-9:
            raise AssertionError(
                "Scaled objective disagrees with floating evaluator score: "
                f"scaled={exact_score}, evaluator={distance_metrics.weighted_score}"
            )
        if abs(exact_lower_bound - distance_metrics.weighted_manhattan_lower_bound) > 1e-9:
            raise AssertionError(
                "Scaled lower bound disagrees with evaluator lower bound: "
                f"scaled={exact_lower_bound}, "
                f"evaluator={distance_metrics.weighted_manhattan_lower_bound}"
            )

        connected_candidates += 1
        room_mass, utility_mass, total_mass, margin, travel_ok, breakdown = _mass_metrics(
            base, rooms, utilities
        )
        room_usage_weights = {
            room.instance_id: MODULE_BY_KEY[room.module_key].visit_weight for room in rooms
        }
        fixed_status = "proven fixed-packing optimum" if fixed_proven else "best-known fixed packing"
        message = (
            f"Exact-objective connected candidate ({fixed_status}). Objective {exact_score:.4f}; "
            f"scaled objective {exact_scaled_score}/{objective.scale}; modified-Manhattan lower "
            f"bound {exact_lower_bound:.4f}; Elevator modules "
            f"{distance_metrics.elevator_module_count}; Corridors {distance_metrics.corridor_count}; "
            f"Base Mass {total_mass}; journey requires {total_mass} Organics; tank capacity "
            f"{base.organics_capacity}. Travel at full tank: {'YES' if travel_ok else 'NO'}."
        )
        candidate_result = PlanResult(
            status="FEASIBLE",
            base=base,
            modules=[*rooms, *utilities],
            objective_value=exact_score,
            objective_scale=objective.scale,
            scaled_objective_value=exact_scaled_score,
            scaled_modified_manhattan_lower_bound=scaled_lower_bound,
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
            weighted_distance_score=exact_score,
            normalized_weighted_distance=distance_metrics.normalized_weighted_distance,
            modified_manhattan_lower_bound=exact_lower_bound,
            pairwise_distances=distance_metrics.pairwise_distances,
            pairwise_contributions=distance_metrics.pairwise_contributions,
            room_usage_weights=room_usage_weights,
            global_objective_optimum_proven=False,
        )
        if best_result is None or _candidate_rank(candidate_result) < _candidate_rank(best_result):
            best_result = candidate_result

        model.add(sum(chosen_vars) <= len(chosen_vars) - 1)
        if fixed_result.time_limit_reached or not fixed_proven:
            time_limit_reached = True
            break
    else:
        attempt_limit_reached = True
        all_fixed_objectives_resolved = False

    if monotonic() >= deadline and not search_exhausted:
        time_limit_reached = True
        all_fixed_objectives_resolved = False

    global_optimum_proven = bool(
        best_result is not None
        and search_exhausted
        and all_fixed_objectives_resolved
        and not time_limit_reached
        and not attempt_limit_reached
    )

    if best_result is not None:
        best_result.global_objective_optimum_proven = global_optimum_proven
        _finalize_search_diagnostics(
            best_result,
            attempts=room_packings_examined,
            connected_candidates=connected_candidates,
            fixed_objective_optima_proven=fixed_objective_optima_proven,
            manhattan_pruned=manhattan_pruned,
            started_at=started_at,
            time_limit_reached=time_limit_reached,
            search_exhausted=search_exhausted,
        )
        if search_exhausted:
            stop_reason = "room-packing search exhausted"
        elif time_limit_reached:
            stop_reason = f"global {time_limit_s:g}s search budget reached"
        elif attempt_limit_reached:
            stop_reason = f"{max_layout_attempts} layout-attempt limit reached"
        else:
            stop_reason = "search stopped"

        proof_text = (
            "Global exact lexicographic optimum PROVEN: every physical room packing was either "
            "solved to its exact fixed-packing objective optimum, proven infrastructure-"
            "infeasible, or excluded by a strict exact integer admissible lower bound."
            if global_optimum_proven
            else "Global objective optimality is not proven for this run."
        )
        best_result.message += (
            f" Best objective among {connected_candidates} connected candidates examined from "
            f"{room_packings_examined} unique room packings; {fixed_objective_optima_proven} "
            f"fixed-packing lexicographic optima proven; {manhattan_pruned} additional packings "
            "pruned by the strict exact-integer modified-Manhattan lower bound; "
            f"{stop_reason}. Identical-module label permutations are symmetry-broken. "
            f"{proof_text}"
        )
        return best_result

    if time_limit_reached:
        result = PlanResult(
            status="TIME_LIMIT",
            base=base,
            attempts=room_packings_examined,
            message=(
                f"No connected layout was found within the global {time_limit_s:g}s search "
                f"budget after examining {room_packings_examined} unique room packings."
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
            "the complete exact room-packing search was exhausted"
            if search_exhausted
            else f"the {max_layout_attempts} layout-attempt limit was reached"
        )
        result = PlanResult(
            status="NO_CONNECTED_LAYOUT",
            base=base,
            attempts=room_packings_examined,
            message=(
                "SYSTEM/PLAYER module packings were physically feasible, but no connected "
                "Corridor/Elevator layout exists among the exactly resolved packings before "
                f"{reason}."
            ),
        )

    _finalize_search_diagnostics(
        result,
        attempts=room_packings_examined,
        connected_candidates=connected_candidates,
        fixed_objective_optima_proven=fixed_objective_optima_proven,
        manhattan_pruned=manhattan_pruned,
        started_at=started_at,
        time_limit_reached=time_limit_reached,
        search_exhausted=search_exhausted,
    )
    return result


def solve_plan(request: PlanRequest, base: BaseGeometry | None = None) -> PlanResult:
    """Optimize the Base with an exact room-packing / fixed-objective decomposition.

    Stage 3 production search now uses:

    1. a CP-SAT master that enumerates legal SYSTEM/PLAYER room packings;
    2. the exact pair-flow CP-SAT subproblem that jointly selects Corridor/Elevator
       infrastructure and proves the accepted fixed-packing lexicographic objective;
    3. exact integer modified-Manhattan lower bounds to prune only when a packing cannot match
       the incumbent primary objective;
    4. exact integer objective ranking across fixed-packing optima.

    A run reports `global_objective_optimum_proven=True` only after the master is exhausted and
    every unpruned fixed packing has been solved exactly or proven infrastructure-infeasible.
    Time or layout-attempt limits therefore preserve best-known semantics rather than creating a
    false global proof.
    """

    started_at = monotonic()
    if base is not None and base.tier != request.tier:
        raise ValueError(
            f"PlanRequest tier {request.tier} does not match supplied BaseGeometry tier {base.tier}"
        )
    base = base or builtin_base(request.tier)
    instances = expand_instances(MODULES, request.room_counts)
    return _solve_instances(
        base,
        instances,
        time_limit_s=float(request.time_limit_s),
        max_layout_attempts=request.max_layout_attempts,
        started_at=started_at,
    )
