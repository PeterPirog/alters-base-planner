from ortools.sat.python import cp_model

from alters_base_planner.hard_constraints import (
    PlacementOptionSpec,
    UtilityAnchorSpec,
    build_hard_constraint_layer,
)
from alters_base_planner.models import PortSide, ResolvedPort


def _port(
    name: str,
    side: PortSide,
    *,
    cell_x: int,
    cell_y: int,
    edge_x: int,
    edge_y: int,
) -> ResolvedPort:
    return ResolvedPort(
        name=name,
        side=side,
        cell_x=cell_x,
        cell_y=cell_y,
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
    transit_allowed: bool = True,
) -> PlacementOptionSpec:
    cells = frozenset((xx, y) for xx in range(x, x + width))
    return PlacementOptionSpec(
        option_id=option_id,
        instance_id=instance_id,
        module_key=module_key,
        cells=cells,
        ports=(
            _port(
                "left",
                PortSide.LEFT,
                cell_x=x,
                cell_y=y,
                edge_x=x,
                edge_y=y,
            ),
            _port(
                "right",
                PortSide.RIGHT,
                cell_x=x + width - 1,
                cell_y=y,
                edge_x=x + width,
                edge_y=y,
            ),
        ),
        transit_allowed=transit_allowed,
    )


def _solve(model: cp_model.CpModel) -> int:
    validation_error = model.validate()
    assert not validation_error
    return cp_model.CpSolver().solve(model)


def test_direct_port_adjacency_is_connected_without_corridor() -> None:
    model = cp_model.CpModel()
    buildable = frozenset((x, 0) for x in range(8))
    options = (
        _room("airlock-pos", "airlock-1", "airlock", x=0, y=0, width=4),
        _room("workshop-pos", "workshop-1", "workshop", x=4, y=0, width=4),
    )

    build_hard_constraint_layer(
        model,
        buildable_cells=buildable,
        placement_options=options,
        utility_anchors=(),
        root_instance_id="airlock-1",
    )

    assert _solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_disconnected_room_is_infeasible() -> None:
    model = cp_model.CpModel()
    buildable = frozenset((x, 0) for x in range(10))
    options = (
        _room("airlock-pos", "airlock-1", "airlock", x=0, y=0, width=4),
        _room("workshop-pos", "workshop-1", "workshop", x=6, y=0, width=4),
    )

    build_hard_constraint_layer(
        model,
        buildable_cells=buildable,
        placement_options=options,
        utility_anchors=(),
        root_instance_id="airlock-1",
    )

    assert _solve(model) == cp_model.INFEASIBLE


def test_non_transit_room_cannot_bridge_between_other_rooms() -> None:
    buildable = frozenset((x, 0) for x in range(6))

    blocked_model = cp_model.CpModel()
    blocked_options = (
        _room("airlock-pos", "airlock-1", "airlock", x=0, y=0, width=2),
        _room(
            "ark-pos",
            "ark-1",
            "rapidium_ark",
            x=2,
            y=0,
            width=2,
            transit_allowed=False,
        ),
        _room("workshop-pos", "workshop-1", "workshop", x=4, y=0, width=2),
    )
    build_hard_constraint_layer(
        blocked_model,
        buildable_cells=buildable,
        placement_options=blocked_options,
        utility_anchors=(),
        root_instance_id="airlock-1",
    )
    assert _solve(blocked_model) == cp_model.INFEASIBLE

    transit_model = cp_model.CpModel()
    transit_options = (
        blocked_options[0],
        _room("middle-pos", "middle-1", "workshop", x=2, y=0, width=2),
        blocked_options[2],
    )
    build_hard_constraint_layer(
        transit_model,
        buildable_cells=buildable,
        placement_options=transit_options,
        utility_anchors=(),
        root_instance_id="airlock-1",
    )
    assert _solve(transit_model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def _two_floor_model(*, force_elevator: bool) -> tuple[cp_model.CpModel, object]:
    model = cp_model.CpModel()
    buildable = frozenset((x, y) for y in range(2) for x in range(6))
    options = (
        _room("airlock-pos", "airlock-1", "airlock", x=0, y=0, width=2),
        _room("workshop-pos", "workshop-1", "workshop", x=4, y=1, width=2),
    )
    anchors = (UtilityAnchorSpec(2, 0), UtilityAnchorSpec(2, 1))
    variables = build_hard_constraint_layer(
        model,
        buildable_cells=buildable,
        placement_options=options,
        utility_anchors=anchors,
        root_instance_id="airlock-1",
    )
    for anchor in ((2, 0), (2, 1)):
        if force_elevator:
            model.add(variables.elevator[anchor] == 1)
            model.add(variables.corridor[anchor] == 0)
        else:
            model.add(variables.corridor[anchor] == 1)
            model.add(variables.elevator[anchor] == 0)
    return model, variables


def test_vertical_connection_requires_stacked_elevators() -> None:
    corridor_model, _ = _two_floor_model(force_elevator=False)
    assert _solve(corridor_model) == cp_model.INFEASIBLE

    elevator_model, _ = _two_floor_model(force_elevator=True)
    assert _solve(elevator_model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_overlapping_utility_anchors_cannot_both_be_selected() -> None:
    model = cp_model.CpModel()
    buildable = frozenset((x, 0) for x in range(8))
    options = (_room("airlock-pos", "airlock-1", "airlock", x=0, y=0, width=2),)
    variables = build_hard_constraint_layer(
        model,
        buildable_cells=buildable,
        placement_options=options,
        utility_anchors=(UtilityAnchorSpec(3, 0), UtilityAnchorSpec(4, 0)),
        root_instance_id="airlock-1",
    )
    model.add(variables.corridor[(3, 0)] == 1)
    model.add(variables.corridor[(4, 0)] == 1)

    assert _solve(model) == cp_model.INFEASIBLE


def test_airlock_requires_external_legal_connection() -> None:
    """Regression for H6: isolated Airlock must be INFEASIBLE.

    The Airlock (root) has no external physical connections. Per normative H6:
    "Every installed network module has at least one legal connection."

    Before fix: FEASIBLE (root flow equation 0 == 0 is trivially satisfiable)
    After fix: INFEASIBLE (explicit root external edge constraint)
    """
    model = cp_model.CpModel()
    buildable = frozenset((x, 0) for x in range(8))
    options = (
        _room("airlock-pos", "airlock-1", "airlock", x=0, y=0, width=4),
    )

    build_hard_constraint_layer(
        model,
        buildable_cells=buildable,
        placement_options=options,
        utility_anchors=(),
        root_instance_id="airlock-1",
    )

    assert _solve(model) == cp_model.INFEASIBLE


def test_airlock_with_direct_room_connection_is_feasible() -> None:
    """Positive control: Airlock with direct room connection must remain FEASIBLE.

    This verifies the H6 fix does not reject legal connected roots.
    """
    model = cp_model.CpModel()
    buildable = frozenset((x, 0) for x in range(8))
    options = (
        _room("airlock-pos", "airlock-1", "airlock", x=0, y=0, width=4),
        _room("workshop-pos", "workshop-1", "workshop", x=4, y=0, width=4),
    )

    build_hard_constraint_layer(
        model,
        buildable_cells=buildable,
        placement_options=options,
        utility_anchors=(),
        root_instance_id="airlock-1",
    )

    assert _solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
