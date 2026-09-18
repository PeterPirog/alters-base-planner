from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic

from ortools.sat.python import cp_model

from .base import builtin_base
from .catalog import MODULE_BY_KEY, MODULES, resolve_usage_weights
from .fixed_flow_objective_solver import (
    FixedFlowObjectiveDiagnostics,
    solve_fixed_layout_flow_objective,
)
from .models import (
    BaseGeometry,
    ModuleInstance,
    ModulePlacement,
    PlacementAuthority,
    PlanRequest,
    PlanResult,
    expand_instances,
    footprint_cells,
)
from .objective import (
    ScaledObjective,
    build_scaled_objective,
    scaled_modified_manhattan_lower_bound,
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    x: int
    y: int
    cells: frozenset[tuple[int, int]]
    search_cost: int


class _RoomMasterMode(StrEnum):
    HEURISTIC_OBJECTIVE = "heuristic_objective"
    FEASIBILITY_ENUMERATION = "feasibility_enumeration"
    HEURISTIC_COST_BANDS = "heuristic_cost_bands"


@dataclass(slots=True)
class _RoomPackingTrace:
    selected_search_cost: int
    master_solve_time_s: float
    master_status: str
    master_phase: str
    fixed_subproblem_status: str = "NOT_EVALUATED"
    fixed_subproblem_time_s: float = 0.0
    connected_candidate: bool = False


@dataclass(slots=True)
class _RoomMasterDiagnostics:
    mode: _RoomMasterMode
    solve_count: int = 0
    solve_time_s: float = 0.0
    first_solution_time_s: float | None = None
    optimal_status_count: int = 0
    feasible_status_count: int = 0
    model_build_time_s: float = 0.0
    band_count: int = 0
    cost_discovery_solve_count: int = 0
    cost_discovery_time_s: float = 0.0
    band_enumeration_solve_count: int = 0
    band_enumeration_time_s: float = 0.0
    same_cost_packings_examined: int = 0
    largest_completed_band_size: int = 0

    def observe(
        self,
        status: cp_model.CpSolverStatus,
        elapsed_s: float,
        *,
        phase: str,
    ) -> None:
        self.solve_count += 1
        self.solve_time_s += elapsed_s
        if phase == "cost_discovery":
            self.cost_discovery_solve_count += 1
            self.cost_discovery_time_s += elapsed_s
        elif phase == "band_enumeration":
            self.band_enumeration_solve_count += 1
            self.band_enumeration_time_s += elapsed_s
        if status == cp_model.OPTIMAL:
            self.optimal_status_count += 1
        elif status == cp_model.FEASIBLE:
            self.feasible_status_count += 1
        if (
            self.first_solution_time_s is None
            and status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        ):
            self.first_solution_time_s = self.solve_time_s

    def observe_model_build(self, elapsed_s: float) -> None:
        self.model_build_time_s += elapsed_s

    def start_band(self) -> None:
        self.band_count += 1

    def complete_band(self, size: int) -> None:
        if size <= 0:
            raise AssertionError("A completed room-master cost band must contain a packing")
        self.largest_completed_band_size = max(self.largest_completed_band_size, size)

    def apply(self, result: PlanResult) -> None:
        result.room_master_mode = self.mode.value
        result.room_master_solve_count = self.solve_count
        result.room_master_solve_time_s = self.solve_time_s
        result.room_master_first_solution_time_s = self.first_solution_time_s
        result.room_master_optimal_status_count = self.optimal_status_count
        result.room_master_feasible_status_count = self.feasible_status_count
        result.room_master_model_build_time_s = self.model_build_time_s
        result.room_master_band_count = self.band_count
        result.room_master_cost_discovery_solve_count = self.cost_discovery_solve_count
        result.room_master_cost_discovery_time_s = self.cost_discovery_time_s
        result.room_master_band_enumeration_solve_count = self.band_enumeration_solve_count
        result.room_master_band_enumeration_time_s = self.band_enumeration_time_s
        result.room_master_same_cost_packings_examined = self.same_cost_packings_examined
        result.room_master_largest_completed_band_size = self.largest_completed_band_size


@dataclass(slots=True)
class _CompiledRoomMaster:
    model: cp_model.CpModel
    vars_by_instance: dict[str, list[cp_model.IntVar]]
    search_cost_expr: cp_model.LinearExpr


@dataclass(slots=True)
class _FixedDiagnosticsAggregate:
    """Aggregate Stage-4 diagnostics across exact fixed-packing subproblems."""

    subproblem_count: int = 0
    max_graph_nodes: int = 0
    max_graph_arcs: int = 0
    max_objective_pairs: int = 0
    flow_formulation: str = "source_aggregated_weighted_flow"
    max_source_commodities: int = 0
    max_source_flow_variables: int = 0
    max_source_flow_full_variables: int = 0
    total_source_flow_variables: int = 0
    total_source_flow_full_variables: int = 0
    max_condition_capacity_buckets: int = 0
    max_condition_capacity_literals: int = 0
    max_endpoint_distribution_variables: int = 0
    max_flow_capacity_constraints: int = 0
    max_flow_balance_constraints: int = 0
    incumbent_distance_cap_pruning_used: bool = False
    objective_bound_relaxation_pruned: bool = False
    max_relaxed_graph_primary_lower_bound: int | None = None
    min_incumbent_primary_bound: int | None = None
    max_incumbent_distance_cap_pairs: int = 0
    max_source_flow_variables_before_cap: int = 0
    max_source_flow_variables_after_cap: int = 0
    max_incumbent_cap_pruned_flow_variables: int = 0
    max_cp_sat_variables: int = 0
    max_cp_sat_constraints: int = 0
    lexicographic_scalarization_used: bool = False
    max_primary_objective_upper_bound: int = 0
    max_combined_objective_upper_bound: int = 0
    max_weight_f: int = 0
    max_weight_mass: int = 0
    max_weight_elevator: int = 0
    max_weight_corridor: int = 0
    max_corridor_bound: int = 0
    max_elevator_bound: int = 0
    max_mass_bound: int = 0
    max_incumbent_scalar_value: int | None = None
    model_build_time_s: float = 0.0
    cp_sat_solve_time_s: float = 0.0
    total_time_s: float = 0.0
    hard_model_build_time_s: float = 0.0
    path_graph_build_time_s: float = 0.0
    objective_definition_time_s: float = 0.0
    flow_model_build_time_s: float = 0.0
    lexicographic_finalize_time_s: float = 0.0

    def observe(self, diagnostics: FixedFlowObjectiveDiagnostics) -> None:
        self.subproblem_count += 1
        if diagnostics.flow_formulation != self.flow_formulation:
            raise AssertionError("Fixed subproblems must use one flow formulation")
        self.max_graph_nodes = max(self.max_graph_nodes, diagnostics.graph_node_count)
        self.max_graph_arcs = max(self.max_graph_arcs, diagnostics.graph_arc_count)
        self.max_objective_pairs = max(
            self.max_objective_pairs,
            diagnostics.objective_pair_count,
        )
        self.max_source_commodities = max(
            self.max_source_commodities,
            diagnostics.source_commodity_count,
        )
        self.max_source_flow_variables = max(
            self.max_source_flow_variables,
            diagnostics.source_flow_variable_count,
        )
        self.max_source_flow_full_variables = max(
            self.max_source_flow_full_variables,
            diagnostics.source_flow_full_variable_count,
        )
        self.total_source_flow_variables += diagnostics.source_flow_variable_count
        self.total_source_flow_full_variables += diagnostics.source_flow_full_variable_count
        self.max_condition_capacity_buckets = max(
            self.max_condition_capacity_buckets,
            diagnostics.condition_capacity_bucket_count,
        )
        self.max_condition_capacity_literals = max(
            self.max_condition_capacity_literals,
            diagnostics.condition_capacity_literal_count,
        )
        self.max_endpoint_distribution_variables = max(
            self.max_endpoint_distribution_variables,
            diagnostics.endpoint_distribution_variable_count,
        )
        self.max_flow_capacity_constraints = max(
            self.max_flow_capacity_constraints,
            diagnostics.flow_capacity_constraint_count,
        )
        self.max_flow_balance_constraints = max(
            self.max_flow_balance_constraints,
            diagnostics.flow_balance_constraint_count,
        )
        self.incumbent_distance_cap_pruning_used = (
            self.incumbent_distance_cap_pruning_used
            or diagnostics.incumbent_distance_cap_pruning_used
        )
        self.objective_bound_relaxation_pruned = (
            self.objective_bound_relaxation_pruned
            or diagnostics.objective_bound_relaxation_pruned
        )
        if diagnostics.relaxed_graph_primary_lower_bound is not None:
            self.max_relaxed_graph_primary_lower_bound = (
                diagnostics.relaxed_graph_primary_lower_bound
                if self.max_relaxed_graph_primary_lower_bound is None
                else max(
                    self.max_relaxed_graph_primary_lower_bound,
                    diagnostics.relaxed_graph_primary_lower_bound,
                )
            )
        if diagnostics.incumbent_primary_bound is not None:
            self.min_incumbent_primary_bound = (
                diagnostics.incumbent_primary_bound
                if self.min_incumbent_primary_bound is None
                else min(
                    self.min_incumbent_primary_bound,
                    diagnostics.incumbent_primary_bound,
                )
            )
        self.max_incumbent_distance_cap_pairs = max(
            self.max_incumbent_distance_cap_pairs,
            diagnostics.incumbent_distance_cap_pair_count,
        )
        self.max_source_flow_variables_before_cap = max(
            self.max_source_flow_variables_before_cap,
            diagnostics.source_flow_variables_before_incumbent_cap,
        )
        self.max_source_flow_variables_after_cap = max(
            self.max_source_flow_variables_after_cap,
            diagnostics.source_flow_variables_after_incumbent_cap,
        )
        self.max_incumbent_cap_pruned_flow_variables = max(
            self.max_incumbent_cap_pruned_flow_variables,
            diagnostics.incumbent_cap_pruned_flow_variables,
        )
        self.max_cp_sat_variables = max(
            self.max_cp_sat_variables,
            diagnostics.cp_sat_variable_count,
        )
        self.max_cp_sat_constraints = max(
            self.max_cp_sat_constraints,
            diagnostics.cp_sat_constraint_count,
        )
        self.lexicographic_scalarization_used |= diagnostics.lexicographic_scalarization_used
        self.max_primary_objective_upper_bound = max(
            self.max_primary_objective_upper_bound,
            diagnostics.primary_objective_upper_bound,
        )
        self.max_combined_objective_upper_bound = max(
            self.max_combined_objective_upper_bound,
            diagnostics.combined_objective_upper_bound,
        )
        self.max_weight_f = max(
            self.max_weight_f,
            diagnostics.weight_f,
        )
        self.max_weight_mass = max(
            self.max_weight_mass,
            diagnostics.weight_mass,
        )
        self.max_weight_elevator = max(
            self.max_weight_elevator,
            diagnostics.weight_elevator,
        )
        self.max_weight_corridor = max(
            self.max_weight_corridor,
            diagnostics.weight_corridor,
        )
        self.max_corridor_bound = max(
            self.max_corridor_bound,
            diagnostics.corridor_bound,
        )
        self.max_elevator_bound = max(
            self.max_elevator_bound,
            diagnostics.elevator_bound,
        )
        self.max_mass_bound = max(self.max_mass_bound, diagnostics.mass_bound)
        if diagnostics.incumbent_scalar_value is not None:
            self.max_incumbent_scalar_value = max(
                self.max_incumbent_scalar_value or 0,
                diagnostics.incumbent_scalar_value,
            )
        self.model_build_time_s += diagnostics.model_build_time_s
        self.cp_sat_solve_time_s += diagnostics.cp_sat_solve_time_s
        self.total_time_s += diagnostics.total_time_s
        self.hard_model_build_time_s += diagnostics.hard_model_build_time_s
        self.path_graph_build_time_s += diagnostics.path_graph_build_time_s
        self.objective_definition_time_s += diagnostics.objective_definition_time_s
        self.flow_model_build_time_s += diagnostics.flow_model_build_time_s
        self.lexicographic_finalize_time_s += diagnostics.lexicographic_finalize_time_s

    def apply(self, result: PlanResult) -> None:
        result.fixed_subproblem_count = self.subproblem_count
        result.max_fixed_graph_nodes = self.max_graph_nodes
        result.max_fixed_graph_arcs = self.max_graph_arcs
        result.max_fixed_objective_pairs = self.max_objective_pairs
        result.fixed_flow_formulation = self.flow_formulation
        result.max_fixed_source_commodities = self.max_source_commodities
        result.max_fixed_source_flow_variables = self.max_source_flow_variables
        result.max_fixed_source_flow_full_variables = self.max_source_flow_full_variables
        result.total_fixed_source_flow_variables = self.total_source_flow_variables
        result.total_fixed_source_flow_full_variables = self.total_source_flow_full_variables
        result.max_fixed_condition_capacity_buckets = self.max_condition_capacity_buckets
        result.max_fixed_condition_capacity_literals = self.max_condition_capacity_literals
        result.max_fixed_endpoint_distribution_variables = (
            self.max_endpoint_distribution_variables
        )
        result.max_fixed_flow_capacity_constraints = self.max_flow_capacity_constraints
        result.max_fixed_flow_balance_constraints = self.max_flow_balance_constraints
        result.fixed_incumbent_distance_cap_pruning_used = (
            self.incumbent_distance_cap_pruning_used
        )
        result.fixed_objective_bound_relaxation_pruned = (
            self.objective_bound_relaxation_pruned
        )
        result.max_fixed_relaxed_graph_primary_lower_bound = (
            self.max_relaxed_graph_primary_lower_bound
        )
        result.min_fixed_incumbent_primary_bound = self.min_incumbent_primary_bound
        result.max_fixed_incumbent_distance_cap_pairs = self.max_incumbent_distance_cap_pairs
        result.max_fixed_source_flow_variables_before_incumbent_cap = (
            self.max_source_flow_variables_before_cap
        )
        result.max_fixed_source_flow_variables_after_incumbent_cap = (
            self.max_source_flow_variables_after_cap
        )
        result.max_fixed_incumbent_cap_pruned_flow_variables = (
            self.max_incumbent_cap_pruned_flow_variables
        )
        result.max_fixed_cp_sat_variables = self.max_cp_sat_variables
        result.max_fixed_cp_sat_constraints = self.max_cp_sat_constraints
        result.fixed_lexicographic_scalarization_used = self.lexicographic_scalarization_used
        result.max_fixed_primary_objective_upper_bound = self.max_primary_objective_upper_bound
        result.max_fixed_combined_objective_upper_bound = self.max_combined_objective_upper_bound
        result.max_fixed_lexicographic_weight_f = self.max_weight_f
        result.max_fixed_lexicographic_weight_mass = self.max_weight_mass
        result.max_fixed_lexicographic_weight_elevator = self.max_weight_elevator
        result.max_fixed_lexicographic_weight_corridor = self.max_weight_corridor
        result.max_fixed_lexicographic_corridor_bound = self.max_corridor_bound
        result.max_fixed_lexicographic_elevator_bound = self.max_elevator_bound
        result.max_fixed_lexicographic_mass_bound = self.max_mass_bound
        result.max_fixed_incumbent_scalar_value = self.max_incumbent_scalar_value
        result.fixed_model_build_time_s = self.model_build_time_s
        result.fixed_cp_sat_solve_time_s = self.cp_sat_solve_time_s
        result.fixed_subproblem_time_s = self.total_time_s
        result.fixed_hard_model_build_time_s = self.hard_model_build_time_s
        result.fixed_path_graph_build_time_s = self.path_graph_build_time_s
        result.fixed_objective_definition_time_s = self.objective_definition_time_s
        result.fixed_source_flow_model_build_time_s = self.flow_model_build_time_s
        result.fixed_lexicographic_finalize_time_s = self.lexicographic_finalize_time_s


def _candidate_positions(
    instance: ModuleInstance,
    base: BaseGeometry,
    usage_weights: Mapping[str, float] | None = None,
) -> list[_Candidate]:
    """Enumerate legal non-SOLVER positions; ``search_cost`` only orders candidates."""

    spec = instance.spec
    cx = (base.width - 1) / 2
    cy = (base.height - 1) / 2
    result: list[_Candidate] = []
    mean_world_port_offset = sum(
        spec.height - 1 - port.cell_y for port in spec.ports
    ) / len(spec.ports)
    for y in range(base.height - spec.height + 1):
        for x in range(base.width - spec.width + 1):
            cells = footprint_cells(x, y, spec.width, spec.height)
            if not cells <= base.buildable_cells:
                continue
            px = x + (spec.width - 1) / 2
            py = y + mean_world_port_offset
            distance = abs(px - cx) + 0.35 * abs(py - cy)
            usage_weight = (
                spec.visit_weight if usage_weights is None else usage_weights[spec.key]
            )
            search_cost = int(100 * max(usage_weight, 0.05) * distance)
            result.append(_Candidate(x, y, cells, search_cost))
    return result


def _validate_utility_geometry(
    base: BaseGeometry,
    rooms: list[ModulePlacement],
    utilities: list[ModulePlacement],
) -> None:
    """Fail fast if selected SOLVER modules violate physical occupancy constraints."""

    room_cells = set().union(*(room.cells for room in rooms)) if rooms else set()
    utility_cells: set[tuple[int, int]] = set()
    seen_anchors: set[tuple[int, int]] = set()

    for utility in utilities:
        spec = MODULE_BY_KEY.get(utility.module_key)
        if spec is None or spec.authority is not PlacementAuthority.SOLVER:
            raise AssertionError(
                f"Selected infrastructure {utility.instance_id} is not a SOLVER module"
            )
        if (utility.width, utility.height) != (spec.width, spec.height):
            raise AssertionError(
                f"Selected utility {utility.instance_id} footprint does not match its ModuleSpec"
            )
        anchor = (utility.x, utility.y)
        if anchor in seen_anchors:
            raise AssertionError(f"Duplicate selected utility anchor at {anchor}")
        seen_anchors.add(anchor)
        if not utility.cells <= base.buildable_cells:
            raise AssertionError(f"Selected utility lies outside buildable Base cells: {anchor}")
        if utility.cells & room_cells:
            raise AssertionError(f"Selected utility overlaps a room at {anchor}")
        overlap = utility.cells & utility_cells
        if overlap:
            raise AssertionError(
                f"Selected utility modules overlap at cells {sorted(overlap)}; anchor={anchor}"
            )
        utility_cells.update(utility.cells)


def _mass_metrics(
    base: BaseGeometry,
    rooms: list[ModulePlacement],
    utilities: list[ModulePlacement],
) -> tuple[int, int, int, int, bool, dict[str, int]]:
    room_mass = sum(MODULE_BY_KEY[room.module_key].mass for room in rooms)
    utility_mass = sum(MODULE_BY_KEY[utility.module_key].mass for utility in utilities)
    total_mass = room_mass + utility_mass
    margin = base.organics_capacity - total_mass

    counts = Counter(module.module_key for module in (*rooms, *utilities))
    mass_breakdown = {
        key: count * MODULE_BY_KEY[key].mass for key, count in sorted(counts.items())
    }
    return room_mass, utility_mass, total_mass, margin, margin >= 0, mass_breakdown


def _candidate_rank(result: PlanResult) -> tuple[int, int, int, int]:
    if result.scaled_objective_value is None:
        raise AssertionError("Cannot rank a candidate without an exact scaled objective value")
    return (
        result.scaled_objective_value,
        result.total_mass,
        result.elevator_module_count,
        result.corridor_count,
    )


def _add_identical_instance_symmetry_breaking(
    model: cp_model.CpModel,
    instances: list[ModuleInstance],
    vars_by_instance: dict[str, list[cp_model.IntVar]],
) -> None:
    """Remove pure label permutations between identical module instances."""

    groups: dict[str, list[ModuleInstance]] = {}
    for instance in instances:
        groups.setdefault(instance.spec.key, []).append(instance)

    for group in groups.values():
        if len(group) < 2:
            continue
        for left, right in zip(group, group[1:], strict=False):
            left_vars = vars_by_instance[left.instance_id]
            right_vars = vars_by_instance[right.instance_id]
            if len(left_vars) != len(right_vars):
                raise AssertionError("Identical module instances must have identical candidates")
            left_rank = sum(index * var for index, var in enumerate(left_vars))
            right_rank = sum(index * var for index, var in enumerate(right_vars))
            model.add(left_rank < right_rank)


def _configure_room_master_ordering(
    model: cp_model.CpModel,
    candidate_order_terms: list[cp_model.LinearExpr],
    mode: _RoomMasterMode,
) -> None:
    """Choose only the master enumeration order; never alter its feasible packing set."""

    if mode is _RoomMasterMode.HEURISTIC_OBJECTIVE:
        model.minimize(sum(candidate_order_terms))
    elif mode not in {
        _RoomMasterMode.FEASIBILITY_ENUMERATION,
        _RoomMasterMode.HEURISTIC_COST_BANDS,
    }:
        raise ValueError("Unsupported room-master mode")


def _compile_room_master(
    instances: list[ModuleInstance],
    candidates: dict[str, list[_Candidate]],
    *,
    minimize_search_cost: bool,
    natural_cost_floor: int,
    cost_floor: int | None = None,
    exact_cost: int | None = None,
) -> _CompiledRoomMaster:
    """Build the canonical room-packing domain with an optional exact cost restriction."""

    if cost_floor is not None and exact_cost is not None:
        raise ValueError("A room master cannot have both a cost floor and an exact cost band")
    model = cp_model.CpModel()
    vars_by_instance: dict[str, list[cp_model.IntVar]] = {}
    cell_vars: dict[tuple[int, int], list[cp_model.IntVar]] = {}
    search_cost_terms: list[cp_model.LinearExpr] = []

    for instance in instances:
        candidate_list = candidates[instance.instance_id]
        variables = [
            model.new_bool_var(f"p_{instance.instance_id}_{idx}")
            for idx in range(len(candidate_list))
        ]
        vars_by_instance[instance.instance_id] = variables
        model.add_exactly_one(variables)
        for var, position in zip(variables, candidate_list, strict=True):
            for cell in position.cells:
                cell_vars.setdefault(cell, []).append(var)
            search_cost_terms.append(position.search_cost * var)

    for variables in cell_vars.values():
        model.add_at_most_one(variables)
    _add_identical_instance_symmetry_breaking(model, instances, vars_by_instance)

    search_cost_expr = cp_model.LinearExpr.sum(search_cost_terms)
    if exact_cost is not None:
        model.add(search_cost_expr == exact_cost)
    elif cost_floor is not None and cost_floor > natural_cost_floor:
        model.add(search_cost_expr >= cost_floor)
    if minimize_search_cost:
        model.minimize(search_cost_expr)

    validation_error = model.validate()
    if validation_error:
        raise RuntimeError(f"Invalid generated CP-SAT placement model: {validation_error}")
    return _CompiledRoomMaster(model, vars_by_instance, search_cost_expr)


def _solve_room_master(
    solver: cp_model.CpSolver,
    model: cp_model.CpModel,
    *,
    remaining_s: float,
) -> tuple[cp_model.CpSolverStatus, float]:
    solver.parameters.max_time_in_seconds = max(0.001, remaining_s)
    solve_started = monotonic()
    status = solver.solve(model)
    return status, max(0.0, monotonic() - solve_started)


def _finalize_search_diagnostics(
    result: PlanResult,
    *,
    attempts: int,
    connected_candidates: int,
    fixed_objective_optima_proven: int,
    manhattan_pruned: int,
    incumbent_bound_pruned: int,
    room_master_diagnostics: _RoomMasterDiagnostics,
    fixed_diagnostics: _FixedDiagnosticsAggregate,
    started_at: float,
    time_limit_reached: bool,
    search_exhausted: bool,
) -> None:
    result.attempts = attempts
    result.connected_candidates_examined = connected_candidates
    result.fixed_objective_optima_proven = fixed_objective_optima_proven
    result.manhattan_pruned_count = manhattan_pruned
    result.incumbent_bound_pruned_count = incumbent_bound_pruned
    result.search_time_s = monotonic() - started_at
    result.time_limit_reached = time_limit_reached
    result.search_exhausted = search_exhausted
    room_master_diagnostics.apply(result)
    fixed_diagnostics.apply(result)


def _validate_master_instances(
    instances: list[ModuleInstance],
    *,
    root_instance_id: str,
) -> None:
    if not instances:
        raise ValueError("Exact decomposition requires at least one non-SOLVER module instance")
    instance_ids = [instance.instance_id for instance in instances]
    if len(instance_ids) != len(set(instance_ids)):
        raise ValueError("Module instance IDs must be unique")
    if any(instance.spec.authority is PlacementAuthority.SOLVER for instance in instances):
        raise ValueError("SOLVER modules must not be supplied to the room-packing master")
    root = next((instance for instance in instances if instance.instance_id == root_instance_id), None)
    if root is None or root.spec.key != "airlock":
        raise ValueError("Exact decomposition root instance must identify the Airlock")
    if sum(instance.spec.key == "airlock" for instance in instances) != 1:
        raise ValueError("Exact decomposition requires exactly one Airlock instance")


def _solve_instances(
    base: BaseGeometry,
    instances: list[ModuleInstance],
    *,
    time_limit_s: float,
    max_layout_attempts: int,
    root_instance_id: str = "airlock-1",
    started_at: float | None = None,
    usage_weights: Mapping[str, float] | None = None,
    room_master_mode: _RoomMasterMode = _RoomMasterMode.HEURISTIC_OBJECTIVE,
    room_packing_trace: list[_RoomPackingTrace] | None = None,
) -> PlanResult:
    """Exact objective decomposition over a supplied non-SOLVER instance set.

    This internal entry point is also used by tiny known-optimum tests. Production `solve_plan()`
    supplies the canonical SYSTEM/PLAYER instance set produced by `expand_instances()`.
    """

    _validate_master_instances(instances, root_instance_id=root_instance_id)
    if time_limit_s <= 0:
        raise ValueError("time_limit_s must be positive")
    if max_layout_attempts <= 0:
        raise ValueError("max_layout_attempts must be positive")
    if not isinstance(room_master_mode, _RoomMasterMode):
        raise ValueError("room_master_mode must be a _RoomMasterMode")

    started_at = monotonic() if started_at is None else started_at
    effective_usage_weights = (
        resolve_usage_weights() if usage_weights is None else usage_weights
    )
    room_master_diagnostics = _RoomMasterDiagnostics(room_master_mode)
    fixed_diagnostics = _FixedDiagnosticsAggregate()
    deadline = started_at + float(time_limit_s)
    candidates: dict[str, list[_Candidate]] = {}

    for instance in instances:
        candidate_list = _candidate_positions(instance, base, effective_usage_weights)
        if not candidate_list:
            result = PlanResult(
                status="INFEASIBLE",
                base=base,
                message=f"No legal position for {instance.spec.name}",
            )
            _finalize_search_diagnostics(
                result,
                attempts=0,
                connected_candidates=0,
                fixed_objective_optima_proven=0,
                manhattan_pruned=0,
                incumbent_bound_pruned=0,
                room_master_diagnostics=room_master_diagnostics,
                fixed_diagnostics=fixed_diagnostics,
                started_at=started_at,
                time_limit_reached=False,
                search_exhausted=True,
            )
            return result
        candidates[instance.instance_id] = candidate_list

    natural_cost_floor = sum(
        min(candidate.search_cost for candidate in candidates[instance.instance_id])
        for instance in instances
    )

    def build_master(
        *,
        minimize_search_cost: bool,
        cost_floor: int | None = None,
        exact_cost: int | None = None,
    ) -> tuple[_CompiledRoomMaster, cp_model.CpSolver]:
        build_started = monotonic()
        compiled_master = _compile_room_master(
            instances,
            candidates,
            minimize_search_cost=minimize_search_cost,
            natural_cost_floor=natural_cost_floor,
            cost_floor=cost_floor,
            exact_cost=exact_cost,
        )
        room_master_diagnostics.observe_model_build(max(0.0, monotonic() - build_started))
        master_solver = cp_model.CpSolver()
        master_solver.parameters.num_search_workers = 8
        return compiled_master, master_solver

    cost_band_mode = room_master_mode is _RoomMasterMode.HEURISTIC_COST_BANDS
    master_phase = "cost_discovery" if cost_band_mode else "standard"
    compiled, solver = build_master(
        minimize_search_cost=room_master_mode
        in {_RoomMasterMode.HEURISTIC_OBJECTIVE, _RoomMasterMode.HEURISTIC_COST_BANDS},
        cost_floor=natural_cost_floor if cost_band_mode else None,
    )
    current_band_cost: int | None = None
    current_band_size = 0
    emitted_cost_band_packings: set[tuple[int, ...]] = set()

    best_result: PlanResult | None = None
    common_objective: ScaledObjective | None = None
    connected_candidates = 0
    fixed_objective_optima_proven = 0
    manhattan_pruned = 0
    incumbent_bound_pruned = 0
    room_packings_examined = 0
    time_to_first_feasible_s: float | None = None
    time_limit_reached = False
    search_exhausted = False
    attempt_limit_reached = False
    all_fixed_objectives_resolved = True

    def advance_after_packing(
        selected_indices: tuple[int, ...],
        selected_search_cost: int,
        status: cp_model.CpSolverStatus,
    ) -> bool:
        nonlocal compiled, solver, master_phase, current_band_cost, current_band_size
        if not cost_band_mode or master_phase == "band_enumeration":
            selected_vars = [
                compiled.vars_by_instance[instance.instance_id][index]
                for instance, index in zip(instances, selected_indices, strict=True)
            ]
            compiled.model.add(sum(selected_vars) <= len(selected_vars) - 1)
            return True
        if status != cp_model.OPTIMAL:
            return False

        current_band_cost = selected_search_cost
        current_band_size = 1
        master_phase = "band_enumeration"
        compiled, solver = build_master(
            minimize_search_cost=False,
            exact_cost=selected_search_cost,
        )
        discovery_vars = [
            compiled.vars_by_instance[instance.instance_id][index]
            for instance, index in zip(instances, selected_indices, strict=True)
        ]
        compiled.model.add(sum(discovery_vars) <= len(discovery_vars) - 1)
        return True

    while room_packings_examined < max_layout_attempts:
        remaining = deadline - monotonic()
        if remaining <= 0:
            time_limit_reached = True
            all_fixed_objectives_resolved = False
            break

        status, master_solve_time_s = _solve_room_master(
            solver,
            compiled.model,
            remaining_s=remaining,
        )
        room_master_diagnostics.observe(status, master_solve_time_s, phase=master_phase)

        if status == cp_model.MODEL_INVALID:
            raise RuntimeError("CP-SAT rejected the generated placement model as invalid")
        if status == cp_model.UNKNOWN:
            time_limit_reached = True
            all_fixed_objectives_resolved = False
            break
        if status == cp_model.INFEASIBLE:
            if cost_band_mode and master_phase == "band_enumeration":
                if current_band_cost is None:
                    raise AssertionError("Room-master band enumeration has no exact cost")
                room_master_diagnostics.complete_band(current_band_size)
                next_cost_floor = current_band_cost + 1
                master_phase = "cost_discovery"
                current_band_cost = None
                current_band_size = 0
                compiled, solver = build_master(
                    minimize_search_cost=True,
                    cost_floor=next_cost_floor,
                )
                continue
            search_exhausted = True
            break
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise RuntimeError(f"Unexpected CP-SAT status: {status}")

        room_packings_examined += 1
        rooms: list[ModulePlacement] = []
        selected_indices: list[int] = []
        selected_search_cost = 0
        for instance in instances:
            for idx, var in enumerate(compiled.vars_by_instance[instance.instance_id]):
                if solver.value(var):
                    position = candidates[instance.instance_id][idx]
                    selected_search_cost += position.search_cost
                    rooms.append(
                        ModulePlacement(
                            instance_id=instance.instance_id,
                            module_key=instance.spec.key,
                            x=position.x,
                            y=position.y,
                            width=instance.spec.width,
                            height=instance.spec.height,
                        )
                    )
                    selected_indices.append(idx)
                    break

        if len(selected_indices) != len(instances):
            raise AssertionError("CP-SAT solution did not select exactly one placement per module")
        selected_indices_tuple = tuple(selected_indices)
        if cost_band_mode:
            if selected_indices_tuple in emitted_cost_band_packings:
                raise AssertionError("Cost-band room master emitted a duplicate room packing")
            emitted_cost_band_packings.add(selected_indices_tuple)
            if master_phase == "cost_discovery" and status == cp_model.OPTIMAL:
                room_master_diagnostics.start_band()
            elif master_phase == "band_enumeration":
                if selected_search_cost != current_band_cost:
                    raise AssertionError(
                        "Room-master band enumeration emitted a packing outside its exact cost"
                    )
                current_band_size += 1
                room_master_diagnostics.same_cost_packings_examined += 1
        objective_bearing_solve = (
            room_master_mode is _RoomMasterMode.HEURISTIC_OBJECTIVE
            or (cost_band_mode and master_phase == "cost_discovery")
        )
        if status == cp_model.OPTIMAL and objective_bearing_solve:
            rounded_objective = round(solver.objective_value)
            if selected_search_cost != rounded_objective:
                raise AssertionError(
                    "Room-master objective disagrees with exact selected search cost: "
                    f"selected={selected_search_cost}, objective={solver.objective_value}"
                )
        trace_entry = _RoomPackingTrace(
            selected_search_cost=selected_search_cost,
            master_solve_time_s=master_solve_time_s,
            master_status=status.name,
            master_phase=master_phase,
        )
        if room_packing_trace is not None:
            room_packing_trace.append(trace_entry)

        objective = build_scaled_objective(rooms, effective_usage_weights)
        if common_objective is None:
            common_objective = objective
        elif objective != common_objective:
            raise AssertionError(
                "Objective coefficients changed across room packings for one planning request"
            )

        scaled_lower_bound = scaled_modified_manhattan_lower_bound(
            rooms,
            objective,
            effective_usage_weights,
        )
        incumbent_scaled: int | None = None
        if best_result is not None:
            incumbent_scaled = best_result.scaled_objective_value
            if incumbent_scaled is None:
                raise AssertionError("Incumbent is missing its exact scaled objective")
            if scaled_lower_bound > incumbent_scaled:
                manhattan_pruned += 1
                trace_entry.fixed_subproblem_status = "MANHATTAN_PRUNED"
                if not advance_after_packing(
                    selected_indices_tuple, selected_search_cost, status
                ):
                    time_limit_reached = True
                    all_fixed_objectives_resolved = False
                    break
                continue

        remaining = deadline - monotonic()
        if remaining <= 0:
            time_limit_reached = True
            all_fixed_objectives_resolved = False
            trace_entry.fixed_subproblem_status = "NOT_RUN_DEADLINE"
            break

        if usage_weights is None:
            fixed_result = solve_fixed_layout_flow_objective(
                base,
                tuple(rooms),
                time_limit_s=remaining,
                root_instance_id=root_instance_id,
                scaled_objective_upper_bound=incumbent_scaled,
            )
        else:
            fixed_result = solve_fixed_layout_flow_objective(
                base,
                tuple(rooms),
                time_limit_s=remaining,
                root_instance_id=root_instance_id,
                scaled_objective_upper_bound=incumbent_scaled,
                usage_weights=effective_usage_weights,
            )
        fixed_diagnostics.observe(fixed_result.diagnostics)
        trace_entry.fixed_subproblem_status = fixed_result.status
        trace_entry.fixed_subproblem_time_s = fixed_result.diagnostics.total_time_s
        if fixed_result.status == "TIME_LIMIT":
            time_limit_reached = True
            all_fixed_objectives_resolved = False
            break
        if fixed_result.status == "INFEASIBLE":
            if incumbent_scaled is not None:
                raise AssertionError(
                    "Bounded fixed subproblem reported unqualified INFEASIBLE status"
                )
            if not advance_after_packing(
                selected_indices_tuple, selected_search_cost, status
            ):
                time_limit_reached = True
                all_fixed_objectives_resolved = False
                break
            continue
        if fixed_result.status == "OBJECTIVE_BOUND_INFEASIBLE":
            if incumbent_scaled is None:
                raise AssertionError(
                    "Unbounded fixed subproblem reported objective-bound infeasibility"
                )
            incumbent_bound_pruned += 1
            if not advance_after_packing(
                selected_indices_tuple, selected_search_cost, status
            ):
                time_limit_reached = True
                all_fixed_objectives_resolved = False
                break
            continue
        if fixed_result.status not in {"OPTIMAL", "FEASIBLE"}:
            raise AssertionError(f"Unexpected fixed objective status: {fixed_result.status}")
        if fixed_result.distance_metrics is None:
            raise AssertionError("Fixed objective solver returned a candidate without distances")
        if fixed_result.objective_scale != objective.scale:
            raise AssertionError(
                "Fixed objective solver and master use different exact objective scales"
            )

        utilities = list(fixed_result.utilities)
        _validate_utility_geometry(base, rooms, utilities)
        distance_metrics = fixed_result.distance_metrics
        exact_scaled_score = objective.scaled_score(distance_metrics.pairwise_distances)
        if scaled_lower_bound > exact_scaled_score:
            raise AssertionError(
                "Exact objective fell below the scaled modified-Manhattan lower bound: "
                f"exact={exact_scaled_score}, lower_bound={scaled_lower_bound}"
            )

        if fixed_result.scaled_objective_value is not None:
            if fixed_result.scaled_objective_value != exact_scaled_score:
                raise AssertionError(
                    "Fixed objective solver scaled score disagrees with exact Dijkstra distances"
                )

        fixed_proven = (
            fixed_result.status == "OPTIMAL" and fixed_result.lexicographic_optimum_proven
        )
        if fixed_result.status == "OPTIMAL" and not fixed_proven:
            raise AssertionError("OPTIMAL fixed objective result lacks lexicographic proof")
        if fixed_proven:
            fixed_objective_optima_proven += 1
        else:
            all_fixed_objectives_resolved = False

        exact_score = objective.unscaled_score(exact_scaled_score)
        exact_lower_bound = objective.unscaled_score(scaled_lower_bound)
        if abs(exact_score - distance_metrics.weighted_score) > 1e-9:
            raise AssertionError(
                "Scaled objective disagrees with floating evaluator score: "
                f"scaled={exact_score}, evaluator={distance_metrics.weighted_score}"
            )
        if abs(exact_lower_bound - distance_metrics.weighted_manhattan_lower_bound) > 1e-9:
            raise AssertionError(
                "Scaled lower bound disagrees with evaluator lower bound: "
                f"scaled={exact_lower_bound}, "
                f"evaluator={distance_metrics.weighted_manhattan_lower_bound}"
            )

        connected_candidates += 1
        trace_entry.connected_candidate = True
        if time_to_first_feasible_s is None:
            time_to_first_feasible_s = monotonic() - started_at
        room_mass, utility_mass, total_mass, margin, travel_ok, breakdown = _mass_metrics(
            base, rooms, utilities
        )
        room_usage_weights = {
            room.instance_id: effective_usage_weights[room.module_key] for room in rooms
        }
        fixed_status = "proven fixed-packing optimum" if fixed_proven else "best-known fixed packing"
        message = (
            f"Exact-objective connected candidate ({fixed_status}). Objective {exact_score:.4f}; "
            f"scaled objective {exact_scaled_score}/{objective.scale}; modified-Manhattan lower "
            f"bound {exact_lower_bound:.4f}; Elevator modules "
            f"{distance_metrics.elevator_module_count}; Corridors {distance_metrics.corridor_count}; "
            f"Base Mass {total_mass}; journey requires {total_mass} Organics; tank capacity "
            f"{base.organics_capacity}. Travel at full tank: {'YES' if travel_ok else 'NO'}."
        )
        candidate_result = PlanResult(
            status="FEASIBLE",
            base=base,
            modules=[*rooms, *utilities],
            objective_value=exact_score,
            objective_scale=objective.scale,
            scaled_objective_value=exact_scaled_score,
            scaled_modified_manhattan_lower_bound=scaled_lower_bound,
            attempts=room_packings_examined,
            message=message,
            room_mass=room_mass,
            utility_mass=utility_mass,
            total_mass=total_mass,
            organics_required_for_journey=total_mass,
            organics_capacity_margin=margin,
            travel_feasible_at_full_tank=travel_ok,
            mass_breakdown=breakdown,
            elevator_module_count=distance_metrics.elevator_module_count,
            elevator_shaft_count=distance_metrics.elevator_shaft_count,
            corridor_count=distance_metrics.corridor_count,
            weighted_distance_score=exact_score,
            normalized_weighted_distance=distance_metrics.normalized_weighted_distance,
            modified_manhattan_lower_bound=exact_lower_bound,
            pairwise_distances=distance_metrics.pairwise_distances,
            pairwise_contributions=distance_metrics.pairwise_contributions,
            room_usage_weights=room_usage_weights,
            time_to_first_feasible_s=time_to_first_feasible_s,
            global_objective_optimum_proven=False,
        )
        if best_result is None or _candidate_rank(candidate_result) < _candidate_rank(best_result):
            best_result = candidate_result

        if fixed_result.time_limit_reached or not fixed_proven:
            time_limit_reached = True
            break
        if not advance_after_packing(selected_indices_tuple, selected_search_cost, status):
            time_limit_reached = True
            all_fixed_objectives_resolved = False
            break
    else:
        attempt_limit_reached = True
        all_fixed_objectives_resolved = False

    if monotonic() >= deadline and not search_exhausted:
        time_limit_reached = True
        all_fixed_objectives_resolved = False

    global_optimum_proven = bool(
        best_result is not None
        and search_exhausted
        and all_fixed_objectives_resolved
        and not time_limit_reached
        and not attempt_limit_reached
    )

    if best_result is not None:
        best_result.global_objective_optimum_proven = global_optimum_proven
        _finalize_search_diagnostics(
            best_result,
            attempts=room_packings_examined,
            connected_candidates=connected_candidates,
            fixed_objective_optima_proven=fixed_objective_optima_proven,
            manhattan_pruned=manhattan_pruned,
            incumbent_bound_pruned=incumbent_bound_pruned,
            room_master_diagnostics=room_master_diagnostics,
            fixed_diagnostics=fixed_diagnostics,
            started_at=started_at,
            time_limit_reached=time_limit_reached,
            search_exhausted=search_exhausted,
        )
        if search_exhausted:
            stop_reason = "room-packing search exhausted"
        elif time_limit_reached:
            stop_reason = f"global {time_limit_s:g}s search budget reached"
        elif attempt_limit_reached:
            stop_reason = f"{max_layout_attempts} layout-attempt limit reached"
        else:
            stop_reason = "search stopped"

        proof_text = (
            "Global exact lexicographic optimum PROVEN: every physical room packing was either "
            "solved to its exact fixed-packing objective optimum, proven infrastructure-"
            "infeasible, excluded by a strict exact integer admissible lower bound, or proven "
            "unable to match the incumbent by the exact bounded fixed subproblem."
            if global_optimum_proven
            else "Global objective optimality is not proven for this run."
        )
        best_result.message += (
            f" Best objective among {connected_candidates} connected candidates examined from "
            f"{room_packings_examined} unique room packings; {fixed_objective_optima_proven} "
            f"fixed-packing lexicographic optima proven; {manhattan_pruned} additional packings "
            "pruned by the strict exact-integer modified-Manhattan lower bound; "
            f"{incumbent_bound_pruned} packings excluded by the exact incumbent objective cut; "
            f"{stop_reason}. Identical-module label permutations are symmetry-broken. "
            f"{proof_text}"
        )
        return best_result

    if time_limit_reached:
        result = PlanResult(
            status="TIME_LIMIT",
            base=base,
            attempts=room_packings_examined,
            message=(
                f"No connected layout was found within the global {time_limit_s:g}s search "
                f"budget after examining {room_packings_examined} unique room packings."
            ),
        )
    elif search_exhausted and room_packings_examined == 0:
        result = PlanResult(
            status="INFEASIBLE",
            base=base,
            message="No feasible SYSTEM/PLAYER module packing exists for the selected Base",
        )
    else:
        reason = (
            "the complete exact room-packing search was exhausted"
            if search_exhausted
            else f"the {max_layout_attempts} layout-attempt limit was reached"
        )
        result = PlanResult(
            status="NO_CONNECTED_LAYOUT",
            base=base,
            attempts=room_packings_examined,
            message=(
                "SYSTEM/PLAYER module packings were physically feasible, but no connected "
                "Corridor/Elevator layout exists among the exactly resolved packings before "
                f"{reason}."
            ),
        )

    _finalize_search_diagnostics(
        result,
        attempts=room_packings_examined,
        connected_candidates=connected_candidates,
        fixed_objective_optima_proven=fixed_objective_optima_proven,
        manhattan_pruned=manhattan_pruned,
        incumbent_bound_pruned=incumbent_bound_pruned,
        room_master_diagnostics=room_master_diagnostics,
        fixed_diagnostics=fixed_diagnostics,
        started_at=started_at,
        time_limit_reached=time_limit_reached,
        search_exhausted=search_exhausted,
    )
    return result


def _solve_plan_with_room_master_mode(
    request: PlanRequest,
    base: BaseGeometry | None = None,
    *,
    room_master_mode: _RoomMasterMode,
    room_packing_trace: list[_RoomPackingTrace] | None = None,
) -> PlanResult:
    """Internal benchmark seam for comparing exact room-master enumeration modes."""

    started_at = monotonic()
    if base is not None and base.tier != request.tier:
        raise ValueError(
            f"PlanRequest tier {request.tier} does not match supplied BaseGeometry tier {base.tier}"
        )
    base = base or builtin_base(request.tier)
    instances = expand_instances(MODULES, request.room_counts)
    effective_usage_weights = resolve_usage_weights(request.usage_weights)
    return _solve_instances(
        base,
        instances,
        time_limit_s=float(request.time_limit_s),
        max_layout_attempts=request.max_layout_attempts,
        started_at=started_at,
        usage_weights=effective_usage_weights,
        room_master_mode=room_master_mode,
        room_packing_trace=room_packing_trace,
    )


def solve_plan(request: PlanRequest, base: BaseGeometry | None = None) -> PlanResult:
    """Optimize the Base with an exact room-packing / fixed-objective decomposition.

    Stage 3 production search now uses:

    1. a CP-SAT master that enumerates legal SYSTEM/PLAYER room packings;
    2. the exact source-aggregated flow CP-SAT subproblem that jointly selects Corridor/Elevator
       infrastructure and proves the accepted fixed-packing lexicographic objective;
    3. exact integer modified-Manhattan lower bounds to prune only when a packing cannot match
       the incumbent primary objective;
    4. the current exact scaled incumbent as an equality-preserving fixed-subproblem upper bound;
    5. exact integer objective ranking across fixed-packing optima.

    A run reports `global_objective_optimum_proven=True` only after the master is exhausted and
    every relevant fixed packing has been solved exactly, proven infrastructure-infeasible or
    excluded by an exact proof-safe bound. Time or layout-attempt limits therefore preserve
    best-known semantics rather than creating a false global proof.
    """

    return _solve_plan_with_room_master_mode(
        request,
        base,
        room_master_mode=_RoomMasterMode.HEURISTIC_OBJECTIVE,
    )
