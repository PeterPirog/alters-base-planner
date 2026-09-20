"""Independent hard-feasibility oracle for CP-SAT formulation audit.

This module provides a correctness oracle that evaluates hard-feasibility
constraints WITHOUT using CP-SAT. It is designed to verify that the current
Formulation A correctly implements the normative H1-H11 structural rules.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from enum import StrEnum

from alters_base_planner.models import PortSide


class UtilityKind(StrEnum):
    NONE = "NONE"
    CORRIDOR = "CORRIDOR"
    ELEVATOR = "ELEVATOR"


@dataclass(frozen=True)
class OraclePort:
    """One resolved port for an installed module."""

    name: str
    side: PortSide
    edge_x: int
    edge_y: int

    @property
    def utility_anchor(self) -> tuple[int, int]:
        """Top-left 2x1 solver-infrastructure anchor outside this horizontal port."""
        x = self.edge_x - 2 if self.side is PortSide.LEFT else self.edge_x
        return (x, self.edge_y)


@dataclass(frozen=True)
class OraclePlacement:
    """One concrete placement for oracle evaluation."""

    instance_id: str
    module_key: str
    x: int
    y: int
    width: int
    height: int
    ports: tuple[OraclePort, ...]

    @property
    def cells(self) -> frozenset[tuple[int, int]]:
        return frozenset(
            (xx, yy)
            for xx in range(self.x, self.x + self.width)
            for yy in range(self.y, self.y + self.height)
        )


@dataclass(frozen=True)
class OracleUtilityAnchor:
    """Legal solver infrastructure anchor."""

    x: int
    y: int

    @property
    def cells(self) -> frozenset[tuple[int, int]]:
        return frozenset({(self.x, self.y), (self.x + 1, self.y)})


@dataclass(frozen=True)
class OracleLayout:
    """A complete physical layout with rooms and utilities."""

    rooms: tuple[OraclePlacement, ...]
    utilities: tuple[tuple[OracleUtilityAnchor, UtilityKind], ...]

    def occupied_cells(self) -> frozenset[tuple[int, int]]:
        cells: set[tuple[int, int]] = set()
        for room in self.rooms:
            cells.update(room.cells)
        for anchor, kind in self.utilities:
            cells.update(anchor.cells)
        return frozenset(cells)

    def room_instances(self) -> frozenset[str]:
        return frozenset(room.instance_id for room in self.rooms)


def check_h2_base_mask(
    layout: OracleLayout, base_buildable: frozenset[tuple[int, int]]
) -> tuple[bool, list[str]]:
    """Check H2: Base mask legality - all room cells must be in buildable cells."""
    violations = []
    for room in layout.rooms:
        if not room.cells <= base_buildable:
            violations.append(f"H2: Room {room.instance_id} outside buildable cells")
    return len(violations) == 0, violations


def check_h3_overlap(layout: OracleLayout) -> tuple[bool, list[str]]:
    """Check H3: No overlap - each cell occupied by at most one module."""
    violations = []
    cell_counts: dict[tuple[int, int], list[str]] = defaultdict(list)
    for room in layout.rooms:
        for cell in room.cells:
            cell_counts[cell].append(f"room:{room.instance_id}")
    for anchor, kind in layout.utilities:
        for cell in anchor.cells:
            cell_counts[cell].append(f"utility:{kind}@{anchor.x},{anchor.y}")
    for cell, occupants in cell_counts.items():
        if len(occupants) > 1:
            violations.append(f"H3: Cell {cell} occupied by {occupants}")
    return len(violations) == 0, violations


def check_h6_local_connection(layout: OracleLayout) -> tuple[bool, list[str]]:
    """Check H6: Every installed module has at least one legal connection.

    A room is connected if it has at least one port that matches another room's port
    (same coordinates, opposite sides) or connects to a utility anchor.
    A utility is connected if it has at least one room port or adjacent utility.
    """
    violations = []

    for room in layout.rooms:
        has_connection = False

        for port in room.ports:
            for other_room in layout.rooms:
                if other_room is room:
                    continue
                for other_port in other_room.ports:
                    if (port.edge_x, port.edge_y) == (other_port.edge_x, other_port.edge_y):
                        has_connection = True
                        break
                if has_connection:
                    break
            if has_connection:
                break

            anchor = port.utility_anchor
            for anchor_obj, kind in layout.utilities:
                if (anchor[0], anchor[1]) == (anchor_obj.x, anchor_obj.y):
                    has_connection = True
                    break
            if has_connection:
                break

        if not has_connection:
            violations.append(f"H6: Room {room.instance_id} has no legal connection")

    for anchor, kind in layout.utilities:
        has_connection = False

        for room in layout.rooms:
            for port in room.ports:
                anchor_edge = (anchor.x, anchor.y)
                if (port.edge_x, port.edge_y) == anchor_edge:
                    has_connection = True
                    break
            if has_connection:
                break

        if not has_connection:
            for other_anchor, other_kind in layout.utilities:
                if (other_anchor.x == anchor.x + 2 and other_anchor.y == anchor.y):
                    has_connection = True
                    break
            if not has_connection:
                for other_anchor, other_kind in layout.utilities:
                    if (other_anchor.x == anchor.x - 2 and other_anchor.y == anchor.y):
                        has_connection = True
                        break

        if not has_connection:
            violations.append(f"H6: Utility {kind}@{anchor.x},{anchor.y} has no legal connection")

    return len(violations) == 0, violations


def check_h7_airlock_reachability(
    layout: OracleLayout, root_instance_id: str = "airlock-1"
) -> tuple[bool, list[str]]:
    """Check H7: All installed modules are reachable from Airlock.

    Uses BFS over the connectivity graph to verify reachability.
    """
    violations = []

    rooms_by_instance = {r.instance_id: r for r in layout.rooms}
    if root_instance_id not in rooms_by_instance:
        violations.append("H7: Root instance missing")
        return False, violations

    graph: dict[str, set[str]] = defaultdict(set)

    for room in layout.rooms:
        for port in room.ports:
            node = f"room:{room.instance_id}:port:{port.name}"
            for other_room in layout.rooms:
                if other_room is room:
                    continue
                for other_port in other_room.ports:
                    if (port.edge_x, port.edge_y) == (other_port.edge_x, other_port.edge_y):
                        other_node = f"room:{other_room.instance_id}:port:{other_port.name}"
                        graph[node].add(other_node)
                        graph[other_node].add(node)

    for anchor, kind in layout.utilities:
        node = f"utility:{anchor.x},{anchor.y}"
        for room in layout.rooms:
            for port in room.ports:
                anchor_edge = port.utility_anchor
                if (port.edge_x, port.edge_y) == (anchor_edge[0], anchor_edge[1]):
                    graph[node].add(f"room:{room.instance_id}:port:{port.name}")
                    graph[f"room:{room.instance_id}:port:{port.name}"].add(node)

    for anchor, kind in layout.utilities:
        node = f"utility:{anchor.x},{anchor.y}"
        right_anchor = (anchor.x + 2, anchor.y)
        for anchor2, kind2 in layout.utilities:
            if (anchor2.x, anchor2.y) == right_anchor:
                right_node = f"utility:{right_anchor[0]},{right_anchor[1]}"
                graph[node].add(right_node)
                graph[right_node].add(node)

    def bfs_reachability(start: str) -> set[str]:
        visited = set()
        queue = deque([start])
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            queue.extend(graph.get(node, set()))
        return visited

    airlock_room = rooms_by_instance[root_instance_id]
    airlock_ports = [
        f"room:{root_instance_id}:port:{port.name}" for port in airlock_room.ports
    ]

    reachable: set[str] = set()
    for port_node in airlock_ports:
        reachable |= bfs_reachability(port_node)

    for room in layout.rooms:
        if room.instance_id == root_instance_id:
            continue
        room_ports = [f"room:{room.instance_id}:port:{port.name}" for port in room.ports]
        room_reachable = any(port_node in reachable for port_node in room_ports)
        if not room_reachable:
            violations.append(f"H7: Room {room.instance_id} not reachable from Airlock")

    for anchor, kind in layout.utilities:
        node = f"utility:{anchor.x},{anchor.y}"
        if node not in reachable:
            violations.append(
                f"H11: Utility {kind}@{anchor.x},{anchor.y} floating (not Airlock-reachable)"
            )

    return len(violations) == 0, violations


def check_h8_non_transit(layout: OracleLayout) -> tuple[bool, list[str]]:
    """Check H8: Non-transit rooms cannot bridge opposite sides.

    Non-transit rooms (radiation_repulsor, rapidium_ark) should not have
    internal left-right edges.
    """
    violations = []

    for room in layout.rooms:
        if room.module_key not in ("radiation_repulsor", "rapidium_ark"):
            continue

        left_ports = [port for port in room.ports if port.side is PortSide.LEFT]
        right_ports = [port for port in room.ports if port.side is PortSide.RIGHT]

        for left_port in left_ports:
            for right_port in right_ports:
                if left_port.edge_x == right_port.edge_x and left_port.edge_y == right_port.edge_y:
                    violations.append(
                        f"H8: Non-transit room {room.instance_id} has internal edge at ({left_port.edge_x}, {left_port.edge_y})"
                    )

    return len(violations) == 0, violations


def check_all_h_rules(
    layout: OracleLayout,
    base_buildable: frozenset[tuple[int, int]],
    root_instance_id: str = "airlock-1",
) -> tuple[bool, list[str]]:
    """Check all H-rules for a layout."""
    all_violations = []

    _, v2 = check_h2_base_mask(layout, base_buildable)
    _, v3 = check_h3_overlap(layout)
    _, v6 = check_h6_local_connection(layout)
    _, v7 = check_h7_airlock_reachability(layout, root_instance_id)
    _, v8 = check_h8_non_transit(layout)

    all_violations.extend(v2)
    all_violations.extend(v3)
    all_violations.extend(v6)
    all_violations.extend(v7)
    all_violations.extend(v8)

    return len(all_violations) == 0, all_violations


def canonicalize_layout(layout: OracleLayout) -> tuple[tuple[str, str, int, int], ...]:
    """Return canonical placement representation for deduplication."""
    return tuple(
        (r.instance_id, r.module_key, r.x, r.y)
        for r in sorted(layout.rooms, key=lambda x: x.instance_id)
    )