from __future__ import annotations

from html import escape
from pathlib import Path
from textwrap import fill as wrap_text

from .catalog import MODULE_BY_KEY
from .models import PlanResult

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
        f"Tier {result.base.tier} | F={objective:.3f} | avg={average_pair_distance(result):.2f} | "
        f"weighted avg={weighted_avg:.2f} | room mass={result.room_mass} | "
        f"utility mass={result.utility_mass} | total mass={result.total_mass}"
    )


def render_svg(result: PlanResult, cell_w: int = 32, cell_h: int = 24) -> str:
    base = result.base
    header_h = 38
    width_px = base.width * cell_w
    height_px = base.height * cell_h + header_h
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px}" height="{height_px}" viewBox="0 0 {width_px} {height_px}">',
        '<rect width="100%" height="100%" fill="#000000"/>',
        f'<text x="8" y="23" font-family="sans-serif" font-size="12" fill="#f8fafc">{escape(_metrics_caption(result))}</text>',
    ]

    # Anything outside allowed_cells stays black. Allowed empty cells are white;
    # fixed blocked cells are also black by design.
    for x, y in base.allowed_cells:
        fill = "#000000" if (x, y) in base.blocked_cells else "#FFFFFF"
        parts.append(
            f'<rect x="{x*cell_w}" y="{header_h+y*cell_h}" width="{cell_w}" height="{cell_h}" fill="{fill}" stroke="#808080" stroke-width="1"/>'
        )

    for utility in result.utilities:
        fill = "#D1D5DB" if utility.kind == "corridor" else "#E879F9"
        parts.append(
            f'<rect x="{utility.x*cell_w}" y="{header_h+utility.y*cell_h}" width="{utility.width*cell_w}" height="{cell_h}" rx="3" fill="{fill}" stroke="#111827" stroke-width="1"/>'
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
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{fill}" stroke="#111827" stroke-width="1.5"/>'
        )
        name = escape(spec.name)
        parts.append(
            f'<text x="{x+w/2}" y="{y+h/2+4}" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#071018">{name}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def render_png(result: PlanResult, path: str | Path, dpi: int = 180) -> None:
    """Render a color-coded cell diagram with legend and optimization metrics."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch, Rectangle

    base = result.base
    used_module_keys = sorted({room.module_key for room in result.rooms})
    legend_rows = len(used_module_keys) + 4
    fig_w = max(11.0, base.width * 0.42 + 4.5)
    fig_h = max(7.0, base.height * 0.42 + 1.8, legend_rows * 0.28)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("black")

    # Entire bounding box remains black: unavailable/outside-base cells.
    for x, y in base.allowed_cells:
        cell_color = "black" if (x, y) in base.blocked_cells else "white"
        edge_color = "#404040" if cell_color == "black" else "#B0B0B0"
        ax.add_patch(
            Rectangle((x, y), 1, 1, facecolor=cell_color, edgecolor=edge_color, linewidth=0.55)
        )

    for utility in result.utilities:
        face = "#D1D5DB" if utility.kind == "corridor" else "#E879F9"
        for dx in range(utility.width):
            ax.add_patch(
                Rectangle(
                    (utility.x + dx, utility.y),
                    1,
                    1,
                    facecolor=face,
                    edgecolor="#202020",
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
        for xx, yy in room.cells:
            ax.add_patch(
                Rectangle(
                    (xx, yy),
                    1,
                    1,
                    facecolor=color,
                    edgecolor="#202020",
                    linewidth=0.8,
                )
            )
        label = wrap_text(spec.name, width=max(6, room.width * 4))
        ax.text(
            room.x + room.width / 2,
            room.y + room.height / 2,
            label,
            ha="center",
            va="center",
            fontsize=6.7,
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
        f"The Alters Base Planner — BASE TIER {base.tier}\n"
        f"F={result.weighted_distance_score or 0.0:.3f}   "
        f"average pair distance={average_pair_distance(result):.2f}   "
        f"weighted average={weighted_avg:.2f}\n"
        f"room mass={result.room_mass}   utility mass={result.utility_mass}   "
        f"TOTAL BASE MASS={result.total_mass}   "
        f"journey Organics={result.organics_required_for_journey}/{base.organics_capacity}",
        fontsize=11,
        pad=12,
    )

    legend_handles = [
        Patch(facecolor="white", edgecolor="black", label="Empty buildable cell"),
        Patch(facecolor="black", edgecolor="#666666", label="Unavailable / outside / fixed core"),
        Patch(facecolor="#D1D5DB", edgecolor="black", label="Corridor — size 2×1, mass 2"),
        Patch(facecolor="#E879F9", edgecolor="black", label="Elevator — size 2×1, mass 2"),
    ]
    for key in used_module_keys:
        spec = MODULE_BY_KEY[key]
        legend_handles.append(
            Patch(
                facecolor=MODULE_COLORS[key],
                edgecolor="black",
                label=(
                    f"{spec.name} — {spec.width}×{spec.height}, "
                    f"mass {spec.mass}, weight {spec.visit_weight:.2f}"
                ),
            )
        )

    ax.legend(
        handles=legend_handles,
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        fontsize=7.2,
        title="Legend: size, mass, usage weight",
        title_fontsize=8,
        frameon=True,
    )

    fig.tight_layout()
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
