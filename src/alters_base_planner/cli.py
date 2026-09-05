from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import solve_plan
from .models import PlanRequest
from .render import render_svg


def _parse_rooms(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in values:
        key, sep, value = item.partition("=")
        if not sep:
            raise argparse.ArgumentTypeError(f"Expected ROOM=COUNT, got {item!r}")
        counts[key.strip()] = int(value)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimize a The Alters base layout")
    parser.add_argument("--tier", type=int, choices=(1, 2, 3, 4), default=2)
    parser.add_argument("--room", action="append", default=[], metavar="ROOM=COUNT")
    parser.add_argument("--time-limit", type=float, default=15.0)
    parser.add_argument("--attempts", type=int, default=20)
    parser.add_argument("--svg", type=Path, default=Path("layout.svg"))
    args = parser.parse_args()

    result = solve_plan(
        PlanRequest(
            tier=args.tier,
            room_counts=_parse_rooms(args.room),
            time_limit_s=args.time_limit,
            max_layout_attempts=args.attempts,
        )
    )
    print(json.dumps({"status": result.status, "attempts": result.attempts, "message": result.message}, indent=2))
    if result.rooms:
        args.svg.write_text(render_svg(result), encoding="utf-8")
        print(f"Wrote {args.svg}")


if __name__ == "__main__":
    main()
