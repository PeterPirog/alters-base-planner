# The Alters Base Planner — Project System Requirements and Development Source of Truth

Status: **normative project-level specification**  
Repository: `PeterPirog/alters-base-planner`  
Primary implementation language: Python >= 3.11  
Optimization engine: Google OR-Tools CP-SAT  
Project role of this document: preserve product intent, game-mechanics knowledge, mathematical semantics, solver requirements, development stages, and acceptance criteria across future ChatGPT-driven iterations.

---

## 1. Purpose and authority

This repository shall implement a reliable optimization-based planner for the mobile Base in **The Alters**. The user specifies the Base tier and counts of optional rooms. The planner must place all required/player-selected modules and automatically determine the number and placement of Corridors and Elevators.

This file is the highest-level repository source of truth for **what the project is supposed to achieve**. More detailed implementation documents (`docs/OPTIMIZATION_MODEL.md`, `docs/ROOM_DATA_AUDIT.md`, `docs/BASE_GEOMETRY_REFERENCE.md`) and code/tests must remain consistent with it.

When evidence changes, do not silently change mechanics. Update the relevant audit/source material, this specification if the project contract changes, implementation, and tests in the same intentional change.

Never invent missing game mechanics. Distinguish:

- **verified game/domain facts** — may define hard constraints;
- **project modelling decisions** — explicit approximations/abstractions;
- **heuristics** — may guide search but must not invalidate otherwise legal layouts;
- **unknown/provisional data** — must be labelled and must not be presented as verified.

The project is an unofficial planning tool and must not claim access to hidden game constants unless independently verified.

---

## 2. Product goal

Given:

1. Base tier I, II, III or IV;
2. requested counts of optional modules;
3. solver budget/configuration;

produce a layout that:

- fits the exact irregular Base mask;
- contains all baseline mandatory modules and exactly the requested optional modules;
- contains solver-generated Corridor/Elevator modules as needed;
- obeys module geometry, ports, connectivity and special module rules;
- forms one legal network rooted at the Airlock;
- reports mass and Organics travel feasibility;
- minimizes the accepted gameplay travel objective;
- emits an auditable JSON result and graphical PNG/SVG plan;
- clearly states whether the result is merely feasible/best-known or globally proven optimal.

The long-term target is an **exact joint optimizer** (or an exact decomposition with valid bounds) over room placement, solver-managed utility placement, network connectivity and the true gameplay objective.

---

## 3. Coordinate systems and Base geometry

### 3.1 Global Base coordinates

The absolute Base grid uses matrix/image coordinates:

```text
origin (0,0) = top-left
x increases to the right
y increases downward
```

CSV semantics:

```text
0 = outside the Base / unavailable
1 = buildable Base cell
X = immovable blocked core cell
```

CSV masks are hard geometry. They MUST NOT be auto-symmetrized, centred, smoothed or inferred from an ideal circle.

A grid cell corresponds approximately to 2 m width × 3 m height in the game-space analysis; the planner objective itself operates in module/grid travel units, not metres.

### 3.2 Validated Base I-IV masks

The canonical built-in geometry files are:

```text
src/alters_base_planner/data/base-size1.csv
src/alters_base_planner/data/base-size2.csv
src/alters_base_planner/data/base-size3.csv
src/alters_base_planner/data/base-size4.csv
```

Validated dimensions and fixed 4×2 core coordinates:

| Tier | Width × Height | Core X coordinates | Organics capacity |
|---|---:|---|---:|
| I | 22 × 12 | x=8..11, y=6..7 | 300* |
| II | 26 × 14 | x=10..13, y=7..8 | 450 |
| III | 30 × 16 | x=12..15, y=8..9 | 700 |
| IV | 34 × 18 | x=14..17, y=9..10 | 800 |

`*` Tier-I value 300 is the current planner value. The supplied Base analysis validates the later 450/700/800 capacities more directly than the Tier-I numeric value; keep Tier-I provenance explicit until stronger game-exact evidence is available.

The Base/core is intentionally asymmetric. Do not force the core to the geometric centre.

---

## 4. Module domain model

### 4.1 Target abstraction

