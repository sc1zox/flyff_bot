---
id: BUG-032
title: Simulator dynamics and paired evaluation invalidate every learned-policy metric
status: resolved
severity: critical
created: 2026-08-25
updated: 2026-08-25
---

# BUG-032: Simulator dynamics and paired evaluation invalidate every learned-policy metric

The offline simulator is the only reward source the hierarchical policy is trained against
([US-072](../user-stories/completed/US-072-offline-farming-and-navigation-simulator.md),
[US-073](../user-stories/completed/US-073-hierarchical-rl-farming-navigation-and-quest-policy.md),
[ADR-007](../decisions/ADR-007-offline-tactical-simulation-boundary.md)). Its dynamics reward
behavior that is impossible in the client, so the exported convergence numbers describe the
simulator defects rather than farming skill. This is the training-side counterpart of
[BUG-031](BUG-031-learning-loop-is-open-recorded-data-and-live-inference.md).

## Environment

- Windows version: Windows 11 Pro 10.0.26200 (deterministic source review; no client required)
- Python version: Python 3.14.7 (`uv` environment)
- Application revision: `849b067` (branch `claude/ml-rl-farming-optimization-3a106b`)
- Client/server version: Entropia Flyff PServer (`neuz.exe`) - not needed to reproduce

## Reproduction

### A. Combat teleports the player and costs no wall-clock time

1. Build a `FarmingSimulator` whose nearest monster is more than
   `MAXIMUM_COMBAT_ENGAGE_DISTANCE_UNITS` (10.0) away.
2. Execute `TARGET_NEAREST` and then `INTERACT` on a `KILL` objective.
3. `_attack_target` (`src/flyff_bot/features/simulator/engine.py:375-377`) assigns
   `self._x = target.position_x` and `self._z = target.position_z`. The player is relocated over
   any distance with zero travel time and zero recorded distance.
4. The sampled combat duration is added to `self._combat_seconds` only
   (`engine.py:385`). `self._elapsed_seconds` advances by `tick_seconds` per step and by nothing
   else (`engine.py:182`), so a kill costs 0.5 simulated seconds regardless of time to kill.
5. `HierarchicalEpisodeMetrics.kills_per_minute` divides by that clock
   (`src/flyff_bot/features/policy/hierarchical_training_simulator.py:31`), producing values that
   cannot occur in the client.

### B. The interaction mask is always open on a kill objective

1. Configure a single `KILL` objective and step the simulator.
2. `_objective_ready` (`engine.py:487-497`) returns `bool(self._monsters)` whenever no live target is
   held. `self._monsters` also contains dead monsters (`_advance_spawns`, `engine.py:357`), so it is
   never empty and `INTERACT` is permanently unmasked.
3. Combined with A, the reward-maximizing policy is "press `INTERACT` every tick", which the
   tabular Q-learner in `_train_masked_q_policy`
   (`src/flyff_bot/features/policy/hierarchical_training.py:186`) duly discovers.

### C. Only the first spawn zone is ever simulated

1. Load a `WorldVectorMap` with several extracted spawn zones.
2. `_reset_state` (`engine.py:338`) iterates `self._zones[:DEFAULT_SPAWN_ZONE_COUNT]` with
   `DEFAULT_SPAWN_ZONE_COUNT = 1` (`engine.py:37`). Every other camp is invisible to training,
   contradicting the multi-zone selection delivered by US-059 and the quest resolver, which
   resolves one zone per quest target (`src/flyff_bot/features/quests/goals.py:257`).

### D. Continuous farming cannot be simulated

1. Construct `FarmingSimulator(world_map, start=..., objectives=())`.
2. `_all_objectives_complete` (`engine.py:518`) evaluates `all([])`, which is `True`.
3. The first `step()` returns `terminated=True`. Farming without a quest - the primary use case -
   has no representable episode.

### E. Movement ignores terrain, NavMesh and obstacles

1. Place an impassable slope between the start position and a spawn zone.
2. `_advance_along` (`engine.py:401`) moves along the straight-line bearing and only samples a
   scalar stuck probability per travelled unit. The extracted NavMesh corridors used by
   `src/flyff_bot/features/navigation/pathing.py` are never consulted; `_height_at` is used for
   observation only.
3. A policy trained here learns straight-line travel costs that the live navigator cannot realize.

