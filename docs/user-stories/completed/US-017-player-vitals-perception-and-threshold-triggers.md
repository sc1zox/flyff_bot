---
id: US-017
title: Player vital gauges perception and threshold-based auto-consumable triggers
status: completed
created: 2026-08-15
updated: 2026-08-16
---

# US-017: Player vital gauges perception and threshold-based auto-consumable triggers

## Story

As a player using the bot and desktop dashboard, I want the bot to extract my character's vital gauge levels (HP, MP, FP) directly from the top-left HUD region of captured window frames via pure pixel-color analysis and trigger configured consumable hotkeys (e.g. food/potions on low HP, refreshers on low MP, vital drinks on low FP) when values drop below user-defined percentage thresholds, so that my character stays alive and combat-ready automatically without manual intervention.

## Context and assumptions

- **Architectural Dependencies:**
  - Depends on [US-002](US-002-vision-frame-capture.md) (`WindowsFrameSource` / `FrameSource` protocol) for raw client-space numpy frames.
  - Depends on [US-007](US-007-perception-worldstate-feed.md) (`PerceptionPipeline` / `WorldState`) to inject a typed `PlayerVitals` object into `WorldState.player_vitals`.
  - Depends on [US-014](US-014-configurable-ui-attack-key.md) for hotkey configuration, persistence, and key-press dispatching.
  - Extends the farming orchestration loop in [US-013](US-013-autonomous-farming-loop-and-orchestration-engine.md).
- **HUD Layout & Perception (Top-Left Vitals Orb):**
  - In the Entropia Flyff PServer (`neuz.exe`) client, the player's status orb is anchored in the top-left corner of the window.
  - It contains three horizontal color gauge bars:
    - **HP (Health Points):** Red bar (dominant red channel).
    - **MP (Mana Points):** Blue bar (dominant blue channel).
    - **FP (Fatigue Points):** Green/Yellow bar (dominant green/red channels).
  - Perception is performed using **pure pixel-color thresholding** across configurable Region of Interest (ROI) sub-regions relative to the top-left client area (no YOLO, no neural network inference overhead).
  - Pixel measurement calculates active colored pixel count vs. full-bar pixel width/area to yield precise fill percentages (`0.0%` to `100.0%`).
- **Trigger Logic, Debounce & Safety:**
  - Users can configure threshold triggers for HP, MP, and FP (e.g. HP < 70% -> press `F1` (Food/Potion), MP < 30% -> press `F2` (Refresher), FP < 20% -> press `F3` (Vital Drink)).
  - To prevent input spamming, each trigger enforces a configurable debounce cooldown (default 800 ms) before the same hotkey can be triggered again while the gauge remains below threshold.
  - **Priority:** Critical HP recovery takes precedence over routine attack rotations ([US-008](US-008-reactive-combat-controller.md)) and periodic timed buffs.
  - **Safety boundaries:** Keystrokes are dispatched only when the Flyff client window is foregrounded and the emergency stop (`END` key) is not active.
- **UI & Localization:**
  - The dashboard UI exposes threshold configuration (enabled, target vital HP/MP/FP, threshold percentage slider/spinbox, hotkey, and debounce cooldown).
  - All user-visible labels, headers, and tooltips are synchronized in German (`de.json`) and English (`en.json`).

## Acceptance criteria

- [x] `PlayerVitalsReader` extracts HP, MP, and FP percentages from the top-left status orb region of captured client frames using pure pixel-color thresholding.
- [x] `WorldState` includes a typed `player_vitals: PlayerVitals` field with `hp_percentage: float`, `mp_percentage: float`, `fp_percentage: float` (each bounded `0.0` to `100.0%`).
- [x] Perception pipeline integrates `PlayerVitalsReader` into the per-frame capture cycle and updates `WorldState` snapshot deterministically.
- [x] `VitalsTriggerController` evaluates `WorldState.player_vitals` against configured rules:
  - Trigger when `hp_percentage <= configured_threshold`
  - Trigger when `mp_percentage <= configured_threshold`
  - Trigger when `fp_percentage <= configured_threshold`
- [x] Configurable debounce / spam-protection timer (default 800 ms) per slot prevents repeated key hammering while below the threshold.
- [x] Priority handling: low-HP emergency triggers are prioritized ahead of attack rotation skills and timed buffs.
- [x] Keystrokes are guarded by window focus verification and the `END` emergency stop; inputs are dropped or deferred safely if focus is lost.
- [x] Dashboard UI and debug overlay provide real-time visualization of detected vital gauge values (HP, MP, FP percentage readouts) for operator feedback and debugging.
- [x] Dashboard UI provides configuration controls (vital type, threshold %, hotkey, cooldown ms, enabled toggle) with persistent disk storage.
- [x] All UI labels, tooltips, and status strings are synchronized in German and English (`de.json` and `en.json`).
- [x] Automated unit tests in `tests/unit/` verify:
  - Pixel measurement on synthetic/fixture images of full, half, empty, and edge-case HP/MP/FP bars.
  - Trigger firing on threshold drop, debounce cooldown enforcement, and state recovery.
  - Focus loss and emergency stop prevention.
  - Persistence serialization/deserialization of vital trigger configurations.

## Out of scope

- OCR text recognition of numerical HP/MP numbers overlaying the bars.
- Automatic inventory replenishment or shop-purchasing when potions/food run out.
- Dynamic party-member healing or targeting (strictly self-character vitals).

## Verification

- Automated: Unit tests in `tests/unit/test_player_vitals.py` and `tests/unit/test_vital_triggers.py`; `./scripts/check.ps1`.
- Manual (Windows):
  1. Launch `uv run python -m flyff_bot ui`.
  2. Configure an HP trigger: `F1` at `<= 70%` HP with 800 ms debounce.
  3. Start the bot with Flyff window active; take damage in-game.
  4. Verify that `F1` is pressed when HP drops below 70% and throttled to once every 800 ms until HP is restored.
  5. Verify that pressing `END` immediately halts all trigger dispatches.
