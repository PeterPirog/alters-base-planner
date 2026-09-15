# Benchmark methodology

Status: **Stage 4 complete / maintain**

This document defines how performance measurements for the exact production solver are collected and interpreted. It does not define game mechanics; `PROJECT_SYSTEM_REQUIREMENTS.md` and `docs/OPTIMIZATION_MODEL.md` remain normative for correctness.

## Purpose

Stage 3 provides a proof-capable exact objective decomposition. The principal remaining engineering risk is scalability: a realistic Tier I-IV request can exhaust its configured time or layout-attempt budget before the global proof closes.

Performance work therefore needs reproducible evidence before any optimization is accepted. The benchmark layer records runtime, model size and proof/search-quality diagnostics so that a faster solver is not accidentally obtained by weakening exactness.

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

## Reproducible GitHub benchmark runs

`.github/workflows/benchmark.yml` provides an explicit `workflow_dispatch` benchmark job. It never runs automatically on ordinary pushes or pull requests, so representative measurements cannot silently increase normal CI duration.

From the GitHub Actions UI choose **Benchmarks**, select **Run workflow**, then choose either:

```text
smoke
representative
```

The workflow uses Ubuntu 24.04 and Python 3.12, installs the package from the selected repository revision, runs the production benchmark command and uploads both reports as one artifact:

```text
benchmark-results.json
benchmark-results.md
```

Artifacts are retained for 30 days. The artifact name includes the selected suite and GitHub run ID. The JSON report remains the authoritative machine-readable record because it also captures Python, platform, OR-Tools and planner versions.

This workflow is intended to provide a stable shared-runner reference environment. It does not make shared-host timing deterministic; compare runtime samples cautiously and use structural model-size/proof metrics alongside wall time.

## Version-controlled suites

### Smoke

The smoke suite runs one short production-path check for each mobile Base tier:

| Case | Tier | Budget |
|---|---:|---:|
| `tier1-baseline-smoke` | I | 1 s / 1 packing |
| `tier2-baseline-smoke` | II | 1 s / 1 packing |
| `tier3-baseline-smoke` | III | 1 s / 1 packing |
| `tier4-baseline-smoke` | IV | 1 s / 1 packing |

These cases verify benchmark collection and honest timeout behavior. Their runtimes are not
regression thresholds, and they are not required to find an incumbent.

### Representative

The Stage-4 suite covers all mobile Base tiers:

| Case | Tier | Intent | Budget |
|---|---:|---|---:|
| `tier1-workshop` | I | small high-traffic PLAYER extension | 15 s / 30 packings |
| `tier2-balanced` | II | mixed weighted and passive modules | 30 s / 60 packings |
| `tier3-production` | III | larger multi-pair production layout | 45 s / 100 packings |
| `tier4-dense` | IV | dense scalability stress case | 60 s / 150 packings |

These cases are benchmark fixtures, not recommendations for an ideal in-game room roster.

The exact case definitions live in `src/alters_base_planner/benchmark.py` and are therefore reviewed and versioned with solver changes.

## Captured metrics

Benchmark schema version 7 records the end-to-end search/proof metrics:

