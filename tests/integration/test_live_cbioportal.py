"""Live cBioPortal checks (opt-in: CBIOPORTAL_LINK_LIVE_INTEGRATION=1 make test-integration).

A handful of sequential calls through the real client. They pin the upstream contract the
recorded fixtures assume (the panel-aware count endpoints, the BRAF/KRAS acceptance answers)
and act as the drift alarm for the Java-to-Go API rewrite: `alteration-counts/fetch` is 404
today, and the day it changes the frequency design should be revisited.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import httpx
import pytest

from cbioportal_link.api.client import CbioClient
from cbioportal_link.config import CbioSettings
from cbioportal_link.service import CbioService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("CBIOPORTAL_LINK_LIVE_INTEGRATION") != "1",
        reason="set CBIOPORTAL_LINK_LIVE_INTEGRATION=1 to call the live cBioPortal API",
    ),
]


@pytest.fixture
async def service() -> AsyncIterator[CbioService]:
    client = CbioClient(CbioSettings())
    try:
        yield CbioService(client)
    finally:
        await client.aclose()


async def test_live_braf_in_tcga_melanoma(service: CbioService) -> None:
    out = await service.get_gene_alteration_frequency(
        "BRAF", ["skcm_tcga_pan_can_atlas_2018"], None, None, False
    )
    mutation = out["studies"][0]["mutation"]
    assert mutation["profiled"] == 440 and 200 <= mutation["altered"] <= 260


async def test_live_kras_g12c_in_luad(service: CbioService) -> None:
    out = await service.get_gene_alteration_frequency(
        "KRAS", ["luad_tcga_pan_can_atlas_2018"], None, "G12C", False
    )
    change = out["studies"][0]["protein_change"]
    assert change["profiled"] == 566 and 60 <= change["altered"] <= 80


async def test_live_restricted_study_is_still_flagged(service: CbioService) -> None:
    out = await service.search_studies("chord", None, True, 5, 0)
    assert any(s["study_id"] == "msk_chord_2024" and s["restricted"] for s in out["studies"])


async def test_drift_alarm_alteration_counts_endpoint_still_gone() -> None:
    """If this starts passing upstream (not 404), re-evaluate the frequency endpoints."""
    async with httpx.AsyncClient(base_url="https://api.cbioportal.org", timeout=30) as http:
        res = await http.post(
            "/api/alteration-counts/fetch", json={"studyIds": ["skcm_tcga_pan_can_atlas_2018"]}
        )
    assert res.status_code == 404, "alteration-counts/fetch is back: revisit the design"
