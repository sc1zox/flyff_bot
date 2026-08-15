"""Tests for deterministic and live-client frame-source contracts."""

from __future__ import annotations

import numpy as np
import pytest

from flyff_bot.features.vision import (
    CapturedFrame,
    FrameCaptureError,
    FrameCaptureErrorCode,
    FrameSource,
    PixelFormat,
    WindowsFrameSource,
)
from flyff_bot.features.vision.capture import _RawClientFrame
from flyff_bot.features.vision.models import ClientSize

WINDOW_HANDLE = 101


class _StaticSource:
    def __init__(self, frame: CapturedFrame) -> None:
        self.frame = frame

    def capture(self, window_handle: int) -> CapturedFrame:
        assert window_handle == WINDOW_HANDLE
        return self.frame


class _FakeCaptureApi:
    def __init__(
        self,
        *,
        valid: bool = True,
        minimized: bool = False,
        visible: bool = True,
        foreground: bool = True,
        failure: OSError | None = None,
    ) -> None:
        self.valid = valid
        self.minimized = minimized
        self.visible = visible
        self.foreground = foreground
        self.failure = failure

    def is_window(self, window_handle: int) -> bool:
        return self.valid

    def is_minimized(self, window_handle: int) -> bool:
        return self.minimized

    def is_visible(self, window_handle: int) -> bool:
        return self.visible

    def is_foreground(self, window_handle: int) -> bool:
        return self.foreground

    def capture_bgra(self, window_handle: int) -> _RawClientFrame:
        if self.failure is not None:
            raise self.failure
        return _RawClientFrame(
            size=ClientSize(2, 1),
            bgra_pixels=bytes((1, 2, 3, 255, 4, 5, 6, 255)),
        )


def test_static_frame_source_is_injectable_for_deterministic_consumers() -> None:
    frame = WindowsFrameSource(_api=_FakeCaptureApi()).capture(WINDOW_HANDLE)
    source: FrameSource = _StaticSource(frame)

    assert source.capture(WINDOW_HANDLE) is frame


def test_capture_returns_exact_client_bounds_and_bgr_pixels() -> None:
    frame = WindowsFrameSource(_api=_FakeCaptureApi()).capture(WINDOW_HANDLE)

    assert frame.client_size == ClientSize(2, 1)
    assert frame.pixels.dtype == np.uint8
    assert frame.pixels.shape == (1, 2, 3)
    assert frame.pixels.flags.c_contiguous
    assert frame.pixels.tolist() == [[[1, 2, 3], [4, 5, 6]]]
    assert frame.client_point_at(1, 0).x == 1
    with pytest.raises(ValueError, match="outside the client area"):
        frame.client_point_at(2, 0)


def test_capture_can_return_rgb_pixels() -> None:
    frame = WindowsFrameSource(PixelFormat.RGB, _api=_FakeCaptureApi()).capture(WINDOW_HANDLE)

    assert frame.pixels.tolist() == [[[3, 2, 1], [6, 5, 4]]]


@pytest.mark.parametrize(
    ("api", "expected_code"),
    [
        (_FakeCaptureApi(valid=False), FrameCaptureErrorCode.INVALID_WINDOW),
        (_FakeCaptureApi(visible=False), FrameCaptureErrorCode.INVALID_WINDOW),
        (_FakeCaptureApi(minimized=True), FrameCaptureErrorCode.MINIMIZED),
        (_FakeCaptureApi(foreground=False), FrameCaptureErrorCode.OCCLUDED),
        (_FakeCaptureApi(failure=OSError("GDI failure")), FrameCaptureErrorCode.CAPTURE_FAILED),
    ],
)
def test_capture_reports_typed_window_and_gdi_errors(
    api: _FakeCaptureApi, expected_code: FrameCaptureErrorCode
) -> None:
    with pytest.raises(FrameCaptureError) as error:
        WindowsFrameSource(_api=api).capture(WINDOW_HANDLE)

    assert error.value.code is expected_code


def test_default_source_rejects_unsupported_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("flyff_bot.features.vision.capture.sys.platform", "unsupported")

    with pytest.raises(FrameCaptureError) as error:
        WindowsFrameSource()

    assert error.value.code is FrameCaptureErrorCode.UNSUPPORTED_PLATFORM
