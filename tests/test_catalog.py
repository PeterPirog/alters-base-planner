from alters_base_planner.catalog import MANDATORY_MODULES, MODULE_BY_KEY, MODULES


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


def test_mandatory_story_modules_include_kitchen_and_womb() -> None:
    keys = {m.key for m in MANDATORY_MODULES}
    assert "kitchen" in keys
    assert "womb" in keys
