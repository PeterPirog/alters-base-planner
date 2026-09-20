"""Tests for the independent hard-feasibility oracle.

These tests verify that the oracle correctly checks H-rules for tiny
synthetic layouts.
"""

from alters_base_planner.models import PortSide
from tests.support.hard_feasibility_oracle import (
    OracleLayout,
    OraclePlacement,
    OraclePort,
    OracleUtilityAnchor,
    UtilityKind,
    check_all_h_rules,
    check_h2_base_mask,
    check_h3_overlap,
    check_h6_local_connection,
    check_h7_airlock_reachability,
    check_h8_non_transit,
)


def test_h2_base_mask_violation():
    """Test that H2 detects rooms outside buildable cells."""
    buildable = frozenset({(0, 0), (1, 0), (2, 0)})

    room = OraclePlacement(
        instance_id="airlock-1",
        module_key="airlock",
        x=0,
        y=0,
        width=2,
        height=1,
        ports=(
            OraclePort(name="left", side=PortSide.LEFT, edge_x=0, edge_y=0),
            OraclePort(name="right", side=PortSide.RIGHT, edge_x=2, edge_y=0),
        ),
    )

    layout = OracleLayout(rooms=(room,), utilities=tuple())

    passed, violations = check_h2_base_mask(layout, buildable)
    assert passed


def test_h2_base_mask_outside():
    """Test that H2 detects rooms outside buildable cells."""
    buildable = frozenset({(0, 0), (1, 0), (2, 0)})

    room = OraclePlacement(
        instance_id="airlock-1",
        module_key="airlock",
        x=3,
        y=0,
        width=2,
        height=1,
        ports=(
            OraclePort(name="left", side=PortSide.LEFT, edge_x=3, edge_y=0),
            OraclePort(name="right", side=PortSide.RIGHT, edge_x=5, edge_y=0),
        ),
    )

    layout = OracleLayout(rooms=(room,), utilities=tuple())

    passed, violations = check_h2_base_mask(layout, buildable)
    assert not passed
    assert len(violations) == 1
    assert "H2" in violations[0]


def test_h3_overlap_detection():
    """Test that H3 detects overlapping rooms."""
    buildable = frozenset({(0, 0), (1, 0), (2, 0), (3, 0)})

    room1 = OraclePlacement(
        instance_id="airlock-1",
        module_key="airlock",
        x=0,
        y=0,
        width=2,
        height=1,
        ports=(
            OraclePort(name="left", side=PortSide.LEFT, edge_x=0, edge_y=0),
            OraclePort(name="right", side=PortSide.RIGHT, edge_x=2, edge_y=0),
        ),
    )

    room2 = OraclePlacement(
        instance_id="workshop-1",
        module_key="workshop",
        x=1,
        y=0,
        width=2,
        height=1,
        ports=(
            OraclePort(name="left", side=PortSide.LEFT, edge_x=1, edge_y=0),
            OraclePort(name="right", side=PortSide.RIGHT, edge_x=3, edge_y=0),
        ),
    )

    layout = OracleLayout(rooms=(room1, room2), utilities=tuple())

    passed, violations = check_h3_overlap(layout)
    assert not passed
    assert len(violations) == 1
    assert "H3" in violations[0]


def test_h3_no_overlap():
    """Test that H3 passes for non-overlapping rooms."""
    rooms = [
        OraclePlacement(
            instance_id="airlock-1",
            module_key="airlock",
            x=0,
            y=0,
            width=2,
            height=1,
            ports=(
                OraclePort(name="left", side=PortSide.LEFT, edge_x=0, edge_y=0),
                OraclePort(name="right", side=PortSide.RIGHT, edge_x=2, edge_y=0),
            ),
        ),
        OraclePlacement(
            instance_id="workshop-1",
            module_key="workshop",
            x=2,
            y=0,
            width=2,
            height=1,
            ports=(
                OraclePort(name="left", side=PortSide.LEFT, edge_x=2, edge_y=0),
                OraclePort(name="right", side=PortSide.RIGHT, edge_x=4, edge_y=0),
            ),
        ),
    ]

    layout = OracleLayout(rooms=tuple(rooms), utilities=tuple())

    passed, violations = check_h3_overlap(layout)
    assert passed


