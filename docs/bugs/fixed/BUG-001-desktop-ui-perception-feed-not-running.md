---
id: BUG-001
title: Desktop UI does not run perception or detection feed when started
status: resolved
severity: high
created: 2026-08-15
updated: 2026-08-15
---

# BUG-001: Desktop UI does not run perception or detection feed when started

## Environment

- Windows version: Windows 10/11
- Python version: 3.14 (.venv)
- Application revision: HEAD (main)
- Client/server version: Entropia Flyff (neuz.exe)

## Reproduction

1. Start the Flyff game client and log in with the character at a farming spot.
2. Launch the desktop user interface via `uv run python -m flyff_bot ui`.
3. Check the "Debug-Overlay anzeigen" checkbox and/or click "Starten".
4. Observe the UI window and terminal output.

## Expected behavior

Per [US-010](../../user-stories/completed/US-010-pyside6-dashboard-and-overlay.md) and [US-013](../../user-stories/US-013-autonomous-farming-loop-and-orchestration-engine.md), launching the desktop UI and clicking "Starten" should attach to the foreground game window, periodically capture frames, run YOLO mob detection and target verification, update the visible monster count on the dashboard, and display the live video stream with green bounding boxes when the debug overlay is enabled.

## Actual behavior

- The UI window displays "Sichtbare Monster: 0" / "Bot-Status: Pausiert" indefinitely.
- No monster detection boxes or video overlay appear when the checkbox is toggled.
- Clicking "Starten" does not trigger continuous perception capture from the running game client, and a traceback / error occurs in the terminal.

## Impact and frequency

- Impact: High. The graphical dashboard UI cannot be used to monitor or control autonomous farming.
- Frequency: 100% reproducible when launching via `python -m flyff_bot ui`.

## Regression verification

- [x] A failing automated test or deterministic manual check exists reproducing UI lifecycle failure without active worker.
- [x] The check passes after the fix.
- [x] Related documentation is current.
