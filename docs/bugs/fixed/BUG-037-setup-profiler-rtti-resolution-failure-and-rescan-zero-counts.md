---
id: BUG-037
title: Setup profiler RTTI resolution failure and rescan zero counts display
status: resolved
severity: high
created: 2026-08-29
updated: 2026-08-29
---

# BUG-037: Setup profiler RTTI resolution failure and rescan zero counts display

## Environment

- Windows version: Windows 11
- Python version: 3.14.7
- Application revision: fb0cbae
- Client/server version: Entropia Flyff PServer (neuz.exe, x64)

## Reproduction

1. Open the first-run Setup Wizard ("Erste Einrichtung") with a valid client installation path (e.g. `Entropia\Entropia` containing `Data\` and `bin64\neuz.exe`).
2. Click "Alle Clientdaten extrahieren" ("Extract all client data"). Static client data extraction completes (16 worlds, 1434 quests, 32 dungeons, 3389 movers, 24943 items).
3. Observe the diagnostic failure at stage 5: `client_profiling_failed: missing_rtti: The primary VTable for .?AVCMover@@ is missing.`.
4. Click "Profile neu analysieren" ("Re-scan Profiles").
5. Observe that all extracted dataset counts in the summary text reset to 0: `Welten: 0 · Quests: 0 · Dungeons: 0 · Mover: 0 · Drops: 0 · Items: 0 · Speicherprofil: nicht installiert...`.

## Expected behavior

1. The offline binary profiler (`rtti.py`) locates MSVC RTTI `TypeDescriptor` headers across valid PE sections (including `.data` where MSVC x64 stores type descriptors) and validates authoritative VTables for single- and multi-method classes (such as `CPlayerDataCenter`), successfully deriving memory profile bundles for `bin64/neuz.exe`.
2. When clicking "Profile neu analysieren" (`run_memory_profile_only()`), the summary view displays the counts of already extracted and stored datasets (worlds, quests, dungeons, movers, items) rather than resetting all numbers to 0.

## Actual behavior

1. `resolve_primary_vtable()` searches only within `.rdata` bytes for RTTI decorated symbol names (e.g. `.?AVCMover@@`), failing to discover type descriptors that MSVC places in `.data`. This raises `ClientProfilingError(MISSING_RTTI, "The primary VTable for .?AVCMover@@ is missing.")`.
2. `_valid_vtable()` assumes every valid VTable contains at least two consecutive executable pointers (16 bytes), which rejects single-method virtual classes like `CPlayerDataCenter`.
3. `run_memory_profile_only()` constructs a blank `SetupExtractionResult()` with zeroed counts, which overwrites the UI summary display and gives the false impression that previously extracted client data was erased.

## Impact and frequency

- Impact: Automated generation of memory profiles (`client_profiles.json`, `client_player_stats_profiles.json`, `client_camera_profiles.json`, `client_dungeon_profiles.json`) fails on real Entropia x64 client binaries, and the setup UI displays confusing zero counts upon re-scanning.
- Frequency: 100% on any Entropia x64 client directory.

## Regression verification

- [x] A failing automated test or deterministic manual check exists.
- [x] The check passes after the fix.
- [x] Related documentation is current.

## Fix

1. In `src/flyff_bot/features/client_profiling/rtti.py`, `resolve_primary_vtable()` now scans all PE sections for RTTI `TypeDescriptor` headers, correctly resolving classes whose type descriptor symbols reside in `.data` while their `_RTTICompleteObjectLocator` and VTables reside in `.rdata`. `_valid_vtable()` checks the primary virtual function pointer entry for executable section bounds, supporting single-method virtual classes like `CPlayerDataCenter`.
2. In `src/flyff_bot/features/client_profiling/profiler.py`, `_discover_camera()` adds buffer-bounds checking on `window` slices during view and projection marker analysis.
3. In `src/flyff_bot/features/setup/extraction.py`, `run_memory_profile_only()` calls `_populate_existing_dataset_counts()` to inspect and populate counts for previously extracted and persisted datasets (client catalog, quest database, dungeon database, world maps) so the setup wizard preserves actual dataset numbers.
4. Comprehensive unit tests added in `tests/unit/test_client_profiling.py` and `tests/unit/test_setup_extraction.py`.
