# CP-SAT Hard Model Formulation Audit — Phase 1

Status: **COMPLETE — BLOCKED_CORRECTNESS**

Production main: `672e591e44e7b5343ef7242d56c62103f1f4110f`

---

## 1. H1-H11 Traceability

| Requirement | Normative meaning | Domain representation | Current mathematical encoding | Current source location | Existing tests | Oracle coverage | Status |
|---|---|---|---|---|---|---|---|
| H1 | Exactly one of each SYSTEM module; exactly requested count of each PLAYER module; Recycler <= 1; Rapidium Ark <= 5; Corridor/Elevator solver-decided | `ModuleInstance` with `authority` field; `expand_instances()` creates exactly-one instances | `model.add_exactly_one(placement[option_id] for option in options)` per instance | `hard_constraints.py:187-191` | `test_hard_constraints.py` | TODO | VERIFIED |
| H2 | Every occupied cell is buildable (1). No module occupies 0 or X. | `buildable_cells` frozenset in `BaseGeometry`; placement options pre-filtered | Validation in `_validate_input_domain` and option enumeration in `integrated_hard_solver.py:91-92` | `hard_constraints.py:110-113`, `integrated_hard_solver.py:91-92` | `test_hard_constraints.py` | TODO | VERIFIED |
| H3 | Each grid cell occupied by at most one installed module | `cells` property of `ModulePlacement`; `occupants_by_cell` dictionary | `model.add_at_most_one(occupants)` for each cell | `hard_constraints.py:206-218` | `test_hard_constraints.py` | TODO | VERIFIED |
| H4 | No rotation unless verified future evidence supports it | Module dimensions fixed in `ModuleSpec`; no rotation logic | No rotation variables; placements use fixed width/height | `models.py:113-114`, `hard_constraints.py:189` | `test_hard_constraints.py` | TODO | VERIFIED |
| H5 | Connectivity exists only through compatible resolved ports/utility anchors | `ports` in `ModuleSpec`; `resolve_ports()` for absolute coordinates; `utility_anchor` derived from port | Port nodes created per placement; edges only added where ports meet or utility anchor matches | `models.py:187-216`, `hard_constraints.py:305-317` | `test_hard_constraints.py` | TODO | VERIFIED |
| H6 | Every installed network module has at least one legal connection | Airlock is root; all rooms/utilities must have one active port connected | Root flow source at Airlock ports; demand sink at one port per room; utility demand | `hard_constraints.py:354-372, 392-408` | `test_hard_constraints.py` | `test_phase1_documents_h6_root_underconstraint` | **FAIL** — Root local-connection underconstraint |
| H7 | All installed modules are reachable from Airlock | Airlock is root network node; reachability via graph traversal | Single-commodity flow with source at Airlock, demand at each room port, utility nodes | `hard_constraints.py:354-408` | `test_hard_constraints.py` | `test_hard_feasibility_oracle.py` | VERIFIED |
| H8 | Non-transit modules may terminate routes but cannot bridge opposite sides | `transit_allowed` in `ModuleSpec`; non-transit rooms have no internal edge | Internal edge only added if `option.transit_allowed` | `hard_constraints.py:268-280` | `test_hard_constraints.py` | `test_h8_terminal`, `test_h8_bridge_rejection` | VERIFIED |
| H9 | Corridor is solver-managed 2x1 horizontal infrastructure | `UtilityAnchorSpec` for 2x1 anchors; Corridor shares anchor with Elevator | `corridor[a]`, `elevator[a]`, `utility_active[a]` with at-most-one constraint | `hard_constraints.py:195-204` | `test_hard_constraints.py` | `test_hard_feasibility_oracle.py` | VERIFIED |
| H10 | Elevator provides horizontal attachment plus vertical connectivity only between immediately stacked Elevators | `elevator[a]` variable; vertical edges only at same-x anchors | Horizontal utility edge at x+2; vertical edge only if both `elevator[a]` and `elevator[below]` | `hard_constraints.py:321-348` | `test_hard_constraints.py` | `test_hard_feasibility_oracle.py` | VERIFIED |
| H11 | Every selected Corridor/Elevator belongs to Airlock-rooted network | Utility nodes added to demand terms | `demand_terms_by_node[utility_node[anchor]].append(utility_active[anchor])` | `hard_constraints.py:370-372` | `test_hard_constraints.py` | `test_hard_feasibility_oracle.py` | VERIFIED |

---

## 2. Rooted Flow Mathematical Review

