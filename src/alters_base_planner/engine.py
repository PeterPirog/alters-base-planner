from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .base import builtin_base
from .catalog import MODULE_BY_KEY, MODULES
from .models import (
    BaseGeometry,
    ConnectionLevel,
    ModuleInstance,
    Placement,
    PlanRequest,
    PlanResult,
    UtilityPlacement,
    expand_instances,
)

UTILITY_MASS = 2


@dataclass(frozen=True, slots=True)
class _Candidate:
    x: int
    y: int
    cells: frozenset[tuple[int, int]]
    cost: int


def _candidate_positions(instance: ModuleInstance, base: BaseGeometry) -> list[_Candidate]:
    spec = instance.spec
    cx = (base.width - 1) / 2
    cy = (base.height - 1) / 2
    result: list[_Candidate] = []
    for y in range(base.height - spec.height + 1):
        for x in range(base.width - spec.width + 1):
            cells = frozenset(
                (xx, yy)
                for xx in range(x, x + spec.width)
                for yy in range(y, y + spec.height)
            )
            if not cells <= base.buildable_cells:
                continue
            px = x + (spec.width - 1) / 2
            py = y + spec.height - 1
            distance = abs(px - cx) + 0.35 * abs(py - cy)
            edge = min(x, base.width - (x + spec.width))
            visit_cost = int(100 * spec.visit_weight * distance)
            storage_bias = int(max(0, edge) * 20) if spec.visit_weight == 0 else 0
            result.append(_Candidate(x, y, cells, visit_cost + storage_bias))
    return result


def _connection_row(room: Placement) -> int:
    spec = MODULE_BY_KEY[room.module_key]
    if spec.connection_level is ConnectionLevel.TOP:
        return room.y
    return room.y + room.height - 1


def _directly_adjacent(a: Placement, a_side: int, b: Placement, b_side: int) -> bool:
    if _connection_row(a) != _connection_row(b):
        return False
    if a_side == 1 and b_side == 0:
        return a.x + a.width == b.x
    if a_side == 0 and b_side == 1:
        return b.x + b.width == a.x
    return False


def _room_port_components(
    rooms: list[Placement],
    base: BaseGeometry,
    occupied: set[tuple[int, int]],
) -> tuple[dict[int, set[int]], dict[int, set[tuple[int, int]]], int] | None:
    """Build connectivity components using left/right room access ports.

    Walk-through rooms connect their two ports internally. Terminal-only modules such as
    the Rapidium Ark do not, so they cannot become an accidental bridge between rooms.
    """

    port_count = len(rooms) * 2
    parent = list(range(port_count))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for idx, room in enumerate(rooms):
        if MODULE_BY_KEY[room.module_key].transit_allowed:
            union(2 * idx, 2 * idx + 1)

    for i, a in enumerate(rooms):
        for j in range(i + 1, len(rooms)):
            b = rooms[j]
            if _directly_adjacent(a, 1, b, 0):
                union(2 * i + 1, 2 * j)
            elif _directly_adjacent(a, 0, b, 1):
                union(2 * i, 2 * j + 1)

    module_components: dict[int, set[int]] = {}
    component_anchors: dict[int, set[tuple[int, int]]] = {}

    for idx, room in enumerate(rooms):
        components: set[int] = set()
        row = _connection_row(room)
        for side in (0, 1):
            port = 2 * idx + side
            root = find(port)
            components.add(root)

            x = room.x - 2 if side == 0 else room.x + room.width
            cells = {(x, row), (x + 1, row)}
            if (
                x >= 0
                and x + 1 < base.width
                and cells <= base.buildable_cells
                and not (cells & occupied)
            ):
                component_anchors.setdefault(root, set()).add((x, row))
        module_components[idx] = components

    airlock_idx = next(
        (idx for idx, room in enumerate(rooms) if room.module_key == "airlock"),
        None,
    )
    if airlock_idx is None:
        return None
    root_component = find(2 * airlock_idx)
    return module_components, component_anchors, root_component


def _neighbors(anchor: tuple[int, int], valid: set[tuple[int, int]]) -> list[tuple[int, int]]:
    x, y = anchor
    candidates = ((x - 2, y), (x + 2, y), (x, y - 1), (x, y + 1))
    return [p for p in candidates if p in valid]


def _shortest_path(
    starts: set[tuple[int, int]],
    goals: set[tuple[int, int]],
    valid: set[tuple[int, int]],
) -> list[tuple[int, int]] | None:
    if not starts or not goals:
        return None
    q = deque(starts)
    prev: dict[tuple[int, int], tuple[int, int] | None] = {s: None for s in starts}
    hit = None
    while q:
        cur = q.popleft()
        if cur in goals:
            hit = cur
            break
        for nxt in _neighbors(cur, valid):
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
    base: BaseGeometry, rooms: list[Placement]
) -> list[UtilityPlacement] | None:
    occupied: set[tuple[int, int]] = set().union(*(r.cells for r in rooms)) if rooms else set()
    valid_anchors: set[tuple[int, int]] = set()
    for y in range(base.height):
        for x in range(base.width - 1):
            cells = {(x, y), (x + 1, y)}
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
        network = set(used)
        for component in connected_components:
            network.update(component_anchors.get(component, set()))
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

        for component in candidate_components:
            starts = component_anchors.get(component, set())
            path = _shortest_path(starts, network, valid_anchors | used)
            if path is not None and (best_path is None or len(path) < len(best_path)):
                best_component = component
                best_path = path

        if best_component is None or best_path is None:
            return None

        used.update(best_path)
        for a, b in zip(best_path, best_path[1:], strict=False):
            if a[0] == b[0]:
                vertical.add(a)
                vertical.add(b)
        connected_components.add(best_component)

    return [
        UtilityPlacement("elevator" if anchor in vertical else "corridor", anchor[0], anchor[1])
        for anchor in sorted(used)
    ]


