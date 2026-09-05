import json

import pytest

from alters_base_planner.config import load_plan_config


def test_load_plan_config(tmp_path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "base_tier": 3,
                "rooms": {"workshop": 2, "dormitory": 1, "small_storage": 0},
                "solver": {
                    "objective": "lexicographic_access",
                    "min_elevators": 3,
                    "max_elevators": 9,
                    "time_limit_s": 5,
                    "max_layout_attempts": 7,
                },
                "output": {"svg": "out/layout.svg", "json": "out/layout.json"},
            }
        ),
        encoding="utf-8",
    )
    loaded = load_plan_config(path)
    assert loaded.request.tier == 3
    assert loaded.request.room_counts["workshop"] == 2
    assert loaded.request.objective == "lexicographic_access"
    assert loaded.request.min_elevators == 3
    assert loaded.request.max_elevators == 9
    assert loaded.output.svg.as_posix() == "out/layout.svg"


def test_max_elevators_cannot_be_below_minimum(tmp_path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "base_tier": 2,
                "rooms": {},
                "solver": {"min_elevators": 4, "max_elevators": 3},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="max_elevators"):
        load_plan_config(path)


def test_mandatory_rooms_cannot_be_configured(tmp_path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"base_tier": 1, "rooms": {"airlock": 2}}), encoding="utf-8")
    with pytest.raises(ValueError, match="Mandatory rooms"):
        load_plan_config(path)


def test_unknown_room_key_is_rejected(tmp_path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"base_tier": 1, "rooms": {"teleporter": 1}}), encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown room keys"):
        load_plan_config(path)
