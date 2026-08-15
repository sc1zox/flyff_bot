---
title: Project overview
status: active
updated: 2026-08-15
sources:
  - ../sources/2026-08-15-repository-bootstrap-request.md
related:
  - architecture.md
  - glossary.md
---

# Project overview

Flyff Bot is a Windows-first Python project for automation that is explicitly allowed by the target
server's rules. Its current implemented scope is deliberately narrow: find a visible `neuz.exe`
window, focus it, and send one keyboard or mouse input through Win32 `SendInput`.

## Boundaries

- The target is Windows with the stable Python version pinned by `.python-version`.
- The emergency stop is the `END` key.
- The local `Entropia/` client installation is runtime context, not source code, and is ignored.
- Process injection, memory manipulation, stealth, anti-cheat evasion, and credential handling are
  outside project scope.
- There is no HTTP boundary, so an ASGI framework or Uvicorn is not currently justified.

## Open product questions

- Which permitted user workflow should be automated first?
- Which Flyff server and written automation rules govern the project?
- Is the intended UI a CLI, Windows desktop UI, local web UI, or a combination?

The requested project constraints are grounded in the captured
[repository bootstrap request](../sources/2026-08-15-repository-bootstrap-request.md). Treat
server-rule assumptions as unverified until a separate authoritative source is added.
