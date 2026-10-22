"""Local/public learner launcher. Run as a script, not bare uvicorn."""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pipecat.runner.run import app, main as runner_main

from eklavya.app import bot as _bot


async def bot(runner_args):
    manager = getattr(app.state, "public_sessions", None)
    if manager is None:
        await _bot(runner_args, enable_behavior_monitor=False)
        return
    policy = manager.leases.get(runner_args.session_id)
    if policy is None or policy.peer is not runner_args.webrtc_connection:
        from eklavya.public_sessions import PublicLimit
        raise PublicLimit("not_found", 404)
    policy.ensure_live()
    await _bot(runner_args, enable_behavior_monitor=False, session_policy=policy)


class LearnerBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if path == "/behavior" or path.startswith("/behavior/"):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            elif scope["type"] == "http":
                await JSONResponse({"error": "not_found"}, status_code=404)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def install_learner_routes(app, *, config):
    app.add_middleware(LearnerBoundary)

    @app.get("/", include_in_schema=False)
    async def learner_root():
        return RedirectResponse("/learn/")

    @app.get("/healthz", include_in_schema=False)
    async def health():
        return {"status": "ok"}

    app.mount("/learn", StaticFiles(directory=config, html=True, check_dir=False), name="learner")


install_learner_routes(
    app,
    config=Path(os.getenv("LEARNER_CLIENT_DIR", Path(__file__).parent / "end-user-client")),
)


def main():
    if "--public" not in sys.argv[1:]:
        runner_main(argparse.ArgumentParser(description="Eklavya local learner"))
        return

    # Approved public-launch correction: normalize only the supported public
    # WebRTC configuration. Do not call runner.main() and then pretend its
    # private route handler became lease-owned.
    import uvicorn
    from eklavya.public_sessions import PublicBoundary, PublicConfig, PublicSessions, install_safe_logging

    parser = argparse.ArgumentParser(description="Eklavya bounded anonymous learner")
    parser.add_argument("--public", action="store_true", required=True)
    parser.add_argument("--public-origin", required=True)
    parser.add_argument("-t", "--transport", choices=["webrtc"], default="webrtc")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7861)
    parser.add_argument("--ice-servers", default=os.getenv("PIPECAT_ICE_SERVERS", "[]"))
    args = parser.parse_args()
    if os.getenv("WEB_CONCURRENCY", "1") != "1":
        parser.error("public sessions require exactly one process")
    try:
        args.ice_servers = json.loads(args.ice_servers)
        if not isinstance(args.ice_servers, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("urls"), (str, list)) or
            set(item) - {"urls", "username", "credential"} for item in args.ice_servers
        ):
            raise ValueError()
        config = PublicConfig(
            origin=args.public_origin,
            assets=Path(os.getenv("LEARNER_CLIENT_DIR", Path(__file__).parent / "end-user-client")),
            ice_servers=args.ice_servers,
            enabled=os.getenv("EKLAVYA_PUBLIC_ENABLED", "1") == "1",
        )
    except (ValueError, TypeError):
        parser.error("invalid public origin or ICE configuration")
    install_safe_logging()
    sessions = PublicSessions(config, bot=bot, cli_args=args)
    app.state.public_sessions = sessions
    public_app = PublicBoundary(app, sessions)
    uvicorn.run(public_app, host=args.host, port=args.port, workers=1,
                access_log=False, log_config=None,
                forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"))


if __name__ == "__main__":
    main()
