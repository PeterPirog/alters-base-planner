from itertools import product

import pytest
from ortools.sat.python import cp_model

import alters_base_planner.engine as engine_module
from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.config import PlanRequest
from alters_base_planner.engine import solve_plan
from alters_base_planner.fixed_flow_objective_solver import (
    FixedFlowObjectiveResult,
    _add_source_aggregated_flow_objective,
    _Arc,
    _SourceCommodity,
    _SourceFlowBuildResult,
    solve_fixed_layout_flow_objective,
)
from alters_base_planner.models import BaseGeometry, ModulePlacement
from alters_base_planner.objective import build_scaled_objective


def _base(width: int, height: int = 1) -> BaseGeometry:
    return BaseGeometry(
        tier=99,
        width=width,
        height=height,
        allowed_cells=frozenset((x, y) for y in range(height) for x in range(width)),
        blocked_cells=frozenset(),
        organics_capacity=999,
        source="distance-cap-pruning-test",
        verified=True,
    )


def _room(instance_id: str, module_key: str, x: int, y: int = 0) -> ModulePlacement:
    spec = MODULE_BY_KEY[module_key]
    return ModulePlacement(instance_id, module_key, x, y, spec.width, spec.height)


def test_pair_caps_are_exhaustively_necessary_under_bound() -> None:
    coefficients = (1, 2, 3)
    lower_bounds = (0, 1, 2)
    relaxed_lower_bound = sum(
        c * lower for c, lower in zip(coefficients, lower_bounds, strict=True)
    )
    for slack in (0, 1, 2, 5, 17):
        bound = relaxed_lower_bound + slack
        caps = tuple(
            lower + slack // coefficient
            for lower, coefficient in zip(lower_bounds, coefficients, strict=True)
        )
        max_distance = max(caps) + 2
        for distances in product(range(max_distance + 1), repeat=len(coefficients)):
            respects_lower_bounds = all(
                d >= lower for d, lower in zip(distances, lower_bounds, strict=True)
            )
            satisfies_bound = (
                sum(c * d for c, d in zip(coefficients, distances, strict=True)) <= bound
            )
            if respects_lower_bounds and satisfies_bound:
                assert all(d <= cap for d, cap in zip(distances, caps, strict=True)), (
                    coefficients,
                    lower_bounds,
                    bound,
                    distances,
                )


def test_bound_below_relaxed_lower_bound_is_exhaustively_infeasible() -> None:
    coefficients = (1, 2, 3)
    lower_bounds = (1, 1, 2)
    relaxed_lower_bound = sum(
        c * lower for c, lower in zip(coefficients, lower_bounds, strict=True)
    )
    assert relaxed_lower_bound > 0
    for bound in range(relaxed_lower_bound):
        feasible_exists = any(
            all(d >= lower for d, lower in zip(distances, lower_bounds, strict=True))
            and sum(c * d for c, d in zip(coefficients, distances, strict=True)) <= bound
            for distances in product(range(30), repeat=len(coefficients))
        )
        assert not feasible_exists


def _arc(arc_id: str, source: str, target: str, cost: int) -> _Arc:
    return _Arc(arc_id=arc_id, source=source, target=target, cost=cost)


def _build_single_commodity(
    arcs: tuple[_Arc, ...],
    nodes: tuple[str, ...],
    *,
    targets: tuple[tuple[str, int], ...],
    bound: int | None,
) -> tuple[cp_model.CpModel, _SourceFlowBuildResult]:
    room_nodes = {node: (node,) for node in nodes}
    commodity = _SourceCommodity("s", targets, sum(c for _, c in targets))
    model = cp_model.CpModel()
    build = _add_source_aggregated_flow_objective(
        model,
        nodes=nodes,
        room_nodes=room_nodes,
        arcs=arcs,
        commodities=(commodity,),
        scaled_objective_upper_bound=bound,
    )
    return model, build


def _flow_variable_names(model: cp_model.CpModel) -> set[str]:
    return {
        variable.name
        for variable in model.Proto().variables
        if variable.name.startswith("source_flow__")
    }


