#
# Simple Pipecat voice agent (hello world)
#
# Run with:
#   uv run bot.py
#
# Then open http://localhost:7860 in your browser and click Connect.
#
# Defaults (work with only GROQ_API_KEY set + the LXC voicebox box):
#   STT  -> Groq Whisper (whisper-large-v3-turbo)
#   LLM  -> Groq (openai/gpt-oss-120b)
#   TTS  -> self-hosted voicebox on the LXC box (kokoro engine)
#
# To swap in other providers (Deepgram, Cartesia, Anthropic, ...), add the
# API key to .env, install the matching extra (see .env.example for the
# `uv add "pipecat-ai[xxx]"` command), and replace the service constructors
# below. Examples are in the comments.

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.evals.transport import EvalTransportParams
from pipecat.frames.frames import InterruptionFrame, LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.types import WebSocketRunnerArguments
from pipecat.runner.utils import create_transport, parse_telephony_websocket
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.groq.stt import GroqSTTService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.workers.runner import WorkerRunner
from voicebox_tts import VoiceboxTTSService

from grounded_tutor import (
    BehaviorInterventionFrame,
    BehaviorRecoveryFrame,
    GroundedTutorProcessor,
    latest_user_text,
)
from behavior_monitor import BehaviorIntervention, BehaviorMonitor
from drona.knowledge.catalog import FileCatalog
from drona.services.groq_tutor import GroqTutor

load_dotenv(override=True)

active_behavior_monitor: BehaviorMonitor | None = None

# Transport parameter factories. The runner picks one based on how the bot is
# started (defaults to "webrtc"). Swap in "daily", "twilio", etc. as needed.
transport_params = {
    "eval": lambda: EvalTransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    ),
    "twilio": lambda: FastAPIWebsocketParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    ),
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    ),
}


def behavior_intervention_frames(event: BehaviorIntervention, context) -> list:
    """Build the warning + concise replay sequence for one CV event."""
    frames = [
        InterruptionFrame(),
        BehaviorInterventionFrame(event.reasons, event.scores),
    ]
    # Reuse the real latest user message. Never inject a synthetic user
    # prompt, and do not run an empty conversation after the warning.
    if latest_user_text(context):
        frames.append(LLMRunFrame())
    return frames

# Daily is optional: register its transport params only if the SDK is installed.
if importlib.util.find_spec("daily"):
    from pipecat.transports.daily.transport import DailyParams

    transport_params["daily"] = lambda: DailyParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    )
else:
    logger.warning("Daily transport not available. Install with: uv add \"pipecat-ai[daily]\"")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing {name} in .env. Copy .env.example to .env and add the key."
        )
    return value


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    logger.info("Starting bot")

    # ------------------------------------------------------------------
    # AI services — pick the STT/LLM/TTS providers you want.
    #   STT  -> Groq Whisper (generous free tier)
    #   LLM  -> Groq (generous free tier)
    #   TTS  -> self-hosted voicebox server (kokoro engine) on the LXC box
    # ------------------------------------------------------------------

    # Speech-to-Text (STT)
    stt = GroqSTTService(
        api_key=require_env("GROQ_API_KEY"),
        settings=GroqSTTService.Settings(model="whisper-large-v3-turbo"),
    )

    # Grounded tutor — answers questions ONLY from the ingested course material.
    # Reuses the Drona OKF corpus the CLI ingests into DATA_DIR/okf.
    data_dir = Path(os.getenv("DATA_DIR", "tutor/data"))
    catalog = FileCatalog(data_dir / "okf", max_context_chars=14_000)
    courses = [p.name for p in (data_dir / "okf").glob("*") if p.is_dir()]
    if not courses:
        raise RuntimeError(
            "No ingested courses found. Run `tutor ingest <file-or-dir>` first "
            f"(expected OKF bundles under {data_dir / 'okf'})."
        )
    course_id = os.getenv("COURSE_ID") or courses[0]
    if course_id not in courses:
        raise RuntimeError(f"COURSE_ID {course_id!r} not found. Available: {', '.join(courses)}")

    tutor = GroqTutor(
        httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=5.0)),
        require_env("GROQ_API_KEY"),
        os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        260,
        reasoning_effort="low",
    )
    logger.info(f"Grounding tutor on course: {course_id} ({len(courses)} course(s) loaded)")

    # Text-to-Speech (TTS) — self-hosted voicebox (kokoro), reachable at
    # http://192.168.29.102:17600 from this machine.
    tts = VoiceboxTTSService(
        base_url=os.getenv("VOICEBOX_URL", "http://192.168.29.102:17600"),
        profile=os.getenv("VOICEBOX_PROFILE", "HF Female"),
        engine=os.getenv("VOICEBOX_ENGINE", "kokoro"),
    )

    # Conversation context (multi-turn memory)
    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    # Grounded tutor replaces the LLM service in the pipeline.
    grounded = GroundedTutorProcessor(catalog=catalog, tutor=tutor, course_id=course_id)

    # Pipeline: audio in -> STT -> user context -> grounded tutor -> TTS -> audio out
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            grounded,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
        processor_unusable_policy=ProcessorUnusablePolicy.END,
    )

    intervention_lock = asyncio.Lock()

    async def on_behavior_intervention(event: BehaviorIntervention) -> None:
        # Keep one intervention in flight so a noisy camera cannot queue a
        # second interruption behind an already-speaking intervention.
        async with intervention_lock:
            await worker.queue_frames(behavior_intervention_frames(event, context))

    async def on_behavior_recovery() -> None:
        await worker.queue_frames([BehaviorRecoveryFrame()])

    behavior_monitor = BehaviorMonitor(
        on_intervention=on_behavior_intervention,
        on_recovery=on_behavior_recovery,
    )

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)

    await runner.add_workers(worker)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        global active_behavior_monitor
        logger.info("Client connected")
        active_behavior_monitor = behavior_monitor
        if await behavior_monitor.start():
            logger.info("CV monitor started; waiting for browser camera frames")
        else:
            logger.warning("CV camera monitor could not be started; voice chat continues")
        # Kick off the conversation.
        context.add_message(
            {"role": "system", "content": "Please introduce yourself to the user."}
        )
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        global active_behavior_monitor
        logger.info("Client disconnected")
        if active_behavior_monitor is behavior_monitor:
            active_behavior_monitor = None
        await behavior_monitor.stop()
        await runner.cancel()

    try:
        await runner.run()
    finally:
        await behavior_monitor.stop()


