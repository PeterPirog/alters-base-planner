# The Alters Base Planner

Optimization-based planner for the mobile Base in **The Alters**.

The user selects Base Tier I-IV and requested counts of optional modules. Baseline mandatory modules are added automatically. Corridor and Elevator are solver-controlled infrastructure and are added automatically when needed.

The project aims at a mathematically auditable optimizer, not a visual layout toy: geometry, legal ports, connectivity, travel distances, Base Mass and solver optimality status are all explicit in the result.

## Project status

The domain model is unified around one `ModuleSpec` / `ModulePlacement` abstraction:

```text
SYSTEM  = baseline mandatory modules, added exactly once
PLAYER  = optional modules whose exact counts come from the user
SOLVER  = Corridor/Elevator infrastructure selected by optimization
```

Corridor and Elevator are canonical module types in the catalogue and in result geometry.

The active production solver now uses an **exact hard-feasibility decomposition**:

```text
CP-SAT SYSTEM/PLAYER room-packing master
        -> exact CP-SAT Corridor/Elevator connectivity subproblem
        -> exact graph distance evaluation
        -> exact F ranking of examined connected candidates
```

For every examined fixed room packing, the infrastructure subproblem decides Corridor/Elevator occupancy, shared no-overlap, explicit port attachment, stacked-Elevator vertical edges, non-transit behaviour, Airlock-rooted connectivity and the absence of floating utilities. If that subproblem returns `INFEASIBLE`, no legal Corridor/Elevator network exists for that fixed packing under the accepted hard model.

This removes the old deterministic greedy post-router from correctness. It does **not** yet prove the global gameplay optimum: the production Stage-2 subproblem returns one hard-feasible infrastructure witness.

Stage 3 is now under exact-objective validation. The repository contains:

```text
fixed_objective_oracle.py
    exhaustive exact infrastructure optimization for one fixed room packing

fixed_flow_objective_solver.py
    exact CP-SAT pair-flow formulation for one fixed room packing
    cross-validated against the exhaustive oracle

global_objective_oracle.py
    exhaustive tiny-instance room + infrastructure proof oracle
```

The pair-flow formulation jointly selects Corridor/Elevator infrastructure and minimizes the exact weighted travel objective before the accepted mass/Elevator/Corridor tie-breakers. It is a scalable candidate, not yet the production correctness boundary. Production `global_objective_optimum_proven` therefore remains false until the room-packing master and exact objective subproblem are integrated with valid global bounds/proof semantics.

See `PROJECT_SYSTEM_REQUIREMENTS.md` for the project-level source of truth, `docs/OPTIMIZATION_MODEL.md` for the normative mathematical/solver contract, and `docs/STAGE3_OBJECTIVE_ORACLE.md` for the Stage-3 validation architecture.

## Validated Base I-IV geometry

The four built-in mobile-Base shapes are stored as separate CSV files:

```text
src/alters_base_planner/data/base-size1.csv
src/alters_base_planner/data/base-size2.csv
src/alters_base_planner/data/base-size3.csv
src/alters_base_planner/data/base-size4.csv
```

CSV semantics:

```text
0 = outside usable Base
1 = buildable cell
X = immovable blocked core cell
```

The supplied 2026-09-11 spatial analysis contains explicit Base I-IV matrices. Repository CSVs were compared against those matrices and match them exactly, including the asymmetric fixed 4x2 core.

| Tier | Grid | Fixed core | Organics capacity |
|---|---:|---|---:|
| I | 22x12 | x=8..11, y=6..7 | 300* |
| II | 26x14 | x=10..13, y=7..8 | 450 |
| III | 30x16 | x=12..15, y=8..9 | 700 |
| IV | 34x18 | x=14..17, y=9..10 | 800 |

`*` Tier-I value is the current planner value and has weaker provenance than Tier II-IV; the audit keeps that distinction explicit.

The CSV data are runtime geometry. Do not symmetrize the masks or recenter the core. Detailed provenance is recorded in `docs/BASE_GEOMETRY_REFERENCE.md`.

## Module ownership and configuration

The current baseline automatically contains exactly one SYSTEM instance of:

