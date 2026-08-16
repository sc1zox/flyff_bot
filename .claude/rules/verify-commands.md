---
description: Verification commands and test execution reference for flyff_bot
alwaysApply: false
---

# Verification Commands

Commands to verify changes before reporting tasks as completed.

## 1. Full Project Verification Suite (Standard Gate)

Run the full gate script from the project root:

```powershell
pwsh -File .\scripts\check.ps1
```

This runs:
1. `uv sync --locked`
2. `uv run ruff check .`
3. `uv run ruff format --check .`
4. `uv run mypy`
5. `uv run pytest`

## 2. Individual Targeted Checks

- **Format Code**:
  ```powershell
  uv run ruff format .
  ```
- **Lint Code**:
  ```powershell
  uv run ruff check . --fix
  ```
- **Type Check**:
  ```powershell
  uv run mypy
  ```
- **Run Unit Tests Only**:
  ```powershell
  uv run pytest tests/unit/
  ```
- **Run Single Test File**:
  ```powershell
  uv run pytest tests/unit/test_keymap.py -v
  ```
