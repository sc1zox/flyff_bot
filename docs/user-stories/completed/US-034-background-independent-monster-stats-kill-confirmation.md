---
id: US-034
title: Background-independent monster stats reading and reliable kill confirmation
status: done
created: 2026-08-18
updated: 2026-08-18
---

# US-034: Background-independent monster stats reading and reliable kill confirmation

## Story

As an **operator farming with kill verification**, I want the **monster-kills HUD counter to be read
reliably while the game world moves behind the transparent stats window**, so that **combat confirms
a kill from the counter instead of guessing from target HP alone**.

## Context and assumptions

- Follows [US-030](US-030-monster-stats-hud-ocr-diagnostics-and-debug-panel.md) (diagnostics panel)
  and [BUG-012](../../bugs/fixed/BUG-012-monster-stats-ocr-failure-and-misleading-anchor-diagnostics.md)
  (engine-unavailable reporting).
- **This story reverses BUG-012's "the fixed region is the intended mode" decision.** That decision
  was made because no anchor template shipped and raw-colour template matching scored poorly. Both
  causes are removed here: `data/monster_stats.png` now ships as the template, and matching runs on
  the glyph mask instead of raw pixels.
- Measured on `data/monster_stats.png` and
  `data/full_screen_view_with_monster_stats_1600_900_Res.png`: the client renders every stats-HUD
  glyph in one constant colour, BGR `(255, 209, 249)` = HSV `(146, 46, 255)`, with a pure black
  outline. The panel itself has no opaque backing.
- Contrast-based binarization (CLAHE + `adaptiveThreshold`) was verified to fail on the reference
  screenshot: the scenery behind the panel survives thresholding and merges with the glyphs.

## Acceptance criteria

- [x] Given the stats HUD drawn over any game background, when a frame is read, then the glyphs are
      isolated by keying the constant HUD text colour rather than by contrast
      (`extract_hud_text_mask`).
- [x] Given the two shipped screenshots, which show the same window over unrelated scenery, when
      each is keyed, then only glyph pixels survive in both.
- [x] Given `data/monster_stats.png`, when the desktop app starts, then its "Time:" header line is
      loaded as the anchor template (`load_header_anchor_template`), and a missing or unreadable
      file degrades to the fixed region instead of failing startup.
- [x] Given anchor matching runs on glyph masks, when the template and the live frame were captured
      over different backgrounds, then the match still succeeds (measured 1.00 on the reference
      screenshot, versus 0.67 for raw-colour matching, against a 0.85 threshold).
- [x] Given the anchor is not found on a frame, when the reading proceeds, then the documented fixed
      region is read instead and `MonsterStatsMetrics.source` names which crop produced the number.
- [x] Given OCR is far slower than one perception tick, when the pipeline ticks, then the HUD
      counter is sampled on its own interval (`DEFAULT_MONSTER_STATS_INTERVAL_SECONDS`, 0.5 s).
- [x] Given the tick loop runs frame capture and OCR, when the desktop app runs, then those run on a
      dedicated worker thread (`SessionWorker`), never on the Qt GUI thread, and are stopped in
      `closeEvent`.
- [x] Given a trustworthy baseline exists, when the HUD counter rises by any amount, then the kill is
      confirmed; a baseline is only ever taken from a reading whose status is `OK`.
- [x] Given a fresh session, when the dashboard opens, then kill verification is enabled by default.
- [x] Given the stats HUD is English in every client locale, when it is read, then OCR requests only
      the English language pack, so a missing German pack cannot fail it.
- [x] All user-visible text is available in German and English.

## Out of scope

- Bundling a Tesseract binary or its language data with the application (see
  [US-033](../US-033-tesseract-ocr-automated-installation-and-detection.md)).
- Reading any stats-HUD field other than `Monster Kills:`.
- Making the HUD text colour operator-configurable; it is a client constant.

## Verification

- Automated: `tests/unit/test_monster_stats.py` (colour key over three synthetic backgrounds and
  both real screenshots; anchor match across differing backgrounds; fixed-region fallback; anchor
  loading; end-to-end read of `Monster Kills: 13` from the reference screenshot through real
  Tesseract, skipped when the English pack is absent), `tests/unit/test_session_worker.py`,
  `tests/unit/test_combat_controller.py` (baseline gating, `+2` rise, failed reading),
  `tests/unit/test_perception_pipeline.py` (sampling interval).
- Manual (Windows): open the session stats window inside the placement guide, enable
  "Monster-Stats-Debug", confirm the source row reads "Über Kopfzeilen-Anker gefunden" and that the
  kill count tracks the HUD while the character moves through changing scenery.

## Known limitations

- The colour key admits background pixels that happen to fall inside the HUD text colour range
  (hue 130–165, saturation 15–95, value ≥ 215). The anchored crop and the `Monster Kills: <int>`
  pattern both have to agree before a count is accepted, so such pixels degrade the reading rather
  than corrupting the counter.
- The anchor template comes from one client version's font rendering. A client font or HUD scale
  change requires recapturing `data/monster_stats.png`.
