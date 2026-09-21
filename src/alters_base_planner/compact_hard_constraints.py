"""EXPERIMENTAL compact placement/occupancy formulation (Phase-2 Formulation B1).

Research module for the CP-SAT hard-model formulation audit, Phase 2
(`docs/CP_SAT_HARD_MODEL_AUDIT_PHASE2.md`). It is intentionally NOT wired into the
production engine: :func:`build_hard_constraint_layer` (Formulation A) remains the
production hard layer.

Formulation B1 replaces only the placement/occupancy representation of Formulation A:

A (production)
    - one Boolean placement literal per legal candidate,
    - ``add_exactly_one`` per room instance,
    - cell-expanded ``add_at_most_one`` occupancy per Base cell.

B1 (this module)
    - one ``choice_i`` IntVar per room instance over its candidate indices,
    - exact ``add_element`` channeling of the selected candidate position to
      ``x_i`` / ``y_i`` integer position variables,
    - mandatory fixed-size X/Y interval per room rectangle,
    - optional fixed-size interval per solver-managed 2x1 utility anchor,
    - ONE native ``add_no_overlap_2d`` system covering rooms + utilities,
    - exact Boolean channel literals ``selected_option[o] <=> choice_i == index(o)``
      used by the SAME shared connectivity layer as Formulation A.

Exactness argument:
    H2/H5 candidate legality still comes from the prevalidated candidate domain: a
    ``choice_i`` value only ever maps to candidate positions whose complete footprint is
    inside the buildable Base mask. NoOverlap2D forbids open-set rectangle overlap between
    any two selected (room/utility) rectangles, which is exactly the H3 no-overlap feasible
    set of Formulation A on the same candidate domain. The irregular mask is therefore
    never approximated by a bounding box. All connectivity semantics are shared verbatim
    with Formulation A through ``_build_connectivity_layer``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .hard_constraints import (
    Anchor,
    Cell,
    HardConstraintVariables,
    PlacementOptionSpec,
    UtilityAnchorSpec,
    _build_connectivity_layer,
    _validate_input_domain,
)


@dataclass(frozen=True, slots=True)
class CompactPlacementChannel:
    """Compact position channel for one room instance."""

    instance_id: str
    choice: cp_model.IntVar
    x: cp_model.IntVar
    y: cp_model.IntVar
    option_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompactHardConstraintVariables:
    """Decision variables created by :func:`build_compact_hard_constraint_layer`."""

    base: HardConstraintVariables
    channel_by_instance: dict[str, CompactPlacementChannel]
    room_x_intervals: tuple[cp_model.IntervalVar, ...]
    room_y_intervals: tuple[cp_model.IntervalVar, ...]
    utility_x_intervals: tuple[cp_model.IntervalVar, ...]
    utility_y_intervals: tuple[cp_model.IntervalVar, ...]


def _instance_geometry(
    options: tuple[PlacementOptionSpec, ...],
) -> tuple[list[int], list[int], int, int]:
    """Deterministic candidate positions plus the shared verified footprint.

    All candidates of one instance must share the verified module footprint (H4); the
    caller's candidate generation already guarantees this, and this helper fails fast if
    a research caller violates the precondition.
    """

    widths = {
        max(x for x, _ in option.cells) - min(x for x, _ in option.cells) + 1
        for option in options
    }
    heights = {
        max(y for _, y in option.cells) - min(y for _, y in option.cells) + 1
        for option in options
    }
    if len(widths) != 1 or len(heights) != 1:
        raise AssertionError(
            "Compact formulation requires one fixed verified footprint per room instance"
        )
    candidate_xs = [min(x for x, _ in option.cells) for option in options]
    candidate_ys = [min(y for _, y in option.cells) for option in options]
    return candidate_xs, candidate_ys, widths.pop(), heights.pop()


def build_compact_hard_constraint_layer(
    model: cp_model.CpModel,
    *,
    buildable_cells: frozenset[Cell],
    placement_options: tuple[PlacementOptionSpec, ...],
    utility_anchors: tuple[UtilityAnchorSpec, ...],
    root_instance_id: str,
) -> CompactHardConstraintVariables:
    """EXPERIMENTAL compact hard-feasibility layer (Phase-2 Formulation B1).

    Same physical feasible set as :func:`build_hard_constraint_layer` on identical inputs
    (verified by exhaustive tiny-domain equivalence tests), with the occupancy representation
    replaced by native CP-SAT position variables, intervals and NoOverlap2D.
    """

    _validate_input_domain(
        buildable_cells=buildable_cells,
        placement_options=placement_options,
        utility_anchors=utility_anchors,
        root_instance_id=root_instance_id,
    )

    options_by_instance: dict[str, list[PlacementOptionSpec]] = defaultdict(list)
    for option in placement_options:
        options_by_instance[option.instance_id].append(option)

    # Deterministic candidate order per instance: sorted by option_id.
    geometry_by_instance: dict[str, tuple[list[int], list[int], int, int]] = {}
    channel_by_instance: dict[str, CompactPlacementChannel] = {}
    selected_option: dict[str, cp_model.IntVar] = {}

    for instance_id in sorted(options_by_instance):
        options = tuple(
            sorted(options_by_instance[instance_id], key=lambda option: option.option_id)
        )
        candidate_xs, candidate_ys, width, height = _instance_geometry(options)
        geometry_by_instance[instance_id] = (candidate_xs, candidate_ys, width, height)

        last_index = len(options) - 1
        choice = model.new_int_var(0, last_index, f"choice__{instance_id}")
        x_var = model.new_int_var(min(candidate_xs), max(candidate_xs), f"room_x__{instance_id}")
        y_var = model.new_int_var(min(candidate_ys), max(candidate_ys), f"room_y__{instance_id}")

        # Exact channeling: x_i / y_i equal the selected candidate's verified position.
        model.add_element(choice, candidate_xs, x_var)
        model.add_element(choice, candidate_ys, y_var)

        channel_by_instance[instance_id] = CompactPlacementChannel(
            instance_id=instance_id,
            choice=choice,
            x=x_var,
            y=y_var,
            option_ids=tuple(option.option_id for option in options),
        )

        # Exact Boolean channel literals: selected_option[o] <=> choice_i == index(o).
        # Both implications are mandatory, so exactly one literal is true per instance and
        # the shared connectivity layer sees the same active-candidate pattern as Formulation A.
        for index, option in enumerate(options):
            literal = model.new_bool_var(f"compact_sel__{option.option_id}")
            selected_option[option.option_id] = literal
            model.add(choice == index).only_enforce_if(literal)
            model.add(choice != index).only_enforce_if(literal.Not())

    # Room rectangles: mandatory intervals channeled to the selected candidate position.
    room_x_intervals: list[cp_model.IntervalVar] = []
    room_y_intervals: list[cp_model.IntervalVar] = []
    for instance_id in sorted(options_by_instance):
        candidate_xs, candidate_ys, width, height = geometry_by_instance[instance_id]
        del candidate_xs, candidate_ys
        channel = channel_by_instance[instance_id]
        room_x_intervals.append(
            model.new_interval_var(
                channel.x, width, channel.x + width, f"room_iv_x__{instance_id}"
            )
        )
        room_y_intervals.append(
            model.new_interval_var(
                channel.y, height, channel.y + height, f"room_iv_y__{instance_id}"
            )
        )

    # Solver-managed Corridor/Elevator occupation (H9/H10) — identical to Formulation A.
    corridor: dict[Anchor, cp_model.IntVar] = {}
    elevator: dict[Anchor, cp_model.IntVar] = {}
    utility_active: dict[Anchor, cp_model.IntVar] = {}
    for utility in utility_anchors:
        anchor = utility.anchor
        corridor[anchor] = model.new_bool_var(f"corridor__{utility.x}_{utility.y}")
        elevator[anchor] = model.new_bool_var(f"elevator__{utility.x}_{utility.y}")
        utility_active[anchor] = model.new_bool_var(f"utility__{utility.x}_{utility.y}")
        model.add_at_most_one(corridor[anchor], elevator[anchor])
        model.add(utility_active[anchor] == corridor[anchor] + elevator[anchor])

    # Utility rectangles: optional fixed-size intervals, present iff the anchor is selected.
    utility_x_intervals: list[cp_model.IntervalVar] = []
    utility_y_intervals: list[cp_model.IntervalVar] = []
    for utility in utility_anchors:
        anchor = utility.anchor
        utility_x_intervals.append(
            model.new_optional_fixed_size_interval_var(
                utility.x, 2, utility_active[anchor], f"utility_iv_x__{utility.x}_{utility.y}"
            )
        )
        utility_y_intervals.append(
            model.new_optional_fixed_size_interval_var(
                utility.y, 1, utility_active[anchor], f"utility_iv_y__{utility.x}_{utility.y}"
            )
        )

    # ONE native 2D no-overlap system for rooms + utilities (exact H3 on the candidate domain).
    model.add_no_overlap_2d(
        [*room_x_intervals, *utility_x_intervals],
        [*room_y_intervals, *utility_y_intervals],
    )

    # Shared connectivity layer (H5/H6/H7/H8/H9/H10/H11) — identical semantics to Formulation A.
    room_sink, flow, source_flow = _build_connectivity_layer(
        model,
        placement=selected_option,
        corridor=corridor,
        elevator=elevator,
        utility_active=utility_active,
        placement_options=placement_options,
        utility_anchors=utility_anchors,
        root_instance_id=root_instance_id,
    )

    base = HardConstraintVariables(
        placement=selected_option,
        corridor=corridor,
        elevator=elevator,
        utility_active=utility_active,
        room_sink=room_sink,
        flow=flow,
        source_flow=source_flow,
    )
    return CompactHardConstraintVariables(
        base=base,
        channel_by_instance=channel_by_instance,
        room_x_intervals=tuple(room_x_intervals),
        room_y_intervals=tuple(room_y_intervals),
        utility_x_intervals=tuple(utility_x_intervals),
        utility_y_intervals=tuple(utility_y_intervals),
    )