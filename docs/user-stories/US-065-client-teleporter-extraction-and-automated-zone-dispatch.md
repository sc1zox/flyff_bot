---
id: US-065
title: Client teleporter data extraction and automated zone fast travel
status: draft
created: 2026-08-20
updated: 2026-08-20
---

# US-065: Client teleporter data extraction and automated zone fast travel

## Story

As a **bot operator on Entropia Flyff**, I want **the bot to automatically extract all teleporter destinations from client files and execute fast travel between game zones via deterministic UI interaction without OCR**, so that **the bot can independently travel to different farming areas, dungeon entrances, and cities when goals require a zone transition**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Authoritative destination data is stored in the client asset `TeleportOption.inc` (located in packed `Data/System3/` archives or client folders) and cached in `teleport.bin`.
- Adheres to [ADR-005](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md) for offline read-only extraction of game client files.
- Teleportation is strictly permitted only when out of combat (`not in combat` / no active target attack engagement).
- The teleporter window (`CWndTeleporter`) is opened via a configurable hotkey (default: `V`).
- UI automation operates deterministically without OCR:
  1. Opens the teleporter window via hotkey (`V`).
  2. Types the target destination name into the search field (`CWndTeleportSearchEdit`).
  3. Selects the first filtered entry in the result list (`CWndTeleportList`).
  4. Clicks the `Teleport` execution button.
- Arrival confirmation is validated authoritatively via live process memory (`ReadProcessMemory` / `WorldPosition`) per [ADR-006](../decisions/ADR-006-read-only-process-memory-access.md) within a configurable timeout window (default: 5.0s).
- In case of failure or timeout, the error is logged and the operation is safely aborted.
- Builds on [US-051](US-051-teleport-dispatch-simplification-and-emergency-eden-reset.md) and [US-045](completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md).

## Acceptance criteria

- [ ] Given local Entropia client assets, when the teleporter extractor runs, then all declared teleport destinations are parsed into typed data models (destination name, target world ID, description, required levels, and category).
- [ ] Given a navigation route or goal requiring a zone transition, when the character is idle and not engaged in combat, then the bot initiates fast travel using the extracted destination metadata.
- [ ] Given an active combat engagement or incoming damage, when a zone change is requested, then teleport dispatch is deferred until combat is fully resolved.
- [ ] Given a teleporter dispatch trigger, when the game window is foregrounded, then the bot pulses the configured teleporter hotkey (default `V`), inputs the target destination name into the search box, selects the filtered item, and clicks the `Teleport` button.
- [ ] Given a dispatched teleporter command, when live GPS coordinates and world ID update via `ReadProcessMemory`, then the bot confirms arrival within the timeout window (default: 5.0s) and initializes local 3D pathing for the target zone.
- [ ] Given an unconfirmed teleport (world ID/coordinates unchanged after timeout) or a blocked UI state, then the bot logs a diagnostic error, closes the teleporter window, aborts the travel attempt, and transitions to safe standby.
- [ ] All user-visible settings, status indicators, and log messages remain synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).

## Out of scope

- OCR text scanning or screen-reading of the teleporter interface (avoided in favor of direct search filtering and deterministic widget coordinates).
- Bypassing server-enforced level requirements, currency fees, or locked maps.
- Memory write operations (`WriteProcessMemory`) or custom network packet injection.
- Teleporting directly to arbitrary player names (friend/guild teleport).

## Verification

- Automated:
  - Unit tests in `tests/unit/test_teleporter_extractor.py` verifying parsing of `TeleportOption.inc` into structured destination records.
  - Unit tests in `tests/unit/test_teleport_dispatch.py` validating the state machine (out-of-combat gate, hotkey pulse, search input sequence, timeout handling, and live GPS arrival confirmation).
- Manual (Windows):
  - Start Entropia client, trigger an automated zone change to Flarine / Darkon, verify the teleporter window opens via `V`, types search query, clicks teleport, confirms arrival via live memory GPS, and resumes navigation.
