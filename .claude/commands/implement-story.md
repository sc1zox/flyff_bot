# Implement User Story Command

Execute the end-to-end user story implementation playbook:
1. Read `docs/wiki/index.md`, `docs/wiki/architecture.md`, decisions in `docs/decisions/`, and the target story file `docs/user-stories/US-XXX-*.md`.
2. Generate an architectural implementation plan mapping each acceptance criterion.
3. Implement criteria step by step (smallest correct change, strict typing, localization in sync, safety boundaries enforced).
4. Run verification (`./scripts/check.ps1`).
5. Update documentation (mark `- [x]`, update status to `completed`, move file to `docs/user-stories/completed/`, update wiki/log if applicable).
6. Create the task commit with conventional commit format.
