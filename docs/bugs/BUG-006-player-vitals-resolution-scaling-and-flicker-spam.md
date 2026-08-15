---
id: BUG-006
title: Player vitals gauge extraction fails across arbitrary resolutions causing consumable item spam
status: reported
severity: high
created: 2026-08-16
updated: 2026-08-16
---

# BUG-006: Player vitals gauge extraction fails across arbitrary resolutions causing consumable item spam

## Environment

- Windows version: Windows 10 / 11 (64-bit)
- Python version: 3.14.7
- Application revision: main
- Client/server version: Classic Flyff client (v15–v22) at arbitrary window/screen resolutions (e.g., 1024x768, 1280x720, 1920x1080, 2560x1440)

## Reproduction

1. Launch `uv run python -m flyff_bot ui` and configure vitals triggers (e.g. HP <= 70% -> `F1`, MP <= 30% -> `F2`, FP <= 20% -> `F3`).
2. Attach the bot to a Flyff game client running at 1920x1080 (or any resolution higher than the reference 260x113 crop).
3. Start the farming session with full HP/MP/FP.
4. Observe the live dashboard readout and character in-game actions.
5. Notice that the perceived vital percentages fluctuate wildly (jumping between 0.0% and random values) or drop to 0.0% when background scenery shifts behind the top-left area.
6. Observe that consumable hotkeys (Food, Potions, Refreshers, Vital Drinks) are continuously spammed on every debounce cycle despite the character having full gauges.

## Expected behavior

Per [US-017](../user-stories/completed/US-017-player-vitals-perception-and-threshold-triggers.md):
- Player vitals perception must reliably extract HP, MP, and FP fill percentages regardless of the game client's window dimensions and resolution.
- When player vitals are full, the gauge values should read ~100.0% stably without noise or false drops.
- Consumable items must only be triggered when the character's vital gauge actually drops below the configured threshold.

## Actual behavior

- `PlayerVitalsReader` uses normalized relative crop bounds (`hud_right = 0.25`, `hud_bottom = 0.20`) applied directly to the full client dimensions. On a 1920x1080 client, this extracts a 480x216 region instead of the fixed ~260x113 HUD orb.
- Sub-region gauge bar coordinates (`region.left = 0.415`, `region.right = 0.946`) are then scaled against the 480-pixel crop ($X \in [199..454]$), sampling 3D game world pixels (sky, terrain, mobs) outside the actual 260-pixel HUD element.
- When background pixels do not match the expected bar colors, `_measure_gauge` yields `0.0%`.
- Because `0.0% <= threshold%` evaluates to `True`, the reactive trigger controller fires consumable keys repeatedly every 800 ms.

## Impact and frequency

- **Impact:** Critical game disruption; player inventory is depleted by rapid consumable item spam (potions, refreshers, food), and emergency recovery preempts legitimate combat actions.
- **Frequency:** 100% reproducible on any client resolution other than small HUD crop windows.

## Regression verification

- [ ] A failing automated test reproducing `PlayerVitalsReader` on full 1024x768, 1280x720, and 1920x1080 frames with fixed top-left HUD dimensions exists.
- [ ] The check passes after implementing resolution-independent fixed-pixel HUD anchoring / template-matched alignment and anti-flicker filtering.
- [ ] Related documentation in `docs/wiki/architecture.md` is updated.
