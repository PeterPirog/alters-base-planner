import random
from itertools import product

import pytest

from alters_base_planner.fixed_flow_objective_solver import (
    _SIGNED_INT64_MAX,
    _assert_lexicographic_objective_fits_int64,
    lexicographic_dominance_weights,
    lexicographic_objective_upper_bound,
)


def test_dominance_weights_satisfy_strict_dominance() -> None:
    corridor_max, elevator_max, mass_max = 3, 5, 11
    w_f, w_m, w_e, w_c = lexicographic_dominance_weights(
        corridor_count_max=corridor_max,
        elevator_count_max=elevator_max,
        utility_mass_max=mass_max,
    )

    # Corridor is the lowest priority: a single Corridor never outweighs a single Elevator.
    assert w_e > w_c * corridor_max
    # Elevator is dominated by mass.
    assert w_m > w_e * elevator_max + w_c * corridor_max
    # Mass is dominated by the primary objective.
    assert w_f > w_m * mass_max + w_e * elevator_max + w_c * corridor_max
    assert w_c == 1


def test_scalarization_preserves_lexicographic_order_randomly() -> None:
    rng = random.Random(20260912)
    corridor_max, elevator_max = 4, 6
    mass_max = corridor_max * 2 + elevator_max * 2
    w_f, w_m, w_e, w_c = lexicographic_dominance_weights(
        corridor_count_max=corridor_max,
        elevator_count_max=elevator_max,
        utility_mass_max=mass_max,
    )

    def lexicographic_key(components: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        f, mass, elevator, corridor = components
        return (f, mass, elevator, corridor)

    for _ in range(20000):
        a = (
            rng.randint(0, 12),
            rng.randint(0, mass_max),
            rng.randint(0, elevator_max),
            rng.randint(0, corridor_max),
        )
        b = (
            rng.randint(0, 12),
            rng.randint(0, mass_max),
            rng.randint(0, elevator_max),
            rng.randint(0, corridor_max),
        )
        lex_a = lexicographic_key(a)
        lex_b = lexicographic_key(b)
        scalar_a = w_f * a[0] + w_m * a[1] + w_e * a[2] + w_c * a[3]
        scalar_b = w_f * b[0] + w_m * b[1] + w_e * b[2] + w_c * b[3]
        if lex_a == lex_b:
            assert scalar_a == scalar_b
        elif lex_a < lex_b:
            assert scalar_a < scalar_b
        else:
            assert scalar_a > scalar_b


def test_scalarization_preserves_lexicographic_order_exhaustively() -> None:
    bounds = (2, 3, 2, 2)
    w_f, w_m, w_e, w_c = lexicographic_dominance_weights(
        corridor_count_max=bounds[3],
        elevator_count_max=bounds[2],
        utility_mass_max=bounds[1],
    )
    weights = (w_f, w_m, w_e, w_c)
    tuples = tuple(
        (f, mass, elevator, corridor)
        for f, mass, elevator, corridor in product(
            range(bounds[0] + 1),
            range(bounds[1] + 1),
            range(bounds[2] + 1),
            range(bounds[3] + 1),
        )
    )

    def scalar(components: tuple[int, int, int, int]) -> int:
        return sum(weight * component for weight, component in zip(weights, components, strict=True))

    for a in tuples:
        for b in tuples:
            assert (a < b) == (scalar(a) < scalar(b))
            assert (a == b) == (scalar(a) == scalar(b))


def test_objective_upper_bound_is_sum_of_weighted_maxima() -> None:
    corridor_max, elevator_max, mass_max = 2, 3, 9
    w_f, w_m, w_e, w_c = lexicographic_dominance_weights(
        corridor_count_max=corridor_max,
        elevator_count_max=elevator_max,
        utility_mass_max=mass_max,
    )
    scaled_f_max = 42
    expected = w_f * scaled_f_max + w_m * mass_max + w_e * elevator_max + w_c * corridor_max
    assert (
        lexicographic_objective_upper_bound(
            weight_f=w_f,
            weight_mass=w_m,
            weight_elevator=w_e,
            weight_corridor=w_c,
            scaled_f_max=scaled_f_max,
            utility_mass_max=mass_max,
            elevator_count_max=elevator_max,
            corridor_count_max=corridor_max,
        )
        == expected
    )


def test_int64_safety_check_accepts_and_rejects() -> None:
    _assert_lexicographic_objective_fits_int64(_SIGNED_INT64_MAX)
    with pytest.raises(ValueError, match="signed 64-bit"):
        _assert_lexicographic_objective_fits_int64(_SIGNED_INT64_MAX + 1)
