# Feature name

Remove Docling and use local LittleParse

# Branch name

`remove-docling-use-littleparse`

# Description

Replace the tutor's Docling ingestion path with a wholly local LittleParse parser that selects MLX on supported Apple Silicon runtimes and otherwise runs its CPU backend.

# Goal

Ingest PDF and DOCX files without a hosted parser, credentials, service process, or runtime network access. Preserve the CLI and Streamlit flows, upload validation, and the `CourseSection` metadata consumed by OKF, BM25, and citations. Remove Docling code, persisted output, dependencies, and documentation.

## Confirmed constraints

- `tutor/src/drona/ingestion/docling_parser.py` is the only conversion implementation. `tutor/cli.py` and `tutor/streamlit_app.py` construct it, then pass `ParsedDocument.document_json` and `sections` to `OKFWriter`.
- `FileCatalog` reads the OKF section Markdown and front matter only. No code reads `data/docling/<course-id>/document.json`, so the raw Docling export must be removed, not migrated.
- Validation already enforces accepted types, size, PDF signature/page count, DOCX signature, filename sanitization, and course identity. Keep it as the trust boundary.
- `tutor` supports Python 3.11-3.12. The development machine is macOS and has MLX 0.32.1 installed; `mlx.core.metal.is_available()` returned `True`. Neither the tutor environment nor the repository has a LittleParse distribution or source.
- Public package/repository searches found no credible PDF/DOCX parser named `LittleParse`; PyPI and npm have no package by that name, and the only GitHub name matches are unrelated parsers. Do not substitute a similarly named hosted product or guess an import/API.
- The current parser exposes PDF page provenance when present; DOCX sections may retain an empty `pages` tuple. The replacement must preserve this distinction rather than fabricate DOCX page numbers.

## Runtime behavior

- Parsing runs in-process against locally installed LittleParse code and pre-provisioned model assets. It must not start a server, read credentials, call an HTTP API, or download a model during ingestion.
- On macOS arm64 only, attempt `import mlx.core as mx`; select LittleParse's documented MLX device only when `mx.metal.is_available()` is `True`. Treat `ImportError` or `OSError` while importing MLX, every non-macOS/arm64 platform, and a false availability result as CPU.
- Do not probe MLX by package metadata alone and do not silently retry CPU after an MLX parse/model failure. A selected-but-broken backend is a setup/conversion error, not evidence that CPU is healthy.
- If LittleParse or its required local model files are absent, fail before conversion with a dedicated, actionable setup error naming the package/model install location from its documentation. The existing CLI and Streamlit exception boundaries display that error; neither flow falls back to a remote service.

## [NEEDS CLARIFICATION: authoritative LittleParse source]

- Provide the exact repository/package, immutable version or commit, model artifact/version, and its documented Python API for local PDF and DOCX conversion. It must support an explicit MLX/CPU device choice, offline model loading, section/body output, and PDF page provenance. This is blocking: the searched public sources do not establish a legitimate package or interface, so an implementation cannot safely pin a dependency or write the adapter call.

# Implementation steps

## 1. Pin and verify the local LittleParse runtime

**Commit:** `build: add offline LittleParse runtime`

**Files**

- `tutor/pyproject.toml`
- `tutor/uv.lock`
- `README.md`

**What**

- Add the clarified LittleParse distribution or immutable Git source at its exact version/commit. Add MLX only with the source's documented platform marker or extra so Linux/Intel installations retain a CPU-capable dependency set.
- Record the required locally provisioned model artifact and the documented offline setup command/path in the tutor section of `README.md`. State that ingestion never downloads assets and requires no service or API key.
- Regenerate the lockfile with `uv`; inspect it rather than editing it. Remove `docling` and its Docling-only transitive graph, retaining project-shared dependencies.
- Verify the locked dependency can be installed from the local cache/artifact source with `uv sync --offline`; if the selected distribution cannot meet this requirement, reject it rather than adding a network fallback.

**Testing**

- Run `cd tutor && uv sync --offline` in a clean virtual environment containing the documented local artifact/model path, then import the selected LittleParse package.
- Run its documented local PDF and DOCX smoke conversion with outbound networking disabled. Confirm no API key, local endpoint, or model-download configuration is required.

## 2. Add the device selector and local LittleParse adapter

**Commit:** `feat: parse tutor documents locally with LittleParse`

**Files**

- `tutor/src/drona/ingestion/littleparse_parser.py` (new)
- `tutor/src/drona/ingestion/docling_parser.py` (delete)
- `tutor/tests/test_littleparse_parser.py` (new)