- Airlock;
- Captain's Cabin;
- Command Center;
- Communication Room;
- Kitchen;
- Machinery;
- Quantum Computer;
- The Womb.

These modules must not be listed in the user `rooms` configuration.

PLAYER modules are optional and use exact requested counts. Verified count ceilings currently include:

```text
Recycler <= 1
Rapidium Ark <= 5
```

SOLVER modules are:

```text
Corridor  2x1, mass 2
Elevator  2x1, mass 2
```

The canonical keys `corridor` and `elevator` are rejected from player room counts. Unknown aliases such as `corridors` and `elevators` are rejected as unknown keys.

## Explicit module ports

Standard modules expose logical LEFT/RIGHT ports in **module-local floor-relative coordinates**:

```text
local y = 0     -> floor
local y = H - 1 -> top

LEFT  = (0, 0)
RIGHT = (W - 1, 0)
```

The absolute Base grid uses the opposite vertical convention (`y=0` at the top), so port conversion is:

```text
world_y = module.y + (H - 1 - local_y)
```

A normal multi-row module is therefore accessed on its physical floor row, never through its centroid or ceiling.

For a 1x1 module, LEFT and RIGHT occupy the same physical cell but remain distinct logical sides.

Verified exception: **Radiation Repulsor** uses top access and is non-transit. **Rapidium Ark** is also non-transit. Non-transit modules still must connect to the Base, but they cannot act as walk-through bridges.

Resolved absolute port coordinates are persisted in `layout.json` for auditability.

## Hard-feasibility rules

A structurally valid layout must satisfy, among other invariants:

- exact SYSTEM and requested PLAYER multiplicity;
- exact irregular Base mask;
- no use of `0` or `X` cells;
- no overlap among any modules;
- no unsupported rotation;
- legal explicit ports only;
- at least one legal network connection for every installed module;
- global reachability from Airlock;
- non-transit modules cannot bridge other modules;
- Corridor/Elevator are solver-managed;
- vertical travel only through immediately adjacent compatible Elevator modules;
- no floating Corridor/Elevator islands.

The central/right-side elevator layout seen in community designs is a useful search intuition, **not a hard constraint**.

## Objective function

Each room-like module has a gameplay traffic weight `w` in:

```text
src/alters_base_planner/data/usage_weights.json
```

These are planner heuristics, not hidden game constants.

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
| Recycler / passive modules / Storage | 0.00 |
| Corridor / Elevator | 0.00 |

For every unordered pair of positive-weight endpoint modules:

```text
pair_score(i,j) = w_i * w_j * d(i,j)
F = sum_{i<j} pair_score(i,j)
```

The accepted optimization order is:

```text
1. lower exact F
2. lower total Base Mass
3. fewer Elevator modules
4. fewer Corridor modules
```

## Exact distance semantics

Final distance is shortest legal path distance in the installed module graph.

```text
start endpoint module           = 0
destination endpoint module     = 0
direct compatible adjacency     = 0
one traversed Corridor module   = +1
one traversed Elevator module   = +1
intermediate transit module C   = +width(C)
non-transit module              = cannot be crossed
```

Example:

```text
A(4x1) | C(6x1) | B(8x1)

d(A,C) = 0
d(C,B) = 0
d(A,B) = 6
```

A four-module Elevator stack contributes 4 when all four Elevator modules are traversed.

## Modified Manhattan lower bound

Modified Manhattan is used only as an admissible search lower bound, never as final distance.

Same floor:

```text
horizontal_lb = ceil(abs(edge_x_a - edge_x_b) / 2)
```

Different floors use external 2x1 utility anchors:

```text
horizontal_lb = ceil(abs(anchor_x_a - anchor_x_b) / 2)
vertical_lb   = abs(edge_y_a - edge_y_b) + 1
```

The weighted bound is:

```text
F_LB = sum_{i<j} w_i * w_j * LB(i,j)
```

The implementation must maintain:

```text
F_LB <= F_exact
```

A violation is an internal solver/model error and fails fast.

## Base Mass and journey feasibility

Every structurally feasible layout reports:

