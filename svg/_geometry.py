"""Geometry pipeline: viewports, CTMs, bounding boxes and pixel hashes.

This module is the numerical counterpart of the string-based serializer:

* :func:`root_viewport` resolves the outer ``width``/``height`` (mm, pt, %,
  ...) into an exact pixel viewport.
* :func:`iter_ctms` walks the element tree, applying nested ``viewBox`` /
  ``preserveAspectRatio`` mappings and every element's transform list to
  produce one exact :class:`~svg._affine.Affine` Current Transform Matrix
  per element.
* :func:`document_bbox` / :func:`element_bbox` compute pixel-space bounding
  boxes with all units and transforms already composed.
* :func:`rasterize` / :func:`pixel_hash` run a small deterministic,
  dependency-free reference rasterizer so the final rendered pixels can be
  checked by a stable hash.

The rasterizer intentionally covers the geometry features used by shapes
and paths (solid fills, plain strokes, both fill rules). Text, markers,
patterns, filters and ``<use>`` shadow trees are not rasterized.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Iterator

from . import elements as e
from ._affine import Affine, _num
from ._transforms import compose
from ._types import Length, Number
from ._units import to_px, viewport_from_lengths


# Number of straight segments used to flatten one curve command.
_CURVE_STEPS = 16
_ARC_STEPS = 24


@dataclass(frozen=True)
class BBox:
    """An axis-aligned bounding box in root pixel coordinates."""

    min_x: Fraction
    min_y: Fraction
    max_x: Fraction
    max_y: Fraction

    @property
    def width(self) -> Fraction:
        return self.max_x - self.min_x

    @property
    def height(self) -> Fraction:
        return self.max_y - self.min_y

    def union(self, other: "BBox") -> "BBox":
        return BBox(
            min(self.min_x, other.min_x),
            min(self.min_y, other.min_y),
            max(self.max_x, other.max_x),
            max(self.max_y, other.max_y),
        )

    def as_tuple(self) -> tuple[float, float, float, float]:
        return tuple(float(v) for v in (  # type: ignore[return-value]
            self.min_x, self.min_y, self.max_x, self.max_y,
        ))


def _from_points(points) -> BBox:
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return BBox(min(xs), min(ys), max(xs), max(ys))


# --------------------------------------------------------------------- viewport

def root_viewport(root: e.SVG) -> tuple[Fraction, Fraction]:
    """Resolve the root SVG viewport into exact pixel dimensions."""
    fallback = _viewbox_extent(root)
    width: Length | Number | None = root.width
    height: Length | Number | None = root.height
    if isinstance(width, Length) and width.unit == "%" and fallback is not None:
        width = fallback[0]
    if isinstance(height, Length) and height.unit == "%" and fallback is not None:
        height = fallback[1]
    if width is None or height is None:
        if fallback is None:
            msg = "root SVG needs width/height (or a viewBox) to resolve its viewport"
            raise ValueError(msg)
        width = fallback[0] if width is None else width
        height = fallback[1] if height is None else height
    return to_px(width, "x"), to_px(height, "y")


def _viewbox_extent(root: e.SVG) -> tuple[Fraction, Fraction] | None:
    if root.viewBox is None:
        return None
    vb = root.viewBox
    return to_px(vb.width, "x"), to_px(vb.height, "y")


def viewbox_matrix(
    viewbox,
    par,
    viewport: tuple[Fraction, Fraction],
) -> Affine:
    """Build the user-space -> viewport mapping for a viewBox."""
    vp_w, vp_h = viewport
    vb_x = to_px(viewbox.min_x, "x", viewport)
    vb_y = to_px(viewbox.min_y, "y", viewport)
    vb_w = to_px(viewbox.width, "x", viewport)
    vb_h = to_px(viewbox.height, "y", viewport)
    if vb_w == 0 or vb_h == 0:
        raise ValueError("viewBox width and height must be non-zero")

    if par is not None and par.alignment == "none":
        sx, sy = vp_w / vb_w, vp_h / vb_h
        tx, ty = -vb_x * sx, -vb_y * sy
        return Affine(sx, 0, 0, sy, tx, ty)

    if par is not None and par.scale_type == "slice":
        scale = max(vp_w / vb_w, vp_h / vb_h)
    else:  # default meet
        scale = min(vp_w / vb_w, vp_h / vb_h)

    alignment = par.alignment if par is not None else "xMidYMid"
    if "xMin" in alignment:
        tx = Fraction(0)
    elif "xMax" in alignment:
        tx = vp_w - scale * vb_w
    else:
        tx = (vp_w - scale * vb_w) / 2
    if "YMin" in alignment:
        ty = Fraction(0)
    elif "YMax" in alignment:
        ty = vp_h - scale * vb_h
    else:
        ty = (vp_h - scale * vb_h) / 2

    # T(viewport offset) * S(uniform) * T(-viewBox origin)
    origin = Affine.translation(-vb_x, -vb_y)
    scaled = origin.then(Affine.scaling(scale))
    return scaled.then(Affine.translation(tx, ty))


# --------------------------------------------------------------------- tree walk

def iter_ctms(
    root: e.SVG,
) -> Iterator[tuple[e.Element, Affine, tuple[Fraction, Fraction]]]:
    """Yield ``(element, ctm, viewport)`` for every node in the tree.

    The CTM maps the element's local user coordinates into root pixel
    coordinates. Nested ``<svg>`` elements establish a new viewport and a
    viewBox mapping; groups and transformable elements compose their
    transform list on top of the parent CTM.

    The reported viewport is the element's *user-space* viewport (the
    viewBox extent when one is present, matching the SVG rule that
    percentage transforms and lengths resolve against the viewport in
    local user units).
    """
    pixel_viewport = root_viewport(root)
    if root.viewBox is not None:
        user_viewport = (
            to_px(root.viewBox.width, "x"),
            to_px(root.viewBox.height, "y"),
        )
    else:
        user_viewport = pixel_viewport
    ctm = Affine.identity()
    if root.viewBox is not None:
        ctm = viewbox_matrix(root.viewBox, root.preserveAspectRatio, pixel_viewport)
    yield root, ctm, user_viewport
    yield from _walk_children(root, ctm, pixel_viewport, user_viewport)


def _walk_children(
    element: e.Element,
    ctm: Affine,
    pixel_viewport: tuple[Fraction, Fraction],
    user_viewport: tuple[Fraction, Fraction],
) -> Iterator[tuple[e.Element, Affine, tuple[Fraction, Fraction]]]:
    for child in element.elements or []:
        child_ctm, child_pixel_vp, child_user_vp = _enter(
            child, ctm, pixel_viewport, user_viewport,
        )
        yield child, child_ctm, child_user_vp
        yield from _walk_children(
            child, child_ctm, child_pixel_vp, child_user_vp,
        )


def _enter(
    element: e.Element,
    parent_ctm: Affine,
    parent_pixel_vp: tuple[Fraction, Fraction],
    parent_user_vp: tuple[Fraction, Fraction],
) -> tuple[Affine, tuple[Fraction, Fraction], tuple[Fraction, Fraction]]:
    ctm = parent_ctm
    pixel_viewport = parent_pixel_vp
    user_viewport = parent_user_vp

    if isinstance(element, e.SVG):
        # Width/height percentages on nested <svg> resolve against the
        # parent pixel viewport.
        pixel_viewport = viewport_from_lengths(
            element.width, element.height, parent_pixel_vp,
        )
        tx = to_px(element.x, "x", parent_pixel_vp) if element.x is not None else Fraction(0)
        ty = to_px(element.y, "y", parent_pixel_vp) if element.y is not None else Fraction(0)
        ctm = parent_ctm.then(Affine.translation(tx, ty))
        if element.viewBox is not None:
            ctm = ctm.then(viewbox_matrix(
                element.viewBox, element.preserveAspectRatio, pixel_viewport,
            ))
            user_viewport = (
                to_px(element.viewBox.width, "x"),
                to_px(element.viewBox.height, "y"),
            )
        else:
            user_viewport = pixel_viewport
        return ctm, pixel_viewport, user_viewport

    transforms = getattr(element, "transform", None)
    if transforms:
        ctm = parent_ctm.then(compose(transforms, user_viewport))
    return ctm, pixel_viewport, user_viewport


def element_ctm(root: e.SVG, target: e.Element) -> Affine:
    """Return the exact CTM of ``target`` within ``root``."""
    for element, ctm, _ in iter_ctms(root):
        if element is target:
            return ctm
    msg = "element is not part of the SVG tree"
    raise ValueError(msg)


# --------------------------------------------------------------------- local geometry

def _px(value, axis: str, viewport) -> Fraction:
    return to_px(value, axis, viewport)  # type: ignore[arg-type]


def _rect_polygon(element, viewport) -> list[tuple[Fraction, Fraction]]:
    x = _px(element.x or 0, "x", viewport)
    y = _px(element.y or 0, "y", viewport)
    w = _px(element.width or 0, "x", viewport)
    h = _px(element.height or 0, "y", viewport)
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def _ellipse_points(cx, cy, rx, ry, steps: int = 64):
    points = []
    for i in range(steps):
        angle = 2 * math.pi * i / steps
        points.append((
            cx + rx * _num(math.cos(angle)),
            cy + ry * _num(math.sin(angle)),
        ))
    return points


def _circle_polygon(element, viewport):
    cx = _px(element.cx or 0, "x", viewport)
    cy = _px(element.cy or 0, "y", viewport)
    r = _px(element.r or 0, "x", viewport)
    return _ellipse_points(cx, cy, r, r)


def _ellipse_polygon(element, viewport):
    cx = _px(element.cx or 0, "x", viewport)
    cy = _px(element.cy or 0, "y", viewport)
    rx = _px(element.rx or 0, "x", viewport)
    ry = _px(element.ry or 0, "y", viewport)
    return _ellipse_points(cx, cy, rx, ry)


def _line_segments(element, viewport):
    return [(
        (_px(element.x1 or 0, "x", viewport), _px(element.y1 or 0, "y", viewport)),
        (_px(element.x2 or 0, "x", viewport), _px(element.y2 or 0, "y", viewport)),
    )]


def _points_polygon(element, viewport):
    return [
        (
            _px(point.x, "x", viewport),
            _px(point.y, "y", viewport),
        )
        for point in element.points or []
    ]


# --------------------------------------------------------------------- path flattening

@dataclass
class _SubPath:
    points: list[tuple[Fraction, Fraction]]
    closed: bool = False


def _f(value) -> Fraction:
    return _num(value)


def flatten_path(commands) -> list[_SubPath]:
    """Flatten path data (including curves and arcs) into polygon subpaths."""
    subpaths: list[_SubPath] = []
    current = _SubPath([])
    start = (Fraction(0), Fraction(0))
    pos = start
    last_control: tuple[Fraction, Fraction] | None = None
    last_command = ""

    def begin(x, y):
        nonlocal current, start
        if current.points:
            subpaths.append(current)
        current = _SubPath([(x, y)])
        start = (x, y)

    def line_to(x, y):
        current.points.append((x, y))

    def cubic(p0, p1, p2, p3):
        for i in range(1, _CURVE_STEPS + 1):
            t = Fraction(i, _CURVE_STEPS)
            mt = 1 - t
            x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
            y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
            line_to(x, y)

    def quadratic(p0, p1, p2):
        for i in range(1, _CURVE_STEPS + 1):
            t = Fraction(i, _CURVE_STEPS)
            mt = 1 - t
            x = mt**2 * p0[0] + 2 * mt * t * p1[0] + t**2 * p2[0]
            y = mt**2 * p0[1] + 2 * mt * t * p1[1] + t**2 * p2[1]
            line_to(x, y)

    def arc(x1, y1, x2, y2, rx, ry, phi_deg, large_arc, sweep):
        rx, ry = abs(_f(rx)), abs(_f(ry))
        if rx == 0 or ry == 0:
            line_to(x2, y2)
            return
        phi = math.radians(float(_f(phi_deg)))
        cos_phi, sin_phi = math.cos(phi), math.sin(phi)
        dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
        x1p = cos_phi * float(dx) + sin_phi * float(dy)
        y1p = -sin_phi * float(dx) + cos_phi * float(dy)
        rxf, ryf = float(rx), float(ry)
        lam = x1p**2 / rxf**2 + y1p**2 / ryf**2
        if lam > 1:
            scale = math.sqrt(lam)
            rxf, ryf = rxf * scale, ryf * scale
            rx, ry = _f(rxf), _f(ryf)
        numerator = rxf**2 * ryf**2 - rxf**2 * y1p**2 - ryf**2 * x1p**2
        denominator = rxf**2 * y1p**2 + ryf**2 * x1p**2
        root = max(0.0, numerator / denominator)
        coef = math.sqrt(root) * (-1 if bool(large_arc) == bool(sweep) else 1)
        cxp = coef * rxf * y1p / ryf
        cyp = coef * -ryf * x1p / rxf
        cx = cos_phi * cxp - sin_phi * cyp + float((x1 + x2) / 2)
        cy = sin_phi * cxp + cos_phi * cyp + float((y1 + y2) / 2)

        def angle(ux, uy, vx, vy):
            dot = ux * vx + uy * vy
            norm = math.hypot(ux, uy) * math.hypot(vx, vy)
            a = math.acos(max(-1.0, min(1.0, dot / norm)))
            if ux * vy - uy * vx < 0:
                a = -a
            return a

        theta1 = angle(1, 0, (x1p - cxp) / rxf, (y1p - cyp) / ryf)
        delta = angle(
            (x1p - cxp) / rxf, (y1p - cyp) / ryf,
            (-x1p - cxp) / rxf, (-y1p - cyp) / ryf,
        )
        if not sweep and delta > 0:
            delta -= 2 * math.pi
        elif sweep and delta < 0:
            delta += 2 * math.pi
        steps = max(_ARC_STEPS // 2, int(math.ceil(abs(delta) / (2 * math.pi) * _ARC_STEPS)))
        for i in range(1, steps + 1):
            theta = theta1 + delta * i / steps
            ex = math.cos(theta) * rxf
            ey = math.sin(theta) * ryf
            line_to(
                _f(cx + cos_phi * ex - sin_phi * ey),
                _f(cy + sin_phi * ex + cos_phi * ey),
            )

    for cmd in commands or []:
        name = cmd.command
        if name == "M":
            pos = (_f(cmd.x), _f(cmd.y))
            begin(*pos)
        elif name == "m":
            pos = (pos[0] + _f(cmd.dx), pos[1] + _f(cmd.dy))
            begin(*pos)
        elif name == "L":
            pos = (_f(cmd.x), _f(cmd.y))
            line_to(*pos)
        elif name == "H":
            pos = (_f(cmd.x), pos[1])
            line_to(*pos)
        elif name == "V":
            pos = (pos[0], _f(cmd.y))
            line_to(*pos)
        elif name in ("l", "h", "v"):
            if name == "l":
                pos = (pos[0] + _f(cmd.dx), pos[1] + _f(cmd.dy))
            elif name == "h":
                pos = (pos[0] + _f(cmd.dx), pos[1])
            else:
                pos = (pos[0], pos[1] + _f(cmd.dy))
            line_to(*pos)
        elif name == "C":
            p1, p2 = (_f(cmd.x1), _f(cmd.y1)), (_f(cmd.x2), _f(cmd.y2))
            end = (_f(cmd.x), _f(cmd.y))
            cubic(pos, p1, p2, end)
            last_control, pos = p2, end
        elif name == "c":
            p1 = (pos[0] + _f(cmd.dx1), pos[1] + _f(cmd.dy1))
            p2 = (pos[0] + _f(cmd.dx2), pos[1] + _f(cmd.dy2))
            end = (pos[0] + _f(cmd.dx), pos[1] + _f(cmd.dy))
            cubic(pos, p1, p2, end)
            last_control, pos = p2, end
        elif name == "S":
            p1 = _reflect(last_control, pos, last_command)
            p2 = (_f(cmd.x2), _f(cmd.y2))
            end = (_f(cmd.x), _f(cmd.y))
            cubic(pos, p1, p2, end)
            last_control, pos = p2, end
        elif name == "s":
            p1 = _reflect(last_control, pos, last_command)
            p2 = (pos[0] + _f(cmd.dx2), pos[1] + _f(cmd.dy2))
            end = (pos[0] + _f(cmd.dx), pos[1] + _f(cmd.dy))
            cubic(pos, p1, p2, end)
            last_control, pos = p2, end
        elif name == "Q":
            p1 = (_f(cmd.x1), _f(cmd.y1))
            end = (_f(cmd.x), _f(cmd.y))
            quadratic(pos, p1, end)
            last_control, pos = p1, end
        elif name == "q":
            p1 = (pos[0] + _f(cmd.dx1), pos[1] + _f(cmd.dy1))
            end = (pos[0] + _f(cmd.dx), pos[1] + _f(cmd.dy))
            quadratic(pos, p1, end)
            last_control, pos = p1, end
        elif name == "T":
            p1 = _reflect(last_control, pos, last_command)
            end = (_f(cmd.x), _f(cmd.y))
            quadratic(pos, p1, end)
            last_control, pos = p1, end
        elif name == "t":
            p1 = _reflect(last_control, pos, last_command)
            end = (pos[0] + _f(cmd.dx), pos[1] + _f(cmd.dy))
            quadratic(pos, p1, end)
            last_control, pos = p1, end
        elif name == "A":
            end = (_f(cmd.x), _f(cmd.y))
            arc(pos[0], pos[1], end[0], end[1], cmd.rx, cmd.ry,
                cmd.angle, cmd.large_arc, cmd.sweep)
            pos = end
        elif name == "a":
            end = (pos[0] + _f(cmd.dx), pos[1] + _f(cmd.dy))
            arc(pos[0], pos[1], end[0], end[1], cmd.rx, cmd.ry,
                cmd.angle, cmd.large_arc, cmd.sweep)
            pos = end
        elif name in ("Z", "z"):
            current.closed = True
            line_to(*start)
            pos = start
        last_command = name
        if name not in ("S", "s", "C", "c", "Q", "q", "T", "t"):
            last_control = None
    if current.points:
        subpaths.append(current)
    return subpaths


def _reflect(control, pos, last_command) -> tuple[Fraction, Fraction]:
    if control is not None and last_command in ("C", "c", "S", "s", "Q", "q", "T", "t"):
        return (2 * pos[0] - control[0], 2 * pos[1] - control[1])
    return pos


# --------------------------------------------------------------------- bbox


def local_outline(element, viewport) -> list[_SubPath]:
    """Return the element's geometry as subpaths in local user units."""
    if isinstance(element, (e.Rect, e.Image, e.ForeignObject)):
        return [_SubPath(_rect_polygon(element, viewport), closed=True)]
    if isinstance(element, e.Circle):
        return [_SubPath(_circle_polygon(element, viewport), closed=True)]
    if isinstance(element, e.Ellipse):
        return [_SubPath(_ellipse_polygon(element, viewport), closed=True)]
    if isinstance(element, (e.Polygon, e.Polyline)):
        closed = isinstance(element, e.Polygon)
        return [_SubPath(_points_polygon(element, viewport), closed=closed)]
    if isinstance(element, e.Line):
        a, b = _line_segments(element, viewport)[0]
        return [_SubPath([a, b], closed=False)]
    if isinstance(element, e.Path):
        return flatten_path(element.d)
    return []