```text
status
configured_time_limit_s
configured_max_layout_attempts
elapsed_wall_s
solver_reported_search_s
time_to_first_feasible_s
room_packings_examined
connected_candidates_examined
fixed_objective_optima_proven
manhattan_pruned_count
incumbent_bound_pruned_count
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

`manhattan_pruned_count` counts room packings excluded before the fixed subproblem because their exact-integer admissible lower bound is strictly worse than the current incumbent primary objective.

`incumbent_bound_pruned_count` counts packings for which the exact fixed source-aggregated flow model, constrained by `scaled_F <= incumbent_scaled_F`, is proven infeasible. Such a packing cannot match or improve the incumbent primary objective. It is intentionally tracked separately from modified-Manhattan pruning because it is a stronger exact subproblem proof, not a heuristic or lower-bound estimate.

Stage-4 fixed-subproblem instrumentation additionally records:

```text
fixed_subproblem_count
max_fixed_graph_nodes
max_fixed_graph_arcs
max_fixed_objective_pairs
fixed_flow_formulation
max_fixed_source_commodities
max_fixed_source_flow_variables
max_fixed_source_flow_full_variables
total_fixed_source_flow_variables
total_fixed_source_flow_full_variables
max_fixed_condition_capacity_buckets
max_fixed_condition_capacity_literals
max_fixed_endpoint_distribution_variables
max_fixed_flow_capacity_constraints
max_fixed_flow_balance_constraints
fixed_incumbent_distance_cap_pruning_used
fixed_objective_bound_relaxation_pruned
max_fixed_relaxed_graph_primary_lower_bound
min_fixed_incumbent_primary_bound
max_fixed_incumbent_distance_cap_pairs
max_fixed_source_flow_variables_before_incumbent_cap
max_fixed_source_flow_variables_after_incumbent_cap
max_fixed_incumbent_cap_pruned_flow_variables
max_fixed_cp_sat_variables
max_fixed_cp_sat_constraints
lexicographic_scalarization.used
lexicographic_scalarization.max_primary_objective_upper_bound
lexicographic_scalarization.max_combined_objective_upper_bound
lexicographic_scalarization.max_weight_f
lexicographic_scalarization.max_weight_mass
lexicographic_scalarization.max_weight_elevator
lexicographic_scalarization.max_weight_corridor
lexicographic_scalarization.max_corridor_bound
lexicographic_scalarization.max_elevator_bound
lexicographic_scalarization.max_mass_bound
lexicographic_scalarization.max_incumbent_scalar_value
fixed_model_build_time_s
fixed_cp_sat_solve_time_s
fixed_subproblem_time_s
fixed_hard_model_build_time_s
fixed_path_graph_build_time_s
fixed_objective_definition_time_s
fixed_source_flow_model_build_time_s
fixed_lexicographic_finalize_time_s
```

The `max_*` values are maxima across all exact fixed-packing subproblems attempted during one planning run. Every timing value above is a total across those subproblems. The five sequential build-phase totals partition the instrumented model-construction work:

- `fixed_hard_model_build_time_s`: `compile_fixed_layout_hard_model(...)`;
- `fixed_path_graph_build_time_s`: `_build_path_graph(...)`;
- `fixed_objective_definition_time_s`: exact scaled-objective and source-commodity definitions;
- `fixed_source_flow_model_build_time_s`: source-flow variables, balances and conditional-arc constraints;
- `fixed_lexicographic_finalize_time_s`: secondary expressions, finite bounds, incumbent cut, scalarized objective and model-size snapshot.

The phase clocks are monotonic, sequential and non-overlapping. Their sum cannot exceed `fixed_model_build_time_s` except for negligible clock/accounting tolerance. CP-SAT search remains outside these build phases and is reported separately by `fixed_cp_sat_solve_time_s`. Model validation and exact evaluator work are also outside the build phases and are included only in `fixed_subproblem_time_s`; phase timing never affects correctness decisions. CP-SAT variable/constraint counts describe the single lexicographic-scalarized model.

`lexicographic_scalarization.used` reports whether attempted fixed subproblems used the exact scalarized objective. The `max_weight_*` and `max_*_bound` fields are maxima across attempted fixed subproblems. `max_primary_objective_upper_bound` is the maximum conservative scaled-`F` bound used in the signed-integer safety calculation, and `max_combined_objective_upper_bound` is the maximum resulting combined-objective safety bound. `max_incumbent_scalar_value` is separately the largest scalar value among returned incumbents; it is not an objective upper bound and is `null` when no fixed subproblem returned an incumbent.

`fixed_model_build_time_s` covers construction of the fixed hard model, conditional travel graph and source-aggregated flow objective. `fixed_cp_sat_solve_time_s` measures time spent inside the single CP-SAT lexicographic-scalarized solve call. `fixed_subproblem_time_s` covers the complete fixed-objective calls, including model construction, validation, the CP-SAT solve and exact evaluator work.

Result JSON schema version 4 keeps the existing total timing fields and adds the phase totals under:

```text
fixed_subproblems.build_phases:
    hard_model_time_s
    path_graph_time_s
    objective_definition_time_s
    source_flow_time_s
    lexicographic_finalize_time_s
    total_model_build_time_s
