from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from ortools.sat.python import cp_model

from .catalog import MODULE_BY_KEY
from .distance import DistanceMetrics, evaluate_distances
from .integrated_hard_solver import compile_fixed_layout_hard_model, extract_integrated_solution
from .models import (
    BaseGeometry,
    ModulePlacement,
    PlacementAuthority,
    PortSide,
    ResolvedPort,
    resolve_ports,
)
from .objective import ObjectivePair, build_scaled_objective

NodeId = str
Anchor = tuple[int, int]


@dataclass(frozen=True, slots=True)
class FixedFlowObjectiveDiagnostics:
    """Performance and proof diagnostics for one fixed-packing exact objective subproblem.

    Counts describe the single lexicographic-scalarized pair-flow model. The objective bounds and
    mixed-radix weights make the signed-64-bit safety calculation auditable. The incumbent scalar
    value is reported separately from those safety bounds. Timings are wall-clock measurements for
    performance analysis only; they never participate in correctness or objective decisions.
    """

    graph_node_count: int = 0
    graph_arc_count: int = 0
    objective_pair_count: int = 0
    pair_flow_variable_count: int = 0
    pair_flow_full_variable_count: int = 0
    cp_sat_variable_count: int = 0
    cp_sat_constraint_count: int = 0
    lexicographic_scalarization_used: bool = False
    primary_objective_upper_bound: int = 0
    combined_objective_upper_bound: int = 0
    weight_f: int = 0
    weight_mass: int = 0
    weight_elevator: int = 0
    weight_corridor: int = 0
    corridor_bound: int = 0
    elevator_bound: int = 0
    mass_bound: int = 0
    incumbent_scalar_value: int | None = None
    model_build_time_s: float = 0.0
    cp_sat_solve_time_s: float = 0.0
    total_time_s: float = 0.0


@dataclass(frozen=True, slots=True)
class FixedFlowObjectiveResult:
    """Exact fixed-packing objective result from the scalable pair-flow formulation.

    The formulation jointly selects Corridor/Elevator infrastructure and one legal path for
    every positive-weight endpoint pair. Its primary integer objective is exactly the accepted
    weighted distance ``F`` after rational scaling. The accepted lexicographic order
    (``F`` then utility mass then Elevator count then Corridor count) is enforced by a single
    exact mixed-radix scalarized objective with dominance weights proven from valid finite bounds,
    so one CP-SAT solve replaces the previous sequential tie-breaker phases.

    ``lexicographic_objective_value`` is the exact scalar value of that objective for the
    returned incumbent; it is meaningful only together with the dominance weights recorded in
    ``diagnostics``.
    """

    status: str
    utilities: tuple[ModulePlacement, ...] = ()
    distance_metrics: DistanceMetrics | None = None
    objective_scale: int = 1
    scaled_objective_value: int | None = None
    primary_objective_optimum_proven: bool = False
    lexicographic_optimum_proven: bool = False
    completed_phase: str = "none"
    time_limit_reached: bool = False
    lexicographic_objective_value: int | None = None
    diagnostics: FixedFlowObjectiveDiagnostics = FixedFlowObjectiveDiagnostics()


@dataclass(frozen=True, slots=True)
class _Arc:
    arc_id: str
    source: NodeId
    target: NodeId
    cost: int
    conditions: tuple[cp_model.IntVar, ...] = ()


@dataclass(frozen=True, slots=True)
class _PairFlowDomain:
    """Exact pair-specific subgraph that can participate in a source-to-target path."""

    source_nodes: tuple[NodeId, ...]
    target_nodes: tuple[NodeId, ...]
    nodes: tuple[NodeId, ...]
    arc_indices: tuple[int, ...]


def _ports_directly_meet(a: ResolvedPort, b: ResolvedPort) -> bool:
    return a.edge_x == b.edge_x and a.edge_y == b.edge_y and a.side is not b.side


