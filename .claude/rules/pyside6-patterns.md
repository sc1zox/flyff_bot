---
description: PySide6 (Qt6) UI architecture, thread safety, and signals & slots standards
globs: src/**/ui/**/*.py,src/**/gui/**/*.py
alwaysApply: false
---

# PySide6 GUI Patterns

Standards for the native desktop UI using PySide6 (Qt6) (see `docs/decisions/ADR-002-target-architecture-and-pyside6.md`).

## 1. Thread Separation (Crucial)

- **UI Thread Isolation**: The Qt Main GUI thread must NEVER run blocking bot loops, sleep calls, OCR routines, or vision inferences.
- **Worker Threads**: Long-running loops (bot engine, supervisor, frame capture) must run on dedicated `QThread` or `threading.Thread` workers.
- **Communication via Signals**: Worker threads communicate state changes and metrics to the UI exclusively via Qt Signals & Slots (`Signal(...)`). Never manipulate UI widgets directly from worker threads.

## 2. Component Design & Lifecycle

- **Clean Widget Decomposition**: Split screens into cohesive sub-widgets (`StatusPanel`, `ControlPanel`, `VisionOverlay`, `LogView`).
- **Graceful Teardown**: Override `closeEvent` to ensure worker threads, camera hooks, and global input monitors are safely stopped before the application exits.
- **Dark Theme & Clean Aesthetics**: Use consistent palette styling, proper margins/paddings, and fluid layouts (`QVBoxLayout`, `QHBoxLayout`, `QGridLayout`).
