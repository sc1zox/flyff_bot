---
id: BUG-020
title: Emergency recovery measures world-unit GPS movement against a minimap pixel threshold
status: fixed
severity: medium
created: 2026-08-20
updated: 2026-08-20
---

# BUG-020: Emergency recovery measures world-unit GPS movement against a minimap pixel threshold

## Environment

- Windows version: Windows 10/11
- Python version: 3.14
- Application revision: `4a81b34` (US-059)
- Client/server version: Entropia Flyff PServer (`neuz.exe`)

## Reproduction

1. Start a farming session with an emergency teleport hotkey configured.
2. Let the character walk normally inside a spawn camp while live GPS is available.
3. Watch `EmergencyRecoveryMonitor.stuck_seconds` across ticks.

## Expected behavior

The unrecoverable-stuck monitor compares the distance the character covered against a threshold
expressed in the same coordinate space the distance is measured in.

## Actual behavior

US-059 replaced the minimap odometry estimate with live GPS: `FarmingOrchestrator` now feeds
`live.x` / `live.z`, which are client world units, into `EmergencyRecoveryConfig`. That config
still carried `progress_distance_pixels = 10.0`, documented as "below one navigation cell
(15 minimap pixels)". Name, value, and calibration comment all described the removed minimap
pixel space, so the progress test compared world units against a pixel threshold and the
teleport recovery fired on the wrong evidence.

## Impact and frequency

- Impact: medium - the last-resort teleport either never triggers or triggers while the
  character is walking normally, depending on the map's unit scale.
- Frequency: always, in every session with live GPS since `4a81b34`.

## Regression verification

- [x] A failing automated test or deterministic manual check exists.
      `tests/unit/test_emergency_recovery.py::test_progress_is_measured_in_client_world_units`
      pins the world-unit semantics.
- [x] The check passes after the fix. The field is now `progress_distance_units`, defaulting to
      `DEFAULT_PROGRESS_DISTANCE_UNITS = 3.0`, calibrated against `REPEATED_STALL_RADIUS_UNITS`,
      and `observe()` takes `position_x` / `position_z` to name the world plane it measures.
- [x] Related documentation is current.
