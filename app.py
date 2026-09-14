from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import cast

import streamlit as st

from alters_base_planner.catalog import (
    MODULE_BY_KEY,
    PLAYER_MODULES,
    SYSTEM_MODULES,
    resolve_usage_weights,
)
from alters_base_planner.config import (
    LoadedPlanConfig,
    build_plan_config_data,
    load_plan_config,
    parse_plan_config,
    plan_config_json,
)
from alters_base_planner.engine import solve_plan
from alters_base_planner.models import PlacementAuthority, PlanRequest, PlanResult
from alters_base_planner.render import render_png, render_svg
from alters_base_planner.serialization import average_pair_distance, result_payload

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = load_plan_config(PROJECT_ROOT / "config" / "plan.json")
TIER_LABELS = {1: "I", 2: "II", 3: "III", 4: "IV"}


def _initialize_form_state() -> None:
    defaults = DEFAULT_CONFIG.request
    if "form_base_tier" not in st.session_state:
        st.session_state.form_base_tier = defaults.tier
    if "form_time_limit_s" not in st.session_state:
        st.session_state.form_time_limit_s = defaults.time_limit_s
    if "form_max_layout_attempts" not in st.session_state:
        st.session_state.form_max_layout_attempts = defaults.max_layout_attempts
    if "form_usage_weights" not in st.session_state:
        st.session_state.form_usage_weights = resolve_usage_weights()
    if "usage_weight_editor_revision" not in st.session_state:
        st.session_state.usage_weight_editor_revision = 0
    for spec in PLAYER_MODULES:
        key = f"room_count__{spec.key}"
        if key not in st.session_state:
            st.session_state[key] = defaults.room_counts.get(spec.key, 0)


def _editor_records(edited: object) -> list[dict[str, object]]:
    if hasattr(edited, "to_dict"):
        return edited.to_dict("records")  # type: ignore[no-any-return, union-attr]
    return list(edited)  # type: ignore[arg-type]


def _request_signature(request: PlanRequest) -> tuple[object, ...]:
    """Identify the semantic planning inputs associated with a rendered result."""

    return (
        request.tier,
        tuple(sorted(request.room_counts.items())),
        tuple(sorted(resolve_usage_weights(request.usage_weights).items())),
        request.time_limit_s,
        request.max_layout_attempts,
        request.objective,
    )


def _render_plan_settings() -> tuple[int, float]:
    st.subheader("Plan settings")
    tier = int(
        st.radio(
            "Base Tier",
            options=(1, 2, 3, 4),
            horizontal=True,
            format_func=lambda value: f"Base Tier {TIER_LABELS[value]}",
            key="form_base_tier",
        )
    )
    time_limit_s = float(
        st.number_input(
            "Optimization time limit (seconds)",
            min_value=1.0,
            step=15.0,
            format="%.0f",
            key="form_time_limit_s",
        )
    )
    return tier, time_limit_s


def _render_room_controls() -> dict[str, int]:
    st.subheader("Rooms")
    st.markdown("**Mandatory rooms (SYSTEM)**")
    st.caption("The planner always includes exactly one of each module.")
    system_columns = st.columns(2)
    for index, spec in enumerate(SYSTEM_MODULES):
        with system_columns[index % 2]:
            st.number_input(
                spec.name,
                min_value=1,
                max_value=1,
                value=1,
                step=1,
                disabled=True,
                key=f"system_count__{spec.key}",
            )

    st.markdown("**PLAYER modules**")
    st.caption("Set the exact count to install. Zero omits a module.")
    room_counts: dict[str, int] = {}
    player_columns = st.columns(2)
    for index, spec in enumerate(PLAYER_MODULES):
        kwargs: dict[str, object] = {
            "label": spec.name,
            "min_value": 0,
            "step": 1,
            "key": f"room_count__{spec.key}",
        }
        if spec.max_count is not None:
            kwargs["max_value"] = spec.max_count
            kwargs["help"] = f"Verified allowed range: 0 to {spec.max_count}."
        with player_columns[index % 2]:
            room_counts[spec.key] = int(st.number_input(**kwargs))

    st.markdown("**Solver-managed infrastructure**")
    infrastructure_columns = st.columns(2)
    with infrastructure_columns[0]:
        st.text_input("Corridor", value="AUTO", disabled=True)
    with infrastructure_columns[1]:
        st.text_input("Elevator", value="AUTO", disabled=True)
    st.caption("The exact solver chooses Corridor and Elevator counts and positions.")
    return room_counts


