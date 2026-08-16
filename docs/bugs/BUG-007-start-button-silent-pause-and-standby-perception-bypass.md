---
id: BUG-007
title: Start button causes silent pause loop on focus mismatch and standby perception is completely bypassed
status: reported
severity: high
created: 2026-08-16
updated: 2026-08-16
---

# BUG-007: Start button causes silent pause loop on focus mismatch and standby perception is completely bypassed

## Environment

- Windows version: Windows 10 / 11 (64-bit)
- Python version: 3.14.7
- Application revision: main
- Client/server version: Classic Flyff / Flyff Universe client with PySide6 desktop dashboard

## Reproduction

1. Launch `uv run python -m flyff_bot ui` while the game client is running.
2. Observe the desktop dashboard while paused: telemetry metrics remain frozen at default placeholder values (`Sichtbare Monster: 0`, `Ziel: nicht konfiguriert`, `HP 100.0% | MP 100.0% | FP 100.0%`), debug overlay / placement guides show no live image data, and no distinct bot status is visible.
3. Click the "Starten" button in the desktop UI.
4. Observe that no in-game actions occur, no visual feedback or error is presented, and the orchestrator immediately reverts to or stays in the paused state.

## Expected behavior

Per [US-010](../user-stories/completed/US-010-pyside6-dashboard-and-overlay.md), [US-013](../user-stories/completed/US-013-autonomous-farming-loop-and-orchestration-engine.md), and [US-028](../user-stories/US-028-live-perception-standby-and-focus-workflow.md):
- In standby mode (paused), the perception pipeline should capture frames and stream real-time vitals, monster counts, target debug metrics, and placement guide overlays to the UI in read-only mode without sending input.
- Clicking "Starten" should bring the game window into the foreground and transition directly into the active farming loop.
- If the game window is not foregrounded, the UI must clearly display a focus waiting/error status (e.g. "Warte auf Spielfokus" / "Spielfenster nicht gefunden") instead of silently pausing without feedback.

## Actual behavior

- In `FarmingOrchestrator.tick()`, `if self._mode in {FarmingMode.PAUSED, ...}: return self._publish(False)` unconditionally skips `PerceptionPipeline.tick()`, leaving `WorldState` unpopulated and `_last_frame=None`.
- When "Starten" is clicked, `start_farming` calls `controller.focus_window(window_handle)` and sets `orchestrator.start()`. However, on the very next 100ms tick, `if not self._input_adapter.is_foreground(self._window_handle): self.pause()` immediately pauses the session if the game window has not yet settled into foreground focus.
- The UI status badge in `MainWindow` overwrites `UI_WORLD_STATUS` ("Sichtbare Monster: X") with `UI_BOT_STATUS`, conflating mob counts with bot states and hiding why nothing is happening.

## Impact and frequency

- **Impact:** Critical usability failure; users cannot verify HUD alignment, vitals reading, or mob detection before starting, and clicking "Starten" silently fails to initiate automation.
- **Frequency:** 100% reproducible on desktop UI startup.

## Regression verification

- [ ] Automated tests in `tests/test_orchestrator.py` verifying standby perception execution and status publishing without input dispatch.
- [ ] Automated tests in `tests/test_main_window.py` verifying status badge separation and window state indications.
- [ ] The checks pass after implementing [US-028](../user-stories/US-028-live-perception-standby-and-focus-workflow.md).
- [ ] Related documentation is current.
