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


class PlacementAuthority(StrEnum):
    """Who determines that a module instance exists in a plan."""

    SYSTEM = "system"
    PLAYER = "player"
    SOLVER = "solver"


class PortSide(StrEnum):
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True, slots=True)
class PortSpec:
    """Logical module access port in module-local coordinates.

    ``cell_x`` is measured from the module's left edge. ``cell_y`` is measured upward from
    the module floor: 0 is the floor row and ``height - 1`` is the top row. World/Base
    coordinates use the opposite vertical convention: y=0 at the top and y grows downward.
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
        """Top-left 2x1 solver-infrastructure anchor outside this horizontal port."""

        x = self.edge_x - 2 if self.side is PortSide.LEFT else self.edge_x
        return (x, self.edge_y)


def floor_ports(width: int) -> tuple[PortSpec, PortSpec]:
    """Derive standard floor ports: LEFT=(0,0), RIGHT=(width-1,0)."""

    if width <= 0:
        raise ValueError("Module width must be positive when deriving floor ports")
    return (
        PortSpec("left", PortSide.LEFT, 0, 0),
        PortSpec("right", PortSide.RIGHT, width - 1, 0),
    )


def top_ports(width: int, height: int) -> tuple[PortSpec, PortSpec]:
    """Derive LEFT/RIGHT ports on the module top row."""

    if width <= 0 or height <= 0:
        raise ValueError("Module width and height must be positive when deriving top ports")
    top_y = height - 1
    return (
        PortSpec("left", PortSide.LEFT, 0, top_y),
        PortSpec("right", PortSide.RIGHT, width - 1, top_y),
    )


def footprint_cells(x: int, y: int, width: int, height: int) -> frozenset[tuple[int, int]]:
    """Return occupied cells for any rectangular module footprint."""

    if x < 0 or y < 0:
        raise ValueError("Module footprint coordinates must be non-negative")
    if width <= 0 or height <= 0:
        raise ValueError("Module footprint dimensions must be positive")
    return frozenset(
        (xx, yy)
        for xx in range(x, x + width)
        for yy in range(y, y + height)
    )


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    """Canonical domain definition for every installable Base module."""

    key: str
    name: str
    width: int
    height: int
    mass: int
    module_type: ModuleType
    authority: PlacementAuthority
    visit_weight: float
    ports: tuple[PortSpec, ...]
    transit_allowed: bool = True
    vertical_connectivity: bool = False
    max_count: int | None = None

    def __post_init__(self) -> None:
        if not self.key or not self.name:
            raise ValueError("Module key and name must be non-empty")
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
        if self.vertical_connectivity and self.authority is not PlacementAuthority.SOLVER:
            raise ValueError(
                f"Vertical connectivity is currently reserved for solver infrastructure: {self.key}"
            )
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
    """Required SYSTEM/PLAYER module before a concrete placement is chosen."""

    instance_id: str
    spec: ModuleSpec


@dataclass(frozen=True, slots=True)
class ModulePlacement:
    """One concrete placement of any SYSTEM, PLAYER or SOLVER module."""

    instance_id: str
    module_key: str
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if not self.instance_id:
            raise ValueError("Module placement instance_id must not be empty")
        if not self.module_key:
            raise ValueError(f"Placement {self.instance_id} has an empty module_key")
        if self.x < 0 or self.y < 0:
            raise ValueError(f"Placement {self.instance_id} has negative coordinates")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"Placement {self.instance_id} must have positive dimensions")

    @property
    def cells(self) -> frozenset[tuple[int, int]]:
        return footprint_cells(self.x, self.y, self.width, self.height)


def resolve_ports(module: ModulePlacement, spec: ModuleSpec) -> tuple[ResolvedPort, ...]:
    """Resolve floor-relative module ports into absolute top-origin Base-grid coordinates."""

    if module.module_key != spec.key:
        raise ValueError(
            f"Placement {module.instance_id} key {module.module_key!r} does not match spec {spec.key!r}"
        )
    if module.width != spec.width or module.height != spec.height:
        raise ValueError(
            f"Placement {module.instance_id} footprint {module.width}x{module.height} does not match "
            f"module {spec.key} footprint {spec.width}x{spec.height}"
        )

    result: list[ResolvedPort] = []
    for port in spec.ports:
        cell_x = module.x + port.cell_x
        world_y_offset = module.height - 1 - port.cell_y
        cell_y = module.y + world_y_offset
        edge_x = module.x if port.side is PortSide.LEFT else module.x + module.width
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
    usage_weights: dict[str, float] = field(default_factory=dict)

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
        if not isinstance(self.usage_weights, dict):
            raise ValueError("usage_weights must be an object mapping module keys to weights")
        self.usage_weights = dict(self.usage_weights)
        for key, weight in self.usage_weights.items():
            if not isinstance(key, str) or not key:
                raise ValueError("usage weight keys must be non-empty strings")
            if (
                isinstance(weight, bool)
                or not isinstance(weight, (int, float))
                or not math.isfinite(float(weight))
                or not 0.0 <= weight <= 1.0
            ):
                raise ValueError(
                    f"usage weight for {key} must be a finite number from 0 to 1"
                )
            self.usage_weights[key] = float(weight)


@dataclass(slots=True)
class PlanResult:
    """Auditable solver result over one unified list of installed modules."""

    status: str
    base: BaseGeometry
    modules: list[ModulePlacement] = field(default_factory=list)
    objective_value: float | None = None
    objective_scale: int = 1
    scaled_objective_value: int | None = None
    scaled_modified_manhattan_lower_bound: int | None = None
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
    fixed_objective_optima_proven: int = 0
    manhattan_pruned_count: int = 0
    incumbent_bound_pruned_count: int = 0
    search_time_s: float = 0.0
    time_limit_reached: bool = False
    search_exhausted: bool = False
    global_objective_optimum_proven: bool = False
    fixed_subproblem_count: int = 0
    max_fixed_graph_nodes: int = 0
    max_fixed_graph_arcs: int = 0
    max_fixed_objective_pairs: int = 0
    fixed_flow_formulation: str = "source_aggregated_weighted_flow"
    max_fixed_source_commodities: int = 0
    max_fixed_source_flow_variables: int = 0
    max_fixed_source_flow_full_variables: int = 0
    total_fixed_source_flow_variables: int = 0
    total_fixed_source_flow_full_variables: int = 0
    max_fixed_condition_capacity_buckets: int = 0
    max_fixed_condition_capacity_literals: int = 0
    max_fixed_endpoint_distribution_variables: int = 0
    max_fixed_flow_capacity_constraints: int = 0
    max_fixed_flow_balance_constraints: int = 0
    max_fixed_cp_sat_variables: int = 0
    max_fixed_cp_sat_constraints: int = 0
    fixed_model_build_time_s: float = 0.0
    fixed_cp_sat_solve_time_s: float = 0.0
    fixed_subproblem_time_s: float = 0.0
    fixed_lexicographic_scalarization_used: bool = False
    max_fixed_primary_objective_upper_bound: int = 0
    max_fixed_combined_objective_upper_bound: int = 0
    max_fixed_lexicographic_weight_f: int = 0
    max_fixed_lexicographic_weight_mass: int = 0
    max_fixed_lexicographic_weight_elevator: int = 0
    max_fixed_lexicographic_weight_corridor: int = 0
    max_fixed_lexicographic_corridor_bound: int = 0
    max_fixed_lexicographic_elevator_bound: int = 0
    max_fixed_lexicographic_mass_bound: int = 0
    max_fixed_incumbent_scalar_value: int | None = None
    fixed_hard_model_build_time_s: float = 0.0
    fixed_path_graph_build_time_s: float = 0.0
    fixed_objective_definition_time_s: float = 0.0
    fixed_source_flow_model_build_time_s: float = 0.0
    fixed_lexicographic_finalize_time_s: float = 0.0

    @property
    def used_cells(self) -> set[tuple[int, int]]:
        cells: set[tuple[int, int]] = set()
        for module in self.modules:
            cells.update(module.cells)
        return cells


def expand_instances(specs: Iterable[ModuleSpec], counts: dict[str, int]) -> list[ModuleInstance]:
    """Expand exactly-one SYSTEM modules plus requested PLAYER modules.

    SOLVER modules deliberately produce no instances here: their multiplicity belongs to the
    optimization model rather than player input.
    """

    spec_list = tuple(specs)
    spec_by_key = {spec.key: spec for spec in spec_list}
    unknown = sorted(set(counts) - set(spec_by_key))
    if unknown:
        raise ValueError(f"Unknown module keys: {', '.join(unknown)}")

    for key, requested in counts.items():
        spec = spec_by_key[key]
        if spec.authority is not PlacementAuthority.PLAYER:
            raise ValueError(
                f"Module {key} is {spec.authority.value}-managed and cannot be configured"
            )
        if spec.max_count is not None and requested > spec.max_count:
            raise ValueError(f"Module {key} allows at most {spec.max_count} instance(s)")

    result: list[ModuleInstance] = []
    for spec in spec_list:
        if spec.authority is PlacementAuthority.SOLVER:
            continue
        count = counts.get(spec.key, 0) if spec.authority is PlacementAuthority.PLAYER else 1
        if spec.max_count is not None and count > spec.max_count:
            raise ValueError(f"Module {spec.key} allows at most {spec.max_count} instance(s)")
        for idx in range(count):
            result.append(ModuleInstance(f"{spec.key}-{idx + 1}", spec))
    return result