def _render_usage_weight_editor(room_counts: dict[str, int]) -> dict[str, float]:
    st.subheader("Usage weights")
    st.caption(
        "Planner traffic heuristics, not game constants. A weight of 0 excludes a room "
        "from objective pairs but never removes hard placement or connectivity requirements. "
        "PLAYER rooms with count 0 do not affect the current objective."
    )

    defaults = resolve_usage_weights()
    current = dict(st.session_state.form_usage_weights)
    editable_specs = sorted((*SYSTEM_MODULES, *PLAYER_MODULES), key=lambda spec: spec.name)
    rows = [
        {
            "Module": spec.name,
            "Authority": spec.authority.value.upper(),
            "Count": 1 if spec.authority is PlacementAuthority.SYSTEM else room_counts[spec.key],
            "Default weight": defaults[spec.key],
            "Weight": current[spec.key],
        }
        for spec in editable_specs
    ]
    editor_key = f"usage_weights_editor_{st.session_state.usage_weight_editor_revision}"
    edited = st.data_editor(
        rows,
        hide_index=True,
        num_rows="fixed",
        disabled=("Module", "Authority", "Count", "Default weight"),
        column_config={
            "Count": st.column_config.NumberColumn("Count", format="%d"),
            "Default weight": st.column_config.NumberColumn(
                "Default weight", min_value=0.0, max_value=1.0, step=0.01, format="%.2f"
            ),
            "Weight": st.column_config.NumberColumn(
                "Weight",
                min_value=0.0,
                max_value=1.0,
                step=0.01,
                format="%.2f",
                required=True,
            ),
        },
        key=editor_key,
        width="stretch",
    )

    key_by_name = {spec.name: spec.key for spec in editable_specs}
    effective = resolve_usage_weights(
        {
            key_by_name[str(row["Module"])]: float(cast(float, row["Weight"]))
            for row in _editor_records(edited)
        }
    )
    st.session_state.form_usage_weights = effective

    if st.button("Reset weights to defaults"):
        st.session_state.form_usage_weights = defaults
        st.session_state.usage_weight_editor_revision += 1
        st.rerun()
    return effective


def _render_solver_controls() -> int:
    with st.expander("Advanced solver settings"):
        max_layout_attempts = int(
            st.number_input(
                "Maximum layout attempts",
                min_value=1,
                step=1,
                key="form_max_layout_attempts",
            )
        )
        st.text_input("Objective", value="weighted_pair_distance", disabled=True)
    return max_layout_attempts


def _render_form_input() -> LoadedPlanConfig:
    _initialize_form_state()
    tier, time_limit_s = _render_plan_settings()
    room_counts = _render_room_controls()
    usage_weights = _render_usage_weight_editor(room_counts)
    max_layout_attempts = _render_solver_controls()
    defaults = resolve_usage_weights()
    custom_weight_count = sum(
        usage_weights[key] != defaults[key] for key in usage_weights
    )
    st.markdown("**Plan summary**")
    summary_columns = st.columns(4)
    summary_columns[0].metric("Selected Base Tier", TIER_LABELS[tier])
    summary_columns[1].metric("SYSTEM rooms", len(SYSTEM_MODULES))
    summary_columns[2].metric("PLAYER rooms", sum(room_counts.values()))
    summary_columns[3].metric(
        "Custom usage weights",
        f"YES ({custom_weight_count})" if custom_weight_count else "NO",
    )
    payload = build_plan_config_data(
        base_tier=tier,
        room_counts=room_counts,
        usage_weights=usage_weights,
        time_limit_s=time_limit_s,
        max_layout_attempts=max_layout_attempts,
        output=DEFAULT_CONFIG.output,
    )
    payload_json = plan_config_json(payload)
    st.download_button(
        "Download plan JSON",
        data=payload_json,
        file_name="alters-plan.json",
        mime="application/json",
    )
    with st.expander("Preview plan JSON"):
        st.code(payload_json, language="json")
    return parse_plan_config(payload)


