"""
tests/generate_fixtures.py

Automated Generator for cad-extractor-ir Adversarial and Pathological CAD Fixtures.
Constructs >=20 (specifically 29) distinct fixtures across all 6 stress testing categories:
  Category 1: Empty CAD Files (4 fixtures)
  Category 2: Extreme Spatial Dimensions and Floating-Point Boundaries (6 fixtures)
  Category 3: Nested and Cyclical Block Definitions (5 fixtures)
  Category 4: Malicious Unicode, Injection Strings and MTEXT Formatting (5 fixtures)
  Category 5: Massive Entity Counts and Scalability (3 fixtures)
  Category 6: Corrupted, Partial and Truncated Streams (6 fixtures)

Uses:
  - ezdxf (v1.4.4) with ezdxf.new('R2000', setup=True) for pristine DXF generation
  - LibreDWG dxf2dwg.exe (--as=r2000) for DWG compilation
"""

import os
import sys
import time
import random
import tempfile
import subprocess
from typing import Dict, List, Tuple

import ezdxf

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
DXF2DWG_BIN = os.path.abspath(os.path.join(PROJECT_ROOT, "../../experiments/libredwg/dxf2dwg.exe"))
TEMPLATE_DWG = os.path.join(PROJECT_ROOT, "examples", "2000_Leader.dwg")


def get_dxf2dwg_bin() -> str:
    """Resolves path to LibreDWG dxf2dwg executable."""
    if os.path.exists(DXF2DWG_BIN):
        return DXF2DWG_BIN
    import shutil
    which = shutil.which("dxf2dwg")
    if which:
        return which
    raise FileNotFoundError(f"dxf2dwg.exe not found at {DXF2DWG_BIN} or on PATH")


