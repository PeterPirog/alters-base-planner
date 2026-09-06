import json

import pytest

from alters_base_planner.config import load_plan_config


def _write(tmp_path, payload) -> object:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_plan_config(tmp_path) -> None:
    path = _write(
        tmp_path,
        {
            "base_tier": 3,
            "rooms": {"workshop": 2, "dormitory": 1, "small_storage": 0},
            "solver": {
                "objective": "weighted_pair_distance",
                "time_limit_s": 5,
                "max_layout_attempts": 7,
            },
            "output": {"svg": "out/layout.svg", "json": "out/layout.json"},
        },
    )
    loaded = load_plan_config(path)
    assert loaded.request.tier == 3
    assert loaded.request.room_counts["workshop"] == 2
    assert loaded.request.objective == "weighted_pair_distance"
    assert loaded.output.svg.as_posix() == "out/layout.svg"


def test_unknown_objective_is_rejected(tmp_path) -> None:
    path = _write(
        tmp_path,
        {
            "base_tier": 2,
            "rooms": {},
            "solver": {"objective": "minimum_elevators"},
        },
    )
    with pytest.raises(ValueError, match="weighted_pair_distance"):
        load_plan_config(path)


def test_mandatory_rooms_cannot_be_configured(tmp_path) -> None:
    path = _write(tmp_path, {"base_tier": 1, "rooms": {"airlock": 2}})
    with pytest.raises(ValueError, match="Mandatory rooms"):
        load_plan_config(path)


@pytest.mark.parametrize("key", ["corridor", "corridors", "elevator", "elevators"])
def test_solver_managed_utilities_cannot_be_configured(tmp_path, key: str) -> None:
    path = _write(tmp_path, {"base_tier": 2, "rooms": {key: 3}})
    with pytest.raises(ValueError, match="solver-managed"):
        load_plan_config(path)


def test_unknown_room_key_is_rejected(tmp_path) -> None:
    path = _write(tmp_path, {"base_tier": 1, "rooms": {"teleporter": 1}})
    with pytest.raises(ValueError, match="Unknown room keys"):
        load_plan_config(path)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"rooms": {}}, "Missing required"),
        ({"base_tier": 2}, "Missing required"),
        ({"base_tier": True, "rooms": {}}, "base_tier"),
        ({"base_tier": 2, "rooms": {}, "unexpected": 1}, "Unknown top-level"),
        (
            {"base_tier": 2, "rooms": {}, "solver": {"time_limit_s": 1, "typo": 1}},
            "Unknown solver",
        ),
        (
            {"base_tier": 2, "rooms": {}, "output": {"json": ""}},
            "output.json",
        ),
        (
            {"base_tier": 2, "rooms": {}, "solver": {"max_layout_attempts": 2.5}},
            "positive integer",
        ),
    ],
)
def test_schema_equivalent_runtime_validation(tmp_path, payload, message: str) -> None:
    path = _write(tmp_path, payload)
    with pytest.raises(ValueError, match=message):
        load_plan_config(path)


def test_non_finite_time_limit_is_rejected(tmp_path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(
        '{"base_tier": 2, "rooms": {}, "solver": {"time_limit_s": NaN}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="finite number"):
        load_plan_config(path)


def test_recycler_gameplay_limit_is_enforced(tmp_path) -> None:
    path = _write(tmp_path, {"base_tier": 2, "rooms": {"recycler": 2}})
    with pytest.raises(ValueError, match=r"rooms\.recycler must be <= 1"):
        load_plan_config(path)
