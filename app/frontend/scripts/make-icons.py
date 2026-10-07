#!/usr/bin/env python3
"""Draw the app icon, at every size and format a browser asks for.

    python3 frontend/scripts/make-icons.py

This is the source of the mark. It writes `public/favicon.svg` *and* the raster
files from the same numbers, so the vector and the bitmaps cannot drift apart —
edit the constants here and re-run, never the SVG by hand.

The mark is a flame, for an app whose whole interaction is a swipe. It is drawn
twice: the full mark has an inner core cut out of it, and below 48px that core
would be two pixels of noise, so the small sizes get the silhouette alone — the
same trick as an icon set that ships separate artwork per size, for the same
reason.

Shapes are signed distance fields rather than paths, which buys two things: the
`grow` dilation that thickens the whole mark at small sizes without redrawing
it, and exact coverage per pixel, which is all the anti-aliasing a 16px icon is.
No image library — a PNG is a zlib stream of filtered scanlines and an ICO is a
short header in front of PNGs, and the standard library does both.

Outputs, and who asks for each:
    favicon.svg              the tab, in browsers that take a vector
    favicon.ico  16/32/48    the tab everywhere else, and everything that
                             requests /favicon.ico without reading the HTML
    icon-192.png             the manifest's small icon
    icon-512.png             the manifest's large icon, install dialogs
    icon-maskable-512.png    Android, which crops icons to its own shape
    apple-touch-icon.png     iOS home screen (it ignores the manifest)

`Layout.tsx` shows favicon.svg as the header badge, so the mark on the home
screen and the mark in the app are the same file.
"""

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "public"

# --color-flame-from → --color-flame-to from index.css, down the
# top-left/bottom-right diagonal.
TOP = (0xFF, 0x78, 0x54)
BOTTOM = (0xFD, 0x26, 0x7D)
CORNER = 22.0          # the tile's radius, in the same 0–100 box as the mark

# The flame, as three tapered cones sharing a base: the spire, and a shorter
# lick either side of it, so the silhouette is a flame rather than a blade. Each
# is (tip x, tip y, tip radius, base x, base y, base radius).
BODY = (57.0, 14.0, 2.0, 47.0, 73.0, 20.0)
LICK = (33.0, 44.0, 1.6, 47.0, 72.0, 14.0)
LICK_R = (72.0, 47.0, 1.6, 51.0, 72.0, 13.0)
# The cooler core, cut out of the middle so the mark reads as fire and not as a
# blob. Same shape, smaller, and sitting low.
CORE = (53.0, 47.0, 1.4, 48.0, 76.0, 10.5)


# --- signed distance fields, all in a 0–100 box ----------------------------

def _segment(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    length = vx * vx + vy * vy
    t = 0.0 if length == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / length))
    return math.hypot(wx - t * vx, wy - t * vy)


def _capsule(px, py, ax, ay, bx, by, r):
    return _segment(px, py, ax, ay, bx, by) - r


def _box(px, py, cx, cy, hx, hy, r=0.0):
    dx = abs(px - cx) - (hx - r)
    dy = abs(py - cy) - (hy - r)
    return math.hypot(max(dx, 0.0), max(dy, 0.0)) + min(max(dx, dy), 0.0) - r


def _cone(px, py, ax, ay, ra, bx, by, rb):
    """A capsule whose radius runs from `ra` at one end to `rb` at the other.

    This is the whole flame: a tapered stroke from a wide base to a point. Doing
    it as a swept radius rather than as a bezier outline keeps the mark a
    distance field, which is what the `grow` dilation and the maskable fit
    below both need.
    """
    vx, vy = bx - ax, by - ay
    length = vx * vx + vy * vy
    if length == 0:
        return math.hypot(px - ax, py - ay) - ra
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / length))
    # A straight lerp of the radius, which over-reports distance slightly near
    # the wide end. At icon sizes the error is under a pixel and it only ever
    # makes the outline tighter, never ragged.
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy)) - (ra + (rb - ra) * t)


def _cut(shape, hole):
    """`shape` with `hole` taken out of it."""
    return max(shape, -hole)


def mark(x: float, y: float, *, detail: bool) -> float:
    """Distance to the mark: negative inside it, positive outside."""
    flame = min(_cone(x, y, *BODY), _cone(x, y, *LICK), _cone(x, y, *LICK_R))
    if not detail:
        # Below 48px the core is two pixels of noise. The silhouette alone is
        # still unmistakably a flame, and it survives the dilation.
        return flame
    return _cut(flame, _cone(x, y, *CORE))


