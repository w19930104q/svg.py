"""Exact affine transforms and matrix composition.

An affine transform in the 2D SVG plane is represented as the 3x3 matrix

    | a c e |
    | b d f |
    | 0 0 1 |

mapping column vectors ``(x, y, 1)``. All entries are stored as
:class:`~fractions.Fraction`, so composing arbitrary chains of
rotate/translate/scale/skew (with inputs given in mm, pt, % or bare
numbers) keeps the resulting Current Transform Matrix exact; the only
rounding happens once, when numbers are formatted into the output string.
"""
from __future__ import annotations

import math
from fractions import Fraction
from typing import Iterable, Tuple

from ._types import Number


# A point in pixel/user units, kept exact while walking the element tree.
Point2 = Tuple[Fraction, Fraction]


def _num(value: Number) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, float):
        # Clamp float-derived coefficients to a fixed decimal precision.
        # Without this, values like cos(pi/2) = 6.12e-17 survive as exact
        # fractions with gigantic denominators and blow up bounding boxes;
        # rounding here also makes every machine produce identical pixels.
        if value == 0.0:
            return Fraction(0)
        return Fraction(f"{value:.12f}")
    return Fraction(str(value))


class Affine:
    """An immutable 2D affine transformation with rational entries."""

    __slots__ = ("a", "b", "c", "d", "e", "f")

    def __init__(
        self,
        a: Number = 1,
        b: Number = 0,
        c: Number = 0,
        d: Number = 1,
        e: Number = 0,
        f: Number = 0,
    ) -> None:
        self.a = _num(a)
        self.b = _num(b)
        self.c = _num(c)
        self.d = _num(d)
        self.e = _num(e)
        self.f = _num(f)

    @classmethod
    def identity(cls) -> "Affine":
        return cls()

    @classmethod
    def translation(cls, tx: Number, ty: Number = 0) -> "Affine":
        return cls(1, 0, 0, 1, tx, ty)

    @classmethod
    def scaling(cls, sx: Number, sy: Number | None = None) -> "Affine":
        if sy is None:
            sy = sx
        return cls(sx, 0, 0, sy, 0, 0)

    @classmethod
    def rotation(cls, angle_deg: Number, cx: Number = 0, cy: Number = 0) -> "Affine":
        """Rotate by ``angle_deg`` around ``(cx, cy)``.

        Equivalent to ``translate(cx, cy) rotate(angle) translate(-cx, -cy)``.
        """
        angle = _num(angle_deg) * Fraction(math.pi) / 180
        cos_a = Fraction(math.cos(float(angle)))
        sin_a = Fraction(math.sin(float(angle)))
        center = cls.translation(cx, cy)
        rot = cls(cos_a, sin_a, -sin_a, cos_a, 0, 0)
        return center @ rot @ center.inverse()

    @classmethod
    def skew_x(cls, angle_deg: Number) -> "Affine":
        angle = _num(angle_deg) * Fraction(math.pi) / 180
        return cls(1, 0, Fraction(math.tan(float(angle))), 1, 0, 0)

    @classmethod
    def skew_y(cls, angle_deg: Number) -> "Affine":
        angle = _num(angle_deg) * Fraction(math.pi) / 180
        return cls(1, Fraction(math.tan(float(angle))), 0, 1, 0, 0)

    def then(self, other: "Affine") -> "Affine":
        """Return the transform applying ``self`` first and ``other`` after.

        This matches the SVG rule that transform lists apply left to right:
        the left-most transform is applied to the element first.
        """
        a, b, c, d, e, f = self
        g, h, i, j, k, m = other
        return Affine(
            a * g + c * h,
            b * g + d * h,
            a * i + c * j,
            b * i + d * j,
            a * k + c * m + e,
            b * k + d * m + f,
        )

    def __matmul__(self, other: "Affine") -> "Affine":
        return self.then(other)

    def __iter__(self):
        return iter((self.a, self.b, self.c, self.d, self.e, self.f))

    @property
    def determinant(self) -> Fraction:
        return self.a * self.d - self.b * self.c

    def inverse(self) -> "Affine":
        det = self.determinant
        if det == 0:
            raise ValueError("cannot invert a singular affine transform")
        inv_det = Fraction(1, 1) / det
        return Affine(
            self.d * inv_det,
            -self.b * inv_det,
            -self.c * inv_det,
            self.a * inv_det,
            (self.c * self.f - self.d * self.e) * inv_det,
            (self.b * self.e - self.a * self.f) * inv_det,
        )

    def apply(self, x: Number, y: Number) -> Point2:
        """Map a single point through the transform."""
        px, py = _num(x), _num(y)
        return (
            self.a * px + self.c * py + self.e,
            self.b * px + self.d * py + self.f,
        )

    def map_points(self, points: Iterable[tuple[Number, Number]]) -> list[Point2]:
        return [self.apply(x, y) for x, y in points]

    @property
    def is_identity(self) -> bool:
        return (self.a, self.b, self.c, self.d, self.e, self.f) == (1, 0, 0, 1, 0, 0)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Affine):
            return NotImplemented
        return tuple(self) == tuple(other)

    def __hash__(self) -> int:
        return hash(tuple(self))

    def __repr__(self) -> str:
        return "Affine(" + ", ".join(str(v) for v in self) + ")"
