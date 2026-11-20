"""Async client for the public cBioPortal web API (``api.cbioportal.org``).

Follows cBioPortal's published policy for scripts and agents (``cbioportal.org/llms.txt``):
small filtered requests only, run **sequentially** (one request in flight process-wide),
cached locally. Every request passes the process-wide :class:`RateLimiter`, carries an
honest User-Agent, is restricted to the configured origin over HTTPS with a hard decoded
byte cap, and backs off exponentially on 429/5xx/timeouts (honouring ``Retry-After``).
Successful JSON is cached in-process, keyed on the portal's ``/api/info`` ``dbVersion``
so a database upgrade invalidates every cached answer.

Upstream error bodies are used only to classify the failure; callers see fixed,
server-authored messages (Response-Envelope v1.1 error-message sanitation).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from typing import Any

import httpx

from cbioportal_link import __version__
from cbioportal_link.api.url_guard import (
    MAX_REDIRECTS,
    build_origin_allowlist,
    make_url_guard,
    read_capped_response,
)
from cbioportal_link.config import CbioSettings
from cbioportal_link.exceptions import (
    InvalidInputError,
    NotFoundError,
    RateLimitedError,
    UpstreamSchemaError,
    UpstreamUnavailableError,
)
from cbioportal_link.ratelimit import RateLimiter

USER_AGENT = f"cbioportal-link/{__version__} (+https://github.com/berntpopp/cbioportal-link)"
INFO_PATH = "/api/info"
_RETRY_STATUS = {429, 500, 502, 503, 504}


def _retry_after(response: httpx.Response | None) -> float | None:
    raw = response.headers.get("retry-after") if response is not None else None
    try:
        return max(0.0, float(raw)) if raw is not None else None
    except ValueError:
        return None


def _classify_400() -> Exception:
    """A cBioPortal 400; its body is never echoed (error-message sanitation)."""
    return InvalidInputError(
        "cBioPortal rejected the request parameters.", recovery_action="reformulate_input"
    )


class CbioClient:
    """Sequential, rate-limited, cached, origin-guarded JSON client for ``api.cbioportal.org``."""

    def __init__(self, settings: CbioSettings, *, limiter: RateLimiter | None = None) -> None:
        """Build the HTTP client, limiter and cache from settings."""
        self.settings = settings
        self.limiter = limiter or RateLimiter(
            min_interval_s=settings.min_interval_s,
            daily_cap=settings.daily_cap,
            max_wait_s=settings.max_wait_s,
        )
        guard = make_url_guard(build_origin_allowlist(settings.base_url))
        self._http = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=settings.request_timeout_s,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            event_hooks={"request": [guard]},
        )
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[Any]] = {}
        self._sequential = asyncio.Lock()  # llms.txt: one request in flight, never concurrent
        self.upstream_requests = 0
        self.cache_hits = 0

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._http.aclose()

    def _cache_get(self, key: str) -> Any:
        hit = self._cache.get(key)
        if hit is None or hit[0] < time.monotonic():
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        self.cache_hits += 1
        return hit[1]

    def _cache_put(self, key: str, value: Any) -> None:
        ttl = self.settings.info_ttl_s if key == INFO_PATH else self.settings.cache_ttl_s
        self._cache[key] = (time.monotonic() + ttl, value)
        while len(self._cache) > self.settings.cache_maxsize:
            self._cache.popitem(last=False)

    async def info(self) -> dict[str, Any]:
        """``/api/info`` (portal + database version); cached for ``info_ttl_s``."""
        info = await self._once(INFO_PATH, "GET", INFO_PATH, None, None)
        if not isinstance(info, dict):
            raise UpstreamSchemaError("cBioPortal returned an unexpected info body.", field="info")
        return info

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET ``path``; return the decoded JSON or raise a typed error."""
        return await self.request("GET", path, params=params)

    async def post_json(self, path: str, body: Any, params: dict[str, Any] | None = None) -> Any:
        """POST a JSON filter body to ``path``; return the decoded JSON or a typed error."""
        return await self.request("POST", path, params=params, body=body)

    async def request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, body: Any = None
    ) -> Any:
        """One cached JSON call; the cache key includes the portal's ``dbVersion``."""
        db_version = (await self.info()).get("dbVersion")
        key = json.dumps([db_version, method, path, params, body], sort_keys=True, default=str)
        return await self._once(key, method, path, params, body)

    async def _once(
        self, key: str, method: str, path: str, params: dict[str, Any] | None, body: Any
    ) -> Any:
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        # Single-flight: parallel identical calls share one upstream request (politeness).
        task = self._inflight.get(key)
        if task is None:
            task = self._inflight[key] = asyncio.ensure_future(
                self._fetch(method, path, params, body)
            )
            task.add_done_callback(lambda done: self._settle(key, done))
        return await asyncio.shield(task)

    def _settle(self, key: str, task: asyncio.Future[Any]) -> None:
        self._inflight.pop(key, None)
        if not task.cancelled() and task.exception() is None:
            self._cache_put(key, task.result())

    async def _fetch(self, method: str, path: str, params: dict[str, Any] | None, body: Any) -> Any:
        attempts = self.settings.max_retries + 1
        response: httpx.Response | None = None
        for attempt in range(attempts):
            if attempt:
                delay = _retry_after(response) or self.settings.backoff_base_s * 2 ** (attempt - 1)
                await asyncio.sleep(min(delay, 30.0))
            await self.limiter.acquire()
            self.upstream_requests += 1
            try:
                async with self._sequential:
                    response = await read_capped_response(
                        self._http,
                        method,
                        path,
                        params=params,
                        json=body,
                        max_bytes=self.settings.max_response_bytes,
                    )
            except httpx.TimeoutException, httpx.TransportError:
                response = None
                continue
            if response.status_code not in _RETRY_STATUS:
                break
        if response is None or response.status_code in _RETRY_STATUS:
            if response is not None and response.status_code == 429:
                raise RateLimitedError(
                    "cBioPortal is rate limiting requests. Retry after retry_after_s seconds.",
                    retryable=True,
                    retry_after_s=_retry_after(response) or 60.0,
                )
            raise UpstreamUnavailableError(
                "The cBioPortal API is temporarily unavailable.", retryable=True
            )
        if response.status_code == 400:
            raise _classify_400()
        if response.status_code == 404:  # unknown study/gene; the service names the argument
            raise NotFoundError("cBioPortal has no record for this identifier.")
        if response.status_code != 200:
            raise UpstreamUnavailableError(
                "The cBioPortal API returned an unexpected status.", retryable=False
            )
        try:
            return response.json()
        except ValueError:
            raise UpstreamSchemaError(
                "cBioPortal returned a non-JSON body.", field="response"
            ) from None
