# La Vinci CAD Intermediate Representation (IR) Specification
**Version:** `LAVINCI_CAD_IR_V1`  
**Status:** Approved Standard  
**Maintainer:** Saikat Dutta Chowdhury / La Vinci Initiative  

---

## 1. Executive Summary

The **CAD Intermediate Representation (IR)** is an open, queryable, vendor-agnostic data specification designed to represent 2D and 3D computer-aided design (CAD) drawings. 

Historically, CAD geometry has been held captive inside complex, proprietary, undocumented binary file formats—most notably Autodesk's `.dwg`. Binary formats entangle layout geometry, visual styling, spatial indices, and software-specific runtime state into monolithic bit-streams.

The La Vinci CAD IR decouples raw CAD parsing from downstream consumers. It translates binary CAD databases into a clean, hierarchical, strongly-typed JSON schema. Downstream tools (SVG exporters, PDF generators, 3D WebGL viewers, Bill of Materials calculators, and GIS pipelines) operate directly on this IR without ever requiring native CAD kernels or heavy desktop runtimes.

---

## 2. Architectural Position: The Hub-and-Spoke Model

```
                    ┌────────────────────────┐
                    │    Input: Raw DWG      │
                    │   (AutoCAD R2000-2024) │
                    └───────────┬────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │    cad-extractor-ir    │
                    │ (Byte-level C Engine)  │
                    └───────────┬────────────┘
                                │
                                ▼
         ════════════════════════════════════════════════════
                     LAVINCI_CAD_IR_V1 (JSON / Pydantic)
         ════════════════════════════════════════════════════
                                │
        ┌───────────────┬───────┴───────┬───────────────┐
        ▼               ▼               ▼               ▼
 ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
 │ Vector (SVG)│ │ Vector (PDF)│ │ Raster (PNG)│ │ Data (CSV)  │
 │  Exporter   │ │  Exporter   │ │  Renderer   │ │ BOM Report  │
 └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘
```

---

## 3. Schema Structure (`LAVINCI_CAD_IR_V1`)

The IR payload is structured into six fundamental domains:

```json
{
  "format": "LAVINCI_CAD_IR_V1",
  "metadata": { ... },
  "extents": { ... },
  "layers": [ ... ],
  "geometry": {
    "summary": { ... },
    "primitives": {
      "lines": [ ... ],
      "arcs": [ ... ],
      "polylines": [ ... ]
    }
  },
  "components": [ ... ],
  "annotations": [ ... ],
  "bill_of_materials": { ... }
}
```

### 3.1 Metadata (`CADMetadata`)
Captures document-level properties required for units, scaling, and provenance.

| Field | Type | Description |
| :--- | :--- | :--- |
| `source_file` | `string` | Origin filename or URI of the CAD file. |
| `dxf_version` | `string` | Underlying DXF header standard (e.g. `AC1021`, `AC1027`). |
| `cad_version` | `string` | Human-readable AutoCAD release (e.g. `R2007`, `R2018`). |
| `units` | `integer` | CAD measurement units code (e.g. `0` = Unspecified, `4` = Millimeters, `1` = Inches). |
| `measurement_system` | `string` | High-level system (`Metric` or `Imperial`). |
| `author` | `string?` | Author or creator if present in CAD header metadata. |

### 3.2 Extents (`CADExtents`)
Pre-computed spatial bounding box of the entire drawing in model-space units. Essential for setting up target canvas viewports (`viewBox` in SVG, page size in PDF).

| Field | Type | Description |
| :--- | :--- | :--- |
| `min` | `[float, float]` | Lower-left coordinate `[min_x, min_y]`. |
| `max` | `[float, float]` | Upper-right coordinate `[max_x, max_y]`. |
| `width` | `float` | Computed bounding width: `max_x - min_x`. |
| `height` | `float` | Computed bounding height: `max_y - min_y`. |

### 3.3 Layers (`CADLayer`)
Drawing organization and visibility rules. Colors are resolved from AutoCAD Color Index (ACI) codes into standard Web Hex RGB strings.

| Field | Type | Description |
| :--- | :--- | :--- |
| `name` | `string` | Unique layer name. |
| `color_aci` | `integer` | AutoCAD Color Index integer (0-256). |
| `hex_color` | `string` | Resolved standard hex color code (e.g. `#FF0000`, `#00FF00`). |
| `is_off` | `boolean` | Whether the layer visibility is toggled off. |
| `is_locked` | `boolean` | Whether entities on this layer are locked from edits. |
| `is_frozen` | `boolean` | Whether the layer is frozen by the CAD viewport. |
| `linetype` | `string` | Dash pattern style (`CONTINUOUS`, `DASHED`, `CENTER`, etc.). |

### 3.4 Geometry Primitives (`CADPrimitives`)
Mathematically pure vector primitives:

* **`lines`**:
  * `start`: `[x1, y1]`
  * `end`: `[x2, y2]`
  * `layer`: Parent layer name.
* **`arcs`**:
  * `center`: `[cx, cy]`
  * `radius`: Radius $r$.
  * `start_angle`: Starting angle in degrees ($0^\circ - 360^\circ$).
  * `end_angle`: Ending angle in degrees ($0^\circ - 360^\circ$).
  * `layer`: Parent layer name.
* **`polylines`**:
  * `points`: Connected array of vertices `[[x1, y1], [x2, y2], ...]`.
  * `is_closed`: Boolean indicating if the last vertex connects back to the first.
  * `layer`: Parent layer name.

### 3.5 Components & Bill of Materials (`CADComponentInstance` & `bill_of_materials`)
AutoCAD block references (symbol instances such as doors, windows, valves, electrical sockets) are captured individually and aggregated into a high-level BOM:

* **Component Instance**:
  * `block_name`: Identifier of the component definition.
  * `layer`: Placement layer.
  * `position`: Insertion point `[x, y]`.
  * `rotation`: Angle of insertion.
  * `scale`: Scaling factors `[scale_x, scale_y]`.
* **Bill of Materials (`bill_of_materials`)**:
  * Key-value dictionary mapping component names to exact instance counts:
    ```json
    {
      "Receptacle": 44,
      "Lighting fixture": 28,
      "Bathtub": 2,
      "Toilet": 1
    }
    ```

### 3.6 Annotations (`CADAnnotation`)
Labels, room names, and text markings:
* `text`: Content string.
* `position`: Placement coordinate `[x, y]`.
* `height`: Text font height in drawing units.
* `layer`: Layer name.

---

## 4. Key Design Decisions & Guarantees

1. **Self-Contained Rendering**: Downstream exporters do not need to query external font databases or block tables to perform clean vector renderings.
2. **Color Normalization**: ACI color tables vary across software; storing normalized 6-character Hex colors (`hex_color`) guarantees consistent visual output across SVG, PDF, WebGL, and Canvas.
3. **Payload Compression**: Reduces multi-megabyte binary dumps (often 100,000+ lines of raw C parser output) by **~97.5%**, yielding clean ~100KB JSON payloads that can be cached and transmitted over HTTP/S3 with negligible cost.
4. **Pydantic Validation**: Ensures strong typing, runtime validation, and direct serializability to Python dicts, dataclasses, or JSON files.
