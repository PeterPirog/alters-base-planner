from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from .catalog import MODULE_BY_KEY
from .models import ConnectionLevel, Placement, UtilityPlacement

Node = str


@dataclass(frozen=True, slots=True)
class DistanceMetrics:
    weighted_score: float
    normalized_weighted_distance: float
    pairwise_distances: dict[str, int]
    pairwise_contributions: dict[str, float]
    elevator_module_count: int
    elevator_shaft_count: int
    corridor_count: int


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


def _add_directed(graph: dict[Node, dict[Node, int]], a: Node, b: Node, cost: int) -> None:
    graph.setdefault(a, {})[b] = min(cost, graph.get(a, {}).get(b, cost))


def _connect_by_entry_cost(
    graph: dict[Node, dict[Node, int]],
    node_cost: dict[Node, int],
    a: Node,
    b: Node,
) -> None:
    """Connect two adjacent modules.

    Distance is defined by modules traversed between rooms:
    - entering a room costs 0,
    - entering one Corridor costs 1,
    - entering one Elevator module costs 1.
    """

    _add_directed(graph, a, b, node_cost[b])
    _add_directed(graph, b, a, node_cost[a])


def _room_nodes(
    rooms: list[Placement],
) -> tuple[
    dict[Node, dict[Node, int]],
    dict[Node, int],
    dict[str, tuple[Node, ...]],
    dict[tuple[str, int], Node],
]:
    graph: dict[Node, dict[Node, int]] = {}
    node_cost: dict[Node, int] = {}
    endpoints: dict[str, tuple[Node, ...]] = {}
    side_nodes: dict[tuple[str, int], Node] = {}

    for room in rooms:
        spec = MODULE_BY_KEY[room.module_key]
        if spec.transit_allowed:
            node = f"room:{room.instance_id}"
            graph[node] = {}
            node_cost[node] = 0
            endpoints[room.instance_id] = (node,)
            side_nodes[(room.instance_id, 0)] = node
            side_nodes[(room.instance_id, 1)] = node
        else:
            left = f"room:{room.instance_id}:left"
            right = f"room:{room.instance_id}:right"
            graph[left] = {}
            graph[right] = {}
            node_cost[left] = 0
            node_cost[right] = 0
            endpoints[room.instance_id] = (left, right)
            side_nodes[(room.instance_id, 0)] = left
            side_nodes[(room.instance_id, 1)] = right

    return graph, node_cost, endpoints, side_nodes


