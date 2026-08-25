# ADR-007: Offline tactical simulator boundary

- Status: accepted
- Date: 2026-08-24
- Related stories: [US-072](../user-stories/completed/US-072-offline-farming-and-navigation-simulator.md), [US-071](../user-stories/completed/US-071-unified-rl-environment-and-reward.md)

## Context

US-072 needs a seeded, high-level farming and quest simulator that can run faster than
real time without a client process. The project also has a strict live boundary: game
input requires foreground checks and emergency stop paths; client memory access is read-only
and fingerprinted.

## Decision

The simulator is a separate `features.simulator` boundary. It reads already extracted world
data and telemetry contracts in memory. It emits typed RL-shaped observations and aggregate
metrics. It never opens the client, reads process memory, dispatches input, or renders frames.

Monster lifecycle, combat duration, stall recovery, movement time, and quest progression are
modeled at the tactical level. Low-level client execution remains the responsibility of the
existing navigation and automation features.

## Consequences

- Training and policy analysis can run offline with reproducible seeds.
- Simulator results are not evidence of live-client behavior until validated on Windows.
- Calibration compares aggregate KPM and navigation time to recorded baselines within an
  explicit tolerance rather than claiming full game emulation.
- Tactical-level modeling is only a defensible reward source while every modeled action pays a
  cost the client would also charge. BUG-032 added the invariants that enforce this: one budgeted
  clock per tick, movement only through the routed corridor, mask enforcement inside `step()`, and
  a calibration gate the training pipeline must pass before it writes an artifact.