async def bot(runner_args: RunnerArguments):
    """Main bot entry point (compatible with the Pipecat dev runner and
    Pipecat Cloud)."""
    # Pipecat's default Twilio serializer enables REST-based auto hang-up,
    # which requires an Account SID and Auth Token even though Media Streams
    # themselves do not. For local/demo calls, let Twilio close the stream when
    # the caller hangs up so no Twilio secret is needed on the bot machine.
    is_twilio_without_credentials = (
        isinstance(runner_args, WebSocketRunnerArguments)
        and runner_args.cli_args is not None
        and runner_args.cli_args.transport == "twilio"
        and not (
            os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN")
        )
    )

    if is_twilio_without_credentials:
        transport_type, call_data = await parse_telephony_websocket(
            runner_args.websocket
        )
        if transport_type != "twilio":
            raise RuntimeError(f"Expected a Twilio stream, got {transport_type!r}")

        runner_args.transport_type = transport_type
        runner_args.call_data = call_data

        params = transport_params["twilio"]()
        params.add_wav_header = False
        params.serializer = TwilioFrameSerializer(
            stream_sid=call_data.stream_id,
            call_sid=call_data.call_id,
            params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
        )
        transport = FastAPIWebsocketTransport(
            websocket=runner_args.websocket,
            params=params,
        )
    else:
        transport = await create_transport(runner_args, transport_params)

    await run_bot(transport, runner_args)


# Serve our own branded copy of the prebuilt client UI. Registered before
# main(), so it shadows the stock mount from pipecat-ai-prebuilt.
from fastapi.staticfiles import StaticFiles
from pipecat.runner.run import app

app.mount("/client", StaticFiles(directory="ui", html=True), name="client")


@app.websocket("/behavior/ws")
async def behavior_websocket(websocket: WebSocket):
    """Receive browser camera JPEGs for the active local bot session."""
    monitor = active_behavior_monitor
    if monitor is None:
        await websocket.close(code=1013, reason="No active bot session")
        return
    await websocket.accept()
    logger.info("Behavior camera stream connected")
    last_sent_timestamp = None
    try:
        await monitor.set_streaming(True)
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            frame = message.get("bytes")
            if frame:
                await monitor.submit_frame(frame)
                sample = getattr(monitor, "latest_sample", None)
                if sample is not None and sample.timestamp != last_sent_timestamp:
                    await websocket.send_json(
                        {
                            "type": "behavior",
                            "timestamp": sample.timestamp,
                            "engagement": sample.scores["engagement"],
                        }
                    )
                    last_sent_timestamp = sample.timestamp
    except WebSocketDisconnect:
        pass
    finally:
        await monitor.set_streaming(False)
        logger.info("Behavior camera stream disconnected")


def _load_twilio_ice_servers() -> None:
    """Fetch Twilio NTS STUN/TURN credentials for WebRTC NAT traversal.

    Without TURN, the bot only offers container-internal host candidates and
    browsers behind NAT can never reach it. Credentials last 24h
    (// ponytail: refresh on process start; restart the app daily or wire a
    refresh task if sessions start failing after 24h uptime).
    """
    if os.getenv("PIPECAT_ICE_SERVERS"):
        return  # explicit config wins
    sid, token = os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN")
    if not (sid and token):
        return

    import base64
    import json
    import urllib.request

    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Tokens.json",
        method="POST",
        headers={
            "Authorization": "Basic "
            + base64.b64encode(f"{sid}:{token}".encode()).decode()
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
    except Exception as e:
        logger.warning(f"Could not fetch Twilio ICE servers: {e}")
        return

    grouped: dict[tuple[str, str], list[str]] = {}
    for s in data.get("ice_servers", []):
        if "turn" not in s.get("urls", ""):
            continue
        grouped.setdefault((s["username"], s["credential"]), []).append(s["urls"])

    servers = [
        {"urls": urls, "username": u, "credential": c}
        for (u, c), urls in grouped.items()
    ]
    if servers:
        os.environ["PIPECAT_ICE_SERVERS"] = json.dumps(servers)
        logger.info(f"Using Twilio TURN relay ({len(servers)} server group(s))")


if __name__ == "__main__":
    _load_twilio_ice_servers()
    from pipecat.runner.run import main

    main()
