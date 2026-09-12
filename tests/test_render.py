from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.models import BaseGeometry, ModulePlacement, PlanResult
from alters_base_planner.render import render_png, render_svg
from alters_base_planner.serialization import average_pair_distance, result_payload


def _module(module_key: str, instance_id: str, x: int, y: int) -> ModulePlacement:
    spec = MODULE_BY_KEY[module_key]
    return ModulePlacement(instance_id, module_key, x, y, spec.width, spec.height)


def _sample_result() -> PlanResult:
    base = BaseGeometry(
        tier=1,
        width=10,
        height=3,
        allowed_cells=frozenset((x, y) for x in range(10) for y in range(3)),
        blocked_cells=frozenset({(8, 1), (9, 1)}),
        organics_capacity=300,
    )
    return PlanResult(
        status="FEASIBLE",
        base=base,
        modules=[
            _module("airlock", "airlock-1", 0, 0),
            _module("workshop", "workshop-1", 6, 0),
            _module("corridor", "corridor-1", 4, 0),
        ],
        objective_value=0.9,
        objective_scale=10,
        scaled_objective_value=9,
        scaled_modified_manhattan_lower_bound=9,
        weighted_distance_score=0.9,
        normalized_weighted_distance=1.0,
        modified_manhattan_lower_bound=0.9,
        pairwise_distances={"airlock-1|workshop-1": 1},
        room_mass=12,
        utility_mass=2,
        total_mass=14,
        organics_required_for_journey=14,
        organics_capacity_margin=286,
        travel_feasible_at_full_tank=True,
        corridor_count=1,
        fixed_objective_optima_proven=3,
        incumbent_bound_pruned_count=2,
        fixed_subproblem_count=4,
        max_fixed_graph_nodes=61,
        max_fixed_graph_arcs=120,
        max_fixed_objective_pairs=28,
        max_fixed_pair_flow_variables=2100,
        max_fixed_pair_flow_full_variables=3360,
        total_fixed_pair_flow_variables=7200,
        total_fixed_pair_flow_full_variables=12000,
        max_fixed_cp_sat_variables=3500,
        max_fixed_cp_sat_constraints=6100,
        fixed_model_build_time_s=0.12,
        fixed_cp_sat_solve_time_s=0.51,
        fixed_subproblem_time_s=0.69,
    )


def test_average_pair_distance() -> None:
    result = _sample_result()
    result.pairwise_distances = {
        "a|b": 1,
        "a|c": 3,
        "b|c": 2,
    }
    assert average_pair_distance(result) == 2.0


def test_serialized_result_is_one_module_collection_with_authority() -> None:
    payload = result_payload(_sample_result())
    modules = payload["modules"]
    assert isinstance(modules, list)
    assert payload["schema_version"] == 2
    assert payload["feasibility"] == {
        "structural_feasible": True,
        "journey_feasible": True,
    }
    assert payload["module_counts_by_authority"] == {
        "system": 1,
        "player": 1,
        "solver": 1,
    }
    assert [module["placement_authority"] for module in modules] == [
        "system",
        "player",
        "solver",
    ]
    corridor = modules[2]
    assert corridor["module_key"] == "corridor"
    assert corridor["mass"] == MODULE_BY_KEY["corridor"].mass
    assert corridor["ports"]

    optimization = payload["optimization"]
    assert optimization["exact_integer_objective"] == {
        "scale": 10,
        "scaled_value": 9,
        "scaled_modified_manhattan_lower_bound": 9,
    }
    diagnostics = optimization["search_diagnostics"]
    assert diagnostics["fixed_objective_optima_proven"] == 3
    assert diagnostics["incumbent_bound_pruned_count"] == 2
    assert diagnostics["fixed_subproblems"] == {
        "count": 4,
        "max_graph_nodes": 61,
        "max_graph_arcs": 120,
        "max_objective_pairs": 28,
        "pair_flow_domain": {
            "max_actual_variables": 2100,
            "max_full_domain_variables": 3360,
            "total_actual_variables": 7200,
            "total_full_domain_variables": 12000,
        },
        "max_cp_sat_variables": 3500,
        "max_cp_sat_constraints": 6100,
        "lexicographic_scalarization": {
            "weight_f": 0,
            "weight_mass": 0,
            "weight_elevator": 0,
            "weight_corridor": 0,
            "corridor_bound": 0,
            "elevator_bound": 0,
            "mass_bound": 0,
            "max_objective_value": 0,
        },
        "model_build_time_s": 0.12,
        "cp_sat_solve_time_s": 0.51,
        "total_time_s": 0.69,
    }


def test_svg_contains_metrics_and_room_labels() -> None:
    svg = render_svg(_sample_result())
    assert "Tier 1" in svg
    assert "avg=1.00" in svg
    assert "total mass=14" in svg
    assert "Airlock" in svg
    assert "Workshop" in svg


def test_png_renderer_writes_nonempty_file(tmp_path) -> None:
    target = tmp_path / "layout.png"
    render_png(_sample_result(), target)
    assert target.exists()
    assert target.stat().st_size > 1000
