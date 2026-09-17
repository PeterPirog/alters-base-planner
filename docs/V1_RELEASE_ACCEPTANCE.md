# V1 release acceptance

Status: **BLOCKED ON PRACTICAL USABILITY**

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

## Measured integrated-main baseline

The release-acceptance suite was measured on integrated `main` commit
`672e591e44e7b5343ef7242d56c62103f1f4110f` in two environments:

- local: Windows 10, CPython 3.12.9, OR-Tools 9.15.6755;
- GitHub Actions: Ubuntu, CPython 3.12.14, OR-Tools 9.15.6755, run
  [35004341669](https://github.com/PeterPirog/alters-base-planner/actions/runs/35004341669).

The tables retain measured values rather than combining the two runs. Fixed build and solve times
are totals across all fixed-packing subproblems in a case.

### Local baseline

| Tier | Classification | First feasible s | Packings | Connected | Fixed build s | Fixed CP-SAT s | Scaled F | Mass | E | C |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| I | USABLE_FEASIBLE | 6.312 | 66 | 6 | 0.985 | 13.516 | 15011 | 68 | 12 | 0 |
| II | USABLE_FEASIBLE | 120.609 | 1 | 1 | 0.485 | 118.235 | 81459 | 158 | 31 | 3 |
| III | NO_INCUMBENT_WITHIN_BUDGET | - | 32 | 0 | 21.841 | 0.611 | - | - | - | - |
| IV | NO_INCUMBENT_WITHIN_BUDGET | - | 27 | 0 | 17.624 | 0.564 | - | - | - | - |

### GitHub Actions baseline

| Tier | Classification | First feasible s | Packings | Connected | Fixed build s | Fixed CP-SAT s | Scaled F | Mass | E | C |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| I | USABLE_FEASIBLE | 4.262 | 142 | 6 | 0.435 | 7.951 | 15011 | 68 | 12 | 0 |
| II | USABLE_FEASIBLE | 120.057 | 1 | 1 | 0.132 | 119.075 | 81459 | 164 | 31 | 6 |
| III | NO_INCUMBENT_WITHIN_BUDGET | - | 50 | 0 | 12.057 | 0.244 | - | - | - | - |
| IV | NO_INCUMBENT_WITHIN_BUDGET | - | 45 | 0 | 9.158 | 0.195 | - | - | - | - |

For Tier III and IV, both environments examined tens of geometrically legal room packings without
finding one structurally connected candidate. Direct profiling attributed approximately 157 of the
local Tier-III 180 seconds and 282 of the local Tier-IV 300 seconds to room-master/packing-search
work before structural connectivity. The recorded fixed CP-SAT search totals were below one second
for both cases; fixed-model construction was secondary. The measured blocker is therefore room
packing enumeration before structural connectivity, not source-flow optimization.

Decision: **BLOCK_V1_ON_USABILITY**.

## Exact integrated hard-feasibility bootstrap experiment

The proposed bootstrap was tested directly against the accepted
`compile_integrated_hard_model()` adapter and its canonical `build_hard_constraint_layer()` on the
same local environment as the baseline. Each case used a 60-second diagnostic target from the
original construction start, eight CP-SAT workers, no gameplay objective and no approximation. No
bootstrap witness was passed to the fixed objective solver because every integrated SAT solve
returned `UNKNOWN` without a solution.

| Tier | Integrated status | Model build s | SAT solve s | Total observed s | CP-SAT variables | Constraints | Witness |
|---|---|---:|---:|---:|---:|---:|---|
| I | UNKNOWN | 1.500 | 60.906 | 62.406 | 32,250 | 57,624 | no |
| II | UNKNOWN | 4.906 | 62.078 | 66.984 | 91,216 | 168,394 | no |
| III | UNKNOWN | 16.766 | 41.265 | 58.031 | 243,002 | 458,736 | no |
| IV | UNKNOWN | 30.454 | 27.656 | 58.110 | 417,902 | 795,244 | no |

CP-SAT can finish slightly after its configured remaining-time limit, so observed wall time may
exceed the 60-second diagnostic target. That strengthens rather than weakens the release concern.
The Tier-I baseline found its first exact incumbent in 6.312 seconds, while this bootstrap found no
hard-feasible witness after consuming the entire release budget. The integrated model also grows to
417,902 variables and 795,244 constraints for Tier IV before the fixed exact objective model is
constructed.

This directly meets the experiment rejection criteria: the bootstrap consumes the Tier-I release
window, materially regresses existing usability and provides no first-feasible improvement. The
authoritative 11-minute release suite was not run because Tier I had already failed a mandatory
acceptance condition. No production solver change was retained and no second optimization strategy
was attempted.

Experiment decision: **REJECTED_EXPERIMENT**.

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
