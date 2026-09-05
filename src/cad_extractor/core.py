"""
Core Extraction Engine (v2 Hardened).
Extracts AutoCAD DWG files into the standardized La Vinci CAD IR v2:
- Full 256 ACI Palette + 24-bit TrueColor
- Both Model Space AND Paper Space (Layouts & Viewports)
- Block Attribute (`ATTRIB`) extraction for real-world BIM data
- Anonymous block resolution
- DIMENSION entity extraction
- Clean MTEXT escape-code sanitization
"""

import os
import re
import shutil
import tempfile
import subprocess
from collections import Counter
from typing import Dict, Any, List, Optional, Tuple

import ezdxf
from ezdxf.colors import aci2rgb

from .models import (
    CADIntermediateRepresentation,
    CADMetadata,
    CADExtents,
    CADLayout,
    CADViewport,
    CADLayer,
    CADComponentInstance,
    CADAnnotation,
    CADDimension,
    CADLine,
    CADArc,
    CADPolyline,
    CADPrimitives,
    CADPrimitiveSummary,
    CADGeometry,
)

def clean_cad_text(text: str) -> str:
    r"""Strips AutoCAD MTEXT formatting tags (\f..., \H..., \P, \C..., underline \L\l, braces)."""
    if not text:
        return ""
    # Strip parameter blocks ending in semicolon (\H...; \f...; \C...; \A...; \W...; \Q...; \T...;)
    s = re.sub(r"\\[HhFfCcAaWwQqTt][^;]*;", "", text)
    # Strip inline mode toggles: \L (underline on), \l (underline off), \O (overline), \o, \K (strike), \k
    s = re.sub(r"\\[LloOkK]", "", s)
    # Replace paragraph breaks with newline
    s = re.sub(r"\\[Pp]", "\n", s)
    # Replace non-breaking space
    s = re.sub(r"\\~", " ", s)
    # Strip curly braces grouping
    s = re.sub(r"[{}]", "", s)
    return s.strip()

def resolve_entity_color(entity, layer_color_map: Dict[str, str]) -> str:
    """Resolves entity color using TrueColor (24-bit RGB), ACI 1-255, or ByLayer inheritance."""
    # 1. 24-bit TrueColor
    if hasattr(entity.dxf, "true_color") and entity.dxf.true_color is not None:
        tc = entity.dxf.true_color
        r = (tc >> 16) & 0xFF
        g = (tc >> 8) & 0xFF
        b = tc & 0xFF
        return f"#{r:02x}{g:02x}{b:02x}"

    # 2. ACI color code
    aci = getattr(entity.dxf, "color", 256)
    if aci == 256:  # ByLayer
        layer_name = entity.dxf.layer
        return layer_color_map.get(layer_name, "#000000")
    if aci == 0:    # ByBlock
        return "#777777"
    
    rgb = aci2rgb(aci)
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

def resolve_aci_to_hex(aci: int) -> str:
    """Maps any of the 256 ACI colors to Hex."""
    if 0 <= aci <= 255:
        rgb = aci2rgb(aci)
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
    return "#000000"

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
    # Check attributes for common identifier keys
    for key in ["STYLE", "MANUFACTURER", "REF#", "SYM.", "TAG", "NAME"]:
        if key in attributes and attributes[key]:
            mfg = attributes.get("MANUFACTURER", "")
            style = attributes.get("STYLE", "")
            label = f"{mfg} {style}".strip() or attributes[key]
            return f"{label} ({name})"
    return name

