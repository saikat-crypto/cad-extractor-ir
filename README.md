# cad-extractor-ir: Headless CAD Ingestion & Geometric Normalization Engine

<div align="center">

[![Python: 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB.svg?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Core Format](https://img.shields.io/badge/Schema-LAVINCI__CAD__IR__V3-6C5CE7.svg?style=for-the-badge)](#)
[![Ingestion Formats](https://img.shields.io/badge/Ingestion-DWG%20%7C%20DXF%20%7C%20DWT-00A86B.svg?style=for-the-badge)](#)
[![Validation](https://img.shields.io/badge/Pydantic-v2.0-E92063.svg?style=for-the-badge&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

**A high-performance, headless CAD binary decompiler lifting proprietary Autodesk `.dwg`, `.dwt` (Templates), and native `.dxf` streams into a standardized, strongly-typed Intermediate Representation (IR v3).**

*Part of the **La Vinci** engineering initiative by **Saikat Dutta Chowdhury** (Mechanical Engineering).*

</div>

---

## 💡 The Mechanical Engineering Challenge

In computational engineering, mechanical designers and automated manufacturing pipelines face a critical roadblock: **Autodesk's binary `.dwg` format is completely closed, proprietary, and undocumented.** 

For over four decades, CAD interoperability has required expensive, heavyweight desktop licenses (AutoCAD, Autodesk Forge / APS, ODA Drawings SDK) that cannot run in lightweight containers, edge compute, or serverless workers.

**`cad-extractor-ir`** solves this by acting as a zero-dependency headless ingestion gateway:
1. Decompiles bit-packed AutoCAD DWG binary streams into clean geometric primitives via an embedded GNU LibreDWG Linux toolchain.
2. Normalizes AutoCAD Color Index (`ACI`), 24-bit TrueColor, layers, line weights, and multi-space viewports.
3. Decodes polyline bulge arc factors ($b = \tan(\Delta\theta/4)$) and parses block attribute tags (`ATTRIB`).
4. Automatically computes spatial extents and aggregates a structured **Bill of Materials (BOM)**.
5. Serializes geometry into the canonical **`LAVINCI_CAD_IR_V3`** JSON contract.

```
                         [ Input: mechanical_assembly.dwg ]
                                         │
                                         ▼
                ┌──────────────────────────────────────────────────┐
                │          cad-extractor-ir Pipeline               │
                │                                                  │
                │  1. Binary Decompilation (GNU LibreDWG C)        │
                │     • Bitstream decoding, handles, object pages  │
                │     • Adaptive timeout supervision               │
                │     • Minimal-mode (-m) recovery heuristic       │
                │                                                  │
                │  2. Low-Level Ingestion & Crypto Patching        │
                │     • Patched ACIS SAT cryptographic decoding    │
                │     • Lone Unicode surrogate sanitization        │
                │                                                  │
                │  3. Geometric Normalization (ezdxf + Pydantic)   │
                │     • Polyline bulge decomposition (tan(Δθ/4))   │
                │     • ACI palette to 24-bit hex color mapping    │
                │     • Block definition tables & transform matrix │
                │     • Automated Bill of Materials (BOM) counting │
                └──────────────────────────────────────────────────┘
                                         │
                                         ▼
                      [ LAVINCI_CAD_IR_V3 Structured JSON ]
                                         │
       ┌─────────────────────┬───────────┴───────────┬─────────────────────┐
       ▼                     ▼                       ▼                     ▼
[ cad-ir-to-dxf ]     [ cad-ir-to-pdf ]       [ cad-ir-to-svg ]     [ cad-ir-to-raster ]
  (CNC R12 Toolpaths)   (Vector Blueprints)     (Web Digital Twins)   (AI Vision PNGs)
```

---

## 🔬 Systems Engineering & Reliability Hardening

### 1. Adaptive Subprocess Timeout & Minimal-Mode (`-m`) Fallback
Corrupted DWG files frequently trigger infinite pointer loops in C decoders. `cad-extractor-ir` wraps the binary subprocess in an adaptive timeout supervisor:
$$\text{Timeout}_{\text{adaptive}} = \min\left(300, \; \max(45, \lceil\text{Size}_{\text{MB}} \times 30\rceil)\right) \text{ seconds}$$
If standard decompression encounters a non-zero exit code or corrupted block tables, the engine automatically triggers **Minimal-Mode (`-m`) Fallback**, instructing the C decompiler to skip auxiliary metadata dictionaries and extract surviving 2D linework that commercial software rejects.

### 2. Lone Unicode Surrogate Neutralization
CAD files authored across international engineering firms often contain orphan half-surrogate code points ($0\text{xD800} \le c \le 0\text{xDFFF}$) in layer or block names, which fatally crash standard UTF-8 JSON encoders. `cad-extractor-ir` intercepts strings with a dual `surrogatepass` filter:
```python
def sanitize_surrogates(text: str) -> str:
    try:
        return text.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
    except Exception:
        return "".join(c for c in text if not (0xD800 <= ord(c) <= 0xDFFF))
```

### 3. Polyline Bulge Decomposition
AutoCAD stores curved polylines as discrete vertices paired with a mathematical **bulge factor** $b$:
$$b = \tan\left(\frac{\Delta\theta}{4}\right)$$
Where $\Delta\theta$ is the included angle. `cad-extractor-ir` decomposes these bulges into planar coordinate sequences using adaptive chord-height tolerance, maintaining sub-micron accuracy.

### 4. Transparent Upstream Warning Diagnostics
When LibreDWG drops proprietary 3D ACIS solids or corrupt proxy objects, `cad-extractor-ir` intercepts `stderr`, harvests warning tokens, and exposes them in `metadata.extraction_warnings`. Downstream applications can alert users transparently rather than failing silently.

---

## ⚡ Quick Start

### Installation
```bash
pip install -e products/cad-extractor-ir
```

### Python SDK
```python
from cad_extractor.core import extract_cad_ir

# Extract from binary DWG, DXF, or DWT template
ir = extract_cad_ir("gearbox_assembly.dwg")

# Inspect structured metadata
print(f"Drawing Version: {ir.metadata.cad_version}")
print(f"Units: {ir.metadata.measurement_system} (Code: {ir.metadata.units})")
print(f"Total Lines: {ir.geometry_primitives.summary.total_lines}")
print(f"Bill of Materials: {ir.bill_of_materials}")

# Export strongly-typed JSON
with open("assembly_ir.json", "w", encoding="utf-8") as f:
    f.write(ir.model_dump_json(indent=2))
```

### Command Line Interface (CLI)
```bash
# Decompile DWG to IR JSON
python -m cad_extractor.cli drawing.dwg -o drawing_ir.json

# Display summary statistics only
python -m cad_extractor.cli drawing.dwg --summary
```

---

## 📄 License

Licensed under the [MIT License](LICENSE).