def test_bounded_builder_keeps_shortest_exact_cap_and_drops_over_cap() -> None:
    # s->t cost 1 is the shortest route; s->a->t totals exactly the cap 3; s->b->t totals 4.
    arcs = (
        _arc("direct", "s", "t", 1),
        _arc("to_a", "s", "a", 1),
        _arc("a_to_t", "a", "t", 2),
        _arc("to_b", "s", "b", 1),
        _arc("b_to_t", "b", "t", 3),
    )
    nodes = ("s", "t", "a", "b")
    targets = (("t", 1),)

    unbounded_model, unbounded_build = _build_single_commodity(
        arcs, nodes, targets=targets, bound=None
    )
    assert unbounded_build.incumbent_distance_cap_pruning_used is False
    assert unbounded_build.relaxed_primary_lower_bound is None
    assert unbounded_build.flow_variables_before_cap == 0
    assert unbounded_build.flow_variable_count == len(arcs)
    assert unbounded_build.incumbent_cap_pruned_flow_variables == 0
    unbounded = cp_model.CpSolver()
    unbounded_model.minimize(unbounded_build.primary_expr)
    assert unbounded.solve(unbounded_model) == cp_model.OPTIMAL
    assert unbounded.value(unbounded_build.primary_expr) == 1

    # LB = 1; B = 3 -> slack 2 -> cap = 1 + 2 = 3.
    model, build = _build_single_commodity(arcs, nodes, targets=targets, bound=3)

    assert build.incumbent_distance_cap_pruning_used is True
    assert build.relaxed_primary_lower_bound == 1
    assert build.capped_pair_count == 1
    assert build.flow_variables_before_cap == len(arcs)
    assert build.flow_variable_count == 3
    assert build.incumbent_cap_pruned_flow_variables == 2
    assert build.relaxation_proved_bound_infeasible is False
    names = _flow_variable_names(model)
    assert names == {
        "source_flow__s__direct",
        "source_flow__s__to_a",
        "source_flow__s__a_to_t",
    }
    solver = cp_model.CpSolver()
    model.minimize(build.primary_expr)
    assert solver.solve(model) == cp_model.OPTIMAL
    assert solver.value(build.primary_expr) == 1


def test_union_pruning_keeps_arc_that_only_helps_second_target() -> None:
    # Targets A (coefficient 1) and B (coefficient 1); supply 2.
    # Relaxed distances: l_sa = 1 + 2 = 3 (via p), l_sb = 1 + 1 = 2 (via p).
    # LB = 5; B = 5 -> slack 0 -> cap_a = 3, cap_b = 2.
    # p->b (1+1=2) violates cap_a (1+1+2=4 > 3) but satisfies cap_b exactly.
    # s->a direct cost 9 is above every cap and must be pruned.
    arcs = (
        _arc("s_p", "s", "p", 1),
        _arc("p_a", "p", "a", 2),
        _arc("p_b", "p", "b", 1),
        _arc("s_a_direct", "s", "a", 9),
    )
    nodes = ("s", "p", "a", "b")
    targets = (("a", 1), ("b", 1))

    model, build = _build_single_commodity(arcs, nodes, targets=targets, bound=5)

    assert build.incumbent_distance_cap_pruning_used is True
    assert build.relaxed_primary_lower_bound == 5
    assert build.capped_pair_count == 2
    assert build.flow_variables_before_cap == len(arcs)
    assert build.flow_variable_count == 3
    assert build.incumbent_cap_pruned_flow_variables == 1
    names = _flow_variable_names(model)
    assert "source_flow__s__p_b" in names
    assert "source_flow__s__s_a_direct" not in names

    solver = cp_model.CpSolver()
    model.minimize(build.primary_expr)
    assert solver.solve(model) == cp_model.OPTIMAL
    assert solver.value(build.primary_expr) == 5


def test_target_as_transit_remains_exact_under_equal_bound() -> None:
    base = _base(12)
    rooms = (
        _room("airlock-1", "airlock", 0),
        _room("workshop-1", "workshop", 4),
        _room("command-center-1", "command_center", 8),
    )
    unbounded = solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)
    assert unbounded.status == "OPTIMAL"
    assert unbounded.scaled_objective_value is not None
    assert unbounded.distance_metrics is not None

    bounded = solve_fixed_layout_flow_objective(
        base,
        rooms,
        time_limit_s=5.0,
        scaled_objective_upper_bound=unbounded.scaled_objective_value,
    )

    assert bounded.status == "OPTIMAL"
    assert bounded.scaled_objective_value == unbounded.scaled_objective_value
    assert bounded.distance_metrics is not None
    assert bounded.distance_metrics.weighted_score == pytest.approx(
        unbounded.distance_metrics.weighted_score
    )
    assert bounded.diagnostics.incumbent_distance_cap_pruning_used is True
    assert bounded.diagnostics.objective_bound_relaxation_pruned is False
    assert bounded.diagnostics.incumbent_distance_cap_pair_count == 3
    assert bounded.diagnostics.source_flow_variables_after_incumbent_cap > 0
    # The transit target keeps carrying flow: pruning may not delete its through-arc.
    assert (
        bounded.diagnostics.source_flow_variables_after_incumbent_cap
        <= bounded.diagnostics.source_flow_variables_before_incumbent_cap
    )