def extract_cad_ir(dwg_path: str, dwg2dxf_binary: Optional[str] = None) -> CADIntermediateRepresentation:
    if not os.path.exists(dwg_path):
        raise FileNotFoundError(f"CAD drawing not found: {dwg_path}")

    exe = dwg2dxf_binary or find_dwg2dxf_binary()

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_dxf = os.path.join(tmpdir, "intermediate.dxf")
        cmd = [exe, "-y", os.path.abspath(dwg_path), "-o", temp_dxf]
        
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 and not os.path.exists(temp_dxf):
            raise RuntimeError(f"Underlying LibreDWG parser failed: {proc.stderr or proc.stdout}")

        doc = ezdxf.readfile(temp_dxf)
        header = doc.header

        metadata = CADMetadata(
            source_file=os.path.basename(dwg_path),
            dxf_version=str(doc.dxfversion),
            cad_version=str(doc.acad_release),
            units=header.get("$INSUNITS", 0),
            measurement_system="Metric" if header.get("$MEASUREMENT", 1) == 1 else "Imperial",
            author=header.get("$LOGINNAME", "Unknown"),
        )

        # Build Layer Table & Color Map
        layers = []
        layer_color_map = {}
        for layer in doc.layers:
            aci_color = layer.color
            hex_col = resolve_aci_to_hex(aci_color)
            layer_color_map[layer.dxf.name] = hex_col
            layers.append(
                CADLayer(
                    name=layer.dxf.name,
                    color_aci=aci_color,
                    hex_color=hex_col,
                    is_off=layer.is_off(),
                    is_locked=layer.is_locked(),
                    is_frozen=layer.is_frozen(),
                    linetype=layer.dxf.linetype
                )
            )

        # Extract Layouts & Viewports (Paper Space)
        layouts = []
        for l in doc.layouts:
            if l.name == "Model":
                continue
            viewports = []
            for e in l:
                if e.dxftype() == "VIEWPORT":
                    cp = getattr(e.dxf, "center", (0, 0, 0))
                    viewports.append(
                        CADViewport(
                            center=[round(cp[0], 3), round(cp[1], 3)],
                            width=round(getattr(e.dxf, "width", 0.0), 3),
                            height=round(getattr(e.dxf, "height", 0.0), 3),
                            view_height=round(getattr(e.dxf, "view_height", 0.0), 3),
                            status=getattr(e.dxf, "status", 0)
                        )
                    )
            layouts.append(
                CADLayout(
                    name=l.name,
                    is_active=(l.name == doc.header.get("$CTAB", "")),
                    viewports=viewports
                )
            )

        # Collect entities from ALL spaces (Model space + all Paper space layouts)
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
        polylines = []

        min_x, min_y = float("inf"), float("inf")
        max_x, max_y = float("-inf"), float("-inf")

        def update_bounds(x: float, y: float):
            nonlocal min_x, min_y, max_x, max_y
            if x < min_x: min_x = x
            if y < min_y: min_y = y
            if x > max_x: max_x = x
            if y > max_y: max_y = y

        for space_name, space in spaces_to_scan:
            for entity in space:
                etype = entity.dxftype()
                layer_name = entity.dxf.layer
                ent_color = resolve_entity_color(entity, layer_color_map)

                if etype == "INSERT":
                    raw_bname = entity.dxf.name
                    ip = entity.dxf.insert
                    update_bounds(ip.x, ip.y)

                    # Extract block attributes (ATTRIB)
                    attrib_dict = {}
                    if hasattr(entity, "attribs"):
                        for a in entity.attribs:
                            if hasattr(a.dxf, "tag") and hasattr(a.dxf, "text"):
                                attrib_dict[a.dxf.tag] = clean_cad_text(a.dxf.text)

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
                            rotation=round(entity.dxf.rotation, 2),
                            scale=[round(entity.dxf.xscale, 3), round(entity.dxf.yscale, 3), round(entity.dxf.zscale, 3)],
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
                    update_bounds(c.x, c.y)
                    arcs.append(
                        CADArc(
                            layer=layer_name,
                            space=space_name,
                            center=[round(c.x, 3), round(c.y, 3)],
                            radius=round(entity.dxf.radius, 3),
                            start_angle=round(entity.dxf.start_angle, 2),
                            end_angle=round(entity.dxf.end_angle, 2),
                            color=ent_color,
                        )
                    )

                elif etype == "LWPOLYLINE":
                    pts = [[round(p[0], 3), round(p[1], 3)] for p in entity.get_points()]
                    for px, py in pts:
                        update_bounds(px, py)
                    polylines.append(
                        CADPolyline(
                            layer=layer_name,
                            space=space_name,
                            is_closed=bool(entity.closed),
                            points=pts,
                            color=ent_color,
                        )
                    )

                elif etype in ("TEXT", "MTEXT"):
                    pos = entity.dxf.insert
                    update_bounds(pos.x, pos.y)
                    raw_text = entity.text if etype == "MTEXT" else entity.dxf.text
                    clean_text = clean_cad_text(raw_text)
                    annotations.append(
                        CADAnnotation(
                            type=etype,
                            layer=layer_name,
                            space=space_name,
                            raw_text=raw_text,
                            clean_text=clean_text,
                            position=[round(pos.x, 3), round(pos.y, 3)],
                            height=round(entity.dxf.char_height if etype == "MTEXT" else entity.dxf.height, 2)
                        )
                    )

                elif "DIMENSION" in etype:
                    dp = getattr(entity.dxf, "defpoint", (0, 0, 0))
                    dp2 = getattr(entity.dxf, "defpoint2", None)
                    meas = getattr(entity.dxf, "actual_measurement", None)
                    dim_text = clean_cad_text(getattr(entity.dxf, "text", ""))
                    update_bounds(dp[0], dp[1])
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
                total_polylines=len(polylines),
                total_components=len(components),
                total_annotations=len(annotations),
                total_dimensions=len(dimensions),
            ),
            primitives=CADPrimitives(
                lines=lines,
                arcs=arcs,
                polylines=polylines,
            )
        )

        return CADIntermediateRepresentation(
            format="LAVINCI_CAD_IR_V2",
            metadata=metadata,
            extents=extents,
            layouts=layouts,
            layers=layers,
            bill_of_materials=dict(block_counts.most_common()),
            annotations=annotations,
            dimensions=dimensions,
            components=components,
            geometry_primitives=geometry,
        )
