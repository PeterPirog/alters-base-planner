from __future__ import annotations

import argparse
import json
from pathlib import Path

from .base import builtin_base
from .catalog import MODULE_BY_KEY
from .config import load_plan_config
from .engine import solve_plan
from .render import average_pair_distance, render_png, render_svg


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
        "optimization": {
            "objective": "sum_i_lt_j(weight_i * weight_j * distance_i_j)",
            "distance_rule": {
                "direct_room_adjacency": 0,
                "corridor_module": 1,
                "elevator_module": 1,
                "room_internal_length": 0,
            },
            "weighted_distance_score": result.weighted_distance_score,
            "average_pair_distance": average_pair_distance(result),
            "weighted_average_pair_distance": result.normalized_weighted_distance,
            "global_objective_optimum_proven": result.global_objective_optimum_proven,
            "elevator_module_count": result.elevator_module_count,
            "elevator_shaft_count": result.elevator_shaft_count,
            "corridor_count": result.corridor_count,
            "room_usage_weights": result.room_usage_weights,
            "pairwise_distances": result.pairwise_distances,
            "pairwise_contributions": result.pairwise_contributions,
        },
        "journey": {
            "room_mass": result.room_mass,
            "utility_mass": result.utility_mass,
            "total_base_mass": result.total_mass,
            "organics_required": result.organics_required_for_journey,
            "organics_tank_capacity": result.base.organics_capacity,
            "capacity_margin": result.organics_capacity_margin,
            "travel_feasible_at_full_tank": result.travel_feasible_at_full_tank,
            "mass_breakdown": result.mass_breakdown,
        },
        "rooms": [
            {
                "instance_id": room.instance_id,
                "module_key": room.module_key,
                "mass": MODULE_BY_KEY[room.module_key].mass,
                "usage_weight": MODULE_BY_KEY[room.module_key].visit_weight,
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
                "mass": 2,
                "distance_cost": 1,
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
            "game-extracted grid. See src/alters_base_planner/data/base-sizeN.csv."
        )

    result = solve_plan(loaded.request, base)
    payload = _result_payload(result)
    print(json.dumps(payload, indent=2))

    if result.rooms:
        loaded.output.svg.parent.mkdir(parents=True, exist_ok=True)
        loaded.output.png.parent.mkdir(parents=True, exist_ok=True)
        loaded.output.json.parent.mkdir(parents=True, exist_ok=True)
        loaded.output.svg.write_text(render_svg(result), encoding="utf-8")
        render_png(result, loaded.output.png)
        loaded.output.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {loaded.output.svg}")
        print(f"Wrote {loaded.output.png}")
        print(f"Wrote {loaded.output.json}")


if __name__ == "__main__":
    main()