def _render_json_input() -> tuple[LoadedPlanConfig | None, bool]:
    uploaded = st.file_uploader("Upload plan JSON", type=("json",))
    if uploaded is None:
        st.info("Upload a plan JSON file to validate and optimize it.")
        return None, False

    try:
        raw = json.loads(uploaded.getvalue().decode("utf-8"))
        loaded = parse_plan_config(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        st.error(f"Invalid plan configuration: {exc}")
        return None, False

    custom_weights = isinstance(raw, dict) and bool(raw.get("usage_weights"))
    st.success("Plan configuration is valid.")
    st.write(
        {
            "Base Tier": TIER_LABELS[loaded.request.tier],
            "PLAYER room count": sum(loaded.request.room_counts.values()),
            "Time limit (seconds)": loaded.request.time_limit_s,
            "Maximum layout attempts": loaded.request.max_layout_attempts,
            "Custom usage weights": custom_weights,
        }
    )
    return loaded, custom_weights


def _write_and_render_result(result: PlanResult) -> None:
    st.subheader("Optimization result")
    metric_columns = st.columns(5)
    metric_columns[0].metric("Status", result.status)
    metric_columns[1].metric("Base", f"Tier {TIER_LABELS[result.base.tier]}")
    metric_columns[2].metric("Room packings", result.attempts)
    metric_columns[3].metric(
        "Base mass",
        result.total_mass if result.status == "FEASIBLE" else "n/a",
    )
    metric_columns[4].metric(
        "Objective F",
        f"{result.weighted_distance_score:.4f}"
        if result.weighted_distance_score is not None
        else "n/a",
    )
    st.write(result.message)
    if result.status != "FEASIBLE":
        st.error(result.message)
        st.info("No feasible layout image is available for this run.")
        st.subheader("Auditable result JSON")
        st.json(result_payload(result))
        return

    objective_columns = st.columns(4)
    objective_columns[0].metric(
        "Modified-Manhattan LB",
        f"{result.modified_manhattan_lower_bound:.4f}"
        if result.modified_manhattan_lower_bound is not None
        else "n/a",
    )
    objective_columns[1].metric(
        "Average pair distance", f"{average_pair_distance(result):.2f}"
    )
    objective_columns[2].metric(
        "Weighted average",
        f"{result.normalized_weighted_distance:.2f}"
        if result.normalized_weighted_distance is not None
        else "n/a",
    )
    objective_columns[3].metric(
        "Elevators / Corridors",
        f"{result.elevator_module_count} / {result.corridor_count}",
    )
    journey_columns = st.columns(4)
    journey_columns[0].metric("Structural feasibility", "YES")
    journey_columns[1].metric("Total Base Mass", result.total_mass)
    journey_columns[2].metric(
        "Journey Organics", result.organics_required_for_journey
    )
    journey_columns[3].metric(
        "Journey feasibility",
        "YES" if result.travel_feasible_at_full_tank else "NO",
        delta=f"capacity margin {result.organics_capacity_margin}",
    )
    if not result.global_objective_optimum_proven:
        st.info(
            "This is the best-known feasible exact candidate found by the current exact "
            "room-packing / fixed-objective decomposition; the global optimum is not proven."
        )

    with tempfile.TemporaryDirectory() as temporary_directory:
        png_path = Path(temporary_directory) / "alters-layout.png"
        render_png(result, png_path)
        png_bytes = png_path.read_bytes()
    svg = render_svg(result)
    serialized = json.dumps(result_payload(result), indent=2) + "\n"

    st.subheader("Optimized Base layout")
    st.image(png_bytes, caption="Color-coded optimized base layout", width="stretch")
    st.markdown("**Effective room usage weights**")
    st.dataframe(
        [
            {
                "Instance": module.instance_id,
                "Module": MODULE_BY_KEY[module.module_key].name,
                "Weight": result.room_usage_weights[module.instance_id],
            }
            for module in result.modules
            if MODULE_BY_KEY[module.module_key].authority is not PlacementAuthority.SOLVER
        ],
        hide_index=True,
        width="stretch",
    )
    download_columns = st.columns(3)
    with download_columns[0]:
        st.download_button(
            "Download layout JSON", serialized, "alters-layout.json", "application/json"
        )
    with download_columns[1]:
        st.download_button("Download layout SVG", svg, "alters-layout.svg", "image/svg+xml")
    with download_columns[2]:
        st.download_button("Download layout PNG", png_bytes, "alters-layout.png", "image/png")
    st.subheader("Auditable result JSON")
    st.json(result_payload(result))


st.set_page_config(page_title="The Alters Base Planner", layout="wide")
st.title("The Alters Base Planner")
st.caption(
    "Configure rooms and per-plan traffic heuristics, then run the same exact planner "
    "used by the CLI."
)

input_method = st.radio(
    "Input method",
    options=("Form", "JSON file"),
    horizontal=True,
)

loaded_config: LoadedPlanConfig | None
if input_method == "Form":
    loaded_config = _render_form_input()
else:
    loaded_config, _custom_weights = _render_json_input()

current_signature = (
    _request_signature(loaded_config.request) if loaded_config is not None else None
)
if st.button("Optimize layout", type="primary", disabled=loaded_config is None):
    if loaded_config is None:
        st.error("Provide a valid plan configuration before optimizing.")
    else:
        st.session_state.pop("last_plan_result", None)
        st.session_state.pop("last_plan_signature", None)
        with st.spinner("Running exact layout optimization..."):
            try:
                plan_result = solve_plan(loaded_config.request)
            except (ValueError, RuntimeError, AssertionError) as exc:
                st.error(f"Planner failed: {exc}")
            else:
                st.session_state["last_plan_result"] = plan_result
                st.session_state["last_plan_signature"] = current_signature

stored_result = st.session_state.get("last_plan_result")
stored_signature = st.session_state.get("last_plan_signature")
if stored_result is not None:
    if current_signature != stored_signature:
        st.info("Configuration changed. Run Optimize layout again.")
    else:
        _write_and_render_result(cast(PlanResult, stored_result))