The target domain abstraction is **Module**, not “everything is a Room”. A module has at least:

```text
key/name
width, height
mass
occupied cells
ports
transit behaviour
visit/traffic weight
count limits
placement authority
```

Recommended placement-authority semantics:

```text
SYSTEM  = baseline mandatory module, injected automatically
PLAYER  = optional room count selected by the user
SOLVER  = infrastructure count/placement chosen by optimization
```

Corridor and Elevator are solver-managed Modules. They are never player count inputs.

### 4.2 Baseline mandatory modules

The current planning baseline contains **exactly one** of each of the following modules:

| Key | Module | Size | Mass |
|---|---|---:|---:|
| `airlock` | Airlock | 4×1 | 4 |
| `captains_cabin` | Captain's Cabin | 4×1 | 4 |
| `command_center` | Command Center | 4×1 | 4 |
| `communication_room` | Communication Room | 4×1 | 4 |
| `kitchen` | Kitchen | 5×1 | 4 |
| `machinery` | Machinery | 4×1 | 4 |
| `quantum_computer` | Quantum Computer | 4×2 | 8 |
| `womb` | The Womb | 5×1 | 4 |

These are `SYSTEM` modules in the current baseline:

- the player MUST NOT configure their count;
- the player MUST NOT set them to `0`;
- they are injected automatically as one instance each.

Important semantic distinction: this is the **planner baseline**, not a claim that every one of these modules physically exists at minute zero of every story state. A future progression-aware model must explicitly introduce `act/game_state`, unlocked modules and already-built non-removable modules before changing this behaviour.

### 4.3 Player-configurable modules

Current catalogue:

| Key | Module | Size | Mass | Special rule |
|---|---|---:|---:|---|
| `ark_sarcophagus` | Ark Sarcophagus | 4×2 | 13 | passive objective weight |
| `contemplation_room` | Contemplation Room | 6×1 | 20 | — |
| `dormitory` | Dormitory | 6×1 | 8 | — |
| `gamers_den` | Gamer's Den | 5×1 | 14 | — |
| `greenhouse` | Greenhouse | 8×1 | 16 | — |
| `gym` | Gym | 6×1 | 20 | — |
| `infirmary` | Infirmary | 6×1 | 16 | — |
| `large_storage` | Large Storage | 8×2 | 140 | passive traffic |
| `materializer` | Materializer | 4×3 | 24 | high standard floor ports |
| `medium_storage` | Medium Storage | 8×1 | 65 | passive traffic |
| `park_with_bench` | Park with Bench | 6×1 | 20 | — |
| `personal_cabin` | Personal Cabin | 3×1 | 10 | — |
| `radiation_repulsor` | Radiation Repulsor | 2×3 | 16 | **top access**, non-transit |
| `rapidium_ark` | Rapidium Ark | 4×2 | 32 | non-transit, max 5 |
| `recycler` | Recycler | 2×1 | 2 | max 1 |
| `refinery` | Refinery | 4×1 | 8 | — |
| `research_lab` | Research Lab | 4×1 | 8 | — |
| `small_storage` | Small Storage | 2×2 | 28 | passive traffic |
| `social_room` | Social Room | 6×1 | 14 | — |
| `workshop` | Workshop | 4×1 | 8 | — |

### 4.4 Solver-managed modules

| Module | Size | Mass | Authority |
|---|---:|---:|---|
| Corridor | 2×1 | 2 | SOLVER |
| Elevator | 2×1 | 2 | SOLVER |

The user must never specify Corridor/Elevator counts. Their number and placement are results of optimization.

---

## 5. Port model

### 5.1 Local port coordinates

Module-local port coordinates are floor-relative:

```text
local y = 0     => floor
local y = H - 1 => top
x increases to the right
```

For every standard horizontally connected module of width `W`:

```text
LEFT  = (0, 0)
RIGHT = (W - 1, 0)
```

These standard ports MUST be derived from width, not redundantly stored per module.

For a 1×1 module, LEFT and RIGHT both occupy physical local cell `(0,0)` but remain distinct logical sides.

### 5.2 Local-to-world transform

Because world `y` grows downward while local port `y` grows upward from the floor:

