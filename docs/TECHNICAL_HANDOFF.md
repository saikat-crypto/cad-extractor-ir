# CAD Extractor IR (`cad-extractor-ir`): Technical Handoff Document

**Module Version:** 1.0.0 (`LAVINCI_CAD_IR_V3`)  
**Maintainer:** Saikat Dutta Chowdhury / La Vinci Initiative  
**License:** MIT  
**Target Runtime:** Python 3.10+ (CLI, Native Service, AWS Lambda Container)

---

## 1. Module Overview & Operational Purpose

`cad-extractor-ir` is the canonical **Ingestion Engine (Hub)** of the La Vinci CAD ecosystem. It ingests CAD drawing files, normalizes disparate versions and internal data structures, and produces a strongly-typed, queryable JSON **Intermediate Representation (IR)**.

Downstream tools (DXF, SVG, PDF, CSV, 3D WebGL viewers) consume this IR as their single source of truth without interacting with raw CAD binary files.

---

## 2. Ingestion Specifications (What the Module Accepts)

### 2.1 Supported File Types & Extensions
1. **`.dwg` (AutoCAD Binary Drawing)**: Binary CAD databases from version R13 up through AutoCAD 2024 (R2018 format `AC1032`).
2. **`.dwt` (AutoCAD Drawing Template)**: Structurally identical to `.dwg` with the same binary magic headers and block/layer definitions.
3. **`.dxf` (Drawing Exchange Format)**: ASCII or Binary DXF files.

### 2.2 Input Detection & Dispatch Logic
* **Extension Matching**: Case-insensitive suffix check (`.dxf`).
* **Magic Byte Fallback**: If the extension is omitted or ambiguous:
  * Reads the first 10 bytes.
  * If `0\nSECTION` or `b"SECTION"` is detected, routes to direct DXF parsing.
  * If binary magic (e.g. `AC1015`, `AC1018`, `AC1021`, `AC1024`, `AC1027`, `AC1032`) is detected, routes to the LibreDWG conversion pipeline.

---

## 3. Exact Input Schema & Calling Interface

### 3.1 Python API (`cad_extractor.core.extract_cad_ir`)
```python
def extract_cad_ir(
    input_path: str,
    dwg2dxf_binary: Optional[str] = None
) -> CADIntermediateRepresentation:
    ...
```

#### Parameters:
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `input_path` | `str` | Yes | N/A | Absolute or relative filesystem path to the target `.dwg`, `.dwt`, or `.dxf` file. |
| `dwg2dxf_binary` | `Optional[str]` | No | `None` | Custom path to the `dwg2dxf` executable. If omitted, the module automatically resolves via `PATH` or relative fallback to `experiments/libredwg/dwg2dxf.exe`. |

### 3.2 CLI Interface (`cad-extractor` / `python -m cad_extractor.cli`)
```bash
cad-extractor <input> [-o OUTPUT] [--bom] [--summary]
```

#### CLI Arguments & Flags:
| Flag | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `input` | Positional `str` | Required | Path to input CAD file (`.dwg`, `.dwt`, `.dxf`). |
| `-o`, `--output` | `str` | `None` | Path to export the formatted JSON IR file. |
| `--bom` | `flag` | `False` | Prints formatted Bill of Materials table to stdout. |
| `--summary` | `flag` | `False` | Prints metadata, entity counts, and dimensions to stdout. |

---

## 4. Exact Output Schema & Types (`LAVINCI_CAD_IR_V3`)

The output is an instance of `CADIntermediateRepresentation` (Pydantic v2 `BaseModel`), serializable to JSON via `.model_dump_json()`.

### 4.1 Schema Tree & Type Hierarchy
```typescript
interface CADIntermediateRepresentation {
  format: "LAVINCI_CAD_IR_V3";
  metadata: CADMetadata;
  extents: CADExtents;
  layouts: CADLayout[];
  layers: CADLayer[];
  bill_of_materials: Record<string, number>;
  block_definitions: Record<string, CADBlockDefinition>;
  annotations: CADAnnotation[];
  dimensions: CADDimension[];
  components: CADComponentInstance[];
  geometry_primitives: CADGeometry;
}
```

### 4.2 Field-by-Field Type Definitions

#### `metadata: CADMetadata`
* `source_file: str` — Base filename of input.
* `dxf_version: str` — AutoCAD internal DXF code (e.g., `"AC1015"`, `"AC1021"`, `"AC1032"`).
* `cad_version: str` — Human-readable release (e.g., `"R2000"`, `"R2007"`, `"R2018"`).
* `units: int` — AutoCAD `$INSUNITS` integer code (`0` = Unspecified, `1` = Inches, `4` = Millimeters, `6` = Meters).
* `measurement_system: str` — `"Metric"` or `"Imperial"`.
* `author: Optional[str]` — Extracted from `$LOGINNAME` (default: `"Unknown"`).

