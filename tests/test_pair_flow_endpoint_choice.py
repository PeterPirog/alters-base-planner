import pytest
from ortools.sat.python import cp_model

from alters_base_planner.fixed_flow_objective_solver import _endpoint_choice


def test_singleton_endpoint_choice_uses_constant_without_cp_sat_variable() -> None:
    model = cp_model.CpModel()

    choice = _endpoint_choice(
        model,
        pair_id="airlock-1|workshop-1",
        role="source",
        nodes=("room:airlock-1:port:right",),
    )

    assert choice == {"room:airlock-1:port:right": 1}
    assert len(model.Proto().variables) == 0
    assert len(model.Proto().constraints) == 0


def test_multiple_endpoint_choices_keep_exactly_one_boolean_decision() -> None:
    model = cp_model.CpModel()

    choice = _endpoint_choice(
        model,
        pair_id="airlock-1|workshop-1",
        role="target",
        nodes=(
            "room:workshop-1:port:left",
            "room:workshop-1:port:right",
        ),
    )

    assert set(choice) == {
        "room:workshop-1:port:left",
        "room:workshop-1:port:right",
    }
    assert len(model.Proto().variables) == 2
    assert len(model.Proto().constraints) == 1


def test_endpoint_choice_rejects_empty_domain() -> None:
    with pytest.raises(ValueError, match="at least one candidate node"):
        _endpoint_choice(
            cp_model.CpModel(),
            pair_id="airlock-1|workshop-1",
            role="source",
            nodes=(),
        )
