import asyncio
import httpx
import pytest
from eklavya.public_sessions import PublicLimit, PublicRTVIProcessor, public_observer_params


def test_actual_outbound_attempts_are_counted_before_send(public_factory):
    async def scenario():
        manager, app, clock = public_factory()
        lease, owner, csrf = await manager.reserve(None, "a")
        sends = []
        client = lease.http_client("tutor", transport=httpx.MockTransport(
            lambda request: (sends.append(request.method) or httpx.Response(200, json={"ok": True}))))
        for index in range(300):
            await client.post("https://provider.invalid/fake", json={})
        with pytest.raises(PublicLimit):
            await client.get("https://provider.invalid/fake")
        assert sends == ["POST"] * 300
        assert lease.attempts == 300
        await lease.close()
        assert client.is_closed
    asyncio.run(scenario())


def test_rtvi_rejects_oversized_text_wrong_version_and_unused_actions(public_factory):
    async def scenario():
        manager, app, clock = public_factory()
        lease, owner, csrf = await manager.reserve(None, "a")
        handshake = {"label": "rtvi-ai", "type": "client-ready", "id": "1", "data": {"version": "2.1.0"}}
        await lease.check_rtvi(handshake)
        with pytest.raises(PublicLimit):
            await lease.check_rtvi({**handshake, "data": {"version": "99.0.0"}})
        await manager.shutdown()

        for kind, data in [("send-text", {"content": "x" * 4001}), ("append-to-audio-buffer", {})]:
            manager, app, clock = public_factory()
            lease, owner, csrf = await manager.reserve(None, "a")
            lease.offer_started = 0; lease.mark_ready()
            with pytest.raises(PublicLimit):
                await lease.check_rtvi({"label": "rtvi-ai", "type": kind, "id": "2", "data": data})
            await manager.shutdown()
    asyncio.run(scenario())


def test_accepted_pending_queue_includes_consumer_and_disables_diagnostics(public_factory):
    async def scenario():
        manager, app, clock = public_factory()
        lease, owner, csrf = await manager.reserve(None, "a")
        lease.offer_started = 0; lease.mark_ready()
        processor = PublicRTVIProcessor(lease)
        for index in range(17):
            await processor.handle_message({"label": "rtvi-ai", "type": "send-text", "id": str(index), "data": {"content": "question"}})
        assert processor.pending == 16
        assert processor.accepted.qsize() == 16
        assert lease.closing
        params = public_observer_params()
        assert params.metrics_enabled is False
        assert params.system_logs_enabled is False
        await manager.shutdown()
    asyncio.run(scenario())

def test_transport_frames_are_bounded_before_stock_enqueue(public_factory, monkeypatch):
    from unittest.mock import AsyncMock
    from pipecat.frames.frames import InputTransportMessageFrame
    from pipecat.processors.frameworks.rtvi.processor import RTVIProcessor

    async def scenario():
        manager, app, clock = public_factory()
        lease, owner, csrf = await manager.reserve(None, "a")
        lease.offer_started = 0; lease.mark_ready()
        processor = PublicRTVIProcessor(lease)
        stock_queue = AsyncMock()
        monkeypatch.setattr(RTVIProcessor, "queue_frame", stock_queue)
        callback = AsyncMock()
        for index in range(17):
            frame = InputTransportMessageFrame(message={"label": "rtvi-ai", "type": "send-text",
                "id": str(index), "data": {"content": "question"}})
            await processor.queue_frame(frame, callback=callback)
        stock_queue.assert_not_awaited()
        assert callback.await_count == 17
        assert processor.pending == 16
        await manager.shutdown()
    asyncio.run(scenario())


