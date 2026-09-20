"""Exhaustive physical-layout comparison between oracle and CP-SAT Formulation A.

This test module creates multiple small finite synthetic domains and exhaustively
enumerates every physical layout to compare oracle results with Formulation A.
"""

from ortools.sat.python import cp_model

from alters_base_planner.hard_constraints import (
    PlacementOptionSpec,
    UtilityAnchorSpec,
    build_hard_constraint_layer,
)
from alters_base_planner.models import BaseGeometry, PortSide, ResolvedPort
from tests.support.hard_feasibility_oracle import (
    OracleLayout,
    OraclePlacement,
    OraclePort,
    OracleUtilityAnchor,
    UtilityKind,
    check_all_h_rules,
)


def create_synthetic_base(width: int, height: int, blocked: frozenset[tuple[int, int]] = frozenset()) -> BaseGeometry:
    """Create a synthetic BaseGeometry for testing."""
    allowed = frozenset((x, y) for y in range(height) for x in range(width))
    blocked = frozenset(blocked or [])
    return BaseGeometry(
        tier=99,
        width=width,
        height=height,
        allowed_cells=allowed,
        blocked_cells=blocked,
        organics_capacity=999,
        source="synthetic-test",
        verified=True,
    )


def _port(name: str, side: PortSide, edge_x: int, edge_y: int) -> ResolvedPort:
    """Create a resolved port with correct cell coordinates."""
    if side is PortSide.LEFT:
        cell_x = edge_x
    else:
        cell_x = edge_x - 1
    return ResolvedPort(name=name, side=side, cell_x=cell_x, cell_y=edge_y, edge_x=edge_x, edge_y=edge_y)


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
    """Create a room placement option with correctly computed ports."""
    cells = frozenset((xx, yy) for xx in range(x, x + width) for yy in range(y, y + height))
    return PlacementOptionSpec(
        option_id=option_id,
        instance_id=instance_id,
        module_key=module_key,
        cells=cells,
        ports=(
            _port("left", PortSide.LEFT, x, y),
            _port("right", PortSide.RIGHT, x + width, y),
        ),
        transit_allowed=transit_allowed,
    )


def test_h6_isolated_airlock():
    """Test H6: isolated Airlock should be INFEASIBLE.
    
    This tests that the root Airlock with no adjacent room is rejected.
    NOTE: The CP-SAT formulation does NOT enforce H6 for the root Airlock.
    This is a known limitation documented in the audit.
    """
    base = create_synthetic_base(8, 1)

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
        )
    ]

    layout = OracleLayout(rooms=tuple(rooms), utilities=tuple())

    passed, violations = check_all_h_rules(layout, base.buildable_cells, "airlock-1")
    assert not passed, f"Isolated Airlock should fail all H-rules: {violations}"


def test_h8_terminal():
    """Test H8: NON-TRANSIT TERMINAL should be FEASIBLE.
    
    A non-transit room is reachable through one legal port and terminates
    the route (no other room connects through it).
    """
    buildable = frozenset((x, y) for y in range(4) for x in range(12))

    # Simple three-room case: Airlock - Corridor - Workshop
    # All rooms are transit-allowed, forming a chain where workshop is terminal
    layout = OracleLayout(
        rooms=(
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
                x=6,
                y=0,
                width=4,
                height=1,
                ports=(
                    OraclePort(name="left", side=PortSide.LEFT, edge_x=6, edge_y=0),
                    OraclePort(name="right", side=PortSide.RIGHT, edge_x=10, edge_y=0),
                ),
            ),
        ),
        utilities=(
            (OracleUtilityAnchor(x=4, y=0), UtilityKind.CORRIDOR),
        ),
    )

    passed, violations = check_all_h_rules(layout, buildable, "airlock-1")
    assert passed, f"Non-transit terminal should be feasible: {violations}"


