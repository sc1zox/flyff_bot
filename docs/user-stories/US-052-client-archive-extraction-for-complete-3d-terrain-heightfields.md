---
id: US-052
title: Client archive extraction, 3D NavMesh generation, settings UI trigger, and full spatial navigation
status: draft
created: 2026-08-19
updated: 2026-08-19
---

# US-052: Client archive extraction, 3D NavMesh generation, settings UI trigger, and full spatial navigation

## Story

As a **bot operator navigating complex 3D terrain across Entropia Flyff**, I want **to trigger a full client terrain extraction and 3D NavMesh generation directly from the settings UI that unpacks all `.one` / `.hdr` archives, triangulates all `.lnd` heightfields and `.dyo` obstacle footprints into a baked 3D NavMesh, and saves it in the application files**, so that **the bot navigates through the complete 3D world with sub-millisecond pathfinding, zero grid zigzagging, automatic character capsule corner clearance, and full awareness of slopes and obstacles**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Client world assets in `Entropia/Entropia/Data/World/` contain 123 `.one` and 123 `.hdr` container archives covering 3,861 declared terrain blocks across all worlds (Eden, Madrigal, dungeons, etc.), with only 153 blocks currently loose (3.96%).
- The `.hdr` files index entries with structured 76-byte and 80-byte header records. The `.one` archives contain compressed/encrypted data using the Flyff/Entropia container cipher (`m1k3d3RS945TI!`) and zlib compression.
- Each extracted `.lnd` heightfield contains a 66,576-byte prefix ($129 \times 129$ float32 heights) which converts directly into $128 \times 128 \times 2 = 32,768$ 3D triangles per block.
- 3D NavMesh generation integrates:
  - Agent capsule radius (e.g. 0.5 world units) to prevent character shoulder friction on corners.
  - Step height clearance (e.g. 0.4 world units) to traverse micro-bumps while blocking steep cliffs.
  - Maximum walkable slope limit ($45^\circ$ / gradient 1.0).
  - Placed `.dyo` obstacle bounding geometries.
- Smooth string-pulling (Funnel algorithm) converts polygon corridor crossings into direct, natural 3D trajectories.
- Extraction and baking are non-destructive and read-only against the game installation: compiled vector and NavMesh maps are stored in `data/navigation/worlds/<region>.json`.
- Builds upon [US-020](completed/US-020-visual-navigation-path-and-heatmap-inspector.md), [US-045](completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md), [US-048](completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md), and [ADR-004](../decisions/ADR-004-coordinate-only-read-process-memory.md).

## Acceptance criteria

- [ ] **Archive Extractor Pipeline:**
  - An `archive_extractor` module reads and parses all `.hdr` index formats (both 76-byte and 80-byte record structures) and unpacks `.one` archive payloads.
  - The extractor unpacks all archived `.lnd` terrain blocks, `.wld` scripts, `.rgn` monster zones, and `.dyo` object placements.
  - Invalid, encrypted, or unsupported archive members are logged as diagnostic warnings and safely skipped without aborting the extraction process.
- [ ] **3D Mesh Triangulation & NavMesh Baking:**
  - Decoded $129 \times 129$ height arrays and `.dyo` obstacle footprints are converted into 3D polygon meshes.
  - A NavMesh builder compiles walkable polygon graphs incorporating agent capsule radius, step height clearance, and maximum slope thresholds.
  - Compiled maps and NavMeshes are serialized into `data/navigation/worlds/<region>.json` for instant startup without re-baking.
- [ ] **Sub-Millisecond 3D Pathfinding & String-Pulling:**
  - The 3D NavMesh route planner calculates optimal polygon corridor routes in sub-millisecond time.
  - A funnel / string-pulling pass converts polygon crossings into smooth, natural 3D waypoint paths with full corner clearance.
- [ ] **Settings UI Trigger & Progress Feedback:**
  - The PySide6 Settings dialog and World Data window provide a dedicated trigger button to start extraction and NavMesh generation for a selected world or all discovered client worlds in batch.
  - Extraction and baking run on a background worker thread (`WorldExtractionWorker`) so the UI remains responsive.
  - The UI displays real-time progress (processed block count, current world name, and completion percentage).
- [ ] **Visual Navigation & Path Inspector:**
  - The Path Inspector / Navigation Map renders continuous 3D topographic contours, NavMesh polygon boundaries, and smooth waypoint trajectories for the active world.
- [ ] **Localization (DE/EN):**
  - All UI buttons, settings labels, extraction progress indicators, and log messages are fully synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).

## Out of scope

- Modifying, repacking, or writing data back into the game client's original `.one` / `.hdr` archives.
- Runtime in-memory archive hooking or DLL injection into the running `neuz.exe` process.
- Free-flight 3D aerobatics on flying mounts.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_archive_extractor.py` verifying header parsing (76-byte and 80-byte layouts) and payload extraction.
  - Unit tests in `tests/unit/test_navmesh.py` verifying 3D mesh triangulation, polygon baking, and funnel path smoothing.
  - Regression tests in `tests/unit/test_terrain_routing.py` verifying that 3D path planning produces smooth corner-cleared routes.
- Manual (Windows):
  - Open the PySide6 application, navigate to Settings / World Data, and click the extraction button.
  - Observe the progress bar completing all blocks and baking the 3D NavMesh.
  - Open the Navigation Map Inspector, verify that continuous 3D topographic contours and NavMesh polygons are rendered, and test route planning across challenging terrain.
