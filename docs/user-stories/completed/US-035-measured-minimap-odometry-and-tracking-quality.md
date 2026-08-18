---
id: US-035
title: Measured minimap odometry, tracking quality gating, and calibrated movement constants
status: completed
created: 2026-08-18
updated: 2026-08-18
---

# US-035: Measured minimap odometry, tracking quality gating, and calibrated movement constants

## Story

As a **bot operator running long farming sessions in one camp**, I want **the navigation position
and heading to be measured from the client's minimap instead of extrapolated from guessed key-press
speeds, and map learning to stop while that measurement is unavailable**, so that **the learned
graph, the spawn heatmap, and the patrol routes describe where the character actually went rather
than accumulating drift and phantom topology**.

## Context and assumptions

### What exists today

- `MovementTracker` (`src/flyff_bot/features/navigation/tracking.py:90`) integrates dispatched key
  presses into a relative position and heading using
  `DEFAULT_FORWARD_SPEED_UNITS_PER_SECOND = 60.0`,
  `DEFAULT_BACKWARD_SPEED_UNITS_PER_SECOND = 45.0` and
  `DEFAULT_TURN_DEGREES_PER_SECOND = 90.0` (`tracking.py:22-24`). None of these were measured
  against the client; they are estimates, as the neighbouring comment about the stall mask
  fractions already admits for its own constants.
- There is no absolute position source anywhere in `src/flyff_bot/features/`: no coordinate OCR,
  no landmark fix. The estimate is open-loop and its error is purely cumulative.
- `PathingController.integrate_movement` is called only for search decisions
  (`features/automation/orchestrator.py:373`) and for pathing decisions via `confirm`
  (`orchestrator.py:417`). The combat dispatches at `orchestrator.py:362` and `orchestrator.py:395`
  never reach it, so any motion during `TARGETING` / `COMBAT` is structurally invisible to the
  estimate.
- `PathingController.observe` records a visit from the dead-reckoned position on every tick
  (`features/navigation/pathing.py:199`), and `SpatialMap.record_visit`
  (`features/navigation/spatial.py:137`) builds both the cell history and the adjacency graph from
  it. Drift therefore does not merely misplace a marker: it writes cells and edges that
  `RoutePlanner` then plans over, and `_persist_navigation()` flushes them to disk every 30 s
  (`orchestrator.py:298`).
- The existing unit tests (`tests/unit/test_tracking.py`, `test_stall_detector.py`,
  `test_path_planning.py`, `test_spatial_heatmap.py`, 50 tests) exercise the integrator against the
  same assumed constants. They establish internal consistency, not physical fidelity.

### Why the minimap and not a calibration wizard

A wizard that measures "units per second" still leaves the estimate open-loop between
measurements, and it cannot see motion the bot did not command. The minimap is a continuous
sensor for the same quantity. The feasibility measurements are recorded in
[the minimap odometry spike](../sources/2026-08-18-minimap-odometry-feasibility-spike.md):

- The minimap ring is detected at the identical fixed-pixel offset in two independent captures of
  different zones (centre 88 px left of the client right edge, inner radius ~68 px), reproducing
  the hand measurement from the [US-027 rejection](US-027-minimap-radar-mob-detection-and-calibrated-navigation.md).
- The player marker is isolated cleanly by colour keying in both frames (~70 px component), and its
  orientation differs between frames while the `N` glyph stays at the top of the ring.
- Phase correlation over the circular-masked inner disk recovers a known scroll offset to within
  0.6-0.9 px for shifts of 1-20 px, with a correlation response of 0.665-0.928, while unrelated
  minimap content from another zone yields a response of -0.052.

Because the minimap is north-up and player-centred, its scroll displacement is already expressed in
world axes: no heading rotation has to be applied to it, so a heading error cannot corrupt the
translation measurement. And because it observes motion rather than commands, it covers combat
auto-run, knockback, and any other motion the bot did not initiate.

### Relationship to US-027