```text
world_cell_x = room.x + local_x
world_cell_y = room.y + (H - 1 - local_y)
```

Therefore a standard high module is entered at its physical floor, never through its ceiling or centroid.

### 5.3 Verified exception

Radiation Repulsor is 2×3 and connects from its **top**. It therefore uses local `y=H-1` access rather than floor `y=0`.

Do not generalize exceptions without evidence.

### 5.4 Target utility ports

In the unified target model:

- Corridor provides horizontal LEFT/RIGHT connectivity;
- Elevator provides horizontal attachment plus vertical UP/DOWN connectivity to immediately adjacent stacked Elevator modules.

Current special-case implementation may be retained during migration, but target semantics must be expressible as module/port compatibility rather than ad-hoc geometry branches.

---

## 6. Connectivity and transit semantics

Every installed module must belong to one Base network rooted at the Airlock.

For every installed accessible/required module:

```text
at least one legal port must connect to the network
reachable(Airlock, module) = true
```

A legal connection may be:

```text
Room <-> Room
Room <-> Corridor
Room <-> Elevator
Corridor <-> Corridor
Corridor <-> Elevator
Elevator <-> Elevator (including vertical stacking rules)
```

Do not require direct room-to-room contact; connection through solver-managed utilities is valid.

`transit_allowed=false` means the module may be reached as a terminal but its opposite ports are not internally connected for through-traffic.

Current non-transit modules:

- Radiation Repulsor;
- Rapidium Ark.

They are **not exempt from Base connectivity**. Rapidium Ark must connect but must not become a bridge between other modules.

All generated Corridor/Elevator modules must themselves be part of the Airlock-rooted network. Floating utility islands are invalid.

---

## 7. Hard constraints

A candidate is hard-feasible only if all applicable rules hold.

### H1 — Exact multiplicity

- exactly one instance of each baseline mandatory SYSTEM module;
- exactly the player-requested count of each optional PLAYER module;
- verified maxima enforced (`Recycler <= 1`, `Rapidium Ark <= 5`);
- Corridor/Elevator multiplicity decided only by the solver.

### H2 — Base-mask legality

Every occupied cell of every module must be `1` in the selected Base CSV. No movable module may occupy `0` or `X`.

### H3 — No overlap

Each physical grid cell may be occupied by at most one installed module. This includes all combinations of room/Corridor/Elevator.

### H4 — Orientation

No rotation unless game evidence explicitly supports it. Current module dimensions are orientation-specific.

### H5 — Legal ports

Direct module connectivity exists only through compatible resolved ports/utility anchors. Ordinary high modules connect at floor level; top-access exceptions must remain explicit.

### H6 — Local connection requirement

Every installed module that is required to belong to the Base network must have at least one active legal connection. This is a local strengthening constraint; it does not replace global reachability.

### H7 — Global Airlock reachability

All installed modules must be reachable from Airlock through the legal module graph.

### H8 — Non-transit behaviour

A non-transit module may terminate a route but may not be used as an intermediate LEFT-to-RIGHT/RIGHT-to-LEFT bridge.

### H9 — Corridor semantics

Corridor is a 2×1 horizontal solver module. It must fit the Base, avoid overlaps, connect legally and belong to the reachable network.

### H10 — Elevator semantics

Elevator is a 2×1 solver module. Vertical movement occurs only between immediately adjacent Elevator modules that are vertically compatible. Each used level in a shaft is represented by an Elevator module.

For used port-floor span `Lmin..Lmax`, the current continuity rule requires every level in the span to contain elevator coverage and every adjacent level pair to share a vertical continuation (or an explicitly modelled legal transfer path).

### H11 — No floating utilities

Every generated Corridor and Elevator must contribute to/reach the Base network; isolated infrastructure is invalid.

### H12 — Journey mass semantics

For the mobile Base:

```text
total_base_mass = sum(room masses) + 2 * corridor_count + 2 * elevator_module_count
organics_required_for_journey = total_base_mass
```

Distinguish two concepts:

- `structural/topological feasible` — valid layout geometry/network;
- `journey feasible` — structural layout AND `total_base_mass <= organics_capacity`.

