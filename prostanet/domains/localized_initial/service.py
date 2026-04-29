from __future__ import annotations

from clinical_scores import briganti_lni, capra_score, kattan_organ_confined, partin_tables

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.localized_initial.rules_eau import classify_eau
from prostanet.domains.localized_initial.rules_nccn import (
    _resolve_genomic_band,
    active_surveillance_position,
    classify_nccn,
)
from prostanet.domains.localized_initial.schemas import LOCALIZED_SCHEMA
from prostanet.domains.patient_tracking.localized_modality import (
    build_active_surveillance_monitoring_profile,
    build_localized_modality_fitness_bundle,
    build_localized_survival_context_bundle,
    build_localized_tradeoff_bundle,
    normalized_localized_values,
    build_radical_prostatectomy_candidacy_profile,
    parse_patient_priority_profile,
)
from prostanet.domains.patient_tracking.score_interpretation_catalog import (
    build_score_interpretation_snapshot,
    extract_epic26_domain_scorecards,
)
from prostanet.domains.patient_tracking.therapeutic_family_engine import (
    build_active_regimen_monitoring_package,
    build_comparative_bundle,
    build_family_profile,
    build_ranked_option,
    build_sequence_transition_bundle,
)
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.epic26 import normalize_epic26_payload
from prostanet.shared.phase7_decision_bundles import build_pre_rp_phase7_bundle
from prostanet.shared.pivotal_contraindication_gates import (
    apply_pivotal_contraindication_gates,
)
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result
from prostanet.shared.staging_requirements_engine import (
    radical_prostatectomy_contraindicated,
    staging_gap_descriptor,
)