def _build_path_graph(
    rooms: tuple[ModulePlacement, ...],
    compiled,
) -> tuple[
    tuple[NodeId, ...],
    dict[str, tuple[NodeId, ...]],
    tuple[_Arc, ...],
]:
    """Build the exact directed travel graph used by the pair-flow objective model."""

    nodes: list[NodeId] = []
    room_nodes: dict[str, tuple[NodeId, ...]] = {}
    node_by_port: dict[tuple[str, str], NodeId] = {}
    resolved_by_room: dict[str, tuple[ResolvedPort, ...]] = {}
    arcs: list[_Arc] = []
    arc_counter = 0

    def add_arc(
        source: NodeId,
        target: NodeId,
        cost: int,
        *conditions: cp_model.IntVar,
    ) -> None:
        nonlocal arc_counter
        if cost < 0:
            raise AssertionError("Travel arc cost must be non-negative")
        arcs.append(
            _Arc(
                arc_id=f"arc_{arc_counter}",
                source=source,
                target=target,
                cost=cost,
                conditions=tuple(conditions),
            )
        )
        arc_counter += 1

    for room in rooms:
        spec = MODULE_BY_KEY[room.module_key]
        ports = resolve_ports(room, spec)
        resolved_by_room[room.instance_id] = ports
        port_nodes: list[NodeId] = []
        for port in ports:
            node_id = f"room:{room.instance_id}:port:{port.name}"
            nodes.append(node_id)
            port_nodes.append(node_id)
            node_by_port[(room.instance_id, port.name)] = node_id
        room_nodes[room.instance_id] = tuple(port_nodes)

        if spec.transit_allowed:
            left = [port for port in ports if port.side is PortSide.LEFT]
            right = [port for port in ports if port.side is PortSide.RIGHT]
            for left_port in left:
                for right_port in right:
                    left_node = node_by_port[(room.instance_id, left_port.name)]
                    right_node = node_by_port[(room.instance_id, right_port.name)]
                    add_arc(left_node, right_node, room.width)
                    add_arc(right_node, left_node, room.width)

    # Direct room adjacency costs zero and is available only at opposite matching port edges.
    for room_index, room_a in enumerate(rooms):
        for room_b in rooms[room_index + 1 :]:
            for port_a in resolved_by_room[room_a.instance_id]:
                for port_b in resolved_by_room[room_b.instance_id]:
                    if not _ports_directly_meet(port_a, port_b):
                        continue
                    node_a = node_by_port[(room_a.instance_id, port_a.name)]
                    node_b = node_by_port[(room_b.instance_id, port_b.name)]
                    add_arc(node_a, node_b, 0)
                    add_arc(node_b, node_a, 0)

    utility_nodes: dict[Anchor, NodeId] = {}
    for anchor in sorted(compiled.variables.utility_active):
        node_id = f"utility:{anchor[0]}:{anchor[1]}"
        utility_nodes[anchor] = node_id
        nodes.append(node_id)

    # Entering a selected Corridor/Elevator contributes +1. Entering an endpoint/intermediate
    # room port contributes zero; any side-to-side room crossing is represented above.
    for room in rooms:
        for port in resolved_by_room[room.instance_id]:
            anchor = port.utility_anchor
            utility_node = utility_nodes.get(anchor)
            if utility_node is None:
                continue
            room_node = node_by_port[(room.instance_id, port.name)]
            utility_active = compiled.variables.utility_active[anchor]
            add_arc(room_node, utility_node, 1, utility_active)
            add_arc(utility_node, room_node, 0, utility_active)

    # Horizontal utility adjacency advances by one complete 2x1 module.
    for anchor, node in utility_nodes.items():
        x, y = anchor
        right_anchor = (x + 2, y)
        right_node = utility_nodes.get(right_anchor)
        if right_node is None:
            continue
        active = compiled.variables.utility_active
        add_arc(node, right_node, 1, active[anchor], active[right_anchor])
        add_arc(right_node, node, 1, active[anchor], active[right_anchor])

    # Vertical movement is legal only through immediately stacked Elevator modules.
    for anchor, node in utility_nodes.items():
        x, y = anchor
        below_anchor = (x, y + 1)
        below_node = utility_nodes.get(below_anchor)
        if below_node is None:
            continue
        elevator = compiled.variables.elevator
        add_arc(node, below_node, 1, elevator[anchor], elevator[below_anchor])
        add_arc(below_node, node, 1, elevator[anchor], elevator[below_anchor])

    if len(nodes) != len(set(nodes)):
        raise AssertionError("Fixed objective graph node IDs must be unique")
    return tuple(nodes), room_nodes, tuple(arcs)


