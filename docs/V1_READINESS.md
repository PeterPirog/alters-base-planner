# V1 readiness and Stage-4 closure

Audit date: 2026-09-15

Accepted solver baseline: `b00abc34beb62221b05d4a76137f0ac6b5bf71d5`

Release-candidate branch: `opencode/v1-release-candidate`

This is the finite architecture and release ledger for the first public release. It closes Stage 4;
it is not an invitation to continue speculative solver optimization.

## Architecture decision

`b00abc34beb62221b05d4a76137f0ac6b5bf71d5` is the accepted v1 solver baseline. It contains the
exact room-packing/fixed-objective decomposition, the exact hard infrastructure model, exact
source-aggregated weighted flow, exact condition-capacity buckets, endpoint and Dijkstra semantics,
one exact mixed-radix `F -> mass -> Elevator -> Corridor` fixed solve, the non-strict incumbent
primary cut, proof-safe incumbent distance-cap pruning, per-plan usage-weight overrides, and honest
fixed/global proof and limit semantics.

`3c07b13e06869efe0e3e487571be6239e2671812` is research evidence, not a production parent. Its
standalone exact master modified-Manhattan encoding is correct and avoids candidate-pair Boolean
products, but minimizing that objective made a Tier-I master solve exceed 30 seconds without an
optimality proof and severely degraded time-to-incumbent. The reference module is left on its public
research branch and is not included in v1.

## V1 scope

### V1 must have

- canonical Base Tier I-IV geometry;
- the SYSTEM/PLAYER/SOLVER authority model and validated count limits;
- exact hard feasibility, port, transit, Elevator and connectivity semantics;
- exact Dijkstra distance evaluation and the accepted weighted objective;
- exact fixed-packing optimization and honest global best-known/proven distinction;
- Base Mass and Organics journey reporting;
- auditable result JSON plus PNG and SVG;
- repository-root CLI and Streamlit workflows;
- version-controlled smoke, representative and known-optimum evidence;
- clean installation, tests, public documentation and release metadata.

### Post v1

- progression and game-state support (Stage 6);
- The Last Variable environment until exact geometry and rules are verified (Stage 7);
- exact master-LB production integration or other solver reformulations;
- new routing heuristics, restart policies, adaptive slicing, pruning or central-Elevator rules;
- hardware-calibrated timing thresholds beyond stable structural/proof diagnostics.

## Stage completion ledger

`Blocks v1` means blocks declaring/tagging the public release, not local Stage-4 closure.

