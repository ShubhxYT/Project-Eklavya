from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from eklavya.ingest.streamlit_app import ingest_document  # noqa: E402


def test_ingest_document_rejects_unsupported_files(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported document type"):
        ingest_document("notes.txt", b"not a document", tmp_path)
