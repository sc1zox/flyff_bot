---
id: BUG-018
title: Win32 ModuleEntry32W structure bad length error in LivePositionReader
status: fixed
severity: high
created: 2026-08-20
updated: 2026-08-20
---

# BUG-018: Win32 ModuleEntry32W structure bad length error in LivePositionReader

## Environment

- Windows version: Windows 10/11
- Python version: 3.14
- Application revision: main
- Client/server version: Entropia Flyff (`neuz.exe`)

## Reproduction

1. Start `neuz.exe` and log into the game world.
2. Launch the bot dashboard: `uv run python -m flyff_bot ui`.
3. Observe console error: `Live position fallback (process_unavailable): [Errno 24] The game module base is unavailable.`
4. Observe dashboard chips showing "GPS offline / Spielprozess nicht verfügbar" and "Kamerageometrie nicht verfügbar".

## Expected behavior

`LivePositionReader.main_module_base()` calls `CreateToolhelp32Snapshot` and `Module32FirstW` to obtain the base address of the main module (`neuz.exe`) without returning `ERROR_BAD_LENGTH` (Errno 24).

## Actual behavior

`_ModuleEntry32W` in `live_position.py` defined `szExePath` using `MAXIMUM_PROCESS_PATH_LENGTH` (32,768 WCHARs) instead of the standard Win32 `MAX_PATH` (260 WCHARs). `dwSize` evaluated to ~66,000 bytes instead of the expected 1080 bytes (x64) / 568 bytes (x86), causing `Module32FirstW` to fail with Win32 Error 24 (`ERROR_BAD_LENGTH`).

## Impact and frequency

- Impact: Blocked `LivePositionReader` and `LiveCameraReader` from reading module base, leaving GPS and camera geometry permanently offline on Windows.
- Frequency: 100% on live Windows clients.

## Regression verification

- [x] A failing automated test or deterministic manual check exists: `test_module_entry_structure_matches_win32_layout()` in `tests/unit/test_live_position.py`.
- [x] The check passes after the fix (1080 bytes on x64, 568 bytes on x86).
- [x] Verified against live `neuz.exe` process (PID 35428), resolving module base `0x7ff634e10000` and player GPS coordinates `X=1312.23, Y=139.01, Z=1109.04`.
- [x] `./scripts/check.ps1` passes cleanly with 807 passed tests.
