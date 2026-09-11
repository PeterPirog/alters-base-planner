# Mobile Base geometry reference

Validation date: 2026-09-11.

This document records the built-in Base I-IV geometry contract used by `alters-base-planner`.
The source material supplied to the project contains explicit 0/1/X matrices for all four
mobile-Base tiers. The repository CSV files were compared against those matrices and already
matched them exactly, so no cell-level CSV rewrite was required.

## Coordinate convention

The absolute Base grid uses a top-left origin:

```text
(0,0) ----> +x
  |
  |
  v
 +y
```

CSV semantics:

```text
0 = outside the physical/usable Base outline
1 = buildable cell
X = fixed non-buildable Organics Tank/core cell
```

The parser must not symmetrize or otherwise reshape these masks. Every module footprint must
fit entirely on `1` cells. `X` belongs to the physical outline but is permanently blocked.

## Validated dimensions and fixed core

| Tier | Width | Height | Fixed core x | Fixed core y | Organics capacity |
|---|---:|---:|---|---|---:|
| I | 22 | 12 | 8..11 | 6..7 | 300 |
| II | 26 | 14 | 10..13 | 7..8 | 450 |
| III | 30 | 16 | 12..15 | 8..9 | 700 |
| IV | 34 | 18 | 14..17 | 9..10 | 800 |

For every tier the blocked core is exactly `4x2` (8 cells). Relative to the rectangular grid
centre it is shifted one cell left and one row down. That asymmetry is intentional and must be
preserved by the solver.

The authoritative runtime geometry remains the CSV data under:

```text
src/alters_base_planner/data/base-size1.csv
src/alters_base_planner/data/base-size2.csv
src/alters_base_planner/data/base-size3.csv
src/alters_base_planner/data/base-size4.csv
```

Automated tests lock the dimensions, exact blocked-core coordinates and the Base-I row-width
profile so accidental edits fail CI.

## Geometry verification status

`BaseGeometry.verified=True` for the four built-in mobile-Base masks means that the repository
matrices were validated against the 2026-09-11 project spatial-analysis reference. It does not
claim that this repository independently extracted the geometry from game binaries/assets.

Custom imported grids keep their own independent `verified` flag.

## Scope

This reference applies to the original nomadic/mobile Base. The supplied analysis also describes
`The Last Variable` DLC as using materially different topology and gameplay constraints, but it
does not provide a complete DLC 0/1/X matrix or a complete dimensional catalogue for the new DLC
modules. The planner therefore must not reuse the mobile-Base masks for DLC mode until those exact
data are available.
