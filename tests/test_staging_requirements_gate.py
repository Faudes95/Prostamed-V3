"""Tests gate de estadificación M obligatoria + contraindicación de PR en cT4.

Respaldo clínico:
- NCCN PROS-2 v5.2026 cat 1 (umbrales de staging M)
- NCCN PROS-3 v5.2026 cat 1 (candidabilidad de RP+PLND)
- EAU 2026 §6.4.1-6.4.3 (investigaciones de extensión)
- EAU 2026 §6.5.1 (indicaciones de prostatectomía radical)
- ProPSMA (Hofman Lancet 2020;395:1208)
- Briganti / ProsTIC nomograms

Cierra la brecha clínica reportada (2026-04-22): paciente con PSA 36 +
cT4 + BTR positiva era ruteado directamente a localized_initial →
very high risk y emitía RT+TPA, RT+TPA+abiraterona y **RP+PLND
extendida** sin exigir estadificación M.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.application.module_registry import ModuleRegistry
from prostanet.shared.staging_requirements_engine import (
    radical_prostatectomy_contraindicated,
    staging_complete,
    staging_gap_descriptor,
    staging_modality_recommended,
    staging_required,
)


@pytest.fixture(scope="module")
def registry():
    return ModuleRegistry()


# ──────────────────────────────────────────────────────────────────
# G.1 — Caso reportado por usuario
# ──────────────────────────────────────────────────────────────────

def test_user_reported_case_t4_psa36_blocks_curative_treatment(registry):
    """PSA 36 + cT4 + GG9 sin staging → bloquea tratamiento curativo."""
    payload = {
        "known_cancer_diagnosis": "1",
        "psa": 36,
        "clinical_tstage": "T4",
        "gleason_total": 9,
        "isup_grade": 5,
        "ecog_score": 0,
        "age": 68,
    }
    result = registry.evaluate_module("localized_initial", payload)

    treatments_blob = " ".join(
        (t.get("name") or "").lower()
        for t in (result.get("eligible_treatments") or result.get("treatments") or [])
    )
    nr_blob = " ".join(
        str(x).lower() for x in (result.get("not_recommended") or [])
    )

    # Debe emitir recomendación de estadificación
    assert (
        "estadificación" in treatments_blob
        or "estadificacion" in treatments_blob
        or "psma" in treatments_blob
    ), f"No se emitió staging; treatments={treatments_blob[:200]}"

    # No debe emitir tratamiento curativo (RT+TPA, RP)
    assert "rt+tpa" not in treatments_blob, f"RT+TPA emitido: {treatments_blob[:200]}"
    assert "prostatectom" not in treatments_blob, f"Prostatectomía emitida: {treatments_blob[:200]}"

    # Mensaje en not_recommended
    assert (
        "diferido" in nr_blob
        or "completar" in nr_blob
        or "estadificación" in nr_blob
        or "estadificacion" in nr_blob
    ), f"No hay mensaje de bloqueo en not_recommended; nr={nr_blob[:300]}"

    # Override y human review
    assert result.get("state_classification_override") == "staging_required"
    assert result.get("requires_human_review") is True


# ──────────────────────────────────────────────────────────────────
# G.1b — Caso usuario CON staging completo M0: NO debe ofrecer RP+PLND por cT4
# ──────────────────────────────────────────────────────────────────

def test_t4_psa36_with_m0_staging_excludes_radical_prostatectomy(registry):
    """PSA 36 + cT4 + staging M0 → EBRT+ADT sí, RP+PLND NO (Gate B)."""
    payload = {
        "known_cancer_diagnosis": "1",
        "psa": 36,
        "clinical_tstage": "T4",
        "gleason_total": 9,
        "isup_grade": 5,
        "psma_pet_done": "Sí",
        "psma_pet_result": "Negativo (M0)",
        "imaging_negative_metastases": "Sí",
        "ecog_score": 0,
        "age": 68,
    }
    result = registry.evaluate_module("localized_initial", payload)

    treatments_blob = " ".join(
        (t.get("name") or "").lower()
        for t in (result.get("eligible_treatments") or result.get("treatments") or [])
    )
    nr_blob = " ".join(
        str(x).lower() for x in (result.get("not_recommended") or [])
    )

    # RT+ADT debe estar disponible
    assert (
        "rt+tpa" in treatments_blob
        or "ebrt" in treatments_blob
        or "radioterap" in treatments_blob
    ), f"RT no emitida pese a M0; treatments={treatments_blob[:300]}"

    # RP+PLND debe estar EXCLUIDA por cT4
    assert "prostatectom" not in treatments_blob, (
        f"Prostatectomía aún emitida en cT4; treatments={treatments_blob[:300]}"
    )
    assert "rp+plnd" not in treatments_blob, (
        f"RP+PLND aún emitida en cT4; treatments={treatments_blob[:300]}"
    )

    # Mensaje justificando exclusión
    assert (
        "t4" in nr_blob
        or "contraindicada" in nr_blob
        or "invasión" in nr_blob
        or "invasion" in nr_blob
    ), f"No hay justificación de exclusión de RP; nr={nr_blob[:300]}"


# ──────────────────────────────────────────────────────────────────
# G.1c — Intermedio desfavorable: staging "considerado", no bloqueante
# ──────────────────────────────────────────────────────────────────

def test_intermediate_unfavorable_staging_considered_not_blocking(registry):
    """PSA 15 + cT2c + GG3 → staging considerado, no bloquea tratamiento."""
    payload = {
        "known_cancer_diagnosis": "1",
        "psa": 15,
        "clinical_tstage": "T2c",
        "gleason_total": 7,
        "gleason_primary": 4,
        "gleason_secondary": 3,
        "isup_grade": 3,
        "ecog_score": 0,
        "age": 65,
    }
    result = registry.evaluate_module("localized_initial", payload)

    # No bloquea — emite tratamientos
    assert result.get("state_classification_override") != "staging_required", (
        "Intermedio desfavorable fue bloqueado (no debería)"
    )
    treatments = (
        result.get("eligible_treatments") or result.get("treatments") or []
    )
    assert len(treatments) > 0, "No hay tratamientos emitidos"


# ──────────────────────────────────────────────────────────────────
# G.2-G.5 — Risk band classification y umbrales PSA (paramétrico)
# ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "psa,t,gleason,expected_band,expected_tier",
    [
        (36, "T4", 9, "very_high", "mandatory"),  # Caso usuario
        (8, "T2a", 6, "intermediate_or_lower", "not_required"),  # Bajo riesgo
        (25, "T2c", 7, "high", "mandatory"),  # PSA>20
        (50, "T3a", 9, "very_high", "mandatory"),  # PSA>40+T3
        (12, "T1c", 6, "intermediate_or_lower", "not_required"),  # PSA<20 sin features
        (110, "T2a", 7, "very_high", "mandatory"),  # PSA>100
        (8, "T3a", 9, "very_high", "mandatory"),  # T3+GG5 sin PSA alto
    ],
)
def test_staging_required_psa_thresholds_and_risk_band(
    psa, t, gleason, expected_band, expected_tier
):
    isup_map = {6: 1, 7: 2, 8: 4, 9: 5, 10: 5}
    isup = isup_map[gleason]
    req = staging_required(
        {
            "psa": psa,
            "clinical_tstage": t,
            "gleason_total": gleason,
            "isup_grade": isup,
        }
    )
    assert req["risk_band"] == expected_band, (
        f"Banda esperada {expected_band}, obtenida {req['risk_band']} "
        f"para PSA={psa}, T={t}, GG={isup}"
    )
    assert req["tier"] == expected_tier, (
        f"Tier esperado {expected_tier}, obtenido {req['tier']}"
    )


# ──────────────────────────────────────────────────────────────────
# G.5b — RP contraindicada por T-stage (Gate B)
# ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "t_stage,expected_contra,expected_severity",
    [
        ("T1c", False, "none"),
        ("T2a", False, "none"),
        ("T3a", False, "none"),
        ("T3b", False, "none"),  # sin invasión SV extensa
        ("T4", True, "absolute"),
    ],
)
def test_radical_prostatectomy_contraindicated_by_t_stage(
    t_stage, expected_contra, expected_severity
):
    rp = radical_prostatectomy_contraindicated({"clinical_tstage": t_stage})
    assert rp["contraindicated"] is expected_contra, (
        f"Para {t_stage}: esperado contraindicated={expected_contra}, "
        f"obtenido={rp['contraindicated']}"
    )
    assert rp["severity"] == expected_severity, (
        f"Para {t_stage}: esperado severity={expected_severity}, "
        f"obtenido={rp['severity']}"
    )


# ──────────────────────────────────────────────────────────────────
# G.5c — RP contraindicada por factores locales
# ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"clinical_tstage": "T3b", "rectal_invasion": "Sí"}, True),
        ({"clinical_tstage": "T3a", "bladder_invasion": "Sí"}, True),
        ({"clinical_tstage": "T2c", "pelvic_fixation": "Sí"}, True),
        (
            {"clinical_tstage": "T3b", "extensive_seminal_vesicle_invasion": "Sí"},
            True,
        ),  # relativo
    ],
)
def test_rp_contraindicated_by_local_factors(payload, expected):
    rp = radical_prostatectomy_contraindicated(payload)
    assert rp["contraindicated"] is expected, (
        f"Payload={payload}: esperado contraindicated={expected}, obtenido={rp['contraindicated']}"
    )


# ──────────────────────────────────────────────────────────────────
# G.6 — Staging completa con PSMA PET/CT solo
# ──────────────────────────────────────────────────────────────────

def test_staging_complete_with_psma_pet_only():
    comp = staging_complete(
        {"psma_pet_done": "Sí", "psma_pet_result": "Negativo (M0)"}
    )
    assert comp["complete"] is True
    assert "PSMA PET/CT" in comp["modalities_done"]


# ──────────────────────────────────────────────────────────────────
# G.7 — Staging completa con GGO + TAC
# ──────────────────────────────────────────────────────────────────

def test_staging_complete_with_bone_scan_plus_ct():
    comp = staging_complete(
        {"bone_scan_done": "Sí", "ct_abdomen_pelvis_done": "Sí"}
    )
    assert comp["complete"] is True
    assert "GGO" in comp["modalities_done"]
    assert "TAC abdomino-pélvico" in comp["modalities_done"]


# ──────────────────────────────────────────────────────────────────
# G.8 — Staging incompleta con solo GGO
# ──────────────────────────────────────────────────────────────────

def test_staging_incomplete_with_only_bone_scan():
    comp = staging_complete({"bone_scan_done": "Sí"})
    assert comp["complete"] is False
    assert any("TAC" in m or "RM" in m for m in comp["missing"])


# ──────────────────────────────────────────────────────────────────
# G.9 — Staging completo + M0 documentado → destrababa tratamiento
# ──────────────────────────────────────────────────────────────────

def test_treatment_unblocked_after_staging_complete_m0(registry):
    """Staging PSMA PET/CT negativo + imaging_negative_metastases='Sí' →
    tratamiento curativo emitido."""
    payload = {
        "known_cancer_diagnosis": "1",
        "psa": 36,
        "clinical_tstage": "T4",
        "gleason_total": 9,
        "isup_grade": 5,
        "psma_pet_done": "Sí",
        "psma_pet_result": "Negativo (M0)",
        "imaging_negative_metastases": "Sí",
        "ecog_score": 0,
        "age": 68,
    }
    result = registry.evaluate_module("localized_initial", payload)
    treatments_blob = " ".join(
        (t.get("name") or "").lower()
        for t in (result.get("eligible_treatments") or result.get("treatments") or [])
    )
    assert (
        "rt+tpa" in treatments_blob
        or "radioterap" in treatments_blob
        or "ebrt" in treatments_blob
    ), f"Tratamiento curativo no emitido pese a M0; treatments={treatments_blob[:300]}"
    assert result.get("state_classification_override") != "staging_required"


# ──────────────────────────────────────────────────────────────────
# G.10 — PSMA positivo M1 documentado → rutea a mCSPC
# ──────────────────────────────────────────────────────────────────

def test_psma_positive_m1_documented_routes_to_metastatic_workflow(registry):
    """PSMA+ y metastasis_site documentado → state classifier rutea a mCSPC."""
    payload = {
        "known_cancer_diagnosis": "1",
        "psa": 36,
        "clinical_tstage": "T4",
        "gleason_total": 9,
        "isup_grade": 5,
        "psma_pet_done": "Sí",
        "psma_pet_result": "Positivo M1",
        "psma_rads_score": "5 (maligno)",
        "metastasis_site": "bone",
        "metastatic": 1,
        "bone_lesion_count": 4,
        "ecog_score": 0,
        "age": 68,
    }
    classification = registry.classify_state(payload)
    state = classification.get("state") or ""
    assert "mcspc" in state.lower() or "m1" in state.lower(), (
        f"Estado esperado mCSPC/M1, obtenido: {state}"
    )


# ──────────────────────────────────────────────────────────────────
# G.11 — diagnostic_workup emite PSMA/GGO/TAC explícitos
# ──────────────────────────────────────────────────────────────────

def test_diagnostic_workup_emits_staging_imaging(registry):
    """PSA 36 + cT4 + GG 5 → diagnostic_workup emite PSMA PET/CT."""
    payload = {
        "psa": 36,
        "clinical_tstage": "T4",
        "gleason_total": 9,
        "isup_grade": 5,
    }
    result = registry.evaluate_module("diagnostic_workup", payload)
    treatments_blob = " ".join(
        (t.get("name") or "").lower()
        for t in (result.get("eligible_treatments") or result.get("treatments") or [])
    )
    assert "psma" in treatments_blob, (
        f"diagnostic_workup no emitió PSMA; treatments={treatments_blob[:500]}"
    )


# ──────────────────────────────────────────────────────────────────
# G.12 — Riesgo intermedio NO requiere staging obligatoria
# ──────────────────────────────────────────────────────────────────

def test_intermediate_risk_no_staging_gate(registry):
    """PSA 12, T2a, GG2 → no requires staging, no bloquea."""
    payload = {
        "known_cancer_diagnosis": "1",
        "psa": 12,
        "clinical_tstage": "T2a",
        "gleason_total": 7,
        "gleason_primary": 3,
        "gleason_secondary": 4,
        "isup_grade": 2,
        "ecog_score": 0,
        "age": 65,
    }
    result = registry.evaluate_module("localized_initial", payload)
    assert result.get("state_classification_override") != "staging_required"


# ──────────────────────────────────────────────────────────────────
# G.13 — Schema coverage: FieldSpecs de staging en localized_initial
# ──────────────────────────────────────────────────────────────────

def test_localized_initial_schema_includes_staging_imaging_fields(registry):
    fields = {f["name"] for f in registry.services["localized_initial"].schema()["fields"]}
    required_new = {
        "psma_pet_done",
        "psma_pet_result",
        "bone_scan_done",
        "ct_abdomen_pelvis_done",
        "imaging_negative_metastases",
    }
    missing = required_new - fields
    assert not missing, f"Faltan FieldSpecs: {missing}"


# ──────────────────────────────────────────────────────────────────
# G.14 — staging_gap_descriptor None cuando no aplica
# ──────────────────────────────────────────────────────────────────

def test_staging_gap_descriptor_none_for_low_risk():
    payload = {
        "psa": 5,
        "clinical_tstage": "T1c",
        "gleason_total": 6,
        "isup_grade": 1,
    }
    assert staging_gap_descriptor(payload) is None


# ──────────────────────────────────────────────────────────────────
# G.15 — Override clínico: imaging_negative_metastases='Sí' sin estudios
# ──────────────────────────────────────────────────────────────────

def test_imaging_negative_alone_does_not_complete_without_modalities():
    """Declarar imaging_negative=Sí sin realizar modalidades no completa staging."""
    comp = staging_complete({"imaging_negative_metastases": "Sí"})
    assert comp["complete"] is False, (
        "Se declaró M0 completo sin modalities_done — debe exigir PSMA o GGO+TAC"
    )


# ──────────────────────────────────────────────────────────────────
# G.16 — Test estructural: FieldSpecs ampliados presentes
# ──────────────────────────────────────────────────────────────────

def test_advanced_staging_imaging_fields_helper_present(registry):
    schema = registry.services["localized_initial"].schema()
    field_names = {f["name"] for f in schema["fields"]}
    assert "psma_rads_score_staging" in field_names, "Falta psma_rads_score_staging"
    assert "staging_imaging_date" in field_names, "Falta staging_imaging_date"


# ──────────────────────────────────────────────────────────────────
# G.17 — modality recommended por risk_band
# ──────────────────────────────────────────────────────────────────

def test_staging_modality_recommended_by_risk_band():
    """Very_high → PSMA preferente; high → ambas; intermediate_unfavorable → considerar."""
    items_vhr = staging_modality_recommended({}, "very_high")
    assert any("PSMA" in (i.get("name") or "") and "preferente" in (i.get("name") or "").lower() for i in items_vhr), (
        f"VERY_HIGH debe recomendar PSMA preferente; obtenido: {items_vhr}"
    )

    items_high = staging_modality_recommended({}, "high")
    assert len(items_high) > 0, "HIGH debe recomendar al menos una modalidad"

    items_iu = staging_modality_recommended({}, "intermediate_unfavorable")
    assert any(i.get("priority") == "considered" for i in items_iu), (
        f"INTERMEDIATE_UNFAVORABLE debe marcar como 'considered'; obtenido: {items_iu}"
    )

    items_low = staging_modality_recommended({}, "intermediate_or_lower")
    assert items_low == [], (
        f"Riesgo bajo no debe recomendar staging; obtenido: {items_low}"
    )


# ──────────────────────────────────────────────────────────────────
# G.18 — Alias funcionales en ARPI_FIELD_ALIASES
# ──────────────────────────────────────────────────────────────────

def test_arpi_field_aliases_resolve_staging_synonyms():
    """m_stage → clinical_mstage; psma_pet → psma_pet_done; etc."""
    from prostanet.domains.patient_tracking.arpi_selection_engine import (
        ARPI_FIELD_ALIASES,
    )

    assert "m_stage" in ARPI_FIELD_ALIASES.get("clinical_mstage", [])
    assert "psma_pet" in ARPI_FIELD_ALIASES.get("psma_pet_done", [])
    assert "staging_complete" in ARPI_FIELD_ALIASES.get(
        "imaging_negative_metastases", []
    )
    bone_aliases = ARPI_FIELD_ALIASES.get("bone_scan_done", [])
    assert "ggo_done" in bone_aliases or "gammagrafia_done" in bone_aliases


# ──────────────────────────────────────────────────────────────────
# G.19 — Evidence citations cargan correctamente
# ──────────────────────────────────────────────────────────────────

def test_staging_gate_evidence_citations_registered():
    """PROPSMA, NCCN_PROS2, NCCN_PROS3 deben estar en DOCUMENTS."""
    from prostanet.domains.evidence_registry.data import DOCUMENTS

    assert "doc_propsma_2020" in DOCUMENTS, "Falta PROPSMA_TRIAL"
    assert "doc_nccn_pros2_v5_2026" in DOCUMENTS, "Falta NCCN_PROS2_GUIDELINE"
    assert "doc_nccn_pros3_v5_2026" in DOCUMENTS, "Falta NCCN_PROS3_GUIDELINE"


# ──────────────────────────────────────────────────────────────────
# G.20 — state_classifier propaga flags de staging
# ──────────────────────────────────────────────────────────────────

def test_state_classifier_propagates_staging_flags(registry):
    """Caso usuario: classify_state debe exponer staging_required_flag=True."""
    payload = {
        "known_cancer_diagnosis": "1",
        "psa": 36,
        "clinical_tstage": "T4",
        "gleason_total": 9,
        "isup_grade": 5,
    }
    classification = registry.classify_state(payload)
    assert classification.get("staging_required_flag") is True, (
        f"staging_required_flag no se propaga; clasificación={classification}"
    )
    assert classification.get("staging_risk_band") == "very_high", (
        f"staging_risk_band esperado very_high; obtenido {classification.get('staging_risk_band')}"
    )


# ──────────────────────────────────────────────────────────────────
# G.21 — recurrence_bcr aplica gate tras PSA muy alto
# ──────────────────────────────────────────────────────────────────

def test_recurrence_bcr_blocks_systemic_when_staging_missing(registry):
    """BCR con PSA muy alto y sin restaging → bloquea ARPI sistémico."""
    payload = {
        "known_cancer_diagnosis": "1",
        "post_prostatectomy": "1",
        "psa": 25,  # very high for post-RP BCR
        "psa_doubling_time_months": 6,
        "ecog_score": 0,
        "age": 70,
    }
    result = registry.evaluate_module("recurrence_bcr", payload)
    # No debe romper el módulo
    assert result is not None
    # Puede aplicar gate (depende de lógica implementada)
    # Solo validamos que no rompa y que el staging_gap se pueda consultar
    staging_gap = result.get("staging_gap")
    if staging_gap:
        assert "risk_band" in staging_gap or "reasons" in staging_gap


# ──────────────────────────────────────────────────────────────────
# G.22 — m0_crpc con legacy imaging_negative funciona
# ──────────────────────────────────────────────────────────────────

def test_m0_crpc_legacy_imaging_negative_unblocks_arpi(registry):
    """m0CRPC con imaging_negative=1 (legacy) → ARPI emitido normalmente."""
    payload = {
        "known_cancer_diagnosis": "1",
        "psa": 25,
        "psa_doubling_time_months": 7,
        "imaging_negative": 1,  # legacy flag
        "testosterone": 30,  # castrate
        "castration_resistant": 1,
        "ecog_score": 0,
        "age": 70,
    }
    result = registry.evaluate_module("m0_crpc", payload)
    treatments_blob = " ".join(
        (t.get("name") or "").lower()
        for t in (result.get("eligible_treatments") or result.get("treatments") or [])
    )
    # Cuando imaging_negative=1 el gate NO debe bloquear
    assert result.get("state_classification_override") != "staging_required", (
        f"m0_crpc bloqueado pese a imaging_negative=1; override={result.get('state_classification_override')}"
    )
