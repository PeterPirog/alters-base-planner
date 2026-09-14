from __future__ import annotations

from collections.abc import Mapping
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

    Counts describe the single lexicographic-scalarized source-aggregated flow model. The objective
    bounds and mixed-radix weights make the signed-64-bit safety calculation auditable. The
    incumbent scalar value is reported separately from those safety bounds. Timings are wall-clock
    measurements for performance analysis only; they never participate in correctness or objective
    decisions.
    """

    flow_formulation: str = "source_aggregated_weighted_flow"
    graph_node_count: int = 0
    graph_arc_count: int = 0
    objective_pair_count: int = 0
    source_commodity_count: int = 0
    source_flow_variable_count: int = 0
    source_flow_full_variable_count: int = 0
    endpoint_distribution_variable_count: int = 0
    condition_capacity_bucket_count: int = 0
    condition_capacity_literal_count: int = 0
    flow_capacity_constraint_count: int = 0
    flow_balance_constraint_count: int = 0
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
    hard_model_build_time_s: float = 0.0
    path_graph_build_time_s: float = 0.0
    objective_definition_time_s: float = 0.0
    flow_model_build_time_s: float = 0.0
    lexicographic_finalize_time_s: float = 0.0


@dataclass(frozen=True, slots=True)
class FixedFlowObjectiveResult:
    """Exact fixed-packing objective result from the source-aggregated flow formulation.

    The formulation jointly selects Corridor/Elevator infrastructure and routes the exact scaled
    pair weights from each deterministically oriented source to its targets. Its primary integer
    objective is exactly the accepted weighted distance ``F`` after rational scaling. The accepted
    lexicographic order
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
class _SourceFlowDomain:
    """Exact subgraph that can carry one source commodity to at least one of its targets."""

    source_nodes: tuple[NodeId, ...]
    target_nodes: tuple[NodeId, ...]
    nodes: tuple[NodeId, ...]
    arc_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _SourceCommodity:
    source_instance_id: str
    targets: tuple[tuple[str, int], ...]
    total_supply: int


@dataclass(frozen=True, slots=True)
class _SourceFlowBuildResult:
    primary_expr: cp_model.LinearExpr | int
    flow_variable_count: int
    full_flow_variable_count: int
    endpoint_distribution_variable_count: int
    condition_capacity_bucket_count: int
    condition_capacity_literal_count: int
    capacity_constraint_count: int
    balance_constraint_count: int


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
    """Build the exact directed travel graph used by the weighted flow objective model."""

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


