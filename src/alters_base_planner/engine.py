from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from time import monotonic

from ortools.sat.python import cp_model

from .base import builtin_base
from .catalog import MODULE_BY_KEY, MODULES
from .distance import evaluate_distances, weighted_modified_manhattan_lower_bound
from .models import (
    BaseGeometry,
    ModuleInstance,
    ModulePlacement,
    PlacementAuthority,
    PlanRequest,
    PlanResult,
    ResolvedPort,
    expand_instances,
    footprint_cells,
    resolve_ports,
)

_CORRIDOR_SPEC = MODULE_BY_KEY["corridor"]
_ELEVATOR_SPEC = MODULE_BY_KEY["elevator"]
if (
    _CORRIDOR_SPEC.authority is not PlacementAuthority.SOLVER
    or _ELEVATOR_SPEC.authority is not PlacementAuthority.SOLVER
):
    raise RuntimeError("Corridor and Elevator must be SOLVER-managed modules")
if (_CORRIDOR_SPEC.width, _CORRIDOR_SPEC.height) != (
    _ELEVATOR_SPEC.width,
    _ELEVATOR_SPEC.height,
):
    raise RuntimeError("Current router requires Corridor and Elevator to share one footprint")


@dataclass(frozen=True, slots=True)
class _Candidate:
    x: int
    y: int
    cells: frozenset[tuple[int, int]]
    search_cost: int


def _candidate_positions(instance: ModuleInstance, base: BaseGeometry) -> list[_Candidate]:
    """Enumerate legal room positions using port proximity only as candidate ordering.

    ``PortSpec.cell_y`` is floor-relative, while the Base grid is top-origin. The
    candidate-order surrogate must therefore resolve the port row into world coordinates
    before measuring vertical proximity to the Base centre. This score is not the planner's
    soft objective F; it only biases which hard-feasible room packings CP-SAT exposes first.
    """

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


def _ports_directly_meet(a: ResolvedPort, b: ResolvedPort) -> bool:
    return a.edge_y == b.edge_y and a.edge_x == b.edge_x and a.side is not b.side


def _anchor_cells(anchor: tuple[int, int]) -> frozenset[tuple[int, int]]:
    x, y = anchor
    return footprint_cells(x, y, _CORRIDOR_SPEC.width, _CORRIDOR_SPEC.height)


def _anchor_is_compatible_with_used(
    anchor: tuple[int, int], used: set[tuple[int, int]]
) -> bool:
    """An exact reused anchor is legal; a partial overlap with another utility is not."""

    if anchor in used:
        return True
    cells = _anchor_cells(anchor)
    return all(not (cells & _anchor_cells(other)) for other in used)


def _validate_utility_geometry(
    base: BaseGeometry,
    rooms: list[ModulePlacement],
    utilities: list[ModulePlacement],
) -> None:
    """Fail fast if generated SOLVER modules violate physical occupancy constraints."""

    room_cells = set().union(*(room.cells for room in rooms)) if rooms else set()
    utility_cells: set[tuple[int, int]] = set()
    seen_anchors: set[tuple[int, int]] = set()

    for utility in utilities:
        spec = MODULE_BY_KEY.get(utility.module_key)
        if spec is None or spec.authority is not PlacementAuthority.SOLVER:
            raise AssertionError(
                f"Generated infrastructure {utility.instance_id} is not a SOLVER module"
            )
        if (utility.width, utility.height) != (spec.width, spec.height):
            raise AssertionError(
                f"Generated utility {utility.instance_id} footprint does not match its ModuleSpec"
            )
        anchor = (utility.x, utility.y)
        if anchor in seen_anchors:
            raise AssertionError(f"Duplicate generated utility anchor at {anchor}")
        seen_anchors.add(anchor)
        if not utility.cells <= base.buildable_cells:
            raise AssertionError(f"Generated utility lies outside buildable base cells: {anchor}")
        if utility.cells & room_cells:
            raise AssertionError(f"Generated utility overlaps a room at {anchor}")
        overlap = utility.cells & utility_cells
        if overlap:
            raise AssertionError(
                f"Generated utility modules overlap at cells {sorted(overlap)}; anchor={anchor}"
            )
        utility_cells.update(utility.cells)