def test_rtvi_errors_and_observer_delivery_are_sanitized(public_factory, monkeypatch):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    import pipecat.processors.frameworks.rtvi.models as RTVI
    from pipecat.processors.frameworks.rtvi.processor import RTVIProcessor

    async def scenario():
        manager, app, clock = public_factory()
        lease, owner, csrf = await manager.reserve(None, "a")
        processor = PublicRTVIProcessor(lease)
        sender = AsyncMock()
        monkeypatch.setattr(RTVIProcessor, "push_transport_message", sender)
        await processor.push_transport_message(RTVI.Error(data=RTVI.ErrorData(error="SENSITIVE_PROVIDER_MARKER", fatal=True)))
        await processor.push_transport_message(RTVI.ErrorResponse(id="safe-id", data=RTVI.ErrorResponseData(error="SENSITIVE_PROVIDER_MARKER")))
        await processor.push_transport_message(SimpleNamespace(type="metrics"))
        await processor.push_transport_message(SimpleNamespace(type="system-log"))
        assert sender.await_count == 2
        for call in sender.await_args_list:
            assert "SENSITIVE_PROVIDER_MARKER" not in call.args[0].model_dump_json()
        observer = processor.create_rtvi_observer()
        await observer.send_rtvi_message(SimpleNamespace(type="bot-interrupted"))
        message = sender.await_args.args[0]
        assert message.type == "server-message"
        assert message.data == {"type": "learner-interrupted"}
        await manager.shutdown()
    asyncio.run(scenario())


def test_retry_and_voicebox_poll_audio_requests_share_attempt_counter(public_factory, monkeypatch):
    import io
    import wave
    from unittest.mock import AsyncMock
    from eklavya.drona.services.groq_client import request_with_retry
    from eklavya.voicebox_tts import VoiceboxTTSService
    from pipecat.frames.frames import TTSAudioRawFrame

    async def scenario():
        manager, app, clock = public_factory()
        lease, owner, csrf = await manager.reserve(None, "a")
        requests = []
        tutor_calls = 0
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setnchannels(2); audio.setsampwidth(2); audio.setframerate(24000)
            audio.writeframes(b"\0\0\0\0" * 8)

        def respond(request):
            nonlocal tutor_calls
            requests.append(request.url.path)
            if request.url.path == "/chat/completions":
                tutor_calls += 1
                return httpx.Response(500 if tutor_calls == 1 else 200, json={"ok": True})
            if request.url.path == "/speak":
                return httpx.Response(200, json={"id": "fake-generation"})
            if request.url.path.endswith("/status"):
                return httpx.Response(200, text='data: {"status":"completed"}\n')
            return httpx.Response(200, content=buffer.getvalue())

        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        tutor = lease.http_client("tutor", transport=httpx.MockTransport(respond))
        await request_with_retry(lambda: tutor.post("https://provider.invalid/chat/completions"), label="fake", retries=1)
        tts_client = lease.http_client("tts", transport=httpx.MockTransport(respond))
        service = VoiceboxTTSService(base_url="https://provider.invalid", http_client=tts_client)
        frames = [frame async for frame in service.run_tts("fake text", "fake-context")]
        assert len(frames) == 1 and isinstance(frames[0], TTSAudioRawFrame)
        assert frames[0].num_channels == 2
        assert lease.attempts == len(requests) == 5
        assert requests.count("/chat/completions") == 2
        await lease.close()
        assert tutor.is_closed and tts_client.is_closed
    asyncio.run(scenario())


def test_shutdown_awaits_worker_peer_and_clients_before_releasing_capacity(public_factory):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace

    async def scenario():
        manager, app, clock = public_factory()
        lease, owner, csrf = await manager.reserve(None, "a")
        await manager.offer(lease, {"sdp": "fake", "type": "offer"}, "POST")
        entered, release = asyncio.Event(), asyncio.Event()

        async def cancel(**kwargs):
            entered.set(); await release.wait()

        worker = SimpleNamespace(cancel=cancel, wait=AsyncMock())
        lease.register_worker(worker, lease.peer)
        client = lease.http_client("tutor", transport=httpx.MockTransport(lambda request: httpx.Response(200)))
        closing = asyncio.create_task(lease.close())
        await entered.wait()
        with pytest.raises(PublicLimit):
            await manager.reserve(None, "other-owner")
        assert lease.session_id in manager.leases
        release.set(); await closing
        worker.wait.assert_awaited_once()
        assert lease.peer.disconnected and client.is_closed
        assert not manager.leases
    asyncio.run(scenario())

