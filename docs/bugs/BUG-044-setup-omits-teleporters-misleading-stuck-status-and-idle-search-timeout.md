---
id: BUG-044
title: Setup wizard omits teleporter extraction, misleading stuck status, and idle in-place search timeout
status: reported
severity: high
created: 2026-08-30
updated: 2026-08-30
---

# BUG-044: Setup wizard omits teleporter extraction, misleading stuck status, and idle in-place search timeout

## Environment

- Windows version: Windows 11 x64
- Python version: 3.14
- Application revision: main
- Client/server version: Entropia Flyff PServer (neuz.exe)

## Reproduction

1. Perform initial setup using the Setup Wizard (`UnifiedClientExtractor` / `SetupWizardDialog`) on a clean client directory.
2. Observe the generated artifacts: `data/navigation/teleporters.json` remains unpopulated (`{"destinations": [], "schema_version": 1}`).
3. Open the main application window and inspect the "Rettung bei ausweglosem Steckenbleiben" (Emergency Recovery) settings panel.
4. Observe the "Teleporter-Ziel" dropdown: it contains only the unassigned entry ("Nicht gewählt" / empty), making it impossible for the operator to configure an emergency teleporter destination without running the separate CLI command `--extract-teleporters`.
5. Start a farming session with character positioned in an area or depression (e.g. a grassy valley/ditch in Eden) where target monsters are in the vicinity but not immediately targeted within the current camera sweep or NavMesh raycast.
6. Observe the bot's behavior in `FarmingMode.SEARCHING`: Because `PathingController` is `IDLE` (no active route/patrol step) and no target mob is selected, `SearchController` continuously rotates the camera in place (`SearchMode.ROTATE` / `SearchMode.SETTLE`) without moving or navigating out along the NavMesh.
7. After the configured timeout expires (e.g. 240 seconds without displacement or combat progress), `EmergencyRecoveryMonitor.observe()` triggers `EmergencyRecoveryAction.UNAVAILABLE` because `destination is None`.
8. Record the observable failure:
   - The bot pauses and sets status to `BotStatus.EMERGENCY_TELEPORT_UNAVAILABLE`.
   - The UI status bar displays the misleading localized message: *"Festgefahren: kein Teleport-Hotkey konfiguriert"* (DE) / *"Stuck: no teleport hotkey configured"* (EN), even though a hotkey (e.g. `V` / `86`) is configured and the actual failure is the absence of a selected teleporter destination.

## Expected behavior

Per [US-051](../user-stories/completed/US-051-teleport-dispatch-simplification-and-emergency-eden-reset.md), [US-088](../user-stories/completed/US-088-unified-client-setup-wizard-and-first-run-flow.md), [US-091](../user-stories/completed/US-091-unified-goal-navigation-fluid-scanning-and-intelligent-unstuck.md), and [US-092](../user-stories/US-092-teleporter-config-target-selection-and-legacy-pruning.md):
1. **Automated Setup Extraction:** The Setup Wizard (`UnifiedClientExtractor.run()`) must extract the client's `TeleportOption` database via `extract_teleporter_catalog()` and save `data/navigation/teleporters.json` alongside world maps, quests, and mover catalogs.
2. **Accurate Emergency Status Localization:** When emergency recovery is triggered without a configured destination (`EmergencyRecoveryConfig.destination is None`), the localized status must state that no destination is selected (*"Festgefahren: kein Teleporter-Ziel gewählt"* / *"Stuck: no teleporter destination selected"*) rather than asserting that no hotkey is configured. If a destination is set but the hotkey is invalid, the status must report the hotkey issue separately.
3. **Active Terrain / Goal Navigation & Avoidance of False Stuck Timeouts:** When the player is in `FarmingMode.SEARCHING` in a designated spawn area without immediate mob visual locks, the bot must not endlessly rotate in place in depressions/valleys until unrecoverable timeout; it must execute active NavMesh patrol / zone exploration to seek out targets and maintain movement progress.

## Actual behavior

1. Teleporter extraction is omitted from `UnifiedClientExtractor` and `SetupWizardDialog`, leaving `teleporters.json` empty on fresh installs.
2. The UI status message for `BotStatus.EMERGENCY_TELEPORT_UNAVAILABLE` misleads the operator by claiming that no hotkey is configured when `destination is None`.
3. In deep terrain / valley locations, the bot remains in `SearchMode.ROTATE` / `SearchMode.SETTLE` standing still in one place without patrolling or navigating outward along the NavMesh, causing the 240s unrecoverable-stuck accumulator to expire on an un-wedged character.

## Impact and frequency

- Impact: High. Emergency recovery cannot function out-of-the-box from the setup wizard, operators receive confusing diagnostics, and characters standing in depressions get paused unnecessarily instead of actively patrolling.
- Frequency: Deterministic on fresh setup and whenever a character stays in search rotation in an area without target locks.

## Regression verification

- [ ] Automated unit test verifies `UnifiedClientExtractor` includes teleporter extraction in `required_datasets()`, `is_first_run_required()`, and `run()`.
- [ ] Automated unit test verifies `_dashboard_status` and localized messages correctly distinguish between missing destination vs. invalid hotkey for emergency teleport.
- [ ] Automated test verifies that search rotation loops in open terrain do not starve NavMesh exploration / patrol waypoints.
- [ ] Related documentation and locale bundles (`de.json`, `en.json`) are updated and synchronized.