You are a cancer genomics researcher evaluating an MCP server named "{SERVER}" (research use only).
Use ONLY that server's tools: no web search, no shell, no files, no other MCP servers.
Answer each task concisely and cite the tool output (tool name and the fields) you relied on.

TASKS
A1. Which cancer type code does the server use for lung adenocarcinoma, and what is its parent
    type?
A2. How often is KRAS G12C seen in lung adenocarcinoma? Use the studies the server picks by
    default for that cancer type. For each study give the study ID, the cohort, the number of
    samples with G12C, the denominator and what that denominator counts. Can the rows be added
    up into one overall frequency?
A3. Give the same KRAS G12C numbers for the TCGA PanCancer Atlas lung adenocarcinoma study, and
    the genomic coordinates of the G12C change in that study with their genome build.
A4. Is KRAS G12C a cancer hotspot? Report the hotspot call type(s), the residue's tumour count
    and the count for G12C itself.
A5. In the TCGA PanCancer Atlas melanoma study, what fraction of profiled samples carry any BRAF
    mutation, and what fraction BRAF V600E? Is V600E a hotspot?
A6. For each study you reported in A3 and A5: its licence, citation (with PMID) and import date.
A7. Which data versions did your answers come from (portal/database and hotspot snapshot), and
    how should the sources be cited?

Then output this block exactly, with an integer 0-100 for each category (100 = flawless), each
followed by a one-line justification that cites a concrete interaction:

RATINGS
discoverability=
schema_clarity=
correctness_confidence=
completeness=
error_recovery=
speed=
token_efficiency=
provenance_citation=
overall_usability=
FRICTION: <bullets, most important first>
IMPROVEMENTS: <bullets: concrete changes to the server>
