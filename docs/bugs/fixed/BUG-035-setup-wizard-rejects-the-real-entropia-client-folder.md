---
id: BUG-035
title: Setup wizard rejects the real Entropia client folder
status: verified
severity: high
created: 2026-08-28
updated: 2026-08-28
---

# BUG-035: Setup wizard rejects the real Entropia client folder

## Environment

- Windows version: Windows 11 Pro 10.0.26200
- Python version: 3.14
- Application revision: a6fed41
- Client/server version: Entropia Flyff PServer (neuz.exe)

## Reproduction

1. Start the desktop application so the first-run setup wizard ("Erste Einrichtung") opens.
2. Choose the real client installation folder, e.g. `I:\coding projects\flyff_bot\Entropia\Entropia`,
   which contains `Data\`, `bin32\neuz.exe`, and `bin64\neuz.exe`.
3. Press "Alle Clientdaten extrahieren".

## Expected behavior

The wizard accepts the installation folder and runs the unified extraction, because the folder is
the documented client root (see `docs/sources/2026-08-19-entropia-client-navigation-data-extraction.md`,
which records `Entropia/Entropia/bin32/neuz.exe` and `Entropia/Entropia/bin64/neuz.exe`).

## Actual behavior

No extraction starts. The wizard only shows `ui.setup_invalid_directory`
("Wählen Sie den Entropia-Ordner aus, der neuz.exe und Data enthält."). `_validate_client_layout`
looked for `<root>\neuz.exe` only, but the shipped install keeps the client binary in `bin64\` and
`bin32\`; the root holds `EntropiaLauncher.exe`. The check therefore failed for every real install,
and the nested-folder fallback failed for the same reason.

## Impact and frequency

- Impact: First-run setup is impossible, so no client data (worlds, quests, dungeons, catalog) is
  ever extracted and autopilot stays blocked behind "Ersteinrichtung erforderlich".
- Frequency: Always, on every unmodified client installation.

## Regression verification

- [x] A failing automated test or deterministic manual check exists.
- [x] The check passes after the fix.
- [x] Related documentation is current.

## Fix

`_validate_client_layout` now resolves `neuz.exe` through `EXECUTABLE_RELATIVE_PATHS`
(`neuz.exe`, `bin64\neuz.exe`, `bin32\neuz.exe`) next to the `Data` directory, for both the selected
folder and the nested same-name folder. The 64-bit build is preferred because `start_64bit.bat` is
the default launcher path. The `ui.setup_invalid_directory` message in `de.json` and `en.json` now
names the accepted layout.

Verified against the real install: 16 world maps, 1434 quests, 3389 movers, 23 drops, and 24943
items were extracted. Remaining diagnostics are unrelated to this defect (`DUNGEONS_EMPTY`,
`MEMORY_PROFILE_NOT_FOUND` without an operator profile registry, and mover table rejections).
