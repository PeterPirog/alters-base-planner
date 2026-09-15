from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .catalog import (
    MODULE_BY_KEY,
    PLAYER_MODULES,
    SOLVER_MODULES,
    SYSTEM_MODULES,
    resolve_usage_weights,
)
from .models import PlanRequest

_PLAYER_KEYS = {module.key for module in PLAYER_MODULES}
_SYSTEM_KEYS = {module.key for module in SYSTEM_MODULES}
_SOLVER_KEYS = {module.key for module in SOLVER_MODULES}
_TOP_LEVEL_KEYS = {
    "$schema",
    "base_tier",
    "rooms",
    "usage_weights",
    "solver",
    "output",
}
_SOLVER_CONFIG_KEYS = {"objective", "time_limit_s", "max_layout_attempts"}
_OUTPUT_KEYS = {"svg", "png", "json"}


@dataclass(frozen=True, slots=True)
class OutputConfig:
    svg: Path = Path("layout.svg")
    png: Path = Path("layout.png")
    json: Path = Path("layout.json")


@dataclass(frozen=True, slots=True)
class LoadedPlanConfig:
    request: PlanRequest
    output: OutputConfig


def _require_non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _require_positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _require_positive_finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number > 0")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{field} must be a finite number > 0")
    return result


def _require_non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _reject_unknown_keys(raw: dict[str, object], allowed: set[str], field: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"Unknown {field} keys: {', '.join(unknown)}")


def parse_plan_config(raw: object) -> LoadedPlanConfig:
    """Validate an already-decoded plan configuration."""

    if not isinstance(raw, dict):
        raise ValueError("Plan configuration root must be a JSON object")

    _reject_unknown_keys(raw, _TOP_LEVEL_KEYS, "top-level")
    missing = sorted({"base_tier", "rooms"} - set(raw))
    if missing:
        raise ValueError(f"Missing required configuration keys: {', '.join(missing)}")

    if "$schema" in raw:
        _require_non_empty_string(raw["$schema"], "$schema")

    tier = _require_positive_int(raw["base_tier"], "base_tier")
    if tier not in (1, 2, 3, 4):
        raise ValueError("base_tier must be one of 1, 2, 3, 4")

    room_counts_raw = raw["rooms"]
    if not isinstance(room_counts_raw, dict):
        raise ValueError("rooms must be a JSON object mapping PLAYER module keys to counts")

    solver_requested = sorted(set(room_counts_raw) & _SOLVER_KEYS)
    if solver_requested:
        raise ValueError(
            "SOLVER modules are generated automatically and must not be configured: "
            + ", ".join(solver_requested)
        )

    system_requested = sorted(set(room_counts_raw) & _SYSTEM_KEYS)
    if system_requested:
        raise ValueError(
            "SYSTEM modules are added exactly once automatically and must not be configured: "
            + ", ".join(system_requested)
        )

    unknown = sorted(set(room_counts_raw) - _PLAYER_KEYS - _SYSTEM_KEYS - _SOLVER_KEYS)
    if unknown:
        raise ValueError(f"Unknown module keys: {', '.join(unknown)}")

    room_counts: dict[str, int] = {}
    for key, value in room_counts_raw.items():
        count = _require_non_negative_int(value, f"rooms.{key}")
        max_count = MODULE_BY_KEY[key].max_count
        if max_count is not None and count > max_count:
            raise ValueError(f"rooms.{key} must be <= {max_count}")
        room_counts[key] = count

    usage_weights_raw = raw.get("usage_weights", {})
    if not isinstance(usage_weights_raw, dict):
        raise ValueError("usage_weights must be a JSON object mapping module keys to weights")
    effective_usage_weights = resolve_usage_weights(usage_weights_raw)
    usage_weight_overrides = {
        key: effective_usage_weights[key] for key in usage_weights_raw
    }

    solver = raw.get("solver", {})
    if not isinstance(solver, dict):
        raise ValueError("solver must be a JSON object")
    _reject_unknown_keys(solver, _SOLVER_CONFIG_KEYS, "solver")

    objective = solver.get("objective", "weighted_pair_distance")
    if objective != "weighted_pair_distance":
        raise ValueError("solver.objective currently must be weighted_pair_distance")

    time_limit_s = _require_positive_finite_number(
        solver.get("time_limit_s", 15.0), "solver.time_limit_s"
    )
    max_layout_attempts = _require_positive_int(
        solver.get("max_layout_attempts", 20), "solver.max_layout_attempts"
    )

    output_raw = raw.get("output", {})
    if not isinstance(output_raw, dict):
        raise ValueError("output must be a JSON object")
    _reject_unknown_keys(output_raw, _OUTPUT_KEYS, "output")

    svg = _require_non_empty_string(output_raw.get("svg", "layout.svg"), "output.svg")
    png = _require_non_empty_string(output_raw.get("png", "layout.png"), "output.png")
    json_path = _require_non_empty_string(output_raw.get("json", "layout.json"), "output.json")

    return LoadedPlanConfig(
        request=PlanRequest(
            tier=tier,
            room_counts=room_counts,
            usage_weights=usage_weight_overrides,
            objective="weighted_pair_distance",
            time_limit_s=time_limit_s,
            max_layout_attempts=max_layout_attempts,
        ),
        output=OutputConfig(svg=Path(svg), png=Path(png), json=Path(json_path)),
    )


def load_plan_config(path: str | Path) -> LoadedPlanConfig:
    """Load a plan JSON file and delegate validation to the canonical parser."""

    path = Path(path)
    return parse_plan_config(json.loads(path.read_text(encoding="utf-8")))


def build_plan_config_data(
    *,
    base_tier: int,
    room_counts: dict[str, int],
    usage_weights: dict[str, float],
    time_limit_s: float,
    max_layout_attempts: int,
    output: OutputConfig | None = None,
) -> dict[str, object]:
    """Build a stable, canonical plan payload from form values."""

    invalid_room_keys = sorted(set(room_counts) - _PLAYER_KEYS)
    if invalid_room_keys:
        raise ValueError(f"Form room counts contain non-PLAYER keys: {invalid_room_keys}")

    effective_usage_weights = resolve_usage_weights(usage_weights)
    output = output or OutputConfig()
    payload: dict[str, object] = {
        "$schema": "./plan.schema.json",
        "base_tier": base_tier,
        "rooms": {
            key: int(room_counts.get(key, 0))
            for key in sorted(_PLAYER_KEYS)
        },
        "usage_weights": {
            key: effective_usage_weights[key]
            for key in sorted(effective_usage_weights)
        },
        "solver": {
            "objective": "weighted_pair_distance",
            "time_limit_s": float(time_limit_s),
            "max_layout_attempts": int(max_layout_attempts),
        },
        "output": {
            "svg": str(output.svg),
            "png": str(output.png),
            "json": str(output.json),
        },
    }
    parse_plan_config(payload)
    return payload


def plan_config_json(payload: object) -> str:
    """Serialize a canonical plan payload for reproducible download."""

    parse_plan_config(payload)
    return json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
