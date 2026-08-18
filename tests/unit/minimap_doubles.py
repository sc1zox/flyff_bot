"""Test doubles that stand in for the live minimap sensor.

`PathingController` only writes to the learned map while the minimap measurement is
available, so every test that exercises map learning has to supply one. These doubles keep
that supply explicit instead of hiding it behind a real frame decode.
"""

from __future__ import annotations

import math

from flyff_bot.features.automation.controllers import VIRTUAL_KEY_W
from flyff_bot.features.navigation.tracking import (
    CLOCKWISE_VIRTUAL_KEYS,
    FULL_TURN_DEGREES,
    ROTATION_VIRTUAL_KEYS,
    MovementModel,
)
from flyff_bot.features.vision.minimap import (
    MinimapDisplacement,
    MinimapReading,
)
from flyff_bot.features.vision.models import CapturedFrame

CONFIDENT_RESPONSE = 0.9
REFERENCE_ZOOM_SIGNATURE = 90.0


class ScriptedOdometer:
    """Return a queued reading per tick, then keep returning the last one."""

    def __init__(self, readings: list[MinimapReading | None]) -> None:
        self._readings = list(readings)
        self._last: MinimapReading | None = None

    def observe(self, frame: CapturedFrame | None) -> MinimapReading | None:
        if self._readings:
            self._last = self._readings.pop(0)
        return self._last

    def reset(self) -> None:
        self._last = None


class MirrorOdometer:
    """Report the motion a client would show for the movement a test dispatched.

    The real sensor observes the client; here the dispatched key stream stands in for it,
    so a test can drive learned-map behaviour without decoding recorded frames.
    """

    def __init__(
        self, model: MovementModel, zoom_signature: float = REFERENCE_ZOOM_SIGNATURE
    ) -> None:
        self._model = model
        self._zoom_signature = zoom_signature
        self._heading_degrees = 0.0
        self._pending_x = 0.0
        self._pending_y = 0.0
        self._blocked = False

    @property
    def heading_degrees(self) -> float:
        """Return the facing the double will report on its next reading."""

        return self._heading_degrees

    def block(self) -> None:
        """Stop reporting translation, as an obstacle in front of the character would."""

        self._blocked = True

    def unblock(self) -> None:
        """Report translation again, as clearing the obstacle would."""

        self._blocked = False

    def displace(self, east_pixels: float, north_pixels: float) -> None:
        """Move the character without a command, as knockback or the operator would."""

        self._pending_x += east_pixels
        self._pending_y += north_pixels

    def command(self, virtual_key: int, duration_seconds: float) -> None:
        """Fold one dispatched pulse into the motion the next reading will report."""

        if duration_seconds <= 0.0:
            return
        if virtual_key in ROTATION_VIRTUAL_KEYS:
            direction = 1.0 if virtual_key in CLOCKWISE_VIRTUAL_KEYS else -1.0
            turned = direction * self._model.turn_degrees_per_second * duration_seconds
            self._heading_degrees = (self._heading_degrees + turned) % FULL_TURN_DEGREES
            return
        if virtual_key == VIRTUAL_KEY_W and not self._blocked:
            radians = math.radians(self._heading_degrees)
            distance = self._model.forward_speed_pixels_per_second * duration_seconds
            self._pending_x += math.sin(radians) * distance
            self._pending_y += math.cos(radians) * distance

    def observe(self, frame: CapturedFrame | None) -> MinimapReading | None:
        # The sensor reports how the map content scrolled, which is opposite to the player
        # in x and, because screen y grows downwards, identical in sign to it in y.
        reading = MinimapReading(
            displacement=MinimapDisplacement(
                x=-self._pending_x, y=self._pending_y, response=CONFIDENT_RESPONSE
            ),
            heading_degrees=self._heading_degrees,
            zoom_signature=self._zoom_signature,
        )
        self._pending_x = 0.0
        self._pending_y = 0.0
        return reading

    def reset(self) -> None:
        self._heading_degrees = 0.0
        self._pending_x = 0.0
        self._pending_y = 0.0
        self._blocked = False
