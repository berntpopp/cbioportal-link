"""cBioPortal tools: prevalence, studies, mutations, cancer types and hotspots."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Annotated, Any, Literal, get_args

from pydantic import AfterValidator, Field, StrictBool, StrictInt

from cbioportal_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from cbioportal_link.mcp.envelope import McpErrorContext, ToolReturn, run_mcp_tool
from cbioportal_link.mcp.next_commands import cmd
from cbioportal_link.mcp.service_adapters import get_cbio_service
from cbioportal_link.service import (
    DEFAULT_LIMIT,
    DEFAULT_STUDIES,
    MAX_POSITIONS,
    MAX_STUDIES,
)
from cbioportal_link.shaping import MAX_LIMIT, RESPONSE_MODES, one_letter

if TYPE_CHECKING:
    from fastmcp import FastMCP

Gene = Annotated[
    str,
    Field(
        min_length=1,
        max_length=40,
        description="Gene symbol (HGNC, e.g. BRAF) or NCBI Gene ID (673 or NCBIGene:673).",
        examples=["BRAF"],
    ),
]
StudyId = Annotated[
    str,
    Field(
        pattern=r"^[A-Za-z0-9_.\-]{2,100}$",
        description="cBioPortal study ID (from search_studies).",
        examples=["luad_tcga_pan_can_atlas_2018"],
    ),
]
CancerType = Annotated[str, Field(pattern=r"^[A-Za-z0-9_]{2,40}$")]
OptCancerType = Annotated[
    CancerType | None,
    Field(
        description="Lowercase OncoTree code as cBioPortal uses it (luad, skcm, mel); "
        "subtypes are included. Find codes with list_cancer_types."
    ),
]


def _known_codes(value: str) -> str:
    """Convert three-letter amino-acid codes; reject an unknown one (never a silent zero)."""
    out = one_letter(value)
    if out is None:
        raise ValueError("use one-letter (G12C) or three-letter (p.Gly12Cys) amino-acid codes")
    return out


def _one_letter_change(value: str) -> str:
    """Convert a three-letter change; reject anything not in one-letter form afterwards."""
    out = _known_codes(value)
    if not re.fullmatch(r"(?:[pP]\.)?[A-Za-z*]\d{1,5}[A-Za-z0-9_*>]{0,30}", out):
        raise ValueError("use one-letter (G12C) or three-letter (p.Gly12Cys) amino-acid codes")
    return out


OptProteinChange = Annotated[
    Annotated[
        str,
        Field(pattern=r"^(?:[pP]\.)?[A-Za-z*]{1,3}\d{1,5}[A-Za-z0-9_*>]{0,30}$"),
        AfterValidator(_one_letter_change),
    ]
    | None,
    Field(
        description="Protein change, e.g. V600E or G12C (p. prefix optional; three-letter "
        "p.Gly12Cys is converted).",
        examples=["G12C"],
    ),
]
IncludeRestricted = Annotated[
    StrictBool,
    Field(description="Opt in to studies with non-commercial/no-derivatives terms (flagged)."),
]
Limit = Annotated[
    StrictInt,
    Field(ge=1, le=MAX_LIMIT, description=f"Max rows (default {DEFAULT_LIMIT}, max {MAX_LIMIT})."),
]
Offset = Annotated[
    StrictInt, Field(ge=0, description="Rows to skip; use the previous `next_offset`.")
]
ResponseModeValue = Literal["minimal", "compact", "standard", "full"]
assert get_args(ResponseModeValue) == RESPONSE_MODES


def _args(**values: Any) -> dict[str, Any]:
    """The call's arguments without unset optionals (for next_commands)."""
    return {k: v for k, v in values.items() if v not in (None, False, "compact")}


def _paged(payload: dict[str, Any], tool: str, args: dict[str, Any]) -> list[dict[str, Any]]:
    """Next page first when truncated."""
    if payload.get("next_offset") is not None:
        return [cmd(tool, **{**args, "offset": payload["next_offset"]})]
    return []


