# Minimap odometry calibration (2026-08-18)

Raw measurement evidence for US-035. Every geometric, statistical, and fitted constant in
`src/flyff_bot/features/vision/minimap.py` and `src/flyff_bot/features/navigation/tracking.py`
cites this document. Immutable after ingestion.

This supersedes the synthetic figures of
[the feasibility spike](2026-08-18-minimap-odometry-feasibility-spike.md) wherever the two
disagree; section 4 explains the one place where they do.

## Recordings

Captured on the Windows client (`neuz.exe`, window title `Entropia - scizox`) with
`scripts/capture_minimap_samples.py`. All frames are **client-area** captures through
`GetClientRect`, so row 0 is the first pixel below the title bar. Client area 1600 x 1200.

| Directory under `data/calibration/` | Protocol | Frames | Rate | Held key |
| --- | --- | --- | --- | --- |
| `20260818-013756-burst-walk-1` | burst, 360x320 minimap crops | 346 | 90.9 /s over 3.805 s | `W` for 3.0 s |
| `20260818-013817-burst-turn-1` | burst, full frames | 61 | 9.1 /s over 6.706 s | `RIGHT` for 6.0 s |
| `20260818-013847-still-zoom-default` | still, full frames | 3 | — | none |
| `20260818-013858-still-zoom-default` | still, full frames | 3 | — | none |

The two still runs were taken from the same standing position: the first at the client's
default minimap zoom, the second with the minimap zoomed fully out. The operator reused the
`zoom-default` label for both, so the directory timestamp is what distinguishes them.

The recordings themselves are gitignored (246 MB). The frames the unit tests replay are the
180 x 180 px window around the widget, shipped under `data/assets/fixtures/minimap/` with a
manifest carrying the client size, crop origin, per-frame `perf_counter` offsets, and key
window of each sequence.

## 1. Ring geometry is fixed-pixel and reproducible in client-area coordinates

The ring centre was located by minimising the mean angular standard deviation of the annulus
r in [70.5, 74.0) px, sampled at 0.25 px radial steps, over a 0.25 px search grid.

| Frame | Centre | Offset from right edge | Offset from top edge |
| --- | --- | --- | --- |
| still default, `frame_0000` | (1512.00, 106.50) | 88.00 | 106.50 |
| still maximum zoom-out, `frame_0000` | (1511.75, 106.75) | 88.25 | 106.75 |
| turn burst, `frame_0000` | (1512.00, 106.50) | 88.00 | 106.50 |
| turn burst, `frame_0030` | (1512.00, 106.50) | 88.00 | 106.50 |
| walk burst, `reference_first` | (1512.00, 106.75) | 88.00 | 106.75 |

**Re-basing against the feasibility spike.** The spike measured centre y = 135.5 on
whole-window captures. 135.5 - 106.5 = 29 rows of title bar, which is the offset the two
coordinate systems differ by. The horizontal offset of 88 px agrees directly.

### Radial structure

Radial profile around the refined centre of the default-zoom still (mean grey and angular
standard deviation, averaged over 1440 angles):

| Radius | Mean | Angular deviation | Interpretation |
| --- | --- | --- | --- |
| 55-64 | 99-110 | 18-24 | map content |
| 65-70 | 115-158 | 29-44 | bevel between content and ring |
| 71.5-73 | 176-188 | 9-12 | opaque ring stroke |
| 76-82 | 190-204 | 14-22 | outer ring highlight and buttons |

Committed: usable surface radius 64 px; the correlation disk uses 62 px to keep a margin.

### Ring-presence statistic

Mean intensity and mean angular deviation of the r in [70.5, 74.0) band:

| Sample | Mean | Deviation |
| --- | --- | --- |
| still default | 185.02 | 11.86 |
| still maximum zoom-out | 184.98 | 11.96 |
| walk burst, `reference_first` | 185.22 | 11.52 |
| turn burst, `frame_0030` | 184.95 | 11.93 |
| scenery at (400, 400) | 135.57 | 7.79 |
| scenery at (700, 300) | 178.57 | 24.58 |
| scenery at (1100, 600) | 137.04 | 11.55 |
| scenery at (300, 800) | 122.34 | 14.18 |
| scenery at (1400, 500) | 153.38 | 30.02 |
| scenery at (800, 900) | 148.58 | 7.73 |
| scenery at (1512, 400) | 181.48 | 25.16 |
| scenery at (900, 150) | 178.21 | 16.50 |