```

These fields are additive diagnostics apart from one incompatible rename: result schema version 4
replaced `max_shared_activation_gates` with `max_condition_capacity_buckets` and added
`max_condition_capacity_literals`, because exact condition-capacity buckets replaced shared
activation gates. Benchmark schema version 6 recorded the same rename, replacing benchmark schema
version 5. Benchmark schema version 7 adds `time_to_first_feasible_s`; it is `null` when no
incumbent was found. The condition-bucket and incumbent distance-cap fields are otherwise purely
additive, so result schema version 4 and evidence metadata schema version 3 remain unchanged. The
four source-flow construction counts are maxima across fixed subproblems. They
expose exact condition-capacity bucket constraints, distinct Boolean infrastructure conditions
represented by those buckets, explicit endpoint-allocation variables, capacity constraints and
balance/endpoint constraints. The direct endpoint formulation reports zero explicit
endpoint-allocation variables, and every flow-capacity constraint is one emitted bucket chunk.

The report also records the Python implementation/version, operating-system platform, OR-Tools version and planner version.

## Source-aggregated flow variable-domain reduction

The exact fixed-packing objective originally created one flow Boolean for every combination of positive-weight objective pair and directed graph arc. The current formulation deterministically orients every pair and aggregates all exact pair coefficients with the same source into one integer multi-sink commodity. For `N` positive-weight rooms this creates at most `N - 1` commodities instead of `N * (N - 1) / 2`.

Each source commodity is restricted to arcs in the intersection of relaxed forward reachability from its source ports and reverse reachability from the union of all its target ports. Infrastructure-selection conditions are ignored for this analysis, so the graph remains a relaxation of every realizable network. Source revisits are removed; target ports remain available for legal transit toward another target. Singleton source/target distributions are represented by constants. These are exact presolve/domain reductions, not heuristic routing rules.

The benchmark records the source commodity count, actual source-flow integer arc variables after domain reduction, and the corresponding full `source commodities x graph arcs` count:

```text
max_fixed_source_commodities
max_fixed_source_flow_variables
max_fixed_source_flow_full_variables
total_fixed_source_flow_variables
total_fixed_source_flow_full_variables
```

The two `total_*` fields are sums over the same fixed-packing subproblems and therefore support a meaningful aggregate structural-reduction ratio:

```text
reduction = 1 - total_actual / total_full
```

The benchmark report must use these totals for the reduction percentage. A ratio derived from independent maxima would be potentially misleading because the maxima need not come from the same subproblem.

These counts are structural diagnostics. A lower flow-variable count is evidence that the formulation is smaller; it is not by itself evidence that end-to-end runtime improved. Runtime claims still require representative benchmark measurements on comparable environments.

### Local fixed-packing comparison

The following isolated comparison was collected on 2026-09-14 with Python 3.14.4,
OR-Tools 9.15.6755 and Windows 10. It uses one deterministic, directly connected row of 15
positive-weight rooms (105 objective pairs), a 20-second fixed-subproblem limit, and five fresh
solves per formulation. It is evidence for this fixed model only, not a representative-suite or
end-to-end runtime claim.

| Metric | Pair-specific baseline | Source-aggregated |
|---|---:|---:|
| Objective pairs | 105 | 105 |
| Flow commodities | 105 | 14 |
| Actual arc-flow variables | 1,834 | 406 |
| Full-domain arc-flow variables | 6,090 | 812 |
| Total CP-SAT variables | 1,937 | 719 |
| Total CP-SAT constraints | 1,296 | 505 |
| Model-build time, min / median / max | 61.4 / 65.9 / 74.9 ms | 20.3 / 21.2 / 21.5 ms |
| CP-SAT solve time, min / median / max | 20.5 / 22.9 / 30.6 ms | 19.0 / 21.1 / 22.2 ms |

On this packing, source aggregation removes 77.9% of the actual arc-flow variables, 62.9% of all
CP-SAT variables and 61.0% of constraints. The deterministic size reduction is the primary result;
the small solve-time difference should not be generalized beyond this sample.

### Local Tier-IV first-subproblem profile

The following diagnostic profile was collected on 2026-09-14 with Python 3.12.9, OR-Tools
9.15.6755 and Windows 10. The TEMP-only request uses Tier IV, the interactive default PLAYER
counts, a 30-second global budget and `max_layout_attempts = 1`. Each formulation was run three
times sequentially. Every run selected a first packing whose fixed graph had exactly 442 nodes,
1,496 arcs and 105 objective pairs, so the structural comparison is directly comparable. All runs
reported `NO_CONNECTED_LAYOUT`, one room packing, zero connected candidates and one fixed
subproblem; the purpose was construction profiling rather than finding or proving an optimal Base.

The pair-specific baseline was executed from a detached worktree at parent commit `8985b5e`.
`PYTHONPATH` pointed explicitly to that worktree's `src`, and the imported package path was checked
before measurement. The source-aggregated runs used the current branch checkout.

| Structural metric | Parent pair-flow | Source-aggregated |
|---|---:|---:|
| Runs | 3 | 3 |
| Graph nodes | 442 | 442 |
| Graph arcs | 1,496 | 1,496 |
| Objective pairs | 105 | 105 |
| Flow commodities | 105 | 14 |
| Actual arc-flow variables | 135,226 | 19,370 |
| Full-domain arc-flow variables | 157,080 | 20,944 |
| Total CP-SAT variables | 138,358 | 22,346 |
| Total CP-SAT constraints | 304,264 | 47,568 |

Source-aggregated build phases:

| Run | Hard | Graph | Objective | Source flow | Lex finalize | Total build | CP-SAT solve | Fixed total |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.172 | 0.016 | 0.000 | 1.140 | 0.188 | 1.516 | 0.062 | 1.625 |
| 2 | 0.203 | 0.000 | 0.016 | 0.984 | 0.187 | 1.390 | 0.063 | 1.500 |
| 3 | 0.203 | 0.015 | 0.000 | 1.141 | 0.281 | 1.640 | 0.062 | 1.765 |

| Phase | Min / median / max |
|---|---:|
| Hard model | 0.172 / 0.203 / 0.203 s |
| Path graph | 0.000 / 0.015 / 0.016 s |
| Objective definition | 0.000 / 0.000 / 0.016 s |
| Source-flow model | 0.984 / 1.140 / 1.141 s |
| Lexicographic finalization | 0.187 / 0.188 / 0.281 s |
| Total model build | 1.390 / 1.516 / 1.640 s |
| CP-SAT solve | 0.062 / 0.062 / 0.063 s |
| Total fixed subproblem | 1.500 / 1.625 / 1.765 s |

The min/median/max values summarize each timing column independently. Consequently, the phase
medians need not add up to the median total; the raw per-run rows above show the timing partition
invariant for each fixed solve.

Parent aggregate timings, for which phase-level instrumentation was not present:

| Timing | Min / median / max |
|---|---:|
| Total model build | 6.234 / 7.125 / 7.329 s |
| CP-SAT solve | 0.313 / 0.343 / 0.344 s |
| Total fixed subproblem | 6.797 / 7.703 / 7.922 s |

These are local development-machine measurements, not correctness thresholds or universal
performance claims. Runtime ratios must not be extrapolated to arbitrary Tier-IV requests. The
deterministic model-size counts and matching graph shape are stronger evidence than the noisy wall
times. Using the diagnostic classification labels, the next bottleneck is
`SOURCE_FLOW_MODEL_BUILD` (the `fixed_source_flow_model_build_time_s` phase), while CP-SAT search
is comparatively small. The next optimization iteration should first micro-profile
`_add_source_aggregated_flow_objective()` and reduce Python/protobuf construction overhead in its
sparse variable, conditional-bound and node-balance creation without changing the exact flow
formulation, objective, domains or proof semantics.

### Local source-flow construction optimization

The next construction iteration was measured on 2026-09-14 with Python 3.12.9, OR-Tools
9.15.6755 and Windows 10. The exact parent `58cfaaa` ran from a detached worktree; the candidate
ran from the feature checkout. Both used the same TEMP-only Tier-IV request and harness described
above. The three timed solves followed one untimed structure probe in each process.

| Structural metric | Parent | Candidate |
|---|---:|---:|
| Graph nodes / arcs | 442 / 1,496 | 442 / 1,496 |
| Objective pairs / source commodities | 105 / 14 | 105 / 14 |
| Source-flow variables | 19,370 | 19,370 |
| Explicit endpoint-allocation variables | 208 | 0 |
| Shared multi-condition activation gates | 0 | 699 |
| Conditional capacity constraints | 37,078 | 18,904 |
| Total CP-SAT variables | 22,346 | 22,837 |
| Total CP-SAT constraints | 47,568 | 30,067 |

| Timing | Parent min / median / max | Candidate min / median / max |
|---|---:|---:|
| Source-flow model build | 0.860 / 0.891 / 0.891 s | 0.610 / 0.719 / 0.797 s |
| Total model build | 1.125 / 1.219 / 1.235 s | 0.985 / 1.141 / 1.156 s |
| CP-SAT solve | 0.047 / 0.047 / 0.062 s | 0.031 / 0.047 / 0.063 s |

The candidate leaves the proof-safe flow domain unchanged, removes every endpoint-allocation
variable, and reduces total constraints by 36.8%. Exact shared gates add 491 net CP-SAT variables
(2.2%), while source-flow construction median falls by 19.3% and total model-build median by 6.4%.
These local timings support the deterministic structural result but remain measurements rather
than correctness thresholds.

The directly connected 15-room control has no conditional arcs. Its source-flow variables remain
406 and total constraints remain 505, while direct endpoint balances reduce total CP-SAT variables
from 719 to 509. This isolates the endpoint-variable elimination from the shared-gate change.

### Local condition-capacity bucket aggregation

The next construction iteration replaced per-variable conditional capacity bounds and shared
AND-gate variables with exact global condition-capacity buckets, measured on 2026-09-14 with
Python 3.12.9, OR-Tools 9.15.6755 and Windows 10. Parent `656870c` and the candidate ran from the
same checkout state on the same machine with the same TEMP-only Tier-IV request and harness; the
three timed solves followed one untimed structure probe in each process.

For one Boolean condition `c` with conditioned flow variables `v_i` and individual upper bounds
`U_i`, the bucket constraint `sum_i v_i <= c * sum_i U_i` is exactly equivalent to the individual
bounds `v_i <= U_i * c`: at `c = 0` every non-negative `v_i` is forced to zero, and at `c = 1` the
bound is implied by the individual domains. A multi-condition arc joins the bucket of every
required condition, so no AND-gate variables remain. Aggregated sums are split into deterministic
int64-safe chunks; production quantities never approach that limit, so one chunk per condition is
normal.

| Structural metric | Parent | Candidate |
|---|---:|---:|
| Graph nodes / arcs | 442 / 1,496 | 442 / 1,496 |
| Objective pairs / source commodities | 105 / 14 | 105 / 14 |
| Source-flow variables | 19,370 | 19,370 |
| Shared activation gates | 699 | 0 |
| Condition-capacity buckets (emitted constraints) | 0 | 805 |
| Distinct bucket condition literals | 0 | 805 |
| Flow-capacity constraints | 18,904 | 805 |
| Total CP-SAT variables | 22,837 | 22,138 |
| Total CP-SAT constraints | 30,067 | 11,269 |

| Timing | Parent min / median / max | Candidate min / median / max |
|---|---:|---:|
| Source-flow model build | 0.672 / 0.750 / 0.891 s | 0.531 / 0.578 / 0.594 s |
| Total model build | 0.938 / 1.078 / 1.329 s | 0.844 / 0.891 / 1.031 s |
| CP-SAT solve | 0.047 / 0.047 / 0.047 s | 0.031 / 0.031 / 0.047 s |

Every bucket required exactly one chunk because the aggregated upper-bound sums stay far below
the safe limit. The candidate removes all 699 gate variables, replaces 18,904 individual capacity
constraints with 805 exact bucket constraints (62.5% fewer total CP-SAT constraints), reduces
total CP-SAT variables by 699 (the removed gates; 3.1%), and improves source-flow construction
median by 23.0% and total model-build median by 17.3%. The
directly connected 15-room control has no conditional arcs; its structure is unchanged (406
source-flow variables, 509 CP-SAT variables, 505 constraints, zero buckets). These local timings
support the deterministic structural result but remain measurements rather than correctness
thresholds. The formulation, objective, incumbent cut and proof semantics are unchanged; only the
representation of conditional flow activation changed.

### Local incumbent distance-cap pruning

The next iteration derives exact per-pair distance caps from the incumbent bound and prunes
source-flow arcs before variables are created, measured on 2026-09-14 with Python 3.12.9,
OR-Tools 9.15.6755 and Windows 10. The proof boundary is documented in `docs/OPTIMIZATION_MODEL.md`:
integer Dijkstra lower bounds `l_st` on the unconditional relaxed graph give `LB = sum c_st*l_st`;
`LB > B` proves bound domination before CP-SAT, otherwise `cap_st = l_st + (B-LB)//c_st` and an
arc is retained for a source commodity iff it is cap-admissible for at least one of that
commodity's targets.