The system must never report an overweight plan as journey-feasible. A diagnostic mode may still render an overweight structurally feasible layout if clearly labelled.

---

## 8. Exact travel-distance semantics

The final objective uses shortest-path distance in the legal module graph, not centroid distance and not raw Manhattan distance.

For endpoint rooms A and B:

### D1 — Endpoint room cost

The start and destination room widths do not contribute to their own pair distance.

### D2 — Direct endpoint adjacency

If compatible endpoint ports directly meet:

```text
d(A,B) = 0
```

### D3 — Corridor

Every traversed Corridor module contributes:

```text
+1
```

### D4 — Elevator

Every traversed Elevator module contributes:

```text
+1
```

A four-module vertical Elevator stack contributes 4 when all four modules are traversed.

### D5 — Intermediate transit room

If a route passes through ordinary transit room C from one side to the other:

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

A 1×1 transit room therefore costs 1 when crossed even though LEFT/RIGHT share the same physical cell.

### D6 — Non-transit module

No internal side-to-side graph edge is created. It cannot be crossed as an intermediate route.

### D7 — Path algorithm

The exact evaluator may use Dijkstra or another provably equivalent non-negative shortest-path algorithm. Exact `d(i,j)` must be reproducible and auditable.

---

## 9. Modified Manhattan lower bound

Manhattan is a **lower bound/search tool**, not the final distance definition.

For two endpoint ports on the same floor:

```text
horizontal_lb = ceil(abs(edge_x_a - edge_x_b) / 2)
```

because one 2×1 Corridor spans two horizontal cells at travel cost 1.

For ports on different floors, compare external 2×1 utility anchors:

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

It is legal to prune a candidate when:

```text
F_LB > incumbent_exact_F
```

The implementation must maintain the invariant:

```text
F_LB <= F_exact
```

Any violation is an internal solver/model bug and must fail fast, not be silently treated as an infeasible layout.

---

## 10. Gameplay objective and soft preferences

### 10.1 Primary objective

For all unordered pairs of installed rooms with positive traffic weights:

```text
pair_score(i,j) = w_i * w_j * d(i,j)
F = sum_{i<j} pair_score(i,j)
```

The solver minimizes exact `F` among hard-feasible candidates.

Zero-weight modules remain subject to all hard constraints; they simply do not create objective pairs.

### 10.2 Default traffic weights

These are gameplay-informed planner parameters, **not hidden game constants**:

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

Weights must remain editable and auditable. Future empirical calibration from observed transition counts is desirable.

### 10.3 Tie-breakers

The accepted lexicographic preference after exact `F` is:

```text
1. lower F
2. lower total Base mass
3. fewer Elevator modules
4. fewer Corridor modules
```

Do not introduce an additional gameplay “soft constraint” that silently competes with `F` unless the project contract is explicitly changed.

### 10.4 Central Elevator meta

Community layouts often favour a central/main elevator shaft, commonly near the right side of the asymmetric core. Treat this as a **search heuristic / emergent expected solution**, not a hard rule. A different configuration must remain legal if it produces a better valid objective.

---

## 11. OR-Tools / solver correctness requirements

### 11.1 Current implementation state

Current CP-SAT solves the **room-placement subproblem** using pre-enumerated legal placements:

```text
P[i,c] = 1 iff room instance i uses candidate placement c
```

Required current constraints:

```text
ExactlyOne(P[i,*])                  for every room instance
AtMostOne(cell occupancy literals) for every Base cell
symmetry breaking                  for identical room instances
```

Candidate enumeration prefilters placements outside `1` cells or overlapping `X`.

Current CP-SAT ordering/surrogate is a search device only. It MUST NOT be described as the true gameplay objective.

Current routing of Corridor/Elevator and exact `F` evaluation happen after room placement. Therefore the current engine does not prove a global optimum over the complete problem.

### 11.2 Target exact formulation

The project must evolve toward either:

1. one integrated exact CP-SAT formulation; or
2. an exact decomposition (e.g. master placement + exact routing/connectivity subproblem) with valid lower bounds and an optimality proof.

The target model must cover:

