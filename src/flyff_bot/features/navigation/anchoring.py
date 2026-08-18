"""Landmark anchoring of navigation profiles: capture, serialisation, and matching.

A learned map is expressed in minimap pixels relative to wherever the session that recorded
it started. Loading it into a later session would silently reinterpret those coordinates
relative to the new start point, so a profile stores the minimap disk it was recorded at as
a landmark. Correlating that stored disk against the live one recovers the offset between
the two sessions' frames, which is what makes a loaded route lead to the place it was
recorded at (US-036).

Only the translational offset is recovered here. The minimap is north-up, so heading is
already absolute (US-035), and the stored zoom signature is the scale: a profile recorded at
a different zoom level describes distances this session cannot reproduce.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from enum import StrEnum

import cv2
import numpy as np
import numpy.typing as npt

from flyff_bot.features.navigation.spatial import WorldPoint
from flyff_bot.features.vision.minimap import (
    FULL_TURN_DEGREES,
    MINIMAP_SURFACE_RADIUS_PIXELS,
    MinimapReading,
    correlate_surfaces,
    windowed_surface,
    zoom_signature_matches,
)

# The disk is stored as a base64 PNG so a profile stays one self-contained, human-readable
# JSON document instead of a file pair that can be separated from each other.
ANCHOR_IMAGE_FORMAT = ".png"
ANCHOR_IMAGE_ENCODING = "ascii"
# Two disks recorded further apart than one surface radius share no content at all, so a
# correlation peak beyond it cannot be evidence of overlap however confident it looks. How
# far the match actually stays usable inside that bound is a measured field quantity
# (US-036), not a value this module can derive.
MAXIMUM_ANCHOR_DISPLACEMENT_PIXELS = float(MINIMAP_SURFACE_RADIUS_PIXELS)

_ANCHOR_SURFACE_KEY = "surface_png_base64"
_ANCHOR_X_KEY = "x"
_ANCHOR_Y_KEY = "y"
_ANCHOR_HEADING_KEY = "heading_degrees"
_ANCHOR_ZOOM_SIGNATURE_KEY = "zoom_signature"


class ProfileAnchorState(StrEnum):
    """How the active map relates to the frame its coordinates were recorded in."""

    # No profile has been loaded or saved: the map is this session's own recording.
    SESSION = "session"
    # A stored landmark was matched against the live minimap, so the map is writable.
    ANCHORED = "anchored"
    # The profile carries a landmark that could not be matched. Routes may be followed, but
    # nothing is written to a map whose frame is unverified.
    READ_ONLY = "read_only"
    # The profile carries no landmark at all, because tracking was degraded when it was
    # saved. It can only ever load read-only.
    UNANCHORED = "unanchored"


class AnchorMatchOutcome(StrEnum):
    """The verdict of correlating a stored landmark against the live minimap."""

    MATCHED = "matched"
    SCALE_MISMATCH = "scale_mismatch"
    UNMATCHED = "unmatched"


@dataclass(frozen=True, slots=True)
class AnchorMatch:
    """The recovered live position of a stored landmark, or why it was not recovered."""

    outcome: AnchorMatchOutcome
    # The current position expressed in the loaded profile's coordinate frame.
    position: WorldPoint | None = None
    response: float | None = None
    stored_zoom_signature: float | None = None
    live_zoom_signature: float | None = None


@dataclass(frozen=True, slots=True)
class MapAnchor:
    """The landmark one profile was recorded at: its disk, place, facing, and scale."""

    surface: npt.NDArray[np.uint8]
    position: WorldPoint
    heading_degrees: float
    zoom_signature: float

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible record of this landmark."""

        return {
            _ANCHOR_SURFACE_KEY: _encode_surface(self.surface),
            _ANCHOR_X_KEY: self.position.x,
            _ANCHOR_Y_KEY: self.position.y,
            _ANCHOR_HEADING_KEY: self.heading_degrees,
            _ANCHOR_ZOOM_SIGNATURE_KEY: self.zoom_signature,
        }

    @classmethod
    def from_dict(cls, payload: object) -> MapAnchor:
        """Rebuild one landmark, raising ``ValueError`` for anything unusable."""

        if not isinstance(payload, dict):
            raise ValueError("A persisted map anchor must be an object.")
        document = {str(key): value for key, value in payload.items()}
        heading = _number(document.get(_ANCHOR_HEADING_KEY), "anchor heading")
        zoom_signature = _number(document.get(_ANCHOR_ZOOM_SIGNATURE_KEY), "anchor zoom signature")
        if not 0.0 <= heading < FULL_TURN_DEGREES:
            raise ValueError("A persisted anchor heading must be a compass bearing.")
        if zoom_signature <= 0.0:
            raise ValueError("A persisted anchor zoom signature must be positive.")
        return cls(
            surface=_decode_surface(document.get(_ANCHOR_SURFACE_KEY)),
            position=WorldPoint(
                _number(document.get(_ANCHOR_X_KEY), "anchor x"),
                _number(document.get(_ANCHOR_Y_KEY), "anchor y"),
            ),
            heading_degrees=heading,
            zoom_signature=zoom_signature,
        )


