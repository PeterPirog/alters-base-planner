from __future__ import annotations

import math
from dataclasses import dataclass
from time import monotonic

from .catalog import MODULE_BY_KEY
from .distance import DistanceMetrics, weighted_modified_manhattan_lower_bound
from .fixed_objective_oracle import FixedObjectiveResult, solve_fixed_layout_objective
from .integrated_hard_solver import StaticInfeasibilityError, enumerate_placement_options
from .models import BaseGeometry, ModuleInstance, ModulePlacement, PlacementAuthority


@dataclass(frozen=True, slots=True)
class GlobalReferenceResult:
    """End-to-end exact reference result over room packings and infrastructure choices.

    This is a Stage-3 correctness oracle for tiny instances. It exhaustively enumerates
    non-overlapping SYSTEM/PLAYER room packings (modulo pure identical-instance symmetry),
    solves the exact fixed-packing infrastructure objective for every packing that cannot be
    safely pruned, and reports a global proof only when every packing is resolved or excluded by
    the admissible modified-Manhattan lower bound.
    """

    status: str
    rooms: tuple[ModulePlacement, ...] = ()
    utilities: tuple[ModulePlacement, ...] = ()
    distance_metrics: DistanceMetrics | None = None
    global_objective_lower_bound: float | None = None
    room_packings_total: int = 0
    room_packings_evaluated: int = 0
    room_packings_pruned_by_bound: int = 0
    infrastructure_networks_examined: int = 0
    time_limit_reached: bool = False
    search_exhausted: bool = False
    global_objective_optimum_proven: bool = False

    @property
    def modules(self) -> tuple[ModulePlacement, ...]:
        return (*self.rooms, *self.utilities)


def _validate_instances(
    instances: tuple[ModuleInstance, ...],
    *,
    root_instance_id: str,
) -> None:
    if not instances:
        raise ValueError("Global objective oracle requires at least one module instance")

    instance_ids = [instance.instance_id for instance in instances]
    if len(instance_ids) != len(set(instance_ids)):
        raise ValueError("Module instance IDs must be unique")

    by_id = {instance.instance_id: instance for instance in instances}
    root = by_id.get(root_instance_id)
    if root is None:
        raise ValueError(f"Root instance {root_instance_id!r} is not present")
    if root.spec.key != "airlock":
        raise ValueError("Global objective oracle root instance must be the Airlock")
    if sum(instance.spec.key == "airlock" for instance in instances) != 1:
        raise ValueError("Global objective oracle requires exactly one Airlock instance")

    canonical_by_key: dict[str, object] = {}
    for instance in instances:
        if instance.spec.authority is PlacementAuthority.SOLVER:
            raise ValueError(
                f"SOLVER module {instance.spec.key} must not be a required room instance"
            )
        prior = canonical_by_key.setdefault(instance.spec.key, instance.spec)
        if prior != instance.spec:
            raise ValueError(
                f"Instances of module key {instance.spec.key!r} must share one ModuleSpec"
            )


