import pytest

from alters_base_planner.base import builtin_base
from alters_base_planner.catalog import MODULE_BY_KEY, MODULES, resolve_usage_weights
from alters_base_planner.distance import room_access_rows
from alters_base_planner.engine import (
    _candidate_positions,
    _mass_metrics,
    _solve_instances,
    _validate_utility_geometry,
    solve_plan,
)
from alters_base_planner.integrated_hard_solver import solve_fixed_layout_infrastructure
from alters_base_planner.models import (
    BaseGeometry,
    ModuleInstance,
    ModulePlacement,
    PlacementAuthority,
    PlanRequest,
    expand_instances,
)
from alters_base_planner.serialization import result_payload


def _utility(module_key: str, x: int, y: int) -> ModulePlacement:
    spec = MODULE_BY_KEY[module_key]
    return ModulePlacement(
        f"{module_key}@{x},{y}",
        module_key,
        x,
        y,
        spec.width,
        spec.height,
    )


def test_base_tiers_grow_and_validated_masks_keep_expected_capacities() -> None:
    areas = []
    expected_capacities = {1: 300, 2: 450, 3: 700, 4: 800}
    for tier in (1, 2, 3, 4):
        base = builtin_base(tier)
        assert base.blocked_cells
        assert base.blocked_cells <= base.allowed_cells
        assert base.organics_capacity == expected_capacities[tier]
        assert base.verified is True
        areas.append(len(base.buildable_cells))
    assert areas == sorted(areas)
    assert len(set(areas)) == 4


def test_explicit_port_access_rows_for_regular_and_special_modules() -> None:
    regular = ModulePlacement("storage-1", "small_storage", 4, 5, 2, 2)
    repulsor = ModulePlacement("repulsor-1", "radiation_repulsor", 4, 5, 2, 3)
    assert room_access_rows(regular) == frozenset({6})
    assert room_access_rows(repulsor) == frozenset({5})


def test_candidate_ordering_resolves_floor_relative_port_to_world_y() -> None:
    base = BaseGeometry(
        tier=9,
        width=4,
        height=5,
        allowed_cells=frozenset((x, y) for y in range(5) for x in range(4)),
        blocked_cells=frozenset(),
        organics_capacity=0,
        source="unit-test",
        verified=True,
    )
    spec = MODULE_BY_KEY["materializer"]
    candidates = _candidate_positions(ModuleInstance("materializer-1", spec), base)
    cost_by_y = {candidate.y: candidate.search_cost for candidate in candidates if candidate.x == 0}
    assert cost_by_y[0] < cost_by_y[2]


def test_expand_instances_injects_system_and_never_solver_modules() -> None:
    instances = expand_instances(MODULES, {"workshop": 2})
    keys = [instance.spec.key for instance in instances]
    system_keys = {
        spec.key for spec in MODULES if spec.authority is PlacementAuthority.SYSTEM
    }
    assert all(keys.count(key) == 1 for key in system_keys)
    assert keys.count("workshop") == 2
    assert "corridor" not in keys
    assert "elevator" not in keys


def test_programmatic_solver_module_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="solver-managed"):
        solve_plan(
            PlanRequest(
                tier=4,
                room_counts={"corridor": 1},
                time_limit_s=0.1,
                max_layout_attempts=1,
            )
        )


def test_rapidium_ark_cannot_be_used_as_walkthrough_bridge() -> None:
    allowed = frozenset((x, y) for y in range(2) for x in range(12))
    base = BaseGeometry(
        tier=1,
        width=12,
        height=2,
        allowed_cells=allowed,
        blocked_cells=frozenset(),
        organics_capacity=300,
        source="unit-test",
        verified=True,
    )
    rooms = (
        ModulePlacement("airlock-1", "airlock", 0, 1, 4, 1),
        ModulePlacement("ark-1", "rapidium_ark", 4, 0, 4, 2),
        ModulePlacement("workshop-1", "workshop", 8, 1, 4, 1),
    )

    result = solve_fixed_layout_infrastructure(base, rooms, time_limit_s=2.0)

    assert result.status == "INFEASIBLE"