Unbounded first-subproblem control (same TEMP-only Tier-IV request and harness as the sections
above; parent `43ffc93` numbers from its own session):

| Metric | Parent | Candidate |
|---|---:|---:|
| Source-flow variables / buckets | 19,370 / 805 | 19,370 / 805 |
| Total CP-SAT variables / constraints | 22,138 / 11,269 | 22,138 / 11,269 |
| Source-flow build min / median / max | 0.531 / 0.578 / 0.594 s | 0.531 / 0.593 / 0.641 s |

The unbounded model is structurally identical, as required; the first fixed subproblem performs
no incumbent-cap computation at all.

Bounded experiments (three timed repetitions after one warm-up each):

- **Controlled trio** (airlock, workshop, command center in one row; exact optimum `F* = 280`,
  three objective pairs, 14 source-flow variables unbounded). With the tight bound `B = F*` the
  relaxed lower bound equals `F*`, all three pairs are capped, and pruning removes 9 of 14 flow
  variables: total CP-SAT variables fall 33 -> 24 and constraints 45 -> 44 while the solver still
  returns `OPTIMAL 280` — equality is preserved. With `B = F* - 1` the relaxation alone proves
  `OBJECTIVE_BOUND_INFEASIBLE` before CP-SAT (zero CP-SAT variables created). A loose bound
  `B = F* + 10^6` prunes zero arcs and keeps the exact result.

