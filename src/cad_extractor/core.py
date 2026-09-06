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
from typing import Dict, Any, List, Optional, Tuple

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

def extract_entity_polyline_points(entity, flatten_distance: float = 1.0) -> List[List[float]]:
    """
    Extracts 2D coordinate points from LWPOLYLINE or POLYLINE entities.
    If the polyline contains curved bulge arc segments, it uses ezdxf.path to tessellate
    and flatten the true mathematical curves, preventing collapse into straight chords.
    """
    if getattr(entity, "has_arc", False):
        try:
            path_obj = ezdxf.path.make_path(entity)
            pts = [[round(float(pt.x), 3), round(float(pt.y), 3)] for pt in path_obj.flattening(distance=flatten_distance)]
            is_closed = bool(getattr(entity, "is_closed", False) or getattr(entity, "closed", False))
            if len(pts) >= 2 and is_closed:
                if math.dist(pts[0], pts[-1]) < 1e-4:
                    pts.pop()
            if pts:
                return pts
        except Exception:
            pass

    if hasattr(entity, "get_points"):
        return [[round(float(p[0]), 3), round(float(p[1]), 3)] for p in entity.get_points()]
    elif hasattr(entity, "vertices"):
        return [[round(float(v.dxf.location.x), 3), round(float(v.dxf.location.y), 3)] for v in entity.vertices]
    return []

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

