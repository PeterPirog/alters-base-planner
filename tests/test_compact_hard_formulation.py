"""Phase-2 exhaustive A-vs-B equivalence tests for the compact hard formulation.

For every tiny family this module enumerates the complete physical-layout domain:

- every legal combination of one placement candidate per room instance;
- every utility anchor state in {NONE, CORRIDOR, ELEVATOR}.

Each physical layout is forced into BOTH formulations (production Formulation A and the
experimental compact Formulation B1) and solved exactly. A physical layout belongs to a
formulation's feasible set iff the forced model is feasible. The test requires the two
feasible sets to be identical for every family (A-only and B-only must both be empty).

Canonical physical-layout key (installed modules + selected utilities only; all auxiliary
choice/channel/flow/sink/interval variables are ignored):

    (sorted room tuples (instance_id, module_key, x, y, width, height),
     sorted utility tuples (kind, x, y))
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from ortools.sat.python import cp_model

from alters_base_planner.compact_hard_constraints import build_compact_hard_constraint_layer
from alters_base_planner.hard_constraints import (
    PlacementOptionSpec,
    UtilityAnchorSpec,
    build_hard_constraint_layer,
)
from alters_base_planner.models import BaseGeometry, PortSide, ResolvedPort


def make_base(width: int, height: int, blocked: frozenset[tuple[int, int]]) -> BaseGeometry:
    # Canonical CSV semantics: 'X' cells belong to both allowed_cells and blocked_cells;
    # buildable_cells is allowed minus blocked.
    allowed = frozenset((x, y) for y in range(height) for x in range(width))
    return BaseGeometry(
        tier=99,
        width=width,
        height=height,
        allowed_cells=allowed,
        blocked_cells=frozenset(blocked),
        organics_capacity=999,
        source="phase2-synthetic",
        verified=False,
        note="Phase-2 equivalence family",
    )


def _port(name: str, side: PortSide, edge_x: int, edge_y: int) -> ResolvedPort:
    return ResolvedPort(
        name=name,
        side=side,
        cell_x=edge_x if side is PortSide.LEFT else edge_x - 1,
        cell_y=edge_y,
        edge_x=edge_x,
        edge_y=edge_y,
    )


def _room(
    option_id: str,
    instance_id: str,
    module_key: str,
    *,
    x: int,
    y: int,
    width: int,
    height: int = 1,
    transit_allowed: bool = True,
) -> PlacementOptionSpec:
    cells = frozenset((xx, yy) for xx in range(x, x + width) for yy in range(y, y + height))
    floor_y = y + height - 1
    return PlacementOptionSpec(
        option_id=option_id,
        instance_id=instance_id,
        module_key=module_key,
        cells=cells,
        ports=(
            _port("left", PortSide.LEFT, x, floor_y),
            _port("right", PortSide.RIGHT, x + width, floor_y),
        ),
        transit_allowed=transit_allowed,
    )


@dataclass(frozen=True)
class Family:
    name: str
    base: BaseGeometry
    instances: dict[str, tuple[PlacementOptionSpec, ...]]
    anchors: tuple[UtilityAnchorSpec, ...]


def _canonical_key(
    chosen: dict[str, PlacementOptionSpec],
    utilities: dict[tuple[int, int], str],
) -> tuple:
    rooms = tuple(
        sorted(
            (
                option.instance_id,
                option.module_key,
                min(x for x, _ in option.cells),
                min(y for _, y in option.cells),
                max(x for x, _ in option.cells) - min(x for x, _ in option.cells) + 1,
                max(y for _, y in option.cells) - min(y for _, y in option.cells) + 1,
            )
            for option in chosen.values()
        )
    )
    utility_key = tuple(sorted((a, k) for a, k in utilities.items() if k != "none"))
    return rooms, utility_key


def _pin_utilities(
    model: cp_model.CpModel,
    corridor: dict[tuple[int, int], cp_model.IntVar],
    elevator: dict[tuple[int, int], cp_model.IntVar],
    utilities: dict[tuple[int, int], str],
) -> None:
    for anchor in corridor:
        kind = utilities.get(anchor, "none")
        model.add(corridor[anchor] == (1 if kind == "corridor" else 0))
        model.add(elevator[anchor] == (1 if kind == "elevator" else 0))


def _solve_status(model: cp_model.CpModel) -> int:
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = 10.0
    return int(solver.solve(model))


def _enumerate_utility_states(
    anchors: tuple[UtilityAnchorSpec, ...],
) -> list[dict[tuple[int, int], str]]:
    if not anchors:
        return [{}]
    ordered = [anchor.anchor for anchor in sorted(anchors, key=lambda a: a.anchor)]
    states: list[dict[tuple[int, int], str]] = []
    for combination in itertools.product(("none", "corridor", "elevator"), repeat=len(ordered)):
        states.append(dict(zip(ordered, combination, strict=True)))
    return states


def _physical_feasible_sets(
    family: Family,
) -> tuple[set[tuple], set[tuple], int]:
    """Exhaustively force every physical layout through A and B1; return both sets."""

    instance_ids = sorted(family.instances)
    anchor_states = _enumerate_utility_states(family.anchors)

    a_feasible: set[tuple] = set()
    b_feasible: set[tuple] = set()
    layouts = 0

    for chosen in itertools.product(*(family.instances[i] for i in instance_ids)):
        chosen_by_instance = dict(zip(instance_ids, chosen))
        for utilities in anchor_states:
            layouts += 1
            key = _canonical_key(chosen_by_instance, utilities)

            # ---- Formulation A (production) ----
            model_a = cp_model.CpModel()
            variables_a = build_hard_constraint_layer(
                model_a,
                buildable_cells=family.base.buildable_cells,
                placement_options=tuple(
                    option for options in family.instances.values() for option in options
                ),
                utility_anchors=family.anchors,
                root_instance_id="airlock-1",
            )
            for option in chosen:
                model_a.add(variables_a.placement[option.option_id] == 1)
            _pin_utilities(model_a, variables_a.corridor, variables_a.elevator, utilities)
            assert model_a.validate() == ""
            status_a = _solve_status(model_a)
            if status_a in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                a_feasible.add(key)

            # ---- Formulation B1 (compact) ----
            model_b = cp_model.CpModel()
            variables_b = build_compact_hard_constraint_layer(
                model_b,
                buildable_cells=family.base.buildable_cells,
                placement_options=tuple(
                    option for options in family.instances.values() for option in options
                ),
                utility_anchors=family.anchors,
                root_instance_id="airlock-1",
            )
            for instance_id, option in chosen_by_instance.items():
                channel = variables_b.channel_by_instance[instance_id]
                index = channel.option_ids.index(option.option_id)
                model_b.add(channel.choice == index)
            _pin_utilities(
                model_b, variables_b.base.corridor, variables_b.base.elevator, utilities
            )
            assert model_b.validate() == ""
            status_b = _solve_status(model_b)
            if status_b in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                b_feasible.add(key)

    return a_feasible, b_feasible, layouts


def _assert_family_equivalence(family: Family) -> tuple[set[tuple], set[tuple], int]:
    a_set, b_set, layouts = _physical_feasible_sets(family)
    a_only = a_set - b_set
    b_only = b_set - a_set
    assert not a_only, f"{family.name}: A-only layouts: {sorted(a_only)}"
    assert not b_only, f"{family.name}: B-only layouts: {sorted(b_only)}"
    return a_set, b_set, layouts


def _family_direct_adjacency() -> Family:
    base = make_base(8, 1, frozenset())
    return Family(
        name="F1_direct_room_adjacency",
        base=base,
        instances={
            "airlock-1": (_room("a@0", "airlock-1", "airlock", x=0, y=0, width=4),),
            "workshop-1": (_room("w@4", "workshop-1", "workshop", x=4, y=0, width=4),),
        },
        anchors=(),
    )


def _family_disconnected_room() -> Family:
    base = make_base(12, 1, frozenset())
    return Family(
        name="F2_disconnected_room",
        base=base,
        instances={
            "airlock-1": (_room("a@0", "airlock-1", "airlock", x=0, y=0, width=4),),
            "workshop-1": (_room("w@6", "workshop-1", "workshop", x=6, y=0, width=4),),
        },
        anchors=(),
    )


def _family_isolated_airlock() -> Family:
    base = make_base(8, 1, frozenset())
    return Family(
        name="F3_isolated_airlock_h6",
        base=base,
        instances={
            "airlock-1": (_room("a@0", "airlock-1", "airlock", x=0, y=0, width=4),),
        },
        anchors=(),
    )


def _family_multiple_airlock_placements() -> Family:
    base = make_base(16, 1, frozenset())
    return Family(
        name="F4_multiple_airlock_placements",
        base=base,
        instances={
            "airlock-1": (
                _room("a@0", "airlock-1", "airlock", x=0, y=0, width=4),
                _room("a@8", "airlock-1", "airlock", x=8, y=0, width=4),
            ),
            "workshop-1": (_room("w@12", "workshop-1", "workshop", x=12, y=0, width=4),),
        },
        anchors=(),
    )


def _family_corridor_attachment() -> Family:
    base = make_base(12, 1, frozenset())
    return Family(
        name="F5_corridor_attachment",
        base=base,
        instances={
            "airlock-1": (_room("a@0", "airlock-1", "airlock", x=0, y=0, width=4),),
            "workshop-1": (_room("w@6", "workshop-1", "workshop", x=6, y=0, width=4),),
        },
        anchors=(UtilityAnchorSpec(4, 0),),
    )


def _family_transit_middle_room() -> Family:
    base = make_base(16, 1, frozenset())
    return Family(
        name="F7_transit_middle_room",
        base=base,
        instances={
            "airlock-1": (_room("a@0", "airlock-1", "airlock", x=0, y=0, width=4),),
            "middle-1": (_room("m@4", "middle-1", "workshop", x=4, y=0, width=4),),
            "far-1": (_room("f@8", "far-1", "workshop", x=8, y=0, width=4),),
        },
        anchors=(),
    )


def _family_non_transit_terminal() -> Family:
    base = make_base(12, 1, frozenset())
    return Family(
        name="F8_non_transit_terminal",
        base=base,
        instances={
            "airlock-1": (_room("a@0", "airlock-1", "airlock", x=0, y=0, width=4),),
            "ark-1": (
                _room(
                    "k@4", "ark-1", "rapidium_ark", x=4, y=0, width=4, transit_allowed=False
                ),
            ),
        },
        anchors=(),
    )


def _family_non_transit_bridge() -> Family:
    base = make_base(16, 1, frozenset())
    return Family(
        name="F9_non_transit_bridge",
        base=base,
        instances={
            "airlock-1": (_room("a@0", "airlock-1", "airlock", x=0, y=0, width=4),),
            "ark-1": (
                _room(
                    "k@4", "ark-1", "rapidium_ark", x=4, y=0, width=4, transit_allowed=False
                ),
            ),
            "workshop-1": (_room("w@8", "workshop-1", "workshop", x=8, y=0, width=4),),
        },
        anchors=(),
    )


def _family_stacked_elevator() -> Family:
    # Airlock on row y=1, workshop directly above on row y=0; the only legal path is the
    # vertical Elevator edge between anchors (4,1) and (4,0).
    base = make_base(8, 2, frozenset())
    return Family(
        name="F10_stacked_elevator_vertical",
        base=base,
        instances={
            "airlock-1": (_room("a@0_1", "airlock-1", "airlock", x=0, y=1, width=4),),
            "workshop-1": (_room("w@0_0", "workshop-1", "workshop", x=0, y=0, width=4),),
        },
        anchors=(UtilityAnchorSpec(4, 0), UtilityAnchorSpec(4, 1)),
    )


def _family_room_utility_overlap() -> Family:
    base = make_base(12, 1, frozenset())
    return Family(
        name="F12_room_utility_overlap",
        base=base,
        instances={
            "airlock-1": (_room("a@0", "airlock-1", "airlock", x=0, y=0, width=4),),
            "workshop-1": (
                _room("w@5", "workshop-1", "workshop", x=5, y=0, width=4),
                _room("w@6", "workshop-1", "workshop", x=6, y=0, width=4),
            ),
        },
        anchors=(UtilityAnchorSpec(4, 0),),
    )


def _family_utility_utility_overlap() -> Family:
    base = make_base(16, 1, frozenset())
    return Family(
        name="F13_utility_utility_overlap",
        base=base,
        instances={
            "airlock-1": (_room("a@0", "airlock-1", "airlock", x=0, y=0, width=4),),
            "workshop-1": (_room("w@6", "workshop-1", "workshop", x=6, y=0, width=4),),
        },
        anchors=(UtilityAnchorSpec(4, 0), UtilityAnchorSpec(5, 0)),
    )


def _family_blocked_geometry() -> Family:
    base = make_base(12, 2, frozenset({(11, 0)}))
    return Family(
        name="F14_blocked_geometry",
        base=base,
        instances={
            "airlock-1": (_room("a@0", "airlock-1", "airlock", x=0, y=0, width=4),),
            "workshop-1": (
                _room("w@4_0", "workshop-1", "workshop", x=4, y=0, width=4),
                _room("w@6_1", "workshop-1", "workshop", x=6, y=1, width=4),
            ),
        },
        anchors=(UtilityAnchorSpec(4, 0), UtilityAnchorSpec(4, 1)),
    )


def _family_alternative_adjacency() -> Family:
    base = make_base(12, 1, frozenset())
    return Family(
        name="F15_alternative_adjacency",
        base=base,
        instances={
            "airlock-1": (_room("a@0", "airlock-1", "airlock", x=0, y=0, width=4),),
            "workshop-1": (
                _room("w@4", "workshop-1", "workshop", x=4, y=0, width=4),
                _room("w@8", "workshop-1", "workshop", x=8, y=0, width=4),
            ),
        },
        anchors=(),
    )


_ALL_FAMILY_BUILDERS = (
    _family_direct_adjacency,
    _family_disconnected_room,
    _family_isolated_airlock,
    _family_multiple_airlock_placements,
    _family_corridor_attachment,
    _family_transit_middle_room,
    _family_non_transit_terminal,
    _family_non_transit_bridge,
    _family_stacked_elevator,
    _family_room_utility_overlap,
    _family_utility_utility_overlap,
    _family_blocked_geometry,
    _family_alternative_adjacency,
)


def test_all_families_feasible_sets_are_identical() -> None:
    """Primary Phase-2 gate: A_feasible_set == B_feasible_set on every tiny family."""

    total_layouts = 0
    total_a = 0
    total_b = 0
    for builder in _ALL_FAMILY_BUILDERS:
        family = builder()
        a_set, b_set, layouts = _assert_family_equivalence(family)
        total_layouts += layouts
        total_a += len(a_set)
        total_b += len(b_set)
        print(
            f"{family.name}: layouts={layouts} A_feasible={len(a_set)} B_feasible={len(b_set)}"
        )
    print(
        f"TOTAL: layouts={total_layouts} A_feasible={total_a} B_feasible={total_b} "
        f"A_only=0 B_only=0"
    )


def test_isolated_airlock_is_infeasible_in_both_formulations() -> None:
    """Normative H6 regression must hold identically in the compact formulation."""

    family = _family_isolated_airlock()
    a_set, b_set, _ = _assert_family_equivalence(family)
    assert len(a_set) == 0
    assert len(b_set) == 0


def test_multiple_airlock_placements_keep_only_connectable_candidate() -> None:
    family = _family_multiple_airlock_placements()
    a_set, b_set, _ = _assert_family_equivalence(family)
    expected = {
        _canonical_key(
            {
                "airlock-1": _room("a@8", "airlock-1", "airlock", x=8, y=0, width=4),
                "workshop-1": _room("w@12", "workshop-1", "workshop", x=12, y=0, width=4),
            },
            {},
        )
    }
    assert a_set == expected
    assert b_set == expected


def test_stacked_elevator_only_vertical_elevator_pair_is_feasible() -> None:
    family = _family_stacked_elevator()
    a_set, b_set, _ = _assert_family_equivalence(family)
    feasible_layouts = {
        _canonical_key(
            {
                "airlock-1": _room("a@0_1", "airlock-1", "airlock", x=0, y=1, width=4),
                "workshop-1": _room("w@0_0", "workshop-1", "workshop", x=0, y=0, width=4),
            },
            {(4, 0): "elevator", (4, 1): "elevator"},
        )
    }
    assert a_set == feasible_layouts
    assert b_set == feasible_layouts


def test_non_transit_bridge_is_infeasible_in_both_formulations() -> None:
    family = _family_non_transit_bridge()
    a_set, b_set, _ = _assert_family_equivalence(family)
    assert len(a_set) == 0
    assert len(b_set) == 0


def test_non_transit_terminal_is_feasible_in_both_formulations() -> None:
    family = _family_non_transit_terminal()
    a_set, b_set, _ = _assert_family_equivalence(family)
    assert len(a_set) == 1
    assert a_set == b_set


def test_corridor_attachment_states() -> None:
    family = _family_corridor_attachment()
    a_set, b_set, _ = _assert_family_equivalence(family)
    # Only selected infrastructure (corridor or elevator at (4,0)) connects the gap.
    expected = {
        _canonical_key(
            {
                "airlock-1": _room("a@0", "airlock-1", "airlock", x=0, y=0, width=4),
                "workshop-1": _room("w@6", "workshop-1", "workshop", x=6, y=0, width=4),
            },
            {(4, 0): kind},
        )
        for kind in ("corridor", "elevator")
    }
    assert a_set == expected
    assert b_set == expected


def test_blocked_geometry_excludes_occupied_candidates_and_anchors() -> None:
    family = _family_blocked_geometry()
    a_set, b_set, _ = _assert_family_equivalence(family)
    # Both rooms reachable: direct adjacency for w@4_0; elevator pair path for w@6_1.
    expected = {
        _canonical_key(
            {
                "airlock-1": _room("a@0", "airlock-1", "airlock", x=0, y=0, width=4),
                "workshop-1": _room("w@4_0", "workshop-1", "workshop", x=4, y=0, width=4),
            },
            {},
        ),
        _canonical_key(
            {
                "airlock-1": _room("a@0", "airlock-1", "airlock", x=0, y=0, width=4),
                "workshop-1": _room("w@6_1", "workshop-1", "workshop", x=6, y=1, width=4),
            },
            {(4, 0): "elevator", (4, 1): "elevator"},
        ),
    }
    assert a_set == expected
    assert b_set == expected


def test_room_utility_overlap_rejected_in_both_formulations() -> None:
    family = _family_room_utility_overlap()
    a_set, b_set, _ = _assert_family_equivalence(family)
    # Only the non-overlapping workshop placement w@6 may appear in feasible layouts.
    for key in a_set:
        workshop_x = next(room[2] for room in key[0] if room[0] == "workshop-1")
        assert workshop_x != 5
    assert a_set == b_set


def test_utility_utility_overlap_rejected_in_both_formulations() -> None:
    family = _family_utility_utility_overlap()
    a_set, b_set, _ = _assert_family_equivalence(family)
    for key in a_set:
        utilities = dict(key[1])
        # Anchors (4,0) and (5,0) overlap in cell (5,0): never both selected.
        assert not (
            utilities.get((4, 0), "none") != "none" and utilities.get((5, 0), "none") != "none"
        )
    assert a_set == b_set


def test_channel_literals_are_exact_in_compact_formulation() -> None:
    """selected_option[o] <=> choice_i == index(o), both directions, on a feasible solve."""

    family = _family_multiple_airlock_placements()
    model = cp_model.CpModel()
    variables = build_compact_hard_constraint_layer(
        model,
        buildable_cells=family.base.buildable_cells,
        placement_options=tuple(
            option for options in family.instances.values() for option in options
        ),
        utility_anchors=family.anchors,
        root_instance_id="airlock-1",
    )
    assert model.validate() == ""
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    status = solver.solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    for channel in variables.channel_by_instance.values():
        choice_value = solver.value(channel.choice)
        selected_flags = [
            solver.value(variables.base.placement[option_id]) for option_id in channel.option_ids
        ]
        assert sum(selected_flags) == 1
        assert selected_flags[choice_value] == 1
        for index, flag in enumerate(selected_flags):
            if index != choice_value:
                assert flag == 0