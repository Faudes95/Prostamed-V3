# IEC 62304 §5.7 (System testing)
"""Tests EPIC 10A — Real-world patient validation (10 casos representativos).

Valida que el catálogo de trayectorias clínicas (`build_trajectory_catalog`)
expone 10 trayectorias `scenario_family="epic10_real_world"` con oráculo
clínico defendible (estado clasificado + tratamiento prioritario +
referencia a guía + evidencia con trial PMID).

A diferencia de EPIC 9 (que valida GAPs específicos), estas trayectorias
representan **casos de consulta típica** distribuidos sobre 18 estadios
NCCN. Validan el contrato end-to-end del CDE Auditable: state classifier
→ rules NCCN/EAU → trial matcher → recomendación humanizada.

Cobertura:
  1. VL risk active surveillance (PIVOT, ProtecT 15y, PRECISE)
  2. IF risk definitive local (EORTC 22991, ProtecT)
  3. VH risk combined modality (STAMPEDE M0)
  4. BCR post-RP salvage RT+ADT (GETUG-AFU 16, RADICALS-RT)
  5. BCR post-RT Phoenix met salvage (AUA/ASTRO/SUO 2024)
  6. mHSPC high volume sync triplet (ARASENS, PEACE-1)
  7. mHSPC oligometachronous MDT (STAMPEDE-H, STOMP)
  8. m0CRPC high-risk PSADT (ARAMIS, SPARTAN, PROSPER)
  9. m1CRPC BRCA2+ PSMA-PET+ (PROfound, VISION)
 10. m1CRPC heavily pretreated AR-V7+ (PROPHECY, KEYNOTE-365)
"""
from __future__ import annotations

import re
from collections import Counter

import pytest

from prostanet.domains.clinical_validation import build_trajectory_catalog


EPIC10_FAMILY = "epic10_real_world"
EPIC10_EXPECTED_COUNT = 10

EPIC10_EXPECTED_SCENARIO_IDS = {
    "epic10_very_low_active_surveillance",
    "epic10_intermediate_favorable_definitive_local",
    "epic10_very_high_combined_modality",
    "epic10_post_rp_bcr_salvage_rt_adt",
    "epic10_post_rt_bcr_phoenix_salvage_candidate",
    "epic10_mhspc_high_volume_sync_triplet",
    "epic10_mhspc_oligometachronous_mdt_sbrt",
    "epic10_m0crpc_high_risk_arpi",
    "epic10_m1crpc_brca2_olaparib_or_lu177",
    "epic10_m1crpc_endline_arv7_reassessment",
}

# Estados canónicos esperados (cobertura distributiva sobre 18 estadios NCCN).
EPIC10_EXPECTED_STATES_COVERAGE = {
    "localized_initial",                 # #1, #2, #3 (VL/IF/VH)
    "recurrence_bcr",                    # #4 (post-RP BCR)
    "post_radiotherapy_or_local_salvage", # #5 (post-RT Phoenix met)
    "mcspc_high_volume_sync",            # #6
    "mcspc_oligo_metachronous",          # #7
    "m0_crpc",                           # #8
    "m1_crpc",                           # #9, #10
}

PMID_RE = re.compile(r"PMID\s*\d{7,9}")
TRIAL_NAME_RE = re.compile(r"(PIVOT|ProtecT|STAMPEDE|GETUG|RADICALS|AUA/ASTRO|ARASENS|PEACE|STOMP|ORIOLE|ARAMIS|SPARTAN|PROSPER|PROfound|VISION|PROpel|PROPHECY|KEYNOTE|CARD|CHAARTED|EORTC)", re.IGNORECASE)


def _epic10_cases():
    trajectories = build_trajectory_catalog()
    return [t for t in trajectories if t.get("scenario_family") == EPIC10_FAMILY]


def test_epic10_catalog_contains_ten_real_world_cases():
    cases = _epic10_cases()
    assert len(cases) == EPIC10_EXPECTED_COUNT, (
        f"EPIC 10 esperaba {EPIC10_EXPECTED_COUNT} trayectorias real-world, "
        f"encontró {len(cases)}."
    )


def test_epic10_scenario_ids_are_unique_and_match_expected_set():
    cases = _epic10_cases()
    scenario_ids = {c["scenario_id"] for c in cases}
    assert scenario_ids == EPIC10_EXPECTED_SCENARIO_IDS, (
        "EPIC 10 scenario_ids divergen del set canónico documentado.\n"
        f"  Extras inesperados: {scenario_ids - EPIC10_EXPECTED_SCENARIO_IDS}\n"
        f"  Faltantes: {EPIC10_EXPECTED_SCENARIO_IDS - scenario_ids}"
    )


def test_epic10_distribution_covers_canonical_nccn_states():
    cases = _epic10_cases()
    modules = {c["module_id"] for c in cases}
    assert modules >= EPIC10_EXPECTED_STATES_COVERAGE, (
        f"EPIC 10 cobertura distributiva incompleta. "
        f"Faltan estados: {EPIC10_EXPECTED_STATES_COVERAGE - modules}"
    )