def compile_dxf_to_dwg(dxf_path: str, dwg_path: str) -> None:
    """Compiles a DXF file to DWG using LibreDWG dxf2dwg.exe --as=r2000."""
    exe = get_dxf2dwg_bin()
    cmd = [exe, "--as=r2000", "-y", os.path.abspath(dxf_path), "-o", os.path.abspath(dwg_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.exists(dwg_path) or os.path.getsize(dwg_path) == 0:
        raise RuntimeError(
            f"dxf2dwg failed for {dxf_path} (code {proc.returncode}): {proc.stderr or proc.stdout}"
        )


def generate_from_dxf_callback(dwg_path: str, populate_fn) -> str:
    """Helper to create a temporary DXF, call populate_fn(doc), and compile to dwg_path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_dxf = os.path.join(tmpdir, "temp.dxf")
        doc = ezdxf.new("R2000", setup=True)
        populate_fn(doc)
        doc.saveas(temp_dxf)
        compile_dxf_to_dwg(temp_dxf, dwg_path)
    return dwg_path


# ==============================================================================
# Category 1: Empty CAD Files (4 fixtures)
# ==============================================================================

def create_cat1_empty_01_zero_entities(out_dir: str) -> str:
    """FX01: Completely empty DWG with 0 entities, default modelspace and paperspace."""
    dest = os.path.join(out_dir, "empty_01_zero_entities.dwg")
    def populate(doc):
        pass  # 0 entities added
    return generate_from_dxf_callback(dest, populate)


def create_cat1_empty_02_no_layers(out_dir: str) -> str:
    """FX02: Minimal DXF with setup=False, 0 entities, and no custom layers."""
    dest = os.path.join(out_dir, "empty_02_no_layers.dxf")
    doc = ezdxf.new("R2000", setup=False)
    doc.saveas(dest)
    return dest


def create_cat1_empty_03_zero_blocks(out_dir: str) -> str:
    """FX03: DWG with custom layers and basic lines, but 0 block definitions."""
    dest = os.path.join(out_dir, "empty_03_zero_blocks.dwg")
    def populate(doc):
        doc.layers.new(name="WALLS", dxfattribs={"color": 1})
        doc.layers.new(name="DOORS", dxfattribs={"color": 2})
        msp = doc.modelspace()
        msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "WALLS"})
        msp.add_line((10, 0), (10, 10), dxfattribs={"layer": "DOORS"})
    return generate_from_dxf_callback(dest, populate)


def create_cat1_empty_04_single_point_zero(out_dir: str) -> str:
    """FX04: DWG with a single zero-length line at (0,0)->(0,0), testing 0-area bounds."""
    dest = os.path.join(out_dir, "empty_04_single_point_zero.dwg")
    def populate(doc):
        doc.modelspace().add_line((0.0, 0.0), (0.0, 0.0))
    return generate_from_dxf_callback(dest, populate)


# ==============================================================================
# Category 2: Extreme Spatial Dimensions and Floating-Point Boundaries (6 fixtures)
# ==============================================================================

def create_cat2_extreme_01_astronomical_1e12(out_dir: str) -> str:
    """FX05: Coordinates at 10^12 scale; stresses precision, bounding box, and large JSON floats."""
    dest = os.path.join(out_dir, "extreme_01_astronomical_1e12.dwg")
    def populate(doc):
        msp = doc.modelspace()
        msp.add_line((1e12, 1e12), (2e12, 2e12))
        msp.add_circle((1.5e12, 1.5e12), radius=1e9)
    return generate_from_dxf_callback(dest, populate)


def create_cat2_extreme_02_microscopic_1e6(out_dir: str) -> str:
    """FX06: Coordinates at 10^-6 scale; triggers 3-decimal rounding to 0.0 in extractor."""
    dest = os.path.join(out_dir, "extreme_02_microscopic_1e-6.dwg")
    def populate(doc):
        msp = doc.modelspace()
        msp.add_line((1e-6, 1e-6), (2e-6, 2e-6))
        msp.add_circle((5e-6, 5e-6), radius=1e-7)
    return generate_from_dxf_callback(dest, populate)


def create_cat2_extreme_03_negative_coords(out_dir: str) -> str:
    """FX07: Coordinates entirely in large negative range [-10^9, -10^6]."""
    dest = os.path.join(out_dir, "extreme_03_negative_coords.dwg")
    def populate(doc):
        msp = doc.modelspace()
        msp.add_line((-1e9, -1e9), (-5e8, -5e8))
        msp.add_arc((-1e8, -1e8), radius=1e7, start_angle=0, end_angle=180)
    return generate_from_dxf_callback(dest, populate)


def create_cat2_extreme_04_mixed_scales(out_dir: str) -> str:
    """FX08: Entities spanning 24 orders of magnitude [-10^12, +10^12] with microscopic 10^-6 items."""
    dest = os.path.join(out_dir, "extreme_04_mixed_scales.dwg")
    def populate(doc):
        msp = doc.modelspace()
        msp.add_line((-1e12, -1e12), (1e12, 1e12))
        msp.add_line((1e-6, 1e-6), (2e-6, 2e-6))
        msp.add_circle((0.0, 0.0), radius=1.0)
    return generate_from_dxf_callback(dest, populate)


def create_cat2_extreme_05_nan_coords(out_dir: str) -> str:
    """FX09: DXF with NaN coordinate injected directly; tests bounds update and JSON NaN handling."""
    dest = os.path.join(out_dir, "extreme_05_nan_coords.dxf")
    doc = ezdxf.new("R2000", setup=True)
    doc.modelspace().add_line((float("nan"), float("nan")), (10.0, 10.0))
    doc.saveas(dest)
    return dest


def create_cat2_extreme_06_inf_coords(out_dir: str) -> str:
    """FX10: DXF with Infinity / -Infinity coordinate injected; tests width/height inf-inf=nan."""
    dest = os.path.join(out_dir, "extreme_06_inf_coords.dxf")
    doc = ezdxf.new("R2000", setup=True)
    doc.modelspace().add_line((float("-inf"), float("-inf")), (float("inf"), float("inf")))
    doc.saveas(dest)
    return dest


# ==============================================================================
# Category 3: Nested and Cyclical Block Definitions (5 fixtures)
# ==============================================================================

def create_cat3_blocks_01_nested_depth_10(out_dir: str) -> str:
    """FX11: 10-level linear nested block hierarchy; exposes FM-14 (silent omission from BOM)."""
    dest = os.path.join(out_dir, "blocks_01_nested_depth_10.dwg")
    def populate(doc):
        prev_name = None
        for i in range(10, 0, -1):
            bname = f"BLOCK_L{i}"
            blk = doc.blocks.new(name=bname)
            if prev_name is None:
                blk.add_line((0, 0), (10, 10))
                blk.add_circle((5, 5), radius=2.5)
            else:
                blk.add_blockref(prev_name, (1, 1))
            prev_name = bname
        doc.modelspace().add_blockref("BLOCK_L1", (0, 0))
    return generate_from_dxf_callback(dest, populate)


def create_cat3_blocks_02_cyclic_self_ref(out_dir: str) -> str:
    """FX12: Self-referential block definition (CYCLIC_SELF inserts CYCLIC_SELF in DXF)."""
    dest = os.path.join(out_dir, "blocks_02_cyclic_self_ref.dxf")
    doc = ezdxf.new("R2000", setup=True)
    blk = doc.blocks.new(name="CYCLIC_SELF")
    blk.add_line((0, 0), (5, 5))
    blk.add_blockref("CYCLIC_SELF", (0, 0))
    doc.modelspace().add_blockref("CYCLIC_SELF", (0, 0))
    doc.saveas(dest)
    return dest


def create_cat3_blocks_03_cyclic_pair(out_dir: str) -> str:
    """FX13: Mutually cyclical block pair (CYCLIC_A inserts CYCLIC_B; CYCLIC_B inserts CYCLIC_A)."""
    dest = os.path.join(out_dir, "blocks_03_cyclic_pair.dxf")
    doc = ezdxf.new("R2000", setup=True)
    ba = doc.blocks.new(name="CYCLIC_A")
    bb = doc.blocks.new(name="CYCLIC_B")
    ba.add_blockref("CYCLIC_B", (0, 0))
    bb.add_blockref("CYCLIC_A", (0, 0))
    doc.modelspace().add_blockref("CYCLIC_A", (0, 0))
    doc.saveas(dest)
    return dest


def create_cat3_blocks_04_deep_transform(out_dir: str) -> str:
    """FX14: 5-level nested blocks with compounding translations, 45-deg rotation, and 2.0x scale."""
    dest = os.path.join(out_dir, "blocks_04_deep_transform.dwg")
    def populate(doc):
        b5 = doc.blocks.new(name="TRANS_L5")
        b5.add_line((0, 0), (10, 10))
        for lvl in (4, 3, 2, 1):
            b = doc.blocks.new(name=f"TRANS_L{lvl}")
            child = f"TRANS_L{lvl+1}"
            b.add_blockref(child, (10.0, 10.0), dxfattribs={"rotation": 45.0, "xscale": 2.0, "yscale": 2.0})
        doc.modelspace().add_blockref("TRANS_L1", (0, 0), dxfattribs={"rotation": 30.0, "xscale": 1.5, "yscale": 1.5})
    return generate_from_dxf_callback(dest, populate)


def create_cat3_blocks_05_empty_definition(out_dir: str) -> str:
    """FX15: Block definition with 0 internal entities, inserted 10 times in modelspace."""
    dest = os.path.join(out_dir, "blocks_05_empty_definition.dwg")
    def populate(doc):
        doc.blocks.new(name="EMPTY_BLK")
        msp = doc.modelspace()
        for i in range(10):
            msp.add_blockref("EMPTY_BLK", (i * 10.0, 0.0))
    return generate_from_dxf_callback(dest, populate)


# ==============================================================================
# Category 4: Malicious Unicode, Injection Strings and MTEXT Formatting (5 fixtures)
# ==============================================================================

def create_cat4_unicode_01_surrogate_uD800(out_dir: str) -> str:
    """FX16: DXF with lone high surrogate chr(0xD800); triggers PydanticSerializationError (FM-08)."""
    dest = os.path.join(out_dir, "unicode_01_surrogate_uD800.dxf")
    doc = ezdxf.new("R2000", setup=True)
    doc.modelspace().add_text(chr(0xD800), dxfattribs={"insert": (0, 0)})
    doc.saveas(dest, encoding="utf-8")
    return dest


def create_cat4_unicode_02_injection_strings(out_dir: str) -> str:
    """FX17: Text entities containing SQLi, shell commands, format strings, and path traversals."""
    dest = os.path.join(out_dir, "unicode_02_injection_strings.dwg")
    def populate(doc):
        msp = doc.modelspace()
        msp.add_text("' OR '1'='1'; DROP TABLE drawings; --", dxfattribs={"insert": (0, 0)})
        msp.add_text('"; calc.exe & echo %PATH% && rem "', dxfattribs={"insert": (0, 10)})
        msp.add_text("%s%n%x%p%d", dxfattribs={"insert": (0, 20)})
        msp.add_text("../../../../etc/passwd", dxfattribs={"insert": (0, 30)})
        msp.add_text("..\\..\\..\\..\\Windows\\System32", dxfattribs={"insert": (0, 40)})
        msp.add_text("<script>alert('xss')</script>", dxfattribs={"insert": (0, 50)})
    return generate_from_dxf_callback(dest, populate)


def create_cat4_unicode_03_multilingual_cjk(out_dir: str) -> str:
    """FX18: Text containing Arabic (RTL), Hebrew, RTL override, CJK, Cyrillic, and Emojis."""
    dest = os.path.join(out_dir, "unicode_03_multilingual_cjk.dwg")
    def populate(doc):
        msp = doc.modelspace()
        msp.add_text("????? ??????? - ????? ???????", dxfattribs={"insert": (0, 0)})
        msp.add_text("???? ???? - ????? ??????", dxfattribs={"insert": (0, 10)})
        rtl_text = chr(0x202E) + "RTL OVERRIDE TEXT" + chr(0x202C)
        msp.add_text(rtl_text, dxfattribs={"insert": (0, 20)})
        msp.add_text("??????? ?????", dxfattribs={"insert": (0, 30)})
        msp.add_text("???? ????????", dxfattribs={"insert": (0, 40)})
        msp.add_text("??? CAD ?? ??", dxfattribs={"insert": (0, 50)})
        msp.add_text("?????? ?????????????", dxfattribs={"insert": (0, 60)})
        msp.add_text("Unicode Symbols: ?????????", dxfattribs={"insert": (0, 70)})
    return generate_from_dxf_callback(dest, populate)


def create_cat4_unicode_04_control_chars(out_dir: str) -> str:
    """FX19: Text containing ASCII control characters \x01-\x1F, tabs, escape sequences."""
    dest = os.path.join(out_dir, "unicode_04_control_chars.dwg")
    def populate(doc):
        msp = doc.modelspace()
        ctrl_chars = "".join(chr(c) for c in range(1, 32) if c not in (10, 13))
        msp.add_text(f"CTRL[{ctrl_chars}]END", dxfattribs={"insert": (0, 0)})
        msp.add_text("Col1\tCol2\tCol3\bBackspace\x1bEscape", dxfattribs={"insert": (0, 10)})
    return generate_from_dxf_callback(dest, populate)


def create_cat4_unicode_05_null_empty_text(out_dir: str) -> str:
    """FX20: Text entities with empty strings, whitespace, and formatting-only MTEXT."""
    dest = os.path.join(out_dir, "unicode_05_null_empty_text.dwg")
    def populate(doc):
        msp = doc.modelspace()
        msp.add_text("", dxfattribs={"insert": (0, 0)})
        msp.add_text("   ", dxfattribs={"insert": (0, 10)})
        msp.add_mtext(r"{\H2;}", dxfattribs={"insert": (0, 20)})
        msp.add_mtext(r"{\C1;\L}", dxfattribs={"insert": (0, 30)})
    return generate_from_dxf_callback(dest, populate)


# ==============================================================================
# Category 5: Massive Entity Counts and Scalability (3 fixtures)
# ==============================================================================

def create_cat5_massive_01_lines_10k(out_dir: str) -> str:
    """FX21: Exactly 10,000 line primitives in DWG format (benchmarked ~23s compile / ~0.9s extract)."""
    dest = os.path.join(out_dir, "massive_01_lines_10k.dwg")
    def populate(doc):
        msp = doc.modelspace()
        for i in range(10000):
            msp.add_line((i * 0.1, 0.0), (i * 0.1, 100.0))
    return generate_from_dxf_callback(dest, populate)


def create_cat5_massive_02_mixed_50k(out_dir: str) -> str:
    """FX22: 50,000 mixed entities in DXF (20k lines, 10k circles, 10k arcs, 10k polylines)."""
    dest = os.path.join(out_dir, "massive_02_mixed_50k.dxf")
    doc = ezdxf.new("R2000", setup=True)
    msp = doc.modelspace()
    for i in range(20000):
        msp.add_line((i * 0.05, 0.0), (i * 0.05, 50.0))
    for i in range(10000):
        msp.add_circle((i * 0.1, 60.0), radius=0.5)
    for i in range(10000):
        msp.add_arc((i * 0.1, 80.0), radius=0.5, start_angle=0, end_angle=180)
    for i in range(10000):
        base_x = i * 0.1
        msp.add_lwpolyline([(base_x, 100.0), (base_x + 0.05, 105.0), (base_x + 0.05, 100.0)], close=True)
    doc.saveas(dest)
    return dest


def create_cat5_massive_03_components_5k(out_dir: str) -> str:
    """FX23: 5,000 component instances (RESISTOR block) in DWG, testing Counter and BOM."""
    dest = os.path.join(out_dir, "massive_03_components_5k.dwg")
    def populate(doc):
        blk = doc.blocks.new(name="RESISTOR")
        blk.add_line((0, 0), (10, 0))
        blk.add_line((10, 0), (10, 5))
        blk.add_line((10, 5), (0, 5))
        blk.add_line((0, 5), (0, 0))
        msp = doc.modelspace()
        for i in range(5000):
            msp.add_blockref("RESISTOR", (float(i % 100 * 20), float((i // 100) * 10)))
    return generate_from_dxf_callback(dest, populate)


# ==============================================================================
# Category 6: Corrupted, Partial and Truncated Streams (6 fixtures)
# ==============================================================================

def create_cat6_corrupt_01_truncated_header(out_dir: str) -> str:
    """FX24: DWG truncated to 16 bytes (cut in header magic)."""
    dest = os.path.join(out_dir, "corrupt_01_truncated_header.dwg")
    with open(TEMPLATE_DWG, "rb") as f:
        data = f.read(16)
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def create_cat6_corrupt_02_zero_byte(out_dir: str) -> str:
    """FX25: 0-byte file (completely empty binary)."""
    dest = os.path.join(out_dir, "corrupt_02_zero_byte.dwg")
    with open(dest, "wb") as f:
        f.write(b"")
    return dest


def create_cat6_corrupt_03_random_fuzz_bytes(out_dir: str) -> str:
    """FX26: 1,024 bytes of deterministic pseudo-random fuzz data."""
    dest = os.path.join(out_dir, "corrupt_03_random_fuzz_bytes.dwg")
    rng = random.Random(42)
    fuzz_data = bytes([rng.randint(0, 255) for _ in range(1024)])
    with open(dest, "wb") as f:
        f.write(fuzz_data)
    return dest


def create_cat6_corrupt_04_invalid_magic(out_dir: str) -> str:
    """FX27: DWG template with invalid magic bytes 'AC1099' instead of 'AC1015'."""
    dest = os.path.join(out_dir, "corrupt_04_invalid_magic.dwg")
    with open(TEMPLATE_DWG, "rb") as f:
        data = f.read()
    with open(dest, "wb") as f:
        f.write(b"AC1099" + data[6:])
    return dest


def create_cat6_corrupt_05_cut_middle(out_dir: str) -> str:
    """FX28: DWG template with first 512B and last 512B intact, but middle 90% zeroed out."""
    dest = os.path.join(out_dir, "corrupt_05_cut_middle.dwg")
    with open(TEMPLATE_DWG, "rb") as f:
        data = bytearray(f.read())
    mid_start = 512
    mid_end = max(512, len(data) - 512)
    for i in range(mid_start, mid_end):
        data[i] = 0
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def create_cat6_corrupt_06_dxf_truncated_section(out_dir: str) -> str:
    """FX29: DXF file truncated abruptly midway through ENTITIES section without ENDSEC/EOF."""
    dest = os.path.join(out_dir, "corrupt_06_dxf_truncated_section.dxf")
    content = (
        "  0\nSECTION\n  2\nHEADER\n  9\n$ACADVER\n  1\nAC1015\n  0\nENDSEC\n"
        "  0\nSECTION\n  2\nENTITIES\n  0\nLINE\n  8\n0\n 10\n0.0\n 20\n0.0\n"
        " 11\n10.0\n 21\n10.0\n  0\nLINE\n  8\n0\n 10\n"
    )
    with open(dest, "w", encoding="ascii") as f:
        f.write(content)
    return dest


# ==============================================================================
# Master Generator Registry and Runner
# ==============================================================================

ALL_FIXTURE_GENERATORS = [
    # Category 1: Empty CAD Files (4)
    ("Category 1: Empty CAD Files", "empty_01_zero_entities.dwg", create_cat1_empty_01_zero_entities),
    ("Category 1: Empty CAD Files", "empty_02_no_layers.dxf", create_cat1_empty_02_no_layers),
    ("Category 1: Empty CAD Files", "empty_03_zero_blocks.dwg", create_cat1_empty_03_zero_blocks),
    ("Category 1: Empty CAD Files", "empty_04_single_point_zero.dwg", create_cat1_empty_04_single_point_zero),

    # Category 2: Extreme Spatial Dimensions (6)
    ("Category 2: Extreme Spatial Dimensions", "extreme_01_astronomical_1e12.dwg", create_cat2_extreme_01_astronomical_1e12),
    ("Category 2: Extreme Spatial Dimensions", "extreme_02_microscopic_1e-6.dwg", create_cat2_extreme_02_microscopic_1e6),
    ("Category 2: Extreme Spatial Dimensions", "extreme_03_negative_coords.dwg", create_cat2_extreme_03_negative_coords),
    ("Category 2: Extreme Spatial Dimensions", "extreme_04_mixed_scales.dwg", create_cat2_extreme_04_mixed_scales),
    ("Category 2: Extreme Spatial Dimensions", "extreme_05_nan_coords.dxf", create_cat2_extreme_05_nan_coords),
    ("Category 2: Extreme Spatial Dimensions", "extreme_06_inf_coords.dxf", create_cat2_extreme_06_inf_coords),

    # Category 3: Nested and Cyclical Blocks (5)
    ("Category 3: Nested and Cyclical Blocks", "blocks_01_nested_depth_10.dwg", create_cat3_blocks_01_nested_depth_10),
    ("Category 3: Nested and Cyclical Blocks", "blocks_02_cyclic_self_ref.dxf", create_cat3_blocks_02_cyclic_self_ref),
    ("Category 3: Nested and Cyclical Blocks", "blocks_03_cyclic_pair.dxf", create_cat3_blocks_03_cyclic_pair),
    ("Category 3: Nested and Cyclical Blocks", "blocks_04_deep_transform.dwg", create_cat3_blocks_04_deep_transform),
    ("Category 3: Nested and Cyclical Blocks", "blocks_05_empty_definition.dwg", create_cat3_blocks_05_empty_definition),

    # Category 4: Malicious Unicode and Text (5)
    ("Category 4: Malicious Unicode and Text", "unicode_01_surrogate_uD800.dxf", create_cat4_unicode_01_surrogate_uD800),
    ("Category 4: Malicious Unicode and Text", "unicode_02_injection_strings.dwg", create_cat4_unicode_02_injection_strings),
    ("Category 4: Malicious Unicode and Text", "unicode_03_multilingual_cjk.dwg", create_cat4_unicode_03_multilingual_cjk),
    ("Category 4: Malicious Unicode and Text", "unicode_04_control_chars.dwg", create_cat4_unicode_04_control_chars),
    ("Category 4: Malicious Unicode and Text", "unicode_05_null_empty_text.dwg", create_cat4_unicode_05_null_empty_text),

    # Category 5: Massive Entity Counts (3)
    ("Category 5: Massive Entity Counts", "massive_01_lines_10k.dwg", create_cat5_massive_01_lines_10k),
    ("Category 5: Massive Entity Counts", "massive_02_mixed_50k.dxf", create_cat5_massive_02_mixed_50k),
    ("Category 5: Massive Entity Counts", "massive_03_components_5k.dwg", create_cat5_massive_03_components_5k),

    # Category 6: Corrupted/Truncated Streams (6)
    ("Category 6: Corrupted/Truncated Streams", "corrupt_01_truncated_header.dwg", create_cat6_corrupt_01_truncated_header),
    ("Category 6: Corrupted/Truncated Streams", "corrupt_02_zero_byte.dwg", create_cat6_corrupt_02_zero_byte),
    ("Category 6: Corrupted/Truncated Streams", "corrupt_03_random_fuzz_bytes.dwg", create_cat6_corrupt_03_random_fuzz_bytes),
    ("Category 6: Corrupted/Truncated Streams", "corrupt_04_invalid_magic.dwg", create_cat6_corrupt_04_invalid_magic),
    ("Category 6: Corrupted/Truncated Streams", "corrupt_05_cut_middle.dwg", create_cat6_corrupt_05_cut_middle),
    ("Category 6: Corrupted/Truncated Streams", "corrupt_06_dxf_truncated_section.dxf", create_cat6_corrupt_06_dxf_truncated_section),
]


def generate_all_fixtures(output_directory: str = FIXTURES_DIR) -> Dict[str, str]:
    """Generates all 29 fixtures in the specified directory."""
    os.makedirs(output_directory, exist_ok=True)
    generated = {}
    print("=== Starting Adversarial CAD Fixture Generation (29 Fixtures) ===")
    print(f"Target directory: {output_directory}")

    t_start = time.time()
    for idx, (cat, filename, gen_fn) in enumerate(ALL_FIXTURE_GENERATORS, start=1):
        t0 = time.time()
        print(f"[{idx:02d}/29] [{cat}] Generating {filename}...", end=" ", flush=True)
        try:
            path = gen_fn(output_directory)
            elapsed = time.time() - t0
            size_kb = os.path.getsize(path) / 1024.0
            generated[filename] = path
            print(f"DONE ({elapsed:.2f}s, {size_kb:.1f} KB)")
        except Exception as e:
            print(f"FAILED! Error: {e}")
            raise

    total_time = time.time() - t_start
    print(f"\n=== Successfully generated {len(generated)}/29 fixtures in {total_time:.2f}s ===\n")
    return generated


if __name__ == "__main__":
    out = FIXTURES_DIR
    if len(sys.argv) > 1:
        out = os.path.abspath(sys.argv[1])
    generate_all_fixtures(out)
