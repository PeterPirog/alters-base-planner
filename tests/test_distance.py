import pytest

from alters_base_planner.distance import evaluate_distances
from alters_base_planner.models import Placement, UtilityPlacement


def test_directly_adjacent_rooms_have_zero_distance() -> None:
    rooms = [
        Placement("airlock-1", "airlock", 0, 0, 4, 1),
        Placement("workshop-1", "workshop", 4, 0, 4, 1),
    ]
    metrics = evaluate_distances(rooms, [])
    assert metrics.pairwise_distances["airlock-1|workshop-1"] == 0
    assert metrics.weighted_score == 0


def test_one_corridor_adds_one_distance_point() -> None:
    rooms = [
        Placement("airlock-1", "airlock", 0, 0, 4, 1),
        Placement("workshop-1", "workshop", 6, 0, 4, 1),
    ]
    utilities = [UtilityPlacement("corridor", 4, 0)]
    metrics = evaluate_distances(rooms, utilities)
    assert metrics.pairwise_distances["airlock-1|workshop-1"] == 1
    assert metrics.weighted_score == pytest.approx(1.0 * 0.90 * 1)


def test_every_elevator_module_adds_one_distance_point() -> None:
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
    assert metrics.pairwise_distances["airlock-1|workshop-1"] == 4
    assert metrics.weighted_score == pytest.approx(1.0 * 0.90 * 4)


def test_separated_elevators_do_not_create_vertical_connection() -> None:
    rooms = [
        Placement("airlock-1", "airlock", 0, 0, 4, 1),
        Placement("workshop-1", "workshop", 6, 2, 4, 1),
    ]
    utilities = [
        UtilityPlacement("elevator", 4, 0),
        UtilityPlacement("elevator", 4, 2),
    ]
    with pytest.raises(ValueError, match="No walkable path"):
        evaluate_distances(rooms, utilities)


def test_room_internal_length_does_not_add_distance() -> None:
    rooms = [
        Placement("airlock-1", "airlock", 0, 0, 4, 1),
        Placement("greenhouse-1", "greenhouse", 4, 0, 8, 1),
    ]
    metrics = evaluate_distances(rooms, [])
    assert metrics.pairwise_distances["airlock-1|greenhouse-1"] == 0


def test_zero_weight_storage_is_excluded_from_pairs() -> None:
    rooms = [
        Placement("airlock-1", "airlock", 0, 0, 4, 1),
        Placement("workshop-1", "workshop", 6, 0, 4, 1),
        Placement("storage-1", "medium_storage", 10, 0, 8, 1),
    ]
    utilities = [UtilityPlacement("corridor", 4, 0)]
    metrics = evaluate_distances(rooms, utilities)
    assert set(metrics.pairwise_distances) == {"airlock-1|workshop-1"}
    assert metrics.weighted_score == pytest.approx(0.90)


def test_unordered_pair_sum_counts_each_pair_once() -> None:
    rooms = [
        Placement("airlock-1", "airlock", 0, 0, 4, 1),
        Placement("workshop-1", "workshop", 6, 0, 4, 1),
        Placement("command-1", "command_center", 12, 0, 4, 1),
    ]
    utilities = [
        UtilityPlacement("corridor", 4, 0),
        UtilityPlacement("corridor", 10, 0),
    ]
    metrics = evaluate_distances(rooms, utilities)
    assert metrics.pairwise_distances == {
        "airlock-1|workshop-1": 1,
        "airlock-1|command-1": 2,
        "workshop-1|command-1": 1,
    }
    expected = (1.0 * 0.90 * 1) + (1.0 * 0.75 * 2) + (0.90 * 0.75 * 1)
    assert metrics.weighted_score == pytest.approx(expected)
    assert sum(metrics.pairwise_contributions.values()) == pytest.approx(expected)
