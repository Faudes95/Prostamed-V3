from __future__ import annotations

from typing import Any

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.patient_tracking.psma_imaging import (
    build_psma_decision_impact,
    build_psma_structured_profile_from_payload,
)
from prostanet.domains.patient_tracking.arpi_selection_engine import (
    build_arpi_capture_contract,
    candidate_regimens_for_state,
    evaluate_arpi_candidate,
)
from prostanet.domains.patient_tracking.post_rp_salvage_intensification_builder import (
    build_post_rp_salvage_intensification_profile,
)
from prostanet.domains.patient_tracking.therapeutic_family_engine import (
    build_active_regimen_monitoring_package,
    build_comparative_bundle,
    build_family_profile,
    build_ranked_option,
    build_sequence_transition_bundle,
)
from prostanet.domains.recurrence_bcr.rules_eau import classify_recurrence_eau
from prostanet.domains.recurrence_bcr.rules_nccn import classify_recurrence
from prostanet.domains.recurrence_bcr.schemas import RECURRENCE_BCR_SCHEMA
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.phase7_decision_bundles import build_post_rp_phase7_bundle
from prostanet.shared.pivotal_contraindication_gates import (
    apply_pivotal_contraindication_gates,
)
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result
from prostanet.shared.staging_requirements_engine import (
    staging_complete,
    staging_required,
)


def _flag_truthy(value: Any) -> bool:
    """Auditoría Pacientes Insignia 2026-04-21 — normaliza flags booleans
    ES-médica / legacy a bool real (Sí/Si/1/yes/true)."""
    return str(value or "").strip().lower() in {"sí", "si", "1", "yes", "true"}


def _late_rt_tier(text: Any) -> int:
    """Auditoría Pacientes Insignia 2026-04-21 (§C.2) — traduce el FieldSpec
    CTCAE v5 late_rt_toxicity_gu/gi a tier 0-5. Alias boolean legacy →
    tier 2 por compatibilidad con perfiles insignia RADICALS-RT."""
    t = str(text or "").strip().lower()
    if not t:
        return 0
    if "grado 5" in t or "muerte" in t:
        return 5
    if "grado 4" in t:
        return 4
    if "grado 3" in t:
        return 3
    if "grado 2" in t:
        return 2
    if "grado 1" in t:
        return 1
    if t in {"sin toxicidad", "no", "0", "false"}:
        return 0
    if t in {"sí", "si", "1", "yes", "true"}:
        return 2
    return 0


def _treatment_is_rt_based(tx: dict) -> bool:
    """Detecta si un tratamiento emitido implica radioterapia externa/pélvica
    (salvage RT, re-irradiación, RT pélvica electiva, SBRT, brachy)."""
    name_lower = str(tx.get("name") or "").lower()
    code_upper = str(tx.get("regimen_code") or "").upper()
    family_code = str(tx.get("family_code") or "").lower()
    rt_name_hits = (
        "radioterapia" in name_lower
        or "rescate" in name_lower and "rt" in name_lower
        or "salvage rt" in name_lower
        or "sbrt" in name_lower
        or "irradiaci" in name_lower
        or "brachy" in name_lower
    )
    rt_code_hits = (
        code_upper.startswith("SALVAGE_RT")
        or "RT_" in code_upper
        or code_upper in {"PSMA_GUIDED_MDT", "LOCAL_MDT", "RESTAGING"}
        and family_code == "salvage_rt_family"
    )
    return bool(rt_name_hits or rt_code_hits or family_code == "salvage_rt_family")


