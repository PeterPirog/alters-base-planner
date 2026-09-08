# OR-Tools hard-constraint layer

This document maps the accepted physical Base rules to the reusable CP-SAT definitions in:

```text
src/alters_base_planner/hard_constraints.py
```

The layer is intentionally **not connected to `solve_plan()` yet**. It is a tested foundation for the future integrated room + Corridor + Elevator solver. The current production engine keeps its existing placement-then-routing behavior until the integrated model is introduced deliberately.

## Modeling principle

Hard constraints answer only:

> Is this final Base layout physically and topologically legal?

They do not encode convenience, traffic preference, Base mass preference or the weighted gameplay objective `F`.

The implementation separates two kinds of hard rules:

1. **static domain rules** — illegal candidates are rejected before CP-SAT variables are created;
2. **combinatorial CP-SAT rules** — OR-Tools chooses among legal room placements and solver-managed utility modules while preserving occupancy and connectivity.

This is intentional. A placement outside the Base mask is not an alternative that the solver should search and reject later; it should never be part of the decision domain.

---

## H1 — inside active Base geometry

**Rule:** every selected room and utility module must lie completely inside the active buildable Base domain.

**Implementation:** `buildable_cells` is the legal spatial domain. `PlacementOptionSpec.cells` and every `UtilityAnchorSpec.cells` are validated as subsets before model construction.

**Type:** static hard-domain constraint.

---

## H2 — fixed obstruction/core exclusion

**Rule:** no movable module may occupy a fixed core/blocked cell.

**Implementation:** callers pass `buildable_cells`, not all allowed cells. Fixed/blocked cells therefore cannot occur in any accepted placement or utility anchor.

**Type:** static hard-domain constraint.

---

## H3 — exclusive physical occupancy

**Rule:** one Base cell may belong to at most one selected module.

**Implementation:** all room-placement literals and utility-active literals occupying a cell are collected and constrained with `model.add_at_most_one(...)`.

This covers room-room, room-Corridor, room-Elevator and every utility-utility overlap, including one-cell overlaps between shifted 2x1 anchors.

**Type:** CP-SAT hard constraint.

---

## H4 — legal size and orientation

**Rule:** a room must preserve the verified module footprint/orientation.

**Implementation:** only pre-enumerated legal `PlacementOptionSpec` candidates are supplied. Unsupported rotated/deformed candidates must never enter this layer.

**Type:** static hard-domain constraint.

---

## H5 — exact required room multiplicity

**Rule:** every required room instance must be placed exactly once.

**Implementation:** every logical room instance has one or more candidate placement literals and receives `add_exactly_one(...)`.

Requested count and mandatory/story-state expansion therefore happens before this layer by creating the appropriate room instances.

**Type:** CP-SAT hard constraint.

---

## H6 — solver ownership of Corridor/Elevator

**Rule:** Corridor and Elevator are solver-managed 2x1 modules.

**Implementation:** every legal `UtilityAnchorSpec(x,y)` receives:

```text
C[x,y]  Corridor BoolVar
E[x,y]  Elevator BoolVar
U[x,y]  utility-active BoolVar
```

with:

```text
C[x,y] + E[x,y] <= 1
U[x,y] = C[x,y] + E[x,y]
```

The player does not provide utility counts.

**Type:** CP-SAT decision domain + hard constraint.

---

## H7 — explicit legal room ports

**Rule:** room connections may use only verified explicit access ports.

**Implementation:** every placement candidate contains absolute `ResolvedPort` objects. Port coordinates must lie inside that candidate's room footprint. Standard LEFT/RIGHT floor-port derivation and special exceptions remain responsibilities of the module/catalog geometry layer.

**Type:** static hard-domain constraint.

---

## H8 — legal direct room adjacency

**Rule:** two rooms connect directly only when opposite explicit port boundaries meet at identical absolute `(edge_x, edge_y)`.

**Implementation:** the graph contains a conditional room-port edge only for matching LEFT/RIGHT boundary pairs. The edge can carry connectivity flow only when both corresponding placement candidates are selected.

**Type:** CP-SAT conditional graph constraint.

---

## H9 — legal room-to-utility contact

**Rule:** a room may join Corridor/Elevator only at the exact 2x1 anchor immediately outside a resolved port.

**Implementation:** room-port-to-utility graph edges are generated only for `ResolvedPort.utility_anchor` and require both the room placement and utility anchor to be active.

**Type:** CP-SAT conditional graph constraint.

