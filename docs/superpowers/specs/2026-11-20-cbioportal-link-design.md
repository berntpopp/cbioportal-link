# cbioportal-link design (2026-11-20)

> Historical record — design as of 2026-11-20; the live tool catalog and README are authoritative.

Source of truth for scope: genefoundry-router
`docs/plans/2026-11-20-cancer-somatic-expansion.md` (§2 cBioPortal + Cancer Hotspots rows,
§3 item 5, §4 DoD) and evidence reports C and F in the same directory.

## Goal

A read-only fleet backend (namespace `cbioportal`) answering **somatic prevalence by cancer
type** with honest denominators, plus a bundled **Cancer Hotspots** lookup. Research use only;
not a clinical actionability report.

## Upstream and policy

- Live proxy of `https://api.cbioportal.org` (the scripted-access host named in
  `cbioportal.org/llms.txt`). Outbound allowlist = that one origin (URL guard on every hop,
  ≤ 5 redirects, 16 MiB decoded cap, fail closed).
- llms.txt policy: filtered requests only; **sequential** (an `asyncio.Lock` keeps one request
  in flight process-wide, plus a 0.5 s spacing limiter and a daily cap); in-process cache keyed
  on `/api/info` `dbVersion` (24 h TTL; `/api/info` itself 1 h); exponential backoff on
  429/5xx honouring `Retry-After`; no tool loops the API for bulk data (study fan-out capped at
  10 studies, default 3).
- Never called: `molecular-data`, `copy-number-segments`, `clinical-data`, unfiltered
  `mutated-genes/fetch` (4.7 MB). Mutation answers are aggregated per variant; no sample or
  patient IDs leave the server.
- `alteration-counts/fetch` is 404 in the Go rewrite. Frequencies use
  `mutation-data-counts/fetch` (gene-filtered, panel-aware: MUTATED / NOT_MUTATED /
  NOT_PROFILED) and `genomic-data-counts/fetch` (discrete CNA). A live integration test pins
  both, and a drift alarm fails if `alteration-counts/fetch` comes back.

## Tools (Tool-Naming v1.1)

| Tool | Upstream |
|---|---|
| `search_studies` | `GET /api/studies?projection=DETAILED` (one cached list, filtered locally) |
| `get_study` | cached list + `GET /api/studies/{id}/molecular-profiles` |
| `get_gene_alteration_frequency` (entry point) | `mutation-data-counts/fetch`, `genomic-data-counts/fetch`, gene mutations (protein change) |
| `get_gene_mutations` | `GET /api/molecular-profiles/{p}/mutations?entrezGeneId=` aggregated per variant |
| `get_mutation_position_counts` | `POST /api/mutation-counts-by-position/fetch` (portal-wide, no denominator) |
| `list_cancer_types` | `GET /api/cancer-types` (OncoTree-derived codes) |
| `get_mutation_hotspots` | bundled snapshot (no runtime fetch) |

Plus the fleet `get_server_capabilities` and `get_diagnostics`.

## Licences and honesty

- Every study row carries `licence`, `restricted`, `citation`, `pmid`, `import_date`.
  Licence = CC code parsed from the study description, else `ODbL-1.0` (cBioPortal default).
  NC/ND studies (e.g. `msk_chord_2024`, CC BY-NC-ND 4.0) are excluded by default;
  `include_restricted=true` opts in and they stay flagged.
- Frequencies state numerator, denominator (samples profiled for the gene) and cohort, per
  study; overlapping studies are never summed.
- Coordinates carry `assembly` from the study's `referenceGenome` (hg19 → GRCh37).
- `data_version` = `/api/info` portal version + database version; each row has `import_date`.

## Cancer Hotspots snapshot

`scripts/build_hotspots.py` downloads `hotspots_v2_v3_and_3d.txt` (GRCh37 + GRCh38 builds) from
`genome-nexus/genome-nexus-importer@4c2d0525`, verifies sha256, keeps v2 single-residue /
in-frame-indel / splice-site hotspots and 3D hotspots (clusters collapsed per residue), and
writes `cbioportal_link/data/hotspots_{grch37,grch38}.tsv` + `hotspots_provenance.json`.
Data ODbL 1.0 (cancerhotspots.org; `cBioPortal/cancerhotspots@b257eeaf`); no AGPL code is
used. Acceptance: BRAF V600 tumour count 897; TP53 R175H is a hotspot.