def _build_module_graph(
    rooms: list[Placement], utilities: list[UtilityPlacement]
) -> tuple[dict[Node, dict[Node, int]], dict[str, tuple[Node, ...]], int]:
    """Build the exact graph used by the user-defined distance objective.

    Room length has zero cost. Directly adjacent rooms therefore have distance 0.
    Every Corridor module traversed contributes +1. Every Elevator module traversed
    contributes +1, including each separate Elevator in a multi-floor shaft.
    """

    graph, node_cost, endpoints, side_nodes = _room_nodes(rooms)

    utility_nodes: dict[tuple[int, int], Node] = {}
    utility_kind: dict[Node, str] = {}
    for idx, utility in enumerate(utilities):
        node = f"utility:{idx}"
        graph[node] = {}
        node_cost[node] = 1
        utility_nodes[(utility.x, utility.y)] = node
        utility_kind[node] = utility.kind

    # Direct legal room-to-room adjacency is free: d = 0.
    for i, a in enumerate(rooms):
        for b in rooms[i + 1 :]:
            if _directly_adjacent(a, 1, b, 0):
                _connect_by_entry_cost(
                    graph,
                    node_cost,
                    side_nodes[(a.instance_id, 1)],
                    side_nodes[(b.instance_id, 0)],
                )
            elif _directly_adjacent(a, 0, b, 1):
                _connect_by_entry_cost(
                    graph,
                    node_cost,
                    side_nodes[(a.instance_id, 0)],
                    side_nodes[(b.instance_id, 1)],
                )

    # A room connects to a utility only when the 2x1 utility occupies the exact
    # legal anchor immediately to the left/right of the room access level.
    for room in rooms:
        row = _connection_row(room)
        anchors = {
            0: (room.x - 2, row),
            1: (room.x + room.width, row),
        }
        for side, anchor in anchors.items():
            utility_node = utility_nodes.get(anchor)
            if utility_node is not None:
                _connect_by_entry_cost(
                    graph,
                    node_cost,
                    side_nodes[(room.instance_id, side)],
                    utility_node,
                )

    # Horizontal utility adjacency. A Corridor or Elevator is one distance unit,
    # regardless of its 2-cell footprint.
    for (x, y), node in utility_nodes.items():
        right = utility_nodes.get((x + 2, y))
        if right is not None:
            _connect_by_entry_cost(graph, node_cost, node, right)

    # Vertical adjacency exists only between immediately stacked Elevator modules.
    # Each Elevator module is a separate +1 in the path length.
    for (x, y), node in utility_nodes.items():
        if utility_kind[node] != "elevator":
            continue
        above = utility_nodes.get((x, y + 1))
        if above is not None and utility_kind[above] == "elevator":
            _connect_by_entry_cost(graph, node_cost, node, above)

    # Report contiguous elevator shafts separately from Elevator module count.
    shaft_count = 0
    by_x: dict[int, list[int]] = {}
    for utility in utilities:
        if utility.kind == "elevator":
            by_x.setdefault(utility.x, []).append(utility.y)
    for ys in by_x.values():
        previous: int | None = None
        for y in sorted(set(ys)):
            if previous is None or y != previous + 1:
                shaft_count += 1
            previous = y

    return graph, endpoints, shaft_count


def _dijkstra(
    graph: dict[Node, dict[Node, int]], sources: tuple[Node, ...]
) -> dict[Node, int]:
    distances: dict[Node, int] = {}
    heap: list[tuple[int, Node]] = []
    for node in sources:
        if node not in graph:
            continue
        distances[node] = 0
        heapq.heappush(heap, (0, node))

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
    graph, endpoints, shaft_count = _build_module_graph(rooms, utilities)

    # Objective pairs contain only rooms with positive usage weight. Storage and
    # other passive modules with weight 0 still remain hard-constrained physical
    # modules and may participate in the walkable topology if transit is legal.
    active_rooms = [room for room in rooms if MODULE_BY_KEY[room.module_key].visit_weight > 0]

    pairwise: dict[str, int] = {}
    contributions: dict[str, float] = {}
    weighted_sum = 0.0
    pair_weight_sum = 0.0

    for idx, room_a in enumerate(active_rooms):
        distances = _dijkstra(graph, endpoints[room_a.instance_id])
        weight_a = MODULE_BY_KEY[room_a.module_key].visit_weight
        for room_b in active_rooms[idx + 1 :]:
            best = min(
                (distances[node] for node in endpoints[room_b.instance_id] if node in distances),
                default=math.inf,
            )
            if math.isinf(best):
                raise ValueError(
                    f"No walkable path between {room_a.instance_id} and {room_b.instance_id}"
                )

            distance = int(best)
            pair_key = f"{room_a.instance_id}|{room_b.instance_id}"
            pair_weight = weight_a * MODULE_BY_KEY[room_b.module_key].visit_weight
            contribution = pair_weight * distance

            pairwise[pair_key] = distance
            contributions[pair_key] = contribution
            weighted_sum += contribution
            pair_weight_sum += pair_weight

    normalized = weighted_sum / pair_weight_sum if pair_weight_sum else 0.0
    return DistanceMetrics(
        weighted_score=weighted_sum,
        normalized_weighted_distance=normalized,
        pairwise_distances=pairwise,
        pairwise_contributions=contributions,
        elevator_module_count=sum(u.kind == "elevator" for u in utilities),
        elevator_shaft_count=shaft_count,
        corridor_count=sum(u.kind == "corridor" for u in utilities),
    )
