# Optimization model

This document is the normative mathematical and solver contract for `alters-base-planner`. `PROJECT_SYSTEM_REQUIREMENTS.md` is the higher-level project contract and takes precedence if the two ever diverge.

The planner has two inseparable correctness layers:

1. **hard feasibility** — the complete Base layout is physically and topologically legal;
2. **gameplay optimization** — minimize the weighted sum of exact pairwise travel distances and then the accepted lexicographic tie-breakers.

Corridor and Elevator are solver-managed modules. The player supplies only the Base tier and exact counts of optional PLAYER modules.

The production architecture is now an exact objective decomposition:

```text
CP-SAT SYSTEM/PLAYER room-packing master
        -> exact integer modified-Manhattan lower bound
        -> exact fixed-packing pair-flow CP-SAT
             hard Corridor/Elevator topology
             exact weighted travel F
             mass -> Elevators -> Corridors
        -> independent exact Dijkstra evaluator
        -> exact integer global incumbent comparison
```

A run is globally proven optimal only when this decomposition accounts for the complete room-packing search domain. Time or attempt limits preserve best-known feasible semantics.

---

## 1. Canonical module domain

Every installable Base element is described by `ModuleSpec`; every concrete installed element by `ModulePlacement`.

Placement ownership:

```text
SYSTEM  = baseline mandatory; injected exactly once
PLAYER  = optional; exact count comes from user configuration
SOLVER  = infrastructure; multiplicity and placement are optimizer decisions
```

`ModuleType` is independent from `PlacementAuthority`. Corridor and Elevator are canonical catalogue entries, not geometry objects outside the domain model.

---

## 2. Coordinates and ports

Absolute Base coordinates:

```text
(0,0) = top-left
x increases right
y increases down
```

Module-local ports are floor-relative:

```text
local y = 0     -> floor
local y = H - 1 -> top
```

Standard horizontal ports for width `W`:

```text
LEFT  = (0, 0)
RIGHT = (W - 1, 0)
```

Local-to-world conversion:

```text
world_cell_x = placement.x + local_x
world_cell_y = placement.y + (H - 1 - local_y)
```

Horizontal port boundaries:

```text
LEFT  edge_x = placement.x
RIGHT edge_x = placement.x + placement.width
edge_y       = world_cell_y
```

For a 1x1 module, LEFT and RIGHT share one physical cell but remain distinct logical sides.

Verified exception: Radiation Repulsor uses top access (`local y = H - 1`) and is non-transit.

The external 2x1 utility anchor for a resolved horizontal port is:

```text
LEFT  = (edge_x - 2, edge_y)
RIGHT = (edge_x,     edge_y)
```

---

## 3. Hard constraints

A layout is structurally feasible only when all applicable rules hold.

### H1 — Multiplicity and ownership

- exactly one of every baseline SYSTEM module;
- exactly the requested count of every PLAYER module;
- Recycler <= 1;
- Rapidium Ark <= 5;
- Corridor/Elevator multiplicity is SOLVER-controlled only.

SYSTEM and SOLVER keys are rejected from player room counts.

### H2 — Exact Base mask

Every occupied cell must be buildable (`1`) in the selected canonical Base CSV. No movable module may occupy `0` or `X`.

```text
src/alters_base_planner/data/base-size1.csv
src/alters_base_planner/data/base-size2.csv
src/alters_base_planner/data/base-size3.csv
src/alters_base_planner/data/base-size4.csv
```

The masks are asymmetric and must not be symmetrized or recentered.

| Tier | Grid | Fixed 4x2 core |
|---|---:|---|
| I | 22x12 | x=8..11, y=6..7 |
| II | 26x14 | x=10..13, y=7..8 |
| III | 30x16 | x=12..15, y=8..9 |
| IV | 34x18 | x=14..17, y=9..10 |

### H3 — No overlap

Each physical grid cell belongs to at most one selected SYSTEM/PLAYER/Corridor/Elevator module.

