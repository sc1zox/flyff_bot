"""Unit tests for the timed power-up scheduler, guarded dispatch, and persistence."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from flyff_bot.features.automation.powerup_controller import (
    DEFAULT_POWERUP_STAGGER_SECONDS,
    PowerUpConfig,
    PowerUpDecision,
    PowerUpEntry,
    PowerUpInputDispatcher,
    PowerUpScheduler,
)
from flyff_bot.features.automation.powerup_persistence import (
    load_powerup_config,
    powerup_config_from_dict,
    powerup_config_to_dict,
    save_powerup_config,
)

VIRTUAL_KEY_F4 = 0x73
VIRTUAL_KEY_F5 = 0x74
TICK_SECONDS = 0.1


class RecordingAdapter:
    """Guarded platform double recording every dispatched power-up key."""

    def __init__(self, *, aborted: bool = False, foreground: bool = True) -> None:
        self.aborted = aborted
        self.foreground = foreground
        self.sent_keys: list[tuple[int, float]] = []

    def is_aborted(self) -> bool:
        return self.aborted

    def is_foreground(self, window_handle: int) -> bool:
        return self.foreground

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        self.sent_keys.append((virtual_key, duration_seconds))


def _run_until_trigger(
    scheduler: PowerUpScheduler, *, start_at: float, limit_seconds: float
) -> tuple[PowerUpDecision, float]:
    """Step the scheduler on a fixed cadence and return the first triggering tick."""

    now = start_at
    while now < start_at + limit_seconds:
        decision = scheduler.step(now)
        if decision.triggered:
            return decision, now
        now += TICK_SECONDS
    raise AssertionError("Scheduler never reported a due power-up.")


def test_entry_rejects_intervals_outside_the_supported_range() -> None:
    with pytest.raises(ValueError):
        PowerUpEntry(virtual_key=VIRTUAL_KEY_F4, interval_seconds=0)
    with pytest.raises(ValueError):
        PowerUpEntry(virtual_key=VIRTUAL_KEY_F4, interval_seconds=90_000)


def test_initial_trigger_happens_immediately_on_session_start() -> None:
    scheduler = PowerUpScheduler(
        PowerUpConfig(entries=(PowerUpEntry(virtual_key=VIRTUAL_KEY_F4, interval_seconds=300),))
    )

    first = scheduler.step(100.0)
    assert first.triggered is True
    assert first.virtual_key == VIRTUAL_KEY_F4


def test_trigger_recurs_after_each_confirmed_press() -> None:
    scheduler = PowerUpScheduler(
        PowerUpConfig(entries=(PowerUpEntry(virtual_key=VIRTUAL_KEY_F4, interval_seconds=2),))
    )
    first = scheduler.step(0.0)
    assert first.triggered is True
    scheduler.confirm(first, 0.0)

    assert scheduler.step(TICK_SECONDS).triggered is False

    second, second_at = _run_until_trigger(scheduler, start_at=2 * TICK_SECONDS, limit_seconds=5.0)

    assert second.virtual_key == VIRTUAL_KEY_F4
    assert second_at >= 2.0


def test_concurrent_entries_are_staggered_and_dispatched_sequentially() -> None:
    scheduler = PowerUpScheduler(
        PowerUpConfig(
            entries=(
                PowerUpEntry(virtual_key=VIRTUAL_KEY_F4, interval_seconds=5),
                PowerUpEntry(virtual_key=VIRTUAL_KEY_F5, interval_seconds=5),
            )
        )
    )

    first = scheduler.step(0.0)
    assert first.virtual_key == VIRTUAL_KEY_F4
    scheduler.confirm(first, 0.0)

    # The second entry stays due but is withheld until the stagger gap elapsed.
    held = scheduler.step(DEFAULT_POWERUP_STAGGER_SECONDS / 2)
    assert held.triggered is False

    second = scheduler.step(DEFAULT_POWERUP_STAGGER_SECONDS)
    assert second.virtual_key == VIRTUAL_KEY_F5


def test_disabled_entries_never_accumulate_or_trigger() -> None:
    scheduler = PowerUpScheduler(
        PowerUpConfig(
            entries=(
                PowerUpEntry(virtual_key=VIRTUAL_KEY_F4, interval_seconds=2, enabled=False),
                PowerUpEntry(virtual_key=VIRTUAL_KEY_F5, interval_seconds=2),
            )
        )
    )

    first = scheduler.step(0.0)
    assert first.virtual_key == VIRTUAL_KEY_F5
    assert scheduler.elapsed_seconds(0) == 0.0


def test_halted_span_does_not_count_towards_an_interval() -> None:
    scheduler = PowerUpScheduler(
        PowerUpConfig(entries=(PowerUpEntry(virtual_key=VIRTUAL_KEY_F4, interval_seconds=10),))
    )
    first = scheduler.step(0.0)
    scheduler.confirm(first, 0.0)
    scheduler.step(4.0)

    scheduler.halt()
    resumed = scheduler.step(600.0)

    assert resumed.triggered is False
    assert scheduler.elapsed_seconds(0) == pytest.approx(4.0)
    assert scheduler.step(606.1).triggered is True


def test_update_config_preserves_countdowns_for_unchanged_entries() -> None:
    entry = PowerUpEntry(virtual_key=VIRTUAL_KEY_F4, interval_seconds=180)
    scheduler = PowerUpScheduler(PowerUpConfig(entries=(entry,)))
    first = scheduler.step(0.0)
    scheduler.confirm(first, 0.0)
    scheduler.step(120.0)

    scheduler.update_config(PowerUpConfig(entries=(replace(entry, label="Haste"),)))
    assert scheduler.elapsed_seconds(0) == pytest.approx(120.0)

    scheduler.update_config(
        PowerUpConfig(entries=(PowerUpEntry(virtual_key=VIRTUAL_KEY_F4, interval_seconds=300),))
    )
    assert scheduler.elapsed_seconds(0) == 300.0


def test_reset_restarts_every_countdown() -> None:
    scheduler = PowerUpScheduler(
        PowerUpConfig(entries=(PowerUpEntry(virtual_key=VIRTUAL_KEY_F4, interval_seconds=10),))
    )
    first = scheduler.step(0.0)
    scheduler.confirm(first, 0.0)
    scheduler.step(9.0)

    scheduler.reset()

    assert scheduler.elapsed_seconds(0) == 10.0
    assert scheduler.step(100.0).triggered is True


def test_unconfirmed_decision_stays_due_until_the_guards_allow_it() -> None:
    scheduler = PowerUpScheduler(
        PowerUpConfig(entries=(PowerUpEntry(virtual_key=VIRTUAL_KEY_F4, interval_seconds=2),))
    )

    assert scheduler.step(0.0).triggered is True
    # Never confirmed, so the very next tick still reports the same entry as due.
    assert scheduler.step(0.1).virtual_key == VIRTUAL_KEY_F4


def test_dispatcher_sends_the_key_when_focused_and_not_aborted() -> None:
    adapter = RecordingAdapter()
    dispatcher = PowerUpInputDispatcher(adapter, window_handle=42)
    decision = PowerUpDecision(
        triggered=True,
        entry_index=0,
        virtual_key=VIRTUAL_KEY_F4,
        key_press_duration_seconds=0.05,
    )

    assert dispatcher.dispatch(decision) is True
    assert adapter.sent_keys == [(VIRTUAL_KEY_F4, 0.05)]


@pytest.mark.parametrize(
    ("aborted", "foreground"),
    [(True, True), (False, False)],
)
def test_dispatcher_withholds_the_key_when_a_guard_blocks(aborted: bool, foreground: bool) -> None:
    adapter = RecordingAdapter(aborted=aborted, foreground=foreground)
    dispatcher = PowerUpInputDispatcher(adapter, window_handle=42)
    decision = PowerUpDecision(triggered=True, entry_index=0, virtual_key=VIRTUAL_KEY_F4)

    assert dispatcher.dispatch(decision) is False
    assert adapter.sent_keys == []


def test_powerup_config_dict_roundtrip() -> None:
    config = PowerUpConfig(
        entries=(
            PowerUpEntry(
                virtual_key=VIRTUAL_KEY_F4,
                interval_seconds=180,
                label="Grilled Eel",
                enabled=True,
                key_press_duration_seconds=0.1,
            ),
            PowerUpEntry(
                virtual_key=VIRTUAL_KEY_F5,
                interval_seconds=3600,
                label="Haste",
                enabled=False,
            ),
        ),
        stagger_seconds=0.05,
    )

    restored = powerup_config_from_dict(powerup_config_to_dict(config))

    assert restored == config


def test_powerup_config_file_save_and_load(tmp_path: Path) -> None:
    config_file = tmp_path / "powerups.json"
    config = PowerUpConfig(
        entries=(PowerUpEntry(virtual_key=VIRTUAL_KEY_F4, interval_seconds=5, label="Upcut Stone"),)
    )

    save_powerup_config(config, config_file)
    loaded = load_powerup_config(config_file)

    assert config_file.is_file()
    assert loaded.entries[0].label == "Upcut Stone"
    assert loaded.entries[0].interval_seconds == 5
    assert loaded.entries[0].virtual_key == VIRTUAL_KEY_F4


def test_stored_empty_entry_list_is_not_replaced_by_defaults(tmp_path: Path) -> None:
    config_file = tmp_path / "powerups.json"
    save_powerup_config(PowerUpConfig(), config_file)

    assert load_powerup_config(config_file).entries == ()


def test_missing_and_corrupt_files_fall_back_to_an_empty_configuration(tmp_path: Path) -> None:
    assert load_powerup_config(tmp_path / "absent.json").entries == ()

    corrupt_file = tmp_path / "corrupt.json"
    corrupt_file.write_text("not json at all {{{", encoding="utf-8")
    assert load_powerup_config(corrupt_file).entries == ()


def test_unusable_entries_are_skipped_without_discarding_valid_ones() -> None:
    config = powerup_config_from_dict(
        {
            "entries": [
                {"virtual_key": VIRTUAL_KEY_F4, "interval_seconds": 180, "label": "Eel"},
                {"virtual_key": VIRTUAL_KEY_F5},
                {"virtual_key": VIRTUAL_KEY_F5, "interval_seconds": 0},
                "not a mapping",
            ]
        }
    )

    assert len(config.entries) == 1
    assert config.entries[0].label == "Eel"
