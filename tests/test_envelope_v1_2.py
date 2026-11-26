"""Response-Envelope Standard v1.2: every data tool result validates against the schema.

The schema is vendored from berntpopp/genefoundry-envelope, tag v1.2.0.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

import jsonschema
import pytest

from cbioportal_link.mcp.capabilities import TOOLS

SCHEMA_PATH = pathlib.Path(__file__).parent / "conformance" / "envelope-v1.2.schema.json"
SCHEMA_SHA256 = "c3c47e20d7dd189aac2568fc963b5514d7a5ac2c3e5f21d126f42c96d1ad1ae3"
SCHEMA = json.loads(SCHEMA_PATH.read_text())

#: Ops/meta tools return no upstream data and are outside the v1.2 provenance rule.
META_TOOLS = {"get_server_capabilities", "get_diagnostics"}
DATA_CALLS: list[tuple[str, dict[str, Any]]] = [
    ("get_gene_alteration_frequency", {"gene": "KRAS", "cancer_type": "luad"}),
    ("search_studies", {"cancer_type": "skcm"}),
    ("get_study", {"study_id": "msk_chord_2024"}),
    ("get_gene_mutations", {"gene": "BRAF", "study_id": "skcm_tcga_pan_can_atlas_2018"}),
    ("get_mutation_position_counts", {"gene": "BRAF", "positions": [600, 601]}),
    ("list_cancer_types", {"query": "melanoma"}),
    ("get_mutation_hotspots", {"gene": "TP53", "residue": "R175H"}),
]


def test_vendored_schema_is_the_pinned_release() -> None:
    assert hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest() == SCHEMA_SHA256


def test_every_data_tool_is_covered() -> None:
    assert {name for name, _ in DATA_CALLS} == set(TOOLS) - META_TOOLS


@pytest.mark.parametrize(("tool", "arguments"), DATA_CALLS)
async def test_data_tool_result_validates(
    facade: Any, call_tool: Any, tool: str, arguments: dict[str, Any]
) -> None:
    out = await call_tool(facade, tool, arguments)
    assert out["success"] is True
    jsonschema.validate(out, SCHEMA)
    meta = out["_meta"]
    if tool == "get_mutation_hotspots":  # answers from the bundled snapshot, not the live API
        assert meta["source"] == "cancerhotspots" and "4c2d0525" in meta["data_version"]
        assert meta["retrieved_at"] == "2026-11-20T11:12:26Z"
    else:
        assert meta["source"] == "cbioportal"
        assert meta["data_version"] == "cBioPortal v7.2.3 (database 3.1.0)"
    assert meta["retrieved_at"].endswith("Z")
    # deprecated top-level copies, kept for one minor release
    assert out["retrieved_at"] == meta["retrieved_at"] and out["data_version"]


async def test_error_result_validates(facade: Any, call_tool: Any) -> None:
    out = await call_tool(facade, "get_study", {"study_id": "no_such_study"})
    assert out["success"] is False
    jsonschema.validate(out, SCHEMA)


async def test_cache_hit_keeps_the_original_fetch_time(
    facade: Any, call_tool: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = iter([1_800_000_000.0 + 3600 * i for i in range(100)])
    monkeypatch.setattr("cbioportal_link.api.client.time.time", lambda: next(clock))
    first = await call_tool(facade, "get_study", {"study_id": "msk_chord_2024"})
    again = await call_tool(facade, "get_study", {"study_id": "msk_chord_2024"})
    # the clock moves an hour per reading: an equal stamp can only be the stored fetch time
    assert again["_meta"]["retrieved_at"] == first["_meta"]["retrieved_at"]
    assert first["_meta"]["retrieved_at"].startswith("2027-01-15T")


PAGED = {"search_studies", "get_gene_mutations", "list_cancer_types"}


@pytest.mark.parametrize(("tool", "arguments"), DATA_CALLS)
async def test_paged_tools_report_meta_pagination(
    facade: Any, call_tool: Any, tool: str, arguments: dict[str, Any]
) -> None:
    out = await call_tool(facade, tool, arguments)
    if tool not in PAGED:
        assert "pagination" not in out["_meta"]
        return
    assert out["_meta"]["pagination"] == {
        "total_count": out["total"],
        "has_more": out["truncated"],
        "next_cursor": None,
        "next_offset": out["next_offset"],
    }
