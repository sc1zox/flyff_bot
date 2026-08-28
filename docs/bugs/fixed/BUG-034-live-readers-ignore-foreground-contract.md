---
id: BUG-034
title: Position and world-ID readers ignore the foreground contract
status: reported
severity: high
created: 2026-08-26
updated: 2026-08-26
---

# BUG-034: Position and world-ID readers ignore the foreground contract

## Environment

- Windows version: Windows 11 Pro 10.0.26200
- Python version: Python 3.14.7 (`uv` environment)
- Application revision: `bd2cde2` on `main`
- Client/server version: Entropia Flyff PServer x64 (`neuz.exe`), SHA-256
  `8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5`

## Reproduction

1. Start the supported client, then keep another application in the foreground. During the live
   audit, `Antigravity.exe` owned foreground focus while the Flyff window was
   `Entropia - Babitzkas`.
2. Construct `LivePositionReader` for the Flyff window and poll it. The reader opens the process and
   returns `PositionSource.LIVE` with position `(8428.203125, 100.0, 3579.460205078125)` even though
   `WindowsInputController.is_foreground()` is false.
3. Inspect `LivePositionReader.poll`. `WindowsProcessMemoryApi` implements
   `is_window_foreground`, and `PositionReadErrorCode.WINDOW_NOT_FOREGROUND` exists, but the poll
   path never calls the method and can never emit that diagnostic.
4. Inspect `LiveWorldIdReader`. Its process protocol has no foreground query and `_ensure_open`
   proceeds directly to process attachment, fingerprinting, module resolution, and the configured
   fixed read. With the current empty registry it stops at `UNSUPPORTED_BUILD`; with a matching
   profile it would read while backgrounded.
5. Compare `LiveCameraReader` and `LivePlayerStatsReader`. Both check foreground before opening or
   reading and return `WINDOW_NOT_FOREGROUND`, demonstrating the intended common boundary.
6. Run the focused live-reader suite. It passes because background coverage exists for camera and
   player stats but not for position or world ID.

## Expected behavior

The repository safety contract, [ADR-006](../../decisions/ADR-006-read-only-process-memory-access.md),
[US-053](../../user-stories/completed/US-053-pure-gps-navigation-and-client-profile-configuration.md),
and [US-065](../../user-stories/completed/US-065-client-teleporter-extraction-and-automated-zone-dispatch.md)
require foreground awareness for the live client boundary.

Before opening a handle or performing any fixed memory read, every live reader must verify that the
configured game window owns foreground focus. A background window must yield a typed
`WINDOW_NOT_FOREGROUND` result, close any retained handle, expose no fresh sample, and recover only
after a later foreground poll. This guard is independent of and additional to the final foreground
check before simulated input.

## Actual behavior

Position reads succeed against a background client and are reported as fresh authoritative GPS.
The world-ID reader contains no foreground check at all. Camera, player stats, dungeon state, frame
capture, and guarded input follow stricter behavior, so the live-provider boundary is internally
inconsistent and readiness can receive a fresh GPS sample obtained under conditions its own
diagnostic enum says should be unavailable.

## Impact and frequency

- Impact: High. The readers violate an explicit safety and lifecycle invariant, retain process
  access when the operator is working in another application, and can make readiness/telemetry
  describe a background sample as valid. Input remains guarded, but the central live-state model is
  not coherent.
- Frequency: Deterministic on every background `LivePositionReader` poll and, when a world-ID
  profile is configured, on every background `LiveWorldIdReader` poll.

## Regression verification

- [ ] A failing `LivePositionReader` test proves a background window is rejected before process
  attachment or memory reading, emits `WINDOW_NOT_FOREGROUND`, and closes a retained handle.
- [ ] The same regression exists for `LiveWorldIdReader` through one shared typed foreground-aware
  process protocol; a background poll performs zero reads.
- [ ] Recovery tests prove the next foreground poll reopens safely and produces a fresh exact-profile
  sample without reusing background timestamps or values.
- [ ] Orchestrator/readiness tests prove a background GPS or world-ID result is unavailable/stale and
  cannot authorize a dependent capability.
- [ ] Camera, player-stats, dungeon, position, and world-ID readers expose consistent diagnostics and
  handle-lifecycle behavior without weakening END/Escape or final dispatcher guards.
- [ ] The real Windows client walkthrough repeats background, foreground, minimize, focus loss, and
  client restart checks while recording that no prohibited API, write, scan, hook, or injection is
  used.
- [ ] Related documentation is current and `./scripts/check.ps1` passes.