def _reachable_nodes(
    starts: tuple[NodeId, ...],
    *,
    arcs: tuple[_Arc, ...],
    adjacency: dict[NodeId, list[int]],
    allowed_arc_indices: set[int],
    reverse: bool,
) -> set[NodeId]:
    """Return reachability in the unconditional directed supergraph."""

    reached = set(starts)
    stack = list(starts)
    while stack:
        node = stack.pop()
        for arc_index in adjacency[node]:
            if arc_index not in allowed_arc_indices:
                continue
            arc = arcs[arc_index]
            next_node = arc.source if reverse else arc.target
            if next_node not in reached:
                reached.add(next_node)
                stack.append(next_node)
    return reached


def _pair_flow_domain(
    *,
    nodes: tuple[NodeId, ...],
    arcs: tuple[_Arc, ...],
    source_nodes: tuple[NodeId, ...],
    target_nodes: tuple[NodeId, ...],
    incoming_arcs: dict[NodeId, list[int]],
    outgoing_arcs: dict[NodeId, list[int]],
) -> _PairFlowDomain:
    """Remove arcs that cannot belong to any legal endpoint-to-endpoint path.

    The graph used here ignores arc-selection conditions, so it is a supergraph of every
    realizable infrastructure graph. Removing an arc that is not on any source-to-target path in
    this relaxation therefore cannot remove a realizable path. Endpoint ports are also terminals:
    entering the source or leaving the destination is unnecessary because every non-negative-cost
    walk contains an equal-or-better simple source-to-target path without such endpoint revisits.
    """

    source_set = set(source_nodes)
    target_set = set(target_nodes)
    allowed_arc_indices = {
        arc_index
        for arc_index, arc in enumerate(arcs)
        if arc.target not in source_set and arc.source not in target_set
    }

    forward = _reachable_nodes(
        source_nodes,
        arcs=arcs,
        adjacency=outgoing_arcs,
        allowed_arc_indices=allowed_arc_indices,
        reverse=False,
    )
    backward = _reachable_nodes(
        target_nodes,
        arcs=arcs,
        adjacency=incoming_arcs,
        allowed_arc_indices=allowed_arc_indices,
        reverse=True,
    )
    relevant_nodes = forward & backward
    relevant_sources = tuple(node for node in source_nodes if node in relevant_nodes)
    relevant_targets = tuple(node for node in target_nodes if node in relevant_nodes)
    relevant_arcs = tuple(
        arc_index
        for arc_index in sorted(allowed_arc_indices)
        if arcs[arc_index].source in relevant_nodes and arcs[arc_index].target in relevant_nodes
    )
    return _PairFlowDomain(
        source_nodes=relevant_sources,
        target_nodes=relevant_targets,
        nodes=tuple(node for node in nodes if node in relevant_nodes),
        arc_indices=relevant_arcs,
    )


def _endpoint_choice(
    model: cp_model.CpModel,
    *,
    pair_id: str,
    role: str,
    nodes: tuple[NodeId, ...],
) -> dict[NodeId, cp_model.IntVar | int]:
    """Represent endpoint choice without variables when only one port remains possible."""

    if not nodes:
        raise ValueError("Endpoint choice requires at least one candidate node")
    if len(nodes) == 1:
        return {nodes[0]: 1}

    choices: dict[NodeId, cp_model.IntVar | int] = {
        node: model.new_bool_var(f"pair_{role}__{pair_id}__{node}") for node in nodes
    }
    model.add_exactly_one(choices.values())
    return choices


