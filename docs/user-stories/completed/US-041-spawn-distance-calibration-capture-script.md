---
id: US-041
title: Automated mob spawn distance and bearing calibration capture script
status: completed
created: 2026-08-18
updated: 2026-08-18
---

# US-041: Automated mob spawn distance and bearing calibration capture script

## Story

As a **developer or operator preparing the mob distance model for US-037**, I want **a dedicated calibration script that records synchronized walk-in approach sequences (YOLO bounding box heights + minimap odometry) and stationary bearing offsets**, so that **the inverse perspective relation and horizontal field of view can be fitted from real game evidence without manual stopwatch estimation**.

## Context and assumptions

- [US-037](../US-037-measured-spawn-distance-and-enforced-leash.md) requires measured calibration data to
  replace the provisional bounding-box distance and half-angle literals in
  `PathingController._estimate_mob_position` (`src/flyff_bot/features/navigation/pathing.py:380-405`).
- The theoretical model under pinhole perspective projection is:
  $$\text{distance} = \frac{a}{\text{bbox\_height}} + b$$
  where $a$ is directly proportional to the camera focal length (zoom factor) and effective camera pitch,
  and $b$ accounts for the melee stopping offset and camera perspective intercept. If camera zoom is
  modified, the apparent bounding-box height $h$ changes drastically for the same real distance.
- **100% reproducibility in-game without memory inspection or injection:**
  - **Zoom Hard Stop (Maximal Zoom-Out):** Scrolling the mouse wheel completely backwards (~10–15
    steps until reaching the hard limit). Flyff enforces a fixed, hard maximum camera distance,
    making this state deterministic and perfectly reproducible across all sessions.
  - **Controlled 45° Camera Pitch:** Pure top-down or maximum tilt is impractical because it severely
    limits forward field of view (FOV) and hides distant mob spawns. Instead, calibrate and run with a
    controlled ~45° pitch (achieved reproducibly by moving the camera to a vertical hard-stop/reset and
    adjusting to a standard 45° farming elevation).
  - **Bot Runtime Consistency:** As long as standard farming sessions operate at this same zoom
    hard-stop and controlled 45° pitch, the calibrated $(a, b)$ parameters correspond exactly to live
    in-game reality.
- To separate $a$ and $b$ robustly, multiple approach sequences across different initial distances
  and mob classes are required.
- [US-035](US-035-measured-minimap-odometry-and-tracking-quality.md) introduced
  `scripts/capture_minimap_samples.py` as a developer calibration harness for minimap odometry. A
  matching dedicated script (`scripts/capture_spawn_distance_samples.py`) is needed to collect the
  raw evidence for US-037.
- Safety boundaries: The script operates in Windows foreground mode, dispatches `W` through the
  standard Win32 input boundary, checks for foreground focus before and during runs, and honors the
  `END` key emergency stop immediately.
- Developer diagnostic output: Console messages and summary outputs are developer tools and
  deliberately do not go through `locales/` (matching `capture_minimap_samples.py`).

## Progress on 2026-08-18

`scripts/capture_spawn_distance_samples.py` implements all three subcommands, and its pure logic
(manifest schema, sample extraction, curve fitting, argument parsing, window-safety gate) is covered
by `tests/unit/test_spawn_distance_calibration.py`. The verification gate is green.

### What a walk-in actually measures

The story's relation `distance = a / h + b` is not directly observable, because the client stops the
character at melee range and the absolute distance to the mob is therefore never known. What the
odometry does measure per frame is how far the character still travels from that frame until the
approach ends:

    remaining_travel(i) = total_travel_of_the_run - travel_up_to_frame(i)

Substituting the observable into the model gives `remaining_travel = a / h + (b - r_melee)`. `a` is
recovered unchanged, and the fitted intercept is the *combined* intercept with the melee stopping
distance folded into it, which is the second of the two options
[US-037](../US-037-measured-spawn-distance-and-enforced-leash.md) criterion 1 allows. That is what the
`fit` subcommand reports. Remaining travel is accumulated backwards from the stop, so an unmeasured
odometry increment invalidates only the frames *before* it; those are dropped rather than silently
under-counted.

### Deviations from the criteria as written

