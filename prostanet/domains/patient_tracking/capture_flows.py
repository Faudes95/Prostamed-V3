from __future__ import annotations

from typing import Any

from prostanet.domains.patient_tracking.capture_surface import (
    build_capture_surface_metadata,
    enrich_capture_block,
)
from prostanet.shared.ui_value_normalizer import (
    normalize_capture_target_cta,
    normalize_capture_target_label,
    normalize_decision_domain_label,
)


ADVANCED_STATES = {
    "adt_progression_verification",
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
    "m0_crpc",
    "m1_crpc",
}

FOLLOWUP_PREFERRED_FIELDS = {
    "line_of_therapy_number",
    "line_of_therapy_context",
    "drug_scheme",
    "current_treatment",
    "current_adt_context",
    "castrate_testosterone_status",
    "psa",
    "psa_history",
    "testosterone",
    "testosterone_history",
    "alp",
    "ldh",
    "hemoglobin",
    "fatigue_score",
    "eq5d_vas_band",
    "fact_p_total_band",
    "bpi_worst_pain_band",
    "fatigue_score_band",
    "mini_cog_score",
    "peripheral_neuropathy_grade",
    "cv_risk_documented",
    "ddi_review_status",
    "active_liver_disease",
    "cirrhosis_or_portal_hypertension",
    "active_hepatitis_b_or_c",
    "prior_drug_induced_liver_injury",
    "dxa_baseline_done",
    "calcium_vitd_started",
    "bone_protection_started",
    "vitamin_d_level",
    "height_cm",
    "weight_loss_6m_kg",
    # EPIC 22b.8 — biopsy/pathology capture fields (route to moment=biopsy_capture)
    "gleason_primary",
    "gleason_secondary",
    "isup_grade",
    "gleason_at_rp",
    "margin_status",
    "surgical_margin_status",
    "percent_pattern_4",
    "percent_positive_cores",
    "perineural_invasion",
    "tumor_stage_at_rp",
    "biopsy_date",
    "biopsy_context",
    "biopsy_route",
}

