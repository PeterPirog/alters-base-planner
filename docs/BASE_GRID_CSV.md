# Editing Base I-IV geometry

Built-in base geometry is stored in four independent files:

```text
src/alters_base_planner/data/base-size1.csv
src/alters_base_planner/data/base-size2.csv
src/alters_base_planner/data/base-size3.csv
src/alters_base_planner/data/base-size4.csv
```

These files are the geometry source of truth for Base I-IV.

## Cell values

```text
0 = outside the usable base
1 = buildable cell
X = immovable Organics/core cell
```

Example:

```csv
y,0,1,2,3,4,5
0,0,0,1,1,0,0
1,0,1,1,1,1,0
2,1,1,X,X,1,1
3,0,1,1,1,1,0
```

## Changing base size

The solver does not keep width/height separately in Python.

- add/remove x columns to change width;
- add/remove y rows to change height;
- x headers must remain consecutive `0..width-1`;
- y row labels must remain consecutive `0..height-1`.

## Changing the perimeter

Change cells between `0` and `1`.

- `0 -> 1` adds a buildable cell;
- `1 -> 0` removes it from the base;
- use `X` only for fixed non-buildable structure inside the physical base.

## Moving/resizing the immovable element

Replace the old `X` cells with `1` (or `0` if appropriate) and mark the corrected footprint with `X`.

At least one `X` cell is required by the built-in tier loader because the current model assumes an immovable core exists.

## Important validation rules

The CSV loader rejects:

- missing or non-consecutive x coordinates;
- missing or non-consecutive y coordinates;
- rows with different lengths;
- cell values other than `0`, `1`, `X`;
- a built-in grid with no `X` cells.

After editing a grid run:

```bash
pytest -q
```

The solver will then use the corrected geometry automatically for the corresponding `base_tier`.
