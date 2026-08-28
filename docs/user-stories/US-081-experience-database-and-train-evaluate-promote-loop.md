---
id: US-081
title: Experience database and a reproducible train, evaluate, promote and deploy loop
status: draft
created: 2026-08-25
updated: 2026-08-25
---

# US-081: Experience database and a reproducible train, evaluate, promote and deploy loop

## Story

As an **operator**, I want **every farming and quest session to add usable experience to a local
SQLite database, and one command to train a candidate policy from it, evaluate it against the
current one and promote it only when it measurably wins**, so that **the bot gets better at farming
and completing quests the longer I run it, without me hand-tuning anything and without an unproven
model ever driving the client**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- The recording half exists: `JsonlTelemetryWorker` and `SqliteTelemetryStore`
  (`features/telemetry/storage.py`) already persist session headers, world snapshots, target
  decisions, navigation episodes, combat episodes, kill cycles and stall events into
  `data/telemetry.sqlite3` with per-session indexes.
- The consuming half is not reachable from the product:
  - `TelemetryTransitionExporter`, `train_hierarchical_policy` and `FarmingSimulator` are referenced
    only by unit tests. No `flyff-bot` subcommand exists for export, training, evaluation or
    promotion.
  - `flyff_bot.features.ml.train_farming_value` has a `main()` and a `__main__` guard but is not
    registered in `[project.scripts]` in `pyproject.toml`.
  - `FarmingConfig.policy_model_directory` (`features/automation/orchestrator.py:213`) has no
    writer, so a trained artifact cannot be selected. See
    [BUG-031](../bugs/BUG-031-learning-loop-is-open-recorded-data-and-live-inference.md).
  - `train_farming_value_models` exports every fitted head regardless of whether it beat its
    heuristic baseline (`features/ml/pipeline.py:202`), and `train_hierarchical_policy` gates only on
    two in-sample simulator metrics (see
    [BUG-032](../bugs/fixed/BUG-032-simulator-dynamics-and-paired-evaluation-invalidate-policy-metrics.md)).
- Depends on [US-079](completed/US-079-unified-goal-conditioned-decision-contract.md) for the contract and on
  [US-080](US-080-goal-driven-quest-execution-and-objective-bus.md) for goal-labelled experience.
- Learning stays offline. Live sessions record experience; weights are never mutated in-process and
  no exploratory or random action is ever dispatched to the client. This preserves
  [ADR-007](../decisions/ADR-007-offline-tactical-simulation-boundary.md) and the project safety
  boundaries.
- Assumption to confirm: the volume of experience one operator produces is enough for the model
  family in use. The pipeline must report the realized sample and session counts and refuse to
  promote below a documented floor rather than fitting noise.

## Acceptance criteria

- [ ] Given a completed live session, when it ends, then the SQLite database contains a complete,
      session-scoped, goal-labelled decision record set from which transitions can be reconstructed
      without ambiguity, including the executed parameterized action, the mask that was in force,
      the reward interval boundaries and the outcome.
- [ ] Given a database with several sessions, when transitions are exported, then no transition
      joins data across `session_id` or episode boundaries, and the export reports how many
      decisions were skipped and why.
- [ ] Given the exported experience, when `flyff-bot rl-export`, `flyff-bot policy-train` and
      `flyff-bot policy-evaluate` are run, then each is reachable from the supported CLI, is fully
      offline, opens no window, sends no input and reads no process memory.
- [ ] Given two runs of `flyff-bot policy-train` with the same inputs and seed, when both complete,
      then they produce byte-identical artifacts and an identical report.
- [ ] Given a trained candidate, when it is evaluated, then it is scored on held-out seeds and
      held-out recorded sessions that are provably disjoint from every seed and session used for
      training, against both the deterministic heuristic baseline and the currently promoted model.
- [ ] Given an evaluation report, when promotion is requested, then the candidate is promoted only
      if it meets documented thresholds for farming throughput, quest completion, navigation cost,
      calibration drift and inference latency; otherwise promotion is refused with the failing
      threshold named.
- [ ] Given a promoted artifact, when the application starts, then the model directory is selectable
      from the supported UI and CLI, the selected artifact version is displayed, and the same version
      is written into the session header of every session it drives.
- [ ] Given a promoted artifact and `ML_SHADOW`, when a session runs, then learned decisions and
      their latency are recorded but never dispatched, and a report compares the learned choice with
      the executed heuristic choice.
- [ ] Given a promoted artifact and `ML_ACTIVE`, when a session runs, then the learned decision is
      executed through the existing guarded execution boundary; the policy never dispatches input
      itself.
- [ ] Given a model that is missing, schema-incompatible, produces non-finite or physically invalid
      output, selects a masked action or breaches the latency budget, when that occurs, then learned
      automation stops or pauses with a synchronized German and English diagnostic and does not
      silently continue on the heuristic path.
- [ ] Given a long-running operator, when several train, evaluate and promote cycles have run, then a
      model registry records for each artifact its version, training data range, session ids, seeds,
      contract version, evaluation metrics, promotion decision and the git commit that produced it.
- [ ] All user-visible text of the new commands, reports, refusals and UI controls is available in
      German and English and the two locale files stay in sync.

## Out of scope

- Online or on-policy learning against the live client, exploratory action selection, and any
  in-process weight mutation.
- Introducing a deep-learning runtime dependency. If the evaluation shows the current linear and
  tabular model family cannot meet the thresholds, that finding is recorded as a decision in
  `docs/decisions/` and handled by a separate accepted story.
- Uploading experience or artifacts anywhere off the machine.

## Verification

- Automated: a multi-session fixture proving session-safe export and reporting skipped decisions;
  determinism test on repeated training runs; a leakage test proving train, evaluation and
  calibration seed and session sets are disjoint; a promotion-gate test proving a candidate that
  loses to the baseline is refused with the failing threshold named; an end-to-end test that trains a
  minimal artifact, promotes it, loads it through the supported application boundary and executes one
  learned decision; fail-closed tests for missing, corrupt, non-finite, masked and late results;
  a registry round-trip test; locale sync test; `./scripts/check.ps1`.
- Manual (Windows): record two live sessions, run export, train, evaluate and promote, then run one
  shadow session and one active session against the live client and confirm the displayed artifact
  version, the recorded decisions and the fail-closed behavior when the model directory is removed
  mid-session.
