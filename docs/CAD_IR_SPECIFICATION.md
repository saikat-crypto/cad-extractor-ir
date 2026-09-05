# La Vinci CAD Intermediate Representation (IR) Specification
**Version:** `LAVINCI_CAD_IR_V2`  
**Status:** Approved Standard  
**Maintainer:** Saikat Dutta Chowdhury / La Vinci Initiative  

---

## 1. Executive Summary

The **CAD Intermediate Representation (IR)** is an open, queryable, vendor-agnostic data specification designed to represent 2D and 3D computer-aided design (CAD) drawings. 

Historically, CAD geometry has been held captive inside complex, proprietary, undocumented binary file formats—most notably Autodesk's `.dwg`. Binary formats entangle layout geometry, visual styling, spatial indices, and software-specific runtime state into monolithic bit-streams.

The La Vinci CAD IR decouples raw CAD parsing from downstream consumers. It translates binary CAD databases into a clean, hierarchical, strongly-typed JSON schema. Downstream tools (SVG exporters, PDF generators, DXF converters, 3D WebGL viewers, Bill of Materials calculators, and GIS pipelines) operate directly on this IR without ever requiring native CAD kernels or heavy desktop runtimes.

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
                     LAVINCI_CAD_IR_V2 (JSON / Pydantic)
         ════════════════════════════════════════════════════
                                │
        ┌───────────────┬───────┴───────┬───────────────┐
        ▼               ▼               ▼               ▼
 ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
 │ Vector (DXF)│ │ Vector (SVG)│ │ Vector (PDF)│ │ Data (CSV)  │
 │  Compiler   │ │  Exporter   │ │  Exporter   │ │ BOM Report  │
 └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘
```

---

## 3. Schema Structure (`LAVINCI_CAD_IR_V2`)

The IR payload is structured into seven fundamental domains:

```json
{
  "format": "LAVINCI_CAD_IR_V2",
  "metadata": { ... },
  "extents": { ... },
  "layers": [ ... ],
  "layouts": [ ... ],
  "geometry": {
    "summary": { ... },
    "primitives": {
      "lines": [ ... ],
      "arcs": [ ... ],
      "polylines": [ ... ]
    }
  },
  "dimensions": [ ... ],
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
Pre-computed spatial bounding box of the entire drawing in model-space units. Essential for setting up target canvas viewports (`viewBox` in SVG, page size in PDF, `$EXTMIN`/`$EXTMAX` in DXF).

| Field | Type | Description |
| :--- | :--- | :--- |
| `min` | `[float, float]` | Lower-left coordinate `[min_x, min_y]`. |
| `max` | `[float, float]` | Upper-right coordinate `[max_x, max_y]`. |
| `width` | `float` | Computed bounding width: `max_x - min_x`. |
| `height` | `float` | Computed bounding height: `max_y - min_y`. |

### 3.3 Layers (`CADLayer`)
Drawing organization and visibility rules. Colors are resolved from AutoCAD Color Index (ACI) codes (full 256 palette) and TrueColor into standard Web Hex RGB strings.

| Field | Type | Description |
| :--- | :--- | :--- |
| `name` | `string` | Unique layer name. |
| `color_aci` | `integer` | AutoCAD Color Index integer (0-256). |
| `hex_color` | `string` | Resolved standard hex color code (e.g. `#FF0000`, `#00FF00`). |
| `is_off` | `boolean` | Whether the layer visibility is toggled off. |
| `is_locked` | `boolean` | Whether entities on this layer are locked from edits. |
| `is_frozen` | `boolean` | Whether the layer is frozen by the CAD viewport. |
| `linetype` | `string` | Dash pattern style (`CONTINUOUS`, `DASHED`, `CENTER`, etc.). |

### 3.4 Paper Space Layouts & Viewports (`CADLayout` & `CADViewport`)
Captures multi-sheet print layouts (e.g. `ISO A1` printable title sheets) alongside modelspace:
* `name`: Layout title.
* `is_active`: Whether this sheet is currently selected.
* `extents_min` / `extents_max`: Printable paper bounds.
* `viewports`: List of camera viewports projecting model space coordinates onto paper sheets (`center`, `width`, `height`, `view_center`, `view_height`).

### 3.5 Geometry Primitives (`CADPrimitives`)
Mathematically pure vector primitives with entity-level color overrides and space tags:

* **`lines`**:
  * `start`: `[x1, y1]`
  * `end`: `[x2, y2]`
  * `layer`: Parent layer name.
  * `space`: `"Model"` or layout sheet name.
  * `color`: Optional hex color override (if distinct from ByLayer).
* **`arcs`**:
  * `center`: `[cx, cy]`
  * `radius`: Radius $r$.
  * `start_angle`: Starting angle in degrees ($0^\circ - 360^\circ$).
  * `end_angle`: Ending angle in degrees ($0^\circ - 360^\circ$).
  * `layer`: Parent layer name.
  * `space`: Space identifier.
  * `color`: Optional hex color override.
* **`polylines`**:
  * `points`: Connected array of vertices `[[x1, y1], [x2, y2], ...]`.
  * `is_closed`: Boolean indicating if closed.
  * `layer`: Parent layer name.
  * `space`: Space identifier.
  * `color`: Optional hex color override.

### 3.6 Dimensions (`CADDimension`)
Ingests native CAD engineering dimension entities:
* `type`: Dimension type (`DIMENSION`, `ALIGNED`, `LINEAR`, `ROTATED`).
* `layer`: Placement layer.
* `space`: Target space (`Model` or Sheet).
* `measurement`: Explicit distance or measurement value.
* `text`: Explicit dimension text or label override.
* `defpoint` / `defpoint2`: Definition point anchors.

### 3.7 Components & Bill of Materials (`CADComponentInstance` & `bill_of_materials`)
AutoCAD block references (doors, windows, valves, electrical sockets) with embedded attribute mining:

* **Component Instance**:
  * `block_name`: Raw symbol name (e.g. `*U48`).
  * `resolved_name`: Human-meaningful label mined from attributes (e.g. `ANDERSEN CASEMENT (*U48)`).
  * `layer`: Placement layer.
  * `space`: Placement space.
  * `position`: Insertion point `[x, y, z]`.
  * `rotation`: Angle of insertion.
  * `scale`: Scaling factors `[scale_x, scale_y, scale_z]`.
  * `attributes`: Key-value dictionary of mined attributes (`MANUFACTURER`, `STYLE`, `TAG`, `COST`).
* **Bill of Materials (`bill_of_materials`)**:
  * Aggregated dictionary mapping resolved names to exact instance counts.

### 3.8 Annotations (`CADAnnotation`)
Sanitized labels and text markings:
* `raw_text`: Unprocessed text from CAD.
* `clean_text`: Stripped of AutoCAD RTF formatting codes (`\fArial;`, `\H0.6667x;`, `\L`, etc.).
* `position`: Placement coordinate `[x, y]`.
* `height`: Text font height in drawing units.
* `layer`: Layer name.
* `space`: Placement space.

---

## 4. Key Design Guarantees

1. **Entity-Level Independence**: Entities maintain explicit colors and space designations, preventing visual degradation across downstream exporters.
2. **RTF Formatting Sanitization**: Text annotations are clean plain-text strings suitable for search, LLM ingestion, and crisp canvas rendering.
3. **TrueColor + Full 256 ACI Support**: Complete color fidelity across all AutoCAD indexed palettes.
4. **Multi-Space Awareness**: Transparent separation between 1:1 Model Space engineering geometry and Paper Space print layouts.
