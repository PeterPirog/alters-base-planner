# Room-master search experiment

Status: **REJECTED FOR PRODUCTION**

Parent: `672e591e44e7b5343ef7242d56c62103f1f4110f`

This V1 release-blocker experiment tests one hypothesis: repeated optimization of the room
master's heuristic `search_cost` might delay the first structurally connected candidate. It does
not change Base mechanics, the exact fixed-packing solver or global proof semantics.

## Measured blocker

The V1 release-acceptance run found a feasible incumbent for Tier I in 4.262 seconds and Tier II in
120.057 seconds. Tier III examined 50 room packings in 180 seconds and Tier IV examined 45 in 300
seconds without reaching a connected candidate. Fixed CP-SAT search was secondary; room-packing
enumeration before structural connectivity consumed most of the large-tier budgets.

The earlier exact integrated-hard bootstrap was rejected as `NO_GO_PERFORMANCE`. Its Tier-III model
had 243,002 variables and 458,736 constraints, and its Tier-IV model had 417,902 variables and
795,244 constraints. Neither found a witness in the respective 180-second and 300-second windows;
sparse Corridor/Elevator hints did not recover a witness. No integrated bootstrap entered
production.

## Compared master modes

`HEURISTIC_OBJECTIVE` is the unchanged production default. It minimizes the sum of candidate
`search_cost` terms. That value is weighted centrality used only to order room packings; it is not
the accepted objective, a lower bound or a global ranking component.

`FEASIBILITY_ENUMERATION` uses the same candidate domains, exactly-one constraints, room occupancy,
identical-instance symmetry constraints and accumulated no-goods, but has no master objective. It is
available only through private benchmark/test seams.

Removing the heuristic objective cannot change the feasible room-packing set. For either mode, each
returned packing is independently handled by the same exact fixed solver, and the no-good

```text
sum(chosen_vars) <= len(chosen_vars) - 1
```

excludes only that packing. If repeated solves eventually return `INFEASIBLE`, the same finite
packing domain is exhausted. Therefore the exact global tuple and proof condition are unchanged;
only enumeration order and anytime behavior may differ.

Exhaustive synthetic tests compare canonical packing sets for two rooms, overlapping alternatives,
identical-instance symmetry and an asymmetric Base mask. The sets are exactly equal. Both modes
also match the independent tiny global oracle on
`(scaled F, total mass, Elevator count, Corridor count)` and agree on global proof.

## Controlled measurements

Measurements were collected sequentially on Windows 10, CPython 3.12.9 and OR-Tools 9.15.6755.
Both modes used the same V1 room requests, exact fixed solver and per-tier budget. `Master s` measures
only calls to `solver.solve(room_master_model)`. `Packings/s` is packings divided by that direct
master time; `Fixed s` is complete fixed-subproblem time. Runtime is noisy, so the decision also
uses packing counts, statuses, fixed-model structure and repeat runs.

| Tier / budget | Mode | Status | Master solves | Master s | Packings | Packings/s | Connected | First feasible s | Fixed s |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| I / 15 s | heuristic | FEASIBLE | 13 | 5.703 | 12 | 2.104 | 3 | 4.750 | 9.218 |
| I / 15 s | feasibility | FEASIBLE | 13 | 1.765 | 13 | 7.365 | 1 | 11.594 | 13.188 |
| II / 30 s | heuristic | TIME_LIMIT | 1 | 1.281 | 1 | 0.781 | 0 | - | 29.000 |
| II / 30 s | feasibility | FEASIBLE | 3 | 1.641 | 3 | 1.828 | 1 | 17.344 | 28.500 |
| III / 60 s | heuristic | TIME_LIMIT | 13 | 52.235 | 13 | 0.249 | 0 | - | 7.329 |
| III / 60 s | feasibility | TIME_LIMIT | 1 | 1.219 | 1 | 0.820 | 0 | - | 59.344 |
| IV / 90 s | heuristic | TIME_LIMIT | 10 | 84.548 | 10 | 0.118 | 0 | - | 5.217 |
| IV / 90 s | feasibility | TIME_LIMIT | 2 | 7.079 | 2 | 0.283 | 0 | - | 84.953 |

The candidate did reduce time spent inside the room master itself. It did not increase unique
packings examined in the large-tier wall-clock windows: Tier III fell from 13 to 1 and Tier IV from
10 to 2. Without the centrality ordering, the first arbitrary packing could be much harder for the
exact fixed solver. Tier III spent 58.703 seconds in the first fixed CP-SAT solve; a repeat spent
57.406 seconds on the same 13,352-variable flow domain. Tier IV spent 82.547 seconds in fixed CP-SAT.

Tier-I anytime behavior also regressed. The paired candidate run delayed the first incumbent from
4.750 to 11.594 seconds and returned `(scaled F, mass, E, C) = (63998, 118, 25, 12)` instead of
`(15253, 66, 11, 0)`. A second candidate run examined 23 packings but found no incumbent in 15
seconds. Tier II improved in the short sample, but that isolated gain does not offset the Tier-I
regression and the large-tier throughput collapse.

## Decision

Classification: **REJECT**.

The hypothesis that removing repeated heuristic master optimization improves time-to-first-feasible
is not supported. The objective is expensive, but its packing order materially reduces downstream
fixed-subproblem risk. The required positive large-tier screen was not met, so the full
60/120/180/300-second candidate release suite was not run. Production remains
`HEURISTIC_OBJECTIVE`; no production-default switch commit exists.

The added diagnostics are additive to result schema version 4 and benchmark schema version 7, so
neither schema version is bumped. They expose measurement detail without changing existing field
meaning or compatibility.
