import pytest

from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.fixed_flow_objective_solver import solve_fixed_layout_flow_objective
from alters_base_planner.fixed_objective_oracle import solve_fixed_layout_objective
from alters_base_planner.models import BaseGeometry, ModulePlacement


def _base(width: int, height: int) -> BaseGeometry:
    return BaseGeometry(
        tier=99,
        width=width,
        height=height,
        allowed_cells=frozenset((x, y) for y in range(height) for x in range(width)),
        blocked_cells=frozenset(),
        organics_capacity=999,
        source="stage3-flow-objective-test",
        verified=True,
    )


def _room(instance_id: str, module_key: str, x: int, y: int) -> ModulePlacement:
    spec = MODULE_BY_KEY[module_key]
    return ModulePlacement(instance_id, module_key, x, y, spec.width, spec.height)


def _signature(result) -> tuple[tuple[str, int, int], ...]:
    return tuple(sorted((u.module_key, u.x, u.y) for u in result.utilities))


def _assert_matches_reference(base: BaseGeometry, rooms: tuple[ModulePlacement, ...]) -> None:
    reference = solve_fixed_layout_objective(base, rooms, time_limit_s=5.0)
    flow = solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)

    assert flow.status == reference.status
    if reference.status == "INFEASIBLE":
        assert flow.distance_metrics is None
        assert flow.utilities == ()
        assert flow.primary_objective_optimum_proven is False
        assert flow.lexicographic_optimum_proven is False
        return

    assert reference.status == "OPTIMAL"
    assert reference.objective_optimum_proven is True
    assert flow.status == "OPTIMAL"
    assert flow.primary_objective_optimum_proven is True
    assert flow.lexicographic_optimum_proven is True
    assert flow.completed_phase == "Corridor tie-breaker"
    assert flow.time_limit_reached is False
    assert flow.distance_metrics is not None
    assert reference.distance_metrics is not None
    assert flow.distance_metrics.weighted_score == pytest.approx(
        reference.distance_metrics.weighted_score
    )
    assert _signature(flow) == _signature(reference)


def test_pair_flow_matches_reference_for_direct_zero_cost_adjacency() -> None:
    base = _base(8, 1)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 4, 0),
    )

    _assert_matches_reference(base, rooms)

    result = solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)
    assert result.utilities == ()
    assert result.scaled_objective_value == 0
    assert result.objective_scale == 10


def test_pair_flow_matches_reference_for_one_corridor_tie_break() -> None:
    base = _base(10, 1)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 6, 0),
    )

    _assert_matches_reference(base, rooms)

    result = solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)
    assert _signature(result) == (("corridor", 4, 0),)
    assert result.scaled_objective_value == 9
    assert result.objective_scale == 10


def test_pair_flow_matches_reference_for_two_corridor_route() -> None:
    base = _base(12, 1)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 8, 0),
    )

    _assert_matches_reference(base, rooms)

    result = solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)
    assert _signature(result) == (("corridor", 4, 0), ("corridor", 6, 0))
    assert result.scaled_objective_value == 18


def test_pair_flow_matches_reference_for_vertical_elevator_chain() -> None:
    base = _base(6, 2)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 0, 1),
    )

    _assert_matches_reference(base, rooms)

    result = solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)
    assert _signature(result) == (("elevator", 4, 0), ("elevator", 4, 1))
    assert result.scaled_objective_value == 18


def test_pair_flow_charges_intermediate_transit_room_width_exactly() -> None:
    base = _base(12, 1)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 4, 0),
        _room("command-center-1", "command_center", 8, 0),
    )

    _assert_matches_reference(base, rooms)

    result = solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)
    assert result.distance_metrics is not None
    assert result.utilities == ()
    assert result.distance_metrics.pairwise_distances["airlock-1|workshop-1"] == 0
    assert result.distance_metrics.pairwise_distances["workshop-1|command-center-1"] == 0
    assert result.distance_metrics.pairwise_distances["airlock-1|command-center-1"] == 4
    assert result.distance_metrics.weighted_score == pytest.approx(1.4)


def test_pair_flow_does_not_bridge_through_non_transit_rapidium_ark() -> None:
    base = _base(12, 2)
    rooms = (
        _room("airlock-1", "airlock", 0, 1),
        _room("rapidium-ark-1", "rapidium_ark", 4, 0),
        _room("workshop-1", "workshop", 8, 1),
    )

    # The Ark is directly reachable from both sides, but it may not join those sides
    # internally. With no legal external route available, the packing is infeasible.
    _assert_matches_reference(base, rooms)


def test_pair_flow_keeps_zero_weight_terminal_in_hard_network() -> None:
    base = _base(6, 1)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("recycler-1", "recycler", 4, 0),
    )

    # Recycler has zero objective weight but remains a hard-connected installed module.
    _assert_matches_reference(base, rooms)

    result = solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)
    assert result.status == "OPTIMAL"
    assert result.distance_metrics is not None
    assert result.distance_metrics.weighted_score == pytest.approx(0.0)
    assert result.objective_scale == 1
    assert result.scaled_objective_value == 0
    assert result.utilities == ()


def test_pair_flow_matches_reference_infeasibility_without_vertical_space() -> None:
    base = _base(4, 2)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 0, 1),
    )

    _assert_matches_reference(base, rooms)


def test_pair_flow_zero_budget_reports_time_limit_without_false_proof() -> None:
    base = _base(8, 1)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 4, 0),
    )

    result = solve_fixed_layout_flow_objective(base, rooms, time_limit_s=0.0)

    assert result.status == "TIME_LIMIT"
    assert result.time_limit_reached is True
    assert result.primary_objective_optimum_proven is False
    assert result.lexicographic_optimum_proven is False
