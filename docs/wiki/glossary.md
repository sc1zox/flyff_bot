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
