from __future__ import annotations

from html import escape

from .catalog import MODULE_BY_KEY
from .models import PlanResult


PALETTE = {
    "core": "#5b8ff9",
    "work": "#61d9a6",
    "wellbeing": "#f6bd16",
    "storage": "#9270ca",
    "utility": "#6dc8ec",
}


def render_svg(result: PlanResult, cell_w: int = 32, cell_h: int = 24) -> str:
    base = result.base
    width_px = base.width * cell_w
    height_px = base.height * cell_h
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px}" height="{height_px}" viewBox="0 0 {width_px} {height_px}">',
        '<rect width="100%" height="100%" fill="#10151c"/>',
    ]

    for x, y in base.allowed_cells:
        fill = "#202a36" if (x, y) not in base.blocked_cells else "#673c3c"
        parts.append(
            f'<rect x="{x*cell_w}" y="{y*cell_h}" width="{cell_w}" height="{cell_h}" fill="{fill}" stroke="#344252" stroke-width="1"/>'
        )

    for utility in result.utilities:
        fill = "#94a3b8" if utility.kind == "corridor" else "#e879f9"
        parts.append(
            f'<rect x="{utility.x*cell_w}" y="{utility.y*cell_h}" width="{utility.width*cell_w}" height="{cell_h}" rx="3" fill="{fill}" stroke="#e2e8f0" stroke-width="1"/>'
        )
        label = "C" if utility.kind == "corridor" else "E"
        parts.append(
            f'<text x="{(utility.x+1)*cell_w}" y="{utility.y*cell_h+16}" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#0f172a">{label}</text>'
        )

    for room in result.rooms:
        spec = MODULE_BY_KEY[room.module_key]
        fill = PALETTE[spec.module_type.value]
        x = room.x * cell_w
        y = room.y * cell_h
        w = room.width * cell_w
        h = room.height * cell_h
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="{fill}" stroke="#f8fafc" stroke-width="1.5"/>'
        )
        name = escape(spec.name)
        parts.append(
            f'<text x="{x+w/2}" y="{y+h/2+4}" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#0f172a">{name}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)
