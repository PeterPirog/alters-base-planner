from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.models import BaseGeometry, ModulePlacement, PlanResult
from alters_base_planner.render import average_pair_distance, render_png, render_svg
from alters_base_planner.serialization import result_payload


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
        rooms=[
            _module("airlock", "airlock-1", 0, 0),
            _module("workshop", "workshop-1", 6, 0),
        ],
        utilities=[_module("corridor", "corridor-1", 4, 0)],
        weighted_distance_score=0.9,
        normalized_weighted_distance=1.0,
        pairwise_distances={"airlock-1|workshop-1": 1},
        total_mass=14,
        organics_required_for_journey=14,
    )


def test_average_pair_distance() -> None:
    result = _sample_result()
    result.pairwise_distances = {
        "a|b": 1,
        "a|c": 3,
        "b|c": 2,
    }
    assert average_pair_distance(result) == 2.0


def test_serialized_result_exposes_module_authority_and_catalog_mass() -> None:
    payload = result_payload(_sample_result())
    rooms = payload["rooms"]
    utilities = payload["utilities"]
    assert isinstance(rooms, list)
    assert isinstance(utilities, list)
    assert rooms[0]["placement_authority"] == "system"
    assert rooms[1]["placement_authority"] == "player"
    assert utilities[0]["placement_authority"] == "solver"
    assert utilities[0]["module_key"] == "corridor"
    assert utilities[0]["kind"] == "corridor"  # compatibility field
    assert utilities[0]["mass"] == MODULE_BY_KEY["corridor"].mass


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