FIELD_GROUP_HINTS = {
    "line_of_therapy_number": ("advanced_sequencing", "systemic_sequencing"),
    "line_of_therapy_context": ("advanced_sequencing", "systemic_sequencing"),
    "drug_scheme": ("advanced_sequencing", "systemic_sequencing"),
    "current_treatment": ("advanced_sequencing", "systemic_sequencing"),
    "current_adt_context": ("advanced_sequencing", "castration_status"),
    "castrate_testosterone_status": ("advanced_sequencing", "castration_status"),
    "psa": ("psa_monitoring", "disease_control"),
    "psa_history": ("psa_monitoring", "disease_control"),
    "testosterone": ("psa_monitoring", "castration_status"),
    "testosterone_history": ("psa_monitoring", "castration_status"),
    "hrr_status": ("biomarker_eligibility", "parp_eligibility"),
    "hrr_gene": ("biomarker_eligibility", "parp_eligibility"),
    "brca2_status": ("biomarker_eligibility", "parp_eligibility"),
    "msi_status": ("biomarker_eligibility", "precision_pathway"),
    "tmb_high": ("biomarker_eligibility", "precision_pathway"),
    "biomarker_source": ("biomarker_eligibility", "precision_pathway"),
    "molecular_assay_date": ("biomarker_eligibility", "precision_pathway"),
    "psma_positive": ("biomarker_eligibility", "psma_eligibility"),
    "psma_negative_dominant_lesions": ("biomarker_eligibility", "psma_eligibility"),
    "dxa_baseline_done": ("bone_support", "bone_safety"),
    "calcium_vitd_started": ("bone_support", "bone_safety"),
    "bone_protection_started": ("bone_support", "bone_safety"),
    "vitamin_d_level": ("bone_support", "bone_safety"),
    "cv_risk_documented": ("adt_safety", "cv_safety"),
    "ddi_review_status": ("adt_safety", "arpi_safety"),
    "active_liver_disease": ("adt_safety", "arpi_safety"),
    "cirrhosis_or_portal_hypertension": ("adt_safety", "arpi_safety"),
    "active_hepatitis_b_or_c": ("adt_safety", "arpi_safety"),
    "prior_drug_induced_liver_injury": ("adt_safety", "arpi_safety"),
    "mini_cog_score": ("frailty_fitness", "treatment_fitness"),
    "fatigue_score": ("frailty_fitness", "treatment_fitness"),
    "eq5d_vas_band": ("frailty_fitness", "treatment_fitness"),
    "fact_p_total_band": ("frailty_fitness", "treatment_fitness"),
    "bpi_worst_pain_band": ("frailty_fitness", "treatment_fitness"),
    "fatigue_score_band": ("frailty_fitness", "treatment_fitness"),
    "peripheral_neuropathy_grade": ("frailty_fitness", "treatment_fitness"),
    "weight_kg": ("frailty_fitness", "treatment_fitness"),
    "height_cm": ("frailty_fitness", "treatment_fitness"),
    "bmi_current": ("frailty_fitness", "treatment_fitness"),
    "weight_loss_6m_kg": ("frailty_fitness", "treatment_fitness"),
    "weight_loss_6m_pct": ("frailty_fitness", "treatment_fitness"),
    "g8_food_intake": ("frailty_fitness", "treatment_fitness"),
    "g8_weight_loss": ("frailty_fitness", "treatment_fitness"),
    "g8_mobility": ("frailty_fitness", "treatment_fitness"),
    "g8_neuropsych": ("frailty_fitness", "treatment_fitness"),
    "g8_bmi": ("frailty_fitness", "treatment_fitness"),
    "g8_medications": ("frailty_fitness", "treatment_fitness"),
    "g8_self_health": ("frailty_fitness", "treatment_fitness"),
    "low_activity": ("frailty_fitness", "treatment_fitness"),
    "slow_gait": ("frailty_fitness", "treatment_fitness"),
    "weak_grip": ("frailty_fitness", "treatment_fitness"),
    "ecog": ("frailty_fitness", "treatment_fitness"),
    "ecog_score": ("frailty_fitness", "treatment_fitness"),
    "histology_subtype": ("official_diagnosis", "official_diagnosis"),
    "gleason_primary": ("official_diagnosis", "official_diagnosis"),
    "gleason_secondary": ("official_diagnosis", "official_diagnosis"),
    "isup_grade": ("official_diagnosis", "official_diagnosis"),
    "clinical_tstage": ("official_diagnosis", "official_diagnosis"),
    "nodal_status": ("official_diagnosis", "official_diagnosis"),
    "clinical_stage_group": ("official_diagnosis", "official_diagnosis"),
    "clinical_risk_group": ("official_diagnosis", "official_diagnosis"),
    "pain": ("palliative_symptom_control", "symptom_control"),
    "bpi_worst_pain": ("palliative_symptom_control", "symptom_control"),
    "bone_pain": ("palliative_rt_bone", "palliative_rt"),
    "neuropathic_pain": ("palliative_symptom_control", "symptom_control"),
    "current_analgesics": ("opioid_safety", "opioid_safety"),
    "opioid_use": ("opioid_safety", "opioid_safety"),
    "breakthrough_pain": ("opioid_safety", "opioid_safety"),
    "bowel_regimen_started": ("opioid_safety", "opioid_safety"),
    "dyspnea_score": ("palliative_symptom_control", "symptom_control"),
    "nausea_score": ("palliative_symptom_control", "symptom_control"),
    "constipation_score": ("opioid_safety", "opioid_safety"),
    "appetite_loss": ("palliative_symptom_control", "symptom_control"),
    "insomnia_score": ("psychosocial_caregiver", "psychosocial_support"),
    "depression_score": ("psychosocial_caregiver", "psychosocial_support"),
    "anxiety_score": ("psychosocial_caregiver", "psychosocial_support"),
    "ecog_delta_3mo": ("palliative_symptom_control", "symptom_control"),
    "albumin": ("hospice_readiness", "hospice_eligibility"),
    "refractory_pain": ("palliative_symptom_control", "symptom_control"),
    "visceral_crisis": ("oncologic_emergency", "urgent_local_palliation"),
    "spinal_cord_compression": ("oncologic_emergency", "urgent_local_palliation"),
    "epidural_compression": ("oncologic_emergency", "urgent_local_palliation"),
    "pathological_fracture_risk": ("palliative_rt_bone", "bone_event_risk"),
    "obstructive_uropathy": ("oncologic_emergency", "urgent_local_palliation"),
    "hematuria_severe": ("oncologic_emergency", "urgent_local_palliation"),
    "brain_metastasis": ("oncologic_emergency", "urgent_local_palliation"),
    "advance_directive_documented": ("advance_care_planning", "goals_of_care"),
    "goals_of_care_discussed": ("advance_care_planning", "goals_of_care"),
    "healthcare_surrogate_designated": ("advance_care_planning", "goals_of_care"),
    "patient_prefers_comfort": ("hospice_readiness", "supportive_only"),
    "prior_systemic_lines": ("hospice_readiness", "hospice_eligibility"),
}

