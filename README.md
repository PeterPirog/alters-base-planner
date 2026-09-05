# The Alters Base Planner

Optimization-based planner for the mobile base in **The Alters**.

The player selects the base tier and requested room counts in `config/plan.json`. **Corridors and elevators are never configured manually**: the planner packs requested rooms with OR-Tools CP-SAT and routes the missing utility network automatically.

## Current status

The optimization architecture is functional, but exact Base I-IV perimeter coordinates are **not yet verified from authoritative game data**. Public sources verify expansion progression and Organics capacities, and screenshots/guide descriptions support an immovable **4×2** Organics Tank. The earlier 6×3 blocked-core model was therefore incorrect and has been fixed.

Built-in grid extents and row spans remain explicitly marked `verified: false` in `src/alters_base_planner/data/base_grids.json`. They are suitable for solver development and provisional layouts, not yet for claiming 1:1 game-exact placement.

## Features

- Base tier in JSON: I-IV.
- Room counts in JSON; no room-count UI is required.
- JSON Schema for editor validation/autocomplete.
- Mandatory story/core modules included automatically, including Kitchen and The Womb.
- Corridor and Elevator counts are solver-controlled only.
- OR-Tools CP-SAT placement on an irregular buildable-cell mask.
- Immovable Organics Tank excluded from legal placements.
- Automatic horizontal Corridor and vertical Elevator routing.
- Iterative re-solving when a geometrically valid packing cannot be connected.
- Multi-height modules supported.
- SVG and JSON solution output.
- Streamlit viewer/runner accepts the same JSON plan file.
- Base geometry stored separately from optimization code.
- CI on Python 3.11-3.13.

## Base-grid verification

What is currently grounded:

- Base I Organics capacity: **300**.
- Base II Organics capacity: **450**.
- Base III Organics capacity: **700**.
- Base IV Organics capacity: **800**.
- Base Expansion adds usable construction space.
- The Organics Tank is immovable and sits slightly down-left from the visual center.
- Published layout material describes the central obstruction as **4×2 grid cells**.

What is **not** yet authoritative:

- exact absolute width/height in cells for Base I-IV,
- exact row-by-row perimeter for every tier,
- exact tank coordinates relative to a canonical grid origin.

For that reason the current 22×12, 26×14, 30×16 and 34×18 envelopes are retained only as **provisional screenshot-derived models**, never as verified facts. The solver exposes `geometry_verified: false` in its output until exact masks are supplied.

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

The Streamlit app no longer contains a room-count configurator. It accepts `config/plan.json` or an uploaded compatible JSON file, runs the same solver, and displays the generated layout.

## Solver model

### Stage 1 - room placement

For every room instance, all legal placements are pre-enumerated over the selected irregular base mask. A Boolean CP-SAT variable represents each candidate placement.

Hard constraints:

- every requested room is placed exactly once,
- footprints stay inside buildable cells,
- no room overlaps blocked Organics Tank cells,
- no two rooms overlap.

### Stage 2 - connectivity routing

Rooms that touch horizontally at their lower connection row are grouped into connected components. The router then builds a 2-cell-wide utility network through remaining free cells:

- horizontal steps become **Corridors**,
- vertical steps become **Elevators**.

The component containing the Airlock is the root. Every other room component must connect to that root. If routing fails, the exact packing is forbidden and CP-SAT searches for another layout.

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
