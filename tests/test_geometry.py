"""Golden tests for the geometry pipeline.

Every fixture pins four things at once:

1. the exact serialized SVG string (so output formatting never drifts),
2. the resolved pixel viewport and per-element CTM (matrix composition),
3. the pixel-space bounding box (unit + viewBox correctness),
4. a SHA-256 hash of the reference-rendered pixels (final visual result).

The reference rasterizer is deterministic and dependency-free, so these
hashes are stable across machines and Python versions.
"""
import math
from fractions import Fraction

import pytest

import svg


GOLDEN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 120" '
    'width="80mm" height="60mm">'
    '<g transform="translate(10mm 36pt)">'
    '<g transform="rotate(90 20 10) translate(25% 0)">'
    '<rect stroke="black" stroke-width="1" x="0" y="0" width="8mm" '
    'height="24pt" fill="red"/>'
    '</g>'
    '<circle cx="40" cy="30" r="5mm" fill="#00ff00"/>'
    '</g>'
    '<polygon points="0,0 20,0 10,15" fill="blue"/>'
    '</svg>'
)

# sha256 of the 302x227 RGB bitmap rendered by svg.rasterize.
GOLDEN_PIXEL_HASH = (
    "6406c17ca054ae8fbbe69126616cc6b389e841d7ab9eeb3dc78639f16612893d"
)


def build_golden() -> svg.SVG:
    return svg.SVG(
        width=svg.mm(80), height=svg.mm(60),
        viewBox=svg.ViewBoxSpec(0, 0, 160, 120),
        elements=[
            svg.G(transform=[svg.Translate(svg.mm(10), svg.pt(36))], elements=[
                svg.G(
                    transform=[svg.Rotate(90, 20, 10), svg.Translate(svg.percent(25), 0)],
                    elements=[
                        svg.Rect(
                            x=0, y=0, width=svg.mm(8), height=svg.pt(24),
                            fill="red", stroke="black", stroke_width=1,
                        ),
                    ],
                ),
                svg.Circle(cx=40, cy=30, r=svg.mm(5), fill="#00ff00"),
            ]),
            svg.Polygon(
                points=[svg.Point(0, 0), svg.Point(20, 0), svg.Point(10, 15)],
                fill="blue",
            ),
        ],
    )


def test_serialized_output_is_pinned():
    assert str(build_golden()) == GOLDEN_SVG


def test_viewport_resolution_mixes_mm_and_viewbox():
    doc = build_golden()
    # 80mm at 96px/in -> 80 * 96 / 25.4 px exactly.
    assert svg.root_viewport(doc) == (
        Fraction(38400, 127), Fraction(28800, 127),
    )


def test_viewbox_sets_uniform_scale_ctm():
    doc = build_golden()
    root_ctm = svg.element_ctm(doc, doc)
    scale = Fraction(38400, 127) / 160
    assert root_ctm.a == scale
    assert root_ctm.d == scale
    assert (root_ctm.b, root_ctm.c, root_ctm.e, root_ctm.f) == (0, 0, 0, 0)


def test_nested_group_ctm_composes_units_and_rotations():
    doc = build_golden()
    groups = [el for el, _, _ in svg.iter_ctms(doc) if isinstance(el, svg.G)]
    outer, inner = groups

    outer_ctm = svg.element_ctm(doc, outer)
    # viewBox scale applied after mm/pt translation.
    scale = Fraction(38400, 127) / 160
    assert outer_ctm.e == scale * Fraction(4800, 127)
    assert outer_ctm.f == scale * Fraction(48)

    inner_ctm = svg.element_ctm(doc, inner)
    # The inner list is rotate(90 20 10) then translate(25% 0), i.e.
    # R * T in matrix terms: the translation happens first in local space
    # (40 user units in a 160-unit-wide viewBox), so (20,10) maps as
    # R * T * (20,10) = R * (60,10).
    cx, cy = inner_ctm.apply(20, 10)
    expected = outer_ctm.apply(*svg.Affine.rotation(90, 20, 10).apply(60, 10))
    assert math.isclose(float(cx), float(expected[0]), abs_tol=1e-9)
    assert math.isclose(float(cy), float(expected[1]), abs_tol=1e-9)
    # The percent translate resolved in user-space viewport units (160),
    # not against the physical pixel viewport (~302px).
    assert isinstance(inner_ctm.a, Fraction)


def test_pixel_bbox_matches_known_extent():
    doc = build_golden()
    box = svg.document_bbox(doc)
    assert box.min_x == 0 and box.min_y == 0
    assert math.isclose(box.width, 182.7267654535309, rel_tol=1e-10)
    assert math.isclose(box.height, 204.54088908177818, rel_tol=1e-10)
    assert box.width < box.height  # rotated mm/pt rect extends vertically


