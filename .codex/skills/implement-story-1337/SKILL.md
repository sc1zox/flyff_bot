---
name: implement-story-1337
description: >-
  Implements a user story from docs/user-stories/ end-to-end: orient, plan, build acceptance
  criteria, verify, update documentation, and commit. Use whenever the user asks to implement a
  user story or feature.
---

# Implement a User Story

Detailed playbook for implementing a user story in the flyff_bot repository.

## 1. Read & orient

- **MANDATORY**: Follow the project knowledge workflow first:
  - Read `docs/wiki/index.md`, `docs/wiki/architecture.md`, and relevant decisions in `docs/decisions/`.
  - Read the story file (`docs/user-stories/US-XXX-*.md`) in full — do not work from a summary.
- **OPTIONAL**: Spawn the `researcher` subagent if you need extensive exploration to locate existing logic or patterns.
- Check existing features under `src/flyff_bot/features/`.
- Identify touched layers (CLI, UI/PySide6, domain feature logic, platform adapters/Win32, locales).

## 2. Plan

- **MANDATORY**: For non-trivial stories, spawn the `advisor` or `planner` subagent to generate the architectural plan before writing code.
- Map each acceptance criterion to specific required changes.
- Surface assumptions. **Ask first** only for genuine ambiguity, safety boundaries, or breaking changes.
- Check for existing constants, models, and helpers before creating new ones.

## 3. Implement criterion by criterion

- Smallest correct change per criterion; minimal diff; no unrelated refactoring.
- Adhere strictly to `AGENTS.md` and safety boundaries:
  - Windows API calls require game window foregrounding.
  - Emergency stop mechanism must be preserved.
  - No memory manipulation, process injection, or anti-cheat evasion.
  - All user-visible text must belong in `src/flyff_bot/locales/*.json` (sync `de.json` and `en.json`).
  - Strict Python type hints and clean domain boundaries.

## 4. Verify

- **MANDATORY**: Spawn the `verifier` subagent to run `./scripts/check.ps1` (uv sync, ruff check/format, mypy, pytest) and report exact results.
- Functional core features must have automated unit/integration tests.
- Never report done on red.

## 5. Complete Documentation

- **MANDATORY**: Spawn the `documenter` subagent to:
  - Check off satisfied acceptance criteria (`- [x]`) in the story markdown.
  - Update story status to `completed` with updated date.
  - Move the story file to `docs/user-stories/completed/`.
  - Update `docs/wiki/` (e.g. `architecture.md`, `glossary.md`) and append to `docs/wiki/log.md` if wiki content changed.

## 6. Commit

- **MANDATORY**: Spawn the `committer` subagent to create the commit for you (e.g., `feat(vision): implement mob detection US-003`).
- Do NOT push unless explicitly requested.
