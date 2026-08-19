# Claude Implementation Contract & Repository Guide

## Mission

Build a small, reliable Windows application for explicitly permitted Flyff automation. Prefer
clear, verifiable behavior over cleverness or speculative architecture.

## Working Method

1. Read `docs/wiki/index.md`, then the relevant user story or bug before changing code.
2. State material assumptions. Ask when scope or acceptance criteria would change the solution.
3. Choose the smallest complete change. Do not add abstractions, services, or dependencies for
   hypothetical future use (YAGNI, KISS).
4. Keep edits feature-scoped and avoid unrelated cleanup.
5. Define success in observable terms, implement, and run the narrowest relevant checks.
6. Before handing off, run `./scripts/check.ps1` and update durable documentation when behavior,
   architecture, or a decision changed.

## Architecture and Code Rules

- Target Windows and the Python version in `.python-version` (Python 3.14); use `uv` and `.venv` only.
- Put production code under `src/flyff_bot/`. Group code by feature under `features/`.
- Prefer classes for stateful resources and cohesive behavior; prefer functions for small pure
  transformations. Do not create classes merely to wrap one function.
- Depend inward: CLI / UI -> feature application / state machine -> platform adapter. Keep Win32 details out of the CLI.
- Keep public interfaces typed. Use dataclasses, enums, and value objects where they clarify intent.
- Follow DRY only for stable, repeated knowledge. A little duplication is better than the wrong
  abstraction.
- Do not use unexplained literals for business rules, virtual-key codes, defaults, paths, statuses,
  or message identifiers. Give them a named constant, enum, or configuration entry. Obvious local
  syntax such as CLI flag names is allowed.
- All user-visible text belongs in `src/flyff_bot/locales/*.json`; German (`de.json`) and English (`en.json`) must remain in
  sync. Never assemble sentences from translated fragments.
- Keep modules focused and APIs small. Delete obsolete paths after a verified migration, unless a
  thin compatibility entry point is intentionally documented.
- Add a production dependency only when the standard library cannot meet a current requirement.
- Do not add an HTTP server such as Uvicorn unless an accepted story requires an HTTP boundary.

## PySide6 GUI Standards

- **UI Thread Isolation**: The Qt Main GUI thread must NEVER run blocking bot loops, sleep calls, OCR routines, or vision inferences.
- **Worker Threads**: Long-running loops (bot engine, supervisor, frame capture) must run on dedicated `QThread` or `threading.Thread` workers.
- **Communication via Signals**: Worker threads communicate state changes and metrics to the UI exclusively via Qt Signals & Slots (`Signal(...)`). Never manipulate UI widgets directly from worker threads.
- **Clean Widget Decomposition**: Split screens into cohesive sub-widgets (`StatusPanel`, `ControlPanel`, `VisionOverlay`, `LogView`).
- **Graceful Teardown**: Override `closeEvent` to ensure worker threads and platform hooks are safely stopped before exit.

## Safety Boundaries

- Use documented Windows APIs and require the game window to be foregrounded before sending input.
- Automatically pause and release all keys if the game window loses focus.
- Read-only access to the game client's process memory (`ReadProcessMemory`) is permitted for
  reading live game state (world coordinates, camera state, projection matrices, player/actor
  data, and client structures).
- Do not add process injection, memory writes (`WriteProcessMemory`), code hooking, anti-cheat evasion,
  credential handling, or stealth behavior.
- Preserve the emergency stop hotkey / killswitch (e.g. `F12` / `Ctrl+Shift+Q`) to immediately release keys and halt execution.
- Never commit the local game installation, logs, secrets, generated caches, or virtual environment.

## Work Items and Knowledge

- New behavior starts in `docs/user-stories/`; defects start in `docs/bugs/`. Copy the relevant
  `TEMPLATE.md`, assign a stable ID, and write testable acceptance criteria or reproduction steps.
- Durable facts live in `docs/wiki/`. Raw evidence goes into `docs/sources/` and is immutable after
  ingestion. Follow `docs/wiki/schema.md` for citations, links, indexing, and maintenance.
- Record durable architectural tradeoffs in `docs/decisions/`; do not hide them in chat history.
- Update `docs/wiki/log.md` only for actual wiki ingest, synthesis, or lint operations.

## Required Verification Checks

```powershell
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```
Or run the gate script:
```powershell
pwsh -File .\scripts\check.ps1
```

## Subagent / Role Playbooks

- **`advisor`**: Built-in to Claude natively in-context (no separate subagent spawn needed); provides strategic advice on architecture, ADRs, and safety constraints.
- **`planner`**: Implementation breakdown and planning.
- **`researcher`**: Read-only investigation and codebase navigation.
- **`verifier`**: Verification suite execution (`scripts/check.ps1`).
- **`documenter`**: Updating user story / bug acceptance criteria, moving files to completed/fixed, and updating wiki.
- **`committer`**: Conventional Git commits scoped to the specific task.

## Available Workflows / Skills

- **Implement Story**: Follow `.claude/skills/implement-story/SKILL.md`
- **Fix Bug**: Follow `.claude/skills/fix-bug/SKILL.md`
- **Write Story/Bug**: Follow `.claude/skills/write-story-bug/SKILL.md`