The ring stroke is opaque: its mean varies by 0.27 grey levels over completely different
scenery. Committed bounds are mean within 185 +- 15 and deviation at most 15, which every
scenery sample above fails on at least one bound.

Halving the angular sampling from 360 to 180 changed both statistics by at most 0.3, so the
cheaper sampling is used for the repeated candidate evaluations of the centre search.

### A second window resolution

The three whole-window frames shipped in `data/assets/fixtures/`, located the same way:

| File | Size | Centre | Right offset | Top offset | Band statistic |
| --- | --- | --- | --- | --- | --- |
| `full_screen_view_with_monster_stats_1600_900_Res.png` | 1600 x 931 | (1514.0, 137.5) | 86.0 | 137.5 | (184.8, 12.08) |
| `placeholder.png` | 1599 x 925 | (1511.0, 136.5) | 88.0 | 136.5 | (185.0, 11.84) |
| `placeholder2.png` | 1280 x 799 | (1193.0, 140.0) | 87.0 | 140.0 | (183.8, 11.27) |

At a 1280 px window width the ring sits 87 px from the right edge with an unchanged radius
and an unchanged band statistic, so the **horizontal** fixed-pixel anchoring inherited from
BUG-006 is confirmed at a second resolution. The **vertical** offsets cannot be compared
directly, because these are whole-window captures whose individual title-bar heights are
unknown; they are consistent with 30.0-33.5 px of decoration above a 106.5 px client-area
offset, but that is not proof. The locator therefore refines the anchored centre within
+-5 px once per client size, which absorbs both the 2 px horizontal spread and the unknown
decoration, and reports "not found" when no ring survives the band bounds.

## 2. Heading is measurable, north-up holds, and the nose is resolved

Colour key `max(B, G, R) > 170 and max - min < 40` in a 52 x 52 px box around the ring
centre, largest 8-connected component, principal component analysis of its pixels.

- The component area was 69-80 px in every frame of both bursts.
- Its centroid sits (-2.56, +2.87) px from the ring centre in the walk burst and
  (-2.82, +2.92) px in the stills, so the marker must be located by colour rather than
  assumed to be at the ring centre.

### North-up

Over the full turn burst the marker rotated 1430.9 deg while the 16 x 14 px patch holding
the `N` glyph above the ring changed by a mean absolute difference of 0.03-0.32 grey levels.
The compass does not rotate: the minimap is north-up.

### Which end is the nose

| Heuristic | Frame-to-frame turn rates over the held span (n = 53) | Sign flips |
| --- | --- | --- |
| farthest point from the centroid | mean -4.2 deg/s, median 225.3, sd 580.1 | 8 |
| largest extreme projection | mean -4.2 deg/s, median 225.3, sd 580.1 | 8 |
| third moment (skew) of the projection | mean 238.8 deg/s, median 244.1, sd 49.4 | 0 |

The wedge is broad at the tail and tapers to a thin nose, so the skew of the projection along
the principal axis points at the nose and never flipped. The farthest-point heuristic the
feasibility spike used flipped on 8 of 53 frames.

### The 180 deg sign convention, validated against real motion

In the walk burst the character held `W` for 3.0 s. The measured travel bearing over that
span is **136.3 deg**; the marker heading read from the same frames is **139.6 deg**. The
skew-positive end of the axis is therefore the nose, validated against motion the client
actually performed rather than against a hand-labelled screenshot.

## 3. Phase-correlation translation

Preprocessing: crop the 62 px surface disk, blank a 12 px disk over the stationary player
marker, subtract the disk mean, multiply by a Hanning window.

### The feasibility spike's 0.6-0.9 px underestimate was an unsubtracted centre offset

`cv2.phaseCorrelate` returns **(0.5, 0.5)**, not (0, 0), for two identical even-sized inputs;
`|(0.5, 0.5)| = 0.707`, which is the middle of the 0.64-0.88 px band the spike attributed to
its synthetic `BORDER_REFLECT` edges. With the offset subtracted, known synthetic shifts are
recovered as follows:

