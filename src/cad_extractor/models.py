"""
Pydantic Schemas defining the CAD Intermediate Representation (IR).
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class CADMetadata(BaseModel):
    source_file: str
    dxf_version: str
    cad_version: str
    units: int
    measurement_system: str
    author: Optional[str] = "Unknown"

class CADExtents(BaseModel):
    min: List[float] = Field(default_factory=lambda: [0.0, 0.0])
    max: List[float] = Field(default_factory=lambda: [0.0, 0.0])
    width: float = 0.0
    height: float = 0.0

class CADLayer(BaseModel):
    name: str
    color_aci: int
    hex_color: str
    is_off: bool
    is_locked: bool
    is_frozen: bool
    linetype: str

class CADComponentInstance(BaseModel):
    block_name: str
    layer: str
    position: List[float]
    rotation: float
    scale: List[float]

class CADAnnotation(BaseModel):
    type: str
    layer: str
    text: str
    position: List[float]
    height: float

class CADLine(BaseModel):
    layer: str
    start: List[float]
    end: List[float]

class CADArc(BaseModel):
    layer: str
    center: List[float]
    radius: float
    start_angle: float
    end_angle: float

class CADPolyline(BaseModel):
    layer: str
    is_closed: bool
    points: List[List[float]]

class CADPrimitives(BaseModel):
    lines: List[CADLine] = Field(default_factory=list)
    arcs: List[CADArc] = Field(default_factory=list)
    polylines: List[CADPolyline] = Field(default_factory=list)

class CADPrimitiveSummary(BaseModel):
    total_lines: int
    total_arcs: int
    total_polylines: int
    total_components: int
    total_annotations: int

class CADGeometry(BaseModel):
    summary: CADPrimitiveSummary
    primitives: CADPrimitives

class CADIntermediateRepresentation(BaseModel):
    format: str = "LAVINCI_CAD_IR_V1"
    metadata: CADMetadata
    extents: CADExtents
    layers: List[CADLayer]
    bill_of_materials: Dict[str, int]
    annotations: List[CADAnnotation]
    components: List[CADComponentInstance]
    geometry_primitives: CADGeometry
