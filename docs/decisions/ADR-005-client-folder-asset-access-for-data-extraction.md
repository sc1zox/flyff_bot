# ADR-005: Unrestricted read-only access to local Entropia client files for offline data extraction

- Status: accepted
- Date: 2026-08-19
- Related stories: [US-045](../user-stories/completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md), [US-052](../user-stories/US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md)
- Evidence: [Entropia client navigation data extraction](../sources/2026-08-19-entropia-client-navigation-data-extraction.md)

## Context

Automating navigation, combat target awareness, obstacle avoidance, and world orientation requires authoritative static ground-truth data (terrain heightfields, NavMeshes, monster spawn zones, object obstacle footprints, UI sprite coordinates, and memory structures).

While runtime interaction with the running `neuz.exe` process is strictly constrained to documented Win32 input/capture APIs and fingerprinted coordinate-only `ReadProcessMemory`, the local Entropia client directory contains complete static assets on disk:
- Container archives and headers (`.one`, `.hdr`)
- World definitions and region polygons (`.wld`, `.wld.cnt`, `.rgn`, `.dyo`)
- Terrain heightfields and 3D models (`.lnd`, `.o3d`)
- Executables, scripts, project files, and textures (`neuz.exe`, `.inc`, `.prj`, `.tga`, `.dds`)

Clarification is required to establish that all local client assets are fully accessible for static extraction, indexing, reverse engineering, and baking, while preserving safety and repository integrity boundaries.

## Decision

1. **Full read-only disk access for extraction tooling:**
   All files, archives, executables, scripts, and assets located within the operator's local Entropia client folder are explicitly accessible for read-only static analysis, reverse engineering, indexing, parsing, and data extraction pipelines.

2. **Decoupling from runtime safety constraints:**
   Static disk-level data extraction runs offline or via background workers (e.g. NavMesh baking, archive unpacking) and does not relax runtime boundaries: no runtime code injection, no DLL hooking, no memory writing, and no runtime archive interception are permitted.

3. **Non-destructive read-only guarantee:**
   Extraction tools and scripts must treat the local game installation as read-only and immutable. No tool may modify, overwrite, delete, or repack files inside the client directory.

4. **Repository safety boundary (no raw asset commits):**
   Raw client executables, proprietary archives, copyrighted art/sound assets, and local client installations must never be committed into the git repository (per `AGENTS.md`). Only distilled, parsed, and synthesized project artifacts (such as parsed JSON world definitions, baked 3D NavMeshes under `data/navigation/worlds/`, YOLO dataset labels, and normalized test fixtures) are checked into version control.

5. **Fault tolerance and graceful degradation:**
   Archive parsers and extractors must handle unknown header layouts, unsupported container cipher variants, or corrupted blocks gracefully by logging diagnostic warnings and continuing extraction rather than failing fatally.

## Alternatives

- **Restrict extraction to loose client files only:**
  Rejected because 96% of declared terrain blocks (3,708 out of 3,861) and crucial asset indices reside inside `.one`/`.hdr` archives; restricting extraction to loose files leaves most game worlds unnavigable.
- **Extract 3D terrain and NavMesh live from client process memory:**
  Rejected because scanning and traversing complex dynamic heap structures at runtime violates the coordinate-only RPM safety boundary and introduces process instability.
- **Manual world surveying or hand-crafted waypoint maps:**
  Rejected because manual mapping across thousands of terrain blocks is unscalable, prone to human error, and cannot provide precise 3D slope and collision boundaries.

## Consequences

- Offline tools and UI extraction triggers can unpack, parse, and triangulate all client assets into structured navigation and perception artifacts.
- Operators can point the application to their local Entropia client directory to generate full world NavMeshes and spawn datasets on demand.
- The project retains strict compliance with repository hygiene, copyright safety, and runtime anti-cheat/safety principles.

## Verification

- Automated tests in `tests/unit/test_archive_extractor.py`, `tests/unit/test_world_vector_map.py`, and related suites verify that extractors parse synthetic headers/archives and decode `.lnd`/`.rgn`/`.dyo` data into valid structures without modifying source fixtures.
- Extraction tools verify that outputs are written exclusively to `data/navigation/worlds/` or configured artifact directories, leaving client folders untouched.
