---
id: US-076
title: Complete fingerprinted client player stats reader
status: draft
created: 2026-08-23
updated: 2026-08-23
---

# US-076: Complete fingerprinted client player stats reader

## Story

As a **bot operator**, I want **the application to read every available player statistic directly from the exact-fingerprinted Entropia client instead of OCR-reading player HUD values**, so that **automation decisions use authoritative numeric state and stop depending on brittle screen recognition**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Read-only process access is allowed under [ADR-006](../decisions/ADR-006-read-only-process-memory-access.md) only with exact SHA-256 profiles, fixed module-relative addresses or pointer-relative ranges, bounded reads, foreground awareness, and no runtime scanning.
- Existing readers establish the safety pattern for position and camera state ([US-053](completed/US-053-pure-gps-navigation-and-client-profile-configuration.md), [US-056](completed/US-056-client-camera-state-and-projection-matrix-reader.md)).
- “Every available statistic” means every field that can be located and verified for a supported executable profile. Unverified guesses are prohibited.
- Player-stat OCR is removed as a decision input. Other perception systems may remain, but they must not be treated as a fallback for stats delivered by this reader.

## Acceptance criteria

- [ ] Given a supported SHA-256 client profile, when the stats reader polls, then it extracts all configured player statistics through fixed bounded reads, including HP, MP, FP, level, experience, current/max values where the client exposes them, stat attributes, relevant derived combat values, active resource state, and any additional fields proven by static analysis.
- [ ] Given each reading, when values are decoded, then the application receives an immutable snapshot carrying source metadata, timestamp, finite validated values, unknown-field markers, and the client digest used.
- [ ] Given HP is available from the client, when combat, vitals triggers, telemetry, RL observations, and dashboards evaluate player state, then they use the client reading and do not invoke player-vitals OCR.
- [ ] Given MP, FP, level, EXP, attributes, or other exposed stats are required by controllers, when decisions run, then they consume the same immutable snapshot instead of separate ad-hoc visual readers.
- [ ] Given an unsupported executable, missing/malformed profile, closed/minimized/background client, short read, invalid pointer, or non-finite value occurs, when polling runs, then the reader returns a typed diagnostic, emits no fabricated values, closes handles promptly, and marks affected fields unavailable.
- [ ] Given a required live player stat is unavailable, when the central live-state gate evaluates the session, then behavior follows US-077 rather than falling back to OCR.
- [ ] Given profiles are added for x86/x64 builds, when configuration loads, then every address range is validated for type, bounds, overlap policy, pointer width, and fingerprint uniqueness before any process handle opens.
- [ ] Given emergency stop fires or foreground focus is lost, when polling is active, then no unsafe recovery loop starts; reads may continue only within ADR-006 and all input dispatch remains blocked.
- [ ] Failure and cancellation behavior is defined for reader startup, polling, shutdown, client restart, binary update, and profile reload.
- [ ] All user-visible text is available in German and English.

## Out of scope

- Discovering addresses by runtime scanning, pointer chasing, debugging, injection, hooking, writing memory, or bypassing client protections.
- Reading party members, other players, inventory containers, buffs, cooldowns, target identity, or dungeon state unless those fields are explicitly introduced by later stories.
- Removing monster-target OCR or loot OCR; this story removes only reliance on player-stats OCR.
- Guessing offsets from similar clients or accepting unverified community offsets.

## Verification

- Automated:
  - Synthetic process-memory tests cover complete snapshots, partial availability, x86/x64 pointers, malformed profiles, short/non-finite reads, handle cleanup, poll throttling, restarts, and foreground/emergency interactions.
  - Controller tests prove vitals and other consumers use client stats and never request player-vitals OCR.
  - Profile-validation tests reject guessed, overlapping, out-of-bounds, duplicate, or malformed configurations.
  - Localization tests enforce German/English parity; `./scripts/check.ps1` passes.
- Manual (Windows):
  - Record supported executable fingerprints, verify each offset against controlled in-game changes, compare HP/MP/FP/level/EXP/attributes with the client UI, restart/minimize the client, and confirm typed degradation without OCR fallback.
  - Verify END/Escape and focus-loss handling while polling and confirm no client mutation or prohibited API use.
