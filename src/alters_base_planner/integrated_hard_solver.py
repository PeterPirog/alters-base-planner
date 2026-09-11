from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .catalog import MODULE_BY_KEY
from .hard_constraints import (
    HardConstraintVariables,
    PlacementOptionSpec,
    UtilityAnchorSpec,
    build_hard_constraint_layer,
)
from .models import (
    BaseGeometry,
    ModuleInstance,
    ModulePlacement,
    PlacementAuthority,
    resolve_ports,
)


class StaticInfeasibilityError(ValueError):
    """The canonical domain contains a required instance with no legal placement."""


@dataclass(frozen=True, slots=True)
class IntegratedHardModel:
    """Canonical-domain adapter around the Stage-2 CP-SAT hard-feasibility layer.

    The object deliberately contains no gameplay objective. It is the bridge from real
    ``ModuleInstance``/``ModulePlacement`` data to the reusable hard-constraint formulation.
    """

    model: cp_model.CpModel
    variables: HardConstraintVariables
    placement_options: tuple[PlacementOptionSpec, ...]
    utility_anchors: tuple[UtilityAnchorSpec, ...]
    placement_by_option_id: dict[str, ModulePlacement]


@dataclass(frozen=True, slots=True)
class FixedInfrastructureResult:
    """Exact hard-feasibility result for one already-fixed SYSTEM/PLAYER packing."""

    status: str
    utilities: tuple[ModulePlacement, ...] = ()
    time_limit_reached: bool = False


def _validate_instances(instances: tuple[ModuleInstance, ...], root_instance_id: str) -> None:
    if not instances:
        raise ValueError("Integrated hard model requires at least one module instance")

    instance_ids = [instance.instance_id for instance in instances]
    if len(instance_ids) != len(set(instance_ids)):
        raise ValueError("Module instance IDs must be unique")
    if root_instance_id not in set(instance_ids):
        raise ValueError(f"Root instance {root_instance_id!r} is not present")

    for instance in instances:
        if instance.spec.authority is PlacementAuthority.SOLVER:
            raise ValueError(
                f"SOLVER module {instance.spec.key} must not be expanded as a required instance"
            )


def enumerate_placement_options(
    base: BaseGeometry,
    instances: tuple[ModuleInstance, ...],
) -> tuple[tuple[PlacementOptionSpec, ...], dict[str, ModulePlacement]]:
    """Enumerate every legal SYSTEM/PLAYER placement against the exact Base mask."""

    options: list[PlacementOptionSpec] = []
    placement_by_option_id: dict[str, ModulePlacement] = {}

    for instance in instances:
        spec = instance.spec
        instance_option_count = 0
        for y in range(base.height - spec.height + 1):
            for x in range(base.width - spec.width + 1):
                placement = ModulePlacement(
                    instance_id=instance.instance_id,
                    module_key=spec.key,
                    x=x,
                    y=y,
                    width=spec.width,
                    height=spec.height,
                )
                if not placement.cells <= base.buildable_cells:
                    continue

                option_id = f"{instance.instance_id}@{x}_{y}"
                option = PlacementOptionSpec(
                    option_id=option_id,
                    instance_id=instance.instance_id,
                    module_key=spec.key,
                    cells=placement.cells,
                    ports=resolve_ports(placement, spec),
                    transit_allowed=spec.transit_allowed,
                )
                options.append(option)
                placement_by_option_id[option_id] = placement
                instance_option_count += 1

        if instance_option_count == 0:
            raise StaticInfeasibilityError(
                f"Required module {instance.instance_id} ({spec.key}) has no legal placement "
                f"inside Base tier {base.tier}"
            )

    return tuple(options), placement_by_option_id


def enumerate_utility_anchors(base: BaseGeometry) -> tuple[UtilityAnchorSpec, ...]:
    """Enumerate every legal anchor shared by canonical Corridor/Elevator footprints."""

    corridor = MODULE_BY_KEY["corridor"]
    elevator = MODULE_BY_KEY["elevator"]
    if corridor.authority is not PlacementAuthority.SOLVER:
        raise AssertionError("Corridor must remain SOLVER-managed")
    if elevator.authority is not PlacementAuthority.SOLVER:
        raise AssertionError("Elevator must remain SOLVER-managed")
    if (corridor.width, corridor.height) != (elevator.width, elevator.height):
        raise AssertionError("Corridor and Elevator must share one anchor footprint")
    if (corridor.width, corridor.height) != (2, 1):
        raise AssertionError("Current port/anchor model requires 2x1 solver infrastructure")

    anchors: list[UtilityAnchorSpec] = []
    for y in range(base.height - corridor.height + 1):
        for x in range(base.width - corridor.width + 1):
            anchor = UtilityAnchorSpec(x, y)
            if anchor.cells <= base.buildable_cells:
                anchors.append(anchor)
    return tuple(anchors)


