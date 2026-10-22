import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from eklavya import app as core


@pytest.mark.parametrize("enabled", [False, True])
def test_monitor_flag_preserves_voice_and_legacy_defaults(enabled, monkeypatch, tmp_path):
    events = []
    (tmp_path / "okf" / "test-course").mkdir(parents=True)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GROQ_API_KEY", "test-not-a-secret")
    monkeypatch.delenv("COURSE_ID", raising=False)
    sentinel = object()
    monkeypatch.setattr(core, "active_behavior_monitor", sentinel)
    spawn = AsyncMock(side_effect=AssertionError("CV worker must never spawn"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    class Monitor:
        def __init__(self, **kwargs):
            events.append("construct")

        async def start(self):
            events.append("start")
            return True

        async def stop(self):
            events.append("stop")

    class Transport:
        def __init__(self):
            self.handlers = {}

        def input(self):
            return object()

        def output(self):
            return object()

        def event_handler(self, name):
            def bind(callback):
                self.handlers[name] = callback
                return callback
            return bind

    transport = Transport()

    class Runner:
        def __init__(self, **kwargs):
            pass

        async def add_workers(self, worker):
            pass

        async def cancel(self):
            events.append("cancel")

        async def run(self):
            await transport.handlers["on_client_connected"](transport, None)
            events.append("voice")
            await transport.handlers["on_client_disconnected"](transport, None)

    worker = SimpleNamespace(queue_frames=AsyncMock())
    context = SimpleNamespace(add_message=Mock())
    monkeypatch.setattr(core, "BehaviorMonitor", Monitor)
    monkeypatch.setattr(core, "GroqSTTService", Mock(Settings=Mock()))
    monkeypatch.setattr(core, "VoiceboxTTSService", Mock())
    monkeypatch.setattr(core, "GroqTutor", Mock())
    monkeypatch.setattr(core, "FileCatalog", Mock())
    monkeypatch.setattr(core, "SileroVADAnalyzer", Mock())
    monkeypatch.setattr(core, "GroundedTutorProcessor", Mock())
    monkeypatch.setattr(core, "Pipeline", Mock())
    monkeypatch.setattr(core, "PipelineWorker", Mock(return_value=worker))
    monkeypatch.setattr(core, "WorkerRunner", Runner)
    monkeypatch.setattr(core, "LLMContext", Mock(return_value=context))
    monkeypatch.setattr(core, "LLMContextAggregatorPair", Mock(return_value=(object(), object())))
    monkeypatch.setattr(core.httpx, "AsyncClient", Mock())
    args = SimpleNamespace(handle_sigint=False, pipeline_idle_timeout_secs=300)

    if enabled:
        asyncio.run(core.run_bot(transport, args))
        assert events == ["construct", "start", "voice", "stop", "cancel", "stop"]
        assert core.active_behavior_monitor is None
    else:
        asyncio.run(core.run_bot(transport, args, enable_behavior_monitor=False))
        assert events == ["voice", "cancel"]
        assert core.active_behavior_monitor is sentinel
    worker.queue_frames.assert_awaited_once()
    spawn.assert_not_awaited()