def _add_pair_flow_objective(
    model: cp_model.CpModel,
    *,
    nodes: tuple[NodeId, ...],
    room_nodes: dict[str, tuple[NodeId, ...]],
    arcs: tuple[_Arc, ...],
    pairs: tuple[ObjectivePair, ...],
) -> tuple[cp_model.LinearExpr | int, int, int]:
    """Add exact pair flows after proof-safe pair-specific domain reduction.

    Returns the weighted objective expression, the number of arc-flow Boolean variables actually
    created and the number that the previous full `pairs x arcs` formulation would have created.
    """

    incoming_arcs: dict[NodeId, list[int]] = {node: [] for node in nodes}
    outgoing_arcs: dict[NodeId, list[int]] = {node: [] for node in nodes}
    for arc_index, arc in enumerate(arcs):
        outgoing_arcs[arc.source].append(arc_index)
        incoming_arcs[arc.target].append(arc_index)

    weighted_terms = []
    pair_flow_variable_count = 0
    pair_flow_full_variable_count = len(arcs) * len(pairs)
    for pair in pairs:
        domain = _pair_flow_domain(
            nodes=nodes,
            arcs=arcs,
            source_nodes=room_nodes[pair.source_instance_id],
            target_nodes=room_nodes[pair.target_instance_id],
            incoming_arcs=incoming_arcs,
            outgoing_arcs=outgoing_arcs,
        )
        if not domain.source_nodes or not domain.target_nodes:
            model.add_bool_or([])
            continue

        source_choice = _endpoint_choice(
            model,
            pair_id=pair.pair_id,
            role="source",
            nodes=domain.source_nodes,
        )
        target_choice = _endpoint_choice(
            model,
            pair_id=pair.pair_id,
            role="target",
            nodes=domain.target_nodes,
        )

        flow = {
            arc_index: model.new_bool_var(
                f"pair_flow__{pair.pair_id}__{arcs[arc_index].arc_id}"
            )
            for arc_index in domain.arc_indices
        }
        pair_flow_variable_count += len(flow)
        for arc_index, variable in flow.items():
            for condition in arcs[arc_index].conditions:
                model.add(variable <= condition)

        for node in domain.nodes:
            incoming = sum(
                flow[index] for index in incoming_arcs[node] if index in flow
            )
            outgoing = sum(
                flow[index] for index in outgoing_arcs[node] if index in flow
            )
            source = source_choice.get(node, 0)
            target = target_choice.get(node, 0)
            model.add(incoming + source == outgoing + target)

        path_cost = sum(arcs[index].cost * variable for index, variable in flow.items())
        weighted_terms.append(pair.coefficient * path_cost)

    return sum(weighted_terms), pair_flow_variable_count, pair_flow_full_variable_count


def _extract_utilities(
    solver: cp_model.CpSolver,
    compiled,
) -> tuple[ModulePlacement, ...]:
    return tuple(
        module
        for module in extract_integrated_solution(solver, compiled)
        if MODULE_BY_KEY[module.module_key].authority is PlacementAuthority.SOLVER
    )


def _evaluate_solution(
    solver: cp_model.CpSolver,
    compiled,
    rooms: tuple[ModulePlacement, ...],
) -> tuple[tuple[ModulePlacement, ...], DistanceMetrics]:
    utilities = _extract_utilities(solver, compiled)
    try:
        metrics = evaluate_distances(list(rooms), list(utilities))
    except ValueError as exc:
        raise AssertionError(
            "Pair-flow objective model returned infrastructure rejected by the exact evaluator"
        ) from exc
    return utilities, metrics


