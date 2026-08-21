---
id: US-066
title: Offline farming value model and dataset training pipeline
status: draft
created: 2026-08-21
updated: 2026-08-21
---

# US-066: Offline farming value model and dataset training pipeline

## Story

As a **Flyff bot developer and ML engineer**,
I want **to generate an offline-trained farming value model from recorded US-054 Parquet telemetry datasets**,
so that **target candidates can be evaluated based on their expected real costs and future farming value without prematurely replacing the existing heuristic target selection in the live bot**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/decisions/ADR-005-client-folder-asset-access-for-data-extraction.md`](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md): Read-only client assets and 3D NavMesh data.
  - [`docs/decisions/ADR-006-read-only-process-memory-access.md`](../decisions/ADR-006-read-only-process-memory-access.md): Read-only memory access for live GPS coordinates and world state.
  - [`docs/user-stories/completed/US-054-farming-telemetry-and-adaptive-navigation-dataset.md`](completed/US-054-farming-telemetry-and-adaptive-navigation-dataset.md): Parquet telemetry datasets (`target_decisions.parquet`, `navigation_trajectories.parquet`, `kill_cycles.parquet`).
  - Follow-up story: **US-067 – ML TargetSelector & ONNX Live Inference**.
- **Scope & Objective:**
  US-066 implements exclusively the **offline training and evaluation layer** for the farming value model.
  The model does not make direct runtime targeting decisions in this story, but predicts measurable quantities for a candidate target:
  - $\hat{T}_{\text{travel}}$ (`predicted_travel_time`)
  - $\hat{T}_{\text{kill}}$ (`predicted_kill_time`)
  - $\hat{P}_{\text{stuck}}$ (`predicted_stuck_probability`)
  - $\hat{T}_{\text{recovery}}$ (`predicted_recovery_cost`)
  - $\widehat{V}_{\text{followup}}$ (`predicted_followup_value`)
- **Cost / Value Formulation:**
  $$\text{ExpectedCost} = \hat{T}_{\text{travel}} + \hat{T}_{\text{kill}} + \hat{P}_{\text{stuck}} \cdot \hat{T}_{\text{recovery}} - \lambda \cdot \widehat{V}_{\text{followup}}$$
  The global optimization objective is $\max \text{KillsPerMinute}$ under minimal stuck, idle, and unnecessary navigation time.
- **Safety Boundaries:**
  - US-066 is 100% offline.
  - No input actions are dispatched to any window.
  - No modifications to `CombatController` runtime logic.
  - No ML decisions activated in live farming sessions.
  - No expansion of memory-read boundaries.
  - Training executes completely decoupled without requiring a running game client (`neuz.exe`).

## Functional Requirements & Technical Architecture

### FR-1 – Dataset Builder
- The existing US-054 Parquet telemetry MUST be compiled into structured, trainable transition samples.
- Primary data sources:
  - `target_decisions.parquet`
  - `navigation_trajectories.parquet`
  - `kill_cycles.parquet`
- Each training sample MUST be deterministically linked to an executed target decision and its observed outcome (via session ID and decision timestamp join).
- Train/test splitting MUST prevent session leakage (split by session ID or contiguous temporal blocks rather than random i.i.d. row shuffling).

### FR-2 – Candidate Features
- For the selected candidate target, the feature extractor MUST support at least:
  - **Spatial & Geometric:** `path_distance`, `relative_distance`, `relative_elevation`, `player_heading`, `target_bearing`, `terrain_slope`.
  - **Perception & Identification:** `target_class_id`, `detection_confidence`.
  - **Density & Cluster Context:** `visible_mob_count`, `reachable_mob_count`, `nearby_targetable_mob_count`.
  - **Temporal & Historical State:** `recent_kill_rate`, `recent_stuck_rate`.
- Missing or unavailable features MUST be explicitly handled (e.g. `NaN` flags / explicit missingness indicators) and NEVER substituted with fabricated pseudo-data.

### FR-3 – Training Labels (Ground Truth)
- Ground-truth labels MUST be derived exclusively from actually observed session episodes:
  - `actual_travel_time` ($T_{\text{travel}}$)
  - `actual_kill_time` ($T_{\text{kill}}$)
  - `stuck_occurred` (boolean indicator)
  - `actual_stuck_time` ($T_{\text{stuck}}$)
  - `actual_recovery_time` ($T_{\text{recovery}}$)
  - `kill_to_kill_time` ($T_{\text{k2k}}$)
  - `targetable_mobs_after_kill`
  - `kills_next_5s`
  - `kills_next_10s`
- Labels MUST NOT incorporate fabricated or guessed values.

### FR-4 – Follow-up Value Formulation
- The system MUST compute a measurable post-kill farming value.
- At least one objective target MUST be supported, such as:
  $$\text{FollowupValue} = \text{KillsNext10Seconds}$$
  or
  $$\text{FollowupValue} = \text{TargetableMobsAfterKill}$$
- The exact formulation MUST be versioned and recorded in the training configuration.

### FR-5 – Separate Prediction Heads / Modular Models
- The architecture MUST favor modular models or cleanly separated prediction heads for distinct physical quantities:
  1. Travel Time Model ($\hat{T}_{\text{travel}}$)
  2. Kill Time Model ($\hat{T}_{\text{kill}}$)
  3. Stuck Risk Model ($\hat{P}_{\text{stuck}}$)
  4. Recovery Cost Model ($\hat{T}_{\text{recovery}}$)
  5. Follow-up Value Model ($\widehat{V}_{\text{followup}}$)
- A monolithic black-box RL/policy model is explicitly NOT required.

### FR-6 – Baseline Models & Dependencies
- At least one simple baseline model MUST be implemented (e.g. Linear/Ridge Regression, Gradient Boosting, or small MLP).
- Any additional lightweight ML dependencies (e.g., `scikit-learn`, `lightgbm`, `onnx`, `onnxruntime`) MUST be justified, reproducible, and pinned cleanly in `pyproject.toml`.

### FR-7 – Offline Evaluation & Benchmarking
- Each model MUST be evaluated against a holdout test set.
- Recorded evaluation metrics MUST include:
  - **Travel time:** MAE, RMSE
  - **Kill time:** MAE, RMSE
  - **Stuck risk:** Precision, Recall, ROC-AUC or PR-AUC
  - **Follow-up value:** MAE, ranking correlation (Spearman's $\rho$ / Kendall's $\tau$)
- The existing heuristic target selection MUST remain comparable as an evaluation baseline.

### FR-8 – Farming Value & Expected Cost Derivation
- Candidate expected cost MUST be computed offline from model outputs:
  $$\text{expected\_cost} = \hat{T}_{\text{travel}} + \hat{T}_{\text{kill}} + \hat{P}_{\text{stuck}} \cdot \hat{T}_{\text{recovery}} - \lambda \cdot \widehat{V}_{\text{followup}}$$
- Component weights ($\lambda$, etc.) MUST be fully configurable.

### FR-9 – Counterfactual Limitation & Off-Policy Integrity
- The system MUST NOT assume or fabricate rewards for unselected candidates ($\text{counterfactual\_reward} = \text{unknown}$).
- The model MUST NOT treat the existing heuristic decisions as ground truth for optimal choices.

### FR-10 – Versioned Model Artifact & Export
- Successfully trained models MUST be stored in a versioned artifact hierarchy:
  ```text
  models/
  └── farming_value/
      └── v1/
          ├── travel_time.onnx
          ├── kill_time.onnx
          ├── stuck_risk.onnx
          ├── followup_value.onnx
          └── metadata.json
  ```
- `metadata.json` MUST contain at least:
  `schema_version`, `training_dataset_version`, `feature_schema`, `label_schema`, `training_timestamp`, `metrics`, `bot_version`, `client_build_hash`.

### CLI / Training Entry Point
- A reproducible offline training command MUST be provided, for example:
  ```powershell
  uv run python -m flyff_bot.features.ml.train_farming_value --dataset data/datasets/rl --output models/farming_value/v1
  ```
- The training routine MUST NOT require a running Flyff client.

## Acceptance criteria

- [ ] **Parquet Telemetry Ingestion:** US-054 Parquet datasets (`target_decisions.parquet`, `navigation_trajectories.parquet`, `kill_cycles.parquet`) can be loaded and joined into structured training samples.
- [ ] **Sample Determinism & Leakage Prevention:** Target decision, navigation trajectory, and kill cycle data are linked deterministically by session ID and decision timestamp, and train/test splits prevent session leakage.
- [ ] **Candidate Feature Extraction:** Feature schema is explicitly versioned; geometric, perceptual, and spatial features (`path_distance`, `relative_distance`, `relative_elevation`, `player_heading`, `target_bearing`, `terrain_slope`, `target_class_id`, `detection_confidence`, `visible_mob_count`, `reachable_mob_count`, `nearby_targetable_mob_count`, `recent_kill_rate`, `recent_stuck_rate`) handle missing data explicitly with zero fabricated values.
- [ ] **Observed Ground-Truth Labels:** Ground-truth labels (`actual_travel_time`, `actual_kill_time`, `stuck_occurred`, `actual_stuck_time`, `actual_recovery_time`, `kill_to_kill_time`, `targetable_mobs_after_kill`, `kills_next_5s`, `kills_next_10s`) originate strictly from observed session episodes.
- [ ] **Follow-up Value Formulation:** At least one measurable post-kill value target (e.g. `kills_next_10s` or `targetable_mobs_after_kill`) is computed and versioned in the training configuration.
- [ ] **Modular Model Training:** Independent models/prediction heads can be trained and evaluated for travel time, kill time, stuck risk, and follow-up value.
- [ ] **Offline Evaluation Metrics:** Standardized metrics (MAE, RMSE, Precision, Recall, ROC-AUC / PR-AUC, ranking correlation) are computed on holdout data and benchmarked against heuristic baselines.
- [ ] **Expected Cost Calculation:** Farming cost / expected cost is calculated offline from predicted outputs using configurable trade-off weights.
- [ ] **Off-Policy Integrity:** Unselected candidates are treated as counterfactually unknown without pseudo-label assumptions.
- [ ] **Versioned Artifact & Metadata Export:** Models can be exported into standardized inference formats (e.g., ONNX) alongside a validated `metadata.json` containing schema, dataset version, metrics, and git commit.
- [ ] **Zero Live Client Interaction:** Training and evaluation execute fully offline without requiring a running game client, sending input actions, or expanding memory reads.
- [ ] **Localization & Diagnostics:** All user-visible CLI options, diagnostic messages, and logs are synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).
- [ ] **Quality Gate:** Code passes `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).

## Out of scope

- Live ONNX inference inside the active farming loop (deferred to US-067).
- `TargetSelector` runtime integration or replacement of `_best_candidate` in `CombatController` (deferred to US-067).
- Reinforcement Learning, Decision Transformers, online policy gradients, or runtime exploration in the live client.
- Multi-step lookahead sequencing over combinatorial monster graphs.
- Memory write operations (`WriteProcessMemory`), code injection, or anti-cheat tampering.
- Automated deployment decision pipelines.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_farming_value_dataset.py` validating Parquet dataset loading, temporal join, feature matrix construction, and label generation.
  - Unit tests in `tests/unit/test_farming_value_models.py` validating baseline model training, evaluation metrics, and expected cost calculation.
  - Unit tests in `tests/unit/test_farming_value_export.py` validating model serialization, ONNX export, and `metadata.json` schema validation.
  - `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows):
  - Run `uv run python -m flyff_bot.features.ml.train_farming_value --dataset data/datasets/rl --output models/farming_value/v1` on recorded US-054 telemetry data.
  - Verify that `models/farming_value/v1/` contains exported models and a valid `metadata.json`.
  - Inspect evaluation logs and verify metric output (MAE, RMSE, ROC-AUC).
