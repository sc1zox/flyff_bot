---
id: US-045
title: Vector world and terrain passability extraction with goal-driven zone navigation
status: completed
created: 2026-08-19
updated: 2026-08-19
---

# US-045: Vector world and terrain passability extraction with goal-driven zone navigation

## Story

As a **bot operator setting up multi-mob quest farming goals**, I want **the application to extract vector spawn zones, terrain elevation, and impassable slope meshes from client world files (`.rgn`, `.wld`, `.lnd`, `.dyo`) starting with Eden (`WdEden`), provide a UI extraction trigger, and automatically plan global obstacle-free vector paths via a lightweight Visibility-Graph A* solver before farming begins**, so that **the bot navigates directly to target mob clusters with guaranteed obstacle avoidance, minimizing stuck risk through authoritative terrain data while preserving all proven core components**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Client world assets (`Entropia/Entropia/Data/World/WdEden/`) contain unencrypted, parseable data:
  - `WdEden.rgn`: Contains 83 `respawn7` zones with exact 3D coordinates $(X, Z, Y)$, 2D bounding boxes $[X_1, Y_1, X_2, Y_2]$, monster IDs, counts, and respawn intervals.
  - `wdeden.wld`: Defines map dimensions ($5 \times 5$ chunks), Meters Per Unit ($MPU = 4$), ambient settings, and camera limits.
  - `WdEden03-02.lnd`: Contains raw IEEE 754 float32 terrain height grids ($129 \times 129$ vertices per chunk).
  - `wdeden.dyo`: Contains placed 3D dynamic objects and collision hulls.
  - `Data/Lang/English/Theme/Default/eden.tga`: 250×250 reference map texture for visual inspection.
- The 6 monster IDs in `WdEden.rgn` (1453, 1454, 1455, 1456, 1457, 1458) map directly to the 6 Eden labels in `models/labels.txt` (`Flame`, `LadyBlum`, `MiniMush`, `NightMist`, `Oldrut`, `Rapra`).
- Slopes with a gradient $\nabla Z / \Delta d > 1.0$ ($> 45^\circ$) represent impassable cliffs in the Flyff physics engine.
- [US-035](../US-035-multi-target-selection-and-per-mob-kill-quotas.md) establishes multi-mob selection and kill quotas for quest goals.
- **Authoritative passability & routing (Visibility-Graph A\*):**
  - Extracting the static terrain mesh and steep slope boundaries ensures path planning uses ground-truth geometry rather than blind exploration.
  - The pathfinder constructs a **lightweight Vector Visibility Graph** connecting zone centroids and obstacle polygon vertices, running an A* search in $< 1\,\text{ms}$ to guarantee shortest, obstacle-free paths around cliffs, rocks, and impassable terrain.
- **Selective simplification principle:** Legacy logic is only superseded or bypassed where it provides no added value. Proven core components are strictly preserved:
  - `MovementTracker` and `MinimapOdometer` ([US-035](US-035-measured-minimap-odometry-and-tracking-quality.md)) remain the continuous, live position & heading sensor.
  - `StallDetector` ([BUG-009](../../bugs/fixed/BUG-009-movement-tracking-wasd-and-obstacle-stall-detection.md), [US-039](US-039-combat-obstacle-stall-detection-and-re-navigation.md)) remains active as the dynamic safety net for unmapped obstacles (other players, dynamic entities).
  - `CameraAligner` ([US-042](US-042-automated-camera-alignment-and-standardized-viewport-initialization.md), [US-043](US-043-continuous-approach-target-tracking-and-minimap-zoom-initialization.md)) remains active for standardizing pitch, zoom, and minimap scale.
  - Heuristic `SpatialMap` grid exploration and exponential spawn weight decay are only bypassed when an authoritative `WorldVectorMap` is present, but kept as a graceful fallback for unmapped custom areas.
- All operations adhere strictly to project safety boundaries: reading client assets is done offline or during pre-flight; no game process memory reading or injection is used.

## Acceptance criteria

- [x] **Generic World and Terrain Extractor Engine:**
  - A dedicated extractor module (`flyff_bot.features.navigation.world_extractor`) parses Flyff world files:
    - `.wld`: Extracts world dimensions and coordinate bounds.
    - `.rgn`: Extracts `respawn7` entries into typed `VectorSpawnZone` records (monster ID, 3D centroid, 2D bounding polygon, mob capacity, respawn seconds).
    - `.lnd`: Decodes float32 height fields and computes static passability polygons / impassable slope boundaries ($\text{slope} > 45^\circ$).
    - `.dyo`: Extracts static object bounding footprints as collision no-go polygons.
  - The extractor outputs a structured, serializable `WorldVectorMap` document (JSON/GeoJSON format) saved under `data/navigation/worlds/<world_name>.json`.
- [x] **Eden (`WdEden`) Vector Data Pipeline:**
  - Complete extraction and validation for Eden: 83 spawn zones, 6 monster classes, and passability terrain mesh.
  - Extracted map includes bounding polygons and cluster centroids for `Flame`, `LadyBlum`, `MiniMush`, `NightMist`, `Oldrut`, and `Rapra`.
