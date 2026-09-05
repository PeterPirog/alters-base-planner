from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from .catalog import MODULE_BY_KEY
from .engine import _connection_row
from .models import Placement, UtilityPlacement

Cell = tuple[int, int]


@dataclass(frozen=True, slots=True)
class DistanceMetrics:
    weighted_score: float
    normalized_weighted_distance: float
    pairwise_distances: dict[str, int]
    elevator_module_count: int
    elevator_shaft_count: int
    corridor_count: int


def _add_edge(graph: dict[Cell, dict[Cell, int]], a: Cell, b: Cell, cost: int) -> None:
    graph.setdefault(a, {})[b] = min(cost, graph.get(a, {}).get(b, cost))
    graph.setdefault(b, {})[a] = min(cost, graph.get(b, {}).get(a, cost))


def _middle_offsets(width: int) -> tuple[int, ...]:
    if width % 2:
        return (width // 2,)
    return (width // 2 - 1, width // 2)


def _room_activity_sources(room: Placement) -> list[tuple[Cell, int]]:
    """Return graph-entry cells and costs for the room's abstract activity point.

    Transit rooms use their central walkable cell(s). Terminal rooms expose their
    left/right boundary cells with the horizontal cost from the centre to that side,
    but the two sides are not connected through the room and therefore cannot be
    used as a shortcut.
    """

    spec = MODULE_BY_KEY[room.module_key]
    row = _connection_row(room)
    centres = _middle_offsets(room.width)
    if spec.transit_allowed:
        return [((room.x + offset, row), 0) for offset in centres]

    left_cost = min(abs(offset) for offset in centres)
    right_offset = room.width - 1
    right_cost = min(abs(right_offset - offset) for offset in centres)
    if room.width == 1:
        return [((room.x, row), 0)]
    return [
        ((room.x, row), left_cost),
        ((room.x + room.width - 1, row), right_cost),
    ]


def _build_walk_graph(
    rooms: list[Placement], utilities: list[UtilityPlacement]
) -> tuple[dict[Cell, dict[Cell, int]], int]:
    graph: dict[Cell, dict[Cell, int]] = {}
    owner: dict[Cell, tuple[str, str, bool]] = {}

    for room in rooms:
        spec = MODULE_BY_KEY[room.module_key]
        row = _connection_row(room)
        if spec.transit_allowed:
            cells = [(x, row) for x in range(room.x, room.x + room.width)]
        elif room.width == 1:
            cells = [(room.x, row)]
        else:
            cells = [(room.x, row), (room.x + room.width - 1, row)]
        for cell in cells:
            graph.setdefault(cell, {})
            owner[cell] = ("room", room.instance_id, spec.transit_allowed)

    elevator_anchors: set[Cell] = set()
    for idx, utility in enumerate(utilities):
        utility_id = f"{utility.kind}-{idx}"
        for cell in utility.cells:
            graph.setdefault(cell, {})
            owner[cell] = ("utility", utility_id, True)
        if utility.kind == "elevator":
            elevator_anchors.add((utility.x, utility.y))

    # Horizontal cell movement always costs one point. The only internal edge
    # suppressed is the left-to-right bridge inside a terminal-only module.
    for x, y in list(graph):
        neighbour = (x + 1, y)
        if neighbour not in graph:
            continue
        a_owner = owner[(x, y)]
        b_owner = owner[neighbour]
        same_terminal_room = (
            a_owner[0] == "room"
            and b_owner[0] == "room"
            and a_owner[1] == b_owner[1]
            and not a_owner[2]
        )
        if not same_terminal_room:
            _add_edge(graph, (x, y), neighbour, 1)

    # A shaft is a contiguous run of Elevator modules at the same x anchor.
    # Any ride between two served floors in that same run costs exactly 1,
    # irrespective of the number of floors crossed.
    shaft_count = 0
    by_x: dict[int, list[int]] = {}
    for x, y in elevator_anchors:
        by_x.setdefault(x, []).append(y)

    for x, ys in by_x.items():
        ys = sorted(set(ys))
        run: list[int] = []
        runs: list[list[int]] = []
        for y in ys:
            if not run or y == run[-1] + 1:
                run.append(y)
            else:
                runs.append(run)
                run = [y]
        if run:
            runs.append(run)

        shaft_count += len(runs)
        for floors in runs:
            for idx, y1 in enumerate(floors):
                for y2 in floors[idx + 1 :]:
                    _add_edge(graph, (x, y1), (x, y2), 1)
                    _add_edge(graph, (x + 1, y1), (x + 1, y2), 1)

    return graph, shaft_count


def _dijkstra(
    graph: dict[Cell, dict[Cell, int]], sources: list[tuple[Cell, int]]
) -> dict[Cell, int]:
    distances: dict[Cell, int] = {}
    heap: list[tuple[int, Cell]] = []
    for node, initial_cost in sources:
        if node not in graph:
            continue
        if initial_cost < distances.get(node, math.inf):
            distances[node] = initial_cost
            heapq.heappush(heap, (initial_cost, node))

    while heap:
        distance, node = heapq.heappop(heap)
        if distance != distances.get(node):
            continue
        for neighbour, edge_cost in graph[node].items():
            candidate = distance + edge_cost
            if candidate < distances.get(neighbour, math.inf):
                distances[neighbour] = candidate
                heapq.heappush(heap, (candidate, neighbour))
    return distances


def evaluate_distances(
    rooms: list[Placement], utilities: list[UtilityPlacement]
) -> DistanceMetrics:
    graph, shaft_count = _build_walk_graph(rooms, utilities)
    sources_by_room = {room.instance_id: _room_activity_sources(room) for room in rooms}
    pairwise: dict[str, int] = {}
    weighted_sum = 0.0
    pair_weight_sum = 0.0

    for idx, room_a in enumerate(rooms):
        distances = _dijkstra(graph, sources_by_room[room_a.instance_id])
        weight_a = MODULE_BY_KEY[room_a.module_key].visit_weight
        for room_b in rooms[idx + 1 :]:
            best = math.inf
            for node, terminal_cost in sources_by_room[room_b.instance_id]:
                if node in distances:
                    best = min(best, distances[node] + terminal_cost)
            if math.isinf(best):
                raise ValueError(
                    f"No walkable path between {room_a.instance_id} and {room_b.instance_id}"
                )
            distance = int(best)
            pairwise[f"{room_a.instance_id}|{room_b.instance_id}"] = distance
            pair_weight = weight_a * MODULE_BY_KEY[room_b.module_key].visit_weight
            weighted_sum += pair_weight * distance
            pair_weight_sum += pair_weight

    normalized = weighted_sum / pair_weight_sum if pair_weight_sum else 0.0
    return DistanceMetrics(
        weighted_score=weighted_sum,
        normalized_weighted_distance=normalized,
        pairwise_distances=pairwise,
        elevator_module_count=sum(u.kind == "elevator" for u in utilities),
        elevator_shaft_count=shaft_count,
        corridor_count=sum(u.kind == "corridor" for u in utilities),
    )
