---
id: US-037
title: Measured spawn distance model and an enforced patrol leash
status: in-progress
created: 2026-08-18
updated: 2026-08-18
---

# US-037: Measured spawn distance model and an enforced patrol leash

## Story

As a **bot operator relying on the spawn heatmap to pick the next patrol stop**, I want **mob
sightings to be placed on the map using a distance relation fitted from recorded frames, and the
configured leash radius to actually constrain planning**, so that **hotspots mark where mobs really
stand and the character cannot patrol out of the camp I set it loose in**.

## Context and assumptions

### The spawn distance is currently guessed

`PathingController._estimate_mob_position` (`src/flyff_bot/features/navigation/pathing.py:283-310`)
converts each detected mob bounding box into a world point using bare literals:

- `30.0` world units as the fallback distance when no viewport is known,
- `+/- 30.0` degrees as the horizontal field-of-view half-angle,
- `15.0 + dist_factor * 35.0` as the distance, where `dist_factor` is derived linearly from the
  bounding box's bottom edge relative to the viewport height.

Every one of these is an unexplained literal driving a business rule, which `CLAUDE.md` forbids, and
each one feeds `SpatialMap.record_spawn` and therefore every route the planner scores. The linear
bottom-edge relation is also the wrong shape: under perspective projection, apparent size falls off
with the inverse of distance, so a linear ramp cannot fit both near and far mobs.

Contrast `src/flyff_bot/features/vision/vitals.py:22`, which states the reference dimensions its
constants were calibrated against.

### The leash is decorative

`leash_radius_pixels` is validated in `PathingConfig.__post_init__` (`pathing.py:77`), carried in
`NavigationSnapshot` (`pathing.py:191`), and drawn as a circle by
`src/flyff_bot/ui/path_inspector.py:306-310`. Nothing clamps planning to it. `RoutePlanner.circuit`
and `best_spawn_route` (`features/navigation/planning.py:91-139`) consider every recorded hotspot
regardless of distance from the session anchor, so the drawn circle promises a constraint the
engine does not apply.

### How to measure instead of guess

[US-035](completed/US-035-measured-minimap-odometry-and-tracking-quality.md) supplies a measured travelled
distance. That turns the distance relation into an ordinary fitting problem with a recordable
ground truth: walk toward a stationary mob while logging, per frame, the detected bounding box
height and the odometry-measured distance travelled. Fitting `distance = a / bbox_height + b` (the
inverse relation implied by pinhole projection) over those samples yields constants with a
residual, not an opinion. The horizontal half-angle is obtained the same way: place a mob at a known
bearing offset and read back the pixel offset.

Two consequences for how the recording must be done:

- **The approach never reaches the mob.** It stops at melee range, so a single walk measures
  `a / h + b - r_melee`, not the distance itself. `a` and the combined intercept must therefore be
  fitted across **several mobs observed at different bounding box heights**, not read off one
  approach. A single sample cannot separate the intercept from the melee offset.
- **Distances are in minimap pixels**, the canonical unit US-035 establishes. This includes
  `leash_radius_pixels`, which is renamed accordingly: its numeric value changes meaning, so the
  default must be re-derived rather than carried over, and an existing operator setting must not be
  silently reinterpreted.

This story depends on US-035 for the odometry and should reuse the same capture sessions.

- **Assumption to verify:** the relation is per-mob-class, because mob models differ in height. The
  fit must be evaluated per class before deciding whether one shared relation is good enough.
- **Assumption to verify:** the relation depends on the camera pitch and zoom. To guarantee 100%
  reproducibility across game sessions without memory inspection, both calibration recordings and
  active bot farming must operate at the **zoom hard-stop** (mouse wheel scrolled all the way back
  to Flyff's physical maximum zoom limit) and a **controlled ~45° camera pitch** (navigated from a
  vertical hard-stop/reset to ensure consistent forward FOV). The recording must note the
  pitch used, and the fit's validity outside this standardized camera state is undefined.
- **Blocked on operator-supplied captures:** criteria 1 and 2 need approach sequences recorded on
  Windows with US-035's odometry in place. Section 3 (leash enforcement) depends on neither and can
  land independently. The instrument for those captures now exists:
  [US-041](completed/US-041-spawn-distance-calibration-capture-script.md) delivered
  `scripts/capture_spawn_distance_samples.py`, whose `walk-in`, `bearing`, and `fit` subcommands
  record and fit exactly the evidence criteria 1 and 2 ask for. What a walk-in observes is the
  *remaining travel* to the stopping point rather than the absolute distance, so the fit reports `a`
  and a combined intercept with the melee stopping distance folded into it — the second of the two
  options criterion 1 allows.

## Progress on 2026-08-18

Section 3 and section 4 are implemented, together with the two bullets of section 2 that do not
depend on the fit. Sections 1 and the fit-dependent bullets of section 2 remain open exactly as the
story predicted: they need approach sequences recorded on Windows and cannot be closed from the
frames already in the repository.

### What landed

- `LeashBound` (`src/flyff_bot/features/navigation/planning.py`) is the circular bound around the
  session anchor. The anchor is `WorldPoint(0, 0)`, because every navigation position is already
  relative to the session start (US-035), so there is no second anchor to configure.
- `RoutePlanner.plan`, `best_spawn_route`, and `circuit` take an optional leash and refuse to
  expand into, or target, a cell whose centre lies outside it. Cell centres are the containment
  test everywhere, so no waypoint of a leashed route can leave the bound.
- `RoutePlanner.return_route` handles the "already outside" case. It searches *without* the leash
  constraint and stops at the first cell inside the bound, because a character that was pushed or
  resumed outside can only walk back in through the cells it actually stands among.