### F. Recovery is bookkeeping only

1. Trigger a stuck event during `GO_TO_OBJECTIVE`.
2. `_advance_recovery` (`engine.py:398`) decrements `self._recovery_seconds` by `tick_seconds` but
   never blocks movement, combat or interaction, and never appears in the reward.

### G. Evaluation seeds were seen during training

1. Run `train_hierarchical_policy(..., episode_count=8)`.
2. `_train_masked_q_policy` resets with `seed=RANDOM_SEED + rollout_index` for
   `rollout_index` in `range(episode_count * Q_LEARNING_ROLLOUTS_PER_EPISODE)` = `range(256)`
   (`hierarchical_training.py:192`), covering seeds `73073..73328`.
3. `_evaluate_paired` uses `first_seed = RANDOM_SEED + episode_count` = `73081`
   (`hierarchical_training.py:102`, `:244`). The "held-out" evaluation seeds are inside the
   training range. The reported convergence is in-sample.

### H. The two exported heads are one head

1. Inspect the behavior-cloning labels: `mid_actions.append(MID_LEVEL_LABEL_BY_SIMULATOR_ACTION[action])`
   (`hierarchical_training.py:93`) is a fixed bijection of the high-level action.
2. The mid-level head therefore learns a deterministic relabeling of the high-level head, and its
   `attack_point` and `corridor` classes are fitted against all-zero targets because no simulator
   action ever maps to them. `HierarchicalOnnxPolicy._mid_mask`
   (`src/flyff_bot/features/policy/hierarchical_onnx.py:161`) nevertheless enables those classes
   live, so an untrained constant logit can win the argmax.

### I. Two reward definitions and three observation builders coexist

1. `RewardEngine` / `RewardConfig` (`src/flyff_bot/features/rl/rewards.py`, version `us071-v1`) is
   used only by the telemetry exporter.
2. `FarmingSimulator._reward` (`engine.py:540`) hard-codes its own unnamed weights
   (`2.0`, `0.25`, `0.01`) and never consults `RewardConfig`.
3. `KillCycle.reward` (`src/flyff_bot/features/telemetry/models.py:205`) is a third recorded reward.
4. Likewise `ObservationSpace.from_telemetry_snapshot`, `FarmingSimulator.observation` and
   `hierarchical_onnx._observation` each build the same 52-dimensional vector from different
   sources with different defaults.
5. `validate_calibration` (`src/flyff_bot/features/simulator/calibration.py:24`) exists but no
   training or export path calls it, so simulated dynamics are never checked against recorded
   telemetry.

## Expected behavior

- One authoritative simulated clock advances through turning, travelling, combat, recovery,
  interaction and respawn. No action relocates the player without paying its travel cost.
- Action masks reflect the actual state and are enforced by `step()`.
- All configured spawn zones and their respawn timers participate, with an explicit visibility
  model instead of exposing dead monsters as candidates.
- Farming without a quest is a valid continuing task; a quest terminates only at its real
  completion condition.
- Travel follows extracted NavMesh corridors and terrain passability.
- Training, evaluation and any calibration use disjoint seed ranges, and evaluation is compared
  against a deterministic baseline on identical held-out seeds.
- Distinct policy heads are trained on distinct targets, and no live-enabled action class is left
  untrained.
- One versioned reward configuration and one observation encoder serve simulator, exporter and live
  inference.
- Simulated aggregates are validated against recorded telemetry via `validate_calibration` before an
  artifact is eligible for promotion.

## Actual behavior

Combat teleports over arbitrary distances and consumes no episode time; `INTERACT` is permanently
legal on kill objectives; only the first spawn zone spawns; a session without objectives terminates
immediately; travel is straight-line; recovery never blocks anything; evaluation seeds are inside
the training range; the mid-level head is a relabeling of the high-level head with two untrained but
live-enabled classes; and three reward definitions plus three observation builders disagree while
the calibration check is never executed.

## Impact and frequency

- Impact: Critical. `learned_kills_per_minute` and `learned_objectives_per_minute` in
  `hierarchical-metadata.json` are not evidence of farming quality, yet they are the only gate the
  training run applies before writing an artifact. Any downstream promotion decision built on them
  is unsound.
- Frequency: Deterministic in every simulator episode and every training run.

## Resolution