def _room_port_components(
    rooms: list[ModulePlacement],
    base: BaseGeometry,
    occupied: set[tuple[int, int]],
) -> tuple[dict[int, set[int]], dict[int, set[tuple[int, int]]], int] | None:
    """Build physical connectivity components from explicit room ports."""

    room_ports = [resolve_ports(room, MODULE_BY_KEY[room.module_key]) for room in rooms]
    port_index: dict[tuple[int, int], int] = {}
    next_index = 0
    for room_idx, ports in enumerate(room_ports):
        for local_idx in range(len(ports)):
            port_index[(room_idx, local_idx)] = next_index
            next_index += 1

    parent = list(range(next_index))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Inside a walk-through room all explicit ports belong to one physical component.
    for room_idx, room in enumerate(rooms):
        if not MODULE_BY_KEY[room.module_key].transit_allowed:
            continue
        indices = [port_index[(room_idx, i)] for i in range(len(room_ports[room_idx]))]
        for other in indices[1:]:
            union(indices[0], other)

    # Two rooms join directly only where compatible explicit boundary ports meet.
    for i, ports_a in enumerate(room_ports):
        for j in range(i + 1, len(rooms)):
            for local_a, port_a in enumerate(ports_a):
                for local_b, port_b in enumerate(room_ports[j]):
                    if _ports_directly_meet(port_a, port_b):
                        union(port_index[(i, local_a)], port_index[(j, local_b)])

    module_components: dict[int, set[int]] = {}
    component_anchors: dict[int, set[tuple[int, int]]] = {}

    for room_idx, ports in enumerate(room_ports):
        components: set[int] = set()
        for local_idx, port in enumerate(ports):
            root = find(port_index[(room_idx, local_idx)])
            components.add(root)
            x, row = port.utility_anchor
            # A horizontal port at the Base edge can resolve to a negative/outside anchor.
            # Reject that anchor before constructing its footprint; it is simply unavailable.
            if x < 0 or x + _CORRIDOR_SPEC.width > base.width:
                continue
            cells = _anchor_cells((x, row))
            if cells <= base.buildable_cells and not (cells & occupied):
                component_anchors.setdefault(root, set()).add((x, row))
        module_components[room_idx] = components

    airlock_idx = next(
        (idx for idx, room in enumerate(rooms) if room.module_key == "airlock"),
        None,
    )
    if airlock_idx is None or not room_ports[airlock_idx]:
        return None
    root_component = find(port_index[(airlock_idx, 0)])
    return module_components, component_anchors, root_component


def _neighbors(anchor: tuple[int, int], valid: set[tuple[int, int]]) -> list[tuple[int, int]]:
    x, y = anchor
    candidates = (
        (x - _CORRIDOR_SPEC.width, y),
        (x + _CORRIDOR_SPEC.width, y),
        (x, y - 1),
        (x, y + 1),
    )
    return [p for p in candidates if p in valid]


def _shortest_path(
    starts: set[tuple[int, int]],
    goals: set[tuple[int, int]],
    valid: set[tuple[int, int]],
) -> list[tuple[int, int]] | None:
    if not starts or not goals:
        return None
    q = deque(sorted(starts))
    prev: dict[tuple[int, int], tuple[int, int] | None] = {s: None for s in starts}
    hit = None
    while q:
        cur = q.popleft()
        if cur in goals:
            hit = cur
            break
        for nxt in sorted(_neighbors(cur, valid)):
            if nxt not in prev:
                prev[nxt] = cur
                q.append(nxt)
    if hit is None:
        return None
    path = [hit]
    while prev[path[-1]] is not None:
        path.append(prev[path[-1]])
    path.reverse()
    return path


