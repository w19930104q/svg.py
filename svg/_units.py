"""CSS/SVG unit resolution.

Every absolute CSS unit is converted to a pixel length with an exact
rational factor, so that documents mixing e.g. mm and pt never accumulate
floating-point drift through repeated transform composition:

    https://www.w3.org/TR/css-values-3/#absolute-lengths

Percentage lengths are resolved against the current viewport (for
``x``/``width``-like attributes) rather than baked into the value itself.
"""
from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING

from ._types import Length, Number


if TYPE_CHECKING:
    from typing_extensions import Literal

    Axis = Literal["x", "y"]


# 1in is always 96px in SVG/CSS. Every other absolute unit is derived from
# that single anchor, hence the fractions stay exact.
PX_PER_UNIT: dict[str, Fraction] = {
    "px": Fraction(1),
    "in": Fraction(96),
    "cm": Fraction(96) / Fraction("2.54"),
    "mm": Fraction(96) / Fraction("25.4"),
    "pt": Fraction(96) / Fraction(72),       # 1pt = 1/72in
    "pc": Fraction(96) / Fraction(6),        # 1pc = 1/6in = 12pt
}

# Font-relative units cannot be resolved without a font-size context.
_FONT_RELATIVE = frozenset({"em", "ex"})


def _coerce(value: Number) -> Fraction:
    """Turn any supported scalar number into an exact rational value.

    Floats are rounded to a fixed decimal precision first so that values
    such as ``cos(pi/2)`` (6.12e-17) cannot introduce gigantic-denominator
    fractions. The rounding rule is shared with :mod:`svg._affine`, which
    keeps the whole pipeline deterministic across machines.
    """
    if isinstance(value, Fraction):
        return value
    if isinstance(value, float):
        if value == 0.0:
            return Fraction(0)
        return Fraction(f"{value:.12f}")
    # Decimal and int round-trip through their exact decimal string.
    return Fraction(str(value))


def to_px(
    value: Length | Number,
    axis: Axis = "x",
    viewport: tuple[Fraction, Fraction] | None = None,
    font_size: Fraction | None = None,
) -> Fraction:
    """Resolve a length (unit-carrying or bare number) to pixel units.

    A bare :class:`int`/:class:`float`/:class:`~decimal.Decimal` is already
    expressed in user units and is only made exact.

    ``%`` lengths are resolved against the current viewport size on the
    given axis (the width for ``x``, the height for ``y``).

    ``em``/``ex`` require ``font_size`` (in px); without it they cannot be
    resolved for geometry computation and raise :class:`ValueError`. They
    remain fully supported for plain SVG serialization via :class:`Length`.
    """
    if not isinstance(value, Length):
        return _coerce(value)

    if value.unit in _FONT_RELATIVE:
        if font_size is None:
            msg = (
                f"cannot resolve {value.unit!r} length without a font_size "
                "context; use absolute units or % for geometry computation"
            )
            raise ValueError(msg)
        factor = Fraction(1) if value.unit == "em" else Fraction(1, 2)
        return _coerce(value.value) * font_size * factor

    if value.unit == "%":
        if viewport is None:
            msg = "cannot resolve '%' length without a viewport"
            raise ValueError(msg)
        extent = viewport[0] if axis == "x" else viewport[1]
        return _coerce(value.value) * extent / Fraction(100)

    unit_factor: Fraction | None = PX_PER_UNIT.get(value.unit)
    if unit_factor is None:  # pragma: no cover - guarded by the Literal type
        msg = f"unsupported SVG length unit: {value.unit!r}"
        raise ValueError(msg)
    return _coerce(value.value) * unit_factor


def viewport_from_lengths(
    width: Length | Number | None,
    height: Length | Number | None,
    parent: tuple[Fraction, Fraction],
    font_size: Fraction | None = None,
) -> tuple[Fraction, Fraction]:
    """Resolve an element's width/height into a pixel viewport size.

    Missing dimensions fall back to the parent viewport; a bare percentage
    is taken relative to the parent extent on the matching axis.
    """
    if width is None:
        w = parent[0]
    else:
        w = to_px(width, "x", parent, font_size)
    if height is None:
        h = parent[1]
    else:
        h = to_px(height, "y", parent, font_size)
    return w, h
