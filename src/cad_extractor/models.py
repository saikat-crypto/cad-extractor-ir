"""
Pydantic Schemas defining the Hardened CAD Intermediate Representation (IR v2).
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

class CADBlockAttribute(BaseModel):
    tag: str
    value: str

class CADComponentInstance(BaseModel):
    block_name: str
    resolved_name: Optional[str] = None
    layer: str
    space: str = "Model"
    position: List[float]
    rotation: float
    scale: List[float]
    attributes: Dict[str, str] = Field(default_factory=dict)

class CADAnnotation(BaseModel):
    type: str
    layer: str
    space: str = "Model"
    raw_text: str
    clean_text: str
    position: List[float]
    height: float

class CADDimension(BaseModel):
    type: str
    layer: str
    space: str = "Model"
    measurement: Optional[float] = None
    text: Optional[str] = None
    defpoint: List[float] = Field(default_factory=lambda: [0.0, 0.0])
    defpoint2: Optional[List[float]] = None

class CADLine(BaseModel):
    layer: str
    space: str = "Model"
    start: List[float]
    end: List[float]
    color: Optional[str] = None

class CADArc(BaseModel):
    layer: str
    space: str = "Model"
    center: List[float]
    radius: float
    start_angle: float
    end_angle: float
    color: Optional[str] = None

class CADPolyline(BaseModel):
    layer: str
    space: str = "Model"
    is_closed: bool
    points: List[List[float]]
    color: Optional[str] = None

class CADPrimitives(BaseModel):
    lines: List[CADLine] = Field(default_factory=list)
    arcs: List[CADArc] = Field(default_factory=list)
    polylines: List[CADPolyline] = Field(default_factory=list)

class CADViewport(BaseModel):
    center: List[float]
    width: float
    height: float
    view_center: Optional[List[float]] = None
    view_height: Optional[float] = None
    status: Optional[int] = None

class CADLayout(BaseModel):
    name: str
    is_active: bool
    extents_min: List[float] = Field(default_factory=lambda: [0.0, 0.0])
    extents_max: List[float] = Field(default_factory=lambda: [0.0, 0.0])
    viewports: List[CADViewport] = Field(default_factory=list)

class CADPrimitiveSummary(BaseModel):
    total_lines: int
    total_arcs: int
    total_polylines: int
    total_components: int
    total_annotations: int
    total_dimensions: int

class CADGeometry(BaseModel):
    summary: CADPrimitiveSummary
    primitives: CADPrimitives

class CADIntermediateRepresentation(BaseModel):
    format: str = "LAVINCI_CAD_IR_V2"
    metadata: CADMetadata
    extents: CADExtents
    layouts: List[CADLayout] = Field(default_factory=list)
    layers: List[CADLayer]
    bill_of_materials: Dict[str, int]
    annotations: List[CADAnnotation]
    dimensions: List[CADDimension] = Field(default_factory=list)
    components: List[CADComponentInstance]
    geometry_primitives: CADGeometry
