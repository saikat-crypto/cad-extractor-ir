# CAD Extractor IR: Comprehensive Adversarial Stress Testing & Vulnerability Audit

**Date**: 2026-09-05  
**Target Engine**: `cad-extractor-ir` (`LAVINCI_CAD_IR_V3`)  
**Scope**: End-to-End Ingestion, Subprocess Isolation, Coordinate Geometry, Floating-Point Invariants, Unicode Robustness, and Failure Mode Catalog  
**Test Suite**: 29 Pathological Fixtures (`tests/fixtures/`) & 26 Automated Invariant Tests (`tests/test_adversarial.py`)  

---

## 1. Executive Summary

An intensive adversarial stress test and invariant audit of the `cad-extractor-ir` engine was performed across 29 specialized CAD fixtures spanning 6 vulnerability categories:
1. **Empty / Minimal CAD Files** (0 entities, 0 layers, 0 blocks)
2. **Extreme Spatial Scales & Floating-Point Boundaries** ($10^{12}$, $10^{-6}$, negative coordinates, NaN, Inf)
3. **Nested & Cyclical Block Hierarchies** (10-level linear hierarchies, cyclic self-references, compound transformations)
4. **Malicious Unicode, Control Characters & Injection Payloads** (SQLi, cmd injection, unpaired surrogate code points `\ud800`, RTL text)
5. **Massive Entity Counts & Scalability Limits** (10,000 to 50,000 primitives)
6. **Corrupted, Truncated & Partial Streams** (0-byte files, truncated headers, corrupted magic bytes, cut mid-streams)

### Key Verdict:
* **The engine demonstrated excellent baseline crash resilience**: All corrupted DWG files and fuzz payloads are safely intercepted by subprocess error detection, raising clean `RuntimeError` exceptions rather than crashing with unhandled Python segfaults.
* **Idempotency and roundtrip schema serialization hold cleanly** for standard and extreme coordinate files.
* However, the audit uncovered **15 distinct failure modes (FM-01 through FM-15)**, including **4 Critical** vulnerabilities and **5 High-severity** defects that must be remediated before enterprise deployment.

---

## 2. Vulnerability Severity Matrix

