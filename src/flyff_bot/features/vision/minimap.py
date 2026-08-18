"""Read-only minimap odometry: ring geometry, player heading, and map scroll.

The Flyff minimap is north-up and player-centred, so the displacement of its content
between two frames is already expressed in world axes and needs no heading rotation. It
observes motion rather than commands, which is why it also covers combat auto-run,
knockback, and manual movement (US-035).

Every geometric and statistical constant below was measured against the recordings
described in `docs/sources/2026-08-18-minimap-odometry-calibration.md`, and the frames the
unit tests replay are shipped under `data/assets/fixtures/minimap/`.

The canonical unit of this module is the **minimap pixel at the calibrated zoom level**.
No conversion to world units exists, because the client does not display the run speed
that such a conversion would require.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np
import numpy.typing as npt

from flyff_bot.features.vision.models import CapturedFrame, PixelFormat

# The minimap widget is a fixed-pixel HUD element anchored to the client's top-right
# corner, exactly like the vitals orb in `vitals.py` (BUG-006). Measured at ring-band
# offsets of 88.0 px from the right edge and 106.5 px from the top edge in client-area
# captures of a 1600x1200 client, reproduced within 0.25 px across both zoom levels, the
# walk burst, and the turn burst.
MINIMAP_CENTRE_RIGHT_OFFSET_PIXELS = 88.0
MINIMAP_CENTRE_TOP_OFFSET_PIXELS = 106.5
# Radius of the map surface that is pure content: the angular profile stays map-like out to
# r = 64 px and the ring bevel takes over from r = 65 px. 62 px keeps a two-pixel margin.
MINIMAP_SURFACE_RADIUS_PIXELS = 62
# The player marker is a stationary overlay that carries no map information. Blanking a
# 12 px disk around the ring centre before correlating cut the integration shortfall from
# 8.1 % to 2.5 % over a 27.6 px traverse.
PLAYER_MARKER_MASK_RADIUS_PIXELS = 12

# The pale ring stroke is opaque, so the annulus between these radii reads 185.0 +- 0.2
# grey with an angular deviation of 11.5-12.0 over completely different scenery. Eight
# displaced scenery samples produced 122-182 grey at deviations of 7.7-30.0, and every one
# of them fails at least one of the two bounds below.
RING_BAND_INNER_RADIUS_PIXELS = 70.5
RING_BAND_OUTER_RADIUS_PIXELS = 74.0
RING_BAND_RADIUS_STEP_PIXELS = 0.25
# Halving the angular sampling from 360 changed both statistics by at most 0.3, so the
# cheaper sampling is used for the repeated candidate evaluations of the centre search.
RING_BAND_ANGULAR_SAMPLES = 180
RING_REFERENCE_INTENSITY = 185.0
RING_MAXIMUM_INTENSITY_DEVIATION = 15.0
RING_MAXIMUM_ANGULAR_DEVIATION = 15.0
# The anchored centre is refined once per client size. Whole-window captures of a 1280 px
# and a 1600 px client put the ring within 2 px of the same right offset, so a small search
# absorbs the residual title-bar and border differences without a resolution rule.
RING_CENTRE_SEARCH_RADIUS_PIXELS = 5

# The marker is a compact desaturated wedge. These thresholds are the colour key from the
# feasibility spike, which isolated it as a single 69-80 px component in every frame of
# both recorded bursts.
MARKER_SEARCH_HALF_SIZE_PIXELS = 26
MARKER_MINIMUM_CHANNEL_VALUE = 170
MARKER_MAXIMUM_CHANNEL_SPREAD = 40
MARKER_MINIMUM_AREA_PIXELS = 30
MARKER_MAXIMUM_AREA_PIXELS = 200

# `cv2.phaseCorrelate` reports (0.5, 0.5) for two identical even-sized inputs. Subtracting
# it removes the 0.6-0.9 px systematic underestimate the feasibility spike attributed to its
# synthetic `BORDER_REFLECT` edges: with the offset removed, known synthetic shifts of 1-20
# px are recovered to within 0.03 px.
PHASE_CORRELATION_CENTRE_OFFSET_PIXELS = 0.5
# Genuine motion produced responses of 0.34-0.99 across displacements of 0.1-28.5 px, while
# a zoom change scored 0.062 and unrelated minimap content -0.006 to 0.097. 0.30 sits above
# every negative control and below every genuine measurement.
MINIMUM_CORRELATION_RESPONSE = 0.30
# Largest displacement with a measured response margin. The recording could not scroll the
# aperture further than 28.5 px, where the response was still 0.344, so this bound is the
# largest measured value rather than an extrapolated cliff.
MAXIMUM_INTER_FRAME_DISPLACEMENT_PIXELS = 24.0

# Mean Sobel gradient magnitude over the map surface. It is translation invariant but scales
# with the zoom level: 88.3-95.3 across both recorded bursts and the default-zoom still,
# 110.0 at maximum zoom-out. A 12 % tolerance sits above the 4.2 % spread measured inside one
# zoom level and well below the 24.6 % step between the two.
ZOOM_SIGNATURE_TOLERANCE_FRACTION = 0.12
_ZOOM_SIGNATURE_MARGIN_PIXELS = 3
_ZOOM_SIGNATURE_MARKER_MARGIN_PIXELS = 2

FULL_TURN_DEGREES = 360.0
_MINIMUM_MARKER_AXIS_LENGTH = 1e-6


@dataclass(frozen=True, slots=True)
class MinimapGeometry:
    """Located ring centre and usable map-surface radius in client-area pixels."""

    centre_x: float
    centre_y: float
    surface_radius: int = MINIMAP_SURFACE_RADIUS_PIXELS

    def __post_init__(self) -> None:
        if self.surface_radius <= 0:
            raise ValueError("Minimap surface radius must be positive.")


@dataclass(frozen=True, slots=True)
class MinimapSample:
    """One prepared minimap observation: correlation input, heading, and zoom signature."""

    geometry: MinimapGeometry
    windowed_surface: npt.NDArray[np.float32]
    zoom_signature: float
    heading_degrees: float | None
    # The unprepared greyscale disk. It is the landmark a navigation profile stores to
    # recover the offset between two sessions' coordinate frames (US-036), which is why the
    # raw picture is kept alongside the correlation input derived from it.
    surface_greyscale: npt.NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class MinimapDisplacement:
    """Measured scroll of the minimap content between two samples, in minimap pixels."""

    x: float
    y: float
    response: float

    @property
    def magnitude(self) -> float:
        """Return the scroll distance in minimap pixels."""

        return math.hypot(self.x, self.y)


@dataclass(frozen=True, slots=True)
class MinimapReading:
    """One tick of minimap odometry: player motion, facing, zoom signature, and landmark."""

    displacement: MinimapDisplacement | None
    heading_degrees: float | None
    zoom_signature: float
    # The greyscale disk this reading was measured from, or ``None`` when the caller
    # synthesised the reading instead of decoding a frame.
    surface: npt.NDArray[np.uint8] | None = None

    @property
    def player_dx(self) -> float:
        """Return how far the player moved east, in minimap pixels."""

        return -self.displacement.x if self.displacement is not None else 0.0

    @property
    def player_dy(self) -> float:
        """Return how far the player moved north, in minimap pixels."""

        # Screen y grows downwards while a compass ordinate grows northwards, and the map
        # content scrolls opposite to the player, so the two sign flips cancel.
        return self.displacement.y if self.displacement is not None else 0.0


def _radial_samples(
    grey: npt.NDArray[np.float32], centre_x: float, centre_y: float, radii: npt.NDArray[np.float64]
) -> npt.NDArray[np.float32]:
    """Sample the frame on concentric circles around a candidate ring centre."""

    angles = np.linspace(0.0, 2.0 * math.pi, RING_BAND_ANGULAR_SAMPLES, endpoint=False)
    xs = (centre_x + np.outer(radii, np.cos(angles))).astype(np.float32)
    ys = (centre_y + np.outer(radii, np.sin(angles))).astype(np.float32)
    sampled = cv2.remap(grey, xs, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return sampled.astype(np.float32)


def _ring_band_statistics(
    grey: npt.NDArray[np.float32], centre_x: float, centre_y: float
) -> tuple[float, float]:
    """Return the mean intensity and mean angular deviation of the ring stroke."""

    radii = np.arange(
        RING_BAND_INNER_RADIUS_PIXELS, RING_BAND_OUTER_RADIUS_PIXELS, RING_BAND_RADIUS_STEP_PIXELS
    )
    samples = _radial_samples(grey, centre_x, centre_y, radii)
    return float(samples.mean()), float(samples.std(axis=1).mean())


def _to_greyscale(
    pixels: npt.NDArray[np.uint8], pixel_format: PixelFormat
) -> npt.NDArray[np.float32]:
    """Convert one already-cropped colour region to float greyscale.

    Only the minimap region is ever converted: greyscaling a whole 1600x1200 client frame
    costs more than the entire measurement.
    """

    code = cv2.COLOR_BGR2GRAY if pixel_format is PixelFormat.BGR else cv2.COLOR_RGB2GRAY
    return cv2.cvtColor(pixels, code).astype(np.float32)


def locate_minimap(frame: CapturedFrame) -> MinimapGeometry | None:
    """Return the minimap ring geometry, or ``None`` when no ring is visible.

    The nominal centre is anchored to the client's right and top edges and then refined
    within a few pixels, so a collapsed minimap, an unexpected window decoration, or a
    client too small to contain the widget all report "not found" instead of returning an
    out-of-bounds region.
    """

    nominal_x = frame.client_size.width - MINIMAP_CENTRE_RIGHT_OFFSET_PIXELS
    nominal_y = MINIMAP_CENTRE_TOP_OFFSET_PIXELS
    reach = RING_BAND_OUTER_RADIUS_PIXELS + RING_CENTRE_SEARCH_RADIUS_PIXELS
    if (
        nominal_x - reach < 0.0
        or nominal_x + reach >= frame.client_size.width
        or nominal_y - reach < 0.0
        or nominal_y + reach >= frame.client_size.height
    ):
        return None

    left = math.floor(nominal_x - reach)
    top = math.floor(nominal_y - reach)
    span = math.ceil(2.0 * reach) + 1
    grey = _to_greyscale(frame.pixels[top : top + span, left : left + span], frame.pixel_format)
    local_x = nominal_x - left
    local_y = nominal_y - top
    best: tuple[float, float, float, float] | None = None
    offsets = range(-RING_CENTRE_SEARCH_RADIUS_PIXELS, RING_CENTRE_SEARCH_RADIUS_PIXELS + 1)
    for offset_y in offsets:
        for offset_x in offsets:
            intensity, deviation = _ring_band_statistics(
                grey, local_x + offset_x, local_y + offset_y
            )
            if best is None or deviation < best[0]:
                best = (deviation, intensity, nominal_x + offset_x, nominal_y + offset_y)
    if best is None:
        return None
    deviation, intensity, centre_x, centre_y = best
    if deviation > RING_MAXIMUM_ANGULAR_DEVIATION:
        return None
    if abs(intensity - RING_REFERENCE_INTENSITY) > RING_MAXIMUM_INTENSITY_DEVIATION:
        return None
    return MinimapGeometry(centre_x=centre_x, centre_y=centre_y)


class _SurfaceKernels:
    """Cached circular masks and the Hanning window for one surface radius."""

    def __init__(self, radius: int) -> None:
        size = 2 * radius
        grid_y, grid_x = np.mgrid[0:size, 0:size]
        distance = np.hypot(grid_x - radius + 0.5, grid_y - radius + 0.5)
        self.surface = distance <= radius
        self.marker = distance <= PLAYER_MARKER_MASK_RADIUS_PIXELS
        self.signature = (distance <= radius - _ZOOM_SIGNATURE_MARGIN_PIXELS) & (
            distance > PLAYER_MARKER_MASK_RADIUS_PIXELS + _ZOOM_SIGNATURE_MARKER_MARGIN_PIXELS
        )
        window = cv2.createHanningWindow((size, size), cv2.CV_32F)
        self.window: npt.NDArray[np.float32] = window.astype(np.float32)


_KERNELS: dict[int, _SurfaceKernels] = {}


def _kernels(radius: int) -> _SurfaceKernels:
    cached = _KERNELS.get(radius)
    if cached is None:
        cached = _SurfaceKernels(radius)
        _KERNELS[radius] = cached
    return cached


def _marker_axis_bearing(surface_pixels: npt.NDArray[np.uint8], centre: int) -> float | None:
    """Return the compass bearing of the player marker, isolated by colour keying.

    The marker is found by colour, never by assuming it sits at the ring centre: its
    centroid was measured 2.6-2.9 px off centre in every recorded frame.
    """

    half = MARKER_SEARCH_HALF_SIZE_PIXELS
    left = centre - half
    top = centre - half
    box = surface_pixels[top : top + 2 * half, left : left + 2 * half].astype(np.int16)
    if box.shape[0] != 2 * half or box.shape[1] != 2 * half:
        return None
    brightest = box.max(axis=2)
    darkest = box.min(axis=2)
    keyed = (
        (brightest > MARKER_MINIMUM_CHANNEL_VALUE)
        & (brightest - darkest < MARKER_MAXIMUM_CHANNEL_SPREAD)
    ).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(keyed, connectivity=8)
    if count <= 1:
        return None
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    area = int(stats[largest, cv2.CC_STAT_AREA])
    if not MARKER_MINIMUM_AREA_PIXELS <= area <= MARKER_MAXIMUM_AREA_PIXELS:
        return None
    rows, columns = np.nonzero(labels == largest)
    points = np.stack([columns, rows], axis=1).astype(np.float64)
    centred = points - points.mean(axis=0)
    _, singular, principal = np.linalg.svd(centred, full_matrices=False)
    if singular[0] < _MINIMUM_MARKER_AXIS_LENGTH:
        return None
    axis = principal[0]
    projection = centred @ axis
    # The wedge is broad at the tail and tapers to a thin nose, so its projection is skewed
    # towards the nose. The third moment picks that end without a flip, where "farthest
    # point from the centroid" flipped on 8 of 53 frames of the recorded turn.
    if float((projection**3).mean()) < 0.0:
        axis = -axis
    return math.degrees(math.atan2(axis[0], -axis[1])) % FULL_TURN_DEGREES


def _zoom_signature(surface: npt.NDArray[np.float32], kernels: _SurfaceKernels) -> float:
    """Return a translation-invariant, scale-sensitive signature of the map surface."""

    gradient_x = cv2.Sobel(surface, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(surface, cv2.CV_32F, 0, 1, ksize=3)
    return float(np.hypot(gradient_x, gradient_y)[kernels.signature].mean())


def _prepare_correlation_surface(
    surface: npt.NDArray[np.float32], kernels: _SurfaceKernels
) -> npt.NDArray[np.float32]:
    """Blank the marker, flatten the bevel, and window one greyscale disk in place.

    The caller hands over ownership of `surface`: it is mutated rather than copied, because
    this runs once per captured frame.
    """

    outside_marker = kernels.surface & ~kernels.marker
    surface[kernels.marker] = float(surface[outside_marker].mean())
    surface[~kernels.surface] = float(surface[kernels.surface].mean())
    windowed = (surface - float(surface[kernels.surface].mean())) * kernels.window
    return windowed.astype(np.float32)


def windowed_surface(greyscale: npt.NDArray[np.uint8]) -> npt.NDArray[np.float32]:
    """Prepare one stored greyscale minimap disk for correlation.

    A disk restored from a navigation profile has to travel the exact same preparation the
    live sample went through, or the two are not comparable (US-036).
    """

    height, width = greyscale.shape[:2]
    if greyscale.ndim != 2 or height != width or height % 2 != 0:
        raise ValueError("A minimap disk must be a square greyscale image of even size.")
    return _prepare_correlation_surface(greyscale.astype(np.float32), _kernels(height // 2))


def zoom_signature_matches(reference: float, candidate: float) -> bool:
    """Return whether two zoom signatures describe the same minimap scale."""

    if reference <= 0.0:
        return False
    return abs(candidate - reference) / reference <= ZOOM_SIGNATURE_TOLERANCE_FRACTION


def read_minimap(frame: CapturedFrame, geometry: MinimapGeometry) -> MinimapSample:
    """Prepare one minimap observation from a captured client frame."""

    radius = geometry.surface_radius
    kernels = _kernels(radius)
    left = round(geometry.centre_x) - radius
    top = round(geometry.centre_y) - radius
    colour = frame.pixels[top : top + 2 * radius, left : left + 2 * radius]
    surface = _to_greyscale(colour, frame.pixel_format)
    signature = _zoom_signature(surface, kernels)
    # Taken before the preparation masks the marker, so the stored landmark is the picture
    # the client actually drew.
    greyscale = surface.astype(np.uint8)
    return MinimapSample(
        geometry=geometry,
        windowed_surface=_prepare_correlation_surface(surface, kernels),
        zoom_signature=signature,
        heading_degrees=_marker_axis_bearing(colour, radius),
        surface_greyscale=greyscale,
    )


def correlate_surfaces(
    reference: npt.NDArray[np.float32], current: npt.NDArray[np.float32]
) -> MinimapDisplacement | None:
    """Return the scroll between two prepared disks, or ``None`` below the confidence gate.

    Only the response gate is applied here. How far the content may legitimately have
    scrolled depends on what the two disks are: consecutive frames of one session and the
    two ends of a re-anchoring both use this measurement under different bounds.
    """

    if reference.shape != current.shape:
        return None
    (raw_x, raw_y), response = cv2.phaseCorrelate(reference, current)
    displacement = MinimapDisplacement(
        x=raw_x - PHASE_CORRELATION_CENTRE_OFFSET_PIXELS,
        y=raw_y - PHASE_CORRELATION_CENTRE_OFFSET_PIXELS,
        response=float(response),
    )
    if displacement.response < MINIMUM_CORRELATION_RESPONSE:
        return None
    return displacement


def measure_translation(
    previous: MinimapSample, current: MinimapSample
) -> MinimapDisplacement | None:
    """Return how far the minimap content scrolled, or ``None`` below the confidence gate."""

    displacement = correlate_surfaces(previous.windowed_surface, current.windowed_surface)
    if displacement is None:
        return None
    if displacement.magnitude > MAXIMUM_INTER_FRAME_DISPLACEMENT_PIXELS:
        return None
    return displacement


class MinimapOdometryFeed(Protocol):
    """Injectable provider of per-tick minimap odometry."""

    def observe(self, frame: CapturedFrame | None) -> MinimapReading | None:
        """Return this tick's odometry, or ``None`` when the minimap is unreadable."""

    def reset(self) -> None:
        """Forget the previous frame so the next read starts a new measurement chain."""