### H4 — Orientation

No rotation unless future verified game evidence explicitly supports it.

### H5 — Direct room connection

Two room-like modules connect directly only when resolved explicit ports have the same `edge_x`, the same `edge_y` and opposite sides. Direct compatible endpoint adjacency has travel cost 0.

### H6 — Room-to-utility connection

A Corridor/Elevator may attach to a room-like module only at the exact external 2x1 anchor derived from a resolved port. The utility footprint must itself be legal and unoccupied.

### H7 — Corridor

Corridor is a solver-managed 2x1 module of mass 2. It provides horizontal connectivity and contributes travel cost +1 when traversed.

### H8 — Elevator

Elevator is a solver-managed 2x1 module of mass 2. It provides horizontal attachment plus vertical connectivity only between immediately adjacent Elevator modules at the same x. Every traversed Elevator contributes +1.

A shifted shaft is legal only through a real horizontal transfer path on a shared floor. No central-shaft community preference is a hard constraint.

### H9 — Airlock-rooted connectivity

Every installed module has at least one legal network connection and is reachable from Airlock. Local degree conditions never replace global reachability.

### H10 — Non-transit modules

A module with `transit_allowed=false` may terminate a route but has no internal side-to-side bridge.

Current non-transit modules:

```text
Radiation Repulsor
Rapidium Ark
```

They still must be Airlock-reachable.

### H11 — No floating utilities

Every selected Corridor/Elevator belongs to the Airlock-rooted network.

### H12 — Elevator continuity

Every vertical graph edge requires selected Elevator modules at both immediately adjacent anchors. The exact evaluator independently checks accepted vertical semantics; disagreement with the CP-SAT hard model is an internal error.

---

## 4. Structural versus journey feasibility

```text
room_mass    = sum(SYSTEM/PLAYER module masses)
utility_mass = sum(selected Corridor/Elevator masses)
total_mass   = room_mass + utility_mass

organics_required_for_journey = total_mass
journey_feasible = structural_feasible and total_mass <= organics_capacity
```

Because Corridor and Elevator each have mass 2:

```text
total_mass = sum(non-SOLVER masses)
             + 2 * corridor_count
             + 2 * elevator_module_count
```

Mass is not the primary objective. It is the first tie-breaker after equal exact F.

---

## 5. Exact travel distance

Final distance is shortest legal path distance in the installed module graph.

```text
source endpoint module          = 0
destination endpoint module     = 0
direct compatible adjacency     = 0
one traversed Corridor          = +1
one traversed Elevator          = +1
intermediate transit module C   = +width(C)
non-transit module              = no internal side-to-side edge
```

Example:

```text
A(4x1) | C(6x1) | B(8x1)

d(A,C) = 0
d(C,B) = 0
d(A,B) = 6
```

The independent evaluator uses Dijkstra or a provably equivalent non-negative shortest-path algorithm. Pair distances and contributions must be reproducible and auditable.

---

## 6. Modified-Manhattan lower bound

Modified Manhattan is an admissible search lower bound only, never final distance.

Same floor:

```text
horizontal_lb = ceil(abs(edge_x_a - edge_x_b) / 2)
```

Different floors:

```text
horizontal_lb = ceil(abs(anchor_x_a - anchor_x_b) / 2)
vertical_lb   = abs(edge_y_a - edge_y_b) + 1
port_lb       = horizontal_lb + vertical_lb
```

For pair `(i,j)`:

```text
LB(i,j) = min(port_lb over compatible endpoint-port choices)
```

Weighted bound:

```text
F_LB = sum(i<j) w_i * w_j * LB(i,j)
```

The exact objective layer converts this to the same integer scale as F:

```text
scaled_F    = scale * F
scaled_F_LB = scale * F_LB
```

A room packing may be pruned only when:

```text
scaled_F_LB > incumbent_scaled_F
```

