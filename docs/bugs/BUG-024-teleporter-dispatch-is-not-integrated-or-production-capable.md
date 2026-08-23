---
id: BUG-024
title: Teleporter dispatch is not integrated or production capable
status: reported
severity: high
created: 2026-08-23
updated: 2026-08-23
---

# BUG-024: Teleporter dispatch is not integrated or production capable

## Environment

- Windows version: Windows 11 (automated checks only)
- Python version: Python 3.14.7 (`uv` environment)
- Application revision: branch `refactor/main-window-feature-slices` (commit `d4a166f`)
- Client/server version: Entropia Flyff PServer (`neuz.exe`)

## Reproduction

1. Check out commit `d4a166f` and inspect the completed [US-065](../user-stories/completed/US-065-client-teleporter-extraction-and-automated-zone-dispatch.md) acceptance criteria.
2. Search production wiring for `TeleporterDispatcher`, `LiveArrivalObserver`, and `LiveWorldIdReader`.
3. Observe that only the offline extractor is reachable through `--extract-teleporters`; no navigation, orchestrator, UI, or application composition root constructs the dispatcher.
4. Inspect the world-ID reader and note that no verified client profile ships and production arrival confirmation therefore fails closed without an operator-supplied verified offset.
5. Run `./scripts/check.ps1`; the automated suite passes while US-065 remains unavailable as an end-to-end fast-travel capability.

## Expected behavior

[US-065](../user-stories/completed/US-065-client-teleporter-extraction-and-automated-zone-dispatch.md) requires a navigation route or goal to initiate guarded fast travel after combat settles, confirm arrival with authoritative world identity and coordinates, initialize local 3D pathing in the target zone, and enter safe standby on timeout. A completed story must expose this behavior through its intended feature boundary.

## Actual behavior

The branch contains typed extraction models, a dispatcher state machine, a concrete input adapter, and focused unit tests. However, the dispatcher is dead code outside tests: no caller requests destinations from navigation or goals, ticks the dispatcher with combat observations, consumes confirmation/failure transitions, or initializes follow-up pathing. In addition, arrival requires both live XYZ and world ID; the world-ID provider intentionally refuses to guess when no fingerprint-bound operator profile exists.

## Impact and frequency

- Impact: High. The marked-completed zone-transition story cannot perform automated fast travel end to end; completion overstates delivered behavior.
- Frequency: Deterministic for every attempted teleporter transition on this revision.

## Regression verification

- [ ] A failing integration test proves navigation or goal execution can request a destination, drive dispatcher ticks, and consume confirmed/failed results.
- [ ] A failing test proves confirmed arrival initializes target-zone pathing as required by US-065.
- [ ] A deterministic check documents the required operator-supplied world-ID profile and proves missing-profile behavior fails closed without pretending readiness.
- [ ] The complete repository gate passes after integration.
- [ ] Related documentation accurately distinguishes implemented components from unavailable end-to-end behavior.
