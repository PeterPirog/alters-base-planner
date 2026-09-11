# The Alters Base Planner — Project System Requirements and Development Source of Truth

Status: **normative project-level specification**  
Repository: `PeterPirog/alters-base-planner`  
Primary implementation language: Python >= 3.11  
Optimization engine: Google OR-Tools CP-SAT

This file is the highest-level repository source of truth for product intent, accepted game/domain mechanics, mathematical semantics, solver requirements, development stages and acceptance criteria.

---

## 1. Purpose and authority

The repository shall implement a reliable optimization-based planner for the mobile Base in **The Alters**. The user selects the Base tier and counts of optional rooms. The planner automatically injects mandatory modules and determines the number and placement of Corridors and Elevators.

More detailed implementation documents (`docs/OPTIMIZATION_MODEL.md`, `docs/ROOM_DATA_AUDIT.md`, `docs/BASE_GEOMETRY_REFERENCE.md`) plus code/tests must remain consistent with this contract.

When verified evidence changes mechanics, do not silently change one layer. Update the evidence/audit material, this specification when the project contract changes, implementation and tests together.

Never invent missing game mechanics. Distinguish:

- **verified game/domain facts** — may define hard constraints;
- **project modelling decisions** — explicit abstractions/approximations;
- **heuristics** — may guide search but must not invalidate an otherwise legal layout;
- **unknown/provisional data** — must be labelled and never presented as verified.

The project is unofficial and must not claim access to hidden game constants unless independently verified.

---

## 2. Product goal

Given:

1. Base tier I, II, III or IV;
2. exact requested counts of optional PLAYER modules;
3. solver budget/configuration;

produce a layout that:

- fits the exact irregular Base mask;
- contains all baseline mandatory SYSTEM modules and exactly the requested PLAYER modules;
- contains solver-generated Corridor/Elevator modules as required;
- obeys module geometry, ports, connectivity, occupancy and special module rules;
- forms one legal network rooted at Airlock;
- computes exact travel distances;
- minimizes the accepted gameplay travel objective;
- reports Base Mass and Organics journey feasibility separately from structural feasibility;
- emits auditable JSON and graphical PNG/SVG output;
- clearly distinguishes a best-known feasible result from a proven global optimum.

The target architecture is one **joint exact optimizer**, or an **exact decomposition with valid bounds**, over module placement, solver infrastructure, connectivity and the true gameplay objective.

The current placement -> post-router -> exact-evaluation architecture is transitional and must not be deepened unnecessarily.

---

## 3. Coordinate systems and Base geometry

### 3.1 Global Base coordinates

```text
origin (0,0) = top-left
x increases right
y increases down
```

CSV semantics:

```text
0 = outside Base / unavailable
1 = buildable Base cell
X = immovable blocked core cell
```

The CSV masks are hard geometry. They MUST NOT be symmetrized, centred, smoothed or inferred from an ideal circle.

A grid cell corresponds approximately to 2 m width × 3 m height in the supplied spatial analysis; optimization uses module/grid travel units, not metres.

### 3.2 Canonical Base I-IV masks

```text
src/alters_base_planner/data/base-size1.csv
src/alters_base_planner/data/base-size2.csv
src/alters_base_planner/data/base-size3.csv
src/alters_base_planner/data/base-size4.csv
```

Validated dimensions, fixed 4x2 core and current Organics capacity:

| Tier | Width x Height | Core coordinates | Organics capacity |
|---|---:|---|---:|
| I | 22 x 12 | x=8..11, y=6..7 | 300* |
| II | 26 x 14 | x=10..13, y=7..8 | 450 |
| III | 30 x 16 | x=12..15, y=8..9 | 700 |
| IV | 34 x 18 | x=14..17, y=9..10 | 800 |

`*` Tier-I value 300 is the current planner value. The supplied project analysis validates 450/700/800 more directly than the Tier-I numeric value; Tier-I provenance must remain explicit until stronger game-exact evidence is available.

The core is intentionally asymmetric relative to the rectangular grid. Do not force it to the geometric centre.

---

## 4. Canonical Module domain model

### 4.1 Abstraction

The canonical abstraction is **Module**, not separate room/utility geometry types. A module has at least:

```text
key/name
width, height
mass
occupied cells
ports
transit behaviour
traffic/visit weight
count limits
placement authority
```

Placement authority is:

```text
SYSTEM  = baseline mandatory; injected automatically
PLAYER  = optional; exact count selected by the user
SOLVER  = generated infrastructure; count/placement chosen by optimization
```

