# ADR-009: Bounded tactical parameter space and hybrid tuning boundary

- Status: accepted
- Date: 2026-08-28
- Related stories: [US-084](../user-stories/completed/US-084-ml-modifiable-tactical-parameters-and-tuning.md), [US-079](../user-stories/completed/US-079-unified-goal-conditioned-decision-contract.md), [US-081](../user-stories/US-081-experience-database-and-train-evaluate-promote-loop.md)
- Supersedes: none

## Context

Operational navigation, combat, perception, camera, vitals, and recovery heuristics need one
typed surface for offline tuning and guarded contextual decisions. System invariants must remain
outside that surface: virtual keys, process fingerprints and memory offsets, focus checks,
emergency stop handling, and schema digests cannot be learned or configured as tactical values.

## Decision

`TacticalParameterSpace` is an immutable value object with exactly 16 scalar, named parameters.
Each scalar has one immutable finite minimum, maximum, and default definition. Engagement distance
also supports a bounded per-monster profile. Values resolve with this precedence:

1. safe defaults;
2. a loaded validated profile;
3. a per-monster engagement profile;
4. a prevalidated transient approach override for one policy decision.

Finite outliers clamp at the parameter boundary. Config and offline values that are non-finite
fall back to the safe default and retain a diagnostic for localized presentation. A live learned
non-finite, malformed, masked, or otherwise invalid action is rejected and fails closed under
[ADR-008](ADR-008-closed-learning-loop-invariants.md); it is never silently replaced by a
heuristic or default action.

Profiles use the standalone `us084-v1` JSON schema and a content digest. This makes a profile
deterministic and suitable for a future US-081 model-registry reference, without claiming that
the US-081 train/evaluate/promote registry is implemented.

## Alternatives

- **Expose every configuration field to ML:** Rejected because it would permit changes to safety
  and identity invariants.
- **Use unbounded floats or silently substitute defaults for live policy faults:** Rejected because
  unbounded values can produce unsafe control and silent substitution corrupts learned-session
  provenance under ADR-008.
- **Create a registry as part of US-084:** Rejected because persistence compatibility is sufficient
  here and the experience/train/evaluate/promote lifecycle belongs to US-081.

## Consequences

- Simulator and deterministic controllers consume the same validated tactical values, while UI
  profile controls expose inspection, export, load, reset, and localized diagnostics.
- Camera pitch and zoom are guarded open-loop actuator calibration parameters. Their behavior in a
  live Windows client remains an operator validation step, not automated evidence.
- The positive profile allow-list makes future fields fail closed until they receive an explicit
  bound and default definition.

## Verification

`tests/unit/test_tactical_parameters.py` covers the 16 definitions, finite clamping, config-file
non-finite fallback and diagnostics, digest-checked profile round trips, invariant rejection,
parameterized approach-action encoding, live non-finite policy rejection, controller and simulator
integration, and German/English diagnostics. The focused 18-test tactical suite, affected
276-test slice, 55-test orchestrator slice, Ruff, and MyPy passed. The final canonical gate passed
on 2026-08-28: `uv sync --locked`, Ruff, format, and MyPy completed successfully, and pytest
reported 1063 passed, 5 skipped, and 89.38% coverage. No live `neuz.exe` camera or zoom
confirmation is claimed.
