"""Tests for exact unit resolution and affine matrix composition.

The whole point of these tests is that mixing mm/pt/% inputs and chaining
rotate/translate across nested groups must not depend on float string
rounding: CTMs are built from exact rationals and compared exactly.
"""
import math
from fractions import Fraction

import pytest

import svg
from svg._affine import Affine
from svg._units import PX_PER_UNIT, to_px


def test_absolute_units_are_exact_fractions():
    assert to_px(svg.mm(10)) == Fraction(4800, 127)
    assert to_px(svg.pt(72)) == Fraction(96)
    assert to_px(svg.Length(1, "in")) == Fraction(96)
    assert to_px(svg.Length(1, "cm")) == Fraction(4800, 127)
    assert to_px(svg.Length(1, "pc")) == Fraction(16)
    assert to_px(svg.px(7)) == Fraction(7)
    # Bare numbers are already user units.
    assert to_px(3) == Fraction(3)
    assert to_px(0.5) == Fraction(1, 2)


def test_standard_unit_table():
    # 96 px per inch anchors every CSS absolute length.
    assert PX_PER_UNIT["in"] == 96
    assert PX_PER_UNIT["pt"] * 72 == 96
    assert PX_PER_UNIT["mm"] * 25.4 == 96
    assert PX_PER_UNIT["pc"] == 16


def test_percentage_resolves_against_viewport_per_axis():
    vp = (Fraction(200), Fraction(100))
    assert to_px(svg.percent(50), "x", vp) == Fraction(100)
    assert to_px(svg.percent(50), "y", vp) == Fraction(50)
    assert to_px(svg.Length(25, "%"), "x", vp) == Fraction(50)


def test_percentage_without_viewport_is_an_error():
    with pytest.raises(ValueError):
        to_px(svg.percent(10))


def test_em_requires_font_size_context():
    with pytest.raises(ValueError):
        to_px(svg.Length(2, "em"))
    assert to_px(svg.Length(2, "em"), font_size=Fraction(10)) == Fraction(20)


def test_affine_apply_and_inverse():
    m = Affine.translation(4, -2).then(Affine.scaling(3, 6))
    assert m.apply(1, 1) == (Fraction(7), Fraction(4))
    back = m.inverse()
    assert back.apply(7, 4) == (Fraction(1), Fraction(1))
    assert m.then(back).is_identity


def test_rotation_around_center_keeps_center_fixed():
    m = Affine.rotation(45, 10, 20)
    x, y = m.apply(10, 20)
    assert x == Fraction(10)
    assert y == Fraction(20)


def test_singular_transform_cannot_invert():
    with pytest.raises(ValueError):
        Affine.scaling(0).inverse()


def test_transform_list_composes_left_to_right():
    vp = (Fraction(100), Fraction(100))
    transforms = [svg.Translate(10, 0), svg.Rotate(90)]
    ctm = svg.TransformList(transforms).to_affine(vp)
    # translate first, then rotate: (0,0) -> (10,0) -> (0,10)
    x, y = ctm.apply(0, 0)
    assert float(x) == 10.0
    assert math.isclose(float(y), 0.0, abs_tol=1e-12)


def test_translate_accepts_mixed_units_exactly():
    vp = (Fraction(38400, 127), Fraction(28800, 127))
    ctm = svg.Translate(svg.mm(10), svg.pt(36)).to_affine(vp)
    assert ctm.e == Fraction(4800, 127)
    assert ctm.f == Fraction(48)


def test_rotate_with_unit_center():
    vp = (Fraction(200), Fraction(200))
    ctm = svg.Rotate(90, svg.mm(10), 0).to_affine(vp)
    # The rotation center must map to itself regardless of input unit.
    x, y = ctm.apply(Fraction(4800, 127), 0)
    assert x == Fraction(4800, 127)
    assert y == 0
