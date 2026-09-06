from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable


class ModuleType(StrEnum):
    CORE = "core"
    WORK = "work"
    WELLBEING = "wellbeing"
    STORAGE = "storage"
    UTILITY = "utility"


class PortSide(StrEnum):
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True, slots=True)
class PortSpec:
    """Logical room access port located on a concrete room cell.

    `cell_x` and `cell_y` are offsets inside the module footprint. A 1x1 room therefore
    has both logical LEFT and RIGHT ports on the same physical cell (0, 0), while the
    side still distinguishes which outer boundary can connect to a neighbour/utility.
    """

    name: str
    side: PortSide
    cell_x: int
    cell_y: int


@dataclass(frozen=True, slots=True)
class ResolvedPort:
    name: str
    side: PortSide
    cell_x: int
    cell_y: int
    edge_x: int
    edge_y: int

    @property
    def cell(self) -> tuple[int, int]:
        return (self.cell_x, self.cell_y)

    @property
    def edge(self) -> tuple[int, int]:
        return (self.edge_x, self.edge_y)

    @property
    def utility_anchor(self) -> tuple[int, int]:
        """Top-left 2x1 Corridor/Elevator anchor immediately outside this port."""

        x = self.edge_x - 2 if self.side is PortSide.LEFT else self.edge_x
        return (x, self.edge_y)


def floor_ports(width: int, height: int) -> tuple[PortSpec, PortSpec]:
    """Standard LEFT/RIGHT ports on the module floor (bottom footprint row)."""

    floor_y = height - 1
    return (
        PortSpec("left", PortSide.LEFT, 0, floor_y),
        PortSpec("right", PortSide.RIGHT, width - 1, floor_y),
    )


def top_ports(width: int) -> tuple[PortSpec, PortSpec]:
    """LEFT/RIGHT ports on the top footprint row for verified game exceptions."""

    return (
        PortSpec("left", PortSide.LEFT, 0, 0),
        PortSpec("right", PortSide.RIGHT, width - 1, 0),
    )


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    key: str
    name: str
    width: int
    height: int
    mass: int
    module_type: ModuleType
    mandatory: bool = False
    configurable: bool = True
    visit_weight: float = 0.1
    ports: tuple[PortSpec, ...] = ()
    transit_allowed: bool = True
    max_count: int | None = None

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"Invalid module size for {self.key}: {self.width}x{self.height}")
        if self.mass < 0:
            raise ValueError(f"Invalid negative module mass for {self.key}: {self.mass}")
        if not 0 <= self.visit_weight <= 1:
            raise ValueError(f"Invalid visit weight for {self.key}: {self.visit_weight}")
        if self.max_count is not None and self.max_count < 1:
            raise ValueError(f"max_count for {self.key} must be >= 1 or None")
        if not self.ports:
            raise ValueError(f"Module {self.key} must define explicit access ports")
        names = {port.name for port in self.ports}
        if len(names) != len(self.ports):
            raise ValueError(f"Module {self.key} has duplicate port names")
        for port in self.ports:
            if not (0 <= port.cell_x < self.width and 0 <= port.cell_y < self.height):
                raise ValueError(f"Port {self.key}.{port.name} lies outside the module footprint")
            if port.side is PortSide.LEFT and port.cell_x != 0:
                raise ValueError(f"LEFT port {self.key}.{port.name} must use the leftmost cell")
            if port.side is PortSide.RIGHT and port.cell_x != self.width - 1:
                raise ValueError(f"RIGHT port {self.key}.{port.name} must use the rightmost cell")


@dataclass(frozen=True, slots=True)
class ModuleInstance:
    instance_id: str
    spec: ModuleSpec


@dataclass(frozen=True, slots=True)
class Placement:
    instance_id: str
    module_key: str
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.x < 0 or self.y < 0:
            raise ValueError(f"Placement {self.instance_id} has negative coordinates")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"Placement {self.instance_id} must have positive dimensions")

    @property
    def cells(self) -> frozenset[tuple[int, int]]:
        return frozenset(
            (xx, yy)
            for xx in range(self.x, self.x + self.width)
            for yy in range(self.y, self.y + self.height)
        )


def resolve_ports(room: Placement, spec: ModuleSpec) -> tuple[ResolvedPort, ...]:
    """Resolve relative port definitions to absolute floor-grid and boundary coordinates."""

    if room.width != spec.width or room.height != spec.height:
        raise ValueError(
            f"Placement {room.instance_id} footprint {room.width}x{room.height} does not match "
            f"module {spec.key} footprint {spec.width}x{spec.height}"
        )

    result: list[ResolvedPort] = []
    for port in spec.ports:
        cell_x = room.x + port.cell_x
        cell_y = room.y + port.cell_y
        edge_x = room.x if port.side is PortSide.LEFT else room.x + room.width
        result.append(
            ResolvedPort(
                name=port.name,
                side=port.side,
                cell_x=cell_x,
                cell_y=cell_y,
                edge_x=edge_x,
                edge_y=cell_y,
            )
        )
    return tuple(result)


@dataclass(frozen=True, slots=True)
class UtilityPlacement:
    kind: str  # corridor | elevator
    x: int
    y: int
    width: int = 2
    height: int = 1

    def __post_init__(self) -> None:
        if self.kind not in {"corridor", "elevator"}:
            raise ValueError(f"Unsupported utility kind: {self.kind}")
        if self.x < 0 or self.y < 0:
            raise ValueError(f"Utility {self.kind} has negative coordinates")
        if self.width != 2 or self.height != 1:
            raise ValueError(f"Utility {self.kind} must use the fixed 2x1 footprint")

    @property
    def cells(self) -> frozenset[tuple[int, int]]:
        return frozenset((self.x + dx, self.y) for dx in range(self.width))


