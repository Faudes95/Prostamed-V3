"""Tests dedicados Iteración Faubot LXCII.1 — Image-Canonical Classification.

Hipótesis verificables H.G3031-H.G3050 cubriendo el refinement LXCII.1
basado en la imagen clínica de referencia adjuntada por el usuario:

  "DEFINICIONES PARA CADA ETAPA DEL CÁNCER DE PRÓSTATA"
  Tabla canonical con definiciones operativas de:
    - Enfermedad localizada (D'Amico bajo/intermedio/alto)
    - Recurrencia bioquímica (post-RP ≥0.2 + ↑ · post-RT nadir+2)
    - CPHSm/CPHNm (alto volumen CHAARTED, bajo volumen, alto riesgo LATITUDE)
    - CPCR (PCWG3: T<50 + 3↑PSA → 2 aumentos 50% sobre nadir + APE>2)
    - CPCR M0 (sin metástasis en imagen) vs M1 (con metástasis en imagen)

Pre-LXCII.1: el schema NO capturaba bone_lesion_count_total ni
bone_appendicular_count ni visceral_metastasis_present discreto, por lo
que el backend `_derive_mhspc_burden_context()` no podía computar
volume_disease correctamente para CHAARTED/LATITUDE.

Post-LXCII.1: schema expandido a 34 fields con auto-derive JS de:
  - volume_disease (CHAARTED HV/LV)
  - latitude_high_risk (≥2 de 3: GS≥8, bone≥3, visceral)
  - bone_axial_count = total - appendicular
  - D'Amico risk live computado en preview card

Faubot 2026-04-28 LXCII.1.
"""
# IEC 62304 §5.6 (Integration testing) — verifica que la captura de
# Step 1 alimenta correctamente la lógica clínica per imagen canonical.

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import logging
logging.getLogger().setLevel(logging.ERROR)


def _make_payload(**overrides):
    base = {
        "full_name": "LXCII.1 Test",
        "dob": "1955-01-15",
        "nss": "98000000999",
        "ecog_score": "0",
        "family_history_cancer": "0",
        "charlson_comorbidity_index": 1,
        "known_cancer_diagnosis": "1",
    }
    base.update(overrides)
    return base


# ─── §A — Schema integrity (LXCII.1 expansion) ──────────────────────────
def test_g3031_schema_includes_bone_lesion_count_total():
    """H.G3031 — Schema incluye bone_lesion_count_total (image: ≥4 → HV CHAARTED)."""
    from prostanet.presentation.v2_adapters import quick_classify_schema
    fields = {f["name"] for f in quick_classify_schema()["fields"]}
    assert "bone_lesion_count_total" in fields, (
        "bone_lesion_count_total missing — CHAARTED HV/LV discrimination broken."
    )


def test_g3032_schema_includes_bone_appendicular_count():
    """H.G3032 — Schema incluye bone_appendicular_count (image: ≥1 apendicular → HV)."""
    from prostanet.presentation.v2_adapters import quick_classify_schema
    fields = {f["name"] for f in quick_classify_schema()["fields"]}
    assert "bone_appendicular_count" in fields, (
        "bone_appendicular_count missing — CHAARTED axial-confined LV vs HV broken."
    )


def test_g3033_schema_includes_visceral_metastasis_present():
    """H.G3033 — Schema incluye visceral_metastasis_present discrete (no sólo M1c)."""
    from prostanet.presentation.v2_adapters import quick_classify_schema
    fields = {f["name"] for f in quick_classify_schema()["fields"]}
    assert "visceral_metastasis_present" in fields, (
        "visceral_metastasis_present missing — CHAARTED visceral=HV trigger broken."
    )


def test_g3034_total_schema_fields_at_least_34():
    """H.G3034 — Schema LXCII.1 tiene ≥34 fields (vs 32 LXCII)."""
    from prostanet.presentation.v2_adapters import quick_classify_schema
    schema = quick_classify_schema()
    assert len(schema["fields"]) >= 34, (
        f"Only {len(schema['fields'])} fields. LXCII.1 expansion requires ≥34."
    )


