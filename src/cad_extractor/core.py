"""
Core Extraction Engine (v3.1 Hardened).
Extracts AutoCAD DWG and native DXF files into the standardized La Vinci CAD IR v3:
- Dual-Format Ingestion: Direct DXF parsing + headless LibreDWG DWG conversion
- Subprocess timeout protection (timeout=120s) and strict exit-code validation
- Robust Bounding Box Extents (Arc/Circle radii, Dimension defpoint2, NaN/Inf protection)
- Unpaired Unicode surrogate sanitization for safe UTF-8 JSON serialization
- Negative ACI color index protection (-1, -7 turned-off layer states)
- Reusable Block Definitions (doc.blocks internal primitives)
- True BYLAYER semantics (color=None unless explicit override)
- Unnormalized Arc Angles (passes native DXF sweep angles)
- Full CIRCLE entity extraction
- Both Model Space AND Paper Space (Layouts & Viewports)
- Block Attribute (`ATTRIB`) extraction & Anonymous Block Disambiguation
- DIMENSION entity extraction
- Clean MTEXT escape-code sanitization
"""

import os
import re
import math
import shutil
import tempfile
import subprocess
from collections import Counter
from typing import Dict, Any, List, Optional, Tuple, Sequence, Set

import ezdxf
import ezdxf.path
import ezdxf.tools.crypt as _ezdxf_crypt
from ezdxf.colors import aci2rgb

# Robustly monkeypatch ACIS crypt decode to handle non-ASCII characters without crashing
_orig_crypt_decode = _ezdxf_crypt.decode
def _safe_crypt_decode(text_lines):
    def _decode_safe(text):
        dectab = _ezdxf_crypt._decode_table
        s = []
        if isinstance(text, str):
            text_bytes = text.encode("ascii", errors="replace")
        else:
            text_bytes = bytes(text)
        skip = False
        for c in text_bytes:
            if skip:
                skip = False
                continue
            if c in dectab:
                s.append(dectab[c])
                skip = (c == 0x5E)
            else:
                s.append(chr(c ^ 0x5F))
        return "".join(s)
    return (_decode_safe(line) for line in text_lines)

_ezdxf_crypt.decode = _safe_crypt_decode


from .models import (
    CADIntermediateRepresentation,
    CADMetadata,
    CADExtents,
    CADLayout,
    CADViewport,
    CADLayer,
    CADComponentInstance,
    CADBlockDefinition,
    CADAnnotation,
    CADDimension,
    CADLine,
    CADArc,
    CADCircle,
    CADPolyline,
    CADPrimitives,
    CADPrimitiveSummary,
    CADGeometry,
)

def sanitize_surrogates(text: str) -> str:
    """Removes lone or unpaired Unicode surrogate code points (\ud800-\udfff) preventing JSON crash."""
    if not text:
        return ""
    try:
        # Encode with surrogatepass, then decode replacing unencodable surrogates
        return text.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
    except Exception:
        return "".join(c for c in text if not (0xD800 <= ord(c) <= 0xDFFF))

def clean_cad_text(text: str) -> str:
    r"""Strips AutoCAD MTEXT formatting tags (\f..., \H..., \P, \C..., underline \L\l, braces)."""
    if not text:
        return ""
    # Strip parameter blocks ending in semicolon (\H...; \f...; \C...; \A...; \W...; \Q...; \T...; \S...;)
    s = re.sub(r"\\[HhFfCcAaWwQqTtSs][^;]*;", "", text)
    # Strip inline mode toggles: \L (underline on), \l (underline off), \O (overline), \o, \K (strike), \k
    s = re.sub(r"\\[LloOkK]", "", s)
    # Replace paragraph breaks with newline
    s = re.sub(r"\\[Pp]", "\n", s)
    # Replace non-breaking space
    s = re.sub(r"\\~", " ", s)
    # Strip curly braces grouping
    s = re.sub(r"[{}]", "", s)
    # Sanitize any unpaired surrogates
    s = sanitize_surrogates(s)
    return s.strip()

def resolve_entity_color(entity) -> Optional[str]:
    """
    Resolves entity color. Returns None if entity inherits BYLAYER (ACI 256 or default).
    Only returns an explicit Hex string if an intentional TrueColor or ACI override is present.
    Safely handles negative ACI colors (e.g. -7) without IndexError.
    """
    # 1. Explicit 24-bit TrueColor
    if hasattr(entity.dxf, "true_color") and entity.dxf.true_color is not None:
        tc = entity.dxf.true_color
        r = (tc >> 16) & 0xFF
        g = (tc >> 8) & 0xFF
        b = tc & 0xFF
        return f"#{r:02x}{g:02x}{b:02x}"

    # 2. ACI color code
    aci = getattr(entity.dxf, "color", 256)
    if aci is None or aci == 256:
        # BYLAYER: Do NOT hardcode hex color! Downstream tools inherit layer styling dynamically
        return None
    if aci == 0:
        # BYBLOCK: Inherits insertion block's color
        return "BYBLOCK"

    # Negative ACI codes denote layer turned OFF; map to absolute or None
    aci_abs = abs(aci)
    if 1 <= aci_abs <= 255:
        rgb = aci2rgb(aci_abs)
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
    
    return None

def resolve_aci_to_hex(aci: int) -> str:
    """Maps any of the 256 ACI colors to Hex for Layer definitions safely."""
    aci_abs = abs(aci)
    if 0 <= aci_abs <= 255:
        rgb = aci2rgb(aci_abs)
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
    return "#000000"

MAX_PHYSICAL_CAD_COORD = 1e7      # Standard CAD physical coordinate ceiling (10,000 km in mm)
MAX_EXTENTS_COORD = 1e15          # Defense-in-depth ceiling for bounds & transforms (rejects overflow residues >1e50 while admitting 1e12)
MIN_NONZERO_CAD_COORD = 1e-6     # Guards against subnormal uninitialized memory noise

