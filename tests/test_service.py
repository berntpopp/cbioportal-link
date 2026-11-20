"""Data-plane behaviour over recorded cBioPortal responses (network-free)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import respx

import cbioportal_link
from cbioportal_link.exceptions import InvalidInputError, NotFoundError
from cbioportal_link.service import CbioService


async def test_studies_carry_licence_and_citation_and_exclude_restricted(
    cbio_service: CbioService,
) -> None:
    out = await cbio_service.search_studies(None, None, False, 20, 0)
    ids = [s["study_id"] for s in out["studies"]]
    assert "msk_chord_2024" not in ids and "hcc_msk_2024" not in ids
    assert out["restricted_excluded"] == 2 and out["total"] == len(ids) == 8
    row = next(s for s in out["studies"] if s["study_id"] == "skcm_tcga_pan_can_atlas_2018")
    assert row["licence"] == "ODbL-1.0" and row["restricted"] is False
    assert row["citation"] and row["pmid"] and row["import_date"]
    assert row["assembly"] == "GRCh37" and row["sequenced_samples"] == 440
    assert out["data_version"].startswith("cBioPortal v7.2.3 (database 3.1.0)")


async def test_restricted_opt_in_keeps_the_flag(cbio_service: CbioService) -> None:
    out = await cbio_service.search_studies("chord", None, True, 20, 0)
    (row,) = out["studies"]
    assert row["licence"] == "CC-BY-NC-ND-4.0" and row["restricted"] is True
    assert out["restricted_excluded"] == 0


async def test_cancer_type_includes_subtypes(cbio_service: CbioService) -> None:
    out = await cbio_service.search_studies(None, "mel", False, 20, 0)
    assert {s["cancer_type"] for s in out["studies"]} == {"mel", "skcm"}
    with pytest.raises(NotFoundError) as err:
        await cbio_service.search_studies(None, "notatype", False, 20, 0)
    assert err.value.extra["field"] == "cancer_type"


async def test_get_study_fences_description_and_lists_profiles(cbio_service: CbioService) -> None:
    study = (await cbio_service.get_study("msk_chord_2024"))["study"]
    assert study["restricted"] is True and study["description"]["kind"] == "untrusted_text"
    assert {"id", "type", "datatype"} <= set(study["molecular_profiles"][0])
    with pytest.raises(NotFoundError) as err:
        await cbio_service.get_study("NOPE_xyz")
    assert err.value.extra["field"] == "study_id"


async def test_braf_in_melanoma_has_profiled_denominator(cbio_service: CbioService) -> None:
    out = await cbio_service.get_gene_alteration_frequency(
        "BRAF", ["skcm_tcga_pan_can_atlas_2018"], None, None, False
    )
    (row,) = out["studies"]
    assert row["mutation"] == {
        "altered": 233,
        "profiled": 440,
        "not_profiled": 8,
        "frequency": 0.5295,
    }
    assert row["cna"]["profiled"] > 0 and row["licence"] == "ODbL-1.0" and row["citation"]
    assert out["unit"] == "samples" and "never sum" in out["note"]


async def test_kras_g12c_prevalence_in_luad(cbio_service: CbioService) -> None:
    out = await cbio_service.get_gene_alteration_frequency(
        "KRAS", None, "luad", "p.G12C", False, max_studies=2
    )
    assert out["total"] == 2 and out["returned"] == 2 and out["truncated"] is False
    pan = next(r for r in out["studies"] if r["study_id"] == "luad_tcga_pan_can_atlas_2018")
    assert pan["protein_change"] == {
        "value": "G12C",
        "altered": 70,
        "profiled": 566,
        "frequency": 0.1237,
    }
    assert out["studies"][0]["study_id"] == "luad_mskcc_2023_met_organotropism"


async def test_restricted_study_needs_opt_in(cbio_service: CbioService) -> None:
    with pytest.raises(InvalidInputError) as err:
        await cbio_service.get_gene_alteration_frequency(
            "KRAS", ["msk_chord_2024"], None, None, False
        )
    assert err.value.extra["field"] == "study_ids" and "include_restricted" in err.value.message
    out = await cbio_service.get_gene_alteration_frequency(
        "KRAS", ["msk_chord_2024"], None, None, True
    )
    assert out["studies"][0]["restricted"] is True


async def test_gene_forms(cbio_service: CbioService) -> None:
    out = await cbio_service.get_gene_alteration_frequency(
        "NCBIGene:3845", ["luad_tcga_pan_can_atlas_2018"], None, None, False
    )
    assert out["gene"] == "KRAS" and out["resolved_from"] == "NCBIGene:3845"
    with pytest.raises(InvalidInputError) as bad:
        await cbio_service.get_gene_mutations("ENSG00000133703", "x_study", None, False, 5, 0)
    extra = bad.value.extra
    assert extra["field"] == "gene" and extra["allowed_values"]
    assert extra["next_commands"][0]["tool"] == "hgnc_resolve_symbol"
    with pytest.raises(NotFoundError) as missing:
        await cbio_service.get_mutation_hotspots("NOTAGENE1", None, "GRCh38")
    assert missing.value.extra["field"] == "gene"


async def test_gene_mutations_are_aggregated_without_sample_ids(
    cbio_service: CbioService,
) -> None:
    out = await cbio_service.get_gene_mutations(
        "BRAF", "skcm_tcga_pan_can_atlas_2018", None, False, 3, 0
    )
    top = out["variants"][0]
    assert top["protein_change"] == "V600E" and top["samples"] == 158
    assert out["assembly"] == "GRCh37" and out["truncated"] is True and out["next_offset"] == 3
    assert out["study"]["licence"] == "ODbL-1.0"
    text = json.dumps(out)
    assert "sampleId" not in text and "TCGA-" not in text
    one = await cbio_service.get_gene_mutations(
        "BRAF", "skcm_tcga_pan_can_atlas_2018", "v600e", False, 3, 0
    )
    assert one["total"] == 1 and one["mutated_samples"] == 158


async def test_position_counts_state_no_denominator(cbio_service: CbioService) -> None:
    out = await cbio_service.get_mutation_position_counts("BRAF", [600, 601])
    assert out["positions"] == [
        {"position": 600, "mutations": 9070},
        {"position": 601, "mutations": 473},
    ]
    assert "not a frequency" in out["scope"]


async def test_list_cancer_types_by_parent_and_name(cbio_service: CbioService) -> None:
    out = await cbio_service.list_cancer_types(None, "nsclc", 100, 0)
    assert "luad" in {t["code"] for t in out["cancer_types"]}
    assert "nsclc" not in {t["code"] for t in out["cancer_types"]}
    mel = await cbio_service.list_cancer_types("melanoma", None, 100, 0)
    assert {"mel", "skcm"} <= {t["code"] for t in mel["cancer_types"]}


async def test_hotspots_braf_v600_and_tp53_r175h(cbio_service: CbioService) -> None:
    braf = await cbio_service.get_mutation_hotspots("BRAF", "V600", "GRCh37")
    single = next(r for r in braf["hotspots"] if r["type"] == "single_residue")
    assert single["tumor_count"] == 897 and single["variants"]["E"] == 833
    assert braf["is_hotspot"] is True and braf["source"]["licence"].startswith("ODbL-1.0")
    tp53 = await cbio_service.get_mutation_hotspots("TP53", "R175H", "GRCh38")
    assert tp53["is_hotspot"] is True and tp53["variant_tumor_count"] == 386
    assert {"single_residue", "3d"} <= {r["type"] for r in tp53["hotspots"]}
    assert tp53["data_version"].startswith("Cancer Hotspots v2 + 3D snapshot")
    cold = await cbio_service.get_mutation_hotspots("TP53", "A1", "GRCh38")
    assert cold["is_hotspot"] is False and cold["total"] == 0
    assert "not mean benign" in cold["note"]


async def test_unobserved_change_at_hotspot_residue_is_not_a_hotspot(
    cbio_service: CbioService,
) -> None:
    # KRAS G12 is a hotspot residue, but G12W was never seen there.
    out = await cbio_service.get_mutation_hotspots("KRAS", "G12W", "GRCh38")
    assert out["is_hotspot"] is False and out["residue_is_hotspot"] is True
    assert out["variant_tumor_count"] == 0
    seen = await cbio_service.get_mutation_hotspots("KRAS", "G12C", "GRCh38")
    assert seen["is_hotspot"] is True and seen["residue_is_hotspot"] is True


async def test_a_substitution_gets_only_residue_calls(cbio_service: CbioService) -> None:
    # BRAF's 592-604 in-frame-indel region covers V600 but says nothing about V600E.
    region = await cbio_service.get_mutation_hotspots("BRAF", "V600", "GRCh38")
    assert "in_frame_indel" in {r["type"] for r in region["hotspots"]}
    change = await cbio_service.get_mutation_hotspots("BRAF", "V600E", "GRCh38")
    assert {r["type"] for r in change["hotspots"]} == {"single_residue", "3d"}


async def test_no_code_path_reaches_row_level_endpoints() -> None:
    root = Path(cbioportal_link.__file__).parent
    source = "\n".join(p.read_text() for p in root.rglob("*.py"))
    for path in ("molecular-data", "copy-number-segments", "clinical-data", "mutated-genes"):
        assert f"/{path}" not in source


async def test_every_upstream_call_is_filtered(
    cbio_service: CbioService, mocked_cbio: respx.MockRouter
) -> None:
    await cbio_service.get_gene_alteration_frequency(
        "KRAS", None, "luad", "G12C", False, max_studies=2
    )
    for call in mocked_cbio.calls:
        url = call.request.url
        if "/mutations" in url.path:
            assert url.params["entrezGeneId"] == "3845"
        if url.path.endswith("counts/fetch"):
            body = json.loads(call.request.content)
            assert body["genomicDataFilters"][0]["hugoGeneSymbol"] == "KRAS"
            assert len(body["studyViewFilter"]["studyIds"]) == 1


def test_shipped_hotspot_tables_match_their_provenance() -> None:
    from cbioportal_link import hotspots

    prov = hotspots.provenance()
    assert prov["license"].startswith("ODbL-1.0") and len(prov["source_commit"]) == 40
    for entry in prov["files"].values():
        data = (hotspots.DATA / entry["derived_file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["derived_sha256"]
        assert data.count(b"\n") - 1 == entry["rows"]


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ('under the <a href="https://creativecommons.org/licenses/by-nc-nd/4.0/">CC</a>',
         ("CC-BY-NC-ND-4.0", True)),
        ("available under the Creative Commons BY-NC-ND 4.0 license.", ("CC-BY-NC-ND-4.0", True)),
        ("Free for research; for commercial use, please contact us.",
         ("see study description (commercial use restricted)", True)),
        ("Creative Commons BY 4.0 license", ("CC-BY-4.0", False)),
        ("TCGA Firehose Legacy.", ("ODbL-1.0", False)),
        (None, ("ODbL-1.0", False)),
    ],
)  # fmt: skip
def test_licence_parser_reads_every_description_form(
    description: str | None, expected: tuple[str, bool]
) -> None:
    from cbioportal_link.shaping import licence

    assert licence(description) == expected


async def test_study_pmids_are_deduplicated(cbio_service: CbioService) -> None:
    out = await cbio_service.get_study("luad_tcga_pan_can_atlas_2018")
    pmids = out["study"]["pmid"].split(",")
    assert pmids[0] == "29625048" and len(pmids) == len(set(pmids)) == 11


async def test_search_matches_words_in_any_order(cbio_service: CbioService) -> None:
    out = await cbio_service.search_studies("luad pan can atlas", None, False, 20, 0)
    assert [s["study_id"] for s in out["studies"]] == ["luad_tcga_pan_can_atlas_2018"]


async def test_guessed_study_id_offers_the_close_match(cbio_service: CbioService) -> None:
    with pytest.raises(NotFoundError) as err:
        await cbio_service.get_study("luad_tcga_pan_can_atlas_2019")
    assert err.value.extra["candidates"] == ["luad_tcga_pan_can_atlas_2018"]
    assert err.value.extra["next_commands"] == [
        {"tool": "get_study", "arguments": {"study_id": "luad_tcga_pan_can_atlas_2018"}}
    ]


async def test_frequency_rows_carry_assembly_and_default_is_flagged(
    cbio_service: CbioService,
) -> None:
    out = await cbio_service.get_gene_alteration_frequency(
        "KRAS", ["luad_tcga_pan_can_atlas_2018"], None, None, False
    )
    assert out["studies"][0]["assembly"] == "GRCh37" and "warning" not in out
    default = await cbio_service.get_gene_alteration_frequency("TP53", None, None, None, False)
    assert "msk_impact_2017" in default["warning"]


async def test_hotspot_tumor_types_only_in_standard_mode(cbio_service: CbioService) -> None:
    lean = await cbio_service.get_mutation_hotspots("KRAS", "G12C", "GRCh38")
    assert all("tumor_types" not in r for r in lean["hotspots"])
    full = await cbio_service.get_mutation_hotspots("KRAS", "G12C", "GRCh38", "standard")
    assert all(r["tumor_types"] for r in full["hotspots"])
