from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import frontmatter
from rank_bm25 import BM25Okapi

from drona.contracts import ContextPack, SourceRef

TOKEN_RE = re.compile(r"[a-z0-9]+")
LINK_RE = re.compile(r"\[[^]]+\]\(([^)]+\.md)\)")
BROAD_TERMS = {
    "all",
    "every",
    "each",
    "list",
    "explain",
    "describe",
    "summarize",
    "summary",
    "overview",
    "everything",
    "anything",
    "any",
}


def tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text.casefold())


def is_broad_query(query: str) -> bool:
    return bool(set(tokens(query)) & BROAD_TERMS)


@dataclass(frozen=True)
class CatalogIssue:
    kind: str
    path: Path


@dataclass(frozen=True)
class Concept:
    course_id: str
    path: Path
    title: str
    body: str
    source_file: str
    pages: tuple[int, ...]
    links: tuple[Path, ...]
    search_text: str


class FileCatalog:
    def __init__(self, root: Path, *, max_context_chars: int) -> None:
        self.root = root
        self.max_context_chars = max_context_chars
        self.concepts: list[Concept] = []
        self.issues: list[CatalogIssue] = []
        self.refresh()

    def refresh(self) -> None:
        self.concepts, self.issues = [], []
        for path in sorted(self.root.glob("*/sections/*.md")):
            try:
                post = frontmatter.load(path)
                metadata = post.metadata
                if not metadata.get("type"):
                    raise ValueError("missing type")
                course_id = path.parents[1].name
                title = str(metadata.get("title") or path.stem.replace("-", " ").title())
                links = tuple(
                    (path.parent / item).resolve() for item in LINK_RE.findall(post.content)
                )
                searchable = " ".join(
                    [title] * 4
                    + [str(metadata.get("description", ""))] * 2
                    + list(metadata.get("tags", [])) * 2
                    + list(metadata.get("heading_path", [])) * 3
                    + [post.content]
                )
                self.concepts.append(
                    Concept(
                        course_id,
                        path.resolve(),
                        title,
                        post.content,
                        str(metadata.get("source_file", "")),
                        tuple(sorted(set(metadata.get("pages", [])))),
                        links,
                        searchable,
                    )
                )
                for link in links:
                    if not link.exists():
                        self.issues.append(CatalogIssue("broken_link", path))
            except Exception:
                self.issues.append(CatalogIssue("malformed", path))

    def search(self, course_id: str, query: str, *, limit: int = 3) -> list[Concept]:
        selected = [item for item in self.concepts if item.course_id == course_id]
        query_tokens = tokens(query)
        if not selected or not query_tokens:
            return []
        corpus = [tokens(item.search_text) for item in selected]
        scores = BM25Okapi(corpus).get_scores(query_tokens)
        ranked = sorted(
            zip(selected, scores, strict=True), key=lambda pair: (-pair[1], pair[0].path.as_posix())
        )
        positive = [item for item, score in ranked if score > 0][:limit]
        if positive:
            known = {item.path for item in positive}
            by_path = {item.path: item for item in selected}
            for link in positive[0].links:
                if link in by_path and link not in known:
                    positive.append(by_path[link])
                    break
        return positive

    def build_context(self, course_id: str, query: str) -> ContextPack:
        sources: dict[str, SourceRef] = {}
        blocks: list[str] = []
        used = 0
        concepts = list(self.search(course_id, query))
        # ponytail: overview/aggregate queries ("all/every/list/explain/...") that already
        # matched something are broadened to cover the whole course, bounded by the context
        # budget. Queries that match nothing stay empty (genuinely out of scope).
        if concepts and is_broad_query(query):
            seen = {concept.path for concept in concepts}
            concepts.extend(
                item
                for item in self.concepts
                if item.course_id == course_id and item.path not in seen
            )
        for concept in concepts:
            source_id = f"S{len(sources) + 1}"
            header = (
                f"[{source_id}] {concept.title} | {concept.source_file}"
                f" | pages {list(concept.pages)}\n"
            )
            remaining = self.max_context_chars - used - len(header)
            if remaining <= 0:
                break
            body = concept.body[:remaining]
            blocks.append(header + body)
            used += len(header) + len(body)
            sources[source_id] = SourceRef(
                source_id,
                course_id,
                concept.path,
                concept.title,
                concept.source_file,
                concept.pages,
            )
        return ContextPack("\n\n".join(blocks)[: self.max_context_chars], sources)
