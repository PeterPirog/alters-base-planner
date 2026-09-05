from alters_base_planner.catalog import MANDATORY_MODULES, MODULE_BY_KEY, MODULES, USAGE_WEIGHTS
from alters_base_planner.models import ConnectionLevel


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
    # Current English wiki table incorrectly repeats the Dormitory's 40-Metal cost as its mass.
    # Patch 1.4 empirical data, the Russian wiki and in-game player reports agree on mass 8.
    assert MODULE_BY_KEY["dormitory"].mass == 8
    assert MODULE_BY_KEY["radiation_repulsor"].mass == 16
    assert MODULE_BY_KEY["rapidium_ark"].mass == 32

    repulsor = MODULE_BY_KEY["radiation_repulsor"]
    assert repulsor.connection_level is ConnectionLevel.TOP
    assert repulsor.transit_allowed is False
    assert MODULE_BY_KEY["rapidium_ark"].transit_allowed is False


def test_mandatory_story_modules_include_kitchen_and_womb() -> None:
    keys = {m.key for m in MANDATORY_MODULES}
    assert "kitchen" in keys
    assert "womb" in keys


def test_every_module_has_gameplay_usage_weight() -> None:
    assert set(USAGE_WEIGHTS) == set(MODULE_BY_KEY)
    assert all(0 < module.visit_weight <= 1 for module in MODULES)


def test_baseline_usage_weight_priorities() -> None:
    assert MODULE_BY_KEY["airlock"].visit_weight == 1.0
    assert MODULE_BY_KEY["workshop"].visit_weight == 0.9
    assert MODULE_BY_KEY["small_storage"].visit_weight == 0.1
    assert MODULE_BY_KEY["large_storage"].visit_weight == 0.1
    assert MODULE_BY_KEY["womb"].visit_weight < MODULE_BY_KEY["workshop"].visit_weight
