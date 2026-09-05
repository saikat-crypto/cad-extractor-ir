"""
Core Extraction Engine.
Decodes binary DWG via underlying LibreDWG C-parser and lifts entities into CAD IR.
"""

import os
import shutil
import tempfile
import subprocess
from collections import Counter
from typing import Dict, Any, Optional

import ezdxf

from .models import (
    CADIntermediateRepresentation,
    CADMetadata,
    CADExtents,
    CADLayer,
    CADComponentInstance,
    CADAnnotation,
    CADLine,
    CADArc,
    CADPolyline,
    CADPrimitives,
    CADPrimitiveSummary,
    CADGeometry,
)

ACI_TO_HEX = {
    1: "#FF0000",
    2: "#FFFF00",
    3: "#00FF00",
    4: "#00FFFF",
    5: "#0000FF",
    6: "#FF00FF",
    7: "#000000",
    8: "#808080",
    9: "#C0C0C0",
}

def resolve_color(color_int: int) -> str:
    return ACI_TO_HEX.get(color_int, "#777777")

def find_dwg2dxf_binary() -> str:
    # 1. System PATH
    found = shutil.which("dwg2dxf")
    if found:
        return found
    
    # 2. Local experiment fallback on Windows
    local_win = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../experiments/libredwg/dwg2dxf.exe"))
    if os.path.exists(local_win):
        return local_win
        
    return "dwg2dxf"

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
        msp = doc.modelspace()
        header = doc.header

        metadata = CADMetadata(
            source_file=os.path.basename(dwg_path),
            dxf_version=str(doc.dxfversion),
            cad_version=str(doc.acad_release),
            units=header.get("$INSUNITS", 0),
            measurement_system="Metric" if header.get("$MEASUREMENT", 1) == 1 else "Imperial",
            author=header.get("$LOGINNAME", "Unknown"),
        )

        layers = [
            CADLayer(
                name=layer.dxf.name,
                color_aci=layer.color,
                hex_color=resolve_color(layer.color),
                is_off=layer.is_off(),
                is_locked=layer.is_locked(),
                is_frozen=layer.is_frozen(),
                linetype=layer.dxf.linetype
            )
            for layer in doc.layers
        ]

        block_counts = Counter()
        components = []
        annotations = []
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

        for entity in msp:
            etype = entity.dxftype()
            layer_name = entity.dxf.layer

            if etype == "INSERT":
                bname = entity.dxf.name
                block_counts[bname] += 1
                ip = entity.dxf.insert
                update_bounds(ip.x, ip.y)
                components.append(
                    CADComponentInstance(
                        block_name=bname,
                        layer=layer_name,
                        position=[round(ip.x, 3), round(ip.y, 3), round(ip.z, 3)],
                        rotation=round(entity.dxf.rotation, 2),
                        scale=[round(entity.dxf.xscale, 3), round(entity.dxf.yscale, 3), round(entity.dxf.zscale, 3)],
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
                        start=[round(p1.x, 3), round(p1.y, 3)],
                        end=[round(p2.x, 3), round(p2.y, 3)],
                    )
                )

            elif etype == "ARC":
                c = entity.dxf.center
                update_bounds(c.x, c.y)
                arcs.append(
                    CADArc(
                        layer=layer_name,
                        center=[round(c.x, 3), round(c.y, 3)],
                        radius=round(entity.dxf.radius, 3),
                        start_angle=round(entity.dxf.start_angle, 2),
                        end_angle=round(entity.dxf.end_angle, 2),
                    )
                )

            elif etype == "LWPOLYLINE":
                pts = [[round(p[0], 3), round(p[1], 3)] for p in entity.get_points()]
                for px, py in pts:
                    update_bounds(px, py)
                polylines.append(
                    CADPolyline(
                        layer=layer_name,
                        is_closed=bool(entity.closed),
                        points=pts,
                    )
                )

            elif etype in ("TEXT", "MTEXT"):
                pos = entity.dxf.insert
                update_bounds(pos.x, pos.y)
                raw_text = entity.text if etype == "MTEXT" else entity.dxf.text
                annotations.append(
                    CADAnnotation(
                        type=etype,
                        layer=layer_name,
                        text=raw_text.strip(),
                        position=[round(pos.x, 3), round(pos.y, 3)],
                        height=round(entity.dxf.char_height if etype == "MTEXT" else entity.dxf.height, 2)
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
            ),
            primitives=CADPrimitives(
                lines=lines,
                arcs=arcs,
                polylines=polylines,
            )
        )

        return CADIntermediateRepresentation(
            format="LAVINCI_CAD_IR_V1",
            metadata=metadata,
            extents=extents,
            layers=layers,
            bill_of_materials=dict(block_counts.most_common()),
            annotations=annotations,
            components=components,
            geometry_primitives=geometry,
        )
