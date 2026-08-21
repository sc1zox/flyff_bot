---
id: US-067
title: ML TargetSelector, ONNX live inference, and runtime shadow mode
status: draft
created: 2026-08-21
updated: 2026-08-21
---

# US-067: ML TargetSelector, ONNX live inference, and runtime shadow mode

## Story

As a **Flyff bot developer and operator**,
I want **to integrate the offline-trained farming value model from US-066 into the live bot via a pluggable TargetSelector interface with ONNX inference, shadow mode evaluation, and deterministic fallback**,
so that **the bot selects target candidates with the lowest expected farming cost and highest farming value among pre-qualified mobs without risking stability or bypassing existing safety guardrails.**

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/decisions/ADR-005-client-folder-asset-access-for-data-extraction.md`](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md): Read-only client assets and 3D NavMesh data.
  - [`docs/decisions/ADR-006-read-only-process-memory-access.md`](../decisions/ADR-006-read-only-process-memory-access.md): Read-only memory access for live GPS coordinates and world state.
  - [`docs/user-stories/completed/US-054-farming-telemetry-and-adaptive-navigation-dataset.md`](completed/US-054-farming-telemetry-and-adaptive-navigation-dataset.md): Telemetry dataset foundation.
  - [`docs/user-stories/US-066-offline-farming-value-model.md`](US-066-offline-farming-value-model.md): Offline trained models, metadata schema, and cost formula.
  - Follow-up story: **US-068 – Rolling-Horizon Target Sequencing & Multi-Kill Planning**.
- **Scope & Role of Machine Learning:**
  US-067 integrates exclusively the **online inference layer** of the farming value models trained in US-066.
  The machine learning model acts strictly as a **ranking layer** over deterministically pre-qualified candidates; it does not replace core safety checks, line-of-sight validation, NavMesh route planning, or combat execution.
  
  ```text
  Visible / Detected Mobs
          ↓
  Deterministic Guardrails (Alive, Unlocked, In Leash, NavMesh Reachable, Valid 3D Pos)
          ↓
  Eligible Candidates
          ↓
  Runtime Feature Builder
          ↓
  Farming Value Model (ONNX Session)
          ↓
  Expected Cost per Candidate
          ↓
  ML TargetSelector
          ↓
  Best Candidate
          ↓
  Existing NavMesh Pathing / Combat Controller
  ```

- **Cost Formula:**
  $$\text{ExpectedCost} = \hat{T}_{\text{travel}} + \hat{T}_{\text{kill}} + \hat{P}_{\text{stuck}} \cdot \hat{T}_{\text{recovery}} - \lambda \cdot \widehat{V}_{\text{followup}}$$
- **Deterministic Safety & Fallback:**
  - The existing heuristic target selection logic is preserved as `HeuristicTargetSelector` and serves as a zero-overhead deterministic fallback.
  - Any model error, incompatibility, unexpected output (NaN/Inf), or timeout immediately falls back to heuristic selection without interrupting the farming session.

## Functional Requirements & Technical Architecture

### FR-1 – TargetSelector Protocol
- Target selection logic MUST be abstracted behind a typed protocol interface:
  ```python
  class TargetSelector(Protocol):
      def select(
          self,
          context: TargetSelectionContext,
          candidates: Sequence[TargetCandidate],
      ) -> TargetCandidate | None:
          ...
  ```
- At least two concrete implementations MUST be provided:
  1. `HeuristicTargetSelector`: Encapsulates the existing deterministic heuristic ranking logic (`_best_candidate`).
  2. `MLTargetSelector`: Evaluates pre-filtered candidates using ONNX model inference and ranks by `ExpectedCost`.

### FR-2 – Deterministic Candidate Filtering
- The ML model MUST ONLY evaluate candidates that pass all deterministic pre-conditions:
  - Candidate is marked alive (`is_alive_candidate == True`)
  - Candidate is not locked out (`is_locked_out == False`)
  - Candidate is within configured patrol leash (`within_leash == True`)
  - Target is reachable on the NavMesh (`navmesh_reachable == True`)
  - Valid, finite 3D world coordinates exist (`world_position is not None`)
- Mobs failing deterministic criteria MUST NOT be evaluated or selected by the ML model.

### FR-3 – Runtime Feature Builder
- A dedicated, versioned `TargetFeatureBuilder` MUST assemble live candidate features matching the exact schema, feature order, normalization, and null-handling used during US-066 offline training:
  - `path_distance`, `relative_distance`, `relative_elevation`
  - `player_heading`, `target_bearing`
  - `terrain_slope`
  - `target_class_id`, `detection_confidence`
  - `visible_mob_count`, `reachable_mob_count`, `nearby_targetable_mob_count`
  - `recent_kill_rate`, `recent_stuck_rate`
- Training and inference feature transformations MUST remain strictly synchronized and versioned.

### FR-4 – Model Loading & Session Lifecycle
- Models MUST be loaded once at farming session startup from the configured artifact path (e.g., `models/farming_value/v1/`).
- Startup validation MUST verify:
  - `schema_version` and `feature_schema` compatibility
  - Model artifact file integrity (ONNX model files present and readable)
  - Bot version and telemetry contract compatibility via `metadata.json`
- Incompatible or corrupted models MUST fail validation gracefully and disable ML mode with diagnostic logging, falling back to heuristic selection.

### FR-5 – ONNX Inference & Candidate Ranking
- Live inference MUST be executed via `onnxruntime`.
- For each valid candidate, the model predicts:
  - $\hat{T}_{\text{travel}}$ (`predicted_travel_time`)
  - $\hat{T}_{\text{kill}}$ (`predicted_kill_time`)
  - $\hat{P}_{\text{stuck}}$ (`predicted_stuck_probability`)
  - $\hat{T}_{\text{recovery}}$ (`predicted_recovery_cost`)
  - $\widehat{V}_{\text{followup}}$ (`predicted_followup_value`)
- Expected cost is computed:
  $$\text{ExpectedCost} = \hat{T}_{\text{travel}} + \hat{T}_{\text{kill}} + \hat{P}_{\text{stuck}} \cdot \hat{T}_{\text{recovery}} - \lambda \cdot \widehat{V}_{\text{followup}}$$
- The eligible candidate with the lowest valid `ExpectedCost` is selected.

### FR-6 – Inference Performance & Latency Budget
- Candidate feature extraction, ONNX inference, and ranking for a typical candidate batch ($\le 20$ mobs) MUST complete within $< 5\text{ ms}$.
- Inference MUST NOT perform file I/O, memory allocations across large arrays, or model reloads during the active 10 Hz orchestrator loop.

### FR-7 – Deterministic Fallback & Fault Tolerance
- Automatic fallback to `HeuristicTargetSelector` MUST occur seamlessly under any of the following conditions:
  - Model artifact missing or uninitialized
  - Model incompatibility / schema version mismatch
  - Invalid feature vector or missing mandatory live inputs
  - Model output contains `NaN`, `Inf`, or violates sanity bounds
  - Inference exception or runtime error
  - Inference exceeds configured latency threshold (timeout)
- A fallback event MUST NOT crash the orchestrator, terminate the farming session, or disrupt character movement.

### FR-8 – Confidence & Sanity Guards
- Predicted quantities MUST pass validation checks before being used for ranking:
  - $\hat{T}_{\text{travel}} \ge 0.0$
  - $\hat{T}_{\text{kill}} \ge 0.0$
  - $0.0 \le \hat{P}_{\text{stuck}} \le 1.0$
  - $\hat{T}_{\text{recovery}} \ge 0.0$
  - All values must be finite floating-point numbers.
- Candidates with invalid model outputs MUST be disqualified from ML ranking or trigger fallback.

### FR-9 – Runtime Shadow Mode
- The system MUST support an evaluation shadow mode (`ML_SHADOW`):
  - `HeuristicTargetSelector` makes the authoritative target decision.
  - `MLTargetSelector` runs concurrently in the background and evaluates candidates.
  - Telemetry logs both selections and comparative scores:
    - `heuristic_target_id`, `ml_target_id`
    - `heuristic_score`, `ml_expected_cost`
    - `selectors_agree` (boolean flag)
- Shadow mode MUST NOT influence live actions, movement, or combat execution.

### FR-10 – Explicit Runtime Modes
- The bot configuration MUST support three distinct selectable modes:
  1. `HEURISTIC`: Pure deterministic heuristic target selection (baseline).
  2. `ML_SHADOW`: Heuristic selection drives execution; ML evaluates in parallel for telemetry collection.
  3. `ML_ACTIVE`: ML target selection drives execution with automatic heuristic fallback.

### FR-11 – Telemetry Integration
- Target decision telemetry MUST be enriched with selection metadata:
  - `selector_type` (`HEURISTIC`, `ML_SHADOW`, `ML_ACTIVE`)
  - `model_version`
  - `candidate_count`
  - `selected_target_id`
  - Predicted metrics ($\hat{T}_{\text{travel}}, \hat{T}_{\text{kill}}, \hat{P}_{\text{stuck}}, \widehat{V}_{\text{followup}}, \text{ExpectedCost}$)
  - `fallback_used` (boolean) and `fallback_reason` (string enum)
  - Candidate ranking breakdown (optional / debug level).

### FR-12 – Model Comparison & Counterfactual Integrity
- Shadow-mode telemetry MUST allow offline comparison of heuristic vs. ML choices against real observed outcomes.
- The system MUST maintain off-policy integrity: unchosen targets are marked as counterfactually unknown rather than assigned synthetic rewards.

## Acceptance criteria

- [ ] **TargetSelector Protocol:** `TargetSelector` is defined as a typed protocol, with `HeuristicTargetSelector` and `MLTargetSelector` implementations.
- [ ] **Heuristic Baseline Preservation:** The existing heuristic target selection algorithm is encapsulated in `HeuristicTargetSelector` and produces identical selections to legacy code.
- [ ] **Model Loading & Validation:** `MLTargetSelector` loads US-066 ONNX model artifacts and validates `metadata.json` schema, feature compatibility, and file integrity on session startup.
- [ ] **Deterministic Pre-Qualification:** Only candidates that are alive, not locked out, within leash, NavMesh-reachable, and possess valid 3D coordinates are submitted to the ML model.
- [ ] **Feature Builder Schema Parity:** `TargetFeatureBuilder` produces runtime feature arrays identical in definition, order, and null-handling to the US-066 training pipeline.
- [ ] **ONNX Batch Inference & Ranking:** `MLTargetSelector` scores candidate batches via ONNX inference and ranks them by `ExpectedCost` using configurable component weights.
- [ ] **Sanity & Confidence Bounds:** Predictions with non-finite values (NaN/Inf), negative durations, or invalid probabilities are rejected.
- [ ] **Deterministic Fallback:** Model load failures, invalid outputs, exceptions, or timeouts trigger an immediate, graceful fallback to `HeuristicTargetSelector` without session interruption.
- [ ] **Mode Configuration:** Runtime modes `HEURISTIC`, `ML_SHADOW`, and `ML_ACTIVE` are configurable via config and dashboard settings.
- [ ] **Shadow Mode Isolation:** In `ML_SHADOW` mode, ML evaluation executes in parallel without altering live targeting decisions.
- [ ] **Telemetry Enrichment:** Target decision events record selector mode, model version, predicted cost breakdown, and fallback diagnostics.
- [ ] **Latency Budget & Performance:** Candidate feature construction, ONNX inference, and ranking complete within $< 5\text{ ms}$ for typical candidate batches without tick-level file I/O.
- [ ] **Localization & Diagnostics:** All new UI configuration labels, mode names, tooltips, and log events are synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).
- [ ] **Quality Gate:** Automated checks pass `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).

