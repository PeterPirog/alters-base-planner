import pytest
from ortools.sat.python import cp_model

import alters_base_planner.fixed_flow_objective_solver as flow_solver_module
from alters_base_planner.catalog import MODULE_BY_KEY, resolve_usage_weights
from alters_base_planner.distance import evaluate_distances
from alters_base_planner.fixed_flow_objective_solver import solve_fixed_layout_flow_objective
from alters_base_planner.fixed_objective_oracle import solve_fixed_layout_objective
from alters_base_planner.integrated_hard_solver import compile_fixed_layout_hard_model
from alters_base_planner.models import BaseGeometry, ModulePlacement
from alters_base_planner.objective import build_scaled_objective


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


def _assert_hard_feasible_network(
    base: BaseGeometry,
    rooms: tuple[ModulePlacement, ...],
    utilities: tuple[ModulePlacement, ...],
) -> None:
    compiled = compile_fixed_layout_hard_model(base, rooms)
    selected = {(utility.module_key, utility.x, utility.y) for utility in utilities}
    for anchor, variable in compiled.variables.corridor.items():
        compiled.model.add(variable == int(("corridor", *anchor) in selected))
    for anchor, variable in compiled.variables.elevator.items():
        compiled.model.add(variable == int(("elevator", *anchor) in selected))
    assert cp_model.CpSolver().solve(compiled.model) == cp_model.OPTIMAL


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
    assert flow.completed_phase == "lexicographic scalarization"
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


def test_equal_f_networks_choose_mass_then_elevator_then_corridor_order() -> None:
    base = _base(14, 1)
    rooms = (
        _room("airlock-1", "airlock", 2, 0),
        _room("workshop-1", "workshop", 8, 0),
    )
    networks = {
        "preferred": (_room("corridor-1", "corridor", 6, 0),),
        "equal-mass-elevator": (_room("elevator-1", "elevator", 6, 0),),
        "extra-corridor": (
            _room("corridor-1", "corridor", 0, 0),
            _room("corridor-2", "corridor", 6, 0),
        ),
        "extra-elevator": (
            _room("elevator-1", "elevator", 0, 0),
            _room("corridor-1", "corridor", 6, 0),
        ),
    }
    objective = build_scaled_objective(rooms)
    ranks: dict[str, tuple[int, int, int, int]] = {}
    for name, utilities in networks.items():
        _assert_hard_feasible_network(base, rooms, utilities)
        metrics = evaluate_distances(list(rooms), list(utilities))
        utility_mass = sum(MODULE_BY_KEY[utility.module_key].mass for utility in utilities)
        ranks[name] = (
            objective.scaled_score(metrics.pairwise_distances),
            utility_mass,
            metrics.elevator_module_count,
            metrics.corridor_count,
        )

    assert ranks == {
        "preferred": (9, 2, 0, 1),
        "equal-mass-elevator": (9, 2, 1, 0),
        "extra-corridor": (9, 4, 0, 2),
        "extra-elevator": (9, 4, 1, 1),
    }
    assert ranks["preferred"] < ranks["equal-mass-elevator"] < ranks["extra-corridor"]
    assert ranks["extra-corridor"] < ranks["extra-elevator"]

    # Corridor and Elevator currently both have mass 2. Therefore equal utility mass plus equal
    # Elevator count algebraically fixes Corridor count; the exhaustive scalarization test covers
    # the final component independently while this physical regression exercises every reachable
    # equal-F tie level and the original excessive-Elevator failure mode.
    assert MODULE_BY_KEY["corridor"].mass == MODULE_BY_KEY["elevator"].mass == 2

    result = solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)
    assert result.status == "OPTIMAL"
    assert _signature(result) == (("corridor", 6, 0),)
    assert result.scaled_objective_value == 9


def test_production_path_recovers_scalar_above_double_exact_integer_range(monkeypatch) -> None:
    base = _base(10, 1)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 6, 0),
    )
    weights = (1 << 50, 1 << 30, 1 << 20, 1)
    monkeypatch.setattr(
        flow_solver_module,
        "lexicographic_dominance_weights",
        lambda **_kwargs: weights,
    )

    result = solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)
    expected = weights[0] * 9 + weights[1] * 2 + weights[3]

    assert result.status == "OPTIMAL"
    assert expected > 1 << 53
    assert result.lexicographic_objective_value == expected
    assert result.diagnostics.incumbent_scalar_value == expected
    assert result.diagnostics.combined_objective_upper_bound <= (1 << 63) - 1


def test_production_path_rejects_combined_objective_overflow_before_solve(monkeypatch) -> None:
    base = _base(10, 1)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 6, 0),
    )
    solve_called = False

    def unexpected_solve(*args, **kwargs):
        nonlocal solve_called
        solve_called = True
        raise AssertionError("CP-SAT solve must not run after overflow detection")

    monkeypatch.setattr(
        flow_solver_module,
        "lexicographic_dominance_weights",
        lambda **_kwargs: (1 << 63, 1, 1, 1),
    )
    monkeypatch.setattr(flow_solver_module, "_solve_phase", unexpected_solve)

    with pytest.raises(ValueError, match="signed 64-bit") as error:
        solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)
    assert "combined_objective_upper_bound=" in str(error.value)
    assert solve_called is False


