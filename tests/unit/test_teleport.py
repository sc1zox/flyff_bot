from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.teleport import (
    TeleportAnchor,
    TeleportConfig,
    TeleportController,
    TeleportStatus,
)

TARGET = WorldPosition(300.0, 20.0, 0.0)
NEAR_ANCHOR = TeleportAnchor("east", WorldPosition(280.0, 20.0, 0.0), 0x70)
FAR_ANCHOR = TeleportAnchor("west", WorldPosition(20.0, 0.0, 0.0), 0x71)


def _controller(**overrides: object) -> TeleportController:
    values: dict[str, object] = {
        "enabled": True,
        "anchors": (FAR_ANCHOR, NEAR_ANCHOR),
    }
    values.update(overrides)
    return TeleportController(TeleportConfig(**values))  # type: ignore[arg-type]


def test_long_range_dispatch_selects_the_anchor_nearest_the_target() -> None:
    controller = _controller()

    dispatch = controller.update(WorldPosition(0.0, 0.0, 0.0), TARGET, 10.0)

    assert dispatch is not None
    assert dispatch.anchor == NEAR_ANCHOR
    assert dispatch.virtual_key == NEAR_ANCHOR.virtual_key
    assert controller.status is TeleportStatus.WAITING_FOR_POSITION


def test_threshold_is_strict_and_disabled_or_unavailable_uses_ground_pathing() -> None:
    exactly_at_threshold = WorldPosition(150.0, 20.0, 0.0)

    assert _controller().update(exactly_at_threshold, TARGET, 1.0) is None
    assert _controller(enabled=False).update(WorldPosition(0.0, 0.0, 0.0), TARGET, 1.0) is None
    assert _controller(anchors=()).update(WorldPosition(0.0, 0.0, 0.0), TARGET, 1.0) is None


def test_fresh_live_position_confirms_the_teleport_without_another_dispatch() -> None:
    controller = _controller()
    controller.update(WorldPosition(0.0, 0.0, 0.0), TARGET, 1.0)

    dispatch = controller.update(WorldPosition(282.0, 20.0, 1.0), TARGET, 1.5)

    assert dispatch is None
    assert controller.status is TeleportStatus.CONFIRMED
    assert controller.pending_anchor is None


def test_timeout_does_not_repeat_the_same_teleport_attempt() -> None:
    controller = _controller(timeout_seconds=2.0)
    origin = WorldPosition(0.0, 0.0, 0.0)
    assert controller.update(origin, TARGET, 1.0) is not None

    assert controller.update(origin, TARGET, 3.0) is None
    assert controller.status is TeleportStatus.UNAVAILABLE
    assert controller.update(origin, TARGET, 4.0) is None


def test_rejected_guarded_dispatch_falls_back_without_hotkey_spam() -> None:
    controller = _controller()
    origin = WorldPosition(0.0, 0.0, 0.0)
    assert controller.update(origin, TARGET, 1.0) is not None

    controller.reject_pending()

    assert controller.status is TeleportStatus.UNAVAILABLE
    assert controller.update(origin, TARGET, 2.0) is None
