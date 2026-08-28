---
id: BUG-036
title: Dungeon extraction fails on missing PartyDungeon.lua and dashboard shows misleading extraction status
status: verified
severity: medium
created: 2026-08-29
updated: 2026-08-29
---

# BUG-036: Dungeon extraction fails on missing PartyDungeon.lua and dashboard shows misleading extraction status

## Environment

- Windows version: Windows 11
- Python version: 3.14.7
- Application revision: 6d76d80
- Client/server version: Entropia Flyff PServer (neuz.exe)

## Reproduction

1. Run the initial setup wizard or execute unified client extraction against a valid Entropia Flyff client directory.
2. Complete all setup stages and open the Flyff Bot dashboard.
3. Switch to the tab "Dungeons Abklingzeiten" (Dungeons Cooldowns) without `neuz.exe` running.
4. Observe the status message displayed inside the panel:
   `"Keine Dungeon-Datenbank gefunden. Bitte zuerst die Dungeon-Extraktion ausführen."`
5. Inspect `data/dungeons/dungeons.json` on disk and observe `"dungeons": []`.

## Expected behavior

1. Client extraction should support the Entropia Flyff client's dungeon definitions (e.g. via `DungeonRanking.inc`, world symbols, or client script tables) rather than failing strictly when `PartyDungeon.lua` is absent.
2. The UI panel in `DungeonCooldownPanel` must distinguish between:
   - Missing dungeon database file on disk (`dungeons.json` absent).
   - Empty dungeon database extracted (`dungeons.json` present but declaring 0 dungeons).
   - Live reader unavailable / disconnected (client process `neuz.exe` not running or window not foregrounded).
3. The dashboard must not prompt the operator to run dungeon extraction when extraction has already completed.

## Actual behavior

1. `extract_dungeon_definitions()` strictly looks for `PartyDungeon.lua` inside `Data/System2/` archives. Because Entropia Flyff does not package `PartyDungeon.lua`, extraction silently records a `DungeonExtractionWarning.MISSING_DUNGEON_SCRIPT` diagnostic and writes an empty `dungeons.json` (`"dungeons": []`).
2. When the dashboard starts or receives `update.dungeons = None` (due to `neuz.exe` not running), `DungeonCooldownPanel.set_snapshots(None)` unconditionally displays `Message.UI_DUNGEON_UNAVAILABLE` ("Keine Dungeon-Datenbank gefunden. Bitte zuerst die Dungeon-Extraktion ausführen.").
3. The operator is led to believe the setup wizard omitted dungeon extraction on first run.

## Impact and frequency

- **Impact:** Dungeons tab remains completely empty and misleadingly instructs the operator to re-run extraction repeatedly.
- **Frequency:** Deterministic on every fresh setup and every run where `neuz.exe` is not active.

## Regression verification

- [x] A failing automated test proves that `DungeonCooldownPanel` accurately reflects database presence and process connection status instead of displaying a false "run extraction" status.
- [x] A failing automated test or parser fixture verifies Entropia dungeon data ingestion from available client structures.
- [x] The checks pass after the fix.
- [x] Related documentation is current.

## Fix

Extraction no longer treats a missing `PartyDungeon.lua` as "no dungeons". `_client_declarations`
prefers the dungeon script, and falls back to the ranking table `DungeonRanking.inc`, which every
Entropia client packs: `parse_dungeon_ranking` reads one numeric world identifier plus its commented
label per reward block, ignoring the leading reset period and commented-out blocks. Because that
table declares neither level ranges nor cooldowns, `DungeonDefinition.minimum_level`,
`maximum_level`, and `base_cooldown_seconds` are now optional and stay `None` rather than being
filled with an invented default. A client that packs neither source reports the new
`MISSING_DUNGEON_RANKING` diagnostic beside `MISSING_DUNGEON_SCRIPT`.

`DungeonCooldownPanel` now keeps the extracted database and the live poll apart, so its status line
names the actual gap: `ui.dungeon_unavailable` only when no readable database exists on disk,
`ui.dungeon_database_empty` when extraction ran and the client declares no dungeons, and
`ui.dungeon_live_unavailable` when the database is loaded but the client is not connected — in that
last case the extracted rows are rendered with `UNKNOWN` status instead of an empty table.
`MainWindow.load_dungeon_database()` binds the database during `reload_client_data()`, so the panel
reflects disk state at startup and again after the setup wizard finishes.

Verified against the real install: 32 dungeons are extracted from `DungeonRanking.inc`
(`Aminus Dungeon` through `Monster Clash`); two entries whose label is a bare world symbol keep that
symbol because the client packs no catalog resolving it.
