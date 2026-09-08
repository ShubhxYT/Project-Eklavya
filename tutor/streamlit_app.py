from __future__ import annotations

import json
import tempfile
from pathlib import Path

import streamlit as st

from drona.ingestion.docling_parser import DoclingParser
from drona.ingestion.validation import UploadRejected, validate_upload
from drona.knowledge.okf_writer import OKFWriter


DATA_DIR = Path(__file__).resolve().parent / "data"
CHATBOT_URL = "http://localhost:7860/client/"
MAX_BYTES = 25 * 1024 * 1024
MAX_PAGES = 200


def ingest_document(filename: str, content: bytes, data_dir: Path = DATA_DIR) -> str:
    checked = validate_upload(filename, content, max_bytes=MAX_BYTES, max_pages=MAX_PAGES)
    parser = DoclingParser(timeout_seconds=180.0)
    with tempfile.TemporaryDirectory() as temp_dir:
        source = Path(temp_dir) / checked.filename
        source.write_bytes(checked.content)
        parsed = parser.parse(source, max_pages=MAX_PAGES)
    OKFWriter(data_dir).publish(checked, parsed.document_json, parsed.sections)
    return checked.course_id


def main() -> None:
    st.set_page_config(page_title="Document ingestion")
    st.title("Ingest a document")
    st.caption("Upload a PDF or DOCX to prepare it for the tutor.")

    uploaded = st.file_uploader("Choose a document", type=["pdf", "docx"])
    if not st.button("Ingest and open chatbot", type="primary", disabled=uploaded is None):
        return

    try:
        with st.spinner("Ingesting document..."):
            course_id = ingest_document(uploaded.name, uploaded.getvalue())
    except UploadRejected as exc:
        st.error(str(exc))
        return
    except Exception as exc:
        st.error(f"Ingestion failed: {type(exc).__name__}: {exc}")
        return

    st.success(f"Ingested successfully: {course_id}")
    st.components.v1.html(
        f"<script>window.top.location.href = {json.dumps(CHATBOT_URL)};</script>",
        height=0,
    )


if __name__ == "__main__":
    main()
