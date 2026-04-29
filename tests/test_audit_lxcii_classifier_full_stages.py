"""Tests dedicados Iteración Faubot LXCII — Classifier Full 18-Stage Routing.

Hipótesis verificables H.G3011-H.G3030 cubriendo el regression fix LXCII:
- Pre-LXCII: quick_classify_schema 15 fields → routea solo flujos básicos
  (localized_initial / mCSPC simple / m1_crpc). Pacientes post-RP+BCR,
  post-RT+failure, screening, diagnostic_workup, post_negative_biopsy_followup,
  mCSPC oligo metacrónico, m0_crpc, adt_progression_verification quedaban
  silenciosamente misclassified como localized_initial.
- Post-LXCII: schema expandido a 32 fields con multi-level
  conditional_visibility (Level 0 universal + Level 1 master gate + Level 2A
  pre-Dx + Level 2B Dx confirmed + Level 3A post-RP + Level 3B post-RT +
  Level 3C metastatic + Level 3D treatment+CRPC). Ahora el classifier puede
  routear correctamente a TODOS los 18 estadios canónicos NCCN.

Faubot 2026-04-28 LXCII.
"""
# IEC 62304 §5.6 (Integration testing) — verifica que el frontend wizard
# captura todos los fields necesarios para que el motor clínico clasifique
# correctamente en NCCN 5.2026.

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import logging
logging.getLogger().setLevel(logging.ERROR)


# ─── Helpers ────────────────────────────────────────────────────────────
def _make_payload(**overrides):
    """Build a baseline NCCN classify payload with sensible defaults."""
    base = {
        "full_name": "LXCII Test Patient",
        "dob": "1955-01-15",
        "nss": "97000000999",
        "ecog_score": "0",
        "family_history_cancer": "0",
        "charlson_comorbidity_index": 1,
        "known_cancer_diagnosis": "1",
    }
    base.update(overrides)
    return base


# ─── §A — Schema integrity (LXCII expansion verification) ────────────────
def test_g3011_quick_classify_schema_has_at_least_30_fields():
    """H.G3011 — Schema expandido tiene ≥30 fields (vs 15 pre-LXCII)."""
    from prostanet.presentation.v2_adapters import quick_classify_schema
    schema = quick_classify_schema()
    assert len(schema["fields"]) >= 30, (
        f"Schema only has {len(schema['fields'])} fields. "
        "LXCII expansion requires ≥30 to route 18 canonical NCCN stages."
    )


def test_g3012_schema_includes_post_rp_routing_fields():
    """H.G3012 — Schema incluye fields post-RP (psa_postop, bcr_detected, bcr_psa)."""
    from prostanet.presentation.v2_adapters import quick_classify_schema
    fields = {f["name"] for f in quick_classify_schema()["fields"]}
    assert "psa_postop" in fields, "psa_postop missing — post-RP path broken"
    assert "bcr_detected" in fields, "bcr_detected missing — BCR detection broken"
    assert "bcr_psa" in fields, "bcr_psa missing — BCR characterization broken"
    assert "bcr_date" in fields


def test_g3013_schema_includes_post_rt_routing_fields():
    """H.G3013 — Schema incluye fields post-RT (rt_completion_date, psa_nadir_post_rt)."""
    from prostanet.presentation.v2_adapters import quick_classify_schema
    fields = {f["name"] for f in quick_classify_schema()["fields"]}
    assert "rt_completion_date" in fields
    assert "psa_nadir_post_rt" in fields


def test_g3014_schema_includes_crpc_routing_fields():
    """H.G3014 — Schema incluye fields CRPC verification."""
    from prostanet.presentation.v2_adapters import quick_classify_schema
    fields = {f["name"] for f in quick_classify_schema()["fields"]}
    assert "castrate_testosterone_status" in fields
    assert "testosterone_value" in fields
    assert "systemic_progression_context" in fields
    assert "line_of_therapy_number" in fields


def test_g3015_schema_includes_pre_dx_routing_fields():
    """H.G3015 — Schema incluye fields pre-Dx (screening_context, prior_negative_biopsy, biopsy_scheduled)."""
    from prostanet.presentation.v2_adapters import quick_classify_schema
    fields = {f["name"] for f in quick_classify_schema()["fields"]}
    assert "screening_context" in fields
    assert "prior_negative_biopsy" in fields
    assert "biopsy_scheduled" in fields
    assert "encounter_type" in fields


def test_g3016_schema_includes_metastatic_routing_fields():
    """H.G3016 — Schema incluye fields metastatic (metachronous_metastasis, conventional_imaging_status)."""
    from prostanet.presentation.v2_adapters import quick_classify_schema
    fields = {f["name"] for f in quick_classify_schema()["fields"]}
    assert "metachronous_metastasis" in fields
    assert "conventional_imaging_status" in fields


