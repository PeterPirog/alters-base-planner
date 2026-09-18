import pytest
from ortools.sat.python import cp_model

import alters_base_planner.engine as engine_module
from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.engine import (
    _configure_room_master_ordering,
    _RoomMasterMode,
    _RoomPackingTrace,
    _solve_instances,
)
from alters_base_planner.fixed_flow_objective_solver import FixedFlowObjectiveResult
from alters_base_planner.models import BaseGeometry, ModuleInstance, ModulePlacement


def _base(
    width: int,
    height: int,
    *,
    excluded: frozenset[tuple[int, int]] = frozenset(),
) -> BaseGeometry:
    cells = frozenset(
        (x, y)
        for y in range(height)
        for x in range(width)
        if (x, y) not in excluded
    )
    return BaseGeometry(
        tier=99,
        width=width,
        height=height,
        allowed_cells=cells,
        blocked_cells=frozenset(),
        organics_capacity=999,
        source="room-master-mode-test",
        verified=True,
    )


def _instances(*module_keys: str) -> list[ModuleInstance]:
    counts: dict[str, int] = {}
    instances = [ModuleInstance("airlock-1", MODULE_BY_KEY["airlock"])]
    for key in module_keys:
        counts[key] = counts.get(key, 0) + 1
        instances.append(ModuleInstance(f"{key}-{counts[key]}", MODULE_BY_KEY[key]))
    return instances


def _canonical_packing(rooms: tuple[ModulePlacement, ...]) -> tuple[tuple[str, int, int], ...]:
    return tuple(sorted((room.instance_id, room.x, room.y) for room in rooms))


def _enumerated_packings(
    monkeypatch: pytest.MonkeyPatch,
    base: BaseGeometry,
    instances: list[ModuleInstance],
    mode: _RoomMasterMode,
    trace: list[_RoomPackingTrace] | None = None,
) -> set[tuple[tuple[str, int, int], ...]]:
    packings: set[tuple[tuple[str, int, int], ...]] = set()

    def record_infeasible(
        _base: BaseGeometry,
        rooms: tuple[ModulePlacement, ...],
        **_kwargs,
    ) -> FixedFlowObjectiveResult:
        packing = _canonical_packing(rooms)
        assert packing not in packings
        packings.add(packing)
        return FixedFlowObjectiveResult(status="INFEASIBLE")

    monkeypatch.setattr(
        engine_module,
        "solve_fixed_layout_flow_objective",
        record_infeasible,
    )
    result = _solve_instances(
        base,
        instances,
        time_limit_s=10.0,
        max_layout_attempts=10_000,
        room_master_mode=mode,
        room_packing_trace=trace,
    )

    assert result.status == "NO_CONNECTED_LAYOUT"
    assert result.search_exhausted is True
    assert result.attempts == len(packings)
    if mode is _RoomMasterMode.HEURISTIC_COST_BANDS:
        assert result.room_master_solve_count == (
            len(packings) + result.room_master_band_count + 1
        )
    else:
        assert result.room_master_solve_count == len(packings) + 1
    assert result.room_master_mode == mode.value
    return packings


def test_room_master_mode_changes_only_objective_presence() -> None:
    heuristic_model = cp_model.CpModel()
    heuristic_var = heuristic_model.new_bool_var("heuristic")
    _configure_room_master_ordering(
        heuristic_model,
        [3 * heuristic_var],
        _RoomMasterMode.HEURISTIC_OBJECTIVE,
    )

    feasibility_model = cp_model.CpModel()
    feasibility_var = feasibility_model.new_bool_var("feasibility")
    _configure_room_master_ordering(
        feasibility_model,
        [3 * feasibility_var],
        _RoomMasterMode.FEASIBILITY_ENUMERATION,
    )

    assert heuristic_model.has_objective()
    assert not feasibility_model.has_objective()

    band_model = cp_model.CpModel()
    band_var = band_model.new_bool_var("band")
    _configure_room_master_ordering(
        band_model,
        [3 * band_var],
        _RoomMasterMode.HEURISTIC_COST_BANDS,
    )
    assert not band_model.has_objective()