def is_valid_coordinate_value(
    c: Any,
    max_coord: float = MAX_PHYSICAL_CAD_COORD,
    min_nonzero: float = MIN_NONZERO_CAD_COORD,
    **kwargs,
) -> bool:
    """
    Validates a single floating-point coordinate:
    1. Rejects None, bool, non-numeric types
    2. Rejects non-finite values (NaN, +Inf, -Inf) to prevent Pydantic null-serialization
    3. Rejects non-physical astronomical coordinates (|c| > max_coord)
    4. Rejects subnormal uninitialized buffer memory noise (|c| < min_nonzero when c != 0.0)
    """
    max_val = kwargs.get("max_val", max_coord)
    if c is None or isinstance(c, bool) or not isinstance(c, (int, float)):
        return False
    if not math.isfinite(c):
        return False
    if abs(c) > max_val:
        return False
    if c != 0.0 and abs(c) < min_nonzero:
        return False
    return True

def is_valid_coordinate_point(
    pt: Any,
    max_coord: float = MAX_PHYSICAL_CAD_COORD,
    min_nonzero: float = MIN_NONZERO_CAD_COORD,
    **kwargs,
) -> bool:
    """Validates that pt is a 2D coordinate pair [x, y] with valid physical coordinates."""
    if not isinstance(pt, (list, tuple)) or len(pt) < 2:
        return False
    return is_valid_coordinate_value(pt[0], max_coord, min_nonzero, **kwargs) and is_valid_coordinate_value(
        pt[1], max_coord, min_nonzero, **kwargs
    )

def sanitize_polyline_coordinates(
    raw_points: Sequence[Sequence[float]],
    is_closed: bool = False,
    max_coord: float = MAX_PHYSICAL_CAD_COORD,
    min_nonzero: float = MIN_NONZERO_CAD_COORD,
    **kwargs,
) -> List[List[float]]:
    """
    Sanitizes raw polyline vertex streams:
    - Filters out corrupted, non-finite, and out-of-bounds coordinates
    - Rounds clean coordinates to 3 decimal places
    - Deduplicates closing point if is_closed is True
    - Discards degenerate polylines with fewer than 2 valid points
    """
    max_val = kwargs.get("max_val", max_coord)
    clean_pts = []
    for p in raw_points:
        if not p or len(p) < 2:
            continue
        x, y = p[0], p[1]
        if is_valid_coordinate_value(x, max_val, min_nonzero) and is_valid_coordinate_value(
            y, max_val, min_nonzero
        ):
            clean_pts.append([round(float(x), 3), round(float(y), 3)])

    if len(clean_pts) >= 2 and is_closed:
        if math.dist(clean_pts[0], clean_pts[-1]) < 1e-4:
            clean_pts.pop()

    return clean_pts if len(clean_pts) >= 2 else []

def extract_entity_polyline_points(
    entity,
    flatten_distance: float = 1.0,
    max_coord: float = MAX_PHYSICAL_CAD_COORD,
) -> List[List[float]]:
    """
    Extracts 2D coordinate points from LWPOLYLINE or POLYLINE entities.
    Sanitizes and filters out non-physical floats (>1e7), NaNs, Infs, and subnormal noise.
    If the polyline contains curved bulge arc segments, it uses ezdxf.path to tessellate
    and flatten the true mathematical curves, preventing collapse into straight chords.
    """
    is_closed = bool(getattr(entity, "is_closed", False) or getattr(entity, "closed", False))

    if getattr(entity, "has_arc", False):
        try:
            path_obj = ezdxf.path.make_path(entity)
            raw_pts = [[pt.x, pt.y] for pt in path_obj.flattening(distance=flatten_distance)]
            clean_pts = sanitize_polyline_coordinates(raw_pts, is_closed=is_closed, max_coord=max_coord)
            if clean_pts:
                return clean_pts
        except Exception:
            pass

    if hasattr(entity, "get_points"):
        raw_pts = [p[:2] for p in entity.get_points()]
        return sanitize_polyline_coordinates(raw_pts, is_closed=is_closed, max_coord=max_coord)
    elif hasattr(entity, "vertices"):
        raw_pts = [[v.dxf.location.x, v.dxf.location.y] for v in entity.vertices]
        return sanitize_polyline_coordinates(raw_pts, is_closed=is_closed, max_coord=max_coord)
    return []

def resolve_entity_linetype(entity) -> Optional[str]:
    """
    Resolves entity-level linetype override.
    Returns None if the entity inherits BYLAYER (standard CAD default).
    Returns explicit linetype string (e.g. 'ACAD_ISO04W100', 'DASHED', 'BYBLOCK') when specified.
    """
    if not hasattr(entity, "dxf") or not entity.dxf.hasattr("linetype"):
        return None
    lt = entity.dxf.linetype
    if not lt:
        return None
    lt_clean = sanitize_surrogates(str(lt)).strip()
    if not lt_clean or lt_clean.upper() == "BYLAYER":
        return None
    if lt_clean.upper() == "BYBLOCK":
        return "BYBLOCK"
    return lt_clean

