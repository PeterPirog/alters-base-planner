# Room data audit

Verification date: 2026-09-08.

This file records the evidence behind the planner's dimensions, masses, connectivity behavior, count limits and default traffic weights.

## Dimension and mass audit

The current catalogue was checked against the current public The Alters module table and independent room guides. The planner dimensions match the strongest current direct module data. The mass values also match except for one known public-source conflict: `Dormitory`.

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
| Dormitory | 6x1 | 8 | verified from independent guides/player reports; current Fandom aggregate conflicts with 40 |
| Gamer's Den | 5x1 | 14 | verified |
| Greenhouse | 8x1 | 16 | verified |
| Gym | 6x1 | 20 | verified |
| Infirmary | 6x1 | 16 | verified |
| Large Storage | 8x2 | 140 | verified |
| Materializer | 4x3 | 24 | verified |
| Medium Storage | 8x1 | 65 | verified |
| Park with Bench | 5x1 | 20 | current direct module page/table; secondary guides conflict with 6x1 |
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

The current Fandom aggregate/direct Dormitory entry displays `Mass 40`, but this is inconsistent with multiple independent sources that describe the in-game Dormitory as mass 8. The value 40 is also identical to the Dormitory's Metals construction cost and is therefore treated as a likely table transcription error unless newer in-game evidence proves otherwise.

Planner decision:

```text
Dormitory mass = 8
```

Do not change this to 40 merely to mirror the current wiki aggregate; first verify against a current in-game build screen or extracted game data.

### Size-source conflicts

Some older/community tables disagree with the current direct module pages:

- older Steam logistics tables have reported `Kitchen 4x1` and `Greenhouse 6x1`;
- QM Games / DigitalPhablet currently report `Park with Bench 6x1`;
- the current direct Fandom module table/page reports `Kitchen 5x1`, `Greenhouse 8x1`, and `Park with Bench 5x1`.

For current planner geometry the direct/current module data is used. Future clean in-game measurements or extracted data should override public wiki data.

## Connectivity and transit audit

Connectivity is a hard gameplay rule and must remain independent of traffic weights.

### Standard access ports

Current room-layout guides consistently describe ordinary modules as connecting horizontally at their lower-left and lower-right corners. The planner therefore derives normal local ports directly from width:

```text
LEFT  = (0, 0)
RIGHT = (W - 1, 0)
```

where local `y=0` is the room floor.

### Radiation Repulsor

The current direct module page explicitly states that, unlike most multi-floor modules, Radiation Repulsor connects at the **top**, not the bottom. A detailed Steam optimization guide independently describes Radiation Repulsor as `Blocks Traffic`.

Planner decision:

```text
top_access = true
transit_allowed = false
```

This exception materially affects legal routing and must not be approximated as an ordinary floor-access transit room.

### Rapidium Ark

Player reports consistently distinguish two rules:

1. Rapidium Ark must still be connected to the Base like other modules;
2. the player cannot walk through it, so it cannot be used as a bridge to modules on the opposite side.

Planner decision:

```text
standard floor ports
transit_allowed = false
still subject to Airlock-rooted connectivity
```

The hard connectivity validator therefore requires at least one Ark port to be reachable from Airlock, while the path graph deliberately has no internal LEFT-to-RIGHT edge for the Ark.

### Corridor and Elevator

Current module tables/guides agree that both occupy `2x1` and have mass `2`. Corridor provides horizontal connection. Elevator is the vertical travel module and connects stacked levels. They remain solver-managed: the player does not provide their counts.

## Progression-dependent mandatory state

Public sources distinguish modules that exist from the initial Base from modules that become non-removable or story-required later. For example, current sources agree that Rapidium Ark becomes non-recyclable once built, while player reports also describe Kitchen and The Womb as non-removable after their story introduction.

The current planner intentionally uses a **single planning baseline** rather than an Act/progression-state model. `mandatory=True` should therefore be read as a planner-baseline requirement, not a claim that the module exists at minute zero of every playthrough.

A future progression-aware planner should replace this static assumption with explicit game-state input such as `act`, unlocked modules and already-built non-recyclable modules. Until that exists, changing mandatory flags from mixed public descriptions risks making the baseline less useful without actually modeling progression correctly.

## Module-count limits

Count ceilings are hard gameplay rules only when sufficiently verified. They are represented by `ModuleSpec.max_count`; `None` means that the planner deliberately has no verified static hard ceiling, not that the game necessarily allows an unlimited number.

Current decisions:

| Module | Planner max_count | Decision |
|---|---:|---|
| Recycler | 1 | enforced; current direct page states only one can be built for the base |
| Rapidium Ark | none | direct source confirms tier limits; secondary guides report one per Base Expansion / maximum five, but the exact tier-to-count mapping is not represented by the current request model |
| Radiation Repulsor | none | no universal static ceiling encoded; guides discuss scaling count with Base size rather than one simple global limit |

For Rapidium Ark, a single scalar `max_count` would be the wrong abstraction if the limit depends on progression/Base expansion. The correct future implementation is a tier/progression-dependent bound, not an invented universal number.

## Public references

- Current module table: https://the-alters.fandom.com/wiki/Modules
- Dormitory: https://the-alters.fandom.com/wiki/Dormitory
- Current broad room/connectivity guide: https://digitalphablet.com/completing-room-modules-in-the-alters-a-guide-to-solving-them/
- QM Games room guide: https://quoramarketing.com/the-alters-rooms-guide/
- Park with Bench: https://the-alters.fandom.com/wiki/Park_with_Bench
- Radiation Repulsor direct page: https://the-alters.fandom.com/wiki/Radiation_Repulsor
- Steam optimization guide (Repulsor blocks traffic): https://steamcommunity.com/sharedfiles/filedetails/?id=3512111380
- Rapidium Ark direct page: https://the-alters.fandom.com/wiki/Rapidium_Ark
- Rapidium Ark connectivity/non-transit discussion: https://steamcommunity.com/app/1601570/discussions/0/604159978054415163/
- Recycler: https://the-alters.fandom.com/wiki/Recycler

## Usage-weight audit

Usage weights are **planner heuristics, not game constants**. They estimate routine physical traffic rather than narrative importance.

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
| Radiation Repulsor | 0.00 | passive and blocks traffic |
| Storage modules | 0.00 | no routine physical entry required |
| Rapidium Ark / Ark Sarcophagus | 0.00 | passive/terminal mission storage |

A weight of zero affects only the soft objective pair set. It does not waive placement, port, connectivity, mass or other hard constraints.

Key evidence used for ranking:

- Alters normally work 09:00-21:00 and can be assigned to Workshop, Greenhouse, Refinery, Research Lab and Infirmary; these rooms can therefore generate sustained daily traffic.
- Dormitory provides four beds and Personal Cabin one bed, so sleep modules create recurring traffic.
- Social Room supports repeated free-time activities such as beer pong and movies.
- Command Center and Communication Room are important but episodic rather than continuous work destinations.
- Storage, Recycler and Radiation Repulsor are passive from a movement-objective perspective.

References:

- Assignments/work hours: https://www.neoseeker.com/the-alters/The_Alters_and_Their_Features
- Base layout/room roles: https://www.gamepressure.com/the-alters/base-layout-and-the-best-rooms/z6119ef
- Current module descriptions: https://the-alters.fandom.com/wiki/Modules

The weights remain intentionally editable. A future empirical mode should calibrate them from measured room-transition counts from one or more full playthroughs.
