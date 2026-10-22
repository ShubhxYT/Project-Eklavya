import asyncio
import pytest
from eklavya.public_sessions import PublicLimit


def test_atomic_single_reservation(public_factory):
    async def scenario():
        manager, app, clock = public_factory()
        barrier = asyncio.Event()

        async def start(index):
            await barrier.wait()
            try:
                return await manager.reserve(None, f"source-{index}")
            except PublicLimit as error:
                return error

        tasks = [asyncio.create_task(start(index)) for index in range(2)]
        barrier.set()
        results = await asyncio.gather(*tasks)
        assert sum(isinstance(result, tuple) for result in results) == 1
        assert len(manager.leases) == 1
        await manager.shutdown()
        assert manager.leases == {}
    asyncio.run(scenario())


def test_owner_csrf_and_expiry(public_factory):
    async def scenario():
        manager, app, clock = public_factory(2)
        first, owner_a, csrf_a = await manager.reserve(None, "a")
        second, owner_b, csrf_b = await manager.reserve(None, "b")
        assert manager.owned(first.session_id, owner_a, csrf_a) is first
        for owner, csrf in [(owner_b, csrf_a), (owner_a, csrf_b), ("guessed", csrf_a)]:
            with pytest.raises(PublicLimit):
                manager.owned(first.session_id, owner, csrf)
        clock.value = 30
        with pytest.raises(PublicLimit):
            first.ensure_live()
        await manager.shutdown()
    asyncio.run(scenario())


def test_limits_are_finite_and_idle_is_user_only(public_factory):
    async def scenario():
        manager, app, clock = public_factory()
        lease, owner, csrf = await manager.reserve(None, "a")
        lease.offer_started = 0
        lease.mark_ready()
        clock.value = 100
        lease.touch_user_activity()
        clock.value = 219
        lease.ensure_live()
        clock.value = 220
        with pytest.raises(PublicLimit):
            lease.ensure_live()
        await manager.shutdown()
    asyncio.run(scenario())


def test_thirty_turns_and_absolute_age(public_factory):
    async def scenario():
        manager, app, clock = public_factory()
        lease, owner, csrf = await manager.reserve(None, "a")
        lease.offer_started = 0
        lease.mark_ready()
        for index in range(30):
            clock.value = index * 7
            lease.accept_turn()
        with pytest.raises(PublicLimit):
            lease.accept_turn()
        await manager.shutdown()
    asyncio.run(scenario())

def test_setup_absolute_and_handshake_do_not_extend_lifetime(public_factory):
    async def scenario():
        for deadline in ["setup", "absolute", "idle"]:
            manager, app, clock = public_factory()
            clock.value = 0
            lease, owner, csrf = await manager.reserve(None, "a")
            lease.offer_started = 0
            if deadline == "setup":
                clock.value = 60
            elif deadline == "absolute":
                lease.mark_ready()
                clock.value = 899
                lease.touch_user_activity()
                clock.value = 900
            else:
                lease.mark_ready()
                clock.value = 100
                lease.mark_ready()  # repeated ready is not meaningful user input
                clock.value = 120
            with pytest.raises(PublicLimit):
                lease.ensure_live()
            await manager.shutdown()
    asyncio.run(scenario())


def test_global_start_limits_and_bounded_limiter_maps(public_factory):
    from collections import deque

    async def scenario():
        manager, app, clock = public_factory()
        manager.starts = deque([0.0] * 6)
        with pytest.raises(PublicLimit):
            await manager.reserve(None, "source")
        clock.value = 61
        manager.starts = deque([0.0] * 60)
        with pytest.raises(PublicLimit):
            await manager.reserve(None, "source")
        clock.value = 86401
        lease, owner, csrf = await manager.reserve(None, "source")
        await lease.close()
        assert len(manager.starts) == 1
        manager.owner_starts = {str(index): deque([clock.value]) for index in range(4096)}
        with pytest.raises(PublicLimit):
            await manager.reserve(None, "new-source")
        assert len(manager.owner_starts) == 4096
        manager.owner_starts.clear()
        manager.ip_starts = {str(index): deque([clock.value]) for index in range(4096)}
        with pytest.raises(PublicLimit):
            await manager.reserve(None, "new-source")
        assert len(manager.ip_starts) == 4096
        await manager.shutdown()
    asyncio.run(scenario())


def test_global_provider_budget_disables_admission_before_send(public_factory):
    from collections import deque
    import httpx

    async def scenario():
        manager, app, clock = public_factory()
        lease, owner, csrf = await manager.reserve(None, "a")
        manager.provider_history = deque([0.0] * 6000)
        sends = []
        client = lease.http_client("stt", transport=httpx.MockTransport(
            lambda request: (sends.append(request) or httpx.Response(200))))
        with pytest.raises(PublicLimit):
            await client.post("https://provider.invalid/test")
        assert sends == []
        assert manager.enabled is False
        await manager.shutdown()
    asyncio.run(scenario())


def test_end_is_idempotent_for_a_closing_lease(public_factory):
    import httpx

    async def scenario():
        manager, boundary, clock = public_factory()
        origin = "http://localhost:7861"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(boundary), base_url=origin
        ) as client:
            start = await client.post("/session/start", json={}, headers={"Origin": origin})
            assert start.status_code == 200
            value = start.json()
            lease = manager.leases[value["sessionId"]]

            # The peer teardown won the race and marked the lease closing.
            lease.closing = True
            headers = {"Origin": origin, "X-Eklavya-CSRF": value["csrf"]}
            ended = await client.post(f"/session/{lease.session_id}/end", json={}, headers=headers)
            assert ended.status_code == 200
            assert ended.json() == {"status": "ended"}

            # Ownership still matters: a bad CSRF must not become a successful end.
            wrong = await client.post(
                f"/session/{lease.session_id}/end",
                json={},
                headers={"Origin": origin, "X-Eklavya-CSRF": "wrong"},
            )
            assert wrong.status_code == 404
        await manager.shutdown()

    asyncio.run(scenario())