def _validate_model(model: cp_model.CpModel, phase: str) -> None:
    validation_error = model.validate()
    if validation_error:
        raise AssertionError(f"Invalid fixed pair-flow model during {phase}: {validation_error}")


def _solve_phase(
    solver: cp_model.CpSolver,
    model: cp_model.CpModel,
    *,
    deadline: float,
    phase: str,
) -> tuple[cp_model.CpSolverStatus, float]:
    remaining = deadline - monotonic()
    if remaining <= 0:
        return cp_model.UNKNOWN, 0.0
    solver.parameters.max_time_in_seconds = max(0.001, remaining)
    _validate_model(model, phase)
    solve_started = monotonic()
    status = solver.solve(model)
    return status, max(0.0, monotonic() - solve_started)


_SIGNED_INT64_MAX = (1 << 63) - 1


def lexicographic_dominance_weights(
    *,
    corridor_count_max: int,
    elevator_count_max: int,
    utility_mass_max: int,
) -> tuple[int, int, int, int]:
    """Derive exact mixed-radix dominance weights for the accepted lexicographic order.

    The accepted order minimizes, in priority order: exact scaled ``F``, utility mass, Elevator
    count and Corridor count. Given valid finite upper bounds on the three lower-order objectives,
    the weights ``(W_F, W_M, W_E, W_C)`` are chosen so that one unit of any higher-priority
    objective strictly dominates the maximum possible loss across every lower-priority objective:

    - ``W_C = 1``
    - ``W_E = C_max + 1``
    - ``W_M = E_max * W_E + C_max + 1``
    - ``W_F = M_max * W_M + E_max * W_E + C_max + 1``

    For non-negative integer objective components this makes the single linear objective
    ``W_F * F + W_M * mass + W_E * elevators + W_C * corridors`` order-preserving with the
    lexicographic order, so one CP-SAT solve is exactly equivalent to the sequential phases.
    """

    if corridor_count_max < 0 or elevator_count_max < 0 or utility_mass_max < 0:
        raise ValueError("Lexicographic bounds must be non-negative")

    w_c = 1
    w_e = corridor_count_max + 1
    w_m = elevator_count_max * w_e + corridor_count_max + 1
    w_f = utility_mass_max * w_m + elevator_count_max * w_e + corridor_count_max + 1
    return w_f, w_m, w_e, w_c


def lexicographic_objective_upper_bound(
    *,
    weight_f: int,
    weight_mass: int,
    weight_elevator: int,
    weight_corridor: int,
    scaled_f_max: int,
    utility_mass_max: int,
    elevator_count_max: int,
    corridor_count_max: int,
) -> int:
    """Return the valid finite maximum of the scalarized objective (all components at their maxima)."""

    if (
        min(weight_f, weight_mass, weight_elevator, weight_corridor) < 1
        or scaled_f_max < 0
        or utility_mass_max < 0
        or elevator_count_max < 0
        or corridor_count_max < 0
    ):
        raise ValueError("Lexicographic weights and bounds must be valid non-negative values")
    return (
        weight_f * scaled_f_max
        + weight_mass * utility_mass_max
        + weight_elevator * elevator_count_max
        + weight_corridor * corridor_count_max
    )


def _assert_lexicographic_objective_fits_int64(
    combined_objective_upper_bound: int,
) -> None:
    """Fail fast if the scalarized objective could exceed signed 64-bit CP-SAT arithmetic."""

    if combined_objective_upper_bound < 0:
        raise AssertionError("Lexicographic objective upper bound must be non-negative")
    if combined_objective_upper_bound > _SIGNED_INT64_MAX:
        raise ValueError(
            "Exact lexicographic scalarization exceeds signed 64-bit CP-SAT objective bounds: "
            f"combined_objective_upper_bound={combined_objective_upper_bound}, "
            f"limit={_SIGNED_INT64_MAX}. "
            "The fixed packing's utility-anchor domain or objective scale is too large for an "
            "overflow-safe dominance weighting."
        )


