---
id: US-036
title: Navigation profile anchoring so saved maps mean the same place in a later session
status: completed
created: 2026-08-18
updated: 2026-08-18
---

# US-036: Navigation profile anchoring so saved maps mean the same place in a later session

## Story

As a **bot operator who saved a map profile for a camp yesterday**, I want **a loaded profile to be
re-anchored to where the character actually stands, or refused if it cannot be**, so that **learned
routes and spawn hotspots lead to the places they were recorded at instead of to an arbitrary offset
from wherever the session happened to start**.

## Context and assumptions

- `SpatialMap` coordinates are relative to the session origin. `PathingController.load_map`
  (`src/flyff_bot/features/navigation/pathing.py:247`) calls `_reset_state()`, which resets the
  tracker to `(0, 0)` and heading 0 (`pathing.py:270`, `tracking.py:110`).
- Therefore a loaded profile is silently reinterpreted relative to the position and facing the
  character happens to have at load time. Its cells, edges, hotspots, and stall markers all shift
  and rotate with it.
- [US-021](US-021-navigation-map-profiles-and-session-reset.md) introduced named profile
  slots explicitly to "avoid cross-zone map contamination", but it specifies no anchoring: none of
  its acceptance criteria constrain what a loaded profile's coordinates mean.
  [BUG-004](../../bugs/fixed/BUG-004-navigation-map-visualization-and-persistence-clarity.md) covers
  persistence timing and visualisation, not frame alignment either. This is an open hole, not a
  documented operating requirement.
- The persisted schema is `SPATIAL_MAP_SCHEMA_VERSION = 1` (`features/navigation/spatial.py:14`) and
  stores only cells and edges — no anchor, no scale, no zoom level.
- After [US-035](US-035-measured-minimap-odometry-and-tracking-quality.md), heading is measured from
  a north-up minimap, so the frame's *rotation* is already absolute and only a *translational*
  anchor is missing. This story depends on US-035.
- Anchoring approach: the minimap disk is a picture of static terrain around the player. Storing the
  disk together with the world coordinates it was captured at gives a landmark that a later session
  can match against with the same phase-correlation machinery US-035 introduces, recovering the
  offset between the two sessions' frames. The
  [minimap odometry spike](../../sources/2026-08-18-minimap-odometry-feasibility-spike.md) measured
  0.6-0.9 px matching accuracy and a clean confidence separation (0.665-0.928 for genuine overlap
  versus -0.052 for unrelated content), which is what makes the match verifiable rather than
  hopeful.
- **Assumption to verify:** matching only works while the character stands close enough to the saved
  anchor for the two minimap disks to overlap. The usable radius is unknown and must be measured;
  the operator-facing rule is expected to be "resume near where you stopped".
  *Implementation status:* a match is bounded to one minimap surface radius (62 px), beyond which two
  disks share no content at all. Where inside that bound matching stops succeeding in the field is
  still unmeasured, so the manual walkthrough below stays open.
- **Assumption to verify:** minimap zoom changes the pixel scale, so a profile recorded at one zoom
  level cannot be matched against another and its stored coordinates mean something different. The
  stored zoom level is what makes this detectable; the recordings listed in US-035 criterion 9
  measure the actual ratio between levels.

## Acceptance criteria

### 1. Profiles carry an anchor

- [x] Given a session with a confident tracking quality, when a profile is saved, then the snapshot
  is written at schema version 2 containing an anchor record: the grayscale minimap disk at save
  time, the map coordinates in minimap pixels it was captured at, the measured heading, and the
  zoom level the profile was recorded at. Per the unit definition in US-035 there is no world-unit
  scale to store; the zoom level *is* the scale, which is why it is mandatory rather than optional.
- [x] Given tracking quality is `DEGRADED` at save time, when the operator saves, then the profile is
  written without an anchor and the UI states that the profile will load unanchored.
- [x] Given a profile on disk with an unsupported schema version (such as legacy version 1), when it is
  loaded, then loading is explicitly rejected with a clear error naming the unsupported schema version
  ([ADR-003](../../decisions/ADR-003-clean-schema-over-backward-compatibility.md)).

### 2. Loading re-anchors or refuses

- [x] Given an anchored profile and a live minimap that overlaps the stored anchor above the
  confidence threshold, when the profile is loaded, then the tracker position is set so that the
  loaded map's coordinates align with the current position, and the inspector redraws the map around
  the character in its correct place.
- [x] Given an anchored profile whose stored scale metadata does not match the live scale, when the
  profile is loaded, then loading is refused with a localized message naming the mismatch, and the
  previously active map stays intact.
- [x] Given an anchored profile that cannot be matched above the confidence threshold, when the
  profile is loaded, then the operator is offered exactly two defined outcomes: load read-only
  (routes may be followed, nothing is written to the map) or cancel. The default is cancel.
- [x] Given an unanchored profile (saved while degraded), when it is loaded, then it loads
  read-only and the UI states why, so a stale frame can never silently accumulate new cells.
- [x] Given a corrupted or truncated anchor record, when the profile is loaded, then it is treated
  as unanchored and no exception escapes to the UI, matching the existing corrupt-profile behaviour
  from US-021.

### 3. Operator visibility

- [x] Given a profile is active, when the dashboard renders, then the anchor state (anchored /
  read-only / unanchored) is visible alongside the profile name.
- [x] All new user-visible text is present and synchronised in `de.json` and `en.json`.

## Out of scope

- Matching a profile from anywhere in the zone: only anchors that overlap the live minimap are in
  scope. No mosaic, no loop closure, no global relocalisation.
- Merging two profiles recorded in the same camp into one map.
- Automatic zone detection or automatic profile selection.
- Backward compatibility or mathematical migration for legacy schema v1 profiles (rejected per ADR-003).
- Changing the profile management UI layout introduced by US-021.

## Verification

- Automated:
  - Round-trip tests for schema version 2 including anchor serialisation, and a test asserting that
    unsupported schema versions (like legacy v1) are rejected with a ValueError.
  - Matching tests using the shipped frames: a shifted crop of one frame's disk must re-anchor to
    the expected offset; the cross-zone disk from the spike must fall below the threshold and
    trigger the refusal path.
  - Tests that a read-only profile receives no `record_visit`, `record_spawn`, or `record_stall`
    calls.
  - `pwsh -File .\scripts\check.ps1`.
- Manual (Windows) — **open, requires the running client**:
  - Record a map in a camp, save it, close the application, restart it at roughly the same spot,
    load the profile, and confirm the hotspots sit where the mobs are.
  - Repeat after walking a few screens away and confirm the refusal path is taken instead of a
    silently shifted map.
  - Repeat with a changed minimap zoom level and confirm the scale mismatch is reported.
  - Measure and record the distance at which matching stops succeeding, and add the finding to
    `docs/sources/`.
