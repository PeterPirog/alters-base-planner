import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

import alters_base_planner.engine as engine_module
from alters_base_planner.catalog import MODULE_BY_KEY, PLAYER_MODULES, SYSTEM_MODULES
from alters_base_planner.models import BaseGeometry, ModulePlacement, PlanRequest, PlanResult

APP_PATH = Path(__file__).parents[1] / "app.py"


def _feasible_result() -> PlanResult:
    base = BaseGeometry(
        tier=2,
        width=4,
        height=1,
        allowed_cells=frozenset((x, 0) for x in range(4)),
        blocked_cells=frozenset(),
        organics_capacity=300,
        source="streamlit-test",
        verified=True,
    )
    airlock = MODULE_BY_KEY["airlock"]
    return PlanResult(
        status="FEASIBLE",
        base=base,
        modules=[
            ModulePlacement(
                "airlock-1",
                "airlock",
                0,
                0,
                airlock.width,
                airlock.height,
            )
        ],
        objective_value=0.0,
        weighted_distance_score=0.0,
        objective_scale=1,
        scaled_objective_value=0,
        scaled_modified_manhattan_lower_bound=0,
        modified_manhattan_lower_bound=0.0,
        room_usage_weights={"airlock-1": 1.0},
        room_mass=4,
        total_mass=4,
        organics_required_for_journey=4,
        organics_capacity_margin=296,
        travel_feasible_at_full_tank=True,
        global_objective_optimum_proven=True,
    )


def test_form_ui_renders_required_controls_without_solving() -> None:
    app = AppTest.from_file(APP_PATH).run(timeout=20)

    assert not app.exception
    assert app.radio[0].value == "Form"
    assert app.subheader[0].value == "Plan settings"
    tier_control = app.radio(key="form_base_tier")
    assert tier_control.options == [
        "Base Tier I",
        "Base Tier II",
        "Base Tier III",
        "Base Tier IV",
    ]
    assert tier_control.value == 2
    time_control = app.number_input(key="form_time_limit_s")
    assert time_control.label == "Optimization time limit (seconds)"
    assert time_control.value == 60.0
    assert time_control.min == 1.0
    for spec in SYSTEM_MODULES:
        control = app.number_input(key=f"system_count__{spec.key}")
        assert control.value == 1
        assert control.disabled

    assert all(app.number_input(key=f"room_count__{spec.key}") for spec in PLAYER_MODULES)
    assert app.number_input(key="room_count__recycler").max == 1.0
    assert app.number_input(key="room_count__rapidium_ark").max == 5.0
    text_inputs = {control.label: control for control in app.text_input}
    assert text_inputs["Corridor"].value == "AUTO"
    assert text_inputs["Elevator"].value == "AUTO"
    assert app.dataframe[0].value.shape == (28, 5)
    assert list(app.dataframe[0].value.columns) == [
        "Module",
        "Authority",
        "Count",
        "Default weight",
        "Weight",
    ]
    summary = {metric.label: metric.value for metric in app.metric}
    assert summary == {
        "Selected Base Tier": "II",
        "SYSTEM rooms": "8",
        "PLAYER rooms": "10",
        "Custom usage weights": "NO",
    }
    optimize = next(button for button in app.button if button.label == "Optimize layout")
    assert optimize.value is False
    assert not optimize.disabled
    assert app.get("download_button")[0].label == "Download plan JSON"