class LocalizedInitialService:
    module_id = "localized_initial"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return LOCALIZED_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        payload = normalized_localized_values(normalize_epic26_payload(payload))
        missing = self._missing(payload, ["psa", "clinical_tstage", "isup_grade", "num_cores_positive", "total_cores"])
        nccn = classify_nccn(payload)
        eau = classify_eau(payload)
        comparison = self.comparison.compare(nccn, eau)
        capra = capra_score(payload)
        briganti = briganti_lni(payload)
        partin = partin_tables(payload)
        msk = kattan_organ_confined(payload)
        as_position = active_surveillance_position(payload, nccn["risk_group"])

        # Multi-protocol AS eligibility via active_surveillance module
        as_multi_eligibility = []
        try:
            from prostanet.domains.patient_tracking.active_surveillance import ActiveSurveillanceService
            as_multi_eligibility = ActiveSurveillanceService.check_eligibility(payload, "localized_initial")
            # Enrich as_position with multi-protocol results
            eligible_protocols = [e.protocol for e in as_multi_eligibility if e.eligible]
            if eligible_protocols:
                as_position["multi_protocol_eligible"] = eligible_protocols
                as_position["multi_protocol_details"] = [
                    {"protocol": e.protocol, "eligible": e.eligible, "criteria_met": e.criteria_met, "criteria_failed": e.criteria_failed}
                    for e in as_multi_eligibility
                ]
            else:
                as_position["multi_protocol_eligible"] = []
                as_position["multi_protocol_details"] = [
                    {"protocol": e.protocol, "eligible": False, "criteria_failed": e.criteria_failed}
                    for e in as_multi_eligibility
                ]
        except Exception:
            pass

        genomic_result = str(payload.get("genomic_classifier_result", "No aplica"))
        # EPIC 2 FIX-LOCALIZED-GENOMIC: si un score numérico promueve al paciente a la
        # banda "high", propaga "Alto" al resto del pipeline de localized_initial
        # aunque el campo categórico sea "No aplica", "Bajo" o "Intermedio".
        _genomic_band, _genomic_src, _genomic_narr = _resolve_genomic_band(payload)
        if _genomic_band == "high" and genomic_result != "Alto":
            genomic_result = "Alto"
        prior_pirads = str(payload.get("prior_mpmri_pirads_score", "desconocido") or "desconocido")
        adverse_variant_type = self._adverse_variant_type(payload)
        predict_ready = all(
            payload.get(field) not in (None, "")
            for field in ("age", "psa", "clinical_tstage", "isup_grade", "life_expectancy_years")
        )
        patient_priorities = parse_patient_priority_profile(payload.get("patient_priority_profile"))
        patient_priority_profile = {
            "available": bool(patient_priorities),
            "priorities": patient_priorities,
        }
        localized_modality_fitness_bundle = build_localized_modality_fitness_bundle(
            payload,
            nccn_group=nccn["risk_group"],
            as_position=as_position,
        )
        radical_prostatectomy_candidacy_profile = build_radical_prostatectomy_candidacy_profile(
            payload,
            nccn_group=nccn["risk_group"],
        )
        localized_survival_context_bundle = build_localized_survival_context_bundle(payload)
        occam_life_expectancy_bundle = payload.get("occam_life_expectancy_bundle") or {}
        active_surveillance_monitoring_profile = build_active_surveillance_monitoring_profile(
            payload,
            as_position=as_position,
        )
        localized_tradeoff_bundle = build_localized_tradeoff_bundle(
            payload,
            nccn_group=nccn["risk_group"],
            modality_bundle=localized_modality_fitness_bundle,
            as_position=as_position,
        )
        score_interpretation_catalog_snapshot = build_score_interpretation_snapshot(payload)
        epic26_domain_scores = extract_epic26_domain_scorecards(score_interpretation_catalog_snapshot)

        eligible_treatments = self._eligible_treatments(
            nccn["risk_group"],
            as_position,
            genomic_result,
            adverse_variant_type,
            localized_modality_fitness_bundle,
            radical_prostatectomy_candidacy_profile,
            localized_survival_context_bundle,
        )
        ranked_treatments = [
            self._hydrate_localized_treatment_item(
                item,
                rank=index,
                risk_group=nccn["risk_group"],
                as_position=as_position,
            )
            for index, item in enumerate(eligible_treatments, start=1)
        ]
        grouped: dict[str, list[dict]] = {}
        family_order: list[str] = []
        for item in ranked_treatments:
            family_code = str(item.get("family_code") or "observation_family")
            grouped.setdefault(family_code, []).append(item)
            if family_code not in family_order:
                family_order.append(family_code)
        preferred_family_order = self._family_order_for_localized(
            nccn["risk_group"],
            as_position,
            family_order,
            dominant_modality=str(localized_modality_fitness_bundle.get("dominant_modality") or ""),
        )
        family_profiles: dict[str, dict] = {}
        if grouped.get("active_surveillance_family"):
            family_profiles["active_surveillance_family"] = build_family_profile(
                family_code="active_surveillance_family",
                ordered_regimens=grouped["active_surveillance_family"],
                context={
                    "eligibility_status": "eligible" if as_position.get("eligible") else "conditional",
                    "caution_drivers": list(localized_modality_fitness_bundle.get("why_not_active_surveillance") or []),
                    "preference_drivers": patient_priorities,
                    "winner_reason": localized_modality_fitness_bundle.get("dominance_reason")
                    if localized_modality_fitness_bundle.get("dominant_modality") == "active_surveillance"
                    else "La vigilancia activa solo lidera cuando la biología, la RM/biopsia confirmatoria y la esperanza de vida sostienen esa vía.",
                    "why_not_preferred": " ".join(list(localized_modality_fitness_bundle.get("why_not_active_surveillance") or [])[:2]) or "Pierde prioridad con histología adversa, MRI de mayor riesgo o expectativa de vida limitada.",
                    "missing_inputs": list(localized_modality_fitness_bundle.get("missing_modality_fields") or []),
                },
            )
        if grouped.get("radiotherapy_family"):
            family_profiles["radiotherapy_family"] = build_family_profile(
                family_code="radiotherapy_family",
                ordered_regimens=grouped["radiotherapy_family"],
                context={
                    "eligibility_status": "conditional" if localized_modality_fitness_bundle.get("radiotherapy_status") == "provisional" else "eligible",
                    "winner_reason": localized_modality_fitness_bundle.get("dominance_reason")
                    if localized_modality_fitness_bundle.get("dominant_modality") == "radiotherapy"
                    else "La familia radioterapia se ordena por grupo de riesgo, factibilidad técnica y costo funcional basal.",
                    "why_not_preferred": " ".join(list(localized_modality_fitness_bundle.get("why_not_radiotherapy") or [])[:2]),
                    "caution_drivers": list(localized_modality_fitness_bundle.get("why_not_radiotherapy") or []),
                    "preference_drivers": patient_priorities,
                    "missing_inputs": list(localized_modality_fitness_bundle.get("missing_modality_fields") or []),
                },
            )
        if grouped.get("multimodal_local_family"):
            family_profiles["multimodal_local_family"] = build_family_profile(
                family_code="multimodal_local_family",
                ordered_regimens=grouped["multimodal_local_family"],
                context={
                    "eligibility_status": "eligible",
                    "winner_reason": localized_modality_fitness_bundle.get("dominance_reason")
                    if localized_modality_fitness_bundle.get("dominant_modality") == "multimodal_local"
                    else "La intensificación multimodal local domina cuando el riesgo muy alto o regional exige control local y sistémico combinados.",
                    "preference_drivers": patient_priorities,
                    "missing_inputs": list(localized_modality_fitness_bundle.get("missing_modality_fields") or []),
                },
            )
        if grouped.get("surgery_family"):
            family_profiles["surgery_family"] = build_family_profile(
                family_code="surgery_family",
                ordered_regimens=grouped["surgery_family"],
                context={
                    "eligibility_status": "conditional" if localized_modality_fitness_bundle.get("surgery_status") == "provisional" else "eligible",
                    "winner_reason": localized_modality_fitness_bundle.get("dominance_reason")
                    if localized_modality_fitness_bundle.get("dominant_modality") == "surgery"
                    else "La cirugía permanece visible para candidatos apropiados, pero su prioridad depende del riesgo, la aptitud anestésico-quirúrgica y el contexto funcional basal.",
                    "why_not_preferred": " ".join(list(localized_modality_fitness_bundle.get("why_not_surgery") or [])[:2]),
                    "caution_drivers": list(localized_modality_fitness_bundle.get("why_not_surgery") or []),
                    "preference_drivers": patient_priorities,
                    "missing_inputs": list(localized_modality_fitness_bundle.get("missing_modality_fields") or []),
                },
            )
        if grouped.get("observation_family"):
            family_profiles["observation_family"] = build_family_profile(
                family_code="observation_family",
                ordered_regimens=grouped["observation_family"],
                context={
                    "eligibility_status": "eligible",
                    "winner_reason": localized_modality_fitness_bundle.get("dominance_reason")
                    if localized_modality_fitness_bundle.get("dominant_modality") == "observation"
                    else "La observación solo sube cuando la expectativa de vida o el balance beneficio-riesgo reducen la utilidad de terapia local definitiva.",
                    "preference_drivers": patient_priorities,
                },
            )
        comparative_bundle = build_comparative_bundle(
            family_profiles=family_profiles,
            family_order=preferred_family_order,
        )
        preferred_regimen = dict(comparative_bundle.get("preferred_regimen") or {})
        active_monitoring_package = build_active_regimen_monitoring_package(
            preferred_regimen.get("regimen_code"),
            family_code=preferred_regimen.get("family_code") or "observation_family",
            field_values=payload,
        )
        sequence_transition_bundle = build_sequence_transition_bundle(
            state=self.module_id,
            preferred_regimen=preferred_regimen,
            eligible_treatments=comparative_bundle.get("eligible_treatments") or ranked_treatments,
            current_treatment=payload.get("current_treatment") or "",
            missing_critical_inputs=missing,
            progression_pattern=str(payload.get("progression_pattern") or ""),
            line_context="localized_initial",
            field_values=payload,
            monitoring_package=active_monitoring_package,
            comparative_eligibility_matrix=comparative_bundle.get("comparative_eligibility_matrix") or {},
        )
        not_recommended = self._not_recommended(nccn["risk_group"], as_position, genomic_result, adverse_variant_type, prior_pirads, payload)
        durations = self._durations(nccn["risk_group"])
        applicability = as_position["status"] if as_position["eligible"] else ("not_recommended" if as_position.get("requires_escalation") else "guideline-consistent")

        # ── Brecha M-staging gate + RP-cT4 — 2026-04-22 (§E.1-E.3) ─────────────
        # Gate A (staging M obligatorio): si PSA>20, cT2b-T4, ISUP≥4 o Gleason≥8
        # exigen estadificación M (NCCN PROS-2 cat 1; EAU 2026 §6.4) y NO está
        # documentada (sin PSMA PET/CT, sin GGO+TAC/RM, sin imaging_negative_metastases),
        # se BLOQUEA toda emisión curativa y se emite "Completar estadificación M".
        # ProPSMA (Hofman 2020) sustenta PSMA PET/CT preferente.
        # Gate B (RP contraindicada): cT4, invasión rectal/vesical o fijación pélvica
        # contraindican RP+PLND de forma ABSOLUTA (NCCN PROS-3; EAU §6.5.1). Aún si
        # el staging libera Gate A (M0 confirmado), se RETIRA la opción quirúrgica
        # del catálogo manteniendo EBRT+ADT como ruta curativa.
        staging_gap = staging_gap_descriptor(payload)
        rp_block = radical_prostatectomy_contraindicated(payload)
        eligible_treatments_local: list[dict] = list(comparative_bundle.get("eligible_treatments") or ranked_treatments)
        rp_filter_applied = False
        if rp_block.get("contraindicated"):
            rp_keywords = (
                "prostatectom", "prostatectomy", "rp+plnd", "rp + plnd",
                "radical prostatectomy",
            )
            filtered: list[dict] = []
            for treatment in eligible_treatments_local:
                name = str(treatment.get("name") or "").lower()
                if any(kw in name for kw in rp_keywords):
                    rp_filter_applied = True
                    continue
                filtered.append(treatment)
            eligible_treatments_local = filtered
            severity_es = "absolutamente" if rp_block.get("severity") == "absolute" else "relativamente"
            not_recommended.append(
                f"Prostatectomía radical (RP+PLND) {severity_es} contraindicada — "
                f"{'; '.join(rp_block.get('reasons') or [])}. "
                f"Alternativas preferentes: {'; '.join(rp_block.get('alternatives') or [])}. "
                "Referencia: NCCN PROS-3 v5.2026; EAU 2026 §6.5.1."
            )
        # ── Pivotal contraindication gates — Faubot 2026-04-23 ─────────────
        # Filtra abiraterona (HTA descontrolada, ICC NYHA III-IV) y docetaxel
        # (neuropatía severa) cuando el comparador sugiere intensificación
        # sistémica multimodal en VERY HIGH risk (STAMPEDE arm G:
        # RT+ADT+abiraterona). Centraliza las 10 contraindicaciones del
        # módulo `pivotal_contraindication_gates` para mantener consistencia
        # entre dominios (mHSPC, mCRPC, BCR, localizado).
        gate_bundle_local = apply_pivotal_contraindication_gates(payload, eligible_treatments_local)
        eligible_treatments_local = gate_bundle_local["filtered_treatments"]
        for msg in gate_bundle_local["not_recommended_messages"]:
            if msg not in not_recommended:
                not_recommended.append(msg)
        pivotal_gates_local = gate_bundle_local["gates_triggered"]
        if staging_gap and staging_gap.get("blocking"):
            risk_band = (staging_gap.get("risk_band") or "").upper() or "ALTO/MUY ALTO"
            staging_treatments: list[dict] = [{
                "name": "Completar estadificación M antes de iniciar tratamiento curativo",
                "priority": "mandatory_pre_treatment",
                "category": "staging_imaging",
                "notes": (
                    f"Riesgo {risk_band}. "
                    f"Motivos: {'; '.join(staging_gap.get('reasons') or [])}. "
                    f"Pendiente: {', '.join(staging_gap.get('missing_modalities') or [])}. "
                    "Referencia: NCCN PROS-2/PROS-3 v5.2026 cat 1; EAU 2026 §6.4."
                ),
                "next_steps": staging_gap.get("recommended") or [],
            }]
            for item in staging_gap.get("recommended") or []:
                staging_treatments.append({
                    "name": item.get("name") or "Imagenología de estadificación M",
                    "priority": item.get("priority", "first_line"),
                    "category": "staging_imaging",
                    "notes": item.get("rationale") or "",
                })
            eligible_treatments_local = staging_treatments
            not_recommended = [
                "Tratamiento curativo radical (prostatectomía radical, radioterapia definitiva, "
                "RT+ADT prolongada o RT+ADT+abiraterona) DIFERIDO hasta completar estadificación M. "
                f"Probabilidad pre-test de M1 oculto en este perfil de riesgo {risk_band}: alta "
                "(Briganti / ProsTIC nomograms; ProPSMA Hofman 2020). Saltar la estadificación puede "
                "llevar a tratamiento radical en un paciente con M1 sincrónico oculto.",
            ]
            applicability = "blocked_pending_staging"

        psa = float(payload.get("psa", 0) or 0)
        clinical_tstage = str(payload.get("clinical_tstage", "T1c")).upper()
        isup_grade = int(payload.get("isup_grade", 1) or 1)
        num_cores_positive = int(payload.get("num_cores_positive", 0) or 0)
        total_cores = int(payload.get("total_cores", 0) or 0)
        life_expectancy = float(payload.get("life_expectancy_years", 15) or 15)
        case_summary = (
            f"El caso corresponde a enfermedad localizada o regional sin metástasis a distancia, "
            f"con antígeno prostático específico de {psa:g} ng/mL, estadio clínico {clinical_tstage}, "
            f"grupo de grado {isup_grade} de la Sociedad Internacional de Patología Urológica y "
            f"{num_cores_positive}/{total_cores} cilindros positivos. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 lo ubica en {nccn['label']} "
            f"y la Asociación Europea de Urología (EAU) 2026 lo compara como {eau['label']}."
        )

        report_sections = {
            "summary": f"NCCN 5.2026 classifies this patient as {nccn['label']}. EAU 2026 comparison: {eau['label']}.",
            "risk_features": nccn["reasons"],
            "active_surveillance": as_position["summary"],
            "nomograms": {
                "capra": capra,
                "briganti": briganti,
                "partin": partin,
                "mskcc_preop": msk,
                "predict_prostate_ready": predict_ready,
                "prior_mpmri_pirads_score": prior_pirads,
                "adverse_histology_variant_type": adverse_variant_type,
            },
        }

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={
                "guideline": "NCCN",
                "version": "5.2026",
                "label": nccn["label"],
                "risk_group": nccn["risk_group"],
                "recommendation": nccn["recommendation"],
                "reasons": nccn["reasons"],
            },
            eau_comparison={
                "guideline": "EAU",
                "version": "2026",
                "label": eau["label"],
                "risk_group": eau["risk_group"],
                "treatment_intent": eau["treatment_intent"],
                "comparison": comparison,
            },
            eligible_treatments=eligible_treatments_local,
            not_recommended=not_recommended,
            missing_critical_inputs=(
                missing + [f"Estadificación M ({m})" for m in (staging_gap.get("missing_modalities") or [])]
                if (staging_gap and staging_gap.get("blocking")) else missing
            ),
            contraindications=[],
            durations_and_conditions=durations,
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=[
                {"trial": "ProtecT", "match": nccn["risk_group"] in {"LOW", "FAVORABLE INTERMEDIATE"}},
                {"trial": "SPCG-4", "match": nccn["risk_group"] in {"FAVORABLE INTERMEDIATE", "UNFAVORABLE INTERMEDIATE", "HIGH", "VERY HIGH"}},
            ],
            applicability_badge=applicability,
            report_sections=report_sections,
            decision_quality={
                "recommendation_family": preferred_regimen.get("family_label") or nccn["label"],
                "confidence_category": "vigilada" if (missing or localized_modality_fitness_bundle.get("modality_fitness_status") != "clear") else "alta",
                "requires_human_review": bool(as_position.get("requires_escalation")) or localized_modality_fitness_bundle.get("modality_fitness_status") != "clear",
            },
        )
        result["comparative_eligibility_matrix"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        result["therapeutic_family_profiles"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        result["preferred_frontline_regimen"] = preferred_regimen
        result["preferred_regimen_code"] = preferred_regimen.get("regimen_code", "")
        result["alternative_regimens"] = comparative_bundle.get("alternative_regimens") or []
        result["variant_ranking"] = ((family_profiles.get("active_surveillance_family") or {}).get("variant_ranking") or {})
        result["care_setting_contract"] = {
            "care_setting": "curative_local",
            "family_code": preferred_regimen.get("family_code") or "",
            "family_label": preferred_regimen.get("family_label") or "",
        }
        result["active_surveillance_position"] = as_position
        result["localized_modality_fitness_bundle"] = localized_modality_fitness_bundle
        result["localized_tradeoff_bundle"] = localized_tradeoff_bundle
        result["radical_prostatectomy_candidacy_profile"] = radical_prostatectomy_candidacy_profile
        result["localized_survival_context_bundle"] = localized_survival_context_bundle
        result["occam_life_expectancy_bundle"] = occam_life_expectancy_bundle
        result["active_surveillance_monitoring_profile"] = active_surveillance_monitoring_profile
        result["patient_priority_profile"] = patient_priority_profile
        result["score_interpretation_catalog_snapshot"] = score_interpretation_catalog_snapshot
        result["epic26_domain_scores"] = epic26_domain_scores
        result["sequence_transition_bundle"] = sequence_transition_bundle
        result["active_regimen_monitoring_package"] = active_monitoring_package
        if as_position.get("requires_escalation"):
            result["state_classification_override"] = "unsupported_or_escalate"
        # Brecha M-staging gate + RP-cT4 — 2026-04-22:
        # Si Gate A activo, override del estado y forzar revisión humana. Si Gate B
        # disparó (RP filtrada), exponer descriptor para auditoría/UI.
        if staging_gap and staging_gap.get("blocking"):
            result["state_classification_override"] = "staging_required"
            result["requires_human_review"] = True
            result["applicability"] = "blocked_pending_staging"
            result["staging_gap"] = staging_gap
            result.setdefault("decision_quality", {})["requires_human_review"] = True
            result["decision_quality"]["confidence_category"] = "vigilada"
        elif staging_gap:
            # Tier="considered" (intermedio desfavorable) — exponer descriptor
            # informativo sin bloquear tratamiento.
            result["staging_gap"] = staging_gap
        if rp_filter_applied:
            result["rp_contraindication"] = rp_block
        if pivotal_gates_local:
            # Faubot 2026-04-23 — exponer trazabilidad de gates pivotal.
            result["pivotal_contraindication_gates"] = [
                {
                    "code": g.get("code"),
                    "severity": g.get("severity"),
                    "message": g.get("message"),
                    "evidence_tag": g.get("evidence_tag"),
                    "trial_refs": list(g.get("trial_refs") or ()),
                }
                for g in pivotal_gates_local
            ]
        result["phase7_advanced_bundle"] = build_pre_rp_phase7_bundle(payload)
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada de manejo inicial localizado",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                *nccn["reasons"],
                as_position["summary"],
                radical_prostatectomy_candidacy_profile.get("candidate_summary") or "",
                localized_survival_context_bundle.get("summary") or "",
                localized_modality_fitness_bundle.get("dominance_reason") or "",
                localized_tradeoff_bundle.get("tradeoff_summary") or "",
                f"ECOG documentado: {payload.get('ecog_score', 'No documentado')}.",
                f"Índice de Charlson documentado: {payload.get('charlson_score', 'No documentado')}.",
                (
                    (
                        f"Esperanza de vida ajustada: {life_expectancy:g} años, derivada por OCCAM público variante {occam_life_expectancy_bundle.get('variant_label', 'calculada')}."
                        if occam_life_expectancy_bundle.get("source") == "pcothercause_public_repo"
                        else f"Esperanza de vida estimada: {life_expectancy:g} años."
                    )
                    if payload.get("life_expectancy_years") not in (None, "")
                    else "La expectativa de vida queda como contexto secundario y no sustituye fitness/comorbilidad objetivos."
                ),
                (
                    f"Horizonte pronóstico NCCN local: {localized_survival_context_bundle.get('life_expectancy_horizon_label', 'No disponible')}."
                    if localized_survival_context_bundle.get("life_expectancy_horizon_label")
                    else ""
                ),
                f"Puntaje pronóstico CAPRA: {capra.get('score', 'no disponible') if isinstance(capra, dict) else capra}.",
                f"Riesgo ganglionar según Briganti: {briganti.get('risk_pct', 'no disponible') if isinstance(briganti, dict) else briganti}.",
                f"Tablas de Partin: probabilidad de organo-confinamiento {partin.get('oc_prob', 'no disponible')}% y riesgo ganglionar {partin.get('lni_prob', 'no disponible')}%.",
                f"Nomograma preoperatorio MSKCC: organo-confinamiento {msk.get('probabilidad_organo_confinado', msk.get('probabilidad_raw', 'no disponible'))}%.",
                (
                    f"PI-RADS previo documentado: {prior_pirads}."
                    if prior_pirads != "desconocido"
                    else "Falta documentar el PI-RADS de la resonancia magnética previa, lo que reduce la solidez de la decisión en vigilancia activa."
                ),
                (
                    f"Variante histológica adversa documentada: {adverse_variant_type}."
                    if adverse_variant_type not in {"none", ""}
                    else "No se documenta una variante histológica adversa adicional más allá de patrón cribiforme o carcinoma intraductal."
                ),
                "PREDICT Prostate debe correrse cuando las entradas estan completas para cuantificar beneficio absoluto y reforzar la decision compartida."
                if predict_ready
                else "PREDICT Prostate aun no puede correrse con total trazabilidad porque faltan entradas estructuradas de counseling.",
                "Los PROs validados y la señal genómica modulan la conversación entre vigilancia activa, cirugía y radioterapia cuando el caso es limítrofe.",
                (
                    "Prioridades del paciente: " + ", ".join(patient_priorities) + "."
                    if patient_priorities
                    else "Si hoy compiten cirugía y radioterapia, falta cerrar prioridades explícitas del paciente para sostener la recomendación."
                ),
            ],
            alternatives=[
                "Prostatectomía radical o radioterapia definitiva según candidabilidad quirúrgica, preferencia del paciente y disponibilidad local.",
                "Observación clínica cuando el horizonte de beneficio sea limitado o la carga de comorbilidad/fragilidad reduzca el beneficio de un tratamiento local definitivo.",
            ],
            shared_decision_message=(
                "La decisión final debe integrar candidabilidad quirúrgica objetiva, disposición a vigilancia activa, factibilidad de radioterapia y la relevancia de preservar función urinaria, sexual e intestinal con escalas validadas."
            ),
            comparison_message=(
                (
                    "La comparación con la Asociación Europea de Urología (EAU) 2026 coincide en la franja clínica principal "
                    "y ayuda a definir si el caso debe orientarse a vigilancia activa, tratamiento local definitivo o manejo intensificado."
                    if comparison["status"] == "coincide"
                    else "La comparación con la Asociación Europea de Urología (EAU) 2026 muestra una diferencia de guías y debe revisarse junto con la elegibilidad para vigilancia activa, tratamiento local definitivo o intensificación."
                )
            ),
        )

    @staticmethod
    def _missing(payload: dict, required_fields: list[str]) -> list[str]:
        return [field for field in required_fields if str(payload.get(field, "")).strip() == ""]

    @staticmethod
    def _eligible_treatments(
        nccn_group: str,
        as_position: dict,
        genomic_result: str,
        adverse_variant_type: str,
        localized_modality_fitness_bundle: dict,
        radical_prostatectomy_candidacy_profile: dict,
        localized_survival_context_bundle: dict,
    ) -> list[dict]:
        treatments: list[dict] = []
        surgery_status = str(radical_prostatectomy_candidacy_profile.get("candidate_status") or "provisional")
        rt_status = str(localized_modality_fitness_bundle.get("radiotherapy_status") or "provisional")
        plnd_role = str(radical_prostatectomy_candidacy_profile.get("plnd_role") or "consider")
        prefer_observation = bool(localized_survival_context_bundle.get("prefer_observation"))
        life_expectancy_horizon_band = str(localized_survival_context_bundle.get("life_expectancy_horizon_band") or "")
        if as_position.get("requires_escalation"):
            return [
                {
                    "name": "Revisión por uropatología y comité oncológico",
                    "priority": "preferente",
                    "notes": "La variante histológica adversa obliga a revisión experta y definición individualizada de estadificación y tratamiento definitivo.",
                },
                {
                    "name": "Terapia local definitiva tras revisión experta",
                    "priority": "eligible",
                    "notes": "La vigilancia activa no debe plantearse como conducta principal cuando existe una variante histológica adversa de muy alto riesgo.",
                },
            ]
        if as_position["eligible"]:
            treatments.append({"name": "Vigilancia activa", "priority": as_position["status"], "notes": as_position["summary"]})
        if nccn_group == "LOW":
            if prefer_observation:
                observation_note = localized_survival_context_bundle.get("summary") or "El horizonte de beneficio local parece limitado y hace razonable observación clínica."
                if life_expectancy_horizon_band == "le_5_years":
                    observation_note = "Con expectativa de vida menor o igual a 5 años, la observación clínica domina claramente sobre una terapia local definitiva automática."
                elif life_expectancy_horizon_band == "between_5_and_10_years":
                    observation_note = "Entre 5 y 10 años de expectativa de vida, la observación clínica suele ser preferente frente a una terapia local definitiva rutinaria."
                treatments.append({"name": "Observación clínica", "priority": "preferred", "notes": observation_note})
            if rt_status != "blocked":
                rt_priority = "selected_candidate" if life_expectancy_horizon_band == "le_5_years" else "eligible"
                rt_note = "Considérese cuando la vigilancia activa no es aceptable y la factibilidad radioterápica está razonablemente cerrada."
                if life_expectancy_horizon_band == "le_5_years":
                    rt_note = "Solo considérese en casos seleccionados cuando exista una razón clínica fuerte para no seguir observación pese a una expectativa de vida menor o igual a 5 años."
                treatments.append({"name": "Radioterapia definitiva", "priority": rt_priority, "notes": rt_note})
            if surgery_status != "not_candidate":
                surgery_priority = "eligible" if surgery_status == "candidate" else "selected_candidate"
                if life_expectancy_horizon_band == "le_5_years":
                    surgery_priority = "selected_candidate"
                treatments.append({"name": "Prostatectomía radical", "priority": surgery_priority, "notes": radical_prostatectomy_candidacy_profile.get("candidate_summary") or "Para candidatos quirúrgicos apropiados tras decisión compartida."})
        elif nccn_group == "FAVORABLE INTERMEDIATE":
            if rt_status != "blocked":
                rt_priority = "selected_candidate" if life_expectancy_horizon_band == "le_5_years" else "eligible"
                rt_note = "Opción estándar razonable para enfermedad intermedia favorable cuando la radioterapia es factible."
                if life_expectancy_horizon_band == "le_5_years":
                    rt_note = "Con expectativa de vida menor o igual a 5 años, la radioterapia debe reservarse para casos seleccionados y no como salida automática."
                elif life_expectancy_horizon_band == "between_5_and_10_years":
                    rt_note = "Sigue siendo una alternativa válida, pero entre 5 y 10 años de expectativa de vida la observación clínica suele ganar peso en pacientes asintomáticos."
                treatments.append({"name": "Radioterapia definitiva", "priority": rt_priority, "notes": rt_note})
            if surgery_status != "not_candidate":
                surgery_priority = "eligible" if surgery_status == "candidate" else "selected_candidate"
                if life_expectancy_horizon_band == "le_5_years":
                    surgery_priority = "selected_candidate"
                surgery_note = radical_prostatectomy_candidacy_profile.get("candidate_summary") or "Opción estándar para candidatos quirúrgicos apropiados."
                if life_expectancy_horizon_band == "between_5_and_10_years":
                    surgery_note = f"{surgery_note} Entre 5 y 10 años de expectativa de vida, la observación clínica suele competir con más fuerza que una cirugía automática."
                elif life_expectancy_horizon_band == "le_5_years":
                    surgery_note = f"{surgery_note} Con expectativa de vida menor o igual a 5 años, debe quedar como opción muy seleccionada, no dominante."
                treatments.append({"name": "Prostatectomía radical", "priority": surgery_priority, "notes": surgery_note})
            if prefer_observation:
                observation_note = "Puede ser preferente en hombres seleccionados cuando el horizonte de beneficio local es limitado."
                if life_expectancy_horizon_band == "between_5_and_10_years":
                    observation_note = "Entre 5 y 10 años de expectativa de vida, la observación clínica suele ser preferente en intermedio favorable asintomático."
                elif life_expectancy_horizon_band == "le_5_years":
                    observation_note = "Con expectativa de vida menor o igual a 5 años, la observación clínica gana prioridad clara sobre una terapia local definitiva automática en intermedio favorable."
                treatments.append({"name": "Observación clínica", "priority": "preferred", "notes": observation_note})
        elif nccn_group == "UNFAVORABLE INTERMEDIATE":
            treatments.extend([
                {"name": "Radioterapia + terapia de privación androgénica", "priority": "preferred", "notes": "La terapia de privación androgénica de curso corto debe acompañar a la radioterapia en la mayoría de los pacientes elegibles."},
            ])
            if surgery_status != "not_candidate":
                treatments.append({"name": "Prostatectomía radical", "priority": "eligible" if surgery_status == "candidate" else "selected_candidate", "notes": "Úsese en pacientes seleccionados apropiadamente, con planeación ganglionar pélvica cuando esté indicada." if plnd_role == "preferred" else radical_prostatectomy_candidacy_profile.get("candidate_summary") or "Úsese en pacientes seleccionados apropiadamente."})
        elif nccn_group == "HIGH":
            treatments.extend([
                {"name": "Radioterapia externa + terapia de privación androgénica", "priority": "preferred", "notes": "Ruta de intensificación con terapia de privación androgénica prolongada."},
            ])
            if surgery_status != "not_candidate":
                treatments.append({"name": "Prostatectomía radical + disección ganglionar pélvica", "priority": "eligible" if surgery_status == "candidate" else "selected_candidate", "notes": "Para candidatos quirúrgicos seleccionados en centros con experiencia."})
        elif nccn_group == "VERY HIGH":
            treatments.extend([
                {"name": "Radioterapia externa + terapia de privación androgénica", "priority": "preferred", "notes": "Úsese terapia de privación androgénica prolongada e intensificación en hombres elegibles."},
                {"name": "Radioterapia externa + terapia de privación androgénica + abiraterona", "priority": "preferred", "notes": "Ruta de intensificación sistémica para enfermedad de muy alto riesgo."},
            ])
            if surgery_status != "not_candidate":
                treatments.append({"name": "Prostatectomía radical + disección ganglionar pélvica", "priority": "selected_candidate", "notes": "Reservada para candidatos quirúrgicos cuidadosamente seleccionados."})
        else:
            treatments.extend([
                {"name": "Radioterapia definitiva + terapia de privación androgénica", "priority": "preferred", "notes": "Ruta preferente para enfermedad regional N1M0."},
                {"name": "Intensificación sistémica", "priority": "eligible", "notes": "Úsese en enfermedad regional con ganglios positivos cuando el paciente sea elegible según NCCN 2026."},
            ])
        if genomic_result == "Alto":
            for item in treatments:
                if item["name"] == "Vigilancia activa":
                    item["priority"] = "not_preferred"
                    item["notes"] = "Una señal genómica de alto riesgo reduce la confianza en vigilancia activa pese a características clinicopatológicas aparentemente favorables."
        if adverse_variant_type == "ductal_predominant":
            for item in treatments:
                if item["name"] == "Vigilancia activa":
                    item["priority"] = "not_preferred"
                    item["notes"] = "El predominio ductal debe alejar la conversación de una vigilancia activa rutinaria."
        return treatments

    @staticmethod
    def _not_recommended(
        nccn_group: str,
        as_position: dict,
        genomic_result: str,
        adverse_variant_type: str,
        prior_pirads: str,
        payload: dict,
    ) -> list[str]:
        items = []
        if nccn_group in {"UNFAVORABLE INTERMEDIATE", "HIGH", "VERY HIGH", "REGIONAL N1M0"}:
            items.append("La vigilancia activa no debe presentarse como estrategia estándar de manejo en este escenario.")
        if not as_position["eligible"] and nccn_group == "FAVORABLE INTERMEDIATE":
            items.append("Evite presentar la vigilancia activa en intermedio favorable como equivalente a la de bajo riesgo.")
        if genomic_result == "Alto":
            items.append("No minimice un clasificador genómico alto al elegir entre vigilancia y terapia local definitiva.")
        if adverse_variant_type not in {"", "none"}:
            items.append("No presentar vigilancia activa como equivalente a terapia definitiva cuando existe una variante histológica adversa específica.")
        if prior_pirads in {"4", "5"} and str(payload.get("prior_mpmri_targeted_biopsy_status", "desconocido")) != "si":
            items.append("No sostener vigilancia activa con PI-RADS 4 o 5 sin biopsia dirigida documentada.")
        return items

    @staticmethod
    def _durations(nccn_group: str) -> list[str]:
        mapping = {
            "UNFAVORABLE INTERMEDIATE": ["Si se selecciona radioterapia, acompáñela con terapia de privación androgénica por 4 a 6 meses."],
            "HIGH": ["Si se selecciona radioterapia externa, use terapia de privación androgénica por 18 a 36 meses.", "Si se utiliza radioterapia externa con braquiterapia, pueden considerarse 12 meses en pacientes seleccionados."],
            "VERY HIGH": ["Si se selecciona radioterapia externa, use terapia de privación androgénica por 18 a 36 meses.", "Puede considerarse intensificación sistémica con abiraterona en pacientes elegibles."],
            "REGIONAL N1M0": ["La terapia de privación androgénica prolongada suele ser necesaria junto con radioterapia definitiva.", "Escale terapia sistémica en pacientes elegibles."],
        }
        return mapping.get(nccn_group, [])

    @staticmethod
    def _adverse_variant_type(payload: dict) -> str:
        explicit = str(payload.get("adverse_histology_variant_type", "none") or "none").strip()
        if explicit and explicit != "none":
            return explicit
        if str(payload.get("rare_histology_variant", "0")) == "1":
            return "other_aggressive_unspecified"
        return "none"

    @staticmethod
    def _family_order_for_localized(
        nccn_group: str,
        as_position: dict,
        discovered: list[str],
        *,
        dominant_modality: str = "",
    ) -> list[str]:
        if nccn_group == "LOW":
            preferred = ["active_surveillance_family", "observation_family", "radiotherapy_family", "surgery_family"]
            if as_position.get("status") == "observation_preferred":
                preferred = ["observation_family", "active_surveillance_family", "radiotherapy_family", "surgery_family"]
        elif nccn_group == "FAVORABLE INTERMEDIATE":
            preferred = ["radiotherapy_family", "surgery_family", "active_surveillance_family", "observation_family"]
            if as_position.get("status") == "observation_preferred":
                preferred = ["observation_family", "radiotherapy_family", "surgery_family", "active_surveillance_family"]
        elif nccn_group in {"UNFAVORABLE INTERMEDIATE", "HIGH"}:
            preferred = ["radiotherapy_family", "surgery_family", "multimodal_local_family", "active_surveillance_family", "observation_family"]
        else:
            preferred = ["multimodal_local_family", "radiotherapy_family", "surgery_family", "observation_family", "active_surveillance_family"]
        dominant_family = LocalizedInitialService._family_code_for_modality(dominant_modality)
        if dominant_family and dominant_family in discovered:
            preferred = [dominant_family] + [family_code for family_code in preferred if family_code != dominant_family]
        for family_code in discovered:
            if family_code not in preferred:
                preferred.append(family_code)
        return preferred

    @staticmethod
    def _family_code_for_modality(modality: str) -> str:
        return {
            "active_surveillance": "active_surveillance_family",
            "surgery": "surgery_family",
            "radiotherapy": "radiotherapy_family",
            "observation": "observation_family",
            "multimodal_local": "multimodal_local_family",
        }.get(str(modality or "").strip(), "")

    @staticmethod
    def _hydrate_localized_treatment_item(
        item: dict[str, Any],
        *,
        rank: int,
        risk_group: str,
        as_position: dict,
    ) -> dict[str, Any]:
        name = str(item.get("name") or "").strip()
        notes = str(item.get("notes") or "").strip()
        priority = str(item.get("priority") or "eligible").strip()
        lower_name = name.lower()
        regimen_code = "OBSERVATION"
        family_code = "observation_family"
        description = notes or name
        dose = ""
        route = ""
        schedule = ""
        duration = ""
        component_drugs: list[dict[str, Any]] = []
        therapy_class = ""
        evidence_tags: list[str] = []

        if "vigilancia activa" in lower_name:
            regimen_code = "ACTIVE_SURVEILLANCE"
            family_code = "active_surveillance_family"
            route = "Seguimiento estructurado"
            schedule = "PSA seriado + mpMRI + biopsia confirmatoria"
            duration = "Continuo mientras no exista upgrade o progresión"
            description = notes or "Seguimiento estructurado para evitar tratamiento local inmediato sin perder ventana curativa."
        elif "observación clínica" in lower_name:
            regimen_code = "OBSERVATION"
            family_code = "observation_family"
            route = "Seguimiento clínico"
            schedule = "PSA seriado y reevaluación por expectativa de vida/comorbilidad"
            description = notes or "Observación clínica cuando el beneficio de tratamiento local definitivo es bajo."
        elif "prostatectomía radical" in lower_name:
            regimen_code = "RP_PLND" if "ganglionar" in lower_name else "RADICAL_PROSTATECTOMY"
            family_code = "surgery_family"
            route = "Cirugía"
            schedule = "Evento único con seguimiento posoperatorio"
            description = notes or "Tratamiento quirúrgico local definitivo."
        elif "abiraterona" in lower_name:
            regimen_code = "RT_ADT_ABIRATERONE" if risk_group == "VERY HIGH" else "REGIONAL_RT_ADT_ABIRATERONE"
            family_code = "multimodal_local_family"
            dose = "RT definitiva + ADT prolongada + abiraterona"
            route = "Radioterapia externa + Sistémica oral"
            schedule = "RT + ADT prolongada con intensificación"
            duration = "ADT 18-36 meses; abiraterona según elegibilidad"
            description = notes or "Intensificación multimodal local para riesgo muy alto o regional."
        elif "radioterapia" in lower_name:
            family_code = "radiotherapy_family"
            if "privación androgénica" in lower_name or "adt" in lower_name:
                regimen_code = "RT_SHORT_ADT" if risk_group == "UNFAVORABLE INTERMEDIATE" else "RT_LONG_ADT"
                dose = "Radioterapia definitiva + ADT"
                route = "Radioterapia externa + Supresión androgénica"
                schedule = "RT diaria + ADT concomitante"
                duration = "4-6 meses" if risk_group == "UNFAVORABLE INTERMEDIATE" else "18-36 meses"
            else:
                regimen_code = "DEFINITIVE_RT"
                dose = "RT definitiva según técnica elegida"
                route = "Radioterapia externa"
                schedule = "20-39 fracciones según protocolo"
            description = notes or "Tratamiento local definitivo con radioterapia."
        elif "uropatología" in lower_name or "comité oncológico" in lower_name:
            regimen_code = "RESTAGING"
            family_code = "observation_family"
            route = "Revisión multidisciplinaria"
            schedule = "Confirmación histológica y board oncológico"
            description = notes or "Revisión experta antes de cerrar terapia definitiva."

        eligibility_status = (
            "preferred"
            if priority in {"preferred", "preferente", "observation_preferred"}
            else "eligible_with_caution"
            if priority in {"selected_candidate", "not_preferred"}
            else "eligible_nonpreferred"
        )
        why = [notes] if notes else []
        if family_code == "active_surveillance_family" and as_position.get("status") != "preferred":
            why.append(as_position.get("summary") or "La vigilancia activa sigue condicionada por la selección clínica fina.")
        return build_ranked_option(
            name=name,
            regimen_code=regimen_code,
            rank=rank,
            priority="preferred" if eligibility_status == "preferred" else "eligible",
            eligibility_status=eligibility_status,
            family_code=family_code,
            molecule_or_backbone=name,
            description=description,
            dose=dose,
            route=route,
            schedule=schedule,
            duration=duration,
            component_drugs=component_drugs,
            metadata_source="guideline_backbone",
            therapy_class=therapy_class,
            evidence_tags=evidence_tags,
            notes=notes,
            why_this_rank=why,
            selection_rationale=why,
            caution_flags=[] if eligibility_status == "preferred" else why[:1],
        )
