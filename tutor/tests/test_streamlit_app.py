from pathlib import Path

import pytest

from streamlit_app import ingest_document


def test_ingest_document_rejects_unsupported_files(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported document type"):
        ingest_document("notes.txt", b"not a document", tmp_path)