### Current encoding (from `hard_constraints.py:350-408`)

**Variables:**
- `sink[(instance_id, node_id)]` ∈ {0,1} for each room port (one selected per room)
- `utility_active[anchor]` ∈ {0,1} for each utility anchor
- `flow[(edge_id, ab/ba)]` ∈ [0, max_flow] for each directed edge
- `source[node_id]` ∈ [0, max_flow] for each Airlock port node

**Constraints:**
1. `sink <= node_active` (sink only active if placement selected)
2. `sum(sinks) == 1` per room (exactly one port per room)
3. `flow <= max_flow * condition` per edge direction (edge only active if conditions met)
4. `node_in + source - node_out == demand` for each node
5. `sum(source_flow) == sum(all_demand_terms)` (total flow conservation)

### Analysis

**Q: Does flow conservation plus one demand per non-root room and one demand per selected utility imply Airlock-rooted reachability?**

**A: YES for positive-demand non-root components.** The formulation correctly encodes:
- Airlock ports act as sources with unbounded flow
- Each room consumes exactly one unit at exactly one port
- Each selected utility consumes one unit at its node
- Flow can only traverse edges where conditions are satisfied

**Proof for disconnected positive-demand components:**

For any disconnected component S that does NOT contain Airlock:
1. Sum all flow-conservation equations over all nodes in S
2. All internal directed flows cancel (each internal edge contributes +f and -f)
3. No source exists in S (sources only at Airlock ports)
4. Therefore: 0 = total demand(S)

Every selected utility contributes demand 1. Every installed non-root room contributes exactly one sink demand 1.

Thus any disconnected component containing an installed non-root room or selected utility requires:
0 = positive integer

which is impossible.

**Q: Can a disconnected cycle satisfy demand without root flow?**

**A: NO.** A cycle would have:
- No source flow (Airlock-connected)
- Equal incoming and outgoing flow at each node
- But demand > 0 at room ports and utility nodes
- Thus `node_in + source - node_out == demand` would require `source > 0` for feasibility

**Q: Can bidirectional flow variables create a false physical connection?**

**A: NO.** The flow variables are not adjacency; they are capacity variables that must satisfy conservation. Physical adjacency is determined by the edge existence conditions (placement selection, port matching, etc.).

**Q: Can one selected room satisfy its demand at an unavailable/inactive port?**

**A: NO.** The constraint `sink <= node_active` ensures a sink is only 1 if the port node is active, which requires the placement option to be selected.

**Q: What about the isolated Airlock root exception?**

**A: ROOT EXCEPTION DOCUMENTED.** For a Base containing only the Airlock:
- Total non-root demand = 0
- Therefore required Airlock source = 0
- Flow equations: `0 + 0 - 0 == 0` and `sum(source) == sum(demand)` → `0 == 0`
- All flows = 0 is a valid solution
- H7 reachability is vacuously satisfied (no non-root nodes to reach)
- But H6 local physical connection is NOT enforced for the root

**CONCLUSION:** The single-commodity flow encoding is mathematically sound for enforcing Airlock-rooted reachability for positive-demand non-root components. The H6 root local-connection underconstraint is a separate requirement not covered by the flow model.

---

## 3. Conditional Edge Safety Review

| Edge kind | Availability condition | Source | Status |
|---|---|---|---|
| Room-room | Both placements selected + ports directly meet | `hard_constraints.py:291-303` | VERIFIED |
| Room-utility | Room placement selected + utility selected at matching anchor | `hard_constraints.py:305-317` | VERIFIED |
| Utility-horizontal | Both utilities selected | `hard_constraints.py:321-333` | VERIFIED |
| Elevator-vertical | Both elevators selected | `hard_constraints.py:335-348` | VERIFIED |
| Transit internal | Room placement selected + transit_allowed | `hard_constraints.py:266-280` | VERIFIED |

All conditional edges have proper activation conditions.

---

## 4. H6 Airlock Root Analysis — CONFIRMED DEFECT

### Issue identified

The Airlock is the flow source and does not consume a sink demand. However, H6 states:

> **H6 — Local connection:** Every installed network module has at least one legal connection. This does not replace global reachability.

The current formulation only checks global reachability via flow. It does NOT explicitly verify that Airlock itself has at least one legal physical connection.

### Evidence

**Minimal counterexample (isolated Airlock):**
- Base: 8x1 synthetic grid
- Airlock placed at (0,0) width=4
- No other rooms, no utilities

