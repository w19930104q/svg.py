from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable

from ._affine import Affine
from ._types import Length, Number
from ._units import to_px


Viewport = tuple[Fraction, Fraction]


class Transform:
    """
    https://developer.mozilla.org/en-US/docs/Web/SVG/Attribute/transform

    Every transform knows how to turn itself into an exact
    :class:`~svg._affine.Affine` matrix, so a whole transform list can be
    composed into a single Current Transform Matrix instead of relying on
    string concatenation at render time.
    """

    def to_affine(
        self,
        viewport: Viewport,
        font_size: Fraction | None = None,
    ) -> Affine:  # pragma: no cover - abstract, overridden everywhere
        raise NotImplementedError


@dataclass
class Matrix(Transform):
    """
    https://developer.mozilla.org/en-US/docs/Web/SVG/Attribute/transform#matrix
    """
    a: Number
    b: Number
    c: Number
    d: Number
    e: Length | Number
    f: Length | Number

    def __str__(self):
        return f'matrix({self.a} {self.b} {self.c} {self.d} {self.e} {self.f})'

    def to_affine(self, viewport, font_size=None) -> Affine:
        return Affine(
            self.a,
            self.b,
            self.c,
            self.d,
            to_px(self.e, 'x', viewport, font_size),
            to_px(self.f, 'y', viewport, font_size),
        )


@dataclass
class Translate(Transform):
    """
    https://developer.mozilla.org/en-US/docs/Web/SVG/Attribute/transform#translate
    """
    x: Length | Number
    y: Length | Number | None = None

    def __str__(self):
        if self.y is None:
            return f'translate({self.x})'
        return f'translate({self.x} {self.y})'

    def to_affine(self, viewport, font_size=None) -> Affine:
        tx = to_px(self.x, 'x', viewport, font_size)
        if self.y is None:
            ty = Fraction(0)
        else:
            ty = to_px(self.y, 'y', viewport, font_size)
        return Affine.translation(tx, ty)


@dataclass
class Scale(Transform):
    """
    https://developer.mozilla.org/en-US/docs/Web/SVG/Attribute/transform#scale
    """
    x: Number
    y: Number | None = None

    def __str__(self):
        if self.y is None:
            return f'scale({self.x})'
        return f'scale({self.x} {self.y})'

    def to_affine(self, viewport, font_size=None) -> Affine:
        return Affine.scaling(self.x, self.y)


@dataclass
class Rotate(Transform):
    """
    https://developer.mozilla.org/en-US/docs/Web/SVG/Attribute/transform#rotate
    """
    a: Number
    x: Length | Number | None = None
    y: Length | Number | None = None

    def __str__(self):
        if self.x is None:
            return f'rotate({self.a})'
        assert self.y is not None
        return f'rotate({self.a} {self.x} {self.y})'

    def to_affine(self, viewport, font_size=None) -> Affine:
        if self.x is None:
            return Affine.rotation(self.a)
        assert self.y is not None
        cx = to_px(self.x, 'x', viewport, font_size)
        cy = to_px(self.y, 'y', viewport, font_size)
        return Affine.rotation(self.a, cx, cy)


@dataclass
class SkewX(Transform):
    """
    https://developer.mozilla.org/en-US/docs/Web/SVG/Attribute/transform#skewx
    """
    a: Number

    def __str__(self):
        return f'skewX({self.a})'

    def to_affine(self, viewport, font_size=None) -> Affine:
        return Affine.skew_x(self.a)


@dataclass
class SkewY(Transform):
    """
    https://developer.mozilla.org/en-US/docs/Web/SVG/Attribute/transform#skewy
    """
    a: Number

    def __str__(self):
        return f'skewY({self.a})'

    def to_affine(self, viewport, font_size=None) -> Affine:
        return Affine.skew_y(self.a)


class TransformList(list):
    """A list of :class:`Transform` objects with fluent chain helpers.

    It stays a plain ``list`` (so serialization and the existing
    ``transform=[...]`` API are unchanged) but also supports::

        transforms = (
            TransformList()
            .translate(10, 20)
            .rotate(45)
            .scale(2)
        )
    """

    def translate(self, x: Length | Number, y: Length | Number | None = None) -> "TransformList":
        self.append(Translate(x, y))
        return self

    def scale(self, x: Number, y: Number | None = None) -> "TransformList":
        self.append(Scale(x, y))
        return self

    def rotate(
        self,
        angle: Number,
        x: Length | Number | None = None,
        y: Length | Number | None = None,
    ) -> "TransformList":
        self.append(Rotate(angle, x, y))
        return self

    def skew_x(self, angle: Number) -> "TransformList":
        self.append(SkewX(angle))
        return self

    def skew_y(self, angle: Number) -> "TransformList":
        self.append(SkewY(angle))
        return self

    def matrix(
        self,
        a: Number,
        b: Number,
        c: Number,
        d: Number,
        e: Length | Number,
        f: Length | Number,
    ) -> "TransformList":
        self.append(Matrix(a, b, c, d, e, f))
        return self

    def to_affine(
        self,
        viewport: Viewport,
        font_size: Fraction | None = None,
    ) -> Affine:
        return compose(self, viewport, font_size)


class TransformableMixin:
    """Fluent transform helpers for elements carrying a ``transform`` field.

    The attribute-based API (``transform=[svg.Rotate(45), ...]``) keeps
    working unchanged; these methods only return ``self`` after appending,
    so an element can be built incrementally::

        rect = svg.Rect(width=10, height=10).translate(20, 5).rotate(45)
    """

    transform: list[Transform] | None

    def transforms(self) -> TransformList:
        """Return the element's transform list, creating it if absent."""
        if self.transform is None:
            self.transform = TransformList()
        elif not isinstance(self.transform, TransformList):
            # Preserve any plain list the user assigned.
            self.transform = TransformList(self.transform)
        return self.transform

    def translate(self, x: Length | Number, y: Length | Number | None = None):
        self.transforms().translate(x, y)
        return self

    def scale(self, x: Number, y: Number | None = None):
        self.transforms().scale(x, y)
        return self

    def rotate(
        self,
        angle: Number,
        x: Length | Number | None = None,
        y: Length | Number | None = None,
    ):
        self.transforms().rotate(angle, x, y)
        return self

    def skew_x(self, angle: Number):
        self.transforms().skew_x(angle)
        return self

    def skew_y(self, angle: Number):
        self.transforms().skew_y(angle)
        return self

    def matrix(
        self,
        a: Number,
        b: Number,
        c: Number,
        d: Number,
        e: Length | Number,
        f: Length | Number,
    ):
        self.transforms().matrix(a, b, c, d, e, f)
        return self


def compose(
    transforms: Iterable[Transform] | None,
    viewport: Viewport,
    font_size: Fraction | None = None,
) -> Affine:
    """Compose a transform list into one exact CTM.

    Transforms apply left to right, exactly as the SVG transform attribute
    specifies: the first transform in the list acts on the element first.
    """
    ctm = Affine.identity()
    if not transforms:
        return ctm
    for transform in transforms:
        ctm = ctm.then(transform.to_affine(viewport, font_size))
    return ctm
