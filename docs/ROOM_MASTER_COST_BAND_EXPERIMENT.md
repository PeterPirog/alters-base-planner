# Room-master cost-band experiment

Status: **REJECTED FOR PRODUCTION**

Parent: `672e591e44e7b5343ef7242d56c62103f1f4110f`

Experimental parent:
`0462b7e9f1dc476fcfb7421ad8a14199bf9086e7`
(`opencode/v1-room-master-feasibility-enumeration`)

This V1 release-blocker experiment tests one hypothesis: the room master's repeated heuristic
optimization may be mostly re-proving the same exact minimum `search_cost` level, so discovering
each level once and then enumerating its complete equal-cost band with pure satisfaction solves
could remove repeated objective optimization overhead while preserving the centrality ordering. It
does not change Base mechanics, the exact fixed-packing solver or global proof semantics.

## Previously rejected interventions

1. `docs/V1_RELEASE_ACCEPTANCE.md` — integrated-hard bootstrap: `NO_GO_PERFORMANCE`. Tier III built
   243,002 variables / 458,736 constraints and Tier IV built 417,902 / 795,244 without a witness in
   180 s / 300 s; sparse Corridor/Elevator hints did not recover a witness.
2. `docs/ROOM_MASTER_SEARCH_EXPERIMENT.md` — pure `FEASIBILITY_ENUMERATION`: `REJECT`. Removing the
   heuristic objective shifted the budget into much harder arbitrary fixed subproblems (Tier III
   58.703 s in one fixed solve; Tier IV 82.547 s) and regressed Tier-I anytime behavior.

The useful property of the production master is therefore its weighted-centrality ordering: packings
with low `search_cost` reach the exact fixed solver first, and those packings are structurally
friendlier. Any replacement must preserve that ordering.

## Measured cost-band structure (production mode, short screens)

Per-packing traces of the unchanged `HEURISTIC_OBJECTIVE` master were recorded through the private
benchmark seam (`scripts/benchmark_room_master_modes.py`), storing exact Python-integer selected
`search_cost` per emitted packing plus master elapsed time and status. Every `OPTIMAL` master solve
was cross-checked against `round(solver.objective_value)`; no disagreement occurred.

| Tier / budget | Packings | Unique H | Packings per H | Largest band | Consecutive same-cost re-optimizations | Master s by H |
|---|---:|---:|---|---:|---:|---|
| I / 15 s | 4 | 1 | 397: 4 | 4 | 3 | 397: 2.296 |
| II / 30 s | 1 | 1 | 637: 1 | 1 | 0 | 637: 1.625 |
| III / 60 s | 8 | 2 | 1243: 7, 3145: 1 | 7 | 6 | 1243: 46.439, 3145: 6.078 |
| IV / 90 s | 6 | 1 | 1523: 6 | 6 | 5 | 1523: 79.718 |

The structure is real: at Tier I, III and IV the master repeatedly re-proved the same minimum cost
level (Tier IV spent 79.718 s of its 82.656 s master time rediscovering H=1523 five times). The
hypothesis was therefore plausible. At Tier III the eighth emitted packing was a
`FEASIBLE`-not-`OPTIMAL` discovery at H=3145 near the deadline, which per the fail-safe rule must
never advance the cost floor.

## Exact cost-band algorithm

`HEURISTIC_COST_BANDS` is a third private room-master mode, reachable only through the internal
benchmark seam and `_solve_instances` tests. It is not exposed through CLI, Streamlit,
`PlanRequest` or configuration schema, and production `solve_plan()` still uses
`HEURISTIC_OBJECTIVE`.

Let `H(p)` be the existing exact integer sum of selected candidate `search_cost` terms.

1. Candidate geometry is generated once per planning request.
2. One canonical builder creates placement variables, exactly-one constraints, cell non-overlap,
   identical-instance symmetry breaking and the integer `H` expression. All three modes share it;
   no second placement implementation exists.