`FarmingSimulator` was rebuilt around one budgeted clock. Each tick partitions
`tick_seconds` into recovery, travel (turning included), combat, and idle, and only
`_travel_toward` moves the player. Combat became a multi-tick engagement over the sampled
duration, so a distant monster must be walked to before it can be fought. `step()` now
rejects any masked action with `IllegalSimulatorAction`, a pending stall recovery leaves
only `WAIT` legal, all extracted zones populate and respawn, candidate visibility is an
explicit radius over live monsters, an objective-free episode is a continuing task, and
travel follows a `VectorRoutePlanner` corridor over the extracted obstacle geometry.

`hierarchical_training` draws training, evaluation, and calibration seeds from three
disjoint blocks (`seed_ranges`), labels the mid-level head from the tactical state instead
of relabeling the strategic action, records the trained action classes per head so
`HierarchicalOnnxPolicy` cannot pick an untrained class live, and runs `validate_calibration`
over held-out heuristic rollouts before it writes an artifact.

Reward definitions were unified on the versioned `RewardConfig` / `RewardEngine`: the
simulator, the telemetry exporter, and `TelemetryRecorder`'s recorded `KillCycle.reward` now
all use it, and the duplicate `features/rl/state_space.py` encoder module was deleted.

Item I also listed `ObservationSpace.from_telemetry_snapshot`, `FarmingSimulator.observation`,
and `hierarchical_onnx._observation` as three observation builders. These are three adapters
from three different data sources into the one typed `RlObservation`, which
`ObservationSpace.encode` remains the single encoder for; they are not duplicates and were
kept.

## Regression verification

- [x] A deterministic test proves that engaging a distant monster costs travel time and distance and
      that the player position changes only through the routed travel step
      (`tests/unit/test_simulator_dynamics.py`, `test_engaging_a_distant_monster_costs_travel_time_and_distance`,
      `test_the_player_only_moves_by_travelling`).
- [x] Elapsed time equals the sum of travel, combat, recovery and idle time within tolerance
      (`test_elapsed_time_equals_the_sum_of_the_activity_buckets`).
- [x] Masked actions are rejected by `step()`, and the interaction mask closes when no interaction
      is legal (`test_step_rejects_masked_actions_and_closes_an_illegal_interaction`,
      `test_recovery_blocks_every_action_but_waiting`).
- [x] A multi-zone map spawns and respawns in every configured zone; dead monsters are not exposed
      as selectable candidates (`test_every_configured_zone_spawns_and_respawns`,
      `test_dead_monsters_are_not_offered_as_candidates`).
- [x] An objective-free episode runs to `truncated` and produces kills
      (`test_an_objective_free_episode_runs_to_truncation_and_kills`).
- [x] A route blocked by impassable terrain forces a corridor detour rather than straight-line
      travel (`test_an_impassable_wall_forces_a_corridor_detour`).
- [x] Training, evaluation and calibration seed ranges are proven disjoint
      (`tests/unit/test_hierarchical_training.py`,
      `test_training_evaluation_and_calibration_seeds_are_disjoint`).
- [x] Fitted heads are proven distinct where their contracts differ, and no live-enabled action
      class is exported untrained (`test_the_two_heads_are_fitted_on_different_targets`,
      `test_an_untrained_action_class_is_never_selected_live`).
- [x] One versioned reward configuration and one observation encoder are the only ones referenced by
      simulator, exporter and live policy; duplicates are deleted
      (`test_the_simulator_scores_ticks_with_the_shared_reward_configuration`,
      `test_the_exported_metadata_names_one_versioned_reward_configuration`;
      `features/rl/state_space.py` removed).
- [x] `validate_calibration` runs inside the training pipeline and blocks artifact export on drift
      (`test_calibration_drift_blocks_the_artifact_export`).
- [x] `./scripts/check.ps1` passes; Windows and live-client validation is listed separately.
      `uv sync --locked`, `ruff check`, `ruff format --check`, and `mypy` are clean; `pytest`
      reports 898 passed, 6 skipped, 88% coverage. `tests/unit/test_attack_point_scoring.py::test_sampling_and_scoring_complete_within_one_millisecond`
      is a pre-existing wall-clock flake unrelated to this fix: it fails intermittently on the
      unmodified tree as well. Simulated dynamics are still offline evidence only; live-client
      behavior on Windows remains unverified.
