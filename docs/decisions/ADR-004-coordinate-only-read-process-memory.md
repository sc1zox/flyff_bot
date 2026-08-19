# ADR-004: Fingerprinted read-only process memory access for navigation, state, and telemetry

- Status: accepted
- Date: 2026-08-19
- Related stories: [US-048](../user-stories/completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md), [US-053](../user-stories/US-053-pure-gps-navigation-and-client-profile-configuration.md), [US-054](../user-stories/US-054-farming-telemetry-and-adaptive-navigation-dataset.md)
- Evidence: [Entropia client navigation data extraction](../sources/2026-08-19-entropia-client-navigation-data-extraction.md)

## Context

Autonomous navigation, farming automation, target evaluation, combat tracking, and ML telemetry require drift-free, authoritative live ground-truth data (e.g. player 3D coordinates, actor positions, live vitals, and state). 

The local Entropia x86 and x64 clients have distinct memory layouts and base pointers across builds. To ensure reliable automation and unhindered telemetry collection while maintaining a secure, auditable, and non-invasive architecture, clear boundaries for process memory access must be established.

## Decision

1. **Fingerprinted client identification:**
   Supported client executables are identified deterministically by their complete SHA-256 fingerprint and known module-relative offsets.
2. **Permitted read-only memory access:**
   Read-only access to the game client's process memory (`ReadProcessMemory` opened with `PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ`) is permitted for reading authoritative live world coordinates (player position XYZ), actor/mob coordinates, and live character state necessary for navigation, perception, and telemetry collection.
3. **Strict non-invasive safety boundary:**
   Memory writing (`WriteProcessMemory`), dynamic code injection, DLL injection, API/function hooking, packet interception, credential handling, anti-cheat evasion, or stealth behaviors remain strictly prohibited.
4. **Idempotent handle and error management:**
   On process termination, build mismatch, handle invalidation, or read failure, handles are closed cleanly and fallbacks (such as vision-based OCR or minimap odometry) are exposed gracefully. Polling may retry so restarted client instances recover automatically.
5. **Emergency stop guarantee:**
   Application teardown and the emergency stop hotkey close process handles idempotently without affecting process stability.

## Alternatives

- **Absolute addresses:** rejected because ASLR makes module-relative addresses necessary.
- **Version-string profiles:** rejected because different verified binaries report the same file version (e.g. 6.0.0.0).
- **Heuristic memory scanning:** rejected in favor of verified module-relative offsets mapped per binary SHA-256 fingerprint.
- **Minimap-only positioning:** rejected as primary navigation source because vision-based odometry drifts over time and cannot reliably confirm 3D heightfield coordinates.

## Consequences

- Automation and telemetry features have unhindered, authoritative read-only access to essential live client state and 3D coordinates without artificial implementation barriers.
- The project preserves a clean, auditable safety boundary: zero memory writes, zero process injection, and zero anti-cheat tampering.
- Telemetry datasets (US-054) and 3D navigation (US-052/US-053) operate with 100% ground-truth precision.

## Verification

- Unit tests in `tests/unit/test_live_position.py` verify that `LivePositionReader` parses memory buffers and handles invalid pointers/handles gracefully.
- Safety checks confirm that all Windows API bindings to `kernel32.dll` operate in read-only mode (`PROCESS_VM_READ`) and do not invoke `WriteProcessMemory` or `VirtualAllocEx`.
