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
                    "objective": "weighted_pair_distance",
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
    assert loaded.request.objective == "weighted_pair_distance"
    assert loaded.output.svg.as_posix() == "out/layout.svg"


def test_unknown_objective_is_rejected(tmp_path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "base_tier": 2,
                "rooms": {},
                "solver": {"objective": "minimum_elevators"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="weighted_pair_distance"):
        load_plan_config(path)


def test_mandatory_rooms_cannot_be_configured(tmp_path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"base_tier": 1, "rooms": {"airlock": 2}}), encoding="utf-8")
    with pytest.raises(ValueError, match="Mandatory rooms"):
        load_plan_config(path)


@pytest.mark.parametrize("key", ["corridor", "corridors", "elevator", "elevators"])
def test_solver_managed_utilities_cannot_be_configured(tmp_path, key: str) -> None:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"base_tier": 2, "rooms": {key: 3}}), encoding="utf-8")
    with pytest.raises(ValueError, match="solver-managed"):
        load_plan_config(path)


def test_unknown_room_key_is_rejected(tmp_path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"base_tier": 1, "rooms": {"teleporter": 1}}), encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown room keys"):
        load_plan_config(path)