GROUP_META = {
    "frailty_fitness": {
        "title": "Completar fragilidad y fitness terapéutica",
        "rationale": "Desbloquea CCI, G8, Fried y aptitud terapéutica con datos reales, sin defaults optimistas.",
        "module_owner": "comorbidity_frailty_fitness",
        "decision_affected": "treatment_fitness",
    },
    "advanced_sequencing": {
        "title": "Confirmar línea terapéutica y secuenciación sistémica",
        "rationale": "Documenta cambios reales de línea y esquema para que el copiloto y la torre de APE por línea reflejen la evolución verdadera.",
        "module_owner": "advanced_panel_context",
        "decision_affected": "systemic_sequencing",
    },
    "biomarker_eligibility": {
        "title": "Completar biomarcadores accionables",
        "rationale": "Puede abrir o cerrar PARP, PSMA u otras rutas de precisión con impacto directo en la decisión.",
        "module_owner": "biomarker_context",
        "decision_affected": "precision_pathway",
    },
    "adt_safety": {
        "title": "Completar seguridad ARPI / ADT",
        "rationale": "Permite ajustar seguridad cardiovascular, cognitiva e interacciones antes de sostener o intensificar tratamiento.",
        "module_owner": "adt_side_effects",
        "decision_affected": "arpi_safety",
    },
    "bone_support": {
        "title": "Completar soporte óseo",
        "rationale": "Aclara riesgo óseo y medidas preventivas para evitar fractura u osteoporosis durante terapia prolongada.",
        "module_owner": "safety_support_context",
        "decision_affected": "bone_safety",
    },
    "psa_monitoring": {
        "title": "Completar monitoreo biológico por línea",
        "rationale": "Permite ver si la línea actual mejoró o perdió control del APE y si ya requiere cambio de conducta.",
        "module_owner": "psa_observability",
        "decision_affected": "disease_control",
    },
    "official_diagnosis": {
        "title": "Completar diagnóstico oficial",
        "rationale": "Permite mostrar un diagnóstico oncológico formal, preciso y trazable en vez de depender solo del módulo clínico operativo.",
        "module_owner": "official_diagnosis",
        "decision_affected": "official_diagnosis",
    },
    "palliative_symptom_control": {
        "title": "Completar control sintomático paliativo",
        "rationale": "Define si hoy la prioridad dominante es aliviar dolor, disnea, fatiga u otros síntomas antes de intensificar tratamiento antitumoral.",
        "module_owner": "palliative_transition_bundle",
        "decision_affected": "symptom_control",
    },
    "opioid_safety": {
        "title": "Completar seguridad analgésica y opioides",
        "rationale": "Asegura que el alivio sintomático sea eficaz y seguro, incluyendo dolor irruptivo y prevención de estreñimiento.",
        "module_owner": "palliative_monitoring_package",
        "decision_affected": "opioid_safety",
    },
    "oncologic_emergency": {
        "title": "Completar urgencias oncológicas paliativas",
        "rationale": "Permite distinguir crisis que deben sobreponerse al siguiente paso sistémico, como compresión medular, fractura o hematuria severa.",
        "module_owner": "palliative_transition_bundle",
        "decision_affected": "urgent_local_palliation",
    },
    "advance_care_planning": {
        "title": "Completar objetivos de cuidado",
        "rationale": "Alinea la conducta visible con voluntades anticipadas, representante y preferencia real del paciente.",
        "module_owner": "palliative_transition_bundle",
        "decision_affected": "goals_of_care",
    },
    "hospice_readiness": {
        "title": "Completar elegibilidad hospice",
        "rationale": "Determina si el beneficio oncológico esperado ya no supera la carga clínica y si debe proponerse soporte exclusivo.",
        "module_owner": "palliative_transition_bundle",
        "decision_affected": "hospice_eligibility",
    },
    "palliative_rt_bone": {
        "title": "Completar paliación local / RT ósea",
        "rationale": "Alinea dolor óseo, fractura inminente o compresión con radioterapia paliativa y soporte ortopédico/urológico.",
        "module_owner": "palliative_transition_bundle",
        "decision_affected": "palliative_rt",
    },
    "psychosocial_caregiver": {
        "title": "Completar soporte psicosocial y cuidador",
        "rationale": "Define necesidades emocionales, del cuidador y de soporte social que cambian la conducta real del seguimiento.",
        "module_owner": "palliative_monitoring_package",
        "decision_affected": "psychosocial_support",
    },
}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No realizado", "Desconocido", "Desconocida")


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(item for item in values if _is_present(item)))


