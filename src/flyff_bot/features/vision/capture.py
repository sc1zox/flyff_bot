"""Documented Win32 GDI capture of foreground client areas."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from flyff_bot.features.vision.models import (
    CapturedFrame,
    ClientSize,
    FrameCaptureError,
    FrameCaptureErrorCode,
    PixelFormat,
)

RASTER_OPERATION_COPY = 0x00CC0020
CAPTURE_LAYERED_WINDOWS = 0x40000000
BITS_PER_PIXEL = 32
DIB_RGB_COLORS = 0
BI_RGB = 0


class FrameSource(Protocol):
    """Injectable provider of deterministic or live client frames."""

    def capture(self, window_handle: int) -> CapturedFrame:
        """Capture the current client frame for a target window handle."""


@dataclass(frozen=True, slots=True)
class _RawClientFrame:
    """Unconverted top-down BGRA pixels read from a client device context."""

    size: ClientSize
    bgra_pixels: bytes


class _CaptureApi(Protocol):
    """Small Win32 seam used to test window states without a live desktop."""

    def is_window(self, window_handle: int) -> bool: ...

    def is_minimized(self, window_handle: int) -> bool: ...

    def is_visible(self, window_handle: int) -> bool: ...

    def is_foreground(self, window_handle: int) -> bool: ...

    def capture_bgra(self, window_handle: int) -> _RawClientFrame: ...


class WindowsFrameSource:
    """Capture a foreground Flyff client area as a contiguous BGR or RGB array."""

    def __init__(
        self,
        pixel_format: PixelFormat = PixelFormat.BGR,
        *,
        _api: _CaptureApi | None = None,
    ) -> None:
        if _api is None:
            if sys.platform != "win32":
                raise FrameCaptureError(FrameCaptureErrorCode.UNSUPPORTED_PLATFORM)
            _api = _Win32CaptureApi()
        self._api = _api
        self._pixel_format = pixel_format

    def capture(self, window_handle: int) -> CapturedFrame:
        """Capture exactly the target's client area after foreground validation."""

        if not self._api.is_window(window_handle) or not self._api.is_visible(window_handle):
            raise FrameCaptureError(FrameCaptureErrorCode.INVALID_WINDOW)
        if self._api.is_minimized(window_handle):
            raise FrameCaptureError(FrameCaptureErrorCode.MINIMIZED)
        if not self._api.is_foreground(window_handle):
            raise FrameCaptureError(FrameCaptureErrorCode.OCCLUDED)
        try:
            raw_frame = self._api.capture_bgra(window_handle)
        except OSError as error:
            raise FrameCaptureError(FrameCaptureErrorCode.CAPTURE_FAILED) from error
        pixels = np.frombuffer(raw_frame.bgra_pixels, dtype=np.uint8).reshape(
            raw_frame.size.height,
            raw_frame.size.width,
            BITS_PER_PIXEL // 8,
        )
        if self._pixel_format is PixelFormat.BGR:
            converted = pixels[:, :, :3]
        else:
            converted = pixels[:, :, (2, 1, 0)]
        return CapturedFrame(
            pixels=np.ascontiguousarray(converted),
            client_size=raw_frame.size,
            pixel_format=self._pixel_format,
        )


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("bmiHeader", _BitmapInfoHeader), ("bmiColors", wintypes.DWORD * 3)]