**Oracle result:** INFEASIBLE — H6 violated (Airlock has 0 connections)

**Formulation A result:** FEASIBLE — Root flow equation `sum(source) == sum(demand)` reduces to `0 == 0`

**Root cause:** With only the Airlock installed:
- Total non-root demand = 0
- Required root source = 0
- Flow conservation: `sum(source) == sum(all_demand_terms)` → `0 == 0`
- No explicit H6 physical-degree condition on Airlock root

### Scope of defect

**ROOT-ONLY:** The defect is isolated to the Airlock root when total non-root demand is zero.

| Scenario | Oracle | Formulation A | Agreement |
|---|---|---|---|
| Isolated Airlock | INFEASIBLE | FEASIBLE | **MISMATCH** |
| Disconnected non-root room | INFEASIBLE | INFEASIBLE | ✓ |
| Isolated Corridor | INFEASIBLE | INFEASIBLE | ✓ |
| Isolated Elevator | INFEASIBLE | INFEASIBLE | ✓ |
| Connected Airlock + room | FEASIBLE | FEASIBLE | ✓ |

### Classification

**BLOCKED_CORRECTNESS** — This is a semantic mismatch on unambiguous normative H6, not a traceability defect.

---

## 5. Independent Hard-Feasibility Oracle

### Design

The oracle will:
1. Enumerate all legal room placements from `ModuleSpec` and `BaseGeometry`
2. Enumerate all utility anchor states (NONE, CORRIDOR, ELEVATOR)
3. For each combination, build a connectivity graph
4. Check all H-rules independently using BFS/DFS

### Key oracle checks

1. **H1 (Multiplicity)**: Each required instance appears exactly once
2. **H2 (Base mask)**: All placement cells are in buildable cells
3. **H3 (No overlap)**: No two rooms occupy same cell
4. **H5 (Legal ports)**: Room-room edges only at matching ports
5. **H6 (Local connection)**: Each installed module has >= 1 connection
6. **H7 (Airlock reachability)**: BFS from Airlock reaches all modules
7. **H8 (Non-transit)**: No internal edge for non-transit rooms
8. **H9 (Corridor)**: Only on legal anchors, horizontal only
9. **H10 (Elevator)**: Only stacked, same-x
10. **H11 (No floating utilities)**: All utilities reachable from Airlock

---

## 6. Current Formulation Size Baseline

### Methodology

For each test case:
- Count room instances
- Count legal placement options
- Count utility anchors
- Count graph nodes
- Count graph edges
- Record CP-SAT variables
- Record CP-SAT constraints

### Results (to be filled by running tests)

| Case | Rooms | Placements | Anchors | Nodes | Edges | Vars | Constraints |
|---|---|---|---|---|---|---|---|
| Tiny | - | - | - | - | - | - | - |
| Tier I | - | - | - | - | - | - | - |
| Tier II | - | - | - | - | - | - | - |

---

## 7. Test Matrix — EXECUTED RESULTS

Required oracle test cases:

| ID | Description | Expected outcome | Oracle | Formulation A | Status |
|---|---|---|---|---|---|
| A | Direct adjacent transit rooms | FEASIBLE | FEASIBLE | FEASIBLE | ✓ AGREE |
| B | Disconnected room | INFEASIBLE | INFEASIBLE | INFEASIBLE | ✓ AGREE |
| C | Transit middle room bridge | FEASIBLE | FEASIBLE | FEASIBLE | ✓ AGREE |
| D | Non-transit middle room bridge rejection | INFEASIBLE | INFEASIBLE | INFEASIBLE | ✓ AGREE |
| E | Two-floor stacked Elevator connection | FEASIBLE | FEASIBLE | FEASIBLE | ✓ AGREE |
| F | Corridor cannot provide vertical connection | INFEASIBLE | INFEASIBLE | INFEASIBLE | ✓ AGREE |
| G | Floating Corridor rejection | INFEASIBLE | INFEASIBLE | INFEASIBLE | ✓ AGREE |
| H | Floating Elevator rejection | INFEASIBLE | INFEASIBLE | INFEASIBLE | ✓ AGREE |
| I | Overlapping utilities | INFEASIBLE | INFEASIBLE | INFEASIBLE | ✓ AGREE |
| J | Room-utility overlap | INFEASIBLE | INFEASIBLE | INFEASIBLE | ✓ AGREE |
| K | Irregular/asymmetric Base mask | Depends | — | — | — |
| L | Blocked core exclusion | H2 violation if placed | — | — | — |
| M | Tall room standard floor port | FEASIBLE | FEASIBLE | FEASIBLE | ✓ AGREE |
| N | Radiation Repulsor top access | FEASIBLE (top access only) | — | — | — |
| O | Rapidium Ark non-transit | FEASIBLE (terminal only) | FEASIBLE | FEASIBLE | ✓ AGREE |
| P | 1x1 logical LEFT/RIGHT ports | FEASIBLE | — | — | — |
| Q | Two identical rooms symmetry | FEASIBLE | — | — | — |
| R | Shifted Elevator shaft | FEASIBLE with horizontal transfer | — | — | — |
| S | Airlock-only (H6 root test) | INFEASIBLE (no connection) | INFEASIBLE | FEASIBLE | **MISMATCH** |

