"""Bundled Cancer Hotspots snapshot (ODbL 1.0): v2 single-residue/indel/splice + 3D hotspots.

Built by ``scripts/build_hotspots.py`` from a pinned, sha256-verified Genome Nexus importer
file; nothing is fetched at runtime. Residue numbering follows each build's transcript
(``transcript`` column), so the GRCh37 and GRCh38 tables can differ for a few genes.
"""

from __future__ import annotations

import csv
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

from cbioportal_link.exceptions import InvalidInputError

DATA = Path(__file__).parent / "data"
ASSEMBLIES = ("GRCh38", "GRCh37")
#: ``V600``, ``V600E``, ``p.R175H``, ``600``, ``X327_splice`` -> the residue position.
NOTE = (
    "is_hotspot: this change (or residue, if no change given) is a statistically recurrent "
    "somatic hotspot in the snapshot; residue_is_hotspot: its residue is. Not a hotspot does "
    "not mean benign, non-pathogenic or non-oncogenic, and a hotspot is not a clinical "
    "actionability call."
)
_RESIDUE = re.compile(r"^(?:p\.)?[A-Za-z*]?(\d{1,5})(?:[A-Za-z*]+|_splice|fs\*?\d*)?$")


@cache
def provenance() -> dict[str, Any]:
    """Source repo, pinned commit, sha256 and licence of the snapshot."""
    return dict(json.loads((DATA / "hotspots_provenance.json").read_text()))


def data_version() -> str:
    """The snapshot's version stamp."""
    return (
        "Cancer Hotspots v2 + 3D snapshot (genome-nexus-importer@"
        f"{provenance()['source_commit'][:8]})"
    )


def _pairs(raw: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for part in raw.split("|"):
        key, _, value = part.rpartition(":")
        if key and value.isdigit():
            out[key] = int(value)
    return out


def _float(raw: str) -> float | None:
    return float(raw) if raw else None


@cache
def table(assembly: str) -> dict[str, list[dict[str, Any]]]:
    """Hotspot rows of one build, grouped by gene symbol."""
    genes: dict[str, list[dict[str, Any]]] = {}
    with (DATA / f"hotspots_{assembly.lower()}.txt").open(newline="") as fh:
        for raw in csv.DictReader(fh, delimiter="\t"):
            row: dict[str, Any] = {
                "residue": raw["residue"],
                "type": raw["type"],
                "start": int(raw["start"]),
                "end": int(raw["end"]),
                "tumor_count": int(raw["tumor_count"]),
                "q_value": _float(raw["q_value"]),
                "variants": _pairs(raw["variants"]),
                "tumor_types": _pairs(raw["tumor_types"]),
                "transcript": raw["transcript"],
            }
            if raw["type"] == "3d":  # 3D calls carry a structural p-value, not a q-value
                row["p_value"] = _float(raw["p_value"])
                row["clusters"] = int(raw["clusters"])
                del row["q_value"]
            genes.setdefault(raw["gene"], []).append(row)
    return genes


def residue_position(value: str) -> int | None:
    """The protein position in a residue or protein change, else ``None``."""
    match = _RESIDUE.match(value.strip())
    return int(match.group(1)) if match else None


def variant_letter(value: str) -> str | None:
    """The alternate amino acid of a protein change (``V600E`` -> ``E``), if any."""
    match = re.match(r"^(?:p\.)?[A-Za-z*]\d+([A-Za-z*])$", value.strip())
    return match.group(1).upper() if match else None


def lookup(gene: str, assembly: str, position: int | None) -> list[dict[str, Any]]:
    """Rows for a gene, optionally only those covering one residue position."""
    rows = table(assembly).get(gene, [])
    if position is None:
        return list(rows)
    return [r for r in rows if r["start"] <= position <= r["end"]]


def check_args(residue: str | None, assembly: str) -> int | None:
    """Validate the call before any lookup; return the residue position (or ``None``)."""
    if assembly not in ASSEMBLIES:
        raise InvalidInputError(
            "`assembly` must be GRCh38 or GRCh37.",
            field="assembly",
            allowed_values=list(ASSEMBLIES),
        )
    if residue is None:
        return None
    position = residue_position(residue)
    if position is None:
        raise InvalidInputError(
            "`residue` must be a residue or protein change like V600, V600E or R175H.",
            field="residue",
        )
    return position


def answer(gene: str, residue: str | None, position: int | None, assembly: str) -> dict[str, Any]:
    """The get_mutation_hotspots payload for a resolved gene symbol."""
    rows = lookup(gene, assembly, position)
    payload: dict[str, Any] = {
        "gene": gene,
        "assembly": assembly,
        "hotspots": rows,
        "total": len(rows),
    }
    if residue is not None:
        payload["residue"] = residue.strip()
        payload["residue_is_hotspot"] = payload["is_hotspot"] = bool(rows)
        letter = variant_letter(residue)
        if letter is not None:
            count = max((r["variants"].get(letter, 0) for r in rows), default=0)
            payload["variant_tumor_count"] = count
            # A change never seen at a hotspot residue is not itself a hotspot change.
            payload["is_hotspot"] = count > 0
        payload["note"] = NOTE
    prov = provenance()
    payload["source"] = {
        "licence": prov["license"],
        "attribution": prov["attribution"],
        "commit": prov["source_commit"],
    }
    payload["data_version"] = data_version()
    return payload