def _tile(x, y, corner):
    """The background. `corner` of None is full bleed, for the masked icons."""
    if corner is None:
        return True
    return _box(x, y, 50, 50, 50, 50, corner) <= 0


# Android crops a maskable icon to whatever shape the launcher likes — a circle
# on most of them — and only guarantees the middle 80%. Drawn plain, this mark
# reaches 88% of the radius, so a round mask takes the tip off the check and a
# corner off the case. The maskable variant is therefore re-centred on the mark
# and shrunk to fit inside that circle, with a little margin.
SAFE_RADIUS = 38.0     # out of 50, so 76% — inside the 80% guarantee


def _extent() -> tuple[float, float, float]:
    """Where the mark sits and how far it spreads: centre x, centre y, radius.

    Measured off the field rather than worked out by hand, so moving a shape
    above cannot quietly invalidate the fit below.
    """
    points = [
        (x / 2.0, y / 2.0)
        for y in range(0, 201)
        for x in range(0, 201)
        if mark(x / 2.0, y / 2.0, detail=True) <= 0
    ]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    return cx, cy, max(math.hypot(px - cx, py - cy) for px, py in points)


# --- raster ---------------------------------------------------------------

def png(size: int, *, rounded: bool = True, maskable: bool = False) -> bytes:
    small = size < 48
    grow = 1.6 if size <= 16 else 1.1 if small else 0.0
    corner = (16.0 if small else CORNER) if rounded else None
    samples = 4 if size <= 64 else 3
    step = 1.0 / (samples + 1)

    fit = None
    if maskable:
        cx, cy, radius = _extent()
        fit = (cx, cy, SAFE_RADIUS / radius)

    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            tile = ink = 0.0
            for sy in range(1, samples + 1):
                for sx in range(1, samples + 1):
                    x = (px + sx * step) * 100.0 / size
                    y = (py + sy * step) * 100.0 / size
                    if _tile(x, y, corner):
                        tile += 1.0
                        mx, my = x, y
                        if fit:
                            mx = (x - 50.0) / fit[2] + fit[0]
                            my = (y - 50.0) / fit[2] + fit[1]
                        if mark(mx, my, detail=not small) <= grow:
                            ink += 1.0
            total = samples * samples
            tile /= total
            ink /= total
            if tile == 0.0:
                row += bytes(4)
                continue
            # The gradient, then the white mark over whatever of the tile is in
            # this pixel — `mix` is the mark's share of the covered part, so an
            # edge pixel blends the two before its own alpha is applied.
            slide = (px + py) / (2.0 * size)
            mix = ink / tile
            pixel = []
            for channel in range(3):
                base = TOP[channel] + (BOTTOM[channel] - TOP[channel]) * slide
                pixel.append(round(base + (255 - base) * mix))
            row += bytes((*pixel, round(tile * 255)))
        rows.append(bytes(row))

    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def ico(sizes: list[int]) -> bytes:
    """An ICO of PNG entries — read by every browser still worth serving."""
    images = [png(size) for size in sizes]
    offset = 6 + 16 * len(images)
    directory = b""
    for size, data in zip(sizes, images):
        directory += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return struct.pack("<HHH", 0, 1, len(images)) + directory + b"".join(images)


