# Optimization model

This document is the normative solver contract for `alters-base-planner`.

The planner is intentionally **lexicographic**. Feasibility and the minimum number of Elevator modules are never traded away for shorter walking distance.

## Terminology

- **Room module** - a requested or mandatory game module (Workshop, Airlock, Storage, etc.).
- **Corridor module** - a 2×1 utility module used for horizontal connectivity.
- **Elevator module** - a 2×1 utility module. Elevator modules directly above/below one another at the same x-coordinate form an **elevator shaft**.
- **Elevator count** - number of installed 2×1 Elevator modules, not the number of shafts. This is the quantity minimized first because every Elevator module occupies cells and adds Base Mass.
- **Tier mask** - exact set of buildable grid cells for Base I-IV, excluding the immovable core/Organics obstruction.
- **Access port** - legal left/right connection point of a room on its connection level. Normal rooms use the bottom level; documented exceptions such as Radiation Repulsor use the top level.
- **Transit module** - a room through which the walkable network may continue from one side to the other.
- **Terminal module** - a module that must be connected but may not be used as a bridge to another module (e.g. Rapidium Ark, Radiation Repulsor).

## Optimization hierarchy

The exact priority order is:

1. **HARD FEASIBILITY** - place every requested/mandatory module in the selected tier and create one valid accessible network.
2. **MINIMUM ELEVATOR COUNT** - solve with a fixed Elevator count `i`, starting at configured lower bound `i = 3`, and increase `i` until the first feasible count is found.
3. **MINIMUM WEIGHTED TRAVEL DISTANCE** - with the minimum Elevator count frozen, minimize gameplay-weighted pairwise shortest-path distance between rooms.
4. **MINIMUM BASE MASS / CORRIDORS** - only as a tie-breaker after weighted travel distance; with room set and Elevator count fixed, this primarily minimizes unnecessary Corridor modules.
5. **PLACEMENT TIE-BREAKERS** - deterministic tie-breaking / compactness only when all higher-priority criteria are equal.

No weighted sum may combine item 2 with item 3. An extra Elevator is never allowed merely because it shortens travel.

---

# Hard constraints

## H1. Exact room multiplicity

For every room type `r` requested in `config/plan.json`, exactly the requested number must be placed. Mandatory story/core modules are automatically included exactly once unless game data says otherwise.

For placement candidates `p` of room instance `r`:

```text
Σ_p x[r,p] = 1
```

## H2. No room rotation unless game data explicitly permits it

Current mobile-base modules keep their published orientation. A 4×1 Workshop is not interchangeable with a 1×4 Workshop.

## H3. Tier-mask containment

Every occupied cell of every room, Corridor and Elevator must lie inside the buildable-cell mask of the selected Base tier.

```text
footprint(module) ⊆ buildable_cells(tier)
```

The external rectangular holding/rearrangement grid is not part of the final buildable mask.

## H4. Immovable core exclusion

No movable module may overlap the blocked core/Organics obstruction.

```text
footprint(module) ∩ blocked_cells = ∅
```

## H5. Non-overlap

A grid cell may belong to at most one installed module.

```text
∀ cell c: Σ modules occupying c ≤ 1
```

## H6. Legal room access level

A room exposes horizontal access only at its documented connection level:

- default: bottom row,
- Radiation Repulsor: top row,
- other exceptions are data-driven.

A geometric rectangle touching another rectangle at an illegal height does not create a connection.

## H7. Legal horizontal connection

A horizontal connection exists only if compatible left/right access ports are aligned on the same grid row and are directly adjacent, or are joined by one or more legal utility modules.

Normal room-to-room adjacency is allowed without a Corridor when the ports meet directly.

## H8. Corridor semantics

A Corridor:

- occupies exactly 2×1 cells,
- can carry horizontal walking traffic,
- may connect to a room, another Corridor, or an Elevator on the same floor,
- cannot by itself provide vertical movement.

Corridor count is not configured by the player.

## H9. Elevator semantics

An Elevator module:

- occupies exactly 2×1 cells,
- may connect horizontally to rooms/Corridors/Elevators on its floor,
- provides vertical connectivity only to an Elevator immediately above or below at the same x-coordinate,
- therefore vertical travel requires a contiguous stack of Elevator modules.

Two Elevator modules separated by an empty floor do **not** belong to the same shaft.

## H10. Fixed Elevator count during feasibility search

Let `E` be the number of installed 2×1 Elevator modules.

For iteration `i`:

```text
E = i
```

The current policy starts at:

```text
i_min = 3
```

and increments one by one:

```text
3, 4, 5, ... E_max
```

The first `i` for which a feasible complete base exists is the globally preferred Elevator count for the second optimization stage.

`i_min = 3` is a planner policy, not a claim that the game mechanically requires at least three Elevators. It can later be made configurable if a scenario needs a different lower bound.

## H11. All installed modules belong to one accessible network

The Airlock-connected network is the root network. Every requested and mandatory room must be connected to it by legal room passages, Corridors and/or Elevator shafts.

No disconnected room is accepted.

Formally, for every installed room `r` there must exist a valid path:

```text
Airlock -> ... -> r
```

## H12. Transit vs terminal modules

If `transit_allowed = false`, the module may be the endpoint of a path but cannot connect traffic through itself from one side to the other.

Current explicit terminal modules:

- Rapidium Ark,
- Radiation Repulsor.

This prevents layouts such as:

```text
Airlock -> Rapidium Ark -> Workshop
```

from being accepted unless the Workshop has another valid route.

## H13. Every utility module is part of the connected utility network

An installed Corridor/Elevator may not float disconnected from the Airlock-rooted network.

Redundant utility branches are not useful and are removed by the tertiary mass/Corridor minimization.

## H14. Walkable path integrity

