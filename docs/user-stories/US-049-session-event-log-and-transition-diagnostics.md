---
id: US-049
title: Session Event Log and Transition Diagnostics
status: draft
created: 2026-08-19
updated: 2026-08-19
---

# US-049: Session Event Log and Transition Diagnostics

## Story

As an **operator**, I want **a structured session event log recorded on disk and displayed in the dashboard UI**, so that **I can reliably audit why the bot paused, stopped, stalled, or changed states during unattended runs without guesswork**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to [`docs/wiki/architecture.md`](../wiki/architecture.md), [`docs/wiki/glossary.md`](../wiki/glossary.md), [`docs/decisions/ADR-002-target-architecture-and-pyside6.md`](../decisions/ADR-002-target-architecture-and-pyside6.md), [`docs/user-stories/completed/US-013-autonomous-farming-loop-and-orchestration-engine.md`](completed/US-013-autonomous-farming-loop-and-orchestration-engine.md), [`docs/user-stories/completed/US-028-live-perception-standby-and-focus-workflow.md`](completed/US-028-live-perception-standby-and-focus-workflow.md), and [`docs/user-stories/completed/US-039-combat-obstacle-stall-detection-and-re-navigation.md`](completed/US-039-combat-obstacle-stall-detection-and-re-navigation.md).
- When running unattended, the bot may automatically pause, stall, or stop due to several discrete conditions:
  - Game window foreground focus loss (`is_foreground == False` / `WindowStatus.NOT_FOREGROUND`), which can be caused by Windows background notifications, popups, or focus-stealing applications.
  - Emergency stop trigger (`EMERGENCY_STOPPED` via UI button or <kbd>END</kbd> / `VK_END` hotkey).
  - Obstacle stall / unreachable target (`EngagementBreakReason.OBSTACLE_STALL`).
  - Supervisor reconciliation failures (`FailureFlag.STUCK` or `NO_PROGRESS` during `RECONCILING`).
  - Frame capture failures (`FrameCaptureError` such as minimized or occluded client).
  - Quota / farming goal completion (`FarmingMode.COMPLETED`).
- Currently, when the bot transitions to standby (`Bot-Status: Bereit (Live-Vorschau)`), there is no persistent or inspectable timeline of events explaining the exact timestamp, prior mode, transition trigger, or foreground window details.

## Acceptance criteria

- [ ] Given a farming session start, the application initializes a dedicated per-session log file (e.g. `logs/sessions/session_<timestamp>.jsonl` or `.log`) in a gitignored `logs/` directory.
- [ ] Given any mode transition in `FarmingOrchestrator` (`PAUSED`, `ALIGNING`, `SEARCHING`, `REPOSITIONING`, `TARGETING`, `COMBAT`, `RECONCILING`, `COMPLETED`, `EMERGENCY_STOPPED`), an event is recorded containing ISO-8601 timestamp, previous mode, new mode, and optional contextual reason.
- [ ] Given an automatic pause caused by game window focus loss (`!is_foreground`), the event record includes diagnostic details about the active foreground window (e.g. window title, class name, or process identifier if queryable via Win32 APIs).
- [ ] Given an emergency stop, obstacle stall, supervisor failure, frame capture error, or goal completion, the event record includes the typed reason (`EngagementBreakReason`, `FailureFlag`, `FrameCaptureErrorCode`, or quota progress).
- [ ] Given the dashboard UI (`MainWindow`), a dedicated Diagnostic Event Log view/panel displays recent session events in reverse chronological order with localized timestamps, event badges, and human-readable event summaries.
- [ ] Logging operations are fail-safe: disk I/O errors or formatting errors never interrupt or crash the farming loop or UI event loop.
- [ ] Log files and session directories remain strictly local and are excluded from git version control.
- [ ] All user-visible text in the UI log view is available and synchronized in German (`de.json`) and English (`en.json`).

## Out of scope

- Uploading or streaming log data to an external HTTP server or cloud service.
- Modifying Windows OS focus-stealing prevention policies or intercepting other application windows.
- Continuous full-frame video or screenshot recording during entire farming sessions.

## Verification

- Automated:
  - Unit tests verifying `SessionEventLogger` creates per-session files, formats structured event records, and safely handles file write exceptions.
  - Unit tests verifying `FarmingOrchestrator` emits events on every mode change, pause trigger, stall, and completion.
  - Unit tests verifying UI event log model/widget updates correctly without blocking Qt rendering.
- Manual (Windows):
  - Start a session on Windows, switch focus to another application (e.g. Notepad), verify that the log records a `FOCUS_LOST` event with Notepad's window title, and verify that the UI Event Log panel updates accordingly.
  - Trigger emergency stop with <kbd>END</kbd>, verify `EMERGENCY_STOPPED` is logged and visible.
