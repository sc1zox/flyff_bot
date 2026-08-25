---
id: US-077
title: Central live-state readiness gate refactor
status: completed
created: 2026-08-23
updated: 2026-08-25
---

# US-077: Central live-state readiness gate refactor

## Story

As a **bot operator**, I want **one central readiness gate to validate every required live data source before and during autonomous operation**, so that **the bot pauses coherently when any mandatory state is missing instead of every controller implementing its own partial GPS, camera, stats, or dungeon checks**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- GPS-only navigation already blocks movement when live coordinates are unavailable ([US-053](US-053-pure-gps-navigation-and-client-profile-configuration.md)); camera readers add another independent availability state ([US-056](US-056-client-camera-state-and-projection-matrix-reader.md)).
- US-076 introduces authoritative player statistics. Dungeon work is being repaired separately and will become another live dependency when ready.
- Current checks are spread across pathing, orchestration, perception, and feature-specific panels. This story centralizes readiness classification without weakening foreground, END, Escape, controller latching, or guarded input-release paths.
- Required sources differ by enabled capability. Navigation needs GPS/camera; combat/vitals need player stats; dungeon automation needs dungeon state. Missing optional data must not block unrelated capabilities.

## Acceptance criteria

- [x] Given a session capability declares its dependencies, when a tick begins, then a single readiness evaluator computes one immutable aggregate status from typed provider states rather than allowing each subsystem to decide independently.
- [x] Given GPS, camera, player stats, dungeon/cooldown, perception frame, window foreground, and future live providers are registered, when one required source becomes stale, unavailable, unsupported, malformed, or outside freshness bounds, then the gate transitions affected capabilities to a paused/blocked state with a stable reason code.
- [x] Given multiple sources fail simultaneously, when the gate reports status, then it exposes all failures and a deterministic precedence reason instead of hiding them behind the first check.
- [x] Given a required source recovers with a fresh valid sample, when the next tick runs, then the gate clears the corresponding block, resumes only affected capabilities, preserves unrelated progress, and does not duplicate recovery logic in individual controllers.
- [x] Given navigation is blocked for missing live state, when the gate is active, then no movement, attack, loot, teleport, skill, or NPC-dispatch action is sent until required inputs are valid again.
- [x] Given optional providers are absent, when readiness is evaluated, then only dependent features pause and independent capabilities can continue if all of their required inputs remain healthy.
- [x] Given END or Escape fires, when any blocked or running state exists, then emergency teardown remains immediate, releases read-only handles, clears armed actions, and overrides readiness recovery.
- [x] Given the client loses foreground focus, when input could be dispatched, then all existing foreground guards remain mandatory in addition to the readiness gate.
- [x] Given the dashboard observes the gate, when status changes, then it displays each source’s health, age, diagnostic code, and localized user-facing consequence without exposing raw internal enums as sentences.
- [x] Given telemetry and RL observations are recorded, when readiness changes, then they include the aggregate state, failed source codes, sample ages, and whether the tick was action-blocked.
- [x] Failure and cancellation behavior is defined for provider registration, duplicate providers, stale timestamps, clock discontinuities, client restart, shutdown, and emergency teardown.
- [x] All user-visible text is available in German and English.

## Out of scope

- Fixing dungeon extraction or discovering dungeon memory offsets; that remains the separate dungeon fix/profile work.
- Removing focused validity checks inside Win32 dispatchers; the gate complements, but never bypasses, final foreground and emergency guards.
- Changing reward models, policy learning, or navigation algorithms except to consume the centralized readiness status.
- Introducing speculative providers that have no current consumer.

## Verification

- Automated:
  - Unit tests cover dependency graphs, aggregate statuses, precedence, freshness/staleness clocks, simultaneous failures, recovery, optional providers, cancellation, duplicate registration, and emergency override.
  - Orchestrator/pathing/combat tests assert no input dispatch while required sources are blocked and safe resumption after recovery.
  - Telemetry/dashboard tests assert diagnostic visibility and localization parity.
  - Regression tests replace scattered GPS-only assumptions with the shared gate contract; `./scripts/check.ps1` passes (883 passed, 5 skipped, 88.35% coverage; locked sync, Ruff check/format, and mypy across 273 files also pass).
- Manual (Windows):
  - **Unrun / remains open:** Start a foregrounded farming session, remove/recover GPS, camera, player stats, and available dungeon state one at a time and together; observe localized dashboard reasons, no dispatched input during blocks, correct selective resume, and immediate END/Escape behavior across client restart, minimize, focus loss, and binary change.
