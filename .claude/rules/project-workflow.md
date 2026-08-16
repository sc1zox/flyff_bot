---
description: How the agent works here — discipline, verification, subagents, and the story/bug loop
alwaysApply: true
---

# Working Discipline

Project facts (mission, stack, layout, commands, safety boundaries) live in `CLAUDE.md` and `AGENTS.md`.
This rule describes *how to work* within this repository.

## Project Knowledge Workflow

For any non-trivial search, investigation, or task:

1. **Wiki & Architecture first**:
   - Read `docs/wiki/index.md`, `docs/wiki/architecture.md`, `docs/wiki/schema.md`, and relevant decisions in `docs/decisions/`.
   - Open only relevant wiki pages and link authoritative sources.
2. **Feature Mapping**:
   - Features reside in `src/flyff_bot/features/<feature_name>/`.
   - Win32 platform adapters, UI components, and CLI interfaces must maintain clean inward dependency flow.
3. **Targeted Search**:
   - Narrow down paths before running global search.

## Keep changes on a tight leash

- **Plan before non-trivial changes**: For complex features, Claude acts as the advisor/planner directly in-context without needing to spawn a separate subagent. Formulate the implementation plan grounded in project wiki/ADRs before writing code. Perform targeted research first if broad context is needed.
- **Minimum diff**: Change only what the task requires. No drive-by refactors or formatting changes in unrelated files.
- **Isolated Commits**: Staged changes must strictly relate to the specific story or bug.
- **Smallest correct step**: Prefer small, verifiable changes (YAGNI).

## Safety and Localization Invariants

- Game foregrounding must be verified before executing Win32 simulated input.
- Emergency stop shortcut / hook must always be honored.
- No memory manipulation, packet sniffing, anti-cheat evasion, or stealth routines.
- User-visible text belongs strictly in `src/flyff_bot/locales/*.json` (keep German `de.json` and English `en.json` synchronized).

## Verify every change

After edits, run `./scripts/check.ps1` (or the verification steps):
- `uv sync --locked`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy`
- `uv run pytest`

Never report done on red.

## Story / bug loop

1. Driven by a file in `docs/user-stories/` or `docs/bugs/`.
2. Implement criteria step by step, smallest correct change each.
3. Verify via `./scripts/check.ps1`.
4. Update documentation (mark `- [x]`, update status in frontmatter, move to `completed/` or `fixed/`).
5. Commit with a Conventional Commit message.
