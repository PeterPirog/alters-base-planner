# The Alters Base Planner

Optimization-based planner for the mobile Base in **The Alters**.

The player selects Base Tier I-IV and exact counts of optional modules. The planner automatically adds baseline mandatory modules and chooses all Corridor/Elevator infrastructure.

The project is designed as an auditable optimizer rather than a visual layout toy: Base geometry, ports, occupancy, connectivity, travel distances, mass, journey feasibility and optimality proof status are explicit in the result.

## Solver status

The canonical domain uses one `ModuleSpec` / `ModulePlacement` model:

```text
SYSTEM  = baseline mandatory modules, injected exactly once
PLAYER  = optional modules, exact user-requested counts
SOLVER  = Corridor/Elevator infrastructure selected by optimization
```

The production solver now uses an **exact objective decomposition**:

```text
CP-SAT SYSTEM/PLAYER room-packing master
        -> exact integer modified-Manhattan lower bound
        -> exact fixed-packing pair-flow CP-SAT
             optional exact cut: scaled_F <= incumbent_scaled_F
             jointly selects Corridor/Elevator infrastructure
             minimizes exact weighted travel F
             then mass -> Elevators -> Corridors
        -> independent exact Dijkstra cross-check
        -> exact lexicographic comparison across room packings
```

The old deterministic greedy post-router is not part of the correctness boundary.

For a fixed room packing, the pair-flow subproblem jointly chooses legal infrastructure and proves the accepted lexicographic optimum when CP-SAT returns `OPTIMAL` for its single exact mixed-radix lexicographic-scalarized objective. Across room packings, the master may prune by the admissible lower bound only when:

```text
scaled_F_LB > incumbent_scaled_F
```

After an exact incumbent exists, later fixed subproblems also receive the proof-safe constraint:

```text
scaled_F <= incumbent_scaled_F
```

Both rules deliberately preserve equality where required: an equal primary objective can still improve Base mass, Elevator count or Corridor count. If the bounded exact fixed model is proven infeasible, that packing cannot match or improve the incumbent primary objective and can be excluded without weakening the global proof.

A run sets:

```text
global_objective_optimum_proven = true
```

**only** when the room-packing search is exhausted and every relevant packing is either solved to its exact fixed-packing optimum, proven infrastructure-infeasible, or excluded by a proof-safe exact bound. A time limit or layout-attempt limit therefore yields a best-known feasible result, never a false proof.

The exhaustive reference solvers remain independent correctness oracles for tiny instances:

```text
fixed_objective_oracle.py
    exhaustive infrastructure optimization for one fixed room packing

fixed_flow_objective_solver.py
    production fixed-packing pair-flow formulation
    cross-validated against the exhaustive fixed oracle

global_objective_oracle.py
    exhaustive tiny-instance room + infrastructure proof oracle
```

See `PROJECT_SYSTEM_REQUIREMENTS.md` for the project-level contract, `docs/OPTIMIZATION_MODEL.md` for the mathematical solver contract, `docs/STAGE3_OBJECTIVE_ORACLE.md` for proof/validation details and `docs/BENCHMARKS.md` for Stage-4 measurement methodology.

## Base I-IV geometry

Canonical mobile-Base masks:

```text
src/alters_base_planner/data/base-size1.csv
src/alters_base_planner/data/base-size2.csv
src/alters_base_planner/data/base-size3.csv
src/alters_base_planner/data/base-size4.csv
```

CSV semantics:

```text
0 = unavailable
1 = buildable
X = fixed blocked core
```

| Tier | Grid | Fixed core | Organics capacity |
|---|---:|---|---:|
| I | 22x12 | x=8..11, y=6..7 | 300* |
| II | 26x14 | x=10..13, y=7..8 | 450 |
| III | 30x16 | x=12..15, y=8..9 | 700 |
| IV | 34x18 | x=14..17, y=9..10 | 800 |

`*` Tier-I capacity has weaker provenance than Tier II-IV and remains explicitly audited.