## Out of scope

- Online Reinforcement Learning, live weight updates, or in-game policy exploration.
- Multi-step lookahead sequencing over combinatorial monster graphs (deferred to US-068).
- Direct waypoint generation or movement key manipulation by ML.
- ML-driven combat skill rotation learning.
- Automated model retraining or deployment triggers.
- Memory write operations (`WriteProcessMemory`), code injection, or anti-cheat tampering.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_target_selector.py` validating `TargetSelector` protocol compliance, `HeuristicTargetSelector` behavior, and candidate filtering guardrails.
  - Unit tests in `tests/unit/test_target_feature_builder.py` validating feature vector extraction and parity with US-066 schemas.
  - Unit tests in `tests/unit/test_ml_target_selector.py` validating ONNX model loading, batch inference, expected cost calculation, ranking, sanity bounds, and fallback triggers.
  - Unit tests in `tests/unit/test_shadow_mode_telemetry.py` validating `ML_SHADOW` mode execution, telemetry logging, and isolation from live decisions.
  - Benchmark test verifying $< 5\text{ ms}$ inference execution on candidate batches.
  - `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows):
  - Start bot in `ML_SHADOW` mode with a loaded US-066 ONNX model: verify smooth farming with heuristic decisions and verify telemetry logs both heuristic and ML predictions.
  - Switch to `ML_ACTIVE` mode: verify the bot targets the highest-value / lowest-cost mobs smoothly and transitions to combat without stuttering.
  - Simulate model error (e.g. corrupt model file or missing feature): verify automatic seamless fallback to `HEURISTIC` without crashing or pausing the bot.
