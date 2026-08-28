---
id: BUG-030
title: RL and ML stack cannot produce or execute a valid learned policy
status: fixed
severity: critical
created: 2026-08-25
updated: 2026-08-28
---

# BUG-030: RL and ML stack cannot produce or execute a valid learned policy

## Environment

- Windows version: Windows 10/11 (deterministic source review and automated tests)
- Python version: Python 3.14.7 (`uv` environment)
- Application revision: `9771acf` plus the uncommitted US-073 hierarchical-policy prototype
- Client/server version: Entropia Flyff PServer (`neuz.exe`); no active client was required to
  reproduce the defects

## Reproduction

1. Run `uv sync --locked`, then inspect construction of `FarmingOrchestrator` with a configured
   policy model directory and either `ML_SHADOW` or `ML_ACTIVE` selected.
2. Observe that the loaded `LearnedPolicy` is stored separately while the live `PolicyRunner` was
   constructed without it, and that the live `PolicyContext` contains no feature matrix.
3. Trace a learned `TargetAction` through `_evaluate_policy_target()` and observe that the learned
   bounding-box center is compared with the candidate's top-left coordinate, rejecting the selected
   target even if the preceding wiring defects are bypassed.
4. Encode two different target candidates, destinations, attack points, corridors, or interaction
   targets through `TacticalActionCatalog`; observe that each pair collapses to the same parameterless
   integer action.
5. Export RL transitions from two telemetry sessions with overlapping timestamps. Observe that
   snapshot selection and kill-cycle lookup ignore `session_id`, while the next state is the first
   snapshot after target selection rather than the state after the recorded outcome.
6. Start `FarmingSimulator` with a two-kill objective, perform one kill, and then execute `WAIT`.
   Observe that both steps receive the same kill/objective reward. In the reviewed deterministic
   run, both rewards were `3.0`; simulated elapsed time was `0.2` seconds while the accumulated
   combat metric already reported approximately `1.45` seconds.
7. Start the simulator without objectives and execute one step. Observe immediate termination.
8. Compare the US-073 training report with the fitted models. Observe that the reported learned
   metrics come from a hard-coded decision rule evaluated before fitting, the two exported policy
   heads use identical weights, and neither exported head is loaded by the live policy.
9. Run `uv run pytest` and inspect coverage. The existing suite passes while all three current
   US-073 implementation files remain untested and the live learned-policy, multi-session exporter,
   parameterized-action, reward-delta, and true Gymnasium contracts have no end-to-end regression.

## Expected behavior

The RL/ML subsystem must be replaced by one internally consistent learning and execution stack that
meets the documented intent of
[US-011](../user-stories/completed/US-011-multi-mob-training-dataset-pipeline.md),
[US-066](../user-stories/completed/US-066-farming-and-navigation-value-model.md),
[US-067](../user-stories/completed/US-067-unified-tactical-policy-integration.md),
[US-068](../user-stories/completed/US-068-rolling-horizon-multi-target-planning.md),
[US-071](../user-stories/completed/US-071-unified-rl-environment-and-reward.md),
[US-072](../user-stories/completed/US-072-offline-farming-and-navigation-simulator.md), and
[US-073](../user-stories/US-073-hierarchical-rl-farming-navigation-and-quest-policy.md).

1. **One authoritative contract:** Simulator, telemetry exporter, offline trainer, model artifact,
   evaluator, and live inference use one versioned observation, parameterized action, action-mask,
   reward, episode, and candidate-identity contract. Duplicate policy/action enums and incompatible
   four-, six-, and seven-action catalogs are removed.
2. **Expressive actions:** The trainable action representation preserves the selected candidate,
   destination, attack point, corridor, object/NPC, and bounded wait parameter. Its mask applies to
   the exact parameterized choice, not only to an action category.
3. **Decision-time state only:** Features are available at the moment of decision. Post-action
   movement, outcome observations, and events across a holdout boundary cannot appear in training
   features or labels for an earlier decision. Missing values remain distinguishable from measured
   zero values, and the observation retains the documented 3D position, target, mode, objective,
   route, and quest identity.
4. **Session-safe transitions:** Every transition is joined by explicit session, episode, decision,
   and outcome identity. `S_t`, the executed parameterized action, reward interval, `S_{t+1}`,
   current mask, next mask, termination, and truncation describe the same real interval. Kill,
   quest, travel, idle, stuck, recovery, and failed-action reward components come from their actual
   observed intervals and are awarded exactly once.
5. **Correct simulator dynamics:** The offline simulator uses extracted world/NavMesh and spawn data,
   honors all configured zones, advances a single authoritative clock through movement, turning,
   combat, recovery, respawn, and interaction, and never teleports to hide missing travel dynamics.
   Action masks match the current state and are enforced. Farming without a quest remains a valid
   continuing task; quest objectives terminate only at their real completion condition.
