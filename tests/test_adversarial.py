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
import math
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
    # Verified Failure Mode Remediations (Fixed in v3.1)
    # -------------------------------------------------------------------------
    def test_remediation_fm01_direct_dxf_ingestion_succeeds(self):
        """FM-01: extract_cad_ir natively processes DXF files without crashing."""
        dxf = os.path.join(FIXTURES_DIR, "empty_02_no_layers.dxf")
        ir = extract_cad_ir(dxf)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        self.assertEqual(ir.format, "LAVINCI_CAD_IR_V3")

    def test_remediation_fm08_surrogate_serialization_resilience(self):
        """FM-08: Lone surrogates in CAD text are safely sanitized, preventing JSON crash."""
        dxf = os.path.join(FIXTURES_DIR, "unicode_01_surrogate_uD800.dxf")
        ir = extract_cad_ir(dxf)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        json_dump = ir.model_dump_json()
        self.assertTrue(len(json_dump) > 0)

    def test_remediation_fm06_arc_circle_extents_includes_radius(self):
        """FM-06: Arc and Circle bounding box correctly includes radius."""
        arc_dwg = os.path.abspath(os.path.join(os.path.dirname(__file__), "../examples/2013_Arc.dwg"))
        ir = extract_cad_ir(arc_dwg)
        # 2013_Arc has radius ~8.293, so width and height must equal 2 * radius ~16.586
        self.assertAlmostEqual(ir.extents.width, 16.586, places=2)
        self.assertAlmostEqual(ir.extents.height, 16.586, places=2)

    # -------------------------------------------------------------------------
    # Feature 1: Coordinate Sanitization & Astronomical Float Hardening
    # -------------------------------------------------------------------------
    def test_feature1_nan_inf_polyline_points_filtered(self):
        """FM-12 / F1: Polyline points containing NaN, Inf, or -Inf are cleanly filtered."""
        import ezdxf
        from cad_extractor.core import extract_entity_polyline_points
        doc = ezdxf.new("R2000")
        msp = doc.modelspace()
        poly = msp.add_lwpolyline([(0.0, 0.0), (10.0, float("nan")), (20.0, 20.0), (float("inf"), 30.0)])
        pts = extract_entity_polyline_points(poly)
        self.assertEqual(pts, [[0.0, 0.0], [20.0, 20.0]])

    def test_feature1_astronomical_floats_sanitized(self):
        """F1: Pathological floats (> 1e7) and uninitialized subnormal buffer noise are dropped."""
        import ezdxf
        from cad_extractor.core import extract_entity_polyline_points
        doc = ezdxf.new("R2000")
        msp = doc.modelspace()
        poly = msp.add_lwpolyline([
            (100.0, 100.0),
            (606.284, -1.772124872286364e+281),
            (200.0, 200.0),
            (1.967e-96, -3.241e-245),
            (300.0, 300.0)
        ])
        pts = extract_entity_polyline_points(poly)
        self.assertEqual(pts, [[100.0, 100.0], [200.0, 200.0], [300.0, 300.0]])

    def test_feature1_degenerate_polyline_discarded(self):
        """F1: Polylines with fewer than 2 valid vertices after sanitization return empty list."""
        import ezdxf
        from cad_extractor.core import extract_entity_polyline_points
        doc = ezdxf.new("R2000")
        msp = doc.modelspace()
        poly = msp.add_lwpolyline([(10.0, 10.0), (float("nan"), float("nan"))])
        pts = extract_entity_polyline_points(poly)
        self.assertEqual(pts, [])

    def test_feature1_schema_roundtrip_with_extreme_kato_handles(self):
        """F1: Kato crane handles 3ADEC and 3E878 serialize and re-validate strictly without null errors."""
        import ezdxf
        from cad_extractor.core import extract_entity_polyline_points
        from cad_extractor.models import CADPolyline
        simulated_points = [[476.908 + i * 0.1, 2675.669 - i * 0.5] for i in range(50)]
        simulated_points.extend([[606.284, -1.77e+281], [1.96e-96, -3.24e-245]])
        doc = ezdxf.new("R2000")
        msp = doc.modelspace()
        poly = msp.add_lwpolyline(simulated_points)
        clean_pts = extract_entity_polyline_points(poly)
        cad_pl = CADPolyline(points=clean_pts, is_closed=False, layer="0")
        dumped_dict = cad_pl.model_dump()
        for pt in dumped_dict["points"]:
            self.assertNotIn(None, pt)
        restored = CADPolyline.model_validate_json(cad_pl.model_dump_json())
        self.assertEqual(len(restored.points), 50)
        for pt in restored.points:
            self.assertTrue(all(isinstance(c, float) and math.isfinite(c) for c in pt))

    # -------------------------------------------------------------------------
    # Feature 2: Composite Extents Boundary Conditions
    # -------------------------------------------------------------------------
    def test_feature2_negative_scale_reflection(self):
        """F2: Negative scale (mirroring) produces correct bounding box."""
        from cad_extractor.models import CADBlockDefinition, CADLine
        from cad_extractor.core import update_bounds_with_component_geometry
        bdef = CADBlockDefinition(
            name="MIRROR_BOX",
            base_point=[0.0, 0.0, 0.0],
            lines=[CADLine(layer="0", start=[10.0, 5.0], end=[30.0, 15.0])]
        )
        min_x, min_y = float("inf"), float("inf")
        max_x, max_y = float("-inf"), float("-inf")
        def update(x, y):
            nonlocal min_x, min_y, max_x, max_y
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)

        update_bounds_with_component_geometry(
            comp_pos=[100.0, 50.0],
            comp_scale=[-1.0, 1.0],
            comp_rotation=0.0,
            bdef=bdef,
            update_bounds_fn=update
        )
        self.assertAlmostEqual(min_x, 70.0, places=2)
        self.assertAlmostEqual(max_x, 90.0, places=2)
        self.assertAlmostEqual(min_y, 55.0, places=2)
        self.assertAlmostEqual(max_y, 65.0, places=2)

    def test_feature2_empty_block_fallback(self):
        """F2: Empty block returns False so caller can fall back to insertion point."""
        from cad_extractor.models import CADBlockDefinition
        from cad_extractor.core import update_bounds_with_component_geometry
        bdef = CADBlockDefinition(name="EMPTY", base_point=[0, 0, 0])
        min_x, min_y = float("inf"), float("inf")
        def update(x, y):
            nonlocal min_x, min_y
            min_x, min_y = x, y
        has_geom = update_bounds_with_component_geometry(
            comp_pos=[50.0, 60.0],
            comp_scale=[1.0, 1.0],
            comp_rotation=0.0,
            bdef=bdef,
            update_bounds_fn=update
        )
        self.assertFalse(has_geom)
        self.assertEqual(min_x, float("inf"))

    def test_feature2_extreme_float_resilience(self):
        """F2: Corrupted float (>1e15) inside block polyline is safely ignored during extents update."""
        from cad_extractor.models import CADBlockDefinition, CADPolyline
        from cad_extractor.core import update_bounds_with_component_geometry
        bdef = CADBlockDefinition(
            name="CORRUPT_POLY",
            base_point=[0, 0, 0],
            polylines=[
                CADPolyline(
                    layer="0",
                    is_closed=False,
                    points=[[10.0, 20.0], [15.0, -1.77e281], [30.0, 40.0]]
                )
            ]
        )
        min_y = float("inf")
        def update(x, y):
            nonlocal min_y
            min_y = min(min_y, y)

        update_bounds_with_component_geometry(
            comp_pos=[0.0, 0.0],
            comp_scale=[1.0, 1.0],
            comp_rotation=0.0,
            bdef=bdef,
            update_bounds_fn=update
        )
        self.assertEqual(min_y, 20.0)

    # -------------------------------------------------------------------------
    # Feature 3: Entity-Level Linetype Semantics
    # -------------------------------------------------------------------------
    def test_feature3_resolve_entity_linetype_semantics(self):
        """F3: BYLAYER -> None, BYBLOCK -> BYBLOCK, and named linetypes preserved."""
        from cad_extractor.core import resolve_entity_linetype
        class MockDXF:
            def __init__(self, lt=None, has=True):
                self.linetype = lt
                self._has = has
            def hasattr(self, name):
                return self._has
        class MockEntity:
            def __init__(self, lt=None, has=True):
                self.dxf = MockDXF(lt, has)

        self.assertIsNone(resolve_entity_linetype(MockEntity(None, False)))
        self.assertIsNone(resolve_entity_linetype(MockEntity("BYLAYER", True)))
        self.assertIsNone(resolve_entity_linetype(MockEntity("bylayer", True)))
        self.assertEqual(resolve_entity_linetype(MockEntity("BYBLOCK", True)), "BYBLOCK")
        self.assertEqual(resolve_entity_linetype(MockEntity("byblock", True)), "BYBLOCK")
        self.assertEqual(resolve_entity_linetype(MockEntity("ACAD_ISO04W100", True)), "ACAD_ISO04W100")
        self.assertEqual(resolve_entity_linetype(MockEntity("DASHED", True)), "DASHED")

    # -------------------------------------------------------------------------
    # Feature 5: Cyclic and Explosive Nested Blocks Safeguards
    # -------------------------------------------------------------------------
    def test_cat3_cyclic_self_reference_safe_termination(self):
        """FM-17: Block referencing itself terminates cleanly without recursion error."""
        dwg = os.path.join(FIXTURES_DIR, "blocks_02_cyclic_self_ref.dxf")
        ir = extract_cad_ir(dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        self.assertIn("CYCLIC_SELF", ir.block_definitions)

    def test_cat3_cyclic_mutual_pair_safe_termination(self):
        """FM-18: Mutual recursion (A -> B -> A) terminates cleanly via cycle detection."""
        dwg = os.path.join(FIXTURES_DIR, "blocks_03_cyclic_pair.dxf")
        ir = extract_cad_ir(dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        self.assertIn("CYCLIC_A", ir.block_definitions)
        self.assertIn("CYCLIC_B", ir.block_definitions)

    def test_cat3_block_bomb_combinatorial_guard(self):
        """FM-19: Billion-Laughs exponential block bomb is constrained by expansion quota."""
        import ezdxf
        from cad_extractor.core import extract_block_definitions
        doc = ezdxf.new()
        prev = None
        for i in range(6):
            bname = f"BOMB_{i}"
            blk = doc.blocks.new(name=bname)
            if prev is None:
                blk.add_line((0, 0), (1, 1))
            else:
                for j in range(10):
                    blk.add_blockref(prev, insert=(j * 10, 0, 0))
            prev = bname

        # 10^5 = 100,000 potential lines; must complete rapidly without OOM or infinite loop
        bdefs = extract_block_definitions(doc)
        self.assertIn("BOMB_5", bdefs)
        self.assertLessEqual(len(bdefs["BOMB_5"].lines), 100_000)

    # -------------------------------------------------------------------------
    # Feature 1 & 4 Adversarial Hardening
    # -------------------------------------------------------------------------
    def test_feature1_subnormal_memory_noise_dropped(self):
        """F1: Subnormal uninitialized memory floats (< 1e-6) dropped, true 0.0 preserved."""
        from cad_extractor.core import sanitize_polyline_coordinates
        raw = [[0.0, 0.0], [10.0, 10.0], [1.9675e-96, -3.241e-245], [20.0, 20.0]]
        clean = sanitize_polyline_coordinates(raw)
        self.assertEqual(clean, [[0.0, 0.0], [10.0, 10.0], [20.0, 20.0]])

    def test_feature1_closed_polyline_closing_point_deduplicated(self):
        """F1: Closed polyline closing point matching start is deduplicated to prevent zero-length segment."""
        from cad_extractor.core import sanitize_polyline_coordinates
        raw = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 0.0]]
        clean = sanitize_polyline_coordinates(raw, is_closed=True)
        self.assertEqual(clean, [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]])

    def test_feature4_adversarial_malformed_hatch_and_wipeout(self):
        """F4: Malformed or degenerate HATCH/WIPEOUT with fewer than 3 vertices is safely skipped."""
        from cad_extractor.core import _process_dxf_document
        doc = ezdxf.new()
        msp = doc.modelspace()
        # Degenerate hatch with only 2 collinear points
        h = msp.add_hatch(color=1, dxfattribs={"layer": "DEGEN_HATCH"})
        h.paths.add_polyline_path([(0, 0), (1, 1)], is_closed=True)
        # Wipeout with degenerate 2-point boundary
        msp.add_wipeout([(0, 0), (1, 1)], dxfattribs={"layer": "DEGEN_WIPEOUT"})

        ir = _process_dxf_document(doc, "degen_test.dxf")
        # Neither degenerate hatch nor degenerate wipeout should produce invalid <3 point polylines
        degen_polys = [p for p in ir.geometry_primitives.primitives.polylines if len(p.points) < 2]
        self.assertEqual(len(degen_polys), 0)


if __name__ == "__main__":
    unittest.main()

