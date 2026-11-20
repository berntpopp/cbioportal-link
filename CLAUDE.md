# CLAUDE.md

**Read [AGENTS.md](AGENTS.md) first** — it is the authoritative contributor and agent guide.

Essentials:

- Read-only MCP server over the public cBioPortal web API (`api.cbioportal.org`) plus a
  bundled Cancer Hotspots snapshot. Follow cBioPortal's llms.txt: filtered, sequential, cached.
- Data plane returns plain dicts and raises typed errors; `run_mcp_tool` owns the envelope.
- Frequencies are altered / profiled samples per study; never sum studies; licence + citation
  on every row; NC/ND studies excluded unless `include_restricted`.
- Never expose molecular-data, segments, clinical data or sample/patient IDs.
- FastMCP 4.x is post-training-cutoff: verify symbols against this repo's `.venv`.
- Gate: `make ci-local` (serialize it on shared machines). Never `gh release create`.
