from __future__ import annotations

import streamlit as st

from alters_base_planner.base import builtin_base
from alters_base_planner.catalog import CONFIGURABLE_MODULES, MANDATORY_MODULES
from alters_base_planner.engine import solve_plan
from alters_base_planner.models import PlanRequest
from alters_base_planner.render import render_svg

st.set_page_config(page_title="The Alters Base Planner", layout="wide")
st.title("The Alters Base Planner")
st.caption("OR-Tools CP-SAT room packing with automatic corridors and elevators")

with st.sidebar:
    tier = st.selectbox("Base size", [1, 2, 3, 4], format_func=lambda x: f"Base Expansion {x}")
    strategy = st.selectbox("Optimization profile", ["balanced", "compact", "minimum_travel"])
    time_limit = st.slider("Solver time limit [s]", 3, 60, 15)
    attempts = st.slider("Connected-layout attempts", 1, 100, 20)

st.subheader("Mandatory modules")
st.write(", ".join(m.name for m in MANDATORY_MODULES))

st.subheader("Configure room counts")
counts: dict[str, int] = {}
cols = st.columns(3)
for idx, module in enumerate(CONFIGURABLE_MODULES):
    with cols[idx % 3]:
        counts[module.key] = st.number_input(
            f"{module.name} ({module.width}×{module.height})",
            min_value=0,
            max_value=12,
            value=0,
            step=1,
            key=module.key,
        )

if st.button("Optimize layout", type="primary"):
    request = PlanRequest(
        tier=tier,
        room_counts=counts,
        objective=strategy,
        time_limit_s=float(time_limit),
        max_layout_attempts=int(attempts),
    )
    with st.spinner("Solving room packing and routing utilities..."):
        result = solve_plan(request, builtin_base(tier))

    st.metric("Status", result.status)
    st.metric("Attempts", result.attempts)
    st.write(result.message)
    if result.rooms:
        room_mass = sum(r.spec.mass if hasattr(r, "spec") else 0 for r in [])
        st.components.v1.html(render_svg(result), height=result.base.height * 26 + 20, scrolling=False)
        st.download_button("Download layout SVG", render_svg(result), "alters-layout.svg", "image/svg+xml")
        st.json({
            "tier": result.base.tier,
            "geometry_source": result.base.source,
            "rooms": [r.__dict__ if hasattr(r, "__dict__") else {
                "instance_id": r.instance_id, "module_key": r.module_key, "x": r.x, "y": r.y,
                "width": r.width, "height": r.height
            } for r in result.rooms],
            "utilities": [
                {"kind": u.kind, "x": u.x, "y": u.y, "width": u.width, "height": u.height}
                for u in result.utilities
            ],
        })

st.info(
    "Corridors and elevators are never configured by the player. They are added automatically by the routing stage. "
    "Built-in Tier I-IV masks are conservative approximations because no authoritative machine-readable grid coordinates are public yet."
)
