---
id: BUG-031
title: The learning loop is open - recorded data is untrainable and no trained policy can act live
status: reported
severity: critical
created: 2026-08-25
updated: 2026-08-25
---

# BUG-031: The learning loop is open - recorded data is untrainable and no trained policy can act live

Narrow, individually verified successor to the broad audit in
[BUG-030](BUG-030-rl-ml-stack-invalid-training-and-live-execution.md). Every defect below was
re-confirmed against the current worktree revision, so BUG-030 items that have since been repaired
(the `PolicyRunner` now receives the loaded policy; hierarchical training now fits and evaluates the
exported weights) are deliberately not repeated here.

## Environment

- Windows version: Windows 11 Pro 10.0.26200 (deterministic source review; no client required)
- Python version: Python 3.14.7 (`uv` environment, `.python-version`)
- Application revision: `849b067` (branch `claude/ml-rl-farming-optimization-3a106b`)
- Client/server version: Entropia Flyff PServer (`neuz.exe`) - not needed to reproduce

## Reproduction

### A. The exported training data carries no decision signal

1. Record or synthesize two farming sessions into `data/telemetry.sqlite3`.
2. Call `TelemetryTransitionExporter(store).transitions()`
   (`src/flyff_bot/features/rl/exporter.py:64`).
3. Inspect the exported rows:
   - Every `action` value is `0`. `exporter.py:108` builds `TargetAction(index, None)` and
     `TacticalActionCatalog.encode` (`src/flyff_bot/features/rl/actions.py:44`) maps any
     `TargetAction` to `SELECT_TARGET`, discarding which candidate was chosen.
   - `next_observation` is built by `ObservationSpace.from_telemetry_snapshot(next_snapshot)`
     without candidates (`exporter.py:92`), so all 28 candidate columns of the next state are zero.
   - `reward` only ever contains `verified_kill` and `travel_seconds` (`exporter.py:95-97`);
     `quest_progress_delta`, `objective_completed`, `idle_seconds`, `stuck_seconds`,
     `recovery_seconds` and `failed_action` of `RewardConfig` are never populated.
   - `terminated` equals `verified_kill`, so every kill ends the episode.
4. `tests/unit/test_rl_exporter.py:69` asserts `row["action"] == 0` - the defect is pinned by the
   test suite instead of being caught by it.

### B. Transitions are joined across sessions

1. Persist two sessions whose `timestamp_ns` ranges overlap.
2. `exporter.py:65-67` reads `WORLD_SNAPSHOT` and `TARGET_SELECTED` for all sessions, and
   `previous_snapshot` / `next_snapshot` are selected purely by timestamp comparison.
3. Observe a state from session A paired with a next state from session B. The `kill_cycles`
   dictionary (`exporter.py:67`) is likewise keyed only on `target_decision_timestamp_ns`.

### C. The live learned policy is structurally unreachable

1. Search the repository for a writer of `FarmingConfig.policy_model_directory`
   (`src/flyff_bot/features/automation/orchestrator.py:213`). Only the declaration and the reader
   exist - no CLI flag, no UI control, no settings file sets it. Selecting `ML_ACTIVE` in the
   dashboard therefore never loads any artifact.
2. Even with a directory injected, `_evaluate_policy_target`
   (`orchestrator.py:586`) builds `PolicyContext(candidates, allowed, locked_out)` and leaves
   `feature_matrix` at `None`.
3. `LearnedPolicy.evaluate` (`src/flyff_bot/features/policy/learned.py:99`) returns `None`
   whenever the matrix is `None`, so `PolicyRunner` records `no_valid_action` and silently executes
   `HeuristicPolicy`. `ML_ACTIVE` and `ML_SHADOW` are observationally identical to `HEURISTIC`.

### D. A learned target can never be matched back to a candidate

1. Bypass C and let `LearnedPolicy` return a `TargetAction`.
2. `LearnedPolicy._action` (`learned.py:162`) sets `target_pos` to the bounding-box centre
   (`mob.x + mob.width // 2`), while `orchestrator.py:596-597` compares it against
   `Position(candidate.mob.x, candidate.mob.y)` - the top-left corner. The equality never holds.
3. The same loop matches on `action.target_id`, which both `LearnedPolicy._action` and
   `MidLevelTacticalPolicy.evaluate_for_goal` (`policy/hierarchical.py:270`) fill with
   `mob.class_id`. With two Aibatt on screen the identifier is ambiguous by construction, and
   `MidLevelTacticalPolicy` resolves the attack point by the same class id (`hierarchical.py:266`).

### E. The hierarchical ONNX policy is served a fabricated observation

