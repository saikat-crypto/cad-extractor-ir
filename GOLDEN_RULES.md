# GOLDEN_RULES.md — La Vinci Engineering & Reliability Contract

> **MANDATORY INSTRUCTION**: This document contains binding engineering invariants for the entire **La Vinci** project across all workspaces, sessions, and products. Any agent or engineer working in this repository MUST strictly follow these rules without exception.

---

## 🏛️ 1. The Zero-Regression Golden Rule: "Test Before You Commit"

Whenever a bug fix, edge-case remediation, performance tuning, or feature upgrade is made to ANY product:

1. **NO Silent Modifications**:
   - Every modification to existing product code must be explicitly communicated and justified.
2. **Pre-Commit Verification Protocol**:
   - Before any commit is created, the full automated test suite of the modified product MUST be executed.
   - If the change affects the shared IR schema or cross-product contracts, the integration/compiler test suites of all downstream products MUST also be run.
   - **Zero tests may fail**. No regression is acceptable.
3. **Baseline Roundtrip Invariance**:
   - Key benchmark fixtures (e.g. `blueprint_sample.dwg`, canonical IR payloads) must be verified to ensure their geometry and entity counts are preserved identically.

---

## 🌐 2. The GitHub Synchronization Contract

Any time a product is created, enhanced, or patched:

1. **Atomic Commits with Semantic Messages**:
   - Every change must have a clear descriptive commit message (e.g., `fix(extractor): harden ACIS SAT text decoder against non-ASCII encodings`).
2. **Immediate GitHub Push**:
   - Changes must NEVER be left lingering locally uncommitted or unpushed.
   - Changes must be pushed immediately to the corresponding remote repository on GitHub (`main` branch):
     - Product 1: [`saikat-crypto/cad-extractor-ir`](https://github.com/saikat-crypto/cad-extractor-ir)
     - Product 2: [`saikat-crypto/cad-ir-to-dxf`](https://github.com/saikat-crypto/cad-ir-to-dxf)
     - Product 3: [`saikat-crypto/cad-ir-to-pdf`](https://github.com/saikat-crypto/cad-ir-to-pdf)
3. **Repository Metadata Integrity**:
   - Repository descriptions, README badges, and CLI documentation must remain in sync with actual functionality.

---

## 📐 3. The Architecture Invariant: Clean Hub-and-Spoke

The single source of truth is **`LAVINCI_CAD_IR_V3`**:
- **Product 1 (`cad-extractor-ir`)**: Strictly input (DWG/DXF) $\to$ `LAVINCI_CAD_IR_V3` JSON.
- **Product 2 (`cad-ir-to-dxf`)**: Strictly `LAVINCI_CAD_IR_V3` JSON $\to$ Production DXF.
- **Product 3 (`cad-ir-to-pdf`)**: Strictly `LAVINCI_CAD_IR_V3` JSON $\to$ Vector PDF.
- **No Intermediate Hacks**: Never bypass the IR or daisy-chain output formats (e.g., never convert DXF to PDF when the pipeline is IR to PDF).

---

## ☁️ 4. Cloud API Deployment Invariant (AWS Lambda / ECS / FastAPI Ready)

EVERY product built in this repository—past, present, and future—MUST strictly adhere to headless, stateless, cloud-ready architecture:

1. **Pure Headless Execution (Zero Desktop / GUI Dependencies)**:
   - Engines must NEVER require an interactive window, display server, X11, Wayland, GPU rendering context, or OS desktop subsystems.
   - All compilers and extractors must run seamlessly in minimal container images (Alpine / Debian Slim / AWS Lambda Python runtimes).
2. **Stateless & In-Memory Stream Support**:
   - Every core function (extraction, compilation, reconstruction) must support in-memory data structures (`dict`, `bytes`, `io.BytesIO`, Pydantic models) in addition to filesystem paths.
   - Operations must be strictly idempotent and thread-safe without relying on persistent local state or shared disk side-effects.
3. **Fully Parameterized & Customizable Presets**:
   - Hardcoded visual or technical parameters are strictly prohibited.
   - Presets, scale factors, page sizes, line weights, color palettes, and layer filters must be configurable via structured input schemas (JSON/Pydantic/Dataclass) so API clients can pass arbitrary custom configurations per request.

---

## 🤖 5. MCP (Model Context Protocol) & AI Agent Interoperability Invariant

EVERY product must be designed and structured so it can be exposed directly as tools in an **MCP Server** for autonomous AI agents (Claude, Gemini, ChatGPT):

1. **Deterministic Structured I/O**:
   - All tool entry points must consume well-defined structured payloads (JSON schemas / Pydantic models) and return structured responses (paths, base64 data, status metrics, or parsed IR).
   - Functions must never emit unhandled exceptions or crash; errors must be captured and returned in structured, machine-readable format.
2. **Inspectability & Dynamic Control**:
   - Each product must expose introspection primitives (e.g., query drawing bounds, list layer names, inspect block definitions, calculate viewport metrics).
   - This empowers AI agents to inspect a drawing before compilation, select or synthesize custom presets, and execute precision conversions dynamically.
3. **Turnkey Tool Wrapping**:
   - Product public APIs (`__all__`) must remain clean, modular, and single-purpose, allowing each capability to be wrapped into a 10-line MCP tool definition with zero refactoring.

