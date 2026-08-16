# Fix Bug Command

Execute the end-to-end bug fix playbook:
1. Read `docs/wiki/index.md`, `docs/wiki/architecture.md`, and the bug report in `docs/bugs/BUG-XXX-*.md`.
2. Trace root cause and write a failing regression test first.
3. Apply the minimal fix to resolve root cause without drive-by refactors.
4. Run verification (`./scripts/check.ps1`) to ensure test suite passes.
5. Update documentation (mark `- [x]`, update status to `resolved`, move file to `docs/bugs/fixed/`).
6. Create the task commit with conventional commit format.
