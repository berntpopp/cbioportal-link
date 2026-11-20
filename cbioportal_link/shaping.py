"""Pure shapers: turn native cBioPortal records into compact, honest payload rows.

Identifiers, counts and controlled vocabularies pass through verbatim. Study descriptions
(free text written by the data submitters) are fenced as ``untrusted_text``. Every study row
carries its licence and citation: cBioPortal data default to ODbL 1.0, but some studies set
their own terms in the description (e.g. CC BY-NC-ND 4.0), which only exist as free text.
"""

from __future__ import annotations

import re
from typing import Any

from cbioportal_link.exceptions import InvalidInputError, UpstreamSchemaError
from cbioportal_link.mcp.untrusted_content import fence_untrusted_text

SITE = "https://www.cbioportal.org"
DEFAULT_LICENCE = "ODbL-1.0"
#: Licence statements as cBioPortal writes them: a creativecommons.org link or prose.
_CC_URL = re.compile(r"creativecommons\.org/licenses/([a-z-]+)/(\d\.\d)", re.I)
_CC_TEXT = re.compile(r"creative\s+commons\s+(BY(?:-(?:NC|ND|SA))*)\s+(\d\.\d)", re.I)
_NONCOMMERCIAL = re.compile(r"non-?commercial|for commercial use", re.I)
ASSEMBLY = {"hg19": "GRCh37", "hg38": "GRCh38"}

MAX_LIMIT = 100

#: Fleet response_mode canon (Response-Envelope Standard v1 §3); compact is the default.
RESPONSE_MODES = ("minimal", "compact", "standard", "full")


def fence(raw: Any, record_id: str) -> dict[str, Any] | None:
    """Fence one upstream prose value (``None``/empty stays ``None``)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    return fence_untrusted_text(raw, source="cbioportal", record_id=record_id).model_dump(
        mode="json"
    )


def page_block(*, total: int, returned: int, limit: int, offset: int) -> dict[str, Any]:
    """Uniform pagination block; ``total`` is the exact upstream/derived count."""
    truncated = offset + returned < total
    return {
        "total": total,
        "returned": returned,
        "limit": limit,
        "offset": offset,
        "truncated": truncated,
        "next_offset": offset + returned if truncated else None,
    }


def licence(description: Any) -> tuple[str, bool]:
    """``(licence, restricted)`` read from a study description; ODbL-1.0 when none is stated.

    Restricted = a non-commercial (NC) or no-derivatives (ND) term, or prose that reserves
    commercial use.
    """
    text = description if isinstance(description, str) else ""
    match = _CC_URL.search(text) or _CC_TEXT.search(text)
    if match:
        code = f"CC-{match.group(1).upper()}-{match.group(2)}"
        return code, bool(re.search(r"-(NC|ND)\b", code))
    if _NONCOMMERCIAL.search(text):
        return "see study description (commercial use restricted)", True
    return DEFAULT_LICENCE, False


def assembly(raw: dict[str, Any]) -> str:
    """Genome assembly of a study's coordinates (cBioPortal ``referenceGenome``)."""
    ref = str(raw.get("referenceGenome") or "")
    return ASSEMBLY.get(ref.lower(), ref or "unknown")


def study_ref(raw: dict[str, Any]) -> dict[str, Any]:
    """The per-row provenance every answer carries: who, licence, citation, import date."""
    code, restricted = licence(raw.get("description"))
    return {
        "study_id": raw.get("studyId"),
        "name": raw.get("name"),
        "licence": code,
        "restricted": restricted,
        "citation": raw.get("citation"),
        "pmid": raw.get("pmid"),
        "import_date": str(raw.get("importDate") or "")[:10] or None,
    }


