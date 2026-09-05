# Optimization model

This document is the normative solver contract for `alters-base-planner`.

The optimization model has two layers only:

1. **hard feasibility constraints** — a layout is either physically valid or rejected;
2. **one soft objective** — minimize the weighted sum of pairwise room distances.

No separate objective minimizes Elevator count. Elevators and Corridors affect the objective through path distance and also contribute to Base Mass.

---

# 1. Hard constraints

## H1. Exact module multiplicity

Every room requested in `config/plan.json` must be present exactly in the requested count. Mandatory story/core modules are included automatically.

```text
sum(place[r,p] for legal placements p) = 1
```

for every room instance `r`.

## H2. Tier-specific irregular base mask

Every room, Corridor and Elevator must fit completely inside the buildable-cell mask of selected Base tier I-IV.

The built-in geometry source of truth is deliberately editable CSV:

```text
src/alters_base_planner/data/base-size1.csv
src/alters_base_planner/data/base-size2.csv
src/alters_base_planner/data/base-size3.csv
src/alters_base_planner/data/base-size4.csv
```

CSV semantics:

```text
0 = outside the usable base
1 = buildable cell
X = immovable blocked/core cell
```

The first row contains x coordinates and the first column contains y coordinates. Width and height are inferred directly from the CSV, so changing the number of rows/columns changes the tier envelope without modifying Python code.

## H3. Immovable core exclusion

No movable module may overlap any `X` cell.

```text
footprint(module) intersection blocked_cells = empty
```

## H4. No overlap

No grid cell may belong to more than one installed module.

```text
for every cell c:
    sum(modules occupying c) <= 1
```

## H5. No unsupported rotation

Published module orientation is preserved unless verified game data explicitly allows rotation.

## H6. Legal room access level

Rooms connect horizontally only at their documented access level.

- normal rooms: bottom connection level;
- documented exceptions such as Radiation Repulsor: top connection level.

Geometric contact at an invalid height is not a connection.

## H7. Legal direct room-to-room connection

Two rooms may connect directly only when compatible left/right ports meet on the same legal row. A valid direct connection requires no Corridor.

## H8. Corridor rules

A Corridor:

- occupies 2x1 cells;
- provides horizontal connectivity;
- may connect rooms, Corridors and Elevators on the same level;
- cannot provide vertical connectivity;
- is added by the solver, never configured by the player.

## H9. Elevator local rules

An Elevator module:

- occupies 2x1 cells;
- may connect horizontally on its floor;
- provides vertical connectivity only to an Elevator immediately above or below at the same x-coordinate;
- is added by the solver, never configured by the player.

Two Elevator modules separated by a missing floor do not form a valid vertical connection.

## H10. Continuous vertical Elevator coverage

This is a hard global constraint designed to prevent a floor from existing without a valid vertical connection.

Let room access levels span from:

```text
Lmin = minimum room connection level
Lmax = maximum room connection level
n = Lmax - Lmin + 1
```

If `n > 1`:

1. every level `Lmin ... Lmax` must contain at least one Elevator module;
2. therefore at least `n` Elevator modules must exist across that vertical span;
3. for every adjacent level pair `(y, y+1)`, there must be at least one Elevator x-coordinate present on both levels:

```text
ElevatorX[y] intersection ElevatorX[y+1] != empty
```

A single straight shaft is therefore valid:

```text
level 2: E(x=4)
level 1: E(x=4)
level 0: E(x=4)
```

A horizontally shifted shaft is also valid, but only through a transfer floor containing both shaft positions:

```text
level 2:        E(x=8)
level 1: E(x=4) E(x=8)
level 0: E(x=4)
```

because levels 0/1 share `x=4` and levels 1/2 share `x=8`. The transfer floor must also provide a legal horizontal route between the two Elevator modules.

This is invalid:

```text
level 2:        E(x=8)
level 1:        E(x=8)
level 0: E(x=4)
```

because levels 0 and 1 do not share an Elevator at the same x-coordinate.

## H11. Single connected base network

Every installed room must be reachable from the Airlock through legal direct room connections, Corridors and/or Elevators.

```text
for every room r:
    path(Airlock, r) must exist
```

Disconnected islands are forbidden.

## H12. Transit vs terminal modules

A module with `transit_allowed = false` may be an endpoint of a path but may not be used as an intermediate bridge.

