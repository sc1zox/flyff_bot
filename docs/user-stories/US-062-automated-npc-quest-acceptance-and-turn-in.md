---
id: US-062
title: Automated NPC quest acceptance and turn-in
status: draft
created: 2026-08-20
updated: 2026-08-20
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

- [ ] Given an active quest goal that has not yet been accepted by the character, when the farming routine starts, then the bot navigates to the quest NPC's world coordinates on the NavMesh.
- [ ] Given the character is within interaction range of the quest NPC, when the interaction sequence triggers, then the bot targets the NPC, opens the dialogue window, and selects the accept option.
- [ ] Given all objectives for an active quest are fulfilled, when farming completes, then the bot navigates back to the quest completion NPC / Black Board on the NavMesh.
- [ ] Given the character reaches the completion NPC, when the turn-in dialogue sequence runs, then the bot interacts with the NPC, completes the quest, and claims rewards.
- [ ] Given the turn-in completes and rewards are granted, when the dialogue closes, then the bot marks the quest as finished and advances to the next queued quest.
- [ ] Given an NPC interaction fails or is obstructed, when an interaction timeout expires, then the bot retreats to a safe position on the NavMesh and retries with backoff.
- [ ] All user-visible text is available in German and English.

## Out of scope

- Bypassing NPC range checks or sending raw network packets.
- Memory writing or internal client function hooking.

## Verification

- Automated:
  - Unit tests for NPC coordinate resolution and NavMesh path dispatch.
  - State machine tests for NPC dialogue state transitions, timeout handling, and retry backoff.
- Manual (Windows):
  - Test end-to-end cycle: accept a quest from the Quest Black Board in Aurania/Eden, navigate to spawn, fulfill objectives, return to NPC, and turn in quest.
