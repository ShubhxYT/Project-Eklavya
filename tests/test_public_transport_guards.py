import asyncio
import httpx
import pytest
from eklavya.public_sessions import PublicLimit


def test_no_alternate_route_bypass_and_body_limit(public_factory):
    async def scenario():
        manager, app, clock = public_factory()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost:7861") as client:
            for path in ["/api/offer", "/start", "/sessions", "/client/", "/behavior/ws",
                         "/files", "/docs", "/openapi.json", "/metrics", "/learn/../.env",
                         "/session/start/", "/session/%73tart"]:
                response = await client.post(path, json={}, headers={"Origin": "http://localhost:7861"})
                assert response.status_code == 404
            response = await client.post("/session/start", content=b"x" * 262145,
                headers={"Origin": "http://localhost:7861", "Content-Type": "application/json"})
            assert response.status_code == 413
            assert not manager.leases
            response = await client.post("/session/start", json={}, headers={"Origin": "https://foreign.example"})
            assert response.status_code == 403
        await manager.shutdown()
    asyncio.run(scenario())


def test_two_owners_cannot_offer_patch_end_each_other(public_factory):
    async def scenario():
        manager, app, clock = public_factory(2)
        transport = httpx.ASGITransport(app)
        headers = {"Origin": "http://localhost:7861"}
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost:7861") as a, \
                httpx.AsyncClient(transport=transport, base_url="http://localhost:7861") as b:
            bootstrap_a = (await a.post("/session/start", json={}, headers=headers)).json()
            bootstrap_b = (await b.post("/session/start", json={}, headers=headers)).json()
            endpoint = bootstrap_a["webrtcRequestParams"]["endpoint"]
            attack = {**headers, "X-Eklavya-CSRF": bootstrap_a["csrf"]}
            for method, path, payload in [
                ("POST", endpoint, {"sdp": "fake", "type": "offer"}),
                ("PATCH", endpoint, {"pc_id": "guessed", "candidates": []}),
                ("POST", endpoint.replace("/offer", "/end"), {}),
            ]:
                assert (await b.request(method, path, json=payload, headers=attack)).status_code == 404
            assert all(lease.peer is None for lease in manager.leases.values())
            result = await a.post(endpoint, json={"sdp": "fake", "type": "offer"}, headers=attack)
            assert result.status_code == 200
            peer_id = result.json()["pc_id"]
            assert (await a.patch(endpoint, json={"pc_id": "foreign", "candidates": []}, headers=attack)).status_code == 404
            result = await a.post(endpoint, json={"sdp": "fake", "type": "offer", "pc_id": peer_id, "restart_pc": True}, headers=attack)
            assert result.status_code == 200
            assert result.json()["pc_id"] != peer_id
            assert (await a.patch(endpoint, json={"pc_id": peer_id, "candidates": []}, headers=attack)).status_code == 404
        await manager.shutdown()
    asyncio.run(scenario())


def test_failed_initialization_retains_peer_until_cleanup(public_factory):
    from conftest import Peer

    class BrokenPeer(Peer):
        async def initialize(self, **kwargs):
            raise RuntimeError("SENSITIVE_PROVIDER_MARKER")

    async def scenario():
        manager, app, clock = public_factory(connection_factory=BrokenPeer)
        lease, owner, csrf = await manager.reserve(None, "a")
        with pytest.raises(RuntimeError):
            await manager.offer(lease, {"sdp": "fake", "type": "offer"}, "POST")
        await lease.close()
        assert lease.peer.disconnected
        assert not manager.leases
    asyncio.run(scenario())

def test_end_during_peer_initialization_cancels_before_release(public_factory):
    from conftest import Peer

    async def scenario():
        entered = asyncio.Event()
        canceled = asyncio.Event()

        class SlowPeer(Peer):
            async def initialize(self, **kwargs):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    canceled.set()

        manager, app, clock = public_factory(connection_factory=SlowPeer)
        lease, owner, csrf = await manager.reserve(None, "a")
        offer = asyncio.create_task(manager.offer(lease, {"sdp": "fake", "type": "offer"}, "POST"))
        await entered.wait()
        assert lease.peer is not None
        await lease.close()
        await asyncio.gather(offer, return_exceptions=True)
        assert canceled.is_set()
        assert lease.peer.disconnected
        assert not manager.leases
    asyncio.run(scenario())


def test_signaling_candidate_patch_and_renegotiation_limits(public_factory):
    async def scenario():
        for limit in ["candidates", "patches", "renegotiations"]:
            manager, app, clock = public_factory()
            lease, owner, csrf = await manager.reserve(None, "a")
            answer = await manager.offer(lease, {"sdp": "fake", "type": "offer"}, "POST")
            peer = answer["pc_id"]
            if limit == "candidates":
                candidate = {"candidate": "", "sdp_mid": "0", "sdp_mline_index": 0}
                with pytest.raises(PublicLimit):
                    await manager.offer(lease, {"pc_id": peer, "candidates": [candidate] * 33}, "PATCH")
            elif limit == "patches":
                for index in range(10):
                    await manager.offer(lease, {"pc_id": peer, "candidates": []}, "PATCH")
                with pytest.raises(PublicLimit):
                    await manager.offer(lease, {"pc_id": peer, "candidates": []}, "PATCH")
            else:
                for index in range(16):
                    await manager.offer(lease, {"pc_id": peer, "sdp": "fake", "type": "offer"}, "POST")
                with pytest.raises(PublicLimit):
                    await manager.offer(lease, {"pc_id": peer, "sdp": "fake", "type": "offer"}, "POST")
            await manager.shutdown()
    asyncio.run(scenario())


def test_public_http_errors_never_echo_initialization_exception(public_factory):
    from conftest import Peer

    class BrokenPeer(Peer):
        async def initialize(self, **kwargs):
            raise RuntimeError("SENSITIVE_PROVIDER_MARKER")

    async def scenario():
        manager, app, clock = public_factory(connection_factory=BrokenPeer)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost:7861") as client:
            headers = {"Origin": "http://localhost:7861"}
            value = (await client.post("/session/start", json={}, headers=headers)).json()
            response = await client.post(value["webrtcRequestParams"]["endpoint"],
                json={"sdp": "fake", "type": "offer"}, headers={**headers, "X-Eklavya-CSRF": value["csrf"]})
            assert response.status_code == 503
            assert response.json() == {"error": "unavailable"}
            assert "SENSITIVE_PROVIDER_MARKER" not in response.text
        await manager.shutdown()
    asyncio.run(scenario())

def test_every_public_websocket_is_denied_before_accept(public_factory):
    async def scenario():
        manager, boundary, clock = public_factory()
        for path in ["/behavior/ws", "/ws", "/session/guessed/offer", "/learn/"]:
            sent = []

            async def receive():
                raise AssertionError("must reject before reading/accepting")

            async def send(message):
                sent.append(message)

            await boundary({"type": "websocket", "path": path}, receive, send)
            assert sent == [{"type": "websocket.close", "code": 1008}]
        await manager.shutdown()
    asyncio.run(scenario())