- PLAYER/SYSTEM/SOLVER module placement;
- occupancy;
- legal port adjacency;
- Corridor/Elevator selection;
- Airlock-rooted connectivity;
- non-transit terminal behaviour;
- Elevator vertical continuity;
- shortest-path/travel-cost semantics or an exact equivalent formulation;
- the true weighted objective `F`.

Do not set:

```text
global_objective_optimum_proven = true
```

unless the complete joint problem (or exact decomposition) has actually produced a proof under the configured problem definition.

### 11.3 Model validation

Every CP-SAT model must be validated with `CpModel.validate()` before solving. Internal invariant failures must be fail-fast.

### 11.4 Search budget

`time_limit_s` is one global wall-clock budget for the complete planning call, not a fresh budget per packing attempt.

Persist diagnostics at minimum:

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

Player configuration must include:

```text
base_tier
rooms
```

Optional solver/output sections may control time/attempt limits and output paths.

The loader must reject:

- unknown Base tiers;
- unknown room keys;
- mandatory SYSTEM module keys in `rooms`;
- Corridor/Elevator keys in `rooms`;
- booleans/fractions/negative counts;
- count-limit violations;
- unknown config fields;
- invalid/non-finite solver budgets;
- unsupported objectives.

Mandatory modules are automatically injected; the player cannot set them to zero.

---

## 13. Output contract

Every run must persist machine-readable diagnostics. A feasible result should contain at least:

