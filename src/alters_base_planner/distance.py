from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from .catalog import MODULE_BY_KEY
from .models import ConnectionLevel, Placement, UtilityPlacement

Node = str
Coordinate = tuple[int, int]


@dataclass(frozen=True, slots=True)
class DistanceMetrics:
    weighted_score: float
    normalized_weighted_distance: float
    pairwise_distances: dict[str, int]
    pairwise_contributions: dict[str, float]
    elevator_module_count: int
    elevator_shaft_count: int
    corridor_count: int


def room_access_floor(room: Placement) -> int:
    """Return the legal vertical access row used for walking-distance calculations.

    Normal modules are entered at floor level, i.e. their bottom grid row.  This is
    crucial for multi-row rooms: the geometric top/centroid is not a walkable entry
    point.  A documented game exception may explicitly expose a different connection
    level (currently Radiation Repulsor uses TOP and is non-transit).
    """

    spec = MODULE_BY_KEY[room.module_key]
    if spec.connection_level is ConnectionLevel.TOP:
        return room.y
    return room.y + room.height - 1


def _connection_row(room: Placement) -> int:
    """Compatibility alias for the legal room access floor."""

    return room_access_floor(room)


def _room_port_coordinates(room: Placement) -> tuple[Coordinate, Coordinate]:
    """Coordinates of the left/right walkable ports on the legal access floor."""

    floor = room_access_floor(room)
    return (room.x, floor), (room.x + room.width, floor)


def _horizontal_module_lower_bound(dx: int) -> int:
    """Optimistic horizontal cost for a grid displacement.

    A Corridor occupies two horizontal grid cells but contributes one distance point,
    therefore two horizontal grid units can be covered for one objective-distance unit.
    """

    return (abs(dx) + 1) // 2


def modified_manhattan_room_lower_bound(a: Placement, b: Placement) -> int:
    """Admissible room-to-room lower bound using legal floor-level ports.

    Horizontal movement is scaled to the 2x1 Corridor convention.  For rooms on
    different floors, a continuous elevator trip needs one Elevator module on every
    traversed floor, so a vertical difference k has a minimum cost k + 1.  Obstacles,
    detours, shifted shafts and intermediate-room traversal can only increase the exact
    graph distance.
    """

    ports_a = _room_port_coordinates(a)
    ports_b = _room_port_coordinates(b)
    horizontal = min(
        _horizontal_module_lower_bound(ax - bx)
        for ax, _ in ports_a
        for bx, _ in ports_b
    )
    floor_delta = abs(room_access_floor(a) - room_access_floor(b))
    vertical = 0 if floor_delta == 0 else floor_delta + 1
    return horizontal + vertical


def _modified_manhattan_node_heuristic(position: Coordinate, targets: tuple[Coordinate, ...]) -> int:
    """Admissible A* heuristic on the module graph.

    It uses the same horizontal 2-cells-per-point scaling and real vertical floor rows.
    The extra first-Elevator cost is deliberately omitted at node level, keeping the
    heuristic admissible from arbitrary graph nodes; the exact graph edges account for
    every individual Elevator module (+1 each).
    """

    x, y = position
    return min(
        _horizontal_module_lower_bound(x - tx) + abs(y - ty) for tx, ty in targets
    )


def _validate_vertical_elevator_coverage(
    rooms: list[Placement], utilities: list[UtilityPlacement]
) -> None:
    """Enforce continuous elevator coverage over every used access floor in the base."""

    if not rooms:
        return

    used_levels = sorted({room_access_floor(room) for room in rooms})
    if len(used_levels) <= 1:
        return

    min_level = min(used_levels)
    max_level = max(used_levels)
    required_levels = list(range(min_level, max_level + 1))

    elevator_x_by_level: dict[int, set[int]] = {}
    for utility in utilities:
        if utility.kind == "elevator":
            elevator_x_by_level.setdefault(utility.y, set()).add(utility.x)

    elevator_count = sum(len(elevator_x_by_level.get(y, set())) for y in required_levels)
    if elevator_count < len(required_levels):
        raise ValueError(
            "Vertical hard constraint violated: a base spanning "
            f"{len(required_levels)} floors requires at least {len(required_levels)} "
            "Elevator modules across that floor span"
        )

    missing_levels = [y for y in required_levels if not elevator_x_by_level.get(y)]
    if missing_levels:
        raise ValueError(
            "Vertical hard constraint violated: no Elevator stop on floor(s) "
            + ", ".join(map(str, missing_levels))
        )

    for lower, upper in zip(required_levels, required_levels[1:], strict=False):
        shared_x = elevator_x_by_level[lower] & elevator_x_by_level[upper]
        if not shared_x:
            raise ValueError(
                "Vertical hard constraint violated: adjacent floors "
                f"{lower} and {upper} do not share an Elevator at the same x-coordinate"
            )


