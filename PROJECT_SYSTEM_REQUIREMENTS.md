# The Alters Base Planner — Project System Requirements and Development Source of Truth

Status: **normative project-level specification**  
Repository: `PeterPirog/alters-base-planner`  
Primary implementation language: Python >= 3.11  
Optimization engine: Google OR-Tools CP-SAT

This file is the highest-level source of truth for product intent, accepted game/domain mechanics, mathematical semantics, solver requirements, development stages and acceptance criteria.

---

## 1. Purpose and authority

The repository implements a reliable optimization-based planner for the mobile Base in **The Alters**. The user selects Base Tier I-IV and exact counts of optional rooms. The planner automatically injects mandatory modules and chooses all Corridor/Elevator infrastructure.

Detailed contracts must remain consistent with this file:

1. `docs/OPTIMIZATION_MODEL.md` — mathematical/solver contract;
2. `docs/ROOM_DATA_AUDIT.md` — module/game evidence;
3. `docs/BASE_GEOMETRY_REFERENCE.md` — Base geometry;
4. current code and tests.

When verified evidence changes mechanics, update documentation, implementation and tests together. Never invent missing game rules. Distinguish verified facts, explicit modelling decisions, heuristics and unknown/provisional data.

The project is unofficial and must not claim hidden game constants without evidence.

---

## 2. Product goal

Given:

1. Base tier I, II, III or IV;
2. exact requested counts of PLAYER modules;
3. optional per-plan SYSTEM/PLAYER traffic-weight overrides;
4. solver budget/configuration;

produce a layout that:

- fits the exact irregular Base mask;
- contains every baseline mandatory SYSTEM module exactly once;
- contains exactly the requested PLAYER modules;
- generates Corridor/Elevator modules automatically;
- obeys exact geometry, ports, occupancy, connectivity and special rules;
- forms one legal network rooted at Airlock;
- computes exact legal travel distances;
- minimizes the accepted weighted travel objective and tie-breakers;
- reports Base Mass and Organics journey feasibility separately from structural feasibility;
- emits auditable JSON and graphical PNG/SVG;
- clearly distinguishes best-known feasible results from mathematically proven global optima.

The accepted target architecture is one joint exact optimizer or an exact decomposition with valid bounds and proof semantics. Heuristic post-routing is not a correctness boundary.

The current production architecture is an **exact room-packing / fixed-objective decomposition**. A configured time or attempt limit may stop it before proof completion; in that case the result remains best-known feasible.

---

## 3. Coordinates and Base geometry

### 3.1 Global coordinates

```text
origin (0,0) = top-left
x increases right
y increases down
```

CSV semantics:

```text
0 = unavailable/outside Base
1 = buildable
X = fixed blocked core
```

The CSV masks are hard geometry. Never symmetrize, smooth, recenter or infer them from an idealized shape.

### 3.2 Canonical masks

```text
src/alters_base_planner/data/base-size1.csv
src/alters_base_planner/data/base-size2.csv
src/alters_base_planner/data/base-size3.csv
src/alters_base_planner/data/base-size4.csv
```

| Tier | Width x Height | Fixed 4x2 core | Organics capacity |
|---|---:|---|---:|
| I | 22 x 12 | x=8..11, y=6..7 | 300* |
| II | 26 x 14 | x=10..13, y=7..8 | 450 |
| III | 30 x 16 | x=12..15, y=8..9 | 700 |
| IV | 34 x 18 | x=14..17, y=9..10 | 800 |

`*` Tier-I capacity is the current planner value and has weaker provenance than Tier II-IV. Preserve that audit distinction until stronger evidence exists.

The blocked core is intentionally asymmetric relative to the rectangular grid.

---

## 4. Canonical Module model

The canonical abstraction is `ModuleSpec`; every installed object uses `ModulePlacement`.

A module describes at least:

```text
key/name
width, height
mass
ports
transit behaviour
traffic weight
count limits
placement authority
```

Placement authority:

```text
SYSTEM  = mandatory planner baseline; injected automatically
PLAYER  = optional; exact count selected by user
SOLVER  = generated infrastructure; count/placement chosen by optimization
```

