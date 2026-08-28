---
id: US-085
title: Production readiness, first-run wizard autostart, and autonomous farming polish
status: ready
created: 2026-08-28
updated: 2026-08-28
---

# US-085: Production Readiness, First-Run Wizard Autostart, and Autonomous Farming Polish

## Story

As a **Flyff bot operator**,
I want **the desktop application and autonomous farming engine to seamlessly guide first-run setup, cleanly autoload verified client data, handle execution states defensively without unhandled crashes, and reliably execute combat, looting, and recovery in live gameplay**,
so that **I have a completely stable, verified, and productive bot for daily unattended farming and questing without technical debt or manual setup friction.**

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Consolidates and completes all remaining productive requirements from:
  - [`docs/user-stories/completed/US-064-continuous-human-like-movement-and-held-key-pathing.md`](completed/US-064-continuous-human-like-movement-and-held-key-pathing.md): Production 3D NavMesh/GPS pathing and guarded key dispatch.
  - [`docs/user-stories/completed/US-078-initial-setup-wizard-and-unified-client-data-extraction.md`](completed/US-078-initial-setup-wizard-and-unified-client-data-extraction.md) & [`docs/bugs/fixed/BUG-033-unified-setup-does-not-ingest-or-autoload-client-data.md`](../bugs/fixed/BUG-033-unified-setup-does-not-ingest-or-autoload-client-data.md): Client data extraction, source manifest, and setup wizard autostart on missing artifacts.
  - [`docs/user-stories/completed/US-080-goal-driven-quest-execution-and-objective-bus.md`](completed/US-080-goal-driven-quest-execution-and-objective-bus.md): Quest objective resolution, teleporter dispatch, and autonomous execution.
  - [`docs/user-stories/completed/US-081-experience-database-and-train-evaluate-promote-loop.md`](completed/US-081-experience-database-and-train-evaluate-promote-loop.md) & [`docs/user-stories/completed/US-082-ml-rl-engineering-quality-gate.md`](completed/US-082-ml-rl-engineering-quality-gate.md): Telemetry persistence, code hygiene, assert removal in production code, and robust error handling.
  - [`docs/user-stories/completed/US-083-authoritative-client-data-fusion-for-yolo-farming.md`](completed/US-083-authoritative-client-data-fusion-for-yolo-farming.md): Mover catalog join, observation interval coherence, target reconciliation, and early YOLO whitelist filtering.
  - [`docs/user-stories/completed/US-084-ml-modifiable-tactical-parameters-and-tuning.md`](completed/US-084-ml-modifiable-tactical-parameters-and-tuning.md): Bounded tactical parameter space and preset management.
- Safety boundaries remain strictly non-negotiable:
  - Game window foreground verification (`is_foreground`) is enforced on all input dispatching.
  - Emergency stop (`END` / `ESC`) immediately halts navigation, releases all held keys, and sets safe state.
  - Process memory access is strictly read-only (`ReadProcessMemory`); no writes or injection.

---

## Acceptance criteria

### 1. First-Run Setup Detection & Seamless Wizard Autostart
- [ ] **Given** a fresh or incomplete installation where mandatory artifacts (`catalog.json`, `source_manifest.json`, world maps, or quest databases) are absent, **when** the desktop application starts (`ui/app.py::run_desktop`), **then** `MainWindow.is_first_run_setup_required()` evaluates to `True` and the setup wizard dialog (`SetupWizardDialog`) opens automatically before the user is allowed to arm autonomous farming.
- [ ] **Given** the setup wizard completes extraction against a valid client directory, **when** the wizard finishes, **then** all generated artifacts (`data/client/catalog.json`, `source_manifest.json`, world maps, quests) are automatically reloaded into the main window and live controllers without requiring an application restart.

### 2. Autoloading and Resilient Capability Readiness
- [ ] **Given** an existing valid installation with extracted client data, **when** the application starts, **then** `catalog.json`, `source_manifest.json`, extracted world maps, and quest databases are loaded automatically on startup.
- [ ] **Given** a client where optional memory profiles (e.g. live player stats or dungeon readers) are not available or not fingerprinted, **when** readiness is evaluated, **then** the bot falls back gracefully to visual HUD / GPS navigation with a clear localized status message, rather than deadlocking the autonomous farming loop.

### 3. Production Code Hygiene & Assertion Removal
- [ ] **Given** all production modules under `src/flyff_bot/`, **when** code is inspected or executed under optimized Python (`-O`), **then** no bare `assert` statements exist in `src/flyff_bot/` for control flow, validation, or invariants; each is replaced by a typed exception (`ValueError`, `RuntimeError`, `KeyError`) or explicit defensive guard.

### 4. Robust Autonomous Farming, Navigation, and Quest Execution
- [ ] **Given** active farming in a configured spawn zone, **when** monsters are detected via YOLO, **then** target candidates are verified against the early whitelist, enriched with authoritative mover catalog data, and approached using 3D NavMesh/GPS pathing.
- [ ] **Given** combat engagement, **when** fighting and looting, **then** target reconciliation verifies the selected target, attack keys are dispatched reliably, combat stall breaks are respected, and loot is collected.
- [ ] **Given** an emergency stop trigger (`END` or `ESC` key) or loss of window foreground focus, **when** moving or attacking, **then** all held keys are released immediately via `PathingInputDispatcher` and the state transitions safely to `PAUSED` or `IDLE`.

### 5. Localization & Quality Gate
- [ ] **Given** any new or updated user-visible diagnostics, status messages, or setup instructions, **when** displayed, **then** all strings are fully synchronized between `src/flyff_bot/locales/de.json` and `src/flyff_bot/locales/en.json`.
- [ ] **Given** the test suite, **when** running `./scripts/check.ps1`, **then** `uv sync --locked`, `ruff check`, `ruff format --check`, `mypy`, and `pytest` pass with 100% success rate and $\ge 85\%$ test coverage.

---

## Out of scope

- Direct memory writing or code injection (`WriteProcessMemory`).
- Online deep reinforcement learning / in-process neural network weight mutation.
- Mount/flying vehicle 3D collision physics.

---

## Verification

### Automated
```powershell
./scripts/check.ps1
```

### Manual (Windows)
1. Start the application on a clean setup: verify the setup wizard automatically prompts for the client path and extracts all tables.
2. Launch Entropia Flyff client, select a spawn zone or quest, and click Start.
3. Observe autonomous navigation, monster targeting, combat, and looting.
4. Press `END` or Alt-Tab out of the game client: verify movement immediately stops and all keys are released.