- **Tier-IV synthetic-bound diagnostic.** The captured first packing (442 nodes, 1,496 arcs, 105
  pairs, 14 commodities, 19,370 unbounded source-flow variables) is hard-infeasible
  (`NO_CONNECTED_LAYOUT`), so it has no credible real incumbent. SYNTHETIC bounds were used purely
  for structural measurement and are not planner incumbents: the relaxed lower bound measured
  `LB = 105,221`. With the synthetic tight bound `B = LB`, 91 of 105 pairs received finite caps,
  source-flow variables fell 19,370 -> 787 (95.9% pruned), total CP-SAT variables fell
  22,138 -> 3,555 and total constraints fell 11,269 -> 5,671, with source-flow build
  0.281 / 0.296 / 0.343 s versus the unbounded 0.718 / 0.750 / 0.765 s in the same script. With
  the synthetic loose bound `B = 2 * LB`, zero arcs were pruned and construction additionally paid
  the Dijkstra overhead (0.828 / 0.876 / 0.937 s) — loose bounds are valid but can prune nothing,
  exactly as the theory predicts.

This is a proof-safe solver/domain reduction, not a game rule. Correctness evidence: the
exhaustive cap-algebra test, bounded/unbounded projection tests, target-as-transit and custom
weight regressions, and the full production-versus-oracle suite all pass with the mechanism live.