`ModuleType` is independent from placement authority.

### 4.1 Mandatory SYSTEM modules

Exactly one each:

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

The player cannot configure these counts or set them to zero. This is the current planning baseline, not a claim that all exist at minute zero of every story state.

### 4.2 PLAYER catalogue

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
| `radiation_repulsor` | Radiation Repulsor | 2x3 | 16 | top access, non-transit |
| `rapidium_ark` | Rapidium Ark | 4x2 | 32 | non-transit, max 5 |
| `recycler` | Recycler | 2x1 | 2 | max 1 |
| `refinery` | Refinery | 4x1 | 8 | — |
| `research_lab` | Research Lab | 4x1 | 8 | — |
| `small_storage` | Small Storage | 2x2 | 28 | passive traffic |
| `social_room` | Social Room | 6x1 | 14 | — |
| `workshop` | Workshop | 4x1 | 8 | — |

### 4.3 SOLVER modules

| Module | Size | Mass |
|---|---:|---:|
| Corridor | 2x1 | 2 |
| Elevator | 2x1 | 2 |

Their multiplicity and placement are optimization results and never player inputs.

---

## 5. Port model

Local module ports are floor-relative:

```text
local y = 0     -> floor
local y = H - 1 -> top
```

Standard ports for width `W`:

```text
LEFT  = (0, 0)
RIGHT = (W - 1, 0)
```

World conversion:

```text
world_x = module.x + local_x
world_y = module.y + (H - 1 - local_y)
```

Ordinary tall modules connect at their floor, not centroid or ceiling.

For a 1x1 module, LEFT and RIGHT share one physical cell but remain separate logical sides.

Verified exception: Radiation Repulsor is 2x3, connects at its top and is non-transit.

Corridor provides horizontal connectivity. Elevator provides horizontal attachment plus vertical connectivity to immediately adjacent stacked Elevator modules.

---

## 6. Connectivity and transit

Every installed module belongs to one network rooted at Airlock.

For every installed required module:

```text
at least one legal port connection
reachable(Airlock, module) = true
```

Legal graph connections may include room-room, room-Corridor, room-Elevator, Corridor-Corridor, Corridor-Elevator and legal Elevator-Elevator edges.

`transit_allowed=false` means the module may be a reachable terminal but its opposite horizontal ports are not internally joined for through-traffic.

Current non-transit modules:

- Radiation Repulsor;
- Rapidium Ark.

Every generated Corridor/Elevator must itself be Airlock-reachable. Floating infrastructure is invalid.

---

## 7. Hard constraints

A structurally feasible layout enforces all applicable rules.

### H1 — Exact multiplicity

- exactly one of each SYSTEM module;
- exactly the requested count of each PLAYER module;
- Recycler <= 1;
- Rapidium Ark <= 5;
- Corridor/Elevator decided only by solver.

### H2 — Base-mask legality

Every occupied cell is buildable (`1`). No movable module occupies `0` or `X`.

### H3 — No overlap

Each grid cell is occupied by at most one installed module, including infrastructure.

### H4 — Orientation

No rotation unless verified future evidence supports it.

### H5 — Legal ports

Connectivity exists only through compatible resolved ports/utility anchors. High rooms use floor-level access except explicit verified exceptions.

### H6 — Local connection

Every installed network module has at least one legal connection. This does not replace global reachability.

### H7 — Airlock reachability

All installed modules are reachable from Airlock.

### H8 — Non-transit behaviour

Non-transit modules may terminate routes but cannot bridge opposite sides.

### H9 — Corridor

Corridor is solver-managed 2x1 horizontal infrastructure, must fit the Base, avoid overlap, connect legally and belong to the reachable network.

### H10 — Elevator continuity

Elevator is solver-managed 2x1 infrastructure. Vertical movement exists only between immediately adjacent compatible Elevators. Every used vertical level is represented by an Elevator module.

Shifted shafts require a real horizontal transfer path. Central-shaft community layouts are not hard constraints.

### H11 — No floating infrastructure

Every selected Corridor/Elevator belongs to the Airlock-rooted network.

