---
id: US-001
title: Agentic repository bootstrap
status: done
created: 2026-08-15
updated: 2026-08-15
---

# US-001: Agentic repository bootstrap

## Story

As the project owner, I want a clean Windows/Python repository with durable agent instructions and
Markdown work-item workflows, so that future Codex sessions can implement features consistently.

## Context and assumptions

- Source: [repository bootstrap request](../sources/2026-08-15-repository-bootstrap-request.md).
- `AGENTS.md` is used instead of `agent.md` because Codex discovers the canonical plural filename.
- The current input PoC remains available through a thin compatibility entry point.

## Acceptance criteria

- [x] Git is initialized on `main`, and local client/caches/environments are ignored.
- [x] Stable Python 3.14.7 is pinned, installed, and used by a `.venv` managed with `uv`.
- [x] Production code uses a typed `src` layout and feature-scoped modules.
- [x] German and English UI resources exist; application-owned UI messages use stable keys.
- [x] LLM wiki, raw-source, user-story, bug, and decision workflows exist as Markdown.
- [x] `AGENTS.md` defines Codex implementation, safety, documentation, and verification rules.
- [x] A Windows CI workflow and local quality gate run lint, format, types, and tests.
- [x] No HTTP server dependency is added without an HTTP use case.

## Out of scope

- Selecting or implementing the first full automation workflow.
- Choosing a desktop or browser-based UI.
- Automating any behavior not explicitly permitted by the target server.

## Verification

- Automated: `./scripts/check.ps1`
- Manual: CLI help in German and English; missing-window error and exit code.

