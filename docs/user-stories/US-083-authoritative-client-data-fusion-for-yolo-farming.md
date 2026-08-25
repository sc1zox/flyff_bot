---
id: US-083
title: Authoritative client-data fusion for YOLO-guided efficient farming
status: draft
created: 2026-08-26
updated: 2026-08-26
---

# US-083: Authoritative client-data fusion for YOLO-guided efficient farming

## Story

As a **bot operator**, I want **every YOLO candidate to be enriched with the relevant verified
static, live, goal, route, and outcome data before it reaches the decision policy**, so that **the
bot can learn offline to maximize measured farming yield per elapsed time while executing one
coherent, safe control loop in the client**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- This story follows [BUG-033](../bugs/BUG-033-unified-setup-does-not-ingest-or-autoload-client-data.md)
  and consumes, rather than duplicates, the canonical contracts and learning workflow of
  [US-079](US-079-unified-goal-conditioned-decision-contract.md),
  [US-080](US-080-goal-driven-quest-execution-and-objective-bus.md), and
  [US-081](US-081-experience-database-and-train-evaluate-promote-loop.md). The repaired learning and
  simulator invariants are documented in
  [ADR-008](../decisions/ADR-008-closed-learning-loop-invariants.md),
  [BUG-031](../bugs/fixed/BUG-031-learning-loop-is-open-recorded-data-and-live-inference.md), and
  [BUG-032](../bugs/fixed/BUG-032-simulator-dynamics-and-paired-evaluation-invalidate-policy-metrics.md).
- The current client archives already expose authoritative mover combat/movement data, drop
  declarations, skill definitions and additions, item definitions, NPC declarations, quests, and
  world/spawn data. The reviewed setup path does not yet turn most of them into consumable artifacts.
- The repository currently has a six-class YOLO model (`Flame`, `LadyBlum`, `MiniMush`, `NightMist`,
  `Oldrut`, and `Rapra`) and maps those labels to mover IDs `1453` through `1458`. All 83 extracted
  Eden spawn zones are named through this narrow mapping, while all 287 extracted Aurania zones have
  no monster name. Sixteen client world directories are discoverable, but only two world maps and
  no baked NavMesh artifact are present in the runtime dataset.
- Existing live adapters can expose exact-profile XYZ, camera/projection state, arbitrary proven
  player-stat fields, a bounded selected-target snapshot, world ID, and dungeon state. At the
  reviewed fingerprint, XYZ is available; camera is foreground-gated; player stats and world ID
  have no proven profile; the dungeon registry is intentionally empty. Missing data must remain
  explicit and must never be guessed.
- `WorldState` retains a complete player-stat snapshot, but current decisions consume only derived
  HP/MP/FP percentages. The client target fields are not fused with YOLO; world ID and dungeon state
  remain outside the policy observation; static mover/drop/skill/item rows do not enrich a detected
  candidate. Telemetry schema 4 repairs transition identity and reward intervals but does not yet
  persist the complete fused source/provenance record proposed here.
- “Efficient farming” means maximizing verified goal value per real elapsed time. For unconstrained
  farming the default observable is verified kills per minute, with travel, turning, combat, idle,
  stall, recovery, resource use, and failed actions as costs. Loot value may be optimized only when
  both static drop semantics and the actual collected outcome are verifiably observed; an expected
  drop must not be reported as acquired loot.
- Learning remains offline. Live sessions execute deterministic or promoted validated policies and
  record experience; they never mutate weights or send exploratory/random client actions.

## Acceptance criteria

- [ ] Given the generated client dataset, when it is loaded, then one versioned source/consumer
      manifest lists every parsed table and live provider with client/content digest, schema,
      completeness, field provenance, freshness rule, and the exact production consumers that use
      it; a parsed field cannot remain silently unused.
- [ ] Given movers, drops, items, skills, NPCs, quests, worlds, spawn zones, obstacles, terrain, and
      NavMeshes in the client, when extraction completes, then each supported record is available as
      a typed normalized artifact or is reported with a typed rejection reason. Filename discovery
      or a positive file counter is not accepted as ingestion.
- [ ] Given a YOLO detection, when it enters perception, then it receives a stable per-instance
      candidate identity from US-079 and is joined through an exact versioned mapping to its mover
      ID, class metadata, verified combat/movement properties, spawn capacity/respawn evidence, and
      available drop metadata. Ambiguous or missing label mappings remain explicit and cannot join
      to a nearby or similarly named mover.
- [ ] Given a camera, GPS, world map, and NavMesh sample from the same valid observation interval,
      when a candidate is enriched, then its screen box, bottom-centre ray, world XYZ, polygon,
      route distance, reachability, leash state, elevation, terrain/corridor cost, and source ages
      describe that same instance and interval. A stale or cross-world sample is rejected rather
      than combined.