def test_bound_equality_keeps_exact_optimum_and_lexicographic_tuple() -> None:
    base = _base(10)
    rooms = (
        _room("airlock-1", "airlock", 0),
        _room("workshop-1", "workshop", 6),
    )
    unbounded = solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)
    assert unbounded.status == "OPTIMAL"
    assert unbounded.scaled_objective_value == 9

    bounded = solve_fixed_layout_flow_objective(
        base,
        rooms,
        time_limit_s=5.0,
        scaled_objective_upper_bound=9,
    )

    assert bounded.status == "OPTIMAL"
    assert bounded.scaled_objective_value == unbounded.scaled_objective_value
    assert bounded.primary_objective_optimum_proven is True
    assert bounded.lexicographic_optimum_proven is True
    assert tuple((m.module_key, m.x, m.y) for m in bounded.utilities) == tuple(
        (m.module_key, m.x, m.y) for m in unbounded.utilities
    )
    assert bounded.diagnostics.incumbent_distance_cap_pruning_used is True
    assert bounded.diagnostics.relaxed_graph_primary_lower_bound == 9


def test_too_tight_bound_proves_relaxation_domination_without_cp_sat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _base(10)
    rooms = (
        _room("airlock-1", "airlock", 0),
        _room("workshop-1", "workshop", 6),
    )

    def forbidden_solve(self, model):  # pragma: no cover - must never run
        raise AssertionError("CP-SAT solve must not run when the relaxation proves domination")

    monkeypatch.setattr(cp_model.CpSolver, "solve", forbidden_solve)
    result = solve_fixed_layout_flow_objective(
        base,
        rooms,
        time_limit_s=5.0,
        scaled_objective_upper_bound=8,
    )

    assert result.status == "OBJECTIVE_BOUND_INFEASIBLE"
    assert result.distance_metrics is None
    assert result.utilities == ()
    assert result.time_limit_reached is False
    diagnostics = result.diagnostics
    assert diagnostics.objective_bound_relaxation_pruned is True
    assert diagnostics.incumbent_primary_bound == 8
    assert diagnostics.relaxed_graph_primary_lower_bound == 9
    assert diagnostics.incumbent_distance_cap_pruning_used is False
    assert diagnostics.source_flow_variable_count == 0
    assert diagnostics.source_flow_variables_before_incumbent_cap > 0
    assert (
        diagnostics.incumbent_cap_pruned_flow_variables
        == diagnostics.source_flow_variables_before_incumbent_cap
    )


def test_loose_bound_preserves_exact_result_and_may_prune_little() -> None:
    base = _base(12)
    rooms = (
        _room("airlock-1", "airlock", 0),
        _room("workshop-1", "workshop", 4),
        _room("command-center-1", "command_center", 8),
    )
    unbounded = solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)
    assert unbounded.status == "OPTIMAL"
    assert unbounded.scaled_objective_value is not None

    loose = solve_fixed_layout_flow_objective(
        base,
        rooms,
        time_limit_s=5.0,
        scaled_objective_upper_bound=unbounded.scaled_objective_value + 10**6,
    )

    assert loose.status == "OPTIMAL"
    assert loose.scaled_objective_value == unbounded.scaled_objective_value
    assert loose.diagnostics.incumbent_distance_cap_pruning_used is True
    assert loose.diagnostics.objective_bound_relaxation_pruned is False
    assert tuple((m.module_key, m.x, m.y) for m in loose.utilities) == tuple(
        (m.module_key, m.x, m.y) for m in unbounded.utilities
    )


