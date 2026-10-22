import asyncio
import io
import json
import re
import wave
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import httpx
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.utils.types import NOT_GIVEN, NotGiven, assert_given


@dataclass
class VoiceboxTTSSettings(TTSSettings):
    base_url: str | None | NotGiven = field(default_factory=lambda: NOT_GIVEN)


class VoiceboxTTSService(TTSService):
    Settings = VoiceboxTTSSettings
    _settings: Settings

    def __init__(
        self, *, base_url: str, profile: str = "HF Female", engine: str = "kokoro",
        language: str = "en", sample_rate: int = 24000,
        settings: Settings | None = None, http_client: httpx.AsyncClient | None = None,
        **kwargs,
    ):
        default_settings = self.Settings(model=engine, voice=profile, language=language, base_url=base_url)
        if settings is not None:
            default_settings.apply_update(settings)
        super().__init__(
            pause_frame_processing=True, push_start_frame=True, push_stop_frames=True,
            sample_rate=sample_rate, settings=default_settings, **kwargs,
        )
        self._owns_client = http_client is None
        self._client = http_client if http_client is not None else httpx.AsyncClient(timeout=60.0)

    def can_generate_metrics(self):
        return True

    async def cleanup(self):
        try:
            await super().cleanup()
        finally:
            if self._owns_client and not self._client.is_closed:
                await self._client.aclose()

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        base_url = assert_given(self._settings.base_url).rstrip("/")
        try:
            async with asyncio.timeout(60):
                response = await self._client.post(f"{base_url}/speak", json={
                    "text": text, "profile": assert_given(self._settings.voice),
                    "engine": assert_given(self._settings.model),
                    "language": str(self._settings.language or "en"),
                })
                response.raise_for_status()
                generation_id = response.json()["id"]
                if not isinstance(generation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", generation_id):
                    raise ValueError("invalid generation identifier")
                while True:
                    response = await self._client.get(f"{base_url}/generate/{generation_id}/status")
                    response.raise_for_status()
                    events = [line.split("data:", 1)[1].strip() for line in response.text.splitlines() if line.startswith("data:")]
                    status = json.loads(events[-1])
                    if status.get("status") == "completed":
                        break
                    if status.get("status") == "failed":
                        raise RuntimeError("generation failed")
                    await asyncio.sleep(.5)
                response = await self._client.get(f"{base_url}/audio/{generation_id}")
                response.raise_for_status()
                with wave.open(io.BytesIO(response.content)) as audio:
                    frame = TTSAudioRawFrame(
                        audio.readframes(audio.getnframes()), audio.getframerate(),
                        audio.getnchannels(), context_id=context_id,
                    )
            yield frame
        except Exception:
            yield ErrorFrame(error="The tutor audio is temporarily unavailable.")