A valid connectivity path may use only:

- walkable cells of transit rooms at their valid access level,
- Corridor cells,
- Elevator stops/shafts,
- legal direct room-to-room port adjacency.

It may not pass through:

- blocked core cells,
- outside-tier cells,
- terminal-only modules as intermediate nodes,
- non-walkable vertical space inside multi-height modules.

## H15. Base mass is always calculated

Mass is not currently a hard feasibility constraint unless explicitly enabled later, but every feasible layout must persist:

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

Each Corridor and Elevator contributes mass 2.

---

# Secondary objective: travel distance

This stage runs **only after the minimum feasible Elevator count is known and frozen**.

## Movement graph

The final layout is converted to a weighted graph.

### Horizontal movement

Crossing one grid cell horizontally costs:

```text
1 point
```

This includes walking through rooms and Corridors.

### Room traversal

For a transit room, its walkable access row is represented cell-by-cell. Crossing each successive grid cell costs 1 point.

For a terminal room, the room may be reached but is not available as an intermediate path.

### Elevator travel

A contiguous vertical stack of Elevator modules at one x-coordinate forms one shaft.

Entering/exiting the shaft still requires ordinary horizontal cell movement. Once inside the same shaft, travel from any served floor to any other served floor costs exactly:

```text
1 point
```

independent of the number of floors crossed.

Implementation-wise, all stops in one contiguous shaft are connected by elevator edges of cost 1 (or via a shaft super-node that produces the same shortest-path metric).

### Distance between rooms

Each room has an **activity point** on its walkable connection row. Until game-extracted interaction coordinates are available, the activity point is the middle cell (or the better of the two middle cells for even-width rooms).

`d(a,b)` is the shortest-path cost between the activity points of rooms `a` and `b` in the movement graph.

The activity-point approximation is explicit and can later be replaced by per-room interaction coordinates without changing the objective definition.

---

# Gameplay usage weights

Weights are data, not hard-coded solver constants. The current calibrated heuristic values live in:

```text
src/alters_base_planner/data/usage_weights.json
```

Scale:

```text
0.10 = almost passive / rarely physically visited
1.00 = extremely frequent route anchor
```

Current baseline:

| Module | Weight |
|---|---:|
| Airlock | 1.00 |
| Captain's Cabin | 0.95 |
| Workshop | 0.90 |
| Command Center | 0.80 |
| Machinery | 0.70 |
| Kitchen | 0.55 |
| Social Room | 0.55 |
| Research Lab | 0.50 |
| Communication Room | 0.45 |
| Infirmary | 0.45 |
| Refinery | 0.30 |
| Greenhouse | 0.30 |
| Quantum Computer | 0.25 |
| Gym | 0.25 |
| Contemplation Room | 0.20 |
| Gamer's Den | 0.20 |
| Park with Bench | 0.20 |
| Materializer | 0.20 |
| The Womb | 0.15 |
| Personal Cabin | 0.15 |
| Dormitory | 0.10 |
| any Storage | 0.10 |
| Recycler | 0.10 |
| Radiation Repulsor | 0.10 |
| Rapidium Ark | 0.10 |
| Ark Sarcophagus | 0.10 |

These weights are gameplay-informed heuristics, not values stored by the game.

---

# Weighted-distance objective

For every unordered room pair `(a,b)`:

```text
pair_weight(a,b) = usage_weight(a) × usage_weight(b)
```

The optimization numerator is:

```text
WeightedDistance = Σ_{a<b} pair_weight(a,b) × d(a,b)
```

Because the room set is fixed during the second stage, the denominator below is constant and may be omitted inside the solver:

```text
NormalizedWeightedDistance =
    Σ pair_weight(a,b) × d(a,b)
    / Σ pair_weight(a,b)
```

The normalized value should be reported to the player as an intuitive expected weighted travel score.

Why the product is used: if room-visit frequencies approximate the probability that the next task is in a room, the frequency of a transition between two rooms is proportional to the product of their visit frequencies. This strongly rewards keeping Airlock/Cabin/Workshop close while making passive Storage placement almost irrelevant.

---

# Tertiary objective: mass and unnecessary Corridors

After minimum Elevator count and minimum weighted distance are frozen, minimize:

```text
total_base_mass
```

For a fixed room configuration and fixed Elevator count this is equivalent to minimizing unnecessary Corridor count, because room mass is constant and each Corridor/Elevator has mass 2.

This preserves journey efficiency without allowing mass to override the requested movement objective.

---

# Required result metrics

Every connected solution must report at least:

```text
minimum_elevator_count
elevator_module_count
elevator_shaft_count
corridor_count
weighted_distance_score
normalized_weighted_distance
pairwise_distances
room_usage_weights
room_mass
utility_mass
total_base_mass
organics_required_for_journey
organics_tank_capacity
capacity_margin
travel_feasible_at_full_tank
```

The result must also preserve geometry provenance (`geometry_verified`, source, notes) so a layout generated on a provisional Base I-IV mask cannot be confused with a game-exact calibrated result.

---

# Exact solver implementation target

The intended exact implementation is a joint placement/connectivity model rather than a purely greedy post-router:

1. enumerate legal room placements,
2. enumerate legal 2×1 utility anchors,
3. create room-placement Boolean variables,
4. create Corridor/Elevator Boolean variables per anchor,
5. enforce cell non-overlap,
6. enforce legal adjacency/ports,
7. use flow/connectivity variables rooted at Airlock,
8. fix `Σ Elevator = i`, starting with `i=3`,
9. stop at first feasible `i`,
10. freeze that `i`,
11. minimize weighted shortest-path distance,
12. then minimize mass/Corridors.

Until this joint model is implemented, any heuristic router must clearly label results as heuristic rather than claiming proof of global minimum Elevator count.
