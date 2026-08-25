---
id: US-079
title: Unified versioned goal-conditioned decision contract
status: draft
created: 2026-08-25
updated: 2026-08-25
---

# US-079: Unified versioned goal-conditioned decision contract

## Story

As a **bot developer**, I want **one versioned observation, action, mask and reward contract that
the simulator, the telemetry exporter, the offline trainer and the live policy all share**, so that
**a policy trained offline behaves identically when it drives a live farming or quest session**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Today the same concepts are defined three or more times:
  - `TacticalAction` is an `IntEnum` with 7 members in `features/rl/actions.py:17`, a different
    `IntEnum` with 4 members in `features/simulator/engine.py:41`, and a union type alias in
    `features/policy/models.py:68`. `TacticalActionKind` (6 members) and `StrategicGoalKind`
    (4 members) add two more vocabularies.
  - The 52-dimensional observation is built by `ObservationSpace.from_telemetry_snapshot`,
    `FarmingSimulator.observation` and `hierarchical_onnx._observation`, each filling different
    fields with different defaults.
  - Reward is defined by `RewardConfig` (`us071-v1`), by `FarmingSimulator._reward` with inline
    literals, and recorded a third time as `KillCycle.reward`.
- The consequences are recorded in
  [BUG-031](../bugs/BUG-031-learning-loop-is-open-recorded-data-and-live-inference.md) and
  [BUG-032](../bugs/fixed/BUG-032-simulator-dynamics-and-paired-evaluation-invalidate-policy-metrics.md).
- [ADR-003](../decisions/ADR-003-clean-schema-over-backward-compatibility.md) authorizes deleting
  the superseded contracts rather than shimming them.
- The user goal driving this work is autonomous quest completion, so the observation must be
  goal-conditioned: the agent must be able to see *which* objective it is currently pursuing.
- Assumption to confirm: the deterministic navigation, quest and combat layers keep ownership of
  which destinations, corridors, attack points and interactions are legal. The policy ranks the
  offered options; it never invents new ones.

## Acceptance criteria

- [ ] Given the repository after this story, when the codebase is searched for action enumerations,
      then exactly one action contract module exists and the duplicate `TacticalAction` definitions
      in `features/rl/actions.py` and `features/simulator/engine.py` are deleted.
- [ ] Given a decision with several legal options, when it is encoded, then the encoded action
      preserves the selected candidate identity, destination, attack point, corridor, interaction
      target and bounded wait duration, and decoding returns an equal payload.
- [ ] Given a parameterized action, when the mask is applied, then the mask rejects the exact
      invalid parameterized choice rather than only the action category.
- [ ] Given a monster candidate, when it is referenced by an action, then it is identified by a
      stable per-instance identity that distinguishes two simultaneously visible monsters of the
      same class.
- [ ] Given an active quest objective, when an observation is encoded, then the observation carries
      the objective identity, its kind, its index in the quest sequence, its measured progress and
      its remaining route distance, so the same state under two different goals encodes differently.
- [ ] Given a measurement that was not observed, when it is encoded, then it is distinguishable from
      a measured zero and from a measured negative value.
- [ ] Given the same world state, when it is encoded by the simulator encoder and by the live
      encoder, then both produce an identical vector; a parity test asserts this.
- [ ] Given a reward interval, when it is computed, then exactly one versioned reward configuration
      is used by simulator, exporter and evaluation, and its version string is written into every
      artifact and dataset it produced.
- [ ] Given an artifact whose contract version does not match the running application, when it is
      loaded, then loading fails with an explicit incompatibility diagnostic and no compatibility
      shim is attempted.
- [ ] All user-visible text, including every contract-incompatibility and validation diagnostic, is
      available in German and English and the two locale files stay in sync.

## Out of scope

- Changing the learning algorithm, the network architecture, or introducing a deep-learning runtime
  dependency. This story only fixes the contract those choices sit on.
- Simulator dynamics repair (BUG-032) and the training and promotion pipeline (US-081), which build
  on this contract.
- Online weight updates or exploratory random actions against the live client.

## Verification

- Automated: round-trip property tests for every action payload; mask rejection tests for invalid
  parameterizations; a goal-conditioning test proving two objectives produce different encodings;
  a missing-versus-zero encoding test; a simulator-versus-live encoder parity test; a contract
  version mismatch rejection test; locale sync test; `./scripts/check.ps1`.
- Manual (Windows): with a real client, confirm that a shadow-mode session logs learned decisions
  whose candidate identity matches the monster the operator sees selected.
