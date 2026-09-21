from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .models import PortSide, ResolvedPort

Cell = tuple[int, int]
Anchor = tuple[int, int]
NodeId = str


@dataclass(frozen=True, slots=True)
class PlacementOptionSpec:
    """One prevalidated legal placement option for one room instance.

    Static hard constraints belong in candidate generation: ``cells`` must already fit the
    buildable Base mask, avoid fixed obstructions and preserve the module's legal orientation.
    ``ports`` are absolute resolved ports for this concrete placement option.
    """

    option_id: str
    instance_id: str
    module_key: str
    cells: frozenset[Cell]
    ports: tuple[ResolvedPort, ...]
    transit_allowed: bool


@dataclass(frozen=True, slots=True)
class UtilityAnchorSpec:
    """A legal solver-managed 2x1 Corridor/Elevator anchor."""

    x: int
    y: int

    @property
    def anchor(self) -> Anchor:
        return (self.x, self.y)

    @property
    def cells(self) -> frozenset[Cell]:
        return frozenset({(self.x, self.y), (self.x + 1, self.y)})


@dataclass(slots=True)
class HardConstraintVariables:
    """Decision variables created by :func:`build_hard_constraint_layer`."""

    placement: dict[str, cp_model.IntVar]
    corridor: dict[Anchor, cp_model.IntVar]
    elevator: dict[Anchor, cp_model.IntVar]
    utility_active: dict[Anchor, cp_model.IntVar]
    room_sink: dict[tuple[str, NodeId], cp_model.IntVar]
    flow: dict[tuple[str, str], cp_model.IntVar]
    source_flow: dict[NodeId, cp_model.IntVar]


@dataclass(frozen=True, slots=True)
class _PortNode:
    node_id: NodeId
    instance_id: str
    option_id: str
    port: ResolvedPort
    active: cp_model.IntVar


@dataclass(frozen=True, slots=True)
class _ConditionalEdge:
    edge_id: str
    a: NodeId
    b: NodeId
    conditions: tuple[cp_model.IntVar, ...]


def _ports_directly_meet(a: ResolvedPort, b: ResolvedPort) -> bool:
    return a.edge_x == b.edge_x and a.edge_y == b.edge_y and a.side is not b.side


def _validate_input_domain(
    *,
    buildable_cells: frozenset[Cell],
    placement_options: tuple[PlacementOptionSpec, ...],
    utility_anchors: tuple[UtilityAnchorSpec, ...],
    root_instance_id: str,
) -> None:
    """Validate hard constraints that are best enforced before CP-SAT variable creation.

    Static domain rules are validated here so illegal candidates never enter the CP-SAT
    search domain: Base-mask containment (H2), resolved-port legality and geometry (H5),
    utility-anchor legality (H5/H2) and candidate/instance consistency. H4 orientation and
    fixed-core exclusion belong to upstream candidate generation, not to this function.
    Connectivity rules (H6 local connection, H7 Airlock reachability) are decision-level
    constraints and are NOT enforced here.
    """

    if not buildable_cells:
        raise ValueError("buildable_cells must not be empty")
    if not placement_options:
        raise ValueError("placement_options must not be empty")

    option_ids = [option.option_id for option in placement_options]
    if len(option_ids) != len(set(option_ids)):
        raise ValueError("placement option IDs must be unique")

    by_instance: dict[str, list[PlacementOptionSpec]] = defaultdict(list)
    for option in placement_options:
        if not option.option_id or not option.instance_id or not option.module_key:
            raise ValueError("placement option identifiers must be non-empty")
        if not option.cells:
            raise ValueError(f"Placement option {option.option_id} has no occupied cells")
        if not option.cells <= buildable_cells:
            raise ValueError(
                f"Placement option {option.option_id} leaves the buildable Base domain"
            )
        if not option.ports:
            raise ValueError(f"Placement option {option.option_id} has no legal access ports")
        port_names = [port.name for port in option.ports]
        if len(port_names) != len(set(port_names)):
            raise ValueError(f"Placement option {option.option_id} has duplicate port names")
        for port in option.ports:
            if port.cell not in option.cells:
                raise ValueError(
                    f"Resolved port {option.option_id}.{port.name} is outside its room footprint"
                )
        by_instance[option.instance_id].append(option)

    if root_instance_id not in by_instance:
        raise ValueError(f"Root instance {root_instance_id!r} has no placement options")

    for instance_id, options in by_instance.items():
        module_keys = {option.module_key for option in options}
        transit_values = {option.transit_allowed for option in options}
        if len(module_keys) != 1:
            raise ValueError(f"Instance {instance_id} mixes module types across candidates")
        if len(transit_values) != 1:
            raise ValueError(f"Instance {instance_id} mixes transit semantics across candidates")

    anchors = [utility.anchor for utility in utility_anchors]
    if len(anchors) != len(set(anchors)):
        raise ValueError("utility anchors must be unique")
    for utility in utility_anchors:
        if not utility.cells <= buildable_cells:
            raise ValueError(f"Utility anchor {utility.anchor} leaves the buildable Base domain")


