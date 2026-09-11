from __future__ import annotations

import argparse
import json
from pathlib import Path

from .base import builtin_base
from .config import load_plan_config
from .engine import solve_plan
from .render import render_png, render_svg
from .serialization import result_payload


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
            "WARNING: selected Base geometry is not marked verified. "
            "Review its 0/1/X source before treating the layout as game-exact."
        )

    result = solve_plan(loaded.request, base)
    payload = result_payload(result)
    payload_text = json.dumps(payload, indent=2)
    print(payload_text)

    # JSON is the machine-readable audit result and is always persisted, including
    # infeasible/time-limit outcomes. PNG/SVG exist only when a feasible layout exists.
    loaded.output.json.parent.mkdir(parents=True, exist_ok=True)
    loaded.output.json.write_text(payload_text, encoding="utf-8")
    print(f"Wrote {loaded.output.json}")

    if result.rooms:
        loaded.output.svg.parent.mkdir(parents=True, exist_ok=True)
        loaded.output.png.parent.mkdir(parents=True, exist_ok=True)
        loaded.output.svg.write_text(render_svg(result), encoding="utf-8")
        render_png(result, loaded.output.png)
        print(f"Wrote {loaded.output.svg}")
        print(f"Wrote {loaded.output.png}")
    else:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