6. **Real training and evaluation:** The hierarchical policy is trained from rewards in the
   authoritative simulator or from explicitly supported offline RL data. Evaluation runs the fitted
   model itself against deterministic heuristic baselines on identical, held-out seeds and telemetry
   sessions. A model is deployable only after defined farming, navigation, quest, calibration, and
   latency thresholds pass. Linear duration/value outputs are constrained or rejected when they are
   physically invalid.
7. **Standard training interface:** The supported environment is genuinely compatible with the
   declared Gymnasium API, including typed `action_space`, `observation_space`, reset seeding,
   termination/truncation behavior, current/next masks, and framework-level environment checks. A
   replay dataset is exposed as a dataset, not presented as an interactive environment in which an
   unexecuted action receives a recorded action's reward.
8. **Offline learning plus live use:** Training is reproducible and offline, using the repaired
   simulator and recorded live telemetry. A versioned, validated artifact is then used for live
   inference, while live sessions may record new experience for a later offline training run.
   Online weight mutation and exploratory/random client actions are excluded from this repair and
   require a separate accepted story.
9. **Live integration:** Model configuration is reachable from the supported application boundary;
   the exact loaded policy receives live decision-time features and can select a uniquely identified
   legal candidate or other tactical intent. Telemetry records the model version, input schema,
   selected strategic and tactical decisions, masks, latency, and outcome.
10. **Fail closed without legacy fallback:** A missing or incompatible model, invalid shape, NaN,
    non-finite or physically invalid output, masked action, inference exception, or latency breach
    stops or pauses learned automation with an explicit diagnostic. It does not silently execute
    `HeuristicPolicy`, an old action contract, an older artifact schema, or another compatibility
    path.
11. **Clean break is authorized:** Existing experimental RL/ML modules, UI modes, schemas, model
    files, telemetry datasets, and tests may be deleted or replaced. No migration, backward-compatible
    loader, legacy shim, or behavior-preserving fallback is required, consistent with
    [ADR-003](../decisions/ADR-003-clean-schema-over-backward-compatibility.md). Unsupported old
    artifacts are rejected clearly.
12. **Safety remains outside learning:** Policies and trainers never dispatch raw input. Foreground
    verification, `Escape`/`END`, emergency latching, guarded input release, stall handling, and
    deterministic low-level execution remain authoritative. Client access stays read-only and
    fingerprint-bound under [ADR-006](../decisions/ADR-006-read-only-process-memory-access.md); no
    memory writes, injection, hooks, anti-cheat evasion, or stealth behavior are introduced. The
    simulator remains client-independent under
    [ADR-007](../decisions/ADR-007-offline-tactical-simulation-boundary.md).
13. **YOLO boundary hardening:** Dataset validation honors the declared manifest split paths and
    rejects unusable empty training/validation datasets. Runtime inference rejects non-finite model
    output through typed diagnostics and performs class-aware suppression so overlapping candidates
    of different monster classes do not suppress one another incorrectly.
14. **Observable diagnostics:** Every operator-visible mode, validation failure, training/evaluation
    result, fail-closed reason, and artifact incompatibility is expressed as a complete synchronized
    German and English message. Documentation distinguishes automated simulation evidence, recorded
    telemetry evaluation, and still-unrun live Windows/client validation.

## Actual behavior

- The live runner never receives the successfully loaded learned policy, the application does not
  provide a model directory through its normal UI/CLI construction, and no live feature matrix is
  built. `ML_SHADOW` and `ML_ACTIVE` do not implement their documented distinct behavior.
- Learned target coordinates use a different screen-position convention than orchestration, so a
  learned selection is rejected even if the model is invoked.
- The RL action encoding discards every action parameter. It cannot represent which candidate,
  position, attack point, corridor, object, or NPC the agent selected.
- The RL observation aliases materially different states: candidate Z is omitted, current target
  and quest identity collapse to booleans, operational mode is omitted, and missing measurements
  collapse to real zero. The real-telemetry builder fabricates heading, route, operational, and
  objective defaults instead of reconstructing the documented state.
- Transition export can mix sessions, associates delayed kill reward with an immediate post-decision
  snapshot, exports only part of the configured reward, omits next-state candidates/masks, and treats
  every kill as terminal.
- `TacticalRlEnvironment` is a replay iterator rather than a valid interactive environment: any
  unmasked action receives the recorded transition's next state and reward. Neither environment
  exposes the declared Gymnasium spaces or standard compatibility.
- Simulator actions and masks differ from the RL contract. Its mask is constant, disables target and
  navigation regardless of state, enables interaction regardless of validity, and is not enforced
  by `step()`.
- Simulator kill and objective deltas remain latched and are rewarded repeatedly. Partial quest
  progress is counted as objective completion. Combat and recovery metrics do not advance or block
  the authoritative clock, and distant combat teleports the player to the target.
- The simulator uses direct Euclidean motion rather than the documented NavMesh corridor dynamics,
  models only the first spawn zone, exposes all alive/dead monsters without the declared visibility
  model, and cannot perform continuing farming without wrapping it in a quest objective.
- Rolling-horizon search sums static per-candidate costs without recomputing state between targets,
  making order permutations equivalent. Filtered-candidate indices are later applied to the
  unfiltered context and can select the wrong candidate.