def build_hard_constraint_layer(
    model: cp_model.CpModel,
    *,
    buildable_cells: frozenset[Cell],
    placement_options: tuple[PlacementOptionSpec, ...],
    utility_anchors: tuple[UtilityAnchorSpec, ...],
    root_instance_id: str,
) -> HardConstraintVariables:
    """Add the reusable hard-feasibility layer for the future integrated Base solver.

    This function intentionally does **not** define a gameplay objective. It encodes only
    feasibility and connectivity semantics (normative H1-H11; H12 journey mass remains
    outside this structural layer):

    - H1: exactly one placement option per required room instance;
    - H3: no room/utility cell overlap;
    - H9/H10: solver-managed optional Corridor/Elevator occupation on legal 2x1 anchors;
    - H5: legal direct room contacts only through matching explicit resolved ports;
    - H5: legal room-to-utility contacts only through the exact external port anchor;
    - H9/H10: horizontal utility connectivity in full 2-cell steps;
    - H10: vertical connectivity only between stacked Elevator modules;
    - H8: no internal LEFT<->RIGHT passage through terminal/non-transit rooms;
    - H7: at least one Airlock-rooted reachable port for every installed room;
    - H6: explicit Airlock local external connection (its own internal transit edge does
      not count);
    - H11: every selected Corridor/Elevator belongs to the Airlock-rooted network.

    Static rules such as Base-mask containment, fixed-core exclusion, orientation and port
    geometry are validated before variable creation because illegal candidates should not be
    present in the search domain at all.
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

    # H1: the requested/mandatory module multiplicity is represented by room instances;
    # every instance must choose exactly one legal placement candidate.
    placement: dict[str, cp_model.IntVar] = {}
    for option in placement_options:
        placement[option.option_id] = model.new_bool_var(f"room_place__{option.option_id}")
    for options in options_by_instance.values():
        model.add_exactly_one(placement[option.option_id] for option in options)

    # H9/H10: Corridor and Elevator are solver-managed 2x1 modules. They share the same
    # anchor, therefore at most one utility kind can occupy a given anchor.
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

    # H3: one physical Base cell can belong to at most one selected room or utility module.
    occupants_by_cell: dict[Cell, list[cp_model.IntVar]] = defaultdict(list)
    for option in placement_options:
        lit = placement[option.option_id]
        for cell in option.cells:
            occupants_by_cell[cell].append(lit)
    for utility in utility_anchors:
        lit = utility_active[utility.anchor]
        for cell in utility.cells:
            occupants_by_cell[cell].append(lit)
    for occupants in occupants_by_cell.values():
        if len(occupants) > 1:
            model.add_at_most_one(occupants)

    room_sink, flow, source_flow = _build_connectivity_layer(
        model,
        placement=placement,
        corridor=corridor,
        elevator=elevator,
        utility_active=utility_active,
        placement_options=placement_options,
        utility_anchors=utility_anchors,
        root_instance_id=root_instance_id,
    )

    return HardConstraintVariables(
        placement=placement,
        corridor=corridor,
        elevator=elevator,
        utility_active=utility_active,
        room_sink=room_sink,
        flow=flow,
        source_flow=source_flow,
    )


def _build_connectivity_layer(
    model: cp_model.CpModel,
    *,
    placement: dict[str, cp_model.IntVar],
    corridor: dict[Anchor, cp_model.IntVar],
    elevator: dict[Anchor, cp_model.IntVar],
    utility_active: dict[Anchor, cp_model.IntVar],
    placement_options: tuple[PlacementOptionSpec, ...],
    utility_anchors: tuple[UtilityAnchorSpec, ...],
    root_instance_id: str,
) -> tuple[
    dict[tuple[str, NodeId], cp_model.IntVar],
    dict[tuple[str, str], cp_model.IntVar],
    dict[NodeId, cp_model.IntVar],
]:
    """Build the candidate-conditioned physical graph and the rooted flow layer.

    ``placement`` maps option_id -> Boolean literal meaning "this candidate is selected".
    Formulation A passes its placement BoolVars directly; the compact Formulation B1 passes
    exact candidate-selection channel literals. Everything below depends only on those
    literals and the utility variables, so both formulations share identical connectivity
    semantics (H5/H6/H7/H8/H9/H10/H11).

    This function is an exact code-motion extraction of the former inline section of
    :func:`build_hard_constraint_layer`; it adds the same constraints in the same order.
    """

    # Create one graph node for every candidate-resolved room port. A port node is active iff
    # the corresponding room placement candidate is selected.
    port_nodes: list[_PortNode] = []
    node_active: dict[NodeId, cp_model.IntVar] = {}
    port_nodes_by_instance: dict[str, list[_PortNode]] = defaultdict(list)
    for option in placement_options:
        active = placement[option.option_id]
        for port in option.ports:
            node_id = f"room:{option.instance_id}:{option.option_id}:port:{port.name}"
            node = _PortNode(
                node_id=node_id,
                instance_id=option.instance_id,
                option_id=option.option_id,
                port=port,
                active=active,
            )
            port_nodes.append(node)
            port_nodes_by_instance[option.instance_id].append(node)
            node_active[node_id] = active

    # One graph node per optional utility anchor. Corridor and Elevator share the horizontal
    # node; only the Elevator kind enables vertical graph edges.
    utility_node: dict[Anchor, NodeId] = {}
    for utility in utility_anchors:
        anchor = utility.anchor
        node_id = f"utility:{utility.x}:{utility.y}"
        utility_node[anchor] = node_id
        node_active[node_id] = utility_active[anchor]

    edges: list[_ConditionalEdge] = []
    edge_counter = 0

    def add_edge(a: NodeId, b: NodeId, *conditions: cp_model.IntVar) -> None:
        nonlocal edge_counter
        if a == b:
            return
        edges.append(
            _ConditionalEdge(
                edge_id=f"edge_{edge_counter}",
                a=a,
                b=b,
                conditions=tuple(conditions),
            )
        )
        edge_counter += 1

    # H8: a transit room joins its LEFT and RIGHT port sides internally (transit_allowed).
    # A terminal/non-transit room has no such internal edge, so it can be reached but cannot
    # serve as a bridge.
    for option in placement_options:
        if not option.transit_allowed:
            continue
        option_nodes = [node for node in port_nodes if node.option_id == option.option_id]
        left = [node for node in option_nodes if node.port.side is PortSide.LEFT]
        right = [node for node in option_nodes if node.port.side is PortSide.RIGHT]
        for left_node in left:
            for right_node in right:
                add_edge(
                    left_node.node_id,
                    right_node.node_id,
                    placement[option.option_id],
                )

    # H5: direct room-to-room contact exists only where opposite explicit resolved ports meet.
    left_index: dict[tuple[int, int], list[_PortNode]] = defaultdict(list)
    right_index: dict[tuple[int, int], list[_PortNode]] = defaultdict(list)
    for node in port_nodes:
        key = (node.port.edge_x, node.port.edge_y)
        if node.port.side is PortSide.LEFT:
            left_index[key].append(node)
        else:
            right_index[key].append(node)
    for boundary, left_nodes in left_index.items():
        for left_node in left_nodes:
            for right_node in right_index.get(boundary, []):
                if left_node.instance_id == right_node.instance_id:
                    continue
                if not _ports_directly_meet(left_node.port, right_node.port):
                    continue
                add_edge(
                    left_node.node_id,
                    right_node.node_id,
                    left_node.active,
                    right_node.active,
                )

    # H5: a room can join a utility module only at the exact 2x1 external anchor derived from
    # its resolved explicit port.
    for node in port_nodes:
        anchor = node.port.utility_anchor
        utility_graph_node = utility_node.get(anchor)
        if utility_graph_node is None:
            continue
        add_edge(
            node.node_id,
            utility_graph_node,
            node.active,
            utility_active[anchor],
        )

    utility_by_anchor = {utility.anchor: utility for utility in utility_anchors}

    # H9/H10: horizontal utility connectivity advances by one complete 2x1 module, i.e. x+2.
    # Both Corridor and Elevator modules may participate in horizontal transfer on a floor.
    for anchor in sorted(utility_by_anchor):
        x, y = anchor
        right_anchor = (x + 2, y)
        if right_anchor not in utility_by_anchor:
            continue
        add_edge(
            utility_node[anchor],
            utility_node[right_anchor],
            utility_active[anchor],
            utility_active[right_anchor],
        )

    # H10: vertical travel exists only through immediately stacked Elevator modules at the
    # same x coordinate. This also permits shifted shafts only through a real horizontal
    # transfer path on a shared floor; no global single-x shaft rule is imposed.
    for anchor in sorted(utility_by_anchor):
        x, y = anchor
        below_anchor = (x, y + 1)
        if below_anchor not in utility_by_anchor:
            continue
        add_edge(
            utility_node[anchor],
            utility_node[below_anchor],
            elevator[anchor],
            elevator[below_anchor],
        )

    # H7: exact Airlock-rooted reachability via single-commodity flow.
    # Every non-root room consumes one unit of flow at exactly one selected active port.
    # Every selected utility consumes one unit too, excluding floating utility islands (H11).
    # The source may inject flow only into active Airlock/root ports.
    room_sink: dict[tuple[str, NodeId], cp_model.IntVar] = {}
    demand_terms_by_node: dict[NodeId, list[cp_model.IntVar]] = defaultdict(list)

    for instance_id, nodes in port_nodes_by_instance.items():
        if instance_id == root_instance_id:
            continue
        sinks: list[cp_model.IntVar] = []
        for node in nodes:
            sink = model.new_bool_var(f"sink__{instance_id}__{node.node_id}")
            room_sink[(instance_id, node.node_id)] = sink
            model.add(sink <= node.active)
            sinks.append(sink)
            demand_terms_by_node[node.node_id].append(sink)
        # Exactly one reachable port is sufficient; a room is not required to connect both sides.
        model.add_exactly_one(sinks)

    # A selected Corridor/Elevator must itself belong to the Airlock-rooted access network.
    for anchor, node_id in utility_node.items():
        demand_terms_by_node[node_id].append(utility_active[anchor])

    max_flow = max(
        1,
        len({option.instance_id for option in placement_options}) - 1 + len(utility_anchors),
    )
    incoming: dict[NodeId, list[cp_model.IntVar]] = defaultdict(list)
    outgoing: dict[NodeId, list[cp_model.IntVar]] = defaultdict(list)
    flow: dict[tuple[str, str], cp_model.IntVar] = {}

    for edge in edges:
        forward = model.new_int_var(0, max_flow, f"flow__{edge.edge_id}__ab")
        backward = model.new_int_var(0, max_flow, f"flow__{edge.edge_id}__ba")
        flow[(edge.edge_id, "ab")] = forward
        flow[(edge.edge_id, "ba")] = backward
        for condition in edge.conditions:
            model.add(forward <= max_flow * condition)
            model.add(backward <= max_flow * condition)
        outgoing[edge.a].append(forward)
        incoming[edge.b].append(forward)
        outgoing[edge.b].append(backward)
        incoming[edge.a].append(backward)

    root_nodes = port_nodes_by_instance[root_instance_id]
    source_flow: dict[NodeId, cp_model.IntVar] = {}
    for node in root_nodes:
        source = model.new_int_var(0, max_flow, f"source__{node.node_id}")
        model.add(source <= max_flow * node.active)
        source_flow[node.node_id] = source

    all_demand_terms = [term for terms in demand_terms_by_node.values() for term in terms]

    for node_id in node_active:
        node_in = sum(incoming[node_id])
        node_out = sum(outgoing[node_id])
        source = source_flow.get(node_id, 0)
        demand = sum(demand_terms_by_node[node_id])
        model.add(node_in + source - node_out == demand)

    model.add(sum(source_flow.values()) == sum(all_demand_terms))

    # H6 (local connection): Airlock (root) must have at least one ACTIVE EXTERNAL physical
    # connection. Internal transit edges (LEFT<->RIGHT within the same room) do NOT satisfy
    # H6. A root connection must be to another room or a selected utility anchor.
    root_node_ids = {node.node_id for node in root_nodes}
    root_external_edge_literals: list[cp_model.IntVar] = []
    for edge in edges:
        a_is_root = edge.a in root_node_ids
        b_is_root = edge.b in root_node_ids
        # External connection: exactly one endpoint is a root port, the other is not
        if a_is_root ^ b_is_root:
            # Create a literal representing: ALL edge.conditions are true
            edge_active = model.new_bool_var(f"root_ext_edge__{edge.edge_id}")
            for condition in edge.conditions:
                # edge_active <= condition (if edge_active then all conditions true)
                model.add(edge_active <= condition)
            # All conditions true => edge_active (equivalence)
            if edge.conditions:
                model.add(sum(edge.conditions) - len(edge.conditions) + 1 <= edge_active)
            else:
                model.add(edge_active == 1)
            root_external_edge_literals.append(edge_active)

    if root_external_edge_literals:
        model.add(sum(root_external_edge_literals) >= 1)
    else:
        # No possible external connection for root: structurally infeasible
        model.add(1 == 0)

    return room_sink, flow, source_flow
