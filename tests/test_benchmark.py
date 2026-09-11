from alters_base_planner.benchmark import (
    BENCHMARK_SCHEMA_VERSION,
    REPRESENTATIVE_CASES,
    BenchmarkCase,
    benchmark_markdown,
    benchmark_payload,
    record_from_result,
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
        search_time_s=0.75,
        search_exhausted=False,
        time_limit_reached=True,
        global_objective_optimum_proven=False,
    )


def test_record_from_result_preserves_solver_diagnostics() -> None:
    case = BenchmarkCase(
        name="sample",
        tier=1,
        room_counts={"workshop": 1},
        time_limit_s=2.0,
        max_layout_attempts=10,
        purpose="unit test",
    )

    record = record_from_result(case, _result(), elapsed_wall_s=0.8)

    assert record.name == "sample"
    assert record.elapsed_wall_s == 0.8
    assert record.room_packings_examined == 7
    assert record.connected_candidates_examined == 4
    assert record.fixed_objective_optima_proven == 3
    assert record.manhattan_pruned_count == 2
    assert record.scaled_objective_value == 125
    assert record.global_objective_optimum_proven is False


def test_payload_and_markdown_are_auditable() -> None:
    case = BenchmarkCase(
        name="sample",
        tier=1,
        room_counts={},
        time_limit_s=1.0,
        max_layout_attempts=1,
        purpose="unit test",
    )
    record = record_from_result(case, _result(), elapsed_wall_s=0.8)

    payload = benchmark_payload((case,), (record,))
    markdown = benchmark_markdown(payload)

    assert payload["schema_version"] == BENCHMARK_SCHEMA_VERSION
    assert payload["environment"]["python"]
    assert payload["environment"]["ortools"]
    assert payload["cases"][0]["room_counts"] == {}
    assert payload["results"][0]["scaled_objective_value"] == 125
    assert "| sample | 1 | FEASIBLE |" in markdown
    assert "Runtime values are measurements, not correctness thresholds" in markdown


def test_representative_suite_covers_all_mobile_base_tiers() -> None:
    assert [case.tier for case in REPRESENTATIVE_CASES] == [1, 2, 3, 4]
    assert len({case.name for case in REPRESENTATIVE_CASES}) == len(REPRESENTATIVE_CASES)
    assert all(case.time_limit_s > 0 for case in REPRESENTATIVE_CASES)
    assert all(case.max_layout_attempts > 0 for case in REPRESENTATIVE_CASES)