```text
status
Base tier / geometry source / geometry verification
room placements
resolved ports
solver-generated utility placements
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

PNG/SVG should be generated for feasible layouts and must preserve cell aspect ratio:

```text
cell height = 2 × cell width
```

The graphic must distinguish unavailable/core/buildable cells, room types, Corridor and Elevator and display key optimization/mass metrics.

---

## 14. Evidence and provenance policy

Use this precedence when changing domain facts:

1. reproducible extracted/game-exact data or direct in-game measurement;
2. validated project geometry/audit data with tests;
3. current direct module documentation;
4. multiple independent high-quality guides;
5. player/community reports for mechanics that are otherwise undocumented;
6. heuristic inference only when explicitly labelled and never as a hard game fact.

`docs/ROOM_DATA_AUDIT.md` must document conflicts instead of hiding them.

Known important decisions/conflicts include:

- Dormitory mass remains 8 despite a conflicting aggregate/wiki value likely reflecting construction cost;
- Park with Bench is 6×1 under the current validated project data;
- Radiation Repulsor uses top access;
- Rapidium Ark is non-transit and capped at 5 in the current contract;
- Recycler is capped at 1;
- Tier-I Organics numeric provenance is weaker than Tier II-IV and should remain auditable.

---

## 15. Development roadmap

### Stage 0 — Data and contract stabilization — COMPLETE / MAINTAIN

Deliverables:

- validated Base I-IV CSV geometry;
- module catalogue dimensions/masses;
- explicit standard floor ports + verified exceptions;
- traffic-weight audit;
- JSON validation;
- exact post-routing distance evaluator;
- CI on Python 3.11/3.12/3.13.

Acceptance: current tests and CI remain green after every future change.

### Stage 1 — Unified Module domain model — NEXT

Goal: represent rooms, Corridor and Elevator under one coherent `ModuleSpec/ModulePlacement` abstraction with explicit placement authority.

Deliverables:

- `SYSTEM`, `PLAYER`, `SOLVER` authority;
- shared occupancy/geometry model;
- standard derived ports;
- utility port semantics (including vertical Elevator connectivity);
- remove duplicate room-vs-utility geometry logic where safe.

Acceptance: no behaviour regression; current feasible examples produce equivalent or better legal layouts.

### Stage 2 — Integrated hard-feasibility model

Goal: move utility placement and connectivity from greedy post-routing into the optimization domain.

Deliverables:

- decision variables for Corridor/Elevator placement;
- shared no-overlap constraints;
- per-module active-port/degree constraints;
- exact Airlock-rooted connectivity (flow or equivalent);
- exact non-transit handling;
- exact Elevator vertical continuity;
- no floating utilities.

Acceptance: small synthetic cases with known feasible/infeasible results are proven correctly by CP-SAT or exact decomposition.

### Stage 3 — Exact objective integration

Goal: optimize the true `F`, not only a placement surrogate.

Deliverables:

- exact path-cost representation or exact routing subproblem;
- valid lower bounds;
- incumbent/bound reporting;
- optimality proof on benchmark instances when search completes.

Acceptance: compare against exhaustive enumeration on small instances and match the true optimum exactly.

### Stage 4 — Performance and benchmark suite

Deliverables:

- representative Tier I-IV benchmark plans;
- deterministic seeds/options where practical;
- runtime, candidate count, pruning, bound quality and objective metrics;
- symmetry breaking;
- Manhattan pruning;
- regression thresholds that detect solver-quality degradation.

Acceptance: no performance claim without reproducible benchmark evidence.

### Stage 5 — User-facing planning quality

Deliverables:

- robust CLI and Streamlit UI;
- clear mandatory-vs-optional room controls;
- user cannot enter Corridor/Elevator counts;
- overweight/journey warnings;
- downloadable PNG/SVG/JSON;
- explanation of objective and best-known-vs-proven-optimal status.

### Stage 6 — Progression-aware mobile Base

Only after Stage 3/4 stability, add explicit game-state modelling:

```text
act / story state
unlocked modules
already-built non-removable modules
available expansion tier
possibly day/work/sleep/evacuation layout state
```

Do not retrofit progression by ad-hoc changes to the baseline mandatory list.

### Stage 7 — The Last Variable DLC — DEFERRED UNTIL DATA COMPLETE

The DLC has a materially different underground/stationary topology, pinned Airlock and different module set/mass semantics. Implement it as a separate environment/mode only when exact geometry and module data are sufficient. Do not approximate DLC with the mobile Base I-IV masks.

---

## 16. Required testing strategy

Every mechanics/solver change must add or update tests at the appropriate level.

Minimum categories:

- geometry CSV dimensions/core coordinates;
- module dimensions/masses/count limits;
- standard floor ports and top-access exception;
- 1×1 logical-port semantics;
- room-room direct adjacency `d=0`;
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
- mandatory room rejection from user config;
- solver-managed utility rejection from user config;
- time-budget semantics;
- end-to-end generation of real PNG/SVG/JSON.

For future exact solver work, add tiny instances whose optimum is independently known by exhaustive enumeration.

---

## 17. ChatGPT-driven repository development protocol

When ChatGPT develops this repository through dialogue:

1. Read this file before major architectural work.
2. Inspect current `main`, CI, relevant code/tests and normative docs before editing.
3. State the project-level reason for a change, not only local code details.
4. Preserve the Base-planner goal; do not allow feature drift.
5. Change game mechanics only with evidence or explicit Project Manager decision.
6. Treat solver correctness as more important than cosmetic features.
7. Add tests for every new hard invariant or distance/objective rule.
8. Keep documentation synchronized with implementation.
9. Never hide limitations: explicitly report heuristic routing, incomplete search, time limit and lack of optimality proof.
10. After changes, verify CI and report global project progress, remaining architectural gaps and the next highest-value milestone.

For major solver changes, prefer an auditable branch/PR workflow unless the Project Manager explicitly requests direct changes to `main`.

---

## 18. Definition of project success

The core mobile-Base planner reaches its target when, for a selected Base tier and requested optional module counts, it can:

1. model all baseline/system, player and solver-managed modules correctly;
2. prove hard feasibility/infeasibility under the validated Base mask;
3. generate the Corridor/Elevator network as part of the optimization problem;
4. enforce legal ports, Airlock-rooted connectivity, terminal behaviour and vertical Elevator rules;
5. compute the exact travel objective using the accepted distance semantics;
6. minimize the true weighted objective and, when search completes, provide a valid optimality proof;
7. report mass and journey feasibility correctly;
8. produce reproducible, auditable JSON and graphical plans;
9. pass the full CI/benchmark suite without regression;
10. remain extensible to progression-aware and DLC modes without corrupting the mobile-Base model.

Until item 6 is achieved for the complete joint problem, returned layouts must be described as **best-known feasible layouts under the current search architecture**, not as globally optimal designs.
