from __future__ import annotations

from .catalog import MODULE_BY_KEY
from .models import ModulePlacement, PlacementAuthority, PlanResult, resolve_ports

RESULT_SCHEMA_VERSION = 3


def average_pair_distance(result: PlanResult) -> float:
    """Arithmetic mean of all positive-weight unordered endpoint-room distances."""

    values = list(result.pairwise_distances.values())
    return sum(values) / len(values) if values else 0.0


def _placed_module_payload(
    module: ModulePlacement,
    room_usage_weights: dict[str, float],
) -> dict[str, object]:
    spec = MODULE_BY_KEY[module.module_key]
    if spec.authority is PlacementAuthority.SOLVER:
        usage_weight = 0.0
    else:
        try:
            usage_weight = room_usage_weights[module.instance_id]
        except KeyError as exc:
            raise ValueError(
                f"Missing effective usage weight for {module.instance_id}"
            ) from exc
    return {
        "instance_id": module.instance_id,
        "module_key": module.module_key,
        "name": spec.name,
        "module_type": spec.module_type.value,
        "placement_authority": spec.authority.value,
        "mass": spec.mass,
        "usage_weight": usage_weight,
        "transit_allowed": spec.transit_allowed,
        "vertical_connectivity": spec.vertical_connectivity,
        "x": module.x,
        "y": module.y,
        "width": module.width,
        "height": module.height,
        "ports": [
            {
                "name": port.name,
                "side": port.side.value,
                "cell": [port.cell_x, port.cell_y],
                "edge": [port.edge_x, port.edge_y],
                "utility_anchor": list(port.utility_anchor),
            }
            for port in resolve_ports(module, spec)
        ],
    }


