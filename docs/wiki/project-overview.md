---
title: Project overview
status: active
updated: 2026-08-19
sources:
  - ../sources/2026-08-15-repository-bootstrap-request.md
  - ../sources/2026-08-19-target-server-entropia-pserver-clarification.md
related:
  - architecture.md
  - glossary.md
---

# Project overview

Flyff Bot is a Windows-first Python project for automation that is explicitly allowed by the target
server's rules. The target client is the **Entropia Flyff private server (PServer)** ([entropia.fun](https://entropia.fun))
running the classic native Windows desktop client (`neuz.exe`). All vision models, HUD anchoring
heuristics, window capture mechanisms, and Win32 input injection rely on the classic Entropia Flyff desktop client.

## Boundaries

- The target game client is the native Windows executable `neuz.exe` from the **Entropia Flyff PServer** ([entropia.fun](https://entropia.fun)).
- The operating platform is Windows with the stable Python version pinned by `.python-version`.
- The emergency stop is the `END` key (and `Escape` key in the UI).
- The local `Entropia/` client installation is runtime context, not source code, and is ignored.
- Process injection, memory manipulation, stealth, anti-cheat evasion, and credential handling are
  outside project scope.
- There is no HTTP boundary, so an ASGI framework or Uvicorn is not currently justified.

## Open product questions

- Which permitted user workflow should be automated first?
- Target server confirmed: **Entropia Flyff PServer** (see [target server clarification](../sources/2026-08-19-target-server-entropia-pserver-clarification.md)).
- Is the intended UI a CLI, Windows desktop UI, or a combination? (Answered: native PySide6 desktop UI and CLI).

The requested project constraints are grounded in the captured
[repository bootstrap request](../sources/2026-08-15-repository-bootstrap-request.md) and the
[target server clarification](../sources/2026-08-19-target-server-entropia-pserver-clarification.md).

