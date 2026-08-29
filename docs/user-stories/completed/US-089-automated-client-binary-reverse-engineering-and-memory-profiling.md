---
id: US-089
title: Automated client binary reverse engineering and memory profiling
status: completed
created: 2026-08-29
updated: 2026-08-29
---

# US-089: Automated client binary reverse engineering and memory profiling

## Story

As a **Flyff bot operator and maintainer**,
I want **the setup pipeline and dashboard to statically reverse engineer the target client binary (`neuz.exe`) and derive exact runtime memory offsets and pointer RVAs**,
so that **memory profiles for GPS coordinates, player vitals, camera matrices, and dungeon state are automatically generated without manual disassembly or hardcoded hex patches**.

## Context and assumptions

- Target client: Entropia Flyff x64 client (`neuz.exe`, PE32+ executable, SHA-256: `8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5`).
- [ADR-006](../../decisions/ADR-006-read-only-process-memory-access.md) permits read-only process memory inspection using fingerprinted SHA-256 offsets and module RVAs without runtime code injection, memory writes, or hooking.
- Builds upon memory reader implementations in [US-053](US-053-pure-gps-navigation-and-client-profile-configuration.md) (`LivePositionReader`), [US-056](US-056-client-camera-state-and-projection-matrix-reader.md) (`LiveCameraReader`), [US-063](US-063-client-dungeon-data-and-live-cooldown-memory-extraction.md) (`LiveDungeonCooldownReader`), and [US-076](US-076-complete-client-player-stats-reader.md) (`LivePlayerStatsReader`).
- The reverse engineering process follows deterministic static binary analysis of the PE executable file on disk:
  1. **PE32+ Header Parsing**: Extracts section table (`.text`, `.rdata`, `.data`), image base (`0x140000000`), and exports.
  2. **MSVC RTTI & VTable Resolution**: Scans `.rdata` and `.data` for TypeDescriptors (`.?AVCMover@@`, `.?AVCWndDungeonCooldownList@@`, `.?AVCPlayerDataCenter@@`, `.?AVCWndStatus@@`) and traverses `_RTTICompleteObjectLocator` descriptors to locate authoritative virtual method tables.
  3. **Player Object & Position Pointer**: Scans `.text` for `GetPlayer()` pattern (`48 8B 05 [disp32]; C3`) to extract `g_pPlayer` RVA (`0x00B7C908`) and coordinate offset (`+0x188`).
  4. **Player Vital Stats Offsets**: Disassembles HUD draw / status calculation routines (`0x006BCB70`, `0x008545A0`) where `(HP * 100) / MaxHP` is computed to extract HP, MP, FP struct offsets.
  5. **Camera & Projection Matrix RVAs**: Scans cross-references to Direct3D matrix routines (`D3DXMatrixLookAtLH`, `D3DXMatrixPerspectiveFovLH`) to resolve camera pointer RVA (`0x00BAD8E8`) and projection matrix RVA (`0x00D76B80`).
  6. **Dungeon State Pointer**: Disassembles `CWndDungeonCooldownList` update logic (`0x00461570`) to resolve global dungeon manager pointer RVA (`0x00B7BF28`).
- Analysis operates 100% offline against the local executable file without requiring a running game process or elevated privileges.

## Acceptance criteria

- [x] Given a local target client directory containing `neuz.exe`, when the automated binary profiler is executed, then it parses the PE headers and scans section byte streams without external disassembler dependencies (e.g. standard library PE/x86-64 decoder).
- [x] Given MSVC RTTI symbols are present in `.rdata`, when the profiler executes, then it authoritatively identifies the VTables for `CMover`, `CWndStatus`, and `CWndDungeonCooldownList`.
- [x] Given `GetPlayer()` instruction sequences are identified, when displacement calculations are evaluated, then the profiler extracts the exact `g_pPlayer` pointer RVA (`0x00B7C908`) and validates the local player coordinate offset (`+0x188`).
- [x] Given HUD calculation routines are analyzed, when mathematical operations (`imul`, `idiv`, `cvtsi2ss`) are decoded, then the profiler extracts the player stat field offsets (`hp`, `mp`, `fp`, `level`, `exp`) and generates a typed `ClientPlayerStatsProfile`.
- [x] Given Direct3D matrix transformation routines are analyzed, when view and projection instructions are decoded, then the profiler extracts `camera_pointer_rva` and `projection_matrix_rva` and generates a typed `ClientCameraProfile`.
- [x] Given dungeon window routines are analyzed, when global manager references are decoded, then the profiler extracts `runtime_state_pointer_rva` and generates a typed `ClientDungeonProfile`.
- [x] Given the Setup Wizard executes stage 5 ("Client-Speicherprofile"), when the extractor runs, then the automated binary profiler executes automatically, writes the generated profile records to `data/config/` mapped to the executable's SHA-256 fingerprint, and reports a completed stage status.
- [x] Given the desktop UI is open, when the operator clicks the "Profile neu analysieren / Re-scan Profiles" button in the Setup Wizard or Settings dialog, then the profiler re-runs against the selected client binary and updates the live readiness indicators immediately.
- [x] Given an invalid, corrupt, or unresolvable executable is analyzed, when profiling cannot discover mandatory pointer RVAs, then the profiler fails closed, emits a localized diagnostic error, and prevents writing invalid or guessed memory offsets.
- [x] All user-visible buttons, status messages, error logs, and tooltips are synchronized in German (`de.json`) and English (`en.json`).

## Out of scope

- Dynamic runtime memory pattern scanning, memory scraping, or cheat-engine style memory searches.
- Direct process injection, DLL hijacking, or API hooking (`WriteProcessMemory`, `SetWindowsHookEx`).
- Reverse engineering of non-x64 client architectures or non-Entropia binary variants.
- Automated deobfuscation of commercial packer/virtualizer protections (e.g. Themida/VMProtect).

## Verification

- Automated:
  - Unit tests for PE32+ header parser reading machine types, sections, and RVA-to-file-offset calculations.
  - Unit tests for MSVC RTTI locator resolution identifying mock/fixture VTables and class descriptors.
  - Unit tests for instruction pattern matching extracting `g_pPlayer`, camera, and dungeon pointers from synthetic opcode fixtures.
  - Unit tests verifying JSON serialization and schema conformity of generated `client_profiles.json`, `client_player_stats_profiles.json`, `client_camera_profiles.json`, and `client_dungeon_profiles.json`.
  - Unit tests asserting fail-closed behavior when analyzing malformed or synthetic non-matching binaries.
  - Check suite passes cleanly: `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows):
  - Run the Setup Wizard against the local Entropia Flyff client directory and verify all 4 memory profile configuration files in `data/config/` are automatically populated with exact RVAs matching `neuz.exe`.
  - Launch the game client and verify on the PySide6 dashboard that GPS Position, Camera Status, Player Vitals, and Dungeon Status all transition to "Fehlerfrei / ok" simultaneously.
  - Click the "Profile neu analysieren" button in the UI and verify that profiles are deterministically re-extracted in under 2 seconds.
