"""Loader for the recorded minimap frames shipped under `data/assets/fixtures/minimap/`.

The recordings themselves are far too large for the repository, so only the fixed window
around the minimap widget is shipped. Each sequence carries the client size it was captured
at, which lets a test rebuild a frame whose right and top edges sit exactly where the live
client would put them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt

from flyff_bot.features.vision.models import CapturedFrame, ClientSize

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "data" / "assets" / "fixtures" / "minimap"


@dataclass(frozen=True, slots=True)
class RecordedFrame:
    """One shipped minimap crop with the timing it was recorded at."""

    frame: CapturedFrame
    seconds: float


@dataclass(frozen=True, slots=True)
class RecordedSequence:
    """One recorded burst: its frames plus the key hold that produced them."""

    frames: tuple[RecordedFrame, ...]
    held_key: str
    key_down_seconds: float
    key_up_seconds: float


@dataclass(frozen=True, slots=True)
class _CropGeometry:
    """Where one shipped crop sat inside the client area it was captured from."""

    client_width: int
    client_height: int
    crop_left: int
    crop_top: int


@lru_cache(maxsize=1)
def _manifest() -> dict[str, object]:
    document: object = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    return _mapping(document)


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("Minimap fixture manifest entries must be objects.")
    return {str(key): item for key, item in value.items()}


def _entry(name: str) -> dict[str, object]:
    return _mapping(_manifest()[name])


def _integer(entry: dict[str, object], key: str) -> int:
    value = entry[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"Minimap fixture field {key!r} must be an integer.")
    return value


def _number(entry: dict[str, object], key: str) -> float:
    value = entry[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"Minimap fixture field {key!r} must be a number.")
    return float(value)


def _text(entry: dict[str, object], key: str) -> str:
    value = entry[key]
    if not isinstance(value, str):
        raise TypeError(f"Minimap fixture field {key!r} must be a string.")
    return value


def _geometry(entry: dict[str, object]) -> _CropGeometry:
    return _CropGeometry(
        client_width=_integer(entry, "client_width"),
        client_height=_integer(entry, "client_height"),
        crop_left=_integer(entry, "crop_left"),
        crop_top=_integer(entry, "crop_top"),
    )


def _read(path: Path) -> npt.NDArray[np.uint8]:
    pixels = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if pixels is None:
        raise FileNotFoundError(f"Missing minimap fixture: {path}")
    return np.asarray(pixels, dtype=np.uint8)


def _compose(path: Path, geometry: _CropGeometry) -> CapturedFrame:
    """Paste one shipped crop back onto a canvas the size of the recorded client area."""

    patch = _read(path)
    canvas = np.zeros((geometry.client_height, geometry.client_width, 3), dtype=np.uint8)
    top, left = geometry.crop_top, geometry.crop_left
    canvas[top : top + patch.shape[0], left : left + patch.shape[1]] = patch
    return CapturedFrame(
        np.ascontiguousarray(canvas), ClientSize(geometry.client_width, geometry.client_height)
    )


def sequence(name: str) -> RecordedSequence:
    """Return one recorded burst by its manifest name (`walk` or `turn`)."""

    entry = _entry(name)
    geometry = _geometry(entry)
    records = entry["frames"]
    if not isinstance(records, list):
        raise TypeError("Minimap fixture sequences must carry a list of frames.")
    frames = tuple(
        RecordedFrame(
            frame=_compose(FIXTURE_ROOT / name / _text(_mapping(record), "file_name"), geometry),
            seconds=_number(_mapping(record), "seconds_since_first"),
        )
        for record in records
    )
    return RecordedSequence(
        frames=frames,
        held_key=_text(entry, "held_key"),
        key_down_seconds=_number(entry, "key_down_seconds"),
        key_up_seconds=_number(entry, "key_up_seconds"),
    )


def still(name: str) -> CapturedFrame:
    """Return one recorded stationary frame by its manifest name."""

    entry = _entry(name)
    return _compose(FIXTURE_ROOT / _text(entry, "file_name"), _geometry(entry))
