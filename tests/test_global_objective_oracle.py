from itertools import product

import pytest

from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.distance import evaluate_distances
from alters_base_planner.global_objective_oracle import solve_global_reference_objective
from alters_base_planner.models import (
    BaseGeometry,
    ModuleInstance,
    ModulePlacement,
    footprint_cells,
)


def _base(width: int, height: int) -> BaseGeometry:
    return BaseGeometry(
        tier=99,
        width=width,
        height=height,
        allowed_cells=frozenset((x, y) for y in range(height) for x in range(width)),
        blocked_cells=frozenset(),
        organics_capacity=999,
        source="stage3-global-reference-test",
        verified=True,
    )


def _instance(instance_id: str, module_key: str) -> ModuleInstance:
    return ModuleInstance(instance_id, MODULE_BY_KEY[module_key])


def _placement(instance_id: str, module_key: str, x: int, y: int) -> ModulePlacement:
    spec = MODULE_BY_KEY[module_key]
    return ModulePlacement(instance_id, module_key, x, y, spec.width, spec.height)


def _brute_force_two_room_global_rank(
    base: BaseGeometry,
) -> tuple[float, int, int, int] | None:
    """Independent exhaustive room + utility enumeration for a tiny one-floor Base."""

    airlock = MODULE_BY_KEY["airlock"]
    workshop = MODULE_BY_KEY["workshop"]
    corridor = MODULE_BY_KEY["corridor"]
    best: tuple[float, int, int, int] | None = None

    for airlock_x in range(base.width - airlock.width + 1):
        airlock_room = _placement("airlock-1", "airlock", airlock_x, 0)
        for workshop_x in range(base.width - workshop.width + 1):
            workshop_room = _placement("workshop-1", "workshop", workshop_x, 0)
            rooms = (airlock_room, workshop_room)
            if airlock_room.cells & workshop_room.cells:
                continue

            occupied = set(airlock_room.cells | workshop_room.cells)
            anchors: list[tuple[int, int]] = []
            for x in range(base.width - corridor.width + 1):
                cells = footprint_cells(x, 0, corridor.width, corridor.height)
                if cells <= base.buildable_cells and not (cells & occupied):
                    anchors.append((x, 0))

            for states in product((None, "corridor", "elevator"), repeat=len(anchors)):
                utilities: list[ModulePlacement] = []
                utility_cells: set[tuple[int, int]] = set()
                counts = {"corridor": 0, "elevator": 0}
                valid = True
                for anchor, module_key in zip(anchors, states, strict=True):
                    if module_key is None:
                        continue
                    spec = MODULE_BY_KEY[module_key]
                    utility = ModulePlacement(
                        instance_id=f"{module_key}-brute-{counts[module_key] + 1}",
                        module_key=module_key,
                        x=anchor[0],
                        y=anchor[1],
                        width=spec.width,
                        height=spec.height,
                    )
                    if utility.cells & utility_cells:
                        valid = False
                        break
                    counts[module_key] += 1
                    utility_cells.update(utility.cells)
                    utilities.append(utility)
                if not valid:
                    continue

                try:
                    metrics = evaluate_distances(list(rooms), utilities)
                except ValueError:
                    continue

                total_mass = sum(
                    MODULE_BY_KEY[module.module_key].mass for module in (*rooms, *utilities)
                )
                rank = (
                    metrics.weighted_score,
                    total_mass,
                    metrics.elevator_module_count,
                    metrics.corridor_count,
                )
                if best is None or rank < best:
                    best = rank

    return best


def test_global_reference_matches_independent_end_to_end_enumeration() -> None:
    base = _base(10, 1)
    instances = (
        _instance("airlock-1", "airlock"),
        _instance("workshop-1", "workshop"),
    )
    brute_rank = _brute_force_two_room_global_rank(base)
    assert brute_rank is not None

    result = solve_global_reference_objective(base, instances, time_limit_s=5.0)

    assert result.status == "OPTIMAL"
    assert result.global_objective_optimum_proven is True
    assert result.search_exhausted is True
    assert result.time_limit_reached is False
    assert result.distance_metrics is not None
    result_rank = (
        result.distance_metrics.weighted_score,
        sum(MODULE_BY_KEY[module.module_key].mass for module in result.modules),
        result.distance_metrics.elevator_module_count,
        result.distance_metrics.corridor_count,
    )
    assert result_rank == pytest.approx(brute_rank)
    assert result.global_objective_lower_bound == pytest.approx(brute_rank[0])
    assert result.room_packings_pruned_by_bound > 0


def test_global_reference_proves_infrastructure_infeasibility_for_all_packings() -> None:
    base = _base(4, 2)
    instances = (
        _instance("airlock-1", "airlock"),
        _instance("workshop-1", "workshop"),
    )

    result = solve_global_reference_objective(base, instances, time_limit_s=5.0)

    assert result.status == "INFEASIBLE"
    assert result.search_exhausted is True
    assert result.global_objective_optimum_proven is False
    assert result.room_packings_total == 2
    assert result.room_packings_evaluated == 2
    assert result.room_packings_pruned_by_bound == 0
    assert result.infrastructure_networks_examined == 0


def test_global_reference_breaks_only_identical_instance_label_symmetry() -> None:
    base = _base(12, 1)
    instances = (
        _instance("airlock-1", "airlock"),
        _instance("workshop-1", "workshop"),
        _instance("workshop-2", "workshop"),
    )

    result = solve_global_reference_objective(base, instances, time_limit_s=5.0)

    assert result.status == "OPTIMAL"
    assert result.global_objective_optimum_proven is True
    assert result.room_packings_total == 3
    assert result.room_packings_evaluated == 3
    assert result.room_packings_pruned_by_bound == 0
    assert result.distance_metrics is not None