def test_h6_local_connection():
    """Test H6: rooms with no connections are invalid."""
    room1 = OraclePlacement(
        instance_id="airlock-1",
        module_key="airlock",
        x=0,
        y=0,
        width=2,
        height=1,
        ports=(
            OraclePort(name="left", side=PortSide.LEFT, edge_x=0, edge_y=0),
            OraclePort(name="right", side=PortSide.RIGHT, edge_x=2, edge_y=0),
        ),
    )

    room2 = OraclePlacement(
        instance_id="workshop-1",
        module_key="workshop",
        x=10,
        y=0,
        width=2,
        height=1,
        ports=(
            OraclePort(name="left", side=PortSide.LEFT, edge_x=10, edge_y=0),
            OraclePort(name="right", side=PortSide.RIGHT, edge_x=12, edge_y=0),
        ),
    )

    layout = OracleLayout(rooms=(room1, room2), utilities=tuple())

    passed, violations = check_h6_local_connection(layout)
    assert not passed


def test_h6_rooms_connected():
    """Test H6: rooms that are connected pass."""
    room1 = OraclePlacement(
        instance_id="airlock-1",
        module_key="airlock",
        x=0,
        y=0,
        width=2,
        height=1,
        ports=(
            OraclePort(name="left", side=PortSide.LEFT, edge_x=0, edge_y=0),
            OraclePort(name="right", side=PortSide.RIGHT, edge_x=2, edge_y=0),
        ),
    )

    room2 = OraclePlacement(
        instance_id="workshop-1",
        module_key="workshop",
        x=2,
        y=0,
        width=2,
        height=1,
        ports=(
            OraclePort(name="left", side=PortSide.LEFT, edge_x=2, edge_y=0),
            OraclePort(name="right", side=PortSide.RIGHT, edge_x=4, edge_y=0),
        ),
    )

    layout = OracleLayout(rooms=(room1, room2), utilities=tuple())

    passed, violations = check_h6_local_connection(layout)
    assert passed, f"Unexpected violations: {violations}"


def test_h7_airlock_reachability():
    """Test H7: all rooms reachable from Airlock."""
    rooms = [
        OraclePlacement(
            instance_id="airlock-1",
            module_key="airlock",
            x=0,
            y=0,
            width=2,
            height=1,
            ports=(
                OraclePort(name="left", side=PortSide.LEFT, edge_x=0, edge_y=0),
                OraclePort(name="right", side=PortSide.RIGHT, edge_x=2, edge_y=0),
            ),
        ),
        OraclePlacement(
            instance_id="workshop-1",
            module_key="workshop",
            x=2,
            y=0,
            width=2,
            height=1,
            ports=(
                OraclePort(name="left", side=PortSide.LEFT, edge_x=2, edge_y=0),
                OraclePort(name="right", side=PortSide.RIGHT, edge_x=4, edge_y=0),
            ),
        ),
    ]

    layout = OracleLayout(rooms=tuple(rooms), utilities=tuple())

    passed, violations = check_h7_airlock_reachability(layout)
    assert passed, f"Unexpected violations: {violations}"


def test_h7_disconnected_room():
    """Test H7: disconnected room fails."""
    room1 = OraclePlacement(
        instance_id="airlock-1",
        module_key="airlock",
        x=0,
        y=0,
        width=2,
        height=1,
        ports=(
            OraclePort(name="left", side=PortSide.LEFT, edge_x=0, edge_y=0),
            OraclePort(name="right", side=PortSide.RIGHT, edge_x=2, edge_y=0),
        ),
    )

    room2 = OraclePlacement(
        instance_id="workshop-1",
        module_key="workshop",
        x=10,
        y=0,
        width=2,
        height=1,
        ports=(
            OraclePort(name="left", side=PortSide.LEFT, edge_x=10, edge_y=0),
            OraclePort(name="right", side=PortSide.RIGHT, edge_x=12, edge_y=0),
        ),
    )

    layout = OracleLayout(rooms=(room1, room2), utilities=tuple())

    passed, violations = check_h7_airlock_reachability(layout)
    assert not passed
    assert "H7" in violations[0]


