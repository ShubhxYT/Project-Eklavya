from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    course_id: str
    concept_path: Path
    title: str
    source_file: str
    pages: tuple[int, ...] = ()


@dataclass(frozen=True)
class ContextPack:
    text: str
    sources: dict[str, SourceRef]


@dataclass(frozen=True)
class TutorAnswer:
    text: str
    citation_ids: tuple[str, ...] = ()
    unsupported: bool = False


@dataclass(frozen=True)
class TurnResult:
    turn_id: str
    transcript: str
    answer: TutorAnswer
    sources: tuple[SourceRef, ...] = ()
    audio: bytes | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)
    warning: str | None = None


class SpeechToText(Protocol):
    async def transcribe(self, wav: bytes, *, keyterms: tuple[str, ...] = ()) -> str: ...


class TutorModel(Protocol):
    async def answer(
        self,
        question: str,
        context: ContextPack,
        *,
        turn_id: str,
        concise: bool = False,
    ) -> TutorAnswer: ...


class KnowledgeCatalog(Protocol):
    def build_context(self, course_id: str, query: str) -> ContextPack: ...


class TextToSpeech(Protocol):
    async def synthesize(self, text: str) -> bytes: ...