### H12 — Journey mass

```text
total_base_mass = sum(installed module masses)
organics_required_for_journey = total_base_mass
journey_feasible = structural_feasible and total_base_mass <= organics_capacity
```

Since Corridor/Elevator mass is 2, this is equivalent to non-SOLVER mass plus `2*corridor_count + 2*elevator_module_count`.

Structural feasibility and journey feasibility are reported separately.

---

## 8. Exact travel distance

Final `d(i,j)` is shortest legal path distance in the installed module graph.

### D1 — Endpoint modules

Source and destination module widths contribute 0.

### D2 — Direct endpoint adjacency

```text
d(A,B) = 0
```

for directly compatible endpoint ports.

### D3 — Corridor

Each traversed Corridor contributes +1.

### D4 — Elevator

Each traversed Elevator contributes +1. A four-module stack contributes 4 when all four are traversed.

### D5 — Intermediate transit module

Crossing transit module C side-to-side costs:

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

### D6 — Non-transit module

No internal side-to-side edge exists.

### D7 — Path algorithm

Use Dijkstra or an exact equivalent non-negative shortest-path algorithm. Exact distances remain reproducible and auditable.

---

## 9. Modified-Manhattan lower bound

Modified Manhattan is an admissible lower bound/search heuristic only.

Same-floor endpoints:

```text
horizontal_lb = ceil(abs(edge_x_a - edge_x_b) / 2)
```

Cross-floor endpoints:

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

Production represents F and F_LB on one exact integer scale. A room packing is prunable by this bound only when:

```text
scaled_F_LB > incumbent_scaled_F
```

Equality must remain because later tie-breakers can improve.

Fail-fast invariant:

```text
scaled_F_LB <= scaled_F_exact
```

A separate exact incumbent cut may also be applied inside a fixed-packing subproblem after an incumbent exists. That cut is not Modified Manhattan and must be reported separately.

---

## 10. Gameplay objective

For every unordered positive-weight non-SOLVER pair:

```text
pair_score(i,j) = w_i * w_j * d(i,j)
F = sum(i<j) pair_score(i,j)
```

Zero-weight modules remain subject to every hard constraint.

Accepted lexicographic order:

```text
1. lower exact F
2. lower total Base mass
3. fewer Elevator modules
4. fewer Corridor modules
```

Traffic weights come from `src/alters_base_planner/data/usage_weights.json` and are planner heuristics, not hidden game constants.

A plan may override known SYSTEM/PLAYER keys with finite numeric values in `[0, 1]`. Missing
keys inherit catalogue defaults. Overrides are immutable per-request inputs: they must not mutate
the catalogue or affect later plans. Corridor and Elevator are not endpoint destinations, retain
effective weight `0`, and are rejected from `usage_weights`. A zero override removes that room
from objective pairs only; every hard placement and connectivity requirement remains active.

Effective per-plan decimal weights are resolved once for a solve and converted through exact
rational arithmetic to integer coefficients. CP-SAT objective comparison, Dijkstra reconstruction,
modified-Manhattan room-packing pruning and all correctness oracles use the same explicit map and
`ScaledObjective` definition.

No undocumented competing objective is allowed.

---

## 11. OR-Tools / solver correctness architecture

### 11.1 Stage 1 domain — COMPLETE / MAINTAIN

`ModuleSpec` is canonical for SYSTEM/PLAYER/SOLVER modules, `ModulePlacement` represents every installed object and configuration ownership is derived from `PlacementAuthority`.

### 11.2 Stage 2 hard feasibility — COMPLETE / MAINTAIN

The reusable hard layer models:

```text
room-packing master
        -> fixed-packing Corridor/Elevator CP-SAT
        -> exact evaluator
```

It enforces room placement, utility occupancy, explicit port/anchor connectivity, non-transit behaviour, adjacent-Elevator vertical edges, Airlock-rooted flow and no floating utilities.

For a fixed packing, CP-SAT `INFEASIBLE` is a proof that no legal infrastructure network exists. `UNKNOWN` remains unknown/time-limited.

