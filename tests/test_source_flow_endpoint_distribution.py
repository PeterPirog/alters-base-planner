from dataclasses import dataclass
from itertools import product

import pytest
from ortools.sat.python import cp_model

from alters_base_planner.fixed_flow_objective_solver import (
    _add_direct_endpoint_balances,
    _SourceCommodity,
    _SourceFlowDomain,
)


@dataclass(frozen=True)
class _Scenario:
    nodes: tuple[str, ...]
    source_nodes: tuple[str, ...]
    room_nodes: dict[str, tuple[str, ...]]
    targets: tuple[tuple[str, int], ...]
    arcs: tuple[tuple[str, str, int, str], ...]

    @property
    def supply(self) -> int:
        return sum(coefficient for _, coefficient in self.targets)


def _old_endpoint_balances(
    model: cp_model.CpModel,
    scenario: _Scenario,
    incoming: dict[str, list[cp_model.IntVar]],
    outgoing: dict[str, list[cp_model.IntVar]],
) -> None:
    def distribution(nodes: tuple[str, ...], total: int, role: str):
        if len(nodes) == 1:
            return {nodes[0]: total}
        choices = {
            node: model.new_int_var(0, total, f"old_{role}_{node}") for node in nodes
        }
        model.add(cp_model.LinearExpr.sum(list(choices.values())) == total)
        return choices

    source = distribution(scenario.source_nodes, scenario.supply, "source")
    target = {}
    for target_id, coefficient in scenario.targets:
        target.update(
            distribution(scenario.room_nodes[target_id], coefficient, f"target_{target_id}")
        )
    for node in scenario.nodes:
        model.add(
            cp_model.LinearExpr.sum(incoming[node]) + source.get(node, 0)
            == cp_model.LinearExpr.sum(outgoing[node]) + target.get(node, 0)
        )


def _objective_by_infrastructure_choice(
    scenario: _Scenario,
    *,
    direct_endpoint_balances: bool,
) -> dict[tuple[int, ...], int | None]:
    condition_names = tuple(sorted({condition for *_, condition in scenario.arcs}))
    result = {}
    for assignment in product((0, 1), repeat=len(condition_names)):
        model = cp_model.CpModel()
        conditions = {
            name: model.new_bool_var(f"condition_{name}") for name in condition_names
        }
        for name, value in zip(condition_names, assignment, strict=True):
            model.add(conditions[name] == value)

        incoming: dict[str, list[cp_model.IntVar]] = {
            node: [] for node in scenario.nodes
        }
        outgoing: dict[str, list[cp_model.IntVar]] = {
            node: [] for node in scenario.nodes
        }
        flow_variables = []
        costs = []
        for index, (source, target, cost, condition_name) in enumerate(scenario.arcs):
            flow = model.new_int_var(0, scenario.supply, f"flow_{index}")
            model.add(flow <= scenario.supply * conditions[condition_name])
            outgoing[source].append(flow)
            incoming[target].append(flow)
            flow_variables.append(flow)
            costs.append(cost)

        if direct_endpoint_balances:
            commodity = _SourceCommodity("source", scenario.targets, scenario.supply)
            domain = _SourceFlowDomain(
                source_nodes=scenario.source_nodes,
                target_nodes=tuple(
                    node
                    for target_id, _ in scenario.targets
                    for node in scenario.room_nodes[target_id]
                ),
                nodes=scenario.nodes,
                arc_indices=tuple(range(len(scenario.arcs))),
            )
            _add_direct_endpoint_balances(
                model,
                commodity=commodity,
                domain=domain,
                room_nodes=scenario.room_nodes,
                incoming_flow_vars=incoming,
                outgoing_flow_vars=outgoing,
            )
        else:
            _old_endpoint_balances(model, scenario, incoming, outgoing)

        objective = cp_model.LinearExpr.weighted_sum(flow_variables, costs)
        model.minimize(objective)
        solver = cp_model.CpSolver()
        status = solver.solve(model)
        result[assignment] = (
            solver.value(objective)
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
            else None
        )
    return result


@pytest.mark.parametrize(
    ("scenario", "expected"),
    (
        (
            _Scenario(
                nodes=("s", "t"),
                source_nodes=("s",),
                room_nodes={"source": ("s",), "target": ("t",)},
                targets=(("target", 2),),
                arcs=(("s", "t", 3, "bridge"),),
            ),
            {(0,): None, (1,): 6},
        ),
        (
            _Scenario(
                nodes=("s1", "s2", "t1", "t2"),
                source_nodes=("s1", "s2"),
                room_nodes={"source": ("s1", "s2"), "target": ("t1", "t2")},
                targets=(("target", 2),),
                arcs=(
                    ("s1", "t1", 2, "left"),
                    ("s2", "t2", 1, "right"),
                ),
            ),
            {(0, 0): None, (0, 1): 2, (1, 0): 4, (1, 1): 2},
        ),
        (
            _Scenario(
                nodes=("s", "a", "b1", "b2"),
                source_nodes=("s",),
                room_nodes={"source": ("s",), "a": ("a",), "b": ("b1", "b2")},
                targets=(("a", 1), ("b", 2)),
                arcs=(
                    ("s", "a", 1, "ingress"),
                    ("a", "b1", 2, "route1"),
                    ("a", "b2", 1, "route2"),
                ),
            ),
            {
                (0, 0, 0): None,
                (0, 0, 1): None,
                (0, 1, 0): None,
                (0, 1, 1): None,
                (1, 0, 0): None,
                (1, 0, 1): 5,
                (1, 1, 0): 7,
                (1, 1, 1): 5,
            },
        ),
    ),
)
def test_direct_endpoint_balances_match_explicit_allocation_projection(
    scenario: _Scenario,
    expected: dict[tuple[int, ...], int | None],
) -> None:
    old_projection = _objective_by_infrastructure_choice(
        scenario,
        direct_endpoint_balances=False,
    )
    new_projection = _objective_by_infrastructure_choice(
        scenario,
        direct_endpoint_balances=True,
    )

    assert old_projection == new_projection == expected


def test_direct_source_balance_rejects_retained_incoming_source_flow() -> None:
    model = cp_model.CpModel()
    incoming_source = model.new_int_var(0, 1, "incoming_source")

    with pytest.raises(AssertionError, match="entering source endpoints"):
        _add_direct_endpoint_balances(
            model,
            commodity=_SourceCommodity("source", (("target", 1),), 1),
            domain=_SourceFlowDomain(
                source_nodes=("s",),
                target_nodes=("t",),
                nodes=("s", "t"),
                arc_indices=(),
            ),
            room_nodes={"source": ("s",), "target": ("t",)},
            incoming_flow_vars={"s": [incoming_source], "t": []},
            outgoing_flow_vars={"s": [], "t": []},
        )


@pytest.mark.parametrize(
    ("targets", "supply"),
    (
        ((("target", 0),), 0),
        ((("target", 1),), 2),
    ),
)
def test_direct_endpoint_balances_reject_invalid_supply_or_demand(
    targets: tuple[tuple[str, int], ...],
    supply: int,
) -> None:
    with pytest.raises(AssertionError, match="supply|demand"):
        _add_direct_endpoint_balances(
            cp_model.CpModel(),
            commodity=_SourceCommodity("source", targets, supply),
            domain=_SourceFlowDomain(
                source_nodes=("s",),
                target_nodes=("t",),
                nodes=("s", "t"),
                arc_indices=(),
            ),
            room_nodes={"source": ("s",), "target": ("t",)},
            incoming_flow_vars={"s": [], "t": []},
            outgoing_flow_vars={"s": [], "t": []},
        )