def _contours(step: float = 0.5) -> list[list[tuple[float, float]]]:
    """The mark's outline, traced off the distance field by marching squares.

    The point of tracing rather than hand-writing paths: the SVG and the PNGs
    are then provably the same drawing. The old mark was a briefcase — four
    primitives that could be restated as five SVG elements without much risk. A
    flame with a cut-out core cannot be, and "edit the constants and re-run" is
    only true if the vector comes from the same numbers as the raster.

    Returns closed loops — the flame's outer edge, and the core's, which
    `fill-rule="evenodd"` then punches out.
    """
    size = int(100 / step)
    field = [[mark(x * step, y * step, detail=True) for x in range(size + 1)] for y in range(size + 1)]

    def cross(x0, y0, v0, x1, y1, v1):
        """Where the zero contour crosses this cell edge."""
        t = v0 / (v0 - v1)
        return (round((x0 + (x1 - x0) * t) * step, 3), round((y0 + (y1 - y0) * t) * step, 3))

    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for y in range(size):
        for x in range(size):
            a, b = field[y][x], field[y][x + 1]
            c, d = field[y + 1][x + 1], field[y + 1][x]
            case = (a < 0) | ((b < 0) << 1) | ((c < 0) << 2) | ((d < 0) << 3)
            if case in (0, 15):
                continue
            top = cross(x, y, a, x + 1, y, b)
            right = cross(x + 1, y, b, x + 1, y + 1, c)
            bottom = cross(x + 1, y + 1, c, x, y + 1, d)
            left = cross(x, y + 1, d, x, y, a)
            # Wound so the inside stays on the left; the saddles (5 and 10) are
            # resolved consistently rather than by centre sample, which at this
            # resolution never differs on a shape this smooth.
            edges = {
                1: [(left, top)], 2: [(top, right)], 3: [(left, right)],
                4: [(right, bottom)], 5: [(left, top), (right, bottom)],
                6: [(top, bottom)], 7: [(left, bottom)], 8: [(bottom, left)],
                9: [(bottom, top)], 10: [(top, right), (bottom, left)],
                11: [(bottom, right)], 12: [(right, left)], 13: [(right, top)],
                14: [(top, left)],
            }[case]
            segments.extend(edges)

    # Chain the segments into loops by walking from each start point to the
    # segment that begins where it ended.
    starting: dict[tuple[float, float], list[tuple[tuple[float, float], tuple[float, float]]]] = {}
    for segment in segments:
        starting.setdefault(segment[0], []).append(segment)

    loops: list[list[tuple[float, float]]] = []
    for segment in segments:
        following = starting.get(segment[0])
        if not following or segment not in following:
            continue
        loop = [segment[0]]
        point = segment[1]
        following.remove(segment)
        while True:
            loop.append(point)
            candidates = starting.get(point)
            if not candidates:
                break
            step_to = candidates.pop()
            point = step_to[1]
            if point == loop[0]:
                break
        if len(loop) > 8:
            loops.append(loop)
    return loops


def _path(loops: list[list[tuple[float, float]]]) -> str:
    parts = []
    for loop in loops:
        head, *rest = loop
        parts.append(f"M{head[0]:g} {head[1]:g}" + "".join(f"L{x:g} {y:g}" for x, y in rest) + "Z")
    return "".join(parts)


def svg() -> str:
    """The same mark as one path, traced off the same field the PNGs sample."""
    return f"""<!-- Generated by frontend/scripts/make-icons.py — edit the constants
     there and re-run, so the vector and the PNGs stay the same mark. -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" role="img" aria-label="Tinternship">
  <defs>
    <linearGradient id="flame" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="100" y2="100">
      <stop offset="0" stop-color="#{TOP[0]:02x}{TOP[1]:02x}{TOP[2]:02x}" />
      <stop offset="1" stop-color="#{BOTTOM[0]:02x}{BOTTOM[1]:02x}{BOTTOM[2]:02x}" />
    </linearGradient>
  </defs>
  <rect width="100" height="100" rx="{CORNER:g}" fill="url(#flame)" />
  <path d="{_path(_contours())}" fill="#fff" fill-rule="evenodd" />
</svg>
"""


def main() -> None:
    written: list[str] = []

    (OUT / "favicon.svg").write_text(svg())
    written.append("favicon.svg")

    (OUT / "favicon.ico").write_bytes(ico([16, 32, 48]))
    written.append("favicon.ico")

    for name, size, rounded, maskable in [
        ("icon-192.png", 192, True, False),
        ("icon-512.png", 512, True, False),
        # Full bleed, because Android supplies the shape — and shrunk to the
        # safe circle, because Android also supplies the crop.
        ("icon-maskable-512.png", 512, False, True),
        # iOS rounds the home-screen icon itself, and a transparent corner there
        # is rendered as black.
        ("apple-touch-icon.png", 180, False, False),
    ]:
        (OUT / name).write_bytes(png(size, rounded=rounded, maskable=maskable))
        written.append(name)

    for name in written:
        print(f"{name:<26} {(OUT / name).stat().st_size:>8,} bytes")

    cx, cy, radius = _extent()
    assert SAFE_RADIUS / 50.0 <= 0.80, "maskable art must stay inside the safe circle"
    print(
        f"\nmark spans {radius / 50 * 100:.0f}% of the radius as drawn, "
        f"{SAFE_RADIUS / 50 * 100:.0f}% in the maskable icon "
        f"(Android guarantees the middle 80%)"
    )


if __name__ == "__main__":
    main()
