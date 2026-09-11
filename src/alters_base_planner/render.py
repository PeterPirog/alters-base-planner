from __future__ import annotations

from html import escape
from pathlib import Path
from textwrap import fill as wrap_text

from .catalog import MODULE_BY_KEY
from .models import ModulePlacement, PlacementAuthority, PlanResult
from .serialization import average_pair_distance

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
    for index, key in enumerate(
        sorted(
            key
            for key, spec in MODULE_BY_KEY.items()
            if spec.authority is not PlacementAuthority.SOLVER
        )
    )
}

_UTILITY_COLORS = {"corridor": "#D1D5DB", "elevator": "#E879F9"}
_UTILITY_LABELS = {"corridor": "C", "elevator": "E"}


def _partition_modules(
    result: PlanResult,
) -> tuple[list[ModulePlacement], list[ModulePlacement]]:
    rooms: list[ModulePlacement] = []
    utilities: list[ModulePlacement] = []
    for module in result.modules:
        spec = MODULE_BY_KEY[module.module_key]
        if spec.authority is PlacementAuthority.SOLVER:
            utilities.append(module)
        else:
            rooms.append(module)
    return rooms, utilities


def _metrics_caption(result: PlanResult) -> str:
    weighted_avg = result.normalized_weighted_distance or 0.0
    objective = result.weighted_distance_score or 0.0
    return (
        f"Tier {result.base.tier} | F={objective:.3f} | avg={average_pair_distance(result):.2f} | "
        f"weighted avg={weighted_avg:.2f} | room mass={result.room_mass} | "
        f"utility mass={result.utility_mass} | total mass={result.total_mass}"
    )


def _utility_visual(module_key: str) -> tuple[str, str]:
    try:
        return _UTILITY_COLORS[module_key], _UTILITY_LABELS[module_key]
    except KeyError as exc:
        raise ValueError(f"No renderer style for solver module {module_key!r}") from exc


def render_svg(result: PlanResult, cell_w: int = 24, cell_h: int = 48) -> str:
    """Render SVG using game-like rectangular cells: height = 2 * width."""

    rooms, utilities = _partition_modules(result)
    base = result.base
    header_h = 38
    width_px = base.width * cell_w
    height_px = base.height * cell_h + header_h
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px}" height="{height_px}" viewBox="0 0 {width_px} {height_px}">',
        '<rect width="100%" height="100%" fill="#000000"/>',
        f'<text x="8" y="23" font-family="sans-serif" font-size="12" fill="#f8fafc">{escape(_metrics_caption(result))}</text>',
    ]

    for x, y in base.allowed_cells:
        fill = "#000000" if (x, y) in base.blocked_cells else "#FFFFFF"
        parts.append(
            f'<rect x="{x*cell_w}" y="{header_h+y*cell_h}" width="{cell_w}" height="{cell_h}" fill="{fill}" stroke="#808080" stroke-width="1"/>'
        )

    for utility in utilities:
        fill, label = _utility_visual(utility.module_key)
        parts.append(
            f'<rect x="{utility.x*cell_w}" y="{header_h+utility.y*cell_h}" width="{utility.width*cell_w}" height="{utility.height*cell_h}" rx="3" fill="{fill}" stroke="#111827" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{(utility.x+utility.width/2)*cell_w}" y="{header_h+(utility.y+utility.height/2)*cell_h+4}" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#0f172a">{label}</text>'
        )

    for room in rooms:
        spec = MODULE_BY_KEY[room.module_key]
        fill = MODULE_COLORS[room.module_key]
        x = room.x * cell_w
        y = header_h + room.y * cell_h
        w = room.width * cell_w
        h = room.height * cell_h
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{fill}" stroke="#111827" stroke-width="1.5"/>'
        )
        parts.append(
            f'<text x="{x+w/2}" y="{y+h/2+4}" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#071018">{escape(spec.name)}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def render_png(result: PlanResult, path: str | Path, dpi: int = 180) -> None:
    """Render a color-coded cell diagram with legend and optimization metrics."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch, Rectangle

    rooms, utilities = _partition_modules(result)
    base = result.base
    used_module_keys = sorted({room.module_key for room in rooms})
    legend_rows = len(used_module_keys) + 4
    fig_w = max(10.5, base.width * 0.34 + 4.5)
    fig_h = max(8.0, base.height * 0.68 + 2.2, legend_rows * 0.28)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("black")

    for x, y in base.allowed_cells:
        cell_color = "black" if (x, y) in base.blocked_cells else "white"
        edge_color = "#404040" if cell_color == "black" else "#B0B0B0"
        ax.add_patch(
            Rectangle((x, y), 1, 1, facecolor=cell_color, edgecolor=edge_color, linewidth=0.55)
        )

    for utility in utilities:
        face, label = _utility_visual(utility.module_key)
        for xx, yy in utility.cells:
            ax.add_patch(
                Rectangle(
                    (xx, yy),
                    1,
                    1,
                    facecolor=face,
                    edgecolor="#202020",
                    linewidth=0.75,
                )
            )
        ax.text(
            utility.x + utility.width / 2,
            utility.y + utility.height / 2,
            label,
            ha="center",
            va="center",
            fontsize=7,
            fontweight="bold",
        )

    for room in rooms:
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
    ax.set_aspect(2.0, adjustable="box")
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

    corridor = MODULE_BY_KEY["corridor"]
    elevator = MODULE_BY_KEY["elevator"]
    legend_handles = [
        Patch(facecolor="white", edgecolor="black", label="Empty buildable cell"),
        Patch(facecolor="black", edgecolor="#666666", label="Unavailable / outside / fixed core"),
        Patch(
            facecolor=_UTILITY_COLORS["corridor"],
            edgecolor="black",
            label=f"Corridor — size {corridor.width}×{corridor.height}, mass {corridor.mass}",
        ),
        Patch(
            facecolor=_UTILITY_COLORS["elevator"],
            edgecolor="black",
            label=f"Elevator — size {elevator.width}×{elevator.height}, mass {elevator.mass}",
        ),
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
