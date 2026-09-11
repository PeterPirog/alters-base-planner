# Optimization model

This document is the normative solver contract for `alters-base-planner`. `PROJECT_SYSTEM_REQUIREMENTS.md` remains the higher-level project contract and takes precedence if the two documents ever diverge.

The planner has two logical layers:

1. **hard feasibility constraints** — a layout is physically valid or rejected;
2. **one gameplay objective** — minimize the weighted sum of exact pairwise travel distances.

Corridor and Elevator are solver-managed modules. The player supplies only the Base tier and counts of optional PLAYER modules.

A critical implementation distinction remains in force: the active production solver still chooses SYSTEM/PLAYER placements first and generates solver infrastructure with a transitional post-router. Exact graph distances and the true objective `F` are then evaluated on the routed candidate. The current engine therefore does **not** prove the global optimum over the complete joint room + Corridor + Elevator problem.

---

## 1. Canonical module domain

Stage 1 unified the domain model.

Every installable Base element is described by `ModuleSpec`, including Corridor and Elevator. Every concrete installed element is represented by `ModulePlacement`. Placement ownership is explicit:

```text
SYSTEM  = baseline mandatory; injected exactly once
PLAYER  = optional; exact count comes from user configuration
SOLVER  = infrastructure; multiplicity and placement are solver decisions
```

`ModuleType` describes the gameplay/category role of a module and is independent from `PlacementAuthority`. For example, Kitchen and The Womb are `WORK` modules while also being SYSTEM-managed.

The current solver path is only **domain-unified**, not yet **optimization-unified**. Corridor/Elevator are canonical catalog modules and result placements, but their decision variables are not yet wired into the production `solve_plan()` model.

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

The standard ports are derived from width; they are not manually duplicated in the catalogue.

Local-to-world conversion is:

```text
world_cell_x = placement.x + local_x
world_cell_y = placement.y + (H - 1 - local_y)
```

The horizontal connection boundary is:

```text
LEFT  edge_x = placement.x
RIGHT edge_x = placement.x + placement.width
edge_y       = world_cell_y
```

For a 1x1 module, LEFT and RIGHT occupy the same physical cell but remain distinct logical sides.

Verified exception: Radiation Repulsor uses top access (`local y = H - 1`) and is non-transit.

A 2x1 solver utility anchor outside a resolved horizontal port is:

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

Canonical configuration keys `corridor` and `elevator` are therefore rejected from `rooms`. Non-canonical keys such as `corridors` or `elevators` are simply unknown configuration keys.

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

Each physical grid cell may belong to at most one selected module. This includes every combination of SYSTEM, PLAYER, Corridor and Elevator placements.

### H4 — Orientation

No rotation is allowed unless future verified game evidence explicitly supports it.

### H5 — Legal direct module connection

Two room-like modules connect directly only when resolved explicit ports:

- have the same `edge_y`;
- have the same `edge_x` boundary;
- use opposite sides (`LEFT` versus `RIGHT`).

Direct endpoint adjacency has travel cost `0`.

### H6 — Legal module-to-utility connection

A Corridor/Elevator may attach to a room-like module only at the exact external 2x1 anchor derived from a resolved port. The selected utility footprint must be buildable and unoccupied.

### H7 — Corridor semantics

Corridor is a solver-managed 2x1 module with mass 2. It provides horizontal connectivity and contributes travel cost `+1` when traversed.

### H8 — Elevator semantics

Elevator is a solver-managed 2x1 module with mass 2. It provides horizontal attachment and vertical connectivity only to immediately adjacent Elevator modules at the same `x` coordinate. Every traversed Elevator module contributes `+1`.

A shifted shaft is legal only through an actual connected horizontal transfer path on a shared floor; there is no community-inspired “central shaft” hard constraint.

### H9 — Airlock-rooted connectivity

Every installed module must have at least one legal connection and must be reachable from Airlock through the legal module graph. A local connection requirement does not replace global reachability.

### H10 — Non-transit modules

A module with `transit_allowed=false` may terminate a route but may not provide an internal LEFT-to-RIGHT/RIGHT-to-LEFT bridge.

Current non-transit modules:

```text
Radiation Repulsor
Rapidium Ark
```

They still must be reachable from Airlock.

### H11 — No floating utilities

Every selected Corridor/Elevator must itself belong to the Airlock-rooted network.

### H12 — Elevator continuity

Vertical movement requires a continuous chain of immediately adjacent Elevator modules. Any used multi-floor route must therefore contain legal Elevator coverage for every vertical step it traverses.

The legacy post-router/evaluator also validates its current floor-span continuity invariant. The Stage 2 integrated hard model must express the same accepted connectivity semantics directly through selected Elevator variables and legal transfer edges.

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

Since Corridor and Elevator each have mass 2, this is equivalent to:

```text
total_mass = sum(non-SOLVER module masses)
             + 2 * corridor_count
             + 2 * elevator_module_count
```

An overweight layout may remain useful as a **structurally feasible diagnostic result**, but it must never be reported as journey-feasible.

Mass is not part of the primary gameplay objective. It is the first deterministic tie-breaker after equal exact `F`.

---

## 5. Exact travel distance

Final distance is the shortest legal path in the installed module graph. It is not centroid distance and not raw Manhattan distance.

For endpoint modules A and B:

### D1 — Endpoint cost

The source and destination module widths do not contribute to their own pair distance.

### D2 — Direct endpoint adjacency

If compatible endpoint ports directly meet:

```text
d(A,B) = 0
```

### D3 — Corridor

Each traversed Corridor module contributes:

```text
+1
```

### D4 — Elevator

Each traversed Elevator module contributes:

```text
+1
```

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

A 1x1 transit module therefore costs 1 when crossed even though its logical LEFT/RIGHT ports occupy the same physical cell.

