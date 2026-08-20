---
id: US-059
title: Authoritative vector navigation, legacy subsystem removal, and multi-zone selection
status: completed
created: 2026-08-20
updated: 2026-08-20
---

# US-059: Authoritative vector navigation, legacy subsystem removal, and multi-zone selection

## Story

As a **bot operator**, I want **the navigation system to rely exclusively on authoritative extracted world data, 3D NavMesh routing, and live GPS without legacy fallbacks, while supporting multi-zone selection for vector farming**, so that **the codebase is streamlined, movement is deterministic, and character navigation across multiple spawn zones requires no manual intervention or heuristic minimap tracking**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Prior iterations implemented heuristic minimap odometry (`MinimapOdometer`), key-press dead reckoning (`MovementTracker`), 2D grid heatmap learning (`SpatialMap`, `RoutePlanner`), and minimap profile persistence (`spatial_map.json`) as temporary navigation fallbacks.
- [US-045](completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md), [US-048](completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md), [US-052](completed/US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md), [US-053](completed/US-053-pure-gps-navigation-and-client-profile-configuration.md), [US-055](completed/US-055-authoritative-3d-world-geometry-and-navmesh-foundation.md), [US-056](completed/US-056-client-camera-state-and-projection-matrix-reader.md), [US-057](completed/US-057-yolo-bottom-center-camera-unprojection-and-navmesh-mob-positioning.md), and [US-058](completed/US-058-navmesh-aware-targeting-and-telemetry-integration.md) established authoritative 3D world geometry, client archive extraction, read-only GPS (`LivePositionReader`), client camera matrix extraction (`LiveCameraReader`), bottom-center camera ray unprojection, and Funnel pathfinding over a baked 3D NavMesh (`BakedNavMesh`).
- Architectural rule: "No GPS, no bot". Navigation strictly requires authoritative live GPS and extracted world geometry. Operating without valid GPS or without loaded world data must immediately pause or block rather than falling back to uncalibrated or heuristic movement.
- Operators need the ability to select and activate multiple spawn zones (either within the same monster class or across different monster classes) in the vector navigation configuration so the bot can farm complex routes across multiple camps.
- Linked wiki pages and decisions:
  - [Architecture](../wiki/architecture.md)
  - [Roadmap](../wiki/roadmap.md)
  - [ADR-005: Client Folder Asset Access for Data Extraction](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md)
  - [ADR-006: Read-only Process Memory Access](../decisions/ADR-006-read-only-process-memory-access.md)
  - [Source: Entropia Client Navigation Data Extraction](../sources/2026-08-19-entropia-client-navigation-data-extraction.md)
  - [Source: Entropia Camera Static Analysis](../sources/2026-08-20-entropia-camera-static-analysis.md)

## Acceptance criteria

- [x] Given a running bot session, when live GPS (`LivePositionReader`) is unavailable, unverified, or returns a read error, then the bot immediately transitions to `FarmingMode.PAUSED` / `PathingMode.BLOCKED`, records a typed diagnostic event, and dispatches zero movement keys.
- [x] Given the navigation subsystem, legacy minimap template-matching odometry (`MinimapOdometer`, `MinimapReading`), key-press dead reckoning (`MovementTracker`), 2D grid heatmap tracking (`SpatialMap`, `GridCell`, `RoutePlanner`, pixel leash calculations), and legacy minimap profiles (`data/navigation/*.json`, `NavigationProfile`, anchor matching) are completely removed from production code and replaced by pure authoritative world-space routing.
- [x] Given the desktop UI, the *Navigation & World* tab and header cards remove obsolete minimap profile controls (*Save Profile*, *Load Profile*, *Reset Map*, anchor status chip) and focus exclusively on World Data extraction, region/zone selection, live GPS status, NavMesh candidate telemetry, and 3D path inspection.
- [x] Given the vector navigation system (`VectorZoneNavigator` / `WorldDataDialog`), when configuring vector farming goals, then the operator can activate multiple distinct spawn zones and configure per-zone / per-monster quotas, with the navigator automatically pathfinding across the 3D NavMesh to the next active zone upon quota completion or target exhaustion.
- [x] Given search when no mobs are visible in the active zone, when staged search executes, then the bot steers exclusively along the extracted NavMesh zone patrol ring and camera rotations without blind WASD roaming.
- [x] All user-visible text, error diagnostics, and dialog strings are synchronized in English and German (`en.json`, `de.json`).

## Post-completion corrections

A review of the implementing commit found three criteria that were marked done but not met, all
fixed and regression-tested afterwards:

- [BUG-019](../../bugs/fixed/BUG-019-live-camera-poll-suppressed-by-gps-sample-guard.md): the live
  camera was polled once per session, freezing the steering heading.
- [BUG-020](../../bugs/fixed/BUG-020-emergency-recovery-progress-threshold-in-minimap-pixels.md):
  emergency recovery compared world-unit GPS movement against the removed minimap pixel threshold.
- [BUG-021](../../bugs/fixed/BUG-021-multi-zone-selection-and-localized-debug-values-missing.md):
  the dialog armed a single zone only, the zone hand-over had no production caller, and the target
  and monster debug panels rendered unlocalized value strings.

The one-way GPS pause shipped by the same commit was corrected in `35e21bf`, which resumes farming
once GPS recovers and keeps a manual pause latched.

## Out of scope

- Memory writes or client code injection (strictly read-only memory per ADR-006).
- Server-side entity packet sniffing or runtime server state interception.
- Modifying YOLO object detection neural network architectures or training pipelines.

## Verification

- Automated:
  - Unit tests verifying strict GPS requirement and refusal to move when GPS is degraded/offline.
  - Unit tests for multi-zone selection, sequential zone switching, and NavMesh patrol ring routing in `VectorZoneNavigator`.
  - Regression test suite verifying complete removal of legacy minimap/spatial map code without broken references.
  - `./scripts/check.ps1` (ruff, mypy, pytest) passing cleanly.
- Manual (Windows):
  - Launching the desktop app, opening *Navigation & World*, verifying clean UI without legacy profile controls.
  - Loading an extracted world map with multiple active spawn zones and verifying automated transit between zones on `neuz.exe`.
