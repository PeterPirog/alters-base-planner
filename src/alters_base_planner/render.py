from __future__ import annotations

from html import escape
from pathlib import Path
from textwrap import fill as wrap_text

from .catalog import MODULE_BY_KEY
from .models import PlanResult

# Stable per-room palette. Repeated instances of the same room type share a color,
# while different room types are visually distinguishable.
_COLOR_LIST = (
    "#4E79A7",
    "#F28E2B",
    "#E15759",
    "#76B7B2",
    "#59A14F",
    "#EDC948",
    "#B07AA1",
    "#FF9DA7",
    "#9C755F",
    "#BAB0AC",
    "#1F77B4",
    "#FF7F0E",
    "#2CA02C",
    "#D62728",
    "#9467BD",
    "#8C564B",
    "#E377C2",
    "#7F7F7F",
    "#BCBD22",
    "#17BECF",
    "#393B79",
    "#637939",
    "#8C6D31",
    "#843C39",
    "#7B4173",
    "#3182BD",
    "#31A354",
    "#756BB1",
    "#636363",
    "#E6550D",
)
MODULE_COLORS = {
    key: _COLOR_LIST[index % len(_COLOR_LIST)]
    for index, key in enumerate(sorted(MODULE_BY_KEY))
}


def average_pair_distance(result: PlanResult) -> float:
    """Arithmetic mean of all positive-weight unordered room-pair distances."""

    values = list(result.pairwise_distances.values())
    return sum(values) / len(values) if values else 0.0


def _metrics_caption(result: PlanResult) -> str:
    weighted_avg = result.normalized_weighted_distance or 0.0
    objective = result.weighted_distance_score or 0.0
    return (
        f"F={objective:.3f} | avg distance={average_pair_distance(result):.2f} | "
        f"weighted avg={weighted_avg:.2f} | mass={result.total_mass}"
    )


def render_svg(result: PlanResult, cell_w: int = 32, cell_h: int = 24) -> str:
    base = result.base
    header_h = 34
    width_px = base.width * cell_w
    height_px = base.height * cell_h + header_h
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px}" height="{height_px}" viewBox="0 0 {width_px} {height_px}">',
        '<rect width="100%" height="100%" fill="#10151c"/>',
        f'<text x="8" y="22" font-family="sans-serif" font-size="13" fill="#f8fafc">{escape(_metrics_caption(result))}</text>',
    ]

    for x, y in base.allowed_cells:
        fill = "#202a36" if (x, y) not in base.blocked_cells else "#673c3c"
        parts.append(
            f'<rect x="{x*cell_w}" y="{header_h+y*cell_h}" width="{cell_w}" height="{cell_h}" fill="{fill}" stroke="#344252" stroke-width="1"/>'
        )

    for utility in result.utilities:
        fill = "#CBD5E1" if utility.kind == "corridor" else "#E879F9"
        parts.append(
            f'<rect x="{utility.x*cell_w}" y="{header_h+utility.y*cell_h}" width="{utility.width*cell_w}" height="{cell_h}" rx="3" fill="{fill}" stroke="#f8fafc" stroke-width="1"/>'
        )
        label = "C" if utility.kind == "corridor" else "E"
        parts.append(
            f'<text x="{(utility.x+1)*cell_w}" y="{header_h+utility.y*cell_h+16}" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#0f172a">{label}</text>'
        )

    for room in result.rooms:
        spec = MODULE_BY_KEY[room.module_key]
        fill = MODULE_COLORS[room.module_key]
        x = room.x * cell_w
        y = header_h + room.y * cell_h
        w = room.width * cell_w
        h = room.height * cell_h
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{fill}" stroke="#f8fafc" stroke-width="1.5"/>'
        )
        name = escape(spec.name)
        parts.append(
            f'<text x="{x+w/2}" y="{y+h/2+4}" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#071018">{name}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def render_png(result: PlanResult, path: str | Path, dpi: int = 180) -> None:
    """Render a color-coded cell diagram to PNG using Matplotlib.

    The chart shows one color per room type, individual grid cells, Corridors,
    Elevators, the fixed obstruction and the key optimization metrics.
    """

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    base = result.base
    fig_w = max(9.0, base.width * 0.38)
    fig_h = max(6.0, base.height * 0.38 + 1.4)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    # Draw the physical base mask cell-by-cell so CSV geometry errors are visible.
    for x, y in base.allowed_cells:
        cell_color = "#E5E7EB" if (x, y) not in base.blocked_cells else "#7F1D1D"
        ax.add_patch(
            Rectangle((x, y), 1, 1, facecolor=cell_color, edgecolor="#9CA3AF", linewidth=0.45)
        )

    # Utilities remain visually distinct from rooms.
    for utility in result.utilities:
        face = "#D1D5DB" if utility.kind == "corridor" else "#E879F9"
        for dx in range(utility.width):
            ax.add_patch(
                Rectangle(
                    (utility.x + dx, utility.y),
                    1,
                    1,
                    facecolor=face,
                    edgecolor="white",
                    linewidth=0.75,
                )
            )
        label = "C" if utility.kind == "corridor" else "E"
        ax.text(
            utility.x + utility.width / 2,
            utility.y + 0.5,
            label,
            ha="center",
            va="center",
            fontsize=7,
            fontweight="bold",
        )

    for room in result.rooms:
        spec = MODULE_BY_KEY[room.module_key]
        color = MODULE_COLORS[room.module_key]
        # Fill each occupied cell separately so the underlying grid remains explicit.
        for xx, yy in room.cells:
            ax.add_patch(
                Rectangle(
                    (xx, yy),
                    1,
                    1,
                    facecolor=color,
                    edgecolor="white",
                    linewidth=0.75,
                )
            )
        label = wrap_text(spec.name, width=max(6, room.width * 4))
        ax.text(
            room.x + room.width / 2,
            room.y + room.height / 2,
            label,
            ha="center",
            va="center",
            fontsize=6.8,
            fontweight="bold",
        )

    ax.set_xlim(0, base.width)
    ax.set_ylim(base.height, 0)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xticks(range(base.width + 1))
    ax.set_yticks(range(base.height + 1))
    ax.tick_params(labelsize=6, length=2)
    ax.set_xlabel("x [grid cells]")
    ax.set_ylabel("y / floor [grid cells]")

    weighted_avg = result.normalized_weighted_distance or 0.0
    ax.set_title(
        f"The Alters Base Planner — Tier {base.tier}\n"
        f"F={result.weighted_distance_score or 0.0:.3f}   "
        f"average distance={average_pair_distance(result):.2f}   "
        f"weighted average={weighted_avg:.2f}   "
        f"mass={result.total_mass} / organics={result.organics_required_for_journey}",
        fontsize=11,
    )

    fig.tight_layout()
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