**What**

- Move `ParsedDocument`, `ParserTimedOut`, `DocumentLimitExceeded`, and slug generation to the new adapter only as needed by current callers; remove `document_json` from `ParsedDocument` because no consumer needs a raw parser export.
- Implement one small `select_device()` path: return the LittleParse MLX device only after the macOS-arm64 and `mx.metal.is_available()` checks described above; otherwise return its documented CPU device. Catch only MLX import/loading absence (`ImportError`, `OSError`) for this fallback.
- Construct LittleParse with that selected device and its documented offline-only model option. Map an absent package/model or invalid local model path to `ParserSetupError` with the exact setup instruction. Preserve `ParserTimedOut` and `DocumentLimitExceeded` where LittleParse exposes equivalent local controls; otherwise rely on the existing validated PDF page limit and retain only an elapsed-time guard around the local call.
- Map the confirmed LittleParse result to `CourseSection`: normalize text, omit empty bodies, preserve heading paths, use PDF provenance only when supplied, and create deterministic unique section IDs. Do not emulate Docling chunking or add a Docling fallback.
- Propagate LittleParse conversion failures after their concise local error context. Do not catch an MLX backend failure and re-run CPU automatically.

**Testing**

- Unit-test device selection by mocking the MLX import/backend: macOS arm64 with available Metal selects MLX; unavailable Metal, import `ImportError`/`OSError`, Intel macOS, and non-macOS select CPU without requiring MLX.
- Unit-test setup errors for a missing local model/package and verify their messages name the documented local remedy, not credentials or a URL.
- Use documented LittleParse result fixtures or a fake at its confirmed interface to test PDF and DOCX mapping, empty-section filtering, heading/title fallback, deterministic unique IDs, PDF page preservation, and empty DOCX pages.
- Add a local parser regression test that blocks outbound socket connections during a fixture conversion; it must pass with provisioned model assets.

## 3. Publish LittleParse sections through both ingestion flows

**Commit:** `refactor: publish local parser output as OKF`

**Files**

- `tutor/cli.py`
- `tutor/streamlit_app.py`
- `tutor/src/drona/knowledge/okf_writer.py`
- `tutor/tests/test_streamlit_app.py`
- `tutor/tests/test_okf_writer.py` (new)
- `tutor/tests/test_cli.py` (new)

**What**

- Replace both Docling parser imports/construction with `LittleParseParser` without changing accepted extensions, validation limits, command arguments, success output, or the existing user-facing exception boundary.
- Change `OKFWriter.publish` to accept sections only. Delete creation of `data/docling/<course-id>/document.json`; retain the original upload copy, atomic OKF replacement, index, section front matter, and `FileCatalog`-required metadata.
- Write `generated.by` as the pinned LittleParse package/source and version, plus the selected `mlx` or `cpu` backend when that provenance is available from the adapter. Do not persist a model download URL or credentials.

**Testing**

- Extend the Streamlit test with a patched local parser to verify successful ingestion creates an OKF bundle and never creates `data/docling/`.
- Add writer coverage for atomic replacement and required metadata: `type`, `source_file`, `source_sha256`, `pages`, `heading_path`, and local parser provenance.
- Add CLI ingestion coverage using the same fake local parser and assert its section-count output and no Docling output directory.

## 4. Remove Docling references and verify the offline replacement

**Commit:** `docs: remove Docling ingestion references`

**Files**

- `README.md`
- `grounded_tutor.py`
- `tutor/pyproject.toml`
- `tutor/uv.lock`

**What**

- Replace the README's Docling claim with the local LittleParse setup and the MLX/CPU selection behavior. Remove the stale Docling comment in `grounded_tutor.py` and the Docling-specific pytest marker.
- Confirm generated data can be discarded and re-ingested; do not migrate ignored `data/docling/` contents.
- Keep benchmarks local: compare representative PDF and DOCX conversion with warmed, pre-provisioned models on the same machine, recording elapsed time, section count, and PDF citation pages. Do not benchmark a network/download warm-up.

**Testing**

- Run `cd tutor && uv run pytest` and `uv lock --check`.
- Run offline CLI and Streamlit smoke ingestion for one local PDF and DOCX, load both OKF bundles with `FileCatalog`, and confirm retrieval exposes section text and PDF citations.
- Search source, manifests, lockfiles, and user documentation for `docling`, excluding this historical plan and Git history, and confirm no production references remain.
- Run the MLX and CPU selector tests on macOS arm64 and one CPU-only environment; verify the latter parses locally without MLX or network access.
