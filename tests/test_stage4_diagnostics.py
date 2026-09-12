import pytest

from alters_base_planner.engine import _FixedDiagnosticsAggregate
from alters_base_planner.fixed_flow_objective_solver import FixedFlowObjectiveDiagnostics
from alters_base_planner.models import BaseGeometry, PlanResult


def _base() -> BaseGeometry:
    return BaseGeometry(
        tier=99,
        width=2,
        height=1,
        allowed_cells=frozenset({(0, 0), (1, 0)}),
        blocked_cells=frozenset(),
        organics_capacity=999,
        source="stage4-diagnostics-test",
        verified=True,
    )


def test_fixed_diagnostics_aggregate_preserves_pair_flow_maxima_and_totals() -> None:
    aggregate = _FixedDiagnosticsAggregate()
    aggregate.observe(
        FixedFlowObjectiveDiagnostics(
            graph_node_count=30,
            graph_arc_count=80,
            objective_pair_count=10,
            pair_flow_variable_count=400,
            pair_flow_full_variable_count=800,
            cp_sat_variable_count=900,
            cp_sat_constraint_count=1200,
            model_build_time_s=0.1,
            cp_sat_solve_time_s=0.4,
            total_time_s=0.6,
        )
    )
    aggregate.observe(
        FixedFlowObjectiveDiagnostics(
            graph_node_count=35,
            graph_arc_count=75,
            objective_pair_count=12,
            pair_flow_variable_count=500,
            pair_flow_full_variable_count=750,
            cp_sat_variable_count=1000,
            cp_sat_constraint_count=1100,
            model_build_time_s=0.2,
            cp_sat_solve_time_s=0.5,
            total_time_s=0.8,
        )
    )

    result = PlanResult(status="TIME_LIMIT", base=_base())
    aggregate.apply(result)

    assert result.fixed_subproblem_count == 2
    assert result.max_fixed_graph_nodes == 35
    assert result.max_fixed_graph_arcs == 80
    assert result.max_fixed_objective_pairs == 12
    assert result.max_fixed_pair_flow_variables == 500
    assert result.max_fixed_pair_flow_full_variables == 800
    assert result.total_fixed_pair_flow_variables == 900
    assert result.total_fixed_pair_flow_full_variables == 1550
    assert result.max_fixed_cp_sat_variables == 1000
    assert result.max_fixed_cp_sat_constraints == 1200
    assert result.fixed_model_build_time_s == pytest.approx(0.3)
    assert result.fixed_cp_sat_solve_time_s == pytest.approx(0.9)
    assert result.fixed_subproblem_time_s == pytest.approx(1.4)
