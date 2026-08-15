---
id: US-005
title: Central loot and system log OCR extraction
status: draft
created: 2026-08-15
updated: 2026-08-15
---

# US-005: Central loot and system log OCR extraction

## Story

As a player using permitted automation, I want the bot to read and parse item pickup notifications
from the central screen log / system message area, so that picked-up loot and drop statistics can be verified and tracked.

## Context and assumptions

- Source: [Computer vision and YOLO request](../sources/2026-08-15-computer-vision-and-yolo-request.md).
- Depends on [US-002](completed/US-002-vision-frame-capture.md) for game frames.
- Flyff displays pickup notifications in the middle of the screen or in system chat (e.g. "[Item-Name] erhalten" in German, or "You received [Item-Name]" in English).
- An OCR engine or font-template reader will extract message text from the preprocessed notification region.

## Acceptance criteria

- [ ] Isolates and preprocesses the central notification / system log region of interest (ROI) from the game frame (e.g. thresholding, contrast enhancement).
- [ ] Extracts text lines reliably from the preprocessed ROI.
- [ ] Parses item pickup patterns for item name and quantity across supported languages (German and English).
- [ ] Emits structured loot events (timestamp, item_name, count, raw_text).
- [ ] Automated unit tests verify OCR/parsing pipeline with synthetic or fixture screenshot crops.
- [ ] All user-visible logs and UI messages exist in German and English.

## Out of scope

- Inventory management and bag sorting.
- Moving to or clicking loot on the ground.
- Long-term persistent database storage for loot tracking (can be added in a separate analytics story).

## Verification

- Automated: Unit tests comparing known sample notification crops to expected parsed loot objects; `./scripts/check.ps1`.
- Manual (Windows): Pick up an item in a running Flyff client and verify CLI/log output shows parsed item name and count.
