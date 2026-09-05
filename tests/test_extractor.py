import os
import unittest
from cad_extractor.core import extract_cad_ir
from cad_extractor.models import CADIntermediateRepresentation

class TestCADExtractor(unittest.TestCase):
    def test_extract_cad_ir_sample(self):
        sample_dwg = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../examples/blueprint_sample.dwg")
        )
        self.assertTrue(os.path.exists(sample_dwg), "Sample DWG file must exist")

        ir = extract_cad_ir(sample_dwg)
        self.assertIsInstance(ir, CADIntermediateRepresentation)
        self.assertEqual(ir.format, "LAVINCI_CAD_IR_V1")
        self.assertEqual(ir.metadata.cad_version, "R2007")
        self.assertGreater(len(ir.layers), 0)
        self.assertIn("Receptacle", ir.bill_of_materials)
        self.assertGreater(ir.geometry_primitives.summary.total_lines, 0)
        self.assertGreater(ir.extents.width, 0)

if __name__ == "__main__":
    unittest.main()
