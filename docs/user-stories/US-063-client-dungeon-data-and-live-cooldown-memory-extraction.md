---
id: US-063
title: Client dungeon data extraction and live cooldown memory reader
status: draft
created: 2026-08-20
updated: 2026-08-20
---

# US-063: Client dungeon data extraction and live cooldown memory reader

## Story

As a **Flyff bot operator planning farming runs**,
I want **the application to extract static dungeon definitions from client archives and read live runtime dungeon cooldown timers directly from game process memory**,
so that **I can inspect current dungeon availability and remaining cooldowns in real-time on the dashboard without manual checks or OCR heuristics**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Client dungeon definitions, names, and parameters reside in client archives and script tables (`Data/System2/data*.one`, `Data/system3/`, `propDungeon*.inc`, `textClient.txt`, `masquerade.prj`).
- Runtime cooldown timers, daily entry counts, and dungeon lockouts are maintained in client memory structures within `neuz.exe`.
- [ADR-005](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md) permits static client asset inspection and unpacking of archive files into repository artifacts.
- [ADR-006](../decisions/ADR-006-read-only-process-memory-access.md) permits read-only memory inspection (`ReadProcessMemory` with `PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION`) using SHA-256 fingerprinted offsets and module RVAs without runtime memory scanning or writes.
- Builds upon the read-only memory reader infrastructure established in [US-053](completed/US-053-pure-gps-navigation-and-client-profile-configuration.md) (`LivePositionReader`) and [US-056](completed/US-056-client-camera-state-and-projection-matrix-reader.md) (`LiveCameraReader`).
- Optical character recognition (OCR) and visual screen scraping are explicitly excluded for this feature in favor of authoritative programmatic extraction and memory reading.

## Acceptance criteria

- [ ] Given an offline or operator-triggered extraction pass against the Entropia client directory, when dungeon definition files are indexed and unpacked from client archives, then a structured JSON dataset (`data/dungeons/dungeons.json`) is generated containing parsed dungeons with IDs, localized names, minimum level requirements, entry restrictions, and base cooldown periods.
- [ ] Given a supported client executable fingerprint in `data/config/client_dungeon_profiles.json`, when the bot is attached to `neuz.exe`, then a fingerprinted read-only memory reader (`LiveDungeonCooldownReader`) extracts current dungeon cooldown timestamps, remaining seconds, and daily entry counts.
- [ ] Given a read tick runs, when dungeon cooldown structures are evaluated, then the system produces an immutable `DungeonStateSnapshot` mapping each dungeon ID to its status (`READY`, `ON_COOLDOWN`, `ENTRY_LIMIT_REACHED`, `UNKNOWN`) and remaining cooldown duration.
- [ ] Given the desktop dashboard UI is open, when the operator views the "Dungeons & Cooldowns" panel, then a clear, real-time list of all extracted dungeons, their level requirements, current status badges, and formatted remaining cooldown timers (`HH:MM:SS`) is displayed.
- [ ] Given memory offsets are unconfigured, invalid, or the game client is closed/minimized, when memory reading is attempted, then the reader reports typed diagnostics (`DungeonReadStatus.UNCONFIGURED_PROFILE`, `DungeonReadStatus.HANDLE_LOST`, `DungeonReadStatus.PROCESS_UNAVAILABLE`) and gracefully falls back to `UNKNOWN` status without raising unhandled exceptions or crashing the UI.
- [ ] Safety boundary preserved: Memory handles are opened strictly read-only (`PROCESS_VM_READ`). Zero memory writes (`WriteProcessMemory`), zero DLL injection, zero code hooking, and zero anti-cheat bypasses.
- [ ] All user-visible UI labels, column headers, tooltips, and diagnostic messages are fully synchronized in German (`de.json`) and English (`en.json`).

## Out of scope

- Automated dungeon entry, teleport dispatching, or NPC dialogue interaction (deferred to subsequent automation stories).
- Autonomous dungeon mob combat, boss encounters, and dungeon room pathfinding.
- Modifying, bypassing, or resetting cooldown timers via memory manipulation or packet crafting (strictly prohibited).
- Optical character recognition (OCR) or visual template matching of in-game dungeon windows.

## Verification

- Automated:
  - Unit tests for archive dungeon extractor parsing synthetic `propDungeon*.inc` and client string tables into structured `DungeonDefinition` models.
  - Unit tests for `LiveDungeonCooldownReader` reading synthetic process memory buffers against mocked Windows APIs.
  - Unit tests verifying status calculation (`READY`, `ON_COOLDOWN`, `ENTRY_LIMIT_REACHED`, `UNKNOWN`) based on extracted timestamps and current clock.
  - Unit tests verifying graceful degradation and typed error handling on invalid handles or unmapped profiles.
  - Check suite passes cleanly: `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows):
  - Run the dungeon archive extraction tool against local Entropia Flyff client files and verify `data/dungeons/dungeons.json` is created with valid entries.
  - Launch the client, enter/complete a dungeon to trigger a cooldown, and verify on the PySide6 dashboard that the live countdown timer matches the in-game cooldown timer in real-time.
