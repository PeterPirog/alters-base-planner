# Stage 3 exact-objective reference and validation architecture

Status: **IN PROGRESS / production objective integration not complete**

The normative contracts remain:

1. `PROJECT_SYSTEM_REQUIREMENTS.md`;
2. `docs/OPTIMIZATION_MODEL.md`.

The Stage-3 components described here do not change game mechanics. Their role is to establish mathematically exact targets, validate scalable formulations against those targets, and only then move a proven formulation into the production solver.

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

The repository now has two exact reference layers plus one scalable exact fixed-packing candidate:

```text
fixed_objective_oracle.py
    exhaustive exact infrastructure objective for one fixed room packing

fixed_flow_objective_solver.py
    exact pair-flow CP-SAT objective for one fixed room packing
    validated against the exhaustive fixed oracle

global_objective_oracle.py
    exhaustive tiny-instance room packing search
        -> fixed objective oracle
        -> admissible packing lower-bound pruning
        -> end-to-end global proof
```

The exhaustive oracles are intentionally small-instance correctness machinery. The pair-flow formulation is designed to be more scalable, but it is not yet the production `solve_plan()` correctness boundary.

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

## Exact pair-flow fixed-packing formulation

`src/alters_base_planner/fixed_flow_objective_solver.py` is the first scalable Stage-3 candidate that optimizes the accepted objective without enumerating every infrastructure selection.

For one fixed room packing it reuses the exact Stage-2 hard model and adds a conditional directed travel graph. Every positive-weight unordered room pair receives one binary unit flow. The graph reproduces the accepted distance semantics:

```text
direct compatible endpoint adjacency = 0
enter/traverse one selected Corridor  = +1
enter/traverse one selected Elevator  = +1
cross intermediate transit room       = +width(room)
non-transit room                       = no internal side-to-side arc
vertical edge                          = adjacent same-x Elevators only
```

Arc use is conditioned on the same Corridor/Elevator selection variables used by the hard-feasibility model. The infrastructure decision is therefore shared by all room-pair flows rather than optimized independently per pair.

Traffic weights are converted from their decimal catalogue representation to exact rational values and then to integer coefficients using the least common multiple of denominators. CP-SAT therefore minimizes an integer-scaled value exactly equivalent to the documented weighted `F`; no floating-point objective approximation is introduced inside the model.

The accepted lexicographic objective is solved in four proof-preserving phases under one global wall-clock budget:

```text
1. minimize scaled exact F
2. constrain F to its proven optimum; minimize utility mass
3. constrain mass to its proven optimum; minimize Elevator count
4. constrain Elevator count to its proven optimum; minimize Corridor count
```

For a fixed room packing the non-SOLVER room mass is constant, so minimizing utility mass is exactly equivalent to minimizing total Base mass in the second phase.

A phase is marked proven only when CP-SAT returns `OPTIMAL`. If the budget expires after a primary incumbent or after only some tie-break phases are proven, the result remains `FEASIBLE` and the unproven lexicographic suffix is not claimed optimal.

### Independent evaluator cross-check

The pair-flow model is not allowed to define its own travel semantics by assertion alone. Every returned infrastructure witness is independently evaluated by the existing Dijkstra graph evaluator.

After CP-SAT proves the primary optimum, the solver reconstructs the exact scaled objective from `DistanceMetrics.pairwise_distances`. Any disagreement between the pair-flow optimum and the Dijkstra result raises an internal assertion. The same check is repeated after the lexicographic tie-break phases to ensure they did not alter the proven primary optimum.

This fail-fast boundary is intentional: model/evaluator disagreement is a correctness defect, not normal infeasibility.

### Current validation boundary

`tests/test_fixed_flow_objective_solver.py` cross-validates the pair-flow result against the exhaustive `fixed_objective_oracle.py`. Current cases cover:

- direct zero-cost room adjacency;
- Corridor-versus-Elevator tie-breaking for one required utility position;
- a two-Corridor horizontal route;
- a continuous two-level Elevator chain;
- exact intermediate transit-room width cost;
- proof that Rapidium Ark cannot be used as a non-transit bridge;
- a zero-weight Recycler that still remains in the hard-connected Base network while creating no objective pair;
- fixed-layout infrastructure infeasibility;
- zero-budget timeout semantics without false proof flags.

The full repository CI currently exercises these cases together with the existing suite on Python 3.11, 3.12 and 3.13. Ruff and all 100 tests pass at this validation point.

Passing these cases is necessary but not by itself sufficient to promote the pair-flow solver to production. Before production adoption it must also be benchmarked on a broader known-optimum suite and integrated with the room-packing master without weakening global proof semantics.

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

The fixed pair-flow solver has its own narrower proof boundary. `lexicographic_optimum_proven=true` proves the complete accepted objective **for one fixed room packing only**. It must never be translated directly into production `global_objective_optimum_proven=true`.

## Scalability limitation and next integration step

The exhaustive reference solvers are deliberately exponential. They remain benchmark/correctness machinery, not production algorithms for full Base I-IV layouts.

The pair-flow solver removes infrastructure-selection enumeration, but its model size grows with the product of weighted room pairs and conditional graph arcs. The next Stage-3 work must therefore measure model size and runtime rather than assuming scalability from formulation structure alone.

The recommended integration path is:

1. extend the known-optimum benchmark suite across representative horizontal, vertical, transit and non-transit tiny instances;
2. compare pair-flow objective, infrastructure signature and proof flags against the exhaustive oracle;
3. record CP-SAT variable/constraint counts and wall-clock time;
4. use pair-flow as the exact fixed-packing objective subproblem in a controlled master/decomposition path;
5. propagate admissible room-packing lower bounds and fixed-subproblem proof status to the master;
6. set production `global_objective_optimum_proven=true` only when every room packing is exactly resolved or safely excluded by a valid bound.

Any future domain reduction, cut or symmetry rule must remain mathematically safe and continue to match the reference oracles on known-optimum cases before becoming part of the production correctness boundary.