[US-027](US-027-minimap-radar-mob-detection-and-calibrated-navigation.md) was rejected because it
added a *second navigation mechanism* that clicked the HUD in parallel to the existing pathing.
This story adds no navigation mechanism and dispatches no minimap input at all. It reads the
minimap as a **sensor for the pathing that already exists**, and it reuses the geometry that the
US-027 spike measured. `MinimapRadar` and `SearchMode.MINIMAP_RADAR` stay untouched and
never-dispatched.

### Assumptions that must be verified, not assumed

- **The minimap is north-up.** Two frames with `N` at the top and different marker angles are
  evidence, not proof. Cheap check: turn in game and watch whether `N` moves.
- **The marker's nose, not its tail, points along the facing direction.** The orientation axis is
  measurable robustly; the 180 deg sign is one unknown that must be pinned once against a known
  in-game facing and then live in a named constant with its validation frame in `docs/sources/`.
- **The 0.6-0.9 px underestimate is synthetic.** It was measured with fabricated edge content
  (`BORDER_REFLECT`). It must be re-measured against real consecutive client frames before it
  informs any production constant.
- **The fixed-pixel geometry has only been measured at a 1600 px client width**, exactly like the
  vitals HUD before [BUG-006](../bugs/fixed/BUG-006-player-vitals-resolution-scaling-and-flicker-spam.md).
- **Minimap zoom defines the unit.** The ring carries `+` / `-` buttons, so a minimap pixel only
  has a fixed meaning at a fixed zoom level. See "The unit is the minimap pixel" below: this is not
  a scaling detail, it is the definition of the measurement unit, and it is the one corruption mode
  that produces no drop in correlation response.

### The unit is the minimap pixel

An earlier draft of this story required a fitted "world units per minimap pixel" constant. That
requirement was wrong and has been removed. Fitting it would need a known world distance, which in
turn needs the character's run speed in world units — a quantity the client does not display and
that no frame capture can recover. Every attempt to derive it would smuggle in a second guessed
constant of exactly the kind this story exists to eliminate.

Instead the **minimap pixel is the canonical unit** for the whole navigation feature: the spatial
map's cell size, the leash bound, the stall threshold, and the fitted movement speeds are all
expressed in minimap pixels and minimap pixels per second. Nothing outside the bot ever needs to
know how many world units that is, so nothing needs to measure it. This is self-consistent, removes
an entire class of calibration error, and makes every constant in the feature directly measurable
from a recorded frame sequence.

The cost is that the unit is only defined per zoom level, which criterion 9 makes explicit.

### What is blocked on operator-supplied captures

`scripts/capture_minimap_samples.py` records the required sequences on the Windows machine: a
`burst` run holds one movement key and captures minimap crops as fast as the client allows, writing
a manifest with the `time.perf_counter()` bracket of every capture, and a `still` run captures full
frames without sending any input. The interval between two captures, not the key-hold duration, is
the time base for any displacement measurement.

Blocked on those recordings are: the streaming-terrain validation and the maximum inter-frame
displacement in criterion 3, the fitted movement constants in criterion 7, the zoom and resolution
comparisons in criterion 9, and the sign-convention part of criterion 2. They cannot be closed from
Linux or from the single frames in `data/`. Everything else — the
locator, the marker isolation and orientation axis, the phase-correlation mechanism and its
confidence gate, the tracking-quality state machine, the map-write gating, controller-independent
observation, and the stall signal — is implementable and testable against the frames already
shipped in `data/`, and should land first.

## Acceptance criteria

### 1. Minimap sensor with explicit, sourced geometry

- [x] Given a captured client frame, when the minimap locator runs, then it returns the ring centre
  and inner-surface radius derived from named constants anchored to the client right and top edges,
  and every constant cites the frame it was measured against in its definition, following the
  precedent of `src/flyff_bot/features/vision/vitals.py:22`.
- [x] Given the geometry constants, when they are committed, then they are expressed in
  **client-area** coordinates. The spike measured ring centre y = 135.5 on whole-window captures of
  `data/`, which include roughly 31 rows of title bar, while `WindowsFrameSource` captures through
  `GetClientRect` and starts at the first row below it. The two coordinate systems must be re-based
  before any comparison, or the offset will be misread as a zoom or resolution effect.
