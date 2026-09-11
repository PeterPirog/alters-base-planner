from __future__ import annotations

import json
import tempfile
from pathlib import Path

import streamlit as st

from alters_base_planner.base import builtin_base
from alters_base_planner.config import load_plan_config
from alters_base_planner.engine import solve_plan
from alters_base_planner.render import render_png, render_svg
from alters_base_planner.serialization import average_pair_distance, result_payload

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
            f"{base.source} is not marked as verified geometry. Review its 0/1/X cells "
            "before treating the generated layout as game-exact."
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
        st.json(result_payload(result))

st.info(
    "Base geometry is editable in `src/alters_base_planner/data/base-size1.csv` ... "
    "`base-size4.csv`; gameplay usage weights live in `usage_weights.json`."
)