def _directly_adjacent(a: Placement, a_side: int, b: Placement, b_side: int) -> bool:
    if room_access_floor(a) != room_access_floor(b):
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
    """Connect adjacent modules using the cost of entering the destination utility."""

    _add_directed(graph, a, b, node_cost[b])
    _add_directed(graph, b, a, node_cost[a])


def _room_nodes(
    rooms: list[Placement],
) -> tuple[
    dict[Node, dict[Node, int]],
    dict[Node, int],
    dict[str, tuple[Node, ...]],
    dict[tuple[str, int], Node],
    dict[Node, Coordinate],
]:
    """Create floor-level left/right access nodes for every room.

    The start and destination rooms are free because shortest-path evaluation starts
    at either side of the source and accepts either side of the destination. A room
    used *between* those endpoints must be crossed from one side to the other, which
    costs its horizontal length in grid cells. Non-transit rooms have no internal
    left-right edge and therefore can never be used as bridges.
    """

    graph: dict[Node, dict[Node, int]] = {}
    node_cost: dict[Node, int] = {}
    endpoints: dict[str, tuple[Node, ...]] = {}
    side_nodes: dict[tuple[str, int], Node] = {}
    node_positions: dict[Node, Coordinate] = {}

    for room in rooms:
        spec = MODULE_BY_KEY[room.module_key]
        left = f"room:{room.instance_id}:left"
        right = f"room:{room.instance_id}:right"
        graph[left] = {}
        graph[right] = {}
        node_cost[left] = 0
        node_cost[right] = 0
        endpoints[room.instance_id] = (left, right)
        side_nodes[(room.instance_id, 0)] = left
        side_nodes[(room.instance_id, 1)] = right
        left_pos, right_pos = _room_port_coordinates(room)
        node_positions[left] = left_pos
        node_positions[right] = right_pos

        if spec.transit_allowed:
            _add_directed(graph, left, right, room.width)
            _add_directed(graph, right, left, room.width)

    return graph, node_cost, endpoints, side_nodes, node_positions