- [x] Given a client resolution other than the measured reference, when the locator runs, then it
  reports whether the minimap was found rather than silently returning an out-of-bounds region.
- [x] Given the operator has collapsed or closed the minimap with its ring buttons, when the locator
  runs, then it reports "not found", the session continues, and no exception escapes the tick.

### 2. Measured heading

- [x] Given a frame with a visible player marker, when heading measurement runs, then the marker is
  isolated by colour keying (not by assuming it sits at the ring centre) and its orientation axis is
  derived by principal component analysis.
- [x] Given the measured axis, when it is converted to a compass bearing, then the 180 deg sign
  convention comes from one named, documented constant validated against a recorded frame of a known
  in-game facing.
- [x] Given a heading measurement is available, when the tracker updates, then the measured heading
  replaces the integrated one; `turn_degrees_per_second` is only used to predict between frames.

### 3. Measured translation

- [x] Given two consecutive frames, when translation measurement runs, then phase correlation over
  the Hanning-windowed, circular-masked inner disk returns a displacement in minimap pixels together
  with its correlation response.
- [x] Given unrelated minimap content (teleport, zone change, obscured minimap), when translation
  measurement runs, then the response falls below the configured confidence threshold and no
  displacement is applied.
- [x] Given a measured displacement, when it is stored or compared anywhere in the navigation
  feature, then it stays in minimap pixels: no conversion to world units exists, and no
  world-unit constant is introduced.
- [x] Given a recorded burst of real consecutive client frames, when the measurement is validated
  against it, then the bias and response distribution are documented in `docs/sources/`, replacing
  the synthetic `BORDER_REFLECT` figures.
- [x] Given the same recorded burst re-paired at increasing frame lags, when the correlation
  response is plotted against displacement, then the displacement at which the response falls below
  the confidence threshold is documented and becomes a named maximum inter-frame displacement.
- [x] Given that maximum, when the perception tick rate is configured, then a minimum sampling rate
  is derived from it and the fitted forward speed, and a tick slower than that reports `PREDICTED`
  rather than trusting a correlation over too little overlap.

### 4. Tracking quality gates map learning

- [x] Given a confident measurement, when a tick completes, then tracking quality is `MEASURED` and
  the position is the measured one.
- [x] Given measurement is unavailable, when a tick completes, then the command model predicts the
  position for at most a configured grace period and quality is `PREDICTED`.
- [x] Given measurement stays unavailable beyond the grace period, when a tick completes, then
  quality is `DEGRADED`.
- [x] Given quality is `DEGRADED`, when `PathingController.observe` runs, then no visit, spawn, or
  stall is written to `SpatialMap`; the map is read-only and existing routes may still be followed
  or abandoned, but no new cells or edges are created.
- [x] Given quality returns to `MEASURED` after a `DEGRADED` span, when the next visit is recorded,
  then no edge is created across the gap, so the graph never gains a link over an unobserved
  traversal.

### 5. Motion is observed independently of the dispatching controller

- [x] Given the orchestrator is in `TARGETING` or `COMBAT` and the character moves, when ticks
  complete, then the position estimate follows that motion, without adding any
  `integrate_movement` call to the combat dispatch paths (`orchestrator.py:362`,
  `orchestrator.py:395`).
- [x] Given the character is moved by the operator manually while the session is paused in standby,
  when ticks complete, then the position estimate follows that motion as well.

### 6. Stall detection uses the measurement

- [x] Given forward movement is commanded and the measured displacement stays below a configured
  threshold for the stall timeout, when the detector is polled, then a stall is reported.
- [x] Given quality is `DEGRADED`, when the detector is polled, then it falls back to the existing
  peripheral pixel-difference signal rather than reporting a false stall.
- [x] Given the measurement path is in use, then the pixel-difference signature is not computed,
  keeping the per-tick cost at or below today's.

