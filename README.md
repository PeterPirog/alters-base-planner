# The Alters Base Planner

Optimization-based planner for the mobile base in **The Alters**.

The player selects the base tier and requested room counts in `config/plan.json`. **Corridors and elevators are never configured manually**: the planner packs requested rooms with OR-Tools CP-SAT and routes the missing utility network automatically.

## Current status

The optimization architecture is functional. The **structural shape semantics** of the mobile base are grounded in current guides and screenshots:

- the base is circular / wheel-shaped,
- usable horizontal width changes from row to row because of the curved perimeter,
- the rectangular holding area outside the wheel is only a temporary rearrangement area and is not valid base space,
- an immovable Organics/core obstruction sits slightly down-left from the visual center.

However, exact Base I-IV cell coordinates are **not yet verified from authoritative game data**. The current 22×12, 26×14, 30×16 and 34×18 masks, their row spans and the 4×2 blocked-core proxy remain screenshot-derived solver fixtures and are explicitly marked `verified: false`.

## Features

- Base tier in JSON: I-IV.
- Room counts in JSON; no room-count UI is required.
- JSON Schema for editor validation/autocomplete.
- Mandatory story/core modules included automatically, including Kitchen and The Womb.
- Corridor and Elevator counts are solver-controlled only.
- OR-Tools CP-SAT placement on an irregular buildable-cell mask.
- Immovable core/Organics obstruction excluded from legal placements.
- Explicit left/right access-port connectivity.
- Standard modules connect at the bottom level; Radiation Repulsor connects at the top.
- Rapidium Ark and Radiation Repulsor are treated as terminal/non-transit modules so the solver cannot route traffic through them.
- Automatic horizontal Corridor and vertical Elevator routing.
- Iterative re-solving when a geometrically valid packing cannot be connected.
- Multi-height modules supported.
- **Base-mass accounting and journey-feasibility output** for every connected solution.
- SVG and JSON solution output.
- Streamlit viewer/runner accepts the same JSON plan file.
- Base geometry stored separately from optimization code.
- CI on Python 3.11-3.13.

## Base-grid verification

What is currently grounded:

- the mobile base is circular / wheel-shaped,
- top/bottom rows have less usable width than central rows,
- the external rectangular holding grid is not part of the usable base,
- the Organics/core obstruction is immovable and slightly down-left from visual center,
- Base I Organics capacity: **300**,
- Base II Organics capacity: **450**,
- Base III Organics capacity: **700**,
- Base IV Organics capacity: **800**,
- Base Expansion adds usable construction space.

What is **not** yet authoritative:

- exact absolute width/height in cells for Base I-IV,
- exact row-by-row perimeter coordinates for every tier,
- exact canonical coordinates of the obstruction,
- exact cell footprint of the obstruction.

For that reason `src/alters_base_planner/data/base_grids.json` keeps every built-in profile at `verified: false`. A future screenshot calibration or game-asset extraction can replace these profiles without changing the solver.

## Connectivity model

The game requires every placed module to belong to the accessible base network. Standard rooms join horizontally through their lower left/right sides, while different floors are joined with Elevator modules. A disconnected room is invalid in build mode.

The solver therefore models:

1. a left and right access port for every room,
2. internal passage through ordinary rooms,
3. direct horizontal adjacency between compatible ports,
4. Corridors for missing horizontal links,
5. Elevators for vertical links,
6. the Airlock-connected component as the required network root.

Special cases currently modeled:

- **Radiation Repulsor**: 2×3, mass 16, connection level at the **top**, terminal/non-transit.
- **Rapidium Ark**: 4×2, mass 32, must be attached to the base but cannot be used as a walk-through connection; terminal/non-transit.

This prevents a layout from being accepted merely because rectangles touch geometrically when there is no valid traversable connection.

## Base mass and movement

Base movement consumes **Organics equal to total Base Mass**. Stored resources use storage volume but do not add to the travel mass calculation; the relevant travel mass comes from the installed base modules.

The planner therefore calculates for every connected layout:

```text
room_mass
+ corridor/elevator mass
= total_base_mass
= organics_required_for_journey
```