Stage 2's satisfiability-only infrastructure solver remains a maintained component, but is no longer the production objective boundary.

### 11.3 Stage 3 exact objective — COMPLETE / MAINTAIN

Production uses:

```text
CP-SAT room-packing master
        -> exact scaled room-packing lower bound
        -> exact fixed-packing source-aggregated flow objective CP-SAT
        -> independent Dijkstra cross-check
        -> exact global lexicographic incumbent
```

The fixed subproblem jointly chooses Corridor/Elevator infrastructure and exact weighted integer flows. Every unordered positive-weight room pair is oriented once by deterministic instance-ID order. Pairs with the same source share one uncapacitated commodity: source supply is the sum of their exact scaled coefficients, and each target absorbs its pair coefficient. Accepted distance costs are represented directly as conditional graph arc costs.

The fixed packing is optimized with a **single exact lexicographic-scalarized objective**, replacing the previous four sequential proof-preserving phases:

```text
1. exact scaled F
2. utility mass (equivalent to total mass for fixed rooms)
3. Elevator count
4. Corridor count
```

The mixed-radix dominance weights are derived from valid finite bounds on the lower-order objectives taken from the fixed hard model's utility-anchor domain, so the single linear objective is order-preserving with the lexicographic order and one CP-SAT solve is exactly equivalent to the sequential phases. The scalarized objective maximum is checked to fit signed 64-bit CP-SAT arithmetic before solving.

The lexicographic optimum is considered proven only on CP-SAT `OPTIMAL` for that single scalarized objective, which simultaneously proves the exact `F` optimum; a timed-out incumbent remains best-known with no proof claim.

After a feasible exact incumbent with primary objective `B` exists, production may constrain later fixed subproblems by:

```text
scaled_F <= B
```

The inequality must remain non-strict because a packing with equal F can still improve mass, Elevator count or Corridor count. If CP-SAT proves this bounded fixed model infeasible, the packing cannot match or improve the incumbent primary objective. Such a certificate is a valid exact decomposition proof even when it does not distinguish hard infrastructure infeasibility from strict objective domination. The same bound may additionally drive a proof-safe domain reduction before CP-SAT: exact integer shortest-path lower bounds on the unconditional relaxed travel graph can prove `scaled_F > bound` directly (reported as `OBJECTIVE_BOUND_INFEASIBLE` without a solve) and derive mathematically necessary per-pair distance caps whose union-of-target arc pruning removes no solution capable of satisfying `scaled_F <= bound`.

Production sets `global_objective_optimum_proven=true` only when:

- a feasible incumbent exists;
- the room-packing master is exhausted;
- every relevant packing is either fully lexicographically optimal, proven infrastructure-infeasible, strictly excluded by exact integer `F_LB > incumbent_F`, or proven unable to satisfy the equality-preserving exact incumbent cut `scaled_F <= incumbent_F`;
- no time limit stopped the search;
- no layout-attempt limit stopped the search.

Otherwise a feasible result is best-known feasible.

### 11.4 Model validation / fail-fast

Every CP-SAT model passes `CpModel.validate()` before solving. Internal mathematical/model inconsistencies fail fast rather than being hidden as ordinary infeasibility.

A `MODEL_INVALID` status from the fixed-packing lexicographic-scalarized model is an internal model/solver contradiction and must fail fast rather than be reported as ordinary timeout or infeasibility. An `INFEASIBLE` status under the incumbent cut remains the valid exact certificate that the packing cannot match the incumbent primary objective.

### 11.5 Global budget

`time_limit_s` is one global wall-clock budget for the complete planning call. A fixed-packing subproblem receives only the remaining time, and its model construction consumes that same remaining budget.

`max_layout_attempts` is also a search-completeness limit; reaching it suppresses a global proof.

Persist at least:

```text
room_packings_examined
connected_candidates_examined
fixed_objective_optima_proven
manhattan_pruned_count
incumbent_bound_pruned_count
search_time_s
time_limit_reached
search_exhausted
global_objective_optimum_proven
```

---

## 12. Input contract

Player configuration includes Base tier and PLAYER module counts. Solver/output sections control budget and paths.

