---
id: US-009
title: Reactive loot collector and drop accounting
status: draft
created: 2026-08-15
updated: 2026-08-15
---

# US-009: Reactive loot collector and drop accounting

## Story

As a player using permitted automation, I want the bot to collect dropped items after combat and track collected loot against farming goals, so that items are picked up reliably without manual intervention.

## Context and assumptions

- Source: [Target architecture proposal](../sources/2026-08-15-target-architecture-proposal.md).
- Depends on [US-005](US-005-loot-log-ocr.md) (Loot OCR), [US-006](completed/US-006-target-architecture-bootstrap.md) (Architecture/Controllers), and [US-007](US-007-perception-worldstate-feed.md).
- In Flyff, loot pickup is triggered by the pickup key/action (e.g. `F` or pet looting) after a mob dies.

## Acceptance criteria

- [ ] `LootController` triggers pickup action sequence when a mob dies in combat.
- [ ] Listens for `LootEvent` emissions from `LootLogReader` to record confirmed pickups.
- [ ] Updates inventory counters and recipe progress metrics in `WorldState`.
- [ ] Handles pickup timeout and resumes patrol if no items are received after configured wait duration.
- [ ] Automated unit tests verify loot state machine transitions and drop accounting.
- [ ] All user-visible logs and messages exist in German and English.

## Out of scope

- Complex bag inventory sorting or vendor selling routines.

## Verification

- Automated: Unit tests simulating kill-to-loot transition and drop event recording; `./scripts/check.ps1`.
- Manual (Windows): Slay a mob in game client, verify pickup execution, and check drop tally output.