class _Win32CaptureApi:
    """Private documented GDI implementation with deterministic resource cleanup."""

    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self._configure_api()

    def _configure_api(self) -> None:
        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._user32.IsWindow.restype = wintypes.BOOL
        self._user32.IsIconic.argtypes = [wintypes.HWND]
        self._user32.IsIconic.restype = wintypes.BOOL
        self._user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self._user32.IsWindowVisible.restype = wintypes.BOOL
        self._user32.GetForegroundWindow.argtypes = []
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(_Rect)]
        self._user32.GetClientRect.restype = wintypes.BOOL
        self._user32.GetDC.argtypes = [wintypes.HWND]
        self._user32.GetDC.restype = wintypes.HDC
        self._user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self._user32.ReleaseDC.restype = ctypes.c_int
        self._gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self._gdi32.CreateCompatibleDC.restype = wintypes.HDC
        self._gdi32.DeleteDC.argtypes = [wintypes.HDC]
        self._gdi32.DeleteDC.restype = wintypes.BOOL
        self._gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        self._gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        self._gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        self._gdi32.SelectObject.restype = wintypes.HGDIOBJ
        self._gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self._gdi32.DeleteObject.restype = wintypes.BOOL
        self._gdi32.BitBlt.argtypes = [
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.DWORD,
        ]
        self._gdi32.BitBlt.restype = wintypes.BOOL
        self._gdi32.GetDIBits.argtypes = [
            wintypes.HDC,
            wintypes.HBITMAP,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.c_void_p,
            ctypes.POINTER(_BitmapInfo),
            wintypes.UINT,
        ]
        self._gdi32.GetDIBits.restype = ctypes.c_int

    def is_window(self, window_handle: int) -> bool:
        return bool(self._user32.IsWindow(window_handle))

    def is_minimized(self, window_handle: int) -> bool:
        return bool(self._user32.IsIconic(window_handle))

    def is_visible(self, window_handle: int) -> bool:
        return bool(self._user32.IsWindowVisible(window_handle))

    def is_foreground(self, window_handle: int) -> bool:
        return int(self._user32.GetForegroundWindow()) == window_handle

    def capture_bgra(self, window_handle: int) -> _RawClientFrame:
        rect = _Rect()
        if not self._user32.GetClientRect(window_handle, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        size = ClientSize(width=rect.right - rect.left, height=rect.bottom - rect.top)
        source_dc = self._user32.GetDC(window_handle)
        if not source_dc:
            raise ctypes.WinError(ctypes.get_last_error())
        memory_dc = self._gdi32.CreateCompatibleDC(source_dc)
        bitmap = wintypes.HBITMAP()
        previous_bitmap = wintypes.HGDIOBJ()
        try:
            if not memory_dc:
                raise ctypes.WinError(ctypes.get_last_error())
            bitmap = self._gdi32.CreateCompatibleBitmap(source_dc, size.width, size.height)
            if not bitmap:
                raise ctypes.WinError(ctypes.get_last_error())
            previous_bitmap = self._gdi32.SelectObject(memory_dc, bitmap)
            if not previous_bitmap:
                raise ctypes.WinError(ctypes.get_last_error())
            raster_operation = RASTER_OPERATION_COPY | CAPTURE_LAYERED_WINDOWS
            if not self._gdi32.BitBlt(
                memory_dc, 0, 0, size.width, size.height, source_dc, 0, 0, raster_operation
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            data_size = size.width * size.height * (BITS_PER_PIXEL // 8)
            pixels = (ctypes.c_ubyte * data_size)()
            bitmap_info = _BitmapInfo(
                bmiHeader=_BitmapInfoHeader(
                    biSize=ctypes.sizeof(_BitmapInfoHeader),
                    biWidth=size.width,
                    biHeight=-size.height,
                    biPlanes=1,
                    biBitCount=BITS_PER_PIXEL,
                    biCompression=BI_RGB,
                    biSizeImage=data_size,
                )
            )
            copied_rows = self._gdi32.GetDIBits(
                memory_dc,
                bitmap,
                0,
                size.height,
                pixels,
                ctypes.byref(bitmap_info),
                DIB_RGB_COLORS,
            )
            if copied_rows != size.height:
                raise ctypes.WinError(ctypes.get_last_error())
            return _RawClientFrame(size=size, bgra_pixels=bytes(pixels))
        finally:
            if previous_bitmap:
                self._gdi32.SelectObject(memory_dc, previous_bitmap)
            if bitmap:
                self._gdi32.DeleteObject(bitmap)
            if memory_dc:
                self._gdi32.DeleteDC(memory_dc)
            self._user32.ReleaseDC(window_handle, source_dc)
