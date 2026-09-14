
from ortools.sat.python import cp_model

from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.master_manhattan_lower_bound import (
    add_master_modified_manhattan_lower_bound,
)
from alters_base_planner.models import BaseGeometry, ModuleInstance, ModulePlacement
from alters_base_planner.objective import (
    build_scaled_objective,
    scaled_modified_manhattan_lower_bound,
)


def _base(width: int, height: int = 1) -> BaseGeometry:
    return BaseGeometry(
        tier=99,
        width=width,
        height=height,
        allowed_cells=frozenset((x, y) for y in range(height) for x in range(width)),
        blocked_cells=frozenset(),
        organics_capacity=999,
        source="master-manhattan-lb-test",
        verified=True,
    )


def _instance(instance_id: str, module_key: str) -> ModuleInstance:
    return ModuleInstance(instance_id, MODULE_BY_KEY[module_key])


def _placements(
    instances: list[ModuleInstance], chosen: dict[str, tuple[int, int]]
) -> tuple[ModulePlacement, ...]:
    return tuple(
        ModulePlacement(
            instance.instance_id,
            instance.spec.key,
            chosen[instance.instance_id][0],
            chosen[instance.instance_id][1],
            instance.spec.width,
            instance.spec.height,
        )
        for instance in instances
    )


def _build_master(base: BaseGeometry, instances: list[ModuleInstance], usage_weights=None):
    model = cp_model.CpModel()
    candidates_by_instance = {
        instance.instance_id: [
            (x, y)
            for y in range(base.height - instance.spec.height + 1)
            for x in range(base.width - instance.spec.width + 1)
        ]
        for instance in instances
    }
    vars_by_instance = {}
    for instance in instances:
        variables = [
            model.new_bool_var(f"p_{instance.instance_id}_{i}")
            for i in range(len(candidates_by_instance[instance.instance_id]))
        ]
        model.add_exactly_one(variables)
        vars_by_instance[instance.instance_id] = variables
    objective = build_scaled_objective(_placements(instances, {i.instance_id: (0, 0) for i in instances}), usage_weights)
    build = add_master_modified_manhattan_lower_bound(
        model,
        instances=instances,
        vars_by_instance=vars_by_instance,
        candidates_by_instance=candidates_by_instance,
        objective=objective,
    )
    return model, vars_by_instance, candidates_by_instance, objective, build


def _solve_fixed_master_lb(
    base: BaseGeometry,
    instances: list[ModuleInstance],
    chosen: dict[str, tuple[int, int]],
    usage_weights=None,
) -> int:
    model, vars_by_instance, candidates_by_instance, _, build = _build_master(
        base, instances, usage_weights
    )
    for instance in instances:
        target = chosen[instance.instance_id]
        indices = [
            index
            for index, candidate in enumerate(candidates_by_instance[instance.instance_id])
            if candidate == target
        ]
        assert len(indices) == 1
        model.add(vars_by_instance[instance.instance_id][indices[0]] == 1)
    solver = cp_model.CpSolver()
    status = solver.solve(model)
    assert status == cp_model.OPTIMAL
    return solver.value(build.master_scaled_lb)


def test_master_lb_matches_documented_bound_for_concrete_placements() -> None:
    base = _base(16, 4)
    instances = [
        _instance("airlock-1", "airlock"),
        _instance("workshop-1", "workshop"),
    ]

    separated_rooms = _placements(
        instances, {"airlock-1": (0, 0), "workshop-1": (8, 0)}
    )
    assert _solve_fixed_master_lb(
        base, instances, {"airlock-1": (0, 0), "workshop-1": (8, 0)}
    ) == scaled_modified_manhattan_lower_bound(separated_rooms)

    direct_rooms = _placements(
        instances, {"airlock-1": (0, 0), "workshop-1": (4, 0)}
    )
    master_value = _solve_fixed_master_lb(
        base, instances, {"airlock-1": (0, 0), "workshop-1": (4, 0)}
    )
    assert master_value == scaled_modified_manhattan_lower_bound(direct_rooms)
    assert master_value == 0

    cross_rooms = _placements(
        instances, {"airlock-1": (0, 0), "workshop-1": (10, 2)}
    )
    assert _solve_fixed_master_lb(
        base, instances, {"airlock-1": (0, 0), "workshop-1": (10, 2)}
    ) == scaled_modified_manhattan_lower_bound(cross_rooms)


