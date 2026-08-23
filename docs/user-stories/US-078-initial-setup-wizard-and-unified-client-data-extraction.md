---
id: US-078
title: Initial setup wizard, unified client data extraction, and memory profile generation
status: draft
created: 2026-08-23
updated: 2026-08-23
---

# US-078: Initial setup wizard, unified client data extraction, and memory profile generation

## Story

As a **bot operator setting up or updating the application**, I want **a guided initial setup wizard and one-click unified client extraction process with live progress reporting that extracts all static client data into a portable dataset with a machine-readable manifest and automatically initializes the exact client-memory profile on first launch after the client path is supplied**, so that **all game regions, NavMeshes, quests, dungeons, movers, items, skills, NPCs, and memory-based player stats are permanently available offline across all bot features without brittle visual fallbacks or requiring the client installation on secondary machines**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Client files reside in an operator-specified directory (e.g. `Entropia/` containing `neuz.exe` and `Data/`).
- The operator explicitly selects or enters the installation path; the application does not assume hardcoded locations.
- Static file extraction is authorized by [ADR-005](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md) and read-only process memory by [ADR-006](../decisions/ADR-006-read-only-process-memory-access.md). The client installation remains strictly read-only.
- Consolidated superset of static client data extraction capabilities ([US-045](completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md), [US-052](completed/US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md), [US-055](completed/US-055-authoritative-3d-world-geometry-and-navmesh-foundation.md), [US-061](completed/US-061-client-quest-data-extraction-and-goal-driven-quest-farming.md), [US-063](US-063-client-dungeon-data-and-live-cooldown-memory-extraction.md), superseding [US-075](obsolete/US-075-portable-client-static-data-extraction.md)) and fingerprinted client memory readers ([US-076](US-076-complete-client-player-stats-reader.md)).
- On application launch, the desktop dashboard checks if required extracted datasets (`data/navigation/worlds/`, `data/quests/quests.json`, `data/dungeons/dungeons.json`) and memory profile configurations (`data/config/client_player_stats_profiles.json`) exist. If missing, the setup wizard opens automatically.
- No visual fallback is used for player vital statistics: once the profile is initialized from the client binary, live player statistics are sourced authoritatively via `LivePlayerStatsReader`.
- Operators can also re-trigger the unified extraction wizard at any time via a dedicated UI action in the settings / menu.
- Extraction runs asynchronously in a dedicated worker thread, emitting granular progress signals (overall progress percentage, current task/region, item counts) without freezing the PySide6 UI event loop.
- All non-critical errors, malformed tables, or missing sub-records are collected as typed diagnostics and presented to the operator in a detailed summary report and written to the machine-readable dataset manifest.
- The resulting extracted directory is fully portable: copying the dataset to another PC allows the bot to run offline without requiring the client installation on that machine.

## Acceptance criteria