#### `extents: CADExtents`
* `min: [float, float]` — Minimum $[x, y]$ bounding box coordinates.
* `max: [float, float]` — Maximum $[x, y]$ bounding box coordinates.
* `width: float` — Total bounding width ($\max(0, \text{max}_x - \text{min}_x)$).
* `height: float` — Total bounding height ($\max(0, \text{max}_y - \text{min}_y)$).

#### `layers: CADLayer[]`
* `name: str` — Layer name (e.g., `"WALLS"`, `"0"`).
* `color_aci: int` — AutoCAD Color Index integer (1–255).
* `hex_color: str` — Normalized 7-character RGB hex string (e.g., `"#ff0000"`).
* `is_off: bool` — Visibility state (`True` if turned off).
* `is_locked: bool` — Lock state.
* `is_frozen: bool` — Freeze state.
* `linetype: str` — Associated linetype name (e.g., `"Continuous"`, `"DASHED"`).

#### `layouts: CADLayout[]`
* `name: str` — Sheet or layout name (e.g., `"ISO A1"`, `"Layout1"`).
* `is_active: bool` — `True` if active sheet in the editor.
* `extents_min: [float, float]` — Paper space extents minimum.
* `extents_max: [float, float]` — Paper space extents maximum.
* `viewports: CADViewport[]` — Array of viewports embedded in the layout:
  * `center: [float, float]` — Paper-space center coordinates.
  * `width: float` — Viewport width.
  * `height: float` — Viewport height.
  * `view_center: Optional[[float, float]]` — Target model-space center point.
  * `view_height: Optional[float]` — Model-space view camera height.
  * `status: Optional[int]` — Active state flag.

#### `block_definitions: Record<string, CADBlockDefinition>`
Mapping of block name $\to$ reusable geometric definition:
* `name: str` — Block record name.
* `base_point: [float, float, float]` — Insertion base offset point $[x, y, z]$.
* `lines: CADLine[]`
* `arcs: CADArc[]`
* `circles: CADCircle[]`
* `polylines: CADPolyline[]`

#### `components: CADComponentInstance[]`
Instantiated block occurrences (`INSERT` entities):
* `block_name: str` — Raw definition handle (e.g. `"*U48"`, `"Bathtub"`).
* `resolved_name: Optional[str]` — Disambiguated human-readable name based on attributes (e.g. `"ANDERSEN CASEMENT (*U48)"`).
* `layer: str` — Layer name on which the component was placed.
* `space: str` — `"Model"` or paper layout name.
* `position: [float, float, float]` — Insertion point $[x, y, z]$.
* `rotation: float` — Counter-clockwise rotation angle in degrees.
* `scale: [float, float, float]` — Scaling factors $[s_x, s_y, s_z]$.
* `attributes: Record<string, str>` — Mined block attributes (e.g. `{"MANUFACTURER": "ANDERSEN", "COST": "249.00"}`).

#### `bill_of_materials: Record<string, number>`
Aggregated component frequencies sorted descending by count:
```json
{
  "Receptacle": 44,
  "Lighting fixture": 28,
  "ANDERSEN CASEMENT (*U48)": 10
}
```

#### `annotations: CADAnnotation[]`
* `type: str` — `"TEXT"` or `"MTEXT"`.
* `layer: str` — Layer name.
* `space: str` — Space location.
* `raw_text: str` — Original unparsed text string.
* `clean_text: str` — Sanitized plain text with formatting and RTF escape tags stripped.
* `position: [float, float]` — Insertion point $[x, y]$.
* `height: float` — Text glyph height.

#### `dimensions: CADDimension[]`
* `type: str` — Dimension type (e.g. `"DIMENSION"`, `"ALIGNED"`, `"ROTATED"`).
* `layer: str` — Layer name.
* `space: str` — Space location.
* `measurement: Optional[float]` — Explicit actual measurement value.
* `text: Optional[str]` — Dimension label or override string.
* `defpoint: [float, float]` — Primary definition/witness point $[x, y]$.
* `defpoint2: Optional[[float, float]]` — Secondary definition point $[x, y]$.
* `text_midpoint: Optional[[float, float]]` — Text position point $[x, y]$.
* `text_height: Optional[float]` — Dimension text height.
* `text_rotation: Optional[float]` — Dimension text rotation.

