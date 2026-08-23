---
id: US-078
title: Initial setup wizard, unified client data extraction, and memory profile generation
status: draft
created: 2026-08-23
updated: 2026-08-23
---

# US-078: Initial setup wizard, unified client data extraction, and memory profile generation

## Story

As a **bot operator setting up or updating the application**, I want **a guided initial setup wizard and one-click unified client extraction process with live progress reporting that also automatically initializes the exact client-memory profile on first launch after the client path is supplied**, so that **all game regions, NavMeshes, quests, dungeons, mover tables, and memory-based player stats are permanently available offline without brittle visual fallbacks**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Client files reside in an operator-specified directory (e.g. `Entropia/` containing `neuz.exe` and `Data/`).
- The operator explicitly selects or enters the installation path; the application does not assume hardcoded locations.
- Static file extraction is authorized by [ADR-005](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md) and read-only process memory by [ADR-006](../decisions/ADR-006-read-only-process-memory-access.md). The client installation remains strictly read-only.
- Builds on static client data extraction capabilities ([US-045](completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md), [US-052](completed/US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md), [US-055](completed/US-055-authoritative-3d-world-geometry-and-navmesh-foundation.md), [US-061](completed/US-061-client-quest-data-extraction-and-goal-driven-quest-farming.md), [US-063](US-063-client-dungeon-data-and-live-cooldown-memory-extraction.md), [US-075](US-075-portable-client-static-data-extraction.md)) and fingerprinted client memory readers ([US-076](US-076-complete-client-player-stats-reader.md)).
- On application launch, the desktop dashboard checks if required extracted datasets (`data/navigation/worlds/`, `data/quests/quests.json`, `data/dungeons/dungeons.json`) and memory profile configurations (`data/config/client_player_stats_profiles.json`) exist. If missing, the setup wizard opens automatically.
- No visual fallback is used for player vital statistics: once the profile is initialized from the client binary, live player statistics are sourced authoritatively via `LivePlayerStatsReader`.
- Operators can also re-trigger the unified extraction wizard at any time via a dedicated UI action in the settings / menu.
- Extraction runs asynchronously in a dedicated worker thread, emitting granular progress signals (overall progress percentage, current task/region, item counts) without freezing the PySide6 UI event loop.
- All non-critical errors, malformed tables, or missing sub-records are collected as typed diagnostics and presented to the operator in a detailed summary report.

## Acceptance criteria

- [ ] Given the application starts with missing extracted datasets or missing memory profiles, when the main window initializes, then it automatically prompts the operator and launches the Initial Setup Wizard.
- [ ] Given the operator opens the dashboard, when selecting the manual re-extraction action from the menu or settings, then the extraction wizard dialog opens.
- [ ] Given the setup wizard is open, when the operator selects an Entropia client directory using a folder picker or text path, then the app validates the presence of essential client structure (including `neuz.exe` and `Data/`) before proceeding.
- [ ] Given valid client files, when extraction starts, then a unified background worker executes all extraction passes sequentially:
  - Phase 1: Mover and static item tables (`propMover.txt`, `PropMoverEx.inc`, `Spec_Item.txt`).
  - Phase 2: Quests and NPC locations (`propQuest*.inc`, `character.inc`, `QuestDestination.txt.txt`).
  - Phase 3: Dungeons and instances (`propDungeon*.inc`).
  - Phase 4: World regions, terrain heightfields, spawn zones, and NavMesh generation for all detected world folders (including Madrigal, Aurania, Eden, Kebaras, and dungeons).
  - Phase 5: Client executable fingerprinting and memory profile generation: calculates SHA-256 of `neuz.exe`, verifies binary architecture (x86/x64), and writes/updates `data/config/client_player_stats_profiles.json` with exact proven offsets so `LivePlayerStatsReader` is fully initialized and operational without requiring visual fallbacks.
- [ ] Given the worker is running, when progress updates occur, then the wizard updates a smooth overall progress bar, stage description, and detailed sub-task status without blocking the UI thread.
- [ ] Given extraction completes, when the summary screen is presented, then it lists total extracted counts (worlds, quests, dungeons, monsters, verified memory profile) and displays any warnings or skipped tables.
- [ ] Given a non-critical error occurs on an individual file or table, when the worker encounters it, then it records a typed diagnostic, displays it in the completion summary, and continues extracting unaffected data.
- [ ] Given the operator cancels extraction mid-run, when cancellation is confirmed, then the worker cleanly aborts subsequent stages, leaves partial artifacts marked incomplete, and restores UI responsiveness.
- [ ] Given extraction has succeeded once, when the application is restarted, then all extracted data and memory profiles are immediately available offline across Quest, Navigation, Dungeon, and Player Stats panels without re-extracting.
- [ ] All user-visible text is available in German and English.

## Out of scope

- YOLO model retraining or modifying visual mob detection pipeline.
- Modifying, patching, or writing files into the game client folder.
- Dynamic runtime memory injection, code hooking, or anti-cheat tampering.
- Visual/OCR fallback for player statistics.

## Verification

- Automated:
  - Unit tests for setup wizard controller and unified extraction orchestrator using synthetic client folder fixtures.
  - Verification of executable SHA-256 fingerprinting and `client_player_stats_profiles.json` profile initialization.
  - Verification of background worker progress reporting, error aggregation, and cancellation handling.
  - Verification of first-run detector logic when datasets and profiles are missing vs. present.
  - Localization parity tests (`de.json` and `en.json`).
  - `./scripts/check.ps1` passes.
- Manual (Windows):
  - Launch app with empty `data/navigation/worlds/`, `data/quests/`, or `data/config/` and verify the Setup Wizard appears.
  - Select real local `Entropia` folder, execute full extraction, observe progress bar and sub-task status.
  - Verify Madrigal, Aurania, Eden, Quests, Dungeons, Mover tables, and `client_player_stats_profiles.json` are fully extracted and loaded in UI panels.
  - Verify dashboard immediately displays live player stats directly from `neuz.exe` via memory reader without OCR/pixel fallback.
  - Test cancellation and error reporting with corrupted or partial client directories.
