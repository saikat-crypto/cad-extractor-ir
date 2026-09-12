import os
import unittest
from cad_extractor.core import extract_cad_ir
from cad_extractor.models import CADIntermediateRepresentation

class TestCADExtractorV3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample_dwg = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../examples/blueprint_sample.dwg")
        )
        cls.ir = extract_cad_ir(cls.sample_dwg)

    def test_ir_schema_v3(self):
        self.assertIsInstance(self.ir, CADIntermediateRepresentation)
        self.assertEqual(self.ir.format, "LAVINCI_CAD_IR_V3")
        self.assertEqual(self.ir.metadata.cad_version, "R2007")

    def test_block_definitions_extracted(self):
        # Verify block definitions are extracted with internal geometry
        self.assertGreater(len(self.ir.block_definitions), 0)
        self.assertIn("Toilet", self.ir.block_definitions)
        self.assertIn("Receptacle", self.ir.block_definitions)
        self.assertIn("Bathtub", self.ir.block_definitions)

        toilet = self.ir.block_definitions["Toilet"]
        self.assertGreater(len(toilet.lines), 0, "Toilet block must contain internal lines")
        self.assertGreater(len(toilet.arcs), 0, "Toilet block must contain internal arcs")

        receptacle = self.ir.block_definitions["Receptacle"]
        self.assertGreater(len(receptacle.circles), 0, "Receptacle block must contain CIRCLE primitive")

    def test_true_bylayer_color_semantics(self):
        # Entities inheriting layer color must have color=None (not hardcoded hex)
        lines = self.ir.geometry_primitives.primitives.lines
        bylayer_lines = [l for l in lines if l.color is None]
        self.assertEqual(len(bylayer_lines), len(lines), "All lines in sample are BYLAYER and must have color=None")

    def test_layer_palette_and_hex(self):
        self.assertGreater(len(self.ir.layers), 0)
        for layer in self.ir.layers:
            self.assertTrue(layer.hex_color.startswith("#"), f"Invalid hex color: {layer.hex_color}")
            self.assertEqual(len(layer.hex_color), 7)

    def test_resolved_block_names_in_bom(self):
        bom = self.ir.bill_of_materials
        self.assertIn("Receptacle", bom)
        self.assertIn("Lighting fixture", bom)
        self.assertTrue(any("ANDERSEN CASEMENT" in k for k in bom.keys()))
        self.assertTrue(any("TRU STYLE" in k for k in bom.keys()))

    def test_block_attributes_mined(self):
        attributed_components = [c for c in self.ir.components if len(c.attributes) > 0]
        self.assertGreater(len(attributed_components), 0)
        first_attr = attributed_components[0].attributes
        self.assertTrue(any(k in first_attr for k in ["MANUFACTURER", "STYLE", "ESTCODE", "SYM."]))

    def test_paper_space_layouts_and_viewports(self):
        self.assertGreater(len(self.ir.layouts), 0)
        layout_names = [l.name for l in self.ir.layouts]
        self.assertIn("ISO A1", layout_names)
        iso_a1 = [l for l in self.ir.layouts if l.name == "ISO A1"][0]
        self.assertGreater(len(iso_a1.viewports), 0)

    def test_polyline_bulge_tessellation(self):
        import ezdxf
        from cad_extractor.core import extract_entity_polyline_points
        doc = ezdxf.new()
        msp = doc.modelspace()
        # Create polyline with semicircular arc bulge (bulge=1.0)
        poly = msp.add_lwpolyline([(0, 0), (10, 0, 0, 0, 1.0), (10, 10)])
        pts = extract_entity_polyline_points(poly, flatten_distance=0.5)
        # Without bulge tessellation, this would only be 3 straight points
        self.assertGreater(len(pts), 5, "Polyline with arc bulges must be tessellated into curved coordinates")
        # Ensure coordinates are floats and non-empty
        self.assertTrue(all(len(p) == 2 and isinstance(p[0], float) for p in pts))

    def test_dimension_extraction_metadata(self):
        import ezdxf
        from cad_extractor.core import _process_dxf_document
        doc = ezdxf.new()
        msp = doc.modelspace()
        dim = msp.add_linear_dim(
            base=(0, 10),
            p1=(0, 0),
            p2=(100, 0),
            dxfattribs={"layer": "DIMS"}
        )
        dim.dimension.dxf.text_midpoint = (50, 15, 0)
        # dim.dimension.dxf.text_height doesn't exist? Oh let's use the override
        # Actually ezdxf doesn't have text_height on dimension dxf? Let's try it.
        # But wait, we can just use the ezdxf way: dim.dimension.dxf.text_midpoint... Wait, we can just set it on the dxf.
        try:
            dim.dimension.dxf.text_height = 2.5
        except:
            pass
        dim.dimension.dxf.text_rotation = 0.0
        dim.dimension.dxf.actual_measurement = 100.0

        ir = _process_dxf_document(doc, "test_dim.dxf")
        self.assertEqual(len(ir.dimensions), 1)
        d = ir.dimensions[0]
        self.assertEqual(d.measurement, 100.0)
        self.assertEqual(d.text_midpoint, [50.0, 15.0])
        self.assertEqual(d.text_rotation, 0.0)

    # -------------------------------------------------------------------------
    # Feature 4: Unhandled Entity Types (SOLID, HATCH, WIPEOUT, POINT)
    # -------------------------------------------------------------------------
    def test_solid_quad_and_triangle_ingestion(self):
        """Feature 4: DXF SOLID quads and triangles ingest as closed CADPolylines."""
        import ezdxf
        from cad_extractor.core import _process_dxf_document
        doc = ezdxf.new()
        msp = doc.modelspace()
        # Quad solid in DXF bowtie order
        msp.add_solid([(0, 0), (10, 0), (0, 10), (10, 10)], dxfattribs={"layer": "STRUCT", "color": 1})
        # Triangle solid
        msp.add_solid([(20, 20), (30, 20), (25, 30)], dxfattribs={"layer": "ARROW", "color": 3})
        ir = _process_dxf_document(doc, "test_solids.dxf")
        polys = ir.geometry_primitives.primitives.polylines
        self.assertEqual(len(polys), 2)
        # Verify quad has 4 perimeter points
        self.assertEqual(len(polys[0].points), 4)
        self.assertTrue(polys[0].is_closed)
        self.assertEqual(polys[0].points, [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
        # Verify triangle has 3 points
        self.assertEqual(len(polys[1].points), 3)
        self.assertTrue(polys[1].is_closed)

    def test_hatch_multi_boundary_loops_ingestion(self):
        """Feature 4: HATCH with multiple loops ingests into discrete closed CADPolylines."""
        import ezdxf
        from cad_extractor.core import _process_dxf_document
        doc = ezdxf.new()
        msp = doc.modelspace()
        h = msp.add_hatch(color=2, dxfattribs={"layer": "PLATES"})
        h.paths.add_polyline_path([(0, 0), (100, 0), (100, 100), (0, 100)], is_closed=True)
        h.paths.add_polyline_path([(20, 20), (40, 20), (40, 40), (20, 40)], is_closed=True)
        ir = _process_dxf_document(doc, "test_hatch.dxf")
        polys = ir.geometry_primitives.primitives.polylines
        self.assertEqual(len(polys), 2)
        self.assertTrue(all(p.is_closed for p in polys))

    def test_wipeout_boundary_ingestion(self):
        """Feature 4: WIPEOUT extracts as a closed CADPolyline in WCS."""
        import ezdxf
        from cad_extractor.core import _process_dxf_document
        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_wipeout([(10, 10), (50, 10), (50, 50), (10, 50)], dxfattribs={"layer": "MASKS"})
        ir = _process_dxf_document(doc, "test_wipeout.dxf")
        polys = ir.geometry_primitives.primitives.polylines
        self.assertEqual(len(polys), 1)
        self.assertEqual(len(polys[0].points), 4)
        self.assertTrue(polys[0].is_closed)

    def test_point_entity_ingestion(self):
        """Feature 4: POINT entity ingests and expands global bounding extents."""
        import ezdxf
        from cad_extractor.core import _process_dxf_document
        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_point((500.0, 700.0, 0.0), dxfattribs={"layer": "SURVEY"})
        ir = _process_dxf_document(doc, "test_point.dxf")
        circles = ir.geometry_primitives.primitives.circles
        self.assertEqual(len(circles), 1)
        self.assertEqual(circles[0].center, [500.0, 700.0])
        self.assertGreaterEqual(ir.extents.max[0], 500.0)
        self.assertGreaterEqual(ir.extents.max[1], 700.0)

    # -------------------------------------------------------------------------
    # Feature 3: Entity-Level Linetype Extraction
    # -------------------------------------------------------------------------
    def test_entity_level_linetype_extraction(self):
        """Feature 3: Explicit entity linetype overrides are preserved, BYLAYER is None."""
        import ezdxf
        from cad_extractor.core import _process_dxf_document
        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_line((0, 0), (10, 10), dxfattribs={"layer": "0", "linetype": "DASHED"})
        msp.add_line((10, 10), (20, 20), dxfattribs={"layer": "0", "linetype": "BYLAYER"})
        msp.add_circle((30, 30), radius=5, dxfattribs={"layer": "0", "linetype": "ACAD_ISO04W100"})
        msp.add_arc((40, 40), radius=5, start_angle=0, end_angle=90, dxfattribs={"layer": "0", "linetype": "CENTER"})
        msp.add_lwpolyline([(50, 50), (60, 50)], dxfattribs={"layer": "0", "linetype": "HIDDEN"})

        ir = _process_dxf_document(doc, "test_linetypes.dxf")
        lines = ir.geometry_primitives.primitives.lines
        self.assertEqual(lines[0].linetype, "DASHED")
        self.assertIsNone(lines[1].linetype)

        circles = ir.geometry_primitives.primitives.circles
        self.assertEqual(circles[0].linetype, "ACAD_ISO04W100")

        arcs = ir.geometry_primitives.primitives.arcs
        self.assertEqual(arcs[0].linetype, "CENTER")

        polys = ir.geometry_primitives.primitives.polylines
        self.assertEqual(polys[0].linetype, "HIDDEN")

    def test_schema_backward_compatibility_without_linetypes(self):
        """Feature 3: Existing IR JSON without linetype deserializes cleanly with default None."""
        from cad_extractor.models import CADLine
        raw_json = '{"layer":"0","space":"Model","start":[0.0, 0.0],"end":[10.0, 10.0]}'
        line = CADLine.model_validate_json(raw_json)
        self.assertIsNone(line.linetype)
        self.assertEqual(line.start, [0.0, 0.0])

    # -------------------------------------------------------------------------
    # Feature 2: True Composite Bounding Box Extents
    # -------------------------------------------------------------------------
    def test_composite_extents_transformed_component(self):
        """Feature 2: Component block geometry expands global bounding extents with affine transform."""
        import ezdxf
        from cad_extractor.core import _process_dxf_document
        doc = ezdxf.new()
        blk = doc.blocks.new("SUB_ASSEMBLY")
        blk.add_line((0, 0), (100, 50))
        blk.add_circle((50, 25), radius=10)

        msp = doc.modelspace()
        # Insert block at (1000, 2000) with scale 2.0
        msp.add_blockref("SUB_ASSEMBLY", insert=(1000, 2000, 0), dxfattribs={"xscale": 2.0, "yscale": 2.0})

        ir = _process_dxf_document(doc, "test_composite.dxf")
        # Transformed line reaches (1000 + 200, 2000 + 100) = (1200, 2100), starts at (1000, 2000)
        self.assertGreaterEqual(ir.extents.max[0], 1200.0)
        self.assertGreaterEqual(ir.extents.max[1], 2100.0)
        self.assertAlmostEqual(ir.extents.min[0], 1000.0, delta=1.0)
        self.assertAlmostEqual(ir.extents.min[1], 2000.0, delta=1.0)


if __name__ == "__main__":
    unittest.main()


