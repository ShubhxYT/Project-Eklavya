from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx


class ProviderError(RuntimeError):
    pass


class ProviderAuthError(ProviderError):
    pass


async def request_with_retry(
    operation: Callable[[], Awaitable[httpx.Response]], *, label: str, retries: int = 2
) -> httpx.Response:
    for attempt in range(retries + 1):
        try:
            response = await operation()
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            if attempt == retries:
                raise ProviderError(f"{label} unavailable") from exc
            await asyncio.sleep(0.2 * (2**attempt))
            continue
        except (
            httpx.ReadError,
            httpx.ReadTimeout,
            httpx.WriteError,
            httpx.WriteTimeout,
            httpx.RemoteProtocolError,
        ) as exc:
            # The provider may already have accepted a chargeable request; never replay it.
            raise ProviderError(f"{label} connection ended ambiguously") from exc
        if response.status_code in {401, 403}:
            raise ProviderAuthError(f"{label} authentication failed")
        if (response.status_code == 429 or response.status_code >= 500) and attempt < retries:
            await asyncio.sleep(0.2 * (2**attempt))
            continue
        if response.is_error:
            raise ProviderError(f"{label} request failed ({response.status_code})")
        return response
    raise AssertionError("unreachable")
