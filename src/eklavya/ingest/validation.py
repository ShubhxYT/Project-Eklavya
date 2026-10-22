from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


class UploadRejected(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    content: bytes
    sha256: str
    course_id: str
    media_type: str
    page_count: int | None


def _slug(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return value[:60] or "course"


def _safe_name(name: str) -> str:
    raw = name.replace("\\", "/").split("/")[-1]
    suffix = Path(raw).suffix.lower()
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", Path(raw).stem).strip(".-") or "document"
    return f"{stem[:100]}{suffix}"


def validate_upload(
    name: str, content: bytes, *, max_bytes: int, max_pages: int
) -> ValidatedUpload:
    filename = _safe_name(name)
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise UploadRejected("unsupported document type")
    if not content or len(content) > max_bytes:
        raise UploadRejected("document size exceeds limit")
    page_count: int | None = None
    if suffix == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise UploadRejected("PDF signature mismatch")
        try:
            page_count = len(PdfReader(BytesIO(content)).pages)
        except Exception as exc:
            raise UploadRejected("invalid PDF") from exc
        if page_count > max_pages:
            raise UploadRejected("PDF page limit exceeded")
        media_type = "application/pdf"
    else:
        if not content.startswith(b"PK"):
            raise UploadRejected("DOCX signature mismatch")
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    digest = hashlib.sha256(content).hexdigest()
    return ValidatedUpload(
        filename,
        content,
        digest,
        f"{digest[:12]}-{_slug(Path(filename).stem)}",
        media_type,
        page_count,
    )