- [ ] Given an exact player-stat profile exposes HP, MP, FP, level, experience, attributes, or
      bounded target fields, when a decision is encoded, then every available proven field is
      represented with provenance and missingness. The client selected-target identity/HP/state is
      reconciled with the visually selected YOLO instance; disagreement is visible and fails closed
      for actions that require authoritative identity.
- [ ] Given an active farming or quest goal, when legal options are built, then world ID, active
      spawn zone, quest/objective identity and progress, route/teleport state, dungeon availability,
      combat engagement, configured skill/resource constraints, and readiness determine the offered
      options before the policy ranks them. Optional unrelated data does not block an independent
      capability.
- [ ] Given the canonical decision snapshot from US-079, when heuristic, learned, simulator, and
      telemetry paths consume it, then all four use the same field definitions, units, coordinate
      systems, missing-value semantics, action candidates, masks, and source digests. No parallel
      reduced observation builder fabricates zeros or drops a client field without a documented
      reason.
- [ ] Given two legal YOLO candidates, when the farming policy ranks them, then the expected objective
      accounts for verified goal value and measured end-to-end time/cost: route and turning time,
      expected combat duration, stall/recovery risk, player-resource risk, respawn/camp follow-up
      value, and failed-action cost. Minimum walking distance is treated as one cost component, not
      as a substitute for total farming yield.
- [ ] Given a pure-farming session, when efficiency is reported, then verified kills per real minute,
      time decomposition, distance, damage/resource cost, stalls, and action failures are shown
      separately. Given a goal or verified loot-value configuration, its reward weights and units
      are versioned and reported; the UI never labels an unobserved expected drop as real yield.
- [ ] Given a live decision and its later outcome, when telemetry is recorded, then the session-safe
      record contains the fused decision-time snapshot, candidate mapping/provenance, active goal,
      exact mask and parameterized action, model/artifact version, latency, source freshness, route,
      combat/resource deltas, objective/loot outcome, and reward interval needed by US-081 without
      post-decision leakage.
- [ ] Given offline training, evaluation, and live inference, when the same recorded state is encoded,
      then train/serve parity tests produce the same vector and candidate identities. Artifact
      metadata binds every static dataset, observation/action/reward schema, YOLO model/labels, world
      map/NavMesh, and training-session set by digest; a mismatch rejects the artifact without a
      compatibility fallback.
- [ ] Given a source is missing, stale, malformed, unsupported, or belongs to another client build,
      when a dependent decision is requested, then readiness and the decision builder fail closed
      with a stable diagnostic and no fabricated value. Recovery requires a fresh coherent sample
      set; END/Escape, foreground checks, emergency latching, and guarded key release remain
      authoritative downstream.
- [ ] Given the target-class selection changes, when the next frame is decoded, then filtering still
      occurs inside the YOLO decode boundary before NMS, tracking, world projection, catalog joins,
      candidate ranking, or target verification. Data enrichment must not reintroduce a filtered
      class or widen the operator's whitelist.
- [ ] All user-visible source states, incompleteness reasons, efficiency metrics, policy refusals,
      and provenance diagnostics are available as complete synchronized German and English strings.

## Out of scope

- Runtime signature scanning, inferred offsets, memory dumps, writes, injection, hooks, anti-cheat
  evasion, credential handling, or stealth behavior.
- Online/on-policy learning, live exploration, random client actions, or in-process weight mutation.
- Reimplementing the canonical action/observation/reward contract, goal executor, or
  train/evaluate/promote commands owned by US-079 through US-081; this story supplies their complete
  verified data and consumer wiring.
- Treating unverified inventory, buff, cooldown, target, or loot values as available merely because
  a similar client build or static table contains a plausible field.
- Expanding the YOLO class set or retraining the detector. A later dataset story may add classes
  after the authoritative label-to-mover mapping and coverage report expose the missing targets.

## Verification

- Automated: manifest/source-consumer coverage test; normalized client-table fixture extraction;
  exact label-to-mover join and ambiguity rejection; temporal/cross-world fusion tests; rich
  player/target missingness tests; goal/readiness option tests; canonical simulator/export/live
  encoder parity; end-to-end record/export/train/load/shadow/act fixture; reward decomposition and
  no-leakage tests; artifact digest rejection; early YOLO whitelist test; localization parity;
  `./scripts/check.ps1`.
- Manual (Windows): on the exact-fingerprinted foreground client, record a session with at least two
  same-class visible mobs and a route between spawn groups; verify screen-to-world identity, static
  mover/spawn enrichment, live player/target agreement, policy option/mask display, executed guarded
  action, time/reward decomposition, and the persisted record. Repeat with focus loss, a missing
  optional source, an unsupported required profile, client restart, and END/Escape. Record camera,
  YOLO, policy latency, and farming efficiency as live evidence rather than inferring them from
  synthetic tests.