---

## H10 — horizontal utility connectivity

**Rule:** consecutive 2x1 utility modules connect horizontally when their anchors differ by exactly two x-cells on the same row.

**Implementation:** conditional utility graph edges connect `(x,y)` to `(x+2,y)` when both utility anchors are active.

Corridor and Elevator may both participate in horizontal transfer on a floor.

**Type:** CP-SAT conditional graph constraint.

---

## H11/H12 — vertical travel only through stacked Elevator modules

**Rule:** vertical movement exists only between Elevator modules at `(x,y)` and `(x,y+1)`.

**Implementation:** vertical graph edges require both `E[x,y]` and `E[x,y+1]`.

No vertical Corridor edge exists. No jump over a floor exists. No global single-shaft-x rule exists.

A shifted shaft is therefore possible only if the selected utilities provide a genuine horizontal transfer path on a floor.

**Type:** CP-SAT conditional graph constraint.

---

## H13 — transit versus terminal room

**Rule:** a terminal/non-transit room can be reached but cannot bridge traffic between its opposite sides.

**Implementation:** internal LEFT-to-RIGHT port graph edges are generated only for placement candidates with `transit_allowed=True`.

For a module such as Rapidium Ark, its ports exist and can satisfy room reachability, but there is no internal graph edge joining them.

**Type:** CP-SAT graph-topology constraint.

---

## H14/H15/H16 — every room reachable from Airlock, at least one port is sufficient

**Rule:** every installed non-root room must have at least one legal port reachable from the Airlock-rooted network. Both room ports are not required.

**Implementation:** the layer uses a single-commodity flow proof of connectivity.

For every non-root room instance exactly one active port becomes a one-unit flow sink. Flow may enter the graph only through active ports of the `root_instance_id` (normally `airlock-1`). Flow can traverse only conditional graph edges whose room/utility decisions are active.

Therefore a disconnected room cannot satisfy the model, while a legal terminal room can consume its flow at one reachable port without becoming a bridge.

**Type:** exact CP-SAT rooted-connectivity constraint.

---

## H17 — special module semantics override defaults

**Rule:** verified module exceptions override standard access/transit assumptions.

**Implementation:** exceptions remain in input data (`ResolvedPort`, `transit_allowed`) and are preserved exactly by the hard layer. The hard layer does not infer a standard floor port for a module that already supplies explicit resolved ports.

**Type:** domain-data rule consumed by CP-SAT topology.

---

## H18 — selected utilities belong to the access network

**Rule:** a selected Corridor or Elevator may not form a floating disconnected island.

**Implementation:** every active utility node consumes one unit of Airlock-rooted flow. A selected utility in a disconnected component therefore makes the model infeasible.

This rule forbids floating utilities but does **not** claim that every connected utility is minimal. Minimizing unnecessary but connected utilities belongs to an objective/tie-breaker, not physical feasibility.

**Type:** exact CP-SAT rooted-connectivity constraint.

---

# Why there is no separate "continuous elevator span" hard rule

The fundamental vertical rules are already:

```text
vertical edge only if E[x,y] and E[x,y+1]
+
every required room is Airlock-reachable
```

If a room on another floor is reachable, a continuous legal vertical path must therefore exist automatically. A separate global rule saying that every row between the minimum and maximum occupied room level must contain an Elevator is not required for semantic correctness and could overconstrain layouts with legal transfer paths.

A future integrated solver may add mathematically redundant elevator-cover constraints only if benchmarks show that they improve CP-SAT propagation without changing the legal solution set.

---

# Explicitly not encoded as hard constraints

The following remain outside this layer:

- weighted pair-distance objective `F`;
- room usage weights;
- minimizing Corridor/Elevator count;
- Base mass minimization;
- Organics tank capacity as layout feasibility;
- preferred proximity to Airlock or other rooms;
- progression/resource/build-order feasibility.

These are objectives, reporting metrics or a future game-state planning layer.

---

# Integration contract for the future solver

The future solver should:

1. expand requested/mandatory rooms into room instances;
2. enumerate only legal room-placement candidates against the selected Base mask;
3. resolve each candidate's explicit ports into absolute coordinates;
4. enumerate every legal 2x1 utility anchor;
5. call `build_hard_constraint_layer(...)`;
6. add the gameplay objective and any proven-valid objective bounds;
7. solve one integrated room + utility model.

The existing `solve_plan()` is intentionally unchanged by this commit.