def test_g3017_schema_has_multi_level_conditional_visibility():
    """H.G3017 — Schema tiene ≥20 conditional_visibility rules (Level 2A/2B/3A/3B/3C/3D)."""
    from prostanet.presentation.v2_adapters import quick_classify_schema
    schema = quick_classify_schema()
    cond_count = sum(1 for f in schema["fields"] if f.get("conditional_visibility"))
    assert cond_count >= 20, (
        f"Only {cond_count} conditional rules — LXCII requires ≥20 for "
        "multi-level progressive disclosure (pre-Dx / post-RP / post-RT / "
        "metastatic / CRPC branches)."
    )


# ─── §B — Routing verification: pre-Dx branch (3 stages) ─────────────────
def test_g3018_routes_to_screening_for_screening_context():
    """H.G3018 — known=0 + screening_context=1 → screening."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        known_cancer_diagnosis="0",
        screening_context="1",
        encounter_type="screening",
    )
    result = StateClassifierService().classify(payload)
    assert result["state"] == "screening", f"Got {result['state']}"


def test_g3019_routes_to_diagnostic_workup_for_biopsy_scheduled():
    """H.G3019 — known=0 + biopsy_scheduled=1 → diagnostic_workup."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        known_cancer_diagnosis="0",
        biopsy_scheduled="1",
        diagnostic_workup_requested="1",
    )
    result = StateClassifierService().classify(payload)
    assert result["state"] == "diagnostic_workup", f"Got {result['state']}"


def test_g3020_routes_to_post_negative_biopsy_followup():
    """H.G3020 — known=0 + prior_negative_biopsy=1 → post_negative_biopsy_followup."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        known_cancer_diagnosis="0",
        prior_negative_biopsy="1",
    )
    result = StateClassifierService().classify(payload)
    assert result["state"] == "post_negative_biopsy_followup", f"Got {result['state']}"


# ─── §C — Routing verification: localized + post-tx branches (4 stages) ──
def test_g3021_routes_to_localized_initial_when_no_prior_tx():
    """H.G3021 — known=1 + no prior_local_therapy + M0 → localized_initial."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="4", gleason_secondary="3",
        clinical_tstage="cT2a", metastasis_site="M0",
        psa_baseline_ng_ml="12.5",
        prior_local_therapy="none",
        current_adt_context="none",
    )
    result = StateClassifierService().classify(payload)
    assert result["state"] == "localized_initial", f"Got {result['state']}"


def test_g3022_routes_to_post_prostatectomy_when_psa_undetectable():
    """H.G3022 — prior_prostatectomy=1 + psa_postop<0.2 + no BCR → post_prostatectomy.

    Regression: pre-LXCII este caso routeaba a localized_initial porque el
    schema NO capturaba prior_prostatectomy ni psa_postop.
    """
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="4", gleason_secondary="3",
        clinical_tstage="cT2a", metastasis_site="M0",
        psa_baseline_ng_ml="12.5",
        prior_local_therapy="prostatectomy",
        prior_prostatectomy="1",
        psa_postop="0.05",
        bcr_detected="0",
    )
    result = StateClassifierService().classify(payload)
    assert result["state"] == "post_prostatectomy", f"Got {result['state']}"


def test_g3023_routes_to_recurrence_bcr_post_rp_with_bcr_detected():
    """H.G3023 — REGRESSION FIX LXCII: post-RP BCR ahora correctly clasifica.

    User-reported bug: paciente con prostatectomía + recurrencia bioquímica
    se clasificaba como `localized_initial` en LXCI/LXC.
    Post-LXCII: con bcr_detected=1 + bcr_psa>=0.2 + bcr_date → recurrence_bcr.
    """
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="4", gleason_secondary="3",
        clinical_tstage="cT2a", metastasis_site="M0",
        psa_baseline_ng_ml="12.5",
        prior_local_therapy="prostatectomy",
        prior_prostatectomy="1",
        psa_postop="0.45",
        bcr_detected="1",
        bcr_psa="0.45",
        bcr_date="2025-09-01",
    )
    result = StateClassifierService().classify(payload)
    assert result["state"] == "recurrence_bcr", (
        f"REGRESSION: Got {result['state']} for post-RP+BCR patient. "
        "Pre-LXCII bug: localized_initial. Post-LXCII fix: recurrence_bcr."
    )


