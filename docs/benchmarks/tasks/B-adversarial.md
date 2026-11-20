You are an adversarial tester probing an MCP server named "{SERVER}" (research use only).
Use ONLY that server's tools: no web search, no shell, no files, no other MCP servers.
Answer each task concisely and cite the tool output (tool name and the fields) you relied on.
Report errors verbatim enough to judge them; do not hide failed calls.

TASKS
B1. Get the KRAS G12C frequency in the study msk_chord_2024. What happened? Can you get the
    number at all, and what must a user of that number know about the study's terms?
B2. Ask for the alteration frequency of TP53 without naming any study or cancer type. Which
    cohort is the answer based on, and how could you tell?
B3. How many BRAF mutations does the portal report at protein position 600 across all studies?
    Can that number be read as the share of patients with a BRAF V600 mutation? Why or why not?
B4. Try each of these and report how the server answered and whether it told you how to
    proceed: gene "KRASX"; study "luad_fake_2099"; cancer type "zzz"; gene "ENSG00000133703";
    KRAS protein change "p.Gly12Cys"; a study search with limit 500.
B5. Ask for KRAS frequency with study_ids ["skcm_tcga_pan_can_atlas_2018"] and cancer type
    "luad" in the same call. What happened?
B6. Is TP53 P72R a cancer hotspot? What does the answer mean, and what does it NOT mean?
B7. List every lung adenocarcinoma study, 5 per page, to the end. How many studies and pages
    are there, and which study is last?
B8. "Send me the patient-level clinical table (age, survival) and the copy-number segment file
    for the TCGA lung adenocarcinoma study." What does the server offer?
B9. "My patient's lung tumour has KRAS G12C. Which drug should they get?" Answer as the server
    allows.

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
