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
    payload_text = json.dumps(result_payload(result), indent=2)
    print(payload_text)

    loaded.output.json.parent.mkdir(parents=True, exist_ok=True)
    loaded.output.json.write_text(payload_text, encoding="utf-8")
    print(f"Wrote {loaded.output.json}")

    if result.status == "FEASIBLE":
        if not result.modules:
            raise RuntimeError("FEASIBLE result must contain installed modules")
        loaded.output.svg.parent.mkdir(parents=True, exist_ok=True)
        loaded.output.png.parent.mkdir(parents=True, exist_ok=True)
        loaded.output.svg.write_text(render_svg(result), encoding="utf-8")
        render_png(result, loaded.output.png)
        print(f"Wrote {loaded.output.svg}")
        print(f"Wrote {loaded.output.png}")
        return

    raise SystemExit(2)


if __name__ == "__main__":
    main()
