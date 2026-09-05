from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .catalog import CONFIGURABLE_MODULES, MANDATORY_MODULES
from .models import PlanRequest

_CONFIGURABLE_KEYS = {m.key for m in CONFIGURABLE_MODULES}
_MANDATORY_KEYS = {m.key for m in MANDATORY_MODULES}


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


def load_plan_config(path: str | Path) -> LoadedPlanConfig:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))

    tier = int(raw.get("base_tier", 2))
    if tier not in (1, 2, 3, 4):
        raise ValueError("base_tier must be one of 1, 2, 3, 4")

    room_counts_raw = raw.get("rooms", {})
    if not isinstance(room_counts_raw, dict):
        raise ValueError("rooms must be a JSON object mapping module keys to counts")

    unknown = sorted(set(room_counts_raw) - _CONFIGURABLE_KEYS - _MANDATORY_KEYS)
    if unknown:
        raise ValueError(f"Unknown room keys: {', '.join(unknown)}")

    mandatory_requested = sorted(set(room_counts_raw) & _MANDATORY_KEYS)
    if mandatory_requested:
        raise ValueError(
            "Mandatory rooms are added automatically and must not be configured: "
            + ", ".join(mandatory_requested)
        )

    room_counts = {
        key: _require_non_negative_int(value, f"rooms.{key}")
        for key, value in room_counts_raw.items()
    }

    solver = raw.get("solver", {})
    if not isinstance(solver, dict):
        raise ValueError("solver must be a JSON object")

    objective = str(solver.get("objective", "weighted_pair_distance"))
    if objective != "weighted_pair_distance":
        raise ValueError("solver.objective currently must be weighted_pair_distance")

    time_limit_s = float(solver.get("time_limit_s", 15.0))
    max_layout_attempts = int(solver.get("max_layout_attempts", 20))
    if time_limit_s <= 0:
        raise ValueError("solver.time_limit_s must be > 0")
    if max_layout_attempts <= 0:
        raise ValueError("solver.max_layout_attempts must be > 0")

    output_raw = raw.get("output", {})
    if not isinstance(output_raw, dict):
        raise ValueError("output must be a JSON object")
    output = OutputConfig(
        svg=Path(str(output_raw.get("svg", "layout.svg"))),
        png=Path(str(output_raw.get("png", "layout.png"))),
        json=Path(str(output_raw.get("json", "layout.json"))),
    )

    return LoadedPlanConfig(
        request=PlanRequest(
            tier=tier,
            room_counts=room_counts,
            objective=objective,
            time_limit_s=time_limit_s,
            max_layout_attempts=max_layout_attempts,
        ),
        output=output,
    )
