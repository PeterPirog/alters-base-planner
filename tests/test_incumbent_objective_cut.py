import pytest

from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.fixed_flow_objective_solver import solve_fixed_layout_flow_objective
from alters_base_planner.models import BaseGeometry, ModulePlacement


def _base(width: int) -> BaseGeometry:
    return BaseGeometry(
        tier=99,
        width=width,
        height=1,
        allowed_cells=frozenset((x, 0) for x in range(width)),
        blocked_cells=frozenset(),
        organics_capacity=999,
        source="incumbent-cut-test",
        verified=True,
    )


def _room(instance_id: str, module_key: str, x: int) -> ModulePlacement:
    spec = MODULE_BY_KEY[module_key]
    return ModulePlacement(instance_id, module_key, x, 0, spec.width, spec.height)


def _one_corridor_rooms() -> tuple[ModulePlacement, ...]:
    return (
        _room("airlock-1", "airlock", 0),
        _room("workshop-1", "workshop", 6),
    )


def test_incumbent_cut_keeps_equality_for_lexicographic_improvement() -> None:
    result = solve_fixed_layout_flow_objective(
        _base(10),
        _one_corridor_rooms(),
        time_limit_s=5.0,
        scaled_objective_upper_bound=9,
    )

    assert result.status == "OPTIMAL"
    assert result.scaled_objective_value == 9
    assert result.primary_objective_optimum_proven is True
    assert result.lexicographic_optimum_proven is True
    assert result.distance_metrics is not None
    assert result.distance_metrics.weighted_score == pytest.approx(0.9)
    assert tuple((module.module_key, module.x, module.y) for module in result.utilities) == (
        ("corridor", 4, 0),
    )


def test_incumbent_cut_proves_packing_cannot_match_better_bound() -> None:
    result = solve_fixed_layout_flow_objective(
        _base(10),
        _one_corridor_rooms(),
        time_limit_s=5.0,
        scaled_objective_upper_bound=8,
    )

    assert result.status == "OBJECTIVE_BOUND_INFEASIBLE"
    assert result.objective_scale == 10
    assert result.distance_metrics is None
    assert result.utilities == ()
    assert result.primary_objective_optimum_proven is False
    assert result.lexicographic_optimum_proven is False
    assert result.time_limit_reached is False


def test_zero_bound_accepts_direct_zero_cost_layout() -> None:
    rooms = (
        _room("airlock-1", "airlock", 0),
        _room("workshop-1", "workshop", 4),
    )
    result = solve_fixed_layout_flow_objective(
        _base(8),
        rooms,
        time_limit_s=5.0,
        scaled_objective_upper_bound=0,
    )

    assert result.status == "OPTIMAL"
    assert result.scaled_objective_value == 0
    assert result.utilities == ()


@pytest.mark.parametrize("bound", [True, -1, 1.5, "9"])
def test_invalid_incumbent_cut_is_rejected(bound) -> None:
    with pytest.raises(ValueError, match="non-negative integer or None"):
        solve_fixed_layout_flow_objective(
            _base(8),
            (
                _room("airlock-1", "airlock", 0),
                _room("workshop-1", "workshop", 4),
            ),
            time_limit_s=5.0,
            scaled_objective_upper_bound=bound,
        )
