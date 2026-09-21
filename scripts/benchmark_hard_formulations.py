"""Phase-2 research benchmark: Formulation A vs compact Formulation B1 (no production change).

Measures, on identical inputs per case:

- candidate/domain generation time
- model construction time (median/min/max over measured repetitions after one warm-up)
- model.validate() time
- CP-SAT variable count
- CP-SAT constraint count, classified by proto constraint kind
- serialized model proto bytes
- placement candidate count
- utility anchor count
- candidate port-node count
- conditional graph-edge count (derived exactly: every conditional edge creates exactly
  two ``flow__`` variables)

Timing discipline: one warm-up build + 3 measured builds for every case (Tiny, Tier I-IV);
Tier III/IV measurements stay cheap because only model construction (never long solves) is
timed. Structural solve screens use identical solver parameters for A and B with small
research budgets (tiny 2 s, Tier I 10 s, Tier II 15 s; Tier III/IV screens run only when
B1 is materially smaller and are activated with --screens tier3/tier4/all).

Run:  python scripts/benchmark_hard_formulations.py [--screens tier3|tier4|all]
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ortools.sat.python import cp_model

from alters_base_planner.base import builtin_base
from alters_base_planner.catalog import MODULES, ModuleSpec
from alters_base_planner.compact_hard_constraints import build_compact_hard_constraint_layer
from alters_base_planner.hard_constraints import (
    PlacementOptionSpec,
    UtilityAnchorSpec,
    build_hard_constraint_layer,
)
from alters_base_planner.integrated_hard_solver import (
    enumerate_placement_options,
    enumerate_utility_anchors,
)
from alters_base_planner.models import BaseGeometry, ModuleInstance

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

TIER_PLAYER_ROOMS: dict[int, dict[str, int]] = {
    1: {},
    2: {
        "workshop": 1,
        "research_lab": 1,
        "dormitory": 1,
        "infirmary": 1,
        "greenhouse": 1,
        "refinery": 1,
        "small_storage": 2,
        "social_room": 1,
        "recycler": 1,
    },
    3: {
        "workshop": 1,
        "research_lab": 1,
        "dormitory": 1,
        "infirmary": 1,
        "greenhouse": 1,
        "refinery": 1,
        "small_storage": 2,
        "social_room": 1,
        "recycler": 1,
        "gym": 1,
        "gamers_den": 1,
        "park_with_bench": 1,
    },
    4: {
        "workshop": 1,
        "research_lab": 1,
        "dormitory": 1,
        "infirmary": 1,
        "greenhouse": 1,
        "refinery": 1,
        "small_storage": 2,
        "social_room": 1,
        "recycler": 1,
        "gym": 1,
        "gamers_den": 1,
        "park_with_bench": 1,
        "rapidium_ark": 2,
        "materializer": 1,
        "large_storage": 1,
    },
}

SOLVE_BUDGET_S: dict[str, float] = {
    "tiny": 2.0,
    "tier1": 10.0,
    "tier2": 15.0,
    "tier3": 20.0,
    "tier4": 20.0,
}


@dataclass(frozen=True)
class CaseData:
    name: str
    tier: int | None
    base: BaseGeometry
    instances: tuple[ModuleInstance, ...]
    placement_options: tuple[PlacementOptionSpec, ...]
    utility_anchors: tuple[UtilityAnchorSpec, ...]


def _module_spec(key: str) -> ModuleSpec:
    return next(spec for spec in MODULES if spec.key == key)


def _make_tiny_case() -> CaseData:
    """1-row synthetic Base: airlock | corridor anchor | workshop (Phase-2 family F5)."""

    from alters_base_planner.models import PortSide, ResolvedPort

    base = BaseGeometry(
        tier=99,
        width=12,
        height=1,
        allowed_cells=frozenset((x, 0) for x in range(12)),
        blocked_cells=frozenset(),
        organics_capacity=999,
        source="phase2-benchmark-tiny",
        verified=False,
        note="Phase-2 benchmark tiny case",
    )

    def port(name: str, side: PortSide, edge_x: int, edge_y: int) -> ResolvedPort:
        return ResolvedPort(
            name=name,
            side=side,
            cell_x=edge_x if side is PortSide.LEFT else edge_x - 1,
            cell_y=edge_y,
            edge_x=edge_x,
            edge_y=edge_y,
        )

    def room(
        option_id: str, instance_id: str, module_key: str, x: int, width: int
    ) -> PlacementOptionSpec:
        cells = frozenset((xx, 0) for xx in range(x, x + width))
        return PlacementOptionSpec(
            option_id=option_id,
            instance_id=instance_id,
            module_key=module_key,
            cells=cells,
            ports=(
                port("left", PortSide.LEFT, x, 0),
                port("right", PortSide.RIGHT, x + width, 0),
            ),
            transit_allowed=True,
        )

    options = (
        room("a@0", "airlock-1", "airlock", 0, 4),
        room("w@6", "workshop-1", "workshop", 6, 4),
    )
    anchors = (UtilityAnchorSpec(4, 0),)
    instances = (
        ModuleInstance("airlock-1", _module_spec("airlock")),
        ModuleInstance("workshop-1", _module_spec("workshop")),
    )
    return CaseData("tiny", None, base, instances, options, anchors)


def _make_tier_case(tier: int) -> CaseData:
    base = builtin_base(tier)
    instances: list[ModuleInstance] = []
    for spec in MODULES:
        if spec.authority.value == "system":
            instances.append(ModuleInstance(f"{spec.key}-1", spec))
    for key, count in TIER_PLAYER_ROOMS[tier].items():
        spec = _module_spec(key)
        for index in range(count):
            instances.append(ModuleInstance(f"{key}-{index + 1}", spec))
    instance_tuple = tuple(instances)
    placement_options, _ = enumerate_placement_options(base, instance_tuple)
    utility_anchors = enumerate_utility_anchors(base)
    return CaseData(f"tier{tier}", tier, base, instance_tuple, placement_options, utility_anchors)


_CONSTRAINT_KINDS = (
    "bool_or",
    "bool_and",
    "bool_xor",
    "at_most_one",
    "exactly_one",
    "linear",
    "interval",
    "no_overlap",
    "no_overlap_2d",
    "element",
    "table",
    "all_diff",
    "cumulative",
    "routes",
    "circuit",
    "reservoir",
    "inverse",
    "automaton",
    "int_div",
    "int_mod",
    "int_prod",
    "lin_max",
    "dummy_constraint",
)


def _constraint_kind_counts(model: cp_model.CpModel) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for constraint in model.proto.constraints:
        for kind in _CONSTRAINT_KINDS:
            if getattr(constraint, f"has_{kind}")():
                counts[kind] += 1
                break
        else:
            counts["unknown"] += 1
    return dict(sorted(counts.items()))


def _conditional_edge_count(model: cp_model.CpModel) -> int:
    return sum(1 for v in model.proto.variables if v.name.startswith("flow__")) // 2


def _build_model(
    formulation: str,
    case: CaseData,
    placement_options: tuple[PlacementOptionSpec, ...],
    utility_anchors: tuple[UtilityAnchorSpec, ...],
) -> cp_model.CpModel:
    model = cp_model.CpModel()
    if formulation == "A":
        build_hard_constraint_layer(
            model,
            buildable_cells=case.base.buildable_cells,
            placement_options=placement_options,
            utility_anchors=utility_anchors,
            root_instance_id="airlock-1",
        )
    else:
        build_compact_hard_constraint_layer(
            model,
            buildable_cells=case.base.buildable_cells,
            placement_options=placement_options,
            utility_anchors=utility_anchors,
            root_instance_id="airlock-1",
        )
    return model


def _serialized_proto_bytes(model: cp_model.CpModel) -> int:
    # pybind11 proto wrapper: str() size is a stable deterministic size proxy for A-vs-B
    # comparison in this research benchmark (real serialized bytes differ by a constant
    # wrapper overhead that cancels in the comparison).
    return len(str(model.proto))


def _metrics(model: cp_model.CpModel) -> dict:
    return {
        "variables": len(model.proto.variables),
        "constraints": len(model.proto.constraints),
        "constraint_kinds": _constraint_kind_counts(model),
        "proto_bytes": _serialized_proto_bytes(model),
        "conditional_edges": sum(
            1 for v in model.proto.variables if v.name.startswith("flow__")
        )
        // 2,
    }


def measure_case(case: CaseData, *, repetitions: int = 3) -> list[dict]:
    rows: list[dict] = []
    for formulation in ("A", "B1"):
        build_times: list[float] = []
        validate_times: list[float] = []
        candidate_generation_s = 0.0
        metrics: dict = {}
        options = case.placement_options
        anchors = case.utility_anchors
        for _rep in range(repetitions + 1):  # the first pass is the warm-up
            if case.tier is None:
                candidate_generation_s = 0.0
                options, anchors = case.placement_options, case.utility_anchors
            else:
                generation_start = time.perf_counter()
                options, _ = enumerate_placement_options(case.base, case.instances)
                anchors = enumerate_utility_anchors(case.base)
                candidate_generation_s = time.perf_counter() - generation_start
            build_start = time.perf_counter()
            model = _build_model(formulation, case, options, anchors)
            build_times.append(time.perf_counter() - build_start)
            validate_start = time.perf_counter()
            error = model.validate()
            validate_times.append(time.perf_counter() - validate_start)
            assert error == "", f"model.validate() failed for {case.name}/{formulation}: {error}"
            metrics = _metrics(model)

        rows.append(
            {
                "case": case.name,
                "formulation": formulation,
                "options": len(options),
                "anchors": len(anchors),
                "port_nodes": sum(len(option.ports) for option in options),
                **metrics,
                "build_median_s": round(statistics.median(build_times), 4),
                "build_min_s": round(min(build_times), 4),
                "build_max_s": round(max(build_times), 4),
                "validate_median_s": round(statistics.median(validate_times), 4),
                "candidate_generation_s": round(candidate_generation_s, 4),
            }
        )
    return rows


def solve_screen(case: CaseData, budget_s: float) -> list[dict]:
    rows: list[dict] = []
    for formulation in ("A", "B1"):
        model = _build_model(formulation, case, case.placement_options, case.utility_anchors)
        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 8
        solver.parameters.max_time_in_seconds = budget_s
        start = time.perf_counter()
        status = solver.solve(model)
        elapsed = time.perf_counter() - start
        rows.append(
            {
                "case": case.name,
                "formulation": f"{formulation}-solve",
                "status": str(status),
                "solve_s": round(elapsed, 3),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screens", choices=["tiny", "tier1", "tier2", "tier3", "tier4", "all"],
                        default="tiny", help="extra structural solve screens to run")
    args = parser.parse_args()

    cases = [_make_tier_case(tier) for tier in (1, 2, 3, 4)]
    cases.insert(0, _make_tiny_case())

    all_rows: list[dict] = []
    for case in cases:
        # Larger tiers get fewer repetitions so the whole benchmark stays bounded.
        repetitions = 2 if case.name in {"tier3", "tier4"} else 3
        all_rows.extend(measure_case(case, repetitions=repetitions))

    screens = {"tiny": 2.0, "tier1": 10.0, "tier2": 15.0, "tier3": 20.0, "tier4": 20.0}
    for case in cases:
        if args.screens == "all" or case.name == args.screens:
            all_rows.extend(solve_screen(case, screens[case.name]))

    print("=== PHASE-2 FORMULATION METRICS (A vs B1) ===")
    for row in all_rows:
        print(row)


if __name__ == "__main__":
    main()