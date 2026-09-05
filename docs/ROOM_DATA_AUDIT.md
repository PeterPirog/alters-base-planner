# Room data audit

Verification date: 2026-09-06.

This file records the evidence behind the planner's room dimensions and default traffic weights.

## Dimension audit

The current `catalog.py` dimensions were checked against the current The Alters Wiki module table and individual module pages. The catalogue is internally consistent with the current direct module pages, so **no room-size code changes were required in this audit**.

| Module | Planner size | Verification |
|---|---:|---|
| Airlock | 4x1 | verified |
| Captain's Cabin | 4x1 | verified |
| Command Center | 4x1 | verified |
| Communication Room | 4x1 | verified |
| Kitchen | 5x1 | verified; conflicting older/community table exists |
| Machinery | 4x1 | verified |
| Quantum Computer | 4x2 | verified |
| The Womb | 5x1 | verified |
| Ark Sarcophagus | 4x2 | verified |
| Contemplation Room | 6x1 | verified |
| Dormitory | 6x1 | verified |
| Gamer's Den | 5x1 | verified |
| Greenhouse | 8x1 | verified; conflicting older/community table exists |
| Gym | 6x1 | verified |
| Infirmary | 6x1 | verified |
| Large Storage | 8x2 | verified |
| Materializer | 4x3 | verified |
| Medium Storage | 8x1 | verified |
| Park with Bench | 5x1 | verified; one secondary guide reports 6x1 |
| Personal Cabin | 3x1 | verified |
| Radiation Repulsor | 2x3 | verified |
| Rapidium Ark | 4x2 | verified |
| Recycler | 2x1 | verified |
| Refinery | 4x1 | verified |
| Research Lab | 4x1 | verified |
| Small Storage | 2x2 | verified |
| Social Room | 6x1 | verified |
| Workshop | 4x1 | verified |
| Corridor | 2x1 | verified |
| Elevator | 2x1 | verified |

### Source conflicts

Some community tables disagree with the current direct module pages:

- Steam community logistics table (Patch 1.4) reports `Kitchen 4x1` and `Greenhouse 6x1`.
- QM Games reports `Park with Bench 6x1`.
- Current direct The Alters Wiki pages and the current aggregate Modules table report `Kitchen 5x1`, `Greenhouse 8x1`, and `Park with Bench 5x1`.

For planner geometry, the direct current module pages are treated as the primary public reference. If future game data or a clean in-game measurement disproves one of these values, change `catalog.py` and add a regression test.

## Public references

- Current module table: https://the-alters.fandom.com/wiki/Modules
- Kitchen: https://the-alters.fandom.com/wiki/Kitchen
- Greenhouse: https://the-alters.fandom.com/wiki/Greenhouse
- Park with Bench: https://the-alters.fandom.com/wiki/Park_with_Bench
- Workshop: https://the-alters.fandom.com/wiki/Workshop
- Research Lab: https://the-alters.fandom.com/wiki/Research_Lab
- Refinery: https://the-alters.fandom.com/wiki/Refinery
- Dormitory: https://the-alters.fandom.com/wiki/Dormitory
- Social Room: https://the-alters.fandom.com/wiki/Social_Room
- Gym: https://the-alters.fandom.com/wiki/Gym
- Infirmary: https://the-alters.fandom.com/wiki/Infirmary
- Contemplation Room: https://the-alters.fandom.com/wiki/Contemplation_Room
- Personal Cabin: https://the-alters.fandom.com/wiki/Personal_Cabin
- Gamer's Den: https://the-alters.fandom.com/wiki/Gamer%27s_Den
- Radiation Repulsor: https://the-alters.fandom.com/wiki/Radiation_Repulsor
- Rapidium Ark: https://the-alters.fandom.com/wiki/Rapidium_Ark
- Ark Sarcophagus: https://the-alters.fandom.com/wiki/Ark_Sarcophagus
- Materializer: https://the-alters.fandom.com/wiki/Materializer
- Medium Storage: https://the-alters.fandom.com/wiki/Medium_Storage
- Large Storage: https://the-alters.fandom.com/wiki/Large_Storage
- Small Storage: https://the-alters.fandom.com/wiki/Small_Storage
- Recycler: https://the-alters.fandom.com/wiki/Recycler
- Corridor: https://the-alters.fandom.com/wiki/Corridor
- Community Patch 1.4 logistics table: https://steamcommunity.com/sharedfiles/filedetails/?id=3509116215
- QM Games room guide: https://quoramarketing.com/the-alters-rooms-guide/

## Usage-weight audit

Usage weights are **planner heuristics, not game constants**. The objective needs an estimate of how much physical traffic each room generates. The previous weights were biased toward Jan's direct interactions and underweighted daily Alter traffic. In particular, Dormitory, Kitchen, Greenhouse and Refinery were too low, while Command Center and Machinery were too high for a routine-traffic model.

The recalibrated defaults in `data/usage_weights.json` use the following hierarchy:

1. mandatory/repeated movement anchor: Airlock;
2. repeated crafting/daily crew routine: Workshop, Kitchen, Dormitory;
3. daily or long-shift staffed rooms: Captain's Cabin, Research Lab, Social Room, Greenhouse, Refinery;
4. episodic technical/story rooms: Command Center, Machinery, Communication Room, Infirmary;
5. optional wellbeing rooms: Contemplation Room, Personal Cabin, Gym, Gamer's Den, Park;
6. rare story modules: Materializer, Quantum Computer, The Womb;
7. passive modules: Recycler, Radiation Repulsor, Storage, Rapidium Ark, Ark Sarcophagus = 0.

Key gameplay evidence:

- Alters normally work 09:00-21:00 and can be assigned to Workshop, Greenhouse, Refinery, Research Lab and Infirmary; specialist Alters receive bonuses or exclusive access in these rooms.
- Dormitory provides four beds; Personal Cabin provides one bed.
- Social Room supports repeated free-time activities such as beer pong and movies.
- Command Center is used for base building/expansion/navigation, so it is important but episodic rather than a daily work station.
- Machinery handles the radiation barrier and technical interactions, but maintenance/filter work can be assigned or automated.
- Storage and Recycler are passive and do not require routine physical entry.

References:

- Assignments/work hours: https://www.neoseeker.com/the-alters/The_Alters_and_Their_Features
- Base-layout guidance and room roles: https://www.gamepressure.com/the-alters/base-layout-and-the-best-rooms/z6119ef
- Base-building mechanics: https://www.neoseeker.com/the-alters/Base_Building_Mechanics_and_Tips
- Social Room behavior: https://the-alters.fandom.com/wiki/Social_Room
- Command Center behavior: https://the-alters.fandom.com/wiki/Command_Center
- Machinery behavior: https://the-alters.fandom.com/wiki/Machinery

The weights should remain user-editable. Future empirical calibration could log actual room transitions from a full playthrough and normalize measured visits instead of using gameplay-informed estimates.