def update_bounds_with_component_geometry(
    comp_pos: Sequence[float],
    comp_scale: Sequence[float],
    comp_rotation: float,
    bdef: CADBlockDefinition,
    update_bounds_fn,
    max_coord: float = MAX_EXTENTS_COORD,
) -> bool:
    """
    Computes world-space extents for an INSERT component instance by transforming
    all geometric primitives inside its referenced CADBlockDefinition.
    
    Transformation:
      M = Translation(pos) * Rotation(rot) * Scale(s) * Translation(-base_point)
    Point mapping:
      X = a * x + c * y + tx
      Y = b * x + d * y + ty
    where:
      a = sx * cos(theta),  b = sx * sin(theta)
      c = -sy * sin(theta), d = sy * cos(theta)
      tx = px - (a * bx + c * by)
      ty = py - (b * bx + d * by)
    
    Returns True if at least one primitive updated the bounding box; False otherwise.
    """
    px = float(comp_pos[0]) if len(comp_pos) >= 1 else 0.0
    py = float(comp_pos[1]) if len(comp_pos) >= 2 else 0.0
    sx = float(comp_scale[0]) if len(comp_scale) >= 1 else 1.0
    sy = float(comp_scale[1]) if len(comp_scale) >= 2 else sx
    
    rot_rad = math.radians(float(comp_rotation or 0.0))
    cos_r = math.cos(rot_rad)
    sin_r = math.sin(rot_rad)
    
    bx = float(bdef.base_point[0]) if len(bdef.base_point) >= 1 else 0.0
    by = float(bdef.base_point[1]) if len(bdef.base_point) >= 2 else 0.0
    
    a = sx * cos_r
    b = sx * sin_r
    c = -sy * sin_r
    d = sy * cos_r
    tx = px - (a * bx + c * by)
    ty = py - (b * bx + d * by)

    def safe_update(x: float, y: float):
        if not is_valid_coordinate_value(x, max_coord=max_coord, min_nonzero=0.0) or not is_valid_coordinate_value(y, max_coord=max_coord, min_nonzero=0.0):
            return
        update_bounds_fn(x, y)

    has_geometry = False
    
    # 1. Lines
    for line in bdef.lines:
        has_geometry = True
        p1, p2 = line.start, line.end
        safe_update(a * p1[0] + c * p1[1] + tx, b * p1[0] + d * p1[1] + ty)
        safe_update(a * p2[0] + c * p2[1] + tx, b * p2[0] + d * p2[1] + ty)
        
    # 2. Polylines
    for poly in bdef.polylines:
        has_geometry = True
        for pt in poly.points:
            safe_update(a * pt[0] + c * pt[1] + tx, b * pt[0] + d * pt[1] + ty)
            
    # 3. Circles (closed-form ellipse extents)
    delta_x_mult = math.sqrt(a * a + c * c)
    delta_y_mult = math.sqrt(b * b + d * d)
    for circ in bdef.circles:
        has_geometry = True
        cc, cr = circ.center, circ.radius
        cx_t = a * cc[0] + c * cc[1] + tx
        cy_t = b * cc[0] + d * cc[1] + ty
        dx = cr * delta_x_mult
        dy = cr * delta_y_mult
        safe_update(cx_t - dx, cy_t - dy)
        safe_update(cx_t + dx, cy_t + dy)
        
    # 4. Arcs (sampling sweep)
    for arc in bdef.arcs:
        has_geometry = True
        ac, ar = arc.center, arc.radius
        sa = math.radians(arc.start_angle)
        ea = math.radians(arc.end_angle)
        if ea <= sa:
            ea += 2 * math.pi
        steps = 12
        sweep = ea - sa
        for i in range(steps + 1):
            ang = sa + sweep * (i / steps)
            lx = ac[0] + ar * math.cos(ang)
            ly = ac[1] + ar * math.sin(ang)
            safe_update(a * lx + c * ly + tx, b * lx + d * ly + ty)
            
    return has_geometry

def extract_solid_as_polyline(
    entity,
    layer_name: str,
    ent_color: Optional[str],
    space_name: str = "Model",
    linetype: Optional[str] = None,
    max_coord: float = MAX_PHYSICAL_CAD_COORD,
) -> Optional[CADPolyline]:
    """
    Converts DXF SOLID (and TRACE) filled polygons into a closed 3-point or 4-point CADPolyline.
    Handles DXF bowtie vertex ordering (0->1->3->2) via ezdxf's boundary-ordered vertices()/wcs_vertices().
    """
    try:
        if hasattr(entity, "wcs_vertices"):
            raw_pts = list(entity.wcs_vertices())
        elif hasattr(entity, "vertices"):
            raw_pts = list(entity.vertices())
        else:
            raw_pts = [entity.dxf.vtx0, entity.dxf.vtx1, entity.dxf.vtx2]
            if getattr(entity.dxf, "vtx3", None) != entity.dxf.vtx2:
                raw_pts.append(entity.dxf.vtx3)

        pts = []
        for p in raw_pts:
            x = float(p.x if hasattr(p, "x") else p[0])
            y = float(p.y if hasattr(p, "y") else p[1])
            if is_valid_coordinate_value(x, max_coord) and is_valid_coordinate_value(y, max_coord):
                pts.append([round(x, 3), round(y, 3)])

        if len(pts) >= 3:
            return CADPolyline(
                layer=layer_name,
                space=space_name,
                is_closed=True,
                points=pts,
                color=ent_color,
                linetype=linetype,
            )
    except Exception:
        pass
    return None

def extract_hatch_as_polylines(
    entity,
    layer_name: str,
    ent_color: Optional[str],
    space_name: str = "Model",
    linetype: Optional[str] = None,
    flatten_distance: float = 1.0,
    max_coord: float = MAX_PHYSICAL_CAD_COORD,
) -> List[CADPolyline]:
    """
    Extracts all boundary loops (outer perimeter + inner island holes) of a HATCH entity
    into closed CADPolyline primitives via ezdxf.path.from_hatch.
    """
    results = []
    try:
        for path_obj in ezdxf.path.from_hatch(entity):
            raw_pts = [[pt.x, pt.y] for pt in path_obj.flattening(distance=flatten_distance)]
            clean_pts = sanitize_polyline_coordinates(raw_pts, is_closed=True, max_coord=max_coord)
            if len(clean_pts) >= 3:
                results.append(
                    CADPolyline(
                        layer=layer_name,
                        space=space_name,
                        is_closed=True,
                        points=clean_pts,
                        color=ent_color,
                        linetype=linetype,
                    )
                )
    except Exception:
        pass
    return results

def extract_wipeout_as_polyline(
    entity,
    layer_name: str,
    ent_color: Optional[str],
    space_name: str = "Model",
    linetype: Optional[str] = None,
    max_coord: float = MAX_PHYSICAL_CAD_COORD,
) -> Optional[CADPolyline]:
    """
    Extracts WIPEOUT masking boundary vertices into a closed CADPolyline.
    Uses boundary_path_wcs() for true WCS geometry.
    """
    try:
        raw_pts = None
        if hasattr(entity, "boundary_path_wcs"):
            raw_pts = list(entity.boundary_path_wcs())
        if raw_pts:
            clean_pts = sanitize_polyline_coordinates(
                [[p.x if hasattr(p, "x") else p[0], p.y if hasattr(p, "y") else p[1]] for p in raw_pts],
                is_closed=True,
                max_coord=max_coord,
            )
            if len(clean_pts) >= 3:
                return CADPolyline(
                    layer=layer_name,
                    space=space_name,
                    is_closed=True,
                    points=clean_pts,
                    color=ent_color,
                    linetype=linetype,
                )
    except Exception:
        pass
    return None

