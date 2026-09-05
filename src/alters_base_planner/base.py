from __future__ import annotations

import json
from pathlib import Path

from .models import BaseGeometry

_DATA_PATH = Path(__file__).with_name("data") / "base_grids.json"


def _load_builtin_profiles() -> dict[str, object]:
    return json.loads(_DATA_PATH.read_text(encoding="utf-8"))


def _cells_from_row_spans(
    width: int, height: int, row_spans: list[list[int]]
) -> frozenset[tuple[int, int]]:
    if len(row_spans) != height:
        raise ValueError(f"Expected {height} row spans, got {len(row_spans)}")
    cells: set[tuple[int, int]] = set()
    for y, span in enumerate(row_spans):
        if len(span) != 2:
            raise ValueError(f"Invalid row span at y={y}: {span!r}")
        x0, x1 = (int(span[0]), int(span[1]))
        if x0 < 0 or x1 < x0 or x1 >= width:
            raise ValueError(f"Invalid row span at y={y}: {span!r}")
        for x in range(x0, x1 + 1):
            cells.add((x, y))
    return frozenset(cells)


def _cells_from_rect(rect: list[int], allowed: frozenset[tuple[int, int]]) -> frozenset[tuple[int, int]]:
    if len(rect) != 4:
        raise ValueError(f"Invalid blocked_rect: {rect!r}")
    x, y, width, height = map(int, rect)
    return frozenset(
        (xx, yy)
        for xx in range(x, x + width)
        for yy in range(y, y + height)
        if (xx, yy) in allowed
    )


def builtin_base(tier: int) -> BaseGeometry:
    raw = _load_builtin_profiles()
    tiers = raw["tiers"]
    profile = tiers.get(str(tier))
    if profile is None:
        raise ValueError(f"Unsupported base tier: {tier}")

    width = int(profile["width"])
    height = int(profile["height"])
    allowed = _cells_from_row_spans(width, height, profile["row_spans"])
    blocked = _cells_from_rect(profile["blocked_rect"], allowed)

    return BaseGeometry(
        tier=tier,
        width=width,
        height=height,
        allowed_cells=allowed,
        blocked_cells=blocked,
        organics_capacity=int(profile["organics_capacity"]),
        source=str(profile.get("source", "builtin-json")),
        verified=bool(profile.get("verified", False)),
        note=str(profile.get("note", "")),
    )


def load_base_json(path: str | Path) -> BaseGeometry:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    width = int(raw["width"])
    height = int(raw["height"])

    if "allowed_cells" in raw:
        allowed = frozenset(tuple(map(int, p)) for p in raw["allowed_cells"])
    elif "row_spans" in raw:
        allowed = _cells_from_row_spans(width, height, raw["row_spans"])
    else:
        raise ValueError("Base geometry JSON requires allowed_cells or row_spans")

    if "blocked_cells" in raw:
        blocked = frozenset(tuple(map(int, p)) for p in raw.get("blocked_cells", []))
    elif "blocked_rect" in raw:
        blocked = _cells_from_rect(raw["blocked_rect"], allowed)
    else:
        blocked = frozenset()

    if not blocked <= allowed:
        raise ValueError("blocked_cells must be a subset of allowed_cells")

    return BaseGeometry(
        tier=int(raw["tier"]),
        width=width,
        height=height,
        allowed_cells=allowed,
        blocked_cells=blocked,
        organics_capacity=int(raw.get("organics_capacity", 0)),
        source=str(raw.get("source", "custom-json")),
        verified=bool(raw.get("verified", False)),
        note=str(raw.get("note", "")),
    )


def export_base_json(base: BaseGeometry) -> str:
    payload = {
        "tier": base.tier,
        "width": base.width,
        "height": base.height,
        "organics_capacity": base.organics_capacity,
        "source": base.source,
        "verified": base.verified,
        "note": base.note,
        "allowed_cells": sorted([list(c) for c in base.allowed_cells]),
        "blocked_cells": sorted([list(c) for c in base.blocked_cells]),
    }
    return json.dumps(payload, indent=2)
