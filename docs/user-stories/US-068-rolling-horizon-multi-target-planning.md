---
id: US-068
title: Rolling-horizon multi-target sequencing and lookahead planning
status: draft
created: 2026-08-21
updated: 2026-08-21
---

# US-068: Rolling-horizon multi-target sequencing and lookahead planning

## Story

As a **Flyff bot developer and operator**,
I want **the bot to evaluate candidate target sequences across a rolling time horizon using US-066 value models and limited beam search**,
so that **the bot optimizes overall farming throughput and kills-per-minute rather than greedily picking the nearest single monster**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/decisions/ADR-005-client-folder-asset-access-for-data-extraction.md`](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md)
  - [`docs/decisions/ADR-006-read-only-process-memory-access.md`](../decisions/ADR-006-read-only-process-memory-access.md)
  - [`docs/user-stories/completed/US-054-farming-telemetry-and-adaptive-navigation-dataset.md`](completed/US-054-farming-telemetry-and-adaptive-navigation-dataset.md)
  - [`docs/user-stories/completed/US-066-farming-and-navigation-value-model.md`](completed/US-066-farming-and-navigation-value-model.md): Transition cost and value models.
  - [`docs/user-stories/US-067-unified-tactical-policy-integration.md`](US-067-unified-tactical-policy-integration.md): Tactical policy protocol integration.
- **Problem Statement:**
  Greedy nearest-neighbor selection often leads the character into isolated corners or high-stuck areas, leaving no nearby monsters after the kill.
  A rolling-horizon planner evaluates candidate chains:
  - *Sequence 1:* Player $\to \text{Mob } A \to \text{Mob } C \to \text{Mob } D$ (Dense cluster, expected duration: 7.8s for 3 kills)
  - *Sequence 2:* Player $\to \text{Mob } B \to \text{Mob } E \to \text{Mob } C$ (Alternative cluster, expected duration: 8.5s for 3 kills)
  - *Sequence 3:* Player $\to \text{Mob } C \to \text{Mob } A \to \text{Mob } F$ (Scattered path, expected duration: 11.2s for 3 kills)
- **Receding Horizon Control:**
  The planner evaluates sequences up to horizon $H \in [2, 4]$, but commits **only the first action** in the optimal sequence.
  When the environment changes (new spawns, dead mob despawns, perception updates), the plan is re-evaluated dynamically.

## Functional Requirements & Technical Architecture

### FR-1 – Multi-Target Sequence Generation
- Given $K$ currently valid candidate mobs, the planner generates acyclic target sequences of depth $H \le \text{max\_horizon}$ (default: $H = 3$).
- Sequences must only include mobs that pass deterministic validity (alive, unlocked, in leash, NavMesh reachable).

### FR-2 – Sequence Cost & Throughput Evaluation
- Sequence cost is evaluated by accumulating expected transitions using US-066 models:
  $$\text{TotalCost}(\sigma) = \sum_{i=1}^{|\sigma|} \left( \hat{T}_{\text{travel}}(m_{i-1}, m_i) + \hat{T}_{\text{kill}}(m_i) + \hat{P}_{\text{stuck}}(m_{i-1}, m_i) \cdot \hat{T}_{\text{recovery}} \right) - \lambda \cdot \widehat{V}_{\text{followup}}(m_{|\sigma|})$$
- The objective maximizes kills per unit time:
  $$\max_{\sigma} \frac{|\sigma|}{\text{TotalCost}(\sigma)}$$

### FR-3 – Bounded Beam Search Planner
- To guarantee deterministic runtime ($< 5\text{ ms}$), tree exploration MUST use bounded Beam Search with:
  - Beam width $B \le 5$ (configurable)
  - Search depth $H \le 4$ (configurable)
  - Pre-pruned candidate sets using topological distance bounds.

### FR-4 – Receding Horizon Commitment
- The planner returns only the first target $m_1^*$ of the optimal sequence $\sigma^*$ as the immediate `TacticalAction`.
- The remaining sequence is held as a provisional path and re-validated on the subsequent cycle.

### FR-5 – Dynamic Replanning Triggers
- Replanning is triggered immediately when:
  - Current target dies or is confirmed killed
  - A new monster spawns in the visual field
  - A planned target becomes locked out or despawns
  - A navigation obstacle stall or evasion occurs
  - Target selection timeout expires

### FR-6 – Greedy Fallback
- If sequence generation times out or yields no multi-target chains, the planner falls back to single-step greedy selection without interruption.

## Acceptance criteria

- [ ] **Sequence Generation:** Evaluates acyclic candidate mob sequences up to horizon $H \in [2, 4]$.
- [ ] **Cost Formulation:** Accumulates travel time, kill duration, stuck risk, and final follow-up cluster density using US-066 value models.
- [ ] **Bounded Search Budget:** Beam search maintains execution time $< 5\text{ ms}$ for typical clusters ($\le 20$ visible mobs).
- [ ] **Receding Horizon Execution:** Executes only the first target of the sequence while maintaining a provisional multi-kill plan.
- [ ] **Dynamic Replanning:** Re-evaluates target sequences upon mob death, new YOLO detections, target despawns, or navigation stalls.
- [ ] **Deterministic Fallback:** Times out or empty sequence sets immediately fall back to single-target greedy selection.
- [ ] **Safety Isolation:** Planning logic does not manipulate keyboard/mouse controls or bypass reachability checks.
- [ ] **Localization & Diagnostics:** Status indicators and logs are synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).
- [ ] **Quality Gate:** Automated tests pass `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).

## Out of scope

- Reinforcement Learning policy gradients (handled in US-071/US-073).
- Full TSP (Traveling Salesperson) brute-force combinatorial search across entire map.
- Prediction of hidden spawns outside the calibrated spawn zone metadata.
- Memory write operations (`WriteProcessMemory`).

## Verification

- Automated:
  - Unit tests in `tests/unit/test_multi_target_planner.py` validating sequence generation, cost accumulation, and beam search pruning.
  - Unit tests in `tests/unit/test_receding_horizon.py` validating first-action execution, provisional plan updates, and replanning triggers.
  - Benchmark test verifying $< 5\text{ ms}$ search execution under simulated 20-mob fields.
  - `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows):
  - Run bot in a dense spawn area (e.g. Aibatts / Lawolfs / Mushpoies): observe the bot planning multi-kill paths and moving systematically through mob clusters rather than bouncing back and forth between isolated targets.
