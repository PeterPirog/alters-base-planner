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
        source="tie-phase-status-test",
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


@pytest.mark.parametrize(
    ("injected_status", "message"),
    [
        (cp_model.MODEL_INVALID, "rejected the fixed pair-flow model during mass tie-breaker"),
        (cp_model.INFEASIBLE, "became infeasible during mass tie-breaker"),
    ],
)
def test_impossible_tie_phase_status_fails_fast(
    monkeypatch,
    injected_status: int,
    message: str,
) -> None:
    real_solve_phase = flow_solver._solve_phase

    def solve_phase_with_injected_failure(solver, model, *, deadline, phase):
        if phase == "mass tie-breaker":
            return injected_status, 0.0
        return real_solve_phase(solver, model, deadline=deadline, phase=phase)

    monkeypatch.setattr(flow_solver, "_solve_phase", solve_phase_with_injected_failure)

    with pytest.raises(AssertionError, match=message):
        flow_solver.solve_fixed_layout_flow_objective(_base(), _rooms(), time_limit_s=5.0)


def test_unknown_tie_phase_preserves_proven_primary_optimum(monkeypatch) -> None:
    real_solve_phase = flow_solver._solve_phase

    def solve_phase_with_tie_timeout(solver, model, *, deadline, phase):
        if phase == "mass tie-breaker":
            return cp_model.UNKNOWN, 0.0
        return real_solve_phase(solver, model, deadline=deadline, phase=phase)

    monkeypatch.setattr(flow_solver, "_solve_phase", solve_phase_with_tie_timeout)

    result = flow_solver.solve_fixed_layout_flow_objective(_base(), _rooms(), time_limit_s=5.0)

    assert result.status == "FEASIBLE"
    assert result.primary_objective_optimum_proven is True
    assert result.lexicographic_optimum_proven is False
    assert result.scaled_objective_value == 0
    assert result.completed_phase == "primary exact F"
    assert result.time_limit_reached is True
    assert result.distance_metrics is not None
    assert result.distance_metrics.weighted_score == pytest.approx(0.0)
