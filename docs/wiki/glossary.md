---
title: Glossary
status: active
updated: 2026-08-20
sources:
  - ../sources/2026-08-15-repository-bootstrap-request.md
  - ../sources/2026-08-15-target-architecture-proposal.md
  - ../sources/2026-08-18-minimap-odometry-calibration.md
  - ../sources/2026-08-19-target-server-entropia-pserver-clarification.md
  - ../sources/2026-08-19-entropia-client-navigation-data-extraction.md
related:
  - project-overview.md
  - architecture.md
---

# Glossary

- **Target Server / Client** — Entropia Flyff PServer (private server, [entropia.fun](https://entropia.fun))
  running the classic Windows PC client executable (`neuz.exe`).
- **Agent** — Codex or another coding agent operating under `AGENTS.md`.
- **LLM wiki** — Agent-maintained, linked project knowledge under `docs/wiki/`.
- **Raw source** — Immutable evidence under `docs/sources/` used to ground wiki claims.
- **User story** — A requested behavior with testable acceptance criteria.
- **Bug** — A reproducible difference between expected and actual behavior.
- **Feature scope** — Code grouped around one user capability rather than a generic technical layer.
- **Magic string/literal** — An unexplained repeated value that encodes behavior, configuration,
  status, or UI text instead of using a named definition or resource.
- **World state** — An immutable snapshot of observed and assumed game reality shared by the
  automation decision layers.
- **Supervisor** — The reconciliation component that compares desired and observed world state
  and emits recovery failure flags.
- **STRIPS-style planner** — A high-level planner that searches typed actions using preconditions
  and add/delete effects to satisfy a goal.
- **Reactive controller** — A focused domain state machine that turns one world-state snapshot
  into an abstract action request.
- **Combat controller** — The reactive controller that selects an allowed visible mob nearest the
  client viewport centre, verifies target lock before a configured attack rotation, and detects
  target death or cleared targeting from subsequent world-state snapshots.
- **Combat input dispatcher** — The Win32-facing combat boundary that dispatches a controller
  click or key request only while the specified game window is foregrounded and the END emergency
  stop is not active.
- **Verified executor** — The execution boundary that accepts an action only after a matching,
  confirmed post-dispatch observation.
- **Frame source** — A typed provider that captures a client-area image for a target window handle;
  the Windows implementation validates foreground visibility and exposes an injectable seam for
  deterministic tests.
- **Captured frame** — A contiguous three-channel `uint8` image array paired with its exact client
  dimensions and BGR or RGB pixel order.
- **Detector** — The injectable protocol that maps a captured frame to structured object
  detections; production inference is provided by the OpenCV DNN YOLO adapter.
- **Detection** — A model result containing a client-space bounding box, confidence, numeric class
  ID, and ordered label name.
- **YOLO label contract** — A UTF-8 text file with one non-empty class name per line; line order
  defines the numeric class IDs emitted by the model.
- **YOLO dataset manifest** — The `data.yaml` file defining dataset root, training and validation
  image locations, and a contiguous numeric monster-name registry; its registry order is exported
  as the YOLO label contract.
- **Dataset validation** — Offline checks that a YOLO dataset has the required split layout,
  readable images, paired annotations, valid normalized YOLO boxes, and no orphan labels.
- **Mob-model export** — Optional local training that produces an ONNX detector and ordered UTF-8
  labels for `OpenCVDnnYoloDetector`, without accessing the game client.
- **Target verification** — Perception-only inspection that first template-matches a target-header
  anchor, then measures HP colour and percentage strictly in a configured target-bar sub-region and
  matches a name against the active whitelist; it reports a typed target status without dispatching
  input.
- **Target status** — The verification result for the current target: `VALID_TARGET`,
  `WRONG_TARGET`, or `NO_TARGET`.
- **Target verification metrics** — The per-criterion debug evidence behind a target status: each
  of the header-anchor, HP-bar, and name-match checks' raw score, configured threshold, and
  pass/fail outcome, carried on `TargetVerificationResult` and `SelectedTarget` for the dashboard's
  Target Debug panel without altering the underlying verification decision.
- **Viewport** — The client-area width and height carried with a world-state snapshot, used to
  choose the visible target nearest the screen centre.
- **Loot-log OCR** — Perception-only extraction of pickup notifications from a normalized central
  client-area region. It preprocesses the crop for text recognition and parses supported German
  and English pickup patterns into timestamped loot events.
- **Loot event** — A typed record of one recognized pickup containing its timestamp, item name,
  quantity, and original OCR text.
- **Loot controller** — The reactive state machine that starts one configured pickup-key attempt
  after explicit combat-death evidence, waits for newly emitted OCR loot confirmation, and requests
  patrol movement once if the confirmation window expires. Since US-025, it is no longer wired into
  `FarmingOrchestrator`, which assumes an active in-game loot pet; it remains a standalone,
  independently tested component.
- **Loot input dispatcher** — The Win32-facing loot boundary that dispatches a pickup key only
  while the specified game window is foregrounded and the END emergency stop is not active. Since
  US-025 it is no longer invoked by `FarmingOrchestrator`'s default kill-to-search transition.
- **Loot de-duplication** — Treating an OCR pickup notification as new only when its item, count,
  and original text were absent from the preceding successful OCR read, so a notification that
  remains visible does not increment inventory again.
- **Perception pipeline** — The application service that captures one frame, independently
  aggregates mob, target, and loot observations into a new immutable world-state snapshot, and
  reports material state changes and non-fatal feed failures.
- **Perception event** — A typed notification emitted by a perception tick when the selected
  target changes, a previously unseen visible mob appears, or a newly confirmed loot pickup is
  recorded.
- **Perception failure** — A typed, non-fatal indication that detection, target verification, or
  loot reading failed for a tick; the snapshot retains that feed's prior value.
- **Farming orchestrator** — A cooperative session state machine that performs one perception,
  control, and guarded-dispatch cycle per tick across `SEARCHING`, `TARGETING`, `COMBAT`, and
  `RECONCILING`; it pauses on lost foreground focus and latches emergency stops. Since US-025 a
  confirmed kill (`CombatMode.TARGET_DEAD`) transitions directly into `RECONCILING` — bumping
  `WorldState.progress_marker` for that kill — instead of the removed `LOOTING` mode, assuming an
  active in-game loot pet.
- **Farming goal** — An optional item name and required inventory quantity that completes a farming
  session when the immutable world-state inventory reaches the target.
- **Attack key** — One supported virtual key (`A`–`Z`, `0`–`9`, Space, or `F1`–`F12`) that the
  dashboard captures as a single physical key press and supplies to the paused farming session's
  combat binding; its dashboard default is `F3`.
- **Staged search** — The no-mob recovery sequence used by the farming orchestrator: a configurable
  idle interval followed by alternating camera rotations and bounded directional roaming pulses,
  cycling back to rotation; it resets immediately when a visible eligible mob is detected.
- **Multi-axis camera search** — The enhanced staged search sequence that alternates horizontal
  yaw rotations (`VK_LEFT`/`VK_RIGHT`) and vertical pitch tilts (`VK_UP`/`VK_DOWN`) separated by
  visual settle pauses to discover spawns on uneven terrain or slopes.
- **Visual settle pause** — A configurable observation interval (`rotation_settle_pause_seconds`)
  between camera rotation and tilt pulses that allows perception to evaluate clean, unblurred
  frames without overshooting candidate mobs.
- **Viewport alignment pre-flight** — The standardized minimap zoom, camera zoom, and pitch routine
  (`CameraAligner`) that runs before a farming session or a calibration recording, so the fitted
  spawn distance relation is read off the same perspective, and the odometry off the same minimap
  scale, that they were measured at.
- **Zoom hard-stop** — The maximum camera distance the game engine clamps the mouse wheel to. Because
  the clamp is the engine's, scrolling forwards past it yields the same focal length in every
  session without inspecting game memory.
- **Minimap zoom hard-stop** — The same idea for the minimap widget: ten clicks on its zoom-out
  button outrun the widget's own range, so it ends on the engine's maximum zoom-out in every session
  and the minimap pixel keeps one meaning across runs.
- **Approach target** — The single mob a calibration walk-in is closing on. Acquired as the candidate
  closest to the viewport's vertical centreline and then followed frame to frame by bounding-box
  overlap and centroid proximity (`ApproachTargetTracker`), so a recorded height series belongs to one
  physical mob rather than to whichever member of a spawn cluster scored highest that frame.
- **Vertical pitch tilt** — Camera elevation adjustments via Up/Down arrow keys during search mode
  to gain bird's-eye or upward perspectives of monsters situated on slopes or hills.
- **Spawn heatmap** — The internal per-cell accumulation of mob sightings on the relative
  navigation grid, weighted by how often mobs were observed there and decayed by a configurable
  half-life so abandoned areas lose priority over time.
- **Navigation graph** — The internal map of grid cells linked by movement the bot actually
  completed, annotated with visit counts, last-visit timestamps, and per-edge stall history.
- **Dead reckoning** — Estimating a session-relative position and compass heading purely from the
  movement and camera keys that were dispatched, without reading any game state.
- **Stall detection** — Concluding that commanded forward movement produced no progress because
  consecutive captured frames stayed visually unchanged for a configured number of samples.
- **Pathing cost penalty** — The bounded multiplicative surcharge that recorded stalls add to a
  cell and to the edge that reached it, so problematic terrain is avoided but never made
  unreachable.
- **Safe waypoint** — The last stall-free cell behind the bot's current one; the retreat target
  from which an alternative bypass route is planned after a stuck situation.
- **Patrol circuit** — A recurring route derived from the densest reachable spawn clusters that
  returns to its starting cell, re-derived whenever spawn densities or path costs change.
- **Navigation profile slot** — A named JSON file stored under `data/navigation/` containing serialized spatial map topology, recorded traversal edges, decayed spawn heatmaps, and stall history for a specific hunting zone or mob camp.
- **Map reset safeguard** — A modal confirmation dialog that prevents accidental purging of live navigation memory, requiring operator confirmation before resetting spatial cells, edges, and dead-reckoned player coordinates to $(0.0, 0.0, 0^\circ)$.
- **Periodic navigation persistence** — Automatic background serialization of the active spatial map every 30 seconds during active farming, on state transitions (pause, emergency stop, goal reached), and upon desktop window closure (`closeEvent`).
- **Fixed-pixel HUD anchoring** — Bounding top-left player vitals gauge extraction to fixed pixel dimensions (`0..260` width, `0..113` height) rather than normalized window percentages, ensuring consistent gauge readings across arbitrary screen resolutions.
- **Placements overlay** — A desktop UI visual guide toggle ("Placements" / "Platzierungshilfen") that draws color-coded, labeled ROI overlay boxes (Player Vitals orb, Target Header bar, Monster Stats window) scaled over the live viewport preview for HUD alignment calibration.
- **Dark Slate theme** — The modern dark stylesheet (QSS) applied across the PySide6 desktop UI,
  including its cards, tab widget, tab bar, internal scroll areas, switches, and child controls;
  it uses restrained slate surfaces, a blue selection accent, and responsive hover/pressed states.
- **Tabbed dashboard** — The US-050 PySide6 main-window composition: a pinned session-control header
  above five localized, internally scrollable views for Dashboard, Combat & Targets, Vitals &
  Buffs, Navigation & World, and Diagnostics & Logs. Selecting a tab changes presentation only;
  hidden pages continue receiving live worker and `DashboardUpdate` state.
- **Toggle switch** — A styled boolean configuration control such as auto-alignment, kill
  verification, or a vitals rule. Unlike the removed panel-visibility checkboxes, it changes a
  setting rather than deciding whether an independently updated dashboard panel exists.
- **Navigation map window** — A standalone pop-out secondary window (`NavigationMapWindow`) hosting the `PathInspectorWidget`, allowing operators to decouple 2D navigation/heatmap inspection from the main controller dashboard.
- **Standby perception** — Continuous read-only perception while the session is paused, completed,
  or emergency-stopped: one frame is captured per tick to refresh vitals, mob counts, target
  verification metrics, and the debug overlay, and no keyboard or mouse input is ever dispatched.
- **Window status** — The typed condition of the game client behind perception (`OK`,
  `NOT_FOREGROUND`, `MINIMIZED`, `NOT_FOUND`, `CAPTURE_FAILED`), published with every dashboard
  update so the operator sees why a preview is live, degraded, or absent.
- **Anchor-relative ROI** — An `AnchorOffsetRegion` pixel rectangle cropped from the top-left corner
  of the matched target-header anchor rather than from fixed fractions of the searched region, so
  the HP-bar and mob-name crops follow the header wherever it is drawn.
- **Match threshold** — The minimum `TM_CCOEFF_NORMED` template score required to accept the target
  header anchor or a whitelisted mob name; both default to `0.75` and are operator-adjustable
  between `0.30` and `1.00` live from the combat panel.
- **Diagnostic metric** — A `TargetVerificationMetrics` measurement taken on every tick regardless
  of whether an earlier criterion passed, so the target debug panel never blanks; the matching
  fields on `TargetVerificationResult` stay gated on the header anchor being accepted, because
  combat control and target-change events read those.
- **Minimap pixel** — The canonical unit of the navigation feature: one pixel of the client's
  minimap surface at the zoom level the session was anchored to. No conversion to world units
  exists, because the client does not display the run speed one would need to fit it. One pixel at
  maximum zoom-out covers exactly two at the default zoom.
- **Patrol leash** — The circle of `leash_radius_pixels` around the session anchor that route
  planning may not leave. The anchor is the origin of the relative navigation frame, so it is the
  point the session started at. Its default is the measured usable minimap surface radius, i.e. the
  camp is the terrain visible around the anchor on the minimap. Hotspots outside it are not
  selectable as route targets, and how many were skipped is reported to the dashboard so a
  shrinking patrol is not mistaken for an empty camp.
- **Tracking quality** — How the current position estimate was obtained: `MEASURED` from a
  confident minimap correlation, `PREDICTED` by the command model inside the grace period after the
  last measurement, or `DEGRADED` beyond it. Map learning is written only while the quality is not
  `DEGRADED`.
- **Zoom signature** — The mean gradient magnitude of the minimap surface, translation invariant
  but proportional to the zoom level. Anchored on the tracker's first measurement and rechecked every
  tick, because a zoom change silently rescales every subsequent measurement without weakening its
  correlation response.
- **Correlation response** — The confidence `cv2.phaseCorrelate` reports for one minimap
  displacement. Genuine motion measured 0.34-0.99; a zoom step measured 0.062 and unrelated minimap
  content -0.006 to 0.097, so the 0.30 gate separates them by a factor of three.
- **Map anchor** — The landmark a navigation profile stores so a later session can tell where its
  coordinates mean: the greyscale minimap disk at save time, the map coordinates it was captured at,
  the measured heading, and the zoom signature. Held as a base64 PNG inside the profile document.
- **Re-anchoring** — Recovering the translational offset between a loaded profile's coordinate frame
  and the live session's, by phase-correlating the stored anchor disk against the live one. Rotation
  needs no recovery because the minimap is north-up; scale is verified against the stored zoom
  signature rather than recovered.
- **Read-only profile** — A loaded profile whose frame could not be verified, either because its
  anchor did not match or because it carries none. Its routes may be followed, but no visit, spawn, or
  stall is recorded and it is never written back to disk.
- **Profile anchor state** — What the dashboard shows beside the profile controls: `SESSION` for this
  session's own recording, `ANCHORED`, `READ_ONLY`, or `UNANCHORED`.
- **Schema version 2** — The only navigation profile format. It is the first whose coordinates are
  measured minimap pixels and which can carry a map anchor; version 1 documents are rejected by name
  rather than migrated (ADR-003).
- **Kill quota** — The number of kills one selected monster class owes before the session stops
  targeting it. Zero means the class is farmed without an upper bound and can never complete a
  session.
- **Active targeting whitelist** — The monster classes whose quota is still open, pushed live into
  detection, target verification, and combat candidate selection. Empty means no restriction at all.
- **Kill attribution** — Counting a verified kill against the class of the candidate the engagement
  clicked, which is the only place a mob's identity is known; the HUD counter reports a total
  without naming the monster.
- **Kill log** — The local SQLite database (`data/kill_log.sqlite3`) recording every verified kill
  with its session id, monster class, and UTC timestamp, plus the quotas that session works towards.
- **Session completion** — `FarmingMode.COMPLETED`, reached when every configured quota is bounded
  and reached, or the item goal is met. It optionally posts one cooperative `WM_CLOSE` to the client.
- **Unrecoverable stuck** — A continuous span, default 60.0 s and configurable between 10.0 s and
  300.0 s, in which the session produced no verified displacement, no landed damage, and no kill.
  It is the state every micro-unstuck mechanism having failed looks like from the session loop.
- **Emergency teleport** — The operator-assigned quickslot hotkey (default `F4`) holding a teleport
  item or skill such as a Town Blinkwing, dispatched under the usual foreground and `END` guards as
  the last resort out of un-walkable geometry. Leaving it unassigned pauses the session instead.
- **Teleport settle delay** — The 2.0 s span (`FarmingMode.TELEPORTING`) in which the session
  observes nothing into the map and steps no controller while the client finishes the transition.
- **Spawn anchor** — The town or respawn coordinate an emergency teleport arrives at, mapped per
  navigation profile and persisted with it. Without one, the reset falls back to the session origin.
- **World vector map** - The extracted, serializable description of one client region: its block
  grid and `MPU`, its `VectorSpawnZone` records, and its impassable rectangles. Stored as versioned
  JSON under `data/navigation/worlds/<world>.json` and read before a session's first step, unlike
  the learned spatial map which is written during one.
- **Vector spawn zone** - One `respawn7` record from a client region script: a monster id, a 3D
  centroid, a 2D bounding rectangle, a mob capacity, and a respawn interval. Under vector navigation
  the rectangle is the patrol boundary, replacing the leash circle around the session anchor.
- **Impassable rectangle** - A merged run of terrain quads whose steepest rise between adjacent
  corners exceeds one metre per metre of run, i.e. the >45 deg cliff the client's physics refuses.
  Merged greedily so the planner gets outer corners rather than a per-quad raster.
- **Search corridor** - The bounding box of one routing query's endpoints plus a margin. Obstacles
  overlapping it are blockers and route vertices are clipped to it, which is what makes a local
  visibility graph sound: the box is convex, so no leg can leave it past an obstacle that was never
  selected.
- **World registration** - The affine map between client world units and a session's minimap pixels.
  It carries no rotation, because the minimap is north-up and the ground plane is axis-aligned; its
  translation comes from the operator naming the zone the character stands in, and its scale is a
  provisional constant because no observation relates the two units.
- **Zone goal** - One monster class to farm and, optionally, the kill count that completes it. The
  navigator works its goals through in order and rebinds to the next unfinished monster's nearest
  zone the moment a quota is reached.
- **Live world position** - The player's finite XYZ float32 coordinate read from the one verified
  player-position struct of a hash-supported `neuz.exe`. It is primary while fresh and valid; it is
  not evidence that terrain, collision, world identity, or server state is complete.
- **Coordinate-only memory boundary** - The safety rule that permits one fingerprinted player
  pointer read followed by one exact 12-byte XYZ read, with query/read process rights only. Memory
  scanning, neighbouring state reads, writes, injection, and hooks remain forbidden.
- **GPS state** - The dashboard's source indicator: green means the latest position came from a
  supported live-coordinate read; otherwise it shows the typed reason GPS is unavailable. A
  `MINIMAP_FALLBACK` source marker never authorizes vector-world route planning or movement.
- **Client position profile** - One operator-maintained, fingerprinted JSON record describing a
  supported `neuz.exe`: SHA-256 digest, player-pointer RVA, pointer width, and optional coordinate
  offset. A missing profile file uses the embedded safe defaults; an invalid file or unknown digest
  is an explicit GPS error, never a guessed memory offset.
- **Stable dialog selection** - A World Data dialog setting stored by durable identity rather than
  list index: client region name, extracted-map filename, spawn-zone key, or kill quota. It can be
  restored after a refresh reorders available items or after a later application launch.
- **Terrain field** - The decoded 129 by 129 float32 height vertices of one `.lnd` block, read
  either from a loose patch file or out of the region's packed archive, and persisted beside the
  world map as a 66,576-byte height field. It is partial only where the client itself ships no
  block for a declared grid coordinate.
- **Packed world archive** - One client region's `<world>.hdr` index and `<world>.one` payload. The
  index stores an opaque digest of each file name; entry bytes are obfuscated with a keystream
  derived from the plain lower-case file name. Reading it is offline and read-only: nothing is
  repacked or written back.
- **Extraction diagnostic** - A typed record of one part of a region that was skipped rather than
  extracted: an unsupported archive index, an undecodable packed block, or a placed-object file in
  an unknown record layout. It never aborts the rest of the region.
- **Terrain route** - A 3D A* route whose edge cost includes elevation and whose walkability rejects
  excessive gradients. Smoothed corner metadata can request lateral strafe to follow a contour.
- **Teleport anchor** - An operator-configured destination position and hotkey used for long-range
  dispatch. It is confirmed from a fresh live position; it is not inferred from `teleport.bin`,
  which contains option identifiers but no verified destination semantics.
- **Temporary world block** - A live coordinate excluded from subsequent route search after repeated
  recovery failure at that location. It is session recovery state, not a permanent collision claim.
- **Session event log** — The per-session, fail-safe JSONL diagnostics trail written by
  `SessionEventLogger` under `logs/sessions/`, gitignored and independent of the durable knowledge
  under `docs/`. Never interrupts the farming loop or the Qt event loop on a disk or formatting
  failure.
- **Session event** — One immutable `SessionEvent` record: an ISO-8601 timestamp, a typed
  `SessionEventKind`, the previous and new `FarmingMode`, an optional free-text reason, and optional
  foreground-window diagnostics. Recorded exactly once per actual `FarmingMode` transition through
  `FarmingOrchestrator._set_mode()`, never on a same-mode no-op.
- **Session event kind** — The seven-value classification of why a mode transition happened:
  `MODE_TRANSITION` (the generic case), `FOCUS_LOST`, `EMERGENCY_STOPPED`, `OBSTACLE_STALL`,
  `SUPERVISOR_FAILURE`, `FRAME_CAPTURE_ERROR`, and `GOAL_COMPLETED`.
- **Foreground window diagnostics** — The title and owning process name of whichever window
  currently holds `GetForegroundWindow()`, read by `WindowsInputController.foreground_window_info()`
  only to explain a `FOCUS_LOST` pause; never used for any input-dispatch decision.
- **Diagnostic Event Log panel** — The dashboard's `EventLogPanel`, hosted on the Diagnostics & Logs
  tab, which renders `DashboardUpdate.events` as a reverse-chronological, localized, colour-badged
  list of recent session events and stays current when another tab is selected.
- **Farming telemetry envelope** — One schema-versioned, append-only JSON object carrying a session
  id, monotonic timestamp, typed event kind, and primitive-only payload. It is produced by
  `TelemetryRecorder` and queued rather than written on the farming tick thread.
- **Telemetry worker** — The bounded `JsonlTelemetryWorker` queue and single daemon persistence
  thread that appends numeric session records to `data/telemetry/` and, when configured, mirrors
  them to SQLite. A full queue drops telemetry rather than delaying farming; worker I/O and
  serialization failures are contained and counted.
- **Operational telemetry store** — `SqliteTelemetryStore`, the local transactional
  `data/telemetry.sqlite3` database with timestamp indexes and event-family tables for fast local
  telemetry queries. It is operational state, not a replacement for append-only JSONL provenance.
- **Telemetry dataset export** — `TelemetryDatasetExporter` and `--export-telemetry`, which compile
  SQLite event records into zstd-compressed Parquet tables for target decisions, navigation
  trajectories, and kill cycles under `data/datasets/rl/`.
- **Explicitly unavailable geometry** — A telemetry field whose US-052 NavMesh or calibrated
  raycast producer is absent. Player/candidate geometry, NavMesh polygon, slope, and path fields
  use `null` when unavailable; the telemetry subsystem must not invent a screen-space estimate.
