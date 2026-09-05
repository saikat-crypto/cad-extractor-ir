"""
Command-line interface for CAD Extractor IR.
"""

import sys
import json
import argparse
from .core import extract_cad_ir

def main():
    parser = argparse.ArgumentParser(
        description="CAD Extractor IR - Extract structured Intermediate Representation & Bill of Materials from DWG"
    )
    parser.add_argument("input", help="Path to input .dwg CAD file")
    parser.add_argument("-o", "--output", help="Path to save output JSON IR file", default=None)
    parser.add_argument("--bom", action="store_true", help="Print Bill of Materials table to stdout")
    parser.add_argument("--summary", action="store_true", help="Print drawing summary to stdout")

    args = parser.parse_args()

    try:
        ir = extract_cad_ir(args.input)
    except Exception as e:
        print(f"Error extracting CAD IR: {e}", file=sys.stderr)
        sys.exit(1)

    if args.summary or (not args.bom and not args.output):
        print(f"=== CAD Drawing Summary ===")
        print(f"File: {ir.metadata.source_file}")
        print(f"Release: {ir.metadata.cad_version} ({ir.metadata.measurement_system})")
        print(f"Dimensions: {ir.extents.width} x {ir.extents.height}")
        print(f"Active Layers: {len(ir.layers)}")
        print(f"Total Components: {ir.geometry_primitives.summary.total_components}")
        print(f"Total Lines: {ir.geometry_primitives.summary.total_lines}")
        print(f"Total Arcs: {ir.geometry_primitives.summary.total_arcs}")

    if args.bom:
        print(f"\n=== Bill of Materials (BOM) ===")
        print(f"{'Component Name':<35} | {'Quantity':<10}")
        print("-" * 48)
        for comp, count in ir.bill_of_materials.items():
            print(f"{comp:<35} | {count:<10}")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(ir.model_dump_json(indent=2))
        print(f"\nIntermediate Representation saved to: {args.output}")

if __name__ == "__main__":
    main()
