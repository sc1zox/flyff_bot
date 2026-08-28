---
id: US-086
title: Unattended autopilot mode, session resilience, and autonomous goal arbitration
status: completed
created: 2026-08-28
updated: 2026-08-28
---

# US-086: Unattended Autopilot Mode, Session Resilience, and Autonomous Goal Arbitration

## Story

As a **Flyff bot operator**,
I want **to arm one autopilot session that chooses its own next goal, survives death, faults, and
lost focus without my intervention, and ends on a declared budget rather than on the first
surprise**,
so that **the bot farms and completes quests unattended for hours and I can tell from the
dashboard whether it is still working.**

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- The session today is armed by the operator choosing zone, target monsters, and quest, and it ends
  on the first unhandled fault. This story turns that into a supervised, self-directed loop.
- The building blocks already exist and are reused rather than replaced:
  `FarmingOrchestrator`, `QuestFarmingQueue`, `KillGoalTracker`, `QuestGoalSequence`,
  `PathingController`, `EmergencyRecoveryController`, `TeleporterDispatch`, `LiveReadinessGate`,
  `StrategicGoalKind`, and `SessionEventLogger`.
- Related decisions:
  [ADR-002](../decisions/ADR-002-target-architecture-and-pyside6.md) (worker threads never touch
  widgets), [ADR-006](../decisions/ADR-006-read-only-process-memory-access.md) (read-only memory),
  [ADR-009](../decisions/ADR-009-bounded-tactical-parameter-space.md) (what may and may not be
  tuned).
- Consolidated predecessors:
  [US-013](completed/US-013-autonomous-farming-loop-and-orchestration-engine.md) (the tick loop),
  [US-040](completed/US-040-unrecoverable-stuck-emergency-teleport-and-spawn-reset.md) (last-resort
  reset), [US-049](completed/US-049-session-event-log-and-transition-diagnostics.md) (event log),
  [US-056](completed/US-056-client-camera-state-and-projection-matrix-reader.md) (camera and
  projection matrices), [US-062](completed/US-062-automated-npc-quest-acceptance-and-turn-in.md)
  (NPC accept and turn-in), [US-077](completed/US-077-central-live-state-readiness-gate.md)
  (readiness gate), [US-080](completed/US-080-goal-driven-quest-execution-and-objective-bus.md)
  (objective bus), [US-085](completed/US-085-production-readiness-and-autonomous-farming-polish.md)
  (production baseline).
- This story deliberately carries four defects found in the 2026-08-28 production-readiness audit,
  because autopilot cannot be demonstrated while any of them stands. They are stated as their own
  acceptance sections (1, 2, 3, 6) so each is separately verifiable:
  1. `SessionWorker._run` calls `orchestrator.tick()` with no exception guard, `is_running` is never
     read in production code, and no watchdog exists. A single unhandled exception ends the worker
     thread silently while the dashboard keeps showing the last state.
  2. There is no player-death state. `VitalsTriggerController.step` fires on
     `current_pct <= rule.threshold_percentage` with no lower bound, so HP 0 % dispatches the HP
     consumable key every `debounce_seconds` indefinitely.
  3. `WindowsInputController.is_aborted` polls `GetAsyncKeyState(VIRTUAL_KEY_ESCAPE)` with mask
     `0x8000`. `ESC` is an ordinary Flyff key that the quest dialogue flow itself provokes, and a
     held-only read makes a short press nondeterministic against the tick rate.
     `CLAUDE.md` and `.claude/rules/windows-safety-and-input.md` document `F12` / `Ctrl+Shift+Q`.
  4. `FarmingOrchestrator._advance_quest_interaction` resolves the quest NPC's screen position by
     matching its world position against `WorldState.visible_mobs`, which contains only YOLO monster
     detections filtered by `allowed_class_names`. An NPC never appears there, so
     `npc_screen_position` stays `None` and the dialogue is never opened.
     `CameraState.view_projection_matrix` is already read live; only the forward world-to-screen
     projection is missing (`unproject_screen_ray` implements the inverse).
- Assumption to confirm during implementation: the client's death state is observable from the
  player-stats reader or the visual HUD without a new memory profile. If neither proves a death
  reliably, the fallback is a bounded zero-HP dwell time, which must then be a named constant.
