---
name: fix-bug
description: >-
  Fixes a bug from docs/bugs/ end-to-end: understand, reproduce with a failing test, find root cause,
  apply minimum fix, verify, update documentation, and commit. Use whenever fixing a reported bug or defect.
---

# Fix a Bug

Detailed playbook for fixing a bug in the flyff_bot repository.

## 1. Understand & Reproduce

- **MANDATORY**: Read `docs/wiki/index.md`, `docs/wiki/architecture.md`, and the bug report in `docs/bugs/BUG-XXX-*.md`.
- Trace code paths across relevant files under `src/flyff_bot/`.
- For logic, input calculation, OCR, vision, or localization bugs: write a failing regression test first.
- For OS/visual-only quirks: reason from code, documentation, and error traces.
- Find the root cause before changing anything — do not patch symptoms.

## 2. Plan the Minimum Fix

- Determine the smallest change that corrects the root cause with minimum diff.
- Consult architecture docs if the bug touches Win32 handles, threading/Qt event loop, safety stop, or architecture boundaries (assess directly in-context; no advisor subagent spawn needed).

## 3. Apply the Fix

- Fix the root cause in the relevant module under `src/flyff_bot/features/`.
- Ensure all safety rules remain enforced (foreground checks, emergency stops).
- Keep `src/flyff_bot/locales/*.json` synchronized if text changes.

## 4. Regression-Test

- Run the regression test written in step 1 to confirm it now passes (green).

## 5. Verify

- **MANDATORY**: Run `./scripts/check.ps1` (`uv sync --locked`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest`).
- Never report done on red.

## 6. Complete Documentation

- **MANDATORY**: Update documentation:
  - Check off regression verification criteria in `docs/bugs/BUG-XXX-*.md`.
  - Update status to `resolved` and set `updated: YYYY-MM-DD`.
  - Move the bug file to `docs/bugs/fixed/`.
  - Update wiki docs or decisions if the bug fix established a new architectural invariant.

## 7. Commit

- Create the commit (e.g., `fix(input): resolve key stuck state BUG-001`).
- Do NOT push unless explicitly requested.
