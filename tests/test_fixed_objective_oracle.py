from itertools import product

import pytest

from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.distance import evaluate_distances
from alters_base_planner.fixed_objective_oracle import solve_fixed_layout_objective
from alters_base_planner.models import BaseGeometry, ModulePlacement, footprint_cells


def _base(width: int, height: int) -> BaseGeometry:
    return BaseGeometry(
        tier=99,
        width=width,
        height=height,
        allowed_cells=frozenset((x, y) for y in range(height) for x in range(width)),
        blocked_cells=frozenset(),
        organics_capacity=999,
        source="stage3-objective-test",
        verified=True,
    )


def _room(instance_id: str, module_key: str, x: int, y: int) -> ModulePlacement:
    spec = MODULE_BY_KEY[module_key]
    return ModulePlacement(instance_id, module_key, x, y, spec.width, spec.height)


def _free_utility_anchors(
    base: BaseGeometry,
    rooms: tuple[ModulePlacement, ...],
) -> tuple[tuple[int, int], ...]:
    corridor = MODULE_BY_KEY["corridor"]
    occupied = set().union(*(room.cells for room in rooms)) if rooms else set()
    anchors: list[tuple[int, int]] = []
    for y in range(base.height - corridor.height + 1):
        for x in range(base.width - corridor.width + 1):
            cells = footprint_cells(x, y, corridor.width, corridor.height)
            if cells <= base.buildable_cells and not (cells & occupied):
                anchors.append((x, y))
    return tuple(anchors)


def _brute_force_fixed_objective(
    base: BaseGeometry,
    rooms: tuple[ModulePlacement, ...],
) -> tuple[tuple[float, int, int, int], tuple[tuple[str, int, int], ...]] | None:
    """Independent exhaustive utility-state enumeration for tiny regression instances."""

    anchors = _free_utility_anchors(base, rooms)
    best: tuple[tuple[float, int, int, int], tuple[tuple[str, int, int], ...]] | None = None

    for states in product((None, "corridor", "elevator"), repeat=len(anchors)):
        utilities: list[ModulePlacement] = []
        counts = {"corridor": 0, "elevator": 0}
        for anchor, module_key in zip(anchors, states, strict=True):
            if module_key is None:
                continue
            spec = MODULE_BY_KEY[module_key]
            counts[module_key] += 1
            utilities.append(
                ModulePlacement(
                    instance_id=f"{module_key}-brute-{counts[module_key]}",
                    module_key=module_key,
                    x=anchor[0],
                    y=anchor[1],
                    width=spec.width,
                    height=spec.height,
                )
            )

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
        signature = tuple(sorted((u.module_key, u.x, u.y) for u in utilities))
        candidate = (rank, signature)
        if best is None or candidate[0] < best[0]:
            best = candidate

    return best


def test_fixed_objective_oracle_proves_zero_cost_direct_adjacency() -> None:
    base = _base(8, 1)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 4, 0),
    )

    result = solve_fixed_layout_objective(base, rooms, time_limit_s=2.0)

    assert result.status == "OPTIMAL"
    assert result.objective_optimum_proven is True
    assert result.search_exhausted is True
    assert result.time_limit_reached is False
    assert result.networks_examined == 1
    assert result.utilities == ()
    assert result.distance_metrics is not None
    assert result.distance_metrics.weighted_score == pytest.approx(0.0)
    assert result.objective_lower_bound == pytest.approx(0.0)


def test_fixed_objective_oracle_matches_independent_exhaustive_enumeration() -> None:
    base = _base(10, 1)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 6, 0),
    )
    assert _free_utility_anchors(base, rooms) == ((4, 0),)

    brute = _brute_force_fixed_objective(base, rooms)
    assert brute is not None
    result = solve_fixed_layout_objective(base, rooms, time_limit_s=2.0)

    assert result.status == "OPTIMAL"
    assert result.objective_optimum_proven is True
    assert result.search_exhausted is True
    assert result.networks_examined == 2
    assert result.distance_metrics is not None
    assert result.distance_metrics.weighted_score == pytest.approx(brute[0][0])
    assert result.objective_lower_bound == pytest.approx(0.9)
    assert tuple(sorted((u.module_key, u.x, u.y) for u in result.utilities)) == brute[1]
    assert brute[1] == (("corridor", 4, 0),)


def test_fixed_objective_oracle_proves_infeasible_without_vertical_space() -> None:
    base = _base(4, 2)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 0, 1),
    )

    result = solve_fixed_layout_objective(base, rooms, time_limit_s=2.0)

    assert result.status == "INFEASIBLE"
    assert result.search_exhausted is True
    assert result.objective_optimum_proven is False
    assert result.networks_examined == 0
    assert result.utilities == ()
    assert result.distance_metrics is None