@pytest.mark.parametrize("scenario_id", sorted(EPIC10_EXPECTED_SCENARIO_IDS))
def test_epic10_case_has_defensible_clinical_oracle(scenario_id: str):
    """Cada caso EPIC 10 debe declarar:
    - expected_effective_state (clasificación de estado clínico)
    - expected_action_label OR expected_action_contains (tratamiento)
    - expected_guideline_basis_any (referencia a guía clínica)
    - epic10_evidence (trial pivotal con PMID o referencia canónica)
    - epic10_scenario_summary (resumen humano-legible de 1 línea)
    """
    cases = _epic10_cases()
    case = next((c for c in cases if c["scenario_id"] == scenario_id), None)
    assert case is not None, f"Trayectoria EPIC 10 no encontrada: {scenario_id}"

    oracle = case.get("clinical_oracle") or {}
    assert oracle.get("expected_effective_state"), (
        f"{scenario_id}: clinical_oracle.expected_effective_state es requerido."
    )

    action_declared = bool(
        oracle.get("expected_action_label")
        or oracle.get("expected_action_contains")
        or oracle.get("expected_selected_therapy_aliases")
    )
    assert action_declared, (
        f"{scenario_id}: clinical_oracle debe declarar tratamiento esperado "
        "(expected_action_label / expected_action_contains / "
        "expected_selected_therapy_aliases)."
    )

    guideline_basis = oracle.get("expected_guideline_basis_any") or []
    assert guideline_basis, (
        f"{scenario_id}: clinical_oracle.expected_guideline_basis_any es requerido "
        "(referencia a NCCN/EAU/AUA section)."
    )
    nccn_or_eau_present = any(
        ("NCCN" in g) or ("EAU" in g) or ("AUA" in g) or ("ESMO" in g)
        for g in guideline_basis
    )
    assert nccn_or_eau_present, (
        f"{scenario_id}: guideline_basis debe referenciar NCCN/EAU/AUA/ESMO. "
        f"Encontrado: {guideline_basis}"
    )

    evidence = oracle.get("epic10_evidence") or ""
    assert evidence, f"{scenario_id}: clinical_oracle.epic10_evidence es requerido."

    summary = oracle.get("epic10_scenario_summary") or ""
    assert summary, f"{scenario_id}: clinical_oracle.epic10_scenario_summary es requerido."
    assert len(summary) <= 200, (
        f"{scenario_id}: summary debe ser <=200 chars, son {len(summary)}."
    )


@pytest.mark.parametrize("scenario_id", sorted(EPIC10_EXPECTED_SCENARIO_IDS))
def test_epic10_evidence_references_trial_or_pmid(scenario_id: str):
    """Cada caso debe referenciar al menos un trial pivotal Y al menos un PMID.

    Esto asegura que el ground truth es defendible: cada recomendación
    está anclada a un estudio pivotal identificable por PMID, no a opinión.
    """
    cases = _epic10_cases()
    case = next((c for c in cases if c["scenario_id"] == scenario_id), None)
    assert case is not None
    evidence = case["clinical_oracle"].get("epic10_evidence") or ""

    assert TRIAL_NAME_RE.search(evidence), (
        f"{scenario_id}: evidencia debe referenciar trial pivotal por nombre. "
        f"Encontrado: '{evidence}'"
    )
    assert PMID_RE.search(evidence), (
        f"{scenario_id}: evidencia debe incluir al menos un PMID con formato "
        f"'PMID 1234567'. Encontrado: '{evidence}'"
    )


@pytest.mark.parametrize("scenario_id", sorted(EPIC10_EXPECTED_SCENARIO_IDS))
def test_epic10_baseline_payload_has_minimum_clinical_inputs(scenario_id: str):
    """Cada baseline_payload debe tener inputs clínicos mínimos para que
    un urólogo pueda reproducir mentalmente la decisión.

    Mínimos:
      - patient_age O información de edad/expectativa
      - psa O testosterone (al menos un marcador)
      - Información de estadificación o estado (Gleason/T/N/M, ADT context,
        prior treatments) — varía por estado
    """
    cases = _epic10_cases()
    case = next((c for c in cases if c["scenario_id"] == scenario_id), None)
    assert case is not None
    payload = case.get("baseline_payload") or {}

    has_age = "patient_age" in payload or "life_expectancy_years" in payload
    assert has_age, f"{scenario_id}: baseline_payload necesita patient_age o life_expectancy_years."

    has_marker = "psa" in payload or "testosterone" in payload
    assert has_marker, f"{scenario_id}: baseline_payload necesita PSA o testosterona."

    has_staging_or_history = (
        "gleason_primary" in payload
        or "isup_grade" in payload
        or "clinical_t_stage" in payload
        or "pathologic_t_stage" in payload
        or "metastasis_site" in payload
        or "prior_radical_prostatectomy" in payload
        or "prior_radiation" in payload
        or "current_adt_context" in payload
    )
    assert has_staging_or_history, (
        f"{scenario_id}: baseline_payload necesita información de estadificación/historial "
        "(Gleason/TNM/ISUP, metástasis o prior treatment)."
    )