- [ ] Given the application starts with missing extracted datasets or missing memory profiles, when the main window initializes, then it automatically prompts the operator and launches the Initial Setup Wizard.
- [ ] Given the operator opens the dashboard, when selecting the manual re-extraction action from the menu or settings, then the extraction wizard dialog opens.
- [ ] Given the setup wizard is open, when the operator selects an Entropia client directory using a folder picker or text path, then the app validates the presence of essential client structure (including `neuz.exe` and `Data/`) before proceeding.
- [ ] Given valid client files, when extraction starts, then a unified background worker executes all extraction passes sequentially:
  - Phase 1: Mover and static item tables:
    - `propMover.txt` (combat stats, movement, resistances, EXP/FXP, killability, and AI references);
    - `PropMoverEx.inc` (drop items, drop counts, gold ranges, item limits, and drop chances);
    - `propSkill.txt` and `propSkillAdd.csv` (skills, skill levels, requirements, ranges, timing, costs, effects, prerequisites, motions, icons);
    - `Spec_Item.txt` (item properties, localized text links, crafting, exchange, upgrade, set-effects, pet tables).
  - Phase 2: Quests and NPC locations:
    - `propQuest*.inc` and `QuestDestination.txt.txt` (quest definitions, objectives, steps, ground destination bindings);
    - `character.inc` and dialog catalogs (NPC identities, names, menu actions, shop entries, dialog references).
  - Phase 3: Dungeons and instances:
    - `propDungeon*.inc` (dungeon definitions, tier constraints, entry requirements, instance structures).
  - Phase 4: World regions, terrain heightfields, spawn zones, and NavMesh generation:
    - `.wld`, `.lnd`, `.rgn`, `.dyo` (terrain elevation heightfields, static object collision bounds, 7,300+ respawn zone bounding boxes, and baked NavMeshes for Madrigal, Aurania, Eden, Kebaras, and dungeons).
  - Phase 5: Client executable fingerprinting and memory profile generation:
    - calculates SHA-256 of `neuz.exe`, verifies binary architecture (x86/x64), and writes/updates `data/config/client_player_stats_profiles.json` (along with camera/dungeon/position profiles if missing) with exact proven offsets so `LivePlayerStatsReader` is fully initialized and operational without requiring visual fallbacks.
  - Phase 6: Machine-readable dataset manifest and portability:
    - generates `manifest.json` containing schema versions, relative table names, record counts, typed warnings, client executable SHA-256 digest, and UTC timestamps;
    - ensures the generated dataset directory can be copied to another PC and loaded without requiring the game client.
- [ ] Given the worker is running, when progress updates occur, then the wizard updates a smooth overall progress bar, stage description, and detailed sub-task status without blocking the UI thread.
- [ ] Given extraction completes, when the summary screen is presented, then it lists total extracted counts (worlds, quests, dungeons, monsters, items, skills, NPCs, verified memory profile) and displays any warnings or skipped tables.
- [ ] Given a non-critical error occurs on an individual file or table, when the worker encounters it, then it records a typed diagnostic, displays it in the completion summary, records it in `manifest.json`, and continues extracting unaffected data.
- [ ] Given the operator cancels extraction mid-run, when cancellation is confirmed, then the worker cleanly aborts subsequent stages, leaves partial artifacts marked incomplete, and restores UI responsiveness.
- [ ] Given extraction has succeeded once, when the application is restarted, then all extracted data and memory profiles are immediately available offline across Quest, Navigation, Dungeon, and Player Stats panels without re-extracting.
- [ ] All user-visible text is available in German and English.

## Out of scope

- YOLO model retraining or modifying visual mob detection pipeline.
- Committing raw client assets, archives, executables, textures, or sounds to Git.
- Modifying, patching, or writing files into the game client folder.
- Dynamic runtime memory injection, code hooking, or anti-cheat tampering.
- Visual/OCR fallback for player statistics.

## Verification

- Automated:
  - Unit tests for setup wizard controller and unified extraction orchestrator using synthetic client folder fixtures.
  - Verification of executable SHA-256 fingerprinting and `client_player_stats_profiles.json` profile initialization.
  - Verification of table extraction across movers, items, skills, NPCs, quests, dungeons, worlds, and `manifest.json` generation.
  - Verification of background worker progress reporting, error aggregation, and cancellation handling.
  - Verification of first-run detector logic when datasets and profiles are missing vs. present.
  - Verification of portable dataset loading from a copied output directory.
  - Localization parity tests (`de.json` and `en.json`).
  - `./scripts/check.ps1` passes.
- Manual (Windows):
  - Launch app with empty `data/navigation/worlds/`, `data/quests/`, or `data/config/` and verify the Setup Wizard appears.
  - Select real local `Entropia` folder, execute full extraction, observe progress bar and sub-task status.
  - Verify Madrigal, Aurania, Eden, Quests, Dungeons, Mover tables, Skills, Items, NPCs, `manifest.json`, and `client_player_stats_profiles.json` are fully extracted and loaded in UI panels.
  - Verify dashboard immediately displays live player stats directly from `neuz.exe` via memory reader without OCR/pixel fallback.
  - Copy extracted dataset directory to a secondary location/PC and confirm offline operation without client directory.
  - Test cancellation and error reporting with corrupted or partial client directories.
