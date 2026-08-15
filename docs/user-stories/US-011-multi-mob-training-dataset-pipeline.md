---
id: US-011
title: Multi-mob training dataset pipeline and custom YOLO model training
status: draft
created: 2026-08-15
updated: 2026-08-15
---

# US-011: Multi-mob training dataset pipeline and custom YOLO model training

## Story

As a bot developer, I want a structured dataset pipeline to organize raw game screenshots, support manual annotations in standard YOLO format (`images/`, `labels/`, `data.yaml`), and export lightweight custom-trained ONNX models, so that multiple game monsters (starting with `Flame` in Eden) can be detected accurately without zero-shot heuristics.

## Context and assumptions

- Source: [Target architecture proposal](../sources/2026-08-15-target-architecture-proposal.md) and user-supplied screenshots in `data/eden/flame/`.
- Raw screenshots are gathered per area and mob type under `data/<area>/<mob_name>/`.
- Annotation uses standard YOLO format: normalized `class_id center_x center_y width height` per line.
- Multi-mob support: class label registry maps integer IDs to monster names (`0: Flame`, etc.).
- Custom lightweight model (e.g. YOLOv8n / YOLOv11n) is trained on labeled dataset and exported to `models/mob_detector.onnx` and `models/labels.txt`.

## Acceptance criteria

- [ ] Directory layout defined for training datasets (`data/datasets/mobs/` with `images/train`, `images/val`, `labels/train`, `labels/val`).
- [ ] Dataset manifest (`data/datasets/mobs/data.yaml`) specifying class IDs and monster names with multi-mob support.
- [ ] Tooling or CLI helper to validate labeled datasets and check for corrupted images or missing label files.
- [ ] Export workflow producing `models/mob_detector.onnx` and UTF-8 `models/labels.txt` compatible with `OpenCVDnnYoloDetector`.
- [ ] Fast automated test verifying that the exported ONNX model artifact loads and infers on a sample test frame.
- [ ] All user-visible logs, CLI flags, and error messages exist in German and English.

## Out of scope

- Zero-shot open-vocabulary detection (YOLO-World).
- Automated web scraping of 3D models outside the client.

## Verification

- Automated: Unit tests validating dataset schema, YAML configuration, and ONNX model compatibility check; `./scripts/check.ps1`.
- Manual (Windows): Train model on labeled `data/eden/flame/` screenshots, export ONNX, and run detection on a live client frame.