def test_pixel_hash_is_stable_and_64_hex_chars():
    doc = build_golden()
    digest = svg.pixel_hash(doc)
    assert digest == GOLDEN_PIXEL_HASH
    assert len(digest) == 64
    int(digest, 16)  # pure hex


def test_raster_canvas_size_matches_viewport():
    image = svg.rasterize(build_golden())
    assert (image.width, image.height) == (302, 227)


def test_moving_an_element_moves_its_bbox_exactly():
    """The original bug: string-built transforms shifted elements subtly.

    A translate of a clean integer distance must move bbox corners by
    exactly that distance in pixels (up to viewBox scale), no drift.
    """
    def make(dx):
        return svg.SVG(
            width=200, height=100,
            elements=[
                svg.G(transform=[svg.Translate(dx, 0)], elements=[
                    svg.Rect(x=10, y=10, width=20, height=20, fill="red"),
                ]),
            ],
        )

    base = svg.document_bbox(make(0))
    moved = svg.document_bbox(make(svg.mm(10)))
    shift = float(svg.to_px(svg.mm(10)))
    assert math.isclose(moved.min_x - base.min_x, shift, rel_tol=1e-12)
    assert moved.min_y == base.min_y
    assert moved.max_y == base.max_y
    assert math.isclose(moved.max_x - base.max_x, shift, rel_tol=1e-12)


def test_fluent_api_produces_identical_output_to_list_api():
    via_list = svg.Rect(
        width=10, height=5,
        transform=[svg.Translate(3, 4), svg.Rotate(45), svg.Scale(2)],
    )
    fluent = svg.Rect(width=10, height=5).translate(3, 4).rotate(45).scale(2)
    assert str(fluent) == str(via_list)
    assert isinstance(via_list.transform, list)


def test_fluent_transform_list_helpers():
    transforms = (
        svg.TransformList()
        .translate(svg.mm(5))
        .rotate(90)
        .scale(2)
        .skew_x(10)
        .matrix(1, 0, 0, 1, svg.pt(6), 0)
    )
    assert [type(t) for t in transforms] == [
        svg.Translate, svg.Rotate, svg.Scale, svg.SkewX, svg.Matrix,
    ]
    # Still serializes through the standard list-based attribute path.
    assert str(svg.G(transform=transforms)) == (
        '<g transform="translate(5mm) rotate(90) scale(2) skewX(10) '
        'matrix(1 0 0 1 6pt 0)"/>'
    )


def test_equivalent_transform_specifications_share_geometry():
    """An explicit matrix and its decomposed list share the same CTM/bbox."""
    angle = math.pi / 2
    a, b = math.cos(angle), math.sin(angle)
    # R(90) * T(10,0): the translation (10,0) lands in matrix slots (e,f).
    e, f = 10.0, 0.0
    matrix_doc = svg.SVG(
        width=100, height=100,
        elements=[svg.Rect(
            x=0, y=0, width=10, height=5, fill="red",
            transform=[svg.Matrix(a, b, -b, a, e, f)],
        )],
    )
    list_doc = svg.SVG(
        width=100, height=100,
        elements=[svg.Rect(
            x=0, y=0, width=10, height=5, fill="red",
            transform=[svg.Translate(10, 0), svg.Rotate(90)],
        )],
    )
    # The two declarations differ only in how the transform is written;
    # the composed CTM (the thing string concatenation used to get wrong)
    # must be numerically identical.
    ctm_a = svg.element_ctm(matrix_doc, matrix_doc.elements[0])
    ctm_b = svg.element_ctm(list_doc, list_doc.elements[0])
    for pa, pb in zip(tuple(ctm_a), tuple(ctm_b)):
        assert math.isclose(float(pa), float(pb), abs_tol=1e-12)
    # Sanity: a 10x5 rect rotated 90 degrees becomes a 5x10 box whose
    # bottom edge sits on y=10.
    box_b = svg.document_bbox(list_doc)
    assert math.isclose(box_b.min_y, 0.0, abs_tol=1e-9)
    assert math.isclose(box_b.max_y, 10.0, abs_tol=1e-9)
    assert math.isclose(box_b.width, 5.0, abs_tol=1e-9)
    assert math.isclose(box_b.height, 10.0, abs_tol=1e-9)
    # Both declarations serialize losslessly and keep the fluent API valid.
    assert "matrix(" in str(matrix_doc)
    assert "rotate(90)" in str(list_doc)


def test_nested_svg_viewport_and_percentage():
    inner = svg.SVG(
        x=svg.mm(5), y=0, width=svg.percent(50), height=svg.percent(50),
        viewBox=svg.ViewBoxSpec(0, 0, 50, 50),
        elements=[svg.Rect(x=0, y=0, width=50, height=50, fill="green")],
    )
    doc = svg.SVG(width=200, height=200, elements=[inner])
    box = svg.element_bbox(doc, inner.elements[0])
    # Nested viewport: 50% of 200px = 100px, viewBox 50 units -> scale 2.
    assert box.min_x == svg.to_px(svg.mm(5))
    assert box.width == 100
    assert box.height == 100


