# Stage 3 exact-objective reference oracle

Status: **IN PROGRESS / reference solver only**

This document records the first Stage-3 implementation step. The normative contracts remain:

1. `PROJECT_SYSTEM_REQUIREMENTS.md`;
2. `docs/OPTIMIZATION_MODEL.md`.

The reference oracle does not replace those contracts and does not change game mechanics.

## Purpose

Stage 2 made hard feasibility exact for a fixed SYSTEM/PLAYER room packing, but it returned only one legal Corridor/Elevator witness. Different legal infrastructure networks can have different exact travel objective values and different lexicographic tie-break values.

Stage 3 therefore needs an exact way to optimize:

```text
1. exact F
2. total Base mass
3. Elevator module count
4. Corridor module count
```

before any scalable production formulation is trusted.

`src/alters_base_planner/fixed_objective_oracle.py` is the small-instance correctness oracle for that purpose.

## Exact search boundary

Input to the oracle is one already-fixed SYSTEM/PLAYER room packing.

For that packing it reuses the Stage-2 CP-SAT hard-feasibility model and repeatedly solves it to enumerate **distinct Corridor/Elevator selections**. Flow and sink assignments are not part of the enumeration identity; after one infrastructure selection is evaluated, a no-good cut excludes exactly that Corridor/Elevator assignment regardless of alternative flow witnesses.

For each hard-feasible infrastructure selection the oracle:

1. extracts canonical `ModulePlacement` objects;
2. evaluates the exact installed-module graph with the accepted Dijkstra semantics;
3. computes exact weighted pair objective `F`;
4. verifies `F_LB <= F_exact` using the modified-Manhattan lower bound;
5. ranks the candidate lexicographically by exact `F`, total mass, Elevator count and Corridor count.

The search is exact only when all distinct hard-feasible infrastructure selections have been exhausted.

## Proof semantics

The oracle may return:

```text
OPTIMAL
FEASIBLE
INFEASIBLE
TIME_LIMIT
```

For a fixed room packing:

- `OPTIMAL` with `objective_optimum_proven=true` means CP-SAT proved that no unexamined Corridor/Elevator selection remains and the best exact lexicographic candidate has therefore been identified;
- `FEASIBLE` means an incumbent exists but the infrastructure-selection domain was not exhausted;
- `INFEASIBLE` means no legal infrastructure network exists for that fixed packing;
- `TIME_LIMIT` means no feasible infrastructure incumbent was obtained before the budget expired.

A fixed-packing objective proof is **not** a global proof over alternative room placements. Production `PlanResult.global_objective_optimum_proven` must therefore remain false until the complete master/subproblem search also establishes the global proof.

## Independent exhaustive regression checks

`tests/test_fixed_objective_oracle.py` contains tiny independently enumerated utility-state cases. The test oracle brute-forces `None / Corridor / Elevator` state choices on free utility anchors, rejects physical utility overlaps, evaluates exact legal paths and applies the same documented lexicographic order.

The CP-SAT reference oracle must match this independent enumeration exactly.

Current regression cases include:

- direct room adjacency with exact objective 0 and no utility modules;
- one required 2x1 utility position where Corridor and Elevator have equal travel cost and mass, so the accepted Elevator-count tie-break must select Corridor;
- a two-module horizontal route with overlapping candidate anchors, validating distinct-network enumeration and tie-breaking over multiple exact-feasible infrastructure alternatives;
- a cross-floor packing with no legal vertical utility space, which must be proven infeasible.

These cases are intentionally tiny so exhaustive enumeration is a reliable test oracle rather than another heuristic.

## Scalability limitation

The reference solver is deliberately exponential in the number of legal infrastructure selections. It is not intended for full Base I-IV production searches.

Its role is to establish a trusted exact target against which more scalable Stage-3 formulations can be verified.

The next scalable Stage-3 work should preserve exactness while reducing the search space through mathematically safe techniques such as:

- stronger admissible lower bounds;
- exact decomposition cuts;
- utility-domain reduction that cannot remove an optimal network;
- indexed graph/model construction;
- objective-aware shortest-path formulations or an exact equivalent;
- incumbent/bound propagation between the room-packing master and infrastructure subproblem.

Any scalable replacement must continue to match this oracle on the tiny benchmark cases before it is used as the production correctness boundary.
