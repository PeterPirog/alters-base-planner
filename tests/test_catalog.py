import pytest

from alters_base_planner.catalog import (
    MODULE_BY_KEY,
    MODULES,
    PLAYER_MODULES,
    SOLVER_MODULES,
    SYSTEM_MODULES,
    USAGE_WEIGHTS,
)
from alters_base_planner.models import (
    ModulePlacement,
    ModuleType,
    PlacementAuthority,
    PortSide,
    floor_ports,
    resolve_ports,
)


def _placement(module_key: str, instance_id: str, x: int, y: int) -> ModulePlacement:
    spec = MODULE_BY_KEY[module_key]
    return ModulePlacement(instance_id, module_key, x, y, spec.width, spec.height)


def test_module_keys_are_unique() -> None:
    assert len(MODULE_BY_KEY) == len(MODULES)


def test_authority_partitions_cover_catalog_without_overlap() -> None:
    system = {module.key for module in SYSTEM_MODULES}
    player = {module.key for module in PLAYER_MODULES}
    solver = {module.key for module in SOLVER_MODULES}

    assert system | player | solver == set(MODULE_BY_KEY)
    assert not (system & player)
    assert not (system & solver)
    assert not (player & solver)
    assert all(module.authority is PlacementAuthority.SYSTEM for module in SYSTEM_MODULES)
    assert all(module.authority is PlacementAuthority.PLAYER for module in PLAYER_MODULES)
    assert all(module.authority is PlacementAuthority.SOLVER for module in SOLVER_MODULES)


def test_placement_authority_does_not_override_game_module_type() -> None:
    assert MODULE_BY_KEY["kitchen"].authority is PlacementAuthority.SYSTEM
    assert MODULE_BY_KEY["womb"].authority is PlacementAuthority.SYSTEM
    assert MODULE_BY_KEY["kitchen"].module_type is ModuleType.WORK
    assert MODULE_BY_KEY["womb"].module_type is ModuleType.WORK


def test_solver_infrastructure_is_canonical_module_data() -> None:
    assert {module.key for module in SOLVER_MODULES} == {"corridor", "elevator"}
    for key in ("corridor", "elevator"):
        spec = MODULE_BY_KEY[key]
        assert spec.authority is PlacementAuthority.SOLVER
        assert (spec.width, spec.height, spec.mass) == (2, 1, 2)
        assert spec.visit_weight == 0.0
        assert spec.ports == floor_ports(2)
    assert MODULE_BY_KEY["elevator"].vertical_connectivity is True
    assert MODULE_BY_KEY["corridor"].vertical_connectivity is False


def test_known_dimensions() -> None:
    assert (MODULE_BY_KEY["workshop"].width, MODULE_BY_KEY["workshop"].height) == (4, 1)
    assert (MODULE_BY_KEY["quantum_computer"].width, MODULE_BY_KEY["quantum_computer"].height) == (4, 2)
    assert (MODULE_BY_KEY["radiation_repulsor"].width, MODULE_BY_KEY["radiation_repulsor"].height) == (2, 3)
    assert (MODULE_BY_KEY["kitchen"].width, MODULE_BY_KEY["kitchen"].height) == (5, 1)
    assert (MODULE_BY_KEY["park_with_bench"].width, MODULE_BY_KEY["park_with_bench"].height) == (6, 1)


def test_verified_mass_values_and_special_connectivity() -> None:
    assert MODULE_BY_KEY["dormitory"].mass == 8
    assert MODULE_BY_KEY["radiation_repulsor"].mass == 16
    assert MODULE_BY_KEY["rapidium_ark"].mass == 32

    repulsor = MODULE_BY_KEY["radiation_repulsor"]
    assert {port.cell_y for port in repulsor.ports} == {repulsor.height - 1}
    assert repulsor.transit_allowed is False
    assert MODULE_BY_KEY["rapidium_ark"].transit_allowed is False


def test_verified_count_limits() -> None:
    assert MODULE_BY_KEY["recycler"].max_count == 1
    assert MODULE_BY_KEY["rapidium_ark"].max_count == 5


def test_every_module_defines_extreme_left_and_right_ports() -> None:
    for module in MODULES:
        left = [port for port in module.ports if port.side is PortSide.LEFT]
        right = [port for port in module.ports if port.side is PortSide.RIGHT]
        assert left, module.key
        assert right, module.key
        assert all(port.cell_x == 0 for port in left)
        assert all(port.cell_x == module.width - 1 for port in right)


def test_standard_floor_ports_are_derived_from_width_only() -> None:
    left, right = floor_ports(6)
    assert (left.cell_x, left.cell_y) == (0, 0)
    assert (right.cell_x, right.cell_y) == (5, 0)
    assert left.side is PortSide.LEFT
    assert right.side is PortSide.RIGHT


def test_floor_ports_reject_non_positive_width() -> None:
    with pytest.raises(ValueError, match="width must be positive"):
        floor_ports(0)


def test_one_by_one_module_has_two_logical_ports_on_same_physical_cell() -> None:
    left, right = floor_ports(1)
    assert (left.cell_x, left.cell_y) == (0, 0)
    assert (right.cell_x, right.cell_y) == (0, 0)
    assert left.side is PortSide.LEFT
    assert right.side is PortSide.RIGHT


def test_normal_modules_match_width_derived_floor_ports() -> None:
    for key in (
        "quantum_computer",
        "small_storage",
        "large_storage",
        "materializer",
        "workshop",
        "corridor",
        "elevator",
    ):
        module = MODULE_BY_KEY[key]
        assert module.ports == floor_ports(module.width)


def test_floor_relative_ports_resolve_to_bottom_world_row() -> None:
    spec = MODULE_BY_KEY["materializer"]
    module = _placement("materializer", "materializer-1", 10, 5)
    resolved = resolve_ports(module, spec)
    assert {port.cell_y for port in resolved} == {7}


def test_top_relative_ports_resolve_to_top_world_row() -> None:
    spec = MODULE_BY_KEY["radiation_repulsor"]
    module = _placement("radiation_repulsor", "repulsor-1", 10, 5)
    resolved = resolve_ports(module, spec)
    assert {port.cell_y for port in resolved} == {5}


def test_system_modules_include_all_mandatory_baseline_modules() -> None:
    keys = {module.key for module in SYSTEM_MODULES}
    assert keys == {
        "airlock",
        "captains_cabin",
        "command_center",
        "communication_room",
        "kitchen",
        "machinery",
        "quantum_computer",
        "womb",
    }


def test_every_module_has_usage_weight_entry() -> None:
    assert set(USAGE_WEIGHTS) == set(MODULE_BY_KEY)
    assert all(0 <= module.visit_weight <= 1 for module in MODULES)


def test_baseline_usage_weight_priorities() -> None:
    assert MODULE_BY_KEY["airlock"].visit_weight == 1.0
    assert MODULE_BY_KEY["workshop"].visit_weight == 0.9
    assert MODULE_BY_KEY["small_storage"].visit_weight == 0.0
    assert MODULE_BY_KEY["medium_storage"].visit_weight == 0.0
    assert MODULE_BY_KEY["large_storage"].visit_weight == 0.0
    assert MODULE_BY_KEY["womb"].visit_weight == 0.1
    assert MODULE_BY_KEY["quantum_computer"].visit_weight == 0.1
    assert MODULE_BY_KEY["corridor"].visit_weight == 0.0
    assert MODULE_BY_KEY["elevator"].visit_weight == 0.0
