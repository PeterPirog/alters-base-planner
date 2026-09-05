from __future__ import annotations

from .models import ModuleSpec, ModuleType


MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec("airlock", "Airlock", 4, 1, 4, ModuleType.CORE, mandatory=True, configurable=False, visit_weight=10),
    ModuleSpec("captains_cabin", "Captain's Cabin", 4, 1, 4, ModuleType.CORE, mandatory=True, configurable=False, visit_weight=10),
    ModuleSpec("command_center", "Command Center", 4, 1, 4, ModuleType.CORE, mandatory=True, configurable=False, visit_weight=9),
    ModuleSpec("communication_room", "Communication Room", 4, 1, 4, ModuleType.CORE, mandatory=True, configurable=False, visit_weight=5),
    ModuleSpec("machinery", "Machinery", 4, 1, 4, ModuleType.CORE, mandatory=True, configurable=False, visit_weight=6),
    ModuleSpec("quantum_computer", "Quantum Computer", 4, 2, 8, ModuleType.CORE, mandatory=True, configurable=False, visit_weight=4),
    ModuleSpec("womb", "The Womb", 5, 1, 4, ModuleType.WORK, mandatory=True, configurable=False, visit_weight=4),
    ModuleSpec("ark_sarcophagus", "Ark Sarcophagus", 4, 2, 13, ModuleType.STORAGE, visit_weight=1),
    ModuleSpec("contemplation_room", "Contemplation Room", 6, 1, 20, ModuleType.WELLBEING, visit_weight=5),
    ModuleSpec("dormitory", "Dormitory", 6, 1, 40, ModuleType.WELLBEING, visit_weight=7),
    ModuleSpec("gamers_den", "Gamer's Den", 5, 1, 14, ModuleType.WELLBEING, visit_weight=6),
    ModuleSpec("greenhouse", "Greenhouse", 8, 1, 16, ModuleType.WORK, visit_weight=2),
    ModuleSpec("gym", "Gym", 6, 1, 20, ModuleType.WELLBEING, visit_weight=4),
    ModuleSpec("infirmary", "Infirmary", 6, 1, 16, ModuleType.WELLBEING, visit_weight=8),
    ModuleSpec("kitchen", "Kitchen", 5, 1, 4, ModuleType.WORK, visit_weight=7),
    ModuleSpec("large_storage", "Large Storage", 8, 2, 140, ModuleType.STORAGE, visit_weight=0),
    ModuleSpec("materializer", "Materializer", 4, 3, 24, ModuleType.STORAGE, visit_weight=1),
    ModuleSpec("medium_storage", "Medium Storage", 8, 1, 65, ModuleType.STORAGE, visit_weight=0),
    ModuleSpec("park_with_bench", "Park with Bench", 5, 1, 20, ModuleType.WELLBEING, visit_weight=4),
    ModuleSpec("personal_cabin", "Personal Cabin", 3, 1, 10, ModuleType.WELLBEING, visit_weight=4),
    ModuleSpec("radiation_repulsor", "Radiation Repulsor", 2, 3, 16, ModuleType.UTILITY, visit_weight=0),
    ModuleSpec("rapidium_ark", "Rapidium Ark", 4, 2, 32, ModuleType.STORAGE, visit_weight=0),
    ModuleSpec("recycler", "Recycler", 2, 1, 2, ModuleType.WELLBEING, visit_weight=1),
    ModuleSpec("refinery", "Refinery", 4, 1, 8, ModuleType.WORK, visit_weight=2),
    ModuleSpec("research_lab", "Research Lab", 4, 1, 8, ModuleType.WORK, visit_weight=6),
    ModuleSpec("small_storage", "Small Storage", 2, 2, 28, ModuleType.STORAGE, visit_weight=0),
    ModuleSpec("social_room", "Social Room", 6, 1, 14, ModuleType.WELLBEING, visit_weight=8),
    ModuleSpec("workshop", "Workshop", 4, 1, 8, ModuleType.WORK, visit_weight=5),
)

MODULE_BY_KEY = {m.key: m for m in MODULES}
CONFIGURABLE_MODULES = tuple(m for m in MODULES if m.configurable)
MANDATORY_MODULES = tuple(m for m in MODULES if m.mandatory)
