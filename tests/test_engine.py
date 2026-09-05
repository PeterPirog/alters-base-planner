from alters_base_planner.base import builtin_base
from alters_base_planner.engine import _connection_row, _mass_metrics, solve_plan
from alters_base_planner.models import Placement, PlanRequest, UtilityPlacement


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


def test_special_connection_rows() -> None:
    regular = Placement("storage-1", "small_storage", 4, 5, 2, 2)
    repulsor = Placement("repulsor-1", "radiation_repulsor", 4, 5, 2, 3)
    assert _connection_row(regular) == 6
    assert _connection_row(repulsor) == 5


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


def test_solver_returns_persisted_mass_metrics_when_connected() -> None:
    result = solve_plan(
        PlanRequest(
            tier=2,
            room_counts={"workshop": 1, "research_lab": 1, "dormitory": 1},
            time_limit_s=3,
            max_layout_attempts=8,
        )
    )
    assert result.status in {"FEASIBLE", "NO_CONNECTED_LAYOUT", "INFEASIBLE"}
    assert result.base.tier == 2
    if result.rooms:
        assert result.total_mass == result.room_mass + result.utility_mass
        assert result.organics_required_for_journey == result.total_mass
        assert result.organics_capacity_margin == result.base.organics_capacity - result.total_mass
        assert result.travel_feasible_at_full_tank == (
            result.total_mass <= result.base.organics_capacity
        )
        assert sum(result.mass_breakdown.values()) == result.total_mass
