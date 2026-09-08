# Remove Docling and Use Local LittleParse

## Goal

Replace the tutor's Docling ingestion path with an offline, local LittleParse adapter while preserving validated uploads, OKF sections, retrieval, and citations.

## Status: Blocked by Missing LittleParse Contract

This implementation cannot safely be written yet. No LittleParse distribution, source repository, import name, immutable version, model artifact, or Python API is available in the repository or authoritative public package sources. Inventing any of those details would create a non-installable dependency and a parser adapter with an unverified interface.

## Prerequisites

- [ ] Verify the intended branch before making implementation changes:

```bash
test "$(git branch --show-current)" = "remove-docling-use-littleparse"
```

- [ ] Provide the authoritative LittleParse repository or package URL in `plans/remove-docling-use-littleparse/plan.md`.
- [ ] Provide its immutable package version or source commit.
- [ ] Provide its Python distribution and import name.
- [ ] Provide its supported Python and platform matrix for CPU and MLX.
- [ ] Provide its exact model artifact name/version and pre-provisioned local path.
- [ ] Provide its documented offline initialization option that prevents model downloads.
- [ ] Provide its documented explicit CPU and MLX device values or constructor arguments.
- [ ] Provide its PDF and DOCX conversion calls, result schema, section/body fields, heading-path fields, and PDF page-provenance fields.
- [ ] Provide its timeout and document-limit controls, if the library supplies them.
- [ ] Provide its local package/artifact installation command usable by `uv sync --offline`.

- [ ] Add `pytest` as a pinned tutor development dependency before using `uv run pytest` as a clean-environment verification command. It is not currently declared or locked.

Technology currently in scope: Python `>=3.11,<3.13`, `uv`, Hatchling, Streamlit `>=1.63.0`, `pypdf>=6,<7`, `python-frontmatter==1.3.0`, and `rank-bm25==0.2.2`. The tutor is independent from the root Python 3.14 Pipecat project and must be managed from `tutor/`.

## 1. Pin and Verify the Local LittleParse Runtime

### Actions

- [ ] STOP: do not edit `tutor/pyproject.toml`, `tutor/uv.lock`, or `README.md` until every prerequisite above is supplied.
- [ ] After the authoritative package and offline model contract are supplied, regenerate this document. The required dependency declaration, platform marker, local-artifact command, README instructions, and exact offline smoke tests depend on those facts.

### Verification

- [ ] Confirm that the supplied distribution installs into a clean tutor environment entirely from its local cache/artifact source.
- [ ] Confirm that its documented PDF and DOCX smoke conversions complete with outbound networking disabled and without credentials, a local endpoint, or model downloads.

### STOP and Commit

STOP. No commit is valid for `build: add offline LittleParse runtime` until the authoritative LittleParse dependency and API contract are available.

## 2. Add the Device Selector and Local LittleParse Adapter

### Actions

- [ ] STOP: do not create `tutor/src/drona/ingestion/littleparse_parser.py` or delete `tutor/src/drona/ingestion/docling_parser.py` yet.
- [ ] The adapter needs the unknown LittleParse constructor, offline-model option, device values, conversion result schema, and local setup error semantics. Those cannot be inferred from MLX or Docling.
- [ ] After Step 1 is unblocked, regenerate this document with complete code for the adapter and `tutor/tests/test_littleparse_parser.py`.

### Fixed Requirements for the Regenerated Adapter

- [ ] Return the documented MLX device only on macOS arm64 after `import mlx.core as mx` and `mx.metal.is_available()` returns true.
- [ ] Return the documented CPU device on every other platform and when that import raises only `ImportError` or `OSError`.
- [ ] Do not retry CPU after a selected MLX backend fails.
- [ ] Remove `ParsedDocument.document_json`; no remaining consumer reads it.
- [ ] Preserve empty DOCX `CourseSection.pages` tuples and use PDF pages only when the parser supplies provenance.
- [ ] Make truncated or normalized section IDs collision-safe deterministically.

### Verification

- [ ] Unit tests must cover MLX selection, CPU selection, absent local package/model errors, PDF/DOCX result mapping, unique IDs, no-network conversion, and the preserved DOCX/PDF page distinction.

### STOP and Commit

STOP. No commit is valid for `feat: parse tutor documents locally with LittleParse` until the LittleParse API identifies the exact code to call and fixtures to model.

## 3. Publish Local Parser Sections Through Both Ingestion Flows

### Actions

- [ ] STOP: do not change `tutor/cli.py`, `tutor/streamlit_app.py`, or `tutor/src/drona/knowledge/okf_writer.py` before Step 2 provides the parser provenance contract.
- [ ] The parser must explicitly expose its pinned source/version and selected backend, or `OKFWriter.publish` must receive those fields explicitly. The current `CourseSection` has no such data, so the planned `generated.by` metadata cannot otherwise be produced.
- [ ] Preserve the existing upload copy, OKF atomic replacement, `FileCatalog` section/front-matter contract, CLI output, and Streamlit exception boundary.
- [ ] Delete raw `data/docling/<course-id>/document.json` creation only after the adapter returns sections successfully.

### Verification

- [ ] Add CLI, Streamlit, and writer coverage after the adapter interface is known.
- [ ] Exercise writer replacement with `force=True`; normal current CLI and Streamlit ingestion leaves an existing course unchanged.
- [ ] Assert required section metadata: `type`, `source_file`, `source_sha256`, `pages`, `heading_path`, and local parser provenance.

### STOP and Commit

STOP. No commit is valid for `refactor: publish local parser output as OKF` until Step 2 defines how parser provenance reaches the writer.

## 4. Remove Docling References and Verify the Offline Replacement

### Actions

- [ ] After Steps 1-3 are implemented, remove the stale Docling README claim, the Docling comment in `grounded_tutor.py`, and the Docling pytest marker.
- [ ] Keep ignored generated `data/docling/` data disposable; do not migrate it.
- [ ] Record warmed, local PDF and DOCX conversion elapsed time, section counts, and PDF citation pages. Do not include a model-download or network warm-up in the benchmark.

### Verification

```bash
cd tutor && uv lock --check
```

- [ ] Run the regenerated, project-specific test command after `pytest` is declared and locked.
- [ ] Run local offline CLI and Streamlit ingestion for one PDF and one DOCX; load both bundles through `FileCatalog`; verify section text and PDF citations.
- [ ] Search production sources, manifests, lockfiles, and user documentation for `docling`, excluding `plans/remove-docling-use-littleparse/plan.md` and Git history; no production reference may remain.
- [ ] Run MLX selection tests on macOS arm64 and CPU tests in a CPU-only environment; both must parse locally without network access.

### STOP and Commit

STOP. Commit `docs: remove Docling ingestion references` only after the supplied LittleParse implementation has passed all offline verifications.
