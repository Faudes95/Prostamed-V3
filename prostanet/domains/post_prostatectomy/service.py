from __future__ import annotations

from typing import Any

from clinical_scores import calculate_capra_s

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.patient_tracking.therapeutic_family_engine import (
    build_active_regimen_monitoring_package,
    build_comparative_bundle,
    build_family_profile,
    build_ranked_option,
    build_sequence_transition_bundle,
)
from prostanet.domains.post_prostatectomy.rules_eau import classify_post_rp_eau
from prostanet.domains.post_prostatectomy.rules_nccn import classify_post_rp
from prostanet.domains.post_prostatectomy.schemas import POST_PROSTATECTOMY_SCHEMA
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.epic26 import normalize_epic26_payload
from prostanet.shared.phase7_decision_bundles import build_post_rp_phase7_bundle
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


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


class PostProstatectomyService:
    module_id = "post_prostatectomy"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return POST_PROSTATECTOMY_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        # EPIC 9 Group F (GAP-17) — Normalización EPIC-26 post-captura. Si el
        # payload trae `epic26_response_packet`, se derivan los 5 dominios + la
        # molestia urinaria global y se inyectan en `payload` antes de las
        # reglas NCCN/EAU. Si no hay packet, la función devuelve el payload
        # intacto (seguro cuando la visita no capturó QoL estructurado).
        payload = normalize_epic26_payload(payload)
        missing = [field for field in ["psa", "psa_postop"] if str(payload.get(field, "")).strip() == ""]
        nccn = classify_post_rp(payload)
        eau = classify_post_rp_eau(payload)
        capra_s = calculate_capra_s(payload)
        comparison = self.comparison.compare(nccn, eau)
        label = nccn["label"]
        is_bcr_or_persistent = label in {
            "PSA persistence/recurrence",
            "BCR / recurrencia bioquímica pos-RP",
        }
        eligible = []
        not_recommended = []
        durations = []
        decipher_risk = str(payload.get("decipher_risk", "No realizado"))
        imaging_modality = str(payload.get("imaging_modality", "Ninguna"))
        surveillance_variants: list[dict] = []
        salvage_variants: list[dict] = []

        if is_bcr_or_persistent:
            surveillance_variants.append(
                build_ranked_option(
                    name="Vigilancia posoperatoria intensificada",
                    regimen_code="POST_RP_SURVEILLANCE",
                    rank=1,
                    priority="eligible",
                    eligibility_status="eligible_nonpreferred",
                    family_code="surveillance_family",
                    molecule_or_backbone="Vigilancia intensificada",
                    description="PSA ultrasensible seriado y reevaluación corta mientras se cierra la estrategia de salvage.",
                    route="Seguimiento longitudinal",
                    schedule="PSA seriado de alta frecuencia",
                    metadata_source="guideline_backbone",
                    notes="Mantenga vigilancia intensificada solo como puente corto mientras se estructura la ruta de rescate.",
                    why_this_rank=["La vigilancia sigue visible como puente operativo, pero ya no debe desplazar la planificación de salvage."],
                )
            )
            salvage_variants.append(
                build_ranked_option(
                    name="Activar salvage y reestadificación dirigida",
                    regimen_code="SALVAGE_RT_ALONE",
                    rank=1,
                    priority="preferred",
                    eligibility_status="preferred",
                    family_code="salvage_rt_family",
                    molecule_or_backbone="Salvage temprana",
                    description="El PSA persistente o recurrente debe acelerar la planificación de rescate postoperatorio.",
                    dose="64-66 Gy al lecho prostático",
                    route="Radioterapia externa",
                    schedule="20-33 fracciones",
                    component_drugs=[{"drug_name": "Radioterapia de salvage", "dose": "64-66 Gy", "route": "Radioterapia externa", "schedule": "20-33 fracciones"}],
                    metadata_source="guideline_backbone",
                    evidence_tags=["RADICALS-RT", "RAVES", "ARTISTIC"],
                    notes="Use el módulo de recurrencia para la lógica de rescate y segunda recurrencia bioquímica.",
                    why_this_rank=["El PSA persistente o recurrente post-RP debe mover la vía de vigilancia a planificación activa de salvage."],
                )
            )
            not_recommended.append("No presente CAPRA-S como sustituto de la estadificación y selección de la ruta de rescate.")
        elif nccn["adverse_features"]:
            surveillance_variants.append(
                build_ranked_option(
                    name="Vigilancia posoperatoria estrecha",
                    regimen_code="POST_RP_SURVEILLANCE",
                    rank=1,
                    priority="preferred" if not nccn.get("early_salvage_emphasis") else "eligible",
                    eligibility_status="preferred" if not nccn.get("early_salvage_emphasis") else "eligible_nonpreferred",
                    family_code="surveillance_family",
                    molecule_or_backbone="Vigilancia estrecha",
                    description="Monitoree PSA ultrasensible y active rescate temprano cuando el patrón evolucione.",
                    route="Seguimiento longitudinal",
                    schedule="PSA seriado y reevaluación postoperatoria",
                    metadata_source="guideline_backbone",
                    notes="Monitoree el PSA en forma estrecha y active rescate temprano cuando esté indicado.",
                    why_this_rank=["La vigilancia sigue siendo válida si la ventana de salvage aún no exige activación inmediata."],
                )
            )
            salvage_variants.append(
                build_ranked_option(
                    name="Planificación temprana de rescate",
                    regimen_code="SALVAGE_RT_ALONE",
                    rank=1,
                    priority="preferred" if nccn.get("early_salvage_emphasis") else "eligible",
                    eligibility_status="preferred" if nccn.get("early_salvage_emphasis") else "eligible_nonpreferred",
                    family_code="salvage_rt_family",
                    molecule_or_backbone="Salvage temprana",
                    description="Discuta el momento y la necesidad de RT de rescate con o sin ADT según riesgo postoperatorio.",
                    dose="64-66 Gy al lecho prostático",
                    route="Radioterapia externa",
                    schedule="20-33 fracciones",
                    component_drugs=[{"drug_name": "Radioterapia de salvage", "dose": "64-66 Gy", "route": "Radioterapia externa", "schedule": "20-33 fracciones"}],
                    metadata_source="guideline_backbone",
                    evidence_tags=["RADICALS-RT", "RAVES", "ARTISTIC"],
                    notes="Discuta el momento y la necesidad de radioterapia con o sin terapia de privación androgénica usando el módulo de recurrencia.",
                    why_this_rank=["Los factores adversos y Decipher pueden adelantar la conversación de salvage aun antes de una recurrencia más franca."],
                )
            )
            not_recommended.append("Evite presentar la radioterapia adyuvante como obligatoria para todo paciente con patología adversa.")
        else:
            surveillance_variants.append(
                build_ranked_option(
                    name="Vigilancia posoperatoria rutinaria",
                    regimen_code="POST_RP_SURVEILLANCE",
                    rank=1,
                    priority="preferred",
                    eligibility_status="preferred",
                    family_code="surveillance_family",
                    molecule_or_backbone="Vigilancia rutinaria",
                    description="Continúe el monitoreo del antígeno prostático específico ultrasensible.",
                    route="Seguimiento longitudinal",
                    schedule="PSA ultrasensible seriado",
                    metadata_source="guideline_backbone",
                    notes="Continúe el monitoreo del antígeno prostático específico.",
                    why_this_rank=["Sin persistencia ni factores que adelanten rescue, la vigilancia sigue siendo la estrategia dominante."],
                )
            )
        if decipher_risk == "Alto":
            durations.append("El riesgo Decipher alto favorece una conversación más temprana sobre rescate posoperatorio si el contexto anatómico sigue siendo curable.")
        if imaging_modality == "PSMA-PET":
            durations.append("La imagen PSMA-PET en el contexto posoperatorio debe cambiar una decisión real de rescate y no sustituir la cronología del PSA ultrasensible.")

        # Auditoría Pacientes Insignia 2026-04-21 (§D.4/§C.3) — gates para
        # salvage RT en post-prostatectomía:
        #   1) Enfermedad inflamatoria intestinal activa (colitis ulcerosa /
        #      Crohn): contraindica radioterapia pélvica por riesgo severo de
        #      exacerbación. Filtramos salvage_variants y emitimos el mensaje.
        #   2) Toxicidad tardía GU/GI CTCAE v5 grado ≥3 (RADICALS-RT): bloquea
        #      re-irradiación y cualquier nuevo ciclo de salvage RT.
        active_ibd = _flag_truthy(payload.get("active_inflammatory_bowel_disease"))
        late_gu_tier = _late_rt_tier(payload.get("late_rt_toxicity_gu"))
        late_gi_tier = _late_rt_tier(payload.get("late_rt_toxicity_gi"))
        late_rt_block = late_gu_tier >= 3 or late_gi_tier >= 3
        contraindications_list: list[str] = []
        if salvage_variants and (active_ibd or late_rt_block):
            salvage_variants = []
            if active_ibd:
                not_recommended.append(
                    "Radioterapia de salvage pélvica contraindicada por enfermedad "
                    "inflamatoria intestinal activa (Crohn/colitis ulcerosa) — riesgo "
                    "de exacerbación severa y proctitis actínica. Priorizar control "
                    "sistémico y evaluar ruta quirúrgica o vigilancia estrecha."
                )
                contraindications_list.append(
                    "RT pélvica contraindicada: enfermedad inflamatoria intestinal activa."
                )
            if late_rt_block:
                _sys = "GU" if late_gu_tier >= 3 else "GI"
                not_recommended.append(
                    "Salvage RT / re-irradiación contraindicada por toxicidad tardía "
                    f"{_sys} grado ≥3 (CTCAE v5). Priorizar manejo sintomático "
                    "multidisciplinar y terapias sistémicas alternativas."
                )
                contraindications_list.append(
                    f"Re-irradiación contraindicada: toxicidad tardía {_sys} grado ≥3."
                )

        family_profiles: dict[str, dict] = {}
        family_order: list[str] = []
        if salvage_variants:
            family_profiles["salvage_rt_family"] = build_family_profile(
                family_code="salvage_rt_family",
                ordered_regimens=salvage_variants,
                context={
                    "eligibility_status": "eligible",
                    "preference_drivers": ["PSA persistente/recidivante" if is_bcr_or_persistent else "Patología adversa / Decipher"],
                    "winner_reason": "La planificación de salvage sube cuando el PSA ya es persistente o la anatomía patológica adversa adelanta el riesgo clínico.",
                },
            )
        if surveillance_variants:
            family_profiles["surveillance_family"] = build_family_profile(
                family_code="surveillance_family",
                ordered_regimens=surveillance_variants,
                context={
                    "eligibility_status": "eligible",
                    "winner_reason": "La vigilancia posoperatoria sigue dominante cuando no hay persistencia franca ni urgencia temprana de salvage.",
                },
            )
        family_order = ["salvage_rt_family", "surveillance_family"] if is_bcr_or_persistent or nccn.get("early_salvage_emphasis") else ["surveillance_family", "salvage_rt_family"]
        comparative_bundle = build_comparative_bundle(
            family_profiles=family_profiles,
            family_order=family_order,
        )
        preferred_regimen = dict(comparative_bundle.get("preferred_regimen") or {})
        active_monitoring_package = build_active_regimen_monitoring_package(
            preferred_regimen.get("regimen_code"),
            family_code=preferred_regimen.get("family_code") or "surveillance_family",
            field_values=payload,
        )
        result_state = "recurrence_bcr" if is_bcr_or_persistent else self.module_id
        sequence_transition_bundle = build_sequence_transition_bundle(
            state=result_state,
            preferred_regimen=preferred_regimen,
            eligible_treatments=comparative_bundle.get("eligible_treatments") or [],
            current_treatment=payload.get("current_treatment") or "",
            missing_critical_inputs=missing,
            progression_pattern=str(payload.get("progression_pattern") or ""),
            line_context="post_prostatectomy",
            field_values=payload,
            monitoring_package=active_monitoring_package,
            comparative_eligibility_matrix=comparative_bundle.get("comparative_eligibility_matrix") or {},
        )
        eligible = comparative_bundle.get("eligible_treatments") or []

        psa_postop = float(payload.get("psa_postop", 0) or 0)
        pathologic_stage = str(payload.get("pathologic_stage", "pTx")).strip() or "pTx"
        case_summary = (
            f"El escenario corresponde a seguimiento después de prostatectomía radical, "
            f"con estadio patológico {pathologic_stage} y antígeno prostático específico posoperatorio de {psa_postop:g} ng/mL. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 describe el caso como {nccn['label']}, "
            f"mientras la Asociación Europea de Urología (EAU) 2026 lo contrasta como {eau['label']}."
        )

        report_sections = {
            "summary": f"Estado posterior a prostatectomía radical: {nccn['label']}. CAPRA-S pertenece exclusivamente a este módulo.",
            "capra_s": capra_s,
            "validated_algorithms": {
                "capra_s_score": capra_s.get("score") if isinstance(capra_s, dict) else None,
                "decipher_risk": decipher_risk,
            },
        }

        result = evaluation_result(
            state=result_state,
            nccn_primary={"guideline": "NCCN", "version": "5.2026", "label": nccn["label"], "recommendation": nccn["recommendation"]},
            eau_comparison={"guideline": "EAU", "version": "2026", "label": eau["label"], "recommendation": eau["recommendation"], "comparison": comparison},
            eligible_treatments=eligible,
            not_recommended=not_recommended,
            missing_critical_inputs=missing,
            contraindications=contraindications_list,
            durations_and_conditions=durations,
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=[{"trial": "RADICALS-RT", "match": nccn["adverse_features"]}, {"trial": "SWOG-8794", "match": nccn["adverse_features"]}],
            applicability_badge="guideline-consistent",
            report_sections=report_sections,
            decision_quality={
                "recommendation_family": preferred_regimen.get("family_label") or ("Salvage" if is_bcr_or_persistent else "Vigilancia"),
                "confidence_category": "vigilada" if missing else "alta",
                "requires_human_review": False,
            },
        )
        result["comparative_eligibility_matrix"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        result["therapeutic_family_profiles"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        result["preferred_frontline_regimen"] = preferred_regimen
        result["preferred_regimen_code"] = preferred_regimen.get("regimen_code", "")
        result["alternative_regimens"] = comparative_bundle.get("alternative_regimens") or []
        result["care_setting_contract"] = {
            "care_setting": "salvage_local" if preferred_regimen.get("family_code") == "salvage_rt_family" else "curative_local",
            "family_code": preferred_regimen.get("family_code") or "",
            "family_label": preferred_regimen.get("family_label") or "",
        }
        result["sequence_transition_bundle"] = sequence_transition_bundle
        result["active_regimen_monitoring_package"] = active_monitoring_package
        result["phase7_advanced_bundle"] = build_post_rp_phase7_bundle(payload)
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada después de prostatectomía radical",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                f"El puntaje postoperatorio CAPRA-S se conserva solo en este módulo y no debe extrapolarse al contexto preoperatorio.",
                f"Puntaje postoperatorio CAPRA-S estimado: {capra_s.get('score', 'no disponible') if isinstance(capra_s, dict) else capra_s}.",
                "La conducta depende de la combinación de antígeno prostático específico posoperatorio, márgenes, extensión extracapsular, invasión de vesículas seminales y ganglios.",
                "Decipher y el tiempo a recurrencia refinan la urgencia del rescate, pero no convierten la adyuvancia rutinaria en estándar universal.",
                "El objetivo es activar rescate temprano cuando exista persistencia o recurrencia, evitando adyuvancia rutinaria indiscriminada.",
            ],
            alternatives=[
                "Vigilancia estrecha con antígeno prostático específico seriado cuando no hay persistencia bioquímica franca.",
                "Planificación temprana de radioterapia de rescate con o sin terapia de privación androgénica en presencia de factores adversos y riesgo clínico suficiente.",
            ],
            shared_decision_message=(
                "La recomendación debe equilibrar la probabilidad de recurrencia, la toxicidad urinaria o sexual esperable y la disposición del paciente a adelantar o diferir tratamiento de rescate."
            ),
            comparison_message=(
                "La comparación con la Asociación Europea de Urología (EAU) 2026 ayuda a distinguir vigilancia estrecha frente a planificación temprana de rescate sin convertir la adyuvancia en una obligación automática."
            ),
        )
