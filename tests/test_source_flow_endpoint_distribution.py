import pytest
from ortools.sat.python import cp_model

from alters_base_planner.fixed_flow_objective_solver import _integer_distribution


def test_singleton_endpoint_distribution_uses_constant_without_cp_sat_variable() -> None:
    model = cp_model.CpModel()

    choice = _integer_distribution(
        model,
        commodity_id="airlock-1",
        role="supply",
        nodes=("room:airlock-1:port:right",),
        total=7,
    )

    assert choice == {"room:airlock-1:port:right": 7}
    assert len(model.Proto().variables) == 0
    assert len(model.Proto().constraints) == 0


def test_multiple_endpoint_ports_split_one_exact_integer_total() -> None:
    model = cp_model.CpModel()

    choice = _integer_distribution(
        model,
        commodity_id="airlock-1",
        role="demand_workshop-1",
        nodes=(
            "room:workshop-1:port:left",
            "room:workshop-1:port:right",
        ),
        total=7,
    )

    assert set(choice) == {
        "room:workshop-1:port:left",
        "room:workshop-1:port:right",
    }
    assert len(model.Proto().variables) == 2
    assert len(model.Proto().constraints) == 1


def test_endpoint_distribution_rejects_empty_domain() -> None:
    with pytest.raises(ValueError, match="at least one candidate node"):
        _integer_distribution(
            cp_model.CpModel(),
            commodity_id="airlock-1",
            role="supply",
            nodes=(),
            total=7,
        )