def result_payload(result: PlanResult) -> dict[str, object]:
    """Serialize one PlanResult into the canonical auditable JSON contract."""

    structural_feasible = result.status == "FEASIBLE"
    journey_feasible = structural_feasible and result.travel_feasible_at_full_tank
    authority_counts = {authority.value: 0 for authority in PlacementAuthority}
    for module in result.modules:
        authority_counts[MODULE_BY_KEY[module.module_key].authority.value] += 1

    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": result.status,
        "message": result.message,
        "base": {
            "tier": result.base.tier,
            "width": result.base.width,
            "height": result.base.height,
            "organics_capacity": result.base.organics_capacity,
            "geometry_source": result.base.source,
            "geometry_verified": result.base.verified,
            "geometry_note": result.base.note,
        },
        "feasibility": {
            "structural_feasible": structural_feasible,
            "journey_feasible": journey_feasible,
        },
        "optimization": {
            "objective": "sum_i_lt_j(weight_i * weight_j * distance_i_j)",
            "objective_value": result.objective_value,
            "exact_integer_objective": {
                "scale": result.objective_scale,
                "scaled_value": result.scaled_objective_value,
                "scaled_modified_manhattan_lower_bound": (
                    result.scaled_modified_manhattan_lower_bound
                ),
            },
            "distance_rule": {
                "measurement": "shortest legal path in the module graph",
                "normal_room_ports": "extreme left/right cells on room floor",
                "direct_room_adjacency": 0,
                "corridor_module": 1,
                "elevator_module": 1,
                "endpoint_room_length": 0,
                "intermediate_transit_room_length": "room width in grid cells",
                "non_transit_room_bridge": "forbidden",
                "modified_manhattan": "admissible explicit-port lower bound used for pruning",
            },
            "weighted_distance_score": result.weighted_distance_score,
            "modified_manhattan_lower_bound": result.modified_manhattan_lower_bound,
            "average_pair_distance": average_pair_distance(result),
            "weighted_average_pair_distance": result.normalized_weighted_distance,
            "global_objective_optimum_proven": result.global_objective_optimum_proven,
            "search_diagnostics": {
                "connected_candidates_examined": result.connected_candidates_examined,
                "fixed_objective_optima_proven": result.fixed_objective_optima_proven,
                "room_packings_examined": result.attempts,
                "manhattan_pruned_count": result.manhattan_pruned_count,
                "incumbent_bound_pruned_count": result.incumbent_bound_pruned_count,
                "search_time_s": result.search_time_s,
                "time_limit_reached": result.time_limit_reached,
                "search_exhausted": result.search_exhausted,
                "fixed_subproblems": {
                    "count": result.fixed_subproblem_count,
                    "max_graph_nodes": result.max_fixed_graph_nodes,
                    "max_graph_arcs": result.max_fixed_graph_arcs,
                    "max_objective_pairs": result.max_fixed_objective_pairs,
                    "flow_formulation": result.fixed_flow_formulation,
                    "source_flow_domain": {
                        "max_commodities": result.max_fixed_source_commodities,
                        "max_actual_variables": result.max_fixed_source_flow_variables,
                        "max_full_domain_variables": (
                            result.max_fixed_source_flow_full_variables
                        ),
                        "total_actual_variables": result.total_fixed_source_flow_variables,
                        "total_full_domain_variables": (
                            result.total_fixed_source_flow_full_variables
                        ),
                        "max_shared_activation_gates": (
                            result.max_fixed_shared_activation_gates
                        ),
                        "max_endpoint_distribution_variables": (
                            result.max_fixed_endpoint_distribution_variables
                        ),
                        "max_capacity_constraints": (
                            result.max_fixed_flow_capacity_constraints
                        ),
                        "max_balance_constraints": (
                            result.max_fixed_flow_balance_constraints
                        ),
                    },
                    "max_cp_sat_variables": result.max_fixed_cp_sat_variables,
                    "max_cp_sat_constraints": result.max_fixed_cp_sat_constraints,
                    "lexicographic_scalarization": {
                        "used": result.fixed_lexicographic_scalarization_used,
                        "max_primary_objective_upper_bound": (
                            result.max_fixed_primary_objective_upper_bound
                        ),
                        "max_combined_objective_upper_bound": (
                            result.max_fixed_combined_objective_upper_bound
                        ),
                        "max_weight_f": result.max_fixed_lexicographic_weight_f,
                        "max_weight_mass": result.max_fixed_lexicographic_weight_mass,
                        "max_weight_elevator": result.max_fixed_lexicographic_weight_elevator,
                        "max_weight_corridor": result.max_fixed_lexicographic_weight_corridor,
                        "max_corridor_bound": result.max_fixed_lexicographic_corridor_bound,
                        "max_elevator_bound": result.max_fixed_lexicographic_elevator_bound,
                        "max_mass_bound": result.max_fixed_lexicographic_mass_bound,
                        "max_incumbent_scalar_value": (
                            result.max_fixed_incumbent_scalar_value
                        ),
                    },
                    "model_build_time_s": result.fixed_model_build_time_s,
                    "cp_sat_solve_time_s": result.fixed_cp_sat_solve_time_s,
                    "total_time_s": result.fixed_subproblem_time_s,
                    "build_phases": {
                        "hard_model_time_s": result.fixed_hard_model_build_time_s,
                        "path_graph_time_s": result.fixed_path_graph_build_time_s,
                        "objective_definition_time_s": (
                            result.fixed_objective_definition_time_s
                        ),
                        "source_flow_time_s": result.fixed_source_flow_model_build_time_s,
                        "lexicographic_finalize_time_s": (
                            result.fixed_lexicographic_finalize_time_s
                        ),
                        "total_model_build_time_s": result.fixed_model_build_time_s,
                    },
                },
            },
            "infrastructure": {
                "elevator_module_count": result.elevator_module_count,
                "elevator_shaft_count": result.elevator_shaft_count,
                "corridor_count": result.corridor_count,
            },
            "room_usage_weights": result.room_usage_weights,
            "pairwise_distances": result.pairwise_distances,
            "pairwise_contributions": result.pairwise_contributions,
        },
        "journey": {
            "room_mass": result.room_mass,
            "utility_mass": result.utility_mass,
            "total_base_mass": result.total_mass,
            "organics_required": result.organics_required_for_journey,
            "organics_tank_capacity": result.base.organics_capacity,
            "capacity_margin": result.organics_capacity_margin,
            "travel_feasible_at_full_tank": result.travel_feasible_at_full_tank,
            "mass_breakdown": result.mass_breakdown,
        },
        "module_counts_by_authority": authority_counts,
        "modules": [
            _placed_module_payload(module, result.room_usage_weights)
            for module in result.modules
        ],
    }