| True shift (px) | Recovered | Response |
| --- | --- | --- |
| (1, 0) | (1.00, 0.00) | 0.999 |
| (3, 2) | (3.00, 2.01) | 0.985 |
| (6, -4) | (5.99, -3.98) | 0.947 |
| (12, 9) | (12.00, 9.02) | 0.789 |
| (20, -15) | (20.01, -14.97) | 0.719 |

### Real-frame integration bias

Chained short steps against the direct frame-0-to-key-release measurement (27.63 px):

| Preprocessing | chain lag 1 | 8 | 16 | 32 |
| --- | --- | --- | --- | --- |
| raw disk | -6.8 % | -8.2 % | -8.1 % | -9.0 % |
| marker masked (r = 12), zero-mean | -2.8 % | -2.3 % | -2.5 % | -6.6 % |

The stationary player marker is the larger contributor; masking it also raised the response
of the long-baseline measurement from 0.351 to 0.397. The committed preprocessing therefore
under-reads a long traverse by roughly 3 % when integrated from short steps.

### Response against displacement

Walk burst, all frame pairs at each lag inside the held span, production preprocessing:

| Lag | Interval (s) | Mean displacement (px) | Mean response | Minimum response |
| --- | --- | --- | --- | --- |
| 1 | 0.011 | 0.14 | 0.986 | 0.851 |
| 8 | 0.088 | 0.93 | 0.963 | 0.854 |
| 16 | 0.176 | 1.66 | 0.939 | 0.836 |
| 32 | 0.352 | 3.34 | 0.860 | 0.704 |
| 48 | 0.528 | 5.05 | 0.807 | 0.671 |
| 64 | 0.704 | 6.75 | 0.766 | 0.638 |
| 100 | 1.100 | 10.54 | 0.682 | 0.592 |
| 140 | 1.540 | 14.76 | 0.581 | 0.492 |
| 200 | 2.200 | 19.21 | 0.483 | 0.383 |
| 260 | 2.857 | 24.31 | 0.397 | 0.347 |
| 320 | 3.517 | 27.70 | 0.385 | 0.344 |
| 340 | 3.738 | 28.43 | 0.395 | 0.392 |

### Negative controls, on real frames

| Pair | Response |
| --- | --- |
| walk `frame_0000` to `frame_0016` (genuine motion) | 0.950 |
| default zoom to maximum zoom-out, same standing position | 0.062 |
| walk `frame_0000` to an unrelated zone | 0.097 |
| default-zoom still to an unrelated zone | -0.006 |

Committed confidence threshold: **0.30**. It sits above every negative control by a factor
of three and below every genuine measurement in the table above.

### Maximum inter-frame displacement

The recording could not scroll the aperture further than 28.5 px, where the response was
still 0.344, so **the cliff was never reached**. The committed bound is 24 px, the largest
displacement with a measured response margin, rather than an extrapolated cliff. Combined
with the fitted forward speed it yields a minimum sampling rate of one measurement every
24 / 9.4 = 2.55 s; a slower tick reports `PREDICTED` instead of trusting the correlation.

## 4. Fitted movement constants

### Forward speed

Correlating each of the first 40 frames against the frame at key release gives
**9.414 +- 0.122 minimap px/s** (mean response 0.387). The single frame-0-to-key-release
measurement is 27.63 px over 2.988 s = 9.247 px/s at bearing 136.3 deg. Committed:
**9.4 minimap px/s at the default zoom level**.

### Turn rate

Least-squares fit of the unwrapped marker axis over the held span: **239.96 deg/s** with a
residual standard deviation of 4.32 deg (n = 54). The total rotation was 1430.9 deg in
5.995 s = 238.7 deg/s. Committed: **240 deg/s**. The previous guess was 90 deg/s, so the
default pathing turn pulse was shortened from 0.15 s to 0.08 s to keep one pulse
(19.2 deg) inside the 25 deg heading tolerance.

### Acceleration and deceleration

Both are folded into the constants above; the recorded coast tails bound their contribution.

| Quantity | Coast after key release | Share of the recorded traverse |
| --- | --- | --- |
| translation | 0.85-0.97 px, all inside the first 44 ms sample | 3.4 % of 27.6 px |
| rotation | 2.5 deg, settled within 0.14 s | 0.2 % of 1430.9 deg |

