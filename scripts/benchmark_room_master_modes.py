from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from time import monotonic

from alters_base_planner.benchmark import benchmark_payload, record_from_result
from alters_base_planner.engine import _RoomMasterMode, _solve_plan_with_room_master_mode
from alters_base_planner.release_acceptance import V1_RELEASE_CASES


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one internal V1 room-master enumeration-mode experiment"
    )
    parser.add_argument("--tier", type=int, choices=(1, 2, 3, 4), required=True)
    parser.add_argument(
        "--mode",
        choices=tuple(mode.value for mode in _RoomMasterMode),
        required=True,
    )
    parser.add_argument("--time-limit", type=float)
    parser.add_argument("--max-layout-attempts", type=int)
    parser.add_argument("--json", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    case = next(case for case in V1_RELEASE_CASES if case.tier == args.tier)
    case = replace(
        case,
        name=f"{case.name}-{args.mode}",
        time_limit_s=(case.time_limit_s if args.time_limit is None else args.time_limit),
        max_layout_attempts=(
            case.max_layout_attempts
            if args.max_layout_attempts is None
            else args.max_layout_attempts
        ),
        purpose=f"Internal exact room-master mode comparison: {args.mode}.",
    )
    mode = _RoomMasterMode(args.mode)

    started = monotonic()
    result = _solve_plan_with_room_master_mode(
        case.request(),
        room_master_mode=mode,
    )
    elapsed = monotonic() - started
    record = record_from_result(case, result, elapsed_wall_s=elapsed)
    payload = benchmark_payload((case,), (record,))

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["results"][0], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
