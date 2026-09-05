# CAD Examples & Extraction Gallery

This directory contains real-world AutoCAD `.dwg` binary files spanning **AutoCAD 2000 through AutoCAD 2018**, paired with their corresponding extracted **La Vinci CAD IR (Intermediate Representation)** output JSON files.

---

## 📂 Gallery of Real Inputs & Extracted Outputs

| CAD Release | Input Binary Drawing (`.dwg`) | Extracted Intermediate Representation (`.json`) | Key Extracted Content |
| :--- | :--- | :--- | :--- |
| **R2007 (Floor Plan)** | [`blueprint_sample.dwg`](blueprint_sample.dwg) | [`blueprint_sample_ir.json`](blueprint_sample_ir.json) | 17 layers, 161 components (BOM: Receptacles, Bathtubs, Sinks), 313 primitives |
| **R2018 (Modern)** | [`2018_Line.dwg`](2018_Line.dwg) | [`2018_Line_ir.json`](2018_Line_ir.json) | Modern AutoCAD 2018 vector lines & extents |
| **R2018 (Modern)** | [`2018_Arc.dwg`](2018_Arc.dwg) | [`2018_Arc_ir.json`](2018_Arc_ir.json) | Modern AutoCAD 2018 arc center points, radii, and angles |
| **R2013** | [`2013_Arc.dwg`](2013_Arc.dwg) | [`2013_Arc_ir.json`](2013_Arc_ir.json) | Vector arc geometry & coordinate bounding box |
| **R2010** | [`2010_Spline.dwg`](2010_Spline.dwg) | [`2010_Spline_ir.json`](2010_Spline_ir.json) | Complex NURBS curve definitions & layer settings |
| **R2007** | [`2007_Line.dwg`](2007_Line.dwg) | [`2007_Line_ir.json`](2007_Line_ir.json) | Vector lines and layer tables |
| **R2004** | [`2004_Leader.dwg`](2004_Leader.dwg) | [`2004_Leader_ir.json`](2004_Leader_ir.json) | Leader annotation geometry & points |
| **R2000 (Legacy)** | [`2000_Leader.dwg`](2000_Leader.dwg) | [`2000_Leader_ir.json`](2000_Leader_ir.json) | Legacy AutoCAD 2000 multi-leader tags & text points |

---

## 🔍 Side-by-Side Example: Architectural Blueprint

### Input DWG
* **File**: `blueprint_sample.dwg` (258 KB binary AutoCAD drawing)

### Output CAD IR (`blueprint_sample_ir.json`):
```json
{
  "format": "LAVINCI_CAD_IR_V1",
  "metadata": {
    "source_file": "blueprint_sample.dwg",
    "cad_version": "R2007",
    "measurement_system": "Metric"
  },
  "extents": {
    "width": 25.444,
    "height": 16.478
  },
  "bill_of_materials": {
    "Receptacle": 44,
    "Lighting fixture": 28,
    "Bathtub": 2,
    "Toilet": 1,
    "Sink": 1
  }
}
```
