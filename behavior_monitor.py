"""Local CV subprocess integration and threshold policy for voice interventions."""

from __future__ import annotations

import asyncio
import json
import math
import os
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger


SIGNALS = ("engagement", "boredom", "confusion", "frustration")
TRIGGER_THRESHOLDS = {
    "engagement": 0.40,
    "boredom": 0.60,
    "confusion": 0.65,
    "frustration": 0.65,
}
RECOVERY_THRESHOLDS = {
    "engagement": 0.45,
    "boredom": 0.55,
    "confusion": 0.60,
    "frustration": 0.60,
}


@dataclass(frozen=True)
class BehaviorSample:
    """One normalized prediction received from the CV process."""

    timestamp: float
    face_present: bool
    scores: dict[str, float]
    monitoring_enabled: bool

    @classmethod
    def from_json(cls, payload: dict) -> "BehaviorSample | None":
        if payload.get("type") != "prediction":
            return None
        scores: dict[str, float] = {}
        try:
            for signal in SIGNALS:
                value = float(payload[signal])
                if not math.isfinite(value):
                    return None
                scores[signal] = max(0.0, min(1.0, value))
            return cls(
                timestamp=float(payload.get("timestamp", time.time())),
                face_present=bool(payload.get("face_present", False)),
                scores=scores,
                monitoring_enabled=bool(payload.get("monitoring_enabled", False)),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(frozen=True)
class BehaviorIntervention:
    reasons: tuple[str, ...]
    scores: dict[str, float]


class BehaviorPolicy:
    """EMA, dwell, hysteresis, and cooldown policy independent of subprocesses."""

    def __init__(
        self,
        *,
        trigger_thresholds: dict[str, float] | None = None,
        recovery_thresholds: dict[str, float] | None = None,
        dwell_seconds: float = 5.0,
        cooldown_seconds: float = 60.0,
        recovery_seconds: float = 5.0,
        ema_alpha: float = 0.2,
    ) -> None:
        self.trigger_thresholds = trigger_thresholds or dict(TRIGGER_THRESHOLDS)
        self.recovery_thresholds = recovery_thresholds or dict(RECOVERY_THRESHOLDS)
        self.dwell_seconds = dwell_seconds
        self.cooldown_seconds = cooldown_seconds
        self.recovery_seconds = recovery_seconds
        self.ema_alpha = ema_alpha
        self.reset()

    def reset(self) -> None:
        self._ema: dict[str, float] = {}
        self._breach_since: dict[str, float | None] = dict.fromkeys(SIGNALS)
        self._recovery_since: dict[str, float | None] = dict.fromkeys(SIGNALS)
        self._armed = dict.fromkeys(SIGNALS, True)
        self._last_intervention_at: float | None = None
        self._mode_signals: set[str] = set()
        self._mode_recovery_since: float | None = None

    @property
    def concise_mode_active(self) -> bool:
        return bool(self._mode_signals)

    def update(self, sample: BehaviorSample, *, now: float | None = None) -> BehaviorIntervention | None:
        now = time.monotonic() if now is None else now
        if not sample.monitoring_enabled or not sample.face_present:
            self._ema.clear()
            for signal in SIGNALS:
                self._breach_since[signal] = None
                self._recovery_since[signal] = None
            return None

        for signal in SIGNALS:
            raw = sample.scores[signal]
            previous = self._ema.get(signal)
            self._ema[signal] = raw if previous is None else (self.ema_alpha * raw + (1 - self.ema_alpha) * previous)

        active: set[str] = set()
        for signal, value in self._ema.items():
            trigger = (
                value <= self.trigger_thresholds[signal]
                if signal == "engagement"
                else value >= self.trigger_thresholds[signal]
            )
            recovered = (
                value >= self.recovery_thresholds[signal]
                if signal == "engagement"
                else value <= self.recovery_thresholds[signal]
            )

            if trigger:
                active.add(signal)
                self._recovery_since[signal] = None
                if self._breach_since[signal] is None:
                    self._breach_since[signal] = now
            else:
                self._breach_since[signal] = None

            if not self._armed[signal]:
                if recovered:
                    if self._recovery_since[signal] is None:
                        self._recovery_since[signal] = now
                    elif now - self._recovery_since[signal] >= self.recovery_seconds:
                        self._armed[signal] = True
                        self._recovery_since[signal] = None
                else:
                    self._recovery_since[signal] = None

        if self._mode_signals:
            mode_recovered = all(
                signal not in active
                and (
                    self._ema[signal] >= self.recovery_thresholds[signal]
                    if signal == "engagement"
                    else self._ema[signal] <= self.recovery_thresholds[signal]
                )
                for signal in self._mode_signals
            )
            if mode_recovered:
                if self._mode_recovery_since is None:
                    self._mode_recovery_since = now
                elif now - self._mode_recovery_since >= self.recovery_seconds:
                    self._mode_signals.clear()
                    self._mode_recovery_since = None
            else:
                self._mode_recovery_since = None

        cooldown_over = (
            self._last_intervention_at is None
            or now - self._last_intervention_at >= self.cooldown_seconds
        )
        qualified = {
            signal
            for signal in active
            if self._armed[signal]
            and self._breach_since[signal] is not None
            and now - self._breach_since[signal] >= self.dwell_seconds
        }
        if not cooldown_over or not qualified:
            return None

        self._last_intervention_at = now
        self._mode_signals.update(qualified)
        for signal in qualified:
            self._armed[signal] = False
        return BehaviorIntervention(
            reasons=tuple(sorted(qualified)),
            scores={signal: self._ema[signal] for signal in qualified},
        )


BehaviorCallback = Callable[[BehaviorIntervention], Awaitable[None]]
RecoveryCallback = Callable[[], Awaitable[None]]


class BehaviorMonitor:
    """Owns one local CV process and forwards qualified policy events."""

    def __init__(
        self,
        *,
        on_intervention: BehaviorCallback,
        on_recovery: RecoveryCallback,
        cv_python: str | None = None,
        model_path: str | None = None,
        camera_index: int | None = None,
        policy: BehaviorPolicy | None = None,
    ) -> None:
        self.root = Path(__file__).resolve().parent
        configured_python = cv_python or os.getenv("CV_PYTHON", "CV/.venv-h5/bin/python")
        configured_model = model_path or os.getenv(
            "CV_MODEL_PATH", "CV/daisee_engagement_model_final.h5"
        )
        self.cv_python = str(self._resolve_path(configured_python))
        self.model_path = str(self._resolve_path(configured_model))
        self.camera_index = camera_index if camera_index is not None else int(os.getenv("CV_CAMERA_INDEX", "0"))
        self.policy = policy or BehaviorPolicy()
        self.on_intervention = on_intervention
        self.on_recovery = on_recovery
        self.process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._writer_task: asyncio.Task | None = None
        self._frame_queue: asyncio.Queue[bytes | None] | None = None
        self._frame_lock = asyncio.Lock()
        self._streaming = False
        self.latest_sample: BehaviorSample | None = None
        self._stopping = False

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.root / path

    async def start(self) -> bool:
        if self.process is not None and self.process.returncode is None:
            return False
        executable = Path(self.cv_python)
        model = Path(self.model_path)
        if not executable.is_file() or not model.is_file():
            logger.warning(
                "CV sensing unavailable: interpreter={} model={}", executable, model
            )
            return False
        self.policy.reset()
        self.latest_sample = None
        self._stopping = False
        try:
            self.process = await asyncio.create_subprocess_exec(
                str(executable),
                str(self.root / "CV/emotion_cam_h5.py"),
                "--model-path",
                str(model),
                "--input-stdin",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            logger.warning("Could not start CV sensing: {}", exc)
            self.process = None
            return False
        self._reader_task = asyncio.create_task(self._read_predictions())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        self._frame_queue = asyncio.Queue(maxsize=1)
        self._writer_task = asyncio.create_task(self._write_frames())
        return True

    async def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        process = self.process
        self.process = None
        self._streaming = False
        self.latest_sample = None
        queue = self._frame_queue
        self._frame_queue = None
        if queue is not None:
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                queue.put_nowait(None)
        if process is not None and process.returncode is None:
            if process.stdin is not None:
                process.stdin.close()
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        tasks = tuple(
            task for task in (self._reader_task, self._stderr_task, self._writer_task)
            if task is not None
        )
        for task in tasks:
            if task is not None and not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._reader_task = None
        self._stderr_task = None
        self._writer_task = None
        self.policy.reset()

    async def set_streaming(self, enabled: bool) -> None:
        """Enable or disable browser-camera sensing for the active session."""
        if self._streaming == enabled:
            return
        self._streaming = enabled
        if not enabled:
            was_concise = self.policy.concise_mode_active
            self.policy.reset()
            self.latest_sample = None
            if was_concise:
                await self.on_recovery()

    async def submit_frame(self, jpeg: bytes) -> bool:
        """Queue one browser JPEG, dropping an older pending frame if needed."""
        if not jpeg or len(jpeg) > 750_000 or self.process is None or self._frame_queue is None:
            return False
        await self.set_streaming(True)
        queue = self._frame_queue
        try:
            queue.put_nowait(jpeg)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return False
            queue.put_nowait(jpeg)
        return True

    async def _write_frames(self) -> None:
        queue = self._frame_queue
        process = self.process
        if queue is None or process is None or process.stdin is None:
            return
        try:
            while True:
                jpeg = await queue.get()
                if jpeg is None or process.returncode is not None:
                    return
                process.stdin.write(struct.pack("!I", len(jpeg)))
                process.stdin.write(jpeg)
                await process.stdin.drain()
        except (asyncio.CancelledError, BrokenPipeError, ConnectionError):
            raise
        except Exception as exc:  # pragma: no cover - defensive process boundary
            logger.warning("CV frame writer stopped: {}", exc)

    async def _read_predictions(self) -> None:
        process = self.process
        assert process is not None and process.stdout is not None
        try:
            async for line in process.stdout:
                try:
                    payload = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    logger.debug("Ignoring malformed CV event")
                    continue
                if payload.get("type") == "monitoring_changed":
                    previous_mode = self.policy.concise_mode_active
                    self.policy.reset()
                    if previous_mode:
                        await self.on_recovery()
                    continue
                sample = BehaviorSample.from_json(payload)
                if sample is None or not self._streaming:
                    continue
                self.latest_sample = sample
                previous_mode = self.policy.concise_mode_active
                event = self.policy.update(sample)
                if event is not None:
                    await self.on_intervention(event)
                if previous_mode and not self.policy.concise_mode_active:
                    await self.on_recovery()
            if not self._stopping:
                returncode = await process.wait()
                if returncode:
                    logger.warning("CV process exited with status {}", returncode)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive process boundary
            logger.warning("CV prediction reader stopped: {}", exc)

    async def _read_stderr(self) -> None:
        process = self.process
        assert process is not None and process.stderr is not None
        try:
            async for line in process.stderr:
                logger.debug("CV: {}", line.decode(errors="replace").rstrip())
        except asyncio.CancelledError:
            raise
        except Exception:
            return