def _source_flow_domain(
    *,
    nodes: tuple[NodeId, ...],
    arcs: tuple[_Arc, ...],
    source_nodes: tuple[NodeId, ...],
    target_nodes: tuple[NodeId, ...],
    incoming_arcs: dict[NodeId, list[int]],
    outgoing_arcs: dict[NodeId, list[int]],
) -> _SourceFlowDomain:
    """Remove arcs that cannot carry flow from the source to any target.

    The graph used here ignores arc-selection conditions, so it is a supergraph of every
    realizable infrastructure graph. Removing an arc that is not on any source-to-target path in
    this relaxation therefore cannot remove a realizable path. Arcs entering the source are
    unnecessary because every non-negative-cost flow decomposes into source-to-target paths and
    removable cycles. Target ports remain available for transit to other targets in the same
    commodity.
    """

    source_set = set(source_nodes)
    allowed_arc_indices = {
        arc_index
        for arc_index, arc in enumerate(arcs)
        if arc.target not in source_set
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
    return _SourceFlowDomain(
        source_nodes=relevant_sources,
        target_nodes=relevant_targets,
        nodes=tuple(node for node in nodes if node in relevant_nodes),
        arc_indices=relevant_arcs,
    )


def _canonical_conditions(
    conditions: tuple[cp_model.IntVar, ...],
) -> tuple[cp_model.IntVar, ...]:
    """Return positive Boolean conditions in stable model-variable order."""

    by_index: dict[int, cp_model.IntVar] = {}
    for condition in conditions:
        if condition.index < 0 or not condition.is_boolean:
            raise AssertionError("Source-flow arc conditions must be positive Boolean variables")
        by_index[condition.index] = condition
    return tuple(by_index[index] for index in sorted(by_index))


_SAFE_BUCKET_SUM_LIMIT = 1 << 62


def _chunk_bucket_contributions(
    contributions: tuple[tuple[cp_model.IntVar, int], ...],
    *,
    safe_limit: int,
) -> tuple[tuple[tuple[cp_model.IntVar, int], ...], ...]:
    """Split ordered condition-bucket contributions into exact int64-safe chunks.

    One aggregated capacity constraint ``sum(v_i) <= c * sum(U_i)`` is exact only while the
    aggregated upper-bound sum fits the supported signed-integer range. Individual bounds may
    each fit while their sum overflows, so contributions are walked in the given stable order
    and closed into chunks whose upper-bound sums never exceed ``safe_limit``. The conjunction
    of the per-chunk constraints is exactly the aggregation: ``c = 0`` still forces every
    non-negative flow in the chunk to zero, and ``c = 1`` only re-states the individual domains.
    A single contribution whose bound exceeds ``safe_limit`` cannot be represented safely and
    fails fast instead of silently weakening exactness.
    """

    if safe_limit <= 0:
        raise ValueError("Condition-bucket safe limit must be positive")
    chunks: list[tuple[tuple[cp_model.IntVar, int], ...]] = []
    current: list[tuple[cp_model.IntVar, int]] = []
    current_upper_sum = 0
    for variable, upper_bound in contributions:
        if upper_bound <= 0 or upper_bound > safe_limit:
            raise AssertionError(
                "Condition-bucket contribution bounds must be positive and within the safe limit"
            )
        if current and current_upper_sum + upper_bound > safe_limit:
            chunks.append(tuple(current))
            current = []
            current_upper_sum = 0
        current.append((variable, upper_bound))
        current_upper_sum += upper_bound
    if current:
        chunks.append(tuple(current))
    return tuple(chunks)


def _add_direct_endpoint_balances(
    model: cp_model.CpModel,
    *,
    commodity: _SourceCommodity,
    domain: _SourceFlowDomain,
    room_nodes: dict[str, tuple[NodeId, ...]],
    incoming_flow_vars: dict[NodeId, list[cp_model.IntVar]],
    outgoing_flow_vars: dict[NodeId, list[cp_model.IntVar]],
) -> int:
    """Add the exact source, target-absorption and ordinary conservation equations."""

    if commodity.total_supply <= 0 or any(
        coefficient <= 0 for _, coefficient in commodity.targets
    ):
        raise AssertionError("Source-flow supplies and target demands must be positive")
    if commodity.total_supply != sum(coefficient for _, coefficient in commodity.targets):
        raise AssertionError("Source-flow supply must equal the sum of target demands")

    source_nodes = set(domain.source_nodes)
    if any(incoming_flow_vars[node] for node in source_nodes):
        raise AssertionError("Source-flow domain must not retain arcs entering source endpoints")

    target_groups: list[tuple[int, tuple[NodeId, ...]]] = []
    target_nodes: set[NodeId] = set()
    domain_nodes = set(domain.nodes)
    constraint_count = 0
    for target_instance_id, coefficient in commodity.targets:
        legal_nodes = tuple(
            node for node in room_nodes[target_instance_id] if node in domain_nodes
        )
        if not legal_nodes:
            model.add_bool_or([])
            constraint_count += 1
            continue
        if source_nodes & set(legal_nodes) or target_nodes & set(legal_nodes):
            raise AssertionError("Source and target endpoint sets must be disjoint")
        target_nodes.update(legal_nodes)
        target_groups.append((coefficient, legal_nodes))

    source_outgoing = [
        variable for node in domain.source_nodes for variable in outgoing_flow_vars[node]
    ]
    model.add(cp_model.LinearExpr.sum(source_outgoing) == commodity.total_supply)
    constraint_count += 1

    for coefficient, legal_nodes in target_groups:
        target_net_inflows = [
            cp_model.LinearExpr.sum(incoming_flow_vars[node])
            - cp_model.LinearExpr.sum(outgoing_flow_vars[node])
            for node in legal_nodes
        ]
        if len(target_net_inflows) == 1:
            model.add(target_net_inflows[0] == coefficient)
            constraint_count += 1
            continue
        for net_inflow in target_net_inflows:
            model.add(net_inflow >= 0)
            constraint_count += 1
        model.add(cp_model.LinearExpr.sum(target_net_inflows) == coefficient)
        constraint_count += 1

    endpoint_nodes = source_nodes | target_nodes
    for node in domain.nodes:
        if node in endpoint_nodes:
            continue
        model.add(
            cp_model.LinearExpr.sum(incoming_flow_vars[node])
            == cp_model.LinearExpr.sum(outgoing_flow_vars[node])
        )
        constraint_count += 1
    return constraint_count


def _build_source_commodities(
    pairs: tuple[ObjectivePair, ...],
) -> tuple[_SourceCommodity, ...]:
    """Orient every objective pair once and aggregate exact coefficients by source."""

    ordered_instance_ids = sorted(
        {
            instance_id
            for pair in pairs
            for instance_id in (pair.source_instance_id, pair.target_instance_id)
        }
    )
    order = {instance_id: index for index, instance_id in enumerate(ordered_instance_ids)}
    targets_by_source: dict[str, list[tuple[str, int]]] = {}
    seen_pairs: set[frozenset[str]] = set()
    for pair in pairs:
        unordered = frozenset((pair.source_instance_id, pair.target_instance_id))
        if len(unordered) != 2 or unordered in seen_pairs:
            raise AssertionError("Every objective pair must identify one unique unordered pair")
        seen_pairs.add(unordered)
        source, target = sorted(unordered, key=order.__getitem__)
        targets_by_source.setdefault(source, []).append((target, pair.coefficient))

    commodities = []
    for source in ordered_instance_ids:
        targets = tuple(sorted(targets_by_source.get(source, ())))
        if not targets:
            continue
        total_supply = sum(coefficient for _, coefficient in targets)
        commodities.append(_SourceCommodity(source, targets, total_supply))
    return tuple(commodities)


def _add_source_aggregated_flow_objective(
    model: cp_model.CpModel,
    *,
    nodes: tuple[NodeId, ...],
    room_nodes: dict[str, tuple[NodeId, ...]],
    arcs: tuple[_Arc, ...],
    commodities: tuple[_SourceCommodity, ...],
) -> _SourceFlowBuildResult:
    """Add exact weighted multi-sink flows after proof-safe source-domain reduction.

    For one source ``s``, total supply is ``Q_s = sum_t c_st`` and target ``t`` absorbs exactly
    ``c_st`` units. With linear non-negative arc costs and no capacities, an integral feasible flow
    decomposes into source-to-target paths plus removable cycles. Its minimum cost is therefore
    exactly ``sum_t c_st * shortest_distance(s, t)``. Summing the commodity costs reproduces the
    accepted exact scaled objective without multiplying arc costs by pair coefficients again.

    Returns the primary expression and auditable structural counts after source-specific domain
    reduction.
    """

    incoming_arcs: dict[NodeId, list[int]] = {node: [] for node in nodes}
    outgoing_arcs: dict[NodeId, list[int]] = {node: [] for node in nodes}
    for arc_index, arc in enumerate(arcs):
        outgoing_arcs[arc.source].append(arc_index)
        incoming_arcs[arc.target].append(arc_index)
    conditions_by_arc = tuple(_canonical_conditions(arc.conditions) for arc in arcs)

    flow_cost_variables: list[cp_model.IntVar] = []
    flow_cost_coefficients: list[int] = []
    condition_buckets: dict[int, list[tuple[cp_model.IntVar, int]]] = {}
    bucket_conditions: dict[int, cp_model.IntVar] = {}
    source_flow_variable_count = 0
    source_flow_full_variable_count = len(arcs) * len(commodities)
    balance_constraint_count = 0
    for commodity in commodities:
        target_nodes = tuple(
            node
            for target_instance_id, _ in commodity.targets
            for node in room_nodes[target_instance_id]
        )
        domain = _source_flow_domain(
            nodes=nodes,
            arcs=arcs,
            source_nodes=room_nodes[commodity.source_instance_id],
            target_nodes=target_nodes,
            incoming_arcs=incoming_arcs,
            outgoing_arcs=outgoing_arcs,
        )
        if not domain.source_nodes or not domain.target_nodes:
            model.add_bool_or([])
            continue

        source_node_set = set(domain.source_nodes)
        if any(arcs[arc_index].target in source_node_set for arc_index in domain.arc_indices):
            raise AssertionError("Source-flow domain retained an arc entering a source endpoint")

        incoming_flow_vars: dict[NodeId, list[cp_model.IntVar]] = {
            node: [] for node in domain.nodes
        }
        outgoing_flow_vars: dict[NodeId, list[cp_model.IntVar]] = {
            node: [] for node in domain.nodes
        }
        flow: dict[int, cp_model.IntVar] = {}
        for arc_index in domain.arc_indices:
            arc = arcs[arc_index]
            variable = model.new_int_var(
                0,
                commodity.total_supply,
                f"source_flow__{commodity.source_instance_id}__{arc.arc_id}",
            )
            flow[arc_index] = variable
            outgoing_flow_vars[arc.source].append(variable)
            incoming_flow_vars[arc.target].append(variable)

            conditions = conditions_by_arc[arc_index]
            for condition in conditions:
                bucket_contributions = condition_buckets.setdefault(condition.index, [])
                bucket_contributions.append((variable, commodity.total_supply))
                bucket_conditions[condition.index] = condition

            if arc.cost:
                flow_cost_variables.append(variable)
                flow_cost_coefficients.append(arc.cost)

        source_flow_variable_count += len(flow)
        balance_constraint_count += _add_direct_endpoint_balances(
            model,
            commodity=commodity,
            domain=domain,
            room_nodes=room_nodes,
            incoming_flow_vars=incoming_flow_vars,
            outgoing_flow_vars=outgoing_flow_vars,
        )

    # Exact condition-capacity buckets. Every conditioned flow variable contributes its own
    # individual upper bound to the bucket of each of its (canonical, de-duplicated) Boolean
    # infrastructure conditions. For one condition c with contributions (v_i, U_i):
    #
    #     sum_i v_i <= c * sum_i U_i
    #
    # is exactly equivalent to the per-variable bounds v_i <= U_i * c:
    #   c = 0  ->  sum_i v_i <= 0 with every v_i >= 0, therefore every v_i = 0;
    #   c = 1  ->  sum_i v_i <= sum_i U_i, already implied by the individual domains.
    # A multi-condition arc contributes its variable to the bucket of EVERY required condition,
    # so any false condition still forces that variable to zero; explicit AND-gate variables are
    # unnecessary. Buckets aggregate across all source commodities and are emitted in stable
    # condition-index order with int64-safe chunking.
    condition_capacity_bucket_count = 0
    for condition_index in sorted(condition_buckets):
        contributions = tuple(condition_buckets[condition_index])
        if len({variable.index for variable, _ in contributions}) != len(contributions):
            raise AssertionError("Condition bucket received duplicate flow contributions")
        chunks = _chunk_bucket_contributions(
            contributions,
            safe_limit=_SAFE_BUCKET_SUM_LIMIT,
        )
        condition = bucket_conditions[condition_index]
        for chunk in chunks:
            chunk_variables = [variable for variable, _ in chunk]
            chunk_upper_bound = sum(upper_bound for _, upper_bound in chunk)
            model.add(
                cp_model.LinearExpr.sum(chunk_variables)
                <= chunk_upper_bound * condition
            )
            condition_capacity_bucket_count += 1

    primary_expr = (
        cp_model.LinearExpr.weighted_sum(flow_cost_variables, flow_cost_coefficients)
        if flow_cost_variables
        else 0
    )
    return _SourceFlowBuildResult(
        primary_expr=primary_expr,
        flow_variable_count=source_flow_variable_count,
        full_flow_variable_count=source_flow_full_variable_count,
        endpoint_distribution_variable_count=0,
        condition_capacity_bucket_count=condition_capacity_bucket_count,
        condition_capacity_literal_count=len(condition_buckets),
        capacity_constraint_count=condition_capacity_bucket_count,
        balance_constraint_count=balance_constraint_count,
    )


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
    usage_weights: Mapping[str, float] | None,
) -> tuple[tuple[ModulePlacement, ...], DistanceMetrics]:
    utilities = _extract_utilities(solver, compiled)
    try:
        metrics = (
            evaluate_distances(list(rooms), list(utilities))
            if usage_weights is None
            else evaluate_distances(list(rooms), list(utilities), usage_weights)
        )
    except ValueError as exc:
        raise AssertionError(
            "Source-aggregated flow model returned infrastructure rejected by the exact evaluator"
        ) from exc
    return utilities, metrics