Reject:

- unsupported Base tiers;
- unknown module keys;
- SYSTEM/SOLVER keys in player room counts;
- booleans, fractions or negative counts;
- verified count-limit violations;
- unknown config fields;
- invalid/non-finite/non-positive budgets;
- unsupported objectives;
- invalid output paths.

SYSTEM modules are injected automatically; Corridor/Elevator are generated automatically.

---

## 13. Output contract

Every run persists machine-readable diagnostics. Feasible JSON schema version 3 includes at least:

```text
status
Base tier / geometry provenance
installed module placements
resolved ports
solver-generated infrastructure
objective_value / exact F
objective_scale / scaled_objective_value
scaled_modified_manhattan_lower_bound
modified_manhattan_lower_bound
pairwise distances and contributions
traffic weights
Elevator/Corridor counts
room/utility/total mass
Organics requirement/capacity/margin
journey feasibility
global_objective_optimum_proven
search diagnostics
```

PNG/SVG preserve:

```text
cell height = 2 * cell width
```

and distinguish unavailable/core/buildable cells, module types, Corridors and Elevators.

---

## 14. Evidence and provenance

Use this precedence for domain facts:

1. reproducible extracted/game-exact data or direct in-game measurement;
2. validated project geometry/audit data with tests;
3. current direct module documentation;
4. multiple independent high-quality guides;
5. community reports for otherwise undocumented mechanics;
6. heuristic inference only when explicitly labelled and never as a hard game fact.

`docs/ROOM_DATA_AUDIT.md` retains source conflicts rather than hiding them.

Current audited decisions include:

- Dormitory mass 8 despite conflicting aggregate data likely reflecting construction cost;
- Park with Bench 6x1;
- Radiation Repulsor top access and non-transit;
- Rapidium Ark non-transit and max 5;
- Recycler max 1;
- weaker Tier-I Organics-capacity provenance.

---

## 15. Development roadmap

### Stage 0 — Data/contract stabilization — COMPLETE / MAINTAIN

Validated Base geometry, module catalogue, ports, traffic-weight audit, config validation, exact graph evaluator and multi-version CI.

### Stage 1 — Unified Module domain — COMPLETE / MAINTAIN

Delivered SYSTEM/PLAYER/SOLVER authority, one catalogue/placement model, canonical utilities, shared geometry and authority-driven config validation.

### Stage 2 — Exact hard-feasibility decomposition — COMPLETE / MAINTAIN

Delivered exact fixed-packing Corridor/Elevator feasibility with shared occupancy, legal ports, Airlock-rooted flow, non-transit handling, Elevator continuity, no floating utilities, exact infeasibility proof and evaluator cross-check.

### Stage 3 — Exact objective decomposition — COMPLETE / HARDEN

Delivered:

- exact source-aggregated weighted-flow representation for fixed room packings;
- exact rational-to-integer objective scaling;
- exact fixed-packing `F -> mass -> Elevator -> Corridor` proof phases;
- admissible exact integer room-packing lower bounds;
- strict-bound global pruning;
- global proof propagation through room-packing exhaustion;
- independently exhaustive fixed/global reference oracles;
- production-vs-oracle known-optimum regression tests;
- explicit suppression of false proof on time/attempt limits.

Stage-3 completion means the architecture can prove the global accepted objective when configured search completes. It does not imply full Base I-IV instances will always complete within practical budgets.

### Stage 4 — Performance and benchmark suite — IN PROGRESS

Delivered or active:

- representative Tier I-IV benchmark configurations;
- fixed-subproblem model-size, construction and CP-SAT timing metrics;
- auditable pruning/proof-completion diagnostics;
- opt-in reproducible benchmark workflow;
- exact equality-preserving incumbent objective cut for fixed subproblems;
- single exact mixed-radix lexicographic-scalarized fixed-objective solve (replacing the four sequential tie-breaker phases), with dominance weights derived from the fixed hard model's utility-anchor domain and a signed-64-bit objective safety check;
- exact source-aggregated weighted integer flow, reducing up to `N * (N - 1) / 2` pair commodities to at most `N - 1` source commodities for `N` positive-weight rooms.

