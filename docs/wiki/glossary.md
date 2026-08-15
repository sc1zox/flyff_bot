---
title: Glossary
status: active
updated: 2026-08-15
sources:
  - ../sources/2026-08-15-repository-bootstrap-request.md
  - ../sources/2026-08-15-target-architecture-proposal.md
related:
  - project-overview.md
  - architecture.md
---

# Glossary

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
- **Target verification** — Perception-only inspection of a normalized target-header region that
  combines HP-bar colour presence with whitelisted name-template matching and reports a typed
  target status.
- **Target status** — The verification result for the current target: `VALID_TARGET`,
  `WRONG_TARGET`, or `NO_TARGET`.
- **Viewport** — The client-area width and height carried with a world-state snapshot, used to
  choose the visible target nearest the screen centre.
- **Loot-log OCR** — Perception-only extraction of pickup notifications from a normalized central
  client-area region. It preprocesses the crop for text recognition and parses supported German
  and English pickup patterns into timestamped loot events.
- **Loot event** — A typed record of one recognized pickup containing its timestamp, item name,
  quantity, and original OCR text.
- **Perception pipeline** — The application service that captures one frame, independently
  aggregates mob, target, and loot observations into a new immutable world-state snapshot, and
  reports material state changes and non-fatal feed failures.
- **Perception event** — A typed notification emitted by a perception tick when the selected
  target changes or a previously unseen visible mob appears.
- **Perception failure** — A typed, non-fatal indication that detection, target verification, or
  loot reading failed for a tick; the snapshot retains that feed's prior value.
