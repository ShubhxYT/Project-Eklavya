"""Pipecat LLM processor that grounds answers in an ingested Drona OKF course.

Reuses the vendored drona modules (FileCatalog BM25 retrieval, GroqTutor grounded
generation, and citation validation). On each user turn it retrieves the relevant
course sections, asks the tutor to answer ONLY from those sources, validates the
citations, and streams the answer to the transcript and to TTS.

Answers are streamed chunk-by-chunk so TTS can speak sentence-by-sentence instead
of waiting for the complete response. Citations appear in the text transcript but
are stripped from the spoken audio.
"""
from __future__ import annotations

import json
import re
import sys
from collections.abc import AsyncIterator
from pathlib import Path

# Reuse the vendored drona runtime modules (no Docling/Streamlit pulled in).
sys.path.insert(0, str(Path(__file__).resolve().parent / "tutor" / "src"))

import httpx  # noqa: E402

from drona.knowledge.catalog import FileCatalog  # noqa: E402
from drona.services.groq_client import ProviderError  # noqa: E402
from drona.services.groq_tutor import GroqTutor  # noqa: E402

from pipecat.frames.frames import (  # noqa: E402
    Frame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor  # noqa: E402

CANONICAL_NOT_FOUND = "Not found in the uploaded material."
CITATION_RE = re.compile(r"\[S[0-9]+\]")

GROUNDED_SYSTEM = (
    "You answer using ONLY the SOURCE BLOCKS. Cite every factual claim by "
    "appending the exact bracketed source id at the end of the sentence.\n\n"
    "Example:\nSOURCE BLOCKS:\n[S1] ATP stores energy.\nQUESTION: What stores "
    "energy?\nANSWER: ATP stores energy in its phosphate bonds [S1].\n\n"
    "Now answer the real question the same way. Use at most 80 words of plain "
    "prose with no headings, lists, tables, or code fences. If the blocks cannot "
    "answer it, reply exactly NOT_FOUND."
)
CHITCHAT_SYSTEM = (
    "You are a helpful assistant in a voice conversation. "
    "Your responses are spoken aloud, so avoid emojis, bullet points, "
    "or formatting that can't be spoken. Be brief and friendly."
)


def citation_strip(text: str) -> str:
    """Remove [S#] citation markers from text destined for TTS."""
    stripped = CITATION_RE.sub("", text)
    return re.sub(r"\s+([.,;:!?])", r"\1", stripped)


def _redact_invalid_citations(text: str, valid: set[str]) -> str:
    """Drop citation markers whose source id is not in the provided context."""

    def repl(match: re.Match) -> str:
        return match.group(0) if match.group(0)[1:-1] in valid else ""

    return CITATION_RE.sub(repl, text)


def latest_user_text(context) -> str:
    """Return the text of the last user message in the LLM context."""
    for message in reversed(context.get_messages()):
        if message.get("role") == "user":
            content = message.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        return part.get("text", "")
    return ""


def _is_pleasantry(text: str) -> bool:
    """True for greetings/pleasantries that should be answered without a caveat."""
    return bool(
        re.search(
            r"\b(hello|hi|hey|good\s+(morning|afternoon|evening)|how\s+are\s+you|"
            r"thanks|thank\s+you|bye|goodbye|what's\s+up|whats\s+up)\b",
            text.casefold(),
        )
    )


class GroundedTutorProcessor(FrameProcessor):
    """Replaces the LLM slot: streams answers grounded in the course."""

    def __init__(
        self,
        *,
        catalog: FileCatalog,
        tutor: GroqTutor,
        course_id: str,
    ) -> None:
        super().__init__()
        self.catalog = catalog
        self.tutor = tutor
        self.course_id = course_id

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if not isinstance(frame, LLMContextFrame):
            # Forward everything we don't consume (StartFrame, audio, VAD, ...).
            await self.push_frame(frame, direction)
            return

        question = latest_user_text(frame.context)
        if not question:
            return

        context = self.catalog.build_context(self.course_id, question)
        await self.push_frame(LLMFullResponseStartFrame(), direction)

        if context.sources:
            valid = set(context.sources)
            try:
                await self._stream_grounded(question, context, direction, valid)
            except ProviderError:
                await self._stream_fallback(question, direction, error="tutor unavailable")
        else:
            await self._stream_fallback(question, direction)

        await self.push_frame(LLMFullResponseEndFrame(), direction)

    async def _stream_grounded(
        self, question: str, context, direction: FrameDirection, valid: set[str]
    ) -> None:
        user = f"SOURCE BLOCKS:\n{context.text}\n\nQUESTION:\n{question}"
        buffer: list[str] = []
        seen_first_token = False
        async for chunk in self._stream_completion(GROUNDED_SYSTEM, user):
            buffer.append(chunk)
            if not seen_first_token:
                if "".join(buffer).strip():
                    seen_first_token = True
                    if "".join(buffer).strip().startswith("NOT_FOUND"):
                        await self._push_transcript(CANONICAL_NOT_FOUND, direction, set())
                        await self._push_spoken(CANONICAL_NOT_FOUND, direction)
                        return
            await self._flush_sentences(buffer, direction, valid)
        await self._push_remaining(buffer, direction, valid)

    async def _stream_fallback(
        self, question: str, direction: FrameDirection, *, error: str | None = None
    ) -> None:
        caveat = ""
        if error:
            caveat = "I could not verify that from the uploaded material."
        elif not _is_pleasantry(question):
            caveat = "I couldn't find that in the uploaded material."
        buffer: list[str] = []
        if caveat:
            buffer.append(caveat + " ")
        try:
            async for chunk in self._stream_completion(CHITCHAT_SYSTEM, question):
                buffer.append(chunk)
                await self._flush_sentences(buffer, direction, set())
        except ProviderError:
            await self._push_remaining([CANONICAL_NOT_FOUND], direction, set())
            return
        await self._push_remaining(buffer, direction, set())

    async def _flush_sentences(
        self, buffer: list[str], direction: FrameDirection, valid: set[str]
    ) -> None:
        """Emit complete sentences as streamed frames; keep the partial tail."""
        full = "".join(buffer)
        parts = re.split(r"(?<=[.!?])\s+", full)
        if len(parts) <= 1:
            return
        ready = " ".join(parts[:-1]).strip()
        buffer.clear()
        tail = parts[-1].strip()
        if tail:
            buffer.append(tail)
        if ready:
            await self._push_transcript(ready, direction, valid)
            await self._push_spoken(ready, direction)

    async def _push_remaining(
        self, buffer: list[str], direction: FrameDirection, valid: set[str]
    ) -> None:
        full = "".join(buffer).strip()
        if not full:
            return
        if not full.endswith((".", "!", "?")):
            full += "."
        await self._push_transcript(full, direction, valid)
        await self._push_spoken(full, direction)
        buffer.clear()

    async def _push_transcript(self, text: str, direction: FrameDirection, valid: set[str]) -> None:
        if not text:
            return
        frame = LLMTextFrame(_redact_invalid_citations(text, valid))
        frame.skip_tts = True
        await self.push_frame(frame, direction)

    async def _push_spoken(self, text: str, direction: FrameDirection) -> None:
        spoken = citation_strip(text).strip()
        if not spoken:
            return
        frame = LLMTextFrame(spoken)
        frame.append_to_context = False
        await self.push_frame(frame, direction)

    async def _stream_completion(self, system: str, user: str) -> AsyncIterator[str]:
        """Stream a Groq chat completion, yielding content deltas."""
        payload = {
            "model": self.tutor.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_completion_tokens": self.tutor.max_output_tokens,
            "reasoning_effort": self.tutor.reasoning_effort,
            "include_reasoning": getattr(self.tutor, "include_reasoning", False),
            "temperature": 0.3,
            "stream": True,
        }
        try:
            async with self.tutor.client.stream(
                "POST",
                f"{self.tutor.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.tutor.api_key}"},
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices")
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"tutor provider stream failed: {exc}") from exc