- Run directories are named `<timestamp>-<protocol>-<label>` rather than `<timestamp>_<label>`,
  under the `data/calibration/spawn_distance/` root the story specifies. The protocol segment
  matches the convention `scripts/capture_minimap_samples.py` established and keeps walk-in and
  bearing runs distinguishable in a glob.
- Per-frame snapshots are stored as bounding-box crops of the target-class detection plus the two
  uncropped reference frames bracketing the run, which is the "or bounding box crops" option of
  criterion 1. Full frames per detection tick would cost roughly 4.3 MB each with detection running
  inline, and the crop is the evidence a later reviewer needs to judge whether the box bounds the
  model.
- `scripts/` is now type-checked and importable by tests (`files`, `mypy_path`, and pytest
  `pythonpath` in `pyproject.toml`), because the fitting and manifest logic is unit tested.

### Not yet done: the recordings themselves

No approach sequence has been recorded. The manual Windows verification of this story, and with it
US-037 criteria 1 and the fit-dependent bullets of criterion 2, still needs an operator to run the
harness against a live client and ingest the result into `docs/sources/`. This story delivers the
instrument, not the measurement.


## Acceptance criteria

### 1. Synchronized walk-in approach protocol

- [x] Given a running Flyff client and a stationary mob of a specified class, when the operator runs
  `python scripts/capture_spawn_distance_samples.py walk-in --mob-class <name> --label <run_label>`,
  then the script executes a configurable countdown (default 3.0s), focuses the client window, holds
  the forward movement key (`W`), and records frame-by-frame data until the key hold expires or the
  operator triggers an emergency stop.
- [x] Given a walk-in run executed at the standardized camera conditions (zoom hard-stop and controlled
  ~45° pitch), on every captured frame, the script extracts and logs:
  - High-resolution timestamp (`time.perf_counter()`),
  - Minimap odometry displacement $(\Delta x, \Delta y)$ and tracking quality from `MinimapOdometer`,
  - YOLO mob detection bounding box coordinates ($x_{min}, y_{min}, x_{max}, y_{max}$), height, width,
    class label, and detection confidence,
  - Current viewport dimensions and camera pitch metadata.
- [x] Given completed walk-in frames, the script saves lossless frame snapshots (or bounding box crops)
  and a complete `manifest.json` under `data/calibration/spawn_distance/<timestamp>_<label>/`.

### 2. Bearing and field-of-view calibration protocol

- [x] Given a running client with mobs at various horizontal pixel offsets on screen, when the operator
  runs `python scripts/capture_spawn_distance_samples.py bearing --label <run_label>`, then the script
  records stationary frames logging the pixel $x$-offset relative to the viewport center and the
  player heading from `MinimapOdometer`.

### 3. Offline curve fitting subcommand

- [x] Given one or more recorded run manifests for a mob class, when the operator runs
  `python scripts/capture_spawn_distance_samples.py fit --input <path_or_glob>`, then the script
  computes the least-squares fit for $d = a / h + b$, reports the fitted parameters $(a, b)$, the
  residual standard error, sample count, and held-out cross-validation accuracy.

### 4. Safety boundaries and error handling

- [x] Given the Flyff client window is not running or not foregrounded, when a capture run is initiated,
  then the script halts before dispatching any key presses and outputs a clear diagnostic error.
- [x] Given an active walk-in run, when the operator presses the `END` key (`VK_END`), then the script
  instantly releases all held keys, flushes already-captured frames to disk, and terminates safely.

## Out of scope

- Direct inclusion into the shipped `flyff_bot` runtime package (this is an offline developer tool
  under `scripts/`).
- Full bot autonomy or combat execution during calibration.
- Dynamic camera pitch adjustment during a single walk-in run.

## Verification

- Automated:
  - CLI argument parsing and configuration unit tests.
  - Curve fitting unit tests asserting $(a, b)$ are correctly recovered from synthetic inverse-distance data.
  - Manifest schema serialization and deserialization unit tests.
  - `pwsh -File .\scripts\check.ps1`.
- Manual (Windows):
  - Execute a walk-in sequence against a live Flyff mob (e.g. *Aibatt* or *Mushpang*) and verify that
    the generated `manifest.json` contains valid decreasing distances and increasing bounding box heights.
  - Run `--fit` over recorded runs and verify residual standard error $< 1.5$ minimap pixels.
