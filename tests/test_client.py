"""cBioPortal client: honest User-Agent, sequential requests, dbVersion-keyed cache, backoff."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from cbioportal_link import __version__
from cbioportal_link.api.client import INFO_PATH, CbioClient
from cbioportal_link.config import CbioSettings
from cbioportal_link.exceptions import (
    InvalidInputError,
    NotFoundError,
    RateLimitedError,
    UpstreamSchemaError,
    UpstreamUnavailableError,
)
from tests.conftest import BASE, fast_settings, load

PATH = "/api/genes/BRAF"
PARAMS: dict[str, object] = {}
INFO = httpx.Response(200, json=load("info"))


@pytest.fixture
async def client() -> AsyncIterator[CbioClient]:
    c = CbioClient(fast_settings())
    c._cache_put(INFO_PATH, load("info"))  # seed /api/info so tests mock only their own path
    yield c
    await c.aclose()


@respx.mock(base_url=BASE)
async def test_sends_honest_user_agent_and_returns_json(
    respx_mock: respx.MockRouter, client: CbioClient
) -> None:
    route = respx_mock.get(PATH).mock(return_value=httpx.Response(200, json=load("gene_BRAF")))
    data = await client.get_json(PATH, PARAMS)
    assert data["hugoGeneSymbol"] == "BRAF"
    ua = route.calls.last.request.headers["user-agent"]
    assert (
        ua.startswith(f"cbioportal-link/{__version__}")
        and "github.com/berntpopp/cbioportal-link" in ua
    )


@respx.mock(base_url=BASE)
async def test_identical_calls_hit_upstream_once(
    respx_mock: respx.MockRouter, client: CbioClient
) -> None:
    route = respx_mock.get(PATH).mock(return_value=httpx.Response(200, json=load("gene_BRAF")))
    await client.get_json(PATH, PARAMS)
    await client.get_json(PATH, dict(PARAMS))
    assert route.call_count == 1


@respx.mock(base_url=BASE)
async def test_other_400_is_invalid_input_with_fixed_message(
    respx_mock: respx.MockRouter, client: CbioClient
) -> None:
    respx_mock.get("/api/studies").mock(
        return_value=httpx.Response(400, json={"message": "bad sortBy evil999"})
    )
    with pytest.raises(InvalidInputError) as info:
        await client.get_json("/api/studies", {"sortBy": "x"})
    assert "evil999" not in info.value.message
    assert "field" not in info.value.extra


@respx.mock(base_url=BASE)
async def test_429_retries_then_rate_limited_with_retry_after(
    respx_mock: respx.MockRouter, client: CbioClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []

    async def _sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("cbioportal_link.api.client.asyncio.sleep", _sleep)
    route = respx_mock.get(PATH).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "7"})
    )
    with pytest.raises(RateLimitedError) as info:
        await client.get_json(PATH, PARAMS)
    assert route.call_count == 1 + fast_settings().max_retries
    assert info.value.extra["retry_after_s"] == 7.0
    assert slept == [7.0, 7.0]  # backoff honours Retry-After


@respx.mock(base_url=BASE)
async def test_503_then_success_recovers(respx_mock: respx.MockRouter, client: CbioClient) -> None:
    respx_mock.get(PATH).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=load("gene_BRAF"))]
    )
    data = await client.get_json(PATH, PARAMS)
    assert data["hugoGeneSymbol"] == "BRAF"


@respx.mock(base_url=BASE)
async def test_persistent_timeout_is_retryable_upstream_unavailable(
    respx_mock: respx.MockRouter, client: CbioClient
) -> None:
    respx_mock.get(PATH).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(UpstreamUnavailableError) as info:
        await client.get_json(PATH, PARAMS)
    assert info.value.retryable is True


@respx.mock(base_url=BASE)
async def test_non_json_success_is_schema_error(
    respx_mock: respx.MockRouter, client: CbioClient
) -> None:
    respx_mock.get(PATH).mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(UpstreamSchemaError):
        await client.get_json(PATH, PARAMS)


async def test_rate_limit_refusal_propagates_before_any_request() -> None:
    settings = fast_settings()
    settings.daily_cap = 2  # /api/info + one data request
    c = CbioClient(settings)
    with respx.mock(base_url=BASE) as router:
        router.get("/api/info").mock(return_value=INFO)
        route = router.get(PATH).mock(return_value=httpx.Response(200, json=load("gene_BRAF")))
        await c.get_json(PATH, PARAMS)
        with pytest.raises(RateLimitedError):
            await c.get_json(PATH, {"x": 1})
        assert route.call_count == 1
    await c.aclose()


@respx.mock(base_url=BASE)
async def test_concurrent_identical_calls_share_one_upstream_request(
    respx_mock: respx.MockRouter, client: CbioClient
) -> None:
    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.01)  # let the other callers start while this one is in flight
        return httpx.Response(200, json=load("gene_BRAF"))

    route = respx_mock.get(PATH).mock(side_effect=slow)
    results = await asyncio.gather(*(client.get_json(PATH, PARAMS) for _ in range(3)))
    assert route.call_count == 1
    assert all(r["hugoGeneSymbol"] == "BRAF" for r in results)


@respx.mock(base_url=BASE)
async def test_backoff_is_exponential_without_retry_after(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []

    async def _sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("cbioportal_link.api.client.asyncio.sleep", _sleep)
    c = CbioClient(CbioSettings(min_interval_s=0.0, backoff_base_s=1.5, max_retries=3))
    c._cache_put(INFO_PATH, load("info"))
    respx_mock.get(PATH).mock(return_value=httpx.Response(429))
    with pytest.raises(RateLimitedError):
        await c.get_json(PATH)
    assert slept == [1.5, 3.0, 6.0]
    await c.aclose()


@respx.mock(base_url=BASE)
async def test_requests_run_strictly_one_at_a_time(
    respx_mock: respx.MockRouter, client: CbioClient
) -> None:
    in_flight, peak = 0, 0

    async def slow(_: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return httpx.Response(200, json=load("gene_BRAF"))

    respx_mock.get(path__regex=r"^/api/genes/").mock(side_effect=slow)
    await asyncio.gather(*(client.get_json(f"/api/genes/G{i}") for i in range(4)))
    assert peak == 1


@respx.mock(base_url=BASE)
async def test_cache_is_keyed_on_db_version(
    respx_mock: respx.MockRouter, client: CbioClient
) -> None:
    route = respx_mock.get(PATH).mock(return_value=httpx.Response(200, json=load("gene_BRAF")))
    await client.get_json(PATH)
    await client.get_json(PATH)
    assert route.call_count == 1
    client._cache_put(INFO_PATH, {**load("info"), "dbVersion": "3.2.0"})  # portal upgraded
    await client.get_json(PATH)
    assert route.call_count == 2


@respx.mock(base_url=BASE)
async def test_404_is_not_found_and_post_sends_json(
    respx_mock: respx.MockRouter, client: CbioClient
) -> None:
    respx_mock.get("/api/genes/NOTAGENE1").mock(
        return_value=httpx.Response(404, json=load("gene_unknown"))
    )
    with pytest.raises(NotFoundError) as err:
        await client.get_json("/api/genes/NOTAGENE1")
    assert "NOTAGENE1" not in err.value.message
    route = respx_mock.post("/api/mutation-counts-by-position/fetch").mock(
        return_value=httpx.Response(200, json=load("position_counts_BRAF"))
    )
    body = [{"entrezGeneId": 673, "proteinPosStart": 600, "proteinPosEnd": 600}]
    assert (await client.post_json("/api/mutation-counts-by-position/fetch", body))[0]["count"]
    assert json.loads(route.calls.last.request.content) == body