Equality cannot be pruned because the packing may still improve later lexicographic tie-breakers.

Fail-fast invariant:

```text
scaled_F_LB <= scaled_F_exact
```

---

## 7. Gameplay objective

All unordered pairs of installed non-SOLVER modules with positive traffic weight contribute:

```text
pair_score(i,j) = w_i * w_j * d(i,j)
F = sum(i<j) pair_score(i,j)
```

Zero-weight modules remain subject to every hard constraint but create no objective pairs.

Accepted lexicographic order:

```text
1. lower exact F
2. lower total Base mass
3. fewer Elevator modules
4. fewer Corridor modules
```

Traffic weights come from `src/alters_base_planner/data/usage_weights.json` and are planner heuristics, not hidden game constants.

No undocumented soft objective may compete with this order. Community layout strategies may guide search only.

### 7.1 Exact coefficient scaling

`objective.py` interprets each documented decimal traffic weight with exact rational arithmetic and chooses a common denominator scale. Each pair obtains a positive integer coefficient.

The same `ScaledObjective` is shared by the pair-flow optimizer, Dijkstra reconstruction, lower-bound calculation and global incumbent ranking. The mathematical proof boundary therefore uses integer arithmetic rather than floating-point epsilon comparisons.

---

## 8. Stage 2 foundation — exact hard feasibility

Stage 2 remains a maintained correctness layer.

For each SYSTEM/PLAYER instance i and placement candidate c:

```text
P[i,c] = 1 iff instance i uses candidate c
```

The master enforces exactly one placement per instance, at-most-one room occupancy per Base cell and safe identical-instance symmetry breaking.

For a fixed room packing, the reusable hard model decides Corridor/Elevator selection and enforces:

- canonical 2x1 utility anchors;
- shared room/utility no-overlap;
- direct room-port adjacency;
- exact room-to-utility anchor compatibility;
- horizontal utility adjacency in full 2-cell steps;
- vertical edges only between immediately stacked Elevators;
- non-transit terminal behaviour;
- Airlock-rooted single-commodity flow;
- one reachable access port for every non-root installed room;
- demand for every selected utility, preventing floating infrastructure.

`INFEASIBLE` is a proof for that fixed room packing. `UNKNOWN` remains time-limited/unknown and is never relabelled infeasible.

The original Stage-2 `solve_fixed_layout_infrastructure()` has no gameplay objective and remains useful as a hard-feasibility component/test boundary. Production Stage 3 adds the exact objective on top of the same accepted hard semantics.

---

## 9. Stage 3 production architecture — exact objective decomposition

Stage 3 is implemented and must be maintained.

### 9.1 Room-packing master

Production `solve_plan()` expands the canonical SYSTEM/PLAYER instance set and calls the exact decomposition master.

The master:

1. enumerates legal room packings with CP-SAT;
2. uses centre/port proximity only as a search-order surrogate;
3. excludes each returned packing with a no-good;
4. removes only pure label symmetry between identical instances;
5. computes the exact integer modified-Manhattan lower bound;
6. prunes only strict `scaled_F_LB > incumbent_scaled_F`;
7. sends every unpruned packing to the fixed-packing exact objective subproblem.

The search-order surrogate has no correctness or objective meaning.

### 9.2 Fixed-packing pair-flow subproblem

`solve_fixed_layout_flow_objective()` shares the Stage-2 Corridor/Elevator selection variables and hard constraints, then adds a conditional directed travel graph and one binary unit flow per positive-weight room pair.

Arc costs reproduce the accepted distance semantics. All pair flows share one infrastructure selection.

The fixed packing is optimized in proof-preserving phases under the remaining global deadline:

```text
1. exact scaled F
2. utility mass
3. Elevator count
4. Corridor count
```

Room mass is constant for a fixed packing, therefore minimizing utility mass in phase 2 is equivalent to minimizing total Base mass.

`lexicographic_optimum_proven=true` requires all four phases to return CP-SAT `OPTIMAL`.

