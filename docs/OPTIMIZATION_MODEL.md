# Optimization model

This document is the normative solver contract for `alters-base-planner`.

The optimization model has two layers only:

1. **hard feasibility constraints** — a layout is either physically valid in The Alters or rejected;
2. **one soft objective** — minimize the weighted sum of pairwise room distances.

No separate objective minimizes Elevator count. Elevators and Corridors influence the objective through path distance, and they also contribute to Base Mass.

---

# 1. Hard constraints

## H1. Exact module multiplicity

Every room requested in `config/plan.json` must be present exactly in the requested count. Mandatory story/core modules are included automatically.

For each room instance `r`:

```text
sum(place[r,p] for legal placements p) = 1
```

## H2. Tier-specific irregular base mask

Every placed room, Corridor and Elevator must fit completely inside the buildable-cell mask of the selected Base tier (I, II, III or IV).

```text
footprint(module) subset_of buildable_cells(tier)
```

The external temporary rearrangement grid is not part of the final base.

## H3. Immovable core exclusion

No movable module may overlap the fixed Organics/core obstruction.

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

Two rooms may connect directly only when compatible left/right ports meet on the same legal row.

A valid direct connection requires no Corridor.

## H8. Corridor rules

A Corridor:

- occupies 2x1 cells;
- provides horizontal connectivity;
- may connect rooms, Corridors and Elevators on the same level;
- cannot provide vertical connectivity;
- is added by the solver, never configured by the player.

## H9. Elevator rules

An Elevator module:

- occupies 2x1 cells;
- may connect horizontally on its floor;
- provides vertical connectivity only to an Elevator immediately above or below at the same x-coordinate;
- therefore a multi-floor shaft is a contiguous stack of Elevator modules;
- is added by the solver, never configured by the player.

Two Elevator modules separated by a missing floor do not form a valid shaft.

## H10. Single connected base network

Every installed room must be reachable from the Airlock through legal direct room connections, Corridors and/or Elevator modules.

```text
for every room r:
    path(Airlock, r) must exist
```

Disconnected islands are forbidden.

## H11. Transit vs terminal modules

A module with `transit_allowed = false` may be an endpoint of a path but may not be used as an intermediate bridge.

Current explicit examples:

- Rapidium Ark;
- Radiation Repulsor.

Thus this is invalid unless Workshop has another route:

```text
Airlock -> Rapidium Ark -> Workshop
```

## H12. Utility connectivity

Every installed Corridor and Elevator must itself belong to the connected access network. Floating or unused utility islands are invalid.

## H13. Base Mass is always calculated

For every feasible layout, persist:

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

Every room type receives a default usage weight in the range:

```text
0.0 <= weight <= 1.0
```

Interpretation:

- `1.0` — extremely frequent/mandatory player route anchor;
- `0.1` — rarely visited room;
- `0.0` — room is not included in objective pairs because routine physical entry is unnecessary.

The default weights are gameplay-informed planner assumptions, not hidden game constants. They are stored in:

```text
src/alters_base_planner/data/usage_weights.json
```

Required examples from the optimization specification:

```text
Airlock             1.0
Workshop            0.9
The Womb            0.1
Quantum Computer    0.1
Small Storage       0.0
Medium Storage      0.0
Large Storage       0.0
```

Storage modules remain physical hard-constrained modules even though their objective weight is 0.

---

# 3. Distance definition

Distance is defined between two rooms using the minimum valid access path.

The important rule is that **room length itself does not add distance**.

## D1. Directly adjacent rooms

If two rooms connect directly through legal ports:

```text
d(room_a, room_b) = 0
```

Example:

```text
[Airlock][Workshop]
```

Distance = 0.

## D2. Corridor

Every Corridor module traversed on the shortest path adds exactly:

```text
+1
```

Example:

```text
[Airlock][Corridor][Workshop]
```

Distance = 1.

Two Corridor modules:

```text
[Airlock][Corridor][Corridor][Workshop]
```

Distance = 2.

## D3. Elevator

Every individual Elevator module traversed adds exactly:

```text
+1
```

This applies separately to every Elevator module in a shaft.

Example: a path uses four stacked Elevator modules:

```text
E
E
E
E
```

The Elevator contribution to distance is 4, not 1.

## D4. Room traversal

Passing through a transit-allowed room adds:

```text
0
```

regardless of whether the room is 2, 4, 6 or 8 cells wide.

This is deliberate: the objective measures the number of communication elements required between room pairs, not the physical internal length of rooms.

## D5. Shortest path

For rooms `i` and `j`:

```text
d(i,j) = minimum number of Corridor + Elevator modules
         required by any legal path between i and j
```

Direct room adjacency therefore yields 0.

---

# 4. Which pairs are included

Create all unordered pairs of installed rooms with positive usage weight.

Do not include:

- Corridors;
- Elevators;
- rooms with weight 0, especially passive Storage modules.

Each room pair is counted exactly once:

```text
i < j
```

There is no double counting of `(i,j)` and `(j,i)`.

Mandatory core rooms such as Airlock are included when their weight is positive, even though the player does not manually specify their count in JSON.

---

# 5. Objective function

For every unordered active room pair `(i,j)` define:

```text
pair_score(i,j) = weight(i) * weight(j) * d(i,j)
```

The complete objective is:

```text
F = sum_{i<j} weight(i) * weight(j) * d(i,j)
```

The optimal layout is the hard-feasible layout with the smallest value of `F`.

No independent Elevator-count term is added.
No independent Corridor-count term is added.
No Base-Mass term is added to `F`.

Because each Corridor and each Elevator already adds 1 to relevant shortest paths, unnecessary communication modules are naturally disfavoured when they affect frequently used routes.

If two layouts have exactly the same value of `F`, Base Mass may be used only as a deterministic tie-breaker. This does not change which objective values are optimal.

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

For auditing, the result JSON must make it possible to reconstruct:

```text
F = sum(pairwise_contributions.values())
```

---

# 7. Current implementation and exact-solver target

The current engine:

1. enumerates legal room placements with CP-SAT;
2. rejects overlap and out-of-mask placements;
3. builds a legal connected Corridor/Elevator network;
4. computes exact shortest module-distance for every active room pair;
5. computes `F` exactly for that candidate;
6. retains the candidate with the smallest `F` among examined candidates;
7. reports Base Mass and journey Organics.

The current post-routing architecture does **not yet prove** that the smallest examined `F` is the global optimum over every possible joint room + Corridor + Elevator placement.

The exact solver milestone is therefore a joint model in which room placement, Corridor placement, Elevator placement, connectivity and path variables are optimized in one search space. Only that implementation may set:

```text
global_objective_optimum_proven = true
```

Until then, objective evaluation is exact per candidate, while global optimality remains explicitly unproven.