| ID | Subsystem | State | Blocks v1 | Remaining work and acceptance criterion |
|---|---|---|---|---|
| A | Domain / Module model | DONE | No | Unified `ModuleSpec`, `ModuleInstance` and `ModulePlacement` authority model is tested. Maintain compatibility with the schema and catalogue. |
| B | Mandatory SYSTEM modules | DONE | No | Exactly one of every mandatory SYSTEM module is injected and cannot be configured as PLAYER input. |
| C | PLAYER counts and count limits | DONE | No | Integer validation and verified limits such as Recycler `<=1` and Rapidium Ark `<=5` are enforced and tested. |
| D | SOLVER Corridor/Elevator generation | DONE | No | Both are solver-owned, absent from input counts and audited in results. |
| E | Canonical Base I-IV geometry | DONE | No | Version-controlled masks, fixed cores, dimensions and provenance are verified by geometry tests. |
| F | Occupancy/no-overlap | DONE | No | Room and utility footprints share exact buildable-cell occupancy constraints. |
| G | Port semantics | DONE | No | Floor-relative normal ports, 1x1 sides and Radiation Repulsor top access are shared by model and evaluator; the top-access production regression is included in this release candidate. |
| H | Airlock-rooted connectivity | DONE | No | Every installed room and selected utility must be reachable from the Airlock. |
| I | Non-transit semantics | DONE | No | Radiation Repulsor and Rapidium Ark can terminate but cannot bridge paths; oracle regressions exist. |
| J | Elevator continuity | DONE | No | Vertical chains require every intermediate level and overlapping adjacent shafts. |
| K | Exact Dijkstra distance | DONE | No | Independent evaluator uses the accepted endpoint/intermediate/utility costs and cross-checks CP-SAT output. |
| L | Objective scaling | DONE | No | Rational weights become exact integer coefficients; signed-64-bit scalar bounds fail fast. |
| M | Exact fixed-packing optimization | DONE | No | Source-aggregated weighted flow and exact mixed-radix ordering match the exhaustive oracle. |
| N | Global decomposition | DONE | No | Master enumeration, no-goods, fixed solves, admissible exclusions and incumbent selection preserve exactness. |
| O | Lower bounds and pruning | DONE | No | Existing modified-Manhattan bound, strict master pruning, incumbent cut and distance caps are proof-safe. The rejected master-LB objective is not required. |
| P | Optimum-proof semantics | DONE | No | `FEASIBLE` is separate from fixed/global proof; time and attempt limits suppress false global optimality. |
| Q | Base Mass | DONE | No | Room, utility and total mass plus a per-module breakdown are serialized. |
| R | Organics journey feasibility | DONE | No | Structural and journey feasibility remain separate; requirement, capacity and margin are reported. |
| S | Auditable JSON | DONE | No | Result schema v4 contains placements, ports, exact objective/LB, diagnostics, mass and proof fields; all public docs now name v4. |
| T | PNG | DONE | No | FEASIBLE CLI/UI results render a non-empty PNG with 2:1 cell aspect. |
| U | SVG | DONE | No | FEASIBLE CLI/UI results render an auditable SVG with the same geometry semantics. |
| V | CLI | DONE | No | Module and installed entry point return 0 with JSON/PNG/SVG for FEASIBLE and 2 with JSON only for non-feasible results. |
| W | Streamlit UI | DONE | No | Form/JSON modes, Tier I-IV, 60 s default, locked SYSTEM, bounded PLAYER, AUTO utilities, weights, persistence/invalidation and downloads pass AppTest and HTTP smoke. |
| X | Benchmark suite | DONE | No | Schema v7 records first-feasible time and all required diagnostics; smoke and representative suites each cover Tier I-IV. Acceptance is semantic, not an arbitrary Tier III/IV proof deadline. |
| Y | Known-optimum regression suite | DONE | No | Fixed/global oracles cover the accepted tuple, bounds, transit, zero weights and custom weights; the missing top-access flow regression was added. |
| Z | CI | PARTIAL | Yes | PR #27 passed Python 3.11-3.13 CI, but the three post-#27 production commits and closure commit have no PR checks. Acceptance: normal CI and evidence workflows pass on every SHA that will be merged; no workflow weakening or waiver by default. |
| AA | Installation/package UX | DONE | No | Python `>=3.11`, dependencies and both console scripts are declared; an isolated Python 3.12 editable install, `pip check`, console invocation and tests pass. |
| AB | Public README | DONE | No | Clone/install/CLI/UI/test instructions match the product and result schema v4. |
| AC | Release/versioning | PARTIAL | Yes | Package remains `0.1.0`; no changelog, software-license file or tag procedure has been executed. Acceptance: owner chooses a software license, adds its file/metadata, records v1 changes, sets `1.0.0`, passes gates, creates an annotated `v1.0.0` tag from the reviewed main SHA, and publishes release notes. |
| AD | Progression/game-state | POST_V1 | No | Add explicit act/game-state, unlock and existing/non-removable state only from a separately accepted specification. |
| AE | The Last Variable | POST_V1 | No | Data-blocked. Acceptance for a future environment: verified DLC geometry, module catalogue and topology rules; never reuse mobile-Base masks as an approximation. |

## Finite v1 blockers

1. Review and merge the existing stack in order; main currently stops before PR #25.
2. Put the three accepted post-#27 performance commits through one cohesive PR and normal CI.
3. Put this closure branch through normal CI after its parent stack is accepted.
4. Obtain the repository owner's software-license decision and add the selected license metadata.
5. Prepare the `1.0.0` changelog/release notes, update the package version, rerun all gates, then tag the reviewed main SHA.

The previously observed Actions billing annotation is not a current blocker: PR #27 later completed
both CI and evidence workflows successfully. Any recurrence is an `EXTERNAL_RELEASE_BLOCKER` and
must not be hidden by editing workflow YAML.

## Benchmark acceptance matrix

The authoritative definitions are `SMOKE_CASES` and `REPRESENTATIVE_CASES` in
`src/alters_base_planner/benchmark.py`. Benchmark schema v7 records status, budgets, wall/search and
first-feasible time, exact/scaled objective and modified-Manhattan LB, mass, utility counts,
packings/candidates/subproblems, source-flow and CP-SAT sizes, proof/exhaustion/limit flags, build
phases and solver environment.

### Smoke