Current explicit examples:

- Rapidium Ark;
- Radiation Repulsor.

## H13. Utility connectivity

Every installed Corridor and Elevator must itself belong to the connected access network. Floating or unused utility islands are invalid.

## H14. Base Mass is always calculated

For every feasible layout persist:

```text
room_mass
utility_mass
total_base_mass
organics_required_for_journey
organics_tank_capacity
capacity_margin
travel_feasible_at_full_tank
```

For the mobile base:

```text
organics_required_for_journey = total_base_mass
```

Each Corridor contributes mass 2.
Each Elevator module contributes mass 2.

Mass is reported for journey planning. It is not part of the primary optimization objective.

---

# 2. Usage weights

Every room type receives a default usage weight:

```text
0.0 <= weight <= 1.0
```

Interpretation:

- `1.0` — extremely frequent/mandatory route anchor;
- `0.1` — rarely visited room;
- `0.0` — excluded from objective pairs because routine physical entry is unnecessary.

Weights live in:

```text
src/alters_base_planner/data/usage_weights.json
```

Required baseline examples:

```text
Airlock             1.0
Workshop            0.9
The Womb            0.1
Quantum Computer    0.1
Small Storage       0.0
Medium Storage      0.0
Large Storage       0.0
```

Storage modules remain physical hard-constrained modules even when their objective weight is 0.

---

# 3. Distance definition

Distance is the minimum valid path cost between two rooms. Room length itself does not add distance.

## D1. Directly adjacent rooms

If two rooms connect directly through legal ports:

```text
d(room_a, room_b) = 0
```

## D2. Corridor

Every Corridor module traversed adds:

```text
+1
```

## D3. Elevator

Every individual Elevator module traversed adds:

```text
+1
```

A path using four stacked Elevator modules therefore receives Elevator cost 4, not 1.

## D4. Room traversal

Passing through a transit-allowed room adds:

```text
0
```

regardless of room width.

## D5. Shortest path

```text
d(i,j) = minimum number of Corridor + Elevator modules
         required by any legal path between rooms i and j
```

Direct room adjacency therefore yields 0.

---

# 4. Objective pairs

Create all unordered pairs of installed rooms with positive usage weight.

Do not include:

- Corridors;
- Elevators;
- rooms with weight 0, especially passive Storage modules.

Each room pair is counted exactly once:

```text
i < j
```

---

# 5. Objective function

For every unordered active room pair `(i,j)`:

```text
pair_score(i,j) = weight(i) * weight(j) * d(i,j)
```

The complete objective is:

```text
F = sum_{i<j} weight(i) * weight(j) * d(i,j)
```

The optimal layout is the hard-feasible layout with the smallest `F`.

No independent Elevator-count term is added.
No independent Corridor-count term is added.
No Base-Mass term is added to `F`.

If two layouts have exactly equal `F`, lower Base Mass may be used only as a deterministic tie-breaker.

---

# 6. Required result metrics

Every feasible result must report:

```text
objective_value
weighted_distance_score
normalized_weighted_distance
pairwise_distances
pairwise_contributions
room_usage_weights
elevator_module_count
elevator_shaft_count
corridor_count
room_mass
utility_mass
total_base_mass
organics_required_for_journey
organics_tank_capacity
capacity_margin
travel_feasible_at_full_tank
geometry_verified
geometry_source
```

For auditing:

```text
F = sum(pairwise_contributions.values())
```

---

# 7. Current implementation and exact-solver target

The current engine:

1. enumerates legal room placements with CP-SAT;
2. rejects overlap and out-of-mask placements;
3. builds a legal Corridor/Elevator network;
4. rejects candidates violating continuous vertical Elevator coverage;
5. computes exact shortest module-distance for every active room pair;
6. computes `F` exactly for that candidate;
7. retains the candidate with the smallest `F` among examined candidates;
8. reports Base Mass and journey Organics.

The current post-routing architecture does **not yet prove** that the smallest examined `F` is the global optimum over every possible joint room + Corridor + Elevator placement.

The exact solver milestone is a joint model in which room placement, Corridor placement, Elevator placement, vertical-coverage rules, connectivity and path variables are optimized in one search space. Only that implementation may set:

```text
global_objective_optimum_proven = true
```
