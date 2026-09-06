from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from .catalog import MODULE_BY_KEY
from .models import Placement, PortSide, ResolvedPort, UtilityPlacement, resolve_ports

Node = str


@dataclass(frozen=True, slots=True)
class DistanceMetrics:
    weighted_score: float
    normalized_weighted_distance: float
    weighted_manhattan_lower_bound: float
    pairwise_distances: dict[str, int]
    pairwise_contributions: dict[str, float]
    pairwise_manhattan_lower_bounds: dict[str, int]
    elevator_module_count: int
    elevator_shaft_count: int
    corridor_count: int


def room_ports(room: Placement) -> tuple[ResolvedPort, ...]:
    return resolve_ports(room, MODULE_BY_KEY[room.module_key])


def room_access_rows(room: Placement) -> frozenset[int]:
    """All legal walkable entry rows exposed by a room's explicit ports."""

    return frozenset(port.edge_y for port in room_ports(room))


def _ports_directly_meet(a: ResolvedPort, b: ResolvedPort) -> bool:
    return (
        a.edge_y == b.edge_y
        and a.edge_x == b.edge_x
        and a.side is not b.side
    )


def _horizontal_module_lower_bound(dx: int) -> int:
    """Optimistic horizontal cost using the 2x1 Corridor convention."""

    return (abs(dx) + 1) // 2


def modified_manhattan_room_lower_bound(a: Placement, b: Placement) -> int:
    """Admissible port-to-port lower bound for the game's movement model.

    Endpoints are explicit room ports rather than centroids. Normal multi-row rooms expose
    those ports on their floor, so a route can never enter a room through its ceiling.

    On one floor, two horizontal grid cells can be bridged by one Corridor module (+1).
    Across floors, the comparison uses the 2x1 utility anchors outside each selected port;
    a vertical difference of k rows needs at least k+1 Elevator modules because both the
    departure and arrival floors require Elevator modules. A single shaft can therefore
    absorb the two-cell width between a room boundary and the opposite room boundary
    without incorrectly adding an extra horizontal point.
    """

    best = math.inf
    for port_a in room_ports(a):
        for port_b in room_ports(b):
            if _ports_directly_meet(port_a, port_b):
                candidate = 0
            elif port_a.edge_y == port_b.edge_y:
                candidate = _horizontal_module_lower_bound(port_a.edge_x - port_b.edge_x)
            else:
                anchor_a = port_a.utility_anchor
                anchor_b = port_b.utility_anchor
                horizontal = _horizontal_module_lower_bound(anchor_a[0] - anchor_b[0])
                vertical = abs(port_a.edge_y - port_b.edge_y) + 1
                candidate = horizontal + vertical
            best = min(best, candidate)
    return int(best)


def weighted_modified_manhattan_lower_bound(rooms: list[Placement]) -> float:
    active = [room for room in rooms if MODULE_BY_KEY[room.module_key].visit_weight > 0]
    total = 0.0
    for idx, room_a in enumerate(active):
        weight_a = MODULE_BY_KEY[room_a.module_key].visit_weight
        for room_b in active[idx + 1 :]:
            weight_b = MODULE_BY_KEY[room_b.module_key].visit_weight
            total += weight_a * weight_b * modified_manhattan_room_lower_bound(room_a, room_b)
    return total


def _validate_vertical_elevator_coverage(
    rooms: list[Placement], utilities: list[UtilityPlacement]
) -> None:
    """Enforce continuous Elevator coverage over every used room-port floor."""

    if not rooms:
        return

    used_levels = sorted({row for room in rooms for row in room_access_rows(room)})
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
        if not (elevator_x_by_level[lower] & elevator_x_by_level[upper]):
            raise ValueError(
                "Vertical hard constraint violated: adjacent floors "
                f"{lower} and {upper} do not share an Elevator at the same x-coordinate"
            )


def _add_directed(graph: dict[Node, dict[Node, int]], a: Node, b: Node, cost: int) -> None:
    graph.setdefault(a, {})[b] = min(cost, graph.get(a, {}).get(b, cost))


def _connect_by_entry_cost(
    graph: dict[Node, dict[Node, int]],
    node_cost: dict[Node, int],
    a: Node,
    b: Node,
) -> None:
    _add_directed(graph, a, b, node_cost[b])
    _add_directed(graph, b, a, node_cost[a])