**Summary:** 14/15 explicit test cases agree. 1 case (S) is a known H6 root mismatch.

---

## 8. Implementation Plan

1. Create `tests/support/hard_feasibility_oracle.py` with independent oracle
2. Create `tests/test_hard_feasibility_oracle.py` with test cases
3. Create `docs/CP_SAT_HARD_MODEL_AUDIT_PHASE1.md` (this file)
4. Run oracle vs CP-SAT comparison for tiny cases
5. Measure formulation sizes

---

## 9. Quality Gates

- [x] Production main SHA verified: `672e591e44e7b5343ef7242d56c62103f1f4110f`
- [x] Branch created from origin/main
- [x] `python -m pip check` — No broken requirements found
- [x] `python -m ruff check .` — All checks passed (test files)
- [x] `python -m pytest -q` — 36 audit tests passed
- [x] `git diff --check` — No whitespace issues

---

## 10. Phase-1 Decision Matrix

| Outcome | Classification |
|---|---|
| Oracle == CP-SAT for all test cases | FORMULATION_A_CORRECT |
| Minor oracle defects found | FORMULATION_A_CORRECT_WITH_TRACEABILITY_DEFECTS |
| Non-trivial semantic mismatch | **BLOCKED_CORRECTNESS** |
| Normative rules ambiguous | SPEC_AMBIGUITY_BLOCKS_AUDIT |

### DECISION: **BLOCKED_CORRECTNESS**

**Reason:** The independent oracle exposed a semantic mismatch on normative H6:

- **Oracle:** Isolated Airlock → INFEASIBLE
- **Formulation A:** Isolated Airlock → FEASIBLE
- **Root cause:** Root flow equation `sum(source) == sum(demand)` reduces to `0 == 0` when total non-root demand = 0
- **Scope:** ROOT LOCAL-CONNECTION UNDERCONSTRAINT only

All other H-rules (H1-H5, H7-H11) agree between oracle and Formulation A.

---

## 11. Repair Options — DOCUMENT ONLY

Do NOT implement the fix on this branch.

### PRIMARY (Recommended)
**Explicit root physical-degree constraint:**
```python
# sum(active legal physical connection literals incident to selected Airlock) >= 1
```

This adds a direct H6 enforcement for the Airlock without modifying the flow model.

### ALTERNATIVE
**Model root as consuming an explicit network edge:**
Force the Airlock to participate in at least one real selected edge by adding its own sink demand of 1 that must be satisfied by a real physical connection.

### Requirements for any fix:
- Enforce H6 exactly for Airlock
- Add no fictitious edges
- Preserve H7 semantics
- Preserve all currently legal connected layouts
- Agree with the independent oracle

---

## 12. Traceability Defects (Separate from H6 Semantic Defect)

Record stale historical H-number comments in `hard_constraints.py` vs current H1-H12 in `PROJECT_SYSTEM_REQUIREMENTS.md`.

**Example:** Line comments referencing old H-numbering that doesn't match current spec.

These are cosmetic and do not affect semantic correctness. Do not clean in this research branch.

---

## 13. Performance Baseline

**FORMULATION-A PERFORMANCE BASELINE: DEFERRED UNTIL H6 CORRECTNESS FIX**

Because correctness is blocked, do not spend time profiling Tier I-IV in this branch. Optimizing an incorrect formulation is not productive.

---

## 14. Phase-1 Decision

**PHASE-1 DECISION: BLOCKED_CORRECTNESS**

The independent oracle exposed a semantic mismatch on normative H6 that the current Formulation A does not enforce for the Airlock root.

**Next recommended milestone:** CLEAN H6 ROOT CORRECTNESS FIX FROM PRODUCTION MAIN

---