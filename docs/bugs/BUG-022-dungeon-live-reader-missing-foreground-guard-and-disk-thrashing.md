---
id: BUG-022
title: Dungeon live reader missing foreground guard and disk-thrashing SHA-256 hashing
status: reported
severity: high
created: 2026-08-23
updated: 2026-08-23
---

# BUG-022: Dungeon live reader missing foreground guard and disk-thrashing SHA-256 hashing

## Environment

- Windows version: Windows 11
- Python version: Python 3.14 (.python-version)
- Application revision: branch `feature-us-060-combat-class-profiles` (commit `227064e`)
- Client/server version: Entropia Flyff PServer (`neuz.exe`)

## Reproduction

1. Launch the application on branch `feature-us-060-combat-class-profiles` with an active Entropia `neuz.exe` client and a configured dungeon profile.
2. Minimize or move focus away from the `neuz.exe` client window to another application.
3. Observe `LiveDungeonCooldownReader.poll()` continuing to open process handles and read client process memory despite the client window not being foregrounded.
4. Profile disk I/O and CPU usage during periodic polling (1 Hz default).
5. Notice that on every single poll tick, `LiveDungeonCooldownReader._read_states()` reads the entire `neuz.exe` executable from disk to compute `executable_sha256(executable)`, queries the module base via `CreateToolhelp32Snapshot`, and immediately closes the handle in `finally`.

## Expected behavior

According to [ADR-006](../decisions/ADR-006-read-only-process-memory-access.md) and project safety rules in `AGENTS.md`:
1. All client memory readers must verify that the target game window is foregrounded (`api.is_window_foreground(window_handle)`) before opening process handles and reading memory. If the window is not foregrounded, polling must immediately degrade to a typed diagnostic without accessing process memory.
2. Executable verification (SHA-256 digest) and process handle opening must be performed once during handle initialization (`_ensure_open`) and cached across polls. Handles, module base addresses, and verified profiles must be retained until window change, process termination, or unrecoverable read errors occur, avoiding repeated disk reads and handle thrashing.

## Actual behavior

1. `LiveDungeonCooldownReader._read_states()` never calls `is_window_foreground(self._window_handle)` before calling `open_read_process(process_id)` and `api.read()`.
2. On every 1 Hz tick, `LiveDungeonCooldownReader` opens a process handle, re-reads and re-hashes `neuz.exe` from disk, creates a new Toolhelp32 snapshot for `main_module_base`, and closes the handle in `finally`. This causes continuous disk I/O and CPU overhead.

## Impact and frequency

- **Impact:** High. Violates core safety constraints (accessing background process memory) and degrades performance due to continuous disk reads and SHA-256 computations on the main tick loop.
- **Frequency:** Deterministic on every polling tick when `LiveDungeonCooldownReader` is active.

## Regression verification

- [ ] A failing automated test proves that `LiveDungeonCooldownReader` rejects background client windows without opening a handle or reading memory.
- [ ] A failing automated test proves that `LiveDungeonCooldownReader` caches the verified process handle and module base across polls rather than re-reading the binary and re-hashing on every tick.
- [ ] The checks pass after refactoring `LiveDungeonCooldownReader` to follow the `_ensure_open()` safety lifecycle pattern.
- [ ] Related documentation is current.
