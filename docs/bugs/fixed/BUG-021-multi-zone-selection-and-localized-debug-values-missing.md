---
id: BUG-021
title: Vector navigation offers no multi-zone selection and renders debug values unlocalized
status: fixed
severity: medium
created: 2026-08-20
updated: 2026-08-20
---

# BUG-021: Vector navigation offers no multi-zone selection and renders debug values unlocalized

## Environment

- Windows version: Windows 10/11
- Python version: 3.14
- Application revision: `4a81b34` (US-059)
- Client/server version: Entropia Flyff PServer (`neuz.exe`)

## Reproduction

1. Launch the dashboard and open *World Data & Maps*.
2. Extract a region that contains several spawn camps.
3. Try to activate two camps at once, then start farming and let one camp run empty.
4. Switch the interface language to German and open the target debug panel.

## Expected behavior

[US-059](../../user-stories/completed/US-059-authoritative-vector-navigation-legacy-removal-and-multi-zone-selection.md)
accepts two criteria this violates:

- the operator can activate multiple distinct spawn zones, and the navigator routes across the
  3D NavMesh to the next active zone on quota completion or target exhaustion, and
- all user-visible text is synchronized in English and German.

## Actual behavior

The zone control was a single-selection `QComboBox`, so exactly one zone was ever armed:
`_on_activate_clicked` passed `active_zones = (zone,)`. `VectorZoneNavigator.advance_to_next_zone`
and `PathingController.advance_to_next_zone` existed but no production caller reached them, so the
target-exhaustion hand-over never happened. With one zone selected, `advance_to_next_zone` also
re-bound the navigator to the zone it was already patrolling.

Independently, `MainWindow._render_target_debug` and `_render_monster_stats_debug` assembled their
value labels from hardcoded f-strings (`f"{verdict} {score:.2f} / {threshold:.2f}"`,
`f"{count} px ({pct:.1f}%)"`, `f"'{text}' -> {candidate}"`, `"none"`, `f"{w} x {h} px"`), leaving
the localized templates `ui.target_debug_anchor_value`, `ui.target_debug_hp_value`,
`ui.target_debug_name_value`, `ui.monster_stats_debug_anchor_value`, and
`ui.monster_stats_debug_roi_value` unused in both locales.

## Impact and frequency

- Impact: medium - multi-camp routes need manual re-arming, and part of the debug panel ignores
  the selected language.
- Frequency: always, since `4a81b34`.

## Regression verification

- [x] A failing automated test or deterministic manual check exists.
      `tests/unit/test_world_data_dialog.py::test_several_checked_zones_are_all_armed_for_sequential_farming`,
      `::test_activation_is_refused_while_no_zone_is_checked`,
      `tests/unit/test_vector_pathing.py::test_an_exhausted_camp_hands_the_session_to_the_next_selected_zone`,
      and `::test_a_single_selected_zone_has_nowhere_to_advance_to`.
- [x] The check passes after the fix. The dialog lists camps as checkable entries and arms every
      checked one; `PathingController.completed_zone_sweeps` counts patrol laps without a kill and
      the orchestrator hands the session to the next selected camp after
      `PATROL_SWEEPS_BEFORE_ZONE_CHANGE` laps; the debug panels render through their locale
      templates again.
- [x] Related documentation is current.