def _build_module_graph(
    rooms: list[Placement], utilities: list[UtilityPlacement]
) -> tuple[
    dict[Node, dict[Node, int]],
    dict[str, tuple[Node, ...]],
    dict[Node, Coordinate],
    int,
]:
    """Build the graph for the user-defined room-pair distance.

    Rules:
    - room ports are placed on their legal access floor, not geometric centroids/tops;
    - start and destination room lengths do not count;
    - directly adjacent start/destination rooms therefore have distance 0;
    - an intermediate transit room contributes its horizontal length in grid cells;
    - each Corridor module traversed contributes +1;
    - each individual Elevator module traversed contributes +1;
    - non-transit modules cannot be used as bridges.
    """

    graph, node_cost, endpoints, side_nodes, node_positions = _room_nodes(rooms)

    utility_nodes: dict[tuple[int, int], Node] = {}
    utility_kind: dict[Node, str] = {}
    for idx, utility in enumerate(utilities):
        node = f"utility:{idx}"
        graph[node] = {}
        node_cost[node] = 1
        utility_nodes[(utility.x, utility.y)] = node
        utility_kind[node] = utility.kind
        # Centerline coordinate makes either side of a 2x1 utility one grid unit away.
        node_positions[node] = (utility.x + 1, utility.y)

    for i, a in enumerate(rooms):
        for b in rooms[i + 1 :]:
            if _directly_adjacent(a, 1, b, 0):
                _add_directed(
                    graph,
                    side_nodes[(a.instance_id, 1)],
                    side_nodes[(b.instance_id, 0)],
                    0,
                )
                _add_directed(
                    graph,
                    side_nodes[(b.instance_id, 0)],
                    side_nodes[(a.instance_id, 1)],
                    0,
                )
            elif _directly_adjacent(a, 0, b, 1):
                _add_directed(
                    graph,
                    side_nodes[(a.instance_id, 0)],
                    side_nodes[(b.instance_id, 1)],
                    0,
                )
                _add_directed(
                    graph,
                    side_nodes[(b.instance_id, 1)],
                    side_nodes[(a.instance_id, 0)],
                    0,
                )

    for room in rooms:
        row = room_access_floor(room)
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

    for (x, y), node in utility_nodes.items():
        right = utility_nodes.get((x + 2, y))
        if right is not None:
            _connect_by_entry_cost(graph, node_cost, node, right)

    for (x, y), node in utility_nodes.items():
        if utility_kind[node] != "elevator":
            continue
        above = utility_nodes.get((x, y + 1))
        if above is not None and utility_kind[above] == "elevator":
            _connect_by_entry_cost(graph, node_cost, node, above)

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

    return graph, endpoints, node_positions, shaft_count


def _astar_distance(
    graph: dict[Node, dict[Node, int]],
    node_positions: dict[Node, Coordinate],
    sources: tuple[Node, ...],
    targets: tuple[Node, ...],
) -> int | float:
    """Exact shortest path accelerated with a floor-aware modified Manhattan heuristic."""

    target_set = set(targets)
    target_positions = tuple(node_positions[node] for node in targets if node in node_positions)
    if not target_positions:
        return math.inf

    distances: dict[Node, int] = {}
    heap: list[tuple[int, int, Node]] = []
    for node in sources:
        if node not in graph:
            continue
        distances[node] = 0
        heuristic = _modified_manhattan_node_heuristic(node_positions[node], target_positions)
        heapq.heappush(heap, (heuristic, 0, node))

    while heap:
        _, distance, node = heapq.heappop(heap)
        if distance != distances.get(node):
            continue
        if node in target_set:
            return distance
        for neighbour, edge_cost in graph[node].items():
            candidate = distance + edge_cost
            if candidate < distances.get(neighbour, math.inf):
                distances[neighbour] = candidate
                heuristic = _modified_manhattan_node_heuristic(
                    node_positions[neighbour], target_positions
                )
                heapq.heappush(heap, (candidate + heuristic, candidate, neighbour))
    return math.inf


def evaluate_distances(
    rooms: list[Placement], utilities: list[UtilityPlacement]
) -> DistanceMetrics:
    _validate_vertical_elevator_coverage(rooms, utilities)
    graph, endpoints, node_positions, shaft_count = _build_module_graph(rooms, utilities)

    active_rooms = [room for room in rooms if MODULE_BY_KEY[room.module_key].visit_weight > 0]

    pairwise: dict[str, int] = {}
    contributions: dict[str, float] = {}
    weighted_sum = 0.0
    pair_weight_sum = 0.0

    for idx, room_a in enumerate(active_rooms):
        weight_a = MODULE_BY_KEY[room_a.module_key].visit_weight
        for room_b in active_rooms[idx + 1 :]:
            best = _astar_distance(
                graph,
                node_positions,
                endpoints[room_a.instance_id],
                endpoints[room_b.instance_id],
            )
            if math.isinf(best):
                raise ValueError(
                    f"No walkable path between {room_a.instance_id} and {room_b.instance_id}"
                )

            distance = int(best)
            manhattan_lb = modified_manhattan_room_lower_bound(room_a, room_b)
            if distance < manhattan_lb:
                raise AssertionError(
                    "Exact path distance fell below the floor-aware modified Manhattan lower "
                    f"bound for {room_a.instance_id}|{room_b.instance_id}: "
                    f"exact={distance}, lower_bound={manhattan_lb}"
                )

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
