# ADR-008: Closed learning-loop invariants

- Status: accepted
- Date: 2026-08-25
- Related defects: [BUG-031](../bugs/fixed/BUG-031-learning-loop-is-open-recorded-data-and-live-inference.md)
- Related stories: [US-071](../user-stories/completed/US-071-unified-rl-environment-and-reward.md), [US-073](../user-stories/completed/US-073-hierarchical-rl-farming-navigation-and-quest-policy.md)

## Context

The project's goal is a loop: farm live, record experience, train offline, evaluate, promote, farm
better. BUG-031 established that the loop was open at both ends. Recorded transitions carried a
constant action, a partially zeroed next state, an incomplete reward, and a termination flag on
every kill, and they could join observations from different sessions. On the live side no supported
path loaded a learned artifact, a learned target could not be matched back to a candidate, and any
learned fault silently produced `HeuristicPolicy` behaviour under an `ML_ACTIVE` label.

Individually these were separate bugs. Together they are one invariant problem: nothing in the
contracts made a decision, its interval, or its provenance unforgeable.

## Decision

Five invariants hold across the RL, policy, and telemetry boundaries.

1. **A decision is parameterized, not enumerated.** `ParameterizedAction` carries the discrete
   index *and* the parameters that identify the exact choice: candidate instance, destination,
   attack point, corridor, interaction target, and wait duration. `TacticalActionCatalog.encode`
   and `decode` round-trip every typed payload without loss, and `TacticalActionMask.allows`
   rejects one exact parameterized choice rather than a whole action family.

2. **An interval belongs to one session and one episode.** Every exported `Transition` names its
   `session_id` and `episode_index`. State, action, reward, next state, both masks, termination,
   and truncation are all reconstructed from events of that one session, inside the interval
   between one decision and the next. An episode ends on an observed objective completion, or is
   truncated at the end of the recording. A verified kill does not end a farming episode.

3. **A reward component is observed, and awarded once.** Each configured component maps to its own
   recorded observation - kill cycles, navigation episodes, combat episodes, and objective-progress
   events. An episode is attributed to the interval its *end* falls into, so no observation is
   counted for two decisions.

4. **A candidate is identified by instance, not by class.** A detector class identifier cannot
   distinguish two mobs of the same class. Target, attack-point, and corridor actions carry
   `candidate_index`, and the execution boundary resolves them by that index alone. Screen
   coordinates are a click convention and never an identity.

5. **Learned automation fails closed.** `PolicyRunner` reports a typed `PolicyFault` for a missing,
   incompatible, non-finite, masked, late, or faulting learned result and returns no action. The
   orchestrator halts learned automation and publishes a synchronized German and English
   diagnostic. The deterministic baseline is produced only when no learned policy is configured at
   all - never as a silent substitute for one that failed. An empty option set is not a fault.

Two supporting rules follow from these:

- A missing measurement stays distinguishable from a measured zero in **every** encoder. The RL
  observation pairs each optional value with an explicit missing indicator and keeps signed
  quantities signed, matching the `NaN` plus `__is_missing` convention the supervised value-model
  stack already used.
- The live policy is served the same decision-time contract it was trained on. Live kinematics and
  NavMesh context are supplied through `LiveObservationState`, decision-time features are built by
  the single shared `candidate_feature_row`, and a quantity that is genuinely unobserved at
  decision time stays missing instead of being fabricated as zero.

## Alternatives

- **Keep the heuristic fallback and only log the fault.** Rejected: the recorded session then
  contains heuristic decisions labelled as learned ones, which poisons the next training round.
- **Add the missing reward components as constants.** Rejected: a reward term with no observation
  behind it teaches the policy an artefact of the exporter rather than a property of the game.
- **Identify a candidate by class identifier plus screen position.** Rejected: two mobs of the same
  class share the identifier, and the position depends on a coordinate convention that already
  diverged between the ranking layer and the execution boundary.
- **Keep the 56-column observation and encode missingness implicitly.** Rejected: absent and
  measured-zero would still alias, and the supervised stack already solved this with explicit
  indicators. Two disagreeing conventions in one repository is the worse outcome.

## Consequences

- The RL observation width and schema version changed, so previously exported artifacts and
  datasets are rejected as incompatible rather than silently misread. This follows
  [ADR-003](ADR-003-clean-schema-over-backward-compatibility.md).
- Telemetry gained an `objective_progress` event and a measured `evasion_seconds` on navigation
  episodes, because a reward component with no observation behind it cannot be honest.
- `ML_ACTIVE` now pauses a session when its model cannot be served. That is louder than the
  previous behaviour and intentionally so: a silent downgrade made learned and heuristic runs
  indistinguishable in recorded data, which corrupts the next training round.
- A learned artifact is warmed up when it is loaded, so the first real decision is not charged for
  ONNX graph setup and does not trip the five-millisecond budget.
- These are offline results. Live-client convergence, real inference latency, and end-to-end
  promotion of a trained artifact remain operator validation on Windows.

## Verification

`tests/unit/test_learning_loop.py` pins each invariant: a two-session fixture with interleaved
timestamps, a payload round-trip across every action family, per-interval reward attribution, a
real five-head ONNX artifact selecting the intended instance of two same-class candidates through
the orchestrator, `ML_SHADOW` and `ML_ACTIVE` dispatching provably different input, train/serve
encoder equality, missing-versus-zero encoding, and a halted session with a localized diagnostic.
The full gate passed on 2026-08-25.