def test_tier_and_time_change_preserve_room_counts_and_usage_weight_state() -> None:
    app = AppTest.from_file(APP_PATH).run(timeout=20)
    app.number_input(key="room_count__workshop").set_value(2)
    app.session_state["form_usage_weights"]["workshop"] = 0.42
    app.radio(key="form_base_tier").set_value("Base Tier IV")
    app.number_input(key="form_time_limit_s").set_value(120.0)

    app.run(timeout=20)

    assert not app.exception
    assert app.radio(key="form_base_tier").value == 4
    assert app.number_input(key="form_time_limit_s").value == 120.0
    assert app.number_input(key="room_count__workshop").value == 2
    assert app.session_state["form_usage_weights"]["workshop"] == 0.42
    summary = {metric.label: metric.value for metric in app.metric}
    assert summary["Custom usage weights"] == "YES (1)"
    generated_plan = json.loads(app.code[0].value)
    assert generated_plan["base_tier"] == 4
    assert generated_plan["solver"]["time_limit_s"] == 120.0

    reset = next(button for button in app.button if button.label == "Reset weights to defaults")
    reset.click().run(timeout=20)
    assert not app.exception
    assert app.session_state["form_usage_weights"]["workshop"] == 0.9
    assert app.number_input(key="room_count__workshop").value == 2
    assert app.number_input(key="form_time_limit_s").value == 120.0
    summary = {metric.label: metric.value for metric in app.metric}
    assert summary["Custom usage weights"] == "NO"


def test_json_mode_validates_uploaded_config_without_solving(tmp_path: Path) -> None:
    config_path = tmp_path / "uploaded-plan.json"
    config_path.write_text(
        json.dumps(
            {
                "base_tier": 3,
                "rooms": {"workshop": 1},
                "usage_weights": {"workshop": 0.42},
                "solver": {"time_limit_s": 45},
            }
        ),
        encoding="utf-8",
    )
    app = AppTest.from_file(APP_PATH).run(timeout=20)
    app.radio[0].set_value("JSON file").run(timeout=20)

    app.file_uploader[0].upload(
        config_path.name,
        config_path.read_bytes(),
        "application/json",
    ).run(timeout=20)

    assert not app.exception
    assert app.success[0].value == "Plan configuration is valid."
    summary = json.loads(app.json[0].value)
    assert summary["Base Tier"] == "III"
    assert summary["Time limit (seconds)"] == 45.0
    optimize = next(button for button in app.button if button.label == "Optimize layout")
    assert not optimize.disabled


def test_feasible_result_persists_and_is_hidden_when_configuration_changes(
    monkeypatch,
) -> None:
    requests: list[PlanRequest] = []

    def fake_solve(request: PlanRequest) -> PlanResult:
        requests.append(request)
        return _feasible_result()

    monkeypatch.setattr(engine_module, "solve_plan", fake_solve)
    app = AppTest.from_file(APP_PATH).run(timeout=20)
    optimize = next(button for button in app.button if button.label == "Optimize layout")
    optimize.click().run(timeout=30)

    assert not app.exception
    assert len(requests) == 1
    assert app.session_state["last_plan_result"].status == "FEASIBLE"
    assert "Optimized Base layout" in [heading.value for heading in app.subheader]
    assert app.image[0].value[0]
    assert app.image[0].captions == ["Color-coded optimized base layout"]
    download_labels = {button.label for button in app.get("download_button")}
    assert {
        "Download layout JSON",
        "Download layout SVG",
        "Download layout PNG",
    } <= download_labels

    app.run(timeout=20)
    assert not app.exception
    assert len(requests) == 1
    assert app.image[0].value[0]

    next(
        button
        for button in app.get("download_button")
        if button.label == "Download layout PNG"
    ).click().run(timeout=20)
    assert not app.exception
    assert len(requests) == 1
    assert app.image[0].value[0]

    app.number_input(key="form_time_limit_s").set_value(120.0).run(timeout=20)
    assert not app.exception
    assert not app.image
    assert "Configuration changed. Run Optimize layout again." in [
        message.value for message in app.info
    ]


def test_non_feasible_result_does_not_render_a_layout_image(monkeypatch) -> None:
    result = _feasible_result()
    result.status = "INFEASIBLE"
    result.modules = []
    result.room_usage_weights = {}
    result.message = "No feasible layout."
    monkeypatch.setattr(engine_module, "solve_plan", lambda request: result)

    app = AppTest.from_file(APP_PATH).run(timeout=20)
    optimize = next(button for button in app.button if button.label == "Optimize layout")
    optimize.click().run(timeout=20)

    assert not app.exception
    assert not app.image
    assert "No feasible layout image is available for this run." in [
        message.value for message in app.info
    ]
