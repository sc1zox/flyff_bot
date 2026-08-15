---
id: US-003
title: Mob detection with YOLO and OpenCV
status: draft
created: 2026-08-15
updated: 2026-08-15
---

# US-003: Mob detection with YOLO and OpenCV

## Story

As a player using permitted automation, I want the bot to detect visible monsters in the game window
using YOLO and OpenCV, so that the bot knows where potential targets are located in screen space.

## Context and assumptions

- Source: [Computer vision and YOLO request](../sources/2026-08-15-computer-vision-and-yolo-request.md).
- Depends on [US-002](US-002-vision-frame-capture.md) for game frame acquisition.
- Inference can run via ONNX Runtime, OpenCV DNN, or Ultralytics YOLO depending on runtime footprint.
- A pretrained or custom-trained model file will be loaded from a designated configuration path.

## Acceptance criteria

- [ ] Loads a YOLO model artifact from a specified file path with error handling for missing or corrupt files.
- [ ] Performs object detection on input frames and returns structured detections containing bounding box (x, y, width, height), confidence score, class ID, and class name.
- [ ] Supports configurable confidence threshold and class name filtering.
- [ ] Returns empty detection lists gracefully without exceptions when no mobs are present.
- [ ] Provides an abstraction/mock detector for fast unit tests without requiring GPU/live model files in standard test runs.
- [ ] All user-visible logs, CLI flags, and error messages exist in German and English.

## Out of scope

- Training or labeling custom YOLO datasets (dataset preparation is a separate operational task).
- Auto-targeting, navigation, or issuing combat inputs.
- Verifying the targeted mob's exact nameplate/HP bar (covered in [US-004](US-004-target-mob-verification.md)).

## Verification

- Automated: Unit tests running detection against mock/fixture frames with known expected bounding boxes; `./scripts/check.ps1`.
- Manual (Windows): Run CLI with `--detect-mobs` against a running game client or static test screenshot.