| ID | Severity | Category | Vulnerability & Root Cause | Affected Invariant | Status in Test Suite |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **FM-01** | **Critical** | Ingestion | **Direct DXF Ingestion Crash**: `extract_cad_ir` unconditionally invokes `dwg2dxf.exe` on all input paths without checking file extension or magic bytes, causing valid DXFs to crash with `Invalid DWG, magic: 0 SECTI`. | Format Flexibility | Verified in `test_failure_mode_fm01` |
| **FM-02** | **Critical** | Subprocess | **Missing Subprocess Timeout**: `subprocess.run(cmd)` in `core.py` lacks a `timeout` argument. A pathological or recursively cyclical DWG can hang worker threads indefinitely. | Denial of Service / Liveness | Documented / Verified |
| **FM-05** | **Critical** | Bounding Box | **Dimension Defpoint2 Omission**: `core.py:411` records `defpoint` in bounds computation but completely omits `defpoint2`. The computed bounding box clips dimension extent lines. | Extents Invariant ($min \le coord \le max$) | Documented / Verified |
| **FM-06** | **Critical** | Bounding Box | **Arc & Circle Radius Omission**: `update_bounds()` registers only the `center` point of arcs and circles, completely ignoring the radius $r$. In files with only arcs/circles (e.g. `2013_Arc.dwg`), extents width/height collapse to `0.0`. | Extents Invariant ($min \le coord \le max$) | Verified in `test_failure_mode_fm06` |
| **FM-08** | **Critical** | Serialization | **Unpaired Unicode Surrogate Crash**: Lone surrogate codepoints (`\ud800`–`\udfff`) in CAD text pass into Pydantic models but trigger unhandled `PydanticSerializationError` (`UnicodeEncodeError`) upon `.model_dump_json()`. | Schema / Serialization | Verified in `test_failure_mode_fm08` |
| **FM-03** | **High** | Windows OS | **Windows Non-ASCII Codepage Mangling**: LibreDWG's Windows C runtime uses `fopen()`, converting non-ASCII directory paths (Cyrillic, CJK, Emoji) to `????`, raising `READ ERROR 0x1000`. | Cross-Platform Portability | Verified with Cyrillic path |
| **FM-04** | **High** | Subprocess | **Subprocess Error Masking**: `if proc.returncode != 0 and not os.path.exists(temp_dxf):` skips the error check if LibreDWG crashes but leaves a partial/empty DXF file, leading to unhandled `ezdxf` parse errors. | Clean Error Handling | Verified with corrupted DWGs |
| **FM-09** | **High** | Color | **IndexError on Negative ACI Colors**: AutoCAD uses negative integers (e.g. `-7`) for turned-off layers. Passing this to `aci2rgb(aci)` triggers unhandled `IndexError: -7`. | Robust Entity Parsing | Documented / Verified |
| **FM-12** | **High** | Coordinates | **NaN / Inf Coordinate Leak**: `NaN` and `Inf` floating point values bypass bounds comparison (`x < min_x` is False for NaN) and serialize to JSON as `null`, causing `model_validate_json` to fail. | Invariant Integrity | Verified on `extreme_05_nan_coords.dxf` |
| **FM-13** | **High** | Scalability | **LibreDWG O(N^2) Compilation Stalls**: Compiling DXF to DWG via `dxf2dwg.exe` scales quadratically ($O(N^2)$), requiring 27s for 10k entities and >10 minutes for 50k entities. | Performance & Benchmarking | Benchmarked during generation |
| **FM-07** | **Medium** | Extents | **Paper Space Extents Pollution**: Paper Space sheets (e.g. ISO A1 title blocks in mm) and Model Space entities (in world meters) are aggregated into a single global bounding box. | Viewport Isolation | Documented in Survey |
| **FM-10** | **Medium** | Schema | **ValidationError on Null Text**: If an AutoCAD `TEXT` entity has an empty text string, Pydantic's `CADAnnotation.raw_text` rejects `None`. | Schema Null-Safety | Documented in Survey |
| **FM-11** | **Medium** | Schema | **TypeError on Missing Viewport Dimensions**: `round(getattr(e.dxf, 'width', 0.0), 3)` crashes if the attribute exists but is explicitly set to `None`. | Schema Null-Safety | Documented in Survey |
| **FM-14** | **Medium** | BOM | **Silent Omission of Nested Blocks in BOM**: If a block definition contains child `INSERT` references, they are not traversed or counted in `bill_of_materials`. | BOM Completeness | Verified on `blocks_01_nested_depth_10.dwg` |
| **FM-15** | **Low** | Sanitization | **Unparsed MTEXT Fraction Tags**: Regex in `clean_cad_text` strips fonts and paragraph breaks, but leaves stacked fraction tags (`\S1/2;`) unparsed. | Text Fidelity | Documented in Survey |

---

## 3. Deep-Dive Root Cause Analysis

### 3.1 FM-01: Direct DXF Ingestion Crash (Critical)
* **Root Cause**: `src/cad_extractor/core.py:207` unconditionally routes the input path to `dwg2dxf.exe`:
  ```python
  cmd = [exe, "-y", os.path.abspath(dwg_path), "-o", temp_dxf]
  proc = subprocess.run(cmd, capture_output=True, text=True)
  ```
* **Impact**: Supplying a `.dxf` file causes `dwg2dxf.exe` to fail with `ERROR: Invalid DWG, magic: 0 SECTI`, raising a `RuntimeError` even though the engine has native `ezdxf` support.
* **Remediation**: Check file extension or magic bytes. If `.dxf`, bypass `dwg2dxf` and open directly with `ezdxf.readfile()`.

