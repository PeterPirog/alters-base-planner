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

Width and height are inferred directly from the CSV, so changing rows/columns changes the tier envelope without modifying Python code.

## H3. Immovable core exclusion

No movable module may overlap any `X` cell.

## H4. No overlap

No grid cell may belong to more than one installed module.

## H5. No unsupported rotation

Published module orientation is preserved unless verified game data explicitly allows rotation.

## H6. Legal room access level

Rooms connect horizontally only at their documented access level. Normal rooms use the bottom connection level; verified exceptions such as Radiation Repulsor use the top level.

## H7. Legal direct room-to-room connection

Two rooms may connect directly only when compatible left/right ports meet on the same legal row. Such direct adjacency requires no Corridor.

## H8. Corridor rules

A Corridor occupies 2x1 cells, provides horizontal connectivity and is solver-controlled.

## H9. Elevator local rules

An Elevator occupies 2x1 cells, may connect horizontally on its floor and provides vertical connectivity only to an immediately adjacent Elevator on the next floor at the same x-coordinate.

## H10. Continuous vertical Elevator coverage

Let room access levels span `Lmin ... Lmax` and `n = Lmax - Lmin + 1`. If `n > 1`:

1. every level in that span must contain at least one Elevator module;
2. at least `n` Elevator modules must therefore exist across the span;
3. every adjacent pair `(y,y+1)` must share at least one Elevator x-coordinate:

```text
ElevatorX[y] intersection ElevatorX[y+1] != empty
```

A shifted shaft is legal only through a transfer floor containing both shaft positions and a legal horizontal route between them.

## H11. Single connected base network

Every installed room must be reachable from the Airlock through legal room adjacency, Corridors and/or Elevators. Disconnected islands are forbidden.

## H12. Transit vs terminal modules

A module with `transit_allowed = false` may be an endpoint but may not be used as an intermediate bridge. Current explicit examples are Rapidium Ark and Radiation Repulsor.

## H13. Utility connectivity

Every Corridor and Elevator must belong to the connected access network. Floating utility islands are invalid.

## H14. Base Mass is always calculated

Every feasible result persists room mass, utility mass, total Base Mass, required journey Organics, tank capacity, margin and travel feasibility.

```text
organics_required_for_journey = total_base_mass
```

Each Corridor contributes mass 2. Each Elevator module contributes mass 2. Mass is reported for journey planning and used only as a tie-breaker for equal primary objective values.

---

# 2. Usage weights

Every room type receives a default usage weight in `src/alters_base_planner/data/usage_weights.json`:

```text
0.0 <= weight <= 1.0
```

`1.0` means a very frequent/mandatory traffic anchor; `0.1` means rare physical use; `0.0` excludes the room from objective pairs while keeping all physical hard constraints.

Baseline examples:

```text
Airlock             1.0
Workshop            0.9
The Womb            0.1
Quantum Computer    0.1
Small Storage       0.0
Medium Storage      0.0
Large Storage       0.0
```

---

# 3. Distance definition

Distance `d(i,j)` is the minimum legal path cost between start room `i` and destination room `j`.

The crucial rule is that **the lengths of the two rooms being measured are not counted**, but any transit room crossed between them contributes its horizontal length in grid cells.

## D1. Directly adjacent endpoint rooms

If rooms `A` and `B` connect directly through legal ports:

```text
d(A,B) = 0
```

regardless of the width of A or B.

## D2. Corridor

Every Corridor module traversed adds:

```text
+1
```

Its 2-cell footprint does not make it cost 2.

## D3. Elevator

Every individual Elevator module traversed adds:

```text
+1
```

Four stacked Elevator modules therefore add 4.

## D4. Intermediate room traversal

If a legal route from endpoint room `A` to endpoint room `B` passes through another transit-allowed room `C`, then crossing `C` from its left port to its right port or vice versa adds:

```text
+ width(C)
```

Example:

```text
A(4x1) | C(6x1) | B(8x1)
```

If all three rooms touch directly:

```text
d(A,C) = 0
d(C,B) = 0
d(A,B) = 6
```

because C is intermediate only for the A-B pair. The widths of A and B never contribute to `d(A,B)`.

## D5. Terminal rooms

Rooms with `transit_allowed = false` have no internal left-right traversal edge, so they cannot appear in the middle of a valid route.

## D6. Shortest path

The solver chooses the minimum-cost legal route using:

```text
Corridor:          1 each
Elevator:          1 each
Intermediate room: room width in grid cells
Start room:        0
Destination room:  0
```

---

# 4. Objective pairs

Create all unordered pairs of installed rooms with positive usage weight. Do not include Corridors, Elevators or rooms with weight 0. Each pair is counted exactly once (`i < j`).

---

# 5. Objective function

For every unordered active room pair `(i,j)`:

```text
pair_score(i,j) = weight(i) * weight(j) * d(i,j)
```

and:

```text
F = sum_{i<j} weight(i) * weight(j) * d(i,j)
```

The preferred hard-feasible layout has the smallest `F`. Elevator count, Corridor count and Base Mass are not independent terms in `F`; lower Base Mass is only a deterministic tie-breaker if `F` is equal.

---

# 6. Required result metrics

Every feasible result reports:

```text
objective_value
weighted_distance_score
average_pair_distance
weighted_average_pair_distance
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

The current engine enumerates legal room packings with CP-SAT, routes legal utilities, rejects candidates that violate connectivity/vertical rules, computes exact graph shortest paths using the distance rules above, evaluates `F` exactly for every generated connected candidate, and retains the smallest examined value.

It does **not yet prove** global optimality over the complete joint placement + Corridor + Elevator search space. Only a future integrated exact model may set:

```text
global_objective_optimum_proven = true
```
