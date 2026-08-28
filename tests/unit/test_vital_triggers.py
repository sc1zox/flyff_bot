"""Unit tests for vitals threshold trigger controller and input dispatcher."""

import pytest

from flyff_bot.features.automation.models import ActionKind, PlayerVitals, Position, WorldState
from flyff_bot.features.automation.vitals_controller import (
    VitalsDecision,
    VitalsInputDispatcher,
    VitalsTriggerConfig,
    VitalsTriggerController,
    VitalTriggerRule,
    VitalTriggerType,
)


class MockVitalsAdapter:
    """Mock platform adapter for testing vitals input dispatching."""

    def __init__(self, foreground: bool = True, aborted: bool = False) -> None:
        self._foreground = foreground
        self._aborted = aborted
        self.sent_keys: list[tuple[int, float]] = []

    def is_foreground(self, window_handle: int) -> bool:
        return self._foreground

    def is_aborted(self) -> bool:
        return self._aborted

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        self.sent_keys.append((virtual_key, duration_seconds))


def _make_world_state(
    observed_at: float = 100.0,
    hp: float = 100.0,
    mp: float = 100.0,
    fp: float = 100.0,
) -> WorldState:
    return WorldState(
        observed_at_seconds=observed_at,
        position=Position(0, 0),
        nearby_mob_count=0,
        inventory=(),
        progress_marker=0,
        player_vitals=PlayerVitals(hp_percentage=hp, mp_percentage=mp, fp_percentage=fp),
    )


def test_vital_trigger_rule_validation() -> None:
    rule = VitalTriggerRule(
        vital_type=VitalTriggerType.HP,
        threshold_percentage=70.0,
        virtual_key=0x70,
        debounce_seconds=0.8,
    )
    assert rule.vital_type is VitalTriggerType.HP
    assert rule.threshold_percentage == 70.0

    with pytest.raises(ValueError, match="Threshold percentage"):
        VitalTriggerRule(
            vital_type=VitalTriggerType.HP,
            threshold_percentage=150.0,
            virtual_key=0x70,
        )
    with pytest.raises(ValueError, match="Debounce seconds"):
        VitalTriggerRule(
            vital_type=VitalTriggerType.HP,
            threshold_percentage=50.0,
            virtual_key=0x70,
            debounce_seconds=-1.0,
        )
    with pytest.raises(ValueError, match="Key press duration"):
        VitalTriggerRule(
            vital_type=VitalTriggerType.HP,
            threshold_percentage=50.0,
            virtual_key=0x70,
            key_press_duration_seconds=0.0,
        )


def test_vitals_controller_no_trigger_above_threshold() -> None:
    controller = VitalsTriggerController()
    state = _make_world_state(observed_at=1.0, hp=90.0, mp=80.0, fp=80.0)

    decision = controller.step(state)
    assert not decision.triggered
    assert decision.rule is None


def test_vitals_controller_hp_threshold_trigger() -> None:
    controller = VitalsTriggerController()
    # Default HP threshold is 70.0
    state = _make_world_state(observed_at=10.0, hp=65.0, mp=100.0, fp=100.0)

    decision = controller.step(state)
    assert decision.triggered
    assert decision.rule is not None
    assert decision.rule.vital_type is VitalTriggerType.HP
    assert decision.virtual_key == 0x70  # F1
    assert decision.action_kind is ActionKind.RECOVER


def test_vitals_controller_debounce_cooldown() -> None:
    controller = VitalsTriggerController()
    # First tick at t=10.0: HP is 50%, fires
    decision1 = controller.step(_make_world_state(observed_at=10.0, hp=50.0))
    assert decision1.triggered

    # Second tick at t=10.4: HP is still 50%, within 0.8s debounce -> should NOT trigger
    decision2 = controller.step(_make_world_state(observed_at=10.4, hp=50.0))
    assert not decision2.triggered

    # Third tick at t=10.85: HP is still 50%, >= 0.8s debounce -> fires again
    decision3 = controller.step(_make_world_state(observed_at=10.85, hp=50.0))
    assert decision3.triggered
    assert decision3.virtual_key == 0x70


