# Optimization model

This document is the normative solver contract for `alters-base-planner`. `PROJECT_SYSTEM_REQUIREMENTS.md` is the higher-level project contract and takes precedence if the two documents ever diverge.

The planner has two logical layers:

1. **hard feasibility** — whether a complete Base layout is physically and topologically legal;
2. **gameplay optimization** — minimize the weighted sum of exact pairwise travel distances, then apply the accepted lexicographic tie-breakers.

Corridor and Elevator are solver-managed modules. The player supplies only the Base tier and counts of optional PLAYER modules.

The active production solver has completed Stage 2 hard-feasibility integration. It now uses an exact decomposition for hard constraints:

```text
CP-SAT SYSTEM/PLAYER room-packing master
        -> exact CP-SAT Corridor/Elevator hard-feasibility subproblem
        -> exact graph distance/F evaluation of the returned infrastructure witness
```

The old deterministic greedy post-router is no longer correctness-critical. The remaining major limitation is objective integration: the infrastructure subproblem currently returns one legal witness rather than minimizing true `F` over all legal infrastructure choices. Therefore `global_objective_optimum_proven` remains `false` until Stage 3 supplies an exact objective formulation/decomposition with valid bounds.

---

## 1. Canonical module domain

Every installable Base element is described by `ModuleSpec`, including Corridor and Elevator. Every concrete installed element is represented by `ModulePlacement`.

Placement ownership is explicit:

```text
SYSTEM  = baseline mandatory; injected exactly once
PLAYER  = optional; exact count comes from user configuration
SOLVER  = infrastructure; multiplicity and placement are solver decisions
```

`ModuleType` describes gameplay/category role and is independent from `PlacementAuthority`. For example, Kitchen and The Womb are `WORK` modules while also being SYSTEM-managed.

Corridor and Elevator are canonical catalogue entries rather than special geometry objects outside the domain model.

---

## 2. Coordinate and port model

The absolute Base grid uses top-left matrix coordinates:

```text
world (0,0) = top-left
x increases right
y increases down
```

Module-local port coordinates are floor-relative:

```text
local y = 0     -> module floor
local y = H - 1 -> module top
```

For a standard horizontally connected module of width `W`:

```text
LEFT  = (0, 0)
RIGHT = (W - 1, 0)
```

Standard ports are derived from width rather than duplicated manually in catalogue data.

Local-to-world conversion is:

```text
world_cell_x = placement.x + local_x
world_cell_y = placement.y + (H - 1 - local_y)
```

Horizontal port boundaries are:

```text
LEFT  edge_x = placement.x
RIGHT edge_x = placement.x + placement.width
edge_y       = world_cell_y
```

For a 1x1 module, LEFT and RIGHT occupy the same physical cell but remain distinct logical sides.

Verified exception: Radiation Repulsor uses top access (`local y = H - 1`) and is non-transit.

The external 2x1 utility anchor for a resolved horizontal port is:

```text
LEFT  port anchor = (edge_x - 2, edge_y)
RIGHT port anchor = (edge_x,     edge_y)
```

---

## 3. Hard constraints

A layout is structurally feasible only when every applicable rule below holds.

### H1 — Exact multiplicity and ownership

- exactly one instance of each baseline SYSTEM module;
- exactly the requested count of each PLAYER module;
- `Recycler <= 1`;
- `Rapidium Ark <= 5`;
- Corridor/Elevator counts are SOLVER decisions only.

Canonical configuration keys `corridor` and `elevator` are rejected from `rooms`. Unknown aliases are rejected as unknown keys.

### H2 — Exact Base mask

Every occupied module cell must be buildable (`1`) in the selected canonical Base CSV. No movable module may occupy `0` or `X`.

Canonical mobile-Base masks:

```text
src/alters_base_planner/data/base-size1.csv
src/alters_base_planner/data/base-size2.csv
src/alters_base_planner/data/base-size3.csv
src/alters_base_planner/data/base-size4.csv
```

The masks are asymmetric and must not be symmetrized, recentered or approximated.

Validated bounding boxes/core coordinates:

| Tier | Grid | Fixed 4x2 core |
|---|---:|---|
| I | 22x12 | x=8..11, y=6..7 |
| II | 26x14 | x=10..13, y=7..8 |
| III | 30x16 | x=12..15, y=8..9 |
| IV | 34x18 | x=14..17, y=9..10 |

### H3 — No overlap

