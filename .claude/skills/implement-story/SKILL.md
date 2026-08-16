---
name: implement-story
description: >-
  Implements a user story from docs/user-stories/ end-to-end: orient, plan, build acceptance
  criteria, verify, update documentation, and commit. Use whenever the user asks to implement a
  user story or feature.
---

# Implement a User Story

Detailed playbook for implementing a user story in the flyff_bot repository.

## 1. Read & Orient

- **MANDATORY**: Follow the project knowledge workflow first:
  - Read `docs/wiki/index.md`, `docs/wiki/architecture.md`, and relevant decisions in `docs/decisions/`.
  - Read the story file (`docs/user-stories/US-XXX-*.md`) in full — do not work from a summary.
- **OPTIONAL**: Perform codebase search or investigate if you need extensive exploration to locate existing logic or patterns.
- Check existing features under `src/flyff_bot/features/`.
- Identify touched layers (CLI, UI/PySide6, domain feature logic, platform adapters/Win32, locales).

## 2. Plan

- **MANDATORY**: For non-trivial stories, generate an architectural plan before writing code.
- Map each acceptance criterion to specific required changes.
- Surface assumptions. **Ask first** only for genuine ambiguity, safety boundaries, or breaking changes.
- Check for existing constants, models, and helpers before creating new ones.

## 3. Implement Criterion by Criterion

- Smallest correct change per criterion; minimal diff; no unrelated refactoring.
- Adhere strictly to `CLAUDE.md`, `AGENTS.md`, and safety boundaries:
  - Windows API calls require game window foregrounding.
  - Emergency stop mechanism must be preserved.
  - No memory manipulation, process injection, or anti-cheat evasion.
  - All user-visible text must belong in `src/flyff_bot/locales/*.json` (sync `de.json` and `en.json`).
  - Strict Python type hints and clean domain boundaries.

## 4. Verify

- **MANDATORY**: Run `./scripts/check.ps1` (`uv sync --locked`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest`) and report exact results.
- Functional core features must have automated unit/integration tests.
- Never report done on red.

## 5. Complete Documentation

- **MANDATORY**: Update documentation:
  - Check off satisfied acceptance criteria (`- [x]`) in the story markdown.
  - Update story status to `completed` with updated date.
  - Move the story file to `docs/user-stories/completed/`.
  - Update `docs/wiki/` (e.g. `architecture.md`, `glossary.md`) and append to `docs/wiki/log.md` if wiki content changed.

## 6. Commit

- Create the commit (e.g., `feat(vision): implement mob detection US-003`).
- Do NOT push unless explicitly requested.