| Case | Tier | Budget | Acceptance |
|---|---:|---:|---|
| `tier1-baseline-smoke` | I | 1 s / 1 packing | No crash/model-invalid; honest status and complete diagnostics. |
| `tier2-baseline-smoke` | II | 1 s / 1 packing | No crash/model-invalid; honest status and complete diagnostics. |
| `tier3-baseline-smoke` | III | 1 s / 1 packing | No crash/model-invalid; honest status and complete diagnostics. |
| `tier4-baseline-smoke` | IV | 1 s / 1 packing | No crash/model-invalid; honest status and complete diagnostics. |

Local closure run on Python 3.12.9 / OR-Tools 9.15.6755 returned honest `TIME_LIMIT` for all four
cases in 0.890-1.032 s, with no layout or false proof.

### Representative

Local closure evidence is intentionally uncommitted under `TEMP/`. A dash means no incumbent was
found, so objective/LB/mass/infrastructure are correctly absent rather than fabricated.

| Case | Tier | Status | Budget | First feasible s | Exact F | Scaled F / LB | Mass | E/C | Packings | Connected | Subproblems | Max source-flow vars | Max CP-SAT vars/constraints | Global proof | Exhausted | Limit |
|---|---:|---|---:|---:|---:|---|---:|---|---:|---:|---:|---:|---|---|---|---|
| `tier1-workshop` | I | FEASIBLE | 15 s / 30 | 5.296 | 38.1325 | 15253 / 15253 | 66 | 11/0 | 10 | 4 | 5 | 4248 | 5329/3505 | no | no | yes |
| `tier2-balanced` | II | TIME_LIMIT | 30 s / 60 | - | - | - | - | - | 1 | 0 | 1 | 8100 | 9631/5571 | no | no | yes |
| `tier3-production` | III | TIME_LIMIT | 45 s / 100 | - | - | - | - | - | 8 | 0 | 8 | 14953 | 16960/8642 | no | no | yes |
| `tier4-dense` | IV | TIME_LIMIT | 60 s / 150 | - | - | - | - | - | 7 | 0 | 6 | 11344 | 13974/8747 | no | no | yes |

Release acceptance does not require a short-budget Tier III/IV global proof. Every case must avoid
crash and `MODEL_INVALID`; every FEASIBLE result must pass the independent exact evaluator,
`scaled_modified_manhattan_lower_bound <= scaled_objective_value`, deterministic structural
invariants and usable evidence serialization. Status and proof fields must describe limits honestly.

## Known-optimum inventory

For fixed-packing cases, the mass tie-break varies only by solver utility mass; total room mass is
constant. The table reports `total mass (utility mass)` where a concrete feasible network exists.

| Case | Expected F | Expected mass | E | C | Proof method |
|---|---:|---:|---:|---:|---|
| Direct adjacency | 0 (scaled 0/10) | 12 (0) | 0 | 0 | Production fixed flow equals exhaustive fixed-network oracle. |
| Corridor path | 1.8 (scaled 18/10) | 16 (4) | 0 | 2 | Exhaustive fixed-network oracle and Dijkstra. |
| Elevator chain | 1.8 (scaled 18/10) | 16 (4) | 2 | 0 | Exhaustive fixed-network oracle and continuity checks. |
| Transit-room crossing | 1.4 | 16 (0) | 0 | 0 | Exact source flow and Dijkstra charge Workshop width only for through-flow. |
| Non-transit module | INFEASIBLE | - | - | - | Exhaustive hard model and production solver reject Rapidium Ark bridging. |
| Zero-weight connected module | 0 | 6 (0) | 0 | 0 | Recycler remains in exact Airlock-rooted hard connectivity. |
| Equal-F secondary tie | 0.9 (scaled 9/10) | 14 (2) | 0 | 1 | Physical alternatives plus exhaustive mixed-radix tuple enumeration. |
| Custom weights | 0.70 (scaled 70/100) | 24 (2) | 0 | 1 | Production tuple equals exhaustive oracle with three unequal weights. |
| Bounded incumbent equality | 0.9 (bound 9/10) | 14 (2) | 0 | 1 | Non-strict exact cut retains equality and proves OPTIMAL. |
| Too-tight incumbent bound | `OBJECTIVE_BOUND_INFEASIBLE` at 8/10 | - | - | - | Relaxed exact lower bound is 9/10 before CP-SAT. |
| Global tiny packing optimum | 0 (scaled 0/10) | 12 (0) | 0 | 0 | Production decomposition equals independently exhaustive global oracle and exhausts search. |
| Radiation Repulsor top access | 0.5 (scaled 1/2) | 22 (2) | 0 | 1 | Production source flow equals exhaustive oracle with positive custom endpoint weight. |

