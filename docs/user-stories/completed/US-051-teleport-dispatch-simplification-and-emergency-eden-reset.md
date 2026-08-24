---
id: US-051
title: Teleport dispatch simplification and dedicated emergency Eden reset hotkey
status: completed
created: 2026-08-19
updated: 2026-08-24
---

# US-051: Teleport dispatch simplification and dedicated emergency Eden reset hotkey

## Story

As a **bot operator on Entropia Flyff**, I want **the navigation system to remove generic blinkwing and multi-target teleport assumptions and instead strictly use a single configurable emergency reset hotkey (default F8) when unrecoverable stalls or death occur**, so that **the bot does not attempt impossible fast-travel actions in a server environment without blinkwings and reliably returns to the Eden spawn anchor exclusively in true emergencies**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Entropia Flyff does not provide generic blinkwings or town return scrolls for arbitrary fast-travel routing across mob zones.
- Generic multi-target teleport dispatch (>150 distance threshold) from [US-048](completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md) does not reflect actual server mechanics and is obsolete for regular traversal.
- Builds on [US-040](completed/US-040-unrecoverable-stuck-emergency-teleport-and-spawn-reset.md) (emergency stuck teleport and spawn reset).
- The emergency reset hotkey (default: `F8`, configurable in settings) triggers an instant server-side teleport back to the Eden entrance/spawn anchor.
- Live GPS (`ReadProcessMemory`) confirms arrival at the Eden spawn area within an instant timeout window (default: 2.0s).
- Standard routine travel strictly uses 3D ground pathing.

## Acceptance criteria

- [x] Given regular long-range navigation, when planning routes to mob spawn zones, then the bot plans 3D ground paths exclusively and does not dispatch routine fast-travel or blinkwing teleports.
- [x] Given an unrecoverable movement stall or character death condition, when emergency recovery triggers, then the operator-selected client teleporter destination is dispatched through Flyff's built-in teleporter UI under foreground and emergency-stop guards.
- [x] Given a teleporter UI sequence, when live world identity and coordinates update, then arrival is confirmed against the extracted destination anchor within a fast confirmation window (default: 2.0s) before navigation resumes safely.
- [x] Given a failed emergency teleport (identity/position remains unchanged after timeout), then the bot enters emergency stop mode and reports `emergency_reset_unconfirmed`; guarded key dispatch releases keys at timeout boundaries.
- [x] Obsolete references to generic town blinkwings and multi-anchor fast-travel controllers are removed from configuration, pathing, persistence, and UI controls; US-065's extracted built-in teleporter workflow remains authoritative.
- [x] All user-visible settings, labels, and log messages remain synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).

## Out of scope

- In-game chat command `/teleport` or `/unstuck` parsing when deterministic built-in teleporter UI dispatch is available.
- Arbitrary point-to-point fast travel routing through external portals or instances.
- Modifying in-game keybindings directly inside the client binary.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_vector_pathing.py`, `tests/unit/test_teleporter_dispatch.py`, and related suites verifying that regular routing uses ground paths and that built-in teleporter requests are guarded and confirmed.
  - Unit tests in `tests/unit/test_emergency_recovery.py` validating destination selection/persistence and unavailable fallbacks.
- Manual (Windows, outstanding):
  - Launch the bot in the Entropia client, select the intended reset destination from extracted data, induce an unrecoverable stall, observe the guarded teleporter sequence, confirm authoritative arrival, and verify safe resume versus emergency stop.
