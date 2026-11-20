# cbioportal-link implementation plan (2026-11-20)

> Historical record — plan as executed on 2026-11-20 for v0.1.0; see the design spec in
> `docs/superpowers/specs/2026-11-20-cbioportal-link-design.md`.

1. Scaffold from `pgscatalog-link` (rename package/namespace, keep docker/, conformance,
   scripts/, Makefile, workflows, container-release.json, skills); vendor `docs/conformance/`
   from the router's main (adds `identifiers.py`), add `identifiers.local.json`.
2. Client: POST + JSON arrays, one request in flight (`asyncio.Lock`), cache keyed on
   `/api/info` `dbVersion`, 404 → `not_found`. Tests: sequential, dbVersion invalidation,
   exponential backoff, Retry-After, URL guard.
3. Record live fixtures (`tests/fixtures/cbio/`, trimmed mutation records).
4. Service + shaping: studies (licence parse, restricted exclusion), cancer-type subtree,
   per-study frequency via `mutation-data-counts` / `genomic-data-counts`, protein change from
   gene mutations, aggregated variants without sample IDs, position counts, cancer types.
5. Hotspots: `scripts/build_hotspots.py` (pinned commit, sha256) → bundled TSVs; lookup tool.
6. Tools, capabilities, README/NOTICE/AGENTS, deploy docs, CHANGELOG 0.1.0.
7. Live integration tests + weekly drift-alarm workflow (`alteration-counts/fetch` still 404).
