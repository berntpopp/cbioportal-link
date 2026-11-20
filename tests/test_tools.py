"""End-to-end MCP tool tests through an in-memory FastMCP client."""

from __future__ import annotations

from typing import Any

from fastmcp import Client

from cbioportal_link.mcp.capabilities import TOOLS


async def _raw(mcp: Any, name: str, args: dict[str, Any]) -> Any:
    async with Client(mcp) as client:
        return await client.call_tool(name, args, raise_on_error=False)


async def test_registered_tools_match_capabilities_and_are_documented(facade: Any) -> None:
    async with Client(facade) as client:
        tools = await client.list_tools()
    assert [t.name for t in tools] == TOOLS
    for tool in tools:
        props = tool.input_schema.get("properties", {})
        for name, prop in props.items():
            assert prop.get("description"), f"{tool.name}.{name} lacks a description"
        for name in tool.input_schema.get("required", []):
            assert props[name].get("examples"), f"{tool.name}.{name} lacks examples"
        assert tool.description and "Signature:" in tool.description
        assert tool.annotations is not None and tool.annotations.read_only_hint is True
        assert tool.output_schema is None


async def test_frequency_envelope_and_next_steps(facade: Any, call_tool: Any) -> None:
    out = await call_tool(
        facade,
        "get_gene_alteration_frequency",
        {"gene": "KRAS", "cancer_type": "luad", "protein_change": "G12C", "max_studies": 1},
    )
    assert out["success"] is True and out["truncated"] is True and out["total"] == 2
    meta = out["_meta"]
    assert meta["tool"] == "get_gene_alteration_frequency" and meta["source"] == "cbioportal"
    assert meta["unsafe_for_clinical_use"] is True
    steps = [c["tool"] for c in meta["next_commands"]]
    assert steps == [
        "get_gene_alteration_frequency",
        "get_gene_mutations",
        "get_mutation_hotspots",
    ]
    assert meta["next_commands"][0]["arguments"]["max_studies"] == 10


async def test_unknown_study_is_is_error_not_found(facade: Any) -> None:
    res = await _raw(facade, "get_study", {"study_id": "NOPE_xyz"})
    assert res.is_error is True
    body = res.structured_content
    assert body["error_code"] == "not_found" and body["field"] == "study_id"


async def test_foreign_gene_id_is_rejected_with_a_converter(facade: Any) -> None:
    res = await _raw(facade, "get_mutation_hotspots", {"gene": "HGNC:6407"})
    body = res.structured_content
    assert res.is_error is True and body["error_code"] == "invalid_input"
    assert body["field"] == "gene" and body["allowed_values"]
    assert body["_meta"]["next_commands"] == [
        {"tool": "hgnc_resolve_symbol", "arguments": {"query": "HGNC:6407"}}
    ]


async def test_hotspot_question_answers_yes(facade: Any, call_tool: Any) -> None:
    out = await call_tool(facade, "get_mutation_hotspots", {"gene": "TP53", "residue": "R175H"})
    assert out["is_hotspot"] is True and "ODbL" in out["source"]["licence"]


async def test_study_name_in_study_id_suggests_search(facade: Any) -> None:
    res = await _raw(facade, "get_study", {"study_id": "TCGA melanoma"})
    assert res.is_error is True
    assert res.structured_content["_meta"]["next_commands"] == [
        {"tool": "search_studies", "arguments": {"query": "TCGA melanoma"}}
    ]


async def test_over_cap_limit_suggests_the_clamped_call(facade: Any) -> None:
    args = {"query": "melanoma", "limit": 500}
    res = await _raw(facade, "search_studies", args)
    assert res.is_error is True
    assert res.structured_content["_meta"]["next_commands"] == [
        {"tool": "search_studies", "arguments": {**args, "limit": 100}}
    ]


