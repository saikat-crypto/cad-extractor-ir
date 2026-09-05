import os
import unittest
from cad_extractor.core import extract_cad_ir
from cad_extractor.models import CADIntermediateRepresentation

class TestCADExtractorV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample_dwg = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../examples/blueprint_sample.dwg")
        )
        cls.ir = extract_cad_ir(cls.sample_dwg)

    def test_ir_schema_v2(self):
        self.assertIsInstance(self.ir, CADIntermediateRepresentation)
        self.assertEqual(self.ir.format, "LAVINCI_CAD_IR_V2")
        self.assertEqual(self.ir.metadata.cad_version, "R2007")

    def test_256_aci_and_hex_colors(self):
        self.assertGreater(len(self.ir.layers), 0)
        for layer in self.ir.layers:
            self.assertTrue(layer.hex_color.startswith("#"), f"Invalid hex color: {layer.hex_color}")
            self.assertEqual(len(layer.hex_color), 7)

    def test_resolved_block_names_in_bom(self):
        # Verify anonymous blocks are resolved to manufacturer/style names
        bom = self.ir.bill_of_materials
        self.assertIn("Receptacle", bom)
        self.assertIn("Lighting fixture", bom)
        self.assertTrue(
            any("ANDERSEN CASEMENT" in k for k in bom.keys()),
            "Anonymous window blocks should resolve to 'ANDERSEN CASEMENT'"
        )
        self.assertTrue(
            any("TRU STYLE" in k for k in bom.keys()),
            "Anonymous door blocks should resolve to 'TRU STYLE'"
        )

    def test_block_attributes_extracted(self):
        # Find a component with attributes
        attributed_components = [c for c in self.ir.components if len(c.attributes) > 0]
        self.assertGreater(len(attributed_components), 0)
        first_attr = attributed_components[0].attributes
        self.assertTrue(any(k in first_attr for k in ["MANUFACTURER", "STYLE", "ESTCODE", "SYM."]))

    def test_layouts_and_viewports(self):
        # Verify Paper Space layouts are captured
        self.assertGreater(len(self.ir.layouts), 0)
        layout_names = [l.name for l in self.ir.layouts]
        self.assertIn("ISO A1", layout_names)
        iso_a1 = [l for l in self.ir.layouts if l.name == "ISO A1"][0]
        self.assertGreater(len(iso_a1.viewports), 0)

    def test_geometry_and_dimensions_summary(self):
        summary = self.ir.geometry_primitives.summary
        self.assertGreater(summary.total_lines, 0)
        self.assertGreater(summary.total_components, 0)
        self.assertIsInstance(summary.total_dimensions, int)

if __name__ == "__main__":
    unittest.main()