```text
room_mass
utility_mass
total_base_mass
organics_required_for_journey
organics_tank_capacity
capacity_margin
journey feasibility
mass_breakdown
```

For the mobile Base:

```text
organics_required_for_journey = total_base_mass
```

Structural feasibility and journey feasibility are separate. A layout can be geometrically/topologically valid yet too heavy to travel. Such a layout must never be labelled journey-feasible.

Room size/mass evidence and source conflicts are recorded in `docs/ROOM_DATA_AUDIT.md`.

## Example graphical result

The planner generates PNG/SVG plans from the selected exact Base mask.

![Example optimized base layout](docs/example-layout.svg)

The rendering distinguishes unavailable/core/buildable cells, module types, Corridors and Elevators. One y-grid cell is rendered twice as tall as one x-grid cell.

The diagram/report includes key optimization and mass metrics and indicates whether global optimality has been proven. Under the current production Stage-2 hard-feasibility architecture, global objective optimality is still not proven.

## Player configuration

Edit `config/plan.json`:

```json
{
  "$schema": "./plan.schema.json",
  "base_tier": 2,
  "rooms": {
    "workshop": 1,
    "research_lab": 1,
    "dormitory": 1,
    "infirmary": 1,
    "greenhouse": 1,
    "refinery": 1,
    "small_storage": 2,
    "social_room": 1,
    "recycler": 1
  },
  "solver": {
    "objective": "weighted_pair_distance",
    "time_limit_s": 15,
    "max_layout_attempts": 30
  },
  "output": {
    "svg": "layout.svg",
    "png": "layout.png",
    "json": "layout.json"
  }
}
```

SYSTEM modules are injected automatically. Corridor/Elevator counts are solver outputs.

## Run from a fresh clone

Python **3.11 or newer** is required.

### Windows PowerShell

Because this repository is private, clone it while authenticated to GitHub:

```powershell
git clone https://github.com/PeterPirog/alters-base-planner.git
cd alters-base-planner

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Run:

```powershell
python -m alters_base_planner.cli config/plan.json
```

Equivalent installed command:

```powershell
alters-base-planner config/plan.json
```

Configured output normally includes:

```text
layout.png
layout.svg
layout.json
```

Open the PNG from PowerShell:

```powershell
Start-Process .\layout.png
```

### Linux / macOS

```bash
git clone https://github.com/PeterPirog/alters-base-planner.git
cd alters-base-planner
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m alters_base_planner.cli config/plan.json
```

## Streamlit UI

```bash
python -m streamlit run app.py
```

The UI uses the same configuration and solver semantics as the CLI, clearly separates structural/journey feasibility, and exposes the auditable result JSON.

## Result JSON

The JSON output persists the exact objective for the returned candidate, modified-Manhattan lower bound, pairwise distances/contributions, resolved ports, usage weights, installed solver infrastructure, geometry provenance, mass metrics, journey feasibility and search/optimality diagnostics.

A current feasible production result has:

```text
global_objective_optimum_proven = false
```

until the complete joint objective problem (or exact decomposition with valid objective bounds) establishes a proof.

## Development

```bash
ruff check .
pytest -q
```

CI runs both commands on Python 3.11, 3.12 and 3.13.

## Roadmap summary

```text
Stage 0  data/contract stabilization           COMPLETE / maintain
Stage 1  unified Module domain                 COMPLETE / maintain
Stage 2  exact hard-feasibility decomposition  COMPLETE / maintain
Stage 3  exact objective integration           IN PROGRESS
Stage 4  benchmark/performance suite           NEXT / overlaps Stage 3
Stage 5  user-facing planning quality          planned
Stage 6  progression-aware mobile Base         deferred
Stage 7  The Last Variable DLC                 deferred until exact data
```

Stage 3 now has exhaustive fixed/global reference oracles and a pair-flow exact fixed-packing candidate. The next milestone is benchmarked master/subproblem integration with valid global bounds and proof propagation.

The DLC is intentionally not approximated with mobile Base geometry.

## License / trademarks

This is an unofficial fan tool. *The Alters* and related trademarks belong to their respective owners.