def _enumerate_nonoverlapping_packings(
    base: BaseGeometry,
    instances: tuple[ModuleInstance, ...],
    *,
    deadline: float,
) -> tuple[tuple[tuple[ModulePlacement, ...], ...], bool]:
    """Enumerate physical room packings exactly, removing only label symmetry.

    Identical module instances are interchangeable for geometry, connectivity, mass and the
    accepted objective. Requiring their selected `(y, x)` placements to increase strictly is
    therefore pure symmetry breaking and cannot remove a distinct physical layout.
    """

    try:
        options, placement_by_option_id = enumerate_placement_options(base, instances)
    except StaticInfeasibilityError:
        return (), True

    placements_by_instance: dict[str, list[ModulePlacement]] = {
        instance.instance_id: [] for instance in instances
    }
    for option in options:
        placements_by_instance[option.instance_id].append(
            placement_by_option_id[option.option_id]
        )
    for placements in placements_by_instance.values():
        placements.sort(key=lambda placement: (placement.y, placement.x))

    packings: list[tuple[ModulePlacement, ...]] = []
    occupied: set[tuple[int, int]] = set()
    selected: list[ModulePlacement] = []
    last_coordinate_by_key: dict[str, tuple[int, int]] = {}
    complete = True

    def visit(index: int) -> None:
        nonlocal complete
        if not complete:
            return
        if monotonic() >= deadline:
            complete = False
            return
        if index == len(instances):
            packings.append(tuple(selected))
            return

        instance = instances[index]
        previous = last_coordinate_by_key.get(instance.spec.key)
        for placement in placements_by_instance[instance.instance_id]:
            coordinate = (placement.y, placement.x)
            if previous is not None and coordinate <= previous:
                continue
            if placement.cells & occupied:
                continue

            selected.append(placement)
            occupied.update(placement.cells)
            old_coordinate = last_coordinate_by_key.get(instance.spec.key)
            last_coordinate_by_key[instance.spec.key] = coordinate
            visit(index + 1)
            if old_coordinate is None:
                del last_coordinate_by_key[instance.spec.key]
            else:
                last_coordinate_by_key[instance.spec.key] = old_coordinate
            occupied.difference_update(placement.cells)
            selected.pop()

            if not complete:
                return

    visit(0)
    return tuple(packings), complete


def _packing_signature(rooms: tuple[ModulePlacement, ...]) -> tuple[tuple[str, int, int], ...]:
    return tuple(sorted((room.module_key, room.x, room.y) for room in rooms))


def _candidate_rank(
    rooms: tuple[ModulePlacement, ...],
    fixed_result: FixedObjectiveResult,
) -> tuple[float, int, int, int]:
    metrics = fixed_result.distance_metrics
    if metrics is None:
        raise AssertionError("Cannot rank a fixed-layout result without exact distance metrics")
    total_mass = sum(
        MODULE_BY_KEY[module.module_key].mass
        for module in (*rooms, *fixed_result.utilities)
    )
    return (
        metrics.weighted_score,
        total_mass,
        metrics.elevator_module_count,
        metrics.corridor_count,
    )


def _time_limited_result(
    *,
    best_rooms: tuple[ModulePlacement, ...],
    best_fixed: FixedObjectiveResult | None,
    lower_bound: float,
    room_packings_total: int,
    room_packings_evaluated: int,
    room_packings_pruned_by_bound: int,
    infrastructure_networks_examined: int,
) -> GlobalReferenceResult:
    return GlobalReferenceResult(
        status="FEASIBLE" if best_fixed is not None else "TIME_LIMIT",
        rooms=best_rooms,
        utilities=best_fixed.utilities if best_fixed is not None else (),
        distance_metrics=best_fixed.distance_metrics if best_fixed is not None else None,
        global_objective_lower_bound=lower_bound,
        room_packings_total=room_packings_total,
        room_packings_evaluated=room_packings_evaluated,
        room_packings_pruned_by_bound=room_packings_pruned_by_bound,
        infrastructure_networks_examined=infrastructure_networks_examined,
        time_limit_reached=True,
    )


