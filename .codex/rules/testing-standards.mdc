---
description: Testing standards, pytest conventions, mocking rules, and coverage thresholds
globs: tests/**/*.py
alwaysApply: false
---

# Testing Standards

Guidelines for unit and integration tests in `flyff_bot`.

## 1. Scope & Isolation

- **Unit Tests**: Place in `tests/unit/`. Pure functions, data models, keymaps, state machines, and localization dictionaries must have deterministic unit tests without hardware dependencies.
- **Mocking External Boundaries**: Mock `ctypes.windll.user32`, display adapters, OpenCV video streams, and PySide6 UI event loops in unit tests.
- **Integration Tests**: Place in `tests/integration/` for component-level pipelines (e.g. state machine + planner simulation).

## 2. Test Quality & Coverage

- Write tests following the **Arrange-Act-Assert (AAA)** pattern.
- Test both happy paths and edge cases (e.g. focus loss, window minimized, emergency stop key pressed, invalid locale key).
- Maintain minimum test coverage of **60%** (enforced by `pytest --cov --cov-fail-under=60`).
