"""Windows adapter for visible-window discovery and foreground input."""

from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes

from flyff_bot.features.input_control.models import (
    InputControlError,
    InputErrorCode,
    ScreenRect,
    WindowRef,
)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SHOW_WINDOW_RESTORE = 9
INPUT_TYPE_MOUSE = 0
INPUT_TYPE_KEYBOARD = 1
KEY_EVENT_KEY_UP = 0x0002
MOUSE_EVENT_MOVE = 0x0001
MOUSE_EVENT_LEFT_DOWN = 0x0002
MOUSE_EVENT_LEFT_UP = 0x0004
MOUSE_EVENT_WHEEL = 0x0800
MOUSE_EVENT_VIRTUAL_DESK = 0x4000
MOUSE_EVENT_ABSOLUTE = 0x8000
# One detent of a standard mouse wheel; a positive value rotates the wheel forward.
WHEEL_DELTA = 120
DWORD_MASK = 0xFFFFFFFF
# SendInput maps an absolute mouse move onto this range across the whole virtual desktop.
ABSOLUTE_COORDINATE_RANGE = 65535
SYSTEM_METRIC_VIRTUAL_SCREEN_LEFT = 76
SYSTEM_METRIC_VIRTUAL_SCREEN_TOP = 77
SYSTEM_METRIC_VIRTUAL_SCREEN_WIDTH = 78
SYSTEM_METRIC_VIRTUAL_SCREEN_HEIGHT = 79
SCROLL_STEP_INTERVAL_SECONDS = 0.03
# The client routes a wheel notch to whatever its own input handling believes the pointer
# hovers, and it only learns that from a processed mouse move, so the pointer move to the
# viewport has to be dispatched and consumed before the first notch is sent.
POINTER_MOVE_SETTLE_SECONDS = 0.15
VIRTUAL_KEY_END = 0x23
KEY_IS_DOWN_MASK = 0x8000
MAXIMUM_PROCESS_PATH_LENGTH = 32_768
FOCUS_SETTLE_SECONDS = 0.25
WAIT_POLL_SECONDS = 0.02


class ClientRect(ctypes.Structure):
    """Win32 RECT structure holding a client area in client coordinates."""

    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class KeyboardInput(ctypes.Structure):
    """Win32 KEYBDINPUT structure."""

    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class MouseInput(ctypes.Structure):
    """Win32 MOUSEINPUT structure."""

    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class InputData(ctypes.Union):
    """Win32 INPUT union."""

    _fields_ = [  # noqa: RUF012 -- ctypes unions require a mutable class-level declaration.
        ("keyboard", KeyboardInput),
        ("mouse", MouseInput),
    ]


class Input(ctypes.Structure):
    """Win32 INPUT structure."""

    _anonymous_ = ("data",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("data", InputData),
    ]