def test_master_lb_matches_for_tall_and_top_access_rooms() -> None:
    base = _base(20, 6)
    instances = [
        _instance("airlock-1", "airlock"),
        _instance("quantum-1", "quantum_computer"),
    ]
    rooms = _placements(
        instances, {"airlock-1": (0, 0), "quantum-1": (8, 1)}
    )
    assert _solve_fixed_master_lb(
        base, instances, {"airlock-1": (0, 0), "quantum-1": (8, 1)}
    ) == scaled_modified_manhattan_lower_bound(rooms)

    top_instances = [
        _instance("airlock-1", "airlock"),
        _instance("repulsor-1", "radiation_repulsor"),
    ]
    repulsor_spec = MODULE_BY_KEY["radiation_repulsor"]
    assert repulsor_spec.ports[0].cell_y == repulsor_spec.height - 1
    repulsor_rooms = _placements(
        top_instances, {"airlock-1": (0, 0), "repulsor-1": (6, 2)}
    )
    assert _solve_fixed_master_lb(
        base,
        top_instances,
        {"airlock-1": (0, 0), "repulsor-1": (6, 2)},
    ) == scaled_modified_manhattan_lower_bound(repulsor_rooms)


def test_master_lb_matches_every_exhaustive_small_packing() -> None:
    base = _base(12, 2)
    instances = [
        _instance("airlock-1", "airlock"),
        _instance("workshop-1", "workshop"),
        _instance("recycler-1", "recycler"),
    ]
    model, vars_by_instance, candidates_by_instance, objective, build = _build_master(
        base, instances
    )

    checked = 0
    ranges = {
        instance.instance_id: candidates_by_instance[instance.instance_id]
        for instance in instances
    }
    for airlock in ranges["airlock-1"]:
        for workshop in ranges["workshop-1"]:
            for recycler in ranges["recycler-1"]:
                chosen = {
                    "airlock-1": airlock,
                    "workshop-1": workshop,
                    "recycler-1": recycler,
                }
                placements = _placements(instances, chosen)
                occupied = [cell for room in placements for cell in room.cells]
                if len(occupied) != len(set(occupied)):
                    continue
                fixed_model = model.clone()
                for instance in instances:
                    index = ranges[instance.instance_id].index(chosen[instance.instance_id])
                    fixed_model.add(vars_by_instance[instance.instance_id][index] == 1)
                solver = cp_model.CpSolver()
                assert solver.solve(fixed_model) == cp_model.OPTIMAL
                assert solver.value(build.master_scaled_lb) == (
                    scaled_modified_manhattan_lower_bound(placements, objective)
                )
                checked += 1
    assert checked > 0


def test_master_ordering_selects_minimum_documented_bound() -> None:
    base = _base(12)
    instances = [
        _instance("airlock-1", "airlock"),
        _instance("workshop-1", "workshop"),
    ]
    model, vars_by_instance, candidates_by_instance, objective, build = _build_master(
        base, instances
    )
    model.minimize(build.master_scaled_lb)
    solver = cp_model.CpSolver()
    status = solver.solve(model)
    assert status == cp_model.OPTIMAL

    selected = {}
    for instance in instances:
        for index, var in enumerate(vars_by_instance[instance.instance_id]):
            if solver.value(var):
                selected[instance.instance_id] = candidates_by_instance[instance.instance_id][index]
                break
    master_lb = solver.value(build.master_scaled_lb)

    best_documented = None
    for airlock in candidates_by_instance["airlock-1"]:
        for workshop in candidates_by_instance["workshop-1"]:
            placements = _placements(
                instances, {"airlock-1": airlock, "workshop-1": workshop}
            )
            occupied = [cell for room in placements for cell in room.cells]
            if len(occupied) != len(set(occupied)):
                continue
            documented = scaled_modified_manhattan_lower_bound(placements, objective)
            if best_documented is None or documented < best_documented:
                best_documented = documented
    assert best_documented is not None
    assert master_lb == best_documented
    assert master_lb == 0
    assert selected == {"airlock-1": (0, 0), "workshop-1": (4, 0)}


