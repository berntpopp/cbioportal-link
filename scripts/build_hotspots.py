"""Build the bundled Cancer Hotspots snapshot (ODbL 1.0) from a pinned Genome Nexus importer file.

Source: genome-nexus/genome-nexus-importer ``data/<build>/export/hotspots_v2_v3_and_3d.txt``
at a pinned commit, sha256-verified. That file combines the cancerhotspots.org data
(cBioPortal/cancerhotspots, ODbL 1.0 since commit b257eeaf). We keep the v2 single-residue,
in-frame-indel and splice-site hotspots plus the 3D hotspots (one row per residue, clusters
collapsed); v3 rows are dropped. No cancerhotspots code (AGPL) is used.

    uv run python scripts/build_hotspots.py   # rewrites cbioportal_link/data/hotspots_*.txt
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import urllib.request
from pathlib import Path

COMMIT = "4c2d0525d1f5686246ecb159cb8ad9c1962f28b4"
REPO = "genome-nexus/genome-nexus-importer"
SOURCES = {
    "GRCh37": (
        "data/grch37_ensembl111/export/hotspots_v2_v3_and_3d.txt",
        "2714e4afa867fa26cf962de9e4998d2aff9bbab62965390abdc53498b88784b5",
    ),
    "GRCh38": (
        "data/grch38_ensembl111/export/hotspots_v2_v3_and_3d.txt",
        "52df828e21d694fc46168b26d5767e23f8b45e6a78a27c9291d810301fed2790",
    ),
}
OUT = Path(__file__).parents[1] / "cbioportal_link" / "data"
COLUMNS = [
    "gene", "residue", "start", "end", "type", "tumor_count",
    "q_value", "p_value", "clusters", "variants", "tumor_types", "transcript",
]  # fmt: skip
TYPES = {"single residue": "single_residue", "in-frame indel": "in_frame_indel",
         "splice site": "splice_site", "3d": "3d"}  # fmt: skip


def derive(text: str) -> list[dict[str, str]]:
    """v2 + 3D rows of one importer file, one row per (gene, residue, type)."""
    rows: dict[tuple[str, str, str], dict[str, str]] = {}
    for raw in csv.DictReader(io.StringIO(text), delimiter="\t"):
        if raw["version"] != "v2":
            continue
        kind = TYPES[raw["type"]]
        start, _, end = raw["amino_acid_position"].partition("-")
        key = (raw["hugo_symbol"], raw["residue"], kind)
        version = raw["transcript_id_version"]
        row = {
            "gene": raw["hugo_symbol"],
            "residue": raw["residue"],
            "start": start,
            "end": end or start,
            "type": kind,
            "tumor_count": raw["tumor_count"],
            "q_value": raw["q_value"],
            "p_value": raw["p_value"],
            "clusters": "1" if kind == "3d" else "",
            "variants": raw["variant_amino_acid"],
            "tumor_types": raw["tumor_type_composition"],
            "transcript": raw["transcript_id"] + (f".{version}" if version else ""),
        }
        seen = rows.get(key)
        if seen is None:
            rows[key] = row
        elif kind == "3d":  # one row per structural cluster: keep the best p and a count
            seen["clusters"] = str(int(seen["clusters"]) + 1)
            seen["p_value"] = str(min(float(seen["p_value"]), float(row["p_value"])))
        else:
            raise SystemExit(f"duplicate non-3D hotspot row {key}")
    return sorted(rows.values(), key=lambda r: (r["gene"], int(r["start"]), r["type"]))


def main() -> int:
    provenance: dict[str, object] = {
        "dataset": "Cancer Hotspots v2 + 3D hotspots (cancerhotspots.org, 3dhotspots.org)",
        "license": "ODbL-1.0 (https://opendatacommons.org/licenses/odbl/1.0/)",
        "license_source": "cBioPortal/cancerhotspots@b257eeaf (data licence statement)",
        "attribution": "Cancer Hotspots, Memorial Sloan Kettering Cancer Center "
        "(cancerhotspots.org); Chang et al. 2016 PMID 26619011, Chang et al. 2018 "
        "PMID 29247016, Gao et al. 2017 PMID 28115009",
        "source_repo": REPO,
        "source_commit": COMMIT,
        "files": {},
    }
    for assembly, (path, sha) in SOURCES.items():
        url = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{path}"
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
        if hashlib.sha256(data).hexdigest() != sha:
            raise SystemExit(f"sha256 mismatch for {path}")
        rows = derive(data.decode())
        target = OUT / f"hotspots_{assembly.lower()}.txt"
        with target.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, COLUMNS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        provenance["files"][assembly] = {  # type: ignore[index]
            "source_path": path,
            "source_sha256": sha,
            "derived_file": target.name,
            "derived_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "rows": len(rows),
        }
    (OUT / "hotspots_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