def test_h8_non_transit_no_internal_bridge():
    """Test H8: non-transit rooms should not have internal left-right bridges.

    This tests that a non-transit room with ports at DIFFERENT coordinates
    (no internal bridge) passes.
    """
    room = OraclePlacement(
        instance_id="repulsor-1",
        module_key="radiation_repulsor",
        x=0,
        y=0,
        width=2,
        height=1,
        ports=(
            OraclePort(name="left", side=PortSide.LEFT, edge_x=0, edge_y=0),
            OraclePort(name="right", side=PortSide.RIGHT, edge_x=2, edge_y=0),
        ),
    )

    layout = OracleLayout(rooms=(room,), utilities=tuple())

    passed, violations = check_h8_non_transit(layout)
    assert passed, f"Non-transit room without internal bridge should pass: {violations}"


def test_h8_non_transit_with_internal_bridge():
    """Test H8: non-transit room with internal bridge fails.

    This tests that a non-transit room with left and right ports at the
    SAME coordinate (internal bridge) fails.
    """
    room = OraclePlacement(
        instance_id="repulsor-1",
        module_key="radiation_repulsor",
        x=0,
        y=0,
        width=1,
        height=1,
        ports=(
            OraclePort(name="left", side=PortSide.LEFT, edge_x=0, edge_y=0),
            OraclePort(name="right", side=PortSide.RIGHT, edge_x=0, edge_y=0),
        ),
    )

    layout = OracleLayout(rooms=(room,), utilities=tuple())

    passed, violations = check_h8_non_transit(layout)
    assert not passed, "Non-transit room with internal bridge should fail"
    assert "H8" in violations[0]


def test_h8_transit_room_ok():
    """Test H8: transit rooms can bridge."""
    room1 = OraclePlacement(
        instance_id="airlock-1",
        module_key="airlock",
        x=0,
        y=0,
        width=2,
        height=1,
        ports=(
            OraclePort(name="left", side=PortSide.LEFT, edge_x=0, edge_y=0),
            OraclePort(name="right", side=PortSide.RIGHT, edge_x=2, edge_y=0),
        ),
    )

    room2 = OraclePlacement(
        instance_id="middle-1",
        module_key="workshop",
        x=2,
        y=0,
        width=2,
        height=1,
        ports=(
            OraclePort(name="left", side=PortSide.LEFT, edge_x=2, edge_y=0),
            OraclePort(name="right", side=PortSide.RIGHT, edge_x=4, edge_y=0),
        ),
    )

    room3 = OraclePlacement(
        instance_id="workshop-1",
        module_key="workshop",
        x=4,
        y=0,
        width=2,
        height=1,
        ports=(
            OraclePort(name="left", side=PortSide.LEFT, edge_x=4, edge_y=0),
            OraclePort(name="right", side=PortSide.RIGHT, edge_x=6, edge_y=0),
        ),
    )

    layout = OracleLayout(rooms=tuple([room1, room2, room3]), utilities=tuple())

    passed, violations = check_h8_non_transit(layout)
    assert passed


def test_all_h_rules_feasible_layout():
    """Test a feasible layout passes all checks."""
    rooms = [
        OraclePlacement(
            instance_id="airlock-1",
            module_key="airlock",
            x=0,
            y=0,
            width=4,
            height=1,
            ports=(
                OraclePort(name="left", side=PortSide.LEFT, edge_x=0, edge_y=0),
                OraclePort(name="right", side=PortSide.RIGHT, edge_x=4, edge_y=0),
            ),
        ),
        OraclePlacement(
            instance_id="workshop-1",
            module_key="workshop",
            x=4,
            y=0,
            width=4,
            height=1,
            ports=(
                OraclePort(name="left", side=PortSide.LEFT, edge_x=4, edge_y=0),
                OraclePort(name="right", side=PortSide.RIGHT, edge_x=8, edge_y=0),
            ),
        ),
    ]

    buildable = frozenset((x, 0) for x in range(9))
    layout = OracleLayout(rooms=tuple(rooms), utilities=tuple())

    passed, violations = check_all_h_rules(layout, buildable, "airlock-1")
    assert passed, f"Unexpected violations: {violations}"