@pytest.mark.parametrize(
    ("base", "instances"),
    [
        (_base(10, 1), _instances("workshop")),
        (_base(12, 2), _instances("workshop")),
        (_base(7, 2), _instances("personal_cabin", "personal_cabin")),
        (_base(9, 2, excluded=frozenset({(8, 0), (0, 1)})), _instances("workshop")),
    ],
    ids=(
        "two-room-overlap-alternatives",
        "multiple-cost-levels",
        "identical-instance-symmetry",
        "asymmetric-mask",
    ),
)
def test_room_master_modes_enumerate_exactly_the_same_packing_set(
    monkeypatch: pytest.MonkeyPatch,
    base: BaseGeometry,
    instances: list[ModuleInstance],
) -> None:
    heuristic_packings = _enumerated_packings(
        monkeypatch,
        base,
        instances,
        _RoomMasterMode.HEURISTIC_OBJECTIVE,
    )
    feasibility_packings = _enumerated_packings(
        monkeypatch,
        base,
        instances,
        _RoomMasterMode.FEASIBILITY_ENUMERATION,
    )
    cost_band_packings = _enumerated_packings(
        monkeypatch,
        base,
        instances,
        _RoomMasterMode.HEURISTIC_COST_BANDS,
    )

    assert heuristic_packings
    assert feasibility_packings == heuristic_packings
    assert cost_band_packings == heuristic_packings


def test_cost_bands_are_complete_and_emitted_in_non_decreasing_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace: list[_RoomPackingTrace] = []
    packings = _enumerated_packings(
        monkeypatch,
        _base(10, 1),
        _instances("workshop"),
        _RoomMasterMode.HEURISTIC_COST_BANDS,
        trace,
    )

    costs = [entry.selected_search_cost for entry in trace]
    assert len(costs) == len(packings)
    assert costs == sorted(costs)
    assert len(set(costs)) > 1
    for cost in set(costs):
        indices = [index for index, value in enumerate(costs) if value == cost]
        assert indices == list(range(min(indices), max(indices) + 1))

    discovery = [
        entry.selected_search_cost
        for entry in trace
        if entry.master_phase == "cost_discovery"
    ]
    assert discovery == sorted(set(costs))
    assert all(entry.master_status == "OPTIMAL" for entry in trace)


def test_cost_band_transition_proves_each_band_then_final_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace: list[_RoomPackingTrace] = []
    seen: set[tuple[tuple[str, int, int], ...]] = set()

    def record_infeasible(_base, rooms, **_kwargs):
        packing = _canonical_packing(rooms)
        assert packing not in seen
        seen.add(packing)
        return FixedFlowObjectiveResult(status="INFEASIBLE")

    monkeypatch.setattr(engine_module, "solve_fixed_layout_flow_objective", record_infeasible)
    result = _solve_instances(
        _base(10, 1),
        _instances("workshop"),
        time_limit_s=10.0,
        max_layout_attempts=10_000,
        room_master_mode=_RoomMasterMode.HEURISTIC_COST_BANDS,
        room_packing_trace=trace,
    )

    costs = [entry.selected_search_cost for entry in trace]
    assert result.status == "NO_CONNECTED_LAYOUT"
    assert result.search_exhausted is True
    assert result.global_objective_optimum_proven is False
    assert result.room_master_band_count == len(set(costs))
    assert result.room_master_cost_discovery_solve_count == len(set(costs)) + 1
    # Every band-enumeration packing plus one INFEASIBLE exhaustion solve per band;
    # discoveries account for exactly one packing per band.
    assert result.room_master_band_enumeration_solve_count == result.attempts
    assert result.room_master_largest_completed_band_size == max(
        costs.count(cost) for cost in set(costs)
    )
    assert result.room_master_solve_count == (
        result.attempts + result.room_master_band_count + 1
    )


def test_cost_discovery_feasible_not_optimal_never_advances_floor_or_proves_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_solve = engine_module._solve_room_master

    def return_unproven_solution(*args, **kwargs):
        status, elapsed = real_solve(*args, **kwargs)
        assert status == cp_model.OPTIMAL
        return cp_model.FEASIBLE, elapsed

    monkeypatch.setattr(engine_module, "_solve_room_master", return_unproven_solution)
    monkeypatch.setattr(
        engine_module,
        "solve_fixed_layout_flow_objective",
        lambda *_args, **_kwargs: FixedFlowObjectiveResult(status="INFEASIBLE"),
    )
    result = _solve_instances(
        _base(10, 1),
        _instances("workshop"),
        time_limit_s=5.0,
        max_layout_attempts=10,
        room_master_mode=_RoomMasterMode.HEURISTIC_COST_BANDS,
    )

    assert result.status == "TIME_LIMIT"
    assert result.attempts == 1
    assert result.room_master_band_count == 0
    assert result.room_master_band_enumeration_solve_count == 0
    assert result.search_exhausted is False
    assert result.global_objective_optimum_proven is False