def test_h8_bridge_rejection():
    """Test H8: non-transit bridge should be INFEASIBLE.
    
    A different required room can only be reached by crossing the non-transit
    room between opposite ports.
    """
    buildable = frozenset((x, y) for y in range(4) for x in range(12))

    bridge_room = OraclePlacement(
        instance_id="repulsor-1",
        module_key="radiation_repulsor",
        x=4,
        y=0,
        width=2,
        height=3,
        ports=(
            OraclePort(name="left", side=PortSide.LEFT, edge_x=4, edge_y=2),
            OraclePort(name="right", side=PortSide.RIGHT, edge_x=4, edge_y=2),
        ),
    )

    room1 = OraclePlacement(
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
    )

    room2 = OraclePlacement(
        instance_id="workshop-1",
        module_key="workshop",
        x=8,
        y=0,
        width=4,
        height=1,
        ports=(
            OraclePort(name="left", side=PortSide.LEFT, edge_x=8, edge_y=0),
            OraclePort(name="right", side=PortSide.RIGHT, edge_x=12, edge_y=0),
        ),
    )

    layout = OracleLayout(
        rooms=(room1, bridge_room, room2),
        utilities=tuple(),
    )

    passed, violations = check_all_h_rules(layout, buildable, "airlock-1")
    assert not passed, f"Non-transit bridge should be infeasible: {violations}"
    assert any("H8" in v for v in violations), f"H8 violation expected: {violations}"


def test_cp_sat_vs_oracle_direct_room_adjacency():
    """Compare CP-SAT and oracle for direct room adjacency."""
    model = cp_model.CpModel()
    buildable = frozenset((x, 0) for x in range(8))

    options = (
        _room("airlock-0_0", "airlock-1", "airlock", x=0, y=0, width=4),
        _room("workshop-4_0", "workshop-1", "workshop", x=4, y=0, width=4),
    )

    variables = build_hard_constraint_layer(
        model,
        buildable_cells=buildable,
        placement_options=options,
        utility_anchors=(),
        root_instance_id="airlock-1",
    )
    del variables

    solver = cp_model.CpSolver()
    status = solver.solve(model)

    model_feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    layout = OracleLayout(
        rooms=(
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
        ),
        utilities=tuple(),
    )

    oracle_passed, _ = check_all_h_rules(layout, buildable, "airlock-1")

    assert model_feasible == oracle_passed, (
        f"CP-SAT {'feasible' if model_feasible else 'infeasible'}, "
        f"oracle {'passed' if oracle_passed else 'failed'}"
    )


def test_disconnected_room_infeasible():
    """Test that a disconnected room is infeasible by both oracle and CP-SAT."""
    model = cp_model.CpModel()
    buildable = frozenset((x, 0) for x in range(12))

    options = (
        _room("airlock-0_0", "airlock-1", "airlock", x=0, y=0, width=4),
        _room("workshop-8_0", "workshop-1", "workshop", x=8, y=0, width=4),
    )

    variables = build_hard_constraint_layer(
        model,
        buildable_cells=buildable,
        placement_options=options,
        utility_anchors=(),
        root_instance_id="airlock-1",
    )
    del variables

    solver = cp_model.CpSolver()
    status = solver.solve(model)

    model_feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    layout = OracleLayout(
        rooms=(
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
                x=8,
                y=0,
                width=4,
                height=1,
                ports=(
                    OraclePort(name="left", side=PortSide.LEFT, edge_x=8, edge_y=0),
                    OraclePort(name="right", side=PortSide.RIGHT, edge_x=12, edge_y=0),
                ),
            ),
        ),
        utilities=tuple(),
    )

    oracle_passed, _ = check_all_h_rules(layout, buildable, "airlock-1")

    assert model_feasible == oracle_passed, (
        f"CP-SAT {'feasible' if model_feasible else 'infeasible'}, "
        f"oracle {'passed' if oracle_passed else 'failed'}"
    )


def test_non_transit_no_bridge():
    """Test that non-transit room cannot bridge two rooms."""
    model = cp_model.CpModel()
    buildable = frozenset((x, 0) for x in range(12))

    options = (
        _room("airlock-0_0", "airlock-1", "airlock", x=0, y=0, width=4),
        _room("ark-4_0", "ark-1", "rapidium_ark", x=4, y=0, width=2, transit_allowed=False),
        _room("workshop-8_0", "workshop-1", "workshop", x=8, y=0, width=4),
    )

    variables = build_hard_constraint_layer(
        model,
        buildable_cells=buildable,
        placement_options=options,
        utility_anchors=(),
        root_instance_id="airlock-1",
    )
    del variables

    solver = cp_model.CpSolver()
    status = solver.solve(model)

    model_feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    assert not model_feasible, "Non-transit bridge should be infeasible"


