---
id: US-037
title: Measured spawn distance model and an enforced patrol leash
status: draft
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
- **Assumption to verify:** the relation depends on the camera pitch, which the operator can change.
  The recording must note the pitch used, and the fit's validity outside it is unknown.
- **Blocked on operator-supplied captures:** criteria 1 and 2 need approach sequences recorded on
  Windows with US-035's odometry in place. Section 3 (leash enforcement) depends on neither and can
  land independently.

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
- [ ] Given no viewport is known, when a sighting arrives, then the current behaviour of placing it
  at a fixed distance ahead is replaced by not recording it at all, since an unplaceable sighting
  contributes nothing but noise to the heatmap.

### 3. The leash constrains planning

- [ ] Given a leash radius and a session anchor, when `RoutePlanner` scores candidate hotspots, then
  hotspots whose cell centre lies outside the leash radius are not selectable as route targets.
- [ ] Given a route to a reachable hotspot, when the route is planned, then no waypoint on it lies
  outside the leash radius.
- [ ] Given the character is already outside the leash radius (pushed, or resumed elsewhere), when
  the next route is planned, then the route leads back inside instead of being empty.
- [ ] Given the leash radius is changed at runtime, when the next replan occurs, then the new radius
  applies without restarting the session.
- [ ] Given the inspector draws the leash circle, then the drawn circle and the enforced radius come
  from the same value, so the drawing cannot drift from the behaviour.

### 4. Operator visibility

- [ ] Given a hotspot is skipped because it lies outside the leash, when the dashboard renders, then
  that is observable rather than silent.
- [ ] All new user-visible text is present and synchronised in `de.json` and `en.json`.

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