def solve_global_reference_objective(
    base: BaseGeometry,
    instances: tuple[ModuleInstance, ...],
    *,
    time_limit_s: float,
    root_instance_id: str = "airlock-1",
) -> GlobalReferenceResult:
    """Prove the complete accepted objective on tiny instances by exact decomposition.

    This reference solver is intentionally exponential. It exists to establish known optima and
    validate future scalable Stage-3 formulations, not to replace the production Base I-IV
    solver. A global proof means every physical room packing has either:

    - an exactly solved fixed-packing infrastructure objective;
    - a proof of infrastructure infeasibility; or
    - an admissible room-packing lower bound strictly above the incumbent exact `F`.

    Equality with the incumbent cannot be pruned because mass/Elevator/Corridor tie-breakers may
    still improve.
    """

    _validate_instances(instances, root_instance_id=root_instance_id)
    if time_limit_s <= 0:
        return GlobalReferenceResult(
            status="TIME_LIMIT",
            global_objective_lower_bound=0.0,
            time_limit_reached=True,
        )

    deadline = monotonic() + float(time_limit_s)
    packings, enumeration_complete = _enumerate_nonoverlapping_packings(
        base,
        instances,
        deadline=deadline,
    )
    if not enumeration_complete:
        return GlobalReferenceResult(
            status="TIME_LIMIT",
            global_objective_lower_bound=0.0,
            room_packings_total=len(packings),
            time_limit_reached=True,
        )
    if not packings:
        return GlobalReferenceResult(
            status="INFEASIBLE",
            room_packings_total=0,
            search_exhausted=True,
        )

    packing_entries = [
        (
            weighted_modified_manhattan_lower_bound(list(rooms)),
            _packing_signature(rooms),
            rooms,
        )
        for rooms in packings
    ]
    packing_entries.sort(key=lambda entry: (entry[0], entry[1]))

    best_rooms: tuple[ModulePlacement, ...] = ()
    best_fixed: FixedObjectiveResult | None = None
    best_rank: tuple[float, int, int, int] | None = None
    room_packings_evaluated = 0
    room_packings_pruned = 0
    networks_examined = 0

    for index, (packing_lower_bound, _signature, rooms) in enumerate(packing_entries):
        incumbent_f = best_rank[0] if best_rank is not None else math.inf
        if packing_lower_bound > incumbent_f + 1e-12:
            room_packings_pruned += len(packing_entries) - index
            break

        current_global_lower_bound = min(incumbent_f, packing_lower_bound)
        remaining = deadline - monotonic()
        if remaining <= 0:
            return _time_limited_result(
                best_rooms=best_rooms,
                best_fixed=best_fixed,
                lower_bound=current_global_lower_bound,
                room_packings_total=len(packings),
                room_packings_evaluated=room_packings_evaluated,
                room_packings_pruned_by_bound=room_packings_pruned,
                infrastructure_networks_examined=networks_examined,
            )

        fixed = solve_fixed_layout_objective(
            base,
            rooms,
            time_limit_s=remaining,
            root_instance_id=root_instance_id,
        )
        room_packings_evaluated += 1
        networks_examined += fixed.networks_examined

        if fixed.status == "INFEASIBLE":
            if not fixed.search_exhausted:
                raise AssertionError("Fixed objective oracle reported unproven infeasibility")
            continue

        if fixed.distance_metrics is not None:
            rank = _candidate_rank(rooms, fixed)
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best_rooms = rooms
                best_fixed = fixed

        if fixed.status != "OPTIMAL" or not fixed.objective_optimum_proven:
            incumbent_f = best_rank[0] if best_rank is not None else math.inf
            lower_bound = min(incumbent_f, packing_lower_bound)
            return _time_limited_result(
                best_rooms=best_rooms,
                best_fixed=best_fixed,
                lower_bound=lower_bound,
                room_packings_total=len(packings),
                room_packings_evaluated=room_packings_evaluated,
                room_packings_pruned_by_bound=room_packings_pruned,
                infrastructure_networks_examined=networks_examined,
            )

    if best_fixed is None:
        return GlobalReferenceResult(
            status="INFEASIBLE",
            room_packings_total=len(packings),
            room_packings_evaluated=room_packings_evaluated,
            room_packings_pruned_by_bound=room_packings_pruned,
            infrastructure_networks_examined=networks_examined,
            search_exhausted=True,
        )

    if best_fixed.distance_metrics is None:
        raise AssertionError("Proven global incumbent is missing exact distance metrics")

    return GlobalReferenceResult(
        status="OPTIMAL",
        rooms=best_rooms,
        utilities=best_fixed.utilities,
        distance_metrics=best_fixed.distance_metrics,
        global_objective_lower_bound=best_fixed.distance_metrics.weighted_score,
        room_packings_total=len(packings),
        room_packings_evaluated=room_packings_evaluated,
        room_packings_pruned_by_bound=room_packings_pruned,
        infrastructure_networks_examined=networks_examined,
        search_exhausted=True,
        global_objective_optimum_proven=True,
    )