def _route_utilities(
    base: BaseGeometry, rooms: list[ModulePlacement]
) -> list[ModulePlacement] | None:
    """Create non-overlapping Corridors/Elevators automatically from explicit room ports."""

    occupied: set[tuple[int, int]] = set().union(*(r.cells for r in rooms)) if rooms else set()
    valid_anchors: set[tuple[int, int]] = set()
    for y in range(base.height - _CORRIDOR_SPEC.height + 1):
        for x in range(base.width - _CORRIDOR_SPEC.width + 1):
            cells = _anchor_cells((x, y))
            if cells <= base.buildable_cells and not (cells & occupied):
                valid_anchors.add((x, y))

    port_data = _room_port_components(rooms, base, occupied)
    if port_data is None:
        return None
    module_components, component_anchors, root_component = port_data

    connected_components = {root_component}
    used: set[tuple[int, int]] = set()
    vertical: set[tuple[int, int]] = set()

    def module_is_connected(idx: int) -> bool:
        return bool(module_components[idx] & connected_components)

    while not all(module_is_connected(idx) for idx in range(len(rooms))):
        routing_valid = {
            anchor for anchor in valid_anchors if _anchor_is_compatible_with_used(anchor, used)
        }
        routing_valid.update(used)

        network = set(used)
        for component in connected_components:
            network.update(
                anchor
                for anchor in component_anchors.get(component, set())
                if anchor in routing_valid
            )
        if not network:
            return None

        best_component: int | None = None
        best_path: list[tuple[int, int]] | None = None
        candidate_components = {
            component
            for idx in range(len(rooms))
            if not module_is_connected(idx)
            for component in module_components[idx]
            if component not in connected_components
        }

        for component in sorted(candidate_components):
            starts = {
                anchor
                for anchor in component_anchors.get(component, set())
                if anchor in routing_valid
            }
            path = _shortest_path(starts, network, routing_valid)
            if path is not None and (best_path is None or len(path) < len(best_path)):
                best_component = component
                best_path = path

        if best_component is None or best_path is None:
            return None

        # A path moves horizontally by one complete utility footprint or vertically at
        # identical x. It cannot overlap itself; routing_valid prevents earlier-path overlap.
        used.update(best_path)
        for a, b in zip(best_path, best_path[1:], strict=False):
            if a[0] == b[0]:
                vertical.add(a)
                vertical.add(b)
        connected_components.add(best_component)

    counters: Counter[str] = Counter()
    utilities: list[ModulePlacement] = []
    for anchor in sorted(used):
        module_key = "elevator" if anchor in vertical else "corridor"
        spec = MODULE_BY_KEY[module_key]
        counters[module_key] += 1
        utilities.append(
            ModulePlacement(
                f"{module_key}-{counters[module_key]}",
                module_key,
                anchor[0],
                anchor[1],
                spec.width,
                spec.height,
            )
        )
    _validate_utility_geometry(base, rooms, utilities)
    return utilities


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
    """Remove pure label permutations between identical room instances."""

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
    """Find hard-feasible layouts and minimize exact weighted room-pair travel distance.

    `time_limit_s` is a single wall-clock search budget for the whole solve operation,
    not a fresh allowance for every no-good iteration. Modified Manhattan is an
    admissible port-to-port lower bound used to prune room packings whose theoretical
    best score is already worse than the best exact layout.

    CP-SAT currently solves the discrete room-placement feasibility problem. Its small
    centre/proximity objective is only a candidate-order surrogate; it is not the planner's
    soft objective. The final objective always uses legal graph paths: endpoint rooms cost 0,
    each Corridor/Elevator costs +1, and an intermediate transit room costs its full width.
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
    for inst in instances:
        cand = _candidate_positions(inst, base)
        if not cand:
            result = PlanResult(
                status="INFEASIBLE",
                base=base,
                message=f"No legal position for {inst.spec.name}",
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
        candidates[inst.instance_id] = cand
        variables = [
            model.new_bool_var(f"p_{inst.instance_id}_{idx}") for idx in range(len(cand))
        ]
        vars_by_instance[inst.instance_id] = variables
        model.add_exactly_one(variables)
        for var, pos in zip(variables, cand, strict=True):
            for cell in pos.cells:
                cell_vars.setdefault(cell, []).append(var)
            candidate_order_terms.append(pos.search_cost * var)

    for variables in cell_vars.values():
        model.add_at_most_one(variables)

    _add_identical_instance_symmetry_breaking(model, instances, vars_by_instance)

    # This is deliberately not the planner objective F. It only orders the sequence of
    # room packings explored by the current placement-then-routing architecture.
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
        for inst in instances:
            for idx, var in enumerate(vars_by_instance[inst.instance_id]):
                if solver.value(var):
                    pos = candidates[inst.instance_id][idx]
                    rooms.append(
                        ModulePlacement(
                            inst.instance_id,
                            inst.spec.key,
                            pos.x,
                            pos.y,
                            inst.spec.width,
                            inst.spec.height,
                        )
                    )
                    chosen_vars.append(var)
                    break

        if len(chosen_vars) != len(instances):
            raise AssertionError("CP-SAT solution did not select exactly one placement per room")

        manhattan_lb = weighted_modified_manhattan_lower_bound(rooms)
        if (
            best_result is not None
            and best_result.weighted_distance_score is not None
            and manhattan_lb > best_result.weighted_distance_score + 1e-12
        ):
            manhattan_pruned += 1
            model.add(sum(chosen_vars) <= len(chosen_vars) - 1)
            continue

        utilities = _route_utilities(base, rooms)
        if utilities is not None:
            try:
                distance_metrics = evaluate_distances(rooms, utilities)
            except ValueError:
                distance_metrics = None

            # AssertionError is deliberately not caught: it represents a violated internal
            # solver invariant and must fail fast instead of silently discarding a valid layout.
            if distance_metrics is not None:
                connected_candidates += 1
                room_mass, utility_mass, total_mass, margin, travel_ok, breakdown = _mass_metrics(
                    base, rooms, utilities
                )
                room_usage_weights = {
                    room.instance_id: MODULE_BY_KEY[room.module_key].visit_weight for room in rooms
                }
                message = (
                    f"Hard-feasible connected candidate. Objective "
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
                    rooms=rooms,
                    utilities=utilities,
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
                if best_result is None or _candidate_rank(candidate_result) < _candidate_rank(
                    best_result
                ):
                    best_result = candidate_result

        model.add(sum(chosen_vars) <= len(chosen_vars) - 1)
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
            f"{stop_reason}. Identical-room label permutations are symmetry-broken. Mass is a "
            "tie-breaker only. Global optimality is not yet proven until placement and routing "
            "are integrated in one exact model."
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
            message="No feasible room packing exists for the selected base and room set",
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
                "Room packings were physically feasible, but automatic corridor/elevator "
                f"routing found no connected layout before {reason}. Try a larger tier, fewer "
                "rooms, or a larger search budget."
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