def test_generated_utilities_are_solver_module_placements() -> None:
    allowed = frozenset((x, 0) for x in range(10))
    base = BaseGeometry(
        tier=1,
        width=10,
        height=1,
        allowed_cells=allowed,
        blocked_cells=frozenset(),
        organics_capacity=300,
        source="unit-test",
        verified=True,
    )
    rooms = (
        ModulePlacement("airlock-1", "airlock", 0, 0, 4, 1),
        ModulePlacement("workshop-1", "workshop", 6, 0, 4, 1),
    )

    result = solve_fixed_layout_infrastructure(base, rooms, time_limit_s=2.0)

    assert result.status == "FEASIBLE"
    assert len(result.utilities) == 1
    utility = result.utilities[0]
    # Both canonical solver modules provide horizontal attachment. Choosing one here is a
    # satisfiability witness, not a hidden routing objective or tie-breaker.
    assert utility.module_key in {"corridor", "elevator"}
    assert MODULE_BY_KEY[utility.module_key].authority is PlacementAuthority.SOLVER
    spec = MODULE_BY_KEY[utility.module_key]
    assert (utility.width, utility.height) == (spec.width, spec.height)


def test_generated_utilities_cannot_overlap_each_other() -> None:
    base = BaseGeometry(
        tier=1,
        width=8,
        height=2,
        allowed_cells=frozenset((x, y) for y in range(2) for x in range(8)),
        blocked_cells=frozenset(),
        organics_capacity=300,
        source="unit-test",
        verified=True,
    )
    with pytest.raises(AssertionError, match="overlap"):
        _validate_utility_geometry(
            base,
            [],
            [
                _utility("corridor", 2, 0),
                _utility("corridor", 3, 0),
            ],
        )


def test_mass_metrics_match_journey_organics_rule() -> None:
    base = builtin_base(2)
    rooms = [
        ModulePlacement("dormitory-1", "dormitory", 0, 0, 6, 1),
        ModulePlacement("workshop-1", "workshop", 0, 1, 4, 1),
    ]
    utilities = [
        _utility("corridor", 0, 2),
        _utility("elevator", 2, 2),
    ]

    room_mass, utility_mass, total_mass, margin, travel_ok, breakdown = _mass_metrics(
        base, rooms, utilities
    )
    assert room_mass == 16
    assert utility_mass == MODULE_BY_KEY["corridor"].mass + MODULE_BY_KEY["elevator"].mass
    assert total_mass == 20
    assert margin == 430
    assert travel_ok is True
    assert sum(breakdown.values()) == total_mass


def test_programmatic_unknown_module_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown module keys"):
        solve_plan(
            PlanRequest(
                tier=4,
                room_counts={"teleporter": 1},
                time_limit_s=0.1,
                max_layout_attempts=1,
            )
        )


def test_programmatic_recycler_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="recycler allows at most 1"):
        solve_plan(
            PlanRequest(
                tier=4,
                room_counts={"recycler": 2},
                time_limit_s=0.1,
                max_layout_attempts=1,
            )
        )


def test_programmatic_rapidium_ark_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="rapidium_ark allows at most 5"):
        solve_plan(
            PlanRequest(
                tier=4,
                room_counts={"rapidium_ark": 6},
                time_limit_s=0.1,
                max_layout_attempts=1,
            )
        )


def test_supplied_base_must_match_requested_tier() -> None:
    with pytest.raises(ValueError, match="does not match"):
        solve_plan(
            PlanRequest(tier=1, room_counts={}, time_limit_s=0.1, max_layout_attempts=1),
            builtin_base(2),
        )


def test_fixed_subproblem_diagnostics_are_aggregated_by_exact_master() -> None:
    base = BaseGeometry(
        tier=99,
        width=10,
        height=1,
        allowed_cells=frozenset((x, 0) for x in range(10)),
        blocked_cells=frozenset(),
        organics_capacity=999,
        source="stage4-engine-diagnostics-test",
        verified=True,
    )
    instances = [
        ModuleInstance("airlock-1", MODULE_BY_KEY["airlock"]),
        ModuleInstance("workshop-1", MODULE_BY_KEY["workshop"]),
    ]

    result = _solve_instances(
        base,
        instances,
        time_limit_s=5.0,
        max_layout_attempts=1,
    )

    assert result.fixed_subproblem_count == 1
    assert result.max_fixed_graph_nodes > 0
    assert result.max_fixed_graph_arcs > 0
    assert result.max_fixed_objective_pairs == 1
    assert result.max_fixed_cp_sat_variables > 0
    assert result.max_fixed_cp_sat_constraints > 0
    assert result.fixed_model_build_time_s >= 0
    assert result.fixed_cp_sat_solve_time_s >= 0
    assert result.fixed_subproblem_time_s >= result.fixed_model_build_time_s
    assert result.room_master_mode == "heuristic_objective"
    assert result.room_master_solve_count == 1
    assert result.room_master_solve_time_s >= 0
    assert result.room_master_first_solution_time_s is not None
    assert (
        result.room_master_optimal_status_count + result.room_master_feasible_status_count
        == result.room_master_solve_count
    )