async def _run(
    tool: str,
    args: dict[str, Any],
    fetch: Callable[[], Awaitable[dict[str, Any]]],
    steps: Callable[[dict[str, Any]], list[dict[str, Any]]],
) -> ToolReturn:
    async def call() -> dict[str, Any]:
        payload = await fetch()
        payload["_meta"] = {"next_commands": steps(payload)}
        return payload

    return await run_mcp_tool(tool, call, context=McpErrorContext(tool, arguments=args))


def register_cbio_tools(mcp: FastMCP) -> None:
    """Register the cBioPortal tools on a FastMCP instance."""

    @mcp.tool(
        name="get_gene_alteration_frequency",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"prevalence"},
        description=(
            "Get how often a gene is altered per cBioPortal study: mutation (altered / "
            "profiled samples, panel-aware), optional protein_change (e.g. KRAS G12C) and "
            "CNA (amplified / deep-deleted / profiled), each row with licence, citation and "
            "import_date. Pick studies by cancer_type (OncoTree code, subtypes included, "
            "largest first, max_studies; total/truncated count matching studies) or study_ids; neither = MSK-IMPACT 2017 pan-cancer. "
            "Never sum rows (cohorts overlap). Restricted (NC/ND) studies are skipped unless "
            "include_restricted. Signature: get_gene_alteration_frequency(gene, cancer_type=, "
            "study_ids=, protein_change=, include_restricted=, max_studies=)."
        ),
    )
    async def get_gene_alteration_frequency(
        gene: Gene,
        cancer_type: OptCancerType = None,
        study_ids: Annotated[
            list[str] | None,
            Field(
                min_length=1,
                max_length=MAX_STUDIES,
                description=f"Explicit study IDs (1-{MAX_STUDIES}); instead of cancer_type.",
                examples=[["luad_tcga_pan_can_atlas_2018"]],
            ),
        ] = None,
        protein_change: OptProteinChange = None,
        include_restricted: IncludeRestricted = False,
        max_studies: Annotated[
            StrictInt,
            Field(
                ge=1,
                le=MAX_STUDIES,
                description=f"With cancer_type: studies to query (default {DEFAULT_STUDIES}).",
            ),
        ] = DEFAULT_STUDIES,
    ) -> ToolReturn:
        args = _args(
            gene=gene,
            cancer_type=cancer_type,
            study_ids=study_ids,
            protein_change=protein_change,
            include_restricted=include_restricted,
            max_studies=None if max_studies == DEFAULT_STUDIES else max_studies,
        )

        def steps(p: dict[str, Any]) -> list[dict[str, Any]]:
            out = []
            if p["truncated"]:
                out.append(cmd("get_gene_alteration_frequency", **{**args, "max_studies": 10}))
            first = p["studies"][0]["study_id"] if p["studies"] else None
            if first:
                out.append(cmd("get_gene_mutations", gene=p["gene"], study_id=first))
            return [*out, cmd("get_mutation_hotspots", gene=p["gene"])]

        return await _run(
            "get_gene_alteration_frequency",
            args,
            lambda: get_cbio_service().get_gene_alteration_frequency(
                gene, study_ids, cancer_type, protein_change, include_restricted, max_studies
            ),
            steps,
        )

    @mcp.tool(
        name="search_studies",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"studies"},
        description=(
            "Search public cBioPortal studies by keyword (ID, name, citation) and/or "
            "cancer_type (OncoTree code, subtypes included), largest first. Each row: "
            "study_id, name, licence, restricted, citation, pmid, import_date, cancer_type, "
            "sample counts and assembly. Restricted (NC/ND) studies are excluded unless "
            "include_restricted (restricted_excluded counts them). No filter lists all. "
            "Signature: search_studies(query=, cancer_type=, include_restricted=, "
            "response_mode=, limit=, offset=)."
        ),
    )
    async def search_studies(
        query: Annotated[
            str | None,
            Field(min_length=2, max_length=100, description="Keyword, e.g. 'pan-cancer atlas'."),
        ] = None,
        cancer_type: OptCancerType = None,
        include_restricted: IncludeRestricted = False,
        response_mode: Annotated[
            ResponseModeValue,
            Field(
                description="minimal: id, name, licence, citation | compact (default): + "
                "cancer type, sample counts, assembly | standard: + URL | full: + fenced "
                "description."
            ),
        ] = "compact",
        limit: Limit = DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> ToolReturn:
        args = _args(
            query=query,
            cancer_type=cancer_type,
            include_restricted=include_restricted,
            response_mode=response_mode,
            limit=limit,
            offset=offset,
        )

        def steps(p: dict[str, Any]) -> list[dict[str, Any]]:
            first = [cmd("get_study", study_id=s["study_id"]) for s in p["studies"][:1]]
            return _paged(p, "search_studies", args) + first

        return await _run(
            "search_studies",
            args,
            lambda: get_cbio_service().search_studies(
                query, cancer_type, include_restricted, limit, offset, response_mode
            ),
            steps,
        )

    @mcp.tool(
        name="get_study",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"studies"},
        description=(
            "Get one cBioPortal study: licence, restricted flag, citation, pmid, "
            "import_date, cancer type, sample counts, assembly, the fenced description, every "
            "PMID (pmids) and its molecular profile IDs (no data matrices). An unknown ID is "
            "not_found. Signature: get_study(study_id)."
        ),
    )
    async def get_study(study_id: StudyId) -> ToolReturn:
        return await _run(
            "get_study",
            {"study_id": study_id},
            lambda: get_cbio_service().get_study(study_id),
            lambda p: [
                cmd(
                    "get_gene_alteration_frequency",
                    gene="TP53",
                    study_ids=[p["study"]["study_id"]],
                )
            ],
        )

    @mcp.tool(
        name="get_gene_mutations",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"mutations"},
        description=(
            "Get the distinct somatic mutations of one gene in one study, most recurrent "
            "first: protein_change, samples, mutation_type and genomic chr/start/end/ref/alt "
            "with their assembly (mostly GRCh37), plus mutated_samples and the study's "
            "licence and citation. protein_change keeps one change. No sample or patient IDs. "
            "Signature: get_gene_mutations(gene, study_id, protein_change=, "
            "include_restricted=, response_mode=, limit=, offset=)."
        ),
    )
    async def get_gene_mutations(
        gene: Gene,
        study_id: StudyId,
        protein_change: OptProteinChange = None,
        include_restricted: IncludeRestricted = False,
        response_mode: Annotated[
            ResponseModeValue,
            Field(
                description="minimal: protein change and samples | compact (default): + "
                "type and genomic coordinates | standard/full: + variant type, RefSeq "
                "transcript, protein position, keyword."
            ),
        ] = "compact",
        limit: Limit = DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> ToolReturn:
        args = _args(
            gene=gene,
            study_id=study_id,
            protein_change=protein_change,
            include_restricted=include_restricted,
            response_mode=response_mode,
            limit=limit,
            offset=offset,
        )

        def steps(p: dict[str, Any]) -> list[dict[str, Any]]:
            top = p["variants"][0]["protein_change"] if p["variants"] else None
            hot = [cmd("get_mutation_hotspots", gene=p["gene"], residue=top)] if top else []
            return _paged(p, "get_gene_mutations", args) + hot

        return await _run(
            "get_gene_mutations",
            args,
            lambda: get_cbio_service().get_gene_mutations(
                gene, study_id, protein_change, include_restricted, limit, offset, response_mode
            ),
            steps,
        )

    @mcp.tool(
        name="get_mutation_position_counts",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"mutations"},
        description=(
            "Get portal-wide mutation counts at protein positions of a gene (e.g. BRAF 600) "
            "across all public cBioPortal studies: a recurrence check with no denominator "
            "(overlapping cohorts count repeatedly; restricted studies included). For a "
            "frequency use get_gene_alteration_frequency. "
            "Signature: get_mutation_position_counts(gene, positions)."
        ),
    )
    async def get_mutation_position_counts(
        gene: Gene,
        positions: Annotated[
            list[StrictInt],
            Field(
                min_length=1,
                max_length=MAX_POSITIONS,
                description=f"Protein positions (1-{MAX_POSITIONS}).",
                examples=[[600]],
            ),
        ],
    ) -> ToolReturn:
        return await _run(
            "get_mutation_position_counts",
            {"gene": gene, "positions": positions},
            lambda: get_cbio_service().get_mutation_position_counts(gene, positions),
            lambda p: [cmd("get_mutation_hotspots", gene=p["gene"])],
        )

    @mcp.tool(
        name="list_cancer_types",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"cancer_types"},
        description=(
            "List cBioPortal cancer types: code (lowercase OncoTree code, the cancer_type "
            "other tools take), name and parent. query matches names or an exact code; "
            "parent lists every subtype below a code. "
            "Signature: list_cancer_types(query=, parent=, limit=, offset=)."
        ),
    )
    async def list_cancer_types(
        query: Annotated[
            str | None,
            Field(min_length=2, max_length=100, description="Name substring or exact code."),
        ] = None,
        parent: Annotated[
            CancerType | None, Field(description="Only subtypes below this code (e.g. nsclc).")
        ] = None,
        limit: Limit = DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> ToolReturn:
        args = _args(query=query, parent=parent, limit=limit, offset=offset)

        def steps(p: dict[str, Any]) -> list[dict[str, Any]]:
            first = [cmd("search_studies", cancer_type=t["code"]) for t in p["cancer_types"][:1]]
            return _paged(p, "list_cancer_types", args) + first

        return await _run(
            "list_cancer_types",
            args,
            lambda: get_cbio_service().list_cancer_types(query, parent, limit, offset),
            steps,
        )

    @mcp.tool(
        name="get_mutation_hotspots",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"hotspots"},
        description=(
            "Get Cancer Hotspots calls for a gene (bundled v2 + 3D snapshot, ODbL 1.0): "
            "residue, type (single_residue, in_frame_indel, splice_site, 3d), tumor_count, "
            "q_value (3d: p_value, clusters), variants (+ tumor_types in standard mode). With "
            "residue (V600, V600E, R175H) it answers residue_is_hotspot and is_hotspot (for "
            "a change: seen at a hotspot residue, variant_tumor_count > 0); not a hotspot "
            "does not mean benign. Residues follow the assembly's transcript (default GRCh38). "
            "Signature: get_mutation_hotspots(gene, residue=, assembly=, response_mode=)."
        ),
    )
    async def get_mutation_hotspots(
        gene: Gene,
        residue: Annotated[
            Annotated[str, AfterValidator(_known_codes)] | None,
            Field(min_length=1, max_length=40, description="Residue or change: V600 or V600E."),
        ] = None,
        assembly: Annotated[
            Literal["GRCh38", "GRCh37"],
            Field(description="Build whose transcript numbers the residues (default GRCh38)."),
        ] = "GRCh38",
        response_mode: Annotated[
            ResponseModeValue,
            Field(
                description="minimal/compact (default): calls without the per-tumour-type "
                "breakdown | standard/full: + tumor_types per call."
            ),
        ] = "compact",
    ) -> ToolReturn:
        args = _args(gene=gene, residue=residue, response_mode=response_mode)
        return await _run(
            "get_mutation_hotspots",
            args,
            lambda: get_cbio_service().get_mutation_hotspots(
                gene, residue, assembly, response_mode
            ),
            lambda p: [cmd("get_gene_alteration_frequency", gene=p["gene"])],
        )
