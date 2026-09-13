import json
from pathlib import Path

import pytest

from alters_base_planner.catalog import (
    PLAYER_MODULES,
    SYSTEM_MODULES,
    USAGE_WEIGHTS,
    resolve_usage_weights,
)
from alters_base_planner.config import (
    build_plan_config_data,
    load_plan_config,
    parse_plan_config,
    plan_config_json,
)


def _write(tmp_path: Path, payload: object) -> Path:
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


def test_system_modules_cannot_be_configured(tmp_path) -> None:
    path = _write(tmp_path, {"base_tier": 1, "rooms": {"airlock": 2}})
    with pytest.raises(ValueError, match="SYSTEM modules"):
        load_plan_config(path)


@pytest.mark.parametrize("key", ["corridor", "elevator"])
def test_solver_modules_cannot_be_configured(tmp_path, key: str) -> None:
    path = _write(tmp_path, {"base_tier": 2, "rooms": {key: 3}})
    with pytest.raises(ValueError, match="SOLVER modules"):
        load_plan_config(path)


def test_noncanonical_plural_solver_key_is_unknown(tmp_path) -> None:
    path = _write(tmp_path, {"base_tier": 2, "rooms": {"corridors": 3}})
    with pytest.raises(ValueError, match="Unknown module keys"):
        load_plan_config(path)


def test_unknown_module_key_is_rejected(tmp_path) -> None:
    path = _write(tmp_path, {"base_tier": 1, "rooms": {"teleporter": 1}})
    with pytest.raises(ValueError, match="Unknown module keys"):
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


def test_rapidium_ark_gameplay_limit_is_enforced(tmp_path) -> None:
    path = _write(tmp_path, {"base_tier": 4, "rooms": {"rapidium_ark": 6}})
    with pytest.raises(ValueError, match=r"rooms\.rapidium_ark must be <= 5"):
        load_plan_config(path)


def _minimal_plan(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {"base_tier": 2, "rooms": {}}
    payload.update(updates)
    return payload


def test_unknown_usage_weight_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown module keys in usage_weights"):
        parse_plan_config(_minimal_plan(usage_weights={"teleporter": 0.5}))


@pytest.mark.parametrize("module_key", ["corridor", "elevator"])
def test_solver_usage_weight_override_is_rejected(module_key: str) -> None:
    with pytest.raises(ValueError, match="SOLVER modules cannot be objective endpoints"):
        parse_plan_config(_minimal_plan(usage_weights={module_key: 0.5}))


@pytest.mark.parametrize("weight", [-0.01, 1.01])
def test_out_of_range_usage_weight_is_rejected(weight: float) -> None:
    with pytest.raises(ValueError, match="finite number from 0 to 1"):
        parse_plan_config(_minimal_plan(usage_weights={"workshop": weight}))


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_usage_weight_is_rejected(weight: float) -> None:
    with pytest.raises(ValueError, match="finite number from 0 to 1"):
        parse_plan_config(_minimal_plan(usage_weights={"workshop": weight}))


def test_boolean_usage_weight_is_rejected() -> None:
    with pytest.raises(ValueError, match="finite number from 0 to 1"):
        parse_plan_config(_minimal_plan(usage_weights={"workshop": True}))


def test_omitted_usage_weights_resolve_to_independent_catalogue_defaults() -> None:
    loaded = parse_plan_config(_minimal_plan())
    effective = resolve_usage_weights(loaded.request.usage_weights)
    expected_keys = {spec.key for spec in (*SYSTEM_MODULES, *PLAYER_MODULES)}

    assert loaded.request.usage_weights == {}
    assert effective == {key: USAGE_WEIGHTS[key] for key in expected_keys}
    effective["workshop"] = 0.17
    assert USAGE_WEIGHTS["workshop"] == 0.9


def test_partial_usage_weight_override_merges_with_catalogue_defaults() -> None:
    loaded = parse_plan_config(_minimal_plan(usage_weights={"workshop": 0.42}))
    effective = resolve_usage_weights(loaded.request.usage_weights)

    assert effective["workshop"] == 0.42
    assert effective["airlock"] == USAGE_WEIGHTS["airlock"]
    assert "corridor" not in effective
    assert "elevator" not in effective


def test_ui_generated_full_weight_map_round_trips_exactly() -> None:
    effective = resolve_usage_weights({"workshop": 0.42, "airlock": 0.73})
    payload = build_plan_config_data(
        base_tier=3,
        room_counts={"workshop": 2, "recycler": 1, "rapidium_ark": 5},
        usage_weights=effective,
        time_limit_s=12.5,
        max_layout_attempts=9,
    )
    loaded = parse_plan_config(json.loads(plan_config_json(payload)))

    assert loaded.request.tier == 3
    assert loaded.request.room_counts["workshop"] == 2
    assert loaded.request.room_counts["recycler"] == 1
    assert loaded.request.room_counts["rapidium_ark"] == 5
    assert loaded.request.room_counts["materializer"] == 0
    assert set(loaded.request.room_counts) == {spec.key for spec in PLAYER_MODULES}
    assert loaded.request.usage_weights == effective
    usage_weights_payload = payload["usage_weights"]
    assert isinstance(usage_weights_payload, dict)
    assert "corridor" not in usage_weights_payload
    assert "elevator" not in usage_weights_payload


@pytest.mark.parametrize(
    ("module_key", "count", "message"),
    [("recycler", 2, "<= 1"), ("rapidium_ark", 6, "<= 5")],
)
def test_ui_plan_generator_enforces_catalogue_count_limits(
    module_key: str,
    count: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_plan_config_data(
            base_tier=2,
            room_counts={module_key: count},
            usage_weights=resolve_usage_weights(),
            time_limit_s=15.0,
            max_layout_attempts=30,
        )
