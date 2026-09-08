from __future__ import annotations

import json
from pathlib import Path

from .models import ModuleSpec, ModuleType, floor_ports, top_ports

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


def _module(
    key: str,
    name: str,
    width: int,
    height: int,
    mass: int,
    module_type: ModuleType,
    *,
    mandatory: bool = False,
    configurable: bool = True,
    transit_allowed: bool = True,
    top_access: bool = False,
    max_count: int | None = None,
) -> ModuleSpec:
    # Standard LEFT/RIGHT floor ports are derived directly from room width:
    # LEFT=(0,0), RIGHT=(width-1,0). Only verified exceptions need height.
    ports = top_ports(width, height) if top_access else floor_ports(width)
    return ModuleSpec(
        key,
        name,
        width,
        height,
        mass,
        module_type,
        mandatory=mandatory,
        configurable=configurable,
        visit_weight=_w(key),
        ports=ports,
        transit_allowed=transit_allowed,
        max_count=max_count,
    )


MODULES: tuple[ModuleSpec, ...] = (
    _module("airlock", "Airlock", 4, 1, 4, ModuleType.CORE, mandatory=True, configurable=False),
    _module("captains_cabin", "Captain's Cabin", 4, 1, 4, ModuleType.CORE, mandatory=True, configurable=False),
    _module("command_center", "Command Center", 4, 1, 4, ModuleType.CORE, mandatory=True, configurable=False),
    _module("communication_room", "Communication Room", 4, 1, 4, ModuleType.CORE, mandatory=True, configurable=False),
    _module("kitchen", "Kitchen", 5, 1, 4, ModuleType.WORK, mandatory=True, configurable=False),
    _module("machinery", "Machinery", 4, 1, 4, ModuleType.CORE, mandatory=True, configurable=False),
    _module("quantum_computer", "Quantum Computer", 4, 2, 8, ModuleType.CORE, mandatory=True, configurable=False),
    _module("womb", "The Womb", 5, 1, 4, ModuleType.WORK, mandatory=True, configurable=False),
    _module("ark_sarcophagus", "Ark Sarcophagus", 4, 2, 13, ModuleType.STORAGE),
    _module("contemplation_room", "Contemplation Room", 6, 1, 20, ModuleType.WELLBEING),
    _module("dormitory", "Dormitory", 6, 1, 8, ModuleType.WELLBEING),
    _module("gamers_den", "Gamer's Den", 5, 1, 14, ModuleType.WELLBEING),
    _module("greenhouse", "Greenhouse", 8, 1, 16, ModuleType.WORK),
    _module("gym", "Gym", 6, 1, 20, ModuleType.WELLBEING),
    _module("infirmary", "Infirmary", 6, 1, 16, ModuleType.WELLBEING),
    _module("large_storage", "Large Storage", 8, 2, 140, ModuleType.STORAGE),
    _module("materializer", "Materializer", 4, 3, 24, ModuleType.STORAGE),
    _module("medium_storage", "Medium Storage", 8, 1, 65, ModuleType.STORAGE),
    _module("park_with_bench", "Park with Bench", 5, 1, 20, ModuleType.WELLBEING),
    _module("personal_cabin", "Personal Cabin", 3, 1, 10, ModuleType.WELLBEING),
    _module(
        "radiation_repulsor",
        "Radiation Repulsor",
        2,
        3,
        16,
        ModuleType.UTILITY,
        transit_allowed=False,
        top_access=True,
    ),
    _module(
        "rapidium_ark",
        "Rapidium Ark",
        4,
        2,
        32,
        ModuleType.STORAGE,
        transit_allowed=False,
    ),
    _module("recycler", "Recycler", 2, 1, 2, ModuleType.WELLBEING, max_count=1),
    _module("refinery", "Refinery", 4, 1, 8, ModuleType.WORK),
    _module("research_lab", "Research Lab", 4, 1, 8, ModuleType.WORK),
    _module("small_storage", "Small Storage", 2, 2, 28, ModuleType.STORAGE),
    _module("social_room", "Social Room", 6, 1, 14, ModuleType.WELLBEING),
    _module("workshop", "Workshop", 4, 1, 8, ModuleType.WORK),
)

MODULE_BY_KEY = {m.key: m for m in MODULES}
CONFIGURABLE_MODULES = tuple(m for m in MODULES if m.configurable)
MANDATORY_MODULES = tuple(m for m in MODULES if m.mandatory)
