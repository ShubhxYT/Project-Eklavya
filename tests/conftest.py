"""Never load developer dotenv files during test collection."""
import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: False

import asyncio
from types import SimpleNamespace
import pytest
from eklavya.public_sessions import PublicConfig, PublicSessions


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class Peer:
    instances = []

    def __init__(self, **kwargs):
        self.handlers = {}
        self.pc_id = "peer-" + str(len(self.instances))
        self.disconnected = False
        self.initialized = False
        self.instances.append(self)

    def event_handler(self, name):
        def bind(callback):
            self.handlers[name] = callback
            return callback
        return bind

    async def initialize(self, **kwargs):
        self.initialized = True

    async def renegotiate(self, **kwargs):
        if kwargs.get("restart_pc"):
            self.pc_id += "-new"

    def get_answer(self):
        return {"sdp": "safe-fake-answer", "type": "answer", "pc_id": self.pc_id}

    async def add_ice_candidate(self, candidate):
        pass

    async def disconnect(self):
        self.disconnected = True


@pytest.fixture
def public_factory(tmp_path):
    from eklavya.public_sessions import PublicBoundary
    root = tmp_path / "public"
    root.mkdir()
    (root / "index.html").write_text("<!doctype html><head></head><body>Learner</body>")
    (root / "test.js").write_text("export {};")
    clock = Clock()
    Peer.instances = []

    async def fake_bot(args):
        await asyncio.Event().wait()

    def make(capacity=1, connection_factory=Peer):
        manager = PublicSessions(
            PublicConfig("http://localhost:7861", root, capacity=capacity), clock=clock,
            connection_factory=connection_factory, bot=fake_bot,
            cli_args=SimpleNamespace(transport="webrtc", ice_servers=[]),
        )
        return manager, PublicBoundary(None, manager), clock
    return make
