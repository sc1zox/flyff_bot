---
id: US-053
title: Pure 3D GPS navigation, dynamic client profile configuration, and minimap fallback retirement
status: draft
created: 2026-08-19
updated: 2026-08-19
---

# US-053: Pure 3D GPS navigation, dynamic client profile configuration, and minimap fallback retirement

## Story

As a **bot operator running vector-world navigation in Flyff**,
I want **the bot to navigate exclusively via authoritative live 3D GPS coordinates read from game memory, load client build profiles from an operator-editable JSON configuration file, pause cleanly with explicit diagnostics whenever GPS is unavailable instead of silently falling back to inaccurate minimap odometry, and persist the world data dialog selections across sessions**,
so that **movement is always drift-free and aligned with true terrain geometry, new client patches can be supported without code edits, and misleading fallback navigation is eliminated**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Builds upon:
  - [US-045](completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md): Vector world terrain extraction, spawn zones, and visibility-graph A* pathing.
  - [US-048](completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md): 3D world navigation with live coordinate memory reading (`ReadProcessMemory`).
  - [ADR-004](../decisions/ADR-004-coordinate-only-read-process-memory.md): Fingerprinted, coordinate-only read access to the Flyff client.
- **Retirement of Minimap Odometry Fallback for Vector Navigation:**
  - Minimap dead-reckoning (`MovementTracker` / `MinimapOdometer`) suffers from pixel drift, scale ambiguities, and lack of vertical ($Y$) awareness.
  - Relying on dead-reckoning as a silent fallback causes misleading pathing loops and misaligned routes against true terrain.
  - Vector navigation should strictly require live $(X, Y, Z)$ GPS signal; when GPS is unavailable, the bot must pause navigation and alert the operator rather than steering blindly.
- **Dynamic Client Profile JSON Configuration:**
  - `LivePositionReader` currently hardcodes SHA-256 fingerprints and pointer RVAs in `ENTROPIA_POSITION_PROFILES`.
  - Storing client build profiles in an external, operator-editable JSON file (e.g. `data/navigation/client_profiles.json`) enables instant support for server updates and custom binaries without Python source changes.
  - If an unknown `neuz.exe` build is attached, the diagnostic log displays the computed SHA-256 digest to facilitate profile creation.
- **World Data UI Streamlining & State Persistence:**
  - The provisional "Minimap-Pixel je Welteinheit" scale calibration spinbox is obsolete under pure GPS and is removed from the UI.
  - `WorldDataDialog` must retain and persist the operator's selected region, extracted map, active spawn zone, and kill quota across dialog opens and application restarts instead of resetting to the first list entry.
- Safety boundaries strictly maintained:
  - Read-only `ReadProcessMemory` for player coordinates only. No code injection, hooking, or memory writes.
  - Foreground window checks and emergency stop (`END`/`Escape`) remain mandatory.
  - Full localization in German (`de.json`) and English (`en.json`).

## Acceptance criteria

- [ ] **Dynamic Client Profile JSON Configuration:**
  - Client position profiles are loaded from `data/navigation/client_profiles.json` (falling back to embedded defaults if the file is missing).
  - Each profile entry defines `sha256`, `player_pointer_rva`, `pointer_size_bytes`, and optional `position_offset`.
  - When an unsupported client build is detected, the error diagnostic explicitly reports the detected SHA-256 hash and path.
- [ ] **Pure GPS Navigation & Explicit Pause:**
  - `VectorZoneNavigator` and `PathingNavigator` require `PositionSource.LIVE` for vector route planning and traversal.
  - If `LivePositionReader` reports `MINIMAP_FALLBACK` or error (window not focused, process not found, unsupported build, player pointer null), navigation halts movement inputs and transitions to `PathingMode.BLOCKED` / `IDLE`.
  - The status bar and map inspector clearly indicate the GPS unavailability reason (e.g. "GPS offline / Client not focused").
- [ ] **UI Streamlining & Removal of Scale Calibration:**
  - The obsolete "Minimap-Pixel je Welteinheit" (`_scale_spin`) spinbox and associated tooltip are removed from `WorldDataDialog`.
  - Vector navigation requests and routing operate natively in client world units.
- [ ] **World Data Dialog State Persistence:**
  - `WorldDataDialog` preserves and restores the selected client region, extracted map, active spawn zone, and kill quota across dialog open/close cycles and app sessions.
  - Calling `refresh()` updates available file lists without resetting active user selections to index 0.
- [ ] **Failure and Cancellation Behavior:**
  - Immediate emergency stop on `Escape` or `END` cleanly releases the process memory handle and aborts movement.
- [ ] **Localization:**
  - All new status chips, error diagnostics, and dialog labels are synchronized in German (`de.json`) and English (`en.json`).

## Out of scope

- Memory writes (`WriteProcessMemory`), hooking, or code injection.
- Dynamic signature scanning across unmapped process address space.
- Automatic byte-pattern decompilation or memory disassembly.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_live_position.py` verifying JSON profile loading, fallback defaults, and SHA-256 matching.
  - Unit tests verifying pure GPS requirement, navigation pause on lost GPS signal, and error diagnostic emission.
  - Unit tests in `tests/unit/test_world_data_dialog.py` verifying state persistence and selection preservation on refresh.
  - `./scripts/check.ps1` runs clean with zero type and lint errors.
- Manual (Windows):
  - Start bot with game client focused: verify GPS status is green, coordinates match live character position, and terrain route aligns accurately.
  - Defocus game client: verify navigation halts and status indicates game window not in foreground.
  - Open and close `Weltdaten & Karten` dialog: verify selected map, zone, and quotas are preserved without resetting to index 0.
