# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-20

### Added

- Read-only MCP server over the public cBioPortal web API (`api.cbioportal.org`) plus a
  bundled Cancer Hotspots v2 + 3D snapshot (ODbL 1.0).
- Tools: `get_gene_alteration_frequency` (entry point), `search_studies`, `get_study`,
  `get_gene_mutations`, `get_mutation_position_counts`, `list_cancer_types`,
  `get_mutation_hotspots`, `get_server_capabilities`, `get_diagnostics`.
- cBioPortal llms.txt policy: filtered requests only, one request in flight, 0.5 s spacing,
  cache keyed on `/api/info` `dbVersion`, exponential backoff on 429 honouring `Retry-After`,
  at most 10 studies per call; 16 MiB decoded-byte cap and a single-origin URL guard.
- Frequencies are samples altered / samples profiled for the gene (panel-aware), per study,
  with cohort, licence, citation and import date on every row; NC/ND studies are excluded
  unless `include_restricted=true` and stay flagged.
- `scripts/build_hotspots.py` rebuilds the hotspot tables from a pinned, sha256-verified
  genome-nexus-importer commit.
