---
description: Python 3.14 style, typing, and architectural idioms for flyff_bot
globs: src/**/*.py,tests/**/*.py
alwaysApply: false
---

# Python Style & Idioms

Strict standards for Python 3.14 code in `flyff_bot`.

## 1. Type Safety & Data Modeling

- **Strict Type Hints**: All function signatures, class attributes, and public APIs must have complete type annotations.
- **Dataclasses & Enums**: Prefer `@dataclass(frozen=True)` or `attrs` for value objects and DTOs. Use `Enum` or `StrEnum` for states, key codes, and statuses.
- **No Unexplained Literals**: Named constants for all virtual-key codes, thresholds, timeouts, and business rules.

## 2. Structure & Design Principles

- **Inward Dependency**: CLI / GUI -> Feature Domain Controller / State Machine -> Platform Adapters (Win32, Vision).
- **Functions vs Classes**:
  - Use pure functions for transformations, coordinate maths, and parsing.
  - Use classes for stateful controllers, worker loops, and resource lifecycles.
  - Do NOT create a class just to wrap a single function.
- **Error Handling**:
  - Never use bare `except:` or catch broad `Exception` without re-raising or logging context.
  - Fail fast on invalid configurations or unrecoverable states.

## 3. Localization (i18n)

- All user-visible strings must be fetched through `get_text(key, lang)` or locale helpers.
- Never hardcode raw user messages in Python files.
- `src/flyff_bot/locales/de.json` and `en.json` must remain strictly in sync.