def test_evenodd_and_nonzero_fill_rules_render_differently():
    def doc(rule):
        return svg.SVG(
            width=60, height=60,
            elements=[svg.Path(
                fill_rule=rule,
                d=[
                    svg.M(0, 0), svg.L(60, 0), svg.L(60, 60), svg.L(0, 60), svg.Z(),
                    svg.M(20, 20), svg.L(40, 20), svg.L(40, 40), svg.L(20, 40), svg.Z(),
                ],
            )],
        )
    hashes = {rule: svg.pixel_hash(doc(rule)) for rule in ("evenodd", "nonzero")}
    assert hashes["evenodd"] != hashes["nonzero"]


def test_path_with_arc_flattens_and_renders():
    doc = svg.SVG(
        width=100, height=100,
        elements=[svg.Path(
            fill="red",
            d=[svg.M(10, 50), svg.Arc(40, 40, 0, False, True, 90, 50), svg.Z()],
        )],
    )
    box = svg.document_bbox(doc)
    assert box.min_x <= 10 and box.max_x >= 90
    digest = svg.pixel_hash(doc)
    assert len(digest) == 64
    # Determinism: re-rendering gives identical pixels.
    assert svg.pixel_hash(doc) == digest


@pytest.mark.parametrize("units,expected", [
    (svg.mm(25.4), 96.0),
    (svg.pt(72), 96.0),
    (svg.Length(1, "in"), 96.0),
    (svg.px(96), 96.0),
])
def test_physical_units_align_on_one_inch(units, expected):
    assert float(svg.to_px(units)) == expected


def _par_doc(alignment, scale_type):
    return svg.SVG(
        width=100, height=200,
        viewBox=svg.ViewBoxSpec(0, 0, 50, 50),
        preserveAspectRatio=svg.PreserveAspectRatio(alignment, scale_type),
        elements=[svg.Rect(width=1, height=1)],
    )


def test_preserve_aspect_ratio_meet_letterboxes():
    doc = _par_doc("xMidYMid", "meet")
    ctm = svg.element_ctm(doc, doc.elements[0])
    # min(100/50, 200/50) = 2; vertical letterbox offset 100px.
    assert float(ctm.a) == 2.0 and float(ctm.d) == 2.0
    assert float(ctm.e) == 0.0 and float(ctm.f) == 100.0


def test_preserve_aspect_ratio_slice_crops():
    doc = _par_doc("xMidYMid", "slice")
    ctm = svg.element_ctm(doc, doc.elements[0])
    # max(...) = 4; horizontal crop offset of -50 user units = -200px.
    assert float(ctm.a) == 4.0 and float(ctm.d) == 4.0
    assert float(ctm.e) == -200.0 and float(ctm.f) == 0.0


def test_preserve_aspect_ratio_none_stretches_per_axis():
    doc = _par_doc("none", "meet")
    ctm = svg.element_ctm(doc, doc.elements[0])
    assert float(ctm.a) == 2.0 and float(ctm.d) == 4.0
    assert float(ctm.e) == 0.0 and float(ctm.f) == 0.0


def test_stroke_only_line_is_rasterized():
    doc = svg.SVG(
        width=20, height=20,
        elements=[svg.Line(x1=2, y1=2, x2=18, y2=18,
                           stroke="black", stroke_width=2)],
    )
    image = svg.rasterize(doc)
    # The diagonal passes through pixel center (10.5, 10.5).
    offset = (10 * 20 + 10) * 3
    assert tuple(image.pixels[offset:offset + 3]) == (0, 0, 0)


def test_pixel_hash_is_deterministic_across_builds():
    def build():
        return svg.SVG(
            width=svg.mm(20), height=svg.pt(60),
            elements=[
                svg.G(
                    transform=svg.TransformList().rotate(30).translate(5, 7),
                    elements=[svg.Rect(x=1, y=2, width=3, height=4,
                                       fill="#aabbcc")],
                ),
            ],
        )
    assert svg.pixel_hash(build()) == svg.pixel_hash(build())


def test_transformable_mixin_covers_all_transformable_elements():
    # Every element type declaring a transform field got the fluent mixin.
    for cls in (
        svg.G, svg.Defs, svg.Image, svg.Switch, svg.Path, svg.Rect,
        svg.Circle, svg.Ellipse, svg.Line, svg.Polyline, svg.Polygon,
        svg.Text, svg.ClipPath, svg.Mask, svg.A, svg.ForeignObject, svg.Use,
    ):
        assert issubclass(cls, svg.TransformableMixin)
        assert callable(cls.translate) and callable(cls.rotate)
