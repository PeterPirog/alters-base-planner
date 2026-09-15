from pathlib import Path

import alters_base_planner.release_acceptance as release_module
from alters_base_planner.benchmark import REPRESENTATIVE_CASES
from alters_base_planner.release_acceptance import V1_RELEASE_CASES


def test_v1_release_suite_preserves_representative_requests_with_longer_budgets() -> None:
    assert [case.tier for case in V1_RELEASE_CASES] == [1, 2, 3, 4]
    assert len(V1_RELEASE_CASES) == len(REPRESENTATIVE_CASES)
    assert [case.time_limit_s for case in V1_RELEASE_CASES] == [60.0, 120.0, 180.0, 300.0]
    assert all(case.max_layout_attempts == 10_000 for case in V1_RELEASE_CASES)

    for release_case, representative_case in zip(V1_RELEASE_CASES, REPRESENTATIVE_CASES):
        assert release_case.room_counts == representative_case.room_counts
        assert release_case.time_limit_s > representative_case.time_limit_s
        assert release_case.name == f"v1-{representative_case.name}"
        assert "global optimality is not required" in release_case.purpose


def test_release_acceptance_main_writes_versioned_suite(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run_cases(cases):
        captured["run_cases"] = cases
        return []

    def fake_write_report(cases, records, *, json_path, markdown_path):
        captured["write_cases"] = cases
        captured["records"] = records
        captured["json_path"] = json_path
        captured["markdown_path"] = markdown_path

    monkeypatch.setattr(release_module, "run_cases", fake_run_cases)
    monkeypatch.setattr(release_module, "write_report", fake_write_report)

    json_path = tmp_path / "acceptance.json"
    markdown_path = tmp_path / "acceptance.md"
    status = release_module.main(
        ["--json", str(json_path), "--markdown", str(markdown_path)]
    )

    assert status == 0
    assert captured["run_cases"] == V1_RELEASE_CASES
    assert captured["write_cases"] == V1_RELEASE_CASES
    assert captured["records"] == []
    assert captured["json_path"] == json_path
    assert captured["markdown_path"] == markdown_path
