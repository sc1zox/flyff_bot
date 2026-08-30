---
id: US-092
title: Teleporter Configuration, Canonical Target Selection, Closed-Loop Camera Positioning, and Legacy Architecture Pruning
status: in-progress
created: 2026-08-29
updated: 2026-08-30
---

# US-092: Teleporter Configuration, Canonical Target Selection, Closed-Loop Camera Positioning, and Legacy Architecture Pruning

## Story

As an **operator running automated farming sessions**, I want **the teleporter hotkey to be configurable and its dialog interaction anchored to the client window, the target selection pipeline harmonized to a single canonical economic heuristic, the camera pitch/zoom positioned closed-loop for optimal perception based on live memory state, and all obsolete OCR, pixel-scanning, and dead bootstrap artifacts pruned from the codebase**, so that **automation is deterministic, high-performance, free of brittle screen-fraction heuristics, and cleanly aligned with authoritative memory and NavMesh data**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Teleporter invocation was previously hardcoded to the `V` key and dispatched blind clicks using rigid screen fractions (`SEARCH_FIELD_X_FRACTION = 0.50`, `FIRST_RESULT_X_FRACTION = 0.50`, `TELEPORT_BUTTON_X_FRACTION = 0.50`), failing if the client window layout, theme, or relative position shifted ([teleporter-dispatch](docs/wiki/architecture.md)).
- Target candidate selection suffered from architectural divergence:
  - `CombatController._best_candidate()` implemented economic ranking with mover catalog metadata and kill quotas ([US-083](completed/US-083-catalog-joined-telemetry-and-unified-data-manifest.md)).
  - `HeuristicPolicy.evaluate()` retained an outdated purely geometric sort (NavMesh distance or screen center).
  - In `ML_SHADOW` mode, policy insights compared against the outdated geometric heuristic while the live loop executed the economic candidate ranking, producing phantom baseline comparisons.
  - In `HEURISTIC` mode, the policy runner was bypassed entirely and fell back to `CombatController`'s internal candidate loop.
- Live process memory reading via `ReadProcessMemory` is authoritative and operational:
  - `LiveCameraReader` ([US-056](US-056-client-camera-state-and-projection-matrix-reader.md)) provides live 4x4 View and Projection matrices, camera world position, yaw, and pitch.
  - `LivePlayerStatsReader` ([US-076](US-076-complete-client-player-stats-reader.md)) provides proven client-memory fields such as monster kills, level, and experience; this client profile does not prove HP/MP/FP percentages or current-vitals fields.
  - `LivePositionReader` ([US-053](US-053-pure-gps-navigation-and-client-profile-configuration.md)) provides live 3D `WorldPosition`.
- Visual heuristics and OCR subsystems left from early iterations are being retired only where authoritative replacements are proven:
  - `PlayerVitalsReader` (pixel scanning top-left HUD orb) remains required for this client build. ADR-010 and completed US-094 found no fingerprint-stable bounded memory path for HP/MP/FP percentages.
  - Monster kill counts can be decoded directly from the client player/session memory structure via `LivePlayerStatsReader`, replacing the brittle `MonsterStatsReader` Tesseract OCR subprocess and HUD window alignment.
  - Nameplate OCR and the target-HP path in `TargetVerifier` remain evidence-gated because no selected-target memory profile has been proven; the verifier must not claim direct-memory verification without one.
  - `StallDetector._observe_frame` (downsampled screenshot pixel diffing) is redundant with `_observe_live` (`WorldPosition` delta over time).
  - Dead bootstrap artifacts (`Planner` in `planner.py`, `VerifiedExecutor` in `executor.py`, `NavigationController` in `controllers.py`, dead `FarmingGoal` item inventory checks) clutter the codebase.
- Relevant decisions and ADRs: [ADR-002](docs/decisions/ADR-002-target-architecture-and-pyside6.md), [ADR-006](docs/decisions/ADR-006-read-only-process-memory-access.md), [ADR-008](docs/decisions/ADR-008-closed-learning-loop-invariants.md), [ADR-009](docs/decisions/ADR-009-bounded-tactical-parameter-space.md).

## Acceptance criteria

