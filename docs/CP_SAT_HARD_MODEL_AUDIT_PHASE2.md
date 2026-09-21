# CP-SAT Hard-Model Formulation Audit — Phase 2: Compact Placement / Occupancy Formulation

Status: **COMPLETE — B1_CORRECT_BUT_NOT_BENEFICIAL**

Research branch: `opencode/cp-sat-formulation-phase2-compact-placement`
Research base SHA (post-PR-#32 production main): `6987b8d3ac926be89f2dbf8b1a1bccc6c39b4fa9`

This document distinguishes strictly between **FACT**, **MEASUREMENT**, **MODELLING
DECISION** and **RECOMMENDATION**. Production semantics are unchanged on this branch.

---

## 1. Research question

**FACT (formulation A, production):** one Boolean placement literal per legal candidate;
`add_exactly_one` per room instance; cell-expanded `add_at_most_one` occupancy per Base cell;
candidate-specific resolved port nodes; conditional graph edges; rooted integer flow
(H6/H7/H8/H9/H10/H11 as audited in Phase 1 and repaired by PR #31).

**QUESTION:** can placement/occupancy be represented more compactly with native CP-SAT
position variables / intervals / `NoOverlap2D` while preserving *exactly* the same physical
feasible set — and does that reduce model size / build cost where Formulation A becomes
extremely large (Tier III/IV)?

Scope isolation: Phase 2 changes only the placement/occupancy representation. Rooted
connectivity semantics are shared verbatim with Formulation A.

---

## 2. Formulation A (reference)

- `placement[o]` ∈ {0,1} per candidate; `add_exactly_one` per instance (H1);
- occupancy: per Base cell, `add_at_most_one` over all room candidates occupying the cell
  plus `utility_active[anchor]` for anchors covering the cell (H3);
- port nodes active iff their candidate literal is selected; conditional edges; single
  rooted flow; explicit H6 Airlock external-connection constraint (PR #31).

## 3. Formulation B1 (this experiment)

- `choice_i` IntVar over candidate indices per instance;
- exact `add_element(choice_i, candidate_xs, x_i)` / `(candidate_ys, y_i)` position
  channeling;
- mandatory interval per room rectangle `[x_i, x_i + w] × [y_i, y_i + h]`;
- optional fixed-size interval per 2x1 utility anchor, present iff `utility_active`;
- ONE native `add_no_overlap_2d` covering rooms + utilities;
- exact Boolean channel literals `selected_option[o] <=> choice_i == index(o)`
  (both implications mandatory) reused by the **same** shared connectivity layer
  (`_build_connectivity_layer`) as Formulation A.

### Exactness argument

- **Candidate-domain mask argument (H2/H5):** `choice_i` only maps to prevalidated
  candidate positions whose complete footprint is inside the buildable mask; no bounding-box
  approximation, no idealized rectangular Base.
- **Occupancy exactness (H3):** rectangle non-overlap between selected room/utility
  rectangles is exactly the pairwise cell-disjointness feasible set of Formulation A on the
  same candidate domain.
- **Connectivity:** byte-identical semantics via the shared extracted layer
  `_build_connectivity_layer` (pure code motion from Formulation A; both call it).

Executable evidence: `tests/test_compact_hard_formulation.py`.

---

## 4. A-vs-B physical feasible-set equality (FACT)

Method: for every tiny family, enumerate the complete physical-layout domain (every
combination of one candidate per instance × every utility anchor state
NONE/CORRIDOR/ELEVATOR), force each layout into both formulations, solve exactly, and
compare canonical physical-layout sets (installed modules + selected utilities only).

| Family | Physical layouts | A feasible | B feasible | A-only | B-only |
|---|---:|---:|---:|---:|---:|
| F1 direct room adjacency | 1 | 1 | 1 | 0 | 0 |
| F2 disconnected room | 1 | 0 | 0 | 0 | 0 |
| F3 isolated Airlock (H6) | 1 | 0 | 0 | 0 | 0 |
| F4 multiple Airlock placements | 2 | 1 | 1 | 0 | 0 |
| F5 selected Corridor attachment | 3 | 2 | 2 | 0 | 0 |
| F7 transit middle room | 1 | 1 | 1 | 0 | 0 |
| F8 non-transit terminal | 1 | 1 | 1 | 0 | 0 |
| F9 non-transit bridge (H8) | 1 | 0 | 0 | 0 | 0 |
| F10 stacked Elevator vertical | 9 | 1 | 1 | 0 | 0 |
| F12 room-utility overlap | 6 | 2 | 2 | 0 | 0 |
| F13 utility-utility overlap | 9 | 2 | 2 | 0 | 0 |
| F14 irregular/blocked geometry | 18 | 2 | 2 | 0 | 0 |
| F15 alternative adjacency | 2 | 1 | 1 | 0 | 0 |
| **Total** | **53** | **11** | **11** | **0** | **0** |

Normative spot-checks (independent of A): isolated Airlock INFEASIBLE (H6);
non-transit bridge INFEASIBLE (H8); non-transit terminal FEASIBLE; stacked Elevator
vertical path feasible exactly for the both-Elevator anchor state; blocked-geometry
candidate/anchor exclusion verified.

Channel exactness: `selected_option[o] <=> choice_i == index(o)` verified in both
directions on a solved model (`test_channel_literals_are_exact_in_compact_formulation`).

**FACT:** `A_feasible_set == B_feasible_set` on every family; `A_only` and `B_only` are
empty. H6, H8, Elevator-continuity and blocked-geometry behaviors are identical.

---

## 5. Model-size and build-time metrics (MEASUREMENT)

Method: candidate/domain generation timed separately; one warm-up build + 3 measured builds
(2 for Tier III/IV); median/min/max reported; identical inputs per formulation;
`model.validate()` always passes on both formulations.

### Tiny (synthetic 12x1, airlock + workshop, 1 anchor)

| Metric | A | B1 | Δ |
|---|---:|---:|---:|
| variables | 18 | 24 | +6 |
| constraints | 31 | 44 | +13 |
| proto size (str) | 5336 | 8235 | +54% |
| conditional edges | 4 | 4 | 0 |
| build median (s) | 0.001 | 0.001 | ~0 |

### Tier I (8 SYSTEM rooms, 1434 candidates, 214 anchors)

| Metric | A | B1 | Δ |
|---|---:|---:|---:|
| variables | 28,756 | 28,780 | +0.08% |
| constraints | 53,423 | 56,516 | +5.8% |
| proto size (str) | 11,113,321 | 11,574,872 | +4.2% |
| at_most_one | 442 | 214 | -52% |
| interval | 0 | 444 | +444 |
| element | 0 | 16 | +16 |
| no_overlap_2d | 0 | 1 | +1 |
| linear | 52,966 | 55,834 | +2,868 |
| conditional edges | 10,884 | 10,884 | 0 |
| build median (s) | 1.244 | 1.211 | -2.6% |
| validate median (s) | 0.045 | 0.043 | -3.1% |

### Tier II (18 rooms, 4,566 candidates, 296 anchors)

| Metric | A | B1 | Δ |
|---|---:|---:|---:|
| variables | 160,024 | 160,078 | +0.03% |
| constraints | 308,201 | 317,668 | +3.1% |
| proto size (str) | 64,312,004 | 65,645,016 | +2.1% |
| at_most_one | 608 | 296 | -51% |
| interval | 0 | 628 | — |
| element | 0 | 36 | — |
| linear | 307,558 | 316,690 | +9,132 |
| conditional edges | 69,241 | 69,241 | 0 |
| build median (s) | 8.583 | 10.778 | +25.6% |
| validate median (s) | 0.267 | 0.277 | +3.7% |

### Tier III (21 instances, 7,302 candidates, 398 anchors)

| Metric | A | B1 | Δ |
|---|---:|---:|---:|
| variables | 299,722 | 299,785 | +0.02% |
| constraints | 581,219 | 596,267 | +2.6% |
| proto size (str) | 121,594,641 | 123,676,196 | +1.7% |
| at_most_one | 814 | 398 | -51% |
| linear | 580,364 | 594,968 | +14,604 |
| conditional edges | 132,452 | 132,452 | 0 |
| build median (s) | 20.025 | 17.055 | -14.8% |
| validate median (s) | 0.523 | 0.489 | -6.5% |

### Tier IV (25 instances, 11,096 candidates, 508 anchors)

| Metric | A | B1 | Δ |
|---|---:|---:|---:|
| variables | 534,344 | 534,419 | +0.01% |
| constraints | 1,043,533 | 1,066,289 | +2.2% |
| proto size (str) | 218,800,700 | 221,737,664 | +1.3% |
| at_most_one | 1,036 | 508 | -51% |
| linear | 1,042,448 | 1,064,640 | +22,192 |
| conditional edges | 240,539 | 240,539 | 0 |
| build median (s) | 32.547 | 38.824 | +19.3% |
| validate median (s) | 0.825 | 0.875 | +6.1% |

### Structural solve screen (research budgets; same parameters for A and B)

| Case | Budget | A status | A (s) | B1 status | B1 (s) |
|---|---:|---|---:|---|---:|
| tiny | 2 s | OPTIMAL | 0.021 | OPTIMAL | 0.014 |
| Tier I | 10 s | UNKNOWN | 10.1 | UNKNOWN | 10.2 |
| Tier II | 15 s | UNKNOWN | 15.0 | UNKNOWN | 14.9 |
| Tier III | 20 s | UNKNOWN | 17.9 | UNKNOWN | 18.8 |
| Tier IV | 20 s | UNKNOWN | 21.7 | UNKNOWN | 23.6 |

The joint rooms+infrastructure satisfiability screen times out at every tier for both
formulations — consistent with production decomposing rooms first (room-packing master) and
solving fixed-packing infrastructure subproblems. The screen is diagnostic only; it is not a
release-acceptance claim.

---

## 6. Interpretation (MEASUREMENT → FACT)

1. **The cell-expanded occupancy representation was never the explosion.** In Formulation A
   the cell-expanded `at_most_one` layer is only ~0.1% of all constraints at every tier
   (Tier II: 608 of 308,201; Tier IV: 1,036 of 1,043,533). Replacing it with one
   `NoOverlap2D` removes ~half the `at_most_one` constraints — a saving of a few hundred
   constraints out of a million.

2. **Channeling overhead cancels the occupancy saving.** Because connectivity is
   candidate-specific, B1 must keep one Boolean channel literal per candidate
   (`selected_option[o] <=> choice_i == index(o)`; both implications mandatory = 2 enforced
   linear constraints per candidate). At Tier IV this adds ~22,000 linear constraints,
   while the occupancy replacement saves only ~500 `at_most_one` constraints. Net effect:
   +2.2% constraints, +0.01% variables, +1.3% proto size.

3. **Build times are statistically unchanged.** Tier medians differ by -15% to +25% across
   tiers with overlapping min/max ranges — no material, consistent improvement.

4. **Variables barely move** because the candidate Booleans remain for connectivity;
   `choice_i`/`x_i`/`y_i`/intervals add a negligible amount (3 IntVars per instance + 2
   intervals per room + 2 optional intervals per anchor).

5. **The real explosion is the conditional-edge/flow layer.** `linear` constraints dominate
   (98-99% of the model): each conditional graph edge contributes
   `flow <= max_flow * condition` per direction per condition, per source-commodity in the
   objective layer, plus node balance rows and H6 edge-activation equivalences. Tier IV has
   240,539 conditional edges and 2,096 candidate port nodes; the edge-conditioning linear
   constraints, not occupancy, grow super-linearly with tier size.

---

## 7. Modelling decisions (MODELLING DECISION)

- B1 is **not** selected for production. Production keeps Formulation A unchanged
  (`build_hard_constraint_layer`); only a strict code-motion extraction of the shared
  connectivity layer was performed and proven behavior-preserving (full focused + integrated
  + compact equivalence suites green).
- No symmetry breaking was added (per plan), to keep the A-vs-B experiment isolated.

## 8. Recommendation (RECOMMENDATION)

Per the pre-registered decision rule: **B1_CORRECT_BUT_NOT_BENEFICIAL**.

- Compact placement/occupancy does not address the actual scaling bottleneck.
- The next formulation experiment should attack the **candidate-specific conditional graph
  representation** (port nodes and per-edge conditioning) and/or the **integer rooted flow**,
  e.g.:
  - shared port-boundary graph nodes across candidates of the same instance (channel
    candidate ports to boundary positions instead of enumerating per-candidate nodes);
  - condition-capacity bucketing for hard-layer edge conditioning (the Stage-4
    source-flow bucket trick applied to H5/H6/H7 edge conditioning);
  - reducing per-edge directional flow variables.
- Occupancy via `NoOverlap2D` may be revisited only if a later connectivity redesign also
  removes the candidate Booleans (then the channeling overhead disappears and the
  occupancy/position representation becomes relevant again).

---

## 9. Provenance

- Phase-2 research branch: `opencode/cp-sat-formulation-phase2-compact-placement`
- Base: `6987b8d3ac926be89f2dbf8b1a1bccc6c39b4fa9` (production main after PR #31 + PR #32)
- New code: `src/alters_base_planner/compact_hard_constraints.py` (experimental),
  `tests/test_compact_hard_formulation.py`, `scripts/benchmark_hard_formulations.py`
- Refactor: `src/alters_base_planner/hard_constraints.py` — extraction of
  `_build_connectivity_layer` (pure code motion; both formulations share identical
  connectivity semantics)
- Production integration: NONE. No PR from this branch; not merged.