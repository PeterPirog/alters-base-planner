# V1 release acceptance

Status: **IN PROGRESS**

Baseline integrated `main` at the start of this milestone:

`849a891c536e87b9552956b7eb7e194009345b52`

This milestone validates whether the mathematically accepted planner is also practically usable as a
public v1. It does not reopen Stage 4 and does not authorize speculative solver changes.

## Why this milestone exists

The short representative benchmark suite is intentionally diagnostic. On the accepted v1 solver it
found a Tier-I incumbent, while the Tier-II, Tier-III and Tier-IV representative cases reached their
short wall-clock limits without an incumbent. That result is not a correctness defect and does not
invalidate the exact model, but it is a product-utility risk that must be measured before v1.0.0.

The release-acceptance suite therefore reuses the exact same representative room configurations with
longer wall-clock windows. Its purpose is to measure practical time-to-first-feasible behavior on the
production solver, not to require global optimality inside arbitrary deadlines.

## Version-controlled release-acceptance suite

The authoritative cases are `V1_RELEASE_CASES` in
`src/alters_base_planner/release_acceptance.py`.

| Case | Tier | Time budget | Attempt ceiling | Purpose |
|---|---:|---:|---:|---|
| `v1-tier1-workshop` | I | 60 s | 10,000 | Confirm a practical feasible incumbent on the smallest representative request. |
| `v1-tier2-balanced` | II | 120 s | 10,000 | Measure time to first feasible on a mixed Tier-II request. |
| `v1-tier3-production` | III | 180 s | 10,000 | Measure practical feasibility on the larger Tier-III request. |
| `v1-tier4-dense` | IV | 300 s | 10,000 | Measure practical feasibility on the dense Tier-IV stress request. |

The high attempt ceiling is intentionally non-binding in normal operation so the global wall-clock
budget remains the meaningful limiter. Search exhaustion may still finish earlier.

These budgets are release-measurement windows, **not runtime SLAs** and **not optimality-proof
requirements**.

## How to run

Locally from an installed repository checkout:

```text
python -m alters_base_planner.release_acceptance \
  --json TEMP/v1-release-acceptance.json \
  --markdown TEMP/v1-release-acceptance.md
```

Or use the manual GitHub Actions `Benchmarks` workflow and select the `release` suite. The workflow
runs on Ubuntu 24.04 / Python 3.12 and uploads the JSON and Markdown report as an artifact.

## Non-negotiable correctness gates

Release acceptance never weakens the solver contract. Every reported feasible layout must still:

- satisfy exact hard feasibility and Airlock-rooted connectivity;
- use the accepted port/transit/Elevator semantics;
- pass the independent Dijkstra evaluation;
- satisfy `scaled_modified_manhattan_lower_bound <= scaled_objective_value`;
- preserve the exact `F -> total Base Mass -> Elevator -> Corridor` ordering;
- report best-known versus proven-global status honestly.

A `MODEL_INVALID`, internal objective/evaluator mismatch, false proof, invalid rendered witness or
lower-bound violation blocks v1 immediately.

## Product-utility decision rule

The release suite first gathers evidence; it does not automatically fail merely because global
optimality is unproven.

After the measured run, classify each Tier as:

- `USABLE_FEASIBLE`: a valid incumbent is found inside the release budget;
- `PROVEN`: the run additionally proves the global accepted objective;
- `NO_INCUMBENT_WITHIN_BUDGET`: no feasible incumbent is found before the configured wall-clock
  limit;
- `CORRECTNESS_FAILURE`: any correctness invariant fails.

The Project Manager and architecture review then make one explicit v1 decision:

1. **ACCEPT** the measured usability profile and continue to release metadata; or
2. **BLOCK V1 ON USABILITY** if one or more target Tier requests remain practically unusable.

If usability blocks v1, the next solver change must target the measured bottleneck from the release
report. It must be a cohesive, proof-safe intervention with before/after evidence. Do not start a
new optimization simply because it is available.

## Results

Release-acceptance results are intentionally not pre-filled. Record only measured evidence from the
integrated solver or from a review branch whose solver tree is identical to the integrated main
baseline.

| Tier | Status | First feasible s | Exact F | Mass | Elevators | Corridors | Global proof | Decision |
|---|---|---:|---:|---:|---:|---:|---|---|
| I | PENDING | - | - | - | - | - | - | PENDING |
| II | PENDING | - | - | - | - | - | - | PENDING |
| III | PENDING | - | - | - | - | - | - | PENDING |
| IV | PENDING | - | - | - | - | - | - | PENDING |

## Remaining release sequence

After release acceptance is explicitly accepted:

1. obtain the repository owner's software-license decision;
2. add the selected license and matching package metadata;
3. prepare `CHANGELOG.md` / release notes;
4. change the package version from `0.1.0` to `1.0.0`;
5. rerun local gates, release acceptance and normal GitHub CI on the final release SHA;
6. create annotated tag `v1.0.0` on reviewed `main`;
7. publish the GitHub Release.

Progression/game-state support and The Last Variable remain post-v1 work.
