---
id: US-002
title: Screen and client frame capture
status: draft
created: 2026-08-15
updated: 2026-08-15
---

# US-002: Screen and client frame capture

## Story

As a bot developer, I want a fast, reliable Windows frame capture pipeline for the Flyff client window,
so that downstream computer vision models (OpenCV, YOLO, OCR) can inspect the current game screen in real time.

## Context and assumptions

- Source: [Computer vision and YOLO request](../sources/2026-08-15-computer-vision-and-yolo-request.md).
- The Flyff client runs in windowed or borderless mode on Windows.
- Frame capture should produce OpenCV-compatible formats (`numpy.ndarray` in BGR/RGB).
- Performance must be sufficient for real-time detection without starving the CPU.
- Unit tests must be decoupled from live Win32 windows using injectable mock frame providers.

## Acceptance criteria

- [ ] Captures the client area of the target Flyff window handle (`HWND`) into a standard image array (e.g. `numpy.ndarray`).
- [ ] Provides an injectable frame-source interface so unit tests run deterministically with static fixtures.
- [ ] Returns typed errors if the game window is minimized, invalid, occluded, or cannot be captured.
- [ ] Frame coordinates accurately map to client-space pixels for subsequent click and bounding-box actions.
- [ ] All user-visible error and log messages exist in German and English.

## Out of scope

- Object detection or machine learning inference.
- Processing or acting on game state.
- Injection into DirectX / Direct3D render pipelines.

## Verification

- Automated: Unit tests with mock frame data checking capture bounds, shape, and error branches; `./scripts/check.ps1`.
- Manual (Windows): Capture a live test frame from a running `neuz.exe` window and save or verify dimensions.