def _validate_model(model: cp_model.CpModel, phase: str) -> None:
    validation_error = model.validate()
    if validation_error:
        raise AssertionError(
            f"Invalid fixed source-aggregated flow model during {phase}: {validation_error}"
        )


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
    usage_weights: Mapping[str, float] | None = None,
) -> FixedFlowObjectiveResult:
    """Optimize exact ``F`` and all accepted tie-breakers for one fixed room packing.

    Unlike the exhaustive reference oracle, this formulation deterministically orients every
    positive-weight room pair and aggregates all pairs with the same source into one weighted
    integer flow over the conditional module graph. Minimizing the sum of per-unit arc costs is
    therefore equivalent to minimizing the sum of exact weighted shortest-path distances.

    Before variables are created, each source flow is restricted to arcs that lie on at least one
    path from that source to the union of its targets in the unconditional supergraph. The
    supergraph ignores infrastructure selection conditions and is therefore a relaxation of every
    realizable network; removing arcs outside all relaxed source-to-target paths is proof-safe and
    cannot change the exact optimum.

    Source supply and each target demand may be split over their legal endpoint ports. Singleton
    endpoint distributions are represented by constants rather than auxiliary integer variables.

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

    Both proof flags are set only when CP-SAT proves the scalarized objective optimal. A timed-out
    incumbent may contain non-shortest auxiliary source flows; its selected infrastructure is
    re-evaluated by exact Dijkstra and reported ``FEASIBLE`` with that proof-safe exact objective
    tuple but no optimality claim.
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

    phase_started_at = monotonic()
    compiled = compile_fixed_layout_hard_model(
        base,
        rooms,
        root_instance_id=root_instance_id,
    )
    hard_model_build_time_s = max(0.0, monotonic() - phase_started_at)

    phase_started_at = monotonic()
    nodes, room_nodes, arcs = _build_path_graph(rooms, compiled)
    path_graph_build_time_s = max(0.0, monotonic() - phase_started_at)

    phase_started_at = monotonic()
    objective = (
        build_scaled_objective(rooms)
        if usage_weights is None
        else build_scaled_objective(rooms, usage_weights)
    )
    source_commodities = _build_source_commodities(objective.pairs)
    objective_definition_time_s = max(0.0, monotonic() - phase_started_at)

    phase_started_at = monotonic()
    flow_build = _add_source_aggregated_flow_objective(
        compiled.model,
        nodes=nodes,
        room_nodes=room_nodes,
        arcs=arcs,
        commodities=source_commodities,
    )
    primary_expr = flow_build.primary_expr
    flow_model_build_time_s = max(0.0, monotonic() - phase_started_at)

    phase_started_at = monotonic()
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

    # Every source-arc flow is bounded by that source's total supply. Summed over sources, charging
    # every arc at this bound gives a conservative finite upper bound on scaled F.
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
    lexicographic_finalize_time_s = max(0.0, monotonic() - phase_started_at)
    model_build_time_s = max(0.0, monotonic() - started_at)

    def diagnostics(incumbent_scalar_value: int | None) -> FixedFlowObjectiveDiagnostics:
        return FixedFlowObjectiveDiagnostics(
            graph_node_count=len(nodes),
            graph_arc_count=len(arcs),
            objective_pair_count=len(objective.pairs),
            source_commodity_count=len(source_commodities),
            source_flow_variable_count=flow_build.flow_variable_count,
            source_flow_full_variable_count=flow_build.full_flow_variable_count,
            endpoint_distribution_variable_count=(
                flow_build.endpoint_distribution_variable_count
            ),
            condition_capacity_bucket_count=flow_build.condition_capacity_bucket_count,
            condition_capacity_literal_count=flow_build.condition_capacity_literal_count,
            flow_capacity_constraint_count=flow_build.capacity_constraint_count,
            flow_balance_constraint_count=flow_build.balance_constraint_count,
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
            hard_model_build_time_s=hard_model_build_time_s,
            path_graph_build_time_s=path_graph_build_time_s,
            objective_definition_time_s=objective_definition_time_s,
            flow_model_build_time_s=flow_model_build_time_s,
            lexicographic_finalize_time_s=lexicographic_finalize_time_s,
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
        raise AssertionError("CP-SAT rejected the fixed source-aggregated flow objective model")
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

    utilities, metrics = _evaluate_solution(solver, compiled, rooms, usage_weights)
    solver_lexicographic_value = solver.value(lexicographic_expr)
    solver_scaled_f = solver.value(primary_expr)
    dijkstra_scaled_f = objective.scaled_score(metrics.pairwise_distances)
    if dijkstra_scaled_f > solver_scaled_f or (
        status == cp_model.OPTIMAL and solver_scaled_f != dijkstra_scaled_f
    ):
        raise AssertionError(
            "Source-aggregated flow primary objective disagrees with exact Dijkstra evaluation: "
            f"model_F={solver_scaled_f}, dijkstra_F={dijkstra_scaled_f}"
        )
    if (
        scaled_objective_upper_bound is not None
        and dijkstra_scaled_f > scaled_objective_upper_bound
    ):
        raise AssertionError(
            "Lexicographic incumbent violates the exact incumbent objective cut: "
            f"F={dijkstra_scaled_f}, bound={scaled_objective_upper_bound}"
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
    if status == cp_model.OPTIMAL and expected_lexicographic != solver_lexicographic_value:
        raise AssertionError(
            "Scalarized lexicographic objective disagrees with the exact incumbent evaluation: "
            f"model_lex={solver_lexicographic_value}, evaluated_lex={expected_lexicographic} "
            f"(F={dijkstra_scaled_f}, mass={utility_mass}, "
            f"elevators={elevator_count}, corridors={corridor_count})"
        )

    if status != cp_model.OPTIMAL:
        return _result_from_solution(
            status="FEASIBLE",
            utilities=utilities,
            metrics=metrics,
            scale=objective.scale,
            scaled_objective_value=dijkstra_scaled_f,
            primary_proven=False,
            lexicographic_proven=False,
            completed_phase="lexicographic scalarization",
            time_limit_reached=True,
            lexicographic_objective_value=expected_lexicographic,
            diagnostics=diagnostics(expected_lexicographic),
        )

    return _result_from_solution(
        status="OPTIMAL",
        utilities=utilities,
        metrics=metrics,
        scale=objective.scale,
        scaled_objective_value=dijkstra_scaled_f,
        primary_proven=True,
        lexicographic_proven=True,
        completed_phase="lexicographic scalarization",
        time_limit_reached=False,
        lexicographic_objective_value=expected_lexicographic,
        diagnostics=diagnostics(expected_lexicographic),
    )
