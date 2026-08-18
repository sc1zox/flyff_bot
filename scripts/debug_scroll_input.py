"""Comprehensive developer CLI tool to debug and test simulated scroll / camera zoom in Flyff.

This script tests multiple Win32 input methods against the active Flyff client
so you can identify exactly which method the Entropia Flyff client responds to.

Usage:
    # Interactive diagnostic menu (RECOMMENDED):
    uv run python scripts/debug_scroll_input.py --interactive

    # Direct test of specific methods:
    uv run python scripts/debug_scroll_input.py --method sendinput --notches -10
    uv run python scripts/debug_scroll_input.py --method mouse_event --notches -10
    uv run python scripts/debug_scroll_input.py --method postmessage --notches -10
    uv run python scripts/debug_scroll_input.py --method sendmessage --notches -10
    uv run python scripts/debug_scroll_input.py --method mmb_drag
    uv run python scripts/debug_scroll_input.py --method rmb_drag
    uv run python scripts/debug_scroll_input.py --method page_keys
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes import wintypes

from flyff_bot.constants import DEFAULT_PROCESS_NAME
from flyff_bot.features.input_control import WindowsInputController

WM_MOUSEWHEEL = 0x020A
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
MK_CONTROL = 0x0008
MK_SHIFT = 0x0004

MOUSE_EVENT_MOVE = 0x0001
MOUSE_EVENT_LEFT_DOWN = 0x0002
MOUSE_EVENT_LEFT_UP = 0x0004
MOUSE_EVENT_RIGHT_DOWN = 0x0008
MOUSE_EVENT_RIGHT_UP = 0x0010
MOUSE_EVENT_MIDDLE_DOWN = 0x0020
MOUSE_EVENT_MIDDLE_UP = 0x0040
MOUSE_EVENT_WHEEL = 0x0800
MOUSE_EVENT_VIRTUAL_DESK = 0x4000
MOUSE_EVENT_ABSOLUTE = 0x8000
WHEEL_DELTA = 120

VK_PRIOR = 0x21  # Page Up
VK_NEXT = 0x22  # Page Down
VK_UP = 0x26  # Up Arrow
VK_DOWN = 0x28  # Down Arrow
VK_ADD = 0x6B  # Numpad +
VK_SUBTRACT = 0x6D  # Numpad -


def makelong(low: int, high: int) -> int:
    """Create a 32-bit integer from low and high 16-bit words."""
    return ((high & 0xFFFF) << 16) | (low & 0xFFFF)


class DebugScrollHarness:
    """Diagnostic harness testing different input injection methods for Flyff camera."""

    def __init__(self, process_name: str = DEFAULT_PROCESS_NAME) -> None:
        self.controller = WindowsInputController()
        self.process_name = process_name
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._setup_api()
        self.handle = self._find_and_focus_window()

    def _setup_api(self) -> None:
        self.user32.mouse_event.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_ulong,
        ]
        self.user32.mouse_event.restype = None
        self.user32.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self.user32.PostMessageW.restype = wintypes.BOOL
        self.user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self.user32.SendMessageW.restype = wintypes.LPARAM

    def _find_and_focus_window(self) -> int:
        windows = self.controller.find_windows(self.process_name)
        if not windows:
            print(f"[ERROR] No visible window found for process: {self.process_name!r}")
            print("Please ensure Flyff (neuz.exe) is running and logged in.")
            sys.exit(1)
        win = windows[0]
        print(f"[FOUND] Window '{win.title}' (HWND: {win.handle})")
        self.focus()
        return win.handle

    def focus(self) -> None:
        """Restore and bring game client to foreground."""
        self.controller.focus_window(self.handle)
        time.sleep(0.15)

    def center_cursor(self) -> tuple[int, int]:
        """Move cursor to the center of the game client."""
        bounds = self.controller.client_screen_bounds(self.handle)
        if not bounds:
            print("[WARN] Could not determine client bounds.")
            return (0, 0)
        cx = bounds.left + bounds.width // 2
        cy = bounds.top + bounds.height // 2
        self.user32.SetCursorPos(cx, cy)
        time.sleep(0.1)
        return (cx, cy)

    # --- Method 1: SendInput ---
    def test_sendinput(self, notches: int, interval: float = 0.05) -> None:
        """SendInput with MOUSEEVENTF_WHEEL."""
        self.focus()
        self.center_cursor()
        direction = 1 if notches >= 0 else -1
        delta = direction * WHEEL_DELTA
        print(f"Executing: SendInput ({notches} notches, delta={delta}, dt={interval}s)...")
        for _ in range(abs(notches)):
            if self.controller.is_aborted():
                print("[ABORT] END key pressed.")
                return
            self.controller.scroll_wheel_while_guarded(self.handle, direction)
            time.sleep(interval)
        print("  -> SendInput complete.")

    # --- Method 2: mouse_event (legacy Win32 API) ---
    def test_mouse_event(self, notches: int, interval: float = 0.05) -> None:
        """Legacy mouse_event API with MOUSEEVENTF_WHEEL."""
        self.focus()
        self.center_cursor()
        direction = 1 if notches >= 0 else -1
        delta = (direction * WHEEL_DELTA) & 0xFFFFFFFF
        print(f"Executing: mouse_event ({notches} notches, delta={direction * WHEEL_DELTA})...")
        for _ in range(abs(notches)):
            if self.controller.is_aborted():
                print("[ABORT] END key pressed.")
                return
            self.user32.mouse_event(MOUSE_EVENT_WHEEL, 0, 0, delta, 0)
            time.sleep(interval)
        print("  -> mouse_event complete.")

    # --- Method 3: PostMessage WM_MOUSEWHEEL ---
    def test_postmessage(self, notches: int, interval: float = 0.05) -> None:
        """PostMessage WM_MOUSEWHEEL directly to the window message queue."""
        self.focus()
        cx, cy = self.center_cursor()
        direction = 1 if notches >= 0 else -1
        delta = direction * WHEEL_DELTA
        wparam = makelong(0, delta)
        lparam = makelong(cx, cy)
        print(f"Executing: PostMessage(WM_MOUSEWHEEL) (wParam={wparam:#x}, l=({cx},{cy}))...")
        for _ in range(abs(notches)):
            if self.controller.is_aborted():
                print("[ABORT] END key pressed.")
                return
            self.user32.PostMessageW(self.handle, WM_MOUSEWHEEL, wparam, lparam)
            time.sleep(interval)
        print("  -> PostMessage complete.")

    # --- Method 4: SendMessage WM_MOUSEWHEEL ---
    def test_sendmessage(self, notches: int, interval: float = 0.05) -> None:
        """SendMessage WM_MOUSEWHEEL synchronously to the window procedure."""
        self.focus()
        cx, cy = self.center_cursor()
        direction = 1 if notches >= 0 else -1
        delta = direction * WHEEL_DELTA
        wparam = makelong(0, delta)
        lparam = makelong(cx, cy)
        print(f"Executing: SendMessage(WM_MOUSEWHEEL) (wParam={wparam:#x}, l=({cx},{cy}))...")
        for _ in range(abs(notches)):
            if self.controller.is_aborted():
                print("[ABORT] END key pressed.")
                return
            self.user32.SendMessageW(self.handle, WM_MOUSEWHEEL, wparam, lparam)
            time.sleep(interval)
        print("  -> SendMessage complete.")

    # --- Method 5: Middle-Mouse-Button Drag ---
    def test_mmb_drag(self, dy_pixels: int = 200, duration: float = 0.5) -> None:
        """Simulate Middle Mouse Button (MMB) press + drag."""
        self.focus()
        cx, cy = self.center_cursor()
        print(f"Executing: MMB Drag (from ({cx}, {cy}) by dy={dy_pixels})...")
        self.user32.mouse_event(MOUSE_EVENT_MIDDLE_DOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        steps = 20
        for i in range(1, steps + 1):
            y = cy + int(dy_pixels * (i / steps))
            self.user32.SetCursorPos(cx, y)
            time.sleep(duration / steps)
        self.user32.mouse_event(MOUSE_EVENT_MIDDLE_UP, 0, 0, 0, 0)
        time.sleep(0.1)
        print("  -> MMB drag complete.")

    # --- Method 6: Right-Mouse-Button Drag ---
    def test_rmb_drag(self, dy_pixels: int = 200, duration: float = 0.5) -> None:
        """Simulate Right Mouse Button (RMB) press + drag."""
        self.focus()
        cx, cy = self.center_cursor()
        print(f"Executing: RMB Drag (from ({cx}, {cy}) by dy={dy_pixels})...")
        self.user32.mouse_event(MOUSE_EVENT_RIGHT_DOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        steps = 20
        for i in range(1, steps + 1):
            y = cy + int(dy_pixels * (i / steps))
            self.user32.SetCursorPos(cx, y)
            time.sleep(duration / steps)
        self.user32.mouse_event(MOUSE_EVENT_RIGHT_UP, 0, 0, 0, 0)
        time.sleep(0.1)
        print("  -> RMB drag complete.")

    # --- Method 7: Keyboard Page Up / Page Down ---
    def test_page_keys(self) -> None:
        """Test Page Up and Page Down keys."""
        self.focus()
        print("Executing: Keyboard Page Up / Page Down...")
        print("  > Holding Page Up (VK_PRIOR) for 1.0s...")
        self.controller.send_key_while_guarded(self.handle, VK_PRIOR, 1.0)
        time.sleep(0.3)
        print("  > Holding Page Down (VK_NEXT) for 1.0s...")
        self.controller.send_key_while_guarded(self.handle, VK_NEXT, 1.0)
        print("  -> Page keys complete.")

    # --- Method 8: Keyboard Numpad +/- ---
    def test_numpad_keys(self) -> None:
        """Test Numpad + and - keys."""
        self.focus()
        print("Executing: Numpad +/- keys...")
        print("  > Holding Numpad + (VK_ADD) for 1.0s...")
        self.controller.send_key_while_guarded(self.handle, VK_ADD, 1.0)
        time.sleep(0.3)
        print("  > Holding Numpad - (VK_SUBTRACT) for 1.0s...")
        self.controller.send_key_while_guarded(self.handle, VK_SUBTRACT, 1.0)
        print("  -> Numpad keys complete.")


def run_interactive(harness: DebugScrollHarness) -> None:
    """Run interactive CLI menu."""
    menu = f"""
