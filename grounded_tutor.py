"""Pipecat LLM processor that grounds answers in an ingested Drona OKF course.

Reuses the vendored drona modules (FileCatalog BM25 retrieval, GroqTutor grounded
generation, and citation validation). On each user turn it retrieves the relevant
course sections, asks the tutor to answer ONLY from those sources, validates the
citations, and emits the answer to the transcript and to TTS.

Citations appear in the text transcript but are stripped from the spoken audio.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Reuse the vendored drona runtime modules (no Docling/Streamlit pulled in).
sys.path.insert(0, str(Path(__file__).resolve().parent / "tutor" / "src"))

from drona.contracts import ContextPack, TutorAnswer  # noqa: E402
from drona.knowledge.catalog import FileCatalog  # noqa: E402
from drona.knowledge.citations import CitationError, validate_answer  # noqa: E402
from drona.services.groq_client import ProviderError, request_with_retry  # noqa: E402
from drona.services.groq_tutor import (  # noqa: E402
    GroqTutor,
    extract_text,
    normalize_for_speech,
)

from pipecat.frames.frames import (  # noqa: E402
    Frame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor  # noqa: E402

CANONICAL_NOT_FOUND = "Not found in the uploaded material."

CITATION_RE = re.compile(r"\[S[0-9]+\]")


def citation_strip(text: str) -> str:
    """Remove [S#] citation markers from text destined for TTS."""
    stripped = CITATION_RE.sub("", text)
    return re.sub(r"\s+([.,;:!?])", r"\1", stripped)


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
            r"\b(hello|hi|hey|hiya|good\s+(morning|afternoon|evening|night)|"
            r"how\s+(are\s+you|is\s+it\s+going)|how's\s+it\s+going|"
            r"hows\s+it\s+going|what's\s+up|whats\s+up|what\s+is\s+up|"
            r"nice\s+to\s+meet\s+you|thanks|thank\s+you|"
            r"bye|goodbye|see\s+you|take\s+care)\b",
            text.casefold(),
        )
    )


def _answer(text: str):
    return TutorAnswer(normalize_for_speech(text))


def _unsupported_answer(text: str):
    return TutorAnswer(text, unsupported=True)


class GroundedTutorProcessor(FrameProcessor):
    """Replaces the LLM slot: answers the user's question from the course."""

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

        answer, sources = await self._grounded_or_fallback(question, context)

        if answer.citation_ids:
            # Grounded: transcript keeps citations (TTS skips it); a separate
            # clean text frame drives TTS so citations are never spoken.
            transcript = LLMTextFrame(answer.text)
            transcript.skip_tts = True
            await self.push_frame(transcript, direction)
            spoken = citation_strip(answer.text).strip()
            if spoken:
                spoken_frame = LLMTextFrame(spoken)
                spoken_frame.append_to_context = False
                await self.push_frame(spoken_frame, direction)
        else:
            # Fallback/chit-chat: no citations, so transcript and speech share
            # one frame (pushing duplicates confuses the client display).
            await self.push_frame(LLMTextFrame(answer.text), direction)
        await self.push_frame(LLMFullResponseEndFrame(), direction)

    async def _grounded_or_fallback(self, question: str, context: ContextPack):
        """Answer from the material when possible; otherwise give a general
        chit-chat answer that notes the material doesn't cover it."""
        if not context.sources:
            return await self._chitchat(question)

        try:
            raw = await self.tutor.answer(question, context, turn_id=question)
            if raw.unsupported:
                # Material exists but cannot answer this question.
                return await self._chitchat(question)
            return validate_answer(raw, context)
        except (CitationError, ProviderError) as exc:
            return await self._chitchat(question, error=str(exc))

    async def _chitchat(self, question: str, *, error: str | None = None):
        """General conversational answer that flags when the material can't help.

        Pure pleasantries (greetings etc.) are answered without the caveat;
        everything else opens with a note that the document doesn't cover it,
        then answers from general knowledge. The caveat is prepended
        deterministically rather than relying on the model to follow the
        instruction.
        """
        caveat = ""
        if _is_pleasantry(question):
            # Greetings/small talk always get a plain friendly reply, even
            # when the tutor call errored on the way here.
            caveat = ""
        elif error:
            caveat = "Although I couldn't verify that in your document, "
        else:
            caveat = "Although your document doesn't have that answer, "
        instruction = (
            "You are a helpful assistant in a voice conversation. "
            "Your responses are spoken aloud, so avoid emojis, bullet points, "
            "or formatting that can't be spoken. Answer helpfully in plain "
            "conversational prose."
        )
        try:
            text = await self._chat_completion(question, instruction)
        except ProviderError:
            return _unsupported_answer("Not found in the uploaded material.")
        if caveat:
            text = f"{caveat} {text}".strip()
        return _answer(text), ()

    async def _chat_completion(self, question: str, instruction: str) -> str:
        payload = {
            "model": self.tutor.model,
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": question},
            ],
            # ponytail: 700 so reasoning tokens never starve the actual answer
            # (the grounded tutor's 260 cap is for the short cited answers).
            "max_completion_tokens": 700,
            "reasoning_effort": self.tutor.reasoning_effort,
            "temperature": 0.3,
        }

        async def send():
            return await self.tutor.client.post(
                f"{self.tutor.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.tutor.api_key}"},
                json=payload,
            )

        # The model is stochastic; an empty content field is retryable.
        for _ in range(2):
            response = await request_with_retry(send, label="tutor provider", retries=self.tutor.retries)
            text = extract_text(response.json())
            if text:
                return text
        raise ProviderError("tutor provider returned an empty response")