def test_custom_weights_use_exact_integer_coefficients_in_caps() -> None:
    base = _base(10)
    rooms = (
        _room("airlock-1", "airlock", 0),
        _room("workshop-1", "workshop", 6),
    )
    usage_weights = {"airlock": 1.0, "workshop": 0.5}
    objective = build_scaled_objective(rooms, usage_weights)
    assert len(objective.pairs) == 1
    coefficient = objective.pairs[0].coefficient

    unbounded = solve_fixed_layout_flow_objective(
        base, rooms, time_limit_s=5.0, usage_weights=usage_weights
    )
    assert unbounded.status == "OPTIMAL"
    assert unbounded.scaled_objective_value == coefficient

    bounded = solve_fixed_layout_flow_objective(
        base,
        rooms,
        time_limit_s=5.0,
        usage_weights=usage_weights,
        scaled_objective_upper_bound=coefficient,
    )

    assert bounded.status == "OPTIMAL"
    assert bounded.scaled_objective_value == coefficient
    assert bounded.diagnostics.relaxed_graph_primary_lower_bound == coefficient
    assert bounded.diagnostics.incumbent_distance_cap_pruning_used is True


def test_zero_weight_rooms_stay_hard_connected_under_caps() -> None:
    base = _base(6)
    rooms = (
        _room("airlock-1", "airlock", 0),
        _room("recycler-1", "recycler", 4),
    )
    usage_weights = {"airlock": 1.0, "recycler": 0.0}
    unbounded = solve_fixed_layout_flow_objective(
        base, rooms, time_limit_s=5.0, usage_weights=usage_weights
    )
    assert unbounded.status == "OPTIMAL"
    assert unbounded.scaled_objective_value == 0

    bounded = solve_fixed_layout_flow_objective(
        base,
        rooms,
        time_limit_s=5.0,
        usage_weights=usage_weights,
        scaled_objective_upper_bound=0,
    )

    assert bounded.status == "OPTIMAL"
    assert bounded.scaled_objective_value == 0
    assert bounded.distance_metrics is not None
    assert bounded.distance_metrics.pairwise_distances == {}
    assert bounded.diagnostics.incumbent_distance_cap_pair_count == 0


def test_unbounded_subproblem_skips_cap_computation() -> None:
    base = _base(10)
    rooms = (
        _room("airlock-1", "airlock", 0),
        _room("workshop-1", "workshop", 6),
    )
    result = solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)

    assert result.status == "OPTIMAL"
    diagnostics = result.diagnostics
    assert diagnostics.incumbent_distance_cap_pruning_used is False
    assert diagnostics.relaxed_graph_primary_lower_bound is None
    assert diagnostics.incumbent_primary_bound is None
    assert diagnostics.incumbent_distance_cap_pair_count == 0
    assert diagnostics.source_flow_variables_before_incumbent_cap == 0
    assert diagnostics.source_flow_variables_after_incumbent_cap == 0
    assert diagnostics.incumbent_cap_pruned_flow_variables == 0
    assert diagnostics.objective_bound_relaxation_pruned is False


def test_production_engine_activates_pruning_on_later_packings() -> None:
    request = PlanRequest(
        tier=1,
        room_counts={"workshop": 1, "recycler": 1},
        time_limit_s=30.0,
        max_layout_attempts=12,
    )

    engine_bounds: list[int | None] = []
    activation_used: list[bool] = []
    activation_results: list[FixedFlowObjectiveResult] = []
    real_solve = engine_module.solve_fixed_layout_flow_objective

    def loose_later_bound_solve(*args, **kwargs):
        engine_bounds.append(kwargs.get("scaled_objective_upper_bound"))
        if len(engine_bounds) > 1:
            # Deterministic test seam: every later packing receives a valid loose exact bound,
            # so the union distance-cap pruning runs inside the production engine path.
            kwargs["scaled_objective_upper_bound"] = 10**9
        result = real_solve(*args, **kwargs)
        activation_used.append(result.diagnostics.incumbent_distance_cap_pruning_used)
        activation_results.append(result)
        return result

    engine_module.solve_fixed_layout_flow_objective = loose_later_bound_solve
    try:
        activation = solve_plan(request)
    finally:
        engine_module.solve_fixed_layout_flow_objective = real_solve

    assert len(activation_results) >= 2
    assert engine_bounds[0] is None
    assert any(bound is not None for bound in engine_bounds[1:])
    assert all(activation_used[1:])
    best_activation_f = min(
        result.scaled_objective_value
        for result in activation_results
        if result.scaled_objective_value is not None
    )
    assert activation.scaled_objective_value == best_activation_f
    assert activation.status in {"FEASIBLE", "OPTIMAL"}
    assert activation.fixed_incumbent_distance_cap_pruning_used is True
    assert activation.min_fixed_incumbent_primary_bound is not None
    assert activation.max_fixed_incumbent_distance_cap_pairs > 0
    assert (
        activation.max_fixed_source_flow_variables_after_incumbent_cap
        <= activation.max_fixed_source_flow_variables_before_incumbent_cap
    )