===================================================================
      FLYFF CAMERA & SCROLL INPUT DIAGNOSTIC HARNESS
===================================================================
Target: Handle {harness.handle}

Select an input method to test on the live Flyff client:

  [1] SendInput Wheel DOWN (-15 notches, zoom out)
  [2] SendInput Wheel UP   (+15 notches, zoom in)
  [3] SendInput Wheel Fast Burst (-30 notches, 10ms interval)

  [4] mouse_event Wheel DOWN (-15 notches)
  [5] mouse_event Wheel UP   (+15 notches)

  [6] PostMessage WM_MOUSEWHEEL DOWN (-15 notches)
  [7] SendMessage WM_MOUSEWHEEL DOWN (-15 notches)

  [8] Middle-Mouse-Button (MMB) Drag UP / DOWN
  [9] Right-Mouse-Button (RMB) Drag UP / DOWN

  [P] Page Up / Page Down Keys (1.0s each)
  [N] Numpad + / - Keys (1.0s each)
  [A] Arrow Keys Up / Down (Pitch 0.8s / 0.35s)

  [C] Re-center Cursor in Client Window
  [Q] Quit

===================================================================
"""

    while True:
        print(menu)
        choice = input("Enter option [1-9, P, N, A, C, Q]: ").strip().upper()
        if choice == "Q":
            print("Exiting.")
            break
        elif choice == "1":
            harness.test_sendinput(notches=-15)
        elif choice == "2":
            harness.test_sendinput(notches=15)
        elif choice == "3":
            harness.test_sendinput(notches=-30, interval=0.01)
        elif choice == "4":
            harness.test_mouse_event(notches=-15)
        elif choice == "5":
            harness.test_mouse_event(notches=15)
        elif choice == "6":
            harness.test_postmessage(notches=-15)
        elif choice == "7":
            harness.test_sendmessage(notches=-15)
        elif choice == "8":
            harness.test_mmb_drag(dy_pixels=-200)
            time.sleep(0.5)
            harness.test_mmb_drag(dy_pixels=200)
        elif choice == "9":
            harness.test_rmb_drag(dy_pixels=-200)
            time.sleep(0.5)
            harness.test_rmb_drag(dy_pixels=200)
        elif choice == "P":
            harness.test_page_keys()
        elif choice == "N":
            harness.test_numpad_keys()
        elif choice == "A":
            harness.focus()
            print("Testing Arrow Keys UP (0.8s) and DOWN (0.35s)...")
            harness.controller.send_key_while_guarded(harness.handle, VK_UP, 0.8)
            time.sleep(0.2)
            harness.controller.send_key_while_guarded(harness.handle, VK_DOWN, 0.35)
            print("Done.")
        elif choice == "C":
            harness.focus()
            cx, cy = harness.center_cursor()
            print(f"Cursor centered at screen ({cx}, {cy}).")
        else:
            print("Unknown option. Please try again.")

        time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Flyff camera scroll debugging harness.")
    parser.add_argument(
        "--interactive", "-i", action="store_true", help="Launch interactive menu mode"
    )
    parser.add_argument(
        "--method",
        choices=[
            "sendinput",
            "mouse_event",
            "postmessage",
            "sendmessage",
            "mmb_drag",
            "rmb_drag",
            "page_keys",
            "numpad_keys",
        ],
        default="sendinput",
        help="Specific method to test (default: sendinput)",
    )
    parser.add_argument(
        "--notches",
        type=int,
        default=-15,
        help="Number of wheel notches (negative: zoom-out, positive: zoom-in, default: -15)",
    )
    parser.add_argument(
        "--process-name",
        default=DEFAULT_PROCESS_NAME,
        help=f"Target executable name (default: {DEFAULT_PROCESS_NAME})",
    )

    args = parser.parse_args()
    harness = DebugScrollHarness(process_name=args.process_name)

    if args.interactive or len(sys.argv) == 1:
        run_interactive(harness)
        return

    if args.method == "sendinput":
        harness.test_sendinput(notches=args.notches)
    elif args.method == "mouse_event":
        harness.test_mouse_event(notches=args.notches)
    elif args.method == "postmessage":
        harness.test_postmessage(notches=args.notches)
    elif args.method == "sendmessage":
        harness.test_sendmessage(notches=args.notches)
    elif args.method == "mmb_drag":
        harness.test_mmb_drag(dy_pixels=-200 if args.notches < 0 else 200)
    elif args.method == "rmb_drag":
        harness.test_rmb_drag(dy_pixels=-200 if args.notches < 0 else 200)
    elif args.method == "page_keys":
        harness.test_page_keys()
    elif args.method == "numpad_keys":
        harness.test_numpad_keys()


if __name__ == "__main__":
    main()
