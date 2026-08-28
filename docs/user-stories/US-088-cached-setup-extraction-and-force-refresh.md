---
id: US-088
title: Setup wizard autostart restriction, cached extraction, and UI re-extraction
status: draft
created: 2026-08-29
updated: 2026-08-29
---

# US-088: Setup wizard autostart restriction, cached extraction, and UI re-extraction

## Story

As a **bot operator launching the application**, I want **the Setup Wizard to only automatically open on startup when no extracted client data exists yet, while remaining accessible on demand in the UI and caching extracted datasets across runs**, so that **I am not prompted with the extraction wizard on every start once data is available, and can trigger a fresh re-extraction easily whenever needed**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Client files reside in an operator-specified directory (e.g. `Entropia/` containing `neuz.exe` and `Data/`).
- Static file extraction is authorized by [ADR-005](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md) and read-only process memory by [ADR-006](../decisions/ADR-006-read-only-process-memory-access.md). The client installation remains strictly read-only.
- Builds upon the unified client extraction and setup wizard from [US-078](completed/US-078-initial-setup-wizard-and-unified-client-data-extraction.md) and production readiness from [US-085](completed/US-085-production-readiness-and-autonomous-farming-polish.md).
- Currently, if any optional or secondary profile/artifact is absent, the application treats setup as required on every startup and forces the Setup Wizard dialog to open.
- When extracted artifacts (world maps, quest database, dungeon database, client catalog, etc.) are already present, the Setup Wizard should not pop up automatically on startup.
- The Setup Wizard remains accessible and openable manually through the application menu / UI action at all times.
- When the Setup Wizard is executed, it caches and reuses existing extracted artifacts to avoid redundant I/O and processing, while providing a clear toggle/button to perform a complete fresh re-extraction.

## Acceptance criteria

- [ ] Given extracted client data already exists on disk, when the application starts, then the main dashboard window opens directly without automatically popping up the Setup Wizard dialog.
- [ ] Given no extracted client data exists on disk (fresh installation), when the application starts, then the Setup Wizard is automatically displayed to guide initial extraction.
- [ ] Given the application dashboard is open, when the operator selects the Setup action from the menu or UI, then the Setup Wizard dialog opens on demand.
- [ ] Given the Setup Wizard is executed without the force re-extraction option, when existing valid extracted artifacts are present, then `UnifiedClientExtractor` reuses the cached artifacts and completes without re-parsing unaffected datasets.
- [ ] Given the Setup Wizard is open, when the operator checks the "Vollständig neu extrahieren" / "Force re-extraction" option and starts extraction, then all client datasets are freshly extracted and overwrite existing caches.
- [ ] All user-visible text (labels, buttons, tooltips, and status messages) is available in German and English and synchronized between `de.json` and `en.json`.

## Out of scope

- Modifying or patching game client files.
- Background filesystem watchers on the game directory.
- YOLO model retraining.

## Verification

- Automated:
  - Unit tests verifying the startup wizard autostart behavior (opens only when no client data exists, stays closed when datasets exist).
  - Unit tests for `SetupWizard` UI manual open action and force re-extraction toggle.
  - Unit tests for cached extraction execution in `UnifiedClientExtractor`.
  - Localization parity tests (`de.json` and `en.json`).
  - `./scripts/check.ps1` passes.
- Manual (Windows):
  - Launch app with existing extracted data; verify the dashboard opens directly without setup popup.
  - Open Setup Wizard via menu, verify UI elements, run cached extraction vs. fresh re-extraction.
  - Delete `data/` artifacts, launch app, verify Setup Wizard automatically appears.
