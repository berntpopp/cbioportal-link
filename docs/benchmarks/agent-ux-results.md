# Agent UX evaluation results (2026-11-20)

Method: [`agent-ux-protocol.md`](agent-ux-protocol.md). Build under test: v0.1.0 plus the fixes
below, against live cBioPortal v7.2.3 (database 3.1.0) and the bundled Cancer Hotspots v2 + 3D
snapshot (genome-nexus-importer@4c2d0525). Agents: Claude Code 2.1.329 (`claude-opus-5-5`),
Codex CLI 0.164.0 (`gpt-6-astra`, reasoning high, from its config), Antigravity `agy` 1.5.13.
Raw traces are machine-local and are not committed.

## Minimum rating per category (0-100, over all rated sessions of the round)

| Round | sessions | discov | schema | correct | complete | error | speed | tokens | provenance | overall |
|------:|------|------:|------:|------:|------:|------:|------:|------:|------:|------:|
| 1 (v0.1.0) | 6 (A, B x 3 agents) | 85 | 82 | 85 | 65 | 72 | 92 | 72 | 89 | 82 |
| 2 | 6 of 9 rated (A, B, C x 3; Codex out of quota) | 85 | 85 | 82 | 72 | 78 | 85 | 75 | 93 | 84 |
| 3 | 6 (A, B, C x Claude, agy) | 88 | 85 | 85 | 60 | 80 | 78 | 75 | 88 | 84 |
| 4 | 6 (A, B, C x Claude, agy) | 88 | 85 | 85 | 72 | 80 | 80 | 75 | 90 | 85 |
| 5 (final) | 6 (A, B, C x Claude, agy) | 85 | 86 | 88 | 78 | 82 | 80 | 78 | 90 | 86 |

Error recovery in brackets (not exercised) is left out, as the protocol says: Claude A in
every round made no failing call.

**Agents.** Codex ran in round 1 only. In round 2 all three Codex sessions failed with "You've
hit your usage limit ... try again at 9:18 PM" (kept, unrated). Rounds 3-5 ran Claude and agy
only: rounds 3-4 because the limit had not reset, round 5 by owner decision (Codex excluded
because of the usage limit, not waited for). Round 5's minimums are over Claude and agy only and
may be higher than a three-agent round would give. Codex's round-1 sessions rated every
category >= 72 (token efficiency 72, error recovery 72).

**The held-out prompt was not held out.** `C-fresh.md` was frozen before round 1 (unchanged,
sha256-checked every round), but it ran from round 2 on, not only in the final round as the
protocol says. Fixes after round 2 could see C friction: the close-match study ID recovery
(`lgg_tcga_pan_can_atlas_2019` -> `_2018`) answers C5 directly. C therefore tests that the
fixes hold, not that they generalise to unseen wording.

## Answer audit

Every answer of every round was checked against a private answer key verified live before
round 1. No wrong fact caused by the server in any round. Round 5, all six sessions:

- A: KRAS G12C in luad, 3 largest of 17 studies (344/2653, 104/915, 96/604), not summed;
  TCGA LUAD 70/566, chr12:25398285 C>A GRCh37; G12 hotspot 2175 tumours, G12C 384; BRAF in
  TCGA SKCM 233/440 (8 not profiled), V600E 158/440, V600E 833; ODbL-1.0, PMID 29625048;
  cBioPortal v7.2.3 / database 3.1.0, hotspots @4c2d0525.
- B: `msk_chord_2024` refused until `include_restricted=true`, then 1114/25040 with its
  CC BY-NC-ND terms and the mixed-cohort caveat; the pan-cancer default named as
  `msk_impact_2017` (4538/10945); BRAF 600's 9070 records read as records, not a patient
  share; every bad input got the right error and field; TP53 P72R "not a hotspot" read as
  "not benign"; 17 LUAD studies in 4 pages, last `luad_mskcc_2015`; patient rows and
  treatment advice refused.
- C: PIK3CA H1047R in brca (522/3879, 424/2433, 129/1066), H1047 647 / H1047R 537; difg and
  its 23 subtypes; IDH1 R132H 358/514, chr2:209113112 C>T GRCh37; TCGA default caveat;
  EGFR L858Q `residue_is_hotspot` true but `is_hotspot` false and not "benign"; the guessed
  study ID recovered in one call; vorasidenib advice refused.

The v0.1.0 defect the key exposed before round 1 (EGFR L858Q reported `is_hotspot: true` with
0 tumours) was fixed before round 1 and never reached an agent.

