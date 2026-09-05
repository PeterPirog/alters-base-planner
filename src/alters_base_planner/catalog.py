from __future__ import annotations

import json
from pathlib import Path

from .models import ConnectionLevel, ModuleSpec, ModuleType

_WEIGHTS_PATH = Path(__file__).with_name("data") / "usage_weights.json"


def _load_usage_weights() -> dict[str, float]:
    raw = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    weights_raw = raw.get("weights", {})
    result: dict[str, float] = {}
    for key, entry in weights_raw.items():
        weight = float(entry["weight"])
        if not 0 <= weight <= 1:
            raise ValueError(f"Invalid usage weight for {key}: {weight}")
        result[key] = weight
    return result


USAGE_WEIGHTS = _load_usage_weights()


def _w(key: str) -> float:
    try:
        return USAGE_WEIGHTS[key]
    except KeyError as exc:
        raise ValueError(f"Missing gameplay usage weight for module {key}") from exc


MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec("airlock", "Airlock", 4, 1, 4, ModuleType.CORE, mandatory=True, configurable=False, visit_weight=_w("airlock")),
    ModuleSpec("captains_cabin", "Captain's Cabin", 4, 1, 4, ModuleType.CORE, mandatory=True, configurable=False, visit_weight=_w("captains_cabin")),
    ModuleSpec("command_center", "Command Center", 4, 1, 4, ModuleType.CORE, mandatory=True, configurable=False, visit_weight=_w("command_center")),
    ModuleSpec("communication_room", "Communication Room", 4, 1, 4, ModuleType.CORE, mandatory=True, configurable=False, visit_weight=_w("communication_room")),
    ModuleSpec("kitchen", "Kitchen", 5, 1, 4, ModuleType.CORE, mandatory=True, configurable=False, visit_weight=_w("kitchen")),
    ModuleSpec("machinery", "Machinery", 4, 1, 4, ModuleType.CORE, mandatory=True, configurable=False, visit_weight=_w("machinery")),
    ModuleSpec("quantum_computer", "Quantum Computer", 4, 2, 8, ModuleType.CORE, mandatory=True, configurable=False, visit_weight=_w("quantum_computer")),
    ModuleSpec("womb", "The Womb", 5, 1, 4, ModuleType.CORE, mandatory=True, configurable=False, visit_weight=_w("womb")),
    ModuleSpec("ark_sarcophagus", "Ark Sarcophagus", 4, 2, 13, ModuleType.STORAGE, visit_weight=_w("ark_sarcophagus")),
    ModuleSpec("contemplation_room", "Contemplation Room", 6, 1, 20, ModuleType.WELLBEING, visit_weight=_w("contemplation_room")),
    ModuleSpec("dormitory", "Dormitory", 6, 1, 8, ModuleType.WELLBEING, visit_weight=_w("dormitory")),
    ModuleSpec("gamers_den", "Gamer's Den", 5, 1, 14, ModuleType.WELLBEING, visit_weight=_w("gamers_den")),
    ModuleSpec("greenhouse", "Greenhouse", 8, 1, 16, ModuleType.WORK, visit_weight=_w("greenhouse")),
    ModuleSpec("gym", "Gym", 6, 1, 20, ModuleType.WELLBEING, visit_weight=_w("gym")),
    ModuleSpec("infirmary", "Infirmary", 6, 1, 16, ModuleType.WELLBEING, visit_weight=_w("infirmary")),
    ModuleSpec("large_storage", "Large Storage", 8, 2, 140, ModuleType.STORAGE, visit_weight=_w("large_storage")),
    ModuleSpec("materializer", "Materializer", 4, 3, 24, ModuleType.STORAGE, visit_weight=_w("materializer")),
    ModuleSpec("medium_storage", "Medium Storage", 8, 1, 65, ModuleType.STORAGE, visit_weight=_w("medium_storage")),
    ModuleSpec("park_with_bench", "Park with Bench", 5, 1, 20, ModuleType.WELLBEING, visit_weight=_w("park_with_bench")),
    ModuleSpec("personal_cabin", "Personal Cabin", 3, 1, 10, ModuleType.WELLBEING, visit_weight=_w("personal_cabin")),
    ModuleSpec(
        "radiation_repulsor",
        "Radiation Repulsor",
        2,
        3,
        16,
        ModuleType.UTILITY,
        visit_weight=_w("radiation_repulsor"),
        connection_level=ConnectionLevel.TOP,
        transit_allowed=False,
    ),
    ModuleSpec(
        "rapidium_ark",
        "Rapidium Ark",
        4,
        2,
        32,
        ModuleType.STORAGE,
        visit_weight=_w("rapidium_ark"),
        transit_allowed=False,
    ),
    ModuleSpec("recycler", "Recycler", 2, 1, 2, ModuleType.WELLBEING, visit_weight=_w("recycler")),
    ModuleSpec("refinery", "Refinery", 4, 1, 8, ModuleType.WORK, visit_weight=_w("refinery")),
    ModuleSpec("research_lab", "Research Lab", 4, 1, 8, ModuleType.WORK, visit_weight=_w("research_lab")),
    ModuleSpec("small_storage", "Small Storage", 2, 2, 28, ModuleType.STORAGE, visit_weight=_w("small_storage")),
    ModuleSpec("social_room", "Social Room", 6, 1, 14, ModuleType.WELLBEING, visit_weight=_w("social_room")),
    ModuleSpec("workshop", "Workshop", 4, 1, 8, ModuleType.WORK, visit_weight=_w("workshop")),
)

MODULE_BY_KEY = {m.key: m for m in MODULES}
CONFIGURABLE_MODULES = tuple(m for m in MODULES if m.configurable)
MANDATORY_MODULES = tuple(m for m in MODULES if m.mandatory)
