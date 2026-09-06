import pytest

from alters_base_planner.distance import (
    _validate_vertical_elevator_coverage,
    evaluate_distances,
    modified_manhattan_room_lower_bound,
    room_access_rows,
)
from alters_base_planner.models import Placement, UtilityPlacement


def test_directly_adjacent_rooms_have_zero_distance() -> None:
    rooms = [
        Placement("airlock-1", "airlock", 0, 0, 4, 1),
        Placement("workshop-1", "workshop", 4, 0, 4, 1),
    ]
    metrics = evaluate_distances(rooms, [])
    assert metrics.pairwise_distances["airlock-1|workshop-1"] == 0
    assert metrics.pairwise_manhattan_lower_bounds["airlock-1|workshop-1"] == 0
    assert metrics.weighted_score == 0


def test_endpoint_room_lengths_do_not_add_distance() -> None:
    rooms = [
        Placement("airlock-1", "airlock", 0, 0, 4, 1),
        Placement("greenhouse-1", "greenhouse", 4, 0, 8, 1),
    ]
    metrics = evaluate_distances(rooms, [])
    assert metrics.pairwise_distances["airlock-1|greenhouse-1"] == 0


def test_intermediate_room_adds_its_grid_length() -> None:
    rooms = [
        Placement("airlock-1", "airlock", 0, 0, 4, 1),
        Placement("workshop-1", "workshop", 4, 0, 4, 1),
        Placement("command-1", "command_center", 8, 0, 4, 1),
    ]
    metrics = evaluate_distances(rooms, [])
    assert metrics.pairwise_distances["airlock-1|workshop-1"] == 0
    assert metrics.pairwise_distances["workshop-1|command-1"] == 0
    assert metrics.pairwise_distances["airlock-1|command-1"] == 4


def test_one_corridor_adds_one_distance_point() -> None:
    rooms = [
        Placement("airlock-1", "airlock", 0, 0, 4, 1),
        Placement("workshop-1", "workshop", 6, 0, 4, 1),
    ]
    utilities = [UtilityPlacement("corridor", 4, 0)]
    metrics = evaluate_distances(rooms, utilities)
    assert metrics.pairwise_distances["airlock-1|workshop-1"] == 1
    assert metrics.pairwise_manhattan_lower_bounds["airlock-1|workshop-1"] == 1
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
    assert modified_manhattan_room_lower_bound(rooms[0], rooms[1]) == 4
    assert metrics.weighted_score == pytest.approx(1.0 * 0.90 * 4)


def test_multirow_room_is_entered_at_floor_not_ceiling() -> None:
    quantum = Placement("quantum-1", "quantum_computer", 0, 0, 4, 2)
    workshop = Placement("workshop-1", "workshop", 6, 1, 4, 1)
    assert room_access_rows(quantum) == frozenset({1})
    metrics = evaluate_distances(
        [quantum, workshop],
        [UtilityPlacement("corridor", 4, 1)],
    )
    assert metrics.pairwise_distances["quantum-1|workshop-1"] == 1


def test_radiation_repulsor_retains_verified_top_access_exception() -> None:
    repulsor = Placement("repulsor-1", "radiation_repulsor", 0, 0, 2, 3)
    assert room_access_rows(repulsor) == frozenset({0})


def test_missing_intermediate_elevator_level_is_hard_infeasible() -> None:
    rooms = [
        Placement("airlock-1", "airlock", 0, 0, 4, 1),
        Placement("workshop-1", "workshop", 6, 2, 4, 1),
    ]
    utilities = [
        UtilityPlacement("elevator", 4, 0),
        UtilityPlacement("elevator", 4, 2),
    ]
    with pytest.raises(ValueError, match="requires at least 3 Elevator modules"):
        evaluate_distances(rooms, utilities)


def test_shifted_shafts_must_overlap_on_each_adjacent_floor_pair() -> None:
    rooms = [
        Placement("airlock-1", "airlock", 0, 0, 4, 1),
        Placement("workshop-1", "workshop", 0, 1, 4, 1),
        Placement("research-1", "research_lab", 0, 2, 4, 1),
    ]
    utilities = [
        UtilityPlacement("elevator", 4, 0),
        UtilityPlacement("elevator", 6, 1),
        UtilityPlacement("elevator", 6, 2),
    ]
    with pytest.raises(ValueError, match="floors 0 and 1 do not share"):
        _validate_vertical_elevator_coverage(rooms, utilities)


def test_shifted_shafts_are_legal_through_transfer_floor() -> None:
    rooms = [
        Placement("airlock-1", "airlock", 0, 0, 4, 1),
        Placement("workshop-1", "workshop", 0, 1, 4, 1),
        Placement("research-1", "research_lab", 0, 2, 4, 1),
    ]
    utilities = [
        UtilityPlacement("elevator", 4, 0),
        UtilityPlacement("elevator", 4, 1),
        UtilityPlacement("elevator", 8, 1),
        UtilityPlacement("elevator", 8, 2),
    ]
    _validate_vertical_elevator_coverage(rooms, utilities)


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


def test_unordered_pair_sum_counts_each_pair_once_with_intermediate_room_cost() -> None:
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
        "airlock-1|command-1": 6,
        "workshop-1|command-1": 1,
    }
    expected = (1.0 * 0.90 * 1) + (1.0 * 0.35 * 6) + (0.90 * 0.35 * 1)
    assert metrics.weighted_score == pytest.approx(expected)
    assert sum(metrics.pairwise_contributions.values()) == pytest.approx(expected)