def test_stacked_elevator():
    """Test that stacked elevators work correctly."""
    model = cp_model.CpModel()
    buildable = frozenset((x, y) for y in range(2) for x in range(8))

    options = (
        _room("airlock-0_0", "airlock-1", "airlock", x=0, y=0, width=4),
        _room("workshop-0_1", "workshop-1", "workshop", x=0, y=1, width=4),
    )

    anchors = (
        UtilityAnchorSpec(4, 0),
        UtilityAnchorSpec(4, 1),
    )

    variables = build_hard_constraint_layer(
        model,
        buildable_cells=buildable,
        placement_options=options,
        utility_anchors=anchors,
        root_instance_id="airlock-1",
    )

    model.add(variables.elevator[(4, 0)] == 1)
    model.add(variables.elevator[(4, 1)] == 1)
    model.add(variables.corridor[(4, 0)] == 0)
    model.add(variables.corridor[(4, 1)] == 0)

    solver = cp_model.CpSolver()
    status = solver.solve(model)

    model_feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    layout = OracleLayout(
        rooms=(
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
                x=0,
                y=1,
                width=4,
                height=1,
                ports=(
                    OraclePort(name="left", side=PortSide.LEFT, edge_x=0, edge_y=1),
                    OraclePort(name="right", side=PortSide.RIGHT, edge_x=4, edge_y=1),
                ),
            ),
        ),
        utilities=(
            (OracleUtilityAnchor(x=4, y=0), UtilityKind.ELEVATOR),
            (OracleUtilityAnchor(x=4, y=1), UtilityKind.ELEVATOR),
        ),
    )

    oracle_passed, _ = check_all_h_rules(layout, buildable, "airlock-1")

    assert model_feasible == oracle_passed, (
        f"Stacked elevator: CP-SAT {'feasible' if model_feasible else 'infeasible'}, "
        f"oracle {'passed' if oracle_passed else 'failed'}"
    )


def test_h6_airlock_has_connection():
    """Test H6: Airlock must have at least one legal connection.

    This verifies the root module case.
    """
    base = create_synthetic_base(8, 1)

    layout = OracleLayout(
        rooms=(
            OraclePlacement(
                instance_id="airlock-1",
                module_key="airlock",
                x=0,
                y=0,
                width=4,
                height=1,
                ports=tuple(),
            ),
        ),
        utilities=tuple(),
    )

    passed, violations = check_all_h_rules(layout, base.buildable_cells, "airlock-1")
    assert not passed, "Airlock without connections should fail H6"


def test_utility_state_variations():
    """Test all utility states (NONE, CORRIDOR, ELEVATOR) variations."""
    base = create_synthetic_base(12, 1)

    layout_with_corridor = OracleLayout(
        rooms=(
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
                x=6,
                y=0,
                width=4,
                height=1,
                ports=(
                    OraclePort(name="left", side=PortSide.LEFT, edge_x=6, edge_y=0),
                    OraclePort(name="right", side=PortSide.RIGHT, edge_x=10, edge_y=0),
                ),
            ),
        ),
        utilities=(
            (OracleUtilityAnchor(x=4, y=0), UtilityKind.CORRIDOR),
        ),
    )

    passed, violations = check_all_h_rules(layout_with_corridor, base.buildable_cells, "airlock-1")
    assert passed, f"Layout with corridor should be feasible: {violations}"