#### `geometry_primitives: CADGeometry`
* `summary: CADPrimitiveSummary` — Integer tallies (`total_lines`, `total_arcs`, `total_circles`, `total_polylines`, `total_components`, `total_annotations`, `total_dimensions`, `total_block_definitions`).
* `primitives: CADPrimitives` — Model-space and top-level primitives:
  * `lines: CADLine[]` — `start: [x, y]`, `end: [x, y]`, `color: Optional[str]`, `linetype: Optional[str]`.
  * `arcs: CADArc[]` — `center: [x, y]`, `radius: float`, `start_angle: float`, `end_angle: float`, `color`, `linetype`.
  * `circles: CADCircle[]` — `center: [x, y]`, `radius: float`, `color`, `linetype`.
  * `polylines: CADPolyline[]` — `is_closed: bool`, `points: [x, y][]`, `color`, `linetype`.

---

## 5. Styling, Color & Inheritance Rules

1. **`BYLAYER` Semantics**:
   * If an entity has no explicit color override (`color == 256` or unset), the IR outputs `"color": null`.
   * Downstream exporters **must** inherit color from the corresponding `CADLayer.hex_color`.
2. **`BYBLOCK` Semantics**:
   * If an entity inside a block definition has color `0`, the IR outputs `"color": "BYBLOCK"`.
   * Downstream exporters must inherit the color of the parent `CADComponentInstance`.
3. **TrueColor Overrides**:
   * Entities with explicit 24-bit RGB or ACI overrides (1–255) output a concrete hex code (e.g., `"#ff00ff"`).
4. **Arc Angles**:
   * Native counter-clockwise degrees $[0^\circ, 360^\circ)$.
   * Arcs that wrap across $0^\circ$ (e.g. `start_angle: 315.0`, `end_angle: 45.0`) are preserved **as-is**. Do not attempt to force `start < end`.

---

## 6. Validation Rules & Defensive Sanitization

The module applies the following defensive transforms during extraction:

1. **Unpaired Unicode Surrogate Stripping**:
   * Legacy CAD drawings frequently contain lone surrogate codepoints (`\ud800`–`\udfff`) from UCS-2 encoding.
   * `clean_cad_text` automatically sanitizes surrogates using `encode('utf-8', 'surrogatepass').decode('utf-8', 'replace')`, guaranteeing that `.model_dump_json()` never raises `PydanticSerializationError`.
2. **MTEXT Format Code Stripping**:
   * Removes formatting tags: `\f...;` (font), `\H...;` (height), `\C...;` (color), `\A...;` (alignment), `\W...;` (width), `\S...;` (stacking/fractions).
   * Strips inline toggles: `\L`, `\l` (underline), `\O`, `\o` (overline), `\K`, `\k` (strikethrough).
   * Replaces `\P` / `\p` with `\n` and `\~` with non-breaking space.
3. **Bounding Box Radius Expansion**:
   * `update_bounds()` for `ARC` and `CIRCLE` primitives explicitly expands bounds by $[c_x - r, c_y - r]$ and $[c_x + r, c_y + r]$.
   * Protects against `NaN` and `Inf` coordinates; non-finite floats are ignored to prevent corrupted JSON serialization.
4. **Dimension Defpoint Coverage**:
   * Both `defpoint` and `defpoint2` are factored into bounding box calculations.
5. **Negative ACI Protection**:
   * Negative ACI color numbers (AutoCAD layer-off status) are mapped to positive equivalents (`abs(aci)`) or `None`, preventing `IndexError` in color tables.

---

## 7. Error Conditions & Exception Hierarchy

| Error | Type | Trigger Condition |
| :--- | :--- | :--- |
| **File Not Found** | `FileNotFoundError` | Target input path does not exist on disk. |
| **Timeout Expired** | `TimeoutError` | LibreDWG subprocess hangs for $> 120$ seconds (e.g. circular blocks or corrupt byte loop). |
| **LibreDWG Failure** | `RuntimeError` | Non-zero exit code from `dwg2dxf.exe` and intermediate DXF cannot be created. |
| **Corrupted DXF** | `RuntimeError` | Malformed DXF structure missing `SECTION` or `EOF` tags. |
| **Schema Validation** | `pydantic.ValidationError` | Internal data fails strict Pydantic v2 type validation. |

---

## 8. Supported vs. Unsupported Entities