def _room_nodes(
    rooms: list[Placement],
) -> tuple[
    dict[Node, dict[Node, int]],
    dict[Node, int],
    dict[str, tuple[Node, ...]],
    dict[tuple[str, str], Node],
    dict[tuple[str, str], ResolvedPort],
]:
    """Create one graph node for every explicit logical room port."""

    graph: dict[Node, dict[Node, int]] = {}
    node_cost: dict[Node, int] = {}
    endpoints: dict[str, tuple[Node, ...]] = {}
    port_nodes: dict[tuple[str, str], Node] = {}
    resolved: dict[tuple[str, str], ResolvedPort] = {}

    for room in rooms:
        spec = MODULE_BY_KEY[room.module_key]
        nodes: list[Node] = []
        ports = room_ports(room)
        for port in ports:
            node = f"room:{room.instance_id}:port:{port.name}"
            graph[node] = {}
            node_cost[node] = 0
            nodes.append(node)
            port_nodes[(room.instance_id, port.name)] = node
            resolved[(room.instance_id, port.name)] = port
        endpoints[room.instance_id] = tuple(nodes)

        if spec.transit_allowed:
            left = [p for p in ports if p.side is PortSide.LEFT]
            right = [p for p in ports if p.side is PortSide.RIGHT]
            for port_left in left:
                for port_right in right:
                    left_node = port_nodes[(room.instance_id, port_left.name)]
                    right_node = port_nodes[(room.instance_id, port_right.name)]
                    # Crossing a transit room from one extreme side to the other costs
                    # its full grid width. A 1x1 room therefore correctly costs 1 even
                    # though its LEFT/RIGHT logical ports occupy the same physical cell.
                    _add_directed(graph, left_node, right_node, room.width)
                    _add_directed(graph, right_node, left_node, room.width)

    return graph, node_cost, endpoints, port_nodes, resolved


def _build_module_graph(
    rooms: list[Placement], utilities: list[UtilityPlacement]
) -> tuple[dict[Node, dict[Node, int]], dict[str, tuple[Node, ...]], int]:
    graph, node_cost, endpoints, port_nodes, resolved = _room_nodes(rooms)

    utility_nodes: dict[tuple[int, int], Node] = {}
    utility_kind: dict[Node, str] = {}
    for idx, utility in enumerate(utilities):
        node = f"utility:{idx}"
        graph[node] = {}
        node_cost[node] = 1
        utility_nodes[(utility.x, utility.y)] = node
        utility_kind[node] = utility.kind

    # Direct room-to-room connections exist only where explicit opposite-side ports meet.
    for i, room_a in enumerate(rooms):
        for room_b in rooms[i + 1 :]:
            for port_a in room_ports(room_a):
                for port_b in room_ports(room_b):
                    if not _ports_directly_meet(port_a, port_b):
                        continue
                    node_a = port_nodes[(room_a.instance_id, port_a.name)]
                    node_b = port_nodes[(room_b.instance_id, port_b.name)]
                    _add_directed(graph, node_a, node_b, 0)
                    _add_directed(graph, node_b, node_a, 0)

    # Every explicit port may connect only to the 2x1 utility anchor directly outside it.
    for room in rooms:
        for port in room_ports(room):
            utility_node = utility_nodes.get(port.utility_anchor)
            if utility_node is None:
                continue
            room_node = port_nodes[(room.instance_id, port.name)]
            _connect_by_entry_cost(graph, node_cost, room_node, utility_node)

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
    _validate_vertical_elevator_coverage(rooms, utilities)
    graph, endpoints, shaft_count = _build_module_graph(rooms, utilities)

    active_rooms = [room for room in rooms if MODULE_BY_KEY[room.module_key].visit_weight > 0]
    pairwise: dict[str, int] = {}
    contributions: dict[str, float] = {}
    manhattan_bounds: dict[str, int] = {}
    weighted_sum = 0.0
    weighted_manhattan = 0.0
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
            lower_bound = modified_manhattan_room_lower_bound(room_a, room_b)
            if distance < lower_bound:
                raise AssertionError(
                    "Exact path distance fell below the explicit-port Manhattan lower bound "
                    f"for {room_a.instance_id}|{room_b.instance_id}: "
                    f"exact={distance}, lower_bound={lower_bound}"
                )

            pair_key = f"{room_a.instance_id}|{room_b.instance_id}"
            pair_weight = weight_a * MODULE_BY_KEY[room_b.module_key].visit_weight
            contribution = pair_weight * distance

            pairwise[pair_key] = distance
            contributions[pair_key] = contribution
            manhattan_bounds[pair_key] = lower_bound
            weighted_sum += contribution
            weighted_manhattan += pair_weight * lower_bound
            pair_weight_sum += pair_weight

    normalized = weighted_sum / pair_weight_sum if pair_weight_sum else 0.0
    return DistanceMetrics(
        weighted_score=weighted_sum,
        normalized_weighted_distance=normalized,
        weighted_manhattan_lower_bound=weighted_manhattan,
        pairwise_distances=pairwise,
        pairwise_contributions=contributions,
        pairwise_manhattan_lower_bounds=manhattan_bounds,
        elevator_module_count=sum(u.kind == "elevator" for u in utilities),
        elevator_shaft_count=shaft_count,
        corridor_count=sum(u.kind == "corridor" for u in utilities),
    )
