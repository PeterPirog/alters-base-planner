from __future__ import annotations

import json
from pathlib import Path

from .models import BaseGeometry

# Public sources document tier progression and organics capacities but not an exact
# machine-readable grid. These masks are conservative built-in approximations.
# The solver is geometry-agnostic: exact masks can be loaded from JSON without
# changing optimization code.
_TIER_META = {
    1: (22, 12, 300),
    2: (26, 14, 450),
    3: (30, 16, 700),
    4: (34, 18, 800),
}


def _rounded_mask(width: int, height: int) -> frozenset[tuple[int, int]]:
    cx = (width - 1) / 2
    cy = (height - 1) / 2
    rx = width / 2
    ry = height / 2
    cells = set()
    for y in range(height):
        for x in range(width):
            # Slightly squared ellipse to resemble the wheel's usable build envelope.
            nx = abs((x - cx) / rx)
            ny = abs((y - cy) / ry)
            if nx**3.2 + ny**3.2 <= 0.95:
                cells.add((x, y))
    return frozenset(cells)


def builtin_base(tier: int) -> BaseGeometry:
    if tier not in _TIER_META:
        raise ValueError(f"Unsupported base tier: {tier}")
    width, height, capacity = _TIER_META[tier]
    allowed = _rounded_mask(width, height)
    # Organics tank: intentionally offset from exact center, matching the game's
    # immovable central obstacle concept. Exact cells can be replaced via JSON.
    core_w, core_h = 6, 3
    core_x = width // 2 - 3
    core_y = height // 2
    blocked = frozenset(
        (x, y)
        for x in range(core_x, core_x + core_w)
        for y in range(core_y, core_y + core_h)
        if (x, y) in allowed
    )
    return BaseGeometry(tier, width, height, allowed, blocked, capacity)


def load_base_json(path: str | Path) -> BaseGeometry:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return BaseGeometry(
        tier=int(raw["tier"]),
        width=int(raw["width"]),
        height=int(raw["height"]),
        allowed_cells=frozenset(tuple(p) for p in raw["allowed_cells"]),
        blocked_cells=frozenset(tuple(p) for p in raw.get("blocked_cells", [])),
        organics_capacity=int(raw.get("organics_capacity", 0)),
        source=str(raw.get("source", "custom-json")),
    )


def export_base_json(base: BaseGeometry) -> str:
    payload = {
        "tier": base.tier,
        "width": base.width,
        "height": base.height,
        "organics_capacity": base.organics_capacity,
        "source": base.source,
        "allowed_cells": sorted([list(c) for c in base.allowed_cells]),
        "blocked_cells": sorted([list(c) for c in base.blocked_cells]),
    }
    return json.dumps(payload, indent=2)