- `PathingController.leash_radius_pixels` is the single leash value. `snapshot()` publishes it to
  the inspector and `_plan()` enforces it, so the drawn circle cannot describe a radius the planner
  does not apply, and a runtime change takes effect at the next replan without a session restart.
  It is operator configuration rather than learned state, so it deliberately survives a map reset
  or profile load.
- `RoutePlanner.hotspots_outside` counts the hotspots the leash excludes.
  `NavigationSnapshot.hotspots_outside_leash` carries the count and the path inspector renders it
  as an amber row of its own in the status HUD. It needed its own row: appended to the existing
  status line it was clipped away by the HUD width and therefore not observable at all.
- Sightings without a known viewport are dropped rather than parked at a fixed distance ahead,
  which removes the `30.0` fallback literal entirely.

### The default leash radius was re-derived

The previous `50.0` was carried over from before the unit rename and never derived from anything.
Now that the value constrains behaviour, `DEFAULT_LEASH_RADIUS_PIXELS` is
`MINIMAP_SURFACE_RADIUS_PIXELS` (62 px): the camp is defined as the terrain visible around the
anchor on the minimap, which is a measured quantity from
[the minimap odometry calibration](../sources/2026-08-18-minimap-odometry-calibration.md) and is
already in the same unit as every navigation position. No persisted operator setting for the leash
exists anywhere in the repository, so nothing is silently reinterpreted by the change.

### The remaining spawn-distance literals are named, not fitted

`PROVISIONAL_HORIZONTAL_HALF_ANGLE_DEGREES`, `PROVISIONAL_NEAREST_SIGHTING_DISTANCE_PIXELS`, and
`PROVISIONAL_SIGHTING_DISTANCE_SPAN_PIXELS` replace the bare literals in
`PathingController._estimate_mob_position` and are documented as estimates awaiting the fit. They
are named so the estimator carries no unexplained literals, not because naming makes them measured.
The linear bottom-edge relation is still the wrong shape and is still in place; criterion 1 is what
replaces it.

The per-mob-class fallback bullet of section 2 was deliberately *not* implemented as a structural
placeholder. With no fitted relation for any class, a class-keyed registry would route every
sighting to the fallback and empty the heatmap, trading a guessed hotspot for no hotspot at all on
no evidence. It lands with the fit.

## Acceptance criteria

### 1. Recorded calibration evidence

- [ ] Given a recorded approach sequence per mob class, when the samples are ingested, then the
  bounding box heights, the measured remaining distances, and the capture conditions (client
  resolution, camera pitch, mob class) are stored under `docs/sources/` and are immutable
  thereafter.
- [ ] Given the samples, when the relation is fitted, then the fitted coefficients, the residual,
  and the number of held-out samples are documented alongside them.
- [ ] Given the fit, when it is accepted, then it covers samples from several mobs at clearly
  different bounding box heights, and the melee stopping distance is either fitted as its own term
  or documented as folded into the intercept.

### 2. The estimator uses the fit

- [ ] Given a detected mob and a known viewport, when its world point is estimated, then the
  distance comes from the fitted relation and the bearing from the measured half-angle, and every
  constant involved is named and cites its source document.
- [ ] Given a held-out sample, when the estimator runs on it, then the estimated distance is within
  the documented tolerance of the measured one.
- [ ] Given a mob class that has no fitted relation, when its world point is estimated, then the
  sighting is recorded at a documented, explicitly labelled fallback rather than silently reusing
  another class's fit.
- [x] Given no viewport is known, when a sighting arrives, then the current behaviour of placing it
  at a fixed distance ahead is replaced by not recording it at all, since an unplaceable sighting
  contributes nothing but noise to the heatmap.

### 3. The leash constrains planning

- [x] Given a leash radius and a session anchor, when `RoutePlanner` scores candidate hotspots, then
  hotspots whose cell centre lies outside the leash radius are not selectable as route targets.
- [x] Given a route to a reachable hotspot, when the route is planned, then no waypoint on it lies
  outside the leash radius.
- [x] Given the character is already outside the leash radius (pushed, or resumed elsewhere), when
  the next route is planned, then the route leads back inside instead of being empty.
- [x] Given the leash radius is changed at runtime, when the next replan occurs, then the new radius
  applies without restarting the session.
- [x] Given the inspector draws the leash circle, then the drawn circle and the enforced radius come
  from the same value, so the drawing cannot drift from the behaviour.

### 4. Operator visibility

- [x] Given a hotspot is skipped because it lies outside the leash, when the dashboard renders, then
  that is observable rather than silent.
- [x] All new user-visible text is present and synchronised in `de.json` and `en.json`.

## Out of scope

- Estimating mob distance from the minimap dots: US-027 stays rejected.
- Per-mob-class combat behaviour or target prioritisation.
- Making the leash anchor operator-placeable on the map; the session anchor is used.
- Re-tuning `RouteConfig` weights or the stall cost policy.

## Verification

- Automated:
  - A fit regression test asserting the committed coefficients reproduce the recorded samples within
    the documented residual, and an accuracy test over held-out samples.
  - Unit tests for the no-viewport and unknown-class paths asserting no sighting is recorded.
  - Planner tests asserting no returned waypoint lies outside the leash radius, including the
    "character starts outside the leash" case.
  - A test asserting the inspector's drawn radius and the planner's enforced radius derive from one
    value.
  - `pwsh -File .\scripts\check.ps1`.
- Manual (Windows):
  - Record the approach sequences per mob class and confirm the resulting hotspots in the inspector
    sit on the mob positions visible on screen.
  - Set a small leash radius and confirm the character patrols inside it for a full session.