def element_bbox(root: e.SVG, target: e.Element) -> BBox:
    """Bounding box of one element in root pixel coordinates."""
    ctm = element_ctm(root, target)
    viewport = _viewport_of(root, target)
    subpaths = local_outline(target, viewport)
    points = [pt for sub in subpaths for pt in ctm.map_points(sub.points)]
    if not points:
        msg = "element has no rasterizable geometry"
        raise ValueError(msg)
    return _from_points(points)


def _viewport_of(root: e.SVG, target: e.Element) -> tuple[Fraction, Fraction]:
    for element, _, viewport in iter_ctms(root):
        if element is target:
            return viewport
    msg = "element is not part of the SVG tree"
    raise ValueError(msg)


def document_bbox(root: e.SVG) -> BBox:
    """Union bounding box of all rasterizable geometry in root pixels."""
    boxes = []
    for element, ctm, viewport in iter_ctms(root):
        subpaths = local_outline(element, viewport)
        for sub in subpaths:
            points = ctm.map_points(sub.points)
            if points:
                boxes.append(_from_points(points))
    if not boxes:
        msg = "document contains no rasterizable geometry"
        raise ValueError(msg)
    box = boxes[0]
    for other in boxes[1:]:
        box = box.union(other)
    return box


# --------------------------------------------------------------------- rasterizer

