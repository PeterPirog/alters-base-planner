from alters_base_planner.models import BaseGeometry, Placement, PlanResult, UtilityPlacement
from alters_base_planner.render import average_pair_distance, render_png, render_svg


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
            Placement("airlock-1", "airlock", 0, 0, 4, 1),
            Placement("workshop-1", "workshop", 6, 0, 4, 1),
        ],
        utilities=[UtilityPlacement("corridor", 4, 0)],
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
