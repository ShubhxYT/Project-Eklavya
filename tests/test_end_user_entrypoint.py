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

def test_public_main_launches_the_actual_outer_boundary(learner, monkeypatch):
    import uvicorn
    from eklavya.public_sessions import PublicBoundary
    module, app, core = learner
    launched = []
    monkeypatch.setattr(sys, "argv", ["end_user_app.py", "--public", "--public-origin", "http://localhost:7861"])
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    monkeypatch.setenv("PIPECAT_ICE_SERVERS", "[]")
    monkeypatch.setattr(uvicorn, "run", lambda application, **kwargs: launched.append((application, kwargs)))
    # Preserve test-process logging; logging suppression is checked in isolation below.
    monkeypatch.setattr("eklavya.public_sessions.install_safe_logging", lambda: None)
    module.main()
    assert len(launched) == 1
    boundary, options = launched[0]
    assert isinstance(boundary, PublicBoundary)
    assert boundary.app is app
    assert boundary.sessions is app.state.public_sessions
    assert options["workers"] == 1 and options["access_log"] is False

def test_public_asset_and_header_boundary(public_factory):
    import asyncio
    import httpx

    async def scenario():
        manager, boundary, clock = public_factory()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(boundary), base_url="http://localhost:7861") as client:
            page = await client.get("/learn/")
            assert page.status_code == 200
            assert 'name="eklavya-mode" content="public"' in page.text
            assert "camera=()" in page.headers["permissions-policy"]
            assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
            assert page.headers["x-content-type-options"] == "nosniff"
            assert (await client.get("/learn/test.js")).status_code == 200
            for path in ["/.env", "/learn/.env", "/learn/missing.js", "/learn/source.map",
                         "/src/eklavya/app.py", "/docs", "/client/", "/behavior/ws", "/files"]:
                assert (await client.get(path)).status_code == 404
            start = await client.post("/session/start", json={}, headers={"Origin": "http://localhost:7861"})
            assert start.status_code == 200
            assert start.headers["cache-control"] == "no-store"
            assert "HttpOnly" in start.headers["set-cookie"]
            assert "SameSite=strict" in start.headers["set-cookie"]
            assert "Domain=" not in start.headers["set-cookie"]
            assert not (await client.options("/api/offer", headers={
                "Origin": "http://localhost:7861", "Access-Control-Request-Method": "POST",
            })).is_success
        await manager.shutdown()
    asyncio.run(scenario())