1. Train an artifact with `train_hierarchical_policy` and load it through `HierarchicalOnnxPolicy`.
2. `_observation` (`src/flyff_bot/features/policy/hierarchical_onnx.py:240`) constructs
   `PlayerKinematics(0.0, 0.0, 0.0, 0.0)` and `NavMeshContext(None, None, None)` even though live
   XYZ, heading and route distance are available from the pathing stack.
3. The policy was trained on simulator observations that carry real position, heading, velocity and
   route distance. Position and NavMesh columns are therefore constant zero at inference time and
   non-zero during training.
4. `HierarchicalOnnxPolicy` is constructed in `orchestrator.py:331` without an `objective`, so it
   always evaluates the default `HierarchicalObjective()` (farming). The active
   `QuestResolution` / `QuestFarmingQueue` never reaches the policy.

### F. Missing and measured-zero are indistinguishable in the RL observation

1. Encode a candidate with `position_x = None` and another with `position_x = -500.0`.
2. `_optional_unit` (`src/flyff_bot/features/rl/models.py:240`) returns `0.0` for `None` and clamps
   negatives to `0.0`, so both encode identically. `_position` uses the same helper for the
   player's own coordinates.
3. The supervised value-model stack solves exactly this problem with explicit `NaN` plus paired
   `__is_missing` indicator columns (`src/flyff_bot/features/ml/features.py:141`,
   `src/flyff_bot/features/ml/models.py:67`). The two subsystems disagree.

## Expected behavior

The intended loop is: farm live, record experience, train offline, evaluate, promote, farm better.
Concretely:

1. An exported transition preserves which parameterized decision was taken (candidate identity,
   destination, attack point, corridor, interaction target, wait duration) and its mask.
2. State, action, reward interval, next state, current mask, next mask, termination and truncation
   all belong to one real interval of one session and one episode.
3. Every configured reward component is populated from its observed interval and awarded once.
4. An operator can point the application at a model directory through the supported UI or CLI, and
   `ML_SHADOW` logs learned decisions without acting while `ML_ACTIVE` executes them.
5. The live policy receives the same decision-time features the model was trained on, and a
   selected candidate is identified by a stable per-instance identity, not a class id or a
   coordinate convention.
6. A missing measurement stays distinguishable from a measured zero in every observation encoder.
7. A model that cannot be served correctly fails closed with a synchronized German and English
   diagnostic instead of silently degrading to `HeuristicPolicy`.

## Actual behavior

- The exported dataset contains one constant action, a partially zeroed next state, an incomplete
  reward and a termination flag on every kill. No algorithm can extract a policy from it.
- Transitions can join observations, rewards and outcomes from different sessions.
- No supported application path can load a learned artifact; `ML_ACTIVE` is heuristic behavior
  under a different label.
- The learned target-selection result is rejected by a coordinate-convention mismatch and is
  addressed by an ambiguous class-level identifier.
- The hierarchical policy is served zeroed kinematics and NavMesh context, and never sees the
  active quest objective.
- Absent and zero measurements alias in the RL observation while the value-model stack keeps them
  separate.

## Impact and frequency

- Impact: Critical. The self-optimizing farming and quest loop the project is built toward cannot
  close. Recorded SQLite experience is unusable for training and a trained artifact cannot act.
- Frequency: Deterministic. Every export, every `ML_ACTIVE` session, every hierarchical inference.

## Regression verification

- [ ] A multi-session telemetry fixture proves no observation, action, reward, mask, termination or
      outcome crosses a `session_id`, episode or decision boundary.
- [ ] A round-trip test proves the exported action preserves candidate, destination, attack point,
      corridor, interaction target and wait parameters, and that the mask rejects the exact
      parameterized choice.
- [ ] A reward test proves every configured component is populated from its own observed interval
      and awarded exactly once per interval.
- [ ] An end-to-end test loads a real minimal artifact through the supported application boundary,
      builds decision-time features, and executes a learned selection against two same-class
      candidates, choosing the intended instance.
- [ ] `ML_SHADOW` records a learned decision without dispatching input; `ML_ACTIVE` dispatches it.
      The two modes are proven distinct.
- [ ] A train/serve parity test asserts that the live observation encoder and the training
      observation encoder produce equal vectors for the same state.
- [ ] Encoding a missing value and a measured zero produces different vectors.
- [ ] A missing, incompatible, non-finite, masked or late model result stops or pauses learned
      automation with a synchronized German and English diagnostic and never falls back to
      `HeuristicPolicy` silently.
- [ ] `./scripts/check.ps1` passes; Windows and live-client validation is listed separately.