### 9.3 Independent exact evaluator

Every feasible infrastructure result is evaluated by the Dijkstra graph evaluator. The exact scaled objective is reconstructed from evaluator pair distances and compared with the CP-SAT optimum. Any disagreement fails fast.

The exact lower bound is also checked against the exact evaluated objective.

### 9.4 Global incumbent ranking

Across room packings, candidates are compared by:

```text
(
    scaled_objective_value,
    total_mass,
    elevator_module_count,
    corridor_count,
)
```

The scale and pair coefficients must remain identical across room packings for one planning request. A change indicates an internal modelling error.

### 9.5 Global proof condition

Production may set:

```text
global_objective_optimum_proven = true
```

only when:

- a feasible incumbent exists;
- the room-packing master reaches `INFEASIBLE` after all no-goods/cuts, proving search exhaustion;
- every unpruned packing was solved to its full fixed-packing lexicographic optimum or proven infrastructure-infeasible;
- every pruned packing had strict exact integer lower bound above the incumbent primary objective;
- no time limit interrupted the search;
- no layout-attempt limit interrupted the search.

A feasible result without all these conditions is best-known feasible, not globally proven.

---

## 10. Configuration and validation

Runtime validation must be at least as strict as `config/plan.schema.json`.

Reject:

- missing `base_tier` or `rooms`;
- unsupported tiers;
- unknown top-level, solver or output fields;
- SYSTEM or SOLVER keys in player counts;
- unknown module keys;
- booleans/fractions/negative counts;
- verified count-limit violations;
- invalid/non-finite/non-positive solver budgets;
- unsupported objectives;
- empty output paths.

Programmatic constructors must enforce essential invariants too. Internal mathematical errors fail fast and are not hidden as infeasibility.

---

## 11. Search budget and diagnostics

`solver.time_limit_s` is one global wall-clock budget. Every fixed-packing subproblem receives only the remaining budget.

`max_layout_attempts` is also a search-completeness limit. Hitting it prevents a global optimality proof even if every attempted packing was solved exactly.

Persist at least:

```text
room_packings_examined
connected_candidates_examined
fixed_objective_optima_proven
manhattan_pruned_count
search_time_s
time_limit_reached
search_exhausted
global_objective_optimum_proven
```

Current public result statuses include:

```text
FEASIBLE
TIME_LIMIT
INFEASIBLE
NO_CONNECTED_LAYOUT
```

Optimality is represented separately by the proof flag.

---

## 12. Required output and audit invariants

Result JSON schema version 2 records at least:

```text
objective_value / weighted_distance_score
objective_scale
scaled_objective_value
scaled_modified_manhattan_lower_bound
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

Audit invariants include:

```text
F = sum(pairwise_contributions.values())
scaled_F reconstructs exactly from pairwise_distances
scaled_F_LB <= scaled_F_exact
all installed modules reachable from Airlock
all selected solver modules reachable from Airlock
no selected footprints overlap
```

PNG/SVG are emitted for feasible layouts and preserve the project cell aspect ratio.

---

## 13. Reference oracles and performance discipline

The exhaustive fixed and global objective oracles are intentionally exponential and remain correctness/benchmark machinery.

The production pair-flow model is exact but can still be expensive. Its variable count grows with approximately the product of weighted room pairs and conditional graph arcs.

Stage 4 performance work must preserve semantics. Safe directions include:

- candidate-domain reduction with proof of equivalence;
- identical-instance symmetry breaking;
- stronger admissible bounds;
- indexed graph construction rather than repeated scans;
- valid decomposition cuts;
- deterministic benchmark cases;
- model-size/runtime instrumentation.

Every CP-SAT model must pass `CpModel.validate()` before solving. No performance optimization may replace a correctness constraint with an arbitrary penalty or undocumented layout assumption.

Any new reduction/cut should continue to match exhaustive known-optimum cases before entering the production correctness boundary.
