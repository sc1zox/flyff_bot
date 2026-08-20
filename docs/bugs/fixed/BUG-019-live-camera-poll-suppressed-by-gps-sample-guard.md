---
id: BUG-019
title: Live camera poll suppressed by the GPS sample guard freezes the steering heading
status: fixed
severity: high
created: 2026-08-20
updated: 2026-08-20
---

# BUG-019: Live camera poll suppressed by the GPS sample guard freezes the steering heading

## Environment

- Windows version: Windows 10/11
- Python version: 3.14
- Application revision: `4a81b34` (US-059)
- Client/server version: Entropia Flyff PServer (`neuz.exe`)

## Reproduction

1. Start `neuz.exe`, log in, and confirm live GPS and camera geometry are available.
2. Arm vector navigation on a spawn zone and start farming.
3. Let the session steer for more than one tick and rotate the camera in the client.
4. Compare the heading the path inspector reports with the client's actual camera yaw.

## Expected behavior

`PathingController` re-reads the live camera once per tick, so `heading_degrees` follows the
client's camera yaw and `_steer` compares the bearing to the current heading.

## Actual behavior

`_poll_live_camera` compared its freshness guard against `self._live_sampled_at_seconds`, the
timestamp of the *position* read. Both call sites (`track`, `step`) poll the position first, so
from the second tick onwards the guard was always satisfied and the camera reader was never
called again. `heading_degrees` returned the yaw of the very first frame for the rest of the
session, and steering decisions were computed against that frozen heading. The camera was only
re-read while GPS was unavailable, which is exactly when navigation is blocked anyway.

## Impact and frequency

- Impact: high - every rotation decision after the first tick uses a stale heading, so the
  character turns the wrong way or never converges on a waypoint bearing.
- Frequency: always, in every session with both a position reader and a camera reader.

## Regression verification

- [x] A failing automated test or deterministic manual check exists.
      `tests/unit/test_vector_pathing.py::test_live_camera_is_polled_on_every_tick_while_gps_is_live`
      failed with `assert 1 == 2` before the fix.
- [x] The check passes after the fix. `_poll_live_camera` now guards against its own
      `_camera_sampled_at_seconds`, which is reset together with the camera state.
- [x] Related documentation is current.