class MinimapOdometer:
    """Turn a stream of client frames into per-tick minimap odometry readings.

    The geometry is located once per client size and reused, because the ring is a static
    HUD element. Reading a frame performs no input of any kind.
    """

    def __init__(self) -> None:
        self._geometry: MinimapGeometry | None = None
        self._located_for: tuple[int, int] | None = None
        self._previous: MinimapSample | None = None

    @property
    def geometry(self) -> MinimapGeometry | None:
        """Return the located ring geometry of the most recent successful read."""

        return self._geometry

    def reset(self) -> None:
        """Forget the previous frame so the next read starts a new measurement chain."""

        self._previous = None

    def observe(self, frame: CapturedFrame | None) -> MinimapReading | None:
        """Return this tick's odometry, or ``None`` when the minimap is unreadable."""

        if frame is None:
            self._previous = None
            return None
        size = (frame.client_size.width, frame.client_size.height)
        if self._geometry is None or self._located_for != size:
            self._geometry = locate_minimap(frame)
            self._located_for = size
            self._previous = None
        if self._geometry is None:
            return None
        sample = read_minimap(frame, self._geometry)
        previous = self._previous
        self._previous = sample
        displacement = None if previous is None else measure_translation(previous, sample)
        return MinimapReading(
            displacement=displacement,
            heading_degrees=sample.heading_degrees,
            zoom_signature=sample.zoom_signature,
            surface=sample.surface_greyscale,
        )