def _mass_metrics(
    base: BaseGeometry,
    rooms: list[Placement],
    utilities: list[UtilityPlacement],
) -> tuple[int, int, int, int, bool, dict[str, int]]:
    room_mass = sum(MODULE_BY_KEY[room.module_key].mass for room in rooms)
    utility_mass = UTILITY_MASS * len(utilities)
    total_mass = room_mass + utility_mass
    margin = base.organics_capacity - total_mass

    counts = Counter(room.module_key for room in rooms)
    mass_breakdown = {
        key: count * MODULE_BY_KEY[key].mass for key, count in sorted(counts.items())
    }
    corridor_count = sum(utility.kind == "corridor" for utility in utilities)
    elevator_count = sum(utility.kind == "elevator" for utility in utilities)
    if corridor_count:
        mass_breakdown["corridor"] = corridor_count * UTILITY_MASS
    if elevator_count:
        mass_breakdown["elevator"] = elevator_count * UTILITY_MASS

    return room_mass, utility_mass, total_mass, margin, margin >= 0, mass_breakdown


def solve_plan(request: PlanRequest, base: BaseGeometry | None = None) -> PlanResult:
    base = base or builtin_base(request.tier)
    instances = expand_instances(MODULES, request.room_counts)
    model = cp_model.CpModel()
    candidates: dict[str, list[_Candidate]] = {}
    vars_by_instance: dict[str, list[cp_model.IntVar]] = {}
    cell_vars: dict[tuple[int, int], list[cp_model.IntVar]] = {}

    objective_terms = []
    for inst in instances:
        cand = _candidate_positions(inst, base)
        if not cand:
            return PlanResult(
                status="INFEASIBLE",
                base=base,
                message=f"No legal position for {inst.spec.name}",
            )
        candidates[inst.instance_id] = cand
        variables = [
            model.new_bool_var(f"p_{inst.instance_id}_{idx}") for idx in range(len(cand))
        ]
        vars_by_instance[inst.instance_id] = variables
        model.add(sum(variables) == 1)
        for var, pos in zip(variables, cand, strict=True):
            for cell in pos.cells:
                cell_vars.setdefault(cell, []).append(var)
            objective_terms.append(pos.cost * var)

    for variables in cell_vars.values():
        model.add(sum(variables) <= 1)

    model.minimize(sum(objective_terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1.0, request.time_limit_s)
    solver.parameters.num_search_workers = 8

    best_result: PlanResult | None = None
    connected_candidates = 0

    for attempt in range(1, request.max_layout_attempts + 1):
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if best_result is not None:
                return best_result
            return PlanResult(
                status="INFEASIBLE",
                base=base,
                attempts=attempt,
                message="No feasible room packing found",
            )

        rooms: list[Placement] = []
        chosen_vars: list[cp_model.IntVar] = []
        for inst in instances:
            for idx, var in enumerate(vars_by_instance[inst.instance_id]):
                if solver.value(var):
                    pos = candidates[inst.instance_id][idx]
                    rooms.append(
                        Placement(
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

        utilities = _route_utilities(base, rooms)
        if utilities is not None:
            connected_candidates += 1
            room_mass, utility_mass, total_mass, margin, travel_ok, breakdown = _mass_metrics(
                base, rooms, utilities
            )
            message = (
                f"Connected layout found. Base mass {total_mass}; journey requires "
                f"{total_mass} Organics; tank capacity {base.organics_capacity}. "
                f"Travel at full tank: {'YES' if travel_ok else 'NO'}."
            )
            candidate_result = PlanResult(
                status="FEASIBLE",
                base=base,
                rooms=rooms,
                utilities=utilities,
                objective_value=solver.objective_value,
                attempts=attempt,
                message=message,
                room_mass=room_mass,
                utility_mass=utility_mass,
                total_mass=total_mass,
                organics_required_for_journey=total_mass,
                organics_capacity_margin=margin,
                travel_feasible_at_full_tank=travel_ok,
                mass_breakdown=breakdown,
            )
            if best_result is None or (
                candidate_result.total_mass,
                candidate_result.objective_value or 0,
            ) < (
                best_result.total_mass,
                best_result.objective_value or 0,
            ):
                best_result = candidate_result
            if utility_mass == 0:
                return candidate_result

        model.add(sum(chosen_vars) <= len(chosen_vars) - 1)

    if best_result is not None:
        best_result.message += (
            f" Best of {connected_candidates} connected layouts examined; automatic utility mass "
            "was minimized among those candidates."
        )
        return best_result

    return PlanResult(
        status="NO_CONNECTED_LAYOUT",
        base=base,
        attempts=request.max_layout_attempts,
        message=(
            "Room packings were feasible, but automatic corridor/elevator routing failed. "
            "Try a larger tier or fewer rooms."
        ),
    )
