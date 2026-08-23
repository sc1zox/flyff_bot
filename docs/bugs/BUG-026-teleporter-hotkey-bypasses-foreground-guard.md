---
id: BUG-026
title: Teleporter hotkey bypasses foreground guard
status: reported
severity: high
created: 2026-08-23
updated: 2026-08-23
---

# BUG-026: Teleporter hotkey bypasses foreground guard

## Environment

- Windows version: Windows 11 (code-path review)
- Python version: Python 3.14.7 (`uv` environment)
- Application revision: branch `refactor/main-window-feature-slices` (commit `d4a166f`)
- Client/server version: Entropia Flyff PServer (`neuz.exe`)

## Reproduction

1. On commit `d4a166f`, call `TeleporterWindowsInput.pulse_teleporter_hotkey()` with any window handle.
2. Trace its adapter method to `WindowsInputController.send_key()`.
3. Move focus to another application immediately before the hotkey pulse.
4. Compare this path with `send_key_while_guarded()`, `type_text_while_guarded()`, and subsequent click handling.

## Expected behavior

US-065 permits teleporter UI interaction only when the configured game window is foregrounded, and the project safety rules require documented Windows APIs with foreground safeguards. Every injected key sequence must continuously verify END/Escape abort state and target-window focus until release, including the initial teleporter-window hotkey.

## Actual behavior

The dispatcher checks `is_foreground()` once before starting its five-action sequence. `pulse_teleporter_hotkey()` calls unguarded `WindowsInputController.send_key()`: that helper checks END/Escape while the key remains held but never checks the target window handle. The remaining search-text, selection-click, and teleport-click actions use guarded helpers. Thus a focus change between the pre-sequence check and the hotkey down-transition allows global virtual-key injection into whichever application becomes foreground.

## Impact and frequency

- Impact: High. Background applications can receive an unintended `V` press, violating the foreground safety boundary.
- Frequency: Deterministically possible on every dispatch whose focus changes during the hotkey pulse; not reproducible as a stable game-state outcome by automated tests alone.

## Regression verification

- [ ] A failing test proves `TeleporterWindowsInput.pulse_teleporter_hotkey()` uses the window-handle-guarded key helper.
- [ ] A failing test proves key release still occurs after abort or focus loss during the pulse.
- [ ] A manual Windows check confirms no key reaches a non-game foreground application after deliberate focus loss.
- [ ] Related safety documentation and tests remain synchronized.
