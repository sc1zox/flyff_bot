---
id: US-084
title: ML-modifiable tactical parameter space, hybrid tuning, and clamped safety bounds
status: draft
created: 2026-08-28
updated: 2026-08-28
---

# US-084: ML-Modifiable Tactical Parameter Space, Hybrid Tuning, and Clamped Safety Bounds

## Story

As a **bot developer and operator**,
I want **all tactical, operational, and perceptual constants exposed as a typed, bounded parameter space that can be optimized offline and modulated dynamically by ML/RL policies**,
so that **farming efficiency, navigation fluidness, and combat engagement can self-tune across monster classes, areas, and setups without modifying hardcoded code literals or risking system invariants.**

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/decisions/ADR-007-offline-tactical-simulation-boundary.md`](../decisions/ADR-007-offline-tactical-simulation-boundary.md): Fast offline simulation boundary.
  - [`docs/decisions/ADR-008-closed-learning-loop-invariants.md`](../decisions/ADR-008-closed-learning-loop-invariants.md): Parameterized action and closed learning invariants.
  - [`docs/user-stories/US-079-unified-goal-conditioned-decision-contract.md`](US-079-unified-goal-conditioned-decision-contract.md): Unified decision contract.
  - [`docs/user-stories/US-081-experience-database-and-train-evaluate-promote-loop.md`](US-081-experience-database-and-train-evaluate-promote-loop.md): Experience DB and train-evaluate-promote loop.
  - [`docs/user-stories/US-083-authoritative-client-data-fusion-for-yolo-farming.md`](US-083-authoritative-client-data-fusion-for-yolo-farming.md): Authoritative client data fusion.

### Background & Rationale

Historically, operational heuristics such as waypoint arrival radii, heading tolerance thresholds, engagement distances, camera pitch angles, potion triggers, and stall timeouts were embedded as module-level constants or default configuration fields. 

While core system invariants (Win32 virtual keys, memory offsets, process signatures, schema versions, and emergency stop mechanisms) must remain strictly immutable, all operational heuristics are **taktische Parameter** that directly determine farming yield, traversal speed, and stuck frequency.

Exposing these parameters to ML/RL enables a **hybrid tuning architecture**:
1. **Offline Hyperparameter & Policy Optimization (Macro-Tuning):** The offline simulator ([US-072](completed/US-072-offline-farming-and-navigation-simulator.md)) evaluates parameter combinations and policies across thousands of episodes, finding optimal configurations per monster class and region.
2. **Contextual Action Overrides (Micro-Tuning):** The live tactical policy ([US-079](US-079-unified-goal-conditioned-decision-contract.md)) can emit dynamic parameter offsets per decision (e.g. contextual approach distance for clustered monsters).
3. **Clamped Safety Bounds:** Every parameter has strict, physically valid minimum and maximum boundaries. Unbounded or out-of-range values are clamped deterministically; non-finite (`NaN`, `Inf`) inputs trigger fail-closed safeguards.

---

## Acceptance criteria

### 1. Typed Tactical Parameter Space & Bounded Definitions
- [ ] **Given** the navigation, combat, perception, and recovery systems, **when** parameters are defined, **then** a typed `TacticalParameterSpace` dataclass encapsulates:
  - **Navigation:** `navmesh_waypoint_arrival_units`, `heading_tolerance_degrees`, `heading_pivot_threshold_degrees`, `replan_interval_seconds`, `stall_timeout_seconds`.
  - **Combat & Targeting:** `engagement_distance_units` (per monster class/profile), `attack_key_delay_seconds`, `target_lockout_seconds`, `click_debounce_seconds`.
  - **Perception & Camera:** `camera_pitch_degrees`, `camera_zoom_level`, `search_turn_duration_seconds`, `target_verification_threshold`.
  - **Vitals & Recovery:** `hp_potion_threshold_percent`, `mp_threshold_percent`, `recovery_debounce_seconds`.
- [ ] **Given** each parameter in the space, **when** inspected, **then** it defines explicit immutable min/max bounds and default fallback values.

### 2. Clamped Safety Enforcement & Non-Finite Safeguards
- [ ] **Given** any parameter input from an offline optimization run, config file, or live ML policy, **when** the value exceeds defined safe bounds, **then** the value is clamped to `[min_bound, max_bound]` without crashing.
- [ ] **Given** any parameter value that is non-finite (`NaN` or `+/-Infinity`), **when** validated, **then** it is rejected, falls back to the safe default, and records a localized diagnostic event.

### 3. Hybrid Optimization: Profile Persistence & Dynamic Policy Overrides
- [ ] **Given** an offline optimization run via simulator or telemetry evaluation, **when** an optimal parameter set is promoted, **then** it is serializable to a versioned `.json` tactical profile compatible with the model registry ([US-081](US-081-experience-database-and-train-evaluate-promote-loop.md)).
- [ ] **Given** a live decision tick with an active ML policy, **when** the policy outputs contextual action parameters (such as dynamic approach distance in `AttackPointAction`), **then** the controller dynamically applies the clamped contextual override for that action.

### 4. Integration with Simulator and Controllers
- [ ] **Given** `FarmingSimulator` ([US-072](completed/US-072-offline-farming-and-navigation-simulator.md)), **when** executed, **then** it accepts a custom `TacticalParameterSpace` instance to evaluate farming yield (KPM, travel time, stall rate) under different parameter sets.
- [ ] **Given** deterministic controllers (`PathingController`, `CombatController`, `RecoveryController`), **when** stepping, **then** they read active values from the unified `TacticalParameterSpace` instead of unmodifiable file-level constants.

### 5. Desktop UI Diagnostics & Profile Controls
- [ ] **Given** the Desktop UI, **when** viewing settings or diagnostics, **then** active tactical parameters are displayed, and operators can inspect, export, load, or reset tactical parameter profiles.

### 6. Strict Isolation of System Invariants
- [ ] **Given** the entire parameter space, **when** verified, **then** Win32 virtual keys, memory offsets, emergency stop keys (`ESC`/`END`), window focus checks, and schema digests remain strictly excluded from ML/RL modification.

### 7. Localization
- [ ] All user-visible parameter names, descriptions, and validation diagnostics are available in synchronized German and English locale resources (`src/flyff_bot/locales/*.json`).

---

## Out of scope

- Direct memory modification or Win32 API code hooking (`WriteProcessMemory`).
- Online weight updates or in-process exploratory random actions against the live game client.
- Modifying OS-level virtual key codes or low-level window handle management.

---

## Verification

### Automated
```powershell
uv run pytest tests/unit/test_tactical_parameters.py tests/unit/test_pathing.py tests/unit/test_simulator_determinism.py
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

### Manual (Windows)
1. Load a custom tactical parameter profile with modified engagement distance and camera pitch in the UI.
2. Start autonomous farming and verify that character maintains the modified engagement distance and camera angle.
3. Test emergency stop (`END`/`ESC`) and verify it halts immediately regardless of active parameter tuning.