def _resolve_group(field_name: str) -> tuple[str, str]:
    return FIELD_GROUP_HINTS.get(field_name, ("frailty_fitness", "clinical_completion"))


def build_missing_input_capture_bundle(
    *,
    patient: dict[str, Any],
    state: str,
    management_track: str,
    missing_inputs_by_panel: dict[str, list[str]],
    therapy_checkpoints: list[dict[str, Any]],
    agenda_items: list[dict[str, Any]],
    copilot: dict[str, Any],
) -> dict[str, Any]:
    has_followup_flow = bool(patient.get("follow_ups") or patient.get("stage_visits"))
    followup_capture_target = "followup" if has_followup_flow else ""
    intake_capture_target = "intake" if not has_followup_flow else ""
    tasks: list[dict[str, Any]] = []

    def add_task(
        *,
        key: str,
        raw_fields: list[str],
        title: str | None = None,
        rationale: str | None = None,
        input_group: str | None = None,
        module_owner: str | None = None,
        decision_affected: str | None = None,
        force_target: str | None = None,
        always_show: bool = False,
    ) -> None:
        fields = _dedupe(raw_fields)
        if not fields and not always_show:
            return
        group_key, field_decision = _resolve_group(fields[0]) if fields else (input_group or "frailty_fitness", "")
        group_key = input_group or group_key
        meta = GROUP_META.get(group_key, {})
        agenda_match = next(
            (
                item
                for item in agenda_items
                if any(field in (item.get("required_inputs") or []) for field in fields)
            ),
            {},
        )
        capture_target = force_target or (
            "followup"
            if has_followup_flow or any(field in FOLLOWUP_PREFERRED_FIELDS for field in fields)
            else "intake"
        )
        surface = build_capture_surface_metadata(fields, required_inputs=fields)
        tasks.append(
            {
                "key": key,
                "title": title or meta.get("title") or "Completar inputs críticos",
                "rationale": rationale or meta.get("rationale") or "Faltan datos estructurados para sostener una decisión clínica.",
                "module_owner": module_owner or meta.get("module_owner") or group_key,
                "decision_affected": decision_affected or meta.get("decision_affected") or field_decision,
                "input_group": group_key,
                "capture_target": capture_target,
                "preferred_entrypoint": capture_target,
                "agenda_id": agenda_match.get("id"),
                "raw_fields": fields,
                "visible_fields": list(surface.get("visible_fields") or []),
                "visible_required_inputs": list(surface.get("visible_required_inputs") or []),
                "form_scope": {
                    "mode": "capture_block",
                    "focus": group_key,
                    "fields": fields,
                    "visible_fields": list(surface.get("visible_fields") or []),
                },
                "action_label": "Completar en visita" if capture_target == "followup" else "Completar ingreso",
                "task_kind": "recapture" if always_show and not fields else "missing",
                "display_label": title or meta.get("title") or "Completar inputs críticos",
                "display_group": normalize_capture_target_label(capture_target),
                "display_cta": normalize_capture_target_cta(capture_target),
                "display_capture_target": normalize_capture_target_label(capture_target),
                "display_impact": (
                    f"Si se completa hoy, puede recalcular {normalize_decision_domain_label(decision_affected or meta.get('decision_affected') or field_decision)}."
                ),
                "display_why_now": rationale or meta.get("rationale") or "Faltan datos estructurados para sostener una decisión clínica.",
                "display_fields_summary": list(surface.get("display_fields_summary") or []),
            }
        )

    fitness = (copilot or {}).get("therapeutic_fitness") or {}
    frailty = fitness.get("frailty") or {}
    charlson = ((copilot or {}).get("comorbidity_scores") or {}).get("charlson") or {}
    g8 = ((copilot or {}).get("comorbidity_scores") or {}).get("g8") or {}
    fit_score = (fitness.get("fit_score") or {})
    if not charlson.get("is_complete") or not g8.get("is_complete") or not frailty.get("is_complete") or not fit_score.get("is_complete"):
        add_task(
            key="frailty_fitness",
            raw_fields=(
                (charlson.get("missing_inputs") or [])
                + (g8.get("missing_inputs") or [])
                + (frailty.get("missing_inputs") or [])
                + (fit_score.get("missing_inputs") or [])
            ),
            input_group="frailty_fitness",
        )

    for panel_name, fields in (missing_inputs_by_panel or {}).items():
        if panel_name == "sequencing_context":
            add_task(key="sequencing_context", raw_fields=fields, input_group="advanced_sequencing")
        elif panel_name == "biomarker_context":
            add_task(key="biomarker_context", raw_fields=fields, input_group="biomarker_eligibility")
        elif panel_name == "safety_support_context":
            add_task(key="safety_support_context", raw_fields=fields, input_group="adt_safety")
        elif panel_name == "official_diagnosis":
            add_task(key="official_diagnosis", raw_fields=fields, input_group="official_diagnosis")

    for checkpoint in therapy_checkpoints or []:
        if checkpoint.get("status") != "needs_data":
            continue
        add_task(
            key=f"checkpoint_{checkpoint.get('key')}",
            raw_fields=checkpoint.get("inputs_required") or [],
            title=checkpoint.get("title"),
            rationale=checkpoint.get("why_it_matters_now"),
            decision_affected=checkpoint.get("decision_supported"),
        )

    if state in ADVANCED_STATES:
        add_task(
            key="line_refresh",
            raw_fields=[
                "line_of_therapy_number",
                "line_of_therapy_context",
                "drug_scheme",
                "current_adt_context",
                "castrate_testosterone_status",
                "psa",
                "testosterone",
            ],
            input_group="advanced_sequencing",
            title="Confirmar línea terapéutica y control biológico de esta visita",
            rationale="Debe recapturarse en cada visita avanzada para detectar cambios de línea y medir si mejoró el antígeno prostático específico con esa secuencia.",
            force_target="followup",
            always_show=True,
        )
        latest_signal_snapshot = dict(patient.get("latest_signal_snapshot") or {})
        palliative_bundle = dict(latest_signal_snapshot.get("palliative_transition_bundle") or {})
        palliative_package = dict(latest_signal_snapshot.get("palliative_monitoring_package") or {})
        palliative_missing = _dedupe(list(palliative_bundle.get("missing_inputs") or []))
        if palliative_bundle.get("available") and (
            str(palliative_bundle.get("trigger_status") or "") not in {"", "observe"}
            or palliative_missing
        ):
            add_task(
                key="palliative_symptom_control",
                raw_fields=[field for field in palliative_missing if field in {"pain", "bpi_worst_pain", "bone_pain", "neuropathic_pain", "fatigue_score", "dyspnea_score", "nausea_score", "constipation_score", "appetite_loss", "ecog", "ecog_delta_3mo"}],
                input_group="palliative_symptom_control",
                force_target="followup",
            )
            add_task(
                key="opioid_safety",
                raw_fields=[field for field in palliative_missing if field in {"current_analgesics", "opioid_use", "breakthrough_pain", "bowel_regimen_started", "constipation_score"}],
                input_group="opioid_safety",
                force_target="followup",
            )
            add_task(
                key="oncologic_emergency",
                raw_fields=[field for field in palliative_missing if field in {"spinal_cord_compression", "epidural_compression", "pathological_fracture_risk", "obstructive_uropathy", "hematuria_severe", "brain_metastasis", "visceral_crisis"}],
                input_group="oncologic_emergency",
                force_target="followup",
            )
            add_task(
                key="advance_care_planning",
                raw_fields=[field for field in palliative_missing if field in {"advance_directive_documented", "goals_of_care_discussed", "healthcare_surrogate_designated"}],
                input_group="advance_care_planning",
                force_target="followup",
            )
            add_task(
                key="hospice_readiness",
                raw_fields=[field for field in palliative_missing if field in {"patient_prefers_comfort", "prior_systemic_lines", "albumin", "weight_loss_6m_kg", "ecog"}],
                input_group="hospice_readiness",
                force_target="followup",
            )
            add_task(
                key="psychosocial_caregiver",
                raw_fields=[field for field in palliative_missing if field in {"depression_score", "anxiety_score", "insomnia_score", "healthcare_surrogate_designated", "goals_of_care_discussed", "patient_prefers_comfort"}],
                input_group="psychosocial_caregiver",
                rationale=str(palliative_package.get("monitoring_focus") or ""),
                force_target="followup",
            )

    deduped_tasks: list[dict[str, Any]] = []
    seen = set()
    for task in tasks:
        marker = (task.get("title"), tuple(task.get("raw_fields") or []), task.get("capture_target"))
        if marker in seen:
            continue
        seen.add(marker)
        deduped_tasks.append(task)

    def build_block(target: str) -> dict[str, Any]:
        block_tasks = [task for task in deduped_tasks if task.get("capture_target") == target]
        block_fields = _dedupe([field for task in block_tasks for field in (task.get("raw_fields") or [])])
        return enrich_capture_block({
            "capture_target": target,
            "title": "Completar datos críticos del ingreso" if target == "intake" else "Completar datos críticos de la visita",
            "summary": "Solicita los inputs faltantes o variables dinámicas que deben reconfirmarse para sostener decisión clínica real.",
            "tasks": block_tasks,
            "fields": block_fields,
        }) if block_tasks else {}

    return {
        "tasks": deduped_tasks[:8],
        "intake_capture_target": intake_capture_target,
        "followup_capture_target": followup_capture_target or "followup",
        "intake_completion_block": build_block("intake"),
        "followup_completion_block": build_block("followup"),
    }


def prepend_capture_block_to_visit_sections(
    sections: list[dict[str, Any]],
    capture_block: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not capture_block or not (capture_block.get("fields") or []):
        return sections

    requested_fields = set(capture_block.get("visible_fields") or capture_block.get("fields") or [])
    extracted_fields: list[dict[str, Any]] = []
    remaining_sections: list[dict[str, Any]] = []

    for section in sections:
        remaining_fields = []
        for field in section.get("fields", []):
            if field.get("name") in requested_fields:
                extracted_fields.append(field)
            else:
                remaining_fields.append(field)
        if remaining_fields:
            clone = dict(section)
            clone["fields"] = remaining_fields
            remaining_sections.append(clone)

    if not extracted_fields:
        return sections

    capture_section = {
        "id": f"capture_{capture_block.get('capture_target')}",
        "title": capture_block.get("title") or "Completar datos críticos",
        "description": capture_block.get("summary") or "",
        "fields": extracted_fields,
    }
    return [capture_section] + remaining_sections