`ModuleType` is independent from placement authority. Authority says **who decides existence**; module type says **what the module is**.

Corridor and Elevator are SOLVER modules and are never user count inputs.

### 4.2 Baseline mandatory SYSTEM modules

Exactly one of each:

| Key | Module | Size | Mass |
|---|---|---:|---:|
| `airlock` | Airlock | 4x1 | 4 |
| `captains_cabin` | Captain's Cabin | 4x1 | 4 |
| `command_center` | Command Center | 4x1 | 4 |
| `communication_room` | Communication Room | 4x1 | 4 |
| `kitchen` | Kitchen | 5x1 | 4 |
| `machinery` | Machinery | 4x1 | 4 |
| `quantum_computer` | Quantum Computer | 4x2 | 8 |
| `womb` | The Womb | 5x1 | 4 |

The player MUST NOT configure these counts or set them to zero. They are injected automatically.

This is the **planner baseline**, not a claim that every module physically exists at minute zero of every story state. Progression-aware modelling belongs to a later explicit `act/game_state` stage.

### 4.3 PLAYER catalogue

| Key | Module | Size | Mass | Special rule |
|---|---|---:|---:|---|
| `ark_sarcophagus` | Ark Sarcophagus | 4x2 | 13 | passive objective weight |
| `contemplation_room` | Contemplation Room | 6x1 | 20 | — |
| `dormitory` | Dormitory | 6x1 | 8 | — |
| `gamers_den` | Gamer's Den | 5x1 | 14 | — |
| `greenhouse` | Greenhouse | 8x1 | 16 | — |
| `gym` | Gym | 6x1 | 20 | — |
| `infirmary` | Infirmary | 6x1 | 16 | — |
| `large_storage` | Large Storage | 8x2 | 140 | passive traffic |
| `materializer` | Materializer | 4x3 | 24 | standard floor ports |
| `medium_storage` | Medium Storage | 8x1 | 65 | passive traffic |
| `park_with_bench` | Park with Bench | 6x1 | 20 | — |
| `personal_cabin` | Personal Cabin | 3x1 | 10 | — |
| `radiation_repulsor` | Radiation Repulsor | 2x3 | 16 | **top access**, non-transit |
| `rapidium_ark` | Rapidium Ark | 4x2 | 32 | non-transit, max 5 |
| `recycler` | Recycler | 2x1 | 2 | max 1 |
| `refinery` | Refinery | 4x1 | 8 | — |
| `research_lab` | Research Lab | 4x1 | 8 | — |
| `small_storage` | Small Storage | 2x2 | 28 | passive traffic |
| `social_room` | Social Room | 6x1 | 14 | — |
| `workshop` | Workshop | 4x1 | 8 | — |

### 4.4 SOLVER modules

| Module | Size | Mass | Authority |
|---|---:|---:|---|
| Corridor | 2x1 | 2 | SOLVER |
| Elevator | 2x1 | 2 | SOLVER |

Their multiplicity and placement are optimization results.

---

## 5. Port model

### 5.1 Local coordinates

Local port coordinates are floor-relative:

```text
local y = 0     => floor
local y = H - 1 => top
x increases right
```

For every standard horizontally connected module of width `W`:

```text
LEFT  = (0, 0)
RIGHT = (W - 1, 0)
```

Standard ports MUST be derived from width, not redundantly stored per module.

For a 1x1 module, LEFT and RIGHT share physical local cell `(0,0)` but remain separate logical sides.

### 5.2 Local-to-world transform

```text
world_cell_x = module.x + local_x
world_cell_y = module.y + (H - 1 - local_y)
```

A standard high module is therefore entered at its physical floor, never through its ceiling or centroid.

### 5.3 Verified exception

Radiation Repulsor is 2x3 and connects from its **top**, so its access uses `local y=H-1` rather than floor `y=0`.

Do not generalize exceptions without evidence.

### 5.4 Utility semantics

In the canonical model:

- Corridor provides horizontal LEFT/RIGHT connectivity;
- Elevator provides horizontal attachment plus vertical UP/DOWN connectivity to immediately adjacent stacked Elevator modules.

Transitional implementation details may remain during migration, but target semantics must be expressible through module/port compatibility rather than ad-hoc duplicated geometry models.

---

## 6. Connectivity and transit semantics

Every installed module must belong to one Base network rooted at Airlock.

For every installed required module:

