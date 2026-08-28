---
id: US-087
title: Dedicated ML/RL insights and policy debugging dashboard tab
status: draft
created: 2026-08-28
updated: 2026-08-28
---

# US-087: Dedicated ML/RL Insights and Policy Debugging Dashboard Tab

## Story

As a **Flyff bot developer and operator**,
I want **a dedicated 'ML & Policy' / 'ML & RL' tab in the PySide6 dashboard that displays comprehensive live policy telemetry, candidate rankings, reward breakdowns, experience recording stats, and offline evaluation diagnostics without moving existing combat tab controls**,
so that **I can inspect real-time ML/RL decision-making, monitor inference latency against the 5ms SLA budget, diagnose policy faults and action masks, observe reward progression, and evaluate learned policies with complete transparency and safety.**

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/decisions/ADR-002-target-architecture-and-pyside6.md`](../decisions/ADR-002-target-architecture-and-pyside6.md): PySide6 presentation boundary and thread decoupling.
  - [`docs/decisions/ADR-007-offline-tactical-simulation-boundary.md`](../decisions/ADR-007-offline-tactical-simulation-boundary.md): Fast offline simulation boundary.
  - [`docs/decisions/ADR-008-closed-learning-loop-invariants.md`](../decisions/ADR-008-closed-learning-loop-invariants.md): Parameterized action, decision intervals, candidate instance identity, and fail-closed policy invariants.
  - [`docs/decisions/ADR-009-bounded-tactical-parameter-space.md`](../decisions/ADR-009-bounded-tactical-parameter-space.md): Bounded tactical parameter space and invariant protection.
- Predecessors and related user stories:
  - [`US-010`](completed/US-010-pyside6-dashboard-and-overlay.md): PySide6 dashboard foundation.
  - [`US-050`](completed/US-050-responsive-tabbed-dashboard-and-ui-refactoring.md): Tabbed dashboard layout.
  - [`US-071`](completed/US-071-unified-rl-environment-and-reward.md): Unified RL environment and reward structure.
  - [`US-072`](completed/US-072-offline-farming-and-navigation-simulator.md): Offline farming and navigation simulator.
  - [`US-073`](completed/US-073-hierarchical-rl-farming-navigation-and-quest-policy.md): Hierarchical RL policy runner and action catalog.
  - [`US-079`](completed/US-079-unified-goal-conditioned-decision-contract.md): Goal-conditioned decision contract.
  - [`US-081`](US-081-experience-database-and-train-evaluate-promote-loop.md): Experience database and train-evaluate-promote loop.
  - [`US-082`](US-082-ml-rl-engineering-quality-gate.md): ML/RL engineering quality gate.
  - [`US-084`](completed/US-084-ml-modifiable-tactical-parameters-and-tuning.md): Tactical parameter space and dynamic overrides.
  - [`US-086`](completed/US-086-unattended-autopilot-session-resilience-and-goal-arbitration.md): Autopilot session resilience and diagnostics.
- Existing controls in the `Combat & Targets` tab (combat class selector, policy mode selector, model path input, and `TacticalParametersPanel`) remain in place and operational; the new tab provides deep, specialized inspection and debugging.
- All telemetry and diagnostic data are passed through immutable `DashboardUpdate` structures via Qt signals, preventing any worker thread stalls or UI locking.

---

## Acceptance criteria

### 1. Dedicated Dashboard Tab (`DashboardTab.ML_POLICY`)
- [ ] **Given** the PySide6 `MainWindow`, **when** constructed, **then** an 8th tab named `ML & Policy` (`DashboardTab.ML_POLICY` / index 7) is available in stable index order.
- [ ] **Given** the `ML & Policy` tab, **when** displayed, **then** it follows the application's dark theme, scrollable container pattern (`QScrollArea`), and modular card structure.

### 2. Live Policy & Inference Telemetry Panel
- [ ] **Given** a running or standby farming session, **when** the policy telemetry card renders, **then** it displays:
  - **Policy Mode:** Active mode (`HEURISTIC`, `SHADOW`, `ACTIVE`).
  - **Model Artifact:** Loaded model directory, artifact filename, and SHA-256 digest (or `N/A (Heuristic)`).
  - **Inference Latency:** Last decision inference latency in milliseconds, formatted with a badge indicating SLA adherence (e.g. green $\le 5\,\text{ms}$, yellow $\le 10\,\text{ms}$, red $> 10\,\text{ms}$).
  - **Policy Fault Status:** Active fault indicator (`NONE`, `TIMEOUT`, `MASKED_ACTION`, `NON_FINITE`, `MODEL_MISSING`, `INCOMPATIBLE_SCHEMA`) with fail-closed diagnostics per ADR-008.

### 3. Candidate Evaluation & Decision Inspector
- [ ] **Given** decision ticks with multiple mob candidates, **when** viewing the decision inspector, **then** a structured candidate ranking table presents:
  - Candidate instance index and mob class name.
  - 3D distance and line-of-sight / NavMesh reachability status.
  - Model evaluation score / Q-value estimate.
  - Action mask verdict (Allowed vs. Rejected/Masked).
  - Highlighting for the chosen candidate.
- [ ] **Given** a hierarchical action decision, **when** inspected, **then** the chosen action details are shown: meta-goal, target candidate index, dynamic attack point / approach distance, corridor index, and wait duration.
- [ ] **Given** `SHADOW` policy mode, **when** active, **then** the inspector displays both the heuristic decision and the shadow policy decision side-by-side, tracking a running agreement/disagreement rate.

### 4. Reward & Learning Episode Telemetry Panel
- [ ] **Given** an active session, **when** viewing the reward telemetry card, **then** it displays:
  - Current episode index and step count.
  - Cumulative episode reward and total session reward.
  - Decomposed reward terms: kill cycle rewards, navigation/evasion efficiency penalties/rewards, and objective progress contributions.
  - Episode termination/truncation reason for the last completed episode.

### 5. Experience Database & Offline Evaluation Diagnostic Panel
- [ ] **Given** experience collection, **when** viewing the experience status card, **then** it displays:
  - Total recorded transitions and episodes in the current session.
  - Experience database status (storage path, total records, schema version).
- [ ] **Given** offline evaluation or benchmark data (e.g., from simulator runs or promoted model registries), **when** present, **then** key benchmark metrics (e.g. KPM, travel time, stall rate vs. heuristic baseline) are summarized for operator inspection.

### 6. Dynamic Tactical Parameters & Overrides View
- [ ] **Given** live ML/RL modulation of tactical parameters ([US-084](completed/US-084-ml-modifiable-tactical-parameters-and-tuning.md)), **when** active overrides are emitted, **then** a read-only table compares configured static baseline parameters against dynamic policy offsets (e.g., dynamic approach distance, contextual replan intervals).

### 7. Performance & Thread-Safety Non-Blocking Guarantees
- [ ] **Given** 20 Hz tick rates and high-frequency perception updates, **when** telemetry is published, **then** UI updates are delivered via immutable snapshots without blocking or slowing the background worker thread.
- [ ] **Given** a policy fault or invalid action in `ACTIVE` mode, **when** detected, **then** the UI displays the fail-closed halt state with localized actionable diagnostic details without crashing or locking the application.

### 8. Localization & Synchronized Strings
- [ ] All user-visible titles, card headers, column headers, tooltips, and diagnostic messages are synchronized in German and English locale resources (`src/flyff_bot/locales/de.json` and `src/flyff_bot/locales/en.json`).

---

## Out of scope

- Live in-game training, backpropagation, or online weight updates against the running game client.
- Modifying OS-level Win32 input dispatch routines or bypassing window focus / emergency stop checks.
- Removing or altering the existing control layout in `DashboardTab.COMBAT_TARGETS`.

---

## Verification

### Automated
```powershell
uv run pytest tests/unit/test_ui.py tests/unit/test_main_window.py tests/unit/test_learning_loop.py tests/unit/test_tactical_parameters.py
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

### Manual (Windows)
1. Launch the dashboard: `uv run python -m flyff_bot --dashboard`.
2. Navigate to the new `ML & Policy` tab.
3. Switch policy mode between `HEURISTIC`, `SHADOW`, and `ACTIVE`:
   - Verify that the model artifact status, latency badge, and fault indicators update accurately.
   - Verify candidate evaluation tables display candidate instances, Q-values, and action masks.
   - In `SHADOW` mode, verify that shadow vs. heuristic decisions and agreement rates update live.
4. Verify reward telemetry cards display decomposed reward terms and cumulative totals.
5. Verify language switching between German and English updates all headers, table columns, and tooltips seamlessly.
6. Verify emergency stop (`F12` / `Ctrl+Shift+Q`) immediately halts execution and reflects in the UI.