def test_policy_is_attached_to_actual_pipeline_and_restart_callbacks(public_factory, monkeypatch, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from eklavya import app as core
    from eklavya.public_sessions import PublicGroundedTutorProcessor

    async def scenario():
        manager, boundary, clock = public_factory()
        policy, owner, csrf = await manager.reserve(None, "source")
        policy.offer_started = 0
        connection = object()
        policy.peer = connection
        (tmp_path / "okf" / "fake-course").mkdir(parents=True)
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("GROQ_API_KEY", "fake-test-value")
        monkeypatch.delenv("COURSE_ID", raising=False)
        handlers = {}

        class Transport:
            def input(self):
                return object()

            def output(self):
                return object()

            def event_handler(self, name):
                def bind(callback):
                    handlers[name] = callback
                    return callback
                return bind

        transport = Transport()
        canceled = []

        class Runner:
            def __init__(self, **kwargs):
                pass

            async def add_workers(self, worker):
                pass

            async def cancel(self):
                canceled.append("cancel")

            async def run(self):
                await handlers["on_client_connected"](transport, None)
                policy.mark_ready()
                await handlers["on_client_connected"](transport, None)
                policy.restarting = True
                await handlers["on_client_disconnected"](transport, None)
                assert canceled == []
                policy.restarting = False
                await handlers["on_client_disconnected"](transport, None)

        worker = SimpleNamespace(queue_frames=AsyncMock(), cancel=AsyncMock(), wait=AsyncMock())
        worker_factory = Mock(return_value=worker)
        pipeline_factory = Mock()
        stt_factory = Mock(Settings=Mock())
        tts_factory = Mock()
        tutor_factory = Mock()
        monkeypatch.setattr(core, "GroqSTTService", stt_factory)
        monkeypatch.setattr(core, "VoiceboxTTSService", tts_factory)
        monkeypatch.setattr(core, "GroqTutor", tutor_factory)
        monkeypatch.setattr(core, "FileCatalog", Mock())
        monkeypatch.setattr(core, "SileroVADAnalyzer", Mock())
        monkeypatch.setattr(core, "LLMContext", Mock(return_value=SimpleNamespace(add_message=Mock())))
        monkeypatch.setattr(core, "LLMContextAggregatorPair", Mock(return_value=(object(), object())))
        monkeypatch.setattr(core, "Pipeline", pipeline_factory)
        monkeypatch.setattr(core, "PipelineWorker", worker_factory)
        monkeypatch.setattr(core, "WorkerRunner", Runner)
        monitor = Mock(side_effect=AssertionError("public monitor construction"))
        monkeypatch.setattr(core, "BehaviorMonitor", monitor)
        args = SimpleNamespace(handle_sigint=False, pipeline_idle_timeout_secs=300, webrtc_connection=connection)
        await core.run_bot(transport, args, enable_behavior_monitor=False, session_policy=policy)
        options = worker_factory.call_args.kwargs
        assert isinstance(options["rtvi_processor"], PublicRTVIProcessor)
        assert options["rtvi_observer_params"].metrics_enabled is False
        assert options["idle_timeout_secs"] is None
        assert policy.worker is worker
        assert isinstance(pipeline_factory.call_args.args[0][3], PublicGroundedTutorProcessor)
        assert stt_factory.call_args.kwargs["http_client"] in policy.clients
        assert tts_factory.call_args.kwargs["http_client"] in policy.clients
        assert tutor_factory.call_args.args[0] in policy.clients
        assert len(policy.clients) == 3
        worker.queue_frames.assert_awaited_once()  # reconnect did not replay introduction
        assert canceled == ["cancel"]
        monitor.assert_not_called()
        # This test uses a sentinel, not an actual peer, so omit peer teardown.
        policy.peer = None
        await policy.close()
        assert all(client.is_closed for client in policy.clients)
    asyncio.run(scenario())

def test_failed_worker_teardown_never_releases_admission(public_factory):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    async def scenario():
        manager, boundary, clock = public_factory()
        lease, owner, csrf = await manager.reserve(None, "a")
        lease.worker = SimpleNamespace(cancel=AsyncMock(), wait=AsyncMock(side_effect=RuntimeError("fake failure")))
        await lease.close()
        assert manager.enabled is False
        assert lease.session_id in manager.leases
        with pytest.raises(PublicLimit):
            await manager.reserve(None, "b")
    asyncio.run(scenario())


def test_concurrent_outbound_attempts_use_the_same_atomic_budget(public_factory):
    async def scenario():
        manager, boundary, clock = public_factory()
        lease, owner, csrf = await manager.reserve(None, "a")
        lease.attempts = 299
        sends = []
        client = lease.http_client("stt", transport=httpx.MockTransport(
            lambda request: (sends.append(request) or httpx.Response(200))))
        results = await asyncio.gather(
            client.post("https://provider.invalid/a"), client.post("https://provider.invalid/b"),
            return_exceptions=True,
        )
        assert len(sends) == 1 and lease.attempts == 300
        assert sum(isinstance(result, PublicLimit) for result in results) == 1
        await lease.close()
    asyncio.run(scenario())

def test_thirty_first_turn_is_denied_before_actual_tutor_delegate(public_factory, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from pipecat.frames.frames import LLMContextFrame
    from pipecat.processors.frame_processor import FrameDirection
    from eklavya.grounded_tutor import GroundedTutorProcessor
    from eklavya.public_sessions import PublicGroundedTutorProcessor

    async def scenario():
        manager, boundary, clock = public_factory()
        lease, owner, csrf = await manager.reserve(None, "a")
        lease.offer_started = 0; lease.mark_ready()
        delegate = AsyncMock()
        monkeypatch.setattr(GroundedTutorProcessor, "process_frame", delegate)
        processor = PublicGroundedTutorProcessor(policy=lease, catalog=Mock(), tutor=Mock(), course_id="fake")
        frame = LLMContextFrame(context=SimpleNamespace(get_messages=lambda: [{"role": "user", "content": "question"}]))
        for index in range(30):
            clock.value = index * 7
            await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
        with pytest.raises(PublicLimit):
            await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
        assert delegate.await_count == 30
        await manager.shutdown()
    asyncio.run(scenario())


def test_rtvi_serialized_bytes_burst_and_refill(public_factory):
    async def scenario():
        manager, boundary, clock = public_factory()
        lease, owner, csrf = await manager.reserve(None, "a")
        with pytest.raises(PublicLimit):
            await lease.check_rtvi({"label": "rtvi-ai", "type": "client-ready", "id": "x",
                "data": {"version": "2.1.0", "about": {"large": "x" * 16384}}})
        await manager.shutdown()
        manager, boundary, clock = public_factory()
        lease, owner, csrf = await manager.reserve(None, "b")
        lease.offer_started = clock.value; lease.mark_ready()
        message = {"label": "rtvi-ai", "type": "send-text", "id": "x", "data": {"content": "question"}}
        for index in range(20):
            await lease.check_rtvi(message)
        clock.value += .1
        await lease.check_rtvi(message)  # one token refilled at 10 messages/sec
        with pytest.raises(PublicLimit):
            await lease.check_rtvi(message)
        await manager.shutdown()
    asyncio.run(scenario())

def test_safe_logging_drops_dependency_secrets():
    import subprocess
    import sys
    code = """
import logging
from loguru import logger
from eklavya.public_sessions import install_safe_logging
install_safe_logging()
logger.error('SENSITIVE_PROVIDER_MARKER')
logging.getLogger('uvicorn.error').error('SENSITIVE_PROVIDER_MARKER')
logging.getLogger('httpx').error('SENSITIVE_PROVIDER_MARKER')
"""
    result = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True, check=True)
    assert "SENSITIVE_PROVIDER_MARKER" not in result.stdout + result.stderr