## Public GitHub state

State recorded during the 2026-09-15 audit. No PR was modified or merged.

| Ref | Base SHA | Head SHA | Decision | CI/checks | Mergeability / downstream |
|---|---|---|---|---|---|
| `main` | - | `e634360c4ef5bb1b93a8ff941f5733587f952b1e` | Current public production | Latest main CI/evidence success | Contains work through PR #24. |
| PR #25 | `e634360c` | `0328487c` | Production-accepted, pending merge | Historical billing failure; rerun required | MERGEABLE / UNSTABLE; draft. |
| PR #26 | `0328487c` | `8985b5e7` | Production-accepted, pending merge | Historical billing failure; rerun required | MERGEABLE / UNSTABLE. |
| PR #27 | `8985b5e7` | `58cfaaab` | Production-accepted, pending merge | CI and evidence SUCCESS | MERGEABLE / CLEAN; draft. |
| source-flow build branch | `58cfaaab` | `656870c1` | Production-accepted | No PR checks | Fully contained downstream in `b00abc`. |
| condition-bucket branch | `656870c1` | `43ffc936` | Production-accepted | No PR checks | Fully contained downstream in `b00abc`. |
| distance-cap branch | `43ffc936` | `b00abc34` | Production-accepted v1 baseline | No PR checks | Contains all accepted post-#27 work. |
| master-LB branch | `b00abc34` | `3c07b13e` | Experimental, rejected for production | No PR checks | Preserve as research evidence; do not merge into v1. |

## Integration plan

Required sequence:

```text
main e634360c
-> PR #25 exact mixed-radix fixed objective
-> PR #26 Streamlit form and usage-weight overrides
-> PR #27 source-aggregated exact weighted flow
-> one cohesive Stage-4 exact-flow performance PR containing:
   656870c1 source-flow construction overhead
   43ffc936 condition-capacity buckets
   b00abc34 incumbent distance-cap pruning
-> opencode/v1-release-candidate closure/release-hardening commit(s)
-> release metadata commit after owner license decision and green CI
```

Use one performance PR against the PR #27 head because the three commits are tightly related,
semantics-preserving fixed-flow implementation work. Keep closure/release hardening separate so it
can be reviewed as release policy and product acceptance. Do not merge while required checks are
not executable or green. Do not merge/cherry-pick `3c07b13`.

## Release gates

### Correctness

- all fixed/global oracle tests pass;
- every returned FEASIBLE layout passes the independent exact evaluator;
- `F_LB <= F_exact` and exact tuple ordering are enforced;
- no time/attempt-limited run claims false global optimality.

### Quality

- `python -m pip check`, `python -m ruff check .`, `python -m pytest -q` and
  `git diff --check` all pass on the release SHA.

### Functional

- CLI module and installed entry point pass FEASIBLE and TIME_LIMIT acceptance;
- Streamlit AppTest and one headless/manual HTTP smoke pass;
- Tier I-IV smoke and representative cases satisfy semantic acceptance;
- JSON/PNG/SVG and Base Mass/Organics output are valid.

### Performance

- smoke completes for all tiers;
- representative Tier I-IV emits complete schema-v7 diagnostics without crash/model-invalid;
- best-known/proven and timeout states remain honest;
- no Tier III/IV short-budget global proof requirement is invented.

### Public repository

- clean clone/install instructions match supported Python versions and entry points;
- current tree contains no secrets, developer-machine paths or committed TEMP artifacts;
- source-of-truth documents agree with result and benchmark schema versions;
- the owner-selected software license is present before release.

### CI

- Python 3.11, 3.12 and 3.13 jobs plus evidence workflow pass on every integrated SHA;
- billing/account inability to start jobs is an external release blocker, never a reason to weaken CI.

### Versioning and release

1. Complete architecture review and merge only the accepted stack in order.
2. Add the owner-selected license, `CHANGELOG.md`/release notes and package version `1.0.0`.
3. Run all local gates, smoke/representative acceptance and normal GitHub checks on the final SHA.
4. Create annotated tag `v1.0.0` on reviewed `main`; do not tag the release-candidate branch.
5. Publish GitHub release notes with exact solver semantics, known limits and benchmark environment.

V1 is not released until every blocking ledger entry and every release gate is DONE.
