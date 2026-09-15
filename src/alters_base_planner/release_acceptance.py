from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from .benchmark import BenchmarkCase, REPRESENTATIVE_CASES, run_cases, write_report

# Release-acceptance budgets are deliberately longer than the representative benchmark budgets.
# They are measurement windows, not runtime SLAs and not optimality-proof requirements.
_V1_TIME_LIMITS_S = {
    1: 60.0,
    2: 120.0,
    3: 180.0,
    4: 300.0,
}

# Keep the room-packing attempt ceiling effectively non-binding so the wall-clock budget is the
# meaningful limiter during release acceptance. Search exhaustion may still finish earlier.
_V1_MAX_LAYOUT_ATTEMPTS = 10_000


V1_RELEASE_CASES: tuple[BenchmarkCase, ...] = tuple(
    replace(
        case,
        name=f"v1-{case.name}",
        time_limit_s=_V1_TIME_LIMITS_S[case.tier],
        max_layout_attempts=_V1_MAX_LAYOUT_ATTEMPTS,
        purpose=(
            "V1 release-acceptance measurement of practical time-to-first-feasible behavior; "
            "global optimality is not required within this budget."
        ),
    )
    for case in REPRESENTATIVE_CASES
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the version-controlled Alters Base Planner v1 release-acceptance suite"
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=Path("v1-release-acceptance.json"),
        help="Output JSON report path.",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path("v1-release-acceptance.md"),
        help="Output Markdown report path.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    records = run_cases(V1_RELEASE_CASES)
    write_report(V1_RELEASE_CASES, records, json_path=args.json, markdown_path=args.markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