def capture_anchor(
    reading: MinimapReading, position: WorldPoint, heading_degrees: float
) -> MapAnchor | None:
    """Return the landmark this reading stands at, or ``None`` without a decoded disk."""

    if reading.surface is None:
        return None
    return MapAnchor(
        surface=reading.surface,
        position=position,
        heading_degrees=heading_degrees,
        zoom_signature=reading.zoom_signature,
    )


def match_anchor(
    anchor: MapAnchor,
    live_surface: npt.NDArray[np.uint8],
    live_zoom_signature: float,
) -> AnchorMatch:
    """Recover where the character stands in a stored profile's coordinate frame."""

    if not zoom_signature_matches(anchor.zoom_signature, live_zoom_signature):
        return AnchorMatch(
            AnchorMatchOutcome.SCALE_MISMATCH,
            stored_zoom_signature=anchor.zoom_signature,
            live_zoom_signature=live_zoom_signature,
        )
    try:
        stored = windowed_surface(anchor.surface)
        live = windowed_surface(live_surface)
    except ValueError:
        return AnchorMatch(AnchorMatchOutcome.UNMATCHED)
    displacement = correlate_surfaces(stored, live)
    if displacement is None:
        return AnchorMatch(AnchorMatchOutcome.UNMATCHED)
    if displacement.magnitude > MAXIMUM_ANCHOR_DISPLACEMENT_PIXELS:
        return AnchorMatch(AnchorMatchOutcome.UNMATCHED, response=displacement.response)
    # The scroll of the map content is turned into player motion by the same sign rule every
    # odometry tick uses, so the two paths can never disagree about which way is east.
    travel = MinimapReading(
        displacement=displacement, heading_degrees=None, zoom_signature=live_zoom_signature
    )
    return AnchorMatch(
        AnchorMatchOutcome.MATCHED,
        position=WorldPoint(
            anchor.position.x + travel.player_dx, anchor.position.y + travel.player_dy
        ),
        response=displacement.response,
    )


def _encode_surface(surface: npt.NDArray[np.uint8]) -> str:
    encoded, buffer = cv2.imencode(ANCHOR_IMAGE_FORMAT, surface)
    if not encoded:
        raise ValueError("The minimap anchor disk could not be encoded.")
    return base64.b64encode(buffer.tobytes()).decode(ANCHOR_IMAGE_ENCODING)


def _decode_surface(value: object) -> npt.NDArray[np.uint8]:
    if not isinstance(value, str):
        raise ValueError("A persisted anchor disk must be a base64 string.")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("A persisted anchor disk must be valid base64.") from error
    decoded = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if decoded is None:
        raise ValueError("A persisted anchor disk must be a decodable image.")
    surface = np.ascontiguousarray(decoded, dtype=np.uint8)
    height, width = surface.shape[:2]
    if surface.ndim != 2 or height != width or height % 2 != 0:
        raise ValueError("A persisted anchor disk must be square and of even size.")
    return surface


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"Persisted {label} must be a number.")
    return float(value)
