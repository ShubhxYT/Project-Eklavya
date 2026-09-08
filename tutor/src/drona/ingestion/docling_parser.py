from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from pathlib import Path

from docling.chunking import HierarchicalChunker
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableStructureOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

from drona.knowledge.okf_schema import CourseSection


@dataclass(frozen=True)
class ParsedDocument:
    document_json: dict
    sections: tuple[CourseSection, ...]


class ParserTimedOut(RuntimeError):
    pass


class DocumentLimitExceeded(RuntimeError):
    pass


class DoclingParser:
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        options = PdfPipelineOptions()
        options.do_ocr = True
        options.do_table_structure = True
        options.table_structure_options = TableStructureOptions(do_cell_matching=True)
        options.accelerator_options = AcceleratorOptions(
            device=AcceleratorDevice.CPU, num_threads=4
        )
        options.document_timeout = timeout_seconds
        self.converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )

    def parse(self, path: Path, *, max_pages: int | None = None) -> ParsedDocument:
        with ThreadPoolExecutor(max_workers=1) as pool:
            kwargs = {"max_num_pages": max_pages} if max_pages is not None else {}
            future = pool.submit(self.converter.convert, path, **kwargs)
            try:
                result = future.result(timeout=self.timeout_seconds + 5)
            except TimeoutError as exc:
                future.cancel()
                raise ParserTimedOut("document conversion timed out") from exc
        if result.has_timeout_errors():
            raise ParserTimedOut("document conversion timed out")
        doc = result.document
        sections: list[CourseSection] = []
        for ordinal, chunk in enumerate(HierarchicalChunker().chunk(dl_doc=doc), 1):
            headings = tuple(getattr(chunk.meta, "headings", None) or ())
            title = headings[-1] if headings else f"Section {ordinal}"
            pages = sorted(
                {p.page_no for item in chunk.meta.doc_items for p in (item.prov or []) if p.page_no}
            )
            if max_pages is not None and pages and max(pages) > max_pages:
                raise DocumentLimitExceeded("converted document exceeds the page limit")
            body = re.sub(r"#_#_DOCLING_DOC_PAGE_BREAK_[^\s]*", "", chunk.text).strip()
            if not body:
                continue
            if sections and headings and sections[-1].heading_path == headings:
                previous = sections[-1]
                sections[-1] = CourseSection(
                    previous.section_id,
                    previous.title,
                    previous.body + "\n\n" + body,
                    tuple(sorted(set(previous.pages) | set(pages))),
                    headings,
                )
            else:
                slug = re_slug("-".join((*headings, str(ordinal))))
                sections.append(CourseSection(slug, title, body, tuple(pages), headings))
        return ParsedDocument(doc.export_to_dict(), tuple(sections))


def re_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:90] or "section"
