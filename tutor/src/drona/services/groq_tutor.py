from __future__ import annotations

import re

import httpx

from drona.contracts import ContextPack, TutorAnswer
from drona.services.groq_client import ProviderError, request_with_retry

CANONICAL_NOT_FOUND = "Not found in the uploaded material."


def normalize_for_speech(text: str) -> str:
    text = re.sub(r"```", "", text)
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*]\s+", "", text)
    return " ".join(text.split())


def extract_text(payload: dict) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("tutor provider returned an invalid response") from exc
    if not isinstance(content, str):
        raise ProviderError("tutor provider returned an invalid response")
    return content.strip()


class GroqTutor:
    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        base_url: str,
        model: str,
        max_output_tokens: int,
        *,
        reasoning_effort: str = "low",
        include_reasoning: bool = False,
        retries: int = 2,
    ) -> None:
        self.client, self.api_key, self.base_url = client, api_key, base_url.rstrip("/")
        self.model, self.max_output_tokens = model, max_output_tokens
        self.reasoning_effort, self.include_reasoning, self.retries = (
            reasoning_effort,
            include_reasoning,
            retries,
        )

    async def answer(self, question: str, context: ContextPack, *, turn_id: str) -> TutorAnswer:
        if not context.sources:
            return TutorAnswer(CANONICAL_NOT_FOUND, unsupported=True)
        system = (
            "You answer using ONLY the SOURCE BLOCKS. Cite every factual claim by "
            "appending the exact bracketed source id at the end of the sentence.\n\n"
            "Example:\nSOURCE BLOCKS:\n[S1] ATP stores energy.\nQUESTION: What stores "
            "energy?\nANSWER: ATP stores energy in its phosphate bonds [S1].\n\n"
            "Now answer the real question the same way. Use at most 80 words of plain "
            "prose with no headings, lists, tables, or code fences. If the blocks cannot "
            "answer it, reply exactly NOT_FOUND."
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": f"SOURCE BLOCKS:\n{context.text}\n\nQUESTION:\n{question}",
                },
            ],
            "max_completion_tokens": self.max_output_tokens,
            "reasoning_effort": self.reasoning_effort,
            "include_reasoning": self.include_reasoning,
            "temperature": 0.3,
        }

        async def send() -> httpx.Response:
            return await self.client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )

        response = await request_with_retry(send, label="tutor provider", retries=self.retries)
        try:
            text = extract_text(response.json())
        except ValueError as exc:
            raise ProviderError("tutor provider returned an invalid response") from exc
        if text == "NOT_FOUND":
            return TutorAnswer(CANONICAL_NOT_FOUND, unsupported=True)
        return TutorAnswer(normalize_for_speech(text))