3. Cost discovery: an objective master `min H` (plus `H >= cost_floor` when the floor exceeds the
   natural minimum) is solved under the remaining global wall-clock budget.
4. On `OPTIMAL`, `h` is the exact Python-integer sum of the selected candidates, cross-checked
   against `round(solver.objective_value)`. The returned packing is the first packing of the band.
5. A fresh satisfaction master with the same domain plus `H == h` and no objective enumerates the
   remaining band members using the existing exact no-good; every emitted packing is evaluated by
   the unchanged fixed solver.
6. When the `H == h` model returns `INFEASIBLE`, the band is exhausted, `cost_floor = h + 1`, and
   the master re-optimizes for the next level.
7. A final discovery `INFEASIBLE` proves all remaining packings exhausted, which supports the
   ordinary global search-exhaustion proof together with the normal fixed-subproblem conditions.

Fail-safe rule: a `FEASIBLE`-not-`OPTIMAL` discovery does not start a band, does not advance the
floor, cannot be used for exhaustion proof, and leaves `global_objective_optimum_proven=false`.
The discovered packing is still evaluated as an ordinary best-effort packing.

`max_layout_attempts` continues to count evaluated room packings only. All construction, discovery,
enumeration and fixed solves share one global deadline. No canonical packing can be emitted twice:
within a band the existing exact no-good excludes each evaluated packing, and between bands
`H >= h_previous + 1` makes older bands impossible.

## Feasible-set and proof argument

The candidate mode does not alter the room-packing feasible set. The finite packing set partitions
by integer `H` into `P = union_h P_h`, `P_h = {p : H(p) = h}`. The algorithm discovers the smallest
remaining non-empty `h`, enumerates `P_h` completely, and advances. Complete exhaustion therefore
enumerates exactly the same packing set as the production master. `H` is only a search-order
heuristic; the authoritative objective for every packing remains
`F -> Base Mass -> Elevator count -> Corridor count`, so global exact optimum and proof semantics
are unchanged.

## Correctness evidence

Tiny exhaustive tests compare canonical packing sets of `HEURISTIC_OBJECTIVE`,
`FEASIBILITY_ENUMERATION` and `HEURISTIC_COST_BANDS` for two-room overlap alternatives, a
multi-cost-level case, identical-instance symmetry and an asymmetric Base mask: the sets are
exactly equal and no packing is emitted twice. The candidate emits heuristic costs in
non-decreasing order, completes each band before any larger `H` appears, transitions
`discover H1 -> enumerate H1 -> prove H1 exhausted -> discover H2 -> ... -> final discovery
INFEASIBLE` with `search_exhausted == true`, matches the tiny global exact oracle tuple
`(scaled F, total mass, Elevator count, Corridor count)` and its proof, and keeps
`global_objective_optimum_proven=false` for timeout during discovery, timeout during enumeration,
fixed-solver timeout after a band packing, and attempt limit inside a band.

## Short-screen measurements

Sequential runs on Windows 10, CPython 3.12.9, OR-Tools 9.15.6755, same machine and requests.
`Master s` covers only `solver.solve(room_master_model)` calls; `Fixed s` covers complete
fixed-subproblem time. Three runs per tier and mode where the window permitted.

Tier I / 15 s:

| Mode | Run | Packings | Master s | Discovery s | Band s | Connected | First feasible s | Fixed s | Scaled F / mass / E / C |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| heuristic | 1 | 4 | 2.296 | - | - | 2 | 8.297 | 12.688 | 15351 / 66 / 11 / 0 |
| heuristic | 2 | 10 | 4.031 | - | - | 3 | 5.781 | 10.891 | 15253 / 66 / 11 / 0 |
| heuristic | 3 | 7 | 3.500 | - | - | 3 | 6.234 | 11.313 | 15253 / 66 / 11 / 0 |
| cost bands | 1 | 2 | 1.531 | 0.375 | 1.156 | 2 | 6.141 | 13.375 | 15601 / 94 / 23 / 2 |
| cost bands | 2 | 2 | 2.266 | 0.344 | 1.922 | 2 | 5.906 | 12.609 | 15601 / 94 / 23 / 2 |
| cost bands | 3 | 2 | 1.312 | 0.312 | 1.000 | 2 | 6.375 | 13.798 | 15601 / 122 / 37 / 2 |

