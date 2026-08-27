---
id: US-080
title: Goal-driven quest execution - resolved objectives steer teleport, navigation and the policy
status: completed
created: 2026-08-25
updated: 2026-08-26
---

# US-080: Goal-driven quest execution - resolved objectives steer teleport, navigation and the policy

## Story

As an **operator**, I want **to select a quest and have the bot resolve it into an ordered goal
sequence that it then executes autonomously - teleporting to the region, navigating to the NPC,
accepting, travelling to the resolved spawn zone, farming the required kills, returning and turning
in**, so that **quests complete without me steering any single step, and the learning stack sees the
same goal the executor is pursuing**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Most building blocks already exist and are individually tested:
  - `QuestGoalResolver` binds quest requirements to extracted spawn zones and NPC world positions
    (`features/quests/goals.py:157`), and `QuestFarmingQueue` walks a selected quest sequence.
  - `QuestInteractionController` drives navigate, interact, accept, await-confirmation, turn-in and
    reward-claim (`features/automation/quest_execution_models.py`), wired at
    `features/automation/orchestrator.py:1094`.
  - `TeleporterDispatcher` performs guarded long-range travel with live arrival confirmation
    (`features/navigation/teleporter_dispatch.py`), and `VectorZoneNavigator` performs terrain-aware
    3D routing.
- What is missing is the connective tissue: there is no single object that states "this is the goal
  right now", so:
  - The teleporter is only used for emergency recovery (US-051), never to reach a quest region.
  - `HierarchicalObjective` (`features/policy/hierarchical.py:42`) is constructed only in tests and
    from a hard-coded default at `orchestrator.py:331`; it is never populated from a
    `QuestResolution`.
  - `WorldSnapshot` (`features/telemetry/models.py:87`) records no quest identity, no objective
    index, no progress and no active spawn zone, so recorded experience cannot be conditioned on the
    goal that produced it.
- Depends on [US-079](US-079-unified-goal-conditioned-decision-contract.md) for the goal-conditioned
  observation fields.
- Safety boundaries are unchanged: foreground verification, the emergency stop, guarded key release
  and read-only client access under
  [ADR-006](../decisions/ADR-006-read-only-process-memory-access.md) stay authoritative and are
  never owned by a policy.
- Assumption to confirm: teleporter destination names extracted by
  `features/navigation/teleporter_extraction.py` can be mapped to the world of a resolved spawn zone
  or quest NPC. If a quest region has no reachable teleporter destination, the goal must fail with an
  explicit reason instead of silently walking.

## Acceptance criteria

- [x] Given a selected quest, when it is resolved, then a typed ordered goal sequence is produced -
      travel to accept NPC, accept, travel to each objective location, satisfy each objective,
      travel to turn-in NPC, turn in - and each goal states its completion condition and its
      measurable progress.
- [x] Given a goal whose destination lies in another world or beyond a configured walking distance,
      when it becomes active, then the teleporter is dispatched to the mapped destination and
      arrival is confirmed from live client state before the goal continues.
- [x] Given a goal whose destination has no mapped teleporter destination and is not walkable, when
      it becomes active, then the session pauses with an explicit localized reason and does not
      attempt an unbounded walk.
- [x] Given an active kill or collect objective, when the session farms, then the target class
      whitelist, the patrol zone and the leash are derived from the resolved spawn zone of that
      objective, and a change of active objective changes them within one decision cycle.
- [x] Given a quest with several objectives, when one objective completes, then the queue advances
      to the next goal without operator input and the dashboard shows the active goal, its index and
      its progress.
- [x] Given any active goal, when a tactical decision is made, then the policy receives that goal as
      its objective and the decision is recorded together with the goal identity, index and progress.
- [x] Given a recorded session, when telemetry is inspected, then every world snapshot and every
      target decision carries the active goal identity, kind, index, progress, active spawn zone and
      world identifier.
- [x] Given a goal that cannot progress within its configured timeout, when the timeout expires,
      then the goal fails with a localized reason, the failure is recorded, and the session either
      advances to the next quest or pauses according to the configured policy.
- [x] Given the game window loses focus or the emergency stop is triggered at any point in the goal
      sequence, when that happens, then all keys are released and execution halts, unchanged from
      today.
- [x] All user-visible text - goal names, goal states, failure reasons and dashboard labels - is
      available in German and English and the two locale files stay in sync.

## Out of scope

- Parsing new quest types beyond the kill and collect requirements the resolver already understands.
- Learning the goal order. This story makes goals explicit and executable; choosing between goals is
  the strategic tier trained under US-081.
- Automatic quest acceptance from an in-game quest list; the operator still selects which quests to
  run.

## Verification

- Automated: goal-sequence resolution tests for kill, collect and multi-objective quests; a
  teleport-required goal test with a stubbed dispatcher asserting arrival confirmation gates
  progress; an unreachable-goal refusal test; an objective-switch test asserting whitelist, zone and
  leash change; a telemetry test asserting goal identity is present on snapshots and decisions; a
  goal-timeout failure test; an emergency-stop-during-goal test; locale sync test;
  `./scripts/check.ps1`.
- Manual (Windows): run one full quest end to end against the live client - teleport, accept, farm,
  return, turn in - and confirm the dashboard goal display, the recorded telemetry and the emergency
  stop at each phase. **Not run**: no foregrounded `neuz.exe` session was available during
  implementation.

## Implementation notes

- `features/quests/objectives.py` is the objective bus. `build_goal_sequence` decomposes a
  `QuestResolution` into ordered `QuestGoal` values; `QuestGoalSequence` owns the active index, the
  measured progress, the per-family timeout and the failure reason, and hands every consumer the
  same `QuestGoalIdentity`.
- Only executable steps enter the sequence: a quest whose accept or turn-in NPC the client never
  resolved contributes no travel or interaction goal for it and starts at its first objective.
- `features/navigation/goal_travel.py` decides walk / teleport / unreachable from the extracted
  teleporter catalog, the live world identifier and the configured walking distance.
  `TeleporterDispatcher` still owns the guarded UI sequence and the arrival confirmation.
- `features/automation/quest_goals.py` projects the active goal onto the kill quotas, the patrol
  zones, the leash anchor and the `HierarchicalObjective` the policy is conditioned on.
- The goal timeout measures *stalled* progress: recorded progress restarts it.
- A refused or timed-out goal advances the quest queue when one has a next quest, and otherwise
  pauses the session for good rather than resuming into the same wall.
