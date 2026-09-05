# The Alters Base Planner

Optimization-based planner for the mobile base in **The Alters**.

The player selects the base tier and requested room counts in `config/plan.json`. Corridors and Elevators are never configured manually: the planner places the requested rooms and adds the required access network automatically.

## Current model

The planner has two layers:

1. **hard constraints** — every requested/mandatory module must fit the selected Base tier, avoid the immovable core, avoid overlaps and belong to one legal walkable network rooted at the Airlock;
2. **one optimization objective** — minimize the weighted sum of pairwise room distances.

The complete normative model is documented in `docs/OPTIMIZATION_MODEL.md`.

## Objective function

Each room type has a gameplay usage weight `w` in `src/alters_base_planner/data/usage_weights.json`.

Examples:

| Module | Weight |
|---|---:|
| Airlock | 1.00 |
| Workshop | 0.90 |
| The Womb | 0.10 |
| Quantum Computer | 0.10 |
| Small/Medium/Large Storage | 0.00 |

For every unordered pair of installed rooms with positive weight:

```text
d(i,j) = minimum legal communication-module distance between rooms i and j
pair_score(i,j) = w(i) * w(j) * d(i,j)
```

The final objective is:

```text
F = sum_{i<j} w(i) * w(j) * d(i,j)
```

The optimal layout is the hard-feasible layout with the smallest `F`.

### Distance semantics

The distance model intentionally ignores the internal length of rooms:

```text
directly adjacent rooms = 0
one Corridor module      = +1
one Elevator module      = +1
room internal traversal  = 0
```

Therefore:

```text
[Airlock][Workshop]                    -> distance 0
[Airlock][Corridor][Workshop]          -> distance 1
[Airlock][Corridor][Corridor][Workshop]-> distance 2
```

A four-module Elevator stack contributes **4 points** if all four Elevator modules are used by the path. Every individual Elevator is `+1`.

Storage rooms have weight `0`, so they are excluded from objective pairs, but they remain normal physical modules subject to all hard placement and connectivity rules.

## Hard constraints

The solver enforces or validates:

- exact requested room counts;
- mandatory story/core rooms automatically included;
- selected Base I-IV irregular buildable mask;
- no overlap with the immovable Organics/core obstruction;
- no room/module overlap;
- no unsupported module rotation;
- legal left/right access ports at the documented connection level;
- Corridors only for horizontal utility connectivity;
- vertical connectivity only through contiguous Elevator modules at the same x-coordinate;
- one connected access network rooted at the Airlock;
- terminal/non-transit modules such as Rapidium Ark and Radiation Repulsor cannot be used as walk-through bridges;
- every installed Corridor/Elevator belongs to the accessible network.

## Base geometry status

Current public evidence supports the structural semantics:

- circular/wheel-shaped base;
- row-dependent usable horizontal width;
- narrower top/bottom rows;
- external rectangular holding area is temporary rearrangement space, not final usable base space;
- immovable Organics/core obstruction;
- Organics capacities 300 / 450 / 700 / 800 for Base I-IV.

Exact cell-by-cell masks for Base I-IV are still not authoritative. The current profiles in `src/alters_base_planner/data/base_grids.json` are deliberately marked `verified: false` until calibrated from clean build-mode screenshots or extracted game data.

## Base Mass and journey cost

Every feasible layout also reports Base Mass because journey Organics equal total Base Mass.

```text
room_mass
+ utility_mass
= total_base_mass
= organics_required_for_journey
```

Each Corridor has mass 2.
Each Elevator module has mass 2.

The result also reports:

```text
organics_tank_capacity
capacity_margin
travel_feasible_at_full_tank
mass_breakdown
```

Mass is **not** part of the primary objective. If two examined layouts have exactly the same weighted-distance score, lower Base Mass may be used only as a deterministic tie-breaker.

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
    "json": "layout.json"
  }
}
```

Rules:

- omit rooms you do not want or set their count to `0`;
- mandatory rooms are added automatically and must not be configured manually;
- `corridor` and `elevator` are not valid configuration keys;
- unknown room names fail fast;
- JSON Schema validation is available in `config/plan.schema.json`.

## Result JSON

For every connected solution the result includes optimization audit data:

```json
{
  "optimization": {
    "objective": "sum_i_lt_j(weight_i * weight_j * distance_i_j)",
    "weighted_distance_score": 3.075,
    "pairwise_distances": {
      "airlock-1|workshop-1": 1,
      "airlock-1|command-1": 2,
      "workshop-1|command-1": 1
    },
    "pairwise_contributions": {
      "airlock-1|workshop-1": 0.9,
      "airlock-1|command-1": 1.5,
      "workshop-1|command-1": 0.675
    }
  },
  "journey": {
    "total_base_mass": 320,
    "organics_required": 320,
    "organics_tank_capacity": 450,
    "capacity_margin": 130,
    "travel_feasible_at_full_tank": true
  }
}
```

The objective can therefore be audited directly:

```text
weighted_distance_score = sum(pairwise_contributions.values())
```

## Optimization engine status

The current implementation:

1. enumerates legal room placements with OR-Tools CP-SAT;
2. rejects overlap/out-of-mask placements;
3. constructs a legal Corridor/Elevator access network;
4. computes exact shortest-path module distance for every positive-weight room pair;
5. evaluates `F` exactly for that candidate;
6. retains the smallest `F` among examined connected candidates;
7. persists Base Mass and journey metrics.

The current placement + post-router architecture does **not yet prove** that the best examined `F` is the global optimum across the entire joint room + Corridor + Elevator search space. Results therefore expose:

```text
global_objective_optimum_proven = false
```

The next solver milestone is a joint exact placement/connectivity/path model. Only then should the flag become `true`.

## Install

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
# source .venv/bin/activate

pip install -e '.[dev]'
```

## CLI

```bash
alters-base-planner
```

or:

```bash
alters-base-planner path/to/my-plan.json
```

## Streamlit

```bash
streamlit run app.py
```

## Project structure

```text
config/
  plan.json
  plan.schema.json
app.py
docs/
  OPTIMIZATION_MODEL.md
src/alters_base_planner/
  base.py
  catalog.py
  cli.py
  config.py
  data/
    base_grids.json
    usage_weights.json
  distance.py
  engine.py
  models.py
  render.py
tests/
.github/workflows/ci.yml
```

## Development

```bash
ruff check .
pytest -q
```

## License / trademarks

This is an unofficial fan tool. *The Alters* and related trademarks belong to their respective owners.
