# Feature name

Replace Docling with local permissive-license parsers

# Branch name

`replace-docling-with-local-parsers`

# Description

Replace the tutor's Docling ingestion path with local `pypdf` PDF extraction and `python-docx` DOCX extraction.

# Goal

Ingest PDF and DOCX files in-process without a hosted parser, credentials, service process, model download, or runtime network access. Preserve the CLI and Streamlit flows, upload validation, `CourseSection` metadata, retrieval, and PDF citations while avoiding PyMuPDF/PyMuPDF4LLM AGPL or commercial licensing.

## Confirmed design

- `tutor/src/drona/ingestion/docling_parser.py` is the only conversion implementation. `tutor/cli.py` and `tutor/streamlit_app.py` construct it, then pass `ParsedDocument.document_json` and `sections` to `OKFWriter`.
- `FileCatalog` reads the OKF section Markdown and front matter only. No code reads `data/docling/<course-id>/document.json`, so the raw Docling export must be removed, not migrated.
- Validation already enforces accepted types, size, PDF signature/page count, DOCX signature, filename sanitization, and course identity. Keep it as the trust boundary.
- `pypdf==6.18.0` is BSD-3-Clause licensed and supports Python 3.11-3.12. `python-docx==1.2.0` is MIT licensed, supports Python 3.11-3.12, and uses the BSD-licensed `lxml` dependency.
- PyMuPDF4LLM is not used because its PyMuPDF dependency is AGPL/commercial licensed and its documented Office support requires PyMuPDF Pro.

## Runtime behavior

- Parsing runs entirely in-process against local Python packages. It must not start a server, read credentials, call an HTTP API, download a model, or require MLX.
- PDFs use `pypdf.PdfReader`; pages are extracted independently with `page.extract_text() or ""`. Each non-empty page becomes a `CourseSection` with a 1-based `pages` tuple containing that page number and an empty `heading_path` because `pypdf` has no semantic heading model.
- DOCX files use `docx.Document`; paragraph text and built-in `Title`/`Heading N` styles produce heading paths and sections. DOCX `pages` remain empty because `python-docx` cannot compute stable rendered page numbers.
- Scanned or image-only PDFs are not OCR'd by this replacement. They produce no extracted sections unless the PDF already contains a text layer; the README and tests must state this limitation.
- Missing or invalid parser packages fail as setup errors before conversion. Conversion errors retain concise local context. There is no remote or alternate parser fallback.
- Preserve the existing timeout boundary around local conversion and the validated PDF page limit. Deterministically make normalized section IDs unique.

## Licensing

Redistributed artifacts must retain the `pypdf` BSD-3-Clause and `python-docx` MIT notices, plus the BSD-licensed `lxml` notice where applicable. Do not add PyMuPDF, PyMuPDF4LLM, PyMuPDF Pro, Docling, or OCR/model dependencies.

# Implementation steps

## 1. Pin local permissive-license parser dependencies

**Commit:** `build: replace Docling with permissive local parsers`

**Files**

- `tutor/pyproject.toml`
- `tutor/uv.lock`
- `README.md`

**What**

- Remove `docling`.
- Pin `pypdf==6.18.0` and add `python-docx==1.2.0`.
- Add pinned `pytest==9.1.1` to the tutor development dependency group.
- Regenerate the lockfile with `uv`; inspect it rather than editing it. Remove Docling-only transitive packages while retaining shared dependencies and `lxml`.
- Document the local parser setup, permissive licenses, no-network behavior, and the no-OCR limitation for scanned PDFs.

**Testing**

- Run `cd tutor && uv sync --offline` from a clean environment with the resolved packages cached.
- Import `pypdf`, `docx`, and `pytest`.
- Run the existing tutor tests before parser changes.

## 2. Add the local PDF/DOCX parser adapter

**Commit:** `feat: parse tutor documents with local open parsers`

**Files**

- `tutor/src/drona/ingestion/pdf_docx_parser.py` (new)
- `tutor/src/drona/ingestion/docling_parser.py` (delete)
- `tutor/tests/test_pdf_docx_parser.py` (new)

**What**

- Move `ParsedDocument`, `ParserTimedOut`, `DocumentLimitExceeded`, and slug generation to the new adapter as needed by current callers. Remove `ParsedDocument.document_json`.
- Implement PDF parsing with `PdfReader`, page-local extraction, 1-based page provenance, empty heading paths, and deterministic unique section IDs.
- Implement DOCX parsing with `Document`, paragraph styles, heading-path tracking, title/heading fallback, empty-body filtering, and empty `pages` tuples. Do not fabricate DOCX page numbers.
- Preserve the validated page limit and a bounded elapsed-time guard around local conversion. Do not add OCR, models, remote services, or a fallback to Docling.

**Testing**

- Test PDF text mapping, page citations, empty pages, page limits, and deterministic unique IDs.
- Test DOCX titles, nested headings, body mapping, empty paragraphs, and empty pages.
- Test missing parser setup errors and conversion failures.
- Block outbound sockets during fixture parsing and verify no network is used.

## 3. Publish local parser sections through both ingestion flows

**Commit:** `refactor: publish local parser output as OKF`

**Files**

- `tutor/cli.py`
- `tutor/streamlit_app.py`
- `tutor/src/drona/knowledge/okf_writer.py`
- `tutor/tests/test_streamlit_app.py`
- `tutor/tests/test_okf_writer.py` (new)
- `tutor/tests/test_cli.py` (new)

**What**

- Replace both Docling imports/construction with `PdfDocxParser` without changing accepted extensions, validation limits, command arguments, success output, or the existing user-facing exception boundary.
- Change `OKFWriter.publish` to accept sections only. Delete creation of `data/docling/<course-id>/document.json`; retain the original upload copy, atomic OKF replacement, index, section front matter, and `FileCatalog` contract.
- Write `generated.by` as the pinned local parser package versions, for example `drona/pypdf-6.18.0+python-docx-1.2.0`. Do not persist credentials, URLs, model paths, or licensing-incompatible packages.

**Testing**

- Extend Streamlit coverage with a patched local parser and assert successful ingestion creates an OKF bundle but no `data/docling/` output.
- Add writer coverage for atomic replacement and required metadata: `type`, `source_file`, `source_sha256`, `pages`, `heading_path`, and local parser provenance.
- Add CLI coverage for section-count output and absence of Docling output.

## 4. Remove Docling references and verify the offline replacement

**Commit:** `docs: remove Docling ingestion references`

**Files**

- `README.md`
- `grounded_tutor.py`
- `tutor/pyproject.toml`
- `tutor/uv.lock`

**What**

- Replace the README's Docling claim with the local `pypdf`/`python-docx` setup and behavior. Remove the stale Docling comment in `grounded_tutor.py` and the Docling-specific pytest marker.
- Confirm generated data can be discarded and re-ingested; do not migrate ignored `data/docling/` contents.
- Keep benchmarks local and warmed: record representative PDF and DOCX conversion elapsed time, section count, and PDF citation pages. Do not include network, model, or OCR warm-up.
- Add third-party license notices for `pypdf`, `python-docx`, and `lxml` if the project distributes them.

**Testing**

- Run `cd tutor && uv run pytest` and `uv lock --check`.
- Run offline CLI and Streamlit smoke ingestion for one local PDF and DOCX, load both OKF bundles with `FileCatalog`, and confirm retrieval exposes section text and PDF citations.
- Search source, manifests, lockfiles, and user documentation for `docling`, `littleparse`, `pymupdf`, and `pymupdf4llm`, excluding this historical plan and Git history; no production reference may remain.
- Run the no-network parser tests and verify CPU-only local parsing without MLX or model assets.
