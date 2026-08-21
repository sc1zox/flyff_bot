---
id: US-070
title: Learned attack point positioning and local waypoint optimization
status: draft
created: 2026-08-21
updated: 2026-08-21
---

# US-070: Learned attack point positioning and local waypoint optimization

## Story

As a **Flyff bot developer and combat tactician**,
I want **the policy to select optimal approach attack points and localized corridor waypoints inside valid engagement zones rather than blindly running to the monster's exact coordinate**,
so that **the character minimizes approach travel time, avoids geometry obstacles, and finishes combat favorably positioned for the next target**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/decisions/ADR-005-client-folder-asset-access-for-data-extraction.md`](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md)
  - [`docs/decisions/ADR-006-read-only-process-memory-access.md`](../decisions/ADR-006-read-only-process-memory-access.md)
  - [`docs/user-stories/US-060-combat-class-profiles-responsive-direct-targeting-and-lockout-minimization.md`](US-060-combat-class-profiles-responsive-direct-targeting-and-lockout-minimization.md): Class engagement distances.
  - [`docs/user-stories/completed/US-066-farming-and-navigation-value-model.md`](completed/US-066-farming-and-navigation-value-model.md)
  - [`docs/user-stories/US-067-unified-tactical-policy-integration.md`](US-067-unified-tactical-policy-integration.md)
  - [`docs/user-stories/US-069-experience-based-navmesh-routing.md`](US-069-experience-based-navmesh-routing.md)
- **Problem Statement:**
  Directly navigating to $\mathbf{p}_{\text{mob}} = (x, y, z)$ forces the character into the monster's exact center, which causes:
  1. Unnecessary running distance (running into point-blank range even when attack range is 3m or 15m).
  2. Sub-optimal line of sight with geometry behind the monster.
  3. Ending the fight facing away from the next spawn cluster, requiring extra turning and travel time for the next target.
- **Attack Region & Positioning Model:**
  - An attack region is modeled as an annulus on the NavMesh centered at $\mathbf{p}_{\text{mob}}$ with radius $[r_{\text{min}}, r_{\text{max}}]$ determined by character class profile (melee vs ranged).
  - Candidate attack points $\{ \mathbf{p}_k \}$ are sampled along the valid NavMesh perimeter.
  - Objective function evaluates:
    $$\text{Score}(\mathbf{p}_k) = \hat{T}_{\text{approach}}(\mathbf{p}_k) + P_{\text{stuck}}(\mathbf{p}_k) \cdot \hat{T}_{\text{recovery}} + w_{\text{turn}} \Delta \theta + w_{\text{next}} d(\mathbf{p}_k, \text{NextTarget})$$

## Functional Requirements & Technical Architecture

### FR-1 – Attack Point Sampling
- Given a target mob and character class profile (melee: 2.5–3.5m, ranged: 10–14m), the sampler generates $M$ candidate attack points $\{ \mathbf{p}_1, \dots, \mathbf{p}_M \}$ on the NavMesh.
- Points outside NavMesh walkable polygons or exceeding maximum slope limits are filtered out.

### FR-2 – Multi-Criteria Attack Point Evaluation
- Candidate attack points are scored considering:
  1. *Approach Travel Time:* Estimated time from current player position to $\mathbf{p}_k$.
  2. *Stuck & Obstacle Risk:* Empirical terrain cost and obstacle clearance around $\mathbf{p}_k$.
  3. *Heading & Turn Cost:* Required character rotation angle to engage the mob and view follow-up spawns.
  4. *Follow-up Target Proximity:* Proximity to expected subsequent targets or high-density spawn clusters.

### FR-3 – Local Waypoint & Corridor Refinement
- The policy may refine intermediate navigation waypoints within the active NavMesh corridor to smooth the approach trajectory.
- Waypoints MUST remain strictly within the convex NavMesh corridor bounds.

### FR-4 – Dynamic Recalculation on Target Movement
- If the monster moves significantly ($\Delta \mathbf{p} > 2.0\text{ m}$), candidate attack points are updated dynamically.

### FR-5 – Deterministic Fallback
- If attack point generation fails or times out, the system defaults to direct Funnel waypoint navigation towards the mob center.

## Acceptance criteria

- [ ] **Attack Point Sampling:** Generates candidate attack points within class engagement radius on walkable NavMesh polygons.
- [ ] **Multi-Criteria Scoring:** Scores points using approach travel time, terrain clearance, turn angle, and distance to anticipated follow-up targets.
- [ ] **Corridor Boundary Safety:** All generated attack points and local waypoints stay strictly inside validated NavMesh polygons.
- [ ] **Melee & Ranged Profile Support:** Correctly sizes engagement radii for melee (3m) and ranged (12–15m) profiles.
- [ ] **Target Movement Handling:** Re-samples and updates attack points dynamically when targets move.
- [ ] **Deterministic Fallback:** Times out or unresolvable geometries fall back cleanly to direct Funnel navigation.
- [ ] **Performance:** Attack point sampling and scoring complete in $< 1\text{ ms}$.
- [ ] **Localization & Diagnostics:** Debug overlays and logs are synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).
- [ ] **Quality Gate:** Automated tests pass `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).

## Out of scope

- Continuous dynamic kiting or evasive retreat during active combat.
- Flying/Hoverboard navigation.
- Memory write operations (`WriteProcessMemory`).

## Verification

- Automated:
  - Unit tests in `tests/unit/test_attack_point_sampler.py` validating polygon clamping, radius enforcement, and slope filtering.
  - Unit tests in `tests/unit/test_attack_point_scoring.py` validating travel time, turning cost, and follow-up cluster weighting.
  - `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows):
  - In Flyff, observe target approaches: verify the character stops at optimal attack distance and positions itself closer to subsequent monster spawns rather than running into the monster center.