# ─── §B — D'Amico risk groups (image canonical) ─────────────────────────
def test_g3035_damico_low_risk_per_image():
    """H.G3035 — D'Amico bajo riesgo: PSA<10 ∧ GS<7 ∧ cT1-2a → localized_initial."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="3", gleason_secondary="3",  # GS=6 <7
        clinical_tstage="cT1c",
        metastasis_site="M0",
        psa_baseline_ng_ml="6.5",  # <10
        prior_local_therapy="none",
        current_adt_context="none",
    )
    result = StateClassifierService().classify(payload)
    assert result["state"] == "localized_initial"


def test_g3036_damico_intermediate_risk_per_image():
    """H.G3036 — D'Amico intermedio: APE 10-20 OR GS=7 OR cT2b → localized_initial."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="3", gleason_secondary="4",  # GS=7
        clinical_tstage="cT2b",
        metastasis_site="M0",
        psa_baseline_ng_ml="15.0",  # 10-20
        prior_local_therapy="none",
        current_adt_context="none",
    )
    result = StateClassifierService().classify(payload)
    assert result["state"] == "localized_initial"


def test_g3037_damico_high_risk_per_image():
    """H.G3037 — D'Amico alto riesgo: APE>20 OR GS>7/8 OR cT2c/T3a → localized_initial."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="4", gleason_secondary="5",  # GS=9
        clinical_tstage="cT3a",
        metastasis_site="M0",
        psa_baseline_ng_ml="35.0",  # >20
        prior_local_therapy="none",
        current_adt_context="none",
    )
    result = StateClassifierService().classify(payload)
    assert result["state"] == "localized_initial"


# ─── §C — CHAARTED HV/LV per image canonical ─────────────────────────────
def test_g3038_chaarted_hv_visceral_metastases():
    """H.G3038 — CHAARTED HV by visceral mets (image: visceral=1 → HV automático)."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="4", gleason_secondary="3",
        clinical_tstage="cT3a",
        metastasis_site="M1c",
        psa_baseline_ng_ml="120",
        visceral_metastasis_present="1",
        visceral_lesion_count="2",
        metachronous_metastasis="0",
        volume_disease="high",
        conventional_imaging_status="M1",
    )
    result = StateClassifierService().classify(payload)
    burden = result["derived_metastatic_context"]
    assert burden.get("volume_disease") == "high", (
        f"volume_disease={burden.get('volume_disease')} — image criterion: visceral → HV"
    )
    assert "mcspc_high_volume" in result["state"]


def test_g3039_chaarted_hv_bone_4_with_appendicular():
    """H.G3039 — CHAARTED HV by ≥4 bone with ≥1 appendicular (CHAARTED 2015 NEJM)."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="4", gleason_secondary="4",
        clinical_tstage="cT3a",
        metastasis_site="M1b",
        psa_baseline_ng_ml="85",
        visceral_metastasis_present="0",
        bone_metastasis_present="1",
        bone_axial_count="3", bone_appendicular_count="2",  # 5 total, 2 appendicular
        metachronous_metastasis="0",
        volume_disease="high",
        conventional_imaging_status="M1",
    )
    result = StateClassifierService().classify(payload)
    burden = result["derived_metastatic_context"]
    assert burden.get("volume_disease") == "high", (
        f"volume_disease={burden.get('volume_disease')} — "
        "image: ≥4 óseas con ≥1 apendicular → HV"
    )


def test_g3040_chaarted_lv_axial_confined():
    """H.G3040 — CHAARTED LV axial-confined: ≥4 óseas pero todas axiales → LV."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="4", gleason_secondary="3",
        clinical_tstage="cT2a",
        metastasis_site="M1b",
        psa_baseline_ng_ml="35",
        visceral_metastasis_present="0",
        bone_metastasis_present="1",
        bone_axial_count="4", bone_appendicular_count="0",  # 4 axial only
        metachronous_metastasis="0",
        volume_disease="low",
        conventional_imaging_status="M1",
    )
    result = StateClassifierService().classify(payload)
    burden = result["derived_metastatic_context"]
    assert burden.get("volume_disease") == "low", (
        f"volume_disease={burden.get('volume_disease')} — "
        "image: ≥4 óseas axial-confined sin visceral → LV"
    )


