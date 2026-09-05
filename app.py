from __future__ import annotations

import json
import tempfile
from pathlib import Path

import streamlit as st

from alters_base_planner.base import builtin_base
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
        with st.spinner("Solving room packing and routing utilities..."):
            result = solve_plan(loaded.request, base)
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        st.error(f"Invalid configuration: {exc}")
        st.stop()

    if not base.verified:
        st.warning(
            "The selected built-in Base I-IV grid is still provisional. Organics capacity and the 4×2 "
            "immovable tank are grounded in public evidence, but authoritative cell coordinates are not public."
        )

    c1, c2, c3 = st.columns(3)
    c1.metric("Status", result.status)
    c2.metric("Attempts", result.attempts)
    c3.metric("Base", f"Tier {result.base.tier}")
    st.write(result.message)

    if result.rooms:
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
                "rooms": [
                    {
                        "instance_id": r.instance_id,
                        "module_key": r.module_key,
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
