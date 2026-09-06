from __future__ import annotations

import json
import tempfile
from pathlib import Path

import streamlit as st

from alters_base_planner.base import builtin_base
from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.config import load_plan_config
from alters_base_planner.engine import solve_plan
from alters_base_planner.models import resolve_ports
from alters_base_planner.render import average_pair_distance, render_png, render_svg

st.set_page_config(page_title="The Alters Base Planner", layout="wide")
st.title("The Alters Base Planner")
st.caption("JSON-configured planner with automatic corridors, elevators and weighted travel scoring")

st.markdown(
    "Room counts are configured **only in JSON for now**. Edit `config/plan.json` or upload "
    "a compatible file below. Corridor and Elevator counts are solver-controlled."
)

uploaded = st.file_uploader("Plan configuration JSON", type=["json"])
use_repo_default = st.checkbox("Use repository config/plan.json", value=uploaded is None)

if st.button("Optimize layout", type="primary"):
    if uploaded is None and not use_repo_default:
        st.error("Upload a JSON configuration or enable the repository default.")
        st.stop()

    if uploaded is not None:
        with tempfile.NamedTemporaryFile(suffix=".json", mode="wb", delete=False) as tmp:
            tmp.write(uploaded.getvalue())
            config_path = Path(tmp.name)
    else:
        config_path = Path("config/plan.json")

    try:
        loaded = load_plan_config(config_path)
        base = builtin_base(loaded.request.tier)
        with st.spinner("Solving hard constraints and minimizing weighted pair distance..."):
            result = solve_plan(loaded.request, base)
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        st.error(f"Invalid configuration: {exc}")
        st.stop()

    if not base.verified:
        st.warning(
            f"{base.source} is an editable provisional Base {base.tier} mask. "
            "Correct 0/1/X cells in the CSV when more accurate game geometry is available."
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", result.status)
    c2.metric("Attempts", result.attempts)
    c3.metric("Base", f"Tier {result.base.tier}")
    c4.metric("Base mass", result.total_mass)
    st.write(result.message)

    if result.rooms:
        o1, o2, o3, o4, o5 = st.columns(5)
        o1.metric(
            "Objective F",
            f"{result.weighted_distance_score:.4f}"
            if result.weighted_distance_score is not None
            else "n/a",
        )
        o2.metric(
            "Manhattan LB",
            f"{result.modified_manhattan_lower_bound:.4f}"
            if result.modified_manhattan_lower_bound is not None
            else "n/a",
        )
        o3.metric("Average pair distance", f"{average_pair_distance(result):.2f}")
        o4.metric(
            "Weighted average",
            f"{result.normalized_weighted_distance:.2f}"
            if result.normalized_weighted_distance is not None
            else "n/a",
        )
        o5.metric("Elevators / Corridors", f"{result.elevator_module_count} / {result.corridor_count}")

        st.caption(
            "Distances are measured between explicit room ports. Standard multi-row rooms expose "
            "LEFT/RIGHT ports on the floor row, never at the ceiling. Adjacent endpoint rooms = 0; "
            "each Corridor = +1; each Elevator module = +1; an intermediate transit room adds its "
            "full width. Objective = Σ(i<j) wi·wj·dij."
        )
        st.caption(
            "Modified Manhattan is an admissible explicit-port lower bound used only to prune "
            "room packings that cannot beat the best exact F."
        )
        st.caption(
            "Vertical hard rule: every floor in the used port-floor span needs an Elevator stop, "
            "and every adjacent floor pair must share at least one Elevator x-coordinate."
        )
        if not result.global_objective_optimum_proven:
            st.info(
                "The objective is evaluated exactly for every generated connected candidate, "
                "but the current placement + post-router engine does not yet prove the global "
                "optimum across the complete joint placement/routing search space."
            )

        j1, j2, j3, j4 = st.columns(4)
        j1.metric("Room mass", result.room_mass)
        j2.metric("Corridor/elevator mass", result.utility_mass)
        j3.metric("Journey Organics", result.organics_required_for_journey)
        j4.metric(
            "Tank margin",
            result.organics_capacity_margin,
            delta="travel possible" if result.travel_feasible_at_full_tank else "too heavy",
        )

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as png_tmp:
            png_path = Path(png_tmp.name)
        render_png(result, png_path)
        png_bytes = png_path.read_bytes()
        st.image(png_bytes, caption="Color-coded optimized base layout", use_container_width=True)
        st.download_button("Download layout PNG", png_bytes, "alters-layout.png", "image/png")

        svg = render_svg(result)
        st.download_button("Download layout SVG", svg, "alters-layout.svg", "image/svg+xml")
        st.json(
            {
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
                    "weighted_distance_score": result.weighted_distance_score,
                    "modified_manhattan_lower_bound": result.modified_manhattan_lower_bound,
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
                        "ports": [
                            {
                                "name": port.name,
                                "side": port.side.value,
                                "cell": [port.cell_x, port.cell_y],
                                "edge": [port.edge_x, port.edge_y],
                                "utility_anchor": list(port.utility_anchor),
                            }
                            for port in resolve_ports(room, MODULE_BY_KEY[room.module_key])
                        ],
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
        )

st.info(
    "Base geometry is editable in `src/alters_base_planner/data/base-size1.csv` ... "
    "`base-size4.csv`; gameplay usage weights live in `usage_weights.json`."
)
