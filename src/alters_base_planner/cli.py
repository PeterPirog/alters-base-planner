from __future__ import annotations

import argparse
import json
from pathlib import Path

from .base import builtin_base
from .config import load_plan_config
from .engine import solve_plan
from .render import render_svg


def _result_payload(result) -> dict[str, object]:
    return {
        "status": result.status,
        "attempts": result.attempts,
        "message": result.message,
        "objective_value": result.objective_value,
        "base": {
            "tier": result.base.tier,
            "width": result.base.width,
            "height": result.base.height,
            "organics_capacity": result.base.organics_capacity,
            "geometry_source": result.base.source,
            "geometry_verified": result.base.verified,
            "geometry_note": result.base.note,
        },
        "rooms": [
            {
                "instance_id": room.instance_id,
                "module_key": room.module_key,
                "x": room.x,
                "y": room.y,
                "width": room.width,
                "height": room.height,
            }
            for room in result.rooms
        ],
        "utilities": [
            {
                "kind": utility.kind,
                "x": utility.x,
                "y": utility.y,
                "width": utility.width,
                "height": utility.height,
            }
            for utility in result.utilities
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimize a The Alters base layout from JSON")
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        default=Path("config/plan.json"),
        help="JSON plan configuration (default: config/plan.json)",
    )
    args = parser.parse_args()

    loaded = load_plan_config(args.config)
    base = builtin_base(loaded.request.tier)
    if not base.verified:
        print(
            "WARNING: selected built-in base geometry is provisional, not an authoritative "
            "game-extracted grid. See src/alters_base_planner/data/base_grids.json."
        )

    result = solve_plan(loaded.request, base)
    payload = _result_payload(result)
    print(json.dumps(payload, indent=2))

    if result.rooms:
        loaded.output.svg.parent.mkdir(parents=True, exist_ok=True)
        loaded.output.json.parent.mkdir(parents=True, exist_ok=True)
        loaded.output.svg.write_text(render_svg(result), encoding="utf-8")
        loaded.output.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {loaded.output.svg}")
        print(f"Wrote {loaded.output.json}")


if __name__ == "__main__":
    main()
