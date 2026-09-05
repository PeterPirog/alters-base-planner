from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import BaseGeometry

_DATA_DIR = Path(__file__).with_name("data")

# Gameplay capacities are metadata, not geometry. Geometry itself lives only in
# base-size1.csv ... base-size4.csv so it can be corrected without code changes.
_BUILTIN_METADATA: dict[int, dict[str, object]] = {
    1: {
        "organics_capacity": 300,
        "verified": False,
        "note": "Editable provisional Base I mask. CSV cells are the geometry source of truth.",
    },
    2: {
        "organics_capacity": 450,
        "verified": False,
        "note": "Editable provisional Base II mask. CSV cells are the geometry source of truth.",
    },
    3: {
        "organics_capacity": 700,
        "verified": False,
        "note": "Editable provisional Base III mask. CSV cells are the geometry source of truth.",
    },
    4: {
        "organics_capacity": 800,
        "verified": False,
        "note": "Editable provisional Base IV mask. CSV cells are the geometry source of truth.",
    },
}


def _read_grid_csv(
    path: str | Path,
) -> tuple[int, int, frozenset[tuple[int, int]], frozenset[tuple[int, int]]]:
    """Read an editable base mask.

    CSV format:
    - first column is row coordinate ``y``;
    - remaining header cells are x coordinates 0..width-1;
    - ``0`` = outside the usable base;
    - ``1`` = buildable cell;
    - ``X`` = immovable blocked/core cell.

    Both ``1`` and ``X`` belong to the physical base outline; only ``1`` is buildable.
    Width and height are inferred from the CSV itself.
    """

    path = Path(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    if len(rows) < 2:
        raise ValueError(f"Base CSV {path} must contain a header and at least one grid row")

    header = [cell.strip() for cell in rows[0]]
    if not header or header[0].lower() != "y":
        raise ValueError(f"Base CSV {path} first header cell must be 'y'")

    try:
        x_coordinates = [int(cell) for cell in header[1:]]
    except ValueError as exc:
        raise ValueError(f"Base CSV {path} x-coordinate headers must be integers") from exc

    width = len(x_coordinates)
    if width <= 0 or x_coordinates != list(range(width)):
        raise ValueError(f"Base CSV {path} x headers must be consecutive 0..{width - 1}")

    allowed: set[tuple[int, int]] = set()
    blocked: set[tuple[int, int]] = set()
    expected_y = 0

    for raw_row in rows[1:]:
        row = [cell.strip() for cell in raw_row]
        if len(row) != width + 1:
            raise ValueError(
                f"Base CSV {path} row {expected_y} has {len(row) - 1} cells; expected {width}"
            )
        try:
            y = int(row[0])
        except ValueError as exc:
            raise ValueError(f"Base CSV {path} row label {row[0]!r} is not an integer") from exc
        if y != expected_y:
            raise ValueError(
                f"Base CSV {path} row labels must be consecutive from 0; "
                f"expected {expected_y}, got {y}"
            )

        for x, token in enumerate(row[1:]):
            normalized = token.upper()
            if normalized not in {"0", "1", "X"}:
                raise ValueError(
                    f"Base CSV {path} invalid token {token!r} at x={x}, y={y}; use 0, 1 or X"
                )
            if normalized in {"1", "X"}:
                allowed.add((x, y))
            if normalized == "X":
                blocked.add((x, y))
        expected_y += 1

    height = expected_y
    if not allowed:
        raise ValueError(f"Base CSV {path} contains no usable/base cells")
    if not blocked:
        raise ValueError(f"Base CSV {path} must mark the immovable element with at least one X cell")

    return width, height, frozenset(allowed), frozenset(blocked)


def builtin_base(tier: int) -> BaseGeometry:
    metadata = _BUILTIN_METADATA.get(tier)
    if metadata is None:
        raise ValueError(f"Unsupported base tier: {tier}")

    path = _DATA_DIR / f"base-size{tier}.csv"
    width, height, allowed, blocked = _read_grid_csv(path)

    return BaseGeometry(
        tier=tier,
        width=width,
        height=height,
        allowed_cells=allowed,
        blocked_cells=blocked,
        organics_capacity=int(metadata["organics_capacity"]),
        source=path.name,
        verified=bool(metadata["verified"]),
        note=str(metadata["note"]),
    )


def load_base_csv(
    path: str | Path,
    *,
    tier: int,
    organics_capacity: int = 0,
    verified: bool = False,
    note: str = "",
) -> BaseGeometry:
    """Load a custom grid CSV using the same 0/1/X format as built-in tiers."""

    width, height, allowed, blocked = _read_grid_csv(path)
    return BaseGeometry(
        tier=tier,
        width=width,
        height=height,
        allowed_cells=allowed,
        blocked_cells=blocked,
        organics_capacity=organics_capacity,
        source=Path(path).name,
        verified=verified,
        note=note,
    )


def load_base_json(path: str | Path) -> BaseGeometry:
    """Legacy custom JSON loader retained for compatibility.

    Built-in Base I-IV geometry no longer uses JSON; edit base-size1.csv ...
    base-size4.csv instead.
    """

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    width = int(raw["width"])
    height = int(raw["height"])

    if "allowed_cells" not in raw:
        raise ValueError("Custom Base geometry JSON requires allowed_cells")
    allowed = frozenset(tuple(map(int, p)) for p in raw["allowed_cells"])
    blocked = frozenset(tuple(map(int, p)) for p in raw.get("blocked_cells", []))

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
