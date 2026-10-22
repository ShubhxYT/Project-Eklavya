import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest


@pytest.fixture
def learner(monkeypatch, tmp_path):
    import pipecat.runner.run as runner
    import eklavya.app as core

    # Do not install learner middleware onto the legacy test singleton.
    fresh = FastAPI()
    monkeypatch.setattr(runner, "app", fresh)
    output = tmp_path / "learner"
    output.mkdir()
    (output / "index.html").write_text("<!doctype html><title>Learner</title>")
    (output / "test.js").write_text("export {};")
    monkeypatch.setenv("LEARNER_CLIENT_DIR", str(output))
    module_name = "isolated_learner_entrypoint"
    spec = importlib.util.spec_from_file_location(module_name, Path("end_user_app.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        yield module, fresh, core
    finally:
        sys.modules.pop(module_name, None)


def test_learner_delegates_without_monitor(learner, monkeypatch):
    module, app, core = learner
    delegate = AsyncMock()
    monkeypatch.setattr(module, "_bot", delegate)
    args = SimpleNamespace()
    asyncio.run(module.bot(args))
    delegate.assert_awaited_once_with(args, enable_behavior_monitor=False)
    assert module.app is app
    assert core.app is not app


def test_behavior_denied_before_handler(learner):
    module, app, core = learner
    with TestClient(app) as client:
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/learn/"
        assert client.get("/learn/").status_code == 200
        for path in ["/behavior", "/behavior/ws", "/behavior/anything"]:
            assert client.get(path).status_code == 404
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/behavior/ws"):
                pytest.fail("learner behavior websocket accepted")


def test_main_exports_delegator_and_uses_runner(learner, monkeypatch):
    module, app, core = learner
    calls = []
    monkeypatch.setattr(module, "runner_main", lambda parser: calls.append(parser))
    module.main()
    assert len(calls) == 1
    assert callable(module.bot)
