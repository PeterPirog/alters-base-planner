from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .catalog import CONFIGURABLE_MODULES, MANDATORY_MODULES, MODULE_BY_KEY, SOLVER_MODULES
from .models import PlanRequest

_CONFIGURABLE_KEYS = {m.key for m in CONFIGURABLE_MODULES}
_MANDATORY_KEYS = {m.key for m in MANDATORY_MODULES}
_SOLVER_KEYS = {m.key for m in SOLVER_MODULES}
_SOLVER_MANAGED_KEYS = _SOLVER_KEYS | {f"{key}s" for key in _SOLVER_KEYS}
_TOP_LEVEL_KEYS = {"$schema", "base_tier", "rooms", "solver", "output"}
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


def load_plan_config(path: str | Path) -> LoadedPlanConfig:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
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
        raise ValueError("rooms must be a JSON object mapping module keys to counts")

    solver_managed_requested = sorted(set(room_counts_raw) & _SOLVER_MANAGED_KEYS)
    if solver_managed_requested:
        raise ValueError(
            "Corridor and Elevator counts are solver-managed and must not be configured by the "
            "player. Remove: " + ", ".join(solver_managed_requested)
        )

    unknown = sorted(set(room_counts_raw) - _CONFIGURABLE_KEYS - _MANDATORY_KEYS)
    if unknown:
        raise ValueError(f"Unknown room keys: {', '.join(unknown)}")

    mandatory_requested = sorted(set(room_counts_raw) & _MANDATORY_KEYS)
    if mandatory_requested:
        raise ValueError(
            "Mandatory rooms are added automatically and must not be configured: "
            + ", ".join(mandatory_requested)
        )

    room_counts: dict[str, int] = {}
    for key, value in room_counts_raw.items():
        count = _require_non_negative_int(value, f"rooms.{key}")
        max_count = MODULE_BY_KEY[key].max_count
        if max_count is not None and count > max_count:
            raise ValueError(f"rooms.{key} must be <= {max_count}")
        room_counts[key] = count

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
    output = OutputConfig(svg=Path(svg), png=Path(png), json=Path(json_path))

    return LoadedPlanConfig(
        request=PlanRequest(
            tier=tier,
            room_counts=room_counts,
            objective="weighted_pair_distance",
            time_limit_s=time_limit_s,
            max_layout_attempts=max_layout_attempts,
        ),
        output=output,
    )
