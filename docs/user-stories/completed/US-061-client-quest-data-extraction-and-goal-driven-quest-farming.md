---
id: US-061
title: Client quest data extraction and goal-driven quest farming
status: completed
created: 2026-08-20
updated: 2026-08-21
---

# US-061: Client quest data extraction and goal-driven quest farming

## Story

As a **bot operator pursuing in-game quests**, I want **the application to extract all quest definitions from client archives, allow selecting quests as high-level farming goals in the UI, autonomously navigate to the required mob spawns on the NavMesh, farm the necessary objectives (mob kills and collection drops), and automatically transition to subsequent selected quests upon completion**, so that **I can automate quest fulfillment without manual waypoint configuration or tedious mob quota setup**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Client quest definitions reside inside client archives (`Data/System2/data*.one`, `Data/system3/`, `Data/Lang/`, etc.) declared in `Data/System2/masquerade.prj` (`propQuest.inc`, `propQuest-RequestBox.inc`, `propQuest-Scenario.inc`, `propQuest-RequestBox2.inc`, `propQuest-DungeonandPK.inc`, `QuestDestination.txt.txt`, `propMover.txt`, `Spec_Item.txt`, `textClient.txt`).
- [ADR-005](../../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md) permits unrestricted read-only static analysis and extraction of local client archives and script files into repository artifacts.
- [ADR-006](../../decisions/ADR-006-read-only-process-memory-access.md) permits read-only memory inspection of active player quest structures if live in-memory progress tracking is used.
- Builds on multi-target kill tracking ([US-035](US-035-multi-target-selection-and-per-mob-kill-quotas.md)), vector terrain navigation ([US-045](US-045-vector-world-terrain-extraction-and-goal-navigation.md)), NavMesh foundation ([US-055](US-055-authoritative-3d-world-geometry-and-navmesh-foundation.md)), and NavMesh-aware targeting ([US-058](US-058-navmesh-aware-targeting-and-telemetry-integration.md), [US-059](US-059-authoritative-vector-navigation-legacy-removal-and-multi-zone-selection.md)).

## Acceptance criteria

- [x] Given an offline or operator-triggered extraction pass against the Entropia client directory, when quest files are indexed and unpacked from client archives, then a complete structured JSON database (`data/quests/quests.json`) is generated containing all parsed quests with IDs, titles, descriptions, categories (Scenario, General, Office, Event, Daily), required monster IDs/names, required kill counts, required item drop IDs/names and quantities, and reward summaries.
- [x] Given the desktop dashboard UI, when the operator opens the Quest Goals panel, then a searchable and filterable list of extracted quests is displayed (filterable by category, zone, level range, and search query).
- [x] Given the operator selects one or more quests in the UI and starts farming, when farming begins, then the bot automatically resolves the required target monsters and their corresponding NavMesh spawn zones from the active quest.
- [x] Given a selected quest requires killing specific monsters or gathering specific item drops, when the bot operates in the spawn zone, then combat execution and kill/loot tracking increment quest progress until the required quota is fulfilled.
- [x] Given the active quest's requirements are 100% completed, when the goal check runs, then the orchestrator automatically transitions to the next selected quest in the queue, updates the active target monster and NavMesh destination, and navigates to the new spawn area.
- [x] Given all selected quests in the queue are completed, when the final goal is met, then the farming session enters `FarmingMode.COMPLETED` (or executes the configured completion action).
- [x] Given no valid spawn zone exists for a required quest mob, when the quest is selected, then the application reports a clear, localized diagnostic status without crashing.
- [x] All user-visible text is available in German and English.

## Out of scope

- Automated NPC dialogue interaction, quest acceptance from NPCs, or turning in finished quests at NPCs (deferred to US-062).
- Memory writing, packet manipulation, or code injection.

## Verification

- Automated:
  - Unit tests for archive quest extractor and `propQuest.inc` parser decoding synthetic archives and text files into structured models.
  - Unit tests for quest goal resolver mapping quest requirements to monster IDs and NavMesh spawn zones.
  - Unit tests for sequential multi-quest queue progression and goal completion transitions.
- Manual (Windows):
  - Run quest extraction against local Entropia client files and verify `data/quests/quests.json` is generated.
  - In the dashboard UI, select multiple quests (e.g. Aurania Daily Quests), start farming, and observe autonomous navigation to mob zones, kill progression, and automatic switching to the next quest upon completion.

## Implementation notes

- All quest data is packed in the *keyed* archive generation `docs/wiki/architecture.md` describes,
  which US-052 previously reported as `UNSUPPORTED_ARCHIVE_INDEX`. Its index layout, salted
  name digest, and payload keystream were recovered for this story and are recorded in
  [the 2026-08-21 static analysis](../../sources/2026-08-21-entropia-keyed-archive-and-quest-data-analysis.md).
  `navigation.client_archive` reads both generations; the world extractor path is unchanged.
- The client does not ship the `MI_*` to numeric monster-id table, so a quest's monsters are bound
  to spawn zones by display name, by the numeric identifier when a quest states one directly, and
  by proximity to the coordinates the quest script itself names.
- A collection objective is farmed as kills of the drop sources the quest declares, because a
  verified kill is the smallest unit of progress a session observes without a loot feed attached
  (US-025). Item counts themselves still need an explicitly attached loot feed.
- Category, area, level range, and free-text filters are provided. The area filter is the quest's
  own group heading, which this client populates with region names (`Flaris`, `Saintmorning`, ...).
- Against the operator's own installation the pass produced 1,434 quests, 563 of them farmable, with
  no extraction diagnostics.
- Gate on 2026-08-21: 674 passed, 2 skipped, 89.22% coverage. The manual Windows walkthrough is
  outstanding; the automated result does not stand in for it.