Remaining Stage-4 work includes:

- representative before/after benchmark evidence for accepted optimizations;
- stronger mathematically safe domain reduction and symmetry breaking;
- objective/incumbent/bound quality tracking where it materially improves diagnosis;
- regression thresholds based on reproducible evidence rather than one noisy timing run.

No performance claim without reproducible benchmark evidence.

### Stage 5 — User-facing planning quality

The Streamlit entry point supports a default Form mode and an alternative JSON-file mode through
one canonical parser and solve path. Form mode exposes a prominent Plan settings section with Base
tier and optimization time, locked mandatory SYSTEM counts, bounded PLAYER counts, solver-generated
infrastructure labels, editable/resettable per-plan usage weights, advanced layout-attempt controls
and reproducible pre-solve plan JSON download. The interactive default time is 60 seconds. A stored
result and optimized Base image survive ordinary reruns only while a deterministic signature of the
semantic planning inputs remains unchanged; changed settings hide the stale result and request a new
solve. Continue improving journey warnings and best-known-vs-proven explanations without weakening
solver semantics.

### Stage 6 — Progression-aware mobile Base

After Stage 3/4 stability, add explicit `act/game_state`, unlocks and already-built/non-removable state. Do not emulate progression with ad-hoc mandatory-list changes.

### Stage 7 — The Last Variable DLC — DEFERRED

DLC topology/module rules differ materially. Implement as a separate environment only when exact geometry/data are sufficient. Never approximate DLC with mobile Base masks.

---

## 16. Testing strategy

Mechanics/solver changes require regression coverage for the relevant layer.

Minimum categories:

- Base dimensions/core coordinates;
- module dimensions/masses/count limits;
- authority partitions;
- standard floor ports/top-access exception;
- 1x1 logical ports;
- direct adjacency d=0;
- Corridor/Elevator costs;
- intermediate-room width;
- non-transit bridge rejection;
- Airlock reachability;
- utility overlap/Elevator continuity/no floating infrastructure;
- hard-feasibility proof cases;
- modified-Manhattan admissibility;
- exact scaled objective reconstruction;
- objective contribution invariant;
- exact incumbent-cut equality and bounded-infeasibility semantics;
- mass/journey calculation;
- config ownership/count validation;
- time/attempt budget semantics;
- independently exhaustive fixed/global known optima;
- production Stage-3 decomposition versus global oracle;
- end-to-end PNG/SVG/JSON generation.

CI runs Ruff and pytest on Python 3.11, 3.12 and 3.13.

---

## 17. ChatGPT-driven development protocol

When developing through dialogue:

1. read this file before major architecture/solver changes;
2. inspect current `main`, CI, relevant code/tests and normative docs;
3. preserve the Base-planner goal and prevent feature drift;
4. change game mechanics only with evidence or explicit PM decision;
5. prioritize solver correctness over cosmetic features;
6. add tests for new hard/distance/objective invariants;
7. keep normative docs synchronized with implementation;
8. never hide incomplete search, time limits or missing optimality proof;
9. use auditable branch/PR workflow for major solver changes;
10. report project-level progress, CI, remaining risks and the highest-value next step.

---

## 18. Definition of project success

The core mobile-Base planner succeeds when it can:

1. model SYSTEM, PLAYER and SOLVER modules correctly;
2. prove hard feasibility/infeasibility under the exact Base mask;
3. choose Corridor/Elevator infrastructure through exact optimization;
4. enforce ports, reachability, transit and Elevator rules;
5. compute exact travel distances and weighted F;
6. minimize true F and tie-breakers and provide a valid global proof when search completes;
7. report mass/journey feasibility correctly;
8. produce auditable JSON and graphical plans;
9. pass correctness and benchmark regressions;
10. remain extensible to progression/DLC modes without corrupting the mobile-Base model.

Items 1-6 now have an exact production decomposition and independently exhaustive tiny-instance validation. The principal remaining technical risk is **scalability**: realistic runs may stop before global proof because of time or attempt limits. Such outputs must remain labelled best-known feasible rather than globally optimal.
