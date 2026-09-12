"""Package the canonical production example; run the acceptance gate after upload."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

INPUT_CONFIG = Path("config/example-plan.json")
RESULT_DIR = Path("example-plan-result")
OUTPUT_NAMES = ("layout.json", "layout.png", "layout.svg")
SEARCH_FIELDS = (
    "search_time_s",
    "room_packings_examined",
    "connected_candidates_examined",
    "fixed_objective_optima_proven",
    "manhattan_pruned_count",
    "incumbent_bound_pruned_count",
    "time_limit_reached",
    "search_exhausted",
)
FIXED_FIELDS = (
    "count",
    "max_graph_nodes",
    "max_graph_arcs",
    "max_objective_pairs",
    "max_cp_sat_variables",
    "max_cp_sat_constraints",
    "model_build_time_s",
    "cp_sat_solve_time_s",
    "total_time_s",
)
PAIR_FLOW_FIELDS = (
    "total_actual_variables",
    "total_full_domain_variables",
    "max_actual_variables",
    "max_full_domain_variables",
)


def git_value(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=Path(__file__).resolve().parents[1],
            text=True, stderr=subprocess.PIPE,
        ).strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def load_object(path: Path) -> dict:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON value {value}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
        if not isinstance(data, dict):
            raise ValueError("root must be a JSON object")
        return data
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"Malformed {path}: {exc}") from exc


def field(data: dict, *keys: str) -> object:
    """Read only reported values; missing/null sections never imply zero or proof."""
    value = data
    for key in keys:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError(f"Malformed layout.json: expected object before {key}")
        value = value.get(key)
    return value


def layout_metadata(layout: dict) -> dict:
    optimization = ("optimization",)
    exact = (*optimization, "exact_integer_objective")
    search = (*optimization, "search_diagnostics")
    fixed = (*search, "fixed_subproblems")
    infrastructure = (*optimization, "infrastructure")
    return {
        "status": field(layout, "status"),
        "base_tier": field(layout, "base", "tier"),
        "objective_scale": field(layout, *exact, "scale"),
        "scaled_objective_value": field(layout, *exact, "scaled_value"),
        "exact_F": field(layout, *optimization, "objective_value"),
        "scaled_modified_manhattan_lower_bound": field(
            layout, *exact, "scaled_modified_manhattan_lower_bound"
        ),
        "modified_manhattan_lower_bound": field(
            layout, *optimization, "modified_manhattan_lower_bound"
        ),
        "global_objective_optimum_proven": field(
            layout, *optimization, "global_objective_optimum_proven"
        ),
        "structural_feasible": field(layout, "feasibility", "structural_feasible"),
        "journey_feasible": field(layout, "feasibility", "journey_feasible"),
        "total_base_mass": field(layout, "journey", "total_base_mass"),
        "elevator_module_count": field(layout, *infrastructure, "elevator_module_count"),
        "corridor_count": field(layout, *infrastructure, "corridor_count"),
        **{key: field(layout, *search, key) for key in SEARCH_FIELDS},
        "fixed_subproblems": {
            **{key: field(layout, *fixed, key) for key in FIXED_FIELDS},
            "pair_flow_domain": {
                key: field(layout, *fixed, "pair_flow_domain", key) for key in PAIR_FLOW_FIELDS
            },
        },
    }


def create_evidence(optimizer_exit_code: int | None, destination: Path = Path(".")) -> Path:
    """Copy available outputs, then archive them even if layout parsing fails.

    Inputs/outputs are relative to the production CLI's working directory. Use a
    fresh destination for each run so old images cannot leak into a new package.
    """
    commit = git_value("rev-parse", "HEAD")
    short_sha = git_value("rev-parse", "--short", "HEAD")
    if commit is None or short_sha is None:
        raise ValueError("Cannot identify the checked-out Git commit")
    result_dir = destination / RESULT_DIR
    zip_path = destination / f"example-plan-{short_sha}.zip"
    if result_dir.exists() or zip_path.exists():
        raise ValueError("Evidence destination already exists; choose a fresh --destination")
    input_dir = result_dir / "input"
    output_dir = result_dir / "output"
    input_dir.mkdir(parents=True)
    output_dir.mkdir()
    shutil.copyfile(INPUT_CONFIG, input_dir / INPUT_CONFIG.name)
    for name in OUTPUT_NAMES:
        source = Path(name)
        if source.is_file():
            shutil.copyfile(source, output_dir / name)

    parse_error = None
    summary = layout_metadata({})
    layout_path = output_dir / "layout.json"
    if layout_path.exists():
        try:
            summary = layout_metadata(load_object(layout_path))
        except ValueError as exc:
            parse_error = str(exc)
    metadata = {
        "schema_version": 1,
        "git_commit": commit,
        "git_ref": os.getenv("GITHUB_REF") or git_value("symbolic-ref", "--quiet", "HEAD"),
        "timestamp_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "python_version": platform.python_version(),
        "ortools_version": package_version("ortools"),
        "planner_version": package_version("alters-base-planner"),
        "input_configuration_path": INPUT_CONFIG.as_posix(),
        "optimizer_exit_code": optimizer_exit_code,
        **summary,
        "layout_parse_error": parse_error,
    }
    (result_dir / "run-metadata.json").write_text(
        json.dumps(metadata, separators=(",", ":"), sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    with ZipFile(zip_path, "x", compression=ZIP_DEFLATED) as archive:
        for path in sorted(result_dir.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(destination).as_posix())
    print(f"Created ZIP: {zip_path}")
    if parse_error:
        raise ValueError(parse_error)
    return zip_path


def verify_evidence(destination: Path = Path(".")) -> None:
    """Smoke acceptance only; proof and quality/timing metrics are not gates."""
    result_dir = destination / RESULT_DIR
    for name in OUTPUT_NAMES:
        path = result_dir / "output" / name
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Baseline acceptance failed: missing or empty {path}")
    layout = load_object(result_dir / "output" / "layout.json")
    metadata = load_object(result_dir / "run-metadata.json")
    if metadata.get("optimizer_exit_code") != 0:
        raise ValueError("Baseline acceptance failed: optimizer exit code is not zero")
    if layout.get("status") != "FEASIBLE":
        raise ValueError(f"Baseline acceptance failed: status={layout.get('status')}")
    modules = layout.get("modules")
    if not isinstance(modules, list) or not modules:
        raise ValueError("Baseline acceptance failed: modules must be a nonempty list")
    if field(layout, "feasibility", "structural_feasible") is not True:
        raise ValueError("Baseline acceptance failed: structural_feasible must be true")
    print("Example-plan baseline acceptance passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--optimizer-exit-code", type=int,
        default=os.getenv("OPTIMIZER_EXIT_CODE") or None,
        help="captured CLI exit code (default: OPTIMIZER_EXIT_CODE, otherwise null)",
    )
    parser.add_argument("--destination", type=Path, default=Path("."))
    parser.add_argument("--verify", action="store_true", help="only check packaged baseline outputs")
    args = parser.parse_args()
    try:
        if args.verify:
            verify_evidence(args.destination)
        else:
            create_evidence(args.optimizer_exit_code, args.destination)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Evidence error: {exc}\n")


if __name__ == "__main__":
    main()
