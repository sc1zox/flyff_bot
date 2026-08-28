---
id: US-088
title: Cached setup extraction and UI force refresh
status: draft
created: 2026-08-29
updated: 2026-08-29
---

# US-088: Cached setup extraction and UI force refresh

## Story

As a **bot operator setting up or launching the application**, I want **the setup extraction workflow to cache already extracted client datasets and skip redundant extraction passes unless forced, with a straightforward option in the UI to trigger a fresh re-extraction**, so that **subsequent setup runs and app launches are fast and avoid unnecessary disk I/O and processing, while still allowing a full re-extraction at any time**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Client files reside in an operator-specified directory (e.g. `Entropia/` containing `neuz.exe` and `Data/`).
- Static file extraction is authorized by [ADR-005](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md) and read-only process memory by [ADR-006](../decisions/ADR-006-read-only-process-memory-access.md). The client installation remains strictly read-only.
- Builds upon the unified client extraction and setup wizard from [US-078](completed/US-078-initial-setup-wizard-and-unified-client-data-extraction.md) and production readiness from [US-085](completed/US-085-production-readiness-and-autonomous-farming-polish.md).
- Currently, `UnifiedClientExtractor.run()` always parses, builds, and writes all mover tables, quests, dungeons, and world regions/NavMeshes from scratch every time the wizard runs.
- World extraction (parsing `.wld`, `.lnd`, `.rgn`, `.dyo`, baking terrain heightfields and NavMeshes) is particularly time- and I/O-intensive.
- When target artifacts (`data/client/catalog.json`, `data/client/source_manifest.json`, `data/quests/quests.json`, `data/dungeons/dungeons.json`, `data/navigation/worlds/*.json`, `data/config/client_player_stats_profiles.json`) are already present and valid, extraction can reuse these cached artifacts instead of repeating the entire extraction pipeline.
- The Setup Wizard UI provides a clean toggle/checkbox ("Vollständig neu extrahieren" / "Force re-extraction") that lets the operator explicitly bypass the cache and re-extract all datasets fresh.

## Acceptance criteria

- [ ] Given valid extracted client artifacts (client catalog, source manifest, quest database, dungeon database, world maps, NavMeshes, and player stats profile) already exist on disk, when the Setup Wizard is executed without the force refresh option, then `UnifiedClientExtractor` detects the cached datasets, skips redundant extraction passes, and reports the cached counts in the result summary.
- [ ] Given some or all target artifacts are missing or invalid, when the Setup Wizard is executed, then `UnifiedClientExtractor` extracts the missing or invalid datasets and writes them to disk.
- [ ] Given the Setup Wizard dialog is open in the desktop UI, when viewed by the operator, then a checkbox/toggle for forcing a fresh re-extraction is visible and defaults to unchecked.
- [ ] Given the force re-extraction toggle is checked in the Setup Wizard UI, when extraction starts, then `UnifiedClientExtractor` bypasses cached artifacts, executes all extraction stages fresh, and overwrites existing datasets with updated data.
- [ ] Given extraction progress is reported during execution, when a stage is skipped due to valid cache or freshly extracted, then the progress updates and status labels accurately reflect the stage status.
- [ ] Given the operator cancels extraction mid-run, when cancellation occurs, then the background worker cleanly aborts without corrupting existing valid cached artifacts.
- [ ] All user-visible text (labels, buttons, checkboxes, tooltips, and status messages) is available in German and English and synchronized between `de.json` and `en.json`.

## Out of scope

- Background file watcher / filesystem polling of the client installation during active bot sessions.
- Modifying, patching, or writing into the game client folder.
- YOLO model retraining or visual detection pipeline modifications.

## Verification

- Automated:
  - Unit tests for `UnifiedClientExtractor` cache detection (skipping stages when cached artifacts exist vs. extracting when missing or when `force_refresh=True`).
  - Unit tests for `SetupWizard` UI checkbox toggle and passing the force refresh flag to the worker and extractor.
  - Tests verifying partial cache handling (extracting only missing datasets while keeping present ones).
  - Localization parity tests (`de.json` and `en.json`).
  - `./scripts/check.ps1` passes.
- Manual (Windows):
  - Open Setup Wizard with already-extracted datasets; observe rapid completion with cached status.
  - Enable "Force re-extraction" in Setup Wizard; observe full extraction passes executing from scratch.
  - Verify German and English localization for all new UI text elements.
