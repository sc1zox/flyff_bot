"""Developer test harness to verify camera alignment and input control on live client.

Usage examples:
    # Test full camera alignment routine (minimap zoom-out, camera zoom-out, pitch ~45°)
    uv run python scripts/test_camera_input.py align

    # Test only mouse wheel zoom-out (30 backward notches)
    uv run python scripts/test_camera_input.py scroll --notches -30

    # Test only mouse wheel zoom-in (30 forward notches)
    uv run python scripts/test_camera_input.py scroll --notches 30

    # Test pitch keys (pitch-up ceiling + pitch-down pulse)
    uv run python scripts/test_camera_input.py pitch

    # Interactive step-by-step test
    uv run python scripts/test_camera_input.py interactive
"""

from __future__ import annotations

import argparse
import sys
import time

from flyff_bot.constants import DEFAULT_PROCESS_NAME
from flyff_bot.features.automation.camera_alignment import (
    CameraAligner,
    CameraAlignmentStatus,
    frame_minimap_locator,
)
from flyff_bot.features.automation.controllers import VIRTUAL_KEY_DOWN, VIRTUAL_KEY_UP
from flyff_bot.features.input_control import WindowsInputController
from flyff_bot.features.vision.capture import WindowsFrameSource

DEFAULT_COUNTDOWN_SECONDS = 3.0
FOCUS_SETTLE_SECONDS = 0.3


def acquire_target_window(
    controller: WindowsInputController,
    process_name: str,
    countdown: float = DEFAULT_COUNTDOWN_SECONDS,
) -> int:
    """Find and focus target window, returning window handle."""
    windows = controller.find_windows(process_name)
    if not windows:
        print(f"[ERROR] No visible window found for process: {process_name!r}")
        print("Please make sure Flyff (neuz.exe) is running and logged in.")
        sys.exit(1)

    window = windows[0]
    print(f"[INFO] Found target window: {window.title!r} (handle: {window.handle})")
    controller.focus_window(window.handle)
    time.sleep(FOCUS_SETTLE_SECONDS)

    print(f"[INFO] Starting in {int(countdown)} seconds... (Emergency stop: hold END key)")
    for remaining in range(int(countdown), 0, -1):
        print(f"  > {remaining}...")
        time.sleep(1.0)

    if controller.is_aborted():
        print("[ABORT] Emergency stop (END) was pressed. Aborting.")
        sys.exit(1)

    if not controller.is_foreground(window.handle):
        print(f"[ERROR] Window {window.title!r} is not foregrounded. Aborting.")
        sys.exit(1)

    return window.handle


def test_align(controller: WindowsInputController, handle: int, skip_minimap: bool = False) -> None:
    """Run full camera alignment."""
    print("\n--- Running Full Camera Alignment ---")
    locator = None
    if not skip_minimap:
        source = WindowsFrameSource()
        locator = frame_minimap_locator(source, handle)

    aligner = CameraAligner(controller, handle, locate_minimap_geometry=locator)
    print("[1/3] Zooming minimap to hard-stop...")
    print("[2/3] Scrolling wheel backward 30 notches (zoom out to hard-stop)...")
    print("[3/3] Tilting pitch up to ceiling and pulsing down ~45°...")

    status = aligner.align()
    if status == CameraAlignmentStatus.ALIGNED:
        print(f"[SUCCESS] Camera alignment finished successfully (status: {status.value})")
    else:
        print(f"[FAILED] Camera alignment ended with status: {status.value}")


def test_scroll(controller: WindowsInputController, handle: int, notches: int) -> None:
    """Test wheel scroll."""
    direction_str = "BACKWARD / ZOOM-OUT (down)" if notches < 0 else "FORWARD / ZOOM-IN (up)"
    print(f"\n--- Testing Scroll Wheel ({abs(notches)} notches, {direction_str}) ---")

    bounds = controller.client_screen_bounds(handle)
    if bounds:
        cx = bounds.left + bounds.width // 2
        cy = bounds.top + bounds.height // 2
        print(f"[INFO] Bounds: {bounds.width}x{bounds.height} at ({bounds.left}, {bounds.top})")
        print(f"[INFO] Centering pointer at ({cx}, {cy})")

    controller.scroll_wheel_while_guarded(handle, notches)
    print("[SUCCESS] Scroll wheel dispatch completed.")