def extract_point_as_circle(
    entity,
    layer_name: str,
    ent_color: Optional[str],
    space_name: str = "Model",
    linetype: Optional[str] = None,
    default_radius: float = 0.5,
    max_coord: float = MAX_PHYSICAL_CAD_COORD,
) -> Optional[CADCircle]:
    """
    Converts a POINT entity at (x, y) into a CADCircle with small radius (default 0.5)
    for seamless backward compatibility across all downstream renderers.
    """
    try:
        loc = entity.dxf.location
        x, y = float(loc.x), float(loc.y)
        if is_valid_coordinate_value(x, max_coord) and is_valid_coordinate_value(y, max_coord):
            return CADCircle(
                layer=layer_name,
                space=space_name,
                center=[round(x, 3), round(y, 3)],
                radius=default_radius,
                color=ent_color,
                linetype=linetype,
            )
    except Exception:
        pass
    return None

def find_dwg2dxf_binary() -> str:
    found = shutil.which("dwg2dxf")
    if found:
        return found
    local_win = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../../../experiments/libredwg/dwg2dxf.exe")
    )
    if os.path.exists(local_win):
        return local_win
    return "dwg2dxf"

def resolve_block_name(name: str, attributes: Dict[str, str]) -> str:
    """Resolves anonymous block handles (*U48, *B20) to human-meaningful names via attributes."""
    if not name.startswith("*"):
        return name
    for key in ["STYLE", "MANUFACTURER", "REF#", "SYM.", "TAG", "NAME"]:
        if key in attributes and attributes[key]:
            mfg = attributes.get("MANUFACTURER", "")
            style = attributes.get("STYLE", "")
            label = f"{mfg} {style}".strip() or attributes[key]
            return f"{label} ({name})"
    return name

MAX_BLOCK_DEPTH = 10
MAX_BLOCK_EXPANDED_ENTITIES = 100_000

