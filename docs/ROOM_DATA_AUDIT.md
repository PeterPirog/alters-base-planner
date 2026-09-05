# Room data audit

Verification date: 2026-09-06.

This file records the evidence behind the planner's dimensions, masses and default traffic weights.

## Dimension and mass audit

The current catalogue was checked against the current public The Alters module table and individual module pages. The planner dimensions match the current direct module data. The mass values also match except for one known public-source conflict: `Dormitory`.

| Module | Size | Planner mass | Audit status |
|---|---:|---:|---|
| Airlock | 4x1 | 4 | verified |
| Captain's Cabin | 4x1 | 4 | verified |
| Command Center | 4x1 | 4 | verified |
| Communication Room | 4x1 | 4 | verified |
| Kitchen | 5x1 | 4 | verified |
| Machinery | 4x1 | 4 | verified |
| Quantum Computer | 4x2 | 8 | verified |
| The Womb | 5x1 | 4 | verified |
| Ark Sarcophagus | 4x2 | 13 | verified |
| Contemplation Room | 6x1 | 20 | verified |
| Dormitory | 6x1 | 8 | verified from player/in-game reports; Fandom currently conflicts with 40 |
| Gamer's Den | 5x1 | 14 | verified |
| Greenhouse | 8x1 | 16 | verified |
| Gym | 6x1 | 20 | verified |
| Infirmary | 6x1 | 16 | verified |
| Large Storage | 8x2 | 140 | verified |
| Materializer | 4x3 | 24 | verified |
| Medium Storage | 8x1 | 65 | verified |
| Park with Bench | 5x1 | 20 | verified size against current module table; older secondary guide reports 6x1 |
| Personal Cabin | 3x1 | 10 | verified |
| Radiation Repulsor | 2x3 | 16 | verified |
| Rapidium Ark | 4x2 | 32 | verified |
| Recycler | 2x1 | 2 | verified |
| Refinery | 4x1 | 8 | verified |
| Research Lab | 4x1 | 8 | verified |
| Small Storage | 2x2 | 28 | verified |
| Social Room | 6x1 | 14 | verified |
| Workshop | 4x1 | 8 | verified |
| Corridor | 2x1 | 2 | verified |
| Elevator | 2x1 | 2 | verified |

### Dormitory mass conflict

The current Fandom aggregate/direct Dormitory entry displays `Mass 40`, but this is inconsistent with multiple independent sources that describe the in-game Dormitory as mass 8. In particular, a Steam player discussion explicitly compares Personal Cabin mass 10 with Dormitory mass 8, and QM Games also reports Dormitory mass 8. The value 40 on Fandom is identical to the Dormitory's Metals construction cost and is therefore treated as a likely table transcription error unless newer in-game evidence proves otherwise.

Planner decision:

```text
Dormitory mass = 8
```

Do not change this to 40 merely to mirror the current wiki table; first verify against a current in-game build screen or extracted game data.

### Size-source conflicts

Some older/community tables disagree with current direct module pages:

- older Steam community logistics tables have reported `Kitchen 4x1` and `Greenhouse 6x1`;
- QM Games reports `Park with Bench 6x1`;
- the current Fandom module table reports `Kitchen 5x1`, `Greenhouse 8x1`, and `Park with Bench 5x1`.

For current planner geometry the direct/current module data is used. Future clean in-game measurements or extracted data should override public wiki data.

## Public references

- Current module table: https://the-alters.fandom.com/wiki/Modules
- Dormitory: https://the-alters.fandom.com/wiki/Dormitory
- Steam Dormitory mass discussion: https://steamcommunity.com/app/1601570/discussions/0/604160355563785000/
- QM Games room guide: https://quoramarketing.com/the-alters-rooms-guide/
- Kitchen: https://the-alters.fandom.com/wiki/Kitchen
- Greenhouse: https://the-alters.fandom.com/wiki/Greenhouse
- Park with Bench: https://the-alters.fandom.com/wiki/Park_with_Bench
- Research Lab: https://the-alters.fandom.com/wiki/Research_Lab
- Radiation Repulsor: https://the-alters.fandom.com/wiki/Radiation_Repulsor
- Rapidium Ark: https://the-alters.fandom.com/wiki/Rapidium_Ark

## Usage-weight audit

Usage weights are **planner heuristics, not game constants**. They estimate routine physical traffic rather than narrative importance. The previous set was biased toward Jan's manual interactions and underweighted crew traffic.

Recalibrated defaults in `data/usage_weights.json`:

| Room | Weight | Rationale |
|---|---:|---|
| Airlock | 1.00 | dominant surface-trip entry/exit anchor |
| Workshop | 0.90 | repeated crafting plus long staffed shifts |
| Kitchen | 0.80 | recurring crew food/canteen routine |
| Dormitory | 0.80 | repeated daily sleeping traffic for up to 4 Alters |
| Captain's Cabin | 0.70 | Jan's regular end-day/sleep route |
| Research Lab | 0.65 | long Scientist work shifts when research is active |
| Social Room | 0.60 | recurring group free-time activities |
| Greenhouse | 0.55 | long staffed production shifts |
| Refinery | 0.55 | long staffed production shifts |
| Command Center | 0.35 | important but episodic building/journey interaction |
| Machinery | 0.35 | recurring but partly assignable/automatable technical work |
| Communication Room | 0.25 | story/event-driven calls |
| Infirmary | 0.25 | intermittent Doctor/patient traffic |
| Contemplation Room | 0.25 | situational wellbeing/therapy traffic |
| Personal Cabin | 0.25 | repeated sleep traffic, but only one Alter per cabin |
| Gym | 0.20 | optional free-time use |
| Gamer's Den | 0.20 | optional recreation |
| Park with Bench | 0.15 | optional low-frequency recreation |
| Materializer | 0.10 | episodic late-game mission use |
| Quantum Computer | 0.10 | critical but physically visited at discrete progression points |
| The Womb | 0.10 | Alter-creation/story use only |
| Recycler | 0.00 | passive |
| Radiation Repulsor | 0.00 | passive |
| Storage modules | 0.00 | no routine physical entry required |
| Rapidium Ark / Ark Sarcophagus | 0.00 | passive/terminal mission storage |

Key evidence used for ranking:

- Alters normally work 09:00-21:00 and can be assigned to Workshop, Greenhouse, Refinery, Research Lab and Infirmary; these rooms can therefore generate sustained daily traffic.
- Dormitory provides four beds and Personal Cabin one bed, so sleep modules create recurring traffic.
- Social Room supports repeated free-time activities such as beer pong and movies.
- Command Center and Communication Room are important but episodic rather than continuous work destinations.
- Storage, Recycler and Radiation Repulsor are passive from a movement-optimization perspective.

References:

- Assignments/work hours: https://www.neoseeker.com/the-alters/The_Alters_and_Their_Features
- Base layout/room roles: https://www.gamepressure.com/the-alters/base-layout-and-the-best-rooms/z6119ef
- Base-building mechanics: https://www.neoseeker.com/the-alters/Base_Building_Mechanics_and_Tips
- Current module descriptions: https://the-alters.fandom.com/wiki/Modules

The weights remain intentionally editable. A future empirical mode should calibrate them from measured room-transition counts from one or more full playthroughs.
