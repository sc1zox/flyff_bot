---
id: US-083
title: Authoritative client-data fusion for YOLO-guided efficient farming
status: in-progress
created: 2026-08-26
updated: 2026-08-28
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
  [US-079](completed/US-079-unified-goal-conditioned-decision-contract.md),
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
- [x] Given a YOLO detection, when it enters perception, then it receives a stable per-instance
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
- [x] Given the target-class selection changes, when the next frame is decoded, then filtering still
      occurs inside the YOLO decode boundary before NMS, tracking, world projection, catalog joins,
      candidate ranking, or target verification. Data enrichment must not reintroduce a filtered
      class or widen the operator's whitelist.
- [ ] All user-visible source states, incompleteness reasons, efficiency metrics, policy refusals,
      and provenance diagnostics are available as complete synchronized German and English strings.

## Progress

- 2026-08-28 - **Foundation layer (data + manifest + join) landed; the fusion, policy, telemetry
  and reporting criteria are not started.** This story is epic-sized; the work below is the layer
  every remaining criterion consumes.

  - **Prerequisite fix.** `main` did not parse. Four committed files carried Python 2-style
    `except A, B:` clauses produced by the pinned formatter, which rewrites an inline
    `except (A, B):` into invalid Python: `navigation/teleporter_extraction.py`,
    `quests/extraction.py`, `setup/profiles.py`, and `telemetry/storage.py`. Each now uses the
    named module-level tuple idiom already used by `DETECTION_ERRORS`. The defect reproduced
    against new code written during this story, so the idiom is not optional.

  - **Static catalog (AC2, partial).** New `features/client_data/` package. `tables.py` parses
    movers, drops, items, skills and NPCs; `extraction.py` reads them through the existing keyed
    archive reader and returns one `ClientCatalog`; `persistence.py` writes and reloads a
    schema-versioned artifact. Mover numeric columns are located by the client's *own* column
    header rather than by a fixed index, and without a header the combat fields stay `None`
    behind a `LAYOUT_UNVERIFIED` rejection instead of being read from a neighbouring column. A
    duplicated symbol rejects both rows; a drop naming an undeclared mover is rejected rather
    than attached. Still outstanding for this criterion: NavMesh baking, and enrolling the
    already-extracted world/spawn/terrain artifacts into the same typed-rejection reporting.

  - **Setup stage rewired (BUG-033).** `_run_mover_stage` no longer counts file names. It parses,
    validates, writes `data/client/catalog.json` and `data/client/source_manifest.json`, and
    reports `mover_count`, `drop_count`, `item_count`, `skill_count` and `npc_count` - rows
    actually persisted. The presence-only `monster_table_count` and `static_item_table_found`
    fields are deleted.

  - **Source/consumer manifest (AC1, partial).** `manifest.py` and `sources.py` declare every
    parsed table with client digest, content digest, schema version, completeness, freshness rule,
    per-field provenance and the exact production consumers that read it.
    `verify_consumer_coverage` makes an unconsumed field a test failure, and `undeclared_tables`
    closes the loophole of hiding a table by declaring no field for it. The check immediately
    surfaced a real gap: **nothing consumes the client's skill rows**, so `client.skills` is
    declared with zero promoted fields and `PARTIAL` completeness rather than an invented
    consumer. AC6 is where that field gets promoted. Live providers are not yet enrolled as
    manifest entries, which is the remaining half of this criterion.

  - **Label-to-mover join (AC3, partial).** The source analysis in
    `docs/sources/2026-08-21-entropia-keyed-archive-and-quest-data-analysis.md` records that the
    client does not ship the `MI_*`-to-numeric-mover-id table; it is compiled into `neuz.exe`.
    The join therefore cannot be derived from the packed tables and is a curated versioned
    artifact instead. `label_mapping.py` binds a detector label to exactly one mover id and
    symbol, stamped with the client digest it was proven against, and fails closed on an
    unmapped label, a label bound to two movers, a display name shared by two movers, a binding
    naming an undeclared symbol, a foreign client digest, and a foreign mapping version. The
    join is keyed by the US-079 per-instance candidate identity, so two simultaneously visible
    monsters of one class stay distinct.

  - **Perception enrichment (AC3, done).** `PerceptionPipeline` now assigns each decoded box
    its candidate identity and joins the frame's own detections, so `WorldState` carries
    `mob_catalog_joins` - mover id, symbol, display name, verified combat properties, declared
    drops and spawn evidence - keyed by that identity, plus `mob_catalog_rejections` for the
    classes it could not join. Spawn evidence (zone count, total capacity, shortest respawn
    interval per mover) is aggregated from the adopted world map and pushed in by
    `configure_vector_navigation`, which is the moment the session learns which world it is
    farming. `persistence.py` gained the versioned read/write for
    `data/client/mover_label_mapping.json`, the artifact `constants.py` had declared but nothing
    produced or consumed.

    Three states are kept distinct rather than collapsed into "no enrichment": no artifacts
    installed yields no join and no rejection; a mapping stamped with a foreign client digest or
    mapping version loads as a *refused* join that keeps stating the refusal on every tick; a
    label the installed mapping does not bind is `LABEL_UNMAPPED`. A rejection is a property of
    the class, so five unjoinable boxes of one class state one fact. The join runs on the boxes
    the same tick produced, so a failed detection keeps the previous mobs *and* their previous
    join instead of re-keying a stale one.

    One caveat, and it is data rather than code: the curated mapping artifact binds a detector
    label to a mover *symbol*, and the six symbols behind `Flame`, `LadyBlum`, `MiniMush`,
    `NightMist`, `Oldrut` and `Rapra` have not been proven against a client. The numeric ids in
    `data/assets/world/monster_ids.json` are evidenced by the extracted spawn zones; the symbols
    are not, and deriving them by name similarity is exactly what this criterion forbids. Until
    an operator authors the artifact against a fingerprinted client, the mechanism runs and
    reports every detection as explicitly unmapped - the same posture as an unbaked NavMesh.

  - **Early YOLO whitelist (AC13, done).** Verified that `OpenCVDnnYoloDetector._decode` already
    applies the operator whitelist before `_suppress_per_class`, and pinned it with a regression
    test that records what reaches NMS, plus a test that an unknown class name cannot widen the
    selection.

  - **Localization.** Thirteen new message identifiers for catalog, manifest-completeness and
    label-join diagnostics, complete and synchronized in `de.json` and `en.json`.

  - **Gate.** `uv sync`, `ruff check`, `ruff format --check` and `mypy` (298 files) pass.
    `pytest` reports 1085 passed, 5 skipped, 0 failed at 89% coverage. The 11 failures recorded
    here earlier belonged to a concurrent US-084 session editing the same working tree; that
    session has since landed and they are gone.

## Remaining work

Criteria 4-12 are untouched: temporal and cross-world fusion coherence, rich player/target
missingness and reconciliation, goal-driven option gating, the single canonical snapshot builder,
the time-and-cost farming objective, efficiency reporting, the fused telemetry record, train/serve
parity with artifact digest binding, and fail-closed readiness.

Criterion 4 is the natural next step and now has what it needs: every detection carries an
identity, an authoritative mover, and a world position, but nothing yet checks that the camera,
GPS, world map and NavMesh samples behind one enriched candidate came from the *same* valid
interval and the same world. Two known seams to close along the way:

- The policy layer's `PolicyCandidate.original_position` is still an index into the *eligible*
  candidate list, not the perception candidate identity the join is keyed by. Downstream code can
  bridge the two through `candidate.mob.candidate_index`, but reconciling them into one identity
  belongs to criteria 5 and 7, which own the canonical snapshot.
- Nothing consumes `mob_catalog_joins` yet. The manifest declares the join function as the
  consumer of the mover and drop fields, which is now true, but no decision reads the enriched
  record; the farming objective in criterion 8 is where the combat, drop and spawn columns start
  changing a ranking.

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
