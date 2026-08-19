# ADR-006: Unrestricted read-only process memory access for runtime game state extraction

- Status: accepted
- Date: 2026-08-20
- Related stories: [US-048](../user-stories/completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md), [US-053](../user-stories/completed/US-053-pure-gps-navigation-and-client-profile-configuration.md), [US-054](../user-stories/US-054-farming-telemetry-and-adaptive-navigation-dataset.md), [US-056](../user-stories/US-056-client-camera-state-and-projection-matrix-reader.md)
- Evidence: [Entropia client navigation data extraction](../sources/2026-08-19-entropia-client-navigation-data-extraction.md)

## Context

Previous iterations constrained runtime `ReadProcessMemory` access strictly and exclusively to live player/actor world coordinates (US-048, US-053). However, advanced perception, telemetry, screen unprojection, and 3D navigation features (such as US-056 Camera State & Projection Matrix Reader and US-054 Kinematics Telemetry) require reading additional client structures such as camera eye position, pitch/yaw angles, zoom/FOV, and $4 \times 4$ View/Projection matrices.

Restricting `ReadProcessMemory` to coordinates created an artificial barrier between permitted read-only data extraction capabilities, requiring ad-hoc exemptions for each new read-only structure.

## Decision

1. **Permit read-only client memory access for game state extraction:**
   Read-only access to the game client's process memory (`ReadProcessMemory`) via documented Windows APIs is permitted for reading runtime game state structures necessary for automation, navigation, perception, telemetry, and diagnostics (including player/actor coordinates, camera parameters, view/projection matrices, and client state structures).

2. **Preserve non-invasive safety boundaries:**
   The memory safety boundaries remain strict:
   - Memory handles are opened strictly read-only (`PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION`).
   - Strictly NO memory writes (`WriteProcessMemory`, `VirtualAllocEx`, patching).
   - Strictly NO code injection, DLL injection, API hooking (e.g., Direct3D `EndScene` hooking), anti-cheat evasion, stealth bypasses, or credential handling.
   - Foreground window focus checks and emergency stop mechanisms remain mandatory before dispatching any simulated input.

3. **SHA-256 binary profile configuration:**
   Memory offsets and pointer paths must continue to be organized by client executable SHA-256 fingerprint in configuration registries (e.g., `client_profiles.json`, `client_camera_profiles.json`) with graceful fallback when offsets or signatures are unavailable.

## Alternatives

- **Keep coordinate-only restriction and rely on CV / inverse-perspective heuristics:**
  Rejected because perspective heuristics suffer from drift, pitch ambiguity, and calibration errors, whereas direct read-only extraction of view/projection matrices yields mathematically exact screen-to-world rays without writing memory.
- **Grant ad-hoc exemptions per user story:**
  Rejected because it introduces unnecessary friction and fragmentation in the project rules whenever read-only perception needs expand.

## Consequences

- US-056 (`LiveCameraReader`) and future perception/telemetry features can read camera vectors, matrices, and state without rule conflicts.
- Code must maintain typed, read-only memory readers with structured error handling (`PROCESS_VM_READ` only).
- Safety invariant is simplified: *read-only memory inspection is allowed; any form of memory mutation, injection, or stealth evasion is strictly forbidden*.

## Verification

- Automated tests continue to verify memory readers against mocked process memory buffers (`tests/unit/test_live_position.py`, `tests/unit/test_live_camera.py`).
- Static analysis and check script (`./scripts/check.ps1`) ensure no prohibited write APIs or injection mechanisms are introduced.