```text
at least one legal port connects to the network
reachable(Airlock, module) = true
```

Legal graph connections may include:

```text
Room-like module <-> Room-like module
Room-like module <-> Corridor
Room-like module <-> Elevator
Corridor <-> Corridor
Corridor <-> Elevator
Elevator <-> Elevator (horizontal and legal vertical stacking)
```

`transit_allowed=false` means a module may be reached as a terminal but its opposite horizontal ports are not internally joined for through-traffic.

Current non-transit modules:

- Radiation Repulsor;
- Rapidium Ark.

They are not exempt from Base connectivity.

Every generated Corridor/Elevator must itself be part of the Airlock-rooted network. Floating infrastructure is invalid.

---

## 7. Hard constraints

A candidate is structurally feasible only if all applicable rules hold.

### H1 — Exact multiplicity

- exactly one of each SYSTEM module;
- exactly the requested count of each PLAYER module;
- `Recycler <= 1`;
- `Rapidium Ark <= 5`;
- Corridor/Elevator multiplicity decided only by the solver.

### H2 — Base-mask legality

Every occupied cell of every module must be `1` in the selected Base CSV. No movable module may occupy `0` or `X`.

### H3 — No overlap

Each physical grid cell may be occupied by at most one installed module, including every room/Corridor/Elevator combination.

### H4 — Orientation

No rotation unless verified game evidence explicitly supports it.

### H5 — Legal ports

Connectivity exists only through compatible resolved ports/utility anchors. Ordinary high modules connect at floor level; verified top-access exceptions remain explicit.

### H6 — Local connection requirement

Every installed module required in the Base network has at least one active legal connection. This strengthens but does not replace global reachability.

### H7 — Global Airlock reachability

All installed modules must be reachable from Airlock through the legal module graph.

### H8 — Non-transit behaviour

A non-transit module may terminate a route but may not be used as an intermediate side-to-side bridge.

### H9 — Corridor semantics

Corridor is 2x1, solver-managed, horizontal, must fit the Base, avoid overlaps, connect legally and belong to the reachable network.

### H10 — Elevator semantics and continuity

Elevator is 2x1, solver-managed. Vertical movement exists only between immediately adjacent compatible Elevator modules. Each used vertical level is represented by an Elevator module.

A shifted shaft is legal only through a real transfer path on a shared floor. Community preference for a central shaft is not a hard rule.

### H11 — No floating utilities

Every selected Corridor/Elevator must reach the Airlock-rooted Base network.

### H12 — Journey mass semantics

For the mobile Base:

```text
total_base_mass = sum(module masses)
organics_required_for_journey = total_base_mass
```

Since each Corridor/Elevator mass is 2, this is equivalent to:

```text
sum(non-SOLVER masses) + 2*corridor_count + 2*elevator_module_count
```

Report separately:

- `structural_feasible` — valid geometry/network;
- `journey_feasible` — structural feasible AND `total_base_mass <= organics_capacity`.

An overweight structurally valid diagnostic layout may be rendered if clearly labelled, but must never be reported as journey-feasible.

---

## 8. Exact travel-distance semantics

Final `d(i,j)` is shortest legal path distance in the module graph, not centroid distance and not raw Manhattan distance.

### D1 — Endpoint modules

Source and destination module widths contribute `0` to their own pair distance.

### D2 — Direct compatible endpoint adjacency

```text
d(A,B) = 0
```

### D3 — Corridor

Each traversed Corridor module contributes `+1`.

### D4 — Elevator

Each traversed Elevator module contributes `+1`. A four-module stack contributes 4 if all four modules are traversed.

### D5 — Intermediate transit module

If a route crosses transit module C from one side to the other:

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

A 1x1 transit module costs 1 when crossed even though LEFT/RIGHT share one physical cell.

### D6 — Non-transit module

No internal side-to-side graph edge is created.

### D7 — Exact path algorithm

Use Dijkstra or an equivalent exact non-negative shortest-path algorithm. Exact distances must be reproducible and auditable.

---

## 9. Modified Manhattan lower bound

Modified Manhattan is an admissible lower bound/search heuristic only, never the final distance.

Same-floor endpoint ports:

```text
horizontal_lb = ceil(abs(edge_x_a - edge_x_b) / 2)
```

Cross-floor endpoint ports use external 2x1 utility anchors:

```text
horizontal_lb = ceil(abs(anchor_x_a - anchor_x_b) / 2)
vertical_lb   = abs(edge_y_a - edge_y_b) + 1
port_lb       = horizontal_lb + vertical_lb
```

