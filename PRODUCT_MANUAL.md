# cad-extractor-ir: Ingestion Engine & Intermediate Representation Extractor

> **Product**: `cad-extractor-ir`  
> **Package Version**: `1.0.0` (Hardened Engine v3.1)  
> **Source Directory**: `products/cad-extractor-ir/`  
> **Role in Ecosystem**: Input Gateway (DWG / DXF / DWT $\to$ `LAVINCI_CAD_IR_V3`)  

---

## 1. Executive Summary & Architecture

The **`cad-extractor-ir`** engine is the primary ingestion gateway of the La Vinci ecosystem. Its sole responsibility is to crack open raw, proprietary, or standard AutoCAD files and transform their geometric, structural, and semantic content into the canonical **`LAVINCI_CAD_IR_V3`** JSON schema.

It implements a hybrid multi-tier extraction pipeline:
1. **Direct Native Parsing**: DXF (`Drawing Exchange Format`) files are parsed in-memory using `ezdxf` with patched low-level C-extension cryptographic decoders.
2. **Binary DWG Transcoding**: DWG (`AutoCAD Drawing Database`) files are decompiled via an embedded headless GNU LibreDWG engine (`dwg2dxf`), monitored with adaptive timeout supervisors and minimal-mode recovery heuristics.
3. **Template Standardization**: DWT (`Drawing Template`) files are processed through the same pipeline, extracting layout viewports and default layer tables.

```
                  ┌─────────────────────────────────────────┐
                  │           Input CAD Artifact            │
                  │        (.dwg / .dxf / .dwt file)        │
                  └────────────────────┬────────────────────┘
                                       │
                         Is DXF or DWG?│
                    ┌──────────────────┴──────────────────┐
                    │                                     │
           [DXF Header Detected]                 [Binary DWG Detected]
                    │                                     │
                    ▼                                     ▼
        ┌───────────────────────┐             ┌────────────────────────┐
        │  Direct ezdxf Parser  │             │  GNU LibreDWG Pipeline │
        │  - ACIS Patching      │             │  - Adaptive Timeout    │
        │  - Memory Stream      │             │  - Fallback Mode (-m)  │
        │  - Handle Recovery    │             │  - Stderr Diagnostics  │
        └───────────┬───────────┘             └───────────┬────────────┘
                    │                                     │
                    └──────────────────┬──────────────────┘
                                       │
                                       ▼
                       ┌──────────────────────────────┐
                       │    Raw Drawing Document      │
                       │         (ezdxf.Drawing)      │
                       └───────────────┬──────────────┘
                                       │
           ┌───────────────────────────┼───────────────────────────┐
           ▼                           ▼                           ▼
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│ Header & Layers     │     │ Model & Paper Space │     │ Block Definitions   │
│ - $INSUNITS         │     │ - Lines, Arcs, Plines│    │ - Internal Primitives│
│ - ACI Color Mapping │     │ - Text & Rotations  │     │ - ATTRIB Extractions│
│ - Layer Flags       │     │ - Linear Dimensions │     │ - Component Matrix  │
└──────────┬──────────┘     └──────────┬──────────┘     └──────────┬──────────┘
           │                           │                           │
           └───────────────────────────┼───────────────────────────┘
                                       │
                                       ▼
                       ┌──────────────────────────────┐
                       │   Sanitization & Guardrails  │
                       │   - Lone Surrogate Stripping │
                       │   - NaN / Inf Coordinate Drop│
                       │   - MTEXT Format Tag Strip   │
                       └───────────────┬──────────────┘
                                       │
                                       ▼
                       ┌──────────────────────────────┐
                       │   LAVINCI_CAD_IR_V3 Output   │
                       └──────────────────────────────┘
```

---

## 2. Ingestion Mechanisms & The Binary Conversion Pipeline

AutoCAD DWG is a proprietary, bit-packed binary format governed by undocumented, cyclical data structures, object handles, and hardware-specific checksums. 

