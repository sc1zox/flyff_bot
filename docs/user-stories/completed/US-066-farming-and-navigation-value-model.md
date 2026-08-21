---
id: US-066
title: Farming and navigation value model and offline telemetry learning
status: completed
created: 2026-08-21
updated: 2026-08-21
---

# US-066: Farming and navigation value model and offline telemetry learning

## Story

As a **Flyff bot developer and ML engineer**,
I want **to train predictive models for travel time, stuck risk, recovery time, kill duration, and post-kill farming value from real farming and navigation episodes recorded in US-054 Parquet telemetry**,
so that **the bot can use empirical real-world experience to accurately evaluate candidate targets, routes, and movement costs without modifying live bot behavior**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../../wiki/architecture.md) & [`docs/wiki/glossary.md`](../../wiki/glossary.md).
  - [`docs/decisions/ADR-005-client-folder-asset-access-for-data-extraction.md`](../../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md): Read-only client assets and 3D NavMesh data.
  - [`docs/decisions/ADR-006-read-only-process-memory-access.md`](../../decisions/ADR-006-read-only-process-memory-access.md): Read-only memory access for live GPS coordinates and world state.
  - [`docs/user-stories/completed/US-054-farming-telemetry-and-adaptive-navigation-dataset.md`](US-054-farming-telemetry-and-adaptive-navigation-dataset.md): Parquet telemetry datasets (`target_decisions.parquet`, `navigation_trajectories.parquet`, `kill_cycles.parquet`).
  - Follow-up story: [`docs/user-stories/US-067-unified-tactical-policy-integration.md`](../US-067-unified-tactical-policy-integration.md).
- **Scope & Objective:**
  US-066 implements exclusively the **offline training and evaluation layer** for predictive farming and navigation value models.
  The models predict measurable physical and operational quantities for target candidates and navigation corridors:
  - $\hat{T}_{\text{travel}}$ (`predicted_travel_time`)
  - $\hat{P}_{\text{stuck}}$ (`predicted_stuck_probability`)
  - $\hat{T}_{\text{recovery}}$ (`predicted_recovery_time`)
  - $\hat{T}_{\text{kill}}$ (`predicted_kill_time`)
  - $\widehat{V}_{\text{followup}}$ (`predicted_followup_value`)
- **Cost / Value Formulation:**
  $$\text{ExpectedCost} = \hat{T}_{\text{travel}} + \hat{T}_{\text{kill}} + \hat{P}_{\text{stuck}} \cdot \hat{T}_{\text{recovery}} - \lambda \cdot \widehat{V}_{\text{followup}}$$
  The global optimization objective is $\max \text{KillsPerMinute}$ under minimal stuck, idle, and unnecessary navigation time.
- **Safety Boundaries:**
  - US-066 is 100% offline.
  - No input actions are dispatched to any window.
  - No modifications to runtime controllers or live farming decisions.
  - No expansion of memory-read boundaries.
  - Training executes completely decoupled without requiring a running game client (`neuz.exe`).

## Functional Requirements & Technical Architecture

### FR-1 – Parquet Telemetry Ingestion & Trajectory Correlation
- The dataset builder MUST ingest US-054 Parquet telemetry tables:
  - `target_decisions.parquet`
  - `navigation_trajectories.parquet`
  - `kill_cycles.parquet`
- GPS trajectory segments MUST be correlated with 3D NavMesh corridors and polygon sequences.
- Each training sample MUST be deterministically linked to an executed target decision and its observed outcome.
- Train/test splitting MUST prevent session leakage (split by session ID or contiguous temporal blocks).

### FR-2 – Feature Extraction
- For each evaluated candidate and navigation trajectory, features MUST include:
  - **Spatial & Geometric:** `path_distance`, `relative_distance`, `relative_elevation`, `player_heading`, `target_bearing`, `terrain_slope`.
  - **NavMesh Corridor:** corridor length, polygon count, turn angles, narrow clearance indicators.
  - **Perception & Identification:** `target_class_id`, `detection_confidence`.
  - **Density & Cluster Context:** `visible_mob_count`, `reachable_mob_count`, `nearby_targetable_mob_count`.
  - **Temporal & Historical State:** `recent_kill_rate`, `recent_stuck_rate`.
- Missing features MUST be handled explicitly with `null`/NaN indicators and NEVER replaced with fabricated values.