For room pair `(i,j)`:

```text
LB(i,j) = min(port_lb over compatible endpoint-port choices)
```

Weighted lower bound:

```text
F_LB = sum_{i<j} w_i * w_j * LB(i,j)
```

It is legal to prune when:

```text
F_LB > incumbent_exact_F
```

The invariant:

```text
F_LB <= F_exact
```

must hold. A violation is an internal solver/model bug and must fail fast.

---

## 10. Gameplay objective and tie-breakers

For all unordered pairs of installed positive-weight non-SOLVER modules:

```text
pair_score(i,j) = w_i * w_j * d(i,j)
F = sum_{i<j} pair_score(i,j)
```

Zero-weight modules remain subject to every hard constraint; they simply do not create objective pairs.

Default traffic weights are gameplay-informed planner parameters, not hidden game constants:

| Module | Weight |
|---|---:|
| Airlock | 1.00 |
| Workshop | 0.90 |
| Kitchen | 0.80 |
| Dormitory | 0.80 |
| Captain's Cabin | 0.70 |
| Research Lab | 0.65 |
| Social Room | 0.60 |
| Greenhouse | 0.55 |
| Refinery | 0.55 |
| Command Center | 0.35 |
| Machinery | 0.35 |
| Communication Room | 0.25 |
| Infirmary | 0.25 |
| Contemplation Room | 0.25 |
| Personal Cabin | 0.25 |
| Gym | 0.20 |
| Gamer's Den | 0.20 |
| Park with Bench | 0.15 |
| Materializer | 0.10 |
| Quantum Computer | 0.10 |
| The Womb | 0.10 |
| Recycler | 0.00 |
| Radiation Repulsor | 0.00 |
| Small/Medium/Large Storage | 0.00 |
| Rapidium Ark | 0.00 |
| Ark Sarcophagus | 0.00 |
| Corridor / Elevator | 0.00 |

Weights remain editable and auditable. Future empirical calibration from observed transition counts is desirable.

Accepted lexicographic optimization order:

```text
1. lower exact F
2. lower total Base mass
3. fewer Elevator modules
4. fewer Corridor modules
```

Do not introduce an undocumented competing soft objective.

Community “central elevator” strategies may guide search but must not become correctness constraints without game-mechanics evidence.

---

## 11. OR-Tools / solver correctness requirements

### 11.1 Current implementation state

**Stage 1 domain unification is complete.** `ModuleSpec` is the canonical definition for SYSTEM/PLAYER/SOLVER modules; `ModulePlacement` represents every concrete installed module, including Corridor and Elevator; configuration ownership is derived from `PlacementAuthority`.

This does **not** mean the active optimization is joint yet.

The production CP-SAT model still solves the SYSTEM/PLAYER placement subproblem using pre-enumerated legal candidates:

```text
P[i,c] = 1 iff module instance i uses candidate placement c
```

Required current constraints:

```text
ExactlyOne(P[i,*])                  for every SYSTEM/PLAYER instance
AtMostOne(cell occupancy literals) for every Base cell
symmetry breaking                  for identical instances
```

Candidate enumeration prefilters positions outside `1` cells, overlapping `X` or requiring unsupported rotation.

The current CP-SAT ordering/surrogate is a search device only and MUST NOT be presented as the gameplay objective.

Corridor/Elevator routing and exact `F` evaluation still happen after room placement, so the current engine does not prove a global optimum over the complete problem.

### 11.2 Existing integrated hard-feasibility foundation

`src/alters_base_planner/hard_constraints.py` already contains a reusable CP-SAT hard-feasibility layer for placement options plus Corridor/Elevator anchor variables, shared occupancy, port connectivity, non-transit semantics and Airlock-rooted flow. Synthetic tests validate key feasible/infeasible cases.

It is not yet wired into the production `solve_plan()` path and therefore does not make Stage 2 complete.

### 11.3 Target exact formulation

The project must evolve toward either:

1. one integrated exact CP-SAT formulation; or
2. an exact decomposition with valid lower bounds and an optimality proof.

The target model/decomposition must cover:

- SYSTEM/PLAYER/SOLVER placement;
- occupancy;
- legal port adjacency;
- Corridor/Elevator selection;
- Airlock-rooted connectivity;
- non-transit terminal behaviour;
- Elevator vertical continuity;
- exact shortest-path/travel-cost semantics or a proven equivalent;
- true weighted objective `F` and accepted tie-breakers.

