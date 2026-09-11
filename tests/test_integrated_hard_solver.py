import pytest
from ortools.sat.python import cp_model

from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.integrated_hard_solver import (
    StaticInfeasibilityError,
    compile_integrated_hard_model,
    enumerate_placement_options,
    extract_integrated_solution,
    solve_fixed_layout_infrastructure,
)
from alters_base_planner.models import (
    BaseGeometry,
    ModuleInstance,
    ModulePlacement,
    PlacementAuthority,
)


def _base(
    width: int,
    height: int,
    *,
    blocked: frozenset[tuple[int, int]] = frozenset(),
) -> BaseGeometry:
    allowed = frozenset((x, y) for y in range(height) for x in range(width))
    return BaseGeometry(
        tier=99,
        width=width,
        height=height,
        allowed_cells=allowed,
        blocked_cells=blocked,
        organics_capacity=999,
        source="synthetic-test",
        verified=True,
    )


def _instance(instance_id: str, module_key: str) -> ModuleInstance:
    return ModuleInstance(instance_id, MODULE_BY_KEY[module_key])


def _placement(instance_id: str, module_key: str, x: int, y: int) -> ModulePlacement:
    spec = MODULE_BY_KEY[module_key]
    return ModulePlacement(instance_id, module_key, x, y, spec.width, spec.height)


def _force_placement(compiled, instance_id: str, x: int, y: int) -> None:
    matching = [
        option
        for option in compiled.placement_options
        if option.instance_id == instance_id
        and compiled.placement_by_option_id[option.option_id].x == x
        and compiled.placement_by_option_id[option.option_id].y == y
    ]
    assert len(matching) == 1
    compiled.model.add(compiled.variables.placement[matching[0].option_id] == 1)


def _minimize_utility_count(compiled) -> None:
    compiled.model.minimize(sum(compiled.variables.utility_active.values()))


def test_real_candidate_enumeration_respects_blocked_cells() -> None:
    base = _base(6, 1, blocked=frozenset({(4, 0), (5, 0)}))
    instances = (_instance("airlock-1", "airlock"),)

    options, placements = enumerate_placement_options(base, instances)

    assert len(options) == 1
    placement = placements[options[0].option_id]
    assert (placement.x, placement.y) == (0, 0)
    assert placement.cells <= base.buildable_cells


def test_required_module_without_legal_candidate_is_static_infeasibility() -> None:
    base = _base(3, 1)
    instances = (_instance("airlock-1", "airlock"),)

    with pytest.raises(StaticInfeasibilityError, match="has no legal placement"):
        compile_integrated_hard_model(base, instances)


def test_integrated_model_uses_direct_room_adjacency_without_utilities() -> None:
    base = _base(8, 1)
    instances = (
        _instance("airlock-1", "airlock"),
        _instance("workshop-1", "workshop"),
    )
    compiled = compile_integrated_hard_model(base, instances)
    _force_placement(compiled, "airlock-1", 0, 0)
    _force_placement(compiled, "workshop-1", 4, 0)
    _minimize_utility_count(compiled)

    solver = cp_model.CpSolver()
    status = solver.solve(compiled.model)

    assert status == cp_model.OPTIMAL
    modules = extract_integrated_solution(solver, compiled)
    assert {module.instance_id for module in modules} == {"airlock-1", "workshop-1"}
    assert not any(
        MODULE_BY_KEY[module.module_key].authority is PlacementAuthority.SOLVER
        for module in modules
    )


def test_integrated_model_selects_minimum_stacked_elevator_chain() -> None:
    base = _base(6, 2)
    instances = (
        _instance("airlock-1", "airlock"),
        _instance("workshop-1", "workshop"),
    )
    compiled = compile_integrated_hard_model(base, instances)
    _force_placement(compiled, "airlock-1", 0, 0)
    _force_placement(compiled, "workshop-1", 0, 1)
    _minimize_utility_count(compiled)

    solver = cp_model.CpSolver()
    status = solver.solve(compiled.model)

    assert status == cp_model.OPTIMAL
    modules = extract_integrated_solution(solver, compiled)
    infrastructure = [
        module
        for module in modules
        if MODULE_BY_KEY[module.module_key].authority is PlacementAuthority.SOLVER
    ]
    assert [(module.module_key, module.x, module.y) for module in infrastructure] == [
        ("elevator", 4, 0),
        ("elevator", 4, 1),
    ]


def test_fixed_layout_solver_finds_stacked_elevators_without_greedy_routing() -> None:
    base = _base(6, 2)
    rooms = (
        _placement("airlock-1", "airlock", 0, 0),
        _placement("workshop-1", "workshop", 0, 1),
    )

    result = solve_fixed_layout_infrastructure(base, rooms, time_limit_s=2.0)

    assert result.status == "FEASIBLE"
    assert result.time_limit_reached is False
    assert {(module.module_key, module.x, module.y) for module in result.utilities} == {
        ("elevator", 4, 0),
        ("elevator", 4, 1),
    }


def test_fixed_layout_solver_proves_infeasible_when_vertical_access_has_no_space() -> None:
    base = _base(4, 2)
    rooms = (
        _placement("airlock-1", "airlock", 0, 0),
        _placement("workshop-1", "workshop", 0, 1),
    )

    result = solve_fixed_layout_infrastructure(base, rooms, time_limit_s=2.0)

    assert result.status == "INFEASIBLE"
    assert result.utilities == ()
    assert result.time_limit_reached is False