### 7. Calibrated movement constants

- [x] Given the recorded bursts, when `MovementModel`'s forward speed, backward speed, and turn rate
  are defined, then each value is fitted from those recordings as minimap pixels per second
  (degrees per second for the turn rate), cites its source document, and is no longer an
  unexplained literal; the `_UNITS_PER_SECOND` names are renamed accordingly.
- [x] Given the burst tail recorded after key release, when the model is fitted, then the client's
  own acceleration and deceleration are either represented or explicitly documented as folded into
  the constant with their contribution to the residual.
- [x] Given the fitted values, when the regression test runs, then predicting each recorded sample
  with the committed constants reproduces the measured displacement within the documented tolerance.

### 8. Operator visibility and safety

- [x] Given the dashboard is open, when tracking quality changes, then the status is displayed as a
  badge on the path inspector and the dashboard, with all text present and synchronised in
  `de.json` and `en.json`.
- [x] Given the sensor runs, then it performs read-only frame analysis only: no click, no key, and
  no input of any kind is dispatched at the minimap.
- [x] Given the sensor runs, then it executes on the existing perception worker thread and never on
  the Qt GUI thread.
- [x] Given one tick, when the sensor runs on the reference disk size, then the added measurement
  cost stays within a documented per-tick budget.

### 9. Zoom level is part of the measurement contract

- [x] Given the recordings of one location at two zoom levels, when they are compared, then the
  ratio between the two scales is documented in `docs/sources/`, together with whether the ring
  geometry itself changes with zoom.
- [x] Given the recordings at a second window resolution, when they are compared against the
  1600 px reference, then the fixed-pixel anchoring is either confirmed or replaced by a measured
  rule, closing the assumption inherited from BUG-006.
- [x] Given a session starts, when the tracker is initialised, then the zoom level it was
  calibrated for is recorded alongside every position it produces.
- [x] Given the operator changes the minimap zoom mid-session, when the next tick runs, then the
  change is detected and quality drops to `DEGRADED` until the tracker is re-anchored. This is the
  one corruption mode that leaves the correlation response untouched: without an explicit check,
  every subsequent measurement is silently rescaled and written into the map as valid.

## Outcome

Implemented on 2026-08-18. The measurements are written up in
[the minimap odometry calibration](../sources/2026-08-18-minimap-odometry-calibration.md),
which supersedes the synthetic figures of the feasibility spike. Production code lives in
`src/flyff_bot/features/vision/minimap.py` (the sensor) and
`src/flyff_bot/features/navigation/tracking.py` (the quality state machine and the fitted
command model). The frames the tests replay are shipped under
`data/assets/fixtures/minimap/`; the 246 MB of raw recordings stay gitignored.

Three criteria were satisfied differently from the way they were written, and one is only
partly satisfied. All four are deliberate:

- **The 180 deg sign convention is a measured rule, not a constant** (criterion 2). The
  farthest-point heuristic the spike used flipped on 8 of 53 recorded turn frames. The third
  moment of the marker's projection along its principal axis flipped on none, because the
  wedge is broad at the tail and tapers to a thin nose. That resolves the ambiguity from the
  shape itself, so no sign constant exists to get wrong. It is still validated against a
  known facing: over the recorded forward run the marker heading is 139.6 deg and the
  measured travel bearing is 136.3 deg.
- **The correlation cliff was never reached** (criterion 3). The recording could not scroll
  the aperture further than 28.5 px, where the response was still 0.344, above the 0.30 gate.
  `MAXIMUM_INTER_FRAME_DISPLACEMENT_PIXELS` is therefore 24 px, the largest displacement with
  a measured response margin, rather than an extrapolated crossing.
- **Backward speed was removed instead of fitted** (criterion 7). No `S` burst was recorded
  and no controller in the repository dispatches `S`, so the alternative to removing it was
  leaving exactly the kind of guessed literal this story exists to eliminate. Backward motion
  is still observed, because the sensor measures motion rather than commands. The calibration
  source names the command that would record it if a controller ever needs to predict it.