def _result_from_solution(
    *,
    status: str,
    utilities: tuple[ModulePlacement, ...],
    metrics: DistanceMetrics,
    scale: int,
    scaled_objective_value: int | None,
    primary_proven: bool,
    lexicographic_proven: bool,
    completed_phase: str,
    time_limit_reached: bool,
    lexicographic_objective_value: int | None,
    diagnostics: FixedFlowObjectiveDiagnostics,
) -> FixedFlowObjectiveResult:
    return FixedFlowObjectiveResult(
        status=status,
        utilities=utilities,
        distance_metrics=metrics,
        objective_scale=scale,
        scaled_objective_value=scaled_objective_value,
        primary_objective_optimum_proven=primary_proven,
        lexicographic_optimum_proven=lexicographic_proven,
        completed_phase=completed_phase,
        time_limit_reached=time_limit_reached,
        lexicographic_objective_value=lexicographic_objective_value,
        diagnostics=diagnostics,
    )


def solve_fixed_layout_flow_objective(
    base: BaseGeometry,
    rooms: tuple[ModulePlacement, ...],
    *,
    time_limit_s: float,
    root_instance_id: str = "airlock-1",
    scaled_objective_upper_bound: int | None = None,
) -> FixedFlowObjectiveResult:
    """Optimize exact ``F`` and all accepted tie-breakers for one fixed room packing.

    Unlike the exhaustive reference oracle, this formulation represents each positive-weight
    room pair by a unit flow over the conditional module graph. Minimizing the sum of weighted
    arc costs is therefore equivalent to minimizing the sum of exact shortest-path distances.

    Before variables are created, each pair flow is restricted to arcs that lie on at least one
    source-to-target path in the unconditional supergraph. The supergraph ignores infrastructure
    selection conditions and is therefore a relaxation of every realizable network; removing
    arcs outside all relaxed endpoint paths is proof-safe and cannot change the exact optimum.

    Singleton endpoint choices are represented by constants rather than auxiliary Boolean
    variables. This is an exact presolve: once domain reduction leaves only one endpoint port,
    its choice is logically fixed and no decision variable is required.

    ``scaled_objective_upper_bound`` is an optional exact decomposition cut. When supplied, the
    fixed subproblem only needs solutions with scaled ``F <= bound``. Equality is deliberately
    retained because a layout with the incumbent primary objective may still improve mass,
    Elevator count or Corridor count. CP-SAT `INFEASIBLE` under this cut proves that the packing
    cannot match or improve the incumbent primary objective, even though it does not distinguish
    hard infrastructure infeasibility from strict objective domination.

    The accepted lexicographic order (exact scaled ``F`` then utility mass then Elevator count
    then Corridor count) is enforced by a single exact mixed-radix scalarized objective. The
    dominance weights are derived from valid finite bounds on the lower-order objectives taken
    from the fixed hard model's utility-anchor domain, so one CP-SAT solve under one wall-clock
    budget (including model construction and search) is exactly equivalent to the sequential
    lexicographic phases while yielding the best lexicographic incumbent at any point.

    Both proof flags are set only when CP-SAT proves the scalarized objective optimal; a timed-out
    incumbent is reported ``FEASIBLE`` with the exact objective tuple but no optimality claim.
    """

    if scaled_objective_upper_bound is not None and (
        isinstance(scaled_objective_upper_bound, bool)
        or not isinstance(scaled_objective_upper_bound, int)
        or scaled_objective_upper_bound < 0
    ):
        raise ValueError("scaled_objective_upper_bound must be a non-negative integer or None")

    if time_limit_s <= 0:
        return FixedFlowObjectiveResult(status="TIME_LIMIT", time_limit_reached=True)

    started_at = monotonic()
    deadline = started_at + float(time_limit_s)
    cp_sat_solve_time_s = 0.0

    compiled = compile_fixed_layout_hard_model(
        base,
        rooms,
        root_instance_id=root_instance_id,
    )
    nodes, room_nodes, arcs = _build_path_graph(rooms, compiled)
    objective = build_scaled_objective(rooms)
    (
        primary_expr,
        pair_flow_variable_count,
        pair_flow_full_variable_count,
    ) = _add_pair_flow_objective(
        compiled.model,
        nodes=nodes,
        room_nodes=room_nodes,
        arcs=arcs,
        pairs=objective.pairs,
    )

    corridor_spec = MODULE_BY_KEY["corridor"]
    elevator_spec = MODULE_BY_KEY["elevator"]
    corridor_count_expr = sum(compiled.variables.corridor.values())
    elevator_count_expr = sum(compiled.variables.elevator.values())
    utility_mass_expr = (
        sum(corridor_spec.mass * variable for variable in compiled.variables.corridor.values())
        + sum(elevator_spec.mass * variable for variable in compiled.variables.elevator.values())
    )

    # Valid finite bounds on the lower-order objectives, derived from the fixed hard model's
    # utility-anchor domain (each anchor selects at most one Corridor or one Elevator module).
    corridor_count_max = len(compiled.variables.corridor)
    elevator_count_max = len(compiled.variables.elevator)
    utility_mass_max = corridor_count_max * corridor_spec.mass + elevator_count_max * elevator_spec.mass

    # Valid finite upper bound on the primary scaled-F objective: a simple path charges each arc at
    # most once, so every pair's path cost is bounded by the total arc cost of the shared graph.
    total_arc_cost = sum(arc.cost for arc in arcs)
    scaled_f_max = total_arc_cost * sum(pair.coefficient for pair in objective.pairs)

    weight_f, weight_mass, weight_elevator, weight_corridor = lexicographic_dominance_weights(
        corridor_count_max=corridor_count_max,
        elevator_count_max=elevator_count_max,
        utility_mass_max=utility_mass_max,
    )
    combined_objective_upper_bound = lexicographic_objective_upper_bound(
        weight_f=weight_f,
        weight_mass=weight_mass,
        weight_elevator=weight_elevator,
        weight_corridor=weight_corridor,
        scaled_f_max=scaled_f_max,
        utility_mass_max=utility_mass_max,
        elevator_count_max=elevator_count_max,
        corridor_count_max=corridor_count_max,
    )
    _assert_lexicographic_objective_fits_int64(combined_objective_upper_bound)

    if scaled_objective_upper_bound is not None:
        compiled.model.add(primary_expr <= scaled_objective_upper_bound)
    lexicographic_expr = (
        weight_f * primary_expr
        + weight_mass * utility_mass_expr
        + weight_elevator * elevator_count_expr
        + weight_corridor * corridor_count_expr
    )
    compiled.model.minimize(lexicographic_expr)

    model_proto = compiled.model.Proto()
    model_variable_count = len(model_proto.variables)
    model_constraint_count = len(model_proto.constraints)
    model_build_time_s = max(0.0, monotonic() - started_at)

    def diagnostics(incumbent_scalar_value: int | None) -> FixedFlowObjectiveDiagnostics:
        return FixedFlowObjectiveDiagnostics(
            graph_node_count=len(nodes),
            graph_arc_count=len(arcs),
            objective_pair_count=len(objective.pairs),
            pair_flow_variable_count=pair_flow_variable_count,
            pair_flow_full_variable_count=pair_flow_full_variable_count,
            cp_sat_variable_count=model_variable_count,
            cp_sat_constraint_count=model_constraint_count,
            lexicographic_scalarization_used=True,
            primary_objective_upper_bound=scaled_f_max,
            combined_objective_upper_bound=combined_objective_upper_bound,
            weight_f=weight_f,
            weight_mass=weight_mass,
            weight_elevator=weight_elevator,
            weight_corridor=weight_corridor,
            corridor_bound=corridor_count_max,
            elevator_bound=elevator_count_max,
            mass_bound=utility_mass_max,
            incumbent_scalar_value=incumbent_scalar_value,
            model_build_time_s=model_build_time_s,
            cp_sat_solve_time_s=cp_sat_solve_time_s,
            total_time_s=max(0.0, monotonic() - started_at),
        )

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 8

    status, phase_solve_time = _solve_phase(
        solver,
        compiled.model,
        deadline=deadline,
        phase="lexicographic scalarization",
    )
    cp_sat_solve_time_s += phase_solve_time
    if status == cp_model.MODEL_INVALID:
        raise AssertionError("CP-SAT rejected the fixed pair-flow objective model")
    if status == cp_model.INFEASIBLE:
        result_status = (
            "OBJECTIVE_BOUND_INFEASIBLE"
            if scaled_objective_upper_bound is not None
            else "INFEASIBLE"
        )
        return FixedFlowObjectiveResult(
            status=result_status,
            objective_scale=objective.scale,
            diagnostics=diagnostics(None),
        )
    if status == cp_model.UNKNOWN:
        return FixedFlowObjectiveResult(
            status="TIME_LIMIT",
            objective_scale=objective.scale,
            time_limit_reached=True,
            diagnostics=diagnostics(None),
        )
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise AssertionError(f"Unexpected CP-SAT lexicographic objective status: {status}")

    utilities, metrics = _evaluate_solution(solver, compiled, rooms)
    lexicographic_value = solver.value(lexicographic_expr)
    model_scaled_f = solver.value(primary_expr)
    dijkstra_scaled_f = objective.scaled_score(metrics.pairwise_distances)
    if model_scaled_f != dijkstra_scaled_f:
        raise AssertionError(
            "Pair-flow primary objective disagrees with exact Dijkstra evaluation: "
            f"model_F={model_scaled_f}, dijkstra_F={dijkstra_scaled_f}"
        )
    if (
        scaled_objective_upper_bound is not None
        and model_scaled_f > scaled_objective_upper_bound
    ):
        raise AssertionError(
            "Lexicographic incumbent violates the exact incumbent objective cut: "
            f"F={model_scaled_f}, bound={scaled_objective_upper_bound}"
        )
    utility_mass = sum(MODULE_BY_KEY[module.module_key].mass for module in utilities)
    elevator_count = sum(1 for module in utilities if module.module_key == "elevator")
    corridor_count = sum(1 for module in utilities if module.module_key == "corridor")
    expected_lexicographic = (
        weight_f * dijkstra_scaled_f
        + weight_mass * utility_mass
        + weight_elevator * elevator_count
        + weight_corridor * corridor_count
    )
    if expected_lexicographic != lexicographic_value:
        raise AssertionError(
            "Scalarized lexicographic objective disagrees with the exact incumbent evaluation: "
            f"model_lex={lexicographic_value}, evaluated_lex={expected_lexicographic} "
            f"(F={dijkstra_scaled_f}, mass={utility_mass}, "
            f"elevators={elevator_count}, corridors={corridor_count})"
        )

    if status != cp_model.OPTIMAL:
        return _result_from_solution(
            status="FEASIBLE",
            utilities=utilities,
            metrics=metrics,
            scale=objective.scale,
            scaled_objective_value=model_scaled_f,
            primary_proven=False,
            lexicographic_proven=False,
            completed_phase="lexicographic scalarization",
            time_limit_reached=True,
            lexicographic_objective_value=lexicographic_value,
            diagnostics=diagnostics(lexicographic_value),
        )

    return _result_from_solution(
        status="OPTIMAL",
        utilities=utilities,
        metrics=metrics,
        scale=objective.scale,
        scaled_objective_value=model_scaled_f,
        primary_proven=True,
        lexicographic_proven=True,
        completed_phase="lexicographic scalarization",
        time_limit_reached=False,
        lexicographic_objective_value=lexicographic_value,
        diagnostics=diagnostics(lexicographic_value),
    )
