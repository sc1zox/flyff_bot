---
id: BUG-028
title: UI refactor retains private control coupling and stale gate evidence
status: reported
severity: low
created: 2026-08-23
updated: 2026-08-23
---

# BUG-028: UI refactor retains private control coupling and stale gate evidence

## Environment

- Windows version: Windows 11 (static review and automated gate)
- Python version: Python 3.14.7 (`uv` environment)
- Application revision: branch `refactor/main-window-feature-slices` (commit `d4a166f`)
- Client/server version: Not applicable (dashboard code and documentation)

## Reproduction

1. Open `src/flyff_bot/ui/main_window.py` and locate `eventFilter()`.
2. Observe direct access to `WindowControlsCard._is_recording_attack_key`.
3. Run `./scripts/check.ps1` on commit `d4a166f`.
4. Compare the resulting test count and coverage with the architecture page's recorded evidence.

## Expected behavior

After slicing `MainWindow`, collaborators should expose intentional state queries or own their event-filter behavior directly. Durable documentation should record the actual revision's automated gate result and clearly separate automated evidence from outstanding Windows/client validation.

## Actual behavior

`MainWindow.eventFilter()` reads the private `_is_recording_attack_key` attribute even though recording state lives in `WindowControlsCard`. Separately, the current gate reports 735 passed, 2 skipped, and 89.09% coverage, while `docs/wiki/architecture.md` records 750 passed, 2 skipped, and 92.54% coverage. Also, `teleporter_extraction.py` says supported records share seven documented fields although accepted forms include three, seven, eight, and ten fields; the diagnostic message names only 7, 8, and 10.

## Impact and frequency

- Impact: Low. Creates avoidable slice coupling and leaves stale/inconsistent documentation evidence.
- Frequency: Deterministic during maintenance, attack-key recording, and future gate comparison.

## Regression verification

- [ ] A static/architecture test or review checklist prevents `MainWindow` from reaching into collaborator-private state.
- [ ] Documentation states the exact gate result for the reviewed commit and identifies live-client checks separately.
- [ ] Parser comments and diagnostics consistently describe every accepted record shape.
- [ ] The complete repository gate passes.
