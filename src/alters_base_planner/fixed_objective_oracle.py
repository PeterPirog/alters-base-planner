from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from time import monotonic

from ortools.sat.python import cp_model

from .catalog import MODULE_BY_KEY
from .distance import DistanceMetrics, evaluate_distances, weighted_modified_manhattan_lower_bound
from .integrated_hard_solver import compile_fixed_layout_hard_model, extract_integrated_solution
from .models import BaseGeometry, ModulePlacement, PlacementAuthority


@dataclass(frozen=True, slots=True)
class FixedObjectiveResult:
    """Exact-objective search result for one fixed SYSTEM/PLAYER room packing.

    This Stage-3 reference solver enumerates distinct hard-feasible Corridor/Elevator
    selections, evaluates the accepted exact graph objective for each selection and proves
    optimality only when the utility-selection domain is exhausted. It is intentionally a
    correctness oracle for small instances, not yet the production full-Base objective solver.
    """

    status: str
    utilities: tuple[ModulePlacement, ...] = ()
    distance_metrics: DistanceMetrics | None = None
    objective_lower_bound: float | None = None
    networks_examined: int = 0
    time_limit_reached: bool = False
    search_exhausted: bool = False
    objective_optimum_proven: bool = False


def _network_signature(utilities: tuple[ModulePlacement, ...]) -> tuple[tuple[str, int, int], ...]:
    return tuple(sorted((module.module_key, module.x, module.y) for module in utilities))


def _network_rank(
    rooms: tuple[ModulePlacement, ...],
    utilities: tuple[ModulePlacement, ...],
    metrics: DistanceMetrics,
) -> tuple[float, int, int, int]:
    total_mass = sum(MODULE_BY_KEY[module.module_key].mass for module in (*rooms, *utilities))
    return (
        metrics.weighted_score,
        total_mass,
        metrics.elevator_module_count,
        metrics.corridor_count,
    )


def _extract_utilities(
    solver: cp_model.CpSolver,
    compiled,
) -> tuple[ModulePlacement, ...]:
    return tuple(
        module
        for module in extract_integrated_solution(solver, compiled)
        if MODULE_BY_KEY[module.module_key].authority is PlacementAuthority.SOLVER
    )


def _exclude_utility_assignment(
    compiled,
    solver: cp_model.CpSolver,
) -> None:
    """Exclude exactly one Corridor/Elevator selection, independent of flow witnesses."""

    differs: list[cp_model.LiteralT] = []
    for variables in (compiled.variables.corridor, compiled.variables.elevator):
        for anchor in sorted(variables):
            variable = variables[anchor]
            differs.append(variable.Not() if solver.value(variable) else variable)

    if differs:
        compiled.model.add_bool_or(differs)
    else:
        compiled.model.add(0 == 1)


def solve_fixed_layout_objective(
    base: BaseGeometry,
    rooms: tuple[ModulePlacement, ...],
    *,
    time_limit_s: float,
    root_instance_id: str = "airlock-1",
    usage_weights: Mapping[str, float] | None = None,
) -> FixedObjectiveResult:
    """Enumerate hard-feasible utility networks and optimize exact ``F`` lexicographically.

    The primary score is the exact weighted pair-distance objective from ``evaluate_distances``.
    Equal primary scores are ordered by total Base mass, then Elevator count, then Corridor
    count, matching the normative project contract.

    ``objective_optimum_proven`` is true only after CP-SAT proves that no unexamined distinct
    Corridor/Elevator selection remains for this fixed room packing. Exhaustion therefore gives
    an exact fixed-packing objective proof; it is not a proof over alternative room packings.
    """

    if time_limit_s <= 0:
        return FixedObjectiveResult(status="TIME_LIMIT", time_limit_reached=True)

    compiled = compile_fixed_layout_hard_model(
        base,
        rooms,
        root_instance_id=root_instance_id,
    )
    lower_bound = weighted_modified_manhattan_lower_bound(list(rooms), usage_weights)
    deadline = monotonic() + float(time_limit_s)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 8

    best_utilities: tuple[ModulePlacement, ...] = ()
    best_metrics: DistanceMetrics | None = None
    best_rank: tuple[float, int, int, int] | None = None
    seen_networks: set[tuple[tuple[str, int, int], ...]] = set()
    networks_examined = 0

    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            status = "FEASIBLE" if best_metrics is not None else "TIME_LIMIT"
            return FixedObjectiveResult(
                status=status,
                utilities=best_utilities,
                distance_metrics=best_metrics,
                objective_lower_bound=lower_bound,
                networks_examined=networks_examined,
                time_limit_reached=True,
            )

        solver.parameters.max_time_in_seconds = max(0.001, remaining)
        status = solver.solve(compiled.model)

        if status == cp_model.MODEL_INVALID:
            raise AssertionError("CP-SAT rejected the fixed-layout objective model")
        if status == cp_model.UNKNOWN:
            result_status = "FEASIBLE" if best_metrics is not None else "TIME_LIMIT"
            return FixedObjectiveResult(
                status=result_status,
                utilities=best_utilities,
                distance_metrics=best_metrics,
                objective_lower_bound=lower_bound,
                networks_examined=networks_examined,
                time_limit_reached=True,
            )
        if status == cp_model.INFEASIBLE:
            if best_metrics is None:
                return FixedObjectiveResult(
                    status="INFEASIBLE",
                    objective_lower_bound=lower_bound,
                    networks_examined=networks_examined,
                    search_exhausted=True,
                )
            return FixedObjectiveResult(
                status="OPTIMAL",
                utilities=best_utilities,
                distance_metrics=best_metrics,
                objective_lower_bound=lower_bound,
                networks_examined=networks_examined,
                search_exhausted=True,
                objective_optimum_proven=True,
            )
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise AssertionError(f"Unexpected CP-SAT objective-oracle status: {status}")

        utilities = _extract_utilities(solver, compiled)
        signature = _network_signature(utilities)
        if signature in seen_networks:
            raise AssertionError("Objective oracle produced a duplicate utility selection")
        seen_networks.add(signature)

        try:
            metrics = evaluate_distances(list(rooms), list(utilities), usage_weights)
        except ValueError as exc:
            raise AssertionError(
                "Hard-feasible utility selection was rejected by the exact distance evaluator"
            ) from exc

        if metrics.weighted_score + 1e-12 < lower_bound:
            raise AssertionError(
                "Exact fixed-layout objective fell below the admissible modified-Manhattan "
                f"lower bound: exact={metrics.weighted_score}, lower_bound={lower_bound}"
            )

        networks_examined += 1
        rank = _network_rank(rooms, utilities, metrics)
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best_utilities = utilities
            best_metrics = metrics

        _exclude_utility_assignment(compiled, solver)

        if status == cp_model.FEASIBLE:
            return FixedObjectiveResult(
                status="FEASIBLE",
                utilities=best_utilities,
                distance_metrics=best_metrics,
                objective_lower_bound=lower_bound,
                networks_examined=networks_examined,
                time_limit_reached=True,
            )
