---
id: US-062
title: Automated NPC quest acceptance and turn-in
status: completed
created: 2026-08-20
updated: 2026-08-22
---

# US-062: Automated NPC quest acceptance and turn-in

## Story

As a **bot operator running unattended quest routines**, I want **the bot to automatically navigate to the designated quest NPC or Quest Black Board via NavMesh, interact with the NPC, accept available quests, and turn in completed quests to claim rewards**, so that **quest progression can run completely end-to-end without manual NPC dialogue interaction**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Builds upon the quest database and goal tracking in [US-061](US-061-client-quest-data-extraction-and-goal-driven-quest-farming.md) and NavMesh vector routing in [US-059](completed/US-059-authoritative-vector-navigation-legacy-removal-and-multi-zone-selection.md).
- NPC world coordinates are resolved from client world placement files (`.dyo`, `character.inc`, `character-etc.inc`, `QuestDestination.txt.txt`) or fixed known coordinates.
- Interaction with NPCs uses documented Win32 input dispatch with foreground checks and END emergency stop per [AGENTS.md](../../AGENTS.md) and [ADR-002](../decisions/ADR-002-target-architecture-and-pyside6.md).
- Strictly read-only memory inspection / vision checks are used to verify dialogue state (no memory writing, no packet injection, no function hooking).

## Acceptance criteria

- [x] Given an active quest goal that has not yet been accepted by the character, when the farming routine starts, then the bot navigates to the explicitly configured quest NPC world coordinates on the NavMesh.
- [x] Given the character is within interaction range of the quest NPC, when the interaction sequence triggers, then the bot opens dialogue using guarded input and selects only a perception-proven accept option.
- [x] Given all objectives for an active quest are fulfilled, when farming completes, then the bot navigates back to the configured quest completion NPC / Black Board on the NavMesh.
- [x] Given the character reaches the completion NPC, when the turn-in dialogue sequence runs, then the bot interacts with the NPC and selects only a perception-proven turn-in option before reward evidence is accepted.
- [x] Given reward evidence is observed, when the bounded turn-in sequence completes, then the controller exposes the finished state for queue retirement and does not advance while evidence is missing.
- [x] Given an NPC interaction fails or is obstructed, when an interaction timeout expires, then the bot enters safe NavMesh-backed retreat and retries with exponential backoff until its configured attempt limit.
- [x] All user-visible text is available in German and English.

## Out of scope

- Bypassing NPC range checks or sending raw network packets.
- Memory writing or internal client function hooking.

## Verification

- Automated:
  - Unit tests for NPC coordinate resolution and NavMesh path dispatch.
  - State machine tests for NPC dialogue state transitions, timeout handling, and retry backoff.
- Completed:
  - `tests/unit/test_quest_goals.py` covers explicit NPC persistence/resolution, guarded input,
    read-only option clicks, timeout/backoff/failure, and position-approach guards.
- Manual (Windows):
  - Outstanding. Configure real Black Board/NPC positions, run the end-to-end cycle in a foregrounded
    client, and verify targeting, dialogue templates, reward claim, queue advance, and recovery.

## Implementation notes

- The current repository evidence names objective coordinates but not quest giver/finisher identity,
  so NPC locations are operator-configured rather than inferred. This is recorded in
  `docs/wiki/architecture.md`; no unverified client dialogue geometry was added.
- Automated checks were run on Linux: 708 passed, 20 skipped, 88.19% coverage; two unrelated
  POSIX-only tests failed (`test_live_position.py` Win32 layout and `test_ocr.py` Tesseract stub).
  The required Windows `./scripts/check.ps1` gate remains outstanding.
