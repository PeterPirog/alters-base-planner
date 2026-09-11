from __future__ import annotations

from .catalog import MODULE_BY_KEY
from .models import ModulePlacement, PlanResult, resolve_ports


def average_pair_distance(result: PlanResult) -> float:
    """Arithmetic mean of all positive-weight unordered endpoint-room distances."""

    values = list(result.pairwise_distances.values())
    return sum(values) / len(values) if values else 0.0


def _placed_module_payload(module: ModulePlacement) -> dict[str, object]:
    spec = MODULE_BY_KEY[module.module_key]
    payload: dict[str, object] = {
        "instance_id": module.instance_id,
        "module_key": module.module_key,
        "placement_authority": spec.authority.value,
        "mass": spec.mass,
        "usage_weight": spec.visit_weight,
        "x": module.x,
        "y": module.y,
        "width": module.width,
        "height": module.height,
    }

    if spec.authority.value == "solver":
        # Keep `kind` for compatibility with pre-Stage-1 JSON consumers while making
        # module_key/placement_authority the canonical domain fields.
        payload["kind"] = module.module_key
        payload["distance_cost"] = 1
    else:
        payload["ports"] = [
            {
                "name": port.name,
                "side": port.side.value,
                "cell": [port.cell_x, port.cell_y],
                "edge": [port.edge_x, port.edge_y],
                "utility_anchor": list(port.utility_anchor),
            }
            for port in resolve_ports(module, spec)
        ]
    return payload


def result_payload(result: PlanResult) -> dict[str, object]:
    """Serialize one PlanResult into the single auditable CLI/UI JSON contract."""

    return {
        "status": result.status,
        "attempts": result.attempts,
        "message": result.message,
        "objective_value": result.objective_value,
        "base": {
            "tier": result.base.tier,
            "width": result.base.width,
            "height": result.base.height,
            "organics_capacity": result.base.organics_capacity,
            "geometry_source": result.base.source,
            "geometry_verified": result.base.verified,
            "geometry_note": result.base.note,
        },
        "optimization": {
            "objective": "sum_i_lt_j(weight_i * weight_j * distance_i_j)",
            "distance_rule": {
                "measurement": "explicit room port to explicit room port",
                "normal_room_ports": "extreme left/right cells on room floor",
                "direct_room_adjacency": 0,
                "corridor_module": 1,
                "elevator_module": 1,
                "endpoint_room_length": 0,
                "intermediate_room_length": "room width in grid cells",
                "modified_manhattan": "admissible explicit-port lower bound used for pruning",
            },
            "weighted_distance_score": result.weighted_distance_score,
            "modified_manhattan_lower_bound": result.modified_manhattan_lower_bound,
            "average_pair_distance": average_pair_distance(result),
            "weighted_average_pair_distance": result.normalized_weighted_distance,
            "global_objective_optimum_proven": result.global_objective_optimum_proven,
            "connected_candidates_examined": result.connected_candidates_examined,
            "room_packings_examined": result.attempts,
            "manhattan_pruned_count": result.manhattan_pruned_count,
            "search_time_s": result.search_time_s,
            "time_limit_reached": result.time_limit_reached,
            "search_exhausted": result.search_exhausted,
            "elevator_module_count": result.elevator_module_count,
            "elevator_shaft_count": result.elevator_shaft_count,
            "corridor_count": result.corridor_count,
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
        # These two arrays are retained for a stable user-facing result shape. Internally both
        # contain the same ModulePlacement type and differ only by placement authority.
        "rooms": [_placed_module_payload(room) for room in result.rooms],
        "utilities": [_placed_module_payload(utility) for utility in result.utilities],
    }