def test_pitch(
    controller: WindowsInputController,
    handle: int,
    up_seconds: float = 0.8,
    down_seconds: float = 0.35,
) -> None:
    """Test pitch adjustment keys."""
    print(f"\n--- Testing Camera Pitch (Hold UP {up_seconds}s, Pulse DOWN {down_seconds}s) ---")
    print(f"[1/2] Holding VK_UP (Up Arrow) for {up_seconds}s...")
    controller.send_key_while_guarded(handle, VIRTUAL_KEY_UP, up_seconds)
    time.sleep(0.2)

    print(f"[2/2] Pulsing VK_DOWN (Down Arrow) for {down_seconds}s...")
    controller.send_key_while_guarded(handle, VIRTUAL_KEY_DOWN, down_seconds)
    time.sleep(0.2)
    print("[SUCCESS] Pitch test completed.")


def test_interactive(controller: WindowsInputController, handle: int) -> None:
    """Interactive step-by-step camera test."""
    print("\n=== Interactive Camera Test Mode ===")

    print("\nStep 1: Test Zoom-Out (30 backward notches)")
    input("Press ENTER to execute Step 1...")
    controller.focus_window(handle)
    time.sleep(0.3)
    test_scroll(controller, handle, -30)

    print("\nStep 2: Test Pitch-Up to Ceiling (0.8s Up Arrow)")
    input("Press ENTER to execute Step 2...")
    controller.focus_window(handle)
    time.sleep(0.3)
    controller.send_key_while_guarded(handle, VIRTUAL_KEY_UP, 0.8)
    print("[DONE] Pitch up sent.")

    print("\nStep 3: Test Pitch-Down to ~45° (0.35s Down Arrow)")
    input("Press ENTER to execute Step 3...")
    controller.focus_window(handle)
    time.sleep(0.3)
    controller.send_key_while_guarded(handle, VIRTUAL_KEY_DOWN, 0.35)
    print("[DONE] Pitch down pulse sent.")

    print("\n=== Interactive Test Completed ===")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test camera alignment and input on Flyff.")
    parser.add_argument(
        "mode",
        choices=["align", "scroll", "pitch", "interactive"],
        default="align",
        nargs="?",
        help="Test mode to run (default: align)",
    )
    parser.add_argument(
        "--process-name",
        default=DEFAULT_PROCESS_NAME,
        help=f"Target executable name (default: {DEFAULT_PROCESS_NAME})",
    )
    parser.add_argument(
        "--notches",
        type=int,
        default=-30,
        help="Notches for 'scroll' mode (negative: zoom-out, positive: zoom-in, default: -30)",
    )
    parser.add_argument(
        "--up-seconds",
        type=float,
        default=0.8,
        help="Seconds to hold Up Arrow in 'pitch' mode (default: 0.8)",
    )
    parser.add_argument(
        "--down-seconds",
        type=float,
        default=0.35,
        help="Seconds to pulse Down Arrow in 'pitch' mode (default: 0.35)",
    )
    parser.add_argument(
        "--skip-minimap",
        action="store_true",
        help="Skip minimap zoom-out clicks during 'align' mode",
    )
    parser.add_argument(
        "--countdown",
        type=float,
        default=DEFAULT_COUNTDOWN_SECONDS,
        help="Countdown delay before starting in seconds (default: 3.0)",
    )

    args = parser.parse_args()
    controller = WindowsInputController()
    handle = acquire_target_window(controller, args.process_name, countdown=args.countdown)

    if args.mode == "align":
        test_align(controller, handle, skip_minimap=args.skip_minimap)
    elif args.mode == "scroll":
        test_scroll(controller, handle, args.notches)
    elif args.mode == "pitch":
        test_pitch(controller, handle, up_seconds=args.up_seconds, down_seconds=args.down_seconds)
    elif args.mode == "interactive":
        test_interactive(controller, handle)


if __name__ == "__main__":
    main()
