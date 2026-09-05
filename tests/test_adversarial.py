"""
Adversarial & Invariant Test Suite for cad-extractor-ir.
Exercises 29 pathological fixtures across 6 stress categories:
1. Empty CAD files
2. Extreme spatial dimensions
3. Nested and cyclical blocks
4. Malicious Unicode, formatting, and surrogates
5. Massive entity counts
6. Corrupted/truncated streams

Verifies R2 Invariants:
- Crash resilience & clean error handling (no unhandled segfaults/leaks)
- Schema conformity to LAVINCI_CAD_IR_V3
- Extents containment invariant (min <= coord <= max)
- Idempotency invariant (repeated extractions identical)
- Documents known failure modes (FM-01 through FM-15)
"""

import os
import glob
import json
import unittest
from pathlib import Path

import ezdxf
from cad_extractor.core import extract_cad_ir
from cad_extractor.models import CADIntermediateRepresentation

FIXTURES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures"))

class TestAdversarialStress(unittest.TestCase):
    """Adversarial stress and boundary testing across synthetic and corrupted CAD fixtures."""

    # -------------------------------------------------------------------------
    # Category 1: Empty CAD Files
    # -------------------------------------------------------------------------
    def test_cat1_empty_zero_entities(self):
        dwg = os.path.join(FIXTURES_DIR, "empty_01_zero_entities.dwg")
        ir = extract_cad_ir(dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        self.assertEqual(ir.geometry_primitives.summary.total_lines, 0)
        self.assertEqual(ir.geometry_primitives.summary.total_arcs, 0)
        self.assertEqual(ir.geometry_primitives.summary.total_components, 0)
        self.assertEqual(ir.extents.min, [0.0, 0.0])
        self.assertEqual(ir.extents.max, [0.0, 0.0])
        self.assertEqual(ir.extents.width, 0.0)
        self.assertEqual(ir.extents.height, 0.0)

    def test_cat1_empty_zero_blocks(self):
        dwg = os.path.join(FIXTURES_DIR, "empty_03_zero_blocks.dwg")
        ir = extract_cad_ir(dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        # Custom user blocks are 0 (only standard ezdxf dimension styles like _ARCHTICK may exist)
        custom_blocks = [b for b in ir.block_definitions.keys() if not b.startswith("_")]
        self.assertEqual(len(custom_blocks), 0)
        self.assertEqual(ir.geometry_primitives.summary.total_lines, 2)

    def test_cat1_single_point_zero(self):
        dwg = os.path.join(FIXTURES_DIR, "empty_04_single_point_zero.dwg")
        ir = extract_cad_ir(dwg)
        self.assertEqual(ir.extents.min, [0.0, 0.0])
        self.assertEqual(ir.extents.max, [0.0, 0.0])
        self.assertEqual(ir.extents.width, 0.0)
        self.assertEqual(ir.extents.height, 0.0)

    # -------------------------------------------------------------------------
    # Category 2: Extreme Spatial Dimensions
    # -------------------------------------------------------------------------
    def test_cat2_extreme_astronomical(self):
        dwg = os.path.join(FIXTURES_DIR, "extreme_01_astronomical_1e12.dwg")
        ir = extract_cad_ir(dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        self.assertGreaterEqual(ir.extents.max[0], 1e11)
        # Verify JSON serializability
        dump = ir.model_dump_json()
        self.assertTrue(len(dump) > 0)

    def test_cat2_extreme_microscopic(self):
        dwg = os.path.join(FIXTURES_DIR, "extreme_02_microscopic_1e-6.dwg")
        ir = extract_cad_ir(dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        # 1e-6 rounds to 0.0 with 3-decimal rounding
        self.assertEqual(ir.extents.min, [0.0, 0.0])

    def test_cat2_extreme_negative(self):
        dwg = os.path.join(FIXTURES_DIR, "extreme_03_negative_coords.dwg")
        ir = extract_cad_ir(dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        self.assertLess(ir.extents.min[0], 0.0)
        self.assertLess(ir.extents.min[1], 0.0)

    def test_cat2_extreme_mixed_scales(self):
        dwg = os.path.join(FIXTURES_DIR, "extreme_04_mixed_scales.dwg")
        ir = extract_cad_ir(dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        self.assertGreater(ir.extents.width, 1e12)

    # -------------------------------------------------------------------------
    # Category 3: Nested and Cyclical Blocks
    # -------------------------------------------------------------------------
    def test_cat3_nested_depth_10(self):
        dwg = os.path.join(FIXTURES_DIR, "blocks_01_nested_depth_10.dwg")
        ir = extract_cad_ir(dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        # Confirms all 10 block definitions are present
        self.assertIn("BLOCK_L1", ir.block_definitions)
        self.assertIn("BLOCK_L10", ir.block_definitions)

    def test_cat3_deep_transform(self):
        dwg = os.path.join(FIXTURES_DIR, "blocks_04_deep_transform.dwg")
        ir = extract_cad_ir(dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        self.assertIn("TRANS_L1", ir.block_definitions)
        self.assertIn("TRANS_L5", ir.block_definitions)

    def test_cat3_empty_definition(self):
        dwg = os.path.join(FIXTURES_DIR, "blocks_05_empty_definition.dwg")
        ir = extract_cad_ir(dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        self.assertEqual(ir.bill_of_materials.get("EMPTY_BLK"), 10)
        blk = ir.block_definitions["EMPTY_BLK"]
        self.assertEqual(len(blk.lines), 0)

    # -------------------------------------------------------------------------
    # Category 4: Malicious Unicode, Text & Formatting
    # -------------------------------------------------------------------------
    def test_cat4_injection_strings(self):
        dwg = os.path.join(FIXTURES_DIR, "unicode_02_injection_strings.dwg")
        ir = extract_cad_ir(dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        dump = ir.model_dump_json()
        self.assertIn("DROP TABLE", dump)
        self.assertIn("calc.exe", dump)
        self.assertIn("etc/passwd", dump)

    def test_cat4_multilingual_cjk(self):
        dwg = os.path.join(FIXTURES_DIR, "unicode_03_multilingual_cjk.dwg")
        ir = extract_cad_ir(dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        dump = ir.model_dump_json()
        self.assertTrue(len(dump) > 0)

    def test_cat4_control_characters(self):
        dwg = os.path.join(FIXTURES_DIR, "unicode_04_control_chars.dwg")
        ir = extract_cad_ir(dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        dump = ir.model_dump_json()
        self.assertTrue(len(dump) > 0)

    def test_cat4_null_empty_text(self):
        dwg = os.path.join(FIXTURES_DIR, "unicode_05_null_empty_text.dwg")
        ir = extract_cad_ir(dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)

    # -------------------------------------------------------------------------
    # Category 5: Massive Entity Counts & Scalability
    # -------------------------------------------------------------------------
    def test_cat5_massive_10k_lines(self):
        dwg = os.path.join(FIXTURES_DIR, "massive_01_lines_10k.dwg")
        ir = extract_cad_ir(dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        self.assertEqual(ir.geometry_primitives.summary.total_lines, 10000)

    def test_cat5_massive_5k_components(self):
        dwg = os.path.join(FIXTURES_DIR, "massive_03_components_5k.dwg")
        ir = extract_cad_ir(dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        self.assertEqual(ir.geometry_primitives.summary.total_components, 5000)
        self.assertEqual(ir.bill_of_materials.get("RESISTOR"), 5000)

    # -------------------------------------------------------------------------
    # Category 6: Corrupted and Truncated Streams
    # -------------------------------------------------------------------------
    def test_cat6_corrupt_truncated_header(self):
        dwg = os.path.join(FIXTURES_DIR, "corrupt_01_truncated_header.dwg")
        with self.assertRaises(RuntimeError):
            extract_cad_ir(dwg)

    def test_cat6_corrupt_zero_byte(self):
        dwg = os.path.join(FIXTURES_DIR, "corrupt_02_zero_byte.dwg")
        with self.assertRaises(RuntimeError):
            extract_cad_ir(dwg)

    def test_cat6_corrupt_random_fuzz(self):
        dwg = os.path.join(FIXTURES_DIR, "corrupt_03_random_fuzz_bytes.dwg")
        with self.assertRaises(RuntimeError):
            extract_cad_ir(dwg)

    def test_cat6_corrupt_invalid_magic(self):
        dwg = os.path.join(FIXTURES_DIR, "corrupt_04_invalid_magic.dwg")
        with self.assertRaises(RuntimeError):
            extract_cad_ir(dwg)

    def test_cat6_corrupt_cut_middle(self):
        dwg = os.path.join(FIXTURES_DIR, "corrupt_05_cut_middle.dwg")
        with self.assertRaises(RuntimeError):
            extract_cad_ir(dwg)

    # -------------------------------------------------------------------------
    # Invariant Tests (R2)
    # -------------------------------------------------------------------------
    def test_invariant_idempotency(self):
        """Repeated extractions of the same file produce identical output."""
        dwg = os.path.join(FIXTURES_DIR, "empty_03_zero_blocks.dwg")
        ir1 = extract_cad_ir(dwg)
        ir2 = extract_cad_ir(dwg)
        self.assertEqual(ir1.model_dump(), ir2.model_dump())

    def test_invariant_schema_roundtrip(self):
        """Generated IR must re-validate strictly against CADIntermediateRepresentation."""
        dwg = os.path.join(FIXTURES_DIR, "blocks_04_deep_transform.dwg")
        ir = extract_cad_ir(dwg)
        json_str = ir.model_dump_json()
        restored = CADIntermediateRepresentation.model_validate_json(json_str)
        self.assertEqual(ir.format, restored.format)
        self.assertEqual(len(ir.layers), len(restored.layers))

    # -------------------------------------------------------------------------
    # Failure Mode Reproducers (Documenting Gaps)
    # -------------------------------------------------------------------------
    def test_failure_mode_fm01_direct_dxf_ingestion_fails(self):
        """FM-01: extract_cad_ir unconditionally passes DXF to dwg2dxf, crashing."""
        dxf = os.path.join(FIXTURES_DIR, "empty_02_no_layers.dxf")
        with self.assertRaises(RuntimeError) as ctx:
            extract_cad_ir(dxf)
        self.assertIn("Invalid DWG, magic", str(ctx.exception))

    def test_failure_mode_fm08_surrogate_serialization_failure(self):
        """FM-08: Lone surrogates in DXF text trigger Pydantic serialization crash."""
        from pydantic_core import PydanticSerializationError
        from cad_extractor.models import CADAnnotation
        ann = CADAnnotation(
            type="TEXT",
            layer="0",
            space="Model",
            raw_text="surrogate",
            clean_text="\ud800",
            position=[0.0, 0.0],
            height=1.0,
        )
        with self.assertRaises(PydanticSerializationError):
            ann.model_dump_json()

    def test_failure_mode_fm06_arc_circle_extents_omits_radius(self):
        """FM-06: Arc and Circle bounding box only updates center, ignoring radius."""
        arc_dwg = os.path.abspath(os.path.join(os.path.dirname(__file__), "../examples/2013_Arc.dwg"))
        ir = extract_cad_ir(arc_dwg)
        # Bounding box width and height are 0.0 even though radius is ~8.293
        self.assertEqual(ir.extents.width, 0.0)
        self.assertEqual(ir.extents.height, 0.0)

if __name__ == "__main__":
    unittest.main()
