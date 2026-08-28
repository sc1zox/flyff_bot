---
id: US-082
title: ML and RL engineering quality gate
status: completed
created: 2026-08-25
updated: 2026-08-28
---

# US-082: ML and RL engineering quality gate

## Story

As a **maintainer**, I want **the machine-learning and reinforcement-learning modules held to the
same verification and code standards as the rest of the repository**, so that **a defect in the
learning stack is caught by the gate instead of being pinned in place by a test that asserts the
defective behavior**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Findings from the current review that this story addresses:
  - `tests/unit/test_rl_exporter.py:69` asserts `row["action"] == 0`, encoding the parameter-loss
    defect of [BUG-031](../bugs/BUG-031-learning-loop-is-open-recorded-data-and-live-inference.md)
    as expected behavior.
  - `tests/unit/test_hierarchical_training.py:69` measures inference latency through
    `PolicyRunner`, which silently substitutes `HeuristicPolicy` on any fault. The test passes even
    if the ONNX policy never produces a decision.
  - `.claude/rules/testing-standards.md` requires component-level tests in `tests/integration/`.
    That directory does not exist; all 97 test files are unit tests. There is no test that exercises
    record, export, train, load and act as one pipeline.
  - `pyproject.toml` enforces `--cov-fail-under=60` repository-wide. No per-module floor protects
    the learning stack, and no test covers `features/rl/exporter.py` beyond a single happy path.
  - Three different definitions share the name `TacticalAction`
    (`features/rl/actions.py:17`, `features/simulator/engine.py:41`, `features/policy/models.py:68`),
    and `hierarchical_training.py` imports one of the enums while operating on the vocabulary of
    another.
  - `FarmingSimulator._reward` (`features/simulator/engine.py:540`) uses the unexplained literals
    `2.0`, `0.25` and `0.01` for business rules, against the repository rule on named constants.
  - `FarmingSimulator._advance_toward_target` (`features/simulator/engine.py:441`) is dead code.
  - Production code contains 42 bare `assert` statements, including in the read-only memory readers
    (`features/navigation/live_camera.py:405`, `features/dungeons/live_reader.py:144`) and in
    `features/simulator/engine.py:499`. Assertions are removed under `-O` and are not a fail-fast
    guard for invalid state.
  - `validate_calibration` (`features/simulator/calibration.py:24`) is implemented and tested but
    never called by any production path.
- [ADR-003](../decisions/ADR-003-clean-schema-over-backward-compatibility.md) authorizes deleting
  superseded modules and tests outright.
- This story is verification and hygiene only. Behavioral repairs belong to
  [US-079](completed/US-079-unified-goal-conditioned-decision-contract.md),
  [US-080](US-080-goal-driven-quest-execution-and-objective-bus.md),
  [US-081](US-081-experience-database-and-train-evaluate-promote-loop.md), BUG-031 and BUG-032.

## Acceptance criteria

- [ ] Given the test suite, when it is inspected, then no test asserts a defect described in BUG-031
      or BUG-032 as expected behavior; each such assertion is replaced by one that states the
      required behavior.
- [ ] Given a latency or behavior test of a learned policy, when it runs, then it exercises the
      policy directly and separately asserts that the fallback path was not taken.
- [ ] Given the repository, when tests are collected, then `tests/integration/` exists and contains
      at least one test that runs record, export, train, load and act as one pipeline against a
      fixture database, without a client, a window or dispatched input.
- [ ] Given the coverage gate, when it runs, then `features/ml`, `features/rl`, `features/policy` and
      `features/simulator` each meet a documented per-module coverage floor above the repository
      floor, and the gate fails when a module drops below it.
- [ ] Given the repository, when action, goal and reward vocabularies are searched, then each concept
      has exactly one definition and no two modules define different types under the same name.
- [ ] Given the simulator and reward code, when it is read, then every business-rule value is a named
      constant or a configuration entry, and the reward weights come from the single versioned reward
      configuration.
- [ ] Given the learning modules, when they are read, then no unreachable function, unused
      compatibility branch, or superseded module remains; removed paths are deleted, not commented
      out.
- [ ] Given production code, when an invalid state or configuration is reached, then it raises a
      typed error with a localized diagnostic; bare `assert` statements are removed from production
      modules and remain only in tests.
- [ ] Given the training pipeline, when a simulator-derived artifact is produced, then
      `validate_calibration` has been executed against recorded telemetry baselines and its result is
      recorded in the artifact metadata.
- [ ] Given `docs/wiki/` and the story index, when the repair stories are completed, then the
      completion status of US-066, US-067, US-068, US-071, US-072 and US-073 reflects the verified
      state, and automated simulation evidence, recorded telemetry evaluation and outstanding live
      Windows validation are stated separately rather than merged.
- [ ] All new user-visible diagnostics are available in German and English and the two locale files
      stay in sync.

## Out of scope

- Repairing the behavior the corrected tests will then expose - that is BUG-031, BUG-032, US-079,
  US-080 and US-081.
- Raising the repository-wide coverage floor for modules outside the learning stack.
- Refactoring the vision, input-control or UI layers.

## Verification

- Automated: the corrected unit tests; the new `tests/integration/` pipeline test; per-module
  coverage enforcement in `pyproject.toml`; a lint or test guard asserting no duplicate action
  vocabulary and no `assert` in `src/`; locale sync test; `./scripts/check.ps1`.
- Manual (Windows): none required. This story changes verification and hygiene only; any live
  validation it uncovers is recorded against the owning story.

---

## Resolution

- 2026-08-28: Closed and consolidated into [US-085](../US-085-production-readiness-and-autonomous-farming-polish.md). The codebase quality requirements (clean error handling replacing bare `assert` statements in `src/`, deterministic regression tests, locale synchronization, and total `./scripts/check.ps1` green gate with 89%+ test coverage) are rolled into and enforced by US-085.

