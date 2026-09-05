from __future__ import annotations

import json
import tempfile
from pathlib import Path

import streamlit as st

from alters_base_planner.base import builtin_base
from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.config import load_plan_config
from alters_base_planner.engine import solve_plan
from alters_base_planner.render import render_svg

st.set_page_config(page_title="The Alters Base Planner", layout="wide")
st.title("The Alters Base Planner")
st.caption("JSON-configured OR-Tools CP-SAT planner with automatic corridors and elevators")

st.markdown(
    "Room counts are configured **only in JSON for now**. Edit `config/plan.json` or upload "
    "a compatible file below. Corridor and Elevator counts are never configured by the player."
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
        with st.spinner("Solving room packing, connectivity, utility mass and journey cost..."):
            result = solve_plan(loaded.request, base)
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        st.error(f"Invalid configuration: {exc}")
        st.stop()

    if not base.verified:
        st.warning(
            "The selected built-in Base I-IV perimeter is provisional. Public evidence verifies "
            "the circular/irregular row structure, the immovable offset Organics core and tank "
            "capacities, but not authoritative cell-by-cell coordinates for each tier."
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", result.status)
    c2.metric("Attempts", result.attempts)
    c3.metric("Base", f"Tier {result.base.tier}")
    c4.metric("Base mass", result.total_mass)
    st.write(result.message)

    if result.rooms:
        j1, j2, j3, j4 = st.columns(4)
        j1.metric("Room mass", result.room_mass)
        j2.metric("Corridor/elevator mass", result.utility_mass)
        j3.metric("Journey Organics", result.organics_required_for_journey)
        j4.metric(
            "Tank margin",
            result.organics_capacity_margin,
            delta="travel possible" if result.travel_feasible_at_full_tank else "too heavy",
        )

        svg = render_svg(result)
        st.components.v1.html(svg, height=result.base.height * 26 + 20, scrolling=False)
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
                        "instance_id": r.instance_id,
                        "module_key": r.module_key,
                        "mass": MODULE_BY_KEY[r.module_key].mass,
                        "x": r.x,
                        "y": r.y,
                        "width": r.width,
                        "height": r.height,
                    }
                    for r in result.rooms
                ],
                "utilities": [
                    {
                        "kind": u.kind,
                        "mass": 2,
                        "x": u.x,
                        "y": u.y,
                        "width": u.width,
                        "height": u.height,
                    }
                    for u in result.utilities
                ],
            }
        )

st.info(
    "Geometry definitions live in `src/alters_base_planner/data/base_grids.json`. "
    "This intentionally separates game-grid calibration from the optimization engine."
)