- Assumption: respawn is reachable through a client dialogue confirmed by the same guarded
  `QuestInputDispatcher`-style path used for NPC dialogues. The exact key or click target is to be
  observed, not guessed.
- Safety boundaries are unchanged and non-negotiable: foreground verification before every
  dispatch, emergency stop releases all held keys, read-only `ReadProcessMemory` only.

---

## Acceptance criteria

### 1. The session survives a fault instead of dying silently

- [x] **Given** an armed session, **when** `orchestrator.tick()` raises any exception, **then** the
      worker thread stays alive, the exception is recorded as a typed session event with its
      exception type and message, the session transitions to a defined faulted state, and all held
      keys are released.
- [x] **Given** a recorded tick fault, **when** the dashboard updates, **then** the operator sees a
      localized fault reason and the time of the fault rather than the last successful state.
- [x] **Given** a running session, **when** the worker thread stops for any reason, **then** the UI
      reflects that within one status interval, because a heartbeat is published per tick and its
      staleness is evaluated.
- [x] **Given** repeated tick faults, **when** the count within the configured window exceeds the
      configured maximum, **then** the session ends on the budget rules of section 5 instead of
      retrying forever.

### 2. Player death is a state, not a potion loop

- [x] **Given** an armed session, **when** the player is observed dead, **then** the session enters
      `FarmingMode.DEAD`, releases all held keys, cancels any active route and engagement, and
      records a typed session event.
- [x] **Given** `FarmingMode.DEAD`, **when** vitals are evaluated, **then** no vitals trigger is
      dispatched, because `VitalsTriggerController` refuses to fire below a named minimum vital
      percentage and the orchestrator does not evaluate vitals in the death state.
- [x] **Given** `FarmingMode.DEAD` under autopilot, **when** the respawn interaction is available,
      **then** it is dispatched through the guarded input path, and on confirmed respawn the session
      returns to goal arbitration.
- [x] **Given** more deaths within the configured window than the configured maximum, **when** the
      next death occurs, **then** autopilot pauses with a localized reason naming the death count,
      rather than respawning again.
- [x] **Given** `FarmingMode.DEAD` without autopilot armed, **when** the death is observed, **then**
      the session pauses and waits for the operator.

### 3. The emergency stop is reliable and does not collide with a game key

- [x] **Given** the running application, **when** the emergency-stop hotkey is evaluated, **then**
      `ESC` is not part of it and the documented combination in
      `.claude/rules/windows-safety-and-input.md` is what is polled.
- [x] **Given** a short press of the emergency-stop hotkey between two ticks, **when** the next tick
      runs, **then** the stop is still detected, because the pressed-since-last-query state is
      latched rather than only the currently-held state being read.
- [x] **Given** a triggered emergency stop, **when** it is handled, **then** every held key is
      released, the session enters `EMERGENCY_STOPPED`, and autopilot does not resume it
      automatically.
- [x] **Given** the emergency stop, **when** documentation is checked, **then** `CLAUDE.md`,
      `AGENTS.md`, and `.claude/rules/windows-safety-and-input.md` name the same keys the code polls.

### 4. Recovery is graded, and a policy fault costs a decision, not the session

- [x] **Given** `PolicyRuntimeMode.ML_ACTIVE`, **when** one policy evaluation reports a fault,
      **then** that decision is discarded, the tick falls through to the deterministic path, and the
      fault is counted, without pausing the session.
- [x] **Given** consecutive policy faults exceeding the configured budget, **when** the budget is
      exhausted, **then** learned automation is demoted to `HEURISTIC` with a localized
      `capability_degraded` event, and farming continues.
- [x] **Given** an attack point whose route is unavailable, **when** the approach cannot start,
      **then** the candidate is skipped for this decision instead of the session being paused.
- [x] **Given** the policy latency budget, **when** it is defined, **then** its value is justified by
      a recorded measurement of live inference on the target machine rather than assumed, and
      exceeding it is treated by the rules above.
- [x] **Given** lost window focus, a frame-capture error, or a readiness block under autopilot,
      **when** the blocking condition clears, **then** the session resumes on its own after a bounded
      backoff wait, and each attempt is recorded.
- [x] **Given** a window that stays absent longer than the configured maximum, **when** the wait
      expires, **then** autopilot ends the session on the budget rules of section 5 with a localized
      reason.

### 5. Autopilot arms one self-directed session with a declared budget