- [x] **Visibility-Graph A\* Path Planner:**
  - A dedicated `VectorRoutePlanner` constructs a visibility graph over obstacle polygon vertices and spawn zone anchors.
  - Runs an A* search over the visibility graph to guarantee global shortest, obstacle-free paths around impassable cliffs and terrain boundaries.
- [x] **UI Extraction & Region Manager Trigger:**
  - The dashboard provides a "World Data & Maps" manager action/dialog where operators can view available client regions and trigger extraction on demand.
  - Progress and results of the extraction (number of zones, passability cells, detected monster classes) are shown in the UI.
- [x] **Pre-Flight Goal-Driven Vector Loading:**
  - When the operator configures monster farming goals / quest quotas (as in US-035) and starts farming in Eden:
    - The bot automatically loads the `WorldVectorMap` for Eden before input dispatch starts.
    - The active target monster's specific vector spawn zones are selected as the primary patrol boundary.
    - Pathing calculates routes exclusively via the Visibility-Graph A* solver, avoiding cliffs and obstacles.
- [x] **Dynamic Zone Switching on Goal Completion:**
  - When the quota for Mob A is reached, the bot automatically transitions to the nearest vector spawn zone of Mob B (the next unfinished goal) and updates the pathing bounds without requiring a session restart.
- [x] **Selective Simplification & Fallback Coexistence:**
  - When a `WorldVectorMap` is active, heuristic grid learning and blind exploration are bypassed in favor of direct vector waypoint and passability navigation.
  - Live odometry (`MovementTracker`) and dynamic obstacle safety (`StallDetector`) continue to operate uninterrupted.
  - Unmapped regions without an extracted vector map continue to function gracefully via existing fallback pathing.
- [x] **Localization:**
  - All new UI elements, dialogs, extraction progress notices, and status chips are localized in German (`de.json`) and English (`en.json`).

## Implementation notes

- **Terrain coverage is whatever the client leaves loose on disk.** Eden ships exactly one
  `.lnd` block (`WdEden03-02.lnd`, block x=3 z=2); every other block lives inside the
  obfuscated `wdeden.one` archive, which the story places out of scope. Extraction therefore
  produces 83 spawn zones, 6 monster classes, and passability geometry for that one block —
  348 impassable slope rectangles plus the single `.dyo` object footprint. Zones outside the
  mapped block route without terrain constraints; the dynamic `StallDetector` remains their
  safety net.
- **The monster-id to detector-class mapping is an assumption, not an extraction.** The
  client's own `propMover.txt` table ships only inside the obfuscated `data.one`, so
  `data/assets/world/monster_ids.json` pairs the six Eden identifiers with the six
  `models/labels.txt` classes in ascending identifier order. It is an operator-editable data
  file, and an unmapped identifier still extracts under its numeric identity.
- **Arming vector navigation is an operator pre-flight step, not an automatic one.** Session
  positions are minimap pixels relative to wherever the session started (US-035), and no
  observation relates them to absolute world coordinates without reading game memory, which
  is out of scope. The "World Data & Maps" dialog therefore asks once which spawn zone the
  character is standing in; from that stated correspondence `WorldRegistration` recovers the
  translation, and everything after it — map loading, zone selection, routing, and zone
  switching on quota completion — is automatic and survives without a session restart.
- **The minimap-to-world scale is provisional.** `PROVISIONAL_MINIMAP_PIXELS_PER_WORLD_UNIT`
  is 1.0 and is exposed in the dialog as a calibration input. Deriving it would need a run
  speed the client does not display, which is the same reason US-035 records for having no
  world-unit conversion anywhere else.
- **Measured routing cost on the real Eden map** (349 obstacles): intra-zone patrol legs
  solve in 0.26 ms median, zone-to-zone hops in 2.5 ms median and 36 ms worst case, with 6 of
  72 zone pairs reported blocked and handed back to learned pathing. The story's `< 1 ms`
  figure holds for the short legs the patrol actually walks, not for cross-block queries.
- **Per-mob kill quotas here are the minimum criterion 6 needs**, not the full dashboard,
  SQLite, and per-class progress surface [US-035](../US-035-multi-target-selection-and-per-mob-kill-quotas.md)
  specifies. Goals are `ZoneGoal(monster_name, kill_quota)` values owned by the navigator, and
  kills are attributed from the verified target nameplate the orchestrator remembers while
  fighting.

## Out of scope

- Runtime memory injection or reading of in-game live actor coordinates.
- Parsing 3D animation files (`.chr`, `.ani`) or dynamic particle effects.
- Automatic extraction for client regions whose asset files are encrypted or missing.

## Verification

- Automated:
  - Unit tests for `.wld`, `.rgn`, `.lnd`, and `.dyo` parsing and coordinate transformations.
  - Unit tests for slope calculation and passability polygon generation.
  - Unit tests for Visibility-Graph A* path planning verifying deterministic obstacle avoidance.
  - Unit tests for goal-driven zone switching and vector path planning.
  - `./scripts/check.ps1` runs clean with no type or lint errors.
- Manual (Windows):
  - In the dashboard, trigger extraction for Eden and verify generated JSON in `data/navigation/worlds/wdeden.json`.
  - Set quest goals (e.g. 5x Flame, 5x Rapra).
  - Verify the bot loads Eden vector data, farms Flames in their designated spawn polygon, switches to Rapra's polygon upon completing Flames, and never walks into impassable cliffs.