## Exact incumbent objective cut

After the production decomposition has a feasible exact incumbent with scaled primary objective `B`, every later fixed-packing source-flow subproblem is solved with the additional exact constraint:

```text
scaled_F <= B
```

The inequality is deliberately non-strict. A room packing with `scaled_F == B` must remain in the search because it may improve later lexicographic criteria:

```text
Base Mass -> Elevator count -> Corridor count
```

If CP-SAT proves the bounded fixed model infeasible, that packing cannot match or improve the current incumbent primary objective. It may be either structurally infeasible or structurally feasible with true minimum `scaled_F > B`; the production decomposition does not need to distinguish those cases for global optimization.

This exclusion is proof-safe. If a packing cannot satisfy `scaled_F <= B`, it also cannot improve any later incumbent whose primary objective is smaller than or equal to `B`. Therefore these exclusions are valid contributors to a completed global proof.

The cut does not change the accepted objective, hard constraints, exact distances or proof definition. It only transfers already-known exact incumbent information from the room-packing master into subsequent exact fixed subproblems.

## Wall-clock budget semantics

`solver.time_limit_s` is one wall-clock budget for the complete planning request. The room-packing master passes only the remaining budget to each fixed-packing subproblem.

The fixed-packing deadline starts **before** hard-model and source-flow construction. Model construction therefore consumes the same remaining budget as CP-SAT search and exact evaluation; rebuilding a large model cannot silently extend the configured planning budget.