### 2.1 Native vs Binary Ingestion Routing
When `extract_cad_ir(input_path)` is called:
1. **Magic Header Sniffing**: The first 10 bytes of the file are inspected.
   - If the file starts with `0\nSECTION` or standard ASCII DXF tags, it bypasses binary transcoding and goes directly to `ezdxf.readfile()`.
   - If binary magic headers (`AC1015`, `AC1018`, `AC1021`, `AC1027`, `AC1032`) are detected, the file is routed to the LibreDWG execution harness.

### 2.2 Adaptive Timeout & Process Supervision
Binary DWG decompression can hang indefinitely when encountering corrupt pointer trees or cyclic block references. `cad-extractor-ir` implements an adaptive timeout supervisor:

$$\text{Timeout}_{\text{adaptive}} = \min\left(300, \max\left(45, \lceil\text{Size}_{\text{MB}} \times 30\rceil\right)\right) \text{ seconds}$$

### 2.3 Two-Stage Decompilation & Minimal-Mode (`-m`) Fallback
1. **Stage 1 (Full Translation)**: The file is executed with `dwg2dxf -y <input> -o <temp.dxf>`.
2. **Stage 2 (Minimal Mode Fallback)**: If Stage 1 exits with a non-zero code or produces an unparseable DXF, the engine automatically attempts a recovery invocation:
   ```bash
   dwg2dxf -y -m <input> -o <temp.dxf>
   ```
   The `-m` (minimal) flag instructs LibreDWG to ignore complex object dictionaries, visual style records, and corrupted metadata classes, successfully extracting 2D geometric linework that would otherwise fail.

### 2.4 Diagnostic Stderr Harvesting
Upstream warnings from LibreDWG are scanned for `Warning:` and `ERROR:` tokens. Dropped object handles (e.g. unsupported 3D ACIS solids or corrupt proxies) are harvested and stored in `metadata.extraction_warnings`.

---

## 3. Core Extraction Algorithms & Mathematical Transformations

### 3.1 Unpaired Unicode Surrogate Sanitization
Corrupt or obfuscated CAD drawings frequently contain lone surrogate code points ($0\text{xD800} \le c \le 0\text{xDFFF}$). These code points crash standard UTF-8 encoders during JSON serialization.

The `sanitize_surrogates` algorithm encodes the raw text stream using Python's `surrogatepass` handler, immediately decoding back to UTF-8 while replacing orphan surrogates with the standard Unicode replacement character `\uFFFD`:
```python
def sanitize_surrogates(text: str) -> str:
    if not text:
        return ""
    try:
        return text.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
    except Exception:
        return "".join(c for c in text if not (0xD800 <= ord(c) <= 0xDFFF))
```

### 3.2 MTEXT Formatting Tag Stripping
AutoCAD stores rich-text annotations as cryptic escape sequences. The extractor cleans them using regex passes:
- **Font & Size Tags**: `\H1.5x;`, `\fArial;`, `\C1;` $\to$ stripped.
- **Styling Switches**: `\L` (underline on), `\l` (underline off), `\O` (overline) $\to$ stripped.
- **Paragraph Delimiters**: `\P` $\to$ normalized to newline `\n`.
- **Non-breaking Spaces**: `\~` $\to$ normalized to standard space `" "`.

### 3.3 Polyline Bulge Decomposition
An AutoCAD polyline vertex can specify an optional **bulge factor** $b$, representing the curvature of the arc segment connecting to the next vertex:

$$b = \tan\left(\frac{\Delta\theta}{4}\right)$$

Where $\Delta\theta$ is the included angle of the arc.
* If $b = 0$, the segment is linear.
* If $b \ne 0$, `cad-extractor-ir` uses `ezdxf.path.make_path()` to tessellate the analytic arc into a sequence of planar vertices based on an adaptive chord-height tolerance:
  ```python
  path_obj = ezdxf.path.make_path(entity)
  raw_pts = [[pt.x, pt.y] for pt in path_obj.flattening(distance=0.1)]
  ```

### 3.4 ACIS Cryptographic Decoding Patch
When AutoCAD DXF documents contain encrypted 3D solids (`ACIS` binary blocks in SAT format), `ezdxf`'s default decoder throws fatal exceptions on non-ASCII characters. `cad-extractor-ir` monkey-patches `ezdxf.tools.crypt.decode` at runtime:
```python
# Replaces unencodable characters safely rather than panicking
text_bytes = text.encode("ascii", errors="replace")
```

