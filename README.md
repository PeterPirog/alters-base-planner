# The Alters Base Planner

Optimization-based planner for the mobile base in **The Alters**.

The player selects the base expansion tier and the number of rooms. **Corridors and elevators are never configured manually**: the planner packs requested rooms with OR-Tools CP-SAT, then routes the missing utility network automatically.

## Features

- Base size selector: Expansion Tier I–IV.
- Complete catalog of known room dimensions and masses.
- Mandatory story/core modules included automatically.
- Player-configurable counts for optional rooms.
- OR-Tools CP-SAT placement on an irregular buildable-cell mask with an immovable central obstacle.
- Automatic horizontal Corridor and vertical Elevator routing.
- Iterative re-solving when a geometrically valid room packing cannot be connected.
- Multi-height modules supported, including Quantum Computer, Small/Large Storage, Radiation Repulsor and Materializer.
- SVG layout visualization and download.
- Streamlit UI plus CLI.
- Custom base-mask JSON import/export API, so exact in-game masks can replace built-in geometry without touching solver logic.
- CI on Python 3.11–3.13.

## Important geometry note

Reliable public sources document module footprints, connectivity rules, the immovable Organics Tank and Base Expansion progression, but there is currently no authoritative machine-readable list of exact grid coordinates for every expansion tier. Therefore the built-in Tier I–IV masks are **conservative approximations**, intentionally isolated in `base.py`.

The optimization engine itself is not approximate. Once exact masks are calibrated from build-mode screenshots or extracted game data, only the geometry data needs replacing.

## Install

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
# source .venv/bin/activate

pip install -e '.[dev]'
```

## Run the UI

```bash
streamlit run app.py
```

Workflow:

1. Select Base Expansion I–IV.
2. Enter the number of each optional module.
3. Do **not** enter Corridor or Elevator counts.
4. Click **Optimize layout**.
5. Inspect the generated connected layout and download SVG.

## CLI

```bash
alters-base-planner \
  --tier 3 \
  --room workshop=1 \
  --room research_lab=1 \
  --room dormitory=2 \
  --room social_room=1 \
  --room medium_storage=2
```

The default output is `layout.svg`.

## Solver model

### Stage 1 — room placement

For every room instance, all legal placements are pre-enumerated over the selected irregular base mask. A Boolean CP-SAT variable represents each candidate placement.

Hard constraints:

- every requested room is placed exactly once,
- footprints stay inside buildable cells,
- no room overlaps the Organics Tank / blocked cells,
- no two rooms overlap.

The objective prefers compact layouts and places frequently visited rooms nearer the center while allowing storage and low-visit modules to occupy peripheral space.

### Stage 2 — connectivity routing

Rooms that touch horizontally at their lower connection row are grouped into connected components. The router then builds a 2-cell-wide utility network through remaining free cells:

- horizontal steps become **Corridors**,
- vertical steps become **Elevators**.

The component containing the Airlock is the root. Every other room component must be connected to that root. If routing fails, the exact CP-SAT packing is forbidden and the solver searches for another layout. This keeps Corridor/Elevator counts fully automatic.

## Project structure

```text
app.py
src/alters_base_planner/
  base.py       # Tier geometry and custom mask I/O
  catalog.py    # module dimensions/masses
  cli.py
  engine.py     # CP-SAT + automatic utility routing
  models.py
  render.py     # SVG renderer
tests/
.github/workflows/ci.yml
```

## Data sources used for initial catalog

The initial module catalog was cross-checked against The Alters Wiki and current community/game-guide documentation. Key verified examples include Workshop 4×1, Quantum Computer 4×2, Large Storage 8×2, Radiation Repulsor 2×3 and Materializer 4×3. Public guides also confirm that rooms require horizontal connectivity and elevators for vertical connectivity.

## Next calibration milestone

For game-exact layouts, capture a clean **Command Center → Base Building** screenshot for each Expansion Tier. The intended next step is a small calibration tool that converts each screenshot into `allowed_cells` and `blocked_cells` JSON. The optimizer will then produce layouts against the exact game grid.

## Development

```bash
ruff check .
pytest -q
```

## License / trademarks

This is an unofficial fan tool. *The Alters* and related trademarks belong to their respective owners.