### D6 — Non-transit module

No internal side-to-side graph edge is created. The module cannot be used as an intermediate bridge.

### D7 — Path algorithm

The evaluator uses Dijkstra or an equivalent exact non-negative shortest-path algorithm. Exact pair distances and contributions must remain auditable and reproducible.

---

## 6. Modified Manhattan lower bound

Modified Manhattan is an admissible lower bound/search heuristic only. It is never the final travel distance.

For two endpoint ports on the same floor:

```text
horizontal_lb = ceil(abs(edge_x_a - edge_x_b) / 2)
```

For ports on different floors, compare their external 2x1 utility anchors:

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

A generated packing may be pruned when:

```text
F_LB > incumbent_exact_F
```

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

The accepted lexicographic optimization order is:

```text
1. lower exact F
2. lower total Base mass
3. fewer Elevator modules
4. fewer Corridor modules
```

Traffic weights are planner heuristics stored in `src/alters_base_planner/data/usage_weights.json`; they are not hidden game constants.

Community strategies such as a central/right-side elevator shaft may be used as search heuristics only. They must not invalidate a legal layout or compete with exact `F` as an undocumented soft objective.

---

## 8. Current production solver

The active `solve_plan()` implementation still uses the transitional architecture:

```text
CP-SAT SYSTEM/PLAYER placement
        -> deterministic post-router for SOLVER modules
        -> exact graph validation and distance evaluation
        -> exact F ranking of examined connected candidates
```

For each non-SOLVER instance `i` and legal pre-enumerated placement candidate `c`:

```text
P[i,c] = 1 iff instance i uses candidate c
```

The current CP-SAT model enforces:

```text
ExactlyOne(P[i,*])                  for every SYSTEM/PLAYER instance
AtMostOne(cell occupancy literals) for every Base cell
symmetry breaking                  for identical instances
```

Candidate generation removes placements that leave the buildable mask, overlap `X`, or require unsupported rotation.

The model also uses a centre/port-proximity ordering score. That score is a search surrogate only; it is **not** gameplay objective `F`.

`CpModel.validate()` must succeed before every solve.

The post-router currently selects one Corridor/Elevator network for a room packing. Consequently:

- a room packing can be rejected even if some different legal utility network might exist;
- utility placement is not jointly optimized with rooms;
- exact `F` is evaluated only after this routing choice;
- `global_objective_optimum_proven` must remain `false`.

---

## 9. Integrated hard-feasibility layer and Stage 2 target

`src/alters_base_planner/hard_constraints.py` contains the reusable CP-SAT hard-feasibility layer intended for Stage 2. It already models, on small/synthetic instances:

- exactly one placement candidate per required SYSTEM/PLAYER instance;
- Corridor/Elevator Boolean selection on legal 2x1 anchors;
- shared room/utility occupancy;
- direct room-port adjacency;
- exact room-to-utility anchor attachment;
- horizontal utility adjacency;
- vertical edges only through stacked Elevator selections;
- non-transit terminal behavior;
- Airlock-rooted single-commodity flow;
- demand for every installed room and every selected utility, preventing floating infrastructure.

This layer is **not yet the production solve path**. Stage 2 is complete only when the active planner uses an integrated hard-feasibility formulation (or a mathematically exact decomposition) and small known cases prove feasibility/infeasibility correctly.

Stage 2 must not deepen the greedy router. The next architectural move is to adapt production candidate enumeration to this hard-feasibility layer and then retire post-routing as correctness-critical infrastructure.

---

## 10. Stage 3 exact-objective target

After hard feasibility is integrated, Stage 3 must optimize true `F` rather than only evaluate it after a candidate has been chosen.

Acceptable target architectures are:

1. one joint exact formulation; or
2. an exact decomposition with valid lower bounds and a mathematically valid optimality proof.

The exact solver/decomposition must cover:

- SYSTEM/PLAYER/SOLVER placement;
- occupancy;
- legal ports;
- Corridor/Elevator selection;
- Airlock-rooted connectivity;
- terminal/non-transit behavior;
- Elevator continuity;
- exact shortest-path/travel-cost semantics or a proven equivalent;
- exact weighted objective `F`;
- lexicographic tie-breakers.

Only then may the project report:

```text
global_objective_optimum_proven = true
```

and only when the configured search has actually established the mathematical proof.

---

## 11. Configuration and validation

Runtime validation must be at least as strict as `config/plan.schema.json`.

Reject:

- missing `base_tier` or `rooms`;
- unsupported tiers;
- unknown top-level, solver or output fields;
- SYSTEM or SOLVER keys in player room counts;
- unknown module keys;
- booleans/fractions/negative room counts;
- verified count-limit violations;
- invalid/non-finite/non-positive solver budgets;
- unsupported objectives;
- empty output paths.

Programmatic constructors must also enforce essential invariants so callers cannot bypass correctness by skipping the JSON loader.

Internal mathematical/model errors must fail fast and must not be hidden as an infeasible result.

---

## 12. Search budget and diagnostics

`solver.time_limit_s` is one global wall-clock budget for the complete planning call, not a fresh budget for every CP-SAT iteration.

Persist at least:

```text
room_packings_examined
connected_candidates_examined
manhattan_pruned_count
search_time_s
time_limit_reached
search_exhausted
```

A feasible incumbent may coexist with `time_limit_reached=true`. Such a result is a best-known feasible layout, not proof of global optimality.

Current result statuses include:

```text
FEASIBLE
TIME_LIMIT
INFEASIBLE
NO_CONNECTED_LAYOUT
```

---

## 13. Required output and audit invariants

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

The project must continue to distinguish **best-known feasible** from **proven globally optimal** results until Stage 3 establishes an exact joint proof mechanism.
