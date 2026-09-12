# Benchmark methodology

Status: **Stage 4 in progress**

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

`tier1-baseline-smoke` is a short production-path check. It is useful for verifying that benchmark collection itself works. Its runtime is not a regression threshold.

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

Benchmark schema version 4 records the end-to-end search/proof metrics:

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

`incumbent_bound_pruned_count` counts packings for which the exact fixed pair-flow model, constrained by `scaled_F <= incumbent_scaled_F`, is proven infeasible. Such a packing cannot match or improve the incumbent primary objective. It is intentionally tracked separately from modified-Manhattan pruning because it is a stronger exact subproblem proof, not a heuristic or lower-bound estimate.

Stage-4 fixed-subproblem instrumentation additionally records:

```text
fixed_subproblem_count
max_fixed_graph_nodes
max_fixed_graph_arcs
max_fixed_objective_pairs
max_fixed_pair_flow_variables
max_fixed_pair_flow_full_variables
total_fixed_pair_flow_variables
total_fixed_pair_flow_full_variables
 max_fixed_cp_sat_variables
max_fixed_cp_sat_constraints
fixed_lexicographic_weight_f
fixed_lexicographic_weight_mass
fixed_lexicographic_weight_elevator
fixed_lexicographic_weight_corridor
fixed_lexicographic_corridor_bound
fixed_lexicographic_elevator_bound
fixed_lexicographic_mass_bound
fixed_lexicographic_objective_value
fixed_model_build_time_s
fixed_cp_sat_solve_time_s
fixed_subproblem_time_s
```

The `max_*` values are maxima across all exact fixed-packing subproblems attempted during one planning run. The three timing values are totals across those subproblems. CP-SAT variable/constraint counts describe the single lexicographic-scalarized model.

The `fixed_lexicographic_*` fields record the exact mixed-radix dominance weights, the valid finite bounds they were derived from (Corridor/Elevator anchor counts and maximum utility mass), and the maximum scalarized objective value. Because these bounds differ per room packing, the reported values are conservative maxima across the subproblems.

`fixed_model_build_time_s` covers construction of the fixed hard model, conditional travel graph and pair-flow objective. `fixed_cp_sat_solve_time_s` measures time spent inside the single CP-SAT lexicographic-scalarized solve call. `fixed_subproblem_time_s` covers the complete fixed-objective calls, including model construction, validation, the CP-SAT solve and exact evaluator work.

The report also records the Python implementation/version, operating-system platform, OR-Tools version and planner version.

## Pair-flow variable-domain reduction

The exact fixed-packing objective originally created one flow Boolean for every combination of positive-weight objective pair and directed graph arc. The current formulation first restricts each pair to the arcs that can lie on a source-to-target path in the unconditional directed supergraph. Infrastructure-selection conditions are ignored for this reachability analysis, so the supergraph is a relaxation of every realizable network. An arc that cannot belong to an endpoint path even in this relaxation cannot belong to any realizable endpoint path and can be removed without changing feasibility or the optimum.

Endpoint ports are also treated as terminals, and singleton endpoint choices are represented by constants rather than auxiliary Boolean variables. These are exact presolve/domain reductions, not heuristic routing rules.

The benchmark records both the actual pair-flow Boolean count after pair-specific domain reduction and the corresponding full-domain count from the previous formulation:

```text
max_fixed_pair_flow_variables
max_fixed_pair_flow_full_variables
total_fixed_pair_flow_variables
total_fixed_pair_flow_full_variables
```

The two `total_*` fields are sums over the same fixed-packing subproblems and therefore support a meaningful aggregate structural-reduction ratio:

```text
reduction = 1 - total_actual / total_full
```

The benchmark report must use these totals for the reduction percentage. A ratio derived from independent maxima would be potentially misleading because the maxima need not come from the same subproblem.

These counts are structural diagnostics. A lower flow-variable count is evidence that the formulation is smaller; it is not by itself evidence that end-to-end runtime improved. Runtime claims still require representative benchmark measurements on comparable environments.

## Exact incumbent objective cut

After the production decomposition has a feasible exact incumbent with scaled primary objective `B`, every later fixed-packing pair-flow subproblem is solved with the additional exact constraint:

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

The fixed-packing deadline starts **before** hard-model and pair-flow construction. Model construction therefore consumes the same remaining budget as CP-SAT search and exact evaluation; rebuilding a large model cannot silently extend the configured planning budget.

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

Metadata schema version 1 records the checked-out commit, Git ref, UTC timestamp,
Python/OR-Tools/planner versions, source configuration path, optimizer process
exit code, status, Base tier, exact/scaled objective and modified-Manhattan lower
bound, feasibility/proof flags, mass, infrastructure counts, search diagnostics,
fixed-subproblem model diagnostics and pair-flow actual/full-domain totals and
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