The CSV masks are exact runtime geometry. They are asymmetric and must not be symmetrized or recentered. See `docs/BASE_GEOMETRY_REFERENCE.md`.

## Mandatory and optional modules

The planner baseline automatically contains exactly one SYSTEM instance of:

- Airlock;
- Captain's Cabin;
- Command Center;
- Communication Room;
- Kitchen;
- Machinery;
- Quantum Computer;
- The Womb.

These cannot be configured by the player.

PLAYER modules use exact requested counts. Verified static limits currently include:

```text
Recycler <= 1
Rapidium Ark <= 5
```

SOLVER modules are:

```text
Corridor  2x1, mass 2
Elevator  2x1, mass 2
```

Their counts and positions are optimizer outputs.

## Ports and connectivity

The Base grid uses `(0,0)` at top-left, x right and y down. Module-local ports are floor-relative:

```text
local y = 0     -> floor
local y = H - 1 -> top

LEFT  = (0, 0)
RIGHT = (W - 1, 0)
```

World conversion:

```text
world_x = module.x + local_x
world_y = module.y + (H - 1 - local_y)
```

Ordinary tall rooms therefore connect at their floor, not centroid or ceiling.

Verified exceptions/rules:

- Radiation Repulsor uses top access and is non-transit;
- Rapidium Ark is non-transit;
- non-transit modules must still reach Airlock but cannot be used as walk-through bridges;
- vertical travel exists only through immediately adjacent compatible Elevator modules;
- every installed Corridor/Elevator must belong to the Airlock-rooted network.

Resolved absolute ports are persisted in result JSON.

## Hard-feasibility rules

A legal layout enforces:

- exactly one of each SYSTEM module;
- exact requested PLAYER counts and verified count limits;
- exact irregular Base mask;
- no use of `0` or `X` cells;
- no overlap among any SYSTEM/PLAYER/SOLVER modules;
- no unsupported rotation;
- legal explicit port/anchor connections only;
- at least one legal network connection for each installed module;
- global reachability from Airlock;
- non-transit modules cannot bridge other modules;
- continuous legal Elevator connectivity;
- no floating Corridor/Elevator islands.

Community preferences such as a central elevator shaft may guide search but are not hard constraints.

## Exact travel objective

Traffic weights are planner heuristics from:

```text
src/alters_base_planner/data/usage_weights.json
```

They are not hidden game constants.

Each plan may override SYSTEM and PLAYER weights with an optional top-level
`usage_weights` object. Omitted keys keep their catalogue defaults. Overrides are isolated to
that plan and never mutate the catalogue. Corridor and Elevator remain path infrastructure with
effective endpoint weight `0` and cannot be overridden.

For every unordered positive-weight room pair:

```text
F = sum(i<j) w_i * w_j * d(i,j)
```

where `d(i,j)` is the shortest legal path in the installed module graph:

```text
source endpoint module          = 0
destination endpoint module     = 0
direct compatible adjacency     = 0
one Corridor module             = +1
one Elevator module             = +1
intermediate transit room C     = +width(C)
non-transit room                = cannot be crossed
```

The accepted lexicographic optimization order is:

```text
1. lower exact F
2. lower total Base mass
3. fewer Elevator modules
4. fewer Corridor modules
```

Effective per-plan decimal weights are converted to exact rational/integer coefficients for
CP-SAT and proof comparisons. The same resolved map is used by pair-flow optimization,
modified-Manhattan bounds and independent Dijkstra evaluation. Result JSON includes both the
user-facing objective, effective room weights and its exact scaled integer representation.

## Modified-Manhattan lower bound

Modified Manhattan is an admissible search bound only, never final travel distance.

Same-floor endpoint ports:

```text
horizontal_lb = ceil(abs(edge_x_a - edge_x_b) / 2)
```

Cross-floor endpoint ports:

```text
horizontal_lb = ceil(abs(anchor_x_a - anchor_x_b) / 2)
vertical_lb   = abs(edge_y_a - edge_y_b) + 1
```

The solver maintains:

