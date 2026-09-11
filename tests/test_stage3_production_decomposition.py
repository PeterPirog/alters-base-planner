import alters_base_planner.engine as engine_module
from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.engine import _solve_instances
from alters_base_planner.global_objective_oracle import solve_global_reference_objective
from alters_base_planner.models import BaseGeometry, ModuleInstance


def _base(width: int, height: int = 1) -> BaseGeometry:
    return BaseGeometry(
        tier=99,
        width=width,
        height=height,
        allowed_cells=frozenset((x, y) for y in range(height) for x in range(width)),
        blocked_cells=frozenset(),
        organics_capacity=999,
        source="stage3-production-test",
        verified=True,
    )


def _instances() -> list[ModuleInstance]:
    return [
        ModuleInstance("airlock-1", MODULE_BY_KEY["airlock"]),
        ModuleInstance("workshop-1", MODULE_BY_KEY["workshop"]),
    ]


def _rank(result) -> tuple[int, int, int, int]:
    assert result.scaled_objective_value is not None
    return (
        result.scaled_objective_value,
        result.total_mass,
        result.elevator_module_count,
        result.corridor_count,
    )


def test_production_decomposition_matches_global_reference_and_proves_optimum() -> None:
    # Width 10 admits direct adjacency, exactly-one-Corridor layouts and physically legal
    # room packings that cannot be connected by a 2x1 utility. The production decomposition
    # must account for all of them and still match the independently exhaustive global oracle.
    base = _base(10)
    instances = _instances()

    reference = solve_global_reference_objective(
        base,
        tuple(instances),
        time_limit_s=5.0,
    )
    result = _solve_instances(
        base,
        instances,
        time_limit_s=5.0,
        max_layout_attempts=50,
    )

    assert reference.status == "OPTIMAL"
    assert reference.global_objective_optimum_proven is True
    assert reference.distance_metrics is not None

    assert result.status == "FEASIBLE"
    assert result.global_objective_optimum_proven is True
    assert result.search_exhausted is True
    assert result.time_limit_reached is False
    assert result.fixed_objective_optima_proven >= 1
    assert result.attempts > result.fixed_objective_optima_proven
    assert result.objective_scale == 10
    assert result.scaled_objective_value == 0
    assert result.scaled_modified_manhattan_lower_bound == 0
    assert result.incumbent_bound_pruned_count >= 0

    reference_total_mass = sum(
        MODULE_BY_KEY[module.module_key].mass for module in reference.modules
    )
    reference_rank = (
        0,
        reference_total_mass,
        reference.distance_metrics.elevator_module_count,
        reference.distance_metrics.corridor_count,
    )
    assert _rank(result) == reference_rank


def test_production_passes_exact_incumbent_bound_after_first_candidate(monkeypatch) -> None:
    real_solver = engine_module.solve_fixed_layout_flow_objective
    seen_bounds: list[int | None] = []

    def recording_solver(*args, **kwargs):
        seen_bounds.append(kwargs.get("scaled_objective_upper_bound"))
        return real_solver(*args, **kwargs)

    monkeypatch.setattr(engine_module, "solve_fixed_layout_flow_objective", recording_solver)

    result = _solve_instances(
        _base(8),
        _instances(),
        time_limit_s=5.0,
        max_layout_attempts=10,
    )

    assert result.status == "FEASIBLE"
    assert result.global_objective_optimum_proven is True
    assert seen_bounds[0] is None
    assert 0 in seen_bounds[1:]
    assert result.scaled_objective_value == 0


def test_layout_attempt_limit_prevents_false_global_optimum_proof() -> None:
    result = _solve_instances(
        _base(8),
        _instances(),
        time_limit_s=5.0,
        max_layout_attempts=1,
    )

    assert result.status == "FEASIBLE"
    assert result.global_objective_optimum_proven is False
    assert result.search_exhausted is False
    assert result.time_limit_reached is False
    assert result.attempts == 1
    assert result.fixed_objective_optima_proven == 1
    assert result.incumbent_bound_pruned_count == 0
    assert "layout-attempt limit reached" in result.message