@dataclass(frozen=True)
class RasterImage:
    width: int
    height: int
    pixels: bytes  # row-major RGB, 3 bytes per pixel

    def hash(self) -> str:
        digest = hashlib.sha256()
        digest.update(f"{self.width}x{self.height}:".encode("ascii"))
        digest.update(self.pixels)
        return digest.hexdigest()


_NAMED_COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "grey": (128, 128, 128),
    "gray": (128, 128, 128), "yellow": (255, 255, 0), "none": None,
}


def _parse_color(value) -> tuple[int, int, int] | None:
    if value is None:
        return (0, 0, 0)  # SVG default fill is black
    if not isinstance(value, str):
        return (0, 0, 0)
    name = value.strip().lower()
    if name in _NAMED_COLORS:
        return _NAMED_COLORS[name]
    if name.startswith("#"):
        hexpart = name[1:]
        if len(hexpart) == 3:
            hexpart = "".join(ch * 2 for ch in hexpart)
        if len(hexpart) == 6:
            try:
                return tuple(int(hexpart[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
            except ValueError:
                return None
    return None


def _distance_to_segment(px: float, py: float, a, b) -> float:
    ax, ay, bx, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(px - qx, py - qy)


def rasterize(root: e.SVG) -> RasterImage:
    """Render the SVG to a small RGB bitmap with the reference rasterizer.

    Coverage is binary (no anti-aliasing) and every coordinate is evaluated
    at pixel centers, so output is fully deterministic across machines.
    """
    vp_w, vp_h = root_viewport(root)
    width = max(1, round(float(vp_w)))
    height = max(1, round(float(vp_h)))
    canvas = bytearray((255, 255, 255) * width * height)

    for element, ctm, viewport in iter_ctms(root):
        subpaths = local_outline(element, viewport)
        if not subpaths:
            continue
        fill = _parse_color(getattr(element, "fill", None))
        stroke_value = getattr(element, "stroke", None)
        stroke = _parse_color(stroke_value) if stroke_value not in (None, "none") else None
        stroke_width = getattr(element, "stroke_width", None)
        explicit_rule = getattr(element, "fill_rule", None)
        if explicit_rule is not None:
            nonzero = explicit_rule == "nonzero"
        else:
            # SVG default: nonzero, except polygons/polylines/rects use
            # evenodd when two subpaths overlap.
            nonzero = not isinstance(element, (e.Polygon, e.Polyline, e.Rect))
        world_subs = [
            ctm.map_points(sub.points) for sub in subpaths
        ]
        inv = ctm.inverse() if ctm.determinant != 0 else None

        for row in range(height):
            py = row + 0.5
            for col in range(width):

                px = col + 0.5
                inside = False
                if fill is not None:
                    # Winding/crossing must accumulate across every subpath
                    # of the element so fill-rule works for holes.
                    winding = 0
                    crossings = 0
                    for polygon in world_subs:
                        for (wx1, wy1), (wx2, wy2) in zip(
                            polygon, polygon[1:] + polygon[:1]
                        ):
                            x1, y1 = float(wx1), float(wy1)
                            x2, y2 = float(wx2), float(wy2)
                            if (y1 <= py < y2) or (y2 <= py < y1):
                                cross_x = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
                                if cross_x < px:
                                    crossings += 1
                                    winding += 1 if y2 > y1 else -1
                    inside = winding != 0 if nonzero else crossings % 2 == 1
                stroked = False
                if stroke is not None and stroke_width is not None and inv is not None:
                    width_local = float(to_px(stroke_width, "x", viewport))
                    lx_f, ly_f = inv.apply(_f(px), _f(py))
                    lx, ly = float(lx_f), float(ly_f)
                    for sub in subpaths:
                        for a, b in zip(sub.points, sub.points[1:]):
                            if _distance_to_segment(lx, ly, a, b) <= width_local / 2:
                                stroked = True
                                break
                        if stroked:
                            break
                color = stroke if stroked else fill if inside else None
                if color is None:
                    continue
                offset = (row * width + col) * 3
                canvas[offset:offset + 3] = bytes(color)

    return RasterImage(width, height, bytes(canvas))


def pixel_hash(root: e.SVG) -> str:
    """SHA-256 of the reference-rendered pixels (including canvas size)."""
    return rasterize(root).hash()