Every automatically added Corridor and Elevator has mass **2**, so the router is not mass-neutral. Among the connected layouts it examines, the planner prefers the one with lower total mass (equivalently fewer/lighter automatic connectors for a fixed room configuration), then uses the placement objective as a tiebreaker.

The output also reports:

```text
organics_tank_capacity
capacity_margin = organics_tank_capacity - total_base_mass
travel_feasible_at_full_tank
mass_breakdown
```

A positive or zero capacity margin means the base can make the journey when the Organics tank is full. A negative margin means modules/connectors must be removed or the base must be expanded.

### Mass-data note

The catalog is cross-checked against current guides/wiki pages. One notable source conflict is the Dormitory: the current English Fandom table lists mass 40, but its Russian page, an empirical Patch 1.4 data guide and player reports agree on **mass 8** while 40 is its Metal construction cost. The planner therefore uses **Dormitory mass 8**.

## Player configuration

Edit:

```text
config/plan.json
```

Example:

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
    "objective": "balanced",
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

- omit rooms you do not want, or set their count to `0`,
- mandatory modules are added automatically and must not be listed,
- `corridor` and `elevator` are intentionally not valid player configuration keys,
- unknown room names cause a validation error instead of being silently ignored.

The schema is in `config/plan.schema.json`.

## Result JSON

For a connected solution the output contains a persistent movement section similar to:

```json
{
  "journey": {
    "room_mass": 154,
    "utility_mass": 18,
    "total_base_mass": 172,
    "organics_required": 172,
    "organics_tank_capacity": 450,
    "capacity_margin": 278,
    "travel_feasible_at_full_tank": true,
    "mass_breakdown": {
      "airlock": 4,
      "dormitory": 8,
      "workshop": 8,
      "corridor": 6,
      "elevator": 12
    }
  }
}
```

The numbers above are illustrative; the generated `layout.json` is authoritative for the selected configuration and solver result.

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

With the repository default configuration:

```bash
alters-base-planner
```

Or with another JSON file:

```bash
alters-base-planner path/to/my-plan.json
```

The configured SVG and JSON outputs are written when a connected layout is found.

## Streamlit

```bash
streamlit run app.py
```

The Streamlit app accepts `config/plan.json` or an uploaded compatible JSON file, runs the same solver, displays the layout and reports Base Mass, journey Organics requirement and tank margin.

## Solver model

### Stage 1 - room placement

For every room instance, all legal placements are pre-enumerated over the selected irregular base mask. A Boolean CP-SAT variable represents each candidate placement.

Hard constraints:

- every requested room is placed exactly once,
- footprints stay inside buildable cells,
- no room overlaps blocked core/Organics cells,
- no two rooms overlap.

### Stage 2 - access-network routing

The router resolves actual access-port components rather than only rectangle contact. It automatically adds 2×1 utility modules:

- horizontal links become **Corridors**,
- vertical links become **Elevators**.

Every room must become reachable from the Airlock component. If routing fails, the exact packing is forbidden and CP-SAT searches for another layout.

### Stage 3 - mass selection

For each connected candidate the planner totals all room masses plus mass 2 for every Corridor/Elevator. Within the configured layout-attempt budget it retains the lightest connected solution and persists the complete journey metrics.

## Geometry data

Built-in profiles live in:

```text
src/alters_base_planner/data/base_grids.json
```

They use explicit `row_spans` rather than generating a hidden mathematical ellipse. This makes every assumption inspectable and allows a verified mask to replace a provisional one without changing solver code.

A custom geometry JSON may also provide either:

- `allowed_cells` + `blocked_cells`, or
- `row_spans` + `blocked_rect`.

## Project structure

```text
config/
  plan.json
  plan.schema.json
app.py
src/alters_base_planner/
  base.py
  catalog.py
  cli.py
  config.py
  data/base_grids.json
  engine.py
  models.py
  render.py
tests/
.github/workflows/ci.yml
```

## Next geometry milestone

The next required step for a game-exact planner is calibration from clean **Command Center → Base Building** screenshots for Base I, II, III and IV, or extraction of equivalent grid data from game assets. Each calibrated tier can then be marked `verified: true` and tested against known in-game layouts.

## Development

```bash
ruff check .
pytest -q
```

## License / trademarks

This is an unofficial fan tool. *The Alters* and related trademarks belong to their respective owners.
