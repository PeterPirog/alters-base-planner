import pytest

from alters_base_planner.catalog import MODULE_BY_KEY
from alters_base_planner.models import ModulePlacement
from alters_base_planner.objective import (
    ScaledObjective,
    build_scaled_objective,
    scaled_modified_manhattan_lower_bound,
)


def _room(instance_id: str, module_key: str, x: int, y: int) -> ModulePlacement:
    spec = MODULE_BY_KEY[module_key]
    return ModulePlacement(instance_id, module_key, x, y, spec.width, spec.height)


def test_two_room_objective_uses_exact_decimal_weight_scaling() -> None:
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 6, 0),
    )

    objective = build_scaled_objective(rooms)

    assert objective.scale == 10
    assert len(objective.pairs) == 1
    assert objective.pairs[0].pair_id == "airlock-1|workshop-1"
    assert objective.pairs[0].coefficient == 9
    assert objective.scaled_score({"airlock-1|workshop-1": 3}) == 27
    assert objective.unscaled_score(27) == pytest.approx(2.7)


def test_multi_pair_objective_uses_one_common_exact_scale() -> None:
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 4, 0),
        _room("command-center-1", "command_center", 8, 0),
    )

    objective = build_scaled_objective(rooms)
    coefficients = {pair.pair_id: pair.coefficient for pair in objective.pairs}

    assert objective.scale == 200
    assert coefficients == {
        "airlock-1|workshop-1": 180,
        "airlock-1|command-center-1": 70,
        "workshop-1|command-center-1": 63,
    }
    distances = {
        "airlock-1|workshop-1": 0,
        "airlock-1|command-center-1": 4,
        "workshop-1|command-center-1": 0,
    }
    assert objective.scaled_score(distances) == 280
    assert objective.unscaled_score(280) == pytest.approx(1.4)


def test_zero_weight_rooms_do_not_create_objective_pairs() -> None:
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("recycler-1", "recycler", 4, 0),
    )

    objective = build_scaled_objective(rooms)

    assert objective == ScaledObjective(scale=1, pairs=())
    assert objective.scaled_score({}) == 0
    assert scaled_modified_manhattan_lower_bound(rooms, objective) == 0


def test_scaled_modified_manhattan_bound_is_integer_exact() -> None:
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 6, 0),
    )
    objective = build_scaled_objective(rooms)

    assert scaled_modified_manhattan_lower_bound(rooms, objective) == 9


def test_scaled_score_rejects_missing_or_invalid_pair_distances() -> None:
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 6, 0),
    )
    objective = build_scaled_objective(rooms)

    with pytest.raises(KeyError, match="Missing exact distance"):
        objective.scaled_score({})
    with pytest.raises(ValueError, match="non-negative integer"):
        objective.scaled_score({"airlock-1|workshop-1": -1})
    with pytest.raises(ValueError, match="non-negative integer"):
        objective.scaled_score({"airlock-1|workshop-1": True})


def test_scaled_lower_bound_rejects_objective_for_different_room_set() -> None:
    rooms = (
        _room("airlock-1", "airlock", 0, 0),
        _room("workshop-1", "workshop", 6, 0),
    )
    objective = build_scaled_objective(rooms)

    with pytest.raises(ValueError, match="missing from the supplied room set"):
        scaled_modified_manhattan_lower_bound((rooms[0],), objective)
