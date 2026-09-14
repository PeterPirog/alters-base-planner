"""Exact CP-SAT encoding of the documented modified-Manhattan room-packing lower bound.

This module contains the verified Stage-4 master lower-bound encoding for the room-packing
master. Its production integration was measured and **blocked**: minimizing this exact bound
inside the room-packing master is combinatorially hard for CP-SAT on realistic instances (more
than 30 seconds without an optimality proof on a Tier-I request with ten rooms, versus
milliseconds for the legacy centrality objective), and lower-bound-ordered enumeration
front-loads packings that are provably infrastructure-infeasible, which destroys anytime
incumbent quality. See `docs/BENCHMARKS.md` ("Master lower-bound integration blocker") for the
measurements. The encoding itself is exact, tested against
`modified_manhattan_room_lower_bound` / `scaled_modified_manhattan_lower_bound`, and kept here so
the next iteration can build on verified ground truth without repeating the correctness work.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .models import ModuleInstance, PortSide
from .objective import ScaledObjective


@dataclass(frozen=True, slots=True)
class MasterPort:
    """Exact affine offsets of one resolved port in master coordinates.

    The offsets reproduce ``resolve_ports`` bit for bit: ``edge_x = room_x + edge_x_offset``,
    ``edge_y = room_y + edge_y_offset`` and the external 2x1 utility anchor
    ``anchor_x = room_x + anchor_x_offset``.
    """

    edge_x_offset: int
    edge_y_offset: int
    anchor_x_offset: int


def master_port_offsets(spec_width: int, spec_height: int, port_side: PortSide, port_cell_y: int) -> MasterPort:
    if port_side is PortSide.LEFT:
        return MasterPort(edge_x_offset=0, edge_y_offset=spec_height - 1 - port_cell_y, anchor_x_offset=-2)
    return MasterPort(
        edge_x_offset=spec_width,
        edge_y_offset=spec_height - 1 - port_cell_y,
        anchor_x_offset=spec_width,
    )


@dataclass(frozen=True, slots=True)
class MasterLowerBoundBuild:
    """Exact CP-SAT encoding of the documented modified-Manhattan lower bound."""

    master_scaled_lb: cp_model.IntVar
    master_lb_upper_bound: int
    pair_lb_by_pair_id: dict[str, cp_model.IntVar]
    aux_variable_count: int
    aux_constraint_count: int


def add_master_modified_manhattan_lower_bound(
    model: cp_model.CpModel,
    *,
    instances: Sequence[ModuleInstance],
    vars_by_instance: Mapping[str, list[cp_model.IntVar]],
    candidates_by_instance: Mapping[str, Sequence[tuple[int, int]]],
    objective: ScaledObjective,
) -> MasterLowerBoundBuild:
    """Encode the documented modified-Manhattan lower bound exactly in a room-packing model.

    For every room instance the selected placement coordinates become integer variables with
    ``room_x == sum(candidate.x * placement_bool)`` and ``room_y == sum(candidate.y *
    placement_bool)``; exactly-one placement semantics make both equalities exact. Every spec
    port contributes affine world expressions identical to ``resolve_ports`` (see
    ``master_port_offsets``). For every canonical objective pair and concrete port pair the
    encoding reproduces ``modified_manhattan_room_lower_bound`` exactly:

        same row    ->  ceil(|edge_x_a - edge_x_b| / 2)
        other rows  ->  ceil(|anchor_x_a - anchor_x_b| / 2) + |edge_y_a - edge_y_b| + 1

    ``same_row`` is an exact iff-reified equality on the port rows (both directions), absolute
    values use the public ``add_abs_equality`` primitive over plain difference variables, and
    ``ceil(d / 2)`` for non-negative integer ``d`` uses the exact linear encoding ``2*h >= d``
    with ``2*h <= d + 1``. ``add_min_equality`` takes the minimum over all port pairs of both
    rooms and the master scaled bound sums ``coefficient * pair_lb``. No Boolean conjunction
    variable for any candidate-pair product is ever created: the auxiliary size grows with
    rooms, objective pairs and port pairs only.

    The projection of this expression onto any selected packing is exactly the documented
    ``scaled_modified_manhattan_lower_bound(...)`` value for that packing.
    """

    room_x_by_instance: dict[str, cp_model.IntVar] = {}
    room_y_by_instance: dict[str, cp_model.IntVar] = {}
    x_bounds: dict[str, tuple[int, int]] = {}
    y_bounds: dict[str, tuple[int, int]] = {}
    aux_variable_count = 0
    aux_constraint_count = 0

    for instance in instances:
        instance_id = instance.instance_id
        candidates = candidates_by_instance[instance_id]
        placement_vars = vars_by_instance[instance_id]
        x_values = [candidate[0] for candidate in candidates]
        y_values = [candidate[1] for candidate in candidates]
        x_lo, x_hi = min(x_values), max(x_values)
        y_lo, y_hi = min(y_values), max(y_values)
        room_x = model.new_int_var(x_lo, x_hi, f"master_room_x__{instance_id}")
        room_y = model.new_int_var(y_lo, y_hi, f"master_room_y__{instance_id}")
        model.add(
            room_x == sum(x * var for x, var in zip(x_values, placement_vars, strict=True))
        )
        model.add(
            room_y == sum(y * var for y, var in zip(y_values, placement_vars, strict=True))
        )
        room_x_by_instance[instance_id] = room_x
        room_y_by_instance[instance_id] = room_y
        x_bounds[instance_id] = (x_lo, x_hi)
        y_bounds[instance_id] = (y_lo, y_hi)
        aux_variable_count += 2
        aux_constraint_count += 2

    pair_lb_by_pair_id: dict[str, cp_model.IntVar] = {}
    pair_ub_by_pair_id: dict[str, int] = {}
    for pair in objective.pairs:
        source = next(instance for instance in instances if instance.instance_id == pair.source_instance_id)
        target = next(instance for instance in instances if instance.instance_id == pair.target_instance_id)
        s_x_lo, s_x_hi = x_bounds[source.instance_id]
        s_y_lo, s_y_hi = y_bounds[source.instance_id]
        t_x_lo, t_x_hi = x_bounds[target.instance_id]
        t_y_lo, t_y_hi = y_bounds[target.instance_id]
        source_ports = [
            master_port_offsets(source.spec.width, source.spec.height, port.side, port.cell_y)
            for port in source.spec.ports
        ]
        target_ports = [
            master_port_offsets(target.spec.width, target.spec.height, port.side, port.cell_y)
            for port in target.spec.ports
        ]

        port_pair_vars: list[cp_model.IntVar] = []
        port_pair_bounds: list[int] = []
        for port_a_index, offsets_a in enumerate(source_ports):
            for port_b_index, offsets_b in enumerate(target_ports):
                suffix = f"{pair.pair_id}__{port_a_index}_{port_b_index}"
                dx_lo = s_x_lo + offsets_a.edge_x_offset - (t_x_hi + offsets_b.edge_x_offset)
                dx_hi = s_x_hi + offsets_a.edge_x_offset - (t_x_lo + offsets_b.edge_x_offset)
                dy_lo = s_y_lo + offsets_a.edge_y_offset - (t_y_hi + offsets_b.edge_y_offset)
                dy_hi = s_y_hi + offsets_a.edge_y_offset - (t_y_lo + offsets_b.edge_y_offset)
                anchor_lo = s_x_lo + offsets_a.anchor_x_offset - (t_x_hi + offsets_b.anchor_x_offset)
                anchor_hi = s_x_hi + offsets_a.anchor_x_offset - (t_x_lo + offsets_b.anchor_x_offset)
                dx_abs_ub = max(abs(dx_lo), abs(dx_hi))
                dy_abs_ub = max(abs(dy_lo), abs(dy_hi))
                anchor_abs_ub = max(abs(anchor_lo), abs(anchor_hi))

                edge_x_a = room_x_by_instance[source.instance_id] + offsets_a.edge_x_offset
                edge_x_b = room_x_by_instance[target.instance_id] + offsets_b.edge_x_offset
                edge_y_a = room_y_by_instance[source.instance_id] + offsets_a.edge_y_offset
                edge_y_b = room_y_by_instance[target.instance_id] + offsets_b.edge_y_offset
                anchor_x_a = room_x_by_instance[source.instance_id] + offsets_a.anchor_x_offset
                anchor_x_b = room_x_by_instance[target.instance_id] + offsets_b.anchor_x_offset

                # Plain intermediate difference variables keep add_abs_equality arguments free
                # of nested linear expressions.
                dx = model.new_int_var(dx_lo, dx_hi, f"master_dx__{suffix}")
                model.add(dx == edge_x_a - edge_x_b)
                dx_abs = model.new_int_var(0, dx_abs_ub, f"master_dx_abs__{suffix}")
                model.add_abs_equality(dx_abs, dx)
                h_edge = model.new_int_var(0, (dx_abs_ub + 1) // 2, f"master_h_edge__{suffix}")
                model.add(2 * h_edge >= dx_abs)
                model.add(2 * h_edge <= dx_abs + 1)

                anchor = model.new_int_var(anchor_lo, anchor_hi, f"master_anchor__{suffix}")
                model.add(anchor == anchor_x_a - anchor_x_b)
                anchor_abs = model.new_int_var(0, anchor_abs_ub, f"master_anchor_abs__{suffix}")
                model.add_abs_equality(anchor_abs, anchor)
                h_anchor = model.new_int_var(0, (anchor_abs_ub + 1) // 2, f"master_h_anchor__{suffix}")
                model.add(2 * h_anchor >= anchor_abs)
                model.add(2 * h_anchor <= anchor_abs + 1)

                dy = model.new_int_var(dy_lo, dy_hi, f"master_dy__{suffix}")
                model.add(dy == edge_y_a - edge_y_b)
                dy_abs = model.new_int_var(0, dy_abs_ub, f"master_dy_abs__{suffix}")
                model.add_abs_equality(dy_abs, dy)

                same_row = model.new_bool_var(f"master_same_row__{suffix}")
                # exact iff: |edge_y_a - edge_y_b| == 0 iff same_row (abs equality links
                # dy_abs to the port-row difference in both directions).
                model.add(dy_abs == 0).only_enforce_if(same_row)
                model.add(dy_abs >= 1).only_enforce_if(same_row.Not())

                port_pair_ub = max(
                    (dx_abs_ub + 1) // 2,
                    (anchor_abs_ub + 1) // 2 + dy_abs_ub + 1,
                )
                port_pair_lb = model.new_int_var(0, port_pair_ub, f"master_port_pair_lb__{suffix}")
                model.add(port_pair_lb == h_edge).only_enforce_if(same_row)
                model.add(port_pair_lb == h_anchor + dy_abs + 1).only_enforce_if(same_row.Not())

                port_pair_vars.append(port_pair_lb)
                port_pair_bounds.append(port_pair_ub)
                aux_variable_count += 10
                aux_constraint_count += 14

        pair_ub = min(port_pair_bounds)
        pair_lb = model.new_int_var(0, pair_ub, f"master_pair_lb__{pair.pair_id}")
        if len(port_pair_vars) == 1:
            model.add(pair_lb == port_pair_vars[0])
        else:
            model.add_min_equality(pair_lb, port_pair_vars)
        pair_lb_by_pair_id[pair.pair_id] = pair_lb
        pair_ub_by_pair_id[pair.pair_id] = pair_ub
        aux_variable_count += 1
        aux_constraint_count += 1

    master_lb_ub = sum(
        pair.coefficient * pair_ub_by_pair_id[pair.pair_id] for pair in objective.pairs
    )
    master_scaled_lb = model.new_int_var(0, master_lb_ub, "master_scaled_manhattan_lb")
    model.add(
        master_scaled_lb
        == sum(pair.coefficient * pair_lb_by_pair_id[pair.pair_id] for pair in objective.pairs)
    )
    aux_variable_count += 1
    aux_constraint_count += 1
    return MasterLowerBoundBuild(
        master_scaled_lb=master_scaled_lb,
        master_lb_upper_bound=master_lb_ub,
        pair_lb_by_pair_id=pair_lb_by_pair_id,
        aux_variable_count=aux_variable_count,
        aux_constraint_count=aux_constraint_count,
    )