def _build_compiled_model(
    base: BaseGeometry,
    placement_options: tuple[PlacementOptionSpec, ...],
    placement_by_option_id: dict[str, ModulePlacement],
    *,
    root_instance_id: str,
    utility_anchors: tuple[UtilityAnchorSpec, ...] | None = None,
) -> IntegratedHardModel:
    if utility_anchors is None:
        utility_anchors = enumerate_utility_anchors(base)

    model = cp_model.CpModel()
    variables = build_hard_constraint_layer(
        model,
        buildable_cells=base.buildable_cells,
        placement_options=placement_options,
        utility_anchors=utility_anchors,
        root_instance_id=root_instance_id,
    )
    validation_error = model.validate()
    if validation_error:
        raise AssertionError(f"Invalid integrated hard-feasibility CP-SAT model: {validation_error}")

    return IntegratedHardModel(
        model=model,
        variables=variables,
        placement_options=placement_options,
        utility_anchors=utility_anchors,
        placement_by_option_id=placement_by_option_id,
    )


def compile_integrated_hard_model(
    base: BaseGeometry,
    instances: tuple[ModuleInstance, ...],
    *,
    root_instance_id: str = "airlock-1",
) -> IntegratedHardModel:
    """Compile canonical module data into the exact Stage-2 hard-feasibility model.

    This is intentionally not yet the production optimization entry point. It establishes a
    tested, auditable adapter that Stage 2 can wire into ``solve_plan()`` without translating
    real modules into a separate hand-written geometry model.
    """

    _validate_instances(instances, root_instance_id)
    placement_options, placement_by_option_id = enumerate_placement_options(base, instances)
    return _build_compiled_model(
        base,
        placement_options,
        placement_by_option_id,
        root_instance_id=root_instance_id,
    )


def compile_fixed_layout_hard_model(
    base: BaseGeometry,
    rooms: tuple[ModulePlacement, ...],
    *,
    root_instance_id: str = "airlock-1",
) -> IntegratedHardModel:
    """Compile one fixed SYSTEM/PLAYER packing and leave only infrastructure undecided.

    This is the exact Stage-2 decomposition boundary used to replace greedy routing: room
    placement may still come from the transitional master model, but Corridor/Elevator hard
    feasibility is decided by CP-SAT rather than by one deterministic path construction.

    Because room placements are fixed here, any utility anchor overlapping an occupied room
    cell is impossible by H3 and can be removed before variable creation. This is an exact
    domain reduction, not a heuristic: it removes only assignments that the shared occupancy
    constraints would otherwise force to zero.
    """

    if not rooms:
        raise ValueError("Fixed-layout hard model requires at least one room placement")

    instance_ids = [room.instance_id for room in rooms]
    if len(instance_ids) != len(set(instance_ids)):
        raise ValueError("Fixed room placement instance IDs must be unique")
    if root_instance_id not in set(instance_ids):
        raise ValueError(f"Root instance {root_instance_id!r} is not present")

    placement_options: list[PlacementOptionSpec] = []
    placement_by_option_id: dict[str, ModulePlacement] = {}
    occupied: set[tuple[int, int]] = set()

    for room in rooms:
        spec = MODULE_BY_KEY.get(room.module_key)
        if spec is None:
            raise ValueError(f"Unknown module key in fixed placement: {room.module_key}")
        if spec.authority is PlacementAuthority.SOLVER:
            raise ValueError(f"Fixed room packing contains SOLVER module {room.instance_id}")
        if (room.width, room.height) != (spec.width, spec.height):
            raise AssertionError(
                f"Fixed placement {room.instance_id} footprint does not match ModuleSpec"
            )
        if not room.cells <= base.buildable_cells:
            raise AssertionError(
                f"Fixed placement {room.instance_id} leaves the buildable Base domain"
            )
        overlap = occupied & room.cells
        if overlap:
            raise AssertionError(
                f"Fixed SYSTEM/PLAYER packing overlaps at cells {sorted(overlap)}"
            )
        occupied.update(room.cells)

        option_id = f"fixed:{room.instance_id}"
        placement_options.append(
            PlacementOptionSpec(
                option_id=option_id,
                instance_id=room.instance_id,
                module_key=room.module_key,
                cells=room.cells,
                ports=resolve_ports(room, spec),
                transit_allowed=spec.transit_allowed,
            )
        )
        placement_by_option_id[option_id] = room

    utility_anchors = tuple(
        anchor for anchor in enumerate_utility_anchors(base) if not (anchor.cells & occupied)
    )
    compiled = _build_compiled_model(
        base,
        tuple(placement_options),
        placement_by_option_id,
        root_instance_id=root_instance_id,
        utility_anchors=utility_anchors,
    )

    # Search hint only: prefer inactive infrastructure first. This does not constrain
    # correctness and does not introduce a competing gameplay objective.
    for variable in compiled.variables.corridor.values():
        compiled.model.add_hint(variable, 0)
    for variable in compiled.variables.elevator.values():
        compiled.model.add_hint(variable, 0)

    validation_error = compiled.model.validate()
    if validation_error:
        raise AssertionError(f"Invalid fixed-layout hard-feasibility model: {validation_error}")
    return compiled