def test_epic10_state_distribution_balances_disease_spectrum():
    """La distribución de estados sobre las 10 trayectorias debe cubrir
    todo el spectrum de la enfermedad — no concentrarse en una etapa.

    Distribución esperada:
      - Localized (VL/IF/VH): 3 casos en module_id='localized_initial'
      - Recurrence (BCR post-RP + post-RT): 2 casos
      - mHSPC (high vol + oligo): 2 casos
      - CRPC (m0 + m1×2): 3 casos
    """
    cases = _epic10_cases()
    module_counts = Counter(c["module_id"] for c in cases)
    assert module_counts["localized_initial"] == 3
    assert module_counts["recurrence_bcr"] == 1
    assert module_counts["post_radiotherapy_or_local_salvage"] == 1
    assert module_counts["mcspc_high_volume_sync"] == 1
    assert module_counts["mcspc_oligo_metachronous"] == 1
    assert module_counts["m0_crpc"] == 1
    assert module_counts["m1_crpc"] == 2


def test_epic10_hard_critical_cases_match_high_stakes_decisions():
    """Los casos con `hard_critical=True` deben ser los de mayor impacto
    de decisión (errores aquí cambian outcome del paciente):
      - #2 IF risk definitive local
      - #3 VH risk combined modality
      - #4 BCR post-RP salvage
      - #5 BCR post-RT salvage candidate
      - #6 mHSPC high volume triplet
      - #8 m0CRPC ARPI
      - #9 m1CRPC BRCA2+ targeted
    """
    cases = _epic10_cases()
    hard_critical_ids = {
        c["scenario_id"]
        for c in cases
        if c["clinical_oracle"].get("hard_critical") is True
    }
    expected_hard_critical = {
        "epic10_intermediate_favorable_definitive_local",
        "epic10_very_high_combined_modality",
        "epic10_post_rp_bcr_salvage_rt_adt",
        "epic10_post_rt_bcr_phoenix_salvage_candidate",
        "epic10_mhspc_high_volume_sync_triplet",
        "epic10_m0crpc_high_risk_arpi",
        "epic10_m1crpc_brca2_olaparib_or_lu177",
    }
    assert hard_critical_ids == expected_hard_critical, (
        f"hard_critical EPIC 10 divergente.\n"
        f"  Inesperados marcados como hard_critical: {hard_critical_ids - expected_hard_critical}\n"
        f"  Faltantes hard_critical: {expected_hard_critical - hard_critical_ids}"
    )


def test_epic10_visits_have_visit_date_and_payload():
    """Cada trayectoria EPIC 10 debe tener al menos 1 visita longitudinal
    con `visit_date` y `payload` (contrato del harness).
    """
    cases = _epic10_cases()
    for case in cases:
        visits = case.get("visits") or []
        assert visits, f"{case['scenario_id']}: requiere al menos 1 visita."
        for visit in visits:
            assert visit.get("visit_date"), (
                f"{case['scenario_id']}: visita sin visit_date."
            )
            assert visit.get("payload"), (
                f"{case['scenario_id']}: visita sin payload."
            )
            assert visit.get("oracle"), (
                f"{case['scenario_id']}: visita sin oracle."
            )


def test_epic10_endpoint_serves_real_world_cases(app_client):
    """E2E — el endpoint `/api/validation/trajectories` debe servir los 10
    casos EPIC 10 con su scenario_family correcto y oracle accesible.
    """
    client, _ = app_client
    response = client.get("/api/validation/trajectories")
    assert response.status_code == 200
    payload = response.get_json()
    epic10_items = [
        t for t in payload["trajectories"]
        if t.get("scenario_family") == EPIC10_FAMILY
    ]
    assert len(epic10_items) == EPIC10_EXPECTED_COUNT
    served_ids = {t["scenario_id"] for t in epic10_items}
    assert served_ids == EPIC10_EXPECTED_SCENARIO_IDS


def test_epic10_summaries_have_decision_today_signal():
    """Cada `epic10_scenario_summary` debe incluir una pista del 'qué hacer'
    (un keyword clínicamente accionable). Verifica que la redacción es
    suficientemente concreta para ser usada como ground truth.
    """
    cases = _epic10_cases()
    action_keywords = (
        "vigilancia", "as", "rp", "prostatect", "rt", "radiotera",
        "salvage", "rescate", "adt", "darolutamida", "apalutamida",
        "enzalutamida", "abiraterona", "docetaxel", "cabazitaxel",
        "olaparib", "talazoparib", "niraparib", "rucaparib",
        "lu-177", "lutecio", "psma", "pembro", "mdt", "sbrt",
        "triplete", "doblete", "ensayo", "re-evaluac", "reevaluac",
    )
    for case in cases:
        summary = (case["clinical_oracle"].get("epic10_scenario_summary") or "").lower()
        assert any(k in summary for k in action_keywords), (
            f"{case['scenario_id']}: summary debe incluir keyword accionable. "
            f"Summary actual: '{summary}'"
        )
