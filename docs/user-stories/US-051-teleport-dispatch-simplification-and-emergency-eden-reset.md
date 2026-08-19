---
id: US-051
title: Teleport dispatch simplification and dedicated emergency Eden reset hotkey
status: draft
created: 2026-08-19
updated: 2026-08-19
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

- [ ] Given regular long-range navigation, when planning routes to mob spawn zones, then the bot plans 3D ground paths exclusively and does not dispatch routine fast-travel or blinkwing teleports.
- [ ] Given an unrecoverable movement stall or character death condition, when emergency recovery triggers, then the system pulses the configured emergency reset hotkey (default `F8`) to return to the Eden spawn anchor.
- [ ] Given an emergency teleport hotkey pulse, when live GPS coordinates update, then the system verifies arrival at the Eden spawn anchor within a fast confirmation window (default: 2.0s) and resets the navigation session to idle/safe start.
- [ ] Given a failed emergency teleport (character position remains unchanged after timeout), then the bot enters emergency stop mode, releases all held movement keys, and notifies the operator.
- [ ] Obsolete references to generic town blinkwings and multi-destination teleport menus are purged from configuration models, telemetry, and UI controls.
- [ ] All user-visible settings, labels, and log messages remain synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).

## Out of scope

- In-game chat command `/teleport` or `/unstuck` parsing when direct hotkey dispatch is available.
- Arbitrary point-to-point fast travel routing through external portals or instances.
- Modifying in-game keybindings directly inside the client binary.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_teleport.py` verifying that regular pathing ignores long-range teleport thresholds and routes by ground.
  - Unit tests in `tests/unit/test_emergency_recovery.py` validating that unrecoverable stalls trigger the `F8` emergency pulse and confirm arrival via `WorldPosition`.
- Manual (Windows):
  - Launch bot in Entropia client, induce an unrecoverable stall or trigger emergency reset, verify `F8` is pulsed, confirm instant arrival at Eden spawn, and observe green GPS status.
