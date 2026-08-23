---
id: BUG-025
title: Committed test artifacts mutate the repository
status: reported
severity: medium
created: 2026-08-23
updated: 2026-08-23
---

# BUG-025: Committed test artifacts mutate the repository

## Environment

- Windows version: Windows 11
- Python version: Python 3.14.7 (`uv` environment)
- Application revision: branch `refactor/main-window-feature-slices` (commit `d4a166f`)
- Client/server version: Not applicable (offline unit tests)

## Reproduction

1. Check out commit `d4a166f` in a clean worktree.
2. Run `./scripts/check.ps1`.
3. Run `git status --short`.
4. Inspect `.us065-test-tmp/` and `tests/unit/neuz.exe`.

## Expected behavior

Unit tests should remain hermetic under pytest-provided temporary paths, should not delete directories beneath the current working directory, and should leave a clean checkout unchanged. Binary fixtures should be generated in the test's temporary directory or stored explicitly with their exact bytes and rationale.

## Actual behavior

`tests/unit/test_teleporter_extractor.py::local_temp_path` creates `.us065-test-tmp` under `Path.cwd()`, recursively deletes matching subdirectories before each archive/save case, and writes generated archives and JSON there. Four fixture files are committed. After running the suite on Windows, `.us065-test-tmp/save/out.json` changes because line endings differ between the committed blob and regenerated output. The fake executable also contains mojibake bytes (`4D 5A EF BF BD 00`) rather than an explicit minimal PE fixture representation.

## Impact and frequency

- Impact: Medium. Tests dirty clean checkouts, risk deleting/recreating repository paths during parallel runs, and obscure genuine diffs.
- Frequency: Deterministic whenever the teleporter extractor tests run.

## Regression verification

- [ ] A failing check proves the repository status is unchanged after running the teleporter extractor tests.
- [ ] Tests use pytest-owned temporary paths and no longer recursively remove repository-relative test output.
- [ ] Committed generated artifacts under `.us065-test-tmp` are removed from source control.
- [ ] The full repository gate passes from a clean checkout and leaves it clean.