class RecurrenceBCRService:
    module_id = "recurrence_bcr"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return RECURRENCE_BCR_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        nccn = classify_recurrence(payload)
        eau = classify_recurrence_eau(payload)
        comparison = self.comparison.compare(nccn, eau)
        psma_profile = (
            build_psma_structured_profile_from_payload(payload)
            if str(payload.get("psma_pet_done", "0")) == "1"
            else {"available": False}
        )
        psma_impact = build_psma_decision_impact(psma_profile, state=self.module_id, patient={"baseline": payload})
        psa_current = float(payload.get("psa_current", payload.get("psa", 0)) or 0)
        psadt = float(payload.get("psadt_months", 0) or 0)
        durations = []
        not_recommended = []
        trials = []
        missing_inputs = [field for field in ["psa_current", "psadt_months"] if str(payload.get(field, "")).strip() == ""]
        family_profiles: dict[str, dict] = {}
        family_order: list[str] = []
        salvage_variants: list[dict] = []
        local_mdt_variants: list[dict] = []
        arpi_variants: list[dict] = []
        observation_variants: list[dict] = []
        confidence_low = psma_impact.get("confidence") == "low"
        psma_pattern = str(psma_impact.get("clinical_pattern") or "").strip()
        systemic_redirect = psma_pattern == "diseminado"
        salvage_feasible = bool(nccn.get("salvage_local_feasible"))
        local_salvage_candidate = bool(nccn.get("local_salvage_candidate"))
        psma_pending = bool(nccn.get("psma_pet_recommended")) and not bool(nccn.get("psma_pet_done"))
        post_rp_salvage_profile = build_post_rp_salvage_intensification_profile(
            payload,
            psma_impact=psma_impact,
        )
        arpi_candidates = candidate_regimens_for_state(self.module_id, payload)
        arpi_capture_contract = build_arpi_capture_contract(
            self.module_id,
            payload,
            candidate_regimens=arpi_candidates,
        )
        missing_inputs.extend(list(arpi_capture_contract.get("arpi_missing_inputs") or []))
        missing_inputs.extend(list(arpi_capture_contract.get("arpi_stale_inputs") or []))
        missing_inputs = list(dict.fromkeys(item for item in missing_inputs if item))

        if psma_pending:
            psma_companion_reason = (
                "La PSMA debe hacerse de forma urgente para definir lecho solo versus lecho + pelvis, sin retrasar el salvage si resulta negativa."
                if post_rp_salvage_profile.get("psma_restaging_role") == "urgent_companion"
                else (nccn.get("psma_pet_reason") or "La PSMA cambia la decisión cuando el rescate local no es trivial.")
            )
            observation_variants.append(
                build_ranked_option(
                    name="Estadificación de rescate guiada por PET/CT con PSMA",
                    regimen_code="PSMA_RESTAGING",
                    rank=len(observation_variants) + 1,
                    priority="eligible",
                    eligibility_status="eligible_with_caution",
                    family_code="observation_family",
                    molecule_or_backbone="PSMA-PET de rescate",
                    description="La imagen dirigida debe realizarse cuando cambia el alcance del salvage o redirige fuera del rescate local.",
                    route="Imagen molecular",
                    schedule=psma_companion_reason,
                    metadata_source="guideline_backbone",
                    why_this_rank=[psma_companion_reason],
                    selection_rationale=[psma_companion_reason],
                )
            )

        if nccn["label"] == "BCR2 N0M0":
            if nccn["enza_match"]:
                arpi_meta = evaluate_arpi_candidate(
                    self.module_id,
                    payload,
                    "ADT_ENZALUTAMIDE",
                    candidate_regimens=arpi_candidates,
                )
                preferred = (
                    arpi_meta.get("eligibility_status") == "preferred"
                    and arpi_meta.get("preference_confidence") == "definitive"
                )
                notes = [
                    "Patrón de segunda recurrencia bioquímica de alto riesgo con imagen convencional M0 y sin opción pélvica curativa dirigida.",
                    str(arpi_meta.get("benefit_basis") or ""),
                ]
                notes.extend(list(arpi_meta.get("safety_rationale") or []))
                if arpi_meta.get("required_missing_fields"):
                    notes.append(
                        "La preferencia molecular sigue provisional hasta completar: "
                        + ", ".join(arpi_meta.get("required_missing_fields") or [])
                    )
                arpi_variants.append(
                    build_ranked_option(
                        name="Enzalutamida con o sin leuprorelina",
                        regimen_code="ADT_ENZALUTAMIDE",
                        rank=1,
                        priority="preferred" if preferred else "eligible",
                        eligibility_status=(
                            "preferred"
                            if preferred
                            else str(arpi_meta.get("eligibility_status") or "eligible_with_caution")
                        ),
                        family_code="arpi_family",
                        molecule_or_backbone="Enzalutamida",
                        notes=" ".join(item for item in notes if item),
                        why_this_rank=["La intensificación sistémica tipo EMBARK solo sube cuando ya no queda rescate local con intención curativa."],
                        selection_rationale=["El escenario cumple patrón BCR2 de alto riesgo no metastásico y la vía pélvica curativa ya no domina."],
                        benefit_basis=arpi_meta.get("benefit_basis"),
                        benefit_endpoint_used=arpi_meta.get("benefit_endpoint_used"),
                        benefit_maturity=arpi_meta.get("benefit_maturity"),
                        benefit_support=arpi_meta.get("benefit_support"),
                        safety_drivers_used=arpi_meta.get("safety_drivers_used"),
                        required_missing_fields=arpi_meta.get("required_missing_fields"),
                        stale_inputs=arpi_meta.get("stale_inputs"),
                        preference_confidence=arpi_meta.get("preference_confidence"),
                    )
                )
                trials.append({"trial": "EMBARK", "match": True})
            # PRESTO (AFT-19, Aggarwal JCO 2023;41:3253) — apalutamida ± abiraterona
            # en BCR alto-riesgo PSADT ≤9 m post-RP (± SRT previo), PSA ≥0.5 ng/mL.
            # Se emite como opción experimental (categoría 2B) únicamente cuando ya
            # no queda salvage local curativo, para no contradecir la advertencia
            # genérica contra uso rutinario (not_recommended.extend abajo).
            if nccn.get("apalutamide_experimental"):
                prior_secondary_rt = str(payload.get("prior_secondary_rt", "0")) == "1"
                presto_setting = (
                    "BCR2 N0M0 post-RP con SRT previa y PSADT ≤9 m"
                    if prior_secondary_rt
                    else "BCR2 N0M0 post-RP con PSADT ≤9 m sin vía de rescate local curativa"
                )
                arpi_variants.append(
                    build_ranked_option(
                        name="Apalutamida + ADT (PRESTO, experimental)",
                        regimen_code="ADT_APALUTAMIDE_PRESTO",
                        rank=len(arpi_variants) + 1,
                        priority="eligible",
                        eligibility_status="eligible_with_caution",
                        family_code="arpi_family",
                        molecule_or_backbone="Apalutamida",
                        description=(
                            "Intensificación experimental basada en PRESTO/AFT-19 para BCR "
                            "alto-riesgo PSADT ≤9 m cuando el salvage local ya no es "
                            "curativo."
                        ),
                        route="Oral",
                        schedule="Apalutamida 240 mg/día + ADT concomitante",
                        metadata_source="trial_backbone",
                        evidence_tags=["PRESTO", "AFT-19"],
                        notes=(
                            "PRESTO mostró mejora significativa en PSA-PFS vs ADT sola "
                            f"en {presto_setting}. Categoría 2B fuera del estándar NCCN; "
                            "requiere documentar PSADT y compartir decisión con el paciente."
                        ),
                        why_this_rank=[
                            "La intensificación PRESTO sube solo cuando el rescate local "
                            "con intención curativa ya no es una vía viable."
                        ],
                        selection_rationale=[
                            "El perfil cumple PRESTO (BCR post-RP con PSADT ≤9 m, PSA ≥0.5 "
                            "ng/mL) y la vía pélvica curativa no domina."
                        ],
                        caution_flags=[
                            "Evidencia categoría 2B / experimental — no es estándar NCCN v5.2026.",
                            "Monitorizar exantema, hipotiroidismo, fatiga y fracturas (perfil PRESTO).",
                        ],
                    )
                )
                # Brazo triplete de PRESTO — apa + abi + ADT. Se ofrece como
                # alternativa cuando existen drivers moleculares o biológicos que
                # justifican intensificación dual de eje androgénico.
                arpi_variants.append(
                    build_ranked_option(
                        name="Apalutamida + Abiraterona + ADT (PRESTO triplete, experimental)",
                        regimen_code="ADT_APALUTAMIDE_ABIRATERONE_PRESTO",
                        rank=len(arpi_variants) + 1,
                        priority="eligible",
                        eligibility_status="eligible_with_caution",
                        family_code="arpi_family",
                        molecule_or_backbone="Apalutamida + Abiraterona",
                        description=(
                            "Brazo triplete de PRESTO (apa + abi + prednisona + ADT) para "
                            "BCR alto-riesgo PSADT ≤9 m sin vía local curativa."
                        ),
                        route="Oral",
                        schedule=(
                            "Apalutamida 240 mg/día + Abiraterona 1000 mg/día + "
                            "Prednisona 5 mg/día + ADT concomitante"
                        ),
                        metadata_source="trial_backbone",
                        evidence_tags=["PRESTO", "AFT-19"],
                        notes=(
                            "El brazo triplete mejoró PSA-PFS adicional sobre ADT sola; "
                            "considérese cuando la carga biológica sugiere beneficio de "
                            "supresión androgénica dual. Requiere prednisona de base y "
                            "vigilancia hepática/mineralocorticoide."
                        ),
                        why_this_rank=[
                            "El triplete se reserva para casos donde la agresividad biológica "
                            "o la preferencia del paciente favorecen bloqueo androgénico doble."
                        ],
                        selection_rationale=[
                            "Brazo experimental de PRESTO con beneficio adicional sobre apa + ADT."
                        ],
                        caution_flags=[
                            "Toxicidad combinada ARPI + CYP17 — monitorizar hepático, potasio, tensión arterial.",
                            "Prednisona crónica añade riesgo metabólico y óseo.",
                        ],
                    )
                )
                trials.append({"trial": "PRESTO", "match": True})
            not_recommended.extend([
                "No exponga opciones sistémicas de segunda recurrencia bioquímica cuando no se cumplen los criterios del escenario.",
                "No trate apalutamida más terapia de privación androgénica como opción rutinaria de segunda recurrencia bioquímica sin cumplir criterios PRESTO (PSADT ≤9 m, PSA ≥0.5 ng/mL, sin vía local curativa).",
            ])
            if arpi_variants:
                family_profiles["arpi_family"] = build_family_profile(
                    family_code="arpi_family",
                    ordered_regimens=arpi_variants,
                    context={
                        "eligibility_status": (
                            "eligible"
                            if arpi_capture_contract.get("arpi_preference_readiness") == "ready"
                            else "conditional"
                        ),
                        "preference_drivers": ["Patrón EMBARK-like documentado", "No persiste una vía local curativa dominante"],
                        "missing_inputs": list(arpi_capture_contract.get("arpi_missing_inputs") or []),
                        "stale_inputs": list(arpi_capture_contract.get("arpi_stale_inputs") or []),
                        "winner_reason": "La familia ARPI solo lidera si el caso ya pertenece a segunda recurrencia bioquímica de alto riesgo sin vía local curativa.",
                        "why_not_preferred": "No debe adelantar salvage local cuando todavía existe una ruta pélvica con intención curativa.",
                    },
                )
                family_order.append("arpi_family")
            if observation_variants:
                family_profiles["observation_family"] = build_family_profile(
                    family_code="observation_family",
                    ordered_regimens=observation_variants,
                    context={
                        "eligibility_status": "conditional",
                        "missing_inputs": ["psma_pet_done"] if psma_pending else [],
                        "winner_reason": "La reestadificación sigue visible porque puede cambiar la magnitud de la intensificación o excluir focos aún rescatables.",
                    },
                )
                family_order.append("observation_family")
        elif nccn["label"] == "Post-RP recurrence":
            salvage_preference = str(post_rp_salvage_profile.get("salvage_intensification_preference") or "rt_alone")
            high_risk_post_rp_salvage = bool(post_rp_salvage_profile.get("high_risk_post_rp_salvage"))
            very_high_risk_post_rp_salvage = bool(post_rp_salvage_profile.get("very_high_risk_post_rp_salvage"))
            pelvic_rt_role = str(post_rp_salvage_profile.get("pelvic_rt_role") or "not_indicated")
            adt_duration_band = str(post_rp_salvage_profile.get("adt_duration_band") or "none")
            high_risk_feature_keys = list(post_rp_salvage_profile.get("high_risk_feature_keys") or [])
            companion_actions = list(
                post_rp_salvage_profile.get("companion_actions_required_for_preferred_regimen") or []
            )
            if salvage_feasible and not systemic_redirect:
                salvage_variants.append(
                    build_ranked_option(
                        name="Radioterapia de rescate temprana",
                        regimen_code="SALVAGE_RT_ALONE",
                        rank=1,
                        priority="preferred" if salvage_preference == "rt_alone" else "eligible",
                        eligibility_status="preferred" if salvage_preference == "rt_alone" else "eligible_nonpreferred",
                        family_code="salvage_rt_family",
                        molecule_or_backbone="Radioterapia de rescate temprana",
                        description="Rescate del lecho prostático cuando la ventana local sigue abierta.",
                        dose="64-66 Gy al lecho prostático",
                        route="Radioterapia externa",
                        schedule="20-33 fracciones según planificación",
                        component_drugs=[{"drug_name": "Radioterapia de rescate", "dose": "64-66 Gy", "route": "Radioterapia externa", "schedule": "20-33 fracciones"}],
                        metadata_source="guideline_backbone",
                        # EPIC 28.7 (GodiBot G45 HIGH) — added missing trials.
                        # RAVES (Kneebone Lancet Oncol 2020 PMID 32702280): adjuvant
                        # vs early salvage RT equipoise — early salvage preferred
                        # when PSA <0.5 (less toxicity, equivalent outcomes).
                        # Tilki BJU Int 2020 PMID 32568627: early <PSA 0.5 vs late.
                        evidence_tags=[
                            "RADICALS-RT Parker Lancet 2020 PMID 33002429",
                            "RAVES Kneebone Lancet Oncol 2020 PMID 32702280",
                            "ARTISTIC pooled analysis",
                            "Tilki BJU Int 2020 PMID 32568627 (early PSA <0.5 vs late)",
                        ],
                        notes=(
                            "La RT sola permanece visible cuando la ventana curativa post-RP sigue abierta, "
                            "pero deja de liderar si ya existen rasgos de alto riesgo que favorecen intensificación hormonal."
                        ),
                        why_this_rank=[
                            "La ventana curativa post-RP sigue abierta y el salvage temprano mantiene prioridad."
                            if salvage_preference == "rt_alone"
                            else "La RT sola ya no lidera porque los high-risk features post-RP favorecen intensificar con ADT."
                        ],
                        selection_rationale=[
                            "El carril dominante sigue siendo salvage local mientras no exista redirector sistémico explícito."
                        ],
                        caution_flags=(
                            ["No debe ser la salida automática cuando PSA >=0.7 ng/mL u otros high-risk features ya empujan a SRT + ADT."]
                            if high_risk_post_rp_salvage
                            else []
                        ),
                    )
                )
                salvage_variants.append(
                    build_ranked_option(
                        name="Radioterapia de rescate + ADT concomitante",
                        regimen_code="SALVAGE_RT_SHORT_HORMONE",
                        rank=2,
                        priority="preferred" if salvage_preference == "rt_short_adt" else "eligible",
                        eligibility_status="preferred" if salvage_preference == "rt_short_adt" else "eligible_nonpreferred",
                        family_code="salvage_rt_family",
                        molecule_or_backbone="Radioterapia de rescate + ADT corta",
                        description="Salvage RT con ADT concomitante corta tipo GETUG-AFU 16 en pacientes con high-risk features post-RP.",
                        dose="RT 66 Gy + goserelina 10.8 mg SC cada 3 meses",
                        route="Radioterapia externa + Subcutánea",
                        schedule="33 fracciones + 2 aplicaciones",
                        duration="6 meses",
                        component_drugs=[
                            {"drug_name": "Radioterapia de rescate", "dose": "66 Gy", "route": "Radioterapia externa", "schedule": "33 fracciones"},
                            {"drug_name": "Goserelina", "dose": "10.8 mg", "route": "Subcutánea", "schedule": "Cada 3 meses"},
                        ],
                        metadata_source="guideline_backbone",
                        # EPIC 28.7 (GodiBot G45 HIGH) — added GETUG-AFU 17 + NRG-GU002
                        evidence_tags=[
                            "GETUG-AFU 16 Carrie Lancet Oncol 2016 PMID 27375295",
                            "GETUG-AFU 17 Sargos Lancet Oncol 2020 PMID 32502443 (goserelin + SRT vs SRT alone)",
                            "RTOG 9601 Shipley NEJM 2017 PMID 28190862 (bicalutamide adjuvant)",
                            "NRG-GU002 / NRG-GU006 ongoing (apa+SRT)",
                        ],
                        notes=(
                            "La ADT corta es la base preferida cuando el salvage post-RP sigue siendo curativo pero el riesgo biológico "
                            "ya no favorece RT sola."
                        ),
                        why_this_rank=[
                            "Los rasgos de alto riesgo post-RP favorecen añadir ADT concomitante a la SRT."
                            if salvage_preference == "rt_short_adt"
                            else "Permanece elegible cuando la cinética o el riesgo justifican intensificación sin imponer ADT prolongada."
                        ],
                        selection_rationale=["GETUG-AFU 16 apoya ADT corta junto con SRT en BCR post-RP seleccionada."],
                        caution_flags=["Añade carga hormonal y toxicidad metabólica frente a salvage RT sola."],
                    )
                )
                salvage_variants.append(
                    build_ranked_option(
                        name="Radioterapia de rescate pélvica + ADT concomitante",
                        regimen_code="SALVAGE_RT_PELVIC_SHORT_HORMONE",
                        rank=3,
                        priority="preferred" if salvage_preference == "rt_pelvic_short_adt" else "eligible",
                        eligibility_status=(
                            "preferred"
                            if salvage_preference == "rt_pelvic_short_adt"
                            else "eligible_with_caution" if pelvic_rt_role == "consider" else "eligible_nonpreferred"
                        ),
                        family_code="salvage_rt_family",
                        molecule_or_backbone="Radioterapia de rescate + pelvis + ADT corta",
                        description="SRT del lecho con irradiación pélvica electiva y ADT corta cuando la biología o la imagen sugieren riesgo nodal relevante.",
                        dose="Lecho 64.8-70.2 Gy + pelvis 45 Gy + ADT 4-6 meses",
                        route="Radioterapia externa + Supresión androgénica",
                        schedule="RT diaria al lecho/ganglios + ADT corta concomitante",
                        duration="4-6 meses",
                        component_drugs=[
                            {"drug_name": "Radioterapia de rescate al lecho", "dose": "64.8-70.2 Gy", "route": "Radioterapia externa", "schedule": "Fraccionamiento convencional"},
                            {"drug_name": "Irradiación pélvica electiva", "dose": "45 Gy", "route": "Radioterapia externa", "schedule": "Concomitante con el lecho"},
                            {"drug_name": "ADT concomitante", "dose": "4-6 meses", "route": "Supresión androgénica", "schedule": "Concomitante"},
                        ],
                        metadata_source="guideline_backbone",
                        evidence_tags=["SPPORT", "GETUG-AFU 16"],
                        notes="SPPORT apoya ampliar a pelvis y añadir ADT corta cuando el riesgo nodal o la imagen cambian el alcance del rescate.",
                        why_this_rank=[
                            "La combinación lecho + pelvis + ADT corta lidera cuando la biología o la PSMA local/pélvica empujan a ampliar campos."
                            if salvage_preference == "rt_pelvic_short_adt"
                            else "La pelvis queda como opción estructurada cuando el riesgo nodal o la imagen pueden cambiar el campo de SRT."
                        ],
                        selection_rationale=["SPPORT/NRG-RTOG 0534 apoya sumar pelvis y ADT corta en salvage post-RP seleccionado."],
                        caution_flags=(
                            []
                            if pelvic_rt_role in {"consider", "preferred"}
                            else ["No debe liderar si no existe señal clínica o imagenológica de beneficio pélvico."]
                        ),
                    )
                )
                salvage_variants.append(
                    build_ranked_option(
                        name="Radioterapia de rescate + ADT prolongada",
                        regimen_code="SALVAGE_RT_LONG_HORMONE",
                        rank=4,
                        priority="preferred" if salvage_preference == "rt_extended_adt" else "eligible",
                        eligibility_status="preferred" if salvage_preference == "rt_extended_adt" else "eligible_with_caution",
                        family_code="salvage_rt_family",
                        molecule_or_backbone="Radioterapia de rescate + ADT prolongada",
                        description="Salvage RT con ADT prolongada en perfiles de muy alto riesgo o con fuerte justificación biológica.",
                        dose="RT 64.8-66 Gy + ADT 18-24 meses en seleccionados",
                        route="Radioterapia externa + Supresión androgénica",
                        schedule="RT al lecho ± pelvis + ADT prolongada",
                        duration="18-24 meses",
                        component_drugs=[
                            {"drug_name": "Radioterapia de rescate", "dose": "64.8-66 Gy", "route": "Radioterapia externa", "schedule": "Fraccionamiento convencional"},
                            {"drug_name": "ADT prolongada", "dose": "18-24 meses", "route": "Supresión androgénica", "schedule": "Adaptada al riesgo"},
                        ],
                        metadata_source="guideline_backbone",
                        evidence_tags=["RTOG 9601", "RADICALS-HD"],
                        notes=(
                            "La exposición hormonal prolongada se conserva como opción estructurada para very-high risk; "
                            "los detalles históricos de RTOG 9601 quedan como backbone de evidencia, no como receta automática."
                        ),
                        why_this_rank=[
                            "La biología de muy alto riesgo permite discutir ADT prolongada junto con SRT."
                            if salvage_preference == "rt_extended_adt"
                            else "Permanece visible para perfiles de muy alto riesgo, pero no debe desplazar RT + ADT corta sin una justificación real."
                        ],
                        selection_rationale=["RTOG 9601 y RADICALS-HD informan la discusión moderna de duración e intensidad hormonal postoperatoria."],
                        caution_flags=["La exposición hormonal prolongada aumenta toxicidad y no debe universalizarse."],
                    )
                )
                # PSMA-guided local salvage refinement (Post-RP branch): cuando la
                # PSMA muestra patrón local/pélvico con confianza razonable, el
                # salvage sigue abierto pero se refuerza con planificación dirigida
                # por PSMA. Mantiene la simetría con el carril Post-RT (líneas
                # 478-495) para que la ventana curativa se exprese con la misma
                # granularidad independiente del contexto local previo.
                if psma_pattern == "local_pelvic" and not confidence_low:
                    local_mdt_variants.append(
                        build_ranked_option(
                            name="Refuerzo de rescate local guiado por PSMA",
                            regimen_code="PSMA_GUIDED_MDT",
                            rank=len(local_mdt_variants) + 1,
                            priority="eligible",
                            eligibility_status="eligible_nonpreferred",
                            family_code="local_mdt_family",
                            molecule_or_backbone="Rescate local guiado por PSMA",
                            description="PSMA local/pélvica refuerza la planificación del salvage post-RP (lecho vs lecho+pelvis) sin sustituir la reestadificación integral.",
                            route="Radioterapia dirigida / ajuste de campos",
                            schedule="Plan dirigido por PSMA",
                            metadata_source="guideline_backbone",
                            notes="PSMA local/pélvico soporta decisión de lecho solo vs lecho+pelvis en salvage post-RP.",
                            why_this_rank=["La PSMA refuerza el rescate local sin reemplazar la evaluación clínica integral."],
                        )
                    )
            elif psma_pattern == "oligometastatic":
                local_mdt_variants.append(
                    build_ranked_option(
                        name="MDT / rescate multimodal guiado por PSMA",
                        regimen_code="PSMA_GUIDED_MDT",
                        rank=1,
                        priority="eligible",
                        eligibility_status="eligible_with_caution",
                        family_code="local_mdt_family",
                        molecule_or_backbone="MDT / SBRT dirigida",
                        description="Carga oligometastásica limitada que habilita MDT o rescate multimodal en comité oncológico.",
                        dose="SBRT 30-35 Gy en 3-5 fracciones o estrategia multimodal equivalente",
                        route="Radioterapia estereotáxica / multimodal",
                        schedule="Tratamiento local dirigido tras comité",
                        metadata_source="guideline_backbone",
                        notes="PSMA multifocal de bajo burden abre discusión de MDT/SBRT o rescate combinado.",
                        why_this_rank=["El patrón oligometastásico mantiene intención de control dirigido, pero por debajo del rescue local simple."],
                    )
                )
            elif psma_pattern == "diseminado":
                not_recommended.append("No priorizar rescate local aislado cuando el PSMA documenta patrón diseminado o estadio M1b/M1c.")
                observation_variants.append(
                    build_ranked_option(
                        name="Reestadificación sistémica post-PSMA",
                        regimen_code="SYSTEMIC_RESTAGING",
                        rank=len(observation_variants) + 1,
                        priority="preferred",
                        eligibility_status="preferred",
                        family_code="observation_family",
                        molecule_or_backbone="Reestadificación sistémica",
                        description="La distribución por PSMA reduce la plausibilidad de rescue local aislado.",
                        route="Imagen/reclasificación",
                        schedule="Redefinir carril sistémico tras PSMA",
                        metadata_source="guideline_backbone",
                        notes="La distribución por PSMA reduce la plausibilidad de rescate local aislado.",
                        why_this_rank=["Ya existe redirector sistémico explícito y el salvage local deja de ser la opción dominante."],
                    )
                )
            durations.append(
                "Si se agrega terapia de privación androgénica a la radioterapia de rescate, use una duración adaptada al riesgo dentro del rango de 4 a 24 meses."
            )
            if companion_actions:
                durations.extend(companion_actions[:3])
            trials.extend(
                [
                    {"trial": "GETUG-AFU 16", "match": high_risk_post_rp_salvage},
                    {"trial": "SPPORT", "match": pelvic_rt_role in {"consider", "preferred"}},
                    {"trial": "RTOG 9601", "match": adt_duration_band in {"discuss_6_24_months", "18_24_months"}},
                    {"trial": "RADICALS-HD", "match": adt_duration_band in {"discuss_6_24_months", "18_24_months"}},
                ]
            )
            if salvage_variants:
                family_profiles["salvage_rt_family"] = build_family_profile(
                    family_code="salvage_rt_family",
                    ordered_regimens=salvage_variants,
                    context={
                        "eligibility_status": "eligible" if salvage_feasible and not systemic_redirect else "conditional",
                        "missing_inputs": ["salvage_local_feasible"] if not salvage_feasible and not systemic_redirect else [],
                        "caution_drivers": (
                            ["PSMA estructurada incompleta"] if confidence_low else []
                        ) + (
                            ["RT sola deja de ser la mejor salida automática cuando ya existen rasgos de alto riesgo post-RP."]
                            if high_risk_post_rp_salvage
                            else []
                        ),
                        "preference_drivers": list(post_rp_salvage_profile.get("guideline_rationale") or []),
                        "winner_reason": (
                            "La familia de salvage sigue liderando, pero en post-RP high-risk debe intensificarse con ADT y considerar pelvis cuando el contexto lo sostiene."
                            if high_risk_post_rp_salvage
                            else "La familia de salvage sigue liderando mientras la vía local curativa permanezca plausible."
                        ),
                        "why_not_preferred": (
                            "RT sola solo debe liderar en salvage post-RP sin high-risk features claros."
                            if high_risk_post_rp_salvage
                            else "Solo pierde precedencia si la PSMA o la factibilidad local redirigen fuera del carril curativo local."
                        ),
                        "ranking_trace": list(post_rp_salvage_profile.get("historical_trial_templates_applicable") or []),
                    },
                )
                family_order.append("salvage_rt_family")
            if local_mdt_variants:
                family_profiles["local_mdt_family"] = build_family_profile(
                    family_code="local_mdt_family",
                    ordered_regimens=local_mdt_variants,
                    context={
                        "eligibility_status": "conditional",
                        "winner_reason": "La MDT queda visible cuando el patrón es oligometastásico y aún existe una estrategia de control dirigida.",
                    },
                )
                family_order.append("local_mdt_family")
            if observation_variants:
                family_profiles["observation_family"] = build_family_profile(
                    family_code="observation_family",
                    ordered_regimens=observation_variants,
                    context={
                        "eligibility_status": "eligible" if systemic_redirect else "conditional",
                        "missing_inputs": ["psma_pet_done"] if psma_pending else [],
                        "winner_reason": "La reestadificación dirigida sigue visible cuando todavía puede cambiar el alcance del salvage o redirigir a sistémico.",
                    },
                )
                family_order.append("observation_family")
        else:
            observation_variants.append(
                build_ranked_option(
                    name="Reestadificación después de recurrencia posradioterapia",
                    regimen_code="RESTAGING",
                    rank=1,
                    priority="preferred" if not local_salvage_candidate else "eligible",
                    eligibility_status="preferred" if not local_salvage_candidate else "eligible_nonpreferred",
                    family_code="observation_family",
                    molecule_or_backbone="Reestadificación post-RT",
                    description="Confirmar recurrencia exclusivamente local frente a recurrencia sistémica antes de seleccionar tratamiento.",
                    route="Imagen/reclasificación",
                    schedule="Reestadificación completa antes de cerrar tratamiento",
                    metadata_source="guideline_backbone",
                    notes="Confirme recurrencia exclusivamente local frente a recurrencia sistémica antes de seleccionar tratamiento.",
                    why_this_rank=["La recurrencia post-RT necesita reestadificación formal antes de fijar salvage local o transición sistémica."],
                )
            )
            if nccn["local_salvage_candidate"]:
                local_mdt_variants.append(
                    build_ranked_option(
                        name="Revisión de rescate local después de radioterapia",
                        regimen_code="LOCAL_MDT",
                        rank=1,
                        priority="preferred",
                        eligibility_status="preferred",
                        family_code="local_mdt_family",
                        molecule_or_backbone="Rescate local post-RT",
                        description="Mantenga visible el rescate local solo cuando siga siendo técnicamente plausible una opción con intención curativa.",
                        route="Cirugía / ablación / radioterapia dirigida",
                        schedule="Definición multidisciplinaria de rescate post-RT",
                        metadata_source="guideline_backbone",
                        notes="Mantenga visible el rescate local solo cuando siga siendo técnicamente plausible una opción con intención curativa.",
                        why_this_rank=["La vía local aún compite formalmente cuando el rescate post-RT es técnicamente plausible."],
                    )
                )
            if psma_pattern == "local_pelvic" and not confidence_low:
                local_mdt_variants.append(
                    build_ranked_option(
                        name="Revisión de rescate local guiada por PSMA",
                        regimen_code="PSMA_GUIDED_MDT",
                        rank=len(local_mdt_variants) + 1,
                        priority="eligible",
                        eligibility_status="eligible_nonpreferred",
                        family_code="local_mdt_family",
                        molecule_or_backbone="Rescate local guiado por PSMA",
                        description="PSMA local/pélvica que apoya salvamento local si sigue siendo técnicamente factible.",
                        route="Cirugía / ablación / radioterapia dirigida",
                        schedule="Plan dirigido por PSMA",
                        metadata_source="guideline_backbone",
                        notes="PSMA local/pélvico apoya salvamento local si sigue siendo técnicamente factible.",
                        why_this_rank=["La PSMA refuerza el rescate local, pero no sustituye la reestadificación integral."],
                    )
                )
            elif psma_pattern == "oligometastatic":
                local_mdt_variants.append(
                    build_ranked_option(
                        name="MDT/SBRT guiado por PSMA",
                        regimen_code="PSMA_GUIDED_MDT",
                        rank=len(local_mdt_variants) + 1,
                        priority="eligible",
                        eligibility_status="eligible_with_caution",
                        family_code="local_mdt_family",
                        molecule_or_backbone="MDT / SBRT guiada",
                        description="Burden limitado en PSMA que habilita ruta oligometastásica contextual.",
                        dose="SBRT 30-35 Gy en 3-5 fracciones",
                        route="Radioterapia estereotáxica",
                        schedule="Tratamiento dirigido tras comité",
                        metadata_source="guideline_backbone",
                        notes="PSMA con burden limitado abre ruta oligometastásica contextual.",
                        why_this_rank=["La ruta oligometastásica sigue siendo contextual y depende de comité multidisciplinario."],
                    )
                )
            elif psma_pattern == "diseminado":
                not_recommended.append("No usar una lectura diseminada de PSMA como base para rescate local aislado después de RT.")
            trials.append({"trial": "Base de evidencia para rescate local tras radioterapia", "match": True})
            not_recommended.append("No use PET/CT con PSMA después de recurrencia posradioterapia si el paciente no es un candidato realista a rescate local.")
            if local_mdt_variants:
                family_profiles["local_mdt_family"] = build_family_profile(
                    family_code="local_mdt_family",
                    ordered_regimens=local_mdt_variants,
                    context={
                        "eligibility_status": "eligible" if local_salvage_candidate and not systemic_redirect else "conditional",
                        "winner_reason": "El rescate local posradioterapia solo lidera cuando sigue siendo técnicamente factible y la imagen no redirige a sistémico.",
                    },
                )
                family_order.append("local_mdt_family")
            if observation_variants:
                family_profiles["observation_family"] = build_family_profile(
                    family_code="observation_family",
                    ordered_regimens=observation_variants,
                    context={
                        "eligibility_status": "eligible",
                        "missing_inputs": ["psma_pet_done"] if psma_pending else [],
                        "winner_reason": "La reestadificación post-RT sigue siendo obligatoria para separar local salvage de transición sistémica.",
                    },
                )
                family_order.append("observation_family")
        if psma_impact.get("confidence") == "low":
            not_recommended.append("No escalar una decisión mayor con PSMA-RADS bajo/intermedio o estructura PSMA incompleta sin correlación adicional.")
        durations.extend(psma_impact.get("recommended_actions", [])[:2])

        # Auditoría Pacientes Insignia 2026-04-21 (§D.4/§C.3) — gates sobre
        # salvage RT / re-irradiación en recurrencia bioquímica:
        #   1) Enfermedad inflamatoria intestinal activa (Crohn/colitis): RT
        #      pélvica contraindicada. Retiramos salvage_rt_family del bundle
        #      y emitimos el mensaje.
        #   2) Toxicidad tardía GU/GI CTCAE v5 grado ≥3 (RADICALS-RT / RTOG):
        #      re-irradiación contraindicada.
        active_ibd = _flag_truthy(payload.get("active_inflammatory_bowel_disease"))
        late_gu_tier = _late_rt_tier(payload.get("late_rt_toxicity_gu"))
        late_gi_tier = _late_rt_tier(payload.get("late_rt_toxicity_gi"))
        late_rt_block = late_gu_tier >= 3 or late_gi_tier >= 3
        contraindications_list: list[str] = []
        if active_ibd or late_rt_block:
            # Retirar salvage_rt_family y cualquier variante RT-based de
            # local_mdt_family (SBRT/RT dirigida cuenta como re-irradiación).
            if "salvage_rt_family" in family_profiles:
                family_profiles.pop("salvage_rt_family", None)
                family_order = [f for f in family_order if f != "salvage_rt_family"]
            if active_ibd:
                not_recommended.append(
                    "Radioterapia de salvage / re-irradiación pélvica contraindicada "
                    "por enfermedad inflamatoria intestinal activa (Crohn / colitis "
                    "ulcerosa) — riesgo severo de proctitis actínica. Priorizar "
                    "reestadificación sistémica o ruta quirúrgica si es candidato."
                )
                contraindications_list.append(
                    "RT pélvica / salvage RT contraindicada: enfermedad inflamatoria intestinal activa."
                )
            if late_rt_block:
                _sys = "GU" if late_gu_tier >= 3 else "GI"
                not_recommended.append(
                    "Re-irradiación / salvage RT contraindicada por toxicidad tardía "
                    f"{_sys} grado ≥3 (CTCAE v5). Priorizar manejo sintomático "
                    "multidisciplinar y evaluar terapias sistémicas alternativas "
                    "(RADICALS-RT / RTOG late toxicity)."
                )
                contraindications_list.append(
                    f"Re-irradiación contraindicada: toxicidad tardía {_sys} grado ≥3."
                )

        comparative_bundle = build_comparative_bundle(
            family_profiles=family_profiles,
            family_order=family_order,
        )
        preferred_regimen = dict(comparative_bundle.get("preferred_regimen") or {})
        if not preferred_regimen and observation_variants:
            preferred_regimen = dict(observation_variants[0])
        active_monitoring_package = build_active_regimen_monitoring_package(
            preferred_regimen.get("regimen_code"),
            family_code=preferred_regimen.get("family_code") or "observation_family",
            field_values=payload,
        )
        sequence_transition_bundle = build_sequence_transition_bundle(
            state=self.module_id,
            preferred_regimen=preferred_regimen,
            eligible_treatments=comparative_bundle.get("eligible_treatments") or [],
            current_treatment=payload.get("current_treatment") or "",
            missing_critical_inputs=missing_inputs,
            progression_pattern=str(payload.get("progression_pattern") or ""),
            line_context="recurrence_bcr",
            field_values=payload,
            monitoring_package=active_monitoring_package,
            comparative_eligibility_matrix=comparative_bundle.get("comparative_eligibility_matrix") or {},
        )

        case_summary = (
            f"El caso corresponde a {nccn['label']} con antígeno prostático específico actual de {psa_current:g} ng/mL "
            f"y tiempo de duplicación del antígeno prostático específico de {psadt:g} meses. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 prioriza {nccn['label']} "
            f"y la Asociación Europea de Urología (EAU) 2026 lo compara como {eau['label']}."
        )

        # Brecha M-staging gate — 2026-04-22 (§E.4):
        # En BCR el restaging es obligatorio antes de iniciar terapia sistémica
        # (ARSI/abiraterona EMBARK) o salvage local cuando PSA es muy alto.
        # Umbral conservador: PSA actual > 20 ng/mL (mismo umbral NCCN PROS-2)
        # OR PSADT corto + sin imagen de extensión documentada. NO bloquea si
        # ya hay PSMA / GGO+TAC / `imaging_negative_metastases='Sí'`.
        bcr_staging_req = staging_required(payload)
        bcr_staging_comp = staging_complete(payload)
        bcr_imaging_negative = str(payload.get("imaging_negative_metastases") or "").strip().lower() in {"sí", "si", "yes", "1", "true"}
        bcr_blocks_systemic = bool(
            bcr_staging_req.get("required")
            and not bcr_staging_comp.get("complete")
            and not bcr_imaging_negative
        )
        bcr_eligible_treatments = list(comparative_bundle.get("eligible_treatments") or [])
        if bcr_blocks_systemic:
            from prostanet.shared.staging_requirements_engine import staging_modality_recommended
            risk_band = bcr_staging_req.get("risk_band") or "high"
            recommended = staging_modality_recommended(payload, risk_band)
            staging_block: list[dict] = [{
                "name": "Completar reestadificación M antes de iniciar terapia sistémica o salvage local",
                "priority": "mandatory_pre_treatment",
                "category": "staging_imaging",
                "notes": (
                    f"PSA actual {psa_current:g} ng/mL en contexto de BCR exige descartar enfermedad "
                    "metastásica oculta antes de seleccionar ruta sistémica (EMBARK / ARPI / abiraterona) "
                    "o salvage local. Referencia: NCCN PROS-2/3 v5.2026 cat 1; EAU 2026 §6.4."
                ),
                "next_steps": recommended,
            }]
            for item in recommended:
                staging_block.append({
                    "name": item.get("name") or "Imagenología de estadificación M",
                    "priority": item.get("priority", "first_line"),
                    "category": "staging_imaging",
                    "notes": item.get("rationale") or "",
                })
            bcr_eligible_treatments = staging_block
            not_recommended.append(
                "Inicio de terapia sistémica (ARPI / abiraterona EMBARK) o salvage RT/RP "
                f"DIFERIDO hasta completar reestadificación M (PSA actual {psa_current:g} ng/mL). "
                f"Motivos: {'; '.join(bcr_staging_req.get('reasons') or [])}. "
                "Referencia: NCCN PROS-2/3 v5.2026 cat 1; EAU 2026 §6.4."
            )

        # ── Pivotal contraindication gates — Faubot 2026-04-23 ─────────────
        # En BCR/BCR2 los regímenes sistémicos (EMBARK enzalutamida ± LHRH,
        # PRESTO triplet apalutamida + abiraterona + ADT) están sujetos a
        # las mismas contraindicaciones documentadas en sus protocolos
        # pivote (HTA descontrolada, ICC NYHA III-IV, neuropatía severa de
        # ciclos previos de docetaxel, hipersensibilidad a darolutamida si
        # se considera ARASENS-like). Filtra los regímenes bloqueados y
        # añade los mensajes a `not_recommended` con trazabilidad.
        bcr_gate_bundle = apply_pivotal_contraindication_gates(payload, bcr_eligible_treatments)
        bcr_eligible_treatments = bcr_gate_bundle["filtered_treatments"]
        for msg in bcr_gate_bundle["not_recommended_messages"]:
            if msg not in not_recommended:
                not_recommended.append(msg)
        bcr_pivotal_gates = bcr_gate_bundle["gates_triggered"]

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={"guideline": "NCCN", "version": "5.2026", "label": nccn["label"], "recommendation": nccn["recommendation"]},
            eau_comparison={"guideline": "EAU", "version": "2026", "label": eau["label"], "recommendation": eau["recommendation"], "comparison": comparison},
            eligible_treatments=bcr_eligible_treatments,
            not_recommended=not_recommended,
            missing_critical_inputs=(
                missing_inputs
                + ([f"Reestadificación M ({m})" for m in (bcr_staging_comp.get("missing") or [])] if bcr_blocks_systemic else [])
            ),
            contraindications=contraindications_list,
            durations_and_conditions=durations,
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=trials,
            applicability_badge="guideline-consistent",
            report_sections={
                "summary": f"Ruta de recurrencia bioquímica: {nccn['label']}.",
                "embark_readiness": {
                    "high_risk_bcr2": nccn["high_risk_bcr2"],
                    "conventional_imaging_m0": nccn["conventional_imaging_m0"],
                    "salvage_local_feasible": nccn["salvage_local_feasible"],
                },
            },
            decision_quality={
                "recommendation_family": preferred_regimen.get("family_label") or nccn["label"],
                "confidence_category": "vigilada" if missing_inputs else "alta",
                "requires_human_review": bool(missing_inputs or confidence_low),
            },
        )
        result["comparative_eligibility_matrix"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        result["therapeutic_family_profiles"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        result["preferred_frontline_regimen"] = preferred_regimen
        result["preferred_regimen_code"] = preferred_regimen.get("regimen_code", "")
        result["alternative_regimens"] = comparative_bundle.get("alternative_regimens") or []
        # Brecha M-staging gate — 2026-04-22 (§E.4): exponer flags y override
        if bcr_blocks_systemic:
            result["state_classification_override"] = "staging_required"
            result["requires_human_review"] = True
            result["applicability"] = "blocked_pending_staging"
            result["staging_gap"] = {
                "risk_band": bcr_staging_req.get("risk_band"),
                "reasons": bcr_staging_req.get("reasons") or [],
                "modalities_done": bcr_staging_comp.get("modalities_done") or [],
                "missing_modalities": bcr_staging_comp.get("missing") or [],
                "context": "recurrence_bcr",
            }
            result.setdefault("decision_quality", {})["requires_human_review"] = True
        if bcr_pivotal_gates:
            # Faubot 2026-04-23 — exponer trazabilidad de gates pivotal en BCR.
            result["pivotal_contraindication_gates"] = [
                {
                    "code": g.get("code"),
                    "severity": g.get("severity"),
                    "message": g.get("message"),
                    "evidence_tag": g.get("evidence_tag"),
                    "trial_refs": list(g.get("trial_refs") or ()),
                }
                for g in bcr_pivotal_gates
            ]
        result["arpi_required_fields"] = list(arpi_capture_contract.get("arpi_required_fields") or [])
        result["arpi_missing_inputs"] = list(arpi_capture_contract.get("arpi_missing_inputs") or [])
        result["arpi_stale_inputs"] = list(arpi_capture_contract.get("arpi_stale_inputs") or [])
        result["arpi_profile_completeness"] = str(arpi_capture_contract.get("arpi_profile_completeness") or "")
        result["arpi_preference_readiness"] = str(arpi_capture_contract.get("arpi_preference_readiness") or "")
        result["arpi_selection_contract"] = dict(arpi_capture_contract)
        result["care_setting_contract"] = {
            "care_setting": (
                "systemic_intensification"
                if preferred_regimen.get("family_code") == "arpi_family"
                else "salvage_local"
            ),
            "family_code": preferred_regimen.get("family_code") or "",
            "family_label": preferred_regimen.get("family_label") or "",
        }
        result["sequence_transition_bundle"] = sequence_transition_bundle
        result["active_regimen_monitoring_package"] = active_monitoring_package
        result["post_rp_salvage_intensification_profile"] = dict(post_rp_salvage_profile)
        result["high_risk_post_rp_salvage"] = bool(post_rp_salvage_profile.get("high_risk_post_rp_salvage"))
        result["high_risk_feature_keys"] = list(post_rp_salvage_profile.get("high_risk_feature_keys") or [])
        result["pelvic_rt_role"] = str(post_rp_salvage_profile.get("pelvic_rt_role") or "")
        result["adt_duration_band"] = str(post_rp_salvage_profile.get("adt_duration_band") or "")
        result["psma_restaging_role"] = str(post_rp_salvage_profile.get("psma_restaging_role") or "")
        result["companion_actions_required_for_preferred_regimen"] = list(
            post_rp_salvage_profile.get("companion_actions_required_for_preferred_regimen") or []
        )
        result["negative_psma_should_not_delay_salvage"] = bool(
            post_rp_salvage_profile.get("negative_psma_should_not_delay_salvage")
        )
        result["phase7_advanced_bundle"] = build_post_rp_phase7_bundle(payload)
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada de recurrencia bioquímica",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                "La conducta cambia según antecedente de prostatectomía radical, radioterapia previa o segunda recurrencia bioquímica sin metástasis.",
                f"El tiempo de duplicación del antígeno prostático específico observado es de {psadt:g} meses.",
                "Las rutas sistémicas para segunda recurrencia bioquímica de alto riesgo solo deben activarse si cumplen exactamente los criterios del escenario y no queda rescate local potencialmente curativo.",
                "La tomografía por emisión de positrones dirigida al antígeno prostático específico de membrana debe usarse solo si cambia una decisión de rescate y no como imagen rutinaria indiscriminada.",
                psma_impact.get("rationale"),
            ],
            alternatives=[
                "Radioterapia de rescate temprana y terapia de privación androgénica adaptada al riesgo si el escenario es posterior a prostatectomía radical.",
                "Reestadificación completa y discusión de rescate local frente a transición sistémica si la recurrencia ocurre después de radioterapia.",
            ],
            shared_decision_message=(
                "La decisión debe integrar velocidad de recaída, imágenes disponibles, oportunidad real de rescate pélvico y preferencia del paciente sobre toxicidad urinaria, intestinal y sistémica."
            ),
            comparison_message=(
                "La comparación con la Asociación Europea de Urología (EAU) 2026 confirma si la ruta dominante es rescate temprano, reestadificación o una vía sistémica específica de segunda recurrencia bioquímica."
            ),
        )