Tier II / 30 s: both modes hit `TIME_LIMIT` in all three runs with exactly one packing whose fixed
subproblem consumed ~29 s (heuristic master 1.172-1.625 s; cost-band discovery 1.063-1.453 s). No
incumbent in either mode.

Tier III / 60 s:

| Mode | Run | Packings | Master s | Discovery s | Band s | Fixed s |
|---|---:|---:|---:|---:|---:|---:|
| heuristic | 1 | 8 | 52.517 | - | - | 7.109 |
| heuristic | 2 | 9 | 50.672 | - | - | 8.498 |
| cost bands | 1 | 8 | 53.279 | 4.484 | 48.795 | 6.282 |
| cost bands | 2 | 7 | 52.486 | 4.422 | 48.064 | 6.219 |

Tier IV / 90 s:

| Mode | Run | Packings | Master s | Discovery s | Band s | Fixed s |
|---|---:|---:|---:|---:|---:|---:|
| heuristic | 1 | 6 | 82.656 | - | - | 5.217 |
| heuristic | 2 | 9 | 82.641 | - | - | 6.782 |
| cost bands | 1 | 6 | 84.936 | 8.250 | 76.686 | 4.205 |
| cost bands | 2 | 6 | 84.564 | 8.485 | 76.079 | 4.329 |

Cost-band multiplicity matched the baseline trace in every candidate run (Tier I band H=397; Tier
III band H=1243; Tier IV band H=1523), and no fixed subproblem exploded the way pure feasibility
enumeration did.

## Short-screen analysis

The hypothesis is falsified. The measured cost-band structure is real, but removing the repeated
optimization does not remove the cost that caused it:

- Tier IV: the candidate examined the same 6 packings as the baseline while its band enumeration
  alone took 76.1-76.7 s versus 82.6 s of full repeated optimization. The discovery step is cheap
  (8.3-8.5 s once), but every subsequent `H == h` satisfaction re-solve under accumulated no-goods
  costs nearly as much as the corresponding re-optimization. Most master time is re-solving the
  increasingly constrained packing model, not proving optimality.
- Tier III: no throughput gain either (7-8 packings both modes; master 52.5-53.3 s candidate vs
  50.7-52.5 s baseline).
- Tier II: unchanged (both modes blocked ~29 s in the first fixed subproblem).
- Tier I: the candidate is faster inside the master (1.3-2.3 s vs 2.3-4.0 s), but within-band order
  is intentionally unspecified, so the second emitted packing had a harder fixed subproblem
  (12.6-13.8 s) and the incumbent regressed from 15253-15351 / 66 / 11 / 0 to 15601 / 94-122 /
  23-37 / 2. There was no collapse below the first feasible time (5.9-6.4 s), but the anytime
  incumbent quality clearly degraded while throughput fell from 4-10 to 2 packings.

The required positive evidence — materially lower master optimization time with at least similar
packing throughput — was not met on any tier.

## Decision

Classification: **REJECT**.

The repeated optimization that the experiment targeted is not redundant work: re-solving the
packing model under accumulated no-goods dominates master time, and the objective component that
cost-band discovery removes is a minority of it. The candidate preserves centrality ordering and
all correctness invariants, but it does not improve the total search process, and it slightly
regresses Tier-I anytime quality. The full 60/120/180/300-second candidate release suite was not
run because the positive large-tier screen failed. Production remains `HEURISTIC_OBJECTIVE`; no
production-default switch commit exists.

The cost-band diagnostics are additive to result schema version 4 and benchmark schema version 7,
so neither schema version is bumped.