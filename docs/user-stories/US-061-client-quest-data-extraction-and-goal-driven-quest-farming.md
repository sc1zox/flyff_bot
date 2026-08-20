---
id: US-061
title: Client quest data extraction and goal-driven quest farming
status: draft
created: 2026-08-20
updated: 2026-08-20
---

# US-061: Client quest data extraction and goal-driven quest farming

## Story

As a **bot operator pursuing in-game quests**, I want **the application to extract all quest definitions from client archives, allow selecting quests as high-level farming goals in the UI, autonomously navigate to the required mob spawns on the NavMesh, farm the necessary objectives (mob kills and collection drops), and automatically transition to subsequent selected quests upon completion**, so that **I can automate quest fulfillment without manual waypoint configuration or tedious mob quota setup**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Client quest definitions reside inside client archives (`Data/System2/data*.one`, `Data/system3/`, `Data/Lang/`, etc.) declared in `Data/System2/masquerade.prj` (`propQuest.inc`, `propQuest-RequestBox.inc`, `propQuest-Scenario.inc`, `propQuest-RequestBox2.inc`, `propQuest-DungeonandPK.inc`, `QuestDestination.txt.txt`, `propMover.txt`, `Spec_Item.txt`, `textClient.txt`).
- [ADR-005](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md) permits unrestricted read-only static analysis and extraction of local client archives and script files into repository artifacts.
- [ADR-006](../decisions/ADR-006-read-only-process-memory-access.md) permits read-only memory inspection of active player quest structures if live in-memory progress tracking is used.
- Builds on multi-target kill tracking ([US-035](completed/US-035-multi-target-selection-and-per-mob-kill-quotas.md)), vector terrain navigation ([US-045](completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md)), NavMesh foundation ([US-055](completed/US-055-authoritative-3d-world-geometry-and-navmesh-foundation.md)), and NavMesh-aware targeting ([US-058](completed/US-058-navmesh-aware-targeting-and-telemetry-integration.md), [US-059](completed/US-059-authoritative-vector-navigation-legacy-removal-and-multi-zone-selection.md)).

## Acceptance criteria

- [ ] Given an offline or operator-triggered extraction pass against the Entropia client directory, when quest files are indexed and unpacked from client archives, then a complete structured JSON database (`data/quests/quests.json`) is generated containing all parsed quests with IDs, titles, descriptions, categories (Scenario, General, Office, Event, Daily), required monster IDs/names, required kill counts, required item drop IDs/names and quantities, and reward summaries.
- [ ] Given the desktop dashboard UI, when the operator opens the Quest Goals panel, then a searchable and filterable list of extracted quests is displayed (filterable by category, zone, level range, and search query).
- [ ] Given the operator selects one or more quests in the UI and starts farming, when farming begins, then the bot automatically resolves the required target monsters and their corresponding NavMesh spawn zones from the active quest.
- [ ] Given a selected quest requires killing specific monsters or gathering specific item drops, when the bot operates in the spawn zone, then combat execution and kill/loot tracking increment quest progress until the required quota is fulfilled.
- [ ] Given the active quest's requirements are 100% completed, when the goal check runs, then the orchestrator automatically transitions to the next selected quest in the queue, updates the active target monster and NavMesh destination, and navigates to the new spawn area.
- [ ] Given all selected quests in the queue are completed, when the final goal is met, then the farming session enters `FarmingMode.COMPLETED` (or executes the configured completion action).
- [ ] Given no valid spawn zone exists for a required quest mob, when the quest is selected, then the application reports a clear, localized diagnostic status without crashing.
- [ ] All user-visible text is available in German and English.

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