def extract_block_definitions(doc) -> Dict[str, CADBlockDefinition]:
    """
    Extracts all block definitions (BLOCK_RECORD) and their internal geometry primitives.
    Recursively resolves nested blocks (blocks inside blocks) and converts ELLIPSE
    and SPLINE entities into high-fidelity vector representations.
    Ignores root model space (*Model_Space) and paper space (*Paper_Space).
    """
    def _extract_single_block_geometry(block_obj, depth: int = 0) -> Dict[str, List[Any]]:
        if depth > 10:
            return {"lines": [], "arcs": [], "circles": [], "polylines": []}

        lines = []
        arcs = []
        circles = []
        polylines = []

        for entity in block_obj:
            etype = entity.dxftype()
            layer_name = getattr(entity.dxf, "layer", "0")
            ent_color = resolve_entity_color(entity)

            if etype == "LINE":
                p1 = entity.dxf.start
                p2 = entity.dxf.end
                lines.append(
                    CADLine(
                        layer=layer_name,
                        space="Block",
                        start=[round(p1.x, 3), round(p1.y, 3)],
                        end=[round(p2.x, 3), round(p2.y, 3)],
                        color=ent_color,
                    )
                )
            elif etype == "ARC":
                c = entity.dxf.center
                arcs.append(
                    CADArc(
                        layer=layer_name,
                        space="Block",
                        center=[round(c.x, 3), round(c.y, 3)],
                        radius=round(entity.dxf.radius, 3),
                        start_angle=round(entity.dxf.start_angle, 2),
                        end_angle=round(entity.dxf.end_angle, 2),
                        color=ent_color,
                    )
                )
            elif etype == "CIRCLE":
                c = entity.dxf.center
                circles.append(
                    CADCircle(
                        layer=layer_name,
                        space="Block",
                        center=[round(c.x, 3), round(c.y, 3)],
                        radius=round(entity.dxf.radius, 3),
                        color=ent_color,
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
                        )
                    )
            elif etype in ("ELLIPSE", "SPLINE"):
                try:
                    pts = [[round(p.x, 3), round(p.y, 3)] for p in entity.flattening(distance=2.0)]
                    if len(pts) >= 2:
                        is_closed = (math.dist(pts[0], pts[-1]) < 1e-4) or bool(getattr(entity, "closed", False))
                        polylines.append(
                            CADPolyline(
                                layer=layer_name,
                                space="Block",
                                is_closed=is_closed,
                                points=pts,
                                color=ent_color,
                            )
                        )
                except Exception:
                    pass
            elif etype == "INSERT":
                # Handle nested block references inside this block!
                child_bname = entity.dxf.name
                if child_bname in doc.blocks and not (child_bname.startswith("*Model") or child_bname.startswith("*Paper")):
                    child_geom = _extract_single_block_geometry(doc.blocks[child_bname], depth + 1)
                    ip = entity.dxf.insert
                    rot = math.radians(getattr(entity.dxf, "rotation", 0.0))
                    sx = getattr(entity.dxf, "xscale", 1.0)
                    sy = getattr(entity.dxf, "yscale", 1.0)
                    cos_r, sin_r = math.cos(rot), math.sin(rot)

                    def transform(x: float, y: float) -> List[float]:
                        tx, ty = x * sx, y * sy
                        return [round(tx * cos_r - ty * sin_r + ip.x, 3), round(tx * sin_r + ty * cos_r + ip.y, 3)]

                    for l in child_geom["lines"]:
                        lines.append(
                            CADLine(
                                layer=l.layer,
                                space="Block",
                                start=transform(l.start[0], l.start[1]),
                                end=transform(l.end[0], l.end[1]),
                                color=l.color,
                            )
                        )
                    for c in child_geom["circles"]:
                        if abs(sx - sy) < 1e-5:
                            circles.append(
                                CADCircle(
                                    layer=c.layer,
                                    space="Block",
                                    center=transform(c.center[0], c.center[1]),
                                    radius=round(c.radius * abs(sx), 3),
                                    color=c.color,
                                )
                            )
                        else:
                            pts = [[round(c.center[0] + c.radius * math.cos(a), 3), round(c.center[1] + c.radius * math.sin(a), 3)] for a in [i * math.pi / 16 for i in range(33)]]
                            polylines.append(
                                CADPolyline(
                                    layer=c.layer,
                                    space="Block",
                                    is_closed=True,
                                    points=[transform(p[0], p[1]) for p in pts],
                                    color=c.color,
                                )
                            )
                    for pl in child_geom["polylines"]:
                        polylines.append(
                            CADPolyline(
                                layer=pl.layer,
                                space="Block",
                                is_closed=pl.is_closed,
                                points=[transform(p[0], p[1]) for p in pl.points],
                                color=pl.color,
                            )
                        )
                    for a in child_geom["arcs"]:
                        if abs(sx - sy) < 1e-5 and sx > 0:
                            new_c = transform(a.center[0], a.center[1])
                            rot_deg = math.degrees(rot)
                            arcs.append(
                                CADArc(
                                    layer=a.layer,
                                    space="Block",
                                    center=new_c,
                                    radius=round(a.radius * sx, 3),
                                    start_angle=round((a.start_angle + rot_deg) % 360, 2),
                                    end_angle=round((a.end_angle + rot_deg) % 360, 2),
                                    color=a.color,
                                )
                            )
                        else:
                            sa, ea = math.radians(a.start_angle), math.radians(a.end_angle)
                            if ea <= sa:
                                ea += 2 * math.pi
                            steps = max(8, int(abs(ea - sa) / (math.pi / 16)))
                            arc_pts = [[round(a.center[0] + a.radius * math.cos(sa + (ea - sa) * i / steps), 3), round(a.center[1] + a.radius * math.sin(sa + (ea - sa) * i / steps), 3)] for i in range(steps + 1)]
                            polylines.append(
                                CADPolyline(
                                    layer=a.layer,
                                    space="Block",
                                    is_closed=False,
                                    points=[transform(p[0], p[1]) for p in arc_pts],
                                    color=a.color,
                                )
                            )

        return {"lines": lines, "arcs": arcs, "circles": circles, "polylines": polylines}

    block_defs = {}
    for block in doc.blocks:
        bname = block.name
        if bname.startswith("*Model") or bname.startswith("*Paper"):
            continue

        base_pt = getattr(block, "base_point", (0.0, 0.0, 0.0))
        geom = _extract_single_block_geometry(block, depth=0)

        block_defs[bname] = CADBlockDefinition(
            name=bname,
            base_point=[round(base_pt[0], 3), round(base_pt[1], 3), round(base_pt[2], 3)],
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
        if proc.returncode != 0:
            raise RuntimeError(f"Underlying LibreDWG parser failed: {proc.stderr or proc.stdout}")

        if not os.path.exists(temp_dxf):
            raise RuntimeError(f"LibreDWG failed to generate intermediate DXF file: {proc.stderr or proc.stdout}")

        try:
            doc = ezdxf.readfile(temp_dxf)
        except Exception as e:
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
        # Protect against NaN and Inf (FM-12 resolved)
        if math.isnan(x) or math.isnan(y) or math.isinf(x) or math.isinf(y):
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

            if etype == "INSERT":
                raw_bname = getattr(entity.dxf, "name", "")
                ip = entity.dxf.insert
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
                update_bounds(p1.x, p1.y)
                update_bounds(p2.x, p2.y)
                lines.append(
                    CADLine(
                        layer=layer_name,
                        space=space_name,
                        start=[round(p1.x, 3), round(p1.y, 3)],
                        end=[round(p2.x, 3), round(p2.y, 3)],
                        color=ent_color,
                    )
                )

            elif etype == "ARC":
                c = entity.dxf.center
                r = float(getattr(entity.dxf, "radius", 0.0))
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
                    )
                )

            elif etype == "CIRCLE":
                c = entity.dxf.center
                r = float(getattr(entity.dxf, "radius", 0.0))
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
                        )
                    )

            elif etype in ("ELLIPSE", "SPLINE"):
                try:
                    pts = [[round(p.x, 3), round(p.y, 3)] for p in entity.flattening(distance=2.0)]
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
                            )
                        )
                except Exception:
                    pass

            elif etype in ("TEXT", "MTEXT"):
                pos = entity.dxf.insert
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
                
                # Robust Dimension Bounding Box updating defpoint AND defpoint2 (FM-05 resolved)
                update_bounds(dp[0], dp[1])
                if dp2 is not None:
                    update_bounds(dp2[0], dp2[1])

                dimensions.append(
                    CADDimension(
                        type=etype,
                        layer=layer_name,
                        space=space_name,
                        measurement=round(meas, 3) if meas is not None else None,
                        text=dim_text,
                        defpoint=[round(dp[0], 3), round(dp[1], 3)],
                        defpoint2=[round(dp2[0], 3), round(dp2[1], 3)] if dp2 else None
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