Never set:

```text
global_objective_optimum_proven = true
```

unless the complete joint problem or exact decomposition has actually established the proof.

### 11.4 Model validation and fail-fast behaviour

Every CP-SAT model must pass `CpModel.validate()` before solving. Internal invariant/mathematical failures must fail fast and must not be hidden as ordinary infeasibility.

### 11.5 Search budget

`time_limit_s` is one global wall-clock budget for the complete planning call, not a fresh budget per packing attempt.

Persist at minimum:

```text
room_packings_examined
connected_candidates_examined
manhattan_pruned_count
search_time_s
time_limit_reached
search_exhausted
```

---

## 12. Input contract

Player configuration includes:

```text
base_tier
rooms
```

Optional solver/output sections may control budgets and output paths.

Reject:

- unknown Base tiers;
- unknown module keys;
- SYSTEM module keys in `rooms`;
- SOLVER module keys in `rooms`;
- booleans/fractions/negative counts;
- count-limit violations;
- unknown config fields;
- invalid/non-finite/non-positive solver budgets;
- unsupported objectives.

SYSTEM modules are injected automatically; Corridor/Elevator are generated automatically.

---

## 13. Output contract

Every run must persist machine-readable diagnostics. A feasible result should contain at least:

```text
status
Base tier / geometry source / verification
installed module placements
resolved ports
solver-generated Corridor/Elevator placements
objective_value / exact F
modified_manhattan_lower_bound
pairwise distances
pairwise objective contributions
average and weighted-average distances
traffic weights
elevator module count / shaft count
corridor count
room mass
utility mass
total Base mass
Organics capacity / requirement / margin
journey feasibility
global_objective_optimum_proven
search diagnostics
```

PNG/SVG must preserve cell aspect ratio:

```text
cell height = 2 * cell width
```

The graphic must distinguish unavailable/core/buildable cells, module types, Corridor and Elevator and display key optimization/mass metrics.

---

## 14. Evidence and provenance policy

Use this precedence when changing domain facts:

1. reproducible extracted/game-exact data or direct in-game measurement;
2. validated project geometry/audit data with tests;
3. current direct module documentation;
4. multiple independent high-quality guides;
5. player/community reports for otherwise undocumented mechanics;
6. heuristic inference only when explicitly labelled and never as a hard game fact.

`docs/ROOM_DATA_AUDIT.md` must retain conflicts rather than hide them.

Known decisions/conflicts include:

- Dormitory mass remains 8 despite a conflicting aggregate/wiki value likely reflecting construction cost;
- Park with Bench is 6x1 under current validated project data;
- Radiation Repulsor uses top access and is non-transit;
- Rapidium Ark is non-transit and capped at 5;
- Recycler is capped at 1;
- Tier-I Organics numeric provenance is weaker than Tier II-IV.

---

## 15. Development roadmap

### Stage 0 — Data and contract stabilization — COMPLETE / MAINTAIN

Deliverables achieved/maintained:

- validated Base I-IV CSV geometry;
- module dimensions/masses and key limits;
- standard floor ports plus verified exception(s);
- traffic-weight audit;
- JSON validation;
- exact post-routing distance evaluator;
- CI on Python 3.11/3.12/3.13.

Acceptance: tests and CI remain green after every future change.

### Stage 1 — Unified Module domain model — COMPLETE / MAINTAIN

Delivered:

- explicit `SYSTEM`, `PLAYER`, `SOLVER` authority;
- one canonical `ModuleSpec` catalogue including Corridor/Elevator;
- one `ModulePlacement` geometry representation for concrete installed modules;
- shared occupancy/geometry helpers;
- standard derived ports;
- canonical utility port/vertical-connectivity data;
- authority-driven configuration validation;
- regression coverage for authority partitions and unified placements.

Stage 1 completion does not imply joint optimization; the post-router is still transitional.

### Stage 2 — Integrated hard-feasibility model — NEXT

Goal: move Corridor/Elevator placement and network correctness into the active optimization domain.

Deliverables:

- production decision variables for Corridor/Elevator placement;
- shared no-overlap constraints;
- per-module legal connection semantics;
- exact Airlock-rooted connectivity (flow or equivalent);
- exact non-transit handling;
- exact Elevator vertical continuity;
- no floating utilities;
- integration of the existing `hard_constraints.py` foundation into production solving.

