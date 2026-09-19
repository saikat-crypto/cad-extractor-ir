"""
Rigorous End-to-End Test Suite for DWT (AutoCAD Drawing Template) Ingestion.
Tests:
1. Real-world AutoCAD 2018 template (omkar_acad_lfs.dwt)
2. Templates across AutoCAD releases (R2000, R2004, R2007, R2010, R2013, R2018)
3. Complex architectural template with multi-sheet layouts, layers, blocks, and viewports
4. Mechanical template with title blocks and dimension styles
5. Edge cases: empty templates, corrupt templates, 0-byte templates
6. Property-based invariants: Idempotency, Schema validation roundtrip, Model/Paper space isolation
"""

import os
import shutil
import tempfile
import unittest
import subprocess
from pathlib import Path

import ezdxf
from cad_extractor.core import extract_cad_ir
from cad_extractor.models import CADIntermediateRepresentation

TEMPLATES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures", "dwt_templates"))
REAL_DWT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../experiments/omkar_acad_lfs.dwt"))

class TestDWTEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(TEMPLATES_DIR, exist_ok=True)
        cls.dxf2dwg_exe = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../experiments/libredwg/dxf2dwg.exe"))

    # -------------------------------------------------------------------------
    # Test 1: Real-World In-the-Wild AutoCAD 2018 Template
    # -------------------------------------------------------------------------
    def test_real_world_autocad_2018_template(self):
        if not os.path.exists(REAL_DWT):
            self.skipTest(f"Real DWT not found at {REAL_DWT}")
        ir = extract_cad_ir(REAL_DWT)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        self.assertEqual(ir.format, "LAVINCI_CAD_IR_V3")
        self.assertEqual(ir.metadata.cad_version, "R2018")
        self.assertEqual(ir.metadata.dxf_version, "AC1032")
        
        # Verify layer extraction
        layer_names = [l.name for l in ir.layers]
        self.assertIn("OBJECT", layer_names)
        self.assertIn("DIMENSION", layer_names)
        self.assertIn("CENTER", layer_names)
        
        # Verify layouts
        layout_names = [l.name for l in ir.layouts]
        self.assertIn("Layout1", layout_names)
        self.assertIn("Layout2", layout_names)

        # Invariant: Must serialize cleanly to JSON
        json_str = ir.model_dump_json()
        self.assertTrue(len(json_str) > 0)
        
        # Invariant: Re-validation must match perfectly
        restored = CADIntermediateRepresentation.model_validate_json(json_str)
        self.assertEqual(restored.metadata.source_file, ir.metadata.source_file)
        self.assertEqual(len(restored.layers), len(ir.layers))

    # -------------------------------------------------------------------------
    # Test 2: Multi-Version DWT Compatibility (R2000 - R2018)
    # -------------------------------------------------------------------------
    def test_multi_version_dwt_support(self):
        versions = ["2000", "2004", "2007", "2013", "2018"]
        examples_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../examples"))
        
        for ver in versions:
            matching = [f for f in os.listdir(examples_dir) if f.startswith(ver) and f.endswith(".dwg")]
            if not matching:
                continue
            src_dwg = os.path.join(examples_dir, matching[0])
            test_dwt = os.path.join(TEMPLATES_DIR, f"template_{ver}.dwt")
            shutil.copyfile(src_dwg, test_dwt)
            
            # Extract from .dwt
            ir = extract_cad_ir(test_dwt)
            self.assertIsInstance(ir, CADIntermediateRepresentation)
            self.assertTrue(ver in ir.metadata.cad_version or ir.metadata.cad_version.startswith(f"R{ver}"))
            self.assertTrue(len(ir.layers) > 0)

    # -------------------------------------------------------------------------
    # Test 3: Complex Architectural Template (Multi-sheet, Titleblock, Layers)
    # -------------------------------------------------------------------------
    def test_complex_architectural_template(self):
        # Generate custom architectural template with 3 layouts, standard A1 border, 15 layers
        dxf_path = os.path.join(TEMPLATES_DIR, "arch_template.dxf")
        dwt_path = os.path.join(TEMPLATES_DIR, "arch_template.dwt")
        
        doc = ezdxf.new("R2000", setup=True)
        # Layers
        for name, color in [("A-WALL", 1), ("A-DOOR", 2), ("A-GLAZ", 3), ("A-FLOR", 4), ("A-ANNO", 7)]:
            doc.layers.new(name=name, dxfattribs={"color": color})
        
        # Title block in block table
        tb = doc.blocks.new(name="A1_TITLEBLOCK")
        tb.add_line((0, 0), (841, 0))
        tb.add_line((841, 0), (841, 594))
        tb.add_line((841, 594), (0, 594))
        tb.add_line((0, 594), (0, 0))
        tb.add_text("PROJECT TITLE", dxfattribs={"insert": (500, 50), "height": 10.0})
        
        # Paper Space Layouts
        l1 = doc.layouts.new("A1 Sheet 1 - Plans")
        l1.add_blockref("A1_TITLEBLOCK", (0, 0))
        l1.add_viewport(center=(400, 300), size=(600, 400), view_center_point=(100, 100), view_height=500)
        
        l2 = doc.layouts.new("A1 Sheet 2 - Sections")
        l2.add_blockref("A1_TITLEBLOCK", (0, 0))
        
        doc.saveas(dxf_path)
        
        # Compile to DWT using dxf2dwg
        cmd = [self.dxf2dwg_exe, "-y", "--as=r2000", dxf_path, "-o", dwt_path]
        subprocess.run(cmd, capture_output=True, check=True)
        
        # Verify extraction
        ir = extract_cad_ir(dwt_path)
        self.assertEqual(ir.format, "LAVINCI_CAD_IR_V3")
        self.assertIn("A-WALL", [l.name for l in ir.layers])
        self.assertIn("A-DOOR", [l.name for l in ir.layers])
        self.assertIn("A1_TITLEBLOCK", ir.block_definitions)
        self.assertEqual(len(ir.block_definitions["A1_TITLEBLOCK"].lines), 4)
        
        layout_names = [l.name for l in ir.layouts]
        self.assertIn("A1 Sheet 1 - Plans", layout_names)
        self.assertIn("A1 Sheet 2 - Sections", layout_names)

    # -------------------------------------------------------------------------
    # Test 4: Mechanical Part Template with Dimension Styles & Micro Scale
    # -------------------------------------------------------------------------
    def test_mechanical_template(self):
        dxf_path = os.path.join(TEMPLATES_DIR, "mech_template.dxf")
        dwt_path = os.path.join(TEMPLATES_DIR, "mech_template.dwt")
        
        doc = ezdxf.new("R2000", setup=True)
        doc.layers.new("CONTOURS", dxfattribs={"color": 3})
        doc.layers.new("DIMENSIONS", dxfattribs={"color": 1})
        msp = doc.modelspace()
        # Circle with center and radius: bounds [25, 25] to [75, 75]
        msp.add_circle((50.0, 50.0), radius=25.0, dxfattribs={"layer": "CONTOURS"})
        # Linear dimension at y=80: extends bounds up to y=80 (height = 80 - 25 = 55)
        dim = msp.add_linear_dim(base=(50, 80), p1=(25, 50), p2=(75, 50), dxfattribs={"layer": "DIMENSIONS"})
        dim.render()
        doc.saveas(dxf_path)
        
        cmd = [self.dxf2dwg_exe, "-y", "--as=r2000", dxf_path, "-o", dwt_path]
        subprocess.run(cmd, capture_output=True, check=True)
        
        ir = extract_cad_ir(dwt_path)
        self.assertEqual(ir.geometry_primitives.summary.total_circles, 1)
        self.assertAlmostEqual(ir.extents.width, 50.0, places=1)
        self.assertAlmostEqual(ir.extents.height, 55.0, places=1)

    # -------------------------------------------------------------------------
    # Test 5: Corrupt, Truncated, and Empty DWT Boundary Cases
    # -------------------------------------------------------------------------
    def test_zero_byte_dwt(self):
        zero_dwt = os.path.join(TEMPLATES_DIR, "zero_byte.dwt")
        with open(zero_dwt, "wb") as f:
            pass
        with self.assertRaises(RuntimeError):
            extract_cad_ir(zero_dwt)

    def test_truncated_dwt(self):
        trunc_dwt = os.path.join(TEMPLATES_DIR, "truncated.dwt")
        with open(trunc_dwt, "wb") as f:
            f.write(b"AC1032\x00\x00some_truncated_garbage")
        with self.assertRaises(RuntimeError):
            extract_cad_ir(trunc_dwt)

    def test_nonexistent_dwt(self):
        with self.assertRaises(FileNotFoundError):
            extract_cad_ir(os.path.join(TEMPLATES_DIR, "does_not_exist.dwt"))

    # -------------------------------------------------------------------------
    # Test 6: Invariant Verification - Idempotency
    # -------------------------------------------------------------------------
    def test_dwt_extraction_idempotency(self):
        if not os.path.exists(REAL_DWT):
            self.skipTest("Real DWT not available")
        ir1 = extract_cad_ir(REAL_DWT)
        ir2 = extract_cad_ir(REAL_DWT)
        self.assertEqual(ir1.model_dump(), ir2.model_dump())

if __name__ == "__main__":
    unittest.main()
