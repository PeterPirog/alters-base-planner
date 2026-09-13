import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from alters_base_planner.catalog import SYSTEM_MODULES

APP_PATH = Path(__file__).parents[1] / "app.py"


def test_form_ui_renders_required_controls_without_solving() -> None:
    app = AppTest.from_file(APP_PATH).run(timeout=20)

    assert not app.exception
    assert app.radio[0].value == "Form"
    assert app.selectbox[0].options == [
        "Base Tier I",
        "Base Tier II",
        "Base Tier III",
        "Base Tier IV",
    ]
    for spec in SYSTEM_MODULES:
        control = app.number_input(key=f"system_count__{spec.key}")
        assert control.value == 1
        assert control.disabled

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


def test_tier_change_preserves_room_counts_and_usage_weight_state() -> None:
    app = AppTest.from_file(APP_PATH).run(timeout=20)
    app.number_input(key="room_count__workshop").set_value(2)
    app.session_state["form_usage_weights"]["workshop"] = 0.42
    app.selectbox[0].set_value("Base Tier III")

    app.run(timeout=20)

    assert not app.exception
    assert app.selectbox[0].value == 3
    assert app.number_input(key="room_count__workshop").value == 2
    assert app.session_state["form_usage_weights"]["workshop"] == 0.42
    summary = {metric.label: metric.value for metric in app.metric}
    assert summary["Custom usage weights"] == "YES (1)"

    reset = next(button for button in app.button if button.label == "Reset weights to defaults")
    reset.click().run(timeout=20)
    assert not app.exception
    assert app.session_state["form_usage_weights"]["workshop"] == 0.9
    assert app.number_input(key="room_count__workshop").value == 2
    summary = {metric.label: metric.value for metric in app.metric}
    assert summary["Custom usage weights"] == "NO"


def test_json_mode_validates_uploaded_config_without_solving(tmp_path: Path) -> None:
    config_path = tmp_path / "uploaded-plan.json"
    config_path.write_text(
        json.dumps(
            {
                "base_tier": 2,
                "rooms": {"workshop": 1},
                "usage_weights": {"workshop": 0.42},
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
    optimize = next(button for button in app.button if button.label == "Optimize layout")
    assert not optimize.disabled
