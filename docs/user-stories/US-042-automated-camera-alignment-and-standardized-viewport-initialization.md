---
id: US-042
title: Automated camera alignment and standardized viewport initialization
status: ready
created: 2026-08-18
updated: 2026-08-18
---

# US-042: Automated camera alignment and standardized viewport initialization

## Story

As a **bot operator starting a farming session or calibration run**, I want **an automated camera alignment routine that sets the camera to the deterministic zoom hard-stop and a standardized ~45° pitch**, so that **the inverse-perspective mob distance model (US-037/US-041) is 100% deterministic and accurate during both calibration and active farming without manual guess-work or memory manipulation**.

## Context and assumptions

- [US-037](US-037-measured-spawn-distance-and-enforced-leash.md) and
  [US-041](completed/US-041-spawn-distance-calibration-capture-script.md) define the mob distance relation
  $$\text{distance} = \frac{a}{\text{bbox\_height}} + b$$
  under pinhole perspective projection. The coefficient $a$ is directly proportional to focal length
  (camera zoom) and effective camera pitch.
- When the camera zoom or vertical pitch varies, the bounding box height $h$ for a given distance changes
  drastically, which invalidates the fitted constants $(a, b)$ if the camera state is not identical to the
  calibration state.
- **100% reproducibility in-game without memory inspection or injection:**
  1. **Zoom Hard Stop:** Scrolling mouse wheel down/backwards 15 steps reaches Flyff's physical upper zoom
     limit. Because this limit is hard-clamped by the game engine, it produces the exact same deterministic
     focal length across all game sessions.
  2. **Standardized ~45° Pitch:** Maximum or top-down pitch severely limits forward field of view (FOV)
     and hides distant spawns on the horizon. Moving to a vertical pitch limit/reset (e.g. `VK_PRIOR` / Page Up
     or Up Arrow for 0.8s) followed by a calibrated downward tilt pulse (e.g. `VK_NEXT` / Page Down or Down
     Arrow for ~0.35s) positions the camera at the standard ~45° elevation.
- `WindowsInputController` provides foreground-guarded key holds (`send_key_while_guarded`) and mouse
  dispatching.
- Safety boundaries: The alignment routine must verify foreground window focus, abort immediately on focus
  loss or `VK_END` emergency stop, and never dispatch blind inputs.
- Operator workflow:
  - An operator can trigger "Align Camera" on demand from the UI when farming is paused.
  - A configurable checkbox "Auto-align camera on start" (persisted or defaulted to true) allows
    `FarmingOrchestrator` to automatically run pre-flight alignment before the first farming tick.
  - The developer calibration harness (`capture_spawn_distance_samples.py`) can also leverage the same
    alignment procedure before walk-in and bearing recordings.

## Acceptance criteria

### 1. Guarded camera alignment routine

- [ ] Given a focused Flyff client window, when `CameraAligner.align()` is called, then it executes the
  standardized alignment sequence:
  1. Sends 15 mouse wheel scroll down steps to reach the physical zoom hard-stop.
  2. Holds the vertical pitch-up key to reach the vertical ceiling/limit.
  3. Dispatches a calibrated pitch-down pulse to set the standardized ~45° elevation.
- [ ] Given an active alignment sequence, when the client loses foreground focus or the operator holds `END`,
  then the alignment immediately halts and returns an explicit failure status without executing remaining
  actions.

### 2. Farming session pre-flight integration

- [ ] Given `auto_align_camera` is enabled in `FarmingConfig`, when the operator starts a farming session, then
  the orchestrator executes the camera alignment pre-flight before transitioning to active perception and
  combat.
- [ ] Given pre-flight alignment is executing, when the dashboard renders, then the status displays a dedicated
  localized alignment state ("Aligning camera...").
- [ ] Given pre-flight alignment fails (due to focus loss, emergency stop, or invalid window), then the
  orchestrator transitions cleanly to paused/stopped state with an explanatory status message rather than
  crashing or continuing with uncalibrated perspective.

### 3. Dashboard UI controls and localization

- [ ] Given the desktop dashboard in paused state, when the operator clicks the "Align Camera" button, then the
  alignment routine runs for the foregrounded game window.
- [ ] Given the dashboard settings panel, the operator can toggle "Auto-align camera on start" with instant
  effect.
- [ ] All new user-visible text (button labels, status messages, tooltips, dialogs) is present and synchronized
  in `src/flyff_bot/locales/de.json` and `en.json`.

## Out of scope

- Continuous active camera tracking or dynamic pitch re-adjustment during combat.
- In-memory camera matrix extraction or direct DirectX hook manipulation.
- Modifying game keybindings outside the standard Flyff camera keys.

## Verification

- Automated:
  - Unit tests for `CameraAligner` verifying the step sequence, timing constants, and abort conditions on
    mocked input adapters.
  - Unit tests for `FarmingOrchestrator` pre-flight lifecycle (success, abort on focus loss, skip when disabled).
  - Unit tests for UI button and checkbox state wiring.
  - `pwsh -File .\scripts\check.ps1`.
- Manual (Windows):
  - Click "Align Camera" on a live client from arbitrary zoom/pitch and verify the client zooms all the way
    out and sets the ~45° pitch.
  - Start a farming session with auto-align enabled and verify smooth pre-flight execution into active farming.
