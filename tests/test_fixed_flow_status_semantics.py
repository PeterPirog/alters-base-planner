import pytest
from ortools.sat.python import cp_model

import alters_base_planner.fixed_flow_objective_solver as flow_solver
from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.models import BaseGeometry, ModulePlacement


def _base() -> BaseGeometry:
    return BaseGeometry(
        tier=99,
        width=8,
        height=1,
        allowed_cells=frozenset((x, 0) for x in range(8)),
        blocked_cells=frozenset(),
        organics_capacity=999,
        source="lexicographic-status-test",
        verified=True,
    )


def _room(instance_id: str, module_key: str, x: int) -> ModulePlacement:
    spec = MODULE_BY_KEY[module_key]
    return ModulePlacement(instance_id, module_key, x, 0, spec.width, spec.height)


def _rooms() -> tuple[ModulePlacement, ...]:
    return (
        _room("airlock-1", "airlock", 0),
        _room("workshop-1", "workshop", 4),
    )


def _inject_status(injected_status: int):
    def solve_phase(solver, model, *, deadline, phase):
        return injected_status, 0.0

    return solve_phase


def _force_status(forced: int):
    real_solve_phase = flow_solver._solve_phase

    def solve_phase(solver, model, *, deadline, phase):
        _, solve_time = real_solve_phase(solver, model, deadline=deadline, phase=phase)
        return forced, solve_time

    return solve_phase


def test_model_invalid_fails_fast(monkeypatch) -> None:
    monkeypatch.setattr(flow_solver, "_solve_phase", _inject_status(cp_model.MODEL_INVALID))
    with pytest.raises(AssertionError, match="rejected the fixed pair-flow objective model"):
        flow_solver.solve_fixed_layout_flow_objective(_base(), _rooms(), time_limit_s=5.0)


def test_infeasible_without_cut_reports_infeasible(monkeypatch) -> None:
    monkeypatch.setattr(flow_solver, "_solve_phase", _inject_status(cp_model.INFEASIBLE))
    result = flow_solver.solve_fixed_layout_flow_objective(_base(), _rooms(), time_limit_s=5.0)
    assert result.status == "INFEASIBLE"
    assert result.distance_metrics is None
    assert result.utilities == ()
    assert result.primary_objective_optimum_proven is False
    assert result.lexicographic_optimum_proven is False
    assert result.time_limit_reached is False


def test_infeasible_with_cut_reports_bound_infeasible(monkeypatch) -> None:
    monkeypatch.setattr(flow_solver, "_solve_phase", _inject_status(cp_model.INFEASIBLE))
    result = flow_solver.solve_fixed_layout_flow_objective(
        _base(), _rooms(), time_limit_s=5.0, scaled_objective_upper_bound=9
    )
    assert result.status == "OBJECTIVE_BOUND_INFEASIBLE"
    assert result.distance_metrics is None
    assert result.utilities == ()
    assert result.primary_objective_optimum_proven is False
    assert result.lexicographic_optimum_proven is False


def test_unknown_reports_time_limit_without_false_proof(monkeypatch) -> None:
    monkeypatch.setattr(flow_solver, "_solve_phase", _inject_status(cp_model.UNKNOWN))
    result = flow_solver.solve_fixed_layout_flow_objective(_base(), _rooms(), time_limit_s=5.0)
    assert result.status == "TIME_LIMIT"
    assert result.time_limit_reached is True
    assert result.primary_objective_optimum_proven is False
    assert result.lexicographic_optimum_proven is False


def test_feasible_timeout_preserves_incumbent_without_proof(monkeypatch) -> None:
    monkeypatch.setattr(flow_solver, "_solve_phase", _force_status(cp_model.FEASIBLE))
    result = flow_solver.solve_fixed_layout_flow_objective(_base(), _rooms(), time_limit_s=5.0)

    assert result.status == "FEASIBLE"
    assert result.primary_objective_optimum_proven is False
    assert result.lexicographic_optimum_proven is False
    assert result.completed_phase == "lexicographic scalarization"
    assert result.time_limit_reached is True
    assert result.scaled_objective_value is not None
    assert result.lexicographic_objective_value is not None
    assert result.distance_metrics is not None
    assert result.distance_metrics.weighted_score == pytest.approx(0.0)
