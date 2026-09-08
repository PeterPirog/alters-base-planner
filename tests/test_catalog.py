import pytest

from alters_base_planner.catalog import MANDATORY_MODULES, MODULE_BY_KEY, MODULES, USAGE_WEIGHTS
from alters_base_planner.models import ModuleType, Placement, PortSide, floor_ports, resolve_ports


def test_module_keys_are_unique() -> None:
    assert len(MODULE_BY_KEY) == len(MODULES)


def test_utility_modules_are_not_user_configurable() -> None:
    assert "corridor" not in MODULE_BY_KEY
    assert "elevator" not in MODULE_BY_KEY


def test_known_dimensions() -> None:
    assert (MODULE_BY_KEY["workshop"].width, MODULE_BY_KEY["workshop"].height) == (4, 1)
    assert (MODULE_BY_KEY["quantum_computer"].width, MODULE_BY_KEY["quantum_computer"].height) == (4, 2)
    assert (MODULE_BY_KEY["radiation_repulsor"].width, MODULE_BY_KEY["radiation_repulsor"].height) == (2, 3)
    assert (MODULE_BY_KEY["kitchen"].width, MODULE_BY_KEY["kitchen"].height) == (5, 1)


def test_verified_mass_values_and_special_connectivity() -> None:
    assert MODULE_BY_KEY["dormitory"].mass == 8
    assert MODULE_BY_KEY["radiation_repulsor"].mass == 16
    assert MODULE_BY_KEY["rapidium_ark"].mass == 32

    repulsor = MODULE_BY_KEY["radiation_repulsor"]
    # PortSpec.cell_y is floor-relative: y=0 is floor, height-1 is top.
    assert {port.cell_y for port in repulsor.ports} == {repulsor.height - 1}
    assert repulsor.transit_allowed is False
    assert MODULE_BY_KEY["rapidium_ark"].transit_allowed is False


def test_verified_count_limits() -> None:
    assert MODULE_BY_KEY["recycler"].max_count == 1
    # Public Rapidium Ark sources/version reports conflict on precise count ceilings;
    # do not invent a hard limit until game-exact data is available.
    assert MODULE_BY_KEY["rapidium_ark"].max_count is None


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


def test_one_by_one_room_has_two_logical_ports_on_same_physical_cell() -> None:
    left, right = floor_ports(1)
    assert (left.cell_x, left.cell_y) == (0, 0)
    assert (right.cell_x, right.cell_y) == (0, 0)
    assert left.side is PortSide.LEFT
    assert right.side is PortSide.RIGHT


def test_normal_modules_match_width_derived_floor_ports() -> None:
    for key in ("quantum_computer", "small_storage", "large_storage", "materializer", "workshop"):
        module = MODULE_BY_KEY[key]
        assert module.ports == floor_ports(module.width)


def test_floor_relative_ports_resolve_to_bottom_world_row() -> None:
    spec = MODULE_BY_KEY["materializer"]  # 4x3 regular floor-access room
    room = Placement("materializer-1", "materializer", 10, 5, spec.width, spec.height)
    resolved = resolve_ports(room, spec)
    assert {port.cell_y for port in resolved} == {7}  # world y = 5 + (3 - 1)


def test_top_relative_ports_resolve_to_top_world_row() -> None:
    spec = MODULE_BY_KEY["radiation_repulsor"]  # 2x3 verified top-access exception
    room = Placement("repulsor-1", "radiation_repulsor", 10, 5, spec.width, spec.height)
    resolved = resolve_ports(room, spec)
    assert {port.cell_y for port in resolved} == {5}


def test_mandatory_story_modules_include_kitchen_and_womb() -> None:
    keys = {m.key for m in MANDATORY_MODULES}
    assert "kitchen" in keys
    assert "womb" in keys


def test_mandatory_state_does_not_override_game_module_type() -> None:
    assert MODULE_BY_KEY["kitchen"].module_type is ModuleType.WORK
    assert MODULE_BY_KEY["womb"].module_type is ModuleType.WORK
    assert MODULE_BY_KEY["kitchen"].mandatory is True
    assert MODULE_BY_KEY["womb"].mandatory is True


def test_every_module_has_gameplay_usage_weight() -> None:
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