This timing rule is a correctness/accounting contract, not a performance heuristic. Timeout results remain best-known/unknown as appropriate and never create a false optimality proof.

## Interpreting results

Performance comparison must preserve correctness first.

A change is suspicious even when faster if it unexpectedly changes any of the following on a deterministic/proven comparison case:

- feasibility status;
- exact objective or accepted tie-break result;
- proof state;
- exact lower-bound semantics;
- Airlock connectivity or other hard constraints.

Wall-clock measurements are noisy. Compare them only on sufficiently similar hardware/software environments and preferably over repeated runs. The repository currently records raw runs rather than pretending that one timing sample is a statistically stable threshold.

`global_objective_optimum_proven=false` is not itself a solver failure. It means the configured search did not close the complete proof. For Stage-4 analysis, the useful questions are where the budget is spent, how the model grows, how quickly the incumbent improves and whether the complete proof closes under fixed budgets.

Model-size measurements are deterministic for a fixed room packing and solver formulation. Runtime measurements are not. This distinction is useful when deciding whether a proposed reduction attacks structural model growth or only happens to improve one timing sample.

## CI policy

Normal CI tests the benchmark **contract**, fixed-subproblem diagnostics, budget accounting, serialization and Markdown reporting but does not run the multi-minute representative suite. This prevents CI duration from becoming a hidden solver budget and avoids treating shared-runner timing noise as a performance regression.

