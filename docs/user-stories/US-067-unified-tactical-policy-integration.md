---
id: US-067
title: Unified tactical policy interface, heuristic baseline, and learned policy integration
status: draft
created: 2026-08-21
updated: 2026-08-21
---

# US-067: Unified tactical policy interface, heuristic baseline, and learned policy integration

## Story

As a **Flyff bot developer and architecture designer**,
I want **a unified TacticalPolicy protocol between WorldState and tactical bot actions with swappable HeuristicPolicy and LearnedPolicy implementations and deterministic safety guardrails**,
so that **heuristic, ML, and future RL policies can be used interchangeably and safely evaluated without altering underlying low-level execution or bypassing safety limits**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/decisions/ADR-005-client-folder-asset-access-for-data-extraction.md`](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md): Read-only client assets and 3D NavMesh data.
  - [`docs/decisions/ADR-006-read-only-process-memory-access.md`](../decisions/ADR-006-read-only-process-memory-access.md): Read-only memory access for live GPS coordinates and world state.
  - [`docs/user-stories/completed/US-054-farming-telemetry-and-adaptive-navigation-dataset.md`](completed/US-054-farming-telemetry-and-adaptive-navigation-dataset.md): Parquet telemetry dataset foundation.
  - [`docs/user-stories/US-066-farming-and-navigation-value-model.md`](US-066-farming-and-navigation-value-model.md): Offline trained value models and metadata.
  - Follow-up stories: [`US-068`](US-068-rolling-horizon-multi-target-planning.md), [`US-069`](US-069-experience-based-navmesh-routing.md), [`US-071`](US-071-unified-rl-environment-and-reward.md).
- **Target Architecture:**
  ```text
  WorldState Snapshot
          ↓
  Deterministic Pre-Filters (Alive, Unlocked, In Leash, NavMesh Reachable, Valid 3D Pos)
          ↓
  TacticalPolicy (HeuristicPolicy | LearnedPolicy)
          ↓
  TacticalAction (TargetAction | NavigateAction | AttackPointAction | CorridorAction | InteractAction)
          ↓
  Safety Guards & NavMesh Route Planner
          ↓
  Navigation / Combat / Interaction Controllers
          ↓
  Guarded Win32 Input Execution
  ```
- **Separation of Policy and Execution:**
  - `TacticalPolicy` decides *what* tactical intent to execute (`TacticalAction`), while existing controllers execute *how* to achieve it via deterministic motion, heading tracking, and skill key presses.
  - All safety guardrails (foreground check, emergency stop, stall detection, collision recovery) remain downstream and fully independent of policies.

## Functional Requirements & Technical Architecture

### FR-1 – TacticalPolicy Protocol
- A typed protocol interface MUST be established:
  ```python
  class TacticalPolicy(Protocol):
      def evaluate(
          self,
          world_state: WorldState,
          context: PolicyContext,
      ) -> TacticalAction | None:
          ...
  ```
- At least two interchangeable policy implementations MUST be supported:
  1. `HeuristicPolicy`: Encapsulates the existing deterministic heuristic logic.
  2. `LearnedPolicy`: Evaluates US-066 offline models / ONNX inference sessions to choose optimal tactical actions.

### FR-2 – TacticalAction Model
- Policies MUST return typed action instances from a structured action hierarchy:
  - `TargetAction(target_id, target_pos, expected_cost)`
  - `NavigateAction(destination, reason)`
  - `AttackPointAction(target_id, attack_point, approach_angle)`
  - `CorridorAction(target_id, preferred_corridor_id)`
  - `InteractAction(interaction_target_id, interaction_type)`
  - `WaitAction(duration_seconds, reason)`
- Policies MUST NOT dispatch raw keyboard or mouse scan codes directly.

### FR-3 – Deterministic Pre-Filtering & Action Masking
- Policies MUST ONLY consider candidates and actions that satisfy deterministic validity:
  - Monster is alive and recognized in perception feed
  - Monster is not spatially locked out
  - Destination is within configured patrol leash
  - Destination is topologically reachable on the NavMesh
  - Valid 3D coordinates exist (`world_position is not None`)
- Policies MUST NOT bypass deterministic safety or boundary checks.

### FR-4 – Heuristic Baseline Policy
- The existing deterministic targeting, navigation, and combat transitions MUST be encapsulated inside `HeuristicPolicy`.
- `HeuristicPolicy` serves as the baseline for performance comparison and default fallback.

### FR-5 – Learned Policy & Model Lifecycle
- `LearnedPolicy` loads US-066 ONNX model artifacts on session start and verifies `metadata.json` schema compatibility.
- Features are extracted via a shared, versioned feature builder.
- Candidate actions are ranked by expected cost or predicted value.

### FR-6 – Automatic Fault-Tolerant Fallback
- The system MUST fall back to `HeuristicPolicy` seamlessly if:
  - Model file is missing or corrupted
  - Feature vector contains unexpected NaNs/Infs
  - Policy produces an invalid or unmasked action
  - Inference raises an unhandled exception
  - Policy execution exceeds the latency threshold ($> 5\text{ ms}$)
- Fallback MUST NOT cause bot stalling, mode crashes, or character death.

### FR-7 – Runtime Modes & Telemetry
- Three selectable modes MUST be supported:
  - `HEURISTIC`: Pure heuristic policy (baseline).
  - `ML_SHADOW`: Heuristic policy governs live execution; Learned policy runs in parallel to log comparison telemetry without executing.
  - `ML_ACTIVE`: Learned policy governs execution with automatic heuristic fallback.
- Telemetry logs selector type, chosen actions, shadow predictions, and fallback events.

## Acceptance criteria

- [ ] **Unified Protocol:** `TacticalPolicy` protocol is defined with typed `TacticalAction` return types.
- [ ] **Heuristic Policy Parity:** `HeuristicPolicy` encapsulates legacy bot decision logic and produces identical operational behavior.
- [ ] **Learned Policy Execution:** `LearnedPolicy` evaluates pre-qualified candidates using US-066 ONNX models and ranks valid actions.
- [ ] **Deterministic Pre-Filtering:** Only candidates satisfying alive, unlocked, in-leash, and NavMesh reachability rules are provided to policies.
- [ ] **Zero-Crash Fallback:** Missing models, NaN outputs, exceptions, or timeouts trigger an immediate fallback to `HeuristicPolicy`.
- [ ] **Runtime Modes:** Modes `HEURISTIC`, `ML_SHADOW`, and `ML_ACTIVE` are selectable via configuration and UI.
- [ ] **Shadow Mode Safety:** In `ML_SHADOW` mode, learned evaluations are recorded in telemetry without affecting live movement or combat.
- [ ] **Safety Decoupling:** Foreground checking, emergency stop (`ESC`/`END`), and obstacle stall recovery remain downstream and independent of policies.
- [ ] **Performance Budget:** Policy evaluation completes in $< 5\text{ ms}$ per cycle without tick-level file I/O.
- [ ] **Localization & Diagnostics:** All new configuration labels, status indicators, and logs are synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).
- [ ] **Quality Gate:** Automated tests pass `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).

## Out of scope

- Direct mouse/keyboard simulation inside policy implementations.
- Real-time online reinforcement learning or live parameter adjustments.
- Multi-step combinatorial lookahead planning (handled in US-068).
- NavMesh graph topology modification (handled in US-069).
- Memory write operations (`WriteProcessMemory`) or anti-cheat manipulation.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_tactical_policy.py` validating `TacticalPolicy` protocol compliance and `TacticalAction` structures.
  - Unit tests in `tests/unit/test_heuristic_policy.py` verifying legacy behavioral parity.
  - Unit tests in `tests/unit/test_learned_policy.py` verifying ONNX inference, action scoring, and error handling.
  - Unit tests in `tests/unit/test_policy_fallback.py` validating automatic fallback to heuristic on corrupted input, NaN, or timeout.
  - Unit tests in `tests/unit/test_policy_shadow_mode.py` validating telemetry output and action isolation in shadow mode.
  - `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows):
  - Run bot in `ML_SHADOW` mode: confirm smooth farming and inspect telemetry to verify parallel policy logging.
  - Run bot in `ML_ACTIVE` mode: confirm seamless target selection and transitions to combat.
  - Delete or corrupt the model file during startup: verify automatic fallback to `HEURISTIC` mode with informative warning logs.
