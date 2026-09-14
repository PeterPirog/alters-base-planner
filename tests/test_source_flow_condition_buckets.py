from itertools import product

import pytest
from ortools.sat.python import cp_model

from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.fixed_flow_objective_solver import (
    _add_source_aggregated_flow_objective,
    _build_path_graph,
    _build_source_commodities,
    _chunk_bucket_contributions,
    solve_fixed_layout_flow_objective,
)
from alters_base_planner.integrated_hard_solver import compile_fixed_layout_hard_model
from alters_base_planner.models import BaseGeometry, ModulePlacement
from alters_base_planner.objective import build_scaled_objective


def _base(width: int, height: int) -> BaseGeometry:
    return BaseGeometry(
        tier=99,
        width=width,
        height=height,
        allowed_cells=frozenset((x, y) for y in range(height) for x in range(width)),
        blocked_cells=frozenset(),
        organics_capacity=999,
        source="condition-bucket-test",
        verified=True,
    )


def _room(instance_id: str, module_key: str, x: int, y: int) -> ModulePlacement:
    spec = MODULE_BY_KEY[module_key]
    return ModulePlacement(instance_id, module_key, x, y, spec.width, spec.height)


def _old_feasible(bound: tuple[int, ...], condition_value: int, flows: tuple[int, ...]) -> bool:
    return all(flow <= limit * condition_value for flow, limit in zip(flows, bound, strict=True))


def _new_feasible(bound: tuple[int, ...], condition_value: int, flows: tuple[int, ...]) -> bool:
    return sum(flows) <= condition_value * sum(bound)


@pytest.mark.parametrize("condition_value", (0, 1))
@pytest.mark.parametrize(
    "bound",
    sum(
        (tuple(product((1, 2, 3), repeat=count)) for count in (1, 2, 3, 4)),
        (),
    ),
)
def test_condition_bucket_matches_individual_bounds_exhaustively(
    bound: tuple[int, ...],
    condition_value: int,
) -> None:
    old_feasible = set()
    new_feasible = set()
    for flows in product(*(range(limit + 1) for limit in bound)):
        if _old_feasible(bound, condition_value, flows):
            old_feasible.add(flows)
        if _new_feasible(bound, condition_value, flows):
            new_feasible.add(flows)

    assert new_feasible == old_feasible


def test_multi_condition_bucket_projection_matches_individual_and_gate_bounds() -> None:
    bounds = (2, 3, 2)
    old_feasible = set()
    new_feasible = set()
    for c1, c2 in product((0, 1), repeat=2):
        for v1, v2, v3 in product(
            range(bounds[0] + 1),
            range(bounds[1] + 1),
            range(bounds[2] + 1),
        ):
            # Old formulation: one individual capacity bound per required condition; an
            # AND-gated arc is exactly equivalent to one individual bound per condition.
            old_ok = (
                v1 <= bounds[0] * c1
                and v2 <= bounds[1] * c2
                and v3 <= bounds[2] * c1
                and v3 <= bounds[2] * c2
            )
            # New formulation: buckets on c1 and c2; the shared variable joins both buckets.
            new_ok = (
                v1 + v3 <= c1 * (bounds[0] + bounds[2])
                and v2 + v3 <= c2 * (bounds[1] + bounds[2])
            )
            if old_ok:
                old_feasible.add((c1, c2, v1, v2, v3))
            if new_ok:
                new_feasible.add((c1, c2, v1, v2, v3))

    assert new_feasible == old_feasible


