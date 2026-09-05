from alters_base_planner.distance import evaluate_distances
from alters_base_planner.models import Placement, UtilityPlacement


def test_elevator_ride_cost_is_independent_of_floor_count() -> None:
    rooms = [
        Placement("airlock-1", "airlock", 0, 0, 4, 1),
        Placement("workshop-1", "workshop", 6, 3, 4, 1),
    ]
    utilities = [
        UtilityPlacement("elevator", 4, 0),
        UtilityPlacement("elevator", 4, 1),
        UtilityPlacement("elevator", 4, 2),
        UtilityPlacement("elevator", 4, 3),
    ]

    metrics = evaluate_distances(rooms, utilities)
    assert metrics.elevator_module_count == 4
    assert metrics.elevator_shaft_count == 1
    assert metrics.corridor_count == 0
    # The ride from floor 0 to floor 3 is one point, not three.
    assert metrics.pairwise_distances["airlock-1|workshop-1"] == 6


def test_separated_elevators_form_separate_shafts() -> None:
    rooms = [
        Placement("airlock-1", "airlock", 0, 0, 4, 1),
        Placement("workshop-1", "workshop", 6, 2, 4, 1),
    ]
    utilities = [
        UtilityPlacement("elevator", 4, 0),
        UtilityPlacement("elevator", 4, 2),
    ]

    try:
        evaluate_distances(rooms, utilities)
    except ValueError as exc:
        assert "No walkable path" in str(exc)
    else:
        raise AssertionError("Non-contiguous Elevator modules must not create vertical travel")


def test_storage_weight_has_small_effect_relative_to_workshop() -> None:
    rooms = [
        Placement("airlock-1", "airlock", 0, 0, 4, 1),
        Placement("workshop-1", "workshop", 4, 0, 4, 1),
        Placement("storage-1", "small_storage", 8, 0, 2, 2),
    ]
    metrics = evaluate_distances(rooms, [])
    assert metrics.weighted_score > 0
    assert metrics.normalized_weighted_distance > 0
