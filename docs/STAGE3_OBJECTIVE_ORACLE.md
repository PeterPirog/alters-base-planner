# Stage 3 exact-objective architecture and validation

Status: **COMPLETE / harden and benchmark**

Normative contracts:

1. `PROJECT_SYSTEM_REQUIREMENTS.md`;
2. `docs/OPTIMIZATION_MODEL.md`.

Stage 3 does not change game mechanics. It moves the accepted exact travel objective and lexicographic tie-breakers into the production optimization boundary while retaining independently exhaustive reference solvers for correctness validation.

## Production architecture

The production solver now uses an exact decomposition:

```text
CP-SAT SYSTEM/PLAYER room-packing master
        -> exact integer modified-Manhattan lower bound
        -> exact fixed-packing source-aggregated flow CP-SAT
             Corridor/Elevator selection
             hard connectivity
             exact weighted travel F
             mass -> Elevators -> Corridors
        -> independent Dijkstra evaluator cross-check
        -> exact lexicographic incumbent comparison
```

The decomposition is exact when its configured search completes. A time limit or layout-attempt limit preserves best-known semantics and prevents a global optimality claim.

## Why Stage 3 was necessary

Stage 2 made hard feasibility exact for a fixed SYSTEM/PLAYER room packing, but returned one arbitrary legal Corridor/Elevator witness. Different legal infrastructure networks can have different travel costs and tie-break values.

Stage 3 optimizes the complete accepted order:

```text
1. exact F
2. total Base mass
3. Elevator module count
4. Corridor module count
```

across infrastructure alternatives and, through the master, across room placements.

## Exact integer objective representation

Catalogue traffic weights are decimal planner parameters. `objective.py` converts their documented decimal form through exact rational arithmetic to a shared integer objective representation:

```text
scaled_F = scale * F
```

Every positive-weight room pair receives an integer coefficient. The same `ScaledObjective` is used for:

- CP-SAT fixed-packing optimization;
- Dijkstra objective reconstruction;
- room-packing incumbent comparison;
- modified-Manhattan lower-bound pruning.

This removes floating-point epsilon logic from the mathematical proof boundary.

For a room packing, pruning is legal only when:

```text
scaled_F_LB > incumbent_scaled_F
```

Equality is deliberately retained because equal primary `F` can still improve mass, Elevator count or Corridor count.

The fail-fast invariant remains:

```text
scaled_F_LB <= scaled_F_exact
```

## Fixed-packing exhaustive oracle

`src/alters_base_planner/fixed_objective_oracle.py` is the independently exhaustive reference for one fixed room packing.

It enumerates distinct Corridor/Elevator selections allowed by the Stage-2 hard model. For every hard-feasible selection it:

1. extracts canonical `ModulePlacement` objects;
2. evaluates the exact installed-module graph with Dijkstra;
3. computes exact weighted `F`;
4. validates the modified-Manhattan lower bound;
5. ranks by `F`, total mass, Elevator count, Corridor count.

Its role is correctness validation, not production-scale solving.

## Fixed-packing source-aggregated flow production solver

`src/alters_base_planner/fixed_flow_objective_solver.py` is the production exact objective subproblem.

For one fixed room packing it reuses the Stage-2 hard-feasibility variables and adds one binary unit flow for every positive-weight unordered room pair over a conditional directed travel graph.

The graph reproduces the accepted distance rules:

```text
direct compatible endpoint adjacency = 0
one selected Corridor                  = +1
one selected Elevator                  = +1
intermediate transit-room crossing     = +width(room)
non-transit room                        = no internal side-to-side arc
vertical movement                       = adjacent same-x Elevators only
```

All source commodities share the same Corridor/Elevator decision variables. Infrastructure is therefore optimized jointly rather than independently for each pair.

### Lexicographic scalarization

The fixed-packing solver optimizes the accepted lexicographic order with a **single exact mixed-radix scalarized objective** under one remaining global deadline, replacing the previous four sequential optimization phases:

```text
1. exact scaled F
2. utility mass
3. Elevator count
4. Corridor count
```

The dominance weights are derived from valid finite bounds on the lower-order objectives taken from the fixed hard model's utility-anchor domain (`W_C = 1`, `W_E = C_max + 1`, `W_M = E_max * W_E + C_max + 1`, `W_F = M_max * W_M + E_max * W_E + C_max + 1`), so the single linear objective is order-preserving with the lexicographic order and one CP-SAT solve is exactly equivalent to the sequential phases. Non-SOLVER room mass is constant for a fixed packing, so utility mass is exactly total Base mass up to a constant.

The proof is set only when CP-SAT returns `OPTIMAL` for that single scalarized objective; `lexicographic_optimum_proven=true` then also proves the exact `F` optimum. A feasible incumbent produced on timeout remains best-known for that packing and carries no optimality claim.

### Independent evaluator cross-check