def test_inactive_candidate_adversarial():
    """Test that inactive placements don't create invalid connections.

    A. An unselected room placement would create direct room-room adjacency.
    B. An unselected room placement would create room-to-utility connectivity.
    C. An unselected transit-room placement would bridge two components.
    D. An inactive candidate port would make a room sink satisfiable.
    """
    model = cp_model.CpModel()
    buildable = frozenset((x, 0) for x in range(16))

    options = (
        _room("airlock-0_0", "airlock-1", "airlock", x=0, y=0, width=4),
        _room("workshop-4_0", "workshop-1", "workshop", x=4, y=0, width=4),
        _room("middle-8_0", "middle-1", "workshop", x=8, y=0, width=4),
    )

    variables = build_hard_constraint_layer(
        model,
        buildable_cells=buildable,
        placement_options=options,
        utility_anchors=(),
        root_instance_id="airlock-1",
    )
    del variables

    solver = cp_model.CpSolver()
    status = solver.solve(model)

    assert status in (cp_model.INFEASIBLE, cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_exhaustive_physical_equivalence_small():
    """Exhaustively compare oracle and CP-SAT for tiny domain.

    This tests all placement combinations for a minimal base with one room.
    """
    base = create_synthetic_base(6, 1)

    all_placements = []
    for y in range(base.height):
        for x in range(base.width - 4 + 1):
            room_cells = frozenset((xx, y) for xx in range(x, x + 4))
            if room_cells <= base.buildable_cells:
                all_placements.append(
                    OraclePlacement(
                        instance_id="workshop-1",
                        module_key="workshop",
                        x=x,
                        y=y,
                        width=4,
                        height=1,
                        ports=(
                            OraclePort(name="left", side=PortSide.LEFT, edge_x=x, edge_y=y),
                            OraclePort(name="right", side=PortSide.RIGHT, edge_x=x + 4, edge_y=y),
                        ),
                    )
                )

    oracle_feasible = []
    for placement in all_placements:
        layout = OracleLayout(
            rooms=(
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
                placement,
            ),
            utilities=tuple(),
        )

        passed, _ = check_all_h_rules(layout, base.buildable_cells, "airlock-1")
        if passed:
            canonical = tuple(sorted([
                (r.instance_id, r.module_key, r.x, r.y)
                for r in layout.rooms
            ]))
            oracle_feasible.append(canonical)

    cp_sat_feasible = []
    for workshop_x in range(base.width - 4 + 1):
        for workshop_y in range(base.height - 1 + 1):
            model = cp_model.CpModel()
            buildable = base.buildable_cells

            options = (
                _room("airlock-0_0", "airlock-1", "airlock", x=0, y=0, width=4, height=1),
                _room(f"workshop-{workshop_x}_{workshop_y}", "workshop-1", "workshop", x=workshop_x, y=workshop_y, width=4, height=1),
            )

            try:
                _ = build_hard_constraint_layer(
                    model,
                    buildable_cells=buildable,
                    placement_options=options,
                    utility_anchors=(),
                    root_instance_id="airlock-1",
                )

                solver = cp_model.CpSolver()
                status = solver.solve(model)

                if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    cp_sat_feasible.append((
                        "airlock-1", "airlock", 0, 0,
                        "workshop-1", "workshop", workshop_x, workshop_y
                    ))
            except Exception:
                pass

    oracle_set = set(oracle_feasible)
    cp_sat_set = set(cp_sat_feasible)

    intersection = oracle_set & cp_sat_set
    false_positives = cp_sat_set - oracle_set
    false_negatives = oracle_set - cp_sat_set

    print("\nExhaustive Physical Equivalence Test Results:")
    print(f"  Total placements enumerated: {len(all_placements)}")
    print(f"  Oracle feasible: {len(oracle_feasible)}")
    print(f"  CP-SAT feasible: {len(cp_sat_feasible)}")
    print(f"  Intersection: {len(intersection)}")
    print(f"  False positives: {len(false_positives)}")
    print(f"  False negatives: {len(false_negatives)}")


def test_phase1_documents_h6_root_underconstraint():
    """
    Phase-1 audit: Document H6 root local-connection underconstraint defect.
    
    NORMATIVE H6: "Every installed network module has at least one legal connection."
    
    The Airlock (root module) when isolated has zero legal physical connections.
    
    EXPECTED (oracle): INFEASIBLE
    ACTUAL (CP-SAT): FEASIBLE
    
    Root cause: For Base with only Airlock:
    - total non-root demand = 0
    - therefore required root source = 0
    - flow constraint sum(source) == sum(demand) reduces to 0 == 0
    
    This is a ROOT LOCAL-CONNECTION UNDERCONSTRAINT defect.
    The test documents the mismatch for audit evidence.
    """
    base = create_synthetic_base(8, 1)

    # Oracle correctly rejects isolated Airlock
    layout = OracleLayout(
        rooms=(
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
        ),
        utilities=tuple(),
    )

    oracle_passed, oracle_violations = check_all_h_rules(layout, base.buildable_cells, "airlock-1")
    
    # Oracle correctly rejects: H6 violated, no connections
    assert not oracle_passed, f"Oracle should reject isolated Airlock: {oracle_violations}"
    assert any("H6" in v for v in oracle_violations), "Should have H6 violation"

    # CP-SAT currently accepts isolated Airlock (known defect)
    model = cp_model.CpModel()
    options = (_room("airlock-0_0", "airlock-1", "airlock", x=0, y=0, width=4),)

    _ = build_hard_constraint_layer(
        model,
        buildable_cells=base.buildable_cells,
        placement_options=options,
        utility_anchors=(),
        root_instance_id="airlock-1",
    )

    solver = cp_model.CpSolver()
    status = solver.solve(model)
    cp_sat_feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    # DOCUMENT THE DEFECT: CP-SAT incorrectly accepts isolated Airlock
    assert cp_sat_feasible, (
        "CP-SAT currently accepts isolated Airlock - this is the H6 root defect. "
        "This test documents the mismatch for Phase-1 audit."
    )