from __future__ import annotations

import json
from pathlib import Path

from .models import ModuleSpec, ModuleType, PlacementAuthority, floor_ports, top_ports

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
    authority: PlacementAuthority = PlacementAuthority.PLAYER,
    transit_allowed: bool = True,
    top_access: bool = False,
    vertical_connectivity: bool = False,
    max_count: int | None = None,
) -> ModuleSpec:
    ports = top_ports(width, height) if top_access else floor_ports(width)
    return ModuleSpec(
        key=key,
        name=name,
        width=width,
        height=height,
        mass=mass,
        module_type=module_type,
        authority=authority,
        visit_weight=_w(key),
        ports=ports,
        transit_allowed=transit_allowed,
        vertical_connectivity=vertical_connectivity,
        max_count=max_count,
    )


SYSTEM = PlacementAuthority.SYSTEM
SOLVER = PlacementAuthority.SOLVER

MODULES: tuple[ModuleSpec, ...] = (
    _module("airlock", "Airlock", 4, 1, 4, ModuleType.CORE, authority=SYSTEM),
    _module("captains_cabin", "Captain's Cabin", 4, 1, 4, ModuleType.CORE, authority=SYSTEM),
    _module("command_center", "Command Center", 4, 1, 4, ModuleType.CORE, authority=SYSTEM),
    _module(
        "communication_room",
        "Communication Room",
        4,
        1,
        4,
        ModuleType.CORE,
        authority=SYSTEM,
    ),
    _module("kitchen", "Kitchen", 5, 1, 4, ModuleType.CORE, authority=SYSTEM),
    _module("machinery", "Machinery", 4, 1, 4, ModuleType.CORE, authority=SYSTEM),
    _module(
        "quantum_computer",
        "Quantum Computer",
        4,
        2,
        8,
        ModuleType.CORE,
        authority=SYSTEM,
    ),
    _module("womb", "The Womb", 5, 1, 4, ModuleType.CORE, authority=SYSTEM),
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
    _module("park_with_bench", "Park with Bench", 6, 1, 20, ModuleType.WELLBEING),
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
        max_count=5,
    ),
    _module("recycler", "Recycler", 2, 1, 2, ModuleType.WELLBEING, max_count=1),
    _module("refinery", "Refinery", 4, 1, 8, ModuleType.WORK),
    _module("research_lab", "Research Lab", 4, 1, 8, ModuleType.WORK),
    _module("small_storage", "Small Storage", 2, 2, 28, ModuleType.STORAGE),
    _module("social_room", "Social Room", 6, 1, 14, ModuleType.WELLBEING),
    _module("workshop", "Workshop", 4, 1, 8, ModuleType.WORK),
    _module("corridor", "Corridor", 2, 1, 2, ModuleType.UTILITY, authority=SOLVER),
    _module(
        "elevator",
        "Elevator",
        2,
        1,
        2,
        ModuleType.UTILITY,
        authority=SOLVER,
        vertical_connectivity=True,
    ),
)

MODULE_BY_KEY = {module.key: module for module in MODULES}
SYSTEM_MODULES = tuple(
    module for module in MODULES if module.authority is PlacementAuthority.SYSTEM
)
PLAYER_MODULES = tuple(
    module for module in MODULES if module.authority is PlacementAuthority.PLAYER
)
SOLVER_MODULES = tuple(
    module for module in MODULES if module.authority is PlacementAuthority.SOLVER
)

if len(MODULE_BY_KEY) != len(MODULES):
    raise RuntimeError("Module catalog contains duplicate keys")
if set(USAGE_WEIGHTS) != set(MODULE_BY_KEY):
    missing = sorted(set(MODULE_BY_KEY) - set(USAGE_WEIGHTS))
    extra = sorted(set(USAGE_WEIGHTS) - set(MODULE_BY_KEY))
    raise RuntimeError(f"Usage-weight catalog mismatch; missing={missing}, extra={extra}")