### 3.5 Coordinate Clamping & Bounding Box Extents Calculation
To guarantee that downstream compilers receive sane bounds:
1. Every vertex is validated against $|x|, |y| \le 1.0 \times 10^9$.
2. For circles and arcs, the extents envelope explicitly accounts for the radius:
   $$X_{\min} = C_x - R, \quad X_{\max} = C_x + R$$
   $$Y_{\min} = C_y - R, \quad Y_{\max} = C_y + R$$
3. For dimensions, definition points (`defpoint` and `defpoint2`) and text midpoints are included in the bounding box.

---

## 4. Layer & Color Invariant Architecture

AutoCAD supports two color addressing modes:
1. **Direct TrueColor**: 24-bit RGB values.
2. **AutoCAD Color Index (ACI)**: 1-255 indexed palette.

### Negative ACI Values
In AutoCAD, a negative ACI value (e.g. `-7`) signifies that a layer is **turned off** while preserving its nominal color assignment ($|-7| = 7$).

`cad-extractor-ir` resolves this automatically:
```python
aci_color = layer.color
is_off = layer.is_off() or aci_color < 0
normalized_aci = abs(aci_color)
hex_color = resolve_aci_to_hex(normalized_aci)
```

### True `BYLAYER` Semantics
To prevent visual distortion when downstream presets apply monochrome or presentation overrides, entity-level colors are set to `None` unless the entity specifies an explicit color override (`color != 256`).

---

## 5. Public API & Usage Reference

### 5.1 Python SDK

```python
from cad_extractor.core import extract_cad_ir
from cad_extractor.models import CADIntermediateRepresentation

# 1. Extract from DWG or DXF file
ir_model: CADIntermediateRepresentation = extract_cad_ir(
    "input_drawing.dwg",
    dwg2dxf_binary="/usr/local/bin/dwg2dxf" # Optional override
)

# 2. Inspect Extracted Metadata
print(f"Drawing Source: {ir_model.metadata.source_file}")
print(f"AutoCAD Version: {ir_model.metadata.cad_version}")
print(f"Total Lines: {ir_model.geometry_primitives.summary.total_lines}")
print(f"Total Arcs: {ir_model.geometry_primitives.summary.total_arcs}")

# 3. Check for Upstream Warnings
if ir_model.metadata.extraction_warnings:
    print(f"Extraction Warnings ({len(ir_model.metadata.extraction_warnings)}):")
    for w in ir_model.metadata.extraction_warnings:
        print(f"  - {w}")

# 4. Serialize to JSON string or dictionary
ir_dict = ir_model.model_dump()
ir_json_string = ir_model.model_dump_json(indent=2)
```

---

### 5.2 Command Line Interface (CLI)

```bash
# Extract to standard JSON output file
python -m cad_extractor.cli input.dwg -o output_ir.json

# Pretty-print summary statistics only
python -m cad_extractor.cli input.dwg --summary

# Force custom LibreDWG binary location
python -m cad_extractor.cli input.dwg -o output_ir.json --dwg2dxf-path /opt/bin/dwg2dxf
```

---

## 6. Failure Modes, Diagnostics & Hardening

| Failure Mode | Root Cause | Engine Mitigation |
| :--- | :--- | :--- |
| **`TimeoutExpired`** | Corrupt block cycle in binary DWG | Adaptive process supervisor kills subprocess after dynamic timeout and attempts `-m` mode. |
| **`Lone Surrogates`** | Unpaired `\ud800` characters in layer/block names | Sanitized via `surrogatepass` pass-through before JSON serialization. |
| **`Negative ACI Crash`** | Frozen/off layer with negative integer color | Absolute value taken before palette lookup; layer marked `is_off=True`. |
| **`ACIS SAT Decode Error`** | Proprietary 3D solid binary records | Patched `_safe_crypt_decode` replacing unencodable bytes with ASCII placeholders. |
| **`Dropped Handles`** | Unsupported proxy objects in LibreDWG | Intercepted on `stderr`, parsed, and returned in `diagnostics.warnings`. |