async def test_capabilities_and_diagnostics(facade: Any, call_tool: Any) -> None:
    caps = await call_tool(facade, "get_server_capabilities", {})
    assert caps["tools"] == TOOLS and caps["research_use_only"] is True
    assert "actionability" in caps["research_use_notice"]
    diag = await call_tool(facade, "get_diagnostics", {})
    assert diag["upstream"]["base_url"] == "https://api.cbioportal.org"


async def test_descriptions_name_only_returned_fields(facade: Any, call_tool: Any) -> None:
    """Contract truth: the fields a description promises are in the response."""
    studies = await call_tool(facade, "search_studies", {"cancer_type": "skcm"})
    assert {
        "study_id",
        "name",
        "licence",
        "restricted",
        "citation",
        "pmid",
        "import_date",
        "cancer_type",
        "assembly",
    } <= set(studies["studies"][0])
    assert "restricted_excluded" in studies
    study = (await call_tool(facade, "get_study", {"study_id": "msk_chord_2024"}))["study"]
    assert {"licence", "restricted", "description", "molecular_profiles"} <= set(study)
    muts = await call_tool(
        facade, "get_gene_mutations", {"gene": "BRAF", "study_id": "skcm_tcga_pan_can_atlas_2018"}
    )
    assert {"protein_change", "samples", "mutation_type", "chr", "start", "ref", "alt"} <= set(
        muts["variants"][0]
    )
    assert {"assembly", "mutated_samples", "study"} <= set(muts)
    types = await call_tool(facade, "list_cancer_types", {"query": "melanoma"})
    assert {"code", "name", "parent"} <= set(types["cancer_types"][0])
    hot = await call_tool(
        facade,
        "get_mutation_hotspots",
        {"gene": "BRAF", "residue": "V600E", "response_mode": "standard"},
    )
    assert {"residue", "type", "tumor_count", "variants", "tumor_types"} <= set(hot["hotspots"][0])
    assert {"is_hotspot", "variant_tumor_count"} <= set(hot)


async def test_restricted_study_error_offers_the_opt_in_retry(facade: Any) -> None:
    args = {"gene": "KRAS", "study_ids": ["msk_chord_2024"], "protein_change": "G12C"}
    res = await _raw(facade, "get_gene_alteration_frequency", args)
    assert res.is_error is True
    assert res.structured_content["_meta"]["next_commands"] == [
        {
            "tool": "get_gene_alteration_frequency",
            "arguments": {**args, "include_restricted": True},
        }
    ]


async def test_both_selectors_error_offers_each_selector(facade: Any) -> None:
    args = {"gene": "KRAS", "study_ids": ["luad_tcga_pan_can_atlas_2018"], "cancer_type": "luad"}
    res = await _raw(facade, "get_gene_alteration_frequency", args)
    assert res.is_error is True
    tool = "get_gene_alteration_frequency"
    assert res.structured_content["_meta"]["next_commands"] == [
        {"tool": tool, "arguments": {"gene": "KRAS", "study_ids": args["study_ids"]}},
        {"tool": tool, "arguments": {"gene": "KRAS", "cancer_type": "luad"}},
    ]


async def test_three_letter_protein_change_is_accepted(facade: Any, call_tool: Any) -> None:
    out = await call_tool(
        facade,
        "get_gene_alteration_frequency",
        {
            "gene": "KRAS",
            "study_ids": ["luad_tcga_pan_can_atlas_2018"],
            "protein_change": "p.Gly12Cys",
        },
    )
    assert out["studies"][0]["protein_change"]["value"] == "G12C"
    hot = await call_tool(facade, "get_mutation_hotspots", {"gene": "TP53", "residue": "Arg175His"})
    assert hot["is_hotspot"] is True and hot["variant_tumor_count"] == 386


async def test_unknown_gene_hint_says_the_resolver_lives_on_the_router(facade: Any) -> None:
    res = await _raw(facade, "get_gene_alteration_frequency", {"gene": "KRASX"})
    body = res.structured_content
    assert body["error_code"] == "not_found" and "genefoundry router" in body["hint"]
