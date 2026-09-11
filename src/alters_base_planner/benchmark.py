from __future__ import annotations

import argparse
import json
import platform
import sys
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path
from time import monotonic
from typing import Iterable

from .engine import solve_plan
from .models import PlanRequest, PlanResult

BENCHMARK_SCHEMA_VERSION = 3


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """One version-controlled production-solver benchmark input."""

    name: str
    tier: int
    room_counts: dict[str, int]
    time_limit_s: float
    max_layout_attempts: int
    purpose: str

    def request(self) -> PlanRequest:
        return PlanRequest(
            tier=self.tier,
            room_counts=dict(self.room_counts),
            time_limit_s=self.time_limit_s,
            max_layout_attempts=self.max_layout_attempts,
        )


@dataclass(frozen=True, slots=True)
class BenchmarkRecord:
    """Stable benchmark measurements derived from one production PlanResult."""

    name: str
    tier: int
    status: str
    configured_time_limit_s: float
    configured_max_layout_attempts: int
    elapsed_wall_s: float
    solver_reported_search_s: float
    room_packings_examined: int
    connected_candidates_examined: int
    fixed_objective_optima_proven: int
    manhattan_pruned_count: int
    incumbent_bound_pruned_count: int
    search_exhausted: bool
    time_limit_reached: bool
    global_objective_optimum_proven: bool
    objective_scale: int
    scaled_objective_value: int | None
    scaled_modified_manhattan_lower_bound: int | None
    weighted_distance_score: float | None
    total_mass: int
    elevator_module_count: int
    corridor_count: int
    fixed_subproblem_count: int
    max_fixed_graph_nodes: int
    max_fixed_graph_arcs: int
    max_fixed_objective_pairs: int
    max_fixed_cp_sat_variables: int
    max_fixed_cp_sat_constraints: int
    fixed_model_build_time_s: float
    fixed_cp_sat_solve_time_s: float
    fixed_subproblem_time_s: float


SMOKE_CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        name="tier1-baseline-smoke",
        tier=1,
        room_counts={},
        time_limit_s=1.0,
        max_layout_attempts=1,
        purpose="Fast production-path smoke measurement; no performance threshold.",
    ),
)

REPRESENTATIVE_CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        name="tier1-workshop",
        tier=1,
        room_counts={"workshop": 1},
        time_limit_s=15.0,
        max_layout_attempts=30,
        purpose="Small mobile-Base objective search with one high-traffic PLAYER module.",
    ),
    BenchmarkCase(
        name="tier2-balanced",
        tier=2,
        room_counts={
            "workshop": 1,
            "research_lab": 1,
            "dormitory": 1,
            "small_storage": 1,
            "recycler": 1,
        },
        time_limit_s=30.0,
        max_layout_attempts=60,
        purpose="Representative mixed traffic/passive Tier-II planning request.",
    ),
    BenchmarkCase(
        name="tier3-production",
        tier=3,
        room_counts={
            "workshop": 1,
            "research_lab": 1,
            "dormitory": 2,
            "greenhouse": 1,
            "refinery": 1,
            "infirmary": 1,
            "small_storage": 2,
            "social_room": 1,
            "recycler": 1,
        },
        time_limit_s=45.0,
        max_layout_attempts=100,
        purpose="Larger Tier-III case with multiple weighted pairs and passive modules.",
    ),
    BenchmarkCase(
        name="tier4-dense",
        tier=4,
        room_counts={
            "workshop": 2,
            "research_lab": 1,
            "dormitory": 2,
            "greenhouse": 1,
            "refinery": 1,
            "infirmary": 1,
            "small_storage": 2,
            "medium_storage": 1,
            "social_room": 1,
            "gym": 1,
            "recycler": 1,
        },
        time_limit_s=60.0,
        max_layout_attempts=150,
        purpose="Dense Tier-IV stress case for decomposition scalability.",
    ),
)


def _environment_payload() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "ortools": version("ortools"),
        "planner": version("alters-base-planner"),
    }


def record_from_result(
    case: BenchmarkCase,
    result: PlanResult,
    *,
    elapsed_wall_s: float,
) -> BenchmarkRecord:
    return BenchmarkRecord(
        name=case.name,
        tier=case.tier,
        status=result.status,
        configured_time_limit_s=case.time_limit_s,
        configured_max_layout_attempts=case.max_layout_attempts,
        elapsed_wall_s=elapsed_wall_s,
        solver_reported_search_s=result.search_time_s,
        room_packings_examined=result.attempts,
        connected_candidates_examined=result.connected_candidates_examined,
        fixed_objective_optima_proven=result.fixed_objective_optima_proven,
        manhattan_pruned_count=result.manhattan_pruned_count,
        incumbent_bound_pruned_count=result.incumbent_bound_pruned_count,
        search_exhausted=result.search_exhausted,
        time_limit_reached=result.time_limit_reached,
        global_objective_optimum_proven=result.global_objective_optimum_proven,
        objective_scale=result.objective_scale,
        scaled_objective_value=result.scaled_objective_value,
        scaled_modified_manhattan_lower_bound=result.scaled_modified_manhattan_lower_bound,
        weighted_distance_score=result.weighted_distance_score,
        total_mass=result.total_mass,
        elevator_module_count=result.elevator_module_count,
        corridor_count=result.corridor_count,
        fixed_subproblem_count=result.fixed_subproblem_count,
        max_fixed_graph_nodes=result.max_fixed_graph_nodes,
        max_fixed_graph_arcs=result.max_fixed_graph_arcs,
        max_fixed_objective_pairs=result.max_fixed_objective_pairs,
        max_fixed_cp_sat_variables=result.max_fixed_cp_sat_variables,
        max_fixed_cp_sat_constraints=result.max_fixed_cp_sat_constraints,
        fixed_model_build_time_s=result.fixed_model_build_time_s,
        fixed_cp_sat_solve_time_s=result.fixed_cp_sat_solve_time_s,
        fixed_subproblem_time_s=result.fixed_subproblem_time_s,
    )


