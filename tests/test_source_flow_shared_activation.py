from itertools import product

import pytest
from ortools.sat.python import cp_model

from alters_base_planner.fixed_flow_objective_solver import _shared_activation_gate


@pytest.mark.parametrize("condition_count", (2, 3))
def test_shared_activation_gate_is_exact_and_for_every_assignment(
    condition_count: int,
) -> None:
    for assignment in product((0, 1), repeat=condition_count):
        model = cp_model.CpModel()
        conditions = tuple(
            model.new_bool_var(f"condition_{index}") for index in range(condition_count)
        )
        gate = _shared_activation_gate(model, conditions=conditions, cache={})
        for condition, value in zip(conditions, assignment, strict=True):
            model.add(condition == value)

        solver = cp_model.CpSolver()
        assert solver.solve(model) == cp_model.OPTIMAL
        assert solver.value(gate) == int(all(assignment))


def test_shared_activation_gate_reuses_reordered_condition_identity() -> None:
    model = cp_model.CpModel()
    conditions = tuple(model.new_bool_var(f"condition_{index}") for index in range(3))
    cache: dict[tuple[int, ...], cp_model.IntVar] = {}

    first = _shared_activation_gate(model, conditions=conditions, cache=cache)
    second = _shared_activation_gate(
        model,
        conditions=tuple(reversed(conditions)),
        cache=cache,
    )

    assert first.index == second.index
    assert len(cache) == 1
    assert len(model.Proto().variables) == 4
    assert len(model.Proto().constraints) == 1


@pytest.mark.parametrize("condition_count", (2, 3))
@pytest.mark.parametrize("total_supply", (1, 2, 3))
def test_shared_gate_flow_projection_matches_per_condition_capacities(
    condition_count: int,
    total_supply: int,
) -> None:
    old_feasible = set()
    new_feasible = set()
    for assignment in product((0, 1), repeat=condition_count):
        for flow_value in range(total_supply + 1):
            old_model = cp_model.CpModel()
            old_conditions = tuple(
                old_model.new_bool_var(f"condition_{index}")
                for index in range(condition_count)
            )
            old_flow = old_model.new_int_var(0, total_supply, "flow")
            for condition, value in zip(old_conditions, assignment, strict=True):
                old_model.add(condition == value)
                old_model.add(old_flow <= total_supply * condition)
            old_model.add(old_flow == flow_value)
            if cp_model.CpSolver().solve(old_model) == cp_model.OPTIMAL:
                old_feasible.add((*assignment, flow_value))

            new_model = cp_model.CpModel()
            new_conditions = tuple(
                new_model.new_bool_var(f"condition_{index}")
                for index in range(condition_count)
            )
            new_flow = new_model.new_int_var(0, total_supply, "flow")
            gate = _shared_activation_gate(new_model, conditions=new_conditions, cache={})
            for condition, value in zip(new_conditions, assignment, strict=True):
                new_model.add(condition == value)
            new_model.add(new_flow <= total_supply * gate)
            new_model.add(new_flow == flow_value)
            if cp_model.CpSolver().solve(new_model) == cp_model.OPTIMAL:
                new_feasible.add((*assignment, flow_value))

    assert new_feasible == old_feasible
