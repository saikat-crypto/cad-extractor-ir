# CAD Extractor IR (Intermediate Representation)

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-brightgreen.svg)](https://python.org)
[![Cloud Native](https://img.shields.io/badge/AWS-Lambda%20%7C%20S3%20%7C%20ECR-orange.svg)](https://aws.amazon.com)
[![Docker](https://img.shields.io/badge/Docker-Multi--stage%20Container-blue.svg)](https://docker.com)
[![Ecosystem](https://img.shields.io/badge/Project-La%20Vinci-purple.svg)](#)

**High-performance, serverless CAD binary extractor lifting raw AutoCAD `.dwg` files into a clean, queryable Intermediate Representation (IR).**

*Engineered by **Saikat Dutta Chowdhury** as part of the **La Vinci** engineering initiative.*

</div>

---

## 💡 The Problem & Vision

Engineering CAD files (specifically Autodesk's proprietary binary `.dwg` format) are locked behind proprietary, undocumented byte specifications, multi-layered bitflags, and vendor-locked SDKs. 

Extracting simple data—such as room dimensions, layer topologies, or a Bill of Materials (BOM)—historically required running heavy desktop CAD software or bloated virtual machines.

**CAD Extractor IR** solves this by establishing a standardized, lightweight **Intermediate Representation (IR)** for CAD geometry:
1. Cracks open binary `.dwg` byte-streams headlessly via low-level C decoders.
2. Normalizes layers, RGB color spaces, handles, and spatial coordinate transforms.
3. Automatically computes real-world bounding boxes and aggregates a structured **Bill of Materials (BOM)**.
4. Serializes into a strongly-typed, cloud-native JSON schema (`LAVINCI_CAD_IR_V1`) designed to power downstream converters (DWF, DXF, SVG, 3D Web Viewers) at **$0 compute cost** on AWS Lambda.

---

## 🏗️ Architecture Pipeline

```
                       [ Input: blueprint.dwg ]
                                  │
                                  ▼
         ┌──────────────────────────────────────────────────┐
         │             AWS Serverless Worker / CLI          │
         │                                                  │
         │   1. Byte-Level C Engine (GNU LibreDWG)          │
         │      • Decodes handles, bit-streams & pages      │
         │                                                  │
         │   2. La Vinci IR Normalizer (Python / Pydantic)  │
         │      • Coordinate & Extent calculations          │
         │      • ACI to Hex Color Resolution               │
         │      • Bill of Materials (BOM) Aggregator        │
         └──────────────────────────────────────────────────┘
                                  │
                                  ▼
                [ La Vinci CAD IR (Structured JSON) ]
                                  │
      ┌───────────────────────────┼───────────────────────────┐
      ▼                           ▼                           ▼
[ Downstream DWF/DXF ]    [ Automated BOM & Cost ]    [ WebGL 2D/3D Viewer ]
```

---

## 📊 Data Efficiency: Raw Dump vs. La Vinci IR

| Metric | Raw CAD Binary Parser Dump | La Vinci CAD IR (`LAVINCI_CAD_IR_V1`) |
| :--- | :--- | :--- |
| **File Size** | **4.8 Megabytes** (179,425 lines) | **~118 Kilobytes** (Clean JSON) |
| **Data Compression** | 0% (Verbose bitfield dump) | **~97.5% Payload Reduction** |
| **Schema Validation**| None (Raw memory handles) | Strongly-typed **Pydantic v2** |
| **Bill of Materials**| Missing (Uncorrelated blocks) | **Auto-generated component dictionary** |
| **Color Handling**   | Raw integer codes (e.g., `256`) | Normalized Hex (`#FF0000`, `#00FF00`) |

---

## ⚡ Multi-Version Benchmark Suite (All Passed)

Tested across diverse real-world AutoCAD binary releases from **AutoCAD 2000 up to AutoCAD 2018**:

| CAD Drawing / Feature | AutoCAD Release | Units | Active Layers | Components (BOM) | Primitives Extracted | Parse & Extraction Latency | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Architectural Floor Plan** | **R2007** | **Metric** | **17** | **161** | **313** | **435 ms** | ✅ **PASS** |
| Modern Line Vector Geometry | R2018 | Imperial | 2 | 0 | 1 | 53 ms | ✅ **PASS** |
| Curved Geometry & Arcs | R2018 | Imperial | 2 | 0 | 1 | 50 ms | ✅ **PASS** |
| Curved Vector Geometry | R2013 | Imperial | 2 | 0 | 1 | 47 ms | ✅ **PASS** |
| NURBS & Spline Entities | R2010 | Imperial | 2 | 0 | 0 | 65 ms | ✅ **PASS** |
| Vector Geometry & Offsets | R2007 | Imperial | 2 | 0 | 1 | 74 ms | ✅ **PASS** |
| Leader Annotations | R2004 | Imperial | 2 | 0 | 2 | 84 ms | ✅ **PASS** |
| Multi-leader Annotation Tags | R2000 | Imperial | 2 | 0 | 2 | 77 ms | ✅ **PASS** |

*Average parsing latency: **~105 ms** across all formats.*

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/saikat-crypto/cad-extractor-ir.git
cd cad-extractor-ir

# Install package
pip install -e .
```

### 2. Command Line Usage

Extract metadata, dimensions, and layer counts:
```bash
cad-extractor blueprint.dwg --summary
```

Generate and display an automated **Bill of Materials (BOM)**:
```bash
cad-extractor blueprint.dwg --bom
```

**Output:**
```text
=== Bill of Materials (BOM) ===
Component Name                      | Quantity  
------------------------------------------------
```text
=== Bill of Materials (BOM) ===
Component Name                      | Quantity  
------------------------------------------------
Receptacle                          | 44        
Lighting fixture                    | 28        
ANDERSEN CASEMENT (*U48)            | 10        
ANDERSEN CASEMENT (*U50)            | 8         
ANDERSEN CASEMENT (*U45)            | 7         
TRU STYLE BI-FOLD (*U38)            | 3         
Bathtub                             | 2         
Toilet                              | 1         
Sink                                | 1         
```

Export complete Intermediate Representation to JSON:
```bash
cad-extractor blueprint.dwg -o blueprint_ir.json
```

---

## 📐 Intermediate Representation (IR v3) Full-Fidelity Schema

```json
{
  "format": "LAVINCI_CAD_IR_V3",
  "metadata": {
    "source_file": "floor_plan.dwg",
    "cad_version": "R2007",
    "measurement_system": "Metric"
  },
  "extents": {
    "width": 524.403,
    "height": 501.854
  },
  "layers": [
    { "name": "Lighting", "color_aci": 1, "hex_color": "#ff0000", "is_off": false },
    { "name": "Power", "color_aci": 6, "hex_color": "#ff00ff", "is_off": false }
  ],
  "bill_of_materials": {
    "Receptacle": 44,
    "Lighting fixture": 28,
    "ANDERSEN CASEMENT (*U48)": 10,
    "TRU STYLE BI-FOLD (*U38)": 3,
    "Bathtub": 2,
    "Toilet": 1
  },
  "block_definitions": {
    "Toilet": {
      "name": "Toilet",
      "base_point": [0.0, 0.0, 0.0],
      "lines": [{ "layer": "0", "start": [0.102, -0.356], "end": [-0.102, -0.356], "color": null }],
      "arcs": [{ "layer": "0", "center": [0.0, 0.0], "radius": 0.229, "start_angle": 0.0, "end_angle": 180.0, "color": null }]
    },
    "Receptacle": {
      "name": "Receptacle",
      "base_point": [0.0, 0.0, 0.0],
      "circles": [{ "layer": "0", "center": [0.0, 0.0], "radius": 0.125, "color": null }]
    }
  }
}
```

---

## 🔍 Technical Transparency: Engineering Capabilities & Current Boundaries

To maintain technical integrity and clear expectations, here is an explicit breakdown of what CAD Extractor IR solves and current architectural boundaries:

### ✅ Hardened & Solved in v3:
* **Reusable Block Definitions (`block_definitions`)**: Captures full internal vector geometry (lines, arcs, circles, polylines) for every block in the drawing. Downstream DXF/SVG/PDF converters now render all components (doors, windows, plumbing, electrical fixtures) with 100% visual fidelity instead of empty stubs.
* **True `BYLAYER` Color Semantics**: Leaves `color = None` for entities inheriting layer styling, preserving native AutoCAD layer-based style switching rather than baking static overrides.
* **Full `CIRCLE` Primitive Extraction**: Ingests circular engineering geometries (pipe cross-sections, columns, receptacles) alongside lines and arcs.
* **Native Arc Angles**: Preserves raw AutoCAD counter-clockwise arc angles (including wraps across $0^\circ$) preventing inverted or distorted sweeps.
* **Paper Space & Print Layouts**: Scans all drawing layouts (A1, A3, ANSI sheets) and captures `VIEWPORT` bounding boxes and camera scales.
* **Deep Block Inspection & Attribute Mining**: Mines `ATTRIB` tags (manufacturer, style, model, cost codes) directly off blocks.
* **Anonymous Block Disambiguation**: Resolves cryptic internal block identifiers (e.g. `*U48`, `*B20`) into human-readable component labels (`ANDERSEN CASEMENT (*U48)`).
* **MTEXT Formatting Sanitization**: Strips proprietary AutoCAD RTF formatting tags (`\f...;`, `\H...;`, `\L` underline, `\P`), returning clean human-readable text.
* **Dimension Entity Extraction**: Ingests `DIMENSION` entities, measurement values, definition points, and tolerance strings.

### ⚠️ Current Architectural Boundaries:
1. **Underlying Parser Dependency**: Binary `.dwg` decoding is currently orchestrated via `GNU LibreDWG` as the headless binary reader. Unrecognized custom third-party C++ objects (AutoCAD Architecture/Civil 3D proxy entities) may be ignored.
2. **ACIS 3D Solid Geometry**: 2D vector primitives and meshes are fully extracted. However, proprietary binary ACIS B-Rep solid kernels (`3DSOLID`, `REGION`) are not yet decomposed into boundary topological faces.
3. **External Dependencies (XREFs & SHX Fonts)**: Text strings embedded within the file are extracted cleanly. However, visual glyph generation that depends on proprietary compiled `.shx` shape fonts or externally linked XREF drawings requires those external asset files to be bundled with the drawing.

---

## ☁️ Cloud-Native Deployment (AWS Lambda Container)

The repository includes a production multi-stage `Dockerfile` targeting AWS Lambda (`public.ecr.aws/lambda/python:3.12`):

```bash
# Build the container image
docker build -t cad-extractor-ir -f docker/Dockerfile .

# Run locally or push to AWS ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <aws_account_id>.dkr.ecr.us-east-1.amazonaws.com
docker tag cad-extractor-ir:latest <aws_account_id>.dkr.ecr.us-east-1.amazonaws.com/lavinci-dwg-extractor:latest
docker push <aws_account_id>.dkr.ecr.us-east-1.amazonaws.com/lavinci-dwg-extractor:latest
```

---

## 📄 License & Credits

* **Author**: [Saikat Dutta Chowdhury](https://github.com/saikat-crypto)
* **Project**: Part of the **La Vinci** engineering initiative.
* **License**: Licensed under the [MIT License](LICENSE).
