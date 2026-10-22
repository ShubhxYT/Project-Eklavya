"""Single-process anonymous leases. No identities, persistence or provider replacement."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from loguru import logger
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse


class PublicLimit(RuntimeError):
    def __init__(self, code="limit", status=429):
        super().__init__(code)
        self.code = code
        self.status = status


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


class Bucket:
    def __init__(self, rate, burst, now):
        self.rate, self.burst, self.tokens, self.last = rate, burst, float(burst), now

    def take(self, now):
        self.tokens = min(self.burst, self.tokens + max(0, now - self.last) * self.rate)
        self.last = now
        if self.tokens < 1:
            raise PublicLimit()
        self.tokens -= 1


@dataclass(frozen=True)
class PublicConfig:
    origin: str
    assets: Path
    ice_servers: list = field(default_factory=list)
    capacity: int = 1
    enabled: bool = True

    def __post_init__(self):
        parsed = urlsplit(self.origin)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or
                parsed.password or parsed.path or parsed.query or parsed.fragment or
                (parsed.scheme != "https" and not local)):
            raise ValueError("public origin must be an exact HTTPS origin or loopback HTTP origin")
        if self.capacity < 1:
            raise ValueError("capacity must be positive")

    @property
    def cookie(self):
        return "__Host-eklavya" if self.origin.startswith("https:") else "eklavya-local"


class PublicSessionPolicy:
    def __init__(self, manager, session_id, owner, csrf):
        self.manager = manager
        self.session_id, self.owner, self.csrf = session_id, owner, csrf
        self.created = manager.clock()
        self.offer_started = None
        self.ready_at = None
        self.activity = None
        self.peer = None
        self.peer_id = None
        self.worker = None
        self.bot_task = None
        self.offer_task = None
        self.close_task = None
        self.closing = False
        self.closed = False
        self.attempts = 0
        self.turns = deque()
        self.turn_count = 0
        self.renegotiations = 0
        self.restarting = False
        self.messages = Bucket(10, 20, self.created)
        self.patches = deque()
        self.turn_lock = asyncio.Lock()
        self.clients = []
        self.handshake_seen = False

    def ensure_live(self):
        now = self.manager.clock()
        expired = now - self.created >= 900
        expired |= self.offer_started is None and now - self.created >= 30
        expired |= self.offer_started is not None and self.ready_at is None and now - self.offer_started >= 60
        expired |= self.activity is not None and now - self.activity >= 120
        if self.closing or self.closed or expired or not self.manager.enabled:
            self.request_close()
            raise PublicLimit("expired", 410)

    def mark_ready(self):
        self.ensure_live()
        if self.ready_at is None:
            self.ready_at = self.manager.clock()
            self.touch_user_activity()

    def touch_user_activity(self):
        self.activity = self.manager.clock()

    def register_worker(self, worker, connection):
        self.ensure_live()
        if connection is not self.peer:
            raise PublicLimit("not_found", 404)
        self.worker = worker

    async def check_provider_request(self, kind):
        if kind not in {"stt", "tutor", "tts"}:
            raise PublicLimit("invalid", 400)
        async with self.manager.lock:
            self.ensure_live()
            now = self.manager.clock()
            history = self.manager.provider_history
            while history and history[0] <= now - 86400:
                history.popleft()
            if self.attempts >= 300 or len(history) >= 6000:
                if len(history) >= 6000:
                    self.manager.enabled = False
                self.request_close()
                raise PublicLimit()
            self.attempts += 1
            history.append(now)

    def http_client(self, kind, *, transport=None):
        self.ensure_live()

        async def check(request):
            await self.check_provider_request(kind)

        client = httpx.AsyncClient(
            timeout=httpx.Timeout(45.0, connect=5.0),
            event_hooks={"request": [check]},
            follow_redirects=False,
            transport=transport,
        )
        self.clients.append(client)
        return client

    async def check_rtvi(self, message):
        self.ensure_live()
        try:
            raw = message.model_dump() if hasattr(message, "model_dump") else message
            encoded = json.dumps(raw, separators=(",", ":"), allow_nan=False).encode()
            if not isinstance(raw, dict) or len(encoded) > 16384:
                raise ValueError()
            if set(raw) - {"label", "type", "id", "data"} or raw.get("label") != "rtvi-ai":
                raise ValueError()
            if not isinstance(raw.get("id"), str) or len(raw["id"]) > 128:
                raise ValueError()
            kind = raw.get("type")
            data = raw.get("data") or {}
            if not isinstance(data, dict):
                raise ValueError()
            if kind == "client-ready":
                if data.get("version") != "2.1.0":
                    raise ValueError()
            elif kind == "send-text":
                if self.ready_at is None or set(data) - {"content", "options"}:
                    raise ValueError()
                text = data.get("content")
                if not isinstance(text, str) or not text.strip() or len(text) > 4000:
                    raise ValueError()
                options = data.get("options") or {}
                if not isinstance(options, dict) or set(options) - {"run_immediately", "audio_response"}:
                    raise ValueError()
                if options.get("run_immediately", True) is not True or options.get("audio_response", True) is not True:
                    raise ValueError()
            elif kind != "disconnect-bot" or data:
                raise ValueError()
            self.messages.take(self.manager.clock())
            if kind == "client-ready":
                self.handshake_seen = True
            if kind == "send-text":
                self.touch_user_activity()
        except PublicLimit:
            self.request_close()
            raise
        except (TypeError, ValueError, OverflowError):
            self.request_close()
            raise PublicLimit("invalid", 400) from None

    def accept_turn(self):
        self.ensure_live()
        now = self.manager.clock()
        while self.turns and self.turns[0] <= now - 60:
            self.turns.popleft()
        if self.turn_count >= 30 or len(self.turns) >= 10:
            self.request_close()
            raise PublicLimit()
        self.turns.append(now)
        self.turn_count += 1
        self.touch_user_activity()

    def request_close(self):
        if self.close_task is None:
            self.closing = True
            self.close_task = asyncio.create_task(self._teardown())
        return self.close_task

    async def close(self):
        task = self.request_close()
        if asyncio.current_task() not in {self.bot_task, self.offer_task, task}:
            await asyncio.shield(task)

    async def _teardown(self):
        success = True

        async def attempt(operation):
            nonlocal success
            try:
                async with asyncio.timeout(10):
                    await operation()
            except (Exception, asyncio.CancelledError):
                success = False

        async def cancel_task(task):
            if task and task is not asyncio.current_task() and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        # Retain admission capacity throughout initialization and actual teardown.
        if self.offer_task:
            await attempt(lambda: cancel_task(self.offer_task))
        if self.worker:
            await attempt(lambda: self.worker.cancel(reason="public_session_closed"))
        if self.bot_task:
            await attempt(lambda: cancel_task(self.bot_task))
        if self.worker:
            await attempt(self.worker.wait)
        if self.peer:
            await attempt(self.peer.disconnect)
        for client in self.clients:
            await attempt(client.aclose)
        if success:
            self.closed = True
            self.peer_id = None
            async with self.manager.lock:
                self.manager.leases.pop(self.session_id, None)
        else:
            # Failed cleanup is not permission to admit another peer.
            self.manager.enabled = False


class PublicSessions:
    def __init__(self, config, *, clock=time.monotonic, connection_factory=None, bot=None, cli_args=None):
        self.config, self.clock = config, clock
        self.lock = asyncio.Lock()
        self.leases = {}
        self.owner_starts = {}
        self.ip_starts = {}
        self.starts = deque()
        self.provider_history = deque()
        self.enabled = config.enabled
        self.connection_factory = connection_factory
        self.bot = bot
        self.cli_args = cli_args
        self.watchdog = None

    def _entry(self, mapping, key, now):
        for old_key in list(mapping):
            history = mapping[old_key]
            while history and history[0] <= now - 60:
                history.popleft()
            if not history:
                del mapping[old_key]
        if key not in mapping and len(mapping) >= 4096:
            raise PublicLimit("busy")
        return mapping.setdefault(key, deque())

    async def reserve(self, owner_token, source):
        async with self.lock:
            now = self.clock()
            while self.provider_history and self.provider_history[0] <= now - 86400:
                self.provider_history.popleft()
            if len(self.provider_history) >= 6000:
                self.enabled = False
            token = owner_token if re.fullmatch(r"[A-Za-z0-9_-]{43}", owner_token or "") else secrets.token_urlsafe(32)
            owner = digest(token)
            source = digest(source)
            owner_history = self._entry(self.owner_starts, owner, now)
            ip_history = self._entry(self.ip_starts, source, now)
            while self.starts and self.starts[0] <= now - 86400:
                self.starts.popleft()
            if (len(owner_history) >= 3 or len(ip_history) >= 3 or len(self.starts) >= 60 or
                    sum(value > now - 60 for value in self.starts) >= 6):
                raise PublicLimit()
            # Count every allowed start attempt, including busy responses.
            owner_history.append(now); ip_history.append(now)
            self.starts.append(now)
            if not self.enabled or len(self.leases) >= self.config.capacity:
                raise PublicLimit("busy")
            session_id = secrets.token_hex(16)
            csrf = secrets.token_urlsafe(32)
            lease = PublicSessionPolicy(self, session_id, owner, digest(csrf))
            self.leases[session_id] = lease
            return lease, token, csrf

    def owned(self, session_id, owner_token, csrf, *, allow_ended=False):
        lease = self.leases.get(session_id)
        if (lease is None or not isinstance(owner_token, str) or not isinstance(csrf, str) or
                not equal(lease.owner, digest(owner_token)) or not equal(lease.csrf, digest(csrf))):
            raise PublicLimit("not_found", 404)
        if allow_ended and (lease.closing or lease.closed):
            return lease
        lease.ensure_live()
        return lease

    async def reap(self):
        while True:
            for lease in tuple(self.leases.values()):
                try:
                    lease.ensure_live()
                except PublicLimit:
                    lease.request_close()
            await asyncio.sleep(.25)

    async def shutdown(self):
        self.enabled = False
        if self.watchdog:
            self.watchdog.cancel()
            await asyncio.gather(self.watchdog, return_exceptions=True)
        await asyncio.gather(*(lease.close() for lease in tuple(self.leases.values())))

    async def offer(self, lease, body, method):
        lease.ensure_live()
        if lease.offer_task is not None:
            raise PublicLimit("busy")
        allowed = {"pc_id", "candidates"} if method == "PATCH" else {"sdp", "type", "pc_id", "restart_pc"}
        if set(body) - allowed:
            raise PublicLimit("invalid", 400)
        pc_id = body.get("pc_id")
        if lease.peer is not None and pc_id != lease.peer_id:
            raise PublicLimit("not_found", 404)
        if lease.peer is None and (pc_id is not None or method == "PATCH"):
            raise PublicLimit("not_found", 404)
        lease.offer_task = asyncio.current_task()
        try:
            if method == "PATCH":
                now = self.clock()
                while lease.patches and lease.patches[0] <= now - 1:
                    lease.patches.popleft()
                if len(lease.patches) >= 10:
                    raise PublicLimit()
                lease.patches.append(now)
                candidates = body.get("candidates")
                if not isinstance(candidates, list) or len(candidates) > 32:
                    raise PublicLimit("invalid", 400)
                from aiortc.sdp import candidate_from_sdp

                parsed = []
                for item in candidates:
                    if (not isinstance(item, dict) or set(item) != {"candidate", "sdp_mid", "sdp_mline_index"} or
                            not isinstance(item["candidate"], str) or len(item["candidate"]) > 8192 or
                            not isinstance(item["sdp_mid"], str) or len(item["sdp_mid"]) > 64 or
                            type(item["sdp_mline_index"]) is not int or not 0 <= item["sdp_mline_index"] <= 32):
                        raise PublicLimit("invalid", 400)
                    candidate = candidate_from_sdp(item["candidate"]) if item["candidate"] else None
                    if candidate:
                        candidate.sdpMid = item["sdp_mid"]
                        candidate.sdpMLineIndex = item["sdp_mline_index"]
                    parsed.append(candidate)
                for candidate in parsed:
                    await lease.peer.add_ice_candidate(candidate)
                return {"status": "success"}
            if (body.get("type") != "offer" or not isinstance(body.get("sdp"), str) or
                    not body["sdp"] or type(body.get("restart_pc", False)) is not bool):
                raise PublicLimit("invalid", 400)
            if lease.peer is None:
                if body.get("restart_pc"):
                    raise PublicLimit("invalid", 400)
                from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection

                factory = self.connection_factory or SmallWebRTCConnection
                lease.offer_started = self.clock()
                # Retain the peer BEFORE any initialization await.
                lease.peer = factory(ice_servers=self.config.ice_servers)

                @lease.peer.event_handler("closed")
                async def closed(connection):
                    lease.request_close()

                @lease.peer.event_handler("failed")
                async def failed(connection):
                    lease.request_close()

                await lease.peer.initialize(sdp=body["sdp"], type="offer")
            else:
                if lease.renegotiations >= 16:
                    raise PublicLimit()
                lease.renegotiations += 1
                lease.restarting = body.get("restart_pc", False)
                try:
                    await lease.peer.renegotiate(sdp=body["sdp"], type="offer", restart_pc=lease.restarting)
                finally:
                    lease.restarting = False
            lease.ensure_live()
            answer = lease.peer.get_answer()
            if (not isinstance(answer, dict) or set(answer) != {"sdp", "type", "pc_id"} or
                    answer["type"] != "answer" or not all(isinstance(answer[key], str) for key in answer)):
                raise PublicLimit("unavailable", 503)
            lease.peer_id = answer["pc_id"]
            if lease.bot_task is None:
                from pipecat.runner.types import SmallWebRTCRunnerArguments

                args = SmallWebRTCRunnerArguments(webrtc_connection=lease.peer, session_id=lease.session_id, body=None)
                args.cli_args = self.cli_args
                lease.bot_task = asyncio.create_task(self._run_bot(lease, args))
            return answer
        except (Exception, asyncio.CancelledError):
            lease.request_close()
            raise
        finally:
            lease.offer_task = None

    async def _run_bot(self, lease, args):
        try:
            lease.ensure_live()
            await self.bot(args)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # Raw exceptions never enter public logging or responses.
        finally:
            lease.request_close()


SECURITY_HEADERS = {
    # Approved public-launch exception: the pinned official SmallWebRTC
    # transport uses Daily's media manager, which fetches and evaluates its
    # call-machine bundle. `blob:` is also required by the GLTF loader for
    # embedded textures. Sentry telemetry remains blocked by connect-src.
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'wasm-unsafe-eval' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; worker-src 'self' blob:; connect-src 'self' blob: https://c.daily.co; media-src 'self' blob:; img-src 'self' data: blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
    "Permissions-Policy": "camera=(), display-capture=(), microphone=(self), speaker-selection=(self)",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


class PublicBoundary:
    """Outer ASGI boundary; never forwards public HTTP/WS to runner routes."""
    def __init__(self, app, sessions):
        self.app, self.sessions = app, sessions
        root = sessions.config.assets.resolve()
        if not (root / "index.html").is_file():
            raise ValueError("build the learner before public launch")
        self.assets = {}
        extensions = {".html", ".js", ".css", ".svg", ".png", ".webp", ".ico", ".glb", ".wasm"}
        for path in root.rglob("*"):
            relative = path.relative_to(root)
            if (path.is_file() and not path.is_symlink() and root in path.resolve().parents and
                    path.suffix in extensions and not any(part.startswith(".") for part in relative.parts) and
                    all(not (root.joinpath(*relative.parts[:index])).is_symlink() for index in range(1, len(relative.parts) + 1))):
                self.assets["/learn/" + relative.as_posix()] = path
        self.index = root / "index.html"

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    self.sessions.watchdog = asyncio.create_task(self.sessions.reap())
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await self.sessions.shutdown()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            return
        request = Request(scope, receive)
        try:
            response = await self.handle(request)
        except PublicLimit as error:
            response = JSONResponse({"error": error.code}, status_code=error.status)
            if error.status == 429:
                response.headers["Retry-After"] = "60"
        except asyncio.CancelledError:
            raise
        except Exception:
            response = JSONResponse({"error": "unavailable"}, status_code=503)
        response.headers.update(SECURITY_HEADERS)
        await response(scope, receive, send)

    async def handle(self, request):
        config = self.sessions.config
        scope = request.scope
        path = scope["path"]
        raw = scope.get("raw_path", path.encode())
        expected_host = urlsplit(config.origin).netloc
        headers = request.headers
        if headers.get("host") != expected_host:
            raise PublicLimit("not_found", 404)
        if raw != path.encode("ascii", errors="replace") or b"%" in raw or "\\" in path or "//" in path:
            raise PublicLimit("not_found", 404)
        if scope.get("query_string"):
            raise PublicLimit("not_found", 404)
        if request.method == "GET":
            if path == "/":
                return RedirectResponse("/learn/")
            if path == "/healthz":
                return JSONResponse({"status": "ok" if self.sessions.enabled else "unavailable"})
            if path in {"/learn/", "/learn/index.html"}:
                text = self.index.read_text()
                text = text.replace("<head>", '<head><meta name="eklavya-mode" content="public">', 1)
                from starlette.responses import HTMLResponse
                return HTMLResponse(text)
            if path in self.assets and path != "/learn/index.html":
                return FileResponse(self.assets[path])
            raise PublicLimit("not_found", 404)
        match = re.fullmatch(r"/session/([a-f0-9]{32})/(offer|end)", path)
        if not (path == "/session/start" and request.method == "POST") and not (
                match and ((match[2] == "offer" and request.method in {"POST", "PATCH"}) or
                           (match[2] == "end" and request.method == "POST"))):
            raise PublicLimit("not_found", 404)
        if headers.get("origin") != config.origin:
            raise PublicLimit("forbidden", 403)
        if headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise PublicLimit("invalid", 415)
        # Reject ambiguous duplicated security/framing headers.
        for name in [b"host", b"origin", b"content-type", b"x-eklavya-csrf", b"content-length", b"cookie"]:
            if sum(key.lower() == name for key, value in scope["headers"]) > 1:
                raise PublicLimit("invalid", 400)
        body = bytearray()
        async with asyncio.timeout(10):
            async for chunk in request.stream():
                if len(body) + len(chunk) > 262144:
                    raise PublicLimit("too_large", 413)
                body.extend(chunk)
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise PublicLimit("invalid", 400) from None
        if not isinstance(data, dict):
            raise PublicLimit("invalid", 400)
        owner = request.cookies.get(config.cookie)
        if path == "/session/start":
            if data:
                raise PublicLimit("invalid", 400)
            source = request.client.host if request.client else "unknown"
            lease, token, csrf = await self.sessions.reserve(owner, source)
            response = JSONResponse({
                "sessionId": lease.session_id, "csrf": csrf,
                "expiresAt": int((time.time() + 900) * 1000),
                "iceConfig": {"iceServers": config.ice_servers},
                "webrtcRequestParams": {"endpoint": f"/session/{lease.session_id}/offer"},
            })
            response.set_cookie(config.cookie, token, httponly=True, secure=config.origin.startswith("https:"),
                                samesite="strict", path="/", max_age=900)
            return response
        lease = self.sessions.owned(
            match[1], owner, headers.get("x-eklavya-csrf"),
            allow_ended=(match[2] == "end"),
        )
        if match[2] == "end":
            if data:
                raise PublicLimit("invalid", 400)
            await lease.close()
            return JSONResponse({"status": "ended"})
        return JSONResponse(await self.sessions.offer(lease, data, request.method))


def install_safe_logging():
    # Drop content-bearing dependency logs rather than trying to redact unknown formats.
    logger.remove()
    logger.add(lambda message: None, filter=lambda record: False)
    logging.disable(logging.CRITICAL)

from pipecat.frames.frames import (
    ErrorFrame, InputTransportMessageFrame, LLMContextFrame,
    LLMMessagesAppendFrame, EndWorkerFrame, StartFrame,
)
from pipecat.processors.frame_processor import FrameDirection
import pipecat.processors.frameworks.rtvi.models as RTVI
from pipecat.processors.frameworks.rtvi.processor import RTVIProcessor
from pipecat.processors.frameworks.rtvi.observer import (
    RTVIObserver, RTVIObserverParams, RTVIFunctionCallReportLevel,
)
from eklavya.grounded_tutor import GroundedTutorProcessor, latest_user_text


def public_observer_params():
    return RTVIObserverParams(
        metrics_enabled=False, system_logs_enabled=False,
        bot_audio_level_enabled=False, user_audio_level_enabled=False,
        function_call_report_level={"*": RTVIFunctionCallReportLevel.DISABLED},
    )


class PublicObserver(RTVIObserver):
    async def send_rtvi_message(self, model, exclude_none=True):
        if model.type == "bot-interrupted":
            model = RTVI.ServerMessage(data={"type": "learner-interrupted"})
        await super().send_rtvi_message(model, exclude_none)


class PublicRTVIProcessor(RTVIProcessor):
    def __init__(self, policy):
        super().__init__()
        self.policy = policy
        self.pending = 0
        self.accepted = asyncio.Queue(maxsize=16)
        self.consumer = None
        self.handshake_done = asyncio.Event()

        @self.event_handler("on_client_ready")
        async def ready(processor):
            self.policy.mark_ready()
            self.handshake_done.set()

    def create_rtvi_observer(self, *, params=None, **kwargs):
        return PublicObserver(self, params=public_observer_params(), **kwargs)

    async def accept(self, raw):
        try:
            await self.policy.check_rtvi(raw)
            if self.pending >= 16:
                raise PublicLimit()
            parsed = raw if isinstance(raw, RTVI.Message) else RTVI.Message.model_validate(raw)
            self.pending += 1
            self.accepted.put_nowait(parsed)
        except Exception:
            self.policy.request_close()

    async def queue_frame(self, frame, direction=FrameDirection.DOWNSTREAM, callback=None):
        if isinstance(frame, InputTransportMessageFrame):
            await self.accept(frame.message)
            if callback:
                await callback(self, frame, direction)
            return
        await super().queue_frame(frame, direction, callback)

    async def handle_message(self, message):
        await self.accept(message)

    async def process_frame(self, frame, direction):
        if isinstance(frame, InputTransportMessageFrame):
            await self.accept(frame.message)
            return
        if isinstance(frame, ErrorFrame):
            frame = ErrorFrame(error="The tutor is temporarily unavailable.", fatal=frame.fatal)
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame) and self.consumer is None:
            self.consumer = self.create_task(self.consume())

    async def consume(self):
        while True:
            message = await self.accepted.get()
            try:
                self.policy.ensure_live()
                if message.type == "client-ready":
                    # One in-flight handshake, including same-lease restart.
                    # Repeated handshakes never reset age/readiness/idle budgets.
                    self.handshake_done.clear()
                    await RTVIProcessor.handle_message(self, message)
                    async with asyncio.timeout(10):
                        await self.handshake_done.wait()
                elif message.type == "send-text":
                    await self.handshake_done.wait()
                    await self.interrupt_bot()
                    await self.pipeline_worker.flush_pipeline()
                    await self.push_frame(LLMMessagesAppendFrame(
                        messages=[{"role": "user", "content": message.data["content"]}], run_llm=True,
                    ))
                elif message.type == "disconnect-bot":
                    await self.push_frame(EndWorkerFrame())
                    self.policy.request_close()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.policy.request_close()
            finally:
                self.pending -= 1
                self.accepted.task_done()

    async def push_transport_message(self, model, exclude_none=True):
        if model.type in {"metrics", "system-log"} or model.type.startswith("llm-function-call"):
            return
        if model.type == "error":
            # Construct the actual version's typed model, preserving only a safe fatal flag.
            values = model.model_dump()
            if isinstance(values.get("data"), dict):
                values["data"]["error"] = "The tutor is temporarily unavailable."
                values["data"].pop("message", None)
            model = type(model).model_validate(values)
        elif model.type == "error-response":
            values = model.model_dump()
            if isinstance(values.get("data"), dict):
                values["data"]["error"] = "Request unavailable."
            model = type(model).model_validate(values)
        await super().push_transport_message(model, exclude_none)

    async def cleanup(self):
        if self.consumer:
            await self.cancel_task(self.consumer)
            self.consumer = None
        await super().cleanup()


class PublicGroundedTutorProcessor(GroundedTutorProcessor):
    def __init__(self, *, policy, **kwargs):
        super().__init__(**kwargs)
        self.policy = policy

    async def process_frame(self, frame, direction):
        if isinstance(frame, LLMContextFrame) and latest_user_text(frame.context):
            self.policy.accept_turn()
            # Normal Pipecat interruption cancels the previous processing task;
            # never allow a second model request while it is still unwinding.
            if self.policy.turn_lock.locked():
                self.policy.request_close()
                raise PublicLimit("busy")
            async with self.policy.turn_lock:
                await super().process_frame(frame, direction)
        else:
            await super().process_frame(frame, direction)