def test_effective_usage_weights_reach_search_result_and_serialization() -> None:
    base = BaseGeometry(
        tier=99,
        width=10,
        height=1,
        allowed_cells=frozenset((x, 0) for x in range(10)),
        blocked_cells=frozenset(),
        organics_capacity=999,
        source="custom-usage-weight-test",
        verified=True,
    )
    instances = [
        ModuleInstance("airlock-1", MODULE_BY_KEY["airlock"]),
        ModuleInstance("workshop-1", MODULE_BY_KEY["workshop"]),
    ]
    usage_weights = resolve_usage_weights({"airlock": 0.75, "workshop": 0.2})

    result = _solve_instances(
        base,
        instances,
        time_limit_s=5.0,
        max_layout_attempts=1,
        usage_weights=usage_weights,
    )

    assert result.status == "FEASIBLE"
    assert result.room_usage_weights == {"airlock-1": 0.75, "workshop-1": 0.2}
    payload = result_payload(result)
    serialized_modules = payload["modules"]
    assert isinstance(serialized_modules, list)
    serialized_weights = {
        module["instance_id"]: module["usage_weight"]
        for module in serialized_modules
    }
    assert serialized_weights["airlock-1"] == 0.75
    assert serialized_weights["workshop-1"] == 0.2
    assert all(
        serialized_weights[module.instance_id] == 0.0
        for module in result.modules
        if module.module_key in {"corridor", "elevator"}
    )
    assert payload["optimization"]["search_diagnostics"]["room_master"] == {
        "mode": "heuristic_objective",
        "solve_count": 1,
        "solve_time_s": result.room_master_solve_time_s,
        "first_solution_time_s": result.room_master_first_solution_time_s,
        "optimal_status_count": result.room_master_optimal_status_count,
        "feasible_status_count": result.room_master_feasible_status_count,
    }


def test_solver_returns_unified_modules_and_search_metrics_when_connected() -> None:
    result = solve_plan(
        PlanRequest(
            tier=2,
            room_counts={"workshop": 1, "research_lab": 1, "dormitory": 1},
            time_limit_s=3,
            max_layout_attempts=8,
        )
    )
    assert result.status in {"FEASIBLE", "NO_CONNECTED_LAYOUT", "INFEASIBLE", "TIME_LIMIT"}
    assert result.base.tier == 2
    assert result.search_time_s >= 0
    assert result.room_master_mode == "heuristic_objective"
    assert 0 <= result.attempts <= 8
    assert result.connected_candidates_examined >= 0
    assert result.manhattan_pruned_count >= 0
    assert result.fixed_subproblem_count >= 0

    if result.status == "FEASIBLE":
        assert result.modules
        assert result.connected_candidates_examined >= 1
        assert result.fixed_subproblem_count >= 1
        assert result.total_mass == result.room_mass + result.utility_mass
        assert result.organics_required_for_journey == result.total_mass
        assert result.organics_capacity_margin == result.base.organics_capacity - result.total_mass
        assert result.travel_feasible_at_full_tank == (
            result.total_mass <= result.base.organics_capacity
        )
        assert sum(result.mass_breakdown.values()) == result.total_mass
        assert all(isinstance(module, ModulePlacement) for module in result.modules)

        authorities = [MODULE_BY_KEY[module.module_key].authority for module in result.modules]
        assert PlacementAuthority.SYSTEM in authorities
        assert PlacementAuthority.PLAYER in authorities
        assert PlacementAuthority.SOLVER in authorities
