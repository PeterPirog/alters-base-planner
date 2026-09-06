import pytest

from alters_base_planner.base import builtin_base
from alters_base_planner.distance import room_access_rows
from alters_base_planner.engine import (
    _mass_metrics,
    _route_utilities,
    _validate_utility_geometry,
    solve_plan,
)
from alters_base_planner.models import BaseGeometry, Placement, PlanRequest, UtilityPlacement


def test_base_tiers_grow_but_exact_masks_remain_provisional() -> None:
    areas = []
    expected_capacities = {1: 300, 2: 450, 3: 700, 4: 800}
    for tier in (1, 2, 3, 4):
        base = builtin_base(tier)
        assert base.blocked_cells
        assert base.blocked_cells <= base.allowed_cells
        assert base.organics_capacity == expected_capacities[tier]
        assert base.verified is False
        areas.append(len(base.buildable_cells))
    assert areas == sorted(areas)
    assert len(set(areas)) == 4


def test_explicit_port_access_rows_for_regular_and_special_modules() -> None:
    regular = Placement("storage-1", "small_storage", 4, 5, 2, 2)
    repulsor = Placement("repulsor-1", "radiation_repulsor", 4, 5, 2, 3)
    assert room_access_rows(regular) == frozenset({6})
    assert room_access_rows(repulsor) == frozenset({5})


def test_rapidium_ark_cannot_be_used_as_walkthrough_bridge() -> None:
    allowed = frozenset((x, y) for y in range(2) for x in range(12))
    base = BaseGeometry(
        tier=1,
        width=12,
        height=2,
        allowed_cells=allowed,
        blocked_cells=frozenset(),
        organics_capacity=300,
        source="unit-test",
        verified=True,
    )
    rooms = [
        Placement("airlock-1", "airlock", 0, 1, 4, 1),
        Placement("ark-1", "rapidium_ark", 4, 0, 4, 2),
        Placement("workshop-1", "workshop", 8, 1, 4, 1),
    ]
    # Everything touches geometrically, but the Ark is sealed/non-transit and fills
    # both rows, so there is no alternative corridor/elevator route around it.
    assert _route_utilities(base, rooms) is None


def test_generated_utilities_cannot_overlap_each_other() -> None:
    base = BaseGeometry(
        tier=1,
        width=8,
        height=2,
        allowed_cells=frozenset((x, y) for y in range(2) for x in range(8)),
        blocked_cells=frozenset(),
        organics_capacity=300,
        source="unit-test",
        verified=True,
    )
    with pytest.raises(AssertionError, match="overlap"):
        _validate_utility_geometry(
            base,
            [],
            [
                UtilityPlacement("corridor", 2, 0),  # cells 2,3
                UtilityPlacement("corridor", 3, 0),  # cells 3,4: illegal one-cell overlap
            ],
        )


def test_mass_metrics_match_journey_organics_rule() -> None:
    base = builtin_base(2)
    rooms = [
        Placement("dormitory-1", "dormitory", 0, 0, 6, 1),
        Placement("workshop-1", "workshop", 0, 1, 4, 1),
    ]
    utilities = [
        UtilityPlacement("corridor", 0, 2),
        UtilityPlacement("elevator", 2, 2),
    ]

    room_mass, utility_mass, total_mass, margin, travel_ok, breakdown = _mass_metrics(
        base, rooms, utilities
    )
    assert room_mass == 16  # Dormitory 8 + Workshop 8
    assert utility_mass == 4
    assert total_mass == 20
    assert margin == 430
    assert travel_ok is True
    assert sum(breakdown.values()) == total_mass


def test_programmatic_unknown_room_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown room keys"):
        solve_plan(
            PlanRequest(
                tier=4,
                room_counts={"teleporter": 1},
                time_limit_s=0.1,
                max_layout_attempts=1,
            )
        )


def test_programmatic_recycler_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="recycler allows at most 1"):
        solve_plan(
            PlanRequest(
                tier=4,
                room_counts={"recycler": 2},
                time_limit_s=0.1,
                max_layout_attempts=1,
            )
        )


def test_supplied_base_must_match_requested_tier() -> None:
    with pytest.raises(ValueError, match="does not match"):
        solve_plan(
            PlanRequest(tier=1, room_counts={}, time_limit_s=0.1, max_layout_attempts=1),
            builtin_base(2),
        )


def test_solver_returns_persisted_mass_and_search_metrics_when_connected() -> None:
    result = solve_plan(
        PlanRequest(
            tier=2,
            room_counts={"workshop": 1, "research_lab": 1, "dormitory": 1},
            time_limit_s=3,
            max_layout_attempts=8,
        )
    )
    assert result.status in {"FEASIBLE", "NO_CONNECTED_LAYOUT", "INFEASIBLE", "TIME_LIMIT"}
    assert result.base.tier == 2
    assert result.search_time_s >= 0
    assert 0 <= result.attempts <= 8
    assert result.connected_candidates_examined >= 0
    assert result.manhattan_pruned_count >= 0
    if result.rooms:
        assert result.status == "FEASIBLE"
        assert result.connected_candidates_examined >= 1
        assert result.total_mass == result.room_mass + result.utility_mass
        assert result.organics_required_for_journey == result.total_mass
        assert result.organics_capacity_margin == result.base.organics_capacity - result.total_mass
        assert result.travel_feasible_at_full_tank == (
            result.total_mass <= result.base.organics_capacity
        )
        assert sum(result.mass_breakdown.values()) == result.total_mass
