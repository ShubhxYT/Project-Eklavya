# Replace Docling With Local Open Parsers

## Goal

Replace the tutor's Docling ingestion path with permissive-license, offline `pypdf` PDF extraction and `python-docx` DOCX extraction while preserving validated uploads, OKF sections, retrieval, and citations.

## Status

Ready to implement. PyMuPDF/PyMuPDF4LLM is intentionally excluded because of AGPL/commercial licensing and its PyMuPDF Pro requirement for Office documents.

## Prerequisites

- [ ] Verify or create the dedicated branch:

```bash
test "$(git branch --show-current)" = "replace-docling-with-local-parsers"
```

- [ ] Confirm `pypdf==6.18.0`, `python-docx==1.2.0`, and `pytest==9.1.1` are available to `uv` from the local cache for offline verification.

## 1. Pin Local Parser Dependencies

### Actions

- [ ] Remove `docling` from `tutor/pyproject.toml`.
- [ ] Pin `pypdf==6.18.0` and add `python-docx==1.2.0`.
- [ ] Add pinned `pytest==9.1.1` to the tutor development dependency group.
- [ ] Regenerate `tutor/uv.lock` with `uv`; do not hand-edit it. Remove Docling-only packages while retaining shared dependencies and `lxml`.
- [ ] Update the tutor README section with local setup, no-network behavior, BSD/MIT licensing, and the no-OCR limitation for scanned PDFs.

### Verification

- [ ] Run `cd tutor && uv sync --offline` in a clean environment with the resolved packages cached.
- [ ] Import `pypdf`, `docx`, and `pytest`.
- [ ] Run the existing tutor tests before parser changes.

### STOP and Commit

STOP. Commit `build: replace Docling with permissive local parsers`, then report the changes and verification command.

## 2. Add the Local PDF/DOCX Adapter

### Actions

- [ ] Create `tutor/src/drona/ingestion/pdf_docx_parser.py` and move the current parser contracts there as needed: `ParsedDocument`, `ParserTimedOut`, `DocumentLimitExceeded`, and slug generation.
- [ ] Remove `ParsedDocument.document_json`.
- [ ] Delete `tutor/src/drona/ingestion/docling_parser.py`.
- [ ] Implement PDF extraction with `pypdf.PdfReader`, processing pages independently with `page.extract_text() or ""`, using 1-based page provenance and empty heading paths.
- [ ] Implement DOCX extraction with `docx.Document`, paragraph text, built-in `Title`/`Heading N` styles, heading-path tracking, empty-body filtering, and empty `pages` tuples.
- [ ] Preserve the validated PDF page limit and bounded elapsed-time guard. Do not add OCR, models, remote services, or a Docling fallback.
- [ ] Make normalized section IDs deterministic and collision-safe.
- [ ] Add `tutor/tests/test_pdf_docx_parser.py`.

### Verification

- [ ] Test PDF mapping, page citations, empty pages, page limits, and deterministic unique IDs.
- [ ] Test DOCX title/heading/body mapping, empty paragraphs, and empty pages.
- [ ] Test setup errors and conversion failures.
- [ ] Block outbound sockets during fixture parsing and verify no network is used.

### STOP and Commit

STOP. Commit `feat: parse tutor documents with local open parsers`, then report the changes and verification command.

## 3. Publish Sections Through Both Ingestion Flows

### Actions

- [ ] Replace Docling imports/construction in `tutor/cli.py` and `tutor/streamlit_app.py` with `PdfDocxParser` without changing accepted extensions, validation limits, arguments, success output, or exception boundaries.
- [ ] Change `OKFWriter.publish` to accept sections only.
- [ ] Delete `data/docling/<course-id>/document.json` creation while retaining upload copies, atomic OKF replacement, index, section front matter, and `FileCatalog` metadata.
- [ ] Write `generated.by` as `drona/pypdf-6.18.0+python-docx-1.2.0`.
- [ ] Add or update CLI, Streamlit, and writer tests for successful ingestion, atomic replacement, required metadata, section counts, and absence of Docling output.

### Verification

- [ ] Run the focused CLI, Streamlit, writer, and parser tests.
- [ ] Exercise writer replacement with `force=True`; verify normal ingestion leaves an existing course unchanged.
- [ ] Assert metadata includes `type`, `source_file`, `source_sha256`, `pages`, `heading_path`, and local parser provenance.

### STOP and Commit

STOP. Commit `refactor: publish local parser output as OKF`, then report the changes and verification command.

## 4. Remove References and Verify Offline Behavior

### Actions

- [ ] Remove the stale Docling comment in `grounded_tutor.py` and Docling-specific pytest marker.
- [ ] Keep ignored generated `data/docling/` data disposable; do not migrate it.
- [ ] Record warmed local PDF/DOCX elapsed time, section counts, and PDF citation pages without network, model, or OCR warm-up.
- [ ] Add third-party license notices for `pypdf`, `python-docx`, and `lxml` if the project distributes them.

### Verification

```bash
cd tutor && uv run pytest
cd tutor && uv lock --check
```

- [ ] Run offline CLI and Streamlit ingestion for one PDF and one DOCX; load both bundles through `FileCatalog`; verify section text and PDF citations.
- [ ] Search production sources, manifests, lockfiles, and user documentation for `docling`, `littleparse`, `pymupdf`, and `pymupdf4llm`, excluding this historical plan and Git history; no production reference may remain.
- [ ] Verify local parsing works without MLX, model assets, credentials, or network access.

### STOP and Commit

STOP. Commit `docs: remove Docling ingestion references` only after all offline verifications pass, then report the changes and checks.