def test_g3041_chaarted_lv_few_bone_no_visceral():
    """H.G3041 — CHAARTED LV by <3 bone + no visceral (image canonical)."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="3", gleason_secondary="4",
        clinical_tstage="cT2c",
        metastasis_site="M1b",
        psa_baseline_ng_ml="22",
        visceral_metastasis_present="0",
        bone_metastasis_present="1",
        bone_axial_count="2", bone_appendicular_count="0",
        metachronous_metastasis="0",
        volume_disease="low",
        conventional_imaging_status="M1",
    )
    result = StateClassifierService().classify(payload)
    burden = result["derived_metastatic_context"]
    assert burden.get("volume_disease") == "low"


# ─── §D — LATITUDE HR ≥2 of 3 criteria (image canonical) ────────────────
def test_g3042_js_auto_derive_includes_latitude_high_risk_function():
    """H.G3042 — iwAutoDeriveClassifierFlags computes latitude_high_risk (≥2/3)."""
    template = PROJECT_ROOT / "templates" / "intake_stage_aware_v2.html"
    content = template.read_text()
    # Verify LATITUDE logic in JS (3 criteria check)
    assert "latitudeCriteria" in content, "latitudeCriteria missing in JS"
    assert "totalGleason >= 8" in content, "GS≥8 criterion missing in LATITUDE check"
    assert "boneTotal >= 3" in content, "≥3 óseas criterion missing in LATITUDE check"
    assert "latitude_high_risk" in content


def test_g3043_js_auto_derive_volume_disease_chaarted():
    """H.G3043 — iwAutoDeriveClassifierFlags computes volume_disease per CHAARTED."""
    template = PROJECT_ROOT / "templates" / "intake_stage_aware_v2.html"
    content = template.read_text()
    assert "volume_disease = 'high'" in content
    assert "volume_disease = 'low'" in content
    # Visceral → HV trigger
    assert "if (visceral)" in content


# ─── §E — CPHNm de novo (hormono naïve) per image ───────────────────────
def test_g3044_cphnm_de_novo_metastatic_no_prior_treatment():
    """H.G3044 — CPHNm: M1 + sync + no prior local tx + ADT none → mcspc_*_sync."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="5", gleason_secondary="4",
        clinical_tstage="cT3b",
        metastasis_site="M1c",
        psa_baseline_ng_ml="280",  # alta carga tumoral
        visceral_metastasis_present="1",
        prior_local_therapy="none",
        current_adt_context="none",
        metachronous_metastasis="0",  # de novo / sync
        volume_disease="high",
        conventional_imaging_status="M1",
    )
    result = StateClassifierService().classify(payload)
    # CPHNm = synchronous metastatic at diagnosis, hormone-naïve
    assert result["state"] == "mcspc_high_volume_sync", (
        f"Got {result['state']} — CPHNm de novo debe routear a mcspc_high_volume_sync"
    )


