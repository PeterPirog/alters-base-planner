import json

import alters_base_planner.benchmark as benchmark_module
from alters_base_planner.benchmark import (
    BENCHMARK_SCHEMA_VERSION,
    REPRESENTATIVE_CASES,
    BenchmarkCase,
    benchmark_markdown,
    benchmark_payload,
    record_from_result,
    run_case,
    write_report,
)
from alters_base_planner.models import BaseGeometry, PlanResult


def _result() -> PlanResult:
    base = BaseGeometry(
        tier=1,
        width=4,
        height=1,
        allowed_cells=frozenset((x, 0) for x in range(4)),
        blocked_cells=frozenset(),
        organics_capacity=300,
        source="benchmark-test",
        verified=True,
    )
    return PlanResult(
        status="FEASIBLE",
        base=base,
        objective_scale=100,
        scaled_objective_value=125,
        scaled_modified_manhattan_lower_bound=100,
        weighted_distance_score=1.25,
        total_mass=42,
        elevator_module_count=2,
        corridor_count=3,
        attempts=7,
        connected_candidates_examined=4,
        fixed_objective_optima_proven=3,
        manhattan_pruned_count=2,
        incumbent_bound_pruned_count=5,
        search_time_s=0.75,
        search_exhausted=False,
        time_limit_reached=True,
        global_objective_optimum_proven=False,
        fixed_subproblem_count=4,
        max_fixed_graph_nodes=61,
        max_fixed_graph_arcs=120,
        max_fixed_objective_pairs=28,
        max_fixed_cp_sat_variables=3500,
        max_fixed_cp_sat_constraints=6100,
        fixed_model_build_time_s=0.12,
        fixed_cp_sat_solve_time_s=0.51,
        fixed_subproblem_time_s=0.69,
    )


def _case() -> BenchmarkCase:
    return BenchmarkCase(
        name="sample",
        tier=1,
        room_counts={"workshop": 1},
        time_limit_s=2.0,
        max_layout_attempts=10,
        purpose="unit test",
    )


def test_record_from_result_preserves_solver_diagnostics() -> None:
    record = record_from_result(_case(), _result(), elapsed_wall_s=0.8)

    assert record.name == "sample"
    assert record.elapsed_wall_s == 0.8
    assert record.room_packings_examined == 7
    assert record.connected_candidates_examined == 4
    assert record.fixed_objective_optima_proven == 3
    assert record.manhattan_pruned_count == 2
    assert record.incumbent_bound_pruned_count == 5
    assert record.scaled_objective_value == 125
    assert record.global_objective_optimum_proven is False
    assert record.fixed_subproblem_count == 4
    assert record.max_fixed_graph_nodes == 61
    assert record.max_fixed_graph_arcs == 120
    assert record.max_fixed_objective_pairs == 28
    assert record.max_fixed_cp_sat_variables == 3500
    assert record.max_fixed_cp_sat_constraints == 6100
    assert record.fixed_model_build_time_s == 0.12
    assert record.fixed_cp_sat_solve_time_s == 0.51
    assert record.fixed_subproblem_time_s == 0.69


def test_payload_and_markdown_are_auditable() -> None:
    case = _case()
    record = record_from_result(case, _result(), elapsed_wall_s=0.8)

    payload = benchmark_payload((case,), (record,))
    markdown = benchmark_markdown(payload)

    assert payload["schema_version"] == BENCHMARK_SCHEMA_VERSION
    assert BENCHMARK_SCHEMA_VERSION == 3
    assert payload["environment"]["python"]
    assert payload["environment"]["ortools"]
    assert payload["cases"][0]["room_counts"] == {"workshop": 1}
    assert payload["results"][0]["scaled_objective_value"] == 125
    assert payload["results"][0]["incumbent_bound_pruned_count"] == 5
    assert payload["results"][0]["max_fixed_cp_sat_variables"] == 3500
    assert "| sample | 1 | FEASIBLE |" in markdown
    assert "| 2 | 5 | 1.2500 |" in markdown
    assert "## Fixed-packing model diagnostics" in markdown
    assert "| sample | 4 | 61 | 120 | 28 | 3500 | 6100 |" in markdown
    assert "Runtime values are measurements, not correctness thresholds" in markdown


def test_run_case_uses_production_request_contract(monkeypatch) -> None:
    captured = []

    def fake_solve(request):
        captured.append(request)
        return _result()

    monkeypatch.setattr(benchmark_module, "solve_plan", fake_solve)
    record = run_case(_case())

    assert len(captured) == 1
    assert captured[0].tier == 1
    assert captured[0].room_counts == {"workshop": 1}
    assert captured[0].time_limit_s == 2.0
    assert captured[0].max_layout_attempts == 10
    assert record.elapsed_wall_s >= 0


def test_write_report_creates_json_and_markdown(tmp_path) -> None:
    case = _case()
    record = record_from_result(case, _result(), elapsed_wall_s=0.8)
    json_path = tmp_path / "result.json"
    markdown_path = tmp_path / "result.md"

    write_report((case,), [record], json_path=json_path, markdown_path=markdown_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["schema_version"] == BENCHMARK_SCHEMA_VERSION
    assert payload["results"][0]["name"] == "sample"
    assert payload["results"][0]["incumbent_bound_pruned_count"] == 5
    assert payload["results"][0]["fixed_subproblem_count"] == 4
    assert "# The Alters Base Planner benchmark report" in markdown


def test_representative_suite_covers_all_mobile_base_tiers() -> None:
    assert [case.tier for case in REPRESENTATIVE_CASES] == [1, 2, 3, 4]
    assert len({case.name for case in REPRESENTATIVE_CASES}) == len(REPRESENTATIVE_CASES)
    assert all(case.time_limit_s > 0 for case in REPRESENTATIVE_CASES)
    assert all(case.max_layout_attempts > 0 for case in REPRESENTATIVE_CASES)
