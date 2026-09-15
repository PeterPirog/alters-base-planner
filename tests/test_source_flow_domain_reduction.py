from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.fixed_flow_objective_solver import (
    _Arc,
    _build_source_commodities,
    _source_flow_domain,
    solve_fixed_layout_flow_objective,
)
from alters_base_planner.models import BaseGeometry, ModulePlacement
from alters_base_planner.objective import ObjectivePair


def _adjacency(nodes: tuple[str, ...], arcs: tuple[_Arc, ...]):
    incoming = {node: [] for node in nodes}
    outgoing = {node: [] for node in nodes}
    for index, arc in enumerate(arcs):
        outgoing[arc.source].append(index)
        incoming[arc.target].append(index)
    return incoming, outgoing


def _base(width: int) -> BaseGeometry:
    return BaseGeometry(
        tier=99,
        width=width,
        height=1,
        allowed_cells=frozenset((x, 0) for x in range(width)),
        blocked_cells=frozenset(),
        organics_capacity=999,
        source="source-flow-domain-test",
        verified=True,
    )


def _room(instance_id: str, module_key: str, x: int) -> ModulePlacement:
    spec = MODULE_BY_KEY[module_key]
    return ModulePlacement(instance_id, module_key, x, 0, spec.width, spec.height)


def test_unordered_pairs_are_oriented_once_and_aggregated_by_source() -> None:
    pairs = (
        ObjectivePair("z|a", "z", "a", 2),
        ObjectivePair("m|z", "m", "z", 3),
        ObjectivePair("a|m", "a", "m", 5),
    )

    commodities = _build_source_commodities(pairs)

    assert tuple(
        (commodity.source_instance_id, commodity.targets, commodity.total_supply)
        for commodity in commodities
    ) == (
        ("a", (("m", 5), ("z", 2)), 7),
        ("m", (("z", 3),), 3),
    )


def test_complete_fifteen_room_objective_uses_fourteen_source_commodities() -> None:
    room_ids = tuple(f"room-{index:02d}" for index in range(15))
    pairs = tuple(
        ObjectivePair(f"{source}|{target}", source, target, 1)
        for index, source in enumerate(room_ids)
        for target in room_ids[index + 1 :]
    )

    commodities = _build_source_commodities(pairs)

    assert len(pairs) == 105
    assert len(commodities) == 14
    assert sum(len(commodity.targets) for commodity in commodities) == len(pairs)


def test_source_domain_removes_disconnected_arcs_and_source_revisits() -> None:
    nodes = ("source-a", "source-b", "middle", "target-a", "target-b", "junk-a", "junk-b")
    arcs = (
        _Arc("forward-1", "source-a", "middle", 1),
        _Arc("forward-2", "middle", "target-a", 1),
        _Arc("leave-target", "target-a", "middle", 0),
        _Arc("reenter-source", "middle", "source-a", 0),
        _Arc("junk-1", "junk-a", "junk-b", 0),
        _Arc("junk-2", "junk-b", "junk-a", 0),
    )
    incoming, outgoing = _adjacency(nodes, arcs)

    domain = _source_flow_domain(
        nodes=nodes,
        arcs=arcs,
        source_nodes=("source-a", "source-b"),
        target_nodes=("target-a", "target-b"),
        incoming_arcs=incoming,
        outgoing_arcs=outgoing,
    )

    assert domain.source_nodes == ("source-a",)
    assert domain.target_nodes == ("target-a",)
    assert domain.nodes == ("source-a", "middle", "target-a")
    # Target ports may carry through-flow toward another target in the same commodity.
    assert domain.arc_indices == (0, 1, 2)


def test_direct_adjacency_reports_source_aggregated_flow_variables() -> None:
    rooms = (
        _room("airlock-1", "airlock", 0),
        _room("workshop-1", "workshop", 4),
    )

    result = solve_fixed_layout_flow_objective(_base(8), rooms, time_limit_s=5.0)

    assert result.status == "OPTIMAL"
    assert result.scaled_objective_value == 0
    diagnostics = result.diagnostics
    assert diagnostics.flow_formulation == "source_aggregated_weighted_flow"
    assert diagnostics.objective_pair_count == 1
    assert diagnostics.source_commodity_count == 1
    assert diagnostics.source_flow_variable_count > 0
    assert diagnostics.source_flow_full_variable_count > diagnostics.source_flow_variable_count
    assert diagnostics.cp_sat_variable_count > diagnostics.source_flow_variable_count
