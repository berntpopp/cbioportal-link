"""cBioPortal data plane: validate input, run small filtered queries, shape honest payloads.

Returns plain dicts and raises typed errors; the MCP envelope owns ``success``/``_meta``.
Frequencies are numerator / samples profiled for the gene (panel-aware), per study, never
summed. Non-commercial or no-derivatives studies are excluded unless the caller opts in;
every row carries its licence and citation. Sample and patient identifiers never leave here.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from cbioportal_link import hotspots
from cbioportal_link.api.client import CbioClient
from cbioportal_link.exceptions import InvalidInputError, NotFoundError, UpstreamSchemaError
from cbioportal_link.mcp.next_commands import cmd
from cbioportal_link.mcp.resources import COHORT_NOTE, DEFAULT_WARNING, POSITION_SCOPE
from cbioportal_link.shaping import (
    MAX_LIMIT,
    assembly,
    fence,
    licence,
    mutation_variant,
    normalize_protein_change,
    page_args,
    page_block,
    ratio,
    rows_of,
    study_ref,
    study_row,
    study_text,
    variant_row,
)

DEFAULT_LIMIT = 20
DEFAULT_STUDIES = 3
MAX_STUDIES = 10
MAX_POSITIONS = 20
#: A gene alone (no study, no cancer type) is answered pan-cancer from this one study.
DEFAULT_STUDY = "msk_impact_2017"
_FOREIGN_GENE = re.compile(r"^(ENSG\d+(\.\d+)?|HGNC:\d+)$", re.I)
_ENTREZ = re.compile(r"^(?:NCBIGene:)?(\d{1,9})$", re.I)
_SYMBOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,29}$")
GENE_FORMS = ["HGNC symbol (BRAF)", "NCBI Gene ID (673 or NCBIGene:673)"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class CbioService:
    """All cBioPortal queries; one instance per process over a shared client."""

    def __init__(self, client: CbioClient) -> None:
        """Bind the service to a sequential, rate-limited, cached upstream client."""
        self.client = client

    async def _stamp(self, payload: dict[str, Any]) -> dict[str, Any]:
        info = await self.client.info()
        payload["data_version"] = (
            f"cBioPortal {info.get('portalVersion')} (database {info.get('dbVersion')}); "
            "per-study import_date on each row"
        )
        payload["retrieved_at"] = _now()
        return payload

    # -- lookups (each one cached request) ------------------------------------------------

    async def _studies(self) -> dict[str, dict[str, Any]]:
        rows = rows_of(
            await self.client.get_json("/api/studies", {"projection": "DETAILED"}), "studies"
        )
        return {str(r.get("studyId")): r for r in rows}

    async def _cancer_types(self) -> list[dict[str, Any]]:
        return rows_of(await self.client.get_json("/api/cancer-types"), "cancer_types")

    async def _descendants(self, code: str) -> set[str]:
        """``code`` plus every cancer type below it in the OncoTree-derived tree."""
        types = await self._cancer_types()
        wanted = code.strip().lower()
        if wanted not in {t.get("cancerTypeId") for t in types}:
            raise NotFoundError(
                "No cBioPortal cancer type has this code.",
                field="cancer_type",
                hint="Codes are lowercase OncoTree codes (luad, skcm, mel); find them with "
                "list_cancer_types(query=<name>).",
                next_commands=[cmd("list_cancer_types", query=code.strip())],
            )
        found, frontier = {wanted}, {wanted}
        while frontier:
            frontier = {
                str(t["cancerTypeId"]) for t in types if t.get("parent") in frontier
            } - found
            found |= frontier
        return found

    async def _study(self, study_id: str, field: str = "study_id") -> dict[str, Any]:
        studies = await self._studies()
        raw = studies.get(study_id.strip())
        if raw is None:
            close = difflib.get_close_matches(study_id.strip(), list(studies), n=3, cutoff=0.85)
            raise NotFoundError(
                "No public cBioPortal study has this ID.",
                field=field,
                hint="Find study IDs with search_studies(query=..., cancer_type=...).",
                candidates=close or None,
                next_commands=[cmd("get_study", study_id=c) for c in close]
                or [cmd("search_studies", query=study_id.strip()[:40])],
            )
        return raw

    def _allow(self, raw: dict[str, Any], include_restricted: bool, field: str) -> None:
        code, restricted = licence(raw.get("description"))
        if restricted and not include_restricted:
            raise InvalidInputError(
                f"Study {raw.get('studyId')} is licensed {code} (non-commercial or "
                "no-derivatives); it is excluded unless include_restricted=true.",
                field=field,
                hint="Set include_restricted=true to opt in; its rows stay flagged restricted.",
                retry_with={"include_restricted": True},
            )

    async def _gene(self, gene: str) -> dict[str, Any]:
        """``{entrez, symbol, resolved_from?}`` for a symbol or NCBI Gene ID."""
        value = gene.strip()
        if _FOREIGN_GENE.match(value):
            raise InvalidInputError(
                "`gene` takes an HGNC symbol or an NCBI Gene ID, not this identifier type.",
                field="gene",
                allowed_values=GENE_FORMS,
                next_commands=[cmd("hgnc_resolve_symbol", query=value)],
            )
        entrez = _ENTREZ.match(value)
        if not entrez and not _SYMBOL.match(value):
            raise InvalidInputError(
                "`gene` is not a gene symbol or NCBI Gene ID.",
                field="gene",
                allowed_values=GENE_FORMS,
            )
        ref = entrez.group(1) if entrez else value.upper()
        try:
            raw = await self.client.get_json(f"/api/genes/{ref}")
        except NotFoundError:
            raise NotFoundError(
                "cBioPortal has no gene with this symbol or ID.",
                field="gene",
                hint="Check the current HGNC symbol (aliases are not resolved here); "
                "hgnc_resolve_symbol is a genefoundry router tool (hgnc-link), not on this server.",
                next_commands=[cmd("hgnc_resolve_symbol", query=value)],
            ) from None
        if not isinstance(raw, dict) or not raw.get("entrezGeneId"):
            raise UpstreamSchemaError("cBioPortal returned an unexpected gene.", field="gene")
        out = {"entrez": int(raw["entrezGeneId"]), "symbol": str(raw.get("hugoGeneSymbol"))}
        if entrez:
            out["resolved_from"] = value
        return out

    async def _profiles(self, study_id: str) -> dict[str, str]:
        """``{"mutation": <profile id>, "cna": <discrete CNA profile id>}`` when present."""
        rows = rows_of(
            await self.client.get_json(f"/api/studies/{study_id}/molecular-profiles"),
            "molecular_profiles",
        )
        out: dict[str, str] = {}
        for p in rows:
            kind, pid = p.get("molecularAlterationType"), str(p.get("molecularProfileId"))
            if kind == "MUTATION_EXTENDED":
                out.setdefault("mutation", pid)
            elif kind == "COPY_NUMBER_ALTERATION" and p.get("datatype") == "DISCRETE":
                out.setdefault("cna", pid)
        return out

    async def _counts(self, path: str, study_id: str, symbol: str, profile: str) -> dict[str, int]:
        body = {
            "genomicDataFilters": [
                {"hugoGeneSymbol": symbol, "profileType": profile.removeprefix(f"{study_id}_")}
            ],
            "studyViewFilter": {"studyIds": [study_id]},
        }
        rows = rows_of(await self.client.post_json(path, body), "counts")
        return {
            str(c.get("value")): int(c.get("count") or 0)
            for row in rows
            for c in row.get("counts") or []
        }

    async def _mutations(self, study_id: str, profile: str, entrez: int) -> list[dict[str, Any]]:
        raw = await self.client.get_json(
            f"/api/molecular-profiles/{profile}/mutations",
            {"sampleListId": f"{study_id}_all", "entrezGeneId": entrez, "projection": "SUMMARY"},
        )
        return rows_of(raw, "mutations")

    # -- tools ------------------------------------------------------------------------------

    async def search_studies(
        self,
        query: str | None,
        cancer_type: str | None,
        include_restricted: bool,
        limit: int,
        offset: int,
        response_mode: str = "compact",
    ) -> dict[str, Any]:
        """Public studies by keyword and/or cancer type (with its subtypes), largest first."""
        page_args(limit, offset)
        studies = list((await self._studies()).values())
        if cancer_type is not None:
            codes = await self._descendants(cancer_type)
            studies = [s for s in studies if s.get("cancerTypeId") in codes]
        if query is not None:
            words = re.split(r"[\s_]+", query.strip().casefold())
            studies = [s for s in studies if all(w in study_text(s) for w in words)]
        restricted = [s for s in studies if licence(s.get("description"))[1]]
        if not include_restricted:
            studies = [s for s in studies if s not in restricted]
        studies.sort(key=lambda s: (-int(s.get("sequencedSampleCount") or 0), s.get("studyId")))
        rows = [study_row(s, response_mode) for s in studies[offset : offset + limit]]
        payload: dict[str, Any] = {
            "query": query,
            "cancer_type": cancer_type,
            "studies": rows,
            **page_block(total=len(studies), returned=len(rows), limit=limit, offset=offset),
            "restricted_excluded": 0 if include_restricted else len(restricted),
        }
        return await self._stamp(payload)

    async def get_study(self, study_id: str) -> dict[str, Any]:
        """One study: provenance, sample counts, profiled data types and description."""
        raw = await self._study(study_id)
        sid = str(raw["studyId"])
        profiles = rows_of(
            await self.client.get_json(f"/api/studies/{sid}/molecular-profiles"),
            "molecular_profiles",
        )
        study = study_row(raw, "standard")
        study["description"] = fence(raw.get("description"), sid)
        study["molecular_profiles"] = [
            {
                "id": p.get("molecularProfileId"),
                "type": p.get("molecularAlterationType"),
                "datatype": p.get("datatype"),
            }
            for p in profiles
        ]
        return await self._stamp({"study": study})

    async def _select(
        self,
        study_ids: list[str] | None,
        cancer_type: str | None,
        include_restricted: bool,
        max_studies: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not 1 <= max_studies <= MAX_STUDIES:
            raise InvalidInputError(f"`max_studies` must be 1-{MAX_STUDIES}.", field="max_studies")
        if study_ids:
            if len(study_ids) > MAX_STUDIES:
                raise InvalidInputError(
                    f"`study_ids` takes 1-{MAX_STUDIES} IDs.", field="study_ids"
                )
            chosen = [await self._study(s, "study_ids") for s in dict.fromkeys(study_ids)]
            for raw in chosen:
                self._allow(raw, include_restricted, "study_ids")
            return chosen, {"study_ids": [s["studyId"] for s in chosen]}
        if cancer_type is None:
            default = {"default": f"{DEFAULT_STUDY} (pan-cancer; set study_ids or cancer_type)"}
            return [await self._study(DEFAULT_STUDY, "study_ids")], default
        page = await self.search_studies(None, cancer_type, include_restricted, MAX_LIMIT, 0)
        if not page["studies"]:
            raise NotFoundError(
                "No public study (within the licence filter) has this cancer type.",
                field="cancer_type",
                hint="Try the parent type (e.g. nsclc for luad) or include_restricted=true.",
            )
        studies = await self._studies()
        ids = [r["study_id"] for r in page["studies"]]
        return [studies[i] for i in ids[:max_studies]], {
            "cancer_type": cancer_type,
            "studies_matching": page["total"],
            "restricted_excluded": page["restricted_excluded"],
            "order": "largest sequenced cohort first",
        }

    async def _frequency_row(
        self, raw: dict[str, Any], gene: dict[str, Any], protein_change: str | None
    ) -> dict[str, Any]:
        sid = str(raw["studyId"])
        row = {**study_ref(raw), "cancer_type": raw.get("cancerTypeId"), "assembly": assembly(raw)}
        profiles = await self._profiles(sid)
        mut = profiles.get("mutation")
        if mut is None:
            row["mutation"] = None
        else:
            c = await self._counts("/api/mutation-data-counts/fetch", sid, gene["symbol"], mut)
            altered, profiled = c.get("MUTATED", 0), c.get("MUTATED", 0) + c.get("NOT_MUTATED", 0)
            row["mutation"] = {
                "altered": altered,
                "profiled": profiled,
                "not_profiled": c.get("NOT_PROFILED", 0),
                "frequency": ratio(altered, profiled),
            }
            if protein_change is not None:
                wanted = normalize_protein_change(protein_change)
                hits = {
                    m.get("sampleId")
                    for m in await self._mutations(sid, mut, gene["entrez"])
                    if normalize_protein_change(str(m.get("proteinChange") or "")) == wanted
                }
                row["protein_change"] = {
                    "value": wanted,
                    "altered": len(hits),
                    "profiled": profiled,
                    "frequency": ratio(len(hits), profiled),
                }
        cna = profiles.get("cna")
        if cna is None:
            row["cna"] = None
        else:
            c = await self._counts("/api/genomic-data-counts/fetch", sid, gene["symbol"], cna)
            profiled = sum(v for k, v in c.items() if k != "NA")
            amp, homdel = c.get("2", 0), c.get("-2", 0)
            row["cna"] = {
                "amplified": amp,
                "deep_deleted": homdel,
                "profiled": profiled,
                "amplified_frequency": ratio(amp, profiled),
                "deep_deleted_frequency": ratio(homdel, profiled),
            }
        return row

    async def get_gene_alteration_frequency(
        self,
        gene: str,
        study_ids: list[str] | None,
        cancer_type: str | None,
        protein_change: str | None,
        include_restricted: bool,
        max_studies: int = DEFAULT_STUDIES,
    ) -> dict[str, Any]:
        """Per-study mutation (and optional protein change) and CNA frequency of one gene."""
        if study_ids and cancer_type is not None:
            keep = {"gene": gene} | ({"protein_change": protein_change} if protein_change else {})
            raise InvalidInputError(
                "Give `study_ids` or `cancer_type`, not both.",
                field="cancer_type",
                next_commands=[
                    cmd("get_gene_alteration_frequency", **keep, **sel)
                    for sel in ({"study_ids": study_ids}, {"cancer_type": cancer_type})
                ],
            )
        resolved = await self._gene(gene)
        chosen, selection = await self._select(
            study_ids, cancer_type, include_restricted, max_studies
        )
        rows = [await self._frequency_row(raw, resolved, protein_change) for raw in chosen]
        payload: dict[str, Any] = {
            "gene": resolved["symbol"],
            "entrez_gene_id": resolved["entrez"],
            "selection": selection,
            "studies": rows,
            "total": selection.get("studies_matching", len(rows)),
            "returned": len(rows),
            "truncated": selection.get("studies_matching", len(rows)) > len(rows),
            "unit": "samples",
            "note": COHORT_NOTE,
            **({"warning": DEFAULT_WARNING} if "default" in selection else {}),
        }
        if "resolved_from" in resolved:
            payload["resolved_from"] = resolved["resolved_from"]
        return await self._stamp(payload)

    async def get_gene_mutations(
        self,
        gene: str,
        study_id: str,
        protein_change: str | None,
        include_restricted: bool,
        limit: int,
        offset: int,
        response_mode: str = "compact",
    ) -> dict[str, Any]:
        """Distinct somatic variants of one gene in one study with their sample counts."""
        page_args(limit, offset)
        resolved = await self._gene(gene)
        raw = await self._study(study_id)
        self._allow(raw, include_restricted, "study_id")
        sid = str(raw["studyId"])
        profile = (await self._profiles(sid)).get("mutation")
        if profile is None:
            raise NotFoundError(
                "This study has no mutation profile.",
                field="study_id",
                next_commands=[cmd("get_study", study_id=sid)],
            )
        records = await self._mutations(sid, profile, resolved["entrez"])
        if protein_change is not None:
            wanted = normalize_protein_change(protein_change)
            records = [
                m
                for m in records
                if normalize_protein_change(str(m.get("proteinChange") or "")) == wanted
            ]
        samples: dict[tuple[Any, ...], set[Any]] = {}
        first: dict[tuple[Any, ...], dict[str, Any]] = {}
        for m in records:
            key = mutation_variant(m)
            samples.setdefault(key, set()).add(m.get("sampleId"))
            first.setdefault(key, m)
        order = sorted(samples, key=lambda k: (-len(samples[k]), str(k[0])))
        rows = [
            variant_row(first[k], len(samples[k]), response_mode)
            for k in order[offset : offset + limit]
        ]
        builds = Counter(str(m.get("ncbiBuild")) for m in records if m.get("ncbiBuild"))
        payload: dict[str, Any] = {
            "gene": resolved["symbol"],
            "study": study_ref(raw),
            "assembly": assembly(raw) if not builds else builds.most_common(1)[0][0],
            "protein_change": None if protein_change is None else wanted,
            "mutated_samples": len({m.get("sampleId") for m in records}),
            "variants": rows,
            **page_block(total=len(order), returned=len(rows), limit=limit, offset=offset),
        }
        if "resolved_from" in resolved:
            payload["resolved_from"] = resolved["resolved_from"]
        return await self._stamp(payload)

    async def get_mutation_position_counts(self, gene: str, positions: list[int]) -> dict[str, Any]:
        """Portal-wide mutation counts at protein positions (a recurrence check, no denominator)."""
        if not 1 <= len(positions) <= MAX_POSITIONS:
            raise InvalidInputError(
                f"`positions` takes 1-{MAX_POSITIONS} protein positions.", field="positions"
            )
        if any(p < 1 for p in positions):
            raise InvalidInputError("`positions` must be >= 1.", field="positions")
        resolved = await self._gene(gene)
        wanted = list(dict.fromkeys(positions))
        body = [
            {"entrezGeneId": resolved["entrez"], "proteinPosStart": p, "proteinPosEnd": p}
            for p in wanted
        ]
        rows = rows_of(
            await self.client.post_json("/api/mutation-counts-by-position/fetch", body), "counts"
        )
        counts = {int(r.get("proteinPosStart") or 0): int(r.get("count") or 0) for r in rows}
        payload: dict[str, Any] = {
            "gene": resolved["symbol"],
            "positions": [{"position": p, "mutations": counts.get(p, 0)} for p in wanted],
            "scope": POSITION_SCOPE,
        }
        if "resolved_from" in resolved:
            payload["resolved_from"] = resolved["resolved_from"]
        return await self._stamp(payload)

    async def list_cancer_types(
        self, query: str | None, parent: str | None, limit: int, offset: int
    ) -> dict[str, Any]:
        """cBioPortal cancer types (lowercase OncoTree codes) by name and/or parent."""
        page_args(limit, offset)
        types = await self._cancer_types()
        if parent is not None:
            codes = await self._descendants(parent)
            types = [t for t in types if t.get("cancerTypeId") in codes - {parent.lower()}]
        if query is not None:
            term = query.strip().casefold()
            types = [
                t
                for t in types
                if term in str(t.get("name") or "").casefold()
                or term == str(t.get("cancerTypeId") or "").casefold()
            ]
        types.sort(key=lambda t: str(t.get("cancerTypeId")))
        rows = [
            {"code": t.get("cancerTypeId"), "name": t.get("name"), "parent": t.get("parent")}
            for t in types[offset : offset + limit]
        ]
        payload = {
            "cancer_types": rows,
            **page_block(total=len(types), returned=len(rows), limit=limit, offset=offset),
        }
        return await self._stamp(payload)

    async def get_mutation_hotspots(
        self, gene: str, residue: str | None, assembly_name: str, mode: str = "compact"
    ) -> dict[str, Any]:
        """Cancer Hotspots calls for a gene, or whether one residue is a hotspot."""
        position = hotspots.check_args(residue, assembly_name)
        resolved = await self._gene(gene)
        payload = hotspots.answer(resolved["symbol"], residue, position, assembly_name, mode)
        if "resolved_from" in resolved:
            payload["resolved_from"] = resolved["resolved_from"]
        payload["retrieved_at"] = _now()
        return payload
