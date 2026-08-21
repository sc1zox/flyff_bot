---
id: US-069
title: Experience-based NavMesh routing and empirical traversal cost integration
status: draft
created: 2026-08-21
updated: 2026-08-21
---

# US-069: Experience-based NavMesh routing and empirical traversal cost integration

## Story

As a **Flyff bot developer and navigation engineer**,
I want **to integrate empirical traversal times, real-world stuck frequencies, and recovery costs from GPS telemetry into NavMesh A* edge weights**,
so that **the bot selects practically faster and obstacle-free routes over geometrically shorter but high-risk paths without altering NavMesh reachability**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/decisions/ADR-005-client-folder-asset-access-for-data-extraction.md`](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md): Local client assets and 3D NavMesh.
  - [`docs/decisions/ADR-006-read-only-process-memory-access.md`](../decisions/ADR-006-read-only-process-memory-access.md): Live GPS memory reads.
  - [`docs/user-stories/US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md`](US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md): 3D NavMesh compilation.
  - [`docs/user-stories/completed/US-054-farming-telemetry-and-adaptive-navigation-dataset.md`](completed/US-054-farming-telemetry-and-adaptive-navigation-dataset.md): GPS trajectories and stall events.
  - [`docs/user-stories/US-066-farming-and-navigation-value-model.md`](US-066-farming-and-navigation-value-model.md): Empirical travel time and stuck models.
- **Problem Statement:**
  Standard A* routing computes shortest geometric distance ($\min \int ds$). However, in practice, certain terrain polygons (narrow rock passes, steep inclines, tree roots) cause frequent collision stalls.
  An 8-meter corridor with an 8% stuck probability and 4-second recovery duration is practically slower and noisier than a smooth 10-meter open corridor.
- **Cost Formulation:**
  $$\text{TraversalCost}(e) = \hat{T}_{\text{travel}}(e) + P_{\text{stuck}}(e) \cdot \mathbb{E}[T_{\text{recovery}}(e)]$$
- **Reachability Invariance:**
  Empirical costs modify edge weights in A* pathfinding but **never remove or alter topological connectivity**. If no empirical data exists for a region, A* defaults to standard geometric length.

## Functional Requirements & Technical Architecture

### FR-1 – Telemetry Trajectory to NavMesh Mapping
- GPS trajectory segments from `navigation_trajectories.parquet` and stall logs MUST be mapped onto US-052 NavMesh polygons and corridor edges.
- Empirical statistics per edge $e = (u, v)$ include:
  - Traversal count $N(e)$
  - Mean observed travel time $\bar{T}(e)$
  - Observed stall count $S(e)$ and stuck probability $P_{\text{stuck}}(e) = S(e) / N(e)$
  - Mean recovery duration $\bar{T}_{\text{recovery}}(e)$.

### FR-2 – Empirical Edge Cost Storage
- Empirical edge statistics MUST be serialized in a compact lookup index alongside the NavMesh map cache (e.g., `data/navmesh/<map_id>_empirical.bin` or SQLite store).
- Versioning and map hash matching prevent applying empirical costs to modified NavMesh geometries.

### FR-3 – Experience-Weighted A* Router
- The A* router evaluates edge cost using a blend of geometric distance and empirical cost:
  $$\text{Cost}(e) = (1 - \alpha) \cdot \frac{\text{dist}(e)}{v_{\text{nominal}}} + \alpha \cdot \left( \hat{T}_{\text{travel}}(e) + P_{\text{stuck}}(e) \cdot \hat{T}_{\text{recovery}}(e) \right)$$
  where $\alpha \in [0.0, 1.0]$ is a configurable empirical weighting factor.

### FR-4 – Cold-Start & Sparse Region Fallback
- For unvisited or low-sample edges ($N(e) < N_{\text{min}}$), the router smoothly falls back to nominal geometric traversal time.

### FR-5 – Reachability & Safety Guarantees
- Empirical cost weighting MUST NOT declare valid paths as unreachable.
- Line-of-sight checks and Funnel string-pulling operate strictly within geometrically valid convex polygons.

## Acceptance criteria

- [ ] **Telemetry Correlation:** GPS trajectory logs and stall events are aggregated into per-polygon and per-edge empirical traversal statistics.
- [ ] **Cost Formulation:** Edge cost incorporates travel time, stuck probability, and recovery duration alongside geometric length.
- [ ] **Router Weighting:** A* path planner supports configurable empirical weight $\alpha \in [0.0, 1.0]$ with default $\alpha = 0.5$.
- [ ] **Cold-Start Fallback:** Unobserved or sparse NavMesh edges fall back to standard geometric distances without errors.
- [ ] **Reachability Preservation:** Valid NavMesh corridors remain reachable regardless of empirical penalty values.
- [ ] **Path Preference:** Validated test cases demonstrate preference for slightly longer, obstacle-free paths over short, stall-prone corridors.
- [ ] **Performance:** Empirical cost lookup adds $< 0.5\text{ ms}$ overhead to A* route calculation.
- [ ] **Localization & Diagnostics:** Path cost metrics and diagnostic logs are synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).
- [ ] **Quality Gate:** Automated tests pass `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).

## Out of scope

- Dynamic real-time NavMesh polygon subdivision.
- Online weight updates on every single step during active combat.
- Flying/Mount navigation meshes.
- Direct memory manipulation (`WriteProcessMemory`).

## Verification

- Automated:
  - Unit tests in `tests/unit/test_empirical_navmesh.py` validating telemetry ingestion, edge aggregation, and cost index serialization.
  - Unit tests in `tests/unit/test_experience_routing.py` verifying that A* chooses an open detour over a simulated high-stuck short corridor.
  - Benchmark test verifying A* path generation remains $< 2\text{ ms}$ with empirical weights loaded.
  - `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows):
  - In a known tricky terrain area (e.g. rocky paths near Flaris bridge / Darkon mountains), verify the bot navigates around troublesome obstacles instead of repeatedly bumping into corners.