def extract_block_definitions(doc) -> Dict[str, CADBlockDefinition]:
    """
    Extracts all block definitions (BLOCK_RECORD) and their internal geometry primitives.
    Hardened with:
    1. Single-pass raw entity extraction (parsing polylines/splines exactly once per block)
    2. Memoized hierarchical resolution (never re-resolves the same sub-assembly)
    3. Cycle detection preventing infinite recursion and combinatorial bloat
    4. Entity expansion quota per block (capped at MAX_BLOCK_EXPANDED_ENTITIES)
    5. Ingestion of SOLID, HATCH, WIPEOUT, POINT entities
    6. Preservation of entity-level linetypes
    """
    raw_blocks: Dict[str, Dict[str, Any]] = {}

    # Phase 1: Parse raw entities exactly once per block
    for block in doc.blocks:
        bname = block.name
        if bname.startswith("*Model") or bname.startswith("*Paper"):
            continue

        lines = []
        arcs = []
        circles = []
        polylines = []
        child_inserts = []

        for entity in block:
            etype = entity.dxftype()
            layer_name = getattr(entity.dxf, "layer", "0")
            ent_color = resolve_entity_color(entity)
            ent_linetype = resolve_entity_linetype(entity)

            if etype == "LINE":
                p1 = entity.dxf.start
                p2 = entity.dxf.end
                if (
                    is_valid_coordinate_point([p1.x, p1.y], max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)
                    and is_valid_coordinate_point([p2.x, p2.y], max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)
                ):
                    lines.append(
                        CADLine(
                            layer=layer_name,
                            space="Block",
                            start=[round(p1.x, 3), round(p1.y, 3)],
                            end=[round(p2.x, 3), round(p2.y, 3)],
                            color=ent_color,
                            linetype=ent_linetype,
                        )
                    )
            elif etype == "ARC":
                c = entity.dxf.center
                r = float(getattr(entity.dxf, "radius", 0.0))
                if (
                    is_valid_coordinate_point([c.x, c.y], max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)
                    and is_valid_coordinate_value(r, max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)
                    and r > 0
                ):
                    arcs.append(
                        CADArc(
                            layer=layer_name,
                            space="Block",
                            center=[round(c.x, 3), round(c.y, 3)],
                            radius=round(r, 3),
                            start_angle=round(entity.dxf.start_angle, 2),
                            end_angle=round(entity.dxf.end_angle, 2),
                            color=ent_color,
                            linetype=ent_linetype,
                        )
                    )
            elif etype == "CIRCLE":
                c = entity.dxf.center
                r = float(getattr(entity.dxf, "radius", 0.0))
                if (
                    is_valid_coordinate_point([c.x, c.y], max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)
                    and is_valid_coordinate_value(r, max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)
                    and r > 0
                ):
                    circles.append(
                        CADCircle(
                            layer=layer_name,
                            space="Block",
                            center=[round(c.x, 3), round(c.y, 3)],
                            radius=round(r, 3),
                            color=ent_color,
                            linetype=ent_linetype,
                        )
                    )
            elif etype in ("LWPOLYLINE", "POLYLINE"):
                pts = extract_entity_polyline_points(entity, flatten_distance=1.0)
                if pts:
                    is_closed = bool(getattr(entity, "is_closed", False) or getattr(entity, "closed", False))
                    polylines.append(
                        CADPolyline(
                            layer=layer_name,
                            space="Block",
                            is_closed=is_closed,
                            points=pts,
                            color=ent_color,
                            linetype=ent_linetype,
                        )
                    )
            elif etype in ("ELLIPSE", "SPLINE"):
                try:
                    raw_pts = [[p.x, p.y] for p in entity.flattening(distance=2.0)]
                    pts = sanitize_polyline_coordinates(raw_pts, is_closed=False)
                    if len(pts) >= 2:
                        is_closed = (math.dist(pts[0], pts[-1]) < 1e-4) or bool(getattr(entity, "closed", False))
                        polylines.append(
                            CADPolyline(
                                layer=layer_name,
                                space="Block",
                                is_closed=is_closed,
                                points=pts,
                                color=ent_color,
                                linetype=ent_linetype,
                            )
                        )
                except Exception:
                    pass
            elif etype in ("SOLID", "TRACE"):
                poly = extract_solid_as_polyline(entity, layer_name, ent_color, space_name="Block", linetype=ent_linetype)
                if poly:
                    polylines.append(poly)
            elif etype == "HATCH":
                h_polys = extract_hatch_as_polylines(entity, layer_name, ent_color, space_name="Block", linetype=ent_linetype)
                polylines.extend(h_polys)
            elif etype == "WIPEOUT":
                poly = extract_wipeout_as_polyline(entity, layer_name, ent_color, space_name="Block", linetype=ent_linetype)
                if poly:
                    polylines.append(poly)
            elif etype == "POINT":
                cir = extract_point_as_circle(entity, layer_name, ent_color, space_name="Block", linetype=ent_linetype)
                if cir:
                    circles.append(cir)
            elif etype == "INSERT":
                child_bname = getattr(entity.dxf, "name", "")
                if child_bname in doc.blocks and not (child_bname.startswith("*Model") or child_bname.startswith("*Paper")):
                    ip = entity.dxf.insert
                    rot = math.radians(getattr(entity.dxf, "rotation", 0.0))
                    sx = getattr(entity.dxf, "xscale", 1.0)
                    sy = getattr(entity.dxf, "yscale", 1.0)
                    child_inserts.append((child_bname, ip, rot, sx, sy))

        base_pt = getattr(block, "base_point", (0.0, 0.0, 0.0))
        raw_blocks[bname] = {
            "base_point": [round(base_pt[0], 3), round(base_pt[1], 3), round(base_pt[2], 3)],
            "lines": lines,
            "arcs": arcs,
            "circles": circles,
            "polylines": polylines,
            "child_inserts": child_inserts,
        }

    # Phase 2: Relative depth-budgeted hierarchical resolution with cycle detection
    resolved_cache: Dict[Tuple[str, int], Dict[str, List[Any]]] = {}

    def _resolve_block(bname: str, budget: int, active_path: Set[str]) -> Dict[str, List[Any]]:
        cache_key = (bname, budget)
        if cache_key in resolved_cache:
            return resolved_cache[cache_key]
        if bname in active_path or bname not in raw_blocks:
            return {"lines": [], "arcs": [], "circles": [], "polylines": []}

        active_path.add(bname)
        raw = raw_blocks[bname]

        lines = list(raw["lines"])
        arcs = list(raw["arcs"])
        circles = list(raw["circles"])
        polylines = list(raw["polylines"])

        total_entities = len(lines) + len(arcs) + len(circles) + len(polylines)

        if budget > 0:
            for child_bname, ip, rot, sx, sy in raw["child_inserts"]:
                if total_entities >= MAX_BLOCK_EXPANDED_ENTITIES:
                    break
                if child_bname not in raw_blocks:
                    continue

                child_geom = _resolve_block(child_bname, budget - 1, active_path)
                cos_r, sin_r = math.cos(rot), math.sin(rot)
                cbx = float(raw_blocks[child_bname]["base_point"][0]) if len(raw_blocks[child_bname]["base_point"]) >= 1 else 0.0
                cby = float(raw_blocks[child_bname]["base_point"][1]) if len(raw_blocks[child_bname]["base_point"]) >= 2 else 0.0

                def transform(x: float, y: float) -> List[float]:
                    dx = (x - cbx) * sx
                    dy = (y - cby) * sy
                    px = dx * cos_r - dy * sin_r + ip.x
                    py = dx * sin_r + dy * cos_r + ip.y
                    return [round(px, 3), round(py, 3)]

                for l in child_geom["lines"]:
                    tp1 = transform(l.start[0], l.start[1])
                    tp2 = transform(l.end[0], l.end[1])
                    if (
                        is_valid_coordinate_point(tp1, max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)
                        and is_valid_coordinate_point(tp2, max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)
                    ):
                        lines.append(
                            CADLine(
                                layer=l.layer,
                                space="Block",
                                start=tp1,
                                end=tp2,
                                color=l.color,
                                linetype=l.linetype,
                            )
                        )
                for c in child_geom["circles"]:
                    tc = transform(c.center[0], c.center[1])
                    if not is_valid_coordinate_point(tc, max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0):
                        continue
                    if abs(sx - sy) < 1e-5:
                        rad = round(c.radius * abs(sx), 3)
                        if is_valid_coordinate_value(rad, max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0) and rad > 0:
                            circles.append(
                                CADCircle(
                                    layer=c.layer,
                                    space="Block",
                                    center=tc,
                                    radius=rad,
                                    color=c.color,
                                    linetype=c.linetype,
                                )
                            )
                    else:
                        pts = [[round(c.center[0] + c.radius * math.cos(a), 3), round(c.center[1] + c.radius * math.sin(a), 3)] for a in [i * math.pi / 16 for i in range(33)]]
                        tpts = [transform(p[0], p[1]) for p in pts]
                        clean_tpts = [p for p in tpts if is_valid_coordinate_point(p, max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)]
                        if len(clean_tpts) >= 2:
                            polylines.append(
                                CADPolyline(
                                    layer=c.layer,
                                    space="Block",
                                    is_closed=True,
                                    points=clean_tpts,
                                    color=c.color,
                                    linetype=c.linetype,
                                )
                            )
                for pl in child_geom["polylines"]:
                    tpts = [transform(p[0], p[1]) for p in pl.points]
                    clean_tpts = [p for p in tpts if is_valid_coordinate_point(p, max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)]
                    if len(clean_tpts) >= 2:
                        polylines.append(
                            CADPolyline(
                                layer=pl.layer,
                                space="Block",
                                is_closed=pl.is_closed,
                                points=clean_tpts,
                                color=pl.color,
                                linetype=pl.linetype,
                            )
                        )
                for a in child_geom["arcs"]:
                    if abs(sx - sy) < 1e-5 and sx > 0:
                        new_c = transform(a.center[0], a.center[1])
                        rot_deg = math.degrees(rot)
                        rad = round(a.radius * sx, 3)
                        if (
                            is_valid_coordinate_point(new_c, max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)
                            and is_valid_coordinate_value(rad, max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)
                            and rad > 0
                        ):
                            arcs.append(
                                CADArc(
                                    layer=a.layer,
                                    space="Block",
                                    center=new_c,
                                    radius=rad,
                                    start_angle=round((a.start_angle + rot_deg) % 360, 2),
                                    end_angle=round((a.end_angle + rot_deg) % 360, 2),
                                    color=a.color,
                                    linetype=a.linetype,
                                )
                            )
                    else:
                        sa, ea = math.radians(a.start_angle), math.radians(a.end_angle)
                        if ea <= sa:
                            ea += 2 * math.pi
                        steps = max(8, int(abs(ea - sa) / (math.pi / 16)))
                        arc_pts = [[round(a.center[0] + a.radius * math.cos(sa + (ea - sa) * i / steps), 3), round(a.center[1] + a.radius * math.sin(sa + (ea - sa) * i / steps), 3)] for i in range(steps + 1)]
                        tpts = [transform(p[0], p[1]) for p in arc_pts]
                        clean_tpts = [p for p in tpts if is_valid_coordinate_point(p, max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)]
                        if len(clean_tpts) >= 2:
                            polylines.append(
                                CADPolyline(
                                    layer=a.layer,
                                    space="Block",
                                    is_closed=False,
                                    points=clean_tpts,
                                    color=a.color,
                                    linetype=a.linetype,
                                )
                            )

                total_entities = len(lines) + len(arcs) + len(circles) + len(polylines)

        active_path.remove(bname)
        res = {"lines": lines, "arcs": arcs, "circles": circles, "polylines": polylines}
        resolved_cache[cache_key] = res
        return res

    block_defs = {}
    for bname, raw in raw_blocks.items():
        geom = _resolve_block(bname, budget=MAX_BLOCK_DEPTH, active_path=set())
        block_defs[bname] = CADBlockDefinition(
            name=bname,
            base_point=raw["base_point"],
            lines=geom["lines"],
            arcs=geom["arcs"],
            circles=geom["circles"],
            polylines=geom["polylines"],
        )

    return block_defs

