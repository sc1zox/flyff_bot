"""Developer calibration harness that records minimap frame sequences from the live client.

This is not part of the shipped application and is never imported by `flyff_bot`. It exists
to produce the raw evidence that the minimap odometry stories need and that cannot be
obtained without running the game: how phase correlation behaves against terrain that
really streams in at the aperture edge, how far the map may scroll between two frames
before the correlation collapses, which way the player marker points, and whether the ring
geometry stays fixed-pixel across zoom levels and window sizes.

Because it only reads frames and holds one movement key, it stays inside the project's
safety boundaries: it captures through the documented GDI path, requires the client to be
foregrounded, and honours the `END` emergency stop through the shared input controller.

Its console output is developer diagnostics rather than shipped user-visible text, so it
deliberately does not go through the locale files.

Usage (run on the Windows machine, with the client already running):

    uv run python scripts/capture_minimap_samples.py burst --key w --label walk-1
    uv run python scripts/capture_minimap_samples.py burst --key right --hold 6 --full \
        --label turn-1
    uv run python scripts/capture_minimap_samples.py still --label zoom-default
    uv run python scripts/capture_minimap_samples.py still --label res-1280x720

Each run writes lossless PNG frames plus a `manifest.json` holding the per-frame
`time.perf_counter()` timestamps, which are the only valid time base for a displacement
measurement: the interval between two captures is not the key-hold duration.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt

from flyff_bot.constants import DEFAULT_PROCESS_NAME
from flyff_bot.features.input_control import WindowsInputController, parse_virtual_key
from flyff_bot.features.vision.capture import WindowsFrameSource
from flyff_bot.features.vision.models import FrameCaptureError

# The minimap ring was measured at centre (1512, 135) with radius 68 px in a 1600 px wide
# client, i.e. 88 px left of the right edge. This crop is anchored to the right edge with
# generous margin so it still contains the whole widget if the fixed-pixel hypothesis holds,
# and visibly clips it if it does not.
MINIMAP_CROP_WIDTH_PIXELS = 360
MINIMAP_CROP_HEIGHT_PIXELS = 320

DEFAULT_COUNTDOWN_SECONDS = 3.0
FOCUS_SETTLE_SECONDS = 0.3
DEFAULT_BURST_HOLD_SECONDS = 3.0
# Capturing past the key release records the client's own deceleration, which a
# command-driven estimator cannot know about.
DEFAULT_BURST_TAIL_SECONDS = 0.8
DEFAULT_STILL_FRAME_COUNT = 3
STILL_FRAME_INTERVAL_SECONDS = 0.25
# Frames are buffered in memory during a burst so PNG encoding never throttles the capture
# rate. A minimap crop costs roughly 0.35 MB, a full 1600x900 frame roughly 4.3 MB, hence the
# two different budgets and the throttle that keeps a full-frame run inside its budget for
# long enough to cover a complete turn.
MAX_BURST_CROP_FRAMES = 400
MAX_BURST_FULL_FRAMES = 80
FULL_FRAME_INTERVAL_SECONDS = 0.1
PNG_COMPRESSION_LEVEL = 3
DEFAULT_OUTPUT_ROOT = Path("data/calibration")
# `WindowsFrameSource` captures the client area through `GetClientRect`, so frame row 0 is the
# first pixel below the title bar. The frames in `data/` that the odometry spike measured are
# whole-window captures and carry roughly 31 extra rows of title bar, which is why the manifest
# names its origin: the two coordinate systems must be re-based before they are compared.
CAPTURE_ORIGIN = "client_area"
# Reference frames are always stored uncropped so the recording keeps an absolute record of
# what the character was doing and facing, which the minimap crop alone cannot show.
FIRST_REFERENCE_FILE_NAME = "reference_first.png"
LAST_REFERENCE_FILE_NAME = "reference_last.png"


@dataclass(frozen=True, slots=True)
class FrameRecord:
    """One captured frame and the perf-counter window it was read in."""

    index: int
    file_name: str
    capture_started_at: float
    capture_finished_at: float


@dataclass
class RunManifest:
    """Everything an offline measurement needs to interpret one recorded sequence."""

    protocol: str
    label: str
    started_at_utc: str
    process_name: str
    window_title: str
    capture_origin: str
    client_width: int
    client_height: int
    cropped: bool
    crop_left: int
    crop_top: int
    crop_width: int
    crop_height: int
    held_key: str | None = None
    hold_seconds: float | None = None
    key_down_at: float | None = None
    key_up_at: float | None = None
    aborted_reason: str | None = None
    frames: list[FrameRecord] = field(default_factory=list)


@dataclass(slots=True)
class _HeldKeyTiming:
    """Perf-counter bracket around the guarded key hold running on its own thread."""

    down_at: float | None = None
    up_at: float | None = None
    error: BaseException | None = None


def _crop_minimap(
    pixels: npt.NDArray[np.uint8],
) -> tuple[npt.NDArray[np.uint8], int, int]:
    """Return the top-right region containing the minimap plus its client-space origin."""

    height, width = pixels.shape[:2]
    left = max(0, width - MINIMAP_CROP_WIDTH_PIXELS)
    bottom = min(height, MINIMAP_CROP_HEIGHT_PIXELS)
    return np.ascontiguousarray(pixels[0:bottom, left:width]), left, 0


def _hold_key_on_thread(
    controller: WindowsInputController,
    window_handle: int,
    virtual_key: int,
    seconds: float,
    timing: _HeldKeyTiming,
) -> None:
    """Hold one movement key through the guarded path while the caller keeps capturing."""

    timing.down_at = time.perf_counter()
    try:
        controller.send_key_while_guarded(window_handle, virtual_key, seconds)
    except (OSError, RuntimeError) as error:  # surfaced on the main thread
        timing.error = error
    finally:
        timing.up_at = time.perf_counter()


def _capture_until(
    source: WindowsFrameSource,
    controller: WindowsInputController,
    window_handle: int,
    deadline: float,
    buffer: list[tuple[float, float, npt.NDArray[np.uint8]]],
    *,
    keep_full_frames: bool,
    max_frames: int,
    interval_seconds: float,
) -> str | None:
    """Capture frames until the deadline; return an abort reason if one occurred."""

    while time.perf_counter() < deadline and len(buffer) < max_frames:
        if controller.is_aborted():
            return "emergency_stop"
        started_at = time.perf_counter()
        try:
            frame = source.capture(window_handle)
        except FrameCaptureError as error:
            return error.code.value
        finished_at = time.perf_counter()
        if keep_full_frames:
            buffer.append((started_at, finished_at, frame.pixels))
        else:
            buffer.append((started_at, finished_at, _crop_minimap(frame.pixels)[0]))
        if interval_seconds > 0.0:
            time.sleep(interval_seconds)
    if len(buffer) >= max_frames:
        return "frame_budget_exhausted"
    return None


def _write_frames(
    output_directory: Path,
    buffer: list[tuple[float, float, npt.NDArray[np.uint8]]],
) -> list[FrameRecord]:
    """Encode the buffered frames losslessly and return their manifest records."""

    records: list[FrameRecord] = []
    parameters = [cv2.IMWRITE_PNG_COMPRESSION, PNG_COMPRESSION_LEVEL]
    for index, (started_at, finished_at, pixels) in enumerate(buffer):
        file_name = f"frame_{index:04d}.png"
        if not cv2.imwrite(str(output_directory / file_name), pixels, parameters):
            raise RuntimeError(f"Failed to write {file_name}.")
        records.append(
            FrameRecord(
                index=index,
                file_name=file_name,
                capture_started_at=started_at,
                capture_finished_at=finished_at,
            )
        )
    return records


def _write_reference_frames(
    output_directory: Path,
    first: npt.NDArray[np.uint8],
    last: npt.NDArray[np.uint8],
) -> None:
    """Store the uncropped frames bracketing a burst.

    The minimap crop alone cannot show what the character was doing: it carries no landmark to
    resolve which end of the marker is the nose, and it cannot distinguish running from being
    wedged against terrain. These two frames keep that absolute context for every recording.
    """

    parameters = [cv2.IMWRITE_PNG_COMPRESSION, PNG_COMPRESSION_LEVEL]
    for file_name, pixels in (
        (FIRST_REFERENCE_FILE_NAME, first),
        (LAST_REFERENCE_FILE_NAME, last),
    ):
        if not cv2.imwrite(str(output_directory / file_name), pixels, parameters):
            raise RuntimeError(f"Failed to write {file_name}.")


def _prepare_output_directory(root: Path, protocol: str, label: str) -> Path:
    """Create a fresh timestamped directory for one recorded sequence."""

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    directory = root / f"{stamp}-{protocol}-{label}"
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def _acquire_window(
    controller: WindowsInputController, process_name: str, countdown_seconds: float
) -> tuple[int, str]:
    """Focus the client window and give the operator time to let the client settle."""

    windows = controller.find_windows(process_name)
    if not windows:
        raise SystemExit(f"No visible {process_name} window found.")
    window = windows[0]
    print(f"Target window: {window.title!r} (handle {window.handle})")
    controller.focus_window(window.handle)
    time.sleep(FOCUS_SETTLE_SECONDS)
    for remaining in range(int(countdown_seconds), 0, -1):
        print(f"Recording in {remaining}...")
        time.sleep(1.0)
    return window.handle, window.title


def _run_burst(args: argparse.Namespace) -> int:
    """Record a frame burst while one movement key is held, then a short coast tail."""

    controller = WindowsInputController()
    source = WindowsFrameSource()
    virtual_key = parse_virtual_key(args.key)
    window_handle, window_title = _acquire_window(controller, args.process, args.countdown)

    probe = source.capture(window_handle)
    _, crop_left, crop_top = _crop_minimap(probe.pixels)
    max_frames = MAX_BURST_FULL_FRAMES if args.full else MAX_BURST_CROP_FRAMES
    interval = FULL_FRAME_INTERVAL_SECONDS if args.full else 0.0

    timing = _HeldKeyTiming()
    key_thread = threading.Thread(
        target=_hold_key_on_thread,
        args=(controller, window_handle, virtual_key, args.hold, timing),
        daemon=True,
    )
    buffer: list[tuple[float, float, npt.NDArray[np.uint8]]] = []
    started_at = time.perf_counter()
    key_thread.start()
    reason = _capture_until(
        source,
        controller,
        window_handle,
        started_at + args.hold + args.tail,
        buffer,
        keep_full_frames=args.full,
        max_frames=max_frames,
        interval_seconds=interval,
    )
    key_thread.join()
    if timing.error is not None:
        raise SystemExit(f"Key hold failed: {timing.error}")
    if not buffer:
        raise SystemExit(
            f"No frames were captured ({reason or 'unknown reason'}); nothing written."
        )
    closing = source.capture(window_handle)

    output_directory = _prepare_output_directory(args.output, "burst", args.label)
    _write_reference_frames(output_directory, probe.pixels, closing.pixels)
    records = _write_frames(output_directory, buffer)
    manifest = RunManifest(
        protocol="burst",
        label=args.label,
        started_at_utc=datetime.now(UTC).isoformat(),
        process_name=args.process,
        window_title=window_title,
        capture_origin=CAPTURE_ORIGIN,
        client_width=probe.client_size.width,
        client_height=probe.client_size.height,
        cropped=not args.full,
        crop_left=0 if args.full else crop_left,
        crop_top=0 if args.full else crop_top,
        crop_width=probe.client_size.width if args.full else MINIMAP_CROP_WIDTH_PIXELS,
        crop_height=probe.client_size.height if args.full else MINIMAP_CROP_HEIGHT_PIXELS,
        held_key=args.key,
        hold_seconds=args.hold,
        key_down_at=timing.down_at,
        key_up_at=timing.up_at,
        aborted_reason=reason,
        frames=records,
    )
    _write_manifest(output_directory, manifest)
    elapsed = records[-1].capture_finished_at - records[0].capture_started_at if records else 0.0
    rate = len(records) / elapsed if elapsed > 0.0 else 0.0
    print(f"Wrote {len(records)} frames to {output_directory} ({rate:.1f} frames/s).")
    if reason is not None:
        print(f"Capture stopped early: {reason}")
    return 0


def _run_still(args: argparse.Namespace) -> int:
    """Record a few full frames of a stationary character for geometry comparisons."""

    controller = WindowsInputController()
    source = WindowsFrameSource()
    window_handle, window_title = _acquire_window(controller, args.process, args.countdown)

    buffer: list[tuple[float, float, npt.NDArray[np.uint8]]] = []
    for _ in range(args.count):
        if controller.is_aborted():
            break
        started_at = time.perf_counter()
        frame = source.capture(window_handle)
        finished_at = time.perf_counter()
        buffer.append((started_at, finished_at, frame.pixels))
        time.sleep(STILL_FRAME_INTERVAL_SECONDS)
    if not buffer:
        raise SystemExit("No frames were captured; nothing written.")

    output_directory = _prepare_output_directory(args.output, "still", args.label)
    records = _write_frames(output_directory, buffer)
    first = buffer[0][2]
    manifest = RunManifest(
        protocol="still",
        label=args.label,
        started_at_utc=datetime.now(UTC).isoformat(),
        process_name=args.process,
        window_title=window_title,
        capture_origin=CAPTURE_ORIGIN,
        client_width=first.shape[1],
        client_height=first.shape[0],
        cropped=False,
        crop_left=0,
        crop_top=0,
        crop_width=first.shape[1],
        crop_height=first.shape[0],
        frames=records,
    )
    _write_manifest(output_directory, manifest)
    print(f"Wrote {len(records)} full frames to {output_directory}.")
    return 0


def _write_manifest(output_directory: Path, manifest: RunManifest) -> None:
    """Persist the run manifest next to the frames it describes."""

    path = output_directory / "manifest.json"
    path.write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    """Describe the two recording protocols and their shared options."""

    parser = argparse.ArgumentParser(description="Record minimap calibration sequences.")
    parser.add_argument("--process", default=DEFAULT_PROCESS_NAME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--countdown", type=float, default=DEFAULT_COUNTDOWN_SECONDS)
    subparsers = parser.add_subparsers(dest="protocol", required=True)

    burst = subparsers.add_parser("burst", help="Hold one key and capture minimap crops.")
    burst.add_argument("--label", required=True)
    burst.add_argument("--key", default="w", help="Movement key to hold, e.g. w, left, right.")
    burst.add_argument("--hold", type=float, default=DEFAULT_BURST_HOLD_SECONDS)
    burst.add_argument("--tail", type=float, default=DEFAULT_BURST_TAIL_SECONDS)
    burst.add_argument(
        "--full",
        action="store_true",
        help="Keep whole frames instead of minimap crops, throttled to stay within the frame "
        "budget. Required for the turn recording, where the 3D viewport is the only absolute "
        "reference for which end of the player marker is its nose.",
    )

    still = subparsers.add_parser("still", help="Capture full frames without sending input.")
    still.add_argument("--label", required=True)
    still.add_argument("--count", type=int, default=DEFAULT_STILL_FRAME_COUNT)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one recording protocol against the live client."""

    if sys.platform != "win32":
        raise SystemExit("This calibration harness requires the Windows client.")
    args = _build_parser().parse_args(argv)
    if args.protocol == "burst":
        return _run_burst(args)
    return _run_still(args)


if __name__ == "__main__":
    raise SystemExit(main())
