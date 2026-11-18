"""SVG drawing library
"""
from ._affine import Affine
from ._filters import (
    FeBlend, FeColorMatrix, FeComponentTransfer, FeComposite, FeConvolveMatrix,
    FeDiffuseLighting, FeDisplacementMap, FeDistantLight, FeDropShadow,
    FeFlood, FeFuncA, FeFuncB, FeFuncG, FeFuncR, FeGaussianBlur, FeImage,
    FeMerge, FeMergeNode, FeMorphology, FeOffset, FePointLight,
    FeSpecularLighting, FeSpotLight, FeTile, FeTurbulence, Filter,
)
from ._geometry import (
    BBox, RasterImage, document_bbox, element_bbox, element_ctm, flatten_path,
    iter_ctms, pixel_hash, rasterize, root_viewport, viewbox_matrix,
)
from ._helpers import escape, mm, percent, pt, px
from ._path import (
    Arc, ArcRel, C, ClosePath, CubicBezier, CubicBezierRel, H,
    HorizontalLineTo, HorizontalLineToRel, L, LineTo, LineToRel, M, MoveTo,
    MoveToRel, PathData, Q, QuadraticBezier, QuadraticBezierRel, S,
    SmoothCubicBezier, SmoothCubicBezierRel, SmoothQuadraticBezier,
    SmoothQuadraticBezierRel, T, V, VerticalLineTo, VerticalLineToRel, Z, a, c,
    h, l, m, q, s, t, v,
)
from ._transforms import (
    Matrix, Rotate, Scale, SkewX, SkewY, Transform, TransformableMixin,
    TransformList, Translate,
)
from ._types import (
    AccessKeyValue, AnimationTimingEvent, EventValue, Length, Point,
    PreserveAspectRatio, RepeatValue, SyncbaseValue, TimeBezierPoint,
    ViewBoxSpec,
)
from ._units import PX_PER_UNIT, to_px, viewport_from_lengths
from .elements import (
    SVG, A, Animate, AnimateMotion, AnimateTransform, Circle, ClipPath,
    ColorProfile, DefinitionSrc, Defs, Desc, Element, Ellipse, ForeignObject,
    G, Image, Line, LinearGradient, Marker, Mask, Metadata, MPath, Path,
    Pattern, Polygon, Polyline, RadialGradient, Rect, Script, Set, Stop, Style,
    Switch, Symbol, Text, TextPath, Title, TSpan, Use, View,
)


SemicolonSeparatedList = list
"""
DEPRECATED: we keep it only for backward compatibility. Use `list` instead.
"""


__version__ = '1.10.0'
__all__ = [
    'values',
    'escape',
    'mm',
    'px',
    'pt',
    'percent',

    # elements
    'Element',
    'A',
    'Animate',
    'AnimateMotion',
    'AnimateTransform',
    'Circle',
    'ClipPath',
    'ColorProfile',
    'DefinitionSrc',
    'Defs',
    'Desc',
    'Element',
    'Ellipse',
    'ForeignObject',
    'G',
    'Image',
    'Line',
    'LinearGradient',
    'Marker',
    'Mask',
    'Metadata',
    'MPath',
    'Path',
    'Pattern',
    'Polygon',
    'Polyline',
    'RadialGradient',
    'Rect',
    'Script',
    'Set',
    'Stop',
    'Style',
    'SVG',
    'Switch',
    'Symbol',
    'Text',
    'TextPath',
    'Title',
    'TSpan',
    'Use',
    'View',

    # filters
    'Filter',
    'FeBlend',
    'FeColorMatrix',
    'FeComponentTransfer',
    'FeComposite',
    'FeConvolveMatrix',
    'FeDiffuseLighting',
    'FeDisplacementMap',
    'FeDistantLight',
    'FeDropShadow',
    'FeFlood',
    'FeFuncA',
    'FeFuncB',
    'FeFuncG',
    'FeFuncR',
    'FeGaussianBlur',
    'FeImage',
    'FeMerge',
    'FeMergeNode',
    'FeMorphology',
    'FeOffset',
    'FePointLight',
    'FeSpecularLighting',
    'FeSpotLight',
    'FeTile',
    'FeTurbulence',

    # transforms
    'Transform',
    'TransformList',
    'TransformableMixin',
    'Matrix',
    'Translate',
    'Scale',
    'Rotate',
    'SkewX',
    'SkewY',

    # geometry pipeline (units, matrices, bbox, pixels)
    'Affine',
    'BBox',
    'RasterImage',
    'PX_PER_UNIT',
    'to_px',
    'viewport_from_lengths',
    'viewbox_matrix',
    'root_viewport',
    'iter_ctms',
    'element_ctm',
    'element_bbox',
    'document_bbox',
    'flatten_path',
    'rasterize',
    'pixel_hash',

    # path data
    'PathData',
    'M', 'MoveTo',
    'm', 'MoveToRel',
    'L', 'LineTo',
    'l', 'LineToRel',
    'H', 'HorizontalLineTo',
    'h', 'HorizontalLineToRel',
    'V', 'VerticalLineTo',
    'v', 'VerticalLineToRel',
    'C', 'CubicBezier',
    'c', 'CubicBezierRel',
    'S', 'SmoothCubicBezier',
    's', 'SmoothCubicBezierRel',
    'Q', 'QuadraticBezier',
    'q', 'QuadraticBezierRel',
    'T', 'SmoothQuadraticBezier',
    't', 'SmoothQuadraticBezierRel',
    'A', 'Arc',
    'a', 'ArcRel',
    'Z', 'ClosePath',

    # types
    'AccessKeyValue',
    'AnimationTimingEvent',
    'EventValue',
    'Length',
    'Point',
    'PreserveAspectRatio',
    'RepeatValue',
    'SyncbaseValue',
    'TimeBezierPoint',
    'ViewBoxSpec',
]