Known-optimum correctness remains protected separately by the exhaustive Stage-3 reference-oracle tests.

The opt-in benchmark workflow is deliberately separate from normal CI. Benchmark artifacts are evidence for performance engineering, not pass/fail correctness gates.

## Example-plan review evidence

Relevant solver pull requests publish example-plan evidence through
`.github/workflows/example-layout.yml`. Changes to `src/**`, tests, the example
configuration, packaging helper, project dependencies or this document trigger
the dedicated workflow. It also runs on relevant pushes to `main` and by manual
dispatch. Its canonical input is `config/example-plan.json`, executed through
the production CLI:

```bash
python -m alters_base_planner.cli config/example-plan.json
```

The `example-plan-evidence` Actions artifact contains
`example-plan-<short-commit-sha>.zip`. Inside the ZIP:

```text
example-plan-result/
    input/example-plan.json
    output/layout.json
    output/layout.png       # if generated
    output/layout.svg       # if generated
    run-metadata.json
```

Metadata schema version 3 records the checked-out commit, Git ref, UTC timestamp,
Python/OR-Tools/planner versions, source configuration path, optimizer process
exit code, status, Base tier, exact/scaled objective and modified-Manhattan lower
bound, feasibility/proof flags, mass, infrastructure counts, search diagnostics,
fixed-subproblem model diagnostics and source-flow actual/full-domain totals and
maxima. Values are copied from the canonical result without recomputing solver
metrics; unavailable values are JSON `null`. The full layout remains separate.
On pull requests the commit identifies the checked-out Actions merge revision,
and the ref identifies the pull-request merge ref.

The workflow captures a nonzero optimizer exit code, packages available files,
and uploads with `if: always()` **before** the final acceptance gate. A timeout,
infeasible result or other optimizer failure therefore keeps diagnostic evidence
while failing the job. If no layout was written, input and metadata are still
packaged. Malformed JSON is preserved verbatim in the ZIP with a parse error in
metadata, and the helper fails clearly.

Acceptance requires a successful optimizer process, `status == FEASIBLE`,
nonempty JSON/PNG/SVG files, a nonempty module list and
`structural_feasible == true`. **FEASIBLE does not mean global optimum proven.**
A best-known feasible result with `global_objective_optimum_proven == false`
passes this smoke-quality case. F, mass, Elevator/Corridor counts and runtime
are review evidence, not numerical CI thresholds.

For local packaging, run from the repository root after the production CLI,
passing its actual exit code (for example, `0` after success):

```bash
python scripts/create_example_evidence.py --optimizer-exit-code 0
python scripts/create_example_evidence.py --verify
```

Use a fresh `--destination` for repeated packaging; existing evidence is never
overwritten. Production outputs must come from the current run (CI uses a clean
checkout). The helper also accepts the captured code through
`OPTIMIZER_EXIT_CODE`; if unavailable it records `null`, which fails acceptance.

The ZIP is ephemeral CI review evidence. Generated ZIP archives and layout
outputs are not committed or kept in Git history. Artifact review complements
but does not replace correctness tests, independent reference oracles and
mathematical proofs. One example run does not establish a performance improvement.

## Stage-4 optimization discipline

The benchmark and model-size instrumentation are now in place. Performance changes must remain mathematically exact and should be evaluated from measured evidence rather than timing anecdotes. Safe candidates include:

- mathematically equivalent candidate-domain reduction;
- stronger admissible lower bounds;
- additional pure label/topology symmetry breaking;
- indexed graph construction;
- proof-safe decomposition cuts such as the exact incumbent objective cut.

Any reduction or cut must continue to match the exhaustive known-optimum reference cases before it is allowed into the production correctness boundary. No benchmark improvement is sufficient justification for weakening hard constraints, changing the accepted objective or suppressing incomplete-search diagnostics.
