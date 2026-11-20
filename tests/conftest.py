"""Shared fixtures: a real CbioService over a respx-mocked cBioPortal web API.

Unit tests are network-free. ``mocked_cbio`` serves the recorded fixtures in
``tests/fixtures/cbio/`` (captured from https://api.cbioportal.org on 2026-11-20; mutation
records trimmed to the fields the server reads); ``facade`` wires the service into a real
FastMCP instance and ``call_tool`` drives it through an in-memory ``fastmcp.Client``.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any

import httpx
import pytest
import respx

from cbioportal_link.api.client import CbioClient
from cbioportal_link.config import CbioSettings
from cbioportal_link.mcp import metrics
from cbioportal_link.mcp.facade import create_cbio_mcp
from cbioportal_link.mcp.service_adapters import set_cbio_service
from cbioportal_link.service import CbioService

FX = pathlib.Path(__file__).parent / "fixtures" / "cbio"
BASE = "https://api.cbioportal.org"


def load(name: str) -> Any:
    """Load a recorded cBioPortal JSON fixture by file stem."""
    return json.loads((FX / f"{name}.json").read_text())


def fast_settings() -> CbioSettings:
    """Upstream settings with politeness spacing disabled so tests run instantly."""
    return CbioSettings(min_interval_s=0.0, backoff_base_s=0.0)


def _ok(name: str) -> httpx.Response:
    return httpx.Response(200, json=load(name))


def _missing(name: str) -> httpx.Response:
    body = load(name)
    body.pop("_status", None)
    return httpx.Response(404, json=body)


def _gene(request: httpx.Request) -> httpx.Response:
    ref = request.url.path.rsplit("/", 1)[-1]
    name = f"gene_{ref}"
    return _ok(name) if (FX / f"{name}.json").exists() else _missing("gene_unknown")


def _profiles(request: httpx.Request) -> httpx.Response:
    study = request.url.path.split("/")[3]
    name = f"profiles_{study}"
    return _ok(name) if (FX / f"{name}.json").exists() else httpx.Response(200, json=[])


def _counts(prefix: str) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        study = body["studyViewFilter"]["studyIds"][0]
        gene = body["genomicDataFilters"][0]["hugoGeneSymbol"]
        name = f"{prefix}_{study}_{gene}"
        return _ok(name) if (FX / f"{name}.json").exists() else httpx.Response(200, json=[])

    return handler


def _mutations(request: httpx.Request) -> httpx.Response:
    profile = request.url.path.split("/")[3]
    study = profile.removesuffix("_mutations")
    gene = {"673": "BRAF", "3845": "KRAS", "7157": "TP53"}[request.url.params["entrezGeneId"]]
    name = f"mutations_{study}_{gene}"
    return _ok(name) if (FX / f"{name}.json").exists() else httpx.Response(200, json=[])


@pytest.fixture(autouse=True)
def _reset_metrics() -> Iterator[None]:
    """Keep the process-wide metrics collector clean between tests."""
    metrics.reset()
    yield
    metrics.reset()


@pytest.fixture
def mocked_cbio() -> Iterator[respx.MockRouter]:
    """A respx router serving the recorded cBioPortal fixtures."""
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        router.get("/api/info").mock(return_value=_ok("info"))
        router.get("/api/studies").mock(return_value=_ok("studies"))
        router.get("/api/cancer-types").mock(return_value=_ok("cancer_types"))
        router.get(path__regex=r"^/api/genes/[^/]+$").mock(side_effect=_gene)
        router.get(path__regex=r"^/api/studies/[^/]+/molecular-profiles$").mock(
            side_effect=_profiles
        )
        router.post("/api/mutation-data-counts/fetch").mock(side_effect=_counts("mutcounts"))
        router.post("/api/genomic-data-counts/fetch").mock(side_effect=_counts("cnacounts"))
        router.get(path__regex=r"^/api/molecular-profiles/[^/]+/mutations$").mock(
            side_effect=_mutations
        )
        router.post("/api/mutation-counts-by-position/fetch").mock(
            return_value=_ok("position_counts_BRAF")
        )
        yield router


@pytest.fixture
async def cbio_service(mocked_cbio: respx.MockRouter) -> AsyncIterator[CbioService]:
    """A real CbioService over the respx-mocked client."""
    client = CbioClient(fast_settings())
    try:
        yield CbioService(client)
    finally:
        await client.aclose()


@pytest.fixture
def facade(cbio_service: CbioService) -> Iterator[Any]:
    """A FastMCP facade with the fixture service injected; cleans up after."""
    mcp = create_cbio_mcp(service_factory=lambda: cbio_service)
    yield mcp
    set_cbio_service(None)


@pytest.fixture
def call_tool() -> Callable[[Any, str, dict[str, Any]], Awaitable[Any]]:
    """Call a tool through an in-memory ``fastmcp.Client``; return the structured dict."""
    from fastmcp import Client

    async def _call(mcp: Any, name: str, args: dict[str, Any]) -> Any:
        async with Client(mcp) as client:
            res = await client.call_tool(name, args, raise_on_error=False)
        if isinstance(res.structured_content, dict):
            return res.structured_content
        return res.data

    return _call