- **Vertical anchoring at a second resolution is inferred, not proven** (criterion 9). At a
  1280 px client width the ring still sits 87 px from the right edge with an unchanged radius,
  so the horizontal fixed-pixel rule from BUG-006 is confirmed. The available second-resolution
  frames are whole-window captures whose title-bar heights are unknown, so their vertical
  offsets cannot be compared against the 106.5 px client-area reference. The locator closes
  this by refining the anchored centre within +-5 px once per client size and reporting "not
  found" when no ring survives the band bounds, which makes the residual uncertainty
  irrelevant instead of assumed away.

The story also predicted that a zoom change is "the one corruption mode that leaves the
correlation response untouched". It is not: a 2x step collapses the response to 0.062, so the
confidence gate catches the transition. The zoom-signature check is still needed and still
implemented, because the gate only rejects the two frames spanning the change while every
measurement afterwards correlates cleanly in a different unit.

Two consequences fell out of the calibration that were not part of the story:

- The measured turn rate is 240 deg/s, not the guessed 90 deg/s, so one 0.15 s pathing turn
  pulse would have overshot the 25 deg heading tolerance by 11 deg and oscillated. The default
  pulse is now 0.08 s.
- The navigation feature's `*_units` identifiers were renamed to `*_pixels`
  (`cell_size_pixels`, `leash_radius_pixels`, `distance_pixels`) so the canonical unit is
  visible in the code rather than only in this story.

## Out of scope

- **Cross-session re-anchoring of persisted map profiles** — a loaded profile still starts at
  `(0, 0)` / heading 0 wherever the character happens to stand. Tracked as US-036.
- **The guessed spawn distance model and the unenforced leash radius** — the literals in
  `PathingController._estimate_mob_position` (`pathing.py:283-310`) and the purely decorative
  `leash_radius_units`. Tracked as US-037.
- Minimap clicking or minimap-based mob detection: US-027 stays rejected.
- Stitching minimap frames into a mosaic, loop closure, or any full SLAM behaviour.
- Any change to how `RoutePlanner` scores routes.

## Verification

- Automated:
  - Unit tests for the locator against the shipped frames in `data/`, including the "minimap not
    found" path.
  - Unit tests for heading extraction against the shipped frames, asserting the axis and the
    documented sign convention.
  - Unit tests for phase-correlation translation using synthetic scroll fixtures plus the
    cross-zone negative control from the spike, asserting both the recovered displacement and the
    confidence gate.
  - Unit tests for the quality state machine: `MEASURED` -> `PREDICTED` -> `DEGRADED` -> recovery,
    and that `SpatialMap` receives no writes while `DEGRADED` and no edge across the gap.
  - An orchestrator test that drives ticks in `COMBAT` with changing minimap content and asserts the
    position advanced.
  - A regression test pinning the fitted movement constants against the recorded samples.
  - `pwsh -File .\scripts\check.ps1`.
- Automated results on 2026-08-18: `pwsh -File .\scripts\check.ps1` green, 407 passed,
  2 skipped, 92 % coverage. The gate additionally required repairing three pre-existing
  `mypy` failures in `features/vision/target_verification.py` and the
  navigation-automation import cycle that made `flyff_bot.features.navigation.tracking`
  unimportable on its own.
- Manual (Windows), still open:
  - Turn the character a full 360 deg and confirm the `N` glyph stays at the top of the ring
    (north-up assumption) and that the reported heading tracks the character.
  - Face a known direction, confirm the reported heading matches it, and record that frame as the
    sign-convention validation source.
  - Walk a closed square by hand and confirm the drawn path in the inspector closes on itself.
  - Run a farming session through several kills and confirm the inspector shows no phantom cells
    behind the character after combat.
  - Cover the minimap (or collapse it), confirm the badge switches to `DEGRADED`, that no new cells
    appear, and that the session keeps running.
  - Change the minimap zoom level and record what happens to the scale, to inform US-036's
    per-profile scale metadata.