- [x] **Configurable Teleporter Hotkey:** Given the desktop dashboard and settings configuration, when an operator binds a custom teleporter hotkey (default `V`), then the key is saved, loaded across sessions, and dispatched by `TeleporterDispatcher` while respecting foreground focus and emergency stop guards.
- [x] **Anchored Teleporter Window Interaction:** Given the teleporter dialog is opened, when clicking the search field, selecting the first result, and confirming teleportation, then click coordinates are computed relative to the detected dialog anchor/geometry rather than static screen fractions. The client-asset template anchor fails closed when geometry is not proven.
- [x] **Single Source of Truth Target Selection:** Given `HeuristicPolicy` in `flyff_bot.features.policy.heuristic`, when evaluating candidate targets, then it uses the canonical `rank_candidates()` economic model (including mover properties, HP, quotas, and NavMesh distance fallback) as the single source of truth.
- [x] **Unified Policy Execution Loop:** Given `policy_mode == PolicyRuntimeMode.HEURISTIC`, when `FarmingOrchestrator` steps a frame, then `PolicyRunner` evaluates the canonical `HeuristicPolicy` and passes `requested_target` into `CombatController.step()`.
- [x] **Streamlined Combat Executor:** Given `CombatController`, when stepping combat, then it executes the requested target from the policy layer without duplicating candidate ranking logic, retaining fallback delegation to the canonical ranking function only for standalone execution.
- [x] **Consistent Shadow Mode Telemetry:** Given `policy_mode == PolicyRuntimeMode.ML_SHADOW`, when recording policy insights and executed selections, then the recorded baseline matches the executed canonical heuristic identically without guesswork or phantom divergence.
- [x] **Closed-Loop Memory-Guided Camera Positioning:** Given live camera state from `LiveCameraReader`, when initializing or resetting viewport perspective, then camera pitch (~45°) and zoom-out are adjusted closed-loop using live memory pitch/zoom values rather than unmeasured blind key holds.
- [x] **Memory-Based Monster Kills Extraction:** Given `LivePlayerStatsReader` and `ClientPlayerStatsProfile`, when polling client memory, then the cumulative session monster kill counter is read directly from proven process memory offsets (`monster_kills`), populating `WorldState.monster_kill_count` without OCR subprocess overhead.
- [ ] **Decommissioning of Pixel Vitals & OCR Subsystems:** Given the perception pipeline, when processing frames:
  - `PlayerVitalsReader` (pixel scanning HUD orb) is retained: ADR-010 and US-094 establish that no bounded fingerprint-stable HP/MP/FP percentage path is proven for the supported client. This subcriterion is explicitly unmet/evidence-gated.
  - [x] `MonsterStatsReader` OCR and `MonsterStatsDebugPanel` UI diagnostics are pruned (delivered in `a80adae`).
  - [ ] Nameplate OCR and target-HP verification in `TargetVerifier` are retained because no selected-target fingerprinted memory profile is proven. This subcriterion is explicitly unmet/evidence-gated.
- [x] **Removal of Frame-Diff Stall Detection:** Given `StallDetector`, when monitoring motion, then stall decisions rely strictly on `_observe_live` (`WorldPosition` delta over time); `_observe_frame` and its peripheral pixel sampling masks are pruned.
- [x] **Pruning of Dead Code & Stubs:** Given the codebase:
  - `planner.py` (`Planner`, `Goal`, `PlanningAction`), `executor.py` (`VerifiedExecutor`), `NavigationController` (in `controllers.py`), and legacy `TeleportController` (`teleport.py`) are deleted.
  - Dead `FarmingGoal` item inventory matching and `WorldState.inventory` remnants from obsolete loot OCR are removed.
  - Obsolete test fixtures (`data/assets/fixtures/minimap/`) and associated dead test files are cleanly removed.
- [x] **Safety & Localization Invariants:** Given an emergency stop (`F12`), when triggered, all dispatching immediately halts; all user-visible strings (settings, telemetry, diagnostics) are kept synchronized in German and English.

## Out of scope

- Direct memory injection or code hooking (`WriteProcessMemory`).
- Quest NPC menu dialogue automation (tracked in a dedicated user story).
- NavMesh-to-Simulator engine conversion (scheduled in follow-up task).

## Verification

- Automated:
  ```powershell
  uv run pytest tests/unit/test_heuristic_policy.py tests/unit/test_combat_controller.py tests/unit/test_teleporter_dispatch.py tests/unit/test_live_camera.py tests/unit/test_orchestrator.py
  uv run ruff check .
  uv run mypy
  ```
- Manual (Windows):
  1. Open dashboard settings, change teleporter hotkey from `V` to another key (e.g. `B`), and trigger a teleporter action; verify new hotkey is dispatched.
  2. Start farming session under `ML_SHADOW` and `HEURISTIC` policy modes; verify target selection is smooth, identical across baseline insights and executed combat, and logs exact candidate scores.
  3. Verify the supported degradation path: HUD-derived HP/MP/FP percentages remain available when memory percentages are absent, while memory-backed monster-kill and level fields update from the client profile.
  4. Verify emergency stop (`F12`) instantly aborts all actions and releases held keys.

## Delivery status

The implementation slices covered by this story are complete and the canonical automated gate is
green: Ruff, format, MyPy, and pytest (`1278 passed, 4 skipped`, 88.70% coverage). US-092 remains
`in-progress` because the manual Windows walkthrough was not run and the two evidence-gated
decommissioning subcriteria above are not satisfied. `PlayerVitalsReader` remains the supported
percentage source under [ADR-010](../../decisions/ADR-010-client-derived-vital-maxima-are-not-runtime-resolvable.md),
and `TargetVerifier` retains nameplate/HP verification until a selected-target memory profile is
proven. Automated tests do not establish live-client behavior.