def study_row(raw: dict[str, Any], mode: str = "compact") -> dict[str, Any]:
    """A search_studies row at one response_mode."""
    row = study_ref(raw)
    if mode == "minimal":
        return {k: row[k] for k in ("study_id", "name", "licence", "restricted", "citation")}
    row.update(
        {
            "cancer_type": raw.get("cancerTypeId"),
            "samples": raw.get("allSampleCount"),
            "sequenced_samples": raw.get("sequencedSampleCount"),
            "cna_samples": raw.get("cnaSampleCount"),
            "assembly": assembly(raw),
        }
    )
    if mode in ("standard", "full"):
        row["url"] = f"{SITE}/study/summary?id={raw.get('studyId')}"
    if mode == "full":
        row["description"] = fence(raw.get("description"), str(raw.get("studyId")))
    return row


def mutation_variant(raw: dict[str, Any]) -> tuple[Any, ...]:
    """Identity of one somatic variant (no sample or patient identifiers)."""
    return (
        raw.get("proteinChange"),
        raw.get("mutationType"),
        raw.get("chr"),
        raw.get("startPosition"),
        raw.get("endPosition"),
        raw.get("referenceAllele"),
        raw.get("variantAllele"),
    )


def variant_row(raw: dict[str, Any], samples: int, mode: str) -> dict[str, Any]:
    """One aggregated variant at one response_mode."""
    row: dict[str, Any] = {"protein_change": raw.get("proteinChange"), "samples": samples}
    if mode == "minimal":
        return row
    row.update(
        {
            "mutation_type": raw.get("mutationType"),
            "chr": raw.get("chr"),
            "start": raw.get("startPosition"),
            "end": raw.get("endPosition"),
            "ref": raw.get("referenceAllele"),
            "alt": raw.get("variantAllele"),
        }
    )
    if mode in ("standard", "full"):
        row.update(
            {
                "variant_type": raw.get("variantType"),
                "refseq_mrna_id": raw.get("refseqMrnaId"),
                "protein_position": raw.get("proteinPosStart"),
                "keyword": raw.get("keyword"),
            }
        )
    return row


def ratio(numerator: int, denominator: int) -> float | None:
    """A frequency rounded to 4 places; ``None`` when nothing was profiled."""
    return round(numerator / denominator, 4) if denominator else None


_AA3 = dict(  # three-letter amino-acid code -> one letter
    zip(
        re.findall("...", "alaargasnaspcysglngluglyhisileleulysmetpheproserthrtrptyrvalter"),
        "ARNDCQEGHILKMFPSTWYV*",
        strict=True,
    )
)
_THREE_LETTER = re.compile(r"^(?:p\.)?([A-Za-z]{3})(\d{1,5})([A-Za-z]{3}|\*)?$")


def one_letter(value: str) -> str:
    """``p.Gly12Cys`` -> ``G12C``; anything else is returned stripped, unchanged."""
    text = value.strip()
    m = _THREE_LETTER.match(text)
    if not m:
        return text
    ref, pos, alt = m.groups()
    ref1 = _AA3.get(ref.lower())
    if ref1 is None or (alt and alt != "*" and alt.lower() not in _AA3):
        return text
    return f"{ref1}{pos}{_AA3.get(alt.lower(), '*') if alt else ''}"


def normalize_protein_change(value: str) -> str:
    """``p.G12C`` / ``g12c`` / ``p.Gly12Cys`` -> ``G12C`` (cBioPortal's one-letter form)."""
    text = one_letter(value)
    if text[:2].lower() == "p.":
        text = text[2:]
    return text.upper()


def page_args(limit: int, offset: int) -> None:
    """Validate a page request against ``MAX_LIMIT``."""
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInputError(f"`limit` must be 1-{MAX_LIMIT}.", field="limit")
    if offset < 0:
        raise InvalidInputError("`offset` must be >= 0.", field="offset")


def rows_of(raw: Any, field: str) -> list[dict[str, Any]]:
    """The object rows of an upstream JSON array, or a schema error naming ``field``."""
    if not isinstance(raw, list):
        raise UpstreamSchemaError("cBioPortal returned an unexpected body.", field=field)
    return [r for r in raw if isinstance(r, dict)]
