from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable


class ModuleType(StrEnum):
    CORE = "core"
    WORK = "work"
    WELLBEING = "wellbeing"
    STORAGE = "storage"
    UTILITY = "utility"


class ConnectionLevel(StrEnum):
    BOTTOM = "bottom"
    TOP = "top"


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
    connection_level: ConnectionLevel = ConnectionLevel.BOTTOM
    transit_allowed: bool = True


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

    @property
    def cells(self) -> frozenset[tuple[int, int]]:
        return frozenset(
            (xx, yy)
            for xx in range(self.x, self.x + self.width)
            for yy in range(self.y, self.y + self.height)
        )


@dataclass(frozen=True, slots=True)
class UtilityPlacement:
    kind: str  # corridor | elevator
    x: int
    y: int
    width: int = 2
    height: int = 1

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

    @property
    def buildable_cells(self) -> frozenset[tuple[int, int]]:
        return self.allowed_cells - self.blocked_cells


@dataclass(slots=True)
class PlanRequest:
    tier: int
    room_counts: dict[str, int]
    objective: str = "lexicographic_access"
    min_elevators: int = 3
    max_elevators: int | None = None
    time_limit_s: float = 15.0
    max_layout_attempts: int = 20


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

    @property
    def used_cells(self) -> set[tuple[int, int]]:
        cells: set[tuple[int, int]] = set()
        for room in self.rooms:
            cells.update(room.cells)
        for utility in self.utilities:
            cells.update(utility.cells)
        return cells


def expand_instances(specs: Iterable[ModuleSpec], counts: dict[str, int]) -> list[ModuleInstance]:
    result: list[ModuleInstance] = []
    for spec in specs:
        count = max(counts.get(spec.key, 0), 1 if spec.mandatory else 0)
        for idx in range(count):
            result.append(ModuleInstance(f"{spec.key}-{idx + 1}", spec))
    return result