def extract_cad_ir(input_path: str, dwg2dxf_binary: Optional[str] = None) -> CADIntermediateRepresentation:
    """
    Primary extraction entry point.
    Accepts both .dwg and .dxf files natively.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"CAD drawing not found: {input_path}")

    # Dual-Format Dispatcher: Direct DXF vs DWG
    is_dxf = input_path.lower().endswith(".dxf")
    if not is_dxf:
        # Check magic bytes in case filename lacks extension
        try:
            with open(input_path, "rb") as f:
                header_bytes = f.read(10)
                if b"SECTION" in header_bytes or header_bytes.startswith(b"0\n"):
                    is_dxf = True
        except Exception:
            pass

    if is_dxf:
        # Native direct DXF parsing (FM-01 resolved)
        try:
            doc = ezdxf.readfile(input_path)
        except Exception as e:
            raise RuntimeError(f"Failed to parse native DXF file: {str(e)}") from e
        return _process_dxf_document(doc, os.path.basename(input_path))

    # Binary DWG Ingestion via LibreDWG
    exe = dwg2dxf_binary or find_dwg2dxf_binary()

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_dxf = os.path.join(tmpdir, "intermediate.dxf")
        cmd = [exe, "-y", os.path.abspath(input_path), "-o", temp_dxf]
        
        try:
            # Subprocess Timeout Protection (FM-02 resolved)
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(f"LibreDWG conversion timed out after 120 seconds on: {input_path}") from e

        # Strict error check: if exit code != 0, fail cleanly (FM-04 resolved)
        if proc.returncode != 0 or not os.path.exists(temp_dxf):
            # Fallback to minimal mode (-m) for complex/corrupted DWG files
            proc_min = subprocess.run([exe, "-y", "-m", os.path.abspath(input_path), "-o", temp_dxf], capture_output=True, text=True, timeout=120)
            if proc_min.returncode != 0 or not os.path.exists(temp_dxf):
                raise RuntimeError(f"Underlying LibreDWG parser failed: {proc.stderr or proc.stdout}")

        try:
            doc = ezdxf.readfile(temp_dxf)
        except Exception as e:
            # Fallback to minimal mode (-m) if full DXF tables/classes have parsing errors
            try:
                proc_min = subprocess.run([exe, "-y", "-m", os.path.abspath(input_path), "-o", temp_dxf], capture_output=True, text=True, timeout=120)
                if proc_min.returncode == 0 and os.path.exists(temp_dxf):
                    doc = ezdxf.readfile(temp_dxf)
                else:
                    raise e
            except Exception:
                raise RuntimeError(f"Failed to read converted DXF from DWG: {str(e)}") from e

        return _process_dxf_document(doc, os.path.basename(input_path))

def _process_dxf_document(doc, source_file: str) -> CADIntermediateRepresentation:
    """Extracts LAVINCI_CAD_IR_V3 from an active ezdxf drawing document."""
    header = doc.header

    metadata = CADMetadata(
        source_file=source_file,
        dxf_version=str(getattr(doc, "dxfversion", "AC1015")),
        cad_version=str(getattr(doc, "acad_release", "Unknown")),
        units=int(header.get("$INSUNITS", 0) or 0),
        measurement_system="Metric" if header.get("$MEASUREMENT", 1) == 1 else "Imperial",
        author=sanitize_surrogates(str(header.get("$LOGINNAME", "Unknown"))),
    )

    # Build Layer Table
    layers = []
    for layer in doc.layers:
        aci_color = layer.color
        hex_col = resolve_aci_to_hex(aci_color)
        layers.append(
            CADLayer(
                name=sanitize_surrogates(layer.dxf.name),
                color_aci=aci_color,
                hex_color=hex_col,
                is_off=layer.is_off(),
                is_locked=layer.is_locked(),
                is_frozen=layer.is_frozen(),
                linetype=getattr(layer.dxf, "linetype", "Continuous")
            )
        )

    # Extract Block Definitions
    block_definitions = extract_block_definitions(doc)

    # Extract Layouts & Viewports (Paper Space)
    layouts = []
    for l in doc.layouts:
        if l.name == "Model":
            continue
        viewports = []
        for e in l:
            if e.dxftype() == "VIEWPORT":
                cp = getattr(e.dxf, "center", (0, 0, 0))
                w = getattr(e.dxf, "width", 0.0)
                h = getattr(e.dxf, "height", 0.0)
                vh = getattr(e.dxf, "view_height", 0.0)
                viewports.append(
                    CADViewport(
                        center=[round(cp[0], 3), round(cp[1], 3)],
                        width=round(w, 3) if w is not None else 0.0,
                        height=round(h, 3) if h is not None else 0.0,
                        view_height=round(vh, 3) if vh is not None else None,
                        status=getattr(e.dxf, "status", 0)
                    )
                )
        layouts.append(
            CADLayout(
                name=sanitize_surrogates(l.name),
                is_active=(l.name == doc.header.get("$CTAB", "")),
                viewports=viewports
            )
        )

    # Collect entities from ALL spaces (Model space + Paper space layouts)
    spaces_to_scan = [("Model", doc.modelspace())]
    for l in doc.layouts:
        if l.name != "Model":
            spaces_to_scan.append((l.name, l))

    block_counts = Counter()
    components = []
    annotations = []
    dimensions = []
    lines = []
    arcs = []
    circles = []
    polylines = []

    min_x, min_y = float("inf"), float("inf")
    max_x, max_y = float("-inf"), float("-inf")

    def update_bounds(x: float, y: float):
        nonlocal min_x, min_y, max_x, max_y
        if not is_valid_coordinate_value(x, max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0) or not is_valid_coordinate_value(y, max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0):
            return
        if x < min_x: min_x = x
        if y < min_y: min_y = y
        if x > max_x: max_x = x
        if y > max_y: max_y = y

    for space_name, space in spaces_to_scan:
        for entity in space:
            etype = entity.dxftype()
            layer_name = sanitize_surrogates(getattr(entity.dxf, "layer", "0"))
            ent_color = resolve_entity_color(entity)
            ent_linetype = resolve_entity_linetype(entity)

            if etype == "INSERT":
                raw_bname = getattr(entity.dxf, "name", "")
                ip = entity.dxf.insert
                rot = getattr(entity.dxf, "rotation", 0.0)
                sx = getattr(entity.dxf, "xscale", 1.0)
                sy = getattr(entity.dxf, "yscale", 1.0)

                # Feature 2: True Composite Bounding Box Extents Calculation
                bdef = block_definitions.get(raw_bname)
                if bdef:
                    has_geom = update_bounds_with_component_geometry(
                        comp_pos=(ip.x, ip.y),
                        comp_scale=(sx, sy),
                        comp_rotation=rot,
                        bdef=bdef,
                        update_bounds_fn=update_bounds,
                    )
                    if not has_geom:
                        update_bounds(ip.x, ip.y)
                else:
                    update_bounds(ip.x, ip.y)

                # Extract block attributes (ATTRIB)
                attrib_dict = {}
                if hasattr(entity, "attribs"):
                    for a in entity.attribs:
                        if hasattr(a.dxf, "tag") and hasattr(a.dxf, "text"):
                            tag_clean = sanitize_surrogates(a.dxf.tag)
                            text_clean = clean_cad_text(a.dxf.text)
                            attrib_dict[tag_clean] = text_clean

                # Resolve anonymous block names
                resolved_bname = resolve_block_name(raw_bname, attrib_dict)
                block_counts[resolved_bname] += 1

                components.append(
                    CADComponentInstance(
                        block_name=raw_bname,
                        resolved_name=resolved_bname,
                        layer=layer_name,
                        space=space_name,
                        position=[round(ip.x, 3), round(ip.y, 3), round(ip.z, 3)],
                        rotation=round(getattr(entity.dxf, "rotation", 0.0), 2),
                        scale=[
                            round(getattr(entity.dxf, "xscale", 1.0), 3),
                            round(getattr(entity.dxf, "yscale", 1.0), 3),
                            round(getattr(entity.dxf, "zscale", 1.0), 3)
                        ],
                        attributes=attrib_dict
                    )
                )

            elif etype == "LINE":
                p1 = entity.dxf.start
                p2 = entity.dxf.end
                if (
                    is_valid_coordinate_point([p1.x, p1.y], max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)
                    and is_valid_coordinate_point([p2.x, p2.y], max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)
                ):
                    update_bounds(p1.x, p1.y)
                    update_bounds(p2.x, p2.y)
                    lines.append(
                        CADLine(
                            layer=layer_name,
                            space=space_name,
                            start=[round(p1.x, 3), round(p1.y, 3)],
                            end=[round(p2.x, 3), round(p2.y, 3)],
                            color=ent_color,
                            linetype=ent_linetype,
                        )
                    )

            elif etype == "ARC":
                c = entity.dxf.center
                r = float(getattr(entity.dxf, "radius", 0.0))
                if (
                    is_valid_coordinate_point([c.x, c.y], max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)
                    and is_valid_coordinate_value(r, max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)
                    and r > 0
                ):
                    # Robust Arc Bounding Box including radius (FM-06 resolved)
                    update_bounds(c.x - r, c.y - r)
                    update_bounds(c.x + r, c.y + r)
                    arcs.append(
                        CADArc(
                            layer=layer_name,
                            space=space_name,
                            center=[round(c.x, 3), round(c.y, 3)],
                            radius=round(r, 3),
                            start_angle=round(entity.dxf.start_angle, 2),
                            end_angle=round(entity.dxf.end_angle, 2),
                            color=ent_color,
                            linetype=ent_linetype,
                        )
                    )

            elif etype == "CIRCLE":
                c = entity.dxf.center
                r = float(getattr(entity.dxf, "radius", 0.0))
                if (
                    is_valid_coordinate_point([c.x, c.y], max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)
                    and is_valid_coordinate_value(r, max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0)
                    and r > 0
                ):
                    # Robust Circle Bounding Box including radius (FM-06 resolved)
                    update_bounds(c.x - r, c.y - r)
                    update_bounds(c.x + r, c.y + r)
                    circles.append(
                        CADCircle(
                            layer=layer_name,
                            space=space_name,
                            center=[round(c.x, 3), round(c.y, 3)],
                            radius=round(r, 3),
                            color=ent_color,
                            linetype=ent_linetype,
                        )
                    )

            elif etype in ("LWPOLYLINE", "POLYLINE"):
                pts = extract_entity_polyline_points(entity, flatten_distance=1.0)
                if pts:
                    for px, py in pts:
                        update_bounds(px, py)
                    is_closed = bool(getattr(entity, "is_closed", False) or getattr(entity, "closed", False))
                    polylines.append(
                        CADPolyline(
                            layer=layer_name,
                            space=space_name,
                            is_closed=is_closed,
                            points=pts,
                            color=ent_color,
                            linetype=ent_linetype,
                        )
                    )

            elif etype in ("ELLIPSE", "SPLINE"):
                try:
                    raw_pts = [[p.x, p.y] for p in entity.flattening(distance=2.0)]
                    pts = sanitize_polyline_coordinates(raw_pts, is_closed=False)
                    if len(pts) >= 2:
                        for px, py in pts:
                            update_bounds(px, py)
                        is_closed = (math.dist(pts[0], pts[-1]) < 1e-4) or bool(getattr(entity, "closed", False))
                        polylines.append(
                            CADPolyline(
                                layer=layer_name,
                                space=space_name,
                                is_closed=is_closed,
                                points=pts,
                                color=ent_color,
                                linetype=ent_linetype,
                            )
                        )
                except Exception:
                    pass

            elif etype in ("SOLID", "TRACE"):
                poly = extract_solid_as_polyline(entity, layer_name, ent_color, space_name=space_name, linetype=ent_linetype)
                if poly:
                    for px, py in poly.points:
                        update_bounds(px, py)
                    polylines.append(poly)

            elif etype == "HATCH":
                h_polys = extract_hatch_as_polylines(entity, layer_name, ent_color, space_name=space_name, linetype=ent_linetype)
                for poly in h_polys:
                    for px, py in poly.points:
                        update_bounds(px, py)
                    polylines.append(poly)

            elif etype == "WIPEOUT":
                poly = extract_wipeout_as_polyline(entity, layer_name, ent_color, space_name=space_name, linetype=ent_linetype)
                if poly:
                    for px, py in poly.points:
                        update_bounds(px, py)
                    polylines.append(poly)

            elif etype == "POINT":
                cir = extract_point_as_circle(entity, layer_name, ent_color, space_name=space_name, linetype=ent_linetype)
                if cir:
                    update_bounds(cir.center[0] - cir.radius, cir.center[1] - cir.radius)
                    update_bounds(cir.center[0] + cir.radius, cir.center[1] + cir.radius)
                    circles.append(cir)

            elif etype in ("TEXT", "MTEXT"):
                pos = entity.dxf.insert
                if is_valid_coordinate_point([pos.x, pos.y], max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0):
                    update_bounds(pos.x, pos.y)
                raw_text = entity.text if etype == "MTEXT" else getattr(entity.dxf, "text", "")
                raw_text_safe = sanitize_surrogates(str(raw_text or ""))
                clean_text = clean_cad_text(raw_text_safe)
                h = getattr(entity.dxf, "char_height" if etype == "MTEXT" else "height", 1.0)
                annotations.append(
                    CADAnnotation(
                        type=etype,
                        layer=layer_name,
                        space=space_name,
                        raw_text=raw_text_safe,
                        clean_text=clean_text,
                        position=[round(pos.x, 3), round(pos.y, 3)],
                        height=round(h, 2) if h is not None else 1.0
                    )
                )

            elif "DIMENSION" in etype:
                dp = getattr(entity.dxf, "defpoint", (0, 0, 0))
                dp2 = getattr(entity.dxf, "defpoint2", None)
                meas = getattr(entity.dxf, "actual_measurement", None)
                dim_text = clean_cad_text(getattr(entity.dxf, "text", ""))
                
                tm = getattr(entity.dxf, "text_midpoint", None)
                text_h = getattr(entity.dxf, "text_height", None) or getattr(entity.dxf, "char_height", None)
                text_rot = getattr(entity.dxf, "text_rotation", None)

                # Fallback to anonymous dimension block (*D...) MTEXT if needed
                geom_name = getattr(entity.dxf, "geometry", None)
                if (not dim_text or text_h is None or tm is None) and geom_name and geom_name in doc.blocks:
                    for sub in doc.blocks[geom_name]:
                        if sub.dxftype() == "MTEXT":
                            if not dim_text:
                                dim_text = clean_cad_text(sub.text)
                            if text_h is None:
                                text_h = getattr(sub.dxf, "char_height", None)
                            if tm is None:
                                tm = getattr(sub.dxf, "insert", None)
                            if text_rot is None:
                                text_rot = getattr(sub.dxf, "rotation", None)
                            break

                # Robust Dimension Bounding Box updating defpoint AND defpoint2 (FM-05 resolved)
                if is_valid_coordinate_point([dp[0], dp[1]], max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0):
                    update_bounds(dp[0], dp[1])
                if dp2 is not None and is_valid_coordinate_point([dp2[0], dp2[1]], max_coord=MAX_EXTENTS_COORD, min_nonzero=0.0):
                    update_bounds(dp2[0], dp2[1])

                tm_list = None
                if tm is not None and len(tm) >= 2 and math.isfinite(tm[0]) and math.isfinite(tm[1]):
                    tm_list = [round(float(tm[0]), 3), round(float(tm[1]), 3)]

                safe_h = round(float(text_h), 2) if (text_h is not None and math.isfinite(text_h) and text_h > 0) else None
                safe_rot = round(float(text_rot), 2) if (text_rot is not None and math.isfinite(text_rot)) else None

                dimensions.append(
                    CADDimension(
                        type=etype,
                        layer=layer_name,
                        space=space_name,
                        measurement=round(meas, 3) if meas is not None else None,
                        text=dim_text,
                        defpoint=[round(dp[0], 3), round(dp[1], 3)],
                        defpoint2=[round(dp2[0], 3), round(dp2[1], 3)] if dp2 else None,
                        text_midpoint=tm_list,
                        text_height=safe_h,
                        text_rotation=safe_rot,
                    )
                )

    extents = CADExtents(
        min=[round(min_x, 3), round(min_y, 3)] if min_x != float("inf") else [0.0, 0.0],
        max=[round(max_x, 3), round(max_y, 3)] if max_x != float("-inf") else [0.0, 0.0],
        width=round(max_x - min_x, 3) if max_x != float("-inf") else 0.0,
        height=round(max_y - min_y, 3) if max_y != float("-inf") else 0.0,
    )

    geometry = CADGeometry(
        summary=CADPrimitiveSummary(
            total_lines=len(lines),
            total_arcs=len(arcs),
            total_circles=len(circles),
            total_polylines=len(polylines),
            total_components=len(components),
            total_annotations=len(annotations),
            total_dimensions=len(dimensions),
            total_block_definitions=len(block_definitions),
        ),
        primitives=CADPrimitives(
            lines=lines,
            arcs=arcs,
            circles=circles,
            polylines=polylines,
        )
    )

    return CADIntermediateRepresentation(
        format="LAVINCI_CAD_IR_V3",
        metadata=metadata,
        extents=extents,
        layouts=layouts,
        layers=layers,
        bill_of_materials=dict(block_counts.most_common()),
        block_definitions=block_definitions,
        annotations=annotations,
        dimensions=dimensions,
        components=components,
        geometry_primitives=geometry,
    )
