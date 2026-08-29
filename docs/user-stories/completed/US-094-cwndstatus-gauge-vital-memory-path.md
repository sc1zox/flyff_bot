---
id: US-094
title: Memory path for vital percentages via CWndStatus gauge floats
status: completed
created: 2026-08-29
updated: 2026-08-29
---

# US-094: Memory path for vital percentages via CWndStatus gauge floats

## Story

As a **bot operator**, I want **HP/MP/FP percentages read from client memory instead of the pixel
HUD reader**, so that **vitals do not depend on screen capture, HUD placement, or resolution**.

## Context and assumptions

- Target client: Entropia Flyff PServer, `Entropia/Entropia/bin64/neuz.exe`,
  SHA-256 `8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5`.
- [ADR-010](../../decisions/ADR-010-client-derived-vital-maxima-are-not-runtime-resolvable.md)
  established that this build computes vital maxima at runtime, so a
  `current * 100 / maximum` ratio cannot be read from a fixed player-struct offset. It recorded
  the `CWndStatus` gauge fill floats as candidate follow-up, and
  [BUG-038](../../bugs/fixed/BUG-038-player-stats-profiler-fails-closed-on-wrapped-vital-ratio-helpers.md)
  carried a "Remaining follow-up" note naming
  `CWndStatus + {0x2168, 0x2194, 0x21C0, 0x21EC, 0x2218} + 0x28` as "0..1 floats".
- This story is the feasibility spike for that candidate: prove an [ADR-006](../../decisions/ADR-006-read-only-process-memory-access.md)-compatible
  bounded read, or formally close it.
- Evidence: [2026-08-29 CWndStatus and player-position static analysis](../../sources/2026-08-29-entropia-cwndstatus-and-player-position-static-analysis.md).

## Outcome

**Not implementable within ADR-006 on this build. Closed without code changes.**

- The gauge members are real: five inline `CWndGauge` structs at
  `CWndStatus + {0x2168, 0x2194, 0x21C0, 0x21EC, 0x2218}` (44-byte stride). HP/MP/FP are gauges
  0/1/2. The fill value is stored at `gauge + 0x28` as a **clamped 0..100 float** (not 0..1),
  written each render tick from the client's own `MulDiv(current, 100, maximum)` — it already
  bakes in the runtime-resolved maximum.
- There is **no fingerprint-stable anchor** to the `CWndStatus` instance: `CWndStatus::OnDraw`
  is a virtual with zero direct callers, the constructor wrapper has zero direct callers
  (class-factory dispatch), and no writable global or statically initialised pointer holds the
  object. Reaching it requires an unbounded walk of the window manager's child collection.
- Vital percentages therefore continue to come from the visual HUD reader
  (`PlayerVitalsReader`), exactly as ADR-010 already decided — now with static-analysis evidence
  rather than a hand-wave. ADR-010 is amended with the closure; the BUG-038 follow-up note is
  corrected.

## Acceptance criteria

- [x] Given the shipped client, when the `CWndStatus` render path is analysed, then whether a
      bounded fingerprinted read can yield HP/MP/FP percentage is decided on recorded evidence.
- [x] Given the analysis, when a bounded read is not provable, then no unverified offset or
      anchor is wired into the player-stat profile or reader (ADR-006, ADR-010, ADR-011
      "no guessed offsets" principle).
- [x] Given the closure, when ADR-010 and BUG-038 are read, then their descriptions of the gauge
      floats are accurate (0..100 float; no bounded anchor).
- [x] Failure and cancellation behavior is defined: on any degraded/absent client-memory vital,
      the pipeline keeps the HUD-reader value via the existing degrade/restore machinery
      (unchanged by this story).
- [ ] All user-visible text is available in German and English — **N/A**, this story adds no
      user-visible text.

## Out of scope

- Any change to `PlayerVitalsReader`, the perception degrade/restore path, or the player-stat
  profile schema.
- Re-analysing a future client build. A build that exposes a fixed vital ratio, a proven
  write-back of the computed maximum, or a stable `CWndStatus*` global can revisit this under a
  new story without a schema change (the `hp`/`mp`/`fp` fields are already optional).
- The generated position-offset defect found during the same analysis — tracked separately in
  [BUG-039](../../bugs/BUG-039-generated-position-offset-false-positive-and-empty-position-world-id-registries.md).

## Verification

- Automated: no code changed; `./scripts/check.ps1` stays green.
- Manual (Windows): none required. The decision rests on the committed static-analysis source.