- [x] **Given** the dashboard, **when** the operator arms autopilot, **then** one control starts a
      session that requires no further zone, monster, or quest selection, and the control states in
      localized text what the session will pursue.
- [x] **Given** autopilot is armed and `is_setup_required()` is true, **when** the operator tries to
      arm it, **then** arming is refused with the same localized reason the ordinary start button
      already carries.
- [x] **Given** an armed autopilot session, **when** a goal completes or becomes unexecutable,
      **then** the arbiter selects the next goal without operator input, in this order: continue the
      active quest, farm the active quest's kill objective, travel to and turn in a completed quest,
      accept the next available quest, and otherwise farm the configured fallback zone.
- [x] **Given** no executable quest remains, **when** the arbiter selects, **then** it farms the
      configured fallback zone and records the reason it stopped pursuing quests, rather than
      completing the session.
- [x] **Given** an arbitration decision, **when** it is taken, **then** it is recorded as a typed
      session event naming the chosen goal and the reason, and the dashboard shows the currently
      pursued goal in localized text.
- [x] **Given** a configured session time budget, **when** it expires, **then** the session finishes
      the current engagement, releases all keys, transitions to `COMPLETED`, and reports a localized
      summary of duration, kills, completed quests, deaths, and recoveries.
- [x] **Given** a configured recovery budget, **when** more recoveries occur within the window than
      the maximum allows, **then** autopilot ends the session the same way with a localized reason
      naming the exhausted budget.
- [x] **Given** every new autopilot setting, **when** it is defined, **then** it has a named default,
      a validated finite range, and a typed error on an invalid value, and no business-rule literal
      appears inline.

### 6. Quest NPC interaction actually reaches the dialogue

- [x] **Given** a live camera state and an NPC world position, **when** the NPC's screen position is
      needed, **then** it is computed by projecting the world position through
      `CameraState.view_projection_matrix` into client pixels, not by matching against
      `WorldState.visible_mobs`.
- [x] **Given** an NPC whose projected position falls outside the client area or behind the camera,
      **when** the projection is evaluated, **then** no click is dispatched and the goal reports a
      typed reason.
- [x] **Given** a quest NPC with no known world position, **when** the goal is evaluated, **then**
      it fails with a typed reason and the arbiter moves on, and no route to the world origin is
      ever started.
- [x] **Given** an open NPC dialogue, **when** its options are read, **then** OCR runs on a bounded
      region of interest rather than the full frame, in line with
      `.claude/rules/vision-and-perception.md`.
- [x] **Given** a dialogue reading below the configured match confidence, **when** it is evaluated,
      **then** no click is dispatched, so a chat or item line can never be mistaken for a menu
      option.
- [x] **Given** an accepted and a turned-in quest, **when** autopilot runs a full cycle, **then** the
      quest queue advances and the arbiter continues with the next goal.

### 7. Diagnostics, localization, and verification

- [x] **Given** the dashboard during an unattended run, **when** the operator looks at it, **then**
      autopilot state, pursued goal, elapsed and remaining budget, death count, recovery count, and
      last fault are visible without opening a dialog.
- [x] **Given** every new user-visible state, reason, refusal, and summary, **when** it is displayed,
      **then** it is present and synchronized in `src/flyff_bot/locales/de.json` and
      `src/flyff_bot/locales/en.json`, assembled from whole sentences rather than fragments.
- [x] **Given** the repository, **when** tests are collected, **then** `tests/integration/` exists
      and contains at least one test that drives the autopilot tick path end to end against fakes,
      covering a tick fault, a death and respawn, a focus loss and resume, and one goal
      arbitration, without a client, a window, or dispatched input.
- [x] **Given** the test suite, **when** `./scripts/check.ps1` runs, **then** `uv sync --locked`,
      `ruff check`, `ruff format --check`, `mypy`, and `pytest` all pass and coverage stays at or
      above the configured 85 % floor.

---

## Out of scope

- Recording telemetry from the desktop application, and any train, evaluate, or promote pipeline.
  The learning loop is a separate concern and gets its own story; autopilot must be demonstrable
  without it.
- Learned selection of the next goal. Arbitration in this story is deterministic and explainable;
  a learned arbiter is a later step on top of it.
