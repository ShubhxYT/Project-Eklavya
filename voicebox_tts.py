#
# Pipecat TTS service for a self-hosted voicebox server.
#
# voicebox (https://voicebox.example) exposes an async API: POST /speak,
# poll GET /generate/{id}/status, fetch audio at GET /audio/{id}.
# Defaults to the kokoro preset engine (24kHz output).
#

import asyncio
import io
import json
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
    """Settings for VoiceboxTTSService.

    Parameters:
        base_url: voicebox server URL, e.g. http://192.168.29.102:17600
    """

    base_url: str | None | NotGiven = field(default_factory=lambda: NOT_GIVEN)


class VoiceboxTTSService(TTSService):
    """Text-to-speech via a self-hosted voicebox server (kokoro engine by default)."""

    Settings = VoiceboxTTSSettings
    _settings: Settings

    def __init__(
        self,
        *,
        base_url: str,
        profile: str = "HF Female",
        engine: str = "kokoro",
        language: str = "en",
        sample_rate: int = 24000,
        settings: Settings | None = None,
        **kwargs,
    ):
        default_settings = self.Settings(
            model=engine,
            voice=profile,
            language=language,
            base_url=base_url,
        )
        if settings is not None:
            default_settings.apply_update(settings)

        super().__init__(
            pause_frame_processing=True,
            push_start_frame=True,
            push_stop_frames=True,
            sample_rate=sample_rate,
            settings=default_settings,
            **kwargs,
        )

        self._client = httpx.AsyncClient(timeout=60.0)

    def can_generate_metrics(self) -> bool:
        return True

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        base_url = assert_given(self._settings.base_url).rstrip("/")
        profile = assert_given(self._settings.voice)
        engine = assert_given(self._settings.model)
        language = str(self._settings.language or "en")
        try:
            resp = await self._client.post(
                f"{base_url}/speak",
                json={"text": text, "profile": profile, "engine": engine, "language": language},
            )
            resp.raise_for_status()
            generation_id = resp.json()["id"]

            while True:
                body = (
                    await self._client.get(f"{base_url}/generate/{generation_id}/status")
                ).text
                status = json.loads(
                    [l.split("data:", 1)[1].strip() for l in body.splitlines() if l.startswith("data:")][-1]
                )
                if status.get("status") == "completed":
                    break
                if status.get("status") == "failed":
                    raise RuntimeError(f"voicebox generation failed: {status.get('error')}")
                await asyncio.sleep(0.5)

            audio = (await self._client.get(f"{base_url}/audio/{generation_id}")).content
            with wave.open(io.BytesIO(audio)) as w:
                yield TTSAudioRawFrame(
                    w.readframes(w.getnframes()),
                    w.getframerate(),
                    w.getnchannels(),
                    context_id=context_id,
                )
        except Exception as e:
            yield ErrorFrame(error=f"voicebox TTS error: {e}")