def test_vitals_controller_priority_hp_over_mp_and_fp() -> None:
    controller = VitalsTriggerController()
    # All HP, MP, and FP are below their thresholds
    state = _make_world_state(observed_at=10.0, hp=50.0, mp=20.0, fp=10.0)

    # HP should fire first
    decision_hp = controller.step(state)
    assert decision_hp.triggered
    assert decision_hp.rule is not None
    assert decision_hp.rule.vital_type is VitalTriggerType.HP

    # On the next tick while HP is on cooldown, MP should fire next
    state_next = _make_world_state(observed_at=10.1, hp=50.0, mp=20.0, fp=10.0)
    decision_mp = controller.step(state_next)
    assert decision_mp.triggered
    assert decision_mp.rule is not None
    assert decision_mp.rule.vital_type is VitalTriggerType.MP

    # On the next tick while HP and MP are on cooldown, FP should fire next
    state_third = _make_world_state(observed_at=10.2, hp=50.0, mp=20.0, fp=10.0)
    decision_fp = controller.step(state_third)
    assert decision_fp.triggered
    assert decision_fp.rule is not None
    assert decision_fp.rule.vital_type is VitalTriggerType.FP


def test_vitals_controller_disabled_rules_do_not_fire() -> None:
    config = VitalsTriggerConfig(
        rules=(
            VitalTriggerRule(
                vital_type=VitalTriggerType.HP,
                threshold_percentage=70.0,
                virtual_key=0x70,
                enabled=False,
            ),
        )
    )
    controller = VitalsTriggerController(config)
    state = _make_world_state(observed_at=10.0, hp=30.0)

    decision = controller.step(state)
    assert not decision.triggered


def test_vitals_controller_refuses_zero_percent_vitals() -> None:
    controller = VitalsTriggerController()

    assert not controller.step(_make_world_state(observed_at=10.0, hp=0.0)).triggered


def test_vitals_controller_reset_clears_cooldowns() -> None:
    controller = VitalsTriggerController()
    decision1 = controller.step(_make_world_state(observed_at=10.0, hp=50.0))
    assert decision1.triggered

    # Reset controller
    controller.reset()

    # Even at t=10.1, it can trigger again because cooldowns were reset
    decision2 = controller.step(_make_world_state(observed_at=10.1, hp=50.0))
    assert decision2.triggered


def test_vitals_input_dispatcher_success() -> None:
    adapter = MockVitalsAdapter(foreground=True, aborted=False)
    dispatcher = VitalsInputDispatcher(adapter, window_handle=12345)

    decision = VitalsDecision(
        triggered=True,
        virtual_key=0x70,
        key_press_duration_seconds=0.05,
    )

    dispatched = dispatcher.dispatch(decision)
    assert dispatched is True
    assert adapter.sent_keys == [(0x70, 0.05)]


def test_vitals_input_dispatcher_guards() -> None:
    decision = VitalsDecision(triggered=True, virtual_key=0x70, key_press_duration_seconds=0.05)

    # Not triggered
    adapter1 = MockVitalsAdapter(foreground=True, aborted=False)
    dispatcher1 = VitalsInputDispatcher(adapter1, 12345)
    assert dispatcher1.dispatch(VitalsDecision(triggered=False)) is False
    assert adapter1.sent_keys == []

    # Aborted
    adapter2 = MockVitalsAdapter(foreground=True, aborted=True)
    dispatcher2 = VitalsInputDispatcher(adapter2, 12345)
    assert dispatcher2.dispatch(decision) is False
    assert adapter2.sent_keys == []

    # Not foreground
    adapter3 = MockVitalsAdapter(foreground=False, aborted=False)
    dispatcher3 = VitalsInputDispatcher(adapter3, 12345)
    assert dispatcher3.dispatch(decision) is False
    assert adapter3.sent_keys == []
