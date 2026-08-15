---
name: write-story-bug
description: Writes a user story or bug report after interviewing the user, validates against existing docs, formats it according to project templates, and commits it.
---

# Write User Story or Bug

When the user asks you to write a user story or a bug report, follow this process exactly:

1. **Information Gathering (Interview):**
   - Do NOT write the story/bug immediately.
   - First, interview the user by asking clarifying questions to gather all necessary requirements, constraints, and edge cases.
   - Conduct a requirements pass to align on edge cases, safety boundaries (e.g. game foregrounding, emergency stop), failure modes, and localization requirements (German/English sync).

2. **Validation against Existing Items & Wiki:**
   - Read `docs/wiki/index.md`, `docs/wiki/architecture.md`, `docs/decisions/`, `docs/user-stories/`, and `docs/bugs/`.
   - Ensure the new story/bug does not duplicate existing items and link relevant wiki articles, decisions, or raw sources.
   - Determine the next sequential stable ID (e.g., `US-007` or `BUG-001`).

3. **Writing the User Story (`docs/user-stories/US-XXX-kebab-title.md`):**
   - Use the filename format: `docs/user-stories/US-XXX-kebab-title.md` (lowercase, kebab-case).
   - Follow the exact structure defined in `docs/user-stories/TEMPLATE.md`:
     ```markdown
     ---
     id: US-XXX
     title: Short title
     status: draft
     created: YYYY-MM-DD
     updated: YYYY-MM-DD
     ---

     # US-XXX: Short title

     ## Story

     As a **type of user**, I want **a capability**, so that **an observable benefit**.

     ## Context and assumptions

     - State what is known.
     - Link relevant wiki pages, decisions, bugs, and raw sources.
     - Mark uncertain assumptions explicitly.

     ## Acceptance criteria

     - [ ] Given ..., when ..., then ...
     - [ ] Failure and cancellation behavior is defined.
     - [ ] All user-visible text is available in German and English.

     ## Out of scope

     - Explicitly list adjacent behavior that this story does not implement.

     ## Verification

     - Automated:
     - Manual (Windows):
     ```

4. **Writing the Bug Report (`docs/bugs/BUG-XXX-kebab-title.md`):**
   - Use the filename format: `docs/bugs/BUG-XXX-kebab-title.md` (lowercase, kebab-case).
   - Follow the exact structure defined in `docs/bugs/TEMPLATE.md`:
     ```markdown
     ---
     id: BUG-XXX
     title: Short title
     status: reported
     severity: medium
     created: YYYY-MM-DD
     updated: YYYY-MM-DD
     ---

     # BUG-XXX: Short title

     ## Environment

     - Windows version:
     - Python version:
     - Application revision:
     - Client/server version:

     ## Reproduction

     1. Start from a known state.
     2. Perform one precise action per step.
     3. Record the first observable failure.

     ## Expected behavior

     Describe the behavior required by a story, decision, or documented rule.

     ## Actual behavior

     Describe what happened and attach sanitized evidence.

     ## Impact and frequency

     - Impact:
     - Frequency:

     ## Regression verification

     - [ ] A failing automated test or deterministic manual check exists.
     - [ ] The check passes after the fix.
     - [ ] Related documentation is current.
     ```

5. **Committing:**
   - After successfully writing the file, commit only the new story or bug report.
   - Run `git add <file>` and `git commit -m "docs: add user story US-XXX for [title]"` or `git commit -m "docs: add bug report BUG-XXX for [title]"`.