def test_chunk_bucket_contributions_partitions_deterministically_within_limit() -> None:
    model = cp_model.CpModel()
    contributions = tuple(
        (model.new_int_var(0, bound, f"v_{index}"), bound)
        for index, bound in enumerate((2, 3, 1, 2, 3))
    )

    chunks = _chunk_bucket_contributions(contributions, safe_limit=5)
    again = _chunk_bucket_contributions(contributions, safe_limit=5)

    assert chunks == again
    assert [
        [variable.index for variable, _ in chunk] for chunk in chunks
    ] == [[0, 1], [2, 3], [4]]
    assert [sum(bound for _, bound in chunk) for chunk in chunks] == [5, 3, 3]
    assert all(sum(bound for _, bound in chunk) <= 5 for chunk in chunks)
    assert sorted(
        variable.index for chunk in chunks for variable, _ in chunk
    ) == [0, 1, 2, 3, 4]

    with pytest.raises(ValueError, match="safe limit must be positive"):
        _chunk_bucket_contributions((), safe_limit=0)
    with pytest.raises(AssertionError, match="within the safe limit"):
        _chunk_bucket_contributions(((model.new_int_var(0, 6, "v_x"), 6),), safe_limit=5)


def test_vertical_elevator_chain_uses_exact_condition_buckets() -> None:
    base = _base(6, 2)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 0, 1),
    )

    result = solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)

    assert result.status == "OPTIMAL"
    assert result.scaled_objective_value == 18
    diagnostics = result.diagnostics
    assert not hasattr(diagnostics, "shared_activation_gate_count")
    assert diagnostics.condition_capacity_literal_count > 0
    assert diagnostics.condition_capacity_bucket_count > 0
    assert diagnostics.flow_capacity_constraint_count == (
        diagnostics.condition_capacity_bucket_count
    )
    assert diagnostics.endpoint_distribution_variable_count == 0


def test_production_model_contains_no_gate_variables() -> None:
    base = _base(6, 2)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 0, 1),
    )
    compiled = compile_fixed_layout_hard_model(base, rooms, root_instance_id="airlock-1")
    nodes, room_nodes, arcs = _build_path_graph(rooms, compiled)
    commodities = _build_source_commodities(build_scaled_objective(rooms).pairs)
    _add_source_aggregated_flow_objective(
        compiled.model,
        nodes=nodes,
        room_nodes=room_nodes,
        arcs=arcs,
        commodities=commodities,
    )

    names = [variable.name for variable in compiled.model.Proto().variables]
    assert all(not name.startswith("source_arc_gate__") for name in names)


def test_unconditional_arcs_create_no_condition_buckets() -> None:
    base = _base(8, 1)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 4, 0),
    )

    result = solve_fixed_layout_flow_objective(base, rooms, time_limit_s=5.0)

    assert result.status == "OPTIMAL"
    diagnostics = result.diagnostics
    assert diagnostics.condition_capacity_bucket_count == 0
    assert diagnostics.condition_capacity_literal_count == 0
    assert diagnostics.flow_capacity_constraint_count == 0
    assert diagnostics.flow_balance_constraint_count > 0


def test_tiny_safe_limit_forces_exact_multi_chunk_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _base(6, 2)
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 0, 1),
    )

    unpatched = solve_fixed_layout_flow_objective(
        base,
        rooms,
        time_limit_s=5.0,
        root_instance_id="airlock-1",
    )
    assert unpatched.status == "OPTIMAL"
    assert unpatched.scaled_objective_value == 18
    single_pass_buckets = unpatched.diagnostics.condition_capacity_bucket_count
    literals = unpatched.diagnostics.condition_capacity_literal_count
    assert literals > 0

    # Every per-commodity contribution bound equals the commodity supply; the tiny safe limit
    # keeps single contributions valid but forces several chunks per condition bucket.
    monkeypatch.setattr(
        "alters_base_planner.fixed_flow_objective_solver._SAFE_BUCKET_SUM_LIMIT",
        10,
    )
    chunked = solve_fixed_layout_flow_objective(
        base,
        rooms,
        time_limit_s=5.0,
        root_instance_id="airlock-1",
    )

    assert chunked.status == "OPTIMAL"
    assert chunked.scaled_objective_value == unpatched.scaled_objective_value
    assert chunked.diagnostics.condition_capacity_literal_count == literals
    assert chunked.diagnostics.condition_capacity_bucket_count > single_pass_buckets
    assert chunked.diagnostics.flow_capacity_constraint_count == (
        chunked.diagnostics.condition_capacity_bucket_count
    )