Every returned infrastructure witness is evaluated independently by the existing Dijkstra graph evaluator.

The solver evaluates the primary source-flow expression directly with exact integer `CpSolver.value()` and independently reconstructs scaled `F` from `DistanceMetrics.pairwise_distances`. A disagreement between source-flow CP-SAT and Dijkstra raises an internal assertion. The complete scalarized expression is evaluated exactly and checked separately against the reconstructed `(F, mass, Elevator, Corridor)` tuple.

Model/evaluator disagreement is an internal correctness defect, never ordinary infeasibility.

## Production room-packing master

`engine._solve_instances()` is the exact decomposition boundary used by `solve_plan()`.

The master:

1. enumerates legal non-overlapping SYSTEM/PLAYER room packings with CP-SAT;
2. removes only pure label permutations between identical module instances;
3. computes the shared exact integer objective definition;
4. computes the admissible exact integer modified-Manhattan bound;
5. prunes only a strict `scaled_F_LB > incumbent_scaled_F`;
6. calls the exact source-flow fixed-packing optimizer for every unpruned packing;
7. ranks proven/best-known candidates by scaled F, total Base mass, Elevator count and Corridor count;
8. excludes each examined packing with a no-good before continuing.

The centre/port-proximity master objective remains only a search-order surrogate. It does not affect legality or the accepted gameplay objective.

## Global proof semantics

Production sets:

```text
global_objective_optimum_proven = true
```

only if all of the following hold:

- a feasible incumbent exists;
- the room-packing master is exhausted;
- every unpruned fixed packing was solved to its full lexicographic optimum or proven infrastructure-infeasible;
- every pruned packing was excluded by the strict admissible exact integer lower bound;
- no global time limit interrupted the search;
- no layout-attempt limit interrupted the search.

Therefore a proof means that every physical room packing in the master domain is accounted for mathematically. A configured budget can prevent a proof without invalidating the feasible incumbent.

The current public result status remains `FEASIBLE`; proof state is represented separately by `global_objective_optimum_proven` so structural feasibility and mathematical optimality are not conflated.

## Global tiny-instance oracle

`src/alters_base_planner/global_objective_oracle.py` remains the deliberately exponential end-to-end reference solver.

It independently enumerates room packings and uses the exhaustive fixed-packing oracle. It validates:

- room-placement enumeration;
- identical-instance symmetry breaking;
- admissible strict lower-bound pruning;
- fixed-packing infrastructure optimization;
- complete global proof semantics.

It is not intended for full Base I-IV production workloads.

## Validation coverage

`tests/test_fixed_objective_oracle.py` independently brute-forces tiny utility-state spaces.

`tests/test_fixed_flow_objective_solver.py` cross-validates source-aggregated flow against the exhaustive fixed oracle for:

- direct zero-cost adjacency;
- Corridor-versus-Elevator tie-breaking;
- one- and two-Corridor horizontal routes;
- continuous vertical Elevator chains;
- intermediate transit-room width;
- Rapidium Ark non-transit behaviour;
- zero-weight modules that remain hard-connected;
- fixed-layout infeasibility;
- timeout/proof semantics.

`tests/test_global_objective_oracle.py` independently validates exhaustive global room + infrastructure optimization.

`tests/test_stage3_production_decomposition.py` now cross-checks the production decomposition against the global exhaustive oracle on a tiny known-optimum instance and separately verifies that a layout-attempt limit suppresses a false global proof.

At the Stage-3 production integration validation point, Ruff passes and the repository test suite reports **108 passing tests** on Python 3.11, 3.12 and 3.13.

## Result audit contract

Result JSON schema version 3 includes:

```text
objective_value
exact_integer_objective.scale
exact_integer_objective.scaled_value
exact_integer_objective.scaled_modified_manhattan_lower_bound
fixed_objective_optima_proven
room_packings_examined
connected_candidates_examined
manhattan_pruned_count
search_time_s
time_limit_reached
search_exhausted
global_objective_optimum_proven
```

Together with pair distances, pair contributions, module placements and mass data, these fields make the proof state inspectable rather than implicit.

## Remaining limitation: scalability, not mathematical semantics

The exhaustive oracles are intentionally exponential. The production source-aggregated formulation avoids infrastructure-selection enumeration and reduces its principal flow dimension from weighted room pairs to deterministic source rooms.

Stage 4 must therefore measure and improve performance without weakening exactness. Priority work:

1. establish representative Tier I-IV benchmark configurations;
2. record model size, fixed subproblem time, room packings examined, pruning rate, incumbent quality and proof completion;
3. profile graph/model construction and remove avoidable scans;
4. add mathematically safe candidate-domain reduction, symmetry breaking and bounds;
5. retain the exhaustive oracles as regression references for every optimization change.

A full-size run that times out remains useful as a best-known feasible solution, but it must never be described as globally optimal unless the proof conditions above were actually satisfied.
