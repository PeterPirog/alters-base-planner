# Stage 3 exact-objective reference oracles

Status: **IN PROGRESS / reference solvers only**

The normative contracts remain:

1. `PROJECT_SYSTEM_REQUIREMENTS.md`;
2. `docs/OPTIMIZATION_MODEL.md`.

The reference solvers do not replace those contracts and do not change game mechanics. Their role is to provide mathematically exact small-instance targets before a scalable production Stage-3 formulation is trusted.

## Purpose

Stage 2 made hard feasibility exact for a fixed SYSTEM/PLAYER room packing, but returned only one legal Corridor/Elevator witness. Different legal infrastructure networks can have different exact travel objective values and different lexicographic tie-break values.

Stage 3 must optimize:

```text
1. exact F
2. total Base mass
3. Elevator module count
4. Corridor module count
```

across both infrastructure alternatives and room placements.

The repository now has two nested exact reference layers:

```text
fixed_objective_oracle.py
    exact infrastructure objective for one fixed room packing

global_objective_oracle.py
    exhaustive tiny-instance room packing search
        -> fixed objective oracle
        -> admissible packing lower-bound pruning
        -> end-to-end global proof
```

Neither layer is intended to solve full Base I-IV production instances by exhaustive enumeration.

## Fixed-packing objective oracle

`src/alters_base_planner/fixed_objective_oracle.py` takes one already-fixed SYSTEM/PLAYER room packing.

For that packing it reuses the Stage-2 CP-SAT hard-feasibility model and repeatedly solves it to enumerate **distinct Corridor/Elevator selections**. Flow and sink assignments are not part of the enumeration identity; after one infrastructure selection is evaluated, a no-good cut excludes exactly that Corridor/Elevator assignment regardless of alternative flow witnesses.

For each hard-feasible infrastructure selection the oracle:

1. extracts canonical `ModulePlacement` objects;
2. evaluates the exact installed-module graph with the accepted Dijkstra semantics;
3. computes exact weighted pair objective `F`;
4. verifies `F_LB <= F_exact` using the modified-Manhattan lower bound;
5. ranks the candidate lexicographically by exact `F`, total mass, Elevator count and Corridor count.

The search is exact only when all distinct hard-feasible infrastructure selections have been exhausted.

For a fixed room packing:

- `OPTIMAL` with `objective_optimum_proven=true` means no unexamined Corridor/Elevator selection remains and the best exact lexicographic candidate is proven;
- `FEASIBLE` means an incumbent exists but the infrastructure-selection domain was not exhausted;
- `INFEASIBLE` means no legal infrastructure network exists for that fixed packing;
- `TIME_LIMIT` means no feasible infrastructure incumbent was obtained before the budget expired.

## Exact fixed-layout domain reduction

For a fixed room packing, a Corridor/Elevator anchor intersecting an occupied SYSTEM/PLAYER cell is impossible under H3 no-overlap. `compile_fixed_layout_hard_model()` therefore removes such anchors before CP-SAT variable creation.

This reduction is exact rather than heuristic: every removed anchor would otherwise be forced inactive by the hard occupancy constraints. The non-fixed integrated room-placement model retains the full utility domain because room occupancy is still undecided there.

## Global tiny-instance objective oracle

`src/alters_base_planner/global_objective_oracle.py` extends the proof boundary across room placements for deliberately small benchmark instances.

It:

1. enumerates every non-overlapping SYSTEM/PLAYER room packing against the exact Base mask;
2. removes only pure label permutations between identical module instances by requiring their placement coordinates to be strictly ordered;
3. computes the admissible modified-Manhattan `F_LB` for each packing;
4. processes packings in increasing lower-bound order;
5. calls the fixed-packing exact objective oracle for every packing that cannot be safely pruned;
6. prunes a packing only when `F_LB > incumbent_exact_F`;
7. does **not** prune equality because equal `F` may still improve mass/Elevator/Corridor tie-breakers;
8. reports a global proof only after every physical packing is exactly resolved, proven infrastructure-infeasible, or excluded by that strict admissible bound.

For this tiny-instance reference solver, `global_objective_optimum_proven=true` therefore has literal mathematical meaning over both room placements and infrastructure choices.

This does **not** change production `PlanResult.global_objective_optimum_proven`, which must remain false until the scalable production solver can establish the same proof boundary for its configured search.

## Independent exhaustive regression checks

`tests/test_fixed_objective_oracle.py` independently brute-forces tiny utility-state spaces using `None / Corridor / Elevator` choices on free utility anchors. Current cases cover:

- direct room adjacency with exact objective 0 and no utilities;
- Corridor-versus-Elevator tie-breaking when travel cost and mass are equal;
- a two-module horizontal route with overlapping candidate anchors;
- fixed-packing infrastructure infeasibility.

`tests/test_global_objective_oracle.py` adds end-to-end checks across room placement and infrastructure selection. It independently brute-forces both room coordinates and utility states for a tiny one-floor Base, compares the complete accepted lexicographic result with the global reference oracle, verifies strict lower-bound pruning, verifies proof of global infeasibility, and locks identical-instance symmetry breaking.

These cases are intentionally tiny so exhaustive enumeration is a reliable test oracle rather than another heuristic.

## Proof semantics

The global reference oracle may return:

```text
OPTIMAL
FEASIBLE
INFEASIBLE
TIME_LIMIT
```

`OPTIMAL` with `global_objective_optimum_proven=true` requires a complete mathematical proof over its enumerated room-placement domain and all legal infrastructure alternatives. A time-limited incumbent is always reported without a global proof.

The global lower bound is propagated from the next unresolved packing's admissible bound and the best exactly resolved incumbent. Once all remaining packing lower bounds are strictly above the incumbent exact `F`, the remaining suffix is safely excluded.

## Scalability limitation

Both reference solvers are deliberately exponential. They are benchmark/correctness machinery, not production algorithms for full Base I-IV layouts.

The next scalable Stage-3 work should preserve exactness through mathematically safe techniques such as:

- stronger admissible lower bounds;
- exact master/subproblem cuts;
- utility-domain reductions that cannot remove an optimal network;
- indexed graph/model construction;
- objective-aware shortest-path formulations or a proven equivalent;
- incumbent/bound propagation between room-packing master and infrastructure subproblem;
- benchmark comparison against the global reference oracle before production adoption.

A scalable replacement must continue to match the reference oracles on known-optimum tiny cases before it becomes a production correctness boundary.