Motion also starts within one sample of key press, so no separate acceleration term is
warranted at this measurement resolution.

### Backward speed

**Not measurable from these recordings**: no `S` burst was recorded. No controller in the
repository dispatches `S`, so rather than leaving a guessed literal in place the backward
speed was removed from `MovementModel` and `MovementTracker` stopped predicting it. Backward
motion is still observed, because the minimap measures motion rather than commands. If a
controller ever needs to command it, record it with:

```powershell
uv run python scripts/capture_minimap_samples.py burst --key s --label back-1
```

## 5. Stationary noise floor

Consecutive-frame displacement while the character was not translating:

| Sequence | Pairs | Mean displacement | Max displacement | Max instantaneous speed | Total drift |
| --- | --- | --- | --- | --- | --- |
| still, default zoom | 2 | 0.064 px | 0.101 px | 0.39 px/s | 0.10 px over 0.52 s |
| still, maximum zoom-out | 2 | 0.042 px | 0.084 px | 0.32 px/s | 0.08 px over 0.52 s |
| turn burst (rotating in place) | 60 | 0.044 px | 0.201 px | 1.78 px/s | 0.12 px over 6.69 s |

Rotating in place for 6.7 s produced 0.12 px of apparent translation, confirming that the
minimap is player-centred and that a heading change cannot corrupt the translation
measurement. Committed stall threshold: **3.0 minimap px/s**, which is 1.7x the worst
instantaneous noise and 0.32x the running speed.

## 6. Zoom is part of the measurement contract

### The scale ratio between the two recorded levels

Upscaling the maximum-zoom-out disk by a factor s and correlating it against the default-zoom
disk of the same standing position:

| Scale | Response |
| --- | --- |
| 1.98 | 0.428 |
| **2.00** | **0.453** |
| 2.02 | 0.376 |
| 2.06 | 0.422 |
| 1.90 | 0.359 |

One minimap pixel at maximum zoom-out covers exactly **two** minimap pixels at the default
zoom. Only these two levels were recorded; intermediate steps of the `+` / `-` buttons were
not measured.

### The ring geometry does not change with zoom

The located centre and the band statistic are identical at both levels (section 1). The
buttons rescale the content, not the widget.

### Detecting a zoom change

Mean Sobel gradient magnitude over the annulus between the marker mask and the surface
radius. It is translation invariant and scales with the zoom level:

| Sample | Mean | Min | Max | Spread |
| --- | --- | --- | --- | --- |
| walk burst (346 frames) | 91.53 | 88.76 | 95.33 | +-4.2 % |
| turn burst (61 frames) | 88.63 | 87.89 | 89.23 | +-0.8 % |
| still, default zoom (3 frames) | 88.36 | 88.26 | 88.55 | +-0.2 % |
| still, maximum zoom-out (3 frames) | 110.01 | 109.93 | 110.05 | +-0.1 % |

The step between the two levels is +24.6 %, against a within-level spread of at most 4.2 %
while the map scrolls. Committed: a 12 % tolerance, confirmed over 5 consecutive readings.

**Correction to the US-035 premise.** The story assumed a zoom change is "the one corruption
mode that leaves the correlation response untouched". It does not: a 2x step collapses the
response to 0.062, well below the 0.30 gate, so the transition itself is caught by the
confidence gate. The signature check is still required, because the gate only rejects the two
frames spanning the change; every measurement afterwards correlates cleanly and would be
silently expressed in a different unit.

## 7. Per-tick cost

Measured on a 1600 x 1200 frame with a 62 px surface disk, averaged over 200 iterations:

| Operation | Cost |
| --- | --- |
| `read_minimap` + `measure_translation` + zoom signature, geometry cached | 1.06 ms |
| `locate_minimap` (121-candidate centre refinement) | 15.1 ms |

The locator runs once per client size. It repeats per tick only while the minimap cannot be
found at all, which is already a degraded session in which no map writes happen.

## 8. Reproduction

All figures above come from throwaway scripts run with the repository's `.venv`
(`uv run python`) against the directories listed under "Recordings", using OpenCV 5.0 and the
parameters quoted in each section. The committed behaviour is pinned by
`tests/unit/test_minimap_odometry.py`, which replays the shipped fixture subset through the
production sensor.