### FR-3 – Observed Ground-Truth Labels
- Ground-truth labels MUST originate strictly from observed session transitions:
  - `actual_travel_time` ($T_{\text{travel}}$)
  - `stuck_occurred` (boolean indicator)
  - `actual_stuck_time` ($T_{\text{stuck}}$)
  - `actual_recovery_time` ($T_{\text{recovery}}$)
  - `actual_kill_time` ($T_{\text{kill}}$)
  - `kill_to_kill_time` ($T_{\text{k2k}}$)
  - `targetable_mobs_after_kill`, `kills_next_5s`, `kills_next_10s`.
- No synthetic rewards may be assigned to unchosen decisions ($\text{counterfactual\_reward} = \text{unknown}$).

### FR-4 – Follow-up Value Formulation
- The system MUST compute a measurable post-kill value target (e.g., $V_{\text{followup}} = \text{KillsNext10Seconds}$ or $V_{\text{followup}} = \text{TargetableMobsAfterKill}$).
- The exact definition MUST be versioned and recorded in the training configuration.

### FR-5 – Modular Prediction Models
- The architecture MUST employ modular models or distinct prediction heads for:
  1. Travel Time Model ($\hat{T}_{\text{travel}}$)
  2. Stuck Risk Model ($\hat{P}_{\text{stuck}}$)
  3. Recovery Time Model ($\hat{T}_{\text{recovery}}$)
  4. Kill Time Model ($\hat{T}_{\text{kill}}$)
  5. Follow-up Value Model ($\widehat{V}_{\text{followup}}$)

### FR-6 – Baseline Models & Lightweight Dependencies
- Simple baseline models MUST be implemented (e.g. Linear/Ridge Regression, Gradient Boosting, or lightweight MLP).
- The existing heuristic cost function MUST remain comparable as an evaluation baseline.
- ML dependencies (e.g. `scikit-learn`, `lightgbm`, `onnx`) MUST be pinned cleanly in `pyproject.toml`.

### FR-7 – Offline Evaluation & Holdout Benchmarking
- Models MUST be evaluated on holdout sessions with standardized metrics:
  - **Travel time & Kill time:** MAE, RMSE
  - **Stuck risk:** Precision, Recall, ROC-AUC, PR-AUC
  - **Follow-up value:** MAE, ranking correlation (Spearman's $\rho$ / Kendall's $\tau$)

### FR-8 – Model Artifact & Metadata Export
- Trained models MUST be saved in a standardized, versioned artifact structure:
  ```text
  models/
  └── farming_value/
      └── v1/
          ├── travel_time.onnx
          ├── stuck_risk.onnx
          ├── recovery_time.onnx
          ├── kill_time.onnx
          ├── followup_value.onnx
          └── metadata.json
  ```
- `metadata.json` MUST capture dataset version, feature schema, label schema, metrics, git commit, and client build hash.

### CLI / Training Entry Point
- A reproducible offline training command MUST be provided:
  ```powershell
  uv run python -m flyff_bot.features.ml.train_farming_value --dataset data/datasets/rl --output models/farming_value/v1
  ```
- Training MUST NOT require a running Flyff client.

## Acceptance criteria

