"""Local learner launcher. Run as a script, not bare uvicorn."""
import argparse
import os
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pipecat.runner.run import app, main as runner_main

from eklavya.app import bot as _bot


async def bot(runner_args):
    await _bot(runner_args, enable_behavior_monitor=False)


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
    parser = argparse.ArgumentParser(description="Eklavya local learner")
    runner_main(parser)


if __name__ == "__main__":
    main()