def extract_integrated_solution(
    solver: cp_model.CpSolver,
    compiled: IntegratedHardModel,
) -> list[ModulePlacement]:
    """Extract selected SYSTEM/PLAYER/SOLVER placements from a solved hard model."""

    selected: list[ModulePlacement] = []
    selected_instances: set[str] = set()
    for option in compiled.placement_options:
        if solver.value(compiled.variables.placement[option.option_id]) != 1:
            continue
        placement = compiled.placement_by_option_id[option.option_id]
        if placement.instance_id in selected_instances:
            raise AssertionError(
                f"Integrated model selected multiple placements for {placement.instance_id}"
            )
        selected_instances.add(placement.instance_id)
        selected.append(placement)

    counters: Counter[str] = Counter()
    for anchor in sorted(compiled.variables.utility_active):
        corridor_selected = solver.value(compiled.variables.corridor[anchor]) == 1
        elevator_selected = solver.value(compiled.variables.elevator[anchor]) == 1
        if corridor_selected and elevator_selected:
            raise AssertionError(f"Both solver module kinds selected at anchor {anchor}")
        if not corridor_selected and not elevator_selected:
            continue

        module_key = "elevator" if elevator_selected else "corridor"
        spec = MODULE_BY_KEY[module_key]
        counters[module_key] += 1
        selected.append(
            ModulePlacement(
                instance_id=f"{module_key}-{counters[module_key]}",
                module_key=module_key,
                x=anchor[0],
                y=anchor[1],
                width=spec.width,
                height=spec.height,
            )
        )

    return selected


def solve_fixed_layout_infrastructure(
    base: BaseGeometry,
    rooms: tuple[ModulePlacement, ...],
    *,
    time_limit_s: float,
    root_instance_id: str = "airlock-1",
) -> FixedInfrastructureResult:
    """Prove/find infrastructure hard-feasibility for one fixed room packing.

    No gameplay or utility-count objective is used here. A false-first hint merely guides the
    SAT search toward sparse infrastructure; any returned network is hard-feasible. `INFEASIBLE`
    means CP-SAT proved that no legal Corridor/Elevator network exists for the fixed packing.
    """

    if time_limit_s <= 0:
        return FixedInfrastructureResult(status="TIME_LIMIT", time_limit_reached=True)

    compiled = compile_fixed_layout_hard_model(
        base,
        rooms,
        root_instance_id=root_instance_id,
    )
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 8
    solver.parameters.max_time_in_seconds = max(0.001, float(time_limit_s))
    status = solver.solve(compiled.model)

    if status == cp_model.MODEL_INVALID:
        raise AssertionError("CP-SAT rejected the fixed-layout hard-feasibility model")
    if status == cp_model.UNKNOWN:
        return FixedInfrastructureResult(status="TIME_LIMIT", time_limit_reached=True)
    if status == cp_model.INFEASIBLE:
        return FixedInfrastructureResult(status="INFEASIBLE")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise AssertionError(f"Unexpected CP-SAT hard-feasibility status: {status}")

    selected = extract_integrated_solution(solver, compiled)
    utilities = tuple(
        module
        for module in selected
        if MODULE_BY_KEY[module.module_key].authority is PlacementAuthority.SOLVER
    )
    return FixedInfrastructureResult(
        status="FEASIBLE",
        utilities=utilities,
        time_limit_reached=status == cp_model.FEASIBLE,
    )