Each physical grid cell may belong to at most one selected module, including every SYSTEM/PLAYER/Corridor/Elevator combination.

### H4 — Orientation

No rotation is allowed unless future verified game evidence explicitly supports it.

### H5 — Legal direct module connection

Two room-like modules connect directly only when resolved explicit ports:

- have the same `edge_y`;
- have the same `edge_x` boundary;
- use opposite sides (`LEFT` versus `RIGHT`).

Direct endpoint adjacency has travel cost `0`.

### H6 — Legal module-to-utility connection

A Corridor/Elevator may attach to a room-like module only at the exact external 2x1 anchor derived from a resolved port. The utility footprint must be buildable and unoccupied.

### H7 — Corridor semantics

Corridor is a solver-managed 2x1 module with mass 2. It provides horizontal connectivity and contributes travel cost `+1` when traversed.

### H8 — Elevator semantics

Elevator is a solver-managed 2x1 module with mass 2. It provides horizontal attachment and vertical connectivity only to immediately adjacent Elevator modules at the same `x`. Every traversed Elevator module contributes `+1`.

A shifted shaft is legal only through an actual connected horizontal transfer path on a shared floor. No community-inspired central-shaft rule is a hard constraint.

### H9 — Airlock-rooted connectivity

Every installed module must have at least one legal network connection and must be reachable from Airlock. Local degree/connectivity requirements do not replace global reachability.

### H10 — Non-transit modules

A module with `transit_allowed=false` may terminate a route but may not provide an internal LEFT-to-RIGHT/RIGHT-to-LEFT bridge.

Current non-transit modules:

```text
Radiation Repulsor
Rapidium Ark
```

They still must be reachable from Airlock.

### H11 — No floating utilities

Every selected Corridor/Elevator must belong to the Airlock-rooted network.

### H12 — Elevator continuity

Vertical travel requires a continuous chain of immediately adjacent Elevator modules. Each vertical graph edge requires Elevator selection at both adjacent anchors.

The exact distance evaluator independently checks the accepted vertical-coverage invariant; disagreement between the CP-SAT hard model and the evaluator is an internal error and must fail fast.

---

## 4. Structural feasibility versus journey feasibility

Mass accounting is mandatory for every structurally feasible mobile-Base layout:

```text
room_mass    = sum(mass of SYSTEM/PLAYER modules)
utility_mass = sum(mass of selected Corridor/Elevator modules)
total_mass   = room_mass + utility_mass

organics_required_for_journey = total_mass
journey_feasible = structural_feasible and total_mass <= organics_capacity
```

Since Corridor and Elevator each have mass 2:

```text
total_mass = sum(non-SOLVER module masses)
             + 2 * corridor_count
             + 2 * elevator_module_count
```

An overweight layout may remain useful as a structurally feasible diagnostic result, but it must never be reported as journey-feasible.

Mass is not part of the primary gameplay objective. It is the first deterministic tie-breaker after equal exact `F`.

---

## 5. Exact travel distance

Final distance is the shortest legal path in the installed module graph, not centroid distance and not raw Manhattan distance.

For endpoint modules A and B:

### D1 — Endpoint cost

The source and destination module widths do not contribute to their own pair distance.

### D2 — Direct endpoint adjacency

If compatible endpoint ports directly meet:

```text
d(A,B) = 0
```

### D3 — Corridor

Each traversed Corridor module contributes `+1`.

### D4 — Elevator

Each traversed Elevator module contributes `+1`.

A four-module vertical stack contributes 4 when all four modules are traversed.

### D5 — Intermediate transit module

If a route crosses ordinary transit module C from one side to the other:

```text
cost += width(C)
```

Example:

```text
A(4x1) | C(6x1) | B(8x1)

d(A,C) = 0
d(C,B) = 0
d(A,B) = 6
```

A 1x1 transit module costs 1 when crossed even though its logical LEFT/RIGHT ports occupy one physical cell.

### D6 — Non-transit module

No internal side-to-side graph edge is created. The module cannot be used as an intermediate bridge.

### D7 — Path algorithm

The evaluator uses Dijkstra or another provably equivalent non-negative shortest-path algorithm. Exact pair distances and contributions must remain reproducible and auditable.

---

## 6. Modified Manhattan lower bound

Modified Manhattan is an admissible lower bound/search heuristic only. It is never the final travel distance.

For endpoint ports on the same floor:

```text
horizontal_lb = ceil(abs(edge_x_a - edge_x_b) / 2)
```