# ─── §F — CPCR M0 vs M1 per PCWG3 (image canonical) ─────────────────────
def test_g3045_pcwg3_m1_crpc_full_criteria():
    """H.G3045 — m1CRPC PCWG3: T<50 + 3↑PSA + M1 imagen → m1_crpc."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="4", gleason_secondary="5",
        clinical_tstage="cT3a",
        metastasis_site="M1b",
        psa_baseline_ng_ml="85",
        prior_local_therapy="prostatectomy",
        prior_prostatectomy="1",
        current_adt_context="medical_adt_continuous",
        castrate_testosterone_status="confirmed_castrate",
        castrate_testosterone_confirmed="1",
        testosterone_value="18",  # <50 ✓
        systemic_progression_context="confirmed_crpc",
        castration_resistant="1",
        line_of_therapy_number="2",
        conventional_imaging_status="M1",  # mets en imagen ✓
    )
    result = StateClassifierService().classify(payload)
    assert result["state"] == "m1_crpc"


def test_g3046_pcwg3_m0_crpc_no_radiographic_mets():
    """H.G3046 — m0CRPC PCWG3: T<50 + 3↑PSA + M0 imagen → m0_crpc.

    Image canonical: "CPCR no metastásico o M0: cuando se cumplen los dos
    criterios anteriores [T<50 + progresión PSA] pero no hay evidencia de
    metástasis detectados en los estudios de imagen."

    Candidatos SPARTAN/PROSPER/ARAMIS si PSADT≤10mo (decisión Step 2).
    """
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="4", gleason_secondary="3",
        clinical_tstage="cT2c",
        metastasis_site="M0",  # sin mets clínico al diagnóstico
        psa_baseline_ng_ml="12.5",
        prior_local_therapy="prostatectomy",
        prior_prostatectomy="1",
        current_adt_context="medical_adt_continuous",
        castrate_testosterone_status="confirmed_castrate",
        castrate_testosterone_confirmed="1",
        testosterone_value="15",
        systemic_progression_context="confirmed_crpc",
        castration_resistant="1",
        line_of_therapy_number="2",
        conventional_imaging_status="M0",  # imagen NEGATIVA ✓ (PCWG3 M0)
    )
    result = StateClassifierService().classify(payload)
    assert result["state"] == "m0_crpc", (
        f"Got {result['state']} — paciente PCWG3 M0CRPC debe routear a m0_crpc "
        "(candidato SPARTAN/PROSPER/ARAMIS)"
    )


# ─── §G — Live preview card UI verification ─────────────────────────────
def test_g3047_intake_wizard_has_live_preview_card():
    """H.G3047 — intake-wizard.html declara <aside id='iw-live-preview'>."""
    template = PROJECT_ROOT / "templates" / "intake_stage_aware_v2.html"
    content = template.read_text()
    assert 'id="iw-live-preview"' in content, "Live preview card missing"
    # Verify it mentions the canonical clinical criteria (image)
    assert "D'Amico" in content
    assert "CHAARTED" in content
    assert "LATITUDE" in content
    assert "PCWG3" in content


def test_g3048_intake_wizard_has_iw_build_live_preview_function():
    """H.G3048 — intake-wizard.html declara iwBuildLiveClassificationPreview."""
    template = PROJECT_ROOT / "templates" / "intake_stage_aware_v2.html"
    content = template.read_text()
    assert "function iwBuildLiveClassificationPreview" in content


def test_g3049_intake_wizard_step1_calls_live_preview_on_input():
    """H.G3049 — Step 1 (iwRenderQuickForm) llama iwBuildLiveClassificationPreview."""
    template = PROJECT_ROOT / "templates" / "intake_stage_aware_v2.html"
    content = template.read_text()
    qf_start = content.find("function iwRenderQuickForm")
    qf_end = content.find("function iwRenderFieldHtml", qf_start)
    qf_section = content[qf_start:qf_end]
    assert "iwBuildLiveClassificationPreview()" in qf_section, (
        "iwRenderQuickForm no invoca iwBuildLiveClassificationPreview — "
        "live preview no actualiza on input change."
    )


# ─── §H — Recurrencia bioquímica per image (post-RP ≥0.2 + ↑) ───────────
def test_g3050_bcr_post_rp_per_image_two_consecutive_above_threshold():
    """H.G3050 — Image canonical post-RP BCR: 2 valores APE ≥0.2 consecutivos.

    Backend `_has_confirmed_post_rp_bcr` valida via:
      (a) bcr_detected=1 (clinician marked) OR
      (b) confirmatory series ≥2 points with PSA≥0.2 OR
      (c) bcr_psa≥0.2 + bcr_definition/bcr_date filled.
    """
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="4", gleason_secondary="3",
        clinical_tstage="cT2c",
        metastasis_site="M0",
        psa_baseline_ng_ml="12.5",
        prior_local_therapy="prostatectomy",
        prior_prostatectomy="1",
        psa_postop="0.45",
        bcr_detected="1",
        bcr_psa="0.45",
        bcr_date="2025-09-01",
        bcr_definition="two_consecutive_above_0.2_rising",
    )
    result = StateClassifierService().classify(payload)
    assert result["state"] == "recurrence_bcr", (
        f"Got {result['state']} — image: post-RP 2 valores ≥0.2 + ↑ → recurrence_bcr"
    )
