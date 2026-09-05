from alters_base_planner.base import builtin_base
from alters_base_planner.engine import solve_plan
from alters_base_planner.models import PlanRequest


def test_base_tiers_grow_and_keep_4x2_blocked_core() -> None:
    areas = []
    expected_capacities = {1: 300, 2: 450, 3: 700, 4: 800}
    for tier in (1, 2, 3, 4):
        base = builtin_base(tier)
        assert base.blocked_cells
        assert base.blocked_cells <= base.allowed_cells
        assert len(base.blocked_cells) == 8  # immovable Organics Tank: 4 x 2
        assert base.organics_capacity == expected_capacities[tier]
        assert base.verified is False  # exact perimeter coordinates are not authoritative yet
        areas.append(len(base.buildable_cells))
    assert areas == sorted(areas)
    assert len(set(areas)) == 4


def test_solver_returns_structured_status() -> None:
    result = solve_plan(
        PlanRequest(
            tier=2,
            room_counts={"workshop": 1, "research_lab": 1, "dormitory": 1},
            time_limit_s=3,
            max_layout_attempts=5,
        )
    )
    assert result.status in {"OPTIMAL", "FEASIBLE", "NO_CONNECTED_LAYOUT", "INFEASIBLE"}
    assert result.base.tier == 2