### 3.2 FM-06: Arc & Circle Extents Center-Only Defect (Critical)
* **Root Cause**: `src/cad_extractor/core.py:348` and `364`:
  ```python
  elif etype == "ARC":
      c = entity.dxf.center
      update_bounds(c.x, c.y)  # ONLY center is updated!
  ```
* **Impact**: For any file containing only arcs or circles (e.g. `2013_Arc.dwg` and `2018_Arc.dwg`), the bounding box width and height are reported as `0.0`, despite a radius of `8.293`. Downstream vector exporters will render an empty or clipped canvas.
* **Remediation**: Expand bounds by radius:
  ```python
  update_bounds(c.x - r, c.y - r)
  update_bounds(c.x + r, c.y + r)
  ```

### 3.3 FM-08: Lone Unicode Surrogate Serialization Crash (Critical)
* **Root Cause**: Windows CAD drawings created under older UCS-2 codepages often have unpaired UTF-16 surrogates (`\ud800`). Pydantic models accept these in memory, but Pydantic's Rust JSON serializer strictly rejects lone surrogates with `UnicodeEncodeError: surrogates not allowed`.
* **Remediation**: Sanitize strings in `clean_cad_text`:
  ```python
  clean = text.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
  ```

### 3.4 FM-02: Absence of Subprocess Timeout (Critical)
* **Root Cause**: `subprocess.run(cmd, capture_output=True, text=True)` lacks `timeout=60`.
* **Impact**: Circular block definitions or deeply corrupt DWGs that trigger loops in LibreDWG can freeze worker processes indefinitely.
* **Remediation**: Add explicit timeout and catch `subprocess.TimeoutExpired`:
  ```python
  proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
  ```

---

## 4. Test Automation & Verification

### 4.1 Fixture Inventory (`tests/fixtures/`)
All 29 adversarial fixtures are generated deterministically by `tests/generate_fixtures.py`:
- 4 Empty CAD Fixtures (`empty_01` to `empty_04`)
- 6 Extreme Spatial Dimension Fixtures (`extreme_01` to `extreme_06`)
- 5 Nested & Cyclical Block Fixtures (`blocks_01` to `blocks_05`)
- 5 Malicious Unicode & String Fixtures (`unicode_01` to `unicode_05`)
- 3 Massive Entity Count Fixtures (`massive_01` 10k lines, `massive_02` 50k mixed, `massive_03` 5k components)
- 6 Corrupted Stream Fixtures (`corrupt_01` to `corrupt_06`)

### 4.2 Automated Test Execution
Run the full test suite using Python's standard `unittest`:
```bash
python -m unittest discover tests
```
**Results**:
```
Ran 33 tests in 4.167s
OK
```
* **7 Baseline Tests** in `tests/test_extractor.py`: PASSED (100%)
* **26 Invariant & Stress Tests** in `tests/test_adversarial.py`: PASSED (100%)
* **Production Code Integrity**: Confirmed 0 modifications to `src/cad_extractor/`.

---

## 5. Architectural Remediation Blueprint (Action Items for Next Release)

1. **Dual-Format Dispatcher**:
   Support native `.dxf` inputs alongside `.dwg` by checking file extension and skipping the LibreDWG conversion step.
2. **Robust Bounds Computation**:
   * Include arc/circle radii in `update_bounds()`.
   * Include `defpoint2` for `DIMENSION` entities.
   * Separate Model Space extents from Paper Space layout extents.
3. **Subprocess Hardening**:
   * Add `timeout=120` to `subprocess.run()`.
   * Always check `proc.returncode != 0` first before inspecting `os.path.exists(temp_dxf)`.
4. **Surrogate-Safe Text Cleaning**:
   * Pass all CAD text through surrogate sanitization to guarantee UTF-8 JSON compliance.
5. **Safe Color Bounds**:
   * Guard `resolve_entity_color` with `if 0 <= aci <= 255:` to prevent negative ACI `IndexError`.
