import json
import platform
import subprocess
import sys
from datetime import datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from zipfile import ZipFile

import pytest

from alters_base_planner.base import builtin_base
from alters_base_planner.models import ModulePlacement, PlanResult
from alters_base_planner.serialization import result_payload

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "create_example_evidence.py"
PREFIX = "example-plan-result/"


@pytest.fixture
def example_files(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REF", "refs/pull/42/merge")
    monkeypatch.delenv("OPTIMIZER_EXIT_CODE", raising=False)
    config = tmp_path / "config" / "example-plan.json"
    config.parent.mkdir()
    config.write_bytes((SCRIPT.parents[1] / "config" / "example-plan.json").read_bytes())
    result = PlanResult(
        status="FEASIBLE", base=builtin_base(1),
        modules=[ModulePlacement("airlock-1", "airlock", 0, 0, 4, 1)],
        room_usage_weights={"airlock-1": 1.0},
        objective_value=1.25, weighted_distance_score=1.25,
        objective_scale=100, scaled_objective_value=125,
        scaled_modified_manhattan_lower_bound=100, modified_manhattan_lower_bound=1.0,
        total_mass=42, elevator_module_count=2, corridor_count=3,
        travel_feasible_at_full_tank=True, global_objective_optimum_proven=False,
        search_time_s=0.75, attempts=7, connected_candidates_examined=4,
        fixed_objective_optima_proven=3, manhattan_pruned_count=2,
        incumbent_bound_pruned_count=1, time_limit_reached=True, search_exhausted=False,
        fixed_subproblem_count=4, max_fixed_graph_nodes=61, max_fixed_graph_arcs=120,
        max_fixed_objective_pairs=28, max_fixed_cp_sat_variables=3500,
        max_fixed_cp_sat_constraints=6100, fixed_lexicographic_scalarization_used=True,
        max_fixed_primary_objective_upper_bound=12000,
        max_fixed_combined_objective_upper_bound=987654321,
        max_fixed_lexicographic_weight_f=7000, max_fixed_lexicographic_weight_mass=300,
        max_fixed_lexicographic_weight_elevator=20,
        max_fixed_lexicographic_weight_corridor=1,
        max_fixed_lexicographic_corridor_bound=19,
        max_fixed_lexicographic_elevator_bound=17,
        max_fixed_lexicographic_mass_bound=72, max_fixed_incumbent_scalar_value=63042,
        fixed_model_build_time_s=0.12,
        fixed_cp_sat_solve_time_s=0.51, fixed_subproblem_time_s=0.69,
        fixed_hard_model_build_time_s=0.04,
        fixed_path_graph_build_time_s=0.01,
        fixed_objective_definition_time_s=0.01,
        fixed_source_flow_model_build_time_s=0.05,
        fixed_lexicographic_finalize_time_s=0.01,
        max_fixed_source_commodities=7,
        max_fixed_source_flow_variables=2100, max_fixed_source_flow_full_variables=3360,
        total_fixed_source_flow_variables=7200,
        total_fixed_source_flow_full_variables=12000,
        max_fixed_shared_activation_gates=11,
        max_fixed_endpoint_distribution_variables=0,
        max_fixed_flow_capacity_constraints=2800,
        max_fixed_flow_balance_constraints=1600,
    )
    payload = result_payload(result)
    (tmp_path / "layout.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "layout.png").write_bytes(b"png fixture")
    (tmp_path / "layout.svg").write_text("<svg/>", encoding="utf-8")
    return tmp_path, payload


def run_helper(root, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=root,
        text=True, capture_output=True, check=False,
    )


def read_metadata(root):
    return json.loads((root / PREFIX / "run-metadata.json").read_text(encoding="utf-8"))


def test_feasible_package_copies_outputs_metadata_and_exact_zip_members(example_files):
    root, _ = example_files
    run = run_helper(root, "--optimizer-exit-code", "0")
    assert run.returncode == 0, run.stderr
    metadata = read_metadata(root)
    assert metadata["schema_version"] == 2
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=SCRIPT.parents[1], text=True
    ).strip()
    assert metadata["git_commit"] == commit
    assert metadata["git_ref"] == "refs/pull/42/merge"
    assert datetime.fromisoformat(metadata["timestamp_utc"]).utcoffset() == timedelta(0)
    assert metadata["python_version"] == platform.python_version()
    assert metadata["ortools_version"] == version("ortools")
    assert metadata["planner_version"] == version("alters-base-planner")
    assert metadata["input_configuration_path"] == "config/example-plan.json"
    assert metadata["optimizer_exit_code"] == 0
    assert metadata["base_tier"] == 1
    assert metadata["status"] == "FEASIBLE"
    assert metadata["structural_feasible"] is True
    assert metadata["journey_feasible"] is True
    assert metadata["layout_parse_error"] is None
    assert "modules" not in metadata
    assert "pairwise_distances" not in metadata

    files = {
        "input/example-plan.json": root / "config/example-plan.json",
        **{f"output/{name}": root / name for name in ("layout.json", "layout.png", "layout.svg")},
        "run-metadata.json": root / PREFIX / "run-metadata.json",
    }
    archives = list(root.glob("example-plan-*.zip"))
    assert len(archives) == 1
    assert commit.startswith(archives[0].stem.removeprefix("example-plan-"))
    with ZipFile(archives[0]) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {PREFIX + name for name in files}
        for name, source in files.items():
            assert archive.read(PREFIX + name) == source.read_bytes()
            assert (root / PREFIX / name).read_bytes() == source.read_bytes()

    # A best-known incumbent without global proof passes; no quality/timing gate.
    gate = run_helper(root, "--verify")
    assert gate.returncode == 0, gate.stderr


def test_diagnostics_are_extracted_from_canonical_serialization(example_files):
    root, payload = example_files
    assert run_helper(root, "--optimizer-exit-code", "0").returncode == 0
    metadata = read_metadata(root)
    assert metadata["exact_F"] == 1.25
    assert metadata["objective_scale"] == 100
    assert metadata["scaled_objective_value"] == 125
    assert metadata["scaled_modified_manhattan_lower_bound"] == 100
    assert metadata["modified_manhattan_lower_bound"] == 1.0
    assert metadata["global_objective_optimum_proven"] is False
    assert metadata["total_base_mass"] == 42
    assert metadata["elevator_module_count"] == 2
    assert metadata["corridor_count"] == 3
    search = payload["optimization"]["search_diagnostics"]
    for key, value in search.items():
        assert metadata[key] == value
    assert metadata["fixed_subproblems"]["flow_formulation"] == (
        "source_aggregated_weighted_flow"
    )
    assert metadata["fixed_subproblems"]["source_flow_domain"] == {
        "max_commodities": 7,
        "total_actual_variables": 7200,
        "total_full_domain_variables": 12000,
        "max_actual_variables": 2100,
        "max_full_domain_variables": 3360,
        "max_shared_activation_gates": 11,
        "max_endpoint_distribution_variables": 0,
        "max_capacity_constraints": 2800,
        "max_balance_constraints": 1600,
    }
    assert metadata["fixed_subproblems"]["build_phases"] == {
        "hard_model_time_s": 0.04,
        "path_graph_time_s": 0.01,
        "objective_definition_time_s": 0.01,
        "source_flow_time_s": 0.05,
        "lexicographic_finalize_time_s": 0.01,
        "total_model_build_time_s": 0.12,
    }
    assert metadata["fixed_subproblems"]["lexicographic_scalarization"] == {
        "used": True,
        "max_primary_objective_upper_bound": 12000,
        "max_combined_objective_upper_bound": 987654321,
        "max_weight_f": 7000,
        "max_weight_mass": 300,
        "max_weight_elevator": 20,
        "max_weight_corridor": 1,
        "max_corridor_bound": 19,
        "max_elevator_bound": 17,
        "max_mass_bound": 72,
        "max_incumbent_scalar_value": 63042,
    }


@pytest.mark.parametrize("status", ["TIME_LIMIT", "INFEASIBLE", "NO_CONNECTED_LAYOUT"])
def test_failure_keeps_json_and_nulls_without_images(tmp_path, monkeypatch, status):
    monkeypatch.delenv("OPTIMIZER_EXIT_CODE", raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/example-plan.json").write_text('{"base_tier":1,"rooms":{}}')
    payload = {
        "status": status, "base": {"tier": 1}, "modules": [],
        "optimization": {
            "objective_value": None, "exact_integer_objective": None,
            "search_diagnostics": {"time_limit_reached": status == "TIME_LIMIT"},
        },
    }
    raw = json.dumps(payload)
    (tmp_path / "layout.json").write_text(raw, encoding="utf-8")
    run = run_helper(tmp_path, "--optimizer-exit-code", "2")
    assert run.returncode == 0, run.stderr
    metadata = read_metadata(tmp_path)
    assert metadata["optimizer_exit_code"] == 2
    assert metadata["status"] == status
    for key in (
        "exact_F", "objective_scale", "scaled_objective_value", "total_base_mass",
        "scaled_modified_manhattan_lower_bound", "modified_manhattan_lower_bound",
        "elevator_module_count", "corridor_count", "global_objective_optimum_proven",
        "structural_feasible", "journey_feasible", "search_time_s",
    ):
        assert metadata[key] is None
    assert all(
        value is None
        for value in metadata["fixed_subproblems"]["source_flow_domain"].values()
    )
    with ZipFile(next(tmp_path.glob("*.zip"))) as archive:
        assert set(archive.namelist()) == {
            PREFIX + "input/example-plan.json", PREFIX + "output/layout.json",
            PREFIX + "run-metadata.json",
        }
        assert archive.read(PREFIX + "output/layout.json").decode() == raw
    assert run_helper(tmp_path, "--verify").returncode != 0


@pytest.mark.parametrize("raw", ["{broken", "[]", '{"optimization":[]}', '{"x":NaN}'])
def test_malformed_layout_fails_clearly_but_archives_raw_evidence(example_files, raw):
    root, _ = example_files
    (root / "layout.json").write_text(raw, encoding="utf-8")
    run = run_helper(root, "--optimizer-exit-code", "2")
    assert run.returncode != 0
    assert "Malformed" in run.stderr and "layout.json" in run.stderr
    with ZipFile(next(root.glob("*.zip"))) as archive:
        assert archive.read(PREFIX + "output/layout.json").decode() == raw
        metadata = json.loads(archive.read(PREFIX + "run-metadata.json"))
        assert metadata["layout_parse_error"]
        assert metadata["exact_F"] is None


def test_crash_before_layout_still_packages_input_and_metadata(tmp_path, monkeypatch):
    monkeypatch.delenv("OPTIMIZER_EXIT_CODE", raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/example-plan.json").write_text('{"base_tier":1,"rooms":{}}')
    run = run_helper(tmp_path, "--optimizer-exit-code", "1")
    assert run.returncode == 0, run.stderr
    metadata = read_metadata(tmp_path)
    assert metadata["status"] is None
    assert metadata["exact_F"] is None
    assert metadata["total_base_mass"] is None
    assert metadata["optimizer_exit_code"] == 1
    with ZipFile(next(tmp_path.glob("*.zip"))) as archive:
        assert set(archive.namelist()) == {
            PREFIX + "input/example-plan.json", PREFIX + "run-metadata.json",
        }
    assert run_helper(tmp_path, "--verify").returncode != 0


@pytest.mark.parametrize("exit_code", ["2", None])
def test_nonzero_or_unknown_process_exit_cannot_pass_feasible_gate(example_files, exit_code):
    root, _ = example_files
    args = ["--optimizer-exit-code", exit_code] if exit_code is not None else []
    assert run_helper(root, *args).returncode == 0
    assert read_metadata(root)["optimizer_exit_code"] == (2 if exit_code else None)
    gate = run_helper(root, "--verify")
    assert gate.returncode != 0
    assert "optimizer exit code is not zero" in gate.stderr


@pytest.mark.parametrize("change", ["status", "modules", "structural", "empty_png", "empty_svg", "empty_json"])
def test_acceptance_rejects_baseline_regressions(example_files, change):
    root, payload = example_files
    if change == "status":
        payload["status"] = "TIME_LIMIT"
    elif change == "modules":
        payload["modules"] = []
    elif change == "structural":
        payload["feasibility"]["structural_feasible"] = False
    (root / "layout.json").write_text(json.dumps(payload), encoding="utf-8")
    if change.startswith("empty_"):
        (root / f"layout.{change.removeprefix('empty_')}").write_bytes(b"")
    run_helper(root, "--optimizer-exit-code", "0")
    assert run_helper(root, "--verify").returncode != 0


def test_capture_environment_and_refuse_overwriting_existing_evidence(example_files, monkeypatch):
    root, _ = example_files
    monkeypatch.setenv("OPTIMIZER_EXIT_CODE", "0")
    assert run_helper(root).returncode == 0
    assert read_metadata(root)["optimizer_exit_code"] == 0
    archive = next(root.glob("*.zip"))
    original = archive.read_bytes()
    rerun = run_helper(root)
    assert rerun.returncode != 0
    assert "already exists" in rerun.stderr
    assert archive.read_bytes() == original
