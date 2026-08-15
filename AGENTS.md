# Codex implementation contract

## Mission

Build a small, reliable Windows application for explicitly permitted Flyff automation. Prefer
clear, verifiable behavior over cleverness or speculative architecture.

## Working method

1. Read `docs/wiki/index.md`, then the relevant user story or bug before changing code.
2. State material assumptions. Ask when scope or acceptance criteria would change the solution.
3. Choose the smallest complete change. Do not add abstractions, services, or dependencies for
   hypothetical future use (YAGNI, KISS).
4. Keep edits feature-scoped and avoid unrelated cleanup.
5. Define success in observable terms, implement, and run the narrowest relevant checks.
6. Before handing off, run `./scripts/check.ps1` and update durable documentation when behavior,
   architecture, or a decision changed.

## Architecture and code rules

- Target Windows and the Python version in `.python-version`; use `uv` and `.venv` only.
- Put production code under `src/flyff_bot/`. Group code by feature under `features/`.
- Prefer classes for stateful resources and cohesive behavior; prefer functions for small pure
  transformations. Do not create classes merely to wrap one function.
- Depend inward: CLI -> feature application -> platform adapter. Keep Win32 details out of the CLI.
- Keep public interfaces typed. Use dataclasses, enums, and value objects where they clarify intent.
- Follow DRY only for stable, repeated knowledge. A little duplication is better than the wrong
  abstraction.
- Do not use unexplained literals for business rules, virtual-key codes, defaults, paths, statuses,
  or message identifiers. Give them a named constant, enum, or configuration entry. Obvious local
  syntax such as CLI flag names is allowed.
- All user-visible text belongs in `src/flyff_bot/locales/*.json`; German and English must remain in
  sync. Never assemble sentences from translated fragments.
- Keep modules focused and APIs small. Delete obsolete paths after a verified migration, unless a
  thin compatibility entry point is intentionally documented.
- Add a production dependency only when the standard library cannot meet a current requirement.
- Do not add an HTTP server such as Uvicorn unless an accepted story requires an HTTP boundary.

## Safety boundaries

- Use documented Windows APIs and require the game window to be foregrounded.
- Do not add process injection, memory manipulation, anti-cheat evasion, credential handling, or
  stealth behavior.
- Preserve the emergency stop and document any action that can affect another process.
- Never commit the local game installation, logs, secrets, generated caches, or virtual environment.

## Work items and knowledge

- New behavior starts in `docs/user-stories/`; defects start in `docs/bugs/`. Copy the relevant
  `TEMPLATE.md`, assign a stable ID, and write testable acceptance criteria or reproduction steps.
- Durable facts live in `docs/wiki/`. Raw evidence goes into `docs/sources/` and is immutable after
  ingestion. Follow `docs/wiki/schema.md` for citations, links, indexing, and maintenance.
- Record durable architectural tradeoffs in `docs/decisions/`; do not hide them in chat history.
- Update `docs/wiki/log.md` only for actual wiki ingest, synthesis, or lint operations.

## Required checks

```powershell
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

## Code review rules

- Flag behavior without an acceptance criterion or regression test.
- Flag user-visible literals outside locale resources.
- Flag duplicated business constants, unsafe Win32 handle use, blocking loops without abort checks,
  broad exception swallowing, and unrelated refactors.
- Flag documentation claims that lack a source or are contradicted by newer evidence.