def test_primary_pair_flow_expression_is_cross_checked_against_dijkstra(monkeypatch) -> None:
    base = _base(10, 1)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 6, 0),
    )
    real_build = flow_solver_module.build_scaled_objective

    def mismatching_objective(fixed_rooms):
        objective = real_build(fixed_rooms)

        class MismatchingObjective:
            scale = objective.scale
            pairs = objective.pairs

            @staticmethod
            def scaled_score(pairwise_distances):
                return objective.scaled_score(pairwise_distances) + 1

        return MismatchingObjective()

    monkeypatch.setattr(flow_solver_module, "build_scaled_objective", mismatching_objective)
    with pytest.raises(AssertionError, match="primary objective disagrees.*Dijkstra"):
        solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)


def test_custom_weights_match_pair_flow_and_independent_dijkstra_objectives() -> None:
    base = _base(10, 1)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 6, 0),
    )
    usage_weights = resolve_usage_weights({"airlock": 0.75, "workshop": 0.2})

    result = solve_fixed_layout_flow_objective(
        base,
        rooms,
        time_limit_s=5.0,
        usage_weights=usage_weights,
    )
    reference = solve_fixed_layout_objective(
        base,
        rooms,
        time_limit_s=5.0,
        usage_weights=usage_weights,
    )

    assert result.status == "OPTIMAL"
    assert result.objective_scale == 20
    assert result.scaled_objective_value == 3
    assert result.distance_metrics is not None
    assert result.distance_metrics.weighted_score == pytest.approx(0.15)
    assert result.distance_metrics.weighted_manhattan_lower_bound == pytest.approx(0.15)
    assert reference.status == "OPTIMAL"
    assert reference.distance_metrics is not None
    assert result.distance_metrics.weighted_score == reference.distance_metrics.weighted_score


def test_custom_zero_weight_keeps_room_hard_connectivity_in_fixed_solver() -> None:
    base = _base(10, 1)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 6, 0),
    )
    usage_weights = resolve_usage_weights({"workshop": 0.0})

    result = solve_fixed_layout_flow_objective(
        base,
        rooms,
        time_limit_s=5.0,
        usage_weights=usage_weights,
    )

    assert result.status == "OPTIMAL"
    assert result.scaled_objective_value == 0
    assert _signature(result) == (("corridor", 4, 0),)


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


def test_pair_flow_reports_primary_model_size_and_timings() -> None:
    base = _base(10, 1)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 6, 0),
    )

    result = solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)
    diagnostics = result.diagnostics

    assert diagnostics.graph_node_count > 0
    assert diagnostics.graph_arc_count > 0
    assert diagnostics.objective_pair_count == 1
    assert diagnostics.cp_sat_variable_count > 0
    assert diagnostics.cp_sat_constraint_count > 0
    assert diagnostics.lexicographic_scalarization_used is True
    assert result.scaled_objective_value is not None
    assert diagnostics.primary_objective_upper_bound >= result.scaled_objective_value
    assert diagnostics.combined_objective_upper_bound == (
        diagnostics.weight_f * diagnostics.primary_objective_upper_bound
        + diagnostics.weight_mass * diagnostics.mass_bound
        + diagnostics.weight_elevator * diagnostics.elevator_bound
        + diagnostics.weight_corridor * diagnostics.corridor_bound
    )
    assert diagnostics.incumbent_scalar_value == result.lexicographic_objective_value
    assert diagnostics.model_build_time_s >= 0
    assert diagnostics.cp_sat_solve_time_s >= 0
    assert diagnostics.total_time_s >= diagnostics.model_build_time_s


def test_pair_flow_budget_includes_model_construction(monkeypatch) -> None:
    base = _base(8, 1)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 4, 0),
    )
    clock = {"now": 0.0}
    real_compile = flow_solver_module.compile_fixed_layout_hard_model

    def delayed_compile(*args, **kwargs):
        compiled = real_compile(*args, **kwargs)
        clock["now"] = 2.0
        return compiled

    monkeypatch.setattr(flow_solver_module, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        flow_solver_module,
        "compile_fixed_layout_hard_model",
        delayed_compile,
    )

    result = flow_solver_module.solve_fixed_layout_flow_objective(
        base,
        rooms,
        time_limit_s=1.0,
    )

    assert result.status == "TIME_LIMIT"
    assert result.time_limit_reached is True
    assert result.primary_objective_optimum_proven is False
    assert result.lexicographic_optimum_proven is False
    assert result.diagnostics.model_build_time_s == pytest.approx(2.0)
    assert result.diagnostics.cp_sat_solve_time_s == pytest.approx(0.0)