- Zone rotation by measured yield. Without recorded telemetry there is no measurement to rotate on.
- Inventory-full handling, vendor runs, repair, and restocking.
- Reconnecting after a client crash or a lost server connection, or starting the client.
- Training additional YOLO monster classes. A quest whose target monster is not in
  `models/labels.txt` must fail its goal with a typed reason and let the arbiter move on, which is
  covered by section 5; extending the detector is separate work.
- Any memory write, injection, hooking, or stealth behavior.

---

## What landed

- `src/flyff_bot/features/automation/autopilot.py` — the whole unattended rulebook with no Win32 and
  no Qt: validated budgets, the rolling-window counters, the zero-HP dwell death detector, and the
  pure `arbitrate_goal`.
- `src/flyff_bot/features/automation/respawn.py` — bounded-ROI `Lodestar` perception and its
  foreground- and killswitch-guarded click.
- `src/flyff_bot/features/navigation/live_camera.py` — `project_world_to_screen`, the fail-closed
  forward projection that replaces the monster-detection match.
- `src/flyff_bot/ui/autopilot_panel.py` — the arming control and the localized state card.
- `src/flyff_bot/ui/session_worker.py` — the tick-fault boundary, the per-tick heartbeat, and
  `is_worker_stalled` for the UI watchdog.
- `scripts/measure_policy_latency.py` and
  [the recorded measurement](../sources/2026-08-28-tactical-policy-inference-latency-measurement.md)
  that justifies the unchanged 5 ms policy latency budget.
- `tests/integration/` — the directory this story required, driving the tick path end to end.

## Carried defects that were not in the original list

The application could not be imported at all from a cold interpreter: `features/automation/__init__`
re-exported the orchestrator and `features/navigation/pathing.py` imported `flyff_bot.ui.dashboard`,
so `flyff_bot.cli` and `flyff_bot.ui.app` both raised `ImportError`. Only `tests/unit/conftest.py`,
which happens to import navigation first, hid it. Autopilot cannot be demonstrated on an application
that does not start, so the layering was fixed (movement keys to `input_control/keymap.py`,
navigation view objects to `features/navigation/snapshots.py`, no orchestrator re-export) and
`tests/integration/test_module_import_graph.py` guards every entry point in its own subprocess.

## Notes on the delivered behavior

- The dashboard shows the fault time as an elapsed session duration, not a wall-clock timestamp,
  because the session clock is monotonic. The exact wall-clock time is in the session event log.
- The full accept → farm → turn-in cycle is exercised by the existing quest-execution tests plus the
  arbitration hand-off on queue advance; a single end-to-end fake covering one whole quest cycle was
  not added, so manual step 2 below still carries that confirmation.

## Verification

### Automated

```powershell
pwsh -File .\scripts\check.ps1
```

Deterministic checks to add:

- A tick that raises keeps the worker alive, records the fault, and enters the faulted state.
- A dead player dispatches no vitals key, and the vitals controller refuses below its minimum.
- The emergency-stop hotkey does not include `ESC`, and a press between two ticks is still detected.
- A single policy fault does not pause the session; an exhausted fault budget demotes to
  `HEURISTIC` and keeps farming.
- Focus loss followed by regained focus resumes the session after the bounded backoff.
- Goal arbitration picks the documented order, and falls back to the configured zone when no quest
  is executable.
- Both budgets end the session in `COMPLETED` with a summary.
- World-to-screen projection returns the expected client pixel for a known camera state, and
  refuses a position behind the camera or outside the client area.
- An NPC without a world position fails its goal and starts no route.
- `de.json` and `en.json` hold the same key set.

### Manual (Windows)

1. Start the client, arm autopilot with a quest available and a fallback zone configured, and leave
   the machine for at least two hours.
2. Confirm the bot accepts a quest at the NPC, farms its objective, returns, and turns it in.
3. Let the character die deliberately: confirm no consumable spam, a recorded death, an automatic
   respawn, and a resumed session.
4. Alt-Tab away for a minute and back: confirm keys are released on focus loss and the session
   resumes on its own.
5. Press the emergency-stop hotkey briefly: confirm every key is released, the session halts, and
   autopilot does not resume it.
6. Press `ESC` in the client to close a dialogue: confirm the session keeps running.
7. Let the time budget expire: confirm an orderly stop and a summary naming duration, kills,
   quests, deaths, and recoveries.
