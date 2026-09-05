from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .base import builtin_base
from .catalog import MODULE_BY_KEY, MODULES
from .models import (
    BaseGeometry,
    ModuleInstance,
    Placement,
    PlanRequest,
    PlanResult,
    UtilityPlacement,
    expand_instances,
)


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
            # Compactness + accessibility objective. Frequently visited rooms are
            # drawn towards the centre while storage/repulsors can live at edges.
            px = x + (spec.width - 1) / 2
            py = y + spec.height - 1
            distance = abs(px - cx) + 0.35 * abs(py - cy)
            edge = min(x, base.width - (x + spec.width))
            visit_cost = int(100 * spec.visit_weight * distance)
            storage_bias = int(max(0, edge) * 20) if spec.visit_weight == 0 else 0
            result.append(_Candidate(x, y, cells, visit_cost + storage_bias))
    return result


def _room_components(rooms: list[Placement]) -> list[list[int]]:
    parent = list(range(len(rooms)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, a in enumerate(rooms):
        for j in range(i + 1, len(rooms)):
            b = rooms[j]
            if a.connection_row != b.connection_row:
                continue
            same_row = a.connection_row
            if a.x + a.width == b.x or b.x + b.width == a.x:
                if a.y <= same_row < a.y + a.height and b.y <= same_row < b.y + b.height:
                    union(i, j)
    groups: dict[int, list[int]] = {}
    for i in range(len(rooms)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _component_terminals(
    component: list[int],
    rooms: list[Placement],
    base: BaseGeometry,
    occupied: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    terminals: set[tuple[int, int]] = set()
    for idx in component:
        room = rooms[idx]
        y = room.connection_row
        for x in (room.x - 2, room.x + room.width):
            cells = {(x, y), (x + 1, y)}
            if (
                x >= 0
                and x + 1 < base.width
                and cells <= base.buildable_cells
                and not (cells & occupied)
            ):
                terminals.add((x, y))
    return terminals


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

    components = _room_components(rooms)
    root_idx = next(
        (
            i
            for i, comp in enumerate(components)
            if any(rooms[j].module_key == "airlock" for j in comp)
        ),
        None,
    )
    if root_idx is None:
        return None

    root_terminals = _component_terminals(components[root_idx], rooms, base, occupied)
    network = set(root_terminals)
    if not network and len(components) > 1:
        return None
    used: set[tuple[int, int]] = set()
    vertical: set[tuple[int, int]] = set()

    remaining = [c for i, c in enumerate(components) if i != root_idx]
    while remaining:
        best = None
        best_path = None
        for comp in remaining:
            occupied_with_utilities = occupied | {
                cell
                for anchor in used
                for cell in ((anchor[0], anchor[1]), (anchor[0] + 1, anchor[1]))
            }
            terminals = _component_terminals(
                comp, rooms, base, occupied_with_utilities
            )
            path = _shortest_path(terminals, network or root_terminals, valid_anchors | used)
            if path is not None and (best_path is None or len(path) < len(best_path)):
                best, best_path = comp, path
        if best is None or best_path is None:
            return None
        for a, b in zip(best_path, best_path[1:], strict=False):
            used.add(a)
            used.add(b)
            if a[0] == b[0]:
                vertical.add(a)
                vertical.add(b)
        network.update(best_path)
        remaining.remove(best)

    return [
        UtilityPlacement("elevator" if anchor in vertical else "corridor", anchor[0], anchor[1])
        for anchor in sorted(used)
    ]


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
                "INFEASIBLE", base, message=f"No legal position for {inst.spec.name}"
            )
        candidates[inst.instance_id] = cand
        vv = [model.new_bool_var(f"p_{inst.instance_id}_{i}") for i in range(len(cand))]
        vars_by_instance[inst.instance_id] = vv
        model.add(sum(vv) == 1)
        for var, pos in zip(vv, cand, strict=True):
            for cell in pos.cells:
                cell_vars.setdefault(cell, []).append(var)
            objective_terms.append(pos.cost * var)

    for vv in cell_vars.values():
        model.add(sum(vv) <= 1)

    model.minimize(sum(objective_terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1.0, request.time_limit_s)
    solver.parameters.num_search_workers = 8

    for attempt in range(1, request.max_layout_attempts + 1):
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return PlanResult(
                "INFEASIBLE",
                base,
                attempts=attempt,
                message="No feasible room packing found",
            )

        rooms: list[Placement] = []
        chosen_vars = []
        for inst in instances:
            for i, var in enumerate(vars_by_instance[inst.instance_id]):
                if solver.value(var):
                    p = candidates[inst.instance_id][i]
                    rooms.append(
                        Placement(
                            inst.instance_id,
                            inst.spec.key,
                            p.x,
                            p.y,
                            inst.spec.width,
                            inst.spec.height,
                        )
                    )
                    chosen_vars.append(var)
                    break

        utilities = _route_utilities(base, rooms)
        if utilities is not None:
            total_mass = sum(MODULE_BY_KEY[r.module_key].mass for r in rooms) + 2 * len(
                utilities
            )
            msg = f"Connected layout found. Estimated total base mass: {total_mass}."
            return PlanResult(
                "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
                base,
                rooms,
                utilities,
                solver.objective_value,
                attempt,
                msg,
            )

        # Reject exactly this room arrangement and ask CP-SAT for another packing.
        model.add(sum(chosen_vars) <= len(chosen_vars) - 1)

    return PlanResult(
        "NO_CONNECTED_LAYOUT",
        base,
        attempts=request.max_layout_attempts,
        message=(
            "Room packings were feasible, but automatic corridor/elevator routing failed. "
            "Try a larger tier or fewer rooms."
        ),
    )
