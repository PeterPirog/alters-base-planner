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


def test_fixed_diagnostics_aggregate_preserves_source_flow_maxima_and_totals() -> None:
    aggregate = _FixedDiagnosticsAggregate()
    aggregate.observe(
        FixedFlowObjectiveDiagnostics(
            graph_node_count=30,
            graph_arc_count=80,
            objective_pair_count=10,
            source_commodity_count=4,
            source_flow_variable_count=400,
            source_flow_full_variable_count=800,
            endpoint_distribution_variable_count=0,
            condition_capacity_bucket_count=11,
            condition_capacity_literal_count=6,
            flow_capacity_constraint_count=700,
            flow_balance_constraint_count=800,
            cp_sat_variable_count=900,
            cp_sat_constraint_count=1200,
            model_build_time_s=0.1,
            cp_sat_solve_time_s=0.4,
            total_time_s=0.6,
            hard_model_build_time_s=0.04,
            path_graph_build_time_s=0.01,
            objective_definition_time_s=0.01,
            flow_model_build_time_s=0.03,
            lexicographic_finalize_time_s=0.01,
        )
    )
    aggregate.observe(
        FixedFlowObjectiveDiagnostics(
            graph_node_count=35,
            graph_arc_count=75,
            objective_pair_count=12,
            source_commodity_count=5,
            source_flow_variable_count=500,
            source_flow_full_variable_count=750,
            endpoint_distribution_variable_count=0,
            condition_capacity_bucket_count=9,
            condition_capacity_literal_count=5,
            flow_capacity_constraint_count=650,
            flow_balance_constraint_count=900,
            cp_sat_variable_count=1000,
            cp_sat_constraint_count=1100,
            model_build_time_s=0.2,
            cp_sat_solve_time_s=0.5,
            total_time_s=0.8,
            hard_model_build_time_s=0.07,
            path_graph_build_time_s=0.02,
            objective_definition_time_s=0.01,
            flow_model_build_time_s=0.08,
            lexicographic_finalize_time_s=0.02,
        )
    )

    result = PlanResult(status="TIME_LIMIT", base=_base())
    aggregate.apply(result)

    assert result.fixed_subproblem_count == 2
    assert result.max_fixed_graph_nodes == 35
    assert result.max_fixed_graph_arcs == 80
    assert result.max_fixed_objective_pairs == 12
    assert result.fixed_flow_formulation == "source_aggregated_weighted_flow"
    assert result.max_fixed_source_commodities == 5
    assert result.max_fixed_source_flow_variables == 500
    assert result.max_fixed_source_flow_full_variables == 800
    assert result.total_fixed_source_flow_variables == 900
    assert result.total_fixed_source_flow_full_variables == 1550
    assert result.max_fixed_condition_capacity_buckets == 11
    assert result.max_fixed_condition_capacity_literals == 6
    assert result.max_fixed_endpoint_distribution_variables == 0
    assert result.max_fixed_flow_capacity_constraints == 700
    assert result.max_fixed_flow_balance_constraints == 900
    assert result.max_fixed_cp_sat_variables == 1000
    assert result.max_fixed_cp_sat_constraints == 1200
    assert result.fixed_model_build_time_s == pytest.approx(0.3)
    assert result.fixed_cp_sat_solve_time_s == pytest.approx(0.9)
    assert result.fixed_subproblem_time_s == pytest.approx(1.4)
    assert result.fixed_hard_model_build_time_s == pytest.approx(0.11)
    assert result.fixed_path_graph_build_time_s == pytest.approx(0.03)
    assert result.fixed_objective_definition_time_s == pytest.approx(0.02)
    assert result.fixed_source_flow_model_build_time_s == pytest.approx(0.11)
    assert result.fixed_lexicographic_finalize_time_s == pytest.approx(0.03)
