from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import frontmatter

from drona.ingestion.validation import ValidatedUpload
from drona.knowledge.okf_schema import CourseSection


class OKFWriter:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def publish(
        self,
        upload: ValidatedUpload,
        document_json: dict,
        sections: list[CourseSection] | tuple[CourseSection, ...],
        *,
        force: bool = False,
    ) -> Path:
        target = self.data_dir / "okf" / upload.course_id
        if target.exists() and not force:
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = Path(tempfile.mkdtemp(prefix=f".{upload.course_id}-", dir=target.parent))
        try:
            self._write_bundle(temp, upload, document_json, sections)
            old = target.with_name(f".{target.name}.old")
            if old.exists():
                shutil.rmtree(old)
            if target.exists():
                os.replace(target, old)
            os.replace(temp, target)
            if old.exists():
                shutil.rmtree(old)
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            raise
        return target

    def _write_bundle(
        self,
        root: Path,
        upload: ValidatedUpload,
        document_json: dict,
        sections: list[CourseSection] | tuple[CourseSection, ...],
    ) -> None:
        upload_dir = self.data_dir / "uploads" / upload.course_id
        docling_dir = self.data_dir / "docling" / upload.course_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        docling_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / upload.filename).write_bytes(upload.content)
        (docling_dir / "document.json").write_text(
            json.dumps(document_json, ensure_ascii=False, indent=2)
        )
        section_dir = root / "sections"
        section_dir.mkdir(parents=True)
        links: list[str] = []
        generated = {
            "by": "drona/docling-2.126.0",
            "at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        }
        for section in sorted(sections, key=lambda item: item.section_id):
            filename = f"{section.section_id}.md"
            metadata = {
                "type": "CourseSection",
                "title": section.title,
                "description": section.body[:180].replace("\n", " "),
                "tags": ["course", "tutor"],
                "source_file": upload.filename,
                "source_sha256": upload.sha256,
                "pages": list(section.pages),
                "heading_path": list(section.heading_path),
                "generated": generated,
            }
            (section_dir / filename).write_text(
                frontmatter.dumps(frontmatter.Post(section.body, **metadata))
            )
            links.append(f"- [{section.title}](sections/{filename})")
        index = frontmatter.Post(
            "# Course sections\n\n" + "\n".join(links),
            okf_version="0.2",
            title=Path(upload.filename).stem,
            source_sha256=upload.sha256,
        )
        (root / "index.md").write_text(frontmatter.dumps(index))