def test_g3024_routes_to_post_radiotherapy_followup_when_no_failure():
    """H.G3024 — prior_local_therapy=radiation + no failure → post_radiotherapy_followup."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="4", gleason_secondary="3",
        clinical_tstage="cT2a", metastasis_site="M0",
        psa_baseline_ng_ml="12.5",
        prior_local_therapy="radiation",
        prior_radiation="1",
        rt_completion_date="2024-06-01",
        psa_nadir_post_rt="0.5",
    )
    result = StateClassifierService().classify(payload)
    assert result["state"] == "post_radiotherapy_followup", f"Got {result['state']}"


# ─── §D — Routing verification: metastatic mCSPC variants (3 stages) ─────
def test_g3025_routes_to_mcspc_high_volume_sync():
    """H.G3025 — M1b + high volume + de novo → mcspc_high_volume_sync."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="5", gleason_secondary="4",
        clinical_tstage="cT3b", metastasis_site="M1b",
        psa_baseline_ng_ml="120",
        metachronous_metastasis="0",
        metastasis_count="8",
        volume_disease="high",
        visceral_metastases="0",
        conventional_imaging_status="M1",
    )
    result = StateClassifierService().classify(payload)
    assert result["state"] == "mcspc_high_volume_sync", f"Got {result['state']}"


def test_g3026_routes_to_mcspc_oligo_metachronous():
    """H.G3026 — M1 metachronous + oligo (≤5 lesions) → mcspc_oligo_metachronous."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="4", gleason_secondary="3",
        clinical_tstage="cT2a", metastasis_site="M1b",
        psa_baseline_ng_ml="35",
        prior_local_therapy="prostatectomy",
        prior_prostatectomy="1",
        metachronous_metastasis="1",
        metastasis_count="3",
        conventional_imaging_status="M1",
    )
    result = StateClassifierService().classify(payload)
    assert result["state"] == "mcspc_oligo_metachronous", f"Got {result['state']}"


# ─── §E — Routing verification: CRPC branches (3 stages) ─────────────────
def test_g3027_routes_to_m1_crpc_with_full_castration_progression():
    """H.G3027 — M1 + ADT + castrate confirmed + confirmed_crpc → m1_crpc."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="4", gleason_secondary="5",
        clinical_tstage="cT3a", metastasis_site="M1b",
        psa_baseline_ng_ml="85",
        current_adt_context="medical_adt_continuous",
        castrate_testosterone_status="confirmed_castrate",
        castrate_testosterone_confirmed="1",
        testosterone_value="15",
        systemic_progression_context="confirmed_crpc",
        castration_resistant="1",
        line_of_therapy_number="2",
        conventional_imaging_status="M1",
    )
    result = StateClassifierService().classify(payload)
    assert result["state"] == "m1_crpc", f"Got {result['state']}"


def test_g3028_routes_to_adt_progression_verification_when_unconfirmed():
    """H.G3028 — ADT+suspicious progression+castrate unconfirmed → adt_progression_verification."""
    from prostanet.domains.state_classifier.service import StateClassifierService
    payload = _make_payload(
        gleason_primary="4", gleason_secondary="3",
        clinical_tstage="cT2a", metastasis_site="M0",
        psa_baseline_ng_ml="12",
        current_adt_context="medical_adt_continuous",
        castrate_testosterone_status="unknown",
        systemic_progression_context="suspicious",
    )
    result = StateClassifierService().classify(payload)
    assert result["state"] == "adt_progression_verification", f"Got {result['state']}"


# ─── §F — JS auto-derive helper verification ──────────────────────────────
def test_g3029_intake_wizard_has_auto_derive_function():
    """H.G3029 — intake-wizard.html declara iwAutoDeriveClassifierFlags handler."""
    template = PROJECT_ROOT / "templates" / "intake_stage_aware_v2.html"
    content = template.read_text()
    assert "function iwAutoDeriveClassifierFlags" in content, (
        "iwAutoDeriveClassifierFlags handler missing — auto-derive of "
        "prior_prostatectomy / prior_radiation / castration_resistant broken."
    )
    # Verify it actually maps prior_local_therapy → prior_prostatectomy/radiation
    assert "prior_prostatectomy = '1'" in content
    assert "prior_radiation = '1'" in content
    assert "castration_resistant = '1'" in content


def test_g3030_intake_wizard_step1_calls_conditional_visibility():
    """H.G3030 — Step 1 form (quick) ahora llama iwApplyConditionalVisibility.

    Pre-LXCII: solo Step 2 aplicaba conditional_visibility, dejando Step 1
    sin progressive disclosure → todos los 32 fields visibles a la vez.
    Post-LXCII: Step 1 también aplica conditional_visibility para mostrar
    sólo branches relevantes según las respuestas previas.
    """
    template = PROJECT_ROOT / "templates" / "intake_stage_aware_v2.html"
    content = template.read_text()
    # Find the iwRenderQuickForm function and check it calls iwApplyConditionalVisibility
    qf_start = content.find("function iwRenderQuickForm")
    qf_end = content.find("function iwRenderFieldHtml", qf_start)
    qf_section = content[qf_start:qf_end]
    assert "iwApplyConditionalVisibility(container)" in qf_section, (
        "iwRenderQuickForm no llama iwApplyConditionalVisibility — "
        "Step 1 conditional_visibility roto."
    )
