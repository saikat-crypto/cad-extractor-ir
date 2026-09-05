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
Receptacle                          | 44        
Lighting fixture                    | 28        
Bathtub                             | 2         
Toilet                              | 1         
Sink                                | 1         
```

Export complete Intermediate Representation to JSON:
```bash
cad-extractor blueprint.dwg -o blueprint_ir.json
```

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

## 📐 Intermediate Representation (IR) Sample Schema

For the full detailed schema, design choices, and field reference, see [CAD_IR_SPECIFICATION.md](docs/CAD_IR_SPECIFICATION.md).

```json
{
  "format": "LAVINCI_CAD_IR_V1",
  "metadata": {
    "source_file": "floor_plan.dwg",
    "cad_version": "R2007",
    "measurement_system": "Metric"
  },
  "extents": {
    "width": 25.444,
    "height": 16.478
  },
  "layers": [
    { "name": "Lighting", "hex_color": "#FF0000", "is_off": false },
    { "name": "Power", "hex_color": "#FF00FF", "is_off": false }
  ],
  "bill_of_materials": {
    "Receptacle": 44,
    "Lighting fixture": 28,
    "Bathtub": 2,
    "Toilet": 1
  }
}
```

---

## 📄 License & Credits

* **Author**: [Saikat Dutta Chowdhury](https://github.com/)
* **Project**: Part of the **La Vinci** engineering initiative.
* **License**: Licensed under the [MIT License](LICENSE).