For ports on different floors, compare external 2x1 utility anchors:

```text
horizontal_lb = ceil(abs(anchor_x_a - anchor_x_b) / 2)
vertical_lb   = abs(edge_y_a - edge_y_b) + 1
port_lb       = horizontal_lb + vertical_lb
```

For pair `(i,j)`:

```text
LB(i,j) = min(port_lb over compatible endpoint-port choices)
```

Weighted lower bound:

```text
F_LB = sum_{i<j} w_i * w_j * LB(i,j)
```

A room packing may be pruned when:

```text
F_LB > incumbent_exact_F
```

because the bound applies to every legal infrastructure network for that room packing.

The implementation must maintain the fail-fast invariant:

```text
F_LB <= F_exact
```

A violation is an internal model/evaluator error, not ordinary infeasibility.

---

## 7. Gameplay objective

Create all unordered pairs of installed non-SOLVER modules with positive traffic weight. Zero-weight modules remain subject to all hard constraints but do not create objective pairs.

For each pair:

```text
pair_score(i,j) = w_i * w_j * d(i,j)
F = sum_{i<j} pair_score(i,j)
```

Accepted lexicographic order:

```text
1. lower exact F
2. lower total Base mass
3. fewer Elevator modules
4. fewer Corridor modules
```

Traffic weights are planner heuristics stored in `src/alters_base_planner/data/usage_weights.json`; they are not hidden game constants.

Community strategies such as a central/right-side elevator shaft may guide search only. They must not invalidate legal layouts or compete with `F` as undocumented objectives.

---

## 8. Stage 2 production architecture — exact hard-feasibility decomposition

Stage 2 is complete and must be maintained.

### 8.1 Room-packing master

For each SYSTEM/PLAYER instance `i` and legal pre-enumerated placement candidate `c`:

```text
P[i,c] = 1 iff instance i uses candidate c
```

The master enforces:

```text
ExactlyOne(P[i,*])                  for every SYSTEM/PLAYER instance
AtMostOne(cell occupancy literals) for every Base cell
symmetry breaking                  for identical instances
```

Candidate enumeration removes placements that leave the buildable mask, overlap `X`, or require unsupported rotation.

The master uses a centre/port-proximity score only to order room packings. That score is a search surrogate, not gameplay objective `F`.

Each returned packing is excluded with a no-good before the next master solve, so packings are not repeated.

### 8.2 Exact Corridor/Elevator hard-feasibility subproblem

For one fixed room packing, `solve_fixed_layout_infrastructure()` compiles canonical `ModulePlacement` and resolved-port data into the reusable CP-SAT hard layer in `hard_constraints.py`.

The subproblem decides:

- Corridor Boolean selection on every legal 2x1 anchor;
- Elevator Boolean selection on every legal 2x1 anchor;
- at most one solver module per anchor;
- shared room/utility cell occupancy;
- direct room-port adjacency;
- exact room-to-utility anchor attachment;
- horizontal utility adjacency in complete 2-cell steps;
- vertical edges only between immediately stacked Elevators;
- non-transit terminal behaviour;
- Airlock-rooted single-commodity flow;
- one reachable access port for every non-root installed room;
- demand for every selected utility, preventing floating infrastructure.

The CP-SAT model is validated before solving.

For this fixed packing:

- `INFEASIBLE` means CP-SAT proved no legal Corridor/Elevator network exists under the accepted hard model;
- `UNKNOWN` due budget is reported as time-limit/unknown, never silently converted to infeasibility;
- a feasible solution yields a legal infrastructure witness represented with canonical `ModulePlacement` objects.

The subproblem deliberately has **no gameplay objective**. False-first variable hints may guide SAT search toward sparse infrastructure, but hints are not constraints and do not establish any optimization property.

### 8.3 Exact evaluator cross-check

A feasible hard witness is passed to the exact graph evaluator. If the CP-SAT hard model claims feasibility but the exact evaluator rejects connectivity/vertical semantics, the planner raises an internal assertion rather than hiding the mismatch as an infeasible candidate.

### 8.4 What Stage 2 proves — and what it does not

This architecture removes heuristic routing from hard-feasibility correctness. If a fixed room packing is proven infeasible by the subproblem, another untried greedy route cannot make it feasible.

However, a fixed packing can have many legal infrastructure networks with different exact distances and mass/tie-break values. Stage 2 evaluates one returned hard-feasible witness. It therefore does **not** establish the best `F` for that fixed packing and cannot establish the global optimum of the complete problem.

