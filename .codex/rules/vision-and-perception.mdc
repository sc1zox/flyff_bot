---
description: Computer vision, YOLO object detection, OCR extraction, and frame capture rules
globs: src/**/vision/**/*.py,src/**/perception/**/*.py
alwaysApply: false
---

# Vision & Perception Guidelines

Standards for computer vision, frame capture, YOLO model inference, and OCR in `flyff_bot`.

## 1. Frame Capture & Resource Management

- Use high-performance desktop capture (e.g. Win32 `BitBlt` or `dxcam` / `mss`).
- Release device contexts (`ReleaseDC`, `DeleteDC`, `DeleteObject`) properly to prevent GDI resource leaks.
- Operate on numpy arrays (`uint8` BGR/RGB) without unnecessary copy allocations.

## 2. YOLO Object Detection

- Wrap YOLO inference in dedicated worker / async pipelines.
- Standardize detection outputs into typed dataclasses (`BoundingBox`, `Confidence`, `ClassLabel`, `CenterPoint`).
- Filter mob detections by confidence threshold and valid region of interest (ROI) to avoid UI false positives.

## 3. Targeted OCR (Loot & Target HP)

- Apply preprocessing (grayscale, thresholding, contrast enhancement) before passing image patches to OCR.
- Restrict OCR execution strictly to bounded ROIs (e.g. chat log window, target nameplate) rather than full-screen frames.