def test_master_incumbent_cut_retains_equality_and_excludes_worse() -> None:
    base = _base(12)
    instances = [
        _instance("airlock-1", "airlock"),
        _instance("workshop-1", "workshop"),
    ]
    model, vars_by_instance, candidates_by_instance, _, build = _build_master(base, instances)

    bound = _solve_fixed_master_lb(
        base, instances, {"airlock-1": (0, 0), "workshop-1": (4, 0)}
    )
    model.add(build.master_scaled_lb <= bound)

    for packing in (
        {"airlock-1": (0, 0), "workshop-1": (4, 0)},
        {"airlock-1": (0, 0), "workshop-1": (4, 0)},
    ):
        fixed = model.clone()
        for instance in instances:
            index = candidates_by_instance[instance.instance_id].index(
                packing[instance.instance_id]
            )
            fixed.add(vars_by_instance[instance.instance_id][index] == 1)
        assert cp_model.CpSolver().solve(fixed) == cp_model.OPTIMAL

    fixed_worse = model.clone()
    for instance in instances:
        index = candidates_by_instance[instance.instance_id].index(
            {"airlock-1": (0, 0), "workshop-1": (8, 0)}[instance.instance_id]
        )
        fixed_worse.add(vars_by_instance[instance.instance_id][index] == 1)
    assert cp_model.CpSolver().solve(fixed_worse) == cp_model.INFEASIBLE


def test_master_lb_uses_effective_custom_weights_and_zero_weight_rooms() -> None:
    base = _base(12)
    instances = [
        _instance("airlock-1", "airlock"),
        _instance("workshop-1", "workshop"),
        _instance("recycler-1", "recycler"),
    ]
    usage_weights = {"airlock": 0.75, "workshop": 0.2, "recycler": 0.0}
    rooms = _placements(
        instances,
        {"airlock-1": (0, 0), "workshop-1": (6, 0), "recycler-1": (10, 0)},
    )
    objective = build_scaled_objective(rooms, usage_weights)
    # Zero-weight recycler creates no objective pair.
    assert [pair.pair_id for pair in objective.pairs] == ["airlock-1|workshop-1"]

    model, vars_by_instance, candidates_by_instance, canonical, build = _build_master(
        base, instances, usage_weights
    )
    assert canonical == objective

    chosen = {"airlock-1": (0, 0), "workshop-1": (6, 0), "recycler-1": (10, 0)}
    for instance in instances:
        index = candidates_by_instance[instance.instance_id].index(chosen[instance.instance_id])
        model.add(vars_by_instance[instance.instance_id][index] == 1)
    solver = cp_model.CpSolver()
    assert solver.solve(model) == cp_model.OPTIMAL
    assert solver.value(build.master_scaled_lb) == (
        scaled_modified_manhattan_lower_bound(rooms, canonical, usage_weights)
    )


def test_master_lb_is_zero_without_positive_weight_pairs() -> None:
    base = _base(12)
    instances = [
        _instance("airlock-1", "airlock"),
        _instance("recycler-1", "recycler"),
    ]
    usage_weights = {"airlock": 1.0, "recycler": 0.0}
    model, vars_by_instance, candidates_by_instance, objective, build = _build_master(
        base, instances, usage_weights
    )
    assert objective.pairs == ()
    solver = cp_model.CpSolver()
    status = solver.solve(model)
    assert status == cp_model.OPTIMAL
    assert solver.value(build.master_scaled_lb) == 0


def test_master_lb_scale_matches_pair_coefficients_exactly() -> None:
    base = _base(12)
    instances = [
        _instance("airlock-1", "airlock"),
        _instance("workshop-1", "workshop"),
    ]
    chosen = {"airlock-1": (0, 0), "workshop-1": (6, 0)}
    rooms = _placements(instances, chosen)
    objective = build_scaled_objective(rooms)
    documented = scaled_modified_manhattan_lower_bound(rooms, objective)
    assert documented == objective.pairs[0].coefficient
    assert _solve_fixed_master_lb(base, instances, chosen) == documented