Accordingly:

```text
global_objective_optimum_proven = false
```

remains mandatory in the current architecture.

---

## 9. Stage 3 exact-objective target

Stage 3 must optimize true `F` over infrastructure alternatives rather than merely evaluate one satisfiable witness.

Acceptable target architectures are:

1. one integrated exact formulation; or
2. an exact decomposition with valid lower bounds and a mathematically valid optimality proof.

The exact objective solver/decomposition must cover:

- SYSTEM/PLAYER/SOLVER placement;
- occupancy and legal ports;
- Corridor/Elevator selection;
- Airlock-rooted connectivity;
- non-transit behaviour;
- Elevator continuity;
- exact shortest-path/travel-cost semantics or a proven equivalent;
- exact weighted objective `F`;
- lexicographic mass/Elevator/Corridor tie-breakers;
- lower/upper bounds sufficient to prove optimality when search completes.

Only then may the project set:

```text
global_objective_optimum_proven = true
```

and only for runs whose configured search has actually established that proof.

A high-value Stage-3 direction is an exact master/subproblem objective decomposition: use admissible room-placement lower bounds, solve or enumerate legal infrastructure networks exactly for promising packings, and return a certified bound together with the incumbent. Any formulation must be validated against exhaustive enumeration on tiny instances before being trusted on full Base tiers.

---

## 10. Configuration and validation

Runtime validation must be at least as strict as `config/plan.schema.json`.

Reject:

- missing `base_tier` or `rooms`;
- unsupported tiers;
- unknown top-level, solver or output fields;
- SYSTEM or SOLVER keys in player room counts;
- unknown module keys;
- booleans/fractions/negative counts;
- verified count-limit violations;
- invalid/non-finite/non-positive solver budgets;
- unsupported objectives;
- empty output paths.

Programmatic constructors must also enforce essential invariants so callers cannot bypass correctness by skipping the JSON loader.

Internal mathematical/model errors must fail fast and must not be hidden as ordinary infeasibility.

---

## 11. Search budget and diagnostics

`solver.time_limit_s` is one global wall-clock budget for the complete planning call. The infrastructure subproblem receives only the remaining global budget; it does not receive a fresh full budget per packing.

Persist at least:

```text
room_packings_examined
connected_candidates_examined
manhattan_pruned_count
search_time_s
time_limit_reached
search_exhausted
```

A feasible incumbent may coexist with `time_limit_reached=true`. Such a result is best-known feasible, not proof of global optimality.

Current result statuses include:

```text
FEASIBLE
TIME_LIMIT
INFEASIBLE
NO_CONNECTED_LAYOUT
```

`NO_CONNECTED_LAYOUT` must state whether the room-packing search was exhausted or an attempt/time budget stopped the search.

---

## 12. Required output and audit invariants

Every feasible result must report at least:

```text
objective_value / weighted_distance_score
modified_manhattan_lower_bound
average_pair_distance
weighted_average_pair_distance
pairwise_distances
pairwise_contributions
room_usage_weights
resolved ports
elevator_module_count
elevator_shaft_count
corridor_count
room_mass
utility_mass
total_base_mass
organics_required_for_journey
organics_tank_capacity
capacity_margin
journey feasibility
geometry source / verification
global_objective_optimum_proven
search diagnostics
```

Every run, including failure/time-limit outcomes, persists machine-readable JSON diagnostics. PNG/SVG are emitted for feasible layouts.

Audit invariants include:

```text
F = sum(pairwise_contributions.values())
F_LB <= F_exact
all installed modules reachable from Airlock
all selected solver modules reachable from Airlock
no selected footprints overlap
```

If the CP-SAT hard-feasibility witness and the exact evaluator disagree, fail fast.

---

## 13. Model validation and performance discipline

Every CP-SAT model must pass `CpModel.validate()` before solving.

Correctness constraints must never be replaced by arbitrary penalties or community-layout assumptions.

Performance work should focus on mathematically safe reductions:

- candidate-domain reduction;
- identical-instance symmetry breaking;
- admissible lower bounds;
- indexed graph construction rather than repeated scans;
- decomposition cuts that preserve exactness;
- deterministic benchmark cases where practical.

The all-placement integrated hard layer may be substantially larger than the fixed-packing subproblem. Before Stage 3 relies on a larger joint model, profile graph/model construction and remove avoidable quadratic scans without changing semantics.