```text
F_LB <= F_exact
```

A violation is an internal model/evaluator error and fails fast.

## Base Mass and journey feasibility

For the mobile Base:

```text
total_base_mass = sum(installed module masses)
organics_required_for_journey = total_base_mass
journey_feasible = structural_feasible and total_base_mass <= organics_capacity
```

Structural feasibility and journey feasibility are deliberately separate. An overweight legal Base is not journey-feasible.

## Output

A feasible run can emit:

```text
layout.png
layout.svg
layout.json
```

The JSON schema version is currently `2`. It contains module placements, resolved ports, exact/scaled objective data, lower bounds, pair distances and contributions, traffic weights, infrastructure counts, mass/journey metrics, search diagnostics and `global_objective_optimum_proven`.

PNG/SVG preserve the project grid aspect ratio and distinguish unavailable/core/buildable cells and module types.

## Configuration

Example `config/plan.json`:

```json
{
  "$schema": "./plan.schema.json",
  "base_tier": 2,
  "rooms": {
    "workshop": 1,
    "research_lab": 1,
    "dormitory": 1,
    "small_storage": 2
  },
  "usage_weights": {
    "airlock": 1.0,
    "workshop": 0.75,
    "small_storage": 0.0
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

SYSTEM modules are injected automatically. Corridor/Elevator counts are never user inputs.
`usage_weights` is optional and may contain only known SYSTEM/PLAYER module keys with finite
numeric values from `0.0` through `1.0`. A zero-weight room still must be placed and connected.

## Run

Python **3.11 or newer** is required.

### Windows PowerShell

```powershell
git clone https://github.com/PeterPirog/alters-base-planner.git
cd alters-base-planner
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m alters_base_planner.cli config/plan.json
```

Equivalent installed command:

```powershell
alters-base-planner config/plan.json
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

Open `http://localhost:8501/`. The default **Form** mode provides:

- Base Tier I-IV selection;
- visible, locked count `1` controls for all mandatory SYSTEM modules;
- exact PLAYER room-count controls with catalogue limits such as Recycler `<= 1` and Rapidium
  Ark `<= 5`;
- Corridor and Elevator shown as solver-generated `AUTO` infrastructure;
- a fixed-row SYSTEM/PLAYER usage-weight editor and **Reset weights to defaults** action;
- advanced time-limit and layout-attempt controls;
- **Download plan JSON** before solving.

The **JSON file** mode remains a fully supported alternative. Uploaded and form-generated data
use the same canonical parser and the same exact `solve_plan` call. Generated `alters-plan.json`
files include every effective SYSTEM/PLAYER weight and can be uploaded again without losing the
configuration.

## Development

```bash
ruff check .
pytest -q
```

CI runs both commands on Python 3.11, 3.12 and 3.13.

Stage-4 benchmark harness:

```bash
alters-base-benchmark --suite smoke
alters-base-benchmark --suite representative
```

Representative benchmarks are deliberately opt-in and are not part of normal CI. See `docs/BENCHMARKS.md`.

## Roadmap

```text
Stage 0  data/contract stabilization           COMPLETE / maintain
Stage 1  unified Module domain                 COMPLETE / maintain
Stage 2  exact hard-feasibility decomposition  COMPLETE / maintain
Stage 3  exact objective decomposition         COMPLETE / harden
Stage 4  benchmark/performance engineering     IN PROGRESS
Stage 5  user-facing planning quality          planned
Stage 6  progression-aware mobile Base         deferred
Stage 7  The Last Variable DLC                 deferred until exact data
```

Stage 3 correctness is validated on independently exhaustive tiny known-optimum cases. Stage 4 is improving scalability without weakening those exact semantics. This does **not** imply that a realistic Tier I-IV run will always finish a global proof inside its configured budget; when it does not, the planner reports the best-known feasible result explicitly.

The DLC is intentionally not approximated with mobile-Base geometry.

## License / trademarks

This is an unofficial fan tool. *The Alters* and related trademarks belong to their respective owners.
