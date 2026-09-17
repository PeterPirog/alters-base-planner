import pytest
from ortools.sat.python import cp_model

import alters_base_planner.engine as engine_module
from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.engine import (
    _configure_room_master_ordering,
    _RoomMasterMode,
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
    )

    assert result.status == "NO_CONNECTED_LAYOUT"
    assert result.search_exhausted is True
    assert result.attempts == len(packings)
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


@pytest.mark.parametrize(
    ("base", "instances"),
    [
        (_base(10, 1), _instances("workshop")),
        (_base(7, 2), _instances("personal_cabin", "personal_cabin")),
        (_base(9, 2, excluded=frozenset({(8, 0), (0, 1)})), _instances("workshop")),
    ],
    ids=("two-rooms", "identical-instance-symmetry", "asymmetric-mask"),
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

    assert heuristic_packings
    assert feasibility_packings == heuristic_packings


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