## Fixes, by round

Before round 1 (from the answer key): `is_hotspot` for a change means that change was seen at
a hotspot residue; `residue_is_hotspot` keeps the residue call; a `note` says not a hotspot is
not benign.

After round 1:

- A licence-blocked study suggests the same call with `include_restricted=true`; `study_ids` +
  `cancer_type` suggests each one alone (all three B sessions had only "see capabilities").
- Three-letter protein changes (`p.Gly12Cys`, `Arg175His`) are converted, not rejected.
- The unknown-gene hint says `hgnc_resolve_symbol` is a genefoundry router tool.
- A study's PMID list is de-duplicated; a substitution query (V600E) no longer returns the
  592-604 in-frame-indel region; capabilities point not-exposed data at the study page.

After round 2:

- An unknown study ID returns close `candidates` with `get_study` next steps.
- `search_studies` matches words in any order (`_` separates words).
- Frequency rows carry `assembly`; the no-filter default (`msk_impact_2017`) adds a top-level
  `warning`; the cohort note says the denominator is the whole study.
- `get_mutation_hotspots(response_mode=)`: `compact` (default) drops the per-tumour-type maps.
- `get_diagnostics` says its counters are process-wide.

After round 3: `get_study` carries `not_exposed`; the per-call cohort note is cut to ~170
characters.

After round 4: rows carry the primary `pmid` plus `more_pmids` (the 11-PMID TCGA string was on
every row); `get_study` lists every PMID and its molecular profiles as IDs. Review fix: an
unknown three-letter code (`Gly12Xyz`) is `invalid_input`, not a silent zero.

After round 5 (not re-evaluated; the round cap was reached):

- Self-review fix: mixed notation (`G12Cys`, `L858Gln`) is converted. Before, `L858Gln` gave
  the frequency tool `L858GLN` (a silent zero) and the hotspot tool a residue-only query
  (`is_hotspot: true` for an unseen change); an unknown code in a hotspot residue is rejected.
- `list_cancer_types(query="lung adenocarcinoma")` lists `luad` before `lais` (agy A: the
  first `next_commands` pointed at `lais`).
- `get_study`'s suggested frequency call for a restricted study carries
  `include_restricted=true` (agy B: followed as given, it failed on the licence gate); the
  Ensembl-ID gene error carries the same router-tool hint as the unknown-symbol error.
- The tool description says `variant_tumor_count` is the change's largest count over the
  calls (Claude A, agy A, round-4 Claude C could not tell single_residue from 3d).

One round-5 friction item is an artefact of the run, not a defect: agy B saw different
`git_sha` values in `get_server_capabilities` and `get_diagnostics`, because a commit landed in
the checkout mid-round and a source checkout reads `.git` at call time. Containers take the sha
from the build environment.

## Gate: not reached after the 5-round cap

Two categories stay below 80 in round 5, both from one Claude session each (agy rates every
category >= 86):

- **Completeness 78** (Claude B; A 86, C 82). The reasons Claude gives are outside what this
  server should change: patient-level clinical rows and copy-number segments are never exposed
  by design (owner scope; `not_exposed` points at the study page); Ensembl -> symbol mapping
  belongs to hgnc-link behind the router, and Response-Envelope §2b accepts an actionable
  `invalid_input`; `citation: null` on four LUAD studies is upstream metadata. Claude B's
  completeness rose 65 -> 72 -> 60 -> 72 -> 78 over the rounds; round 3's 60 is the same
  by-design refusal read as missing coverage.
- **Token efficiency 78** (Claude C; A 82, B 80). Claude names the per-response `_meta`
  (`next_commands`, `unsafe_for_clinical_use`) and the licence / attribution block on every
  hotspot answer. `_meta` is the fleet Response-Envelope standard and per-answer attribution is
  the ODbL / study-licence requirement, so the remaining bulk is standard-bound. What the server
  controlled is fixed: one PMID per row instead of 11, profile IDs instead of objects, hotspot
  tumour-type maps only in `standard`.

Speed (80, Claude C) is at the gate: the slowest calls are the first upstream fetches of a
cancer type's studies (brca, 7.1-7.6 s) under the polite sequential client (0.5 s spacing),
which cBioPortal's `llms.txt` asks for; cached calls answer in 0-2 ms.

`make ci-local` and the live conformance probes (transport, behaviour, foreign identifiers)
were green on the round-5 build and again on the final build.
