---
id: BUG-036
title: Dungeon extraction fails on missing PartyDungeon.lua and dashboard shows misleading extraction status
status: reported
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

- [ ] A failing automated test proves that `DungeonCooldownPanel` accurately reflects database presence and process connection status instead of displaying a false "run extraction" status.
- [ ] A failing automated test or parser fixture verifies Entropia dungeon data ingestion from available client structures.
- [ ] The checks pass after the fix.
- [ ] Related documentation is current.