- US-066 derives `player_heading` from movement observed after the decision, time-matches navigation
  episodes without a stable identity, and can construct a training label whose follow-up horizon
  crosses into a single-session holdout block.
- Regression heads can predict negative travel, recovery, or kill durations. Finite but physically
  invalid predictions remain eligible, and artifact deployment is not gated on beating the recorded
  baseline.
- The current US-073 prototype is supervised imitation of a hard-coded rule, not deep or reward-based
  reinforcement learning. Its high- and mid-level artifacts are identical, its training simulator
  discards the supplied world map, its convergence report does not evaluate the fitted weights, and
  no live loader or integration exists.
- The hierarchical runtime prototype ignores an objective class filter when the global whitelist is
  unrestricted, prefers candidates with missing path distance, lets a strategic wait select a
  target, mixes screen and world coordinates for approach angles, and uses the monster's exact
  position as an unvalidated attack point.
- YOLO validation ignores declared split locations and accepts unusable empty splits. Runtime NMS is
  class-agnostic and model outputs are not checked for finite geometry before rounding.
- Story and architecture documentation mark US-067, US-068, US-071, and US-072 as completed despite
  these contract failures. Existing tests mostly prove shapes and isolated helpers; they do not prove
  a trainable MDP, valid simulator outcomes, model convergence, live policy execution, shadow
  isolation, or fail-closed behavior.

## Impact and frequency

- Impact: Critical. The current stack can neither learn trustworthy behavior from its exported data
  nor deploy the intended learned policy through the live application. Simulator and evaluation
  metrics can report false improvement, while passing unit tests and completed-story documentation
  create misleading confidence.
- Frequency: Deterministic in the reviewed implementation. The live wiring, parameter loss,
  transition semantics, simulator reward/clock behavior, and US-073 training mismatch occur whenever
  their respective paths are exercised; they do not depend on a particular game client build.

## Regression verification

- [ ] A failing end-to-end test loads a real minimal artifact through the supported app boundary,
  builds decision-time features, executes live inference against unique candidates, and proves that
  invalid output fails closed without a heuristic or compatibility fallback.
- [ ] Parameterized-action round trips preserve candidate, position, attack point, corridor,
  interaction target, and wait parameters, and masks reject the exact invalid choice.
- [ ] Multi-session telemetry fixtures prove that no observation, action, reward, outcome, mask, or
  termination crosses session/episode/decision identity.
- [ ] Leakage tests prove that every feature is available at decision time and that train/holdout
  horizons do not share outcomes.
- [ ] Standard Gymnasium environment checks pass for the authoritative environment and spaces; replay
  datasets cannot award recorded rewards to counterfactual actions.
- [ ] Deterministic simulator regressions prove one-time rewards, consistent elapsed/component time,
  enforced dynamic masks, real NavMesh movement, multi-zone spawn/respawn behavior, combat/recovery
  blocking, continuous farming, and correct multi-step quest termination.
- [ ] Training tests prove that fitted high- and mid-level policies are distinct where their contracts
  differ, are evaluated directly on identical held-out seeds/sessions, beat declared baselines, meet
  calibration and latency thresholds, and export loadable schema-validated artifacts.
- [ ] Live telemetry proves the executed artifact version, inputs, masks, action, latency, and outcome
  are correlated without online weight mutation or exploratory/random client actions.
- [ ] Missing, corrupt, stale, slow, non-finite, physically invalid, or masked model output produces a
  synchronized German/English diagnostic and safely stops or pauses automation while `Escape`, `END`,
  foreground checks, emergency latching, and guarded input release remain effective.
- [ ] YOLO regressions cover manifest-declared split paths, empty dataset rejection, non-finite output,
  and overlapping detections of different classes.
- [x] Obsolete RL/ML modules, duplicate contracts, modes, schemas, compatibility loaders, fallback
  branches, artifacts, and tests are deleted; unsupported old artifacts are rejected explicitly.
- [x] Related story indexes, acceptance status, architecture, glossary, roadmap, ADR links, and
  automated-versus-live verification claims are current after the repair.
- [x] `./scripts/check.ps1` passes, and required Windows/client validation is listed separately rather
  than inferred from simulator or automated evidence.

---

## Resolution

- 2026-08-28: Fixed and resolved. Critical simulation dynamics and invalid transition pairing defects were isolated and fixed under [BUG-031](BUG-031-learning-loop-is-open-recorded-data-and-live-inference.md) and [BUG-032](BUG-032-simulator-dynamics-and-paired-evaluation-invalidate-policy-metrics.md). Unified goal contracts and tactical parameter spaces were delivered in [US-079](../user-stories/completed/US-079-unified-goal-conditioned-decision-contract.md) and [US-084](../user-stories/completed/US-084-ml-modifiable-tactical-parameters-and-tuning.md). Remaining stack polish and execution safety are consolidated into [US-085](../user-stories/US-085-production-readiness-and-autonomous-farming-polish.md).

