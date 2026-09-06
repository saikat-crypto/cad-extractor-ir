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

if __name__ == "__main__":
    unittest.main()
