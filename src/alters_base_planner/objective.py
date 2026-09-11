from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Mapping, Sequence

from .catalog import MODULE_BY_KEY
from .distance import modified_manhattan_room_lower_bound
from .models import ModulePlacement


@dataclass(frozen=True, slots=True)
class ObjectivePair:
    """One positive-weight unordered room pair in the exact scaled objective."""

    pair_id: str
    source_instance_id: str
    target_instance_id: str
    coefficient: int


@dataclass(frozen=True, slots=True)
class ScaledObjective:
    """Exact integer representation of the documented weighted travel objective.

    ``scale`` is the common denominator used to convert every pair weight ``w_i * w_j``
    into an integer coefficient. Therefore:

    ``scaled_F = scale * F``

    whenever ``F`` is evaluated from the same exact integer pair distances.
    """

    scale: int
    pairs: tuple[ObjectivePair, ...]

    def __post_init__(self) -> None:
        if self.scale <= 0:
            raise ValueError("Objective scale must be positive")
        if any(pair.coefficient <= 0 for pair in self.pairs):
            raise ValueError("Objective pair coefficients must be positive")
        pair_ids = [pair.pair_id for pair in self.pairs]
        if len(pair_ids) != len(set(pair_ids)):
            raise ValueError("Objective pair IDs must be unique")

    def scaled_score(self, pairwise_distances: Mapping[str, int]) -> int:
        """Return exact integer ``scale * F`` from exact pairwise distances."""

        total = 0
        for pair in self.pairs:
            if pair.pair_id not in pairwise_distances:
                raise KeyError(f"Missing exact distance for objective pair {pair.pair_id}")
            distance = pairwise_distances[pair.pair_id]
            if isinstance(distance, bool) or not isinstance(distance, int) or distance < 0:
                raise ValueError(
                    f"Distance for objective pair {pair.pair_id} must be a non-negative integer"
                )
            total += pair.coefficient * distance
        return total

    def unscaled_score(self, scaled_score: int) -> float:
        """Convert an exact scaled score to the user-facing floating representation."""

        if isinstance(scaled_score, bool) or not isinstance(scaled_score, int):
            raise ValueError("Scaled objective score must be an integer")
        return scaled_score / self.scale


def build_scaled_objective(rooms: Sequence[ModulePlacement]) -> ScaledObjective:
    """Build one exact integer objective definition for an installed room set.

    Catalogue traffic weights are decimal planner parameters. ``Fraction(str(weight))`` treats
    their documented decimal representation exactly instead of importing binary floating-point
    round-off into CP-SAT coefficients or global proof comparisons.
    """

    active = [room for room in rooms if MODULE_BY_KEY[room.module_key].visit_weight > 0]
    fractional_pairs: list[tuple[str, str, str, Fraction]] = []
    scale = 1

    for index, room_a in enumerate(active):
        weight_a = Fraction(str(MODULE_BY_KEY[room_a.module_key].visit_weight))
        for room_b in active[index + 1 :]:
            weight_b = Fraction(str(MODULE_BY_KEY[room_b.module_key].visit_weight))
            pair_weight = weight_a * weight_b
            if pair_weight <= 0:
                raise AssertionError("Positive-weight objective pair has non-positive weight")
            pair_id = f"{room_a.instance_id}|{room_b.instance_id}"
            fractional_pairs.append(
                (pair_id, room_a.instance_id, room_b.instance_id, pair_weight)
            )
            scale = math.lcm(scale, pair_weight.denominator)

    pairs: list[ObjectivePair] = []
    for pair_id, source, target, pair_weight in fractional_pairs:
        coefficient_fraction = pair_weight * scale
        if coefficient_fraction.denominator != 1:
            raise AssertionError("Objective scaling did not produce an integer coefficient")
        coefficient = coefficient_fraction.numerator
        if coefficient <= 0:
            raise AssertionError("Positive-weight objective pair has non-positive coefficient")
        pairs.append(ObjectivePair(pair_id, source, target, coefficient))

    return ScaledObjective(scale=scale, pairs=tuple(pairs))


def scaled_modified_manhattan_lower_bound(
    rooms: Sequence[ModulePlacement],
    objective: ScaledObjective | None = None,
) -> int:
    """Return the admissible modified-Manhattan lower bound in exact objective units."""

    objective = objective or build_scaled_objective(rooms)
    by_instance_id = {room.instance_id: room for room in rooms}
    if len(by_instance_id) != len(rooms):
        raise ValueError("Module placement instance IDs must be unique")

    total = 0
    for pair in objective.pairs:
        try:
            source = by_instance_id[pair.source_instance_id]
            target = by_instance_id[pair.target_instance_id]
        except KeyError as exc:
            raise ValueError(
                "Objective definition references an instance missing from the supplied room set"
            ) from exc
        distance_lb = modified_manhattan_room_lower_bound(source, target)
        if distance_lb < 0:
            raise AssertionError("Modified-Manhattan lower bound must be non-negative")
        total += pair.coefficient * distance_lb
    return total