def test_cost_band_timeout_during_enumeration_has_no_false_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_solve = engine_module._solve_room_master
    solve_count = 0

    def timeout_second_solve(*args, **kwargs):
        nonlocal solve_count
        solve_count += 1
        if solve_count == 2:
            return cp_model.UNKNOWN, 0.0
        return real_solve(*args, **kwargs)

    monkeypatch.setattr(engine_module, "_solve_room_master", timeout_second_solve)
    monkeypatch.setattr(
        engine_module,
        "solve_fixed_layout_flow_objective",
        lambda *_args, **_kwargs: FixedFlowObjectiveResult(status="INFEASIBLE"),
    )
    result = _solve_instances(
        _base(10, 1),
        _instances("workshop"),
        time_limit_s=5.0,
        max_layout_attempts=10,
        room_master_mode=_RoomMasterMode.HEURISTIC_COST_BANDS,
    )

    assert result.status == "TIME_LIMIT"
    assert result.attempts == 1
    assert result.room_master_band_count == 1
    assert result.room_master_largest_completed_band_size == 0
    assert result.search_exhausted is False
    assert result.global_objective_optimum_proven is False


def test_cost_band_fixed_timeout_after_band_packing_has_no_false_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_calls = 0

    def timeout_second_fixed(*_args, **_kwargs):
        nonlocal fixed_calls
        fixed_calls += 1
        if fixed_calls == 1:
            return FixedFlowObjectiveResult(status="INFEASIBLE")
        return FixedFlowObjectiveResult(status="TIME_LIMIT", time_limit_reached=True)

    monkeypatch.setattr(engine_module, "solve_fixed_layout_flow_objective", timeout_second_fixed)
    result = _solve_instances(
        _base(10, 1),
        _instances("workshop"),
        time_limit_s=5.0,
        max_layout_attempts=10,
        room_master_mode=_RoomMasterMode.HEURISTIC_COST_BANDS,
    )

    assert result.status == "TIME_LIMIT"
    assert result.attempts == 2
    assert result.room_master_same_cost_packings_examined == 1
    assert result.search_exhausted is False
    assert result.global_objective_optimum_proven is False


def test_cost_band_attempt_limit_inside_band_has_no_false_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        engine_module,
        "solve_fixed_layout_flow_objective",
        lambda *_args, **_kwargs: FixedFlowObjectiveResult(status="INFEASIBLE"),
    )
    result = _solve_instances(
        _base(10, 1),
        _instances("workshop"),
        time_limit_s=5.0,
        max_layout_attempts=2,
        room_master_mode=_RoomMasterMode.HEURISTIC_COST_BANDS,
    )

    assert result.status == "NO_CONNECTED_LAYOUT"
    assert result.attempts == 2
    assert result.time_limit_reached is False
    assert result.search_exhausted is False
    assert result.room_master_largest_completed_band_size == 0
    assert result.global_objective_optimum_proven is False


def test_feasibility_enumeration_timeout_without_incumbent_is_time_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_module, "monotonic", lambda: 6.0)

    result = _solve_instances(
        _base(8, 1),
        _instances("workshop"),
        time_limit_s=5.0,
        max_layout_attempts=10,
        started_at=0.0,
        room_master_mode=_RoomMasterMode.FEASIBILITY_ENUMERATION,
    )

    assert result.status == "TIME_LIMIT"
    assert result.time_limit_reached is True
    assert result.global_objective_optimum_proven is False
    assert result.room_master_solve_count == 0
    assert result.room_master_first_solution_time_s is None


def test_feasibility_enumeration_timeout_after_incumbent_keeps_best_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_completed = False
    post_fixed_clock_calls = 0
    real_fixed_solver = engine_module.solve_fixed_layout_flow_objective

    def controlled_clock() -> float:
        nonlocal post_fixed_clock_calls
        if not fixed_completed:
            return 0.0
        post_fixed_clock_calls += 1
        return 1.0 if post_fixed_clock_calls == 1 else 6.0

    def solve_then_expire(*args, **kwargs):
        nonlocal fixed_completed
        result = real_fixed_solver(*args, **kwargs)
        fixed_completed = True
        return result

    monkeypatch.setattr(engine_module, "monotonic", controlled_clock)
    monkeypatch.setattr(engine_module, "solve_fixed_layout_flow_objective", solve_then_expire)

    result = _solve_instances(
        _base(8, 1),
        _instances("workshop"),
        time_limit_s=5.0,
        max_layout_attempts=10,
        started_at=0.0,
        room_master_mode=_RoomMasterMode.FEASIBILITY_ENUMERATION,
    )

    assert result.status == "FEASIBLE"
    assert result.time_limit_reached is True
    assert result.global_objective_optimum_proven is False
    assert result.time_to_first_feasible_s == 1.0
    assert result.room_master_solve_count == 1
    assert result.room_master_first_solution_time_s == 0.0
