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
class FixedFlowObjectiveResult:
    """Exact fixed-packing objective result from the scalable pair-flow formulation.

    The formulation jointly selects Corridor/Elevator infrastructure and one legal path for
    every positive-weight endpoint pair. Its primary integer objective is exactly the accepted
    weighted distance ``F`` after rational scaling. Lexicographic tie-breakers are then solved
    sequentially under equality constraints that preserve all previously proven optima.
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


@dataclass(frozen=True, slots=True)
class _Arc:
    arc_id: str
    source: NodeId
    target: NodeId
    cost: int
    conditions: tuple[cp_model.IntVar, ...] = ()


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


def _add_pair_flow_objective(
    model: cp_model.CpModel,
    *,
    nodes: tuple[NodeId, ...],
    room_nodes: dict[str, tuple[NodeId, ...]],
    arcs: tuple[_Arc, ...],
    pairs: tuple[ObjectivePair, ...],
):
    """Add one unit-flow shortest-path problem per weighted endpoint pair."""

    incoming_arcs: dict[NodeId, list[int]] = {node: [] for node in nodes}
    outgoing_arcs: dict[NodeId, list[int]] = {node: [] for node in nodes}
    for arc_index, arc in enumerate(arcs):
        outgoing_arcs[arc.source].append(arc_index)
        incoming_arcs[arc.target].append(arc_index)

    weighted_terms = []
    for pair in pairs:
        source_nodes = room_nodes[pair.source_instance_id]
        target_nodes = room_nodes[pair.target_instance_id]
        source_choice = {
            node: model.new_bool_var(f"pair_source__{pair.pair_id}__{node}")
            for node in source_nodes
        }
        target_choice = {
            node: model.new_bool_var(f"pair_target__{pair.pair_id}__{node}")
            for node in target_nodes
        }
        model.add_exactly_one(source_choice.values())
        model.add_exactly_one(target_choice.values())

        flow = [
            model.new_bool_var(f"pair_flow__{pair.pair_id}__{arc.arc_id}")
            for arc in arcs
        ]
        for arc_index, arc in enumerate(arcs):
            for condition in arc.conditions:
                model.add(flow[arc_index] <= condition)

        for node in nodes:
            incoming = sum(flow[index] for index in incoming_arcs[node])
            outgoing = sum(flow[index] for index in outgoing_arcs[node])
            source = source_choice.get(node, 0)
            target = target_choice.get(node, 0)
            model.add(incoming + source == outgoing + target)

        path_cost = sum(arc.cost * flow[index] for index, arc in enumerate(arcs))
        weighted_terms.append(pair.coefficient * path_cost)

    return sum(weighted_terms)


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
) -> int:
    remaining = deadline - monotonic()
    if remaining <= 0:
        return cp_model.UNKNOWN
    solver.parameters.max_time_in_seconds = max(0.001, remaining)
    _validate_model(model, phase)
    return solver.solve(model)


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
    )


def solve_fixed_layout_flow_objective(
    base: BaseGeometry,
    rooms: tuple[ModulePlacement, ...],
    *,
    time_limit_s: float,
    root_instance_id: str = "airlock-1",
) -> FixedFlowObjectiveResult:
    """Optimize exact ``F`` and all accepted tie-breakers for one fixed room packing.

    Unlike the exhaustive reference oracle, this formulation represents each positive-weight
    room pair by a unit flow over the conditional module graph. Minimizing the sum of weighted
    arc costs is therefore equivalent to minimizing the sum of exact shortest-path distances.

    The phases are solved lexicographically under one global wall-clock budget:

    1. scaled exact weighted distance ``F``;
    2. utility mass (room mass is constant for the fixed packing);
    3. Elevator count;
    4. Corridor count.

    A proof flag is set only when CP-SAT proves the corresponding optimization phase optimal.
    """

    if time_limit_s <= 0:
        return FixedFlowObjectiveResult(status="TIME_LIMIT", time_limit_reached=True)

    compiled = compile_fixed_layout_hard_model(
        base,
        rooms,
        root_instance_id=root_instance_id,
    )
    nodes, room_nodes, arcs = _build_path_graph(rooms, compiled)
    objective = build_scaled_objective(rooms)
    primary_expr = _add_pair_flow_objective(
        compiled.model,
        nodes=nodes,
        room_nodes=room_nodes,
        arcs=arcs,
        pairs=objective.pairs,
    )
    compiled.model.minimize(primary_expr)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 8
    deadline = monotonic() + float(time_limit_s)

    status = _solve_phase(
        solver,
        compiled.model,
        deadline=deadline,
        phase="primary exact F",
    )
    if status == cp_model.MODEL_INVALID:
        raise AssertionError("CP-SAT rejected the fixed pair-flow objective model")
    if status == cp_model.INFEASIBLE:
        return FixedFlowObjectiveResult(status="INFEASIBLE", objective_scale=objective.scale)
    if status == cp_model.UNKNOWN:
        return FixedFlowObjectiveResult(
            status="TIME_LIMIT",
            objective_scale=objective.scale,
            time_limit_reached=True,
        )
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise AssertionError(f"Unexpected CP-SAT primary objective status: {status}")

    utilities, metrics = _evaluate_solution(solver, compiled, rooms)
    if status != cp_model.OPTIMAL:
        return _result_from_solution(
            status="FEASIBLE",
            utilities=utilities,
            metrics=metrics,
            scale=objective.scale,
            scaled_objective_value=None,
            primary_proven=False,
            lexicographic_proven=False,
            completed_phase="primary exact F",
            time_limit_reached=True,
        )

    primary_optimum = int(round(solver.objective_value))
    scaled_evaluator_value = objective.scaled_score(metrics.pairwise_distances)
    if scaled_evaluator_value != primary_optimum:
        raise AssertionError(
            "Pair-flow optimum disagrees with exact Dijkstra evaluation: "
            f"model={primary_optimum}, evaluator={scaled_evaluator_value}"
        )
    compiled.model.add(primary_expr == primary_optimum)

    last_utilities = utilities
    last_metrics = metrics
    completed_phase = "primary exact F"

    corridor_spec = MODULE_BY_KEY["corridor"]
    elevator_spec = MODULE_BY_KEY["elevator"]
    utility_mass_expr = sum(
        corridor_spec.mass * variable
        for variable in compiled.variables.corridor.values()
    ) + sum(
        elevator_spec.mass * variable
        for variable in compiled.variables.elevator.values()
    )
    compiled.model.minimize(utility_mass_expr)
    status = _solve_phase(
        solver,
        compiled.model,
        deadline=deadline,
        phase="mass tie-breaker",
    )
    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        last_utilities, last_metrics = _evaluate_solution(solver, compiled, rooms)
    if status != cp_model.OPTIMAL:
        return _result_from_solution(
            status="FEASIBLE",
            utilities=last_utilities,
            metrics=last_metrics,
            scale=objective.scale,
            scaled_objective_value=primary_optimum,
            primary_proven=True,
            lexicographic_proven=False,
            completed_phase=completed_phase,
            time_limit_reached=True,
        )
    mass_optimum = int(round(solver.objective_value))
    compiled.model.add(utility_mass_expr == mass_optimum)
    completed_phase = "mass tie-breaker"

    elevator_count_expr = sum(compiled.variables.elevator.values())
    compiled.model.minimize(elevator_count_expr)
    status = _solve_phase(
        solver,
        compiled.model,
        deadline=deadline,
        phase="Elevator tie-breaker",
    )
    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        last_utilities, last_metrics = _evaluate_solution(solver, compiled, rooms)
    if status != cp_model.OPTIMAL:
        return _result_from_solution(
            status="FEASIBLE",
            utilities=last_utilities,
            metrics=last_metrics,
            scale=objective.scale,
            scaled_objective_value=primary_optimum,
            primary_proven=True,
            lexicographic_proven=False,
            completed_phase=completed_phase,
            time_limit_reached=True,
        )
    elevator_optimum = int(round(solver.objective_value))
    compiled.model.add(elevator_count_expr == elevator_optimum)
    completed_phase = "Elevator tie-breaker"

    corridor_count_expr = sum(compiled.variables.corridor.values())
    compiled.model.minimize(corridor_count_expr)
    status = _solve_phase(
        solver,
        compiled.model,
        deadline=deadline,
        phase="Corridor tie-breaker",
    )
    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        last_utilities, last_metrics = _evaluate_solution(solver, compiled, rooms)
    if status != cp_model.OPTIMAL:
        return _result_from_solution(
            status="FEASIBLE",
            utilities=last_utilities,
            metrics=last_metrics,
            scale=objective.scale,
            scaled_objective_value=primary_optimum,
            primary_proven=True,
            lexicographic_proven=False,
            completed_phase=completed_phase,
            time_limit_reached=True,
        )

    final_scaled_evaluator = objective.scaled_score(last_metrics.pairwise_distances)
    if final_scaled_evaluator != primary_optimum:
        raise AssertionError(
            "Lexicographic pair-flow solution changed the proven exact F optimum: "
            f"primary={primary_optimum}, final={final_scaled_evaluator}"
        )

    return _result_from_solution(
        status="OPTIMAL",
        utilities=last_utilities,
        metrics=last_metrics,
        scale=objective.scale,
        scaled_objective_value=primary_optimum,
        primary_proven=True,
        lexicographic_proven=True,
        completed_phase="Corridor tie-breaker",
        time_limit_reached=False,
    )