### ✅ Fully Supported & Extracted:
* `LINE` (with endpoints, color, linetype)
* `ARC` (with center, radius, start/end angles, color, linetype)
* `CIRCLE` (with center, radius, color, linetype)
* `LWPOLYLINE` / `POLYLINE` (2D flattened vertices, closed flag, bulge curves)
* `INSERT` (block occurrences with translation, rotation, scale, attribute dictionaries)
* `BLOCK_RECORD` (reusable internal primitives table)
* `TEXT` / `MTEXT` (raw text + sanitized clean text, position, height)
* `DIMENSION` (linear, aligned, rotated, definition points, actual measurements)
* `LAYOUT` / `VIEWPORT` (paper space sheets, viewport view centers, view heights)
* `LAYER` (names, states, 256 ACI colors, TrueColor, linetypes)

### ⚠️ Unsupported or Simplified Entities:
1. **3D ACIS B-Rep Solids (`3DSOLID`, `REGION`, `BODY`)**:
   * Proprietary binary Dassault ACIS modeling kernels embedded in AutoCAD.
   * Primitive boundary surfaces are not decomposed into 3D meshes.
2. **Splines (`SPLINE`)**:
   * Currently omitted or flattened where tessellated.
3. **Hatches (`HATCH`)**:
   * Associative patterns are extracted if boundary loops are present; gradient fill shaders are omitted.
4. **External References (`XREF`)**:
   * Extracted as an `INSERT` block reference; external file resolution requires sibling drawing files.
5. **Proprietary Shape Fonts (`.shx`)**:
   * Embedded text characters are extracted cleanly; visual glyph vector outlines depend on having local `.shx` font files.

---

## 9. Performance & Resource Characteristics

* **Extraction Throughput**:
  * Simple drawings ($< 500$ entities): **30 ms – 90 ms**.
  * Medium architectural floor plans (1,000 – 5,000 entities): **200 ms – 450 ms**.
  * Large drawings (10,000 lines): **~900 ms**.
* **Memory Footprint**:
  * Python runtime: $\approx 45 \text{ MB}$.
  * Temporary intermediate DXF storage: Automatically purged via Python `tempfile.TemporaryDirectory()`.
* **Payload Compression Ratio**:
  * Raw binary/DXF parser dump: $\approx 4.8 \text{ MB}$.
  * Standardized `LAVINCI_CAD_IR_V3` JSON: $\approx 118 \text{ KB}$ (**~97.5% payload reduction**).

---

## 10. External Dependencies & Native Binaries

### 10.1 Python Packages
* `pydantic >= 2.0.0`
* `pydantic-core >= 2.0.0`
* `ezdxf >= 1.4.0`

### 10.2 Native C Binary Dependencies
* **LibreDWG (`dwg2dxf.exe` / `dwg2dxf`)**:
  * Windows: Self-contained 64-bit binary in `experiments/libredwg/` linked against MinGW. Requires co-located DLLs (`libredwg-0.dll`, `libiconv-2.dll`, `libpcre2-8-0.dll`, `libpcre2-16-0.dll`).
  * Linux / Lambda Container: Packaged in multi-stage Docker build via GNU Autotools (`/usr/local/bin/dwg2dxf`).

---

## 11. Concrete Usage Examples

### 11.1 Python API Example
```python
from cad_extractor.core import extract_cad_ir

# 1. Ingest DWG or DWT
ir = extract_cad_ir("floor_plan.dwg")

# 2. Access Metadata & Dimensions
print(f"File: {ir.metadata.source_file} (AutoCAD {ir.metadata.cad_version})")
print(f"Canvas Bounds: {ir.extents.width} x {ir.extents.height}")

# 3. Access Bill of Materials
for part_name, quantity in ir.bill_of_materials.items():
    print(f"  {part_name}: {quantity}")

# 4. Access Reusable Block Geometry
for block_name, definition in ir.block_definitions.items():
    print(f"Block '{block_name}' has {len(definition.lines)} lines, {len(definition.arcs)} arcs")

# 5. Serialize to JSON
json_payload = ir.model_dump_json(indent=2)
```

### 11.2 Downstream Wrapper Checklist (For Building DXF / SVG / PDF Exporters)
When building downstream tools that consume this IR, ensure your wrapper adheres to these four rules:
1. **Always Check for `None` Color**:
   ```python
   color = entity.color if entity.color is not None else layer_color_map[entity.layer]
   ```
2. **Draw Blocks via References**:
   Look up `component.block_name` in `ir.block_definitions`. Translate by `position`, rotate by `rotation`, and scale by `scale`.
3. **Support Arc Angle Wraps**:
   If an arc has `start_angle > end_angle`, draw counter-clockwise sweeping across $0^\circ$.
4. **Sanitize Output Filepaths**:
   When writing downstream exports on Windows, ensure directory paths avoid non-representable ANSI codepages if passing through native C tools.
