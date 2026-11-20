# Agent UX evaluation protocol

How we test cbioportal-link the way it is used: real agent CLIs, each with only this MCP server
mounted, doing realistic and adversarial somatic cancer genomics work, then rating the
experience. It adapts the pgscatalog-link protocol (`docs/benchmarks/agent-ux-protocol.md` in
that repo) to cBioPortal and the Cancer Hotspots snapshot.

## Agents

Each prompt runs once per agent per round against one local server. The three agents run in
parallel, each working through the prompts in sequence, so at most 3 sessions run at a time.
Each session also holds a slot of a fleet-wide session semaphore (`SLOT=<wrapper>`), and its
wall clock starts only once the slot is held, so queueing does not count as speed.

| Agent | Invocation (see `scripts/agent_ux_session.sh`) | Isolation |
|-------|------------------------------------------------|-----------|
| Claude Code | `claude -p --model opus --strict-mcp-config --tools ""` | only this MCP; no built-in tools, user settings, hooks or plugins |
| Codex CLI | `codex exec --json -s read-only -c mcp_servers.<name>.url=...` | read-only sandbox, empty working directory |
| Antigravity (`agy`) | `agy -p` with the server added through `agy mcp add eval-cbioportal-link` | empty working directory; other user MCP servers stay mounted, the prompt forbids them |

Record the model each client actually resolved (Claude's `init` event, Codex's config). Never
substitute a model silently. Keep every session, including failed or timed-out ones.

## Upstream politeness

All sessions share one server, and so its strictly sequential cBioPortal client (0.5 s spacing)
and its cache. Never raise concurrency or lower the spacing to make a round faster: cBioPortal's
`llms.txt` asks scripts and agents for small, sequential, cached requests. Speed ratings are
taken under that contention; single-call latency is reported next to them.

## Tasks

Prompts live in `tasks/` and are frozen before a round. `{SERVER}` is replaced by the mounted
name.

- `A-researcher.md`: the somatic prevalence workflow. OncoTree code for lung adenocarcinoma,
  default study selection, numerator / profiled denominator / cohort / study ID, why rows must
  not be summed, genomic coordinates with their build (GRCh37), hotspot status and counts,
  BRAF in melanoma, per-study licence and citation, data versions.
- `B-adversarial.md`: a restricted (CC BY-NC-ND) study requested by ID (`msk_chord_2024`), the
  pan-cancer default study when no study or cancer type is given, portal-wide position counts
  over overlapping cohorts, unknown gene / study / cancer-type codes, a foreign gene ID
  (Ensembl) and a three-letter protein change, an over-cap limit, conflicting `study_ids` +
  `cancer_type`, a non-hotspot that must not read as "benign", paging to the end, a request for
  patient-level clinical rows and segment files (never exposed), and a treatment request
  (research use only).
- `C-fresh.md`: written and frozen before the final round and never shown earlier. Different
  genes and tumours (PIK3CA in breast, IDH1 in glioma, TP53 pan-cancer, EGFR hotspots) check
  that fixes generalise instead of fitting the A/B wording.

Agents get no answer key and no score target. A private answer key, verified against the live
API (and the bundled hotspot snapshot) before round 1, is kept with the run artefacts, outside
the repo.

## Ratings

Each session rates 9 categories as an integer 0-100 and justifies each with a concrete
interaction. It also lists its friction points and suggested improvements:

`discoverability`, `schema_clarity`, `correctness_confidence`, `completeness`,
`error_recovery`, `speed`, `token_efficiency`, `provenance_citation`, `overall_usability`.

`scripts/agent_ux_scores.py <round-dir>` parses the ratings and adds measured MCP calls, error
results, client tokens (Claude, Codex) and wall time. A missing rating counts as a failure, not
as 100.

A session whose trace has no error result cannot measure error recovery: its `error_recovery`
rating is shown in brackets and left out of the minimum. agy writes no trace, so its ratings
always count.

## Gate

A round passes when **every category's minimum over all sessions is >= 80**. Averages are never
used, so one bad session cannot be hidden. It must also pass all of:

1. Every answer is audited against the answer key. A wrong fact the server caused (misleading
   field, dishonest count, an empty result read as a negative clinical claim) blocks the round
   whatever the self-ratings say.
2. The final round includes `C-fresh.md`.
3. `make ci-local` and the live conformance probes stay green.

At most five rounds; if the gate is still not met, the blocking categories are reported with
evidence, including those outside the server's control (upstream latency).

## Improvement loop

1. Run the round:
   `SLOT=<semaphore> scripts/agent_ux_eval.sh <out>/round-N` (copy the runner per round first;
   editing a running bash script breaks it).
2. Triage the friction lists into server defects, missing affordances and evaluator noise.
   Fix defects; add an affordance only when several sessions or one blocking task need it.
   Do not tune wording to one prompt.
3. Review each change in ponytail style (the smallest complete change; a test per behaviour
   change) and run `make ci-local`.
4. Restart the server and rerun every prompt. Never drop a low-scoring session or reword a task
   to raise its score.

The rounds and their scores are written up in `agent-ux-results.md`.