Acceptance: small synthetic cases with independently known feasible/infeasible outcomes are proven correctly by CP-SAT or an exact decomposition, and production candidates no longer depend on greedy routing for correctness.

### Stage 3 — Exact objective integration

Goal: optimize true `F`, not only evaluate it after a candidate is routed.

Deliverables:

- exact path-cost representation or exact routing subproblem;
- valid lower bounds;
- incumbent/bound reporting;
- optimality proof on benchmark instances when search completes.

Acceptance: match exhaustive enumeration on small instances exactly.

### Stage 4 — Performance and benchmark suite

Deliverables:

- representative Tier I-IV benchmark plans;
- deterministic seeds/options where practical;
- runtime, candidate count, pruning, bound quality and objective metrics;
- symmetry breaking and domain reduction;
- regression thresholds that detect solver-quality degradation.

No performance claim without reproducible benchmark evidence.

### Stage 5 — User-facing planning quality

Deliverables:

- robust CLI and Streamlit UI;
- clear SYSTEM-vs-PLAYER room controls;
- user cannot configure Corridor/Elevator counts;
- overweight/journey warnings;
- downloadable PNG/SVG/JSON;
- clear best-known-vs-proven-optimal explanation.

### Stage 6 — Progression-aware mobile Base

Only after Stage 3/4 stability, add explicit game-state modelling such as:

```text
act / story state
unlocked modules
already-built non-removable modules
available expansion tier
possibly work/sleep/evacuation layout state
```

Do not retrofit progression with ad-hoc mandatory-list changes.

### Stage 7 — The Last Variable DLC — DEFERRED UNTIL DATA COMPLETE

The DLC has materially different underground/stationary topology, pinned Airlock and different module/mass semantics. Implement it as a separate environment only when exact geometry and module data are sufficient. Never approximate DLC with mobile Base I-IV masks.

---

## 16. Required testing strategy

Every mechanics/solver change must add/update tests at the appropriate level.

Minimum categories:

- geometry dimensions/core coordinates;
- module dimensions/masses/count limits;
- authority partitions;
- standard floor ports and top-access exception;
- 1x1 logical-port semantics;
- direct room adjacency `d=0`;
- Corridor cost `+1`;
- Elevator module cost `+1`;
- intermediate-room width cost;
- non-transit bridge rejection;
- Airlock reachability;
- utility overlap rejection;
- Elevator continuity;
- Manhattan LB admissibility;
- objective contribution sum invariant;
- mass/journey calculation;
- SYSTEM module rejection from user config;
- SOLVER module rejection from user config;
- time-budget semantics;
- end-to-end PNG/SVG/JSON generation.

Future exact solver work must add tiny instances whose optimum is independently known by exhaustive enumeration.

---

## 17. ChatGPT-driven repository development protocol

When developing this repository through dialogue:

1. Read this file before major architectural work.
2. Inspect current `main`, CI, relevant code/tests and normative docs before editing.
3. State the project-level reason for a change, not only local code details.
4. Preserve the Base-planner goal; prevent feature drift.
5. Change game mechanics only with evidence or explicit Project Manager decision.
6. Treat solver correctness as more important than cosmetic features.
7. Add tests for every new hard invariant or distance/objective rule.
8. Keep documentation synchronized with implementation.
9. Never hide heuristic routing, incomplete search, time limits or lack of optimality proof.
10. After each significant iteration report global progress, CI, remaining architectural gaps and the next highest-value milestone.

For major solver changes, prefer an auditable branch/PR workflow unless the Project Manager explicitly requests direct changes to `main`.

---

## 18. Definition of project success

The core mobile-Base planner succeeds when, for a selected tier and requested optional counts, it can:

1. model all SYSTEM, PLAYER and SOLVER modules correctly;
2. prove hard feasibility/infeasibility under the exact Base mask;
3. generate Corridor/Elevator placement as part of the optimization problem;
4. enforce legal ports, Airlock-rooted connectivity, terminal behaviour and Elevator rules;
5. compute exact travel distances and true weighted `F`;
6. minimize true `F` and, when search completes, provide a valid global optimality proof;
7. report Base Mass and journey feasibility correctly;
8. produce reproducible auditable JSON and graphical plans;
9. pass the full CI/benchmark suite without regression;
10. remain extensible to progression-aware and DLC modes without corrupting the mobile-Base model.

Until item 6 is achieved for the complete joint problem, returned layouts must be described as **best-known feasible layouts under the current search architecture**, never as globally optimal designs.