def run_case(case: BenchmarkCase) -> BenchmarkRecord:
    started = monotonic()
    result = solve_plan(case.request())
    elapsed = monotonic() - started
    return record_from_result(case, result, elapsed_wall_s=elapsed)


def run_cases(cases: Iterable[BenchmarkCase]) -> list[BenchmarkRecord]:
    return [run_case(case) for case in cases]


def benchmark_payload(
    cases: Iterable[BenchmarkCase],
    records: Iterable[BenchmarkRecord],
) -> dict[str, object]:
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "environment": _environment_payload(),
        "cases": [asdict(case) for case in cases],
        "results": [asdict(record) for record in records],
    }


def benchmark_markdown(payload: dict[str, object]) -> str:
    environment = payload["environment"]
    results = payload["results"]
    if not isinstance(environment, dict) or not isinstance(results, list):
        raise ValueError("Invalid benchmark payload")

    lines = [
        "# The Alters Base Planner benchmark report",
        "",
        f"Schema version: {payload['schema_version']}",
        "",
        "## Environment",
        "",
    ]
    for key, value in environment.items():
        lines.append(f"- {key}: `{value}`")

    lines.extend(
        [
            "",
            "## Results",
            "",
            "| Case | Tier | Status | Wall s | Packings | Exact fixed optima | LB pruned | Incumbent-cut | F | Mass | E | C | Global proof |",
            "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for raw in results:
        if not isinstance(raw, dict):
            raise ValueError("Invalid benchmark result row")
        score = raw["weighted_distance_score"]
        score_text = "-" if score is None else f"{score:.4f}"
        lines.append(
            "| {name} | {tier} | {status} | {wall:.3f} | {packings} | {fixed} | {pruned} | "
            "{incumbent_cut} | {score} | {mass} | {elevators} | {corridors} | {proof} |".format(
                name=raw["name"],
                tier=raw["tier"],
                status=raw["status"],
                wall=raw["elapsed_wall_s"],
                packings=raw["room_packings_examined"],
                fixed=raw["fixed_objective_optima_proven"],
                pruned=raw["manhattan_pruned_count"],
                incumbent_cut=raw["incumbent_bound_pruned_count"],
                score=score_text,
                mass=raw["total_mass"],
                elevators=raw["elevator_module_count"],
                corridors=raw["corridor_count"],
                proof="yes" if raw["global_objective_optimum_proven"] else "no",
            )
        )

    lines.extend(
        [
            "",
            "## Fixed-packing model diagnostics",
            "",
            "Counts are maxima over fixed-packing subproblems in the run; timing columns are totals.",
            "",
            "| Case | Subproblems | Nodes | Arcs | Pairs | CP vars | CP constraints | Build s | CP-SAT s | Fixed total s |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for raw in results:
        if not isinstance(raw, dict):
            raise ValueError("Invalid benchmark result row")
        lines.append(
            "| {name} | {count} | {nodes} | {arcs} | {pairs} | {variables} | {constraints} | "
            "{build:.3f} | {solve:.3f} | {total:.3f} |".format(
                name=raw["name"],
                count=raw["fixed_subproblem_count"],
                nodes=raw["max_fixed_graph_nodes"],
                arcs=raw["max_fixed_graph_arcs"],
                pairs=raw["max_fixed_objective_pairs"],
                variables=raw["max_fixed_cp_sat_variables"],
                constraints=raw["max_fixed_cp_sat_constraints"],
                build=raw["fixed_model_build_time_s"],
                solve=raw["fixed_cp_sat_solve_time_s"],
                total=raw["fixed_subproblem_time_s"],
            )
        )

    lines.extend(
        [
            "",
            "> Runtime values are measurements, not correctness thresholds. Compare reports only on sufficiently similar hardware/software environments.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(
    cases: tuple[BenchmarkCase, ...],
    records: list[BenchmarkRecord],
    *,
    json_path: Path,
    markdown_path: Path,
) -> None:
    payload = benchmark_payload(cases, records)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(benchmark_markdown(payload), encoding="utf-8")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run reproducible Alters Base Planner benchmarks")
    parser.add_argument(
        "--suite",
        choices=("smoke", "representative"),
        default="smoke",
        help="Benchmark suite to run. Representative may consume several minutes.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=Path("benchmark-results.json"),
        help="Output JSON report path.",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path("benchmark-results.md"),
        help="Output Markdown report path.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cases = SMOKE_CASES if args.suite == "smoke" else REPRESENTATIVE_CASES
    records = run_cases(cases)
    write_report(cases, records, json_path=args.json, markdown_path=args.markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
