# ADR-006: Fingerprinted read-only process memory access for runtime game state extraction

- Status: accepted
- Date: 2026-08-20
- Related stories: [US-048](../user-stories/completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md), [US-053](../user-stories/completed/US-053-pure-gps-navigation-and-client-profile-configuration.md), [US-054](../user-stories/US-054-farming-telemetry-and-adaptive-navigation-dataset.md), [US-056](../user-stories/completed/US-056-client-camera-state-and-projection-matrix-reader.md)
- Evidence: [Entropia client navigation data extraction](../sources/2026-08-19-entropia-client-navigation-data-extraction.md), [Entropia camera and projection static analysis](../sources/2026-08-20-entropia-camera-static-analysis.md)

## Context

Previous iterations constrained runtime `ReadProcessMemory` access strictly and exclusively to live player/actor world coordinates (US-048, US-053). Advanced perception, telemetry, screen unprojection, and 3D navigation features require additional client structures such as camera matrices and client state.

Restricting `ReadProcessMemory` to coordinates created an artificial barrier between permitted read-only data extraction capabilities, requiring ad-hoc exemptions for each new read-only structure.

## Decision

1. **Permit narrowly scoped, fingerprinted reads:**
   Read-only access to the game client's process memory (`ReadProcessMemory`) via documented Windows APIs is permitted for explicitly configured runtime game-state structures necessary for automation, navigation, perception, telemetry, and diagnostics. Every address must be selected by an exact SHA-256 executable profile; readers must use fixed pointer-relative ranges or fixed module-relative RVAs and must not scan, dump, or infer addresses at runtime.

2. **Preserve non-invasive safety boundaries:**
   The memory safety boundaries remain strict:
   - Memory handles are opened strictly read-only (`PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION`).
   - Strictly NO memory writes (`WriteProcessMemory`, `VirtualAllocEx`, patching).
   - Strictly NO code injection, DLL injection, API hooking (e.g., Direct3D `EndScene` hooking), anti-cheat evasion, stealth bypasses, or credential handling.
   - Foreground window focus checks and emergency stop mechanisms remain mandatory before dispatching any simulated input.

3. **Camera profile shape and derived state:**
   `client_camera_profiles.json` must distinguish pointer-relative camera offsets from the independent module-relative projection-matrix RVA. Camera pitch, yaw, FOV, and distance are derived from verified matrices and target vectors; unverified scalar fields are not read or treated as authoritative.

4. **SHA-256 binary profile configuration:**
   Memory offsets and pointer paths must continue to be organized by client executable SHA-256 fingerprint in configuration registries (e.g., `client_profiles.json`, `client_camera_profiles.json`) with graceful fallback when offsets or signatures are unavailable.

## Alternatives

- **Keep coordinate-only restriction and rely on CV / inverse-perspective heuristics:**
  Rejected because perspective heuristics suffer from drift, pitch ambiguity, and calibration errors, whereas direct read-only extraction of view/projection matrices yields mathematically exact screen-to-world rays without writing memory.
- **Grant ad-hoc exemptions per user story:**
  Rejected because it introduces unnecessary friction and fragmentation in the project rules whenever read-only perception needs expand.

## Consequences

- US-056 (`LiveCameraReader`) and future perception/telemetry features can read exact-profile camera vectors and matrices without rule conflicts, while remaining bounded to explicitly configured addresses.
- Code must maintain typed, read-only memory readers with structured error handling (`PROCESS_VM_READ` only).
- Safety invariant is simplified: *read-only memory inspection is allowed; any form of memory mutation, injection, or stealth evasion is strictly forbidden*.

## Verification

- Automated tests continue to verify memory readers against mocked process memory buffers (`tests/unit/test_live_position.py`, `tests/unit/test_live_camera.py`).
- Static analysis of the supported binaries establishes the camera pointer and projection paths. The check script verifies repository quality; it is not a complete detector for prohibited APIs, so code review and the explicit safety contract remain required.
