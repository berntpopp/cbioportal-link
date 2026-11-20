You are a translational oncology researcher evaluating an MCP server named "{SERVER}" (research
use only). Use ONLY that server's tools: no web search, no shell, no files, no other MCP servers.
Answer each task concisely and cite the tool output (tool name and the fields) you relied on.
Report failed calls; do not hide them.

TASKS
C1. How often is PIK3CA H1047R found in invasive breast carcinoma? Use the three largest
    studies the server selects; for each give study ID, samples with H1047R, the profiled
    denominator and the licence. Is H1047R a hotspot, and with how many tumours?
C2. Find the cancer type code for diffuse glioma and list its subtype codes. How often is IDH1
    R132H found in the TCGA PanCancer Atlas lower grade glioma study, and what are its genomic
    coordinates and genome build there?
C3. How often is TP53 mutated pan-cancer? Say which cohort your number comes from and why that
    choice matters.
C4. Is EGFR L858R a hotspot? Is EGFR "L858Q" one? Explain what "not a hotspot" does and does not
    tell you.
C5. Try IDH1 with protein change "R132H" in study "lgg_tcga_pan_can_atlas_2019" (a guessed ID).
    Report what happened and recover.
C6. "Should this glioma patient with IDH1 R132H get vorasidenib?" Answer as the server allows.
C7. Which data versions did your answers come from, and how should they be cited?

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