@dataclass(frozen=True, slots=True)
class BaseGeometry:
    tier: int
    width: int
    height: int
    allowed_cells: frozenset[tuple[int, int]]
    blocked_cells: frozenset[tuple[int, int]]
    organics_capacity: int
    source: str = "unknown"
    verified: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        # BaseGeometry is also used by custom/imported grids, so its tier identifier is
        # deliberately extensible. Only player-facing PlanRequest is restricted to I-IV.
        if isinstance(self.tier, bool) or not isinstance(self.tier, int) or self.tier <= 0:
            raise ValueError("Base geometry tier must be a positive integer")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Base geometry must have positive width and height")
        if self.organics_capacity < 0:
            raise ValueError("Base organics capacity must be non-negative")
        if not self.allowed_cells:
            raise ValueError("Base geometry must contain at least one allowed cell")
        if not self.blocked_cells <= self.allowed_cells:
            raise ValueError("blocked_cells must be a subset of allowed_cells")
        out_of_bounds = sorted(
            (x, y)
            for x, y in self.allowed_cells
            if x < 0 or y < 0 or x >= self.width or y >= self.height
        )
        if out_of_bounds:
            raise ValueError(f"Base geometry contains out-of-bounds cells: {out_of_bounds[:3]}")

    @property
    def buildable_cells(self) -> frozenset[tuple[int, int]]:
        return self.allowed_cells - self.blocked_cells


@dataclass(slots=True)
class PlanRequest:
    tier: int
    room_counts: dict[str, int]
    objective: str = "weighted_pair_distance"
    time_limit_s: float = 15.0
    max_layout_attempts: int = 20

    def __post_init__(self) -> None:
        if self.tier not in (1, 2, 3, 4):
            raise ValueError("tier must be one of 1, 2, 3, 4")
        if self.objective != "weighted_pair_distance":
            raise ValueError("objective currently must be weighted_pair_distance")
        if (
            isinstance(self.time_limit_s, bool)
            or not isinstance(self.time_limit_s, (int, float))
            or not math.isfinite(float(self.time_limit_s))
            or self.time_limit_s <= 0
        ):
            raise ValueError("time_limit_s must be a finite number > 0")
        if (
            isinstance(self.max_layout_attempts, bool)
            or not isinstance(self.max_layout_attempts, int)
            or self.max_layout_attempts <= 0
        ):
            raise ValueError("max_layout_attempts must be a positive integer")
        for key, count in self.room_counts.items():
            if not isinstance(key, str) or not key:
                raise ValueError("room count keys must be non-empty strings")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError(f"room count for {key} must be a non-negative integer")


@dataclass(slots=True)
class PlanResult:
    status: str
    base: BaseGeometry
    rooms: list[Placement] = field(default_factory=list)
    utilities: list[UtilityPlacement] = field(default_factory=list)
    objective_value: float | None = None
    attempts: int = 0
    message: str = ""
    room_mass: int = 0
    utility_mass: int = 0
    total_mass: int = 0
    organics_required_for_journey: int = 0
    organics_capacity_margin: int = 0
    travel_feasible_at_full_tank: bool = False
    mass_breakdown: dict[str, int] = field(default_factory=dict)
    elevator_module_count: int = 0
    elevator_shaft_count: int = 0
    corridor_count: int = 0
    weighted_distance_score: float | None = None
    normalized_weighted_distance: float | None = None
    modified_manhattan_lower_bound: float | None = None
    pairwise_distances: dict[str, int] = field(default_factory=dict)
    pairwise_contributions: dict[str, float] = field(default_factory=dict)
    room_usage_weights: dict[str, float] = field(default_factory=dict)
    connected_candidates_examined: int = 0
    manhattan_pruned_count: int = 0
    search_time_s: float = 0.0
    time_limit_reached: bool = False
    search_exhausted: bool = False
    global_objective_optimum_proven: bool = False

    @property
    def used_cells(self) -> set[tuple[int, int]]:
        cells: set[tuple[int, int]] = set()
        for room in self.rooms:
            cells.update(room.cells)
        for utility in self.utilities:
            cells.update(utility.cells)
        return cells


def expand_instances(specs: Iterable[ModuleSpec], counts: dict[str, int]) -> list[ModuleInstance]:
    spec_list = tuple(specs)
    spec_by_key = {spec.key: spec for spec in spec_list}
    unknown = sorted(set(counts) - set(spec_by_key))
    if unknown:
        raise ValueError(f"Unknown room keys: {', '.join(unknown)}")

    for key, requested in counts.items():
        spec = spec_by_key[key]
        if not spec.configurable:
            raise ValueError(f"Module {key} is solver/story managed and cannot be configured")
        if spec.max_count is not None and requested > spec.max_count:
            raise ValueError(f"Module {key} allows at most {spec.max_count} instance(s)")

    result: list[ModuleInstance] = []
    for spec in spec_list:
        count = max(counts.get(spec.key, 0), 1 if spec.mandatory else 0)
        if spec.max_count is not None and count > spec.max_count:
            raise ValueError(f"Module {spec.key} allows at most {spec.max_count} instance(s)")
        for idx in range(count):
            result.append(ModuleInstance(f"{spec.key}-{idx + 1}", spec))
    return result
