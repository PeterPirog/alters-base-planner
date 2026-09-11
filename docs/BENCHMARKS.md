# Benchmark methodology

Status: **Stage 4 foundation**

This document defines how performance measurements for the exact production solver are collected and interpreted. It does not define game mechanics; `PROJECT_SYSTEM_REQUIREMENTS.md` and `docs/OPTIMIZATION_MODEL.md` remain normative for correctness.

## Purpose

Stage 3 provides a proof-capable exact objective decomposition. The principal remaining engineering risk is scalability: a realistic Tier I-IV request can exhaust its configured time or layout-attempt budget before the global proof closes.

Performance work therefore needs reproducible evidence before any optimization is accepted. The benchmark layer records both runtime and proof/search-quality diagnostics so that a faster solver is not accidentally obtained by weakening exactness.

## Benchmark command

After installing the project:

```bash
alters-base-benchmark --suite smoke
```

or equivalently:

```bash
python -m alters_base_planner.benchmark --suite smoke
```

The default output files are:

```text
benchmark-results.json
benchmark-results.md
```

Use the representative suite for deliberate performance measurements:

```bash
alters-base-benchmark \
  --suite representative \
  --json benchmark-results.json \
  --markdown benchmark-results.md
```

The representative suite can consume several minutes because its cases intentionally exercise the exact production solver under non-trivial budgets. It is not part of the normal unit-test CI path.

## Version-controlled suites

### Smoke

`tier1-baseline-smoke` is a short production-path check. It is useful for verifying that benchmark collection itself works. Its runtime is not a regression threshold.

### Representative

The initial Stage-4 suite covers all mobile Base tiers:

| Case | Tier | Intent | Budget |
|---|---:|---|---:|
| `tier1-workshop` | I | small high-traffic PLAYER extension | 15 s / 30 packings |
| `tier2-balanced` | II | mixed weighted and passive modules | 30 s / 60 packings |
| `tier3-production` | III | larger multi-pair production layout | 45 s / 100 packings |
| `tier4-dense` | IV | dense scalability stress case | 60 s / 150 packings |

These cases are benchmark fixtures, not recommendations for an ideal in-game room roster.

The exact case definitions live in `src/alters_base_planner/benchmark.py` and are therefore reviewed and versioned with solver changes.

## Captured metrics

Each record contains:

```text
status
configured_time_limit_s
configured_max_layout_attempts
elapsed_wall_s
solver_reported_search_s
room_packings_examined
connected_candidates_examined
fixed_objective_optima_proven
manhattan_pruned_count
search_exhausted
time_limit_reached
global_objective_optimum_proven
objective_scale
scaled_objective_value
scaled_modified_manhattan_lower_bound
weighted_distance_score
total_mass
elevator_module_count
corridor_count
```

The report also records the Python implementation/version, operating-system platform, OR-Tools version and planner version.

## Interpreting results

Performance comparison must preserve correctness first.

A change is suspicious even when faster if it unexpectedly changes any of the following on a deterministic/proven comparison case:

- feasibility status;
- exact objective or accepted tie-break result;
- proof state;
- exact lower-bound semantics;
- Airlock connectivity or other hard constraints.

Wall-clock measurements are noisy. Compare them only on sufficiently similar hardware/software environments and preferably over repeated runs. The repository currently records raw runs rather than pretending that one timing sample is a statistically stable threshold.

`global_objective_optimum_proven=false` is not itself a solver failure. It means the configured search did not close the complete proof. For Stage-4 analysis, the useful question is how quickly the solver improves the incumbent and closes the gap/proof boundary under fixed budgets.

## CI policy

Normal CI tests the benchmark **contract** (case definitions, serialization and Markdown reporting) but does not run the multi-minute representative suite. This prevents CI duration from becoming a hidden solver budget and avoids treating shared-runner timing noise as a performance regression.

Known-optimum correctness remains protected separately by the exhaustive Stage-3 reference-oracle tests.

## Next instrumentation increment

The current foundation captures end-to-end production metrics already exposed by `PlanResult`. The next Stage-4 increment should add internal model-size/build diagnostics, especially:

```text
fixed pair-flow graph nodes/arcs
positive-weight objective pair count
CP-SAT variable count
CP-SAT constraint count
model construction time
fixed-subproblem solve time
```

Those measurements should be added without changing solver decisions and then used to identify the actual dominant growth term before implementing domain reductions or cuts.
