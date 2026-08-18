# Minimap odometry feasibility spike (2026-08-18)

Raw measurement evidence collected while assessing how functional the navigation tracking in
`src/flyff_bot/features/navigation/` actually is. Immutable after ingestion.

All measurements were taken on Linux with the repository's `.venv` (`uv run python`), OpenCV
4.x, against the frames shipped in `data/`. No game client was executed.

## Input frames

| Label | File | Size (h, w) |
| --- | --- | --- |
| `a` | `data/full_screen_view_with_monster_stats_1600_900_Res.png` | 931 x 1600 |
| `b` | `data/placeholder.png` | 925 x 1599 |

Both frames include the Windows title bar above the client area and show a different zone
(`a`: water and green foliage, `b`: orange autumn trees), i.e. they are independent samples.

## 1. Minimap geometry is fixed-pixel and reproducible

`cv2.HoughCircles` over the top-right 320 x 300 px region
(`dp=1, minDist=100, param1=120, param2=45, minRadius=60, maxRadius=110`):

| Frame | Circle centre (image coordinates) | Radius |
| --- | --- | --- |
| `a` | (1512.5, 135.5) | 68.4 px |
| `b` | (1509.5, 134.5) | 67.6 px |

Exactly one circle was detected per frame. The two independent captures agree within 3 px, and
the radius agrees with the inner navigable surface radius of 67 px that the US-027 calibration
spike measured by hand. The centre is 88 px left of the client right edge, which also reproduces
the US-027 measurement.

Inference (not measured): like the vitals HUD in BUG-006, the minimap is a fixed-pixel element,
so these offsets are anchored to the client edges rather than expressed as window fractions.
This has only been measured at a 1600 px client width.

## 2. The player marker is locatable and its orientation is measurable

Colour key over a 53 x 53 px box around the ring centre, selecting desaturated bright pixels
(`max(B,G,R) > 170 and max - min < 40`), largest connected component:

| Frame | Component area | Centroid offset from ring centre | Farthest-point angle |
| --- | --- | --- | --- |
| `a` | 70 px | (+0.8, +6.4) px | 98.9 deg |
| `b` | 74 px | (-0.6, +5.7) px | 129.4 deg |

Observations:

- The marker is a compact, high-contrast, desaturated wedge that colour keying isolates cleanly
  in both frames.
- Its centroid sits a consistent ~6 px below the detected ring centre in both frames, so the
  marker must be localised by colour rather than assumed to be at the ring centre.
- The two frames yield clearly different angles while the `N` compass glyph stays at the top of
  the ring in both, which is evidence that the minimap is north-up and the marker rotates.
- The angle above was derived by taking the component point farthest from its centroid as the
  arrow tip. On a paper-plane silhouette this heuristic can select the tail instead of the nose,
  and these two frames cannot resolve which. The orientation *axis* is measurable; the 180 deg
  sign convention is unresolved and needs one validation against a known in-game facing.

## 3. Phase correlation recovers minimap scroll to sub-pixel accuracy

Synthetic experiment on frame `a`. The inner disk (R = 62 px, grayscale) was scrolled by a known
offset with `cv2.warpAffine` (`BORDER_REFLECT`), after which the fixed circular aperture was
re-applied and the central marker pixels were pasted back unshifted, simulating map content that
scrolls beneath a stationary aperture and a stationary player marker. Both frames were multiplied
by a Hanning window before `cv2.phaseCorrelate`.

| True shift (px) | Recovered magnitude error | Response |
| --- | --- | --- |
| (1, 0) | 0.82 px | 0.928 |
| (3, 2) | 0.74 px | 0.729 |
| (6, -4) | 0.74 px | 0.794 |
| (12, 9) | 0.64 px | 0.805 |
| (20, -15) | 0.88 px | 0.665 |

`cv2.phaseCorrelate` returned the negated shift, which is its documented convention.

Negative control: correlating frame `a`'s disk against frame `b`'s disk (different zone, no
common content) returned a response of **-0.052** versus 0.665-0.928 for genuine scroll. The
response value therefore separates a valid measurement from a meaningless one by more than an
order of magnitude and is usable as a confidence gate.

Known limitation of this experiment: `BORDER_REFLECT` fabricates the content that enters at the
aperture edge. In the live client, previously unseen terrain streams in there and the earlier
frame carries no information about it. The systematic 0.6-0.9 px underestimate measured above is
therefore a property of the synthetic setup and must be re-measured against real consecutive
client frames before any scale factor is fitted from it.

## 4. Reproduction

The measurements above come from three throwaway scripts run against the two frames listed in
section "Input frames": a `cv2.HoughCircles` call over the top-right region, the colour-key and
connected-component pass over the ring centre, and the `warpAffine` / `phaseCorrelate` loop.
Each is fully described by the parameters quoted in the sections above.