- [x] **Parquet Ingestion & Temporal Join:** US-054 Parquet datasets (`target_decisions.parquet`, `navigation_trajectories.parquet`, `kill_cycles.parquet`) are loaded and joined into structured training samples without session leakage.
- [x] **Empirical Feature Construction:** Feature extractor derives spatial, geometric, corridor, perceptual, and historical features with explicit `null`/NaN handling and zero fabricated data.
- [x] **Ground-Truth Label Extraction:** Observed travel time, kill time, stuck occurrences, recovery duration, and post-kill follow-up values are extracted exclusively from real session transitions.
- [x] **Modular Model Training:** Independent models/prediction heads for travel time, stuck risk, recovery time, kill time, and follow-up value can be trained and evaluated.
- [x] **Offline Holdout Benchmarking:** Evaluation metrics (MAE, RMSE, ROC-AUC, PR-AUC, ranking correlation) are computed against holdout data and benchmarked against heuristic baselines.
- [x] **Expected Cost Computation:** Expected farming cost is computed offline from model outputs using configurable component weights.
- [x] **Off-Policy Integrity:** Unselected candidates are treated as counterfactually unknown with no synthetic reward assumptions.
- [x] **Versioned Artifact & Metadata Export:** Models can be exported into standardized formats (e.g. ONNX) accompanied by a schema-validated `metadata.json`.
- [x] **Zero Live Client Interaction:** Training and evaluation execute fully offline without requiring a running game client, sending input actions, or expanding memory reads.
- [x] **Localization & Diagnostics:** User-visible CLI options, diagnostic messages, and logs are synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).
- [x] **Quality Gate:** Code passes `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).

## Implementation status

`flyff_bot.features.ml` is a fully offline package. `dataset.py` reads the three US-054 Parquet
tables back into typed records and joins them into one supervised sample per *executed* target
decision: a kill cycle is linked to its decision through `target_decision_timestamp_ns`, and the
navigation episode the bot actually ran between those two timestamps supplies the corridor and
trajectory geometry. Candidates the bot did not select never become samples; they only contribute
observed context counts, so no counterfactual reward is invented.

Features and labels stay strictly observational. A quantity the recorded session never measured is
`None`, becomes `NaN` in the model matrix, and is carried into the models as a training-set median
plus an explicit `*__is_missing` indicator column, so an imputed value is always distinguishable
from a measurement. Follow-up windows that reach past the end of a session are treated as
right-censored and stay unknown rather than being recorded as zero kills, and recovery time is
defined only for cycles where a stall was actually observed. Clearance width is not present in the
US-054 schema, so the corridor is described by its length, waypoint count, turn angles, and detour
ratio instead of a fabricated clearance value.

The five heads are regularized linear models fitted on numpy alone: ridge regression for travel,
recovery, kill, and follow-up value, and an L2-penalized logistic classifier for stuck risk. Each is
benchmarked on holdout sessions against a heuristic reference predictor -- a least-squares scaling of
the single measurement the deterministic controller would have used, or the training mean where it
has no such rule. Heads without enough observed labels are reported as untrained instead of being
fitted to noise.

Every head exports to a self-contained ONNX graph (`IsNaN` -> `Where` -> `Cast` -> `Concat` ->
`Gemm` [-> `Sigmoid`]) that accepts the raw `NaN`-carrying feature matrix, so a consumer cannot
disagree with the training-time preparation. `metadata.json` records the dataset digest, session
identifiers, split strategy, feature and label schema, follow-up value definition, expected cost
weights, per-head model and baseline metrics, the checked-out git commit, and the client build
hashes read from the telemetry database.

Enabling change: importing the telemetry package first previously raised a circular `ImportError`
through `navigation` and `automation`. `automation/orchestrator.py` now takes
`CombatVerificationSource` from `telemetry.models` and `TelemetryRecorder` under `TYPE_CHECKING`,
and `telemetry/__init__.py` no longer re-exports `geometry`, which is shared with the navigation
layer it depends on. `python -m flyff_bot.features.ml.train_farming_value` therefore runs with no
game client, no window, no input, and no memory reads.

## Out of scope

- Live ONNX inference inside the active farming loop (handled in US-067).
- Runtime policy execution or replacing `_best_candidate` in live combat (handled in US-067).
- Online Reinforcement Learning, live weight updates, or in-game exploration.
- Multi-step lookahead sequencing over combinatorial monster graphs (handled in US-068).
- Memory write operations (`WriteProcessMemory`) or client code injection.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_farming_value_dataset.py` validating dataset loading, trajectory-corridor correlation, and label extraction.
  - Unit tests in `tests/unit/test_farming_value_models.py` validating model training, evaluation metrics, and expected cost calculations.
  - Unit tests in `tests/unit/test_farming_value_export.py` validating ONNX model export and `metadata.json` integrity.
  - `./scripts/check.ps1` ran clean on 2026-08-21 (`ruff check`, `ruff format --check`,
    `mypy`, `pytest`): 719 passed, 2 skipped, 89.70 % coverage.
- Manual (Windows, outstanding):
  - [ ] Execute `uv run python -m flyff_bot.features.ml.train_farming_value --dataset data/datasets/rl --output models/farming_value/v1` on recorded US-054 telemetry data.
  - [ ] Inspect generated `models/farming_value/v1/` artifacts and verify valid metric output in `metadata.json`.