class WindowsInputController:
    """Own the Win32 resources used by the input-control feature."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise InputControlError(InputErrorCode.UNSUPPORTED_PLATFORM)
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_api()

    def _configure_api(self) -> None:
        self._kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

        self._user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self._user32.IsWindowVisible.restype = wintypes.BOOL
        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._user32.IsWindow.restype = wintypes.BOOL
        self._user32.IsIconic.argtypes = [wintypes.HWND]
        self._user32.IsIconic.restype = wintypes.BOOL
        self._user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(ClientRect)]
        self._user32.GetClientRect.restype = wintypes.BOOL
        self._user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self._user32.GetWindowTextLengthW.restype = ctypes.c_int
        self._user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self._user32.GetWindowTextW.restype = ctypes.c_int
        self._user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.ShowWindow.restype = wintypes.BOOL
        self._user32.BringWindowToTop.argtypes = [wintypes.HWND]
        self._user32.BringWindowToTop.restype = wintypes.BOOL
        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.SetForegroundWindow.restype = wintypes.BOOL
        self._user32.GetForegroundWindow.argtypes = []
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self._user32.GetAsyncKeyState.restype = ctypes.c_short
        self._user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self._user32.ClientToScreen.restype = wintypes.BOOL
        self._user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self._user32.SetCursorPos.restype = wintypes.BOOL
        self._user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        self._user32.GetSystemMetrics.restype = ctypes.c_int
        self._user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
        self._user32.SendInput.restype = wintypes.UINT

    def _process_name(self, window_handle: int) -> str:
        process_id = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(window_handle, ctypes.byref(process_id))
        process_handle = self._kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            process_id.value,
        )
        if not process_handle:
            return ""
        try:
            size = wintypes.DWORD(MAXIMUM_PROCESS_PATH_LENGTH)
            path = ctypes.create_unicode_buffer(size.value)
            if self._kernel32.QueryFullProcessImageNameW(
                process_handle,
                0,
                path,
                ctypes.byref(size),
            ):
                return os.path.basename(path.value)
            return ""
        finally:
            self._kernel32.CloseHandle(process_handle)

    def find_windows(self, process_name: str) -> list[WindowRef]:
        """Find visible top-level windows owned by a named executable."""

        matches: list[WindowRef] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type  # type: ignore[untyped-decorator]  # ctypes callback factories are untyped.
        def callback(window_handle: int, _parameter: int) -> bool:
            actual_name = self._process_name(window_handle)
            if (
                self._user32.IsWindowVisible(window_handle)
                and actual_name.casefold() == process_name.casefold()
            ):
                length = self._user32.GetWindowTextLengthW(window_handle)
                title = ctypes.create_unicode_buffer(length + 1)
                self._user32.GetWindowTextW(window_handle, title, len(title))
                matches.append(WindowRef(handle=window_handle, title=title.value))
            return True

        self._user32.EnumWindows(callback, 0)
        return matches

    def focus_window(self, window_handle: int) -> None:
        """Restore and focus a window before input is sent."""

        self._user32.ShowWindow(window_handle, SHOW_WINDOW_RESTORE)
        self._user32.BringWindowToTop(window_handle)
        self._user32.SetForegroundWindow(window_handle)
        deadline = time.monotonic() + FOCUS_SETTLE_SECONDS
        while time.monotonic() < deadline:
            if self.is_foreground(window_handle):
                return
            time.sleep(WAIT_POLL_SECONDS)
        if (
            not self.is_foreground(window_handle)
            and not self._user32.SetForegroundWindow(window_handle)
            and not self.is_foreground(window_handle)
        ):
            raise InputControlError(InputErrorCode.FOCUS_FAILED)

    def client_screen_bounds(self, window_handle: int) -> ScreenRect | None:
        """Return the target's client area in desktop pixels, or None when unavailable."""

        if not self._user32.IsWindow(window_handle) or not self._user32.IsWindowVisible(
            window_handle
        ):
            return None
        if self._user32.IsIconic(window_handle):
            return None
        rect = ClientRect()
        if not self._user32.GetClientRect(window_handle, ctypes.byref(rect)):
            return None
        origin = wintypes.POINT(rect.left, rect.top)
        if not self._user32.ClientToScreen(window_handle, ctypes.byref(origin)):
            return None
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return None
        return ScreenRect(left=origin.x, top=origin.y, width=width, height=height)

    def is_aborted(self) -> bool:
        """Return whether the emergency-stop key is currently held."""

        return bool(self._user32.GetAsyncKeyState(VIRTUAL_KEY_END) & KEY_IS_DOWN_MASK)

    def is_foreground(self, window_handle: int) -> bool:
        """Return whether a target window remains foregrounded for combat input."""

        foreground_handle = self._user32.GetForegroundWindow()
        return bool(foreground_handle and int(foreground_handle) == window_handle)

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        """Press and release one virtual key while honoring the emergency stop."""

        key_down = Input(
            type=INPUT_TYPE_KEYBOARD,
            keyboard=KeyboardInput(wVk=virtual_key),
        )
        key_up = Input(
            type=INPUT_TYPE_KEYBOARD,
            keyboard=KeyboardInput(wVk=virtual_key, dwFlags=KEY_EVENT_KEY_UP),
        )
        if self._user32.SendInput(1, ctypes.byref(key_down), ctypes.sizeof(Input)) != 1:
            raise ctypes.WinError(ctypes.get_last_error())

        deadline = time.monotonic() + duration_seconds
        try:
            while time.monotonic() < deadline and not self.is_aborted():
                remaining = deadline - time.monotonic()
                time.sleep(min(WAIT_POLL_SECONDS, max(0.0, remaining)))
        finally:
            if self._user32.SendInput(1, ctypes.byref(key_up), ctypes.sizeof(Input)) != 1:
                raise ctypes.WinError(ctypes.get_last_error())

    def send_key_while_guarded(
        self, window_handle: int, virtual_key: int, duration_seconds: float
    ) -> None:
        """Hold a search key only while END is clear and the client stays foregrounded."""

        key_down = Input(type=INPUT_TYPE_KEYBOARD, keyboard=KeyboardInput(wVk=virtual_key))
        key_up = Input(
            type=INPUT_TYPE_KEYBOARD,
            keyboard=KeyboardInput(wVk=virtual_key, dwFlags=KEY_EVENT_KEY_UP),
        )
        if self._user32.SendInput(1, ctypes.byref(key_down), ctypes.sizeof(Input)) != 1:
            raise ctypes.WinError(ctypes.get_last_error())
        deadline = time.monotonic() + duration_seconds
        try:
            while (
                time.monotonic() < deadline
                and not self.is_aborted()
                and self.is_foreground(window_handle)
            ):
                remaining = deadline - time.monotonic()
                time.sleep(min(WAIT_POLL_SECONDS, max(0.0, remaining)))
        finally:
            if self._user32.SendInput(1, ctypes.byref(key_up), ctypes.sizeof(Input)) != 1:
                raise ctypes.WinError(ctypes.get_last_error())

    def _send_mouse_event(self, event: Input) -> None:
        """Dispatch one mouse event, raising the Win32 error when it is not accepted."""

        if self._user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input)) != 1:
            raise ctypes.WinError(ctypes.get_last_error())

    def _absolute_pointer_coordinates(
        self, x_coordinate: int, y_coordinate: int
    ) -> tuple[int, int]:
        """Normalize desktop pixels onto the absolute range SendInput expects."""

        left = self._user32.GetSystemMetrics(SYSTEM_METRIC_VIRTUAL_SCREEN_LEFT)
        top = self._user32.GetSystemMetrics(SYSTEM_METRIC_VIRTUAL_SCREEN_TOP)
        width = max(self._user32.GetSystemMetrics(SYSTEM_METRIC_VIRTUAL_SCREEN_WIDTH), 1)
        height = max(self._user32.GetSystemMetrics(SYSTEM_METRIC_VIRTUAL_SCREEN_HEIGHT), 1)
        return (
            round((x_coordinate - left) * ABSOLUTE_COORDINATE_RANGE / width),
            round((y_coordinate - top) * ABSOLUTE_COORDINATE_RANGE / height),
        )

    def _move_pointer(self, x_coordinate: int, y_coordinate: int) -> None:
        """Move the pointer to desktop pixels through an injected absolute mouse move.

        ``SetCursorPos`` teleports the cursor without placing a move into the injected
        input stream the client reads, so a client that tracks the pointer from move
        events keeps hit-testing later input against the position it last saw.
        """

        absolute_x, absolute_y = self._absolute_pointer_coordinates(x_coordinate, y_coordinate)
        self._send_mouse_event(
            Input(
                type=INPUT_TYPE_MOUSE,
                mouse=MouseInput(
                    dx=absolute_x,
                    dy=absolute_y,
                    dwFlags=MOUSE_EVENT_MOVE | MOUSE_EVENT_ABSOLUTE | MOUSE_EVENT_VIRTUAL_DESK,
                ),
            )
        )

    def scroll_wheel_while_guarded(self, window_handle: int, notches: int) -> None:
        """Send discrete wheel notches while END is clear and the client stays foregrounded.

        A positive count rotates the wheel forwards, which is the direction Flyff zooms
        the camera out towards its hard stop.
        """

        if self.is_aborted() or not self.is_foreground(window_handle):
            return
        bounds = self.client_screen_bounds(window_handle)
        if bounds is None:
            # Without the client rectangle the notches would land wherever the pointer was
            # left, which after the minimap zoom-out clicks is the HUD and not the camera.
            return
        # Windows routes wheel input by cursor position, so the notches have to land over
        # the client area rather than whatever window is under the pointer.
        self._move_pointer(bounds.left + bounds.width // 2, bounds.top + bounds.height // 2)
        time.sleep(POINTER_MOVE_SETTLE_SECONDS)
        direction = 1 if notches >= 0 else -1
        for _ in range(abs(notches)):
            if self.is_aborted() or not self.is_foreground(window_handle):
                return
            self._send_mouse_event(
                Input(
                    type=INPUT_TYPE_MOUSE,
                    mouse=MouseInput(
                        mouseData=(direction * WHEEL_DELTA) & DWORD_MASK,
                        dwFlags=MOUSE_EVENT_WHEEL,
                    ),
                )
            )
            time.sleep(SCROLL_STEP_INTERVAL_SECONDS)

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None:
        """Send one left click at client-relative coordinates."""

        point = wintypes.POINT(x_coordinate, y_coordinate)
        if not self._user32.ClientToScreen(window_handle, ctypes.byref(point)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not self._user32.SetCursorPos(point.x, point.y):
            raise ctypes.WinError(ctypes.get_last_error())

        events = (Input * 2)(
            Input(type=INPUT_TYPE_MOUSE, mouse=MouseInput(dwFlags=MOUSE_EVENT_LEFT_DOWN)),
            Input(type=INPUT_TYPE_MOUSE, mouse=MouseInput(dwFlags=MOUSE_EVENT_LEFT_UP)),
        )
        if self._user32.SendInput(len(events), events, ctypes.sizeof(Input)) != len(events):
            raise ctypes.WinError(ctypes.get_last_error())
