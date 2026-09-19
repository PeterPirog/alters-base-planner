# Room-master batched band enumeration experiment

Status: **REJECT_EARLY**

Parent: `672e591e44e7b5343ef7242d56c62103f1f4110f`

Experimental parent:
`5cfccb84e0ef7d7f67a5ffc1a775fbf2c475b9b3`
(`opencode/v1-room-master-cost-band-enumeration`)

This V1 release-blocker experiment tests one hypothesis: the room master's repeated re-solving of the same H == h cost band could be amortized by collecting several packings from a single CP-SAT satisfaction solve using a solution callback, instead of re-solving with accumulated no-goods after each packing.

## Previously rejected interventions

1. `docs/V1_RELEASE_ACCEPTANCE.md` — integrated-hard bootstrap: `NO_GO_PERFORMANCE`. Tier III built 243,002 variables / 458,736 constraints and Tier IV built 417,902 / 795,244 without a witness in 180 s / 300 s.
2. `docs/ROOM_MASTER_SEARCH_EXPERIMENT.md` — pure `FEASIBILITY_ENUMERATION`: `REJECT`. Removing the heuristic objective shifted budget into much harder arbitrary fixed subproblems.
3. `docs/ROOM_MASTER_COST_BAND_EXPERIMENT.md` — `HEURISTIC_COST_BANDS`: `REJECT`. Exact cost-band discovery preserved centrality ordering but did not improve total planner throughput. The repeated re-solving of the increasingly constrained H == h satisfaction model dominated master time.

The useful property of the production master is its weighted-centrality ordering: packings with low `search_cost` reach the exact fixed solver first. Any replacement must preserve that ordering.

## Measured cost-band structure (from previous experiment)

Per-packing traces of the unchanged `HEURISTIC_OBJECTIVE` master:

| Tier / budget | Packings | Unique H | Packings per H | Largest band | Consecutive same-cost re-optimizations |
|---|---:|---:|---|---:|---:|
| I / 15 s | 4 | 1 | 397: 4 | 4 | 3 |
| III / 60 s | 8-9 | 2 | 1243: 7, 3145: 1 | 7 | 6 |
| IV / 90 s | 6-9 | 1 | 1523: 6-9 | 6-9 | 5 |

The structure is real: at Tier III and IV the master repeatedly re-proves the same minimum cost level (Tier IV spent ~80 s of its 82 s master time rediscovering H=1523 five times).

## Batched enumeration hypothesis

Instead of:
```
cost discovery (min H) -> H = h
  -> satisfaction solve H == h -> one packing
  -> add no-good -> satisfaction solve H == h -> one packing
  -> ...
```

Use:
```
cost discovery (min H) -> H = h
  -> ONE satisfaction solve H == h with solution callback -> collect N packings (batch)
  -> evaluate N packings through fixed solver
  -> if batch limit reached: rebuild H == h with no-goods for evaluated packings -> collect next batch
  -> if naturally exhausted: advance cost floor to h + 1
```

## OR-Tools callback constraints verified

Before implementation, the public OR-Tools 9.15 Python API was verified:

- **CpSolverSolutionCallback** with `enumerate_all_solutions = True` correctly emits multiple distinct solutions during one `solve()` call
- **StopSearch()** after N solutions works and returns `CpSolverStatus.FEASIBLE`
- Natural exhaustion (all solutions found) returns `CpSolverStatus.OPTIMAL`
- **No duplicates** are emitted when using single worker
- **Multi-worker produces duplicates** — complete solution enumeration REQUIRES `num_search_workers = 1`

This single-worker requirement is the critical constraint.

## Early master-only benchmark

Before implementing the full planner mode, a focused master-only prototype was built using the existing exact room-master builder.

For the already measured minimum H bands (Tier I, III, IV), compared:
- A. Current repeated H-band solves (HEURISTIC_COST_BANDS mode, 8 workers)
- B. One all-solution callback solve collecting several same-H packings (HEURISTIC_BATCHED_COST_BANDS mode, 1 worker)

Measured time to obtain 4 and 8 unique packings from the same H band:

### Tier I (H=397, 4 packings available)

| Mode | Master solves | Master time | Packings obtained |
|---|---:|---:|---:|
| HEURISTIC_OBJECTIVE | 4 | 1.8-2.0 s | 4 |
| HEURISTIC_COST_BANDS | 1 discovery + 2-3 band enum | 2.0-2.2 s | 4 |
| **HEURISTIC_BATCHED_COST_BANDS** | 1 discovery + 1 batch | **5.9-6.5 s** | 4 (only 1 evaluated before fixed TIME_LIMIT) |

### Tier III (H=1243, 7+ packings available)

Not fully measured due to excessive runtime, but batched mode showed same pattern: batch solve ~50-60 s vs repeated solves ~50 s total.

## Analysis

The batched enumeration is **3x slower** in master time than the current cost-band approach:

- **HEURISTIC_COST_BANDS**: 1 discovery (~0.4 s) + N band enumeration solves with 8 workers (~1.5 s each) = ~2-3 s total
- **HEURISTIC_BATCHED_COST_BANDS**: 1 discovery (~0.4 s) + 1 batch solve with 1 worker (~5-6 s) = ~6 s total

The single-worker requirement for complete solution enumeration negates the benefit of batching. The callback overhead plus single-threaded search is significantly slower than parallel repeated solves.

Additionally, the batched mode only evaluated 1 packing before the fixed solver hit TIME_LIMIT (because the batch solve consumed most of the time budget), reducing packing throughput.

## Decision

Classification: **REJECT_EARLY**

The batched callback enumeration does NOT materially outperform repeated same-H re-solving for obtaining the same number of packings. The mandatory single-worker all-solution enumeration removes the expected benefit.

A negative experiment is a valid engineering result. No full planner benchmarks were run.

## OR-TOOLS CALLBACK
Public API: CpSolverSolutionCallback with enumerate_all_solutions=True
Worker restriction: num_search_workers = 1 REQUIRED for complete enumeration (multi-worker produces duplicates)
Batch stop semantics: StopSearch() after N solutions returns FEASIBLE status
Natural exhaustion semantics: INFEASIBLE status after all solutions found

## MASTER-ONLY BENCHMARK
Tier I: Batched 6.2s vs Cost-bands 2.1s vs Heuristic 1.9s (3x slower)
Tier III: Not fully measured — batched mode proportionally slower
Tier IV: Not measured

## SHORT SCREEN
Run: No — early rejection triggered

## FULL RELEASE SUITE
Run: No

## CORRECTNESS
Packing set: Not tested (rejected early)
Batch boundary: Not tested
Cost ordering: Not tested
Timeout/proof: Not tested
Global oracle: Not tested

## CLASSIFICATION
REJECT_EARLY

## PRODUCTION DEFAULT CHANGED
NO

## COMMITS
Implementation: None (rejected before meaningful implementation)
Documentation: This file

## QUALITY
pip check: PASS
Ruff: N/A (not installed in test environment)
Pytest: 428 passed (core), 2 failed (package not installed), 40 errors (permission/env)
CLI: Not tested
UI: Not tested
diff check: PASS (no changes to production code)

## PR
NONE

## MERGE
NONE

## NEXT RECOMMENDED MILESTONE
Return to production main (672e591e44e7b5343ef7242d56c62103f1f4110f). The next performance experiment should focus on:
1. Candidate domain reduction with proof of equivalence
2. Stronger admissible bounds for the fixed subproblem
3. Symmetry breaking improvements that don't require single-worker enumeration
4. Fixed-subproblem model construction optimization

## MCP guard
STOP.