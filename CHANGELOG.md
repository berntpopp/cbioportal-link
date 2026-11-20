# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-11-20

Agent UX evaluation (`docs/benchmarks/`): five rounds with Claude Code and Antigravity (Codex in
rounds 1-2 only; see `agent-ux-results.md`).

### Added

- `get_mutation_hotspots(response_mode=)`: `compact` (default) leaves out the per-tumour-type
  maps, `standard`/`full` keep them. With a residue it also answers `residue_is_hotspot`,
  and a `note` says that "not a hotspot" does not mean benign.
- Three-letter and mixed protein changes (`p.Gly12Cys`, `Arg175His`, `G12Cys`) are converted to
  one-letter form; an unknown code (`Gly12Xyz`) is `invalid_input`, never a silent zero.
- An unknown study ID returns close `candidates` with `get_study` next steps.
- `get_study` returns `pmids` (every PMID) and `not_exposed`; frequency rows carry `assembly`;
  the pan-cancer default (`msk_impact_2017`) adds a top-level `warning`.
- Agent UX protocol, frozen tasks and harness (`scripts/agent_ux_*.{sh,py}`).

### Changed

- `is_hotspot` for a protein change is true only if that change was seen at a hotspot
  residue (EGFR L858Q was reported as a hotspot with 0 tumours). A substitution query no
  longer returns indel or splice regions.
- Study rows carry the primary `pmid` plus `more_pmids` instead of the full comma-joined list;
  `get_study` lists molecular profiles as IDs.
- `search_studies` matches query words in any order (`_` separates words).
- A licence-blocked study suggests the same call with `include_restricted=true`; giving
  both `study_ids` and `cancer_type` suggests each one alone.
- The cohort note is shorter and says the denominator covers the whole study;
  `get_diagnostics` states that its counters are process-wide.
- `list_cancer_types(query=)` lists an exact name or code match first (`luad` before `lais`).
- `get_study`'s suggested frequency call for a restricted study carries
  `include_restricted=true`; an Ensembl / HGNC-ID gene error says `hgnc_resolve_symbol` is a
  router tool. `get_mutation_hotspots` says `variant_tumor_count` is the change's largest count
  over the calls.

## [0.1.0] - 2026-11-20

### Added

- Read-only MCP server over the public cBioPortal web API (`api.cbioportal.org`) plus a
  bundled Cancer Hotspots v2 + 3D snapshot (ODbL 1.0).
- Tools: `get_gene_alteration_frequency` (entry point), `search_studies`, `get_study`,
  `get_gene_mutations`, `get_mutation_position_counts`, `list_cancer_types`,
  `get_mutation_hotspots`, `get_server_capabilities`, `get_diagnostics`.
- cBioPortal llms.txt policy: filtered requests only, one request in flight, 0.5 s spacing,
  cache keyed on `/api/info` `dbVersion`, exponential backoff on 429 honouring `Retry-After`,
  at most 10 studies per call; 8 MiB decoded-byte cap and a 32 MiB byte-budgeted cache and a single-origin URL guard.
- Frequencies are samples altered / samples profiled for the gene (panel-aware), per study,
  with cohort, licence, citation and import date on every row; NC/ND studies are excluded
  unless `include_restricted=true` and stay flagged.
- `scripts/build_hotspots.py` rebuilds the hotspot tables from a pinned, sha256-verified
  genome-nexus-importer commit.
