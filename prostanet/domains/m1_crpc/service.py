from __future__ import annotations

from prostanet.shared.precision_medicine_legacy import evaluate_patient_for_mcrpc

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.patient_tracking.arpi_selection_engine import (
    build_arpi_capture_contract,
    candidate_regimens_for_state,
    evaluate_arpi_candidate,
)
from prostanet.domains.patient_tracking.psma_imaging import (
    build_psma_decision_impact,
    build_psma_structured_profile_from_payload,
)
from prostanet.domains.m1_crpc.rules_eau import evaluate_m1_crpc_eau
from prostanet.domains.m1_crpc.rules_nccn import evaluate_m1_crpc
from prostanet.domains.m1_crpc.rules_nepc import evaluate_nepc_pathway
from prostanet.domains.m1_crpc.rules_post_parp import evaluate_post_parp_sequencing
from prostanet.domains.m1_crpc.rules_vision_eligibility import evaluate_vision_eligibility
from prostanet.domains.m1_crpc.schemas import M1_CRPC_SCHEMA
from prostanet.domains.patient_tracking.therapy_catalog import build_treatment_option
from prostanet.domains.patient_tracking.therapeutic_family_engine import (
    build_active_regimen_monitoring_package,
    build_comparative_bundle,
    build_family_profile,
    build_ranked_option,
    build_sequence_transition_bundle,
    regimen_family_code,
)
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.metastatic_profile import build_metastatic_composition_summary
from prostanet.shared.phase7_decision_bundles import build_m1_crpc_phase7_bundle
from prostanet.shared.pivotal_contraindication_gates import (
    apply_pivotal_contraindication_gates,
)
from prostanet.shared.presentation_text import abiraterone_hepatic_contraindication_note
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result
from prostanet.shared.systemic_regimen_scope import build_systemic_regimen_scope_contract


def _flag_truthy(value) -> bool:
    """Helper local para normalizar flags ES-médica/legacy boolean."""
    return str(value or "").strip().lower() in {"1", "true", "yes", "sí", "si", "positivo"}


class M1CrpcService:
    module_id = "m1_crpc"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return M1_CRPC_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        nccn = evaluate_m1_crpc(payload)
        eau = evaluate_m1_crpc_eau(payload)
        comparison = self.comparison.compare(nccn, eau)
        normalized = dict(payload)
        if isinstance(normalized.get("prior_therapy"), str):
            normalized["prior_therapy"] = [item.strip() for item in normalized["prior_therapy"].split(",") if item.strip()]
        legacy = evaluate_patient_for_mcrpc(normalized)
        biomarker_source = str(payload.get("biomarker_source", "Desconocida"))
        hrr_gene = str(payload.get("hrr_gene", "Desconocido"))
        psma_negative_dominant_lesions = str(payload.get("psma_negative_dominant_lesions", "0")) == "1"
        psma_profile = (
            build_psma_structured_profile_from_payload(payload)
            if str(payload.get("psma_pet_done", "0")) == "1" or str(payload.get("psma_positive", "0")) == "1"
            else {"available": False}
        )
        psma_impact = build_psma_decision_impact(psma_profile, state=self.module_id, patient={"baseline": payload})
        molecular_report_date = str(payload.get("molecular_report_date", "")).strip()
        biomarker_traceable = biomarker_source not in {"", "Desconocida", "Desconocido"} and (not nccn["hrr_positive"] or hrr_gene not in {"", "Desconocido"})
        explicit_partial_psma = psma_profile.get("source_mode") == "structured" and (
            psma_impact.get("confidence") == "low"
            or str(psma_profile.get("psma_radioligand") or "") in {"", "Desconocido"}
            or str(psma_profile.get("psma_rads_score") or "") == "3"
        )
        taxane_candidate_now = bool(nccn.get("taxane_candidate_now"))
        taxane_verified = str(nccn.get("docetaxel_verification_status") or "verified") == "verified"
        taxane_available_now = (
            taxane_candidate_now
            and str(nccn.get("docetaxel_base_eligibility") or "") in {"eligible", "eligible_with_caution"}
            and taxane_verified
        )
        taxane_needs_verification = taxane_candidate_now and not taxane_verified
        taxane_blocked_now = str(nccn.get("docetaxel_base_eligibility") or "") == "contraindicated"
        abiraterone_hard_block = bool(nccn.get("abiraterone_hard_block"))
        abiraterone_caution = bool(nccn.get("abiraterone_caution"))
        current_medications_present = bool(nccn.get("current_medications_present"))
        ddi_reviewed = str(nccn.get("ddi_review_status") or "").strip().lower() == "completed"
        seizure_risk = bool(nccn.get("comorbidity_seizure"))
        frailty_status = str(nccn.get("frailty_status") or "Fit").strip().lower()
        # Auditoría Pacientes Insignia 2026-04-21 (§D.4) — gates IO/hematología.
        severe_neutropenia_active = _flag_truthy(payload.get("severe_neutropenia_grade4"))
        active_immunosuppression = _flag_truthy(payload.get("active_immunosuppression"))
        active_autoimmune_disease = _flag_truthy(payload.get("active_autoimmune_disease"))
        # VISION/PSMAfore formal eligibility checker (EPIC 3) — enforza SUV
        # lesión ≥ SUV hígado, ECOG 0-2, exposición ARPI previa, reserva
        # medular/renal preservada y ausencia de lesiones PSMA-negativas dominantes.
        vision_bundle = evaluate_vision_eligibility(payload, m1_context=nccn)
        vision_eligibility_label = str(vision_bundle.get("eligibility_label") or "")
        vision_eligible = vision_eligibility_label == "vision_full"
        pre_taxane_pluvicto_candidate = vision_eligibility_label == "psmafore_pre_taxane" or (
            vision_eligibility_label == "partial"
            and nccn["psma_positive"]
            and not psma_negative_dominant_lesions
            and nccn["prior_arpi"]
            and not nccn["prior_docetaxel"]
            and (
                nccn["chemotherapy_delay_candidate"]
                or taxane_blocked_now
                or taxane_needs_verification
                or str(nccn.get("docetaxel_default_intensification") or "") == "conditional"
                or nccn["line_context"] == "post_arpi_pre_taxane"
            )
            and not explicit_partial_psma
        )
        # NEPC pathway (EPIC 3): sospecha + confirmación histológica + regímenes platino
        nepc_bundle = evaluate_nepc_pathway(payload, m1_context=nccn)
        # Post-PARP sequencing (EPIC 3): aplica sólo si paciente tuvo PARPi previo
        post_parp_bundle = evaluate_post_parp_sequencing(
            payload,
            m1_context=nccn,
            vision_bundle=vision_bundle,
            nepc_bundle=nepc_bundle,
        )
        prior_arpi_duration = float(payload.get("prior_arpi_duration_months", 0) or 0)
        prior_arpi_duration_documented = str(payload.get("prior_arpi_duration_months", "")).strip() != ""
        card_applicable = nccn["prior_arpi"] and nccn["prior_docetaxel"]
        card_fully_validated = card_applicable and prior_arpi_duration_documented and prior_arpi_duration >= 6
        supportive_context = [
            "La recomendación principal permanece anclada a la Red Nacional Integral del Cáncer (NCCN) 5.2026 y la Asociación Europea de Urología (EAU) 2026.",
            "CARD se usa para priorizar cabazitaxel sobre un intercambio ARPI-ARPI cuando ya hubo docetaxel y ARPI previo.",
            "VISION se usa para exigir elegibilidad PSMA estructurada y exposición previa correcta antes de priorizar lutecio-177 PSMA-617.",
            "PROfound se usa para exigir biomarcador HRR trazable por gen y por fuente analítica antes de priorizar olaparib.",
            "Las rutas de primera línea guiadas por biomarcadores se restringen a contexto first-line mCRPC y a biomarcadores trazables.",
            psma_impact.get("rationale"),
        ]
        arpi_candidate_regimens = candidate_regimens_for_state(self.module_id, payload)
        arpi_capture_contract = build_arpi_capture_contract(
            self.module_id,
            payload,
            candidate_regimens=arpi_candidate_regimens,
        )
        treatments = []
        missing_inputs = []
        not_recommended = [
            "Avoid repeating exhausted ARPI sequences without a biomarker or sequencing rationale.",
            "Do not offer Radium-223 in visceral metastatic disease.",
            "Do not use MRI or PET as routine monitoring tools outside a trial-oriented or decision-changing context.",
        ]

        if not nccn["castrate_confirmed"]:
            treatments.append(
                {
                    "name": "Confirm castrate testosterone and optimize ADT",
                    "priority": "preferred",
                    "notes": "No debe secuenciarse como enfermedad resistente a la castración con metástasis sin confirmar testosterona en rango de castración.",
                }
            )
            missing_inputs.append("castrate_testosterone_confirmed")
            not_recommended.append("Do not intensify or relabel as mCRPC until castrate-range testosterone is documented.")
        else:
            if nccn["line_context"] == "first_line_mcrpc" and not nccn["prior_arpi"]:
                frontline_candidates = []
                if not nccn["prior_enza_class"]:
                    arpi_meta = evaluate_arpi_candidate(
                        self.module_id,
                        payload,
                        "ADT_ENZALUTAMIDE",
                        candidate_regimens=arpi_candidate_regimens,
                    )
                    enzalutamide_notes = [
                        "Ruta estándar de primera línea mCRPC antes de reciclar clases o saltar directamente a inmunoterapia por biomarcadores aislados."
                    ]
                    if arpi_meta.get("benefit_basis"):
                        enzalutamide_notes.append(str(arpi_meta.get("benefit_basis") or ""))
                    enzalutamide_notes.extend(list(arpi_meta.get("safety_rationale") or []))
                    if arpi_meta.get("required_missing_fields"):
                        enzalutamide_notes.append(
                            "Perfil ARPI incompleto: " + ", ".join(arpi_meta.get("required_missing_fields") or [])
                        )
                    frontline_candidates.append(
                        {
                            "name": "Enzalutamide",
                            "score": float(arpi_meta.get("benefit_adjustment") or 0.0),
                            "notes": " ".join(enzalutamide_notes),
                            "arpi_meta": arpi_meta,
                        }
                    )
                if not nccn["prior_abiraterone"] and not abiraterone_hard_block:
                    arpi_meta = evaluate_arpi_candidate(
                        self.module_id,
                        payload,
                        "ADT_ABIRATERONE",
                        candidate_regimens=arpi_candidate_regimens,
                    )
                    abiraterone_notes = [
                        "Alternativa estándar de primera línea mCRPC cuando no existe contraindicación hepática relevante."
                    ]
                    if arpi_meta.get("benefit_basis"):
                        abiraterone_notes.append(str(arpi_meta.get("benefit_basis") or ""))
                    abiraterone_notes.extend(list(arpi_meta.get("safety_rationale") or []))
                    if arpi_meta.get("required_missing_fields"):
                        abiraterone_notes.append(
                            "Perfil ARPI incompleto: " + ", ".join(arpi_meta.get("required_missing_fields") or [])
                        )
                    frontline_candidates.append(
                        {
                            "name": "Acetato de Abiraterona",
                            "score": float(arpi_meta.get("benefit_adjustment") or 0.0),
                            "notes": " ".join(abiraterone_notes),
                            "arpi_meta": arpi_meta,
                        }
                    )
                elif not nccn["prior_abiraterone"] and abiraterone_hard_block:
                    not_recommended.append("No priorizar abiraterona cuando existe riesgo hepático clínicamente relevante o Child-Pugh B/C.")
                frontline_candidates.sort(key=lambda item: (item["score"], item["name"]), reverse=True)
                for index, item in enumerate(frontline_candidates):
                    arpi_meta = dict(item.get("arpi_meta") or {})
                    definitive = str(arpi_meta.get("preference_confidence") or "definitive") == "definitive"
                    treatments.append(
                        {
                            "name": item["name"],
                            "priority": "preferred" if index == 0 and definitive else "eligible",
                            "notes": item["notes"],
                            "benefit_basis": arpi_meta.get("benefit_basis", ""),
                            "benefit_endpoint_used": arpi_meta.get("benefit_endpoint_used", ""),
                            "benefit_maturity": arpi_meta.get("benefit_maturity", ""),
                            "preference_confidence": arpi_meta.get("preference_confidence", "definitive"),
                            "required_missing_fields": list(arpi_meta.get("required_missing_fields") or []),
                            "stale_inputs": list(arpi_meta.get("stale_inputs") or []),
                            "safety_drivers_used": list(arpi_meta.get("safety_drivers_used") or []),
                        }
                    )
            if nccn["line_context"] == "first_line_mcrpc" and nccn["hrr_positive"] and biomarker_traceable and not nccn["prior_enza_class"]:
                treatments.append(
                    {
                        "name": "Talazoparib + Enzalutamide",
                        "priority": "selected_candidate",
                        "notes": "Ruta de precisión first-line válida cuando el biomarcador HRR es trazable, pero no debe sobreponerse automáticamente a la secuencia estándar ARPI en esta v1 clínica.",
                    }
                )
            if nccn["line_context"] == "first_line_mcrpc" and nccn["brca_pathway"] and biomarker_traceable and not nccn["prior_abiraterone"]:
                if not abiraterone_hard_block:
                    treatments.append(
                        {
                            "name": "Niraparib + Abiraterone",
                            "priority": "selected_candidate",
                            "notes": f"Ruta BRCA de primera línea con biomarcador trazable ({hrr_gene}); se muestra como overlay de precisión y no como sustituto automático de la secuencia estándar ARPI.",
                        }
                    )
                else:
                    # Auditoría Pacientes Insignia 2026-04-21 (§B.2) — MAGNITUDE
                    # (niraparib+abiraterona) bloqueado por hepatopatía; ofrecer
                    # monoterapia olaparib como alternativa HRR+ cuando el
                    # biomarcador es trazable.
                    not_recommended.append(
                        abiraterone_hepatic_contraindication_note(
                            "MAGNITUDE (niraparib + abiraterona)",
                            "olaparib monoterapia si HRR+/BRCA2+ trazable",
                        )
                    )
            if biomarker_traceable and nccn["prior_arpi"]:
                treatments.append(
                    {
                        "name": "Olaparib",
                        "priority": "preferred",
                        "notes": (
                            self._note_for(legacy, "Olaparib")
                            or f"Biomarcador HRR trazable ({hrr_gene}) documentado desde {biomarker_source.lower()}."
                        ),
                    }
                )
            # Pembrolizumab (KEYNOTE-158 / KEYNOTE-199) — MSI-H O dMMR O TMB ≥10 mut/Mb.
            # EPIC 3: dMMR por IHC y variantes MMR somáticas/germinales amplían el candidato
            # incluso cuando MSI PCR no es documentada.
            if nccn.get("pembrolizumab_candidate") or nccn["msi_high"] or nccn["tmb_high"]:
                if nccn.get("dmmr_high_confidence"):
                    pembro_priority = "preferred"
                    pembro_note = (
                        "MSI-H/dMMR confirmado (MSI inestable, IHC MMR deficiente o variante MMR somática/germinal) — "
                        "pembrolizumab es terapia dirigida categoría 2A según KEYNOTE-158 y KEYNOTE-199."
                    )
                elif nccn["tmb_high"]:
                    pembro_priority = "eligible"
                    pembro_note = (
                        "TMB ≥10 mut/Mb documentado — pembrolizumab habilitado por aprobación agnóstica FDA 2020 "
                        "(Marabelle JCO 2020). Recomendar biopsia IHC MMR antes de iniciar si hay dudas."
                    )
                else:
                    pembro_priority = "eligible"
                    pembro_note = (
                        self._note_for(legacy, "Pembrolizumab")
                        or "Vía inmunológica habilitada por biomarcador inmune accionable."
                    )
                treatments.append(
                    {
                        "name": "Pembrolizumab",
                        "priority": pembro_priority,
                        "notes": pembro_note,
                    }
                )
            # ── AR-V7: preferir quimioterapia sobre ARPI (PROPHECY / Antonarakis 2014) ──
            # EPIC 3.7: la resistencia a ARPI se asume documentada con AR-V7+,
            # por lo que la recomendación de taxano se emite incluso con labs
            # pendientes de verificar (se explicita la verificación como caveat).
            if nccn["ar_v7_positive"] and nccn["prior_arpi"]:
                if not nccn["prior_docetaxel"] and not taxane_blocked_now:
                    arv7_notes = [
                        "AR-V7 positivo predice resistencia a ARPI. PROPHECY (Armstrong 2019) y "
                        "Antonarakis NEJM 2014 respaldan preferir taxanos sobre secuenciar otro ARPI."
                    ]
                    arv7_priority = "preferred"
                    if taxane_needs_verification:
                        arv7_notes.append(
                            "Verificación pre-taxano pendiente (CBC/LFT/neuropatía) — iniciar tan pronto "
                            "se cierren labs de seguridad."
                        )
                        arv7_priority = "selected_candidate"
                    treatments.append({
                        "name": "Docetaxel (AR-V7 dirigido)",
                        "priority": arv7_priority,
                        "notes": " ".join(arv7_notes),
                    })
                if not nccn["prior_docetaxel"] and taxane_needs_verification:
                    for field in list(nccn.get("docetaxel_missing_inputs") or []) + list(nccn.get("docetaxel_stale_inputs") or []):
                        if field not in missing_inputs:
                            missing_inputs.append(field)
                if nccn["prior_docetaxel"]:
                    # Post-docetaxel AR-V7+: cabazitaxel sigue siendo la mejor ruta
                    # (CARD) — ya se genera por card_applicable, reforzar not_recommended.
                    pass
                not_recommended.append(
                    "No secuenciar otro ARPI cuando AR-V7 es positivo — la resistencia está documentada (PROPHECY, Antonarakis 2014)."
                )
            # ── NEPC pathway (EPIC 3) — usa evaluate_nepc_pathway con IHC + score Aggarwal ──
            # Regla: si confirmado histológicamente → platino; si sospechado con score ≥5
            # → biopsia dirigida; si score ≥3 → monitoreo intensivo y no continuar ARPI.
            if nepc_bundle.get("nepc_confirmed"):
                for regimen in nepc_bundle.get("regimens") or []:
                    reg_code = str(regimen.get("regimen_code") or "")
                    reg_priority = str(regimen.get("priority") or "eligible")
                    if reg_priority == "not_eligible":
                        for block in regimen.get("hard_blocks") or []:
                            not_recommended.append(f"NEPC {regimen.get('drug_label', reg_code)}: {block}")
                        continue
                    drug_label = str(regimen.get("drug_label") or reg_code)
                    regimen_notes = [str(regimen.get("rationale") or "")]
                    if regimen.get("dose"):
                        regimen_notes.append(f"Dosis: {regimen['dose']}")
                    treatments.append({
                        "name": drug_label,
                        "priority": reg_priority,
                        "notes": " ".join(filter(None, regimen_notes)),
                    })
                not_recommended.append(
                    "NEPC confirmado histológicamente — suspender ARPI como línea activa y pasar a esquema platino."
                )
            elif nepc_bundle.get("nepc_suspected"):
                if nepc_bundle.get("biopsy_trigger"):
                    treatments.append({
                        "name": "Biopsia dirigida con IHC neuroendocrina",
                        "priority": "preferred",
                        "notes": (
                            f"Score NEPC {nepc_bundle.get('suspicion_score', 0)}/8 alcanza el umbral de biopsia. "
                            "Indicar sitio viscerales/ganglionar y solicitar IHC sinaptofisina + cromogranina A + Ki-67 + AR "
                            "antes de iniciar esquema platino."
                        ),
                    })
                treatments.append({
                    "name": "Monitoreo intensivo NEPC",
                    "priority": "eligible",
                    "notes": (
                        f"Score NEPC {nepc_bundle.get('suspicion_score', 0)}/8 — vigilar NSE/LDH/CgA, PSA discordante bajo "
                        "y progresión viscerales sin óseo. Considerar biopsia dirigida si la puntuación sube."
                    ),
                })
                not_recommended.append(
                    "No continuar ARPI como línea principal sin biopsia IHC si existe sospecha fuerte de NEPC."
                )
            elif nccn["lineage_plasticity_risk"]:
                treatments.append({
                    "name": "Monitoreo intensivo NEPC",
                    "priority": "eligible",
                    "notes": "TP53 + RB1 loss documentados — riesgo de lineage plasticity. Monitorear NSE, LDH, cromogranina A y PSA discordante bajo. Considerar biopsia si progresa.",
                })
            # ── PTEN loss → inhibidores AKT (IPATential150 / CAPItello-281) ──
            if nccn["pten_loss"]:
                if not abiraterone_hard_block:
                    treatments.append({
                        "name": "Ipatasertib + Abiraterona",
                        "priority": "eligible",
                        "notes": "PTEN loss documentado. IPATential150 (de Bono 2020) mostró beneficio en rPFS en subgrupo PTEN-loss. Considerar si no hay contraindicación a abiraterona.",
                    })
                else:
                    # Auditoría Pacientes Insignia 2026-04-21 (§B.2) — IPATential150
                    # bloqueado por hepatopatía; sugerir capivasertib+abiraterona NO
                    # aplica (también abiraterona). Alternativa: docetaxel o ARPI
                    # hepáticamente seguro (enzalutamida/darolutamida).
                    not_recommended.append(
                        abiraterone_hepatic_contraindication_note(
                            "IPATential150 (ipatasertib + abiraterona)",
                            "enzalutamida o darolutamida con monitoreo de PTEN loss",
                        )
                    )
                supportive_context.append("PTEN loss activa la vía PI3K/AKT y se asocia a peor pronóstico bajo ARPI estándar (Jamaspishvili 2018).")
            # ── CDK12 biallelic → alta carga neoantigénica → IO (Wu 2018) ──
            if nccn["cdk12_biallelic"] and not (nccn["msi_high"] or nccn["tmb_high"]):
                treatments.append({
                    "name": "Pembrolizumab (CDK12-dirigido)",
                    "priority": "eligible",
                    "notes": "CDK12 bialélico genera alta carga neoantigénica independiente de MSI-H. Wu 2018 y Antonarakis 2020 respaldan inmunoterapia en este contexto.",
                })
            # ── TMB zona gris (6-10 mut/Mb) → monitoreo ──
            if nccn["tmb_zone"] == "gray" and not nccn["msi_high"]:
                treatments.append({
                    "name": "Monitoreo TMB zona gris",
                    "priority": "eligible",
                    "notes": f"TMB {nccn['tmb_value']:.0f} mut/Mb en zona gris (6-10). No alcanza umbral para IO, pero monitorear si sube en siguiente biopsia líquida.",
                })
            # ── ctDNA rising → señal de resistencia temprana (Wyatt 2021) ──
            if nccn["ctdna_rising"]:
                not_recommended.append("ctDNA en ascenso sugiere resistencia emergente — anticipar cambio de línea antes de progresión radiográfica (Wyatt 2021, Chi 2022).")
            # VISION/PSMAfore — rutas surtidas por el checker formal (EPIC 3).
            if vision_eligible:
                vision_notes = [
                    self._note_for(legacy, "Lu-177 PSMA")
                    or "Elegibilidad VISION documentada: PSMA+ post-ARPI post-taxano con SUV lesión ≥ hígado."
                ]
                vision_notes.extend(list(vision_bundle.get("cautions") or []))
                treatments.append(
                    {
                        "name": "Lu-177 PSMA-617",
                        "priority": "preferred",
                        "notes": " ".join(filter(None, vision_notes)),
                    }
                )
            elif pre_taxane_pluvicto_candidate:
                psmafore_notes = [
                    "PSMAfore: PSMA+ pre-taxano con racional clínico para diferir docetaxel — SUV lesión ≥ hígado verificado."
                    if vision_eligibility_label == "psmafore_pre_taxane"
                    else "PSMA positivo documentado en contexto pre-taxano con necesidad clínica de diferir o evitar docetaxel."
                ]
                psmafore_notes.extend(list(vision_bundle.get("cautions") or []))
                treatments.append(
                    {
                        "name": "Lu-177 PSMA-617",
                        "priority": "selected_candidate" if vision_eligibility_label != "psmafore_pre_taxane" else "preferred",
                        "notes": " ".join(filter(None, psmafore_notes)),
                    }
                )
            elif nccn["psma_positive"] and nccn["prior_arpi"]:
                treatments.append(
                    {
                        "name": "Lu-177 PSMA-617",
                        "priority": "selected_candidate",
                        "notes": (
                            "PSMA positivo documentado, pero la elegibilidad de radioligando sigue siendo parcial — "
                            "completar SUV per-lesión, SUV hígado y bundle hematológico para confirmar VISION/PSMAfore."
                        ),
                    }
                )
            for hard_block in vision_bundle.get("hard_blocks") or []:
                not_recommended.append(f"VISION/PSMAfore: {hard_block}")
            for missing_field in vision_bundle.get("missing_inputs") or []:
                if missing_field not in missing_inputs:
                    missing_inputs.append(missing_field)
            if str(psma_profile.get("psma_radioligand") or "") == "18F-PSMA-1007":
                not_recommended.append("Usar cautela al sobreinterpretar hallazgos óseos dudosos con 18F-PSMA-1007 cuando la decisión dependa exclusivamente del PET.")
            if nccn["symptomatic_bone_only"]:
                treatments.append({"name": "Radium-223", "priority": "eligible", "notes": self._note_for(legacy, "Radium-223")})
            # ── Auditoría Pacientes Insignia 2026-04-21 (§A.4) ────────────
            # IMPACT (Kantoff NEJM 2010) — Sipuleucel-T en mCRPC asintomático
            # o mínimamente sintomático, sin metástasis viscerales, sin uso
            # crónico de opioides y sin exposición previa a docetaxel.
            # Contraindicado si hay inmunosupresión activa (respuesta
            # autóloga insuficiente).
            if nccn.get("impact_candidate"):
                if not nccn.get("impact_blocked_by_immunosuppression"):
                    treatments.append({
                        "name": "Sipuleucel-T",
                        "priority": "selected_candidate",
                        "notes": (
                            "IMPACT (Kantoff NEJM 2010;363:411): inmunoterapia autóloga para mCRPC "
                            "asintomático o mínimamente sintomático sin metástasis viscerales, "
                            "pre-docetaxel, sin uso crónico de opioides. OS mediana +4.1 meses vs placebo."
                        ),
                        "evidence_tag": "impact_2010_sipuleucel_t",
                    })
                else:
                    not_recommended.append(
                        "Sipuleucel-T (IMPACT) contraindicado por inmunosupresión activa — "
                        "la respuesta inmunitaria autóloga es insuficiente en este contexto. "
                        "Priorizar otras opciones de primera línea mCRPC."
                    )
            # Auditoría Pacientes Insignia 2026-04-21 (§D.4) — neutropenia grado 4
            # activa aplaza taxanos hasta recuperación (ANC >1000/µL). El
            # gate dispara incluso cuando la verificación de labs taxano
            # todavía está pendiente: la neutropenia G4 es un bloqueo duro
            # independiente de la completitud de laboratorio.
            _taxane_scenario = card_applicable or (
                not nccn["prior_docetaxel"]
                and (
                    bool(nccn.get("taxane_candidate_now"))
                    or taxane_available_now
                    or taxane_needs_verification
                )
            )
            if severe_neutropenia_active and _taxane_scenario:
                not_recommended.append(
                    "Docetaxel/cabazitaxel aplazado hasta resolución de neutropenia grado 4 "
                    "activa (ANC <500/µL). Reanudar con ANC >1000/µL y considerar G-CSF "
                    "profiláctico para los ciclos siguientes (TAX-327 / CARD / TROPIC)."
                )
            elif card_applicable:
                card_priority = "preferred" if card_fully_validated else "eligible"
                card_notes = self._note_for(legacy, "Cabazitaxel") or "CARD respalda priorizar cabazitaxel sobre secuenciar otro ARPI tras docetaxel y ARPI previo."
                if not prior_arpi_duration_documented:
                    card_notes += " Nota: duración de ARPI previo no documentada — verificar ≥6 meses per CARD (de Wit 2019) para confirmar prioridad."
                elif prior_arpi_duration < 6:
                    card_notes += f" Precaución: duración de ARPI previo ({prior_arpi_duration:.0f} meses) <6 meses — CARD requería ≥6 meses de exposición previa."
                treatments.append(
                    {
                        "name": "Cabazitaxel",
                        "priority": card_priority,
                        "notes": card_notes,
                    }
                )
            elif not nccn["prior_docetaxel"] and taxane_available_now:
                treatments.append(
                    {
                        "name": "Docetaxel",
                        "priority": "eligible",
                        "notes": (
                            self._note_for(legacy, "Docetaxel")
                            or "Docetaxel sigue siendo una alternativa estructurada cuando la elegibilidad taxano ya fue verificada y no hay exposición previa."
                        ),
                    }
                )
            elif not nccn["prior_docetaxel"] and taxane_needs_verification:
                for field in list(nccn.get("docetaxel_missing_inputs") or []) + list(nccn.get("docetaxel_stale_inputs") or []):
                    if field not in missing_inputs:
                        missing_inputs.append(field)
                not_recommended.append("No cerrar una ruta taxano en mCRPC sin verificar antes CBC/LFT y seguridad estructurada de docetaxel.")
            elif not nccn["prior_docetaxel"] and taxane_blocked_now:
                not_recommended.append("Docetaxel no debe competir hoy porque la elegibilidad taxano está clínicamente bloqueada.")
            # ── Auditoría Pacientes Insignia 2026-04-21 (§A.4) ────────────
            # CONTACT-02 (Agarwal Lancet Oncol 2024) — Cabozantinib + Atezolizumab
            # en mCRPC post-ARPI con enfermedad visceral o adenopatías
            # extra-pélvicas que rehúsan o no son candidatos a docetaxel.
            # Mejora rPFS vs switch ARPI. Contraindicado con enfermedad
            # autoinmune activa (atezolizumab puede exacerbar autoinmunidad).
            if nccn.get("contact02_candidate"):
                treatments.append({
                    "name": "Cabozantinib + Atezolizumab",
                    "priority": "selected_candidate",
                    "notes": (
                        "CONTACT-02 (Agarwal Lancet Oncol 2024;25:1267): mCRPC post-ARPI con "
                        "enfermedad visceral o adenopatías extra-pélvicas, en pacientes que "
                        "rehúsan o no son candidatos a docetaxel. Mejora rPFS vs switch de "
                        "ARPI. Screening basal de autoinmunidad y monitoreo hepático."
                    ),
                    "evidence_tag": "contact02_2024_cabozantinib_atezolizumab",
                })
            elif nccn.get("contact02_blocked_by_autoimmune"):
                not_recommended.append(
                    "CONTACT-02 (cabozantinib + atezolizumab) contraindicado por enfermedad "
                    "autoinmune activa — atezolizumab puede exacerbar autoinmunidad. "
                    "Considerar alternativas no inmunoterapéuticas (switch ARPI, cabazitaxel "
                    "si taxano apto, radioligand si PSMA+)."
                )
            # ── Post-PARP sequencing (EPIC 3) — añade rutas ortogonales si hubo PARPi previo ──
            if post_parp_bundle.get("applicable"):
                existing_regimen_codes = {
                    str(t.get("regimen_code") or t.get("name") or "").upper()
                    for t in treatments
                }
                for candidate in post_parp_bundle.get("candidates") or []:
                    regimen_code = str(candidate.get("regimen_code") or "").upper()
                    candidate_priority = str(candidate.get("priority") or "eligible")
                    if candidate_priority == "not_eligible":
                        for block in candidate.get("hard_blocks") or []:
                            not_recommended.append(
                                f"Post-PARP {candidate.get('drug_label', regimen_code)}: {block}"
                            )
                        continue
                    if regimen_code in existing_regimen_codes:
                        # Ya existe (CARD / VISION) — anotar contexto post-PARP sin duplicar.
                        for existing in treatments:
                            if str(existing.get("regimen_code") or existing.get("name") or "").upper() == regimen_code:
                                existing_notes = str(existing.get("notes") or "").strip()
                                post_parp_note = (
                                    f"Post-PARP: {candidate.get('rank_reason') or ''}"
                                ).strip()
                                if post_parp_note and post_parp_note not in existing_notes:
                                    existing["notes"] = (
                                        f"{existing_notes} {post_parp_note}" if existing_notes else post_parp_note
                                    ).strip()
                                break
                        continue
                    post_parp_notes = list(
                        filter(
                            None,
                            [
                                str(candidate.get("rank_reason") or ""),
                                str(candidate.get("notes") or ""),
                            ],
                        )
                    )
                    treatments.append(
                        {
                            "name": str(candidate.get("drug_label") or regimen_code),
                            "priority": candidate_priority,
                            "notes": " ".join(post_parp_notes),
                        }
                    )
                    existing_regimen_codes.add(regimen_code)
                for missing_field in post_parp_bundle.get("missing_inputs") or []:
                    if missing_field not in missing_inputs:
                        missing_inputs.append(missing_field)
                supportive_context.append(
                    "Post-progresión a PARPi (CARD de Wit 2019, VISION Sartor 2021, PSMAfore Morris 2024, "
                    "Schmid 2022 platinum rechallenge) — prioridad a mecanismos ortogonales al PARP "
                    "con reserva medular preservada y biomarcador accionable."
                )
            if nccn["rare_histology_variant"] or nccn["neuroendocrine_features"]:
                not_recommended.append("Do not assume standard adenocarcinoma sequencing remains appropriate when rare aggressive or neuroendocrine features are present.")
        case_summary = (
            "El caso corresponde a enfermedad resistente a la castración con metástasis y requiere secuenciación terapéutica basada en biomarcadores, exposición previa y distribución metastásica. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 lo resume como {nccn['label']} "
            f"y la Asociación Europea de Urología (EAU) 2026 lo contrasta como {eau['label']}."
        )
        metastatic_summary = build_metastatic_composition_summary(payload)
        if metastatic_summary.get("available"):
            case_summary = f"{case_summary} {metastatic_summary.get('narrative')}"
        if nccn["hrr_positive"] and biomarker_source in {"", "Desconocida", "Desconocido"}:
            missing_inputs.append("biomarker_source")
        if nccn["hrr_positive"] and hrr_gene in {"", "Desconocido"}:
            missing_inputs.append("hrr_gene")
        if (nccn["hrr_positive"] or nccn["msi_high"] or nccn["tmb_high"] or nccn["brca_pathway"]) and not molecular_report_date:
            missing_inputs.append("molecular_report_date")
        if nccn["psma_positive"] and psma_negative_dominant_lesions:
            missing_inputs.append("psma_negative_dominant_lesions")
        if card_applicable:
            not_recommended.append("No priorizar un intercambio ARPI-ARPI por encima de cabazitaxel tras docetaxel y ARPI previo salvo justificación biomolecular clara.")
            if not prior_arpi_duration_documented:
                missing_inputs.append("prior_arpi_duration_months")
        if nccn["hrr_positive"] and not biomarker_traceable:
            not_recommended.append("No priorizar PARP sin gen HRR y fuente del biomarcador claramente trazables.")
        if nccn["psma_positive"] and psma_negative_dominant_lesions:
            not_recommended.append("No priorizar lutecio-177 PSMA-617 si existen lesiones dominantes PSMA-negativas no resueltas.")
        if explicit_partial_psma:
            not_recommended.append("No etiquetar la elegibilidad PSMA como plena cuando PSMA-RADS es intermedio, el radioligando es desconocido o la documentación estructurada es insuficiente.")
        missing_inputs.extend(arpi_capture_contract.get("arpi_missing_inputs") or [])
        missing_inputs.extend(arpi_capture_contract.get("arpi_stale_inputs") or [])
        missing_inputs = list(dict.fromkeys(missing_inputs))
        not_recommended = list(dict.fromkeys(not_recommended))

        preferred_seen = False
        for item in treatments:
            if item.get("priority") != "preferred":
                continue
            if not preferred_seen:
                preferred_seen = True
                continue
            item["priority"] = "eligible"
            item["notes"] = f"{item.get('notes', '').strip()} Alternativa válida, pero queda por debajo de la prioridad terapéutica principal en este escenario.".strip()
        ranked_treatments = []
        for index, item in enumerate(treatments, start=1):
            hydrated = self._hydrate_treatment_item(item, rank=index)
            ranked_treatments.append(hydrated)
        treatments = ranked_treatments

        family_profiles: dict[str, dict] = {}
        family_order: list[str] = []
        grouped: dict[str, list[dict]] = {}
        for item in treatments:
            family_code = str(item.get("family_code") or regimen_family_code(item.get("regimen_code")))
            grouped.setdefault(family_code, []).append(item)
            if family_code not in family_order:
                family_order.append(family_code)

        if grouped.get("arpi_family"):
            family_profiles["arpi_family"] = build_family_profile(
                family_code="arpi_family",
                ordered_regimens=grouped["arpi_family"],
                context={
                    "eligibility_status": "eligible",
                    "caution_drivers": [
                        reason
                        for reason, active in (
                            ("Riesgo convulsivo", seizure_risk),
                            ("Fragilidad relativa", frailty_status in {"vulnerable", "frail"}),
                            ("Polifarmacia con DDI pendiente", current_medications_present and not ddi_reviewed),
                        )
                        if active
                    ],
                    "missing_inputs": list(arpi_capture_contract.get("arpi_missing_inputs") or []),
                    "stale_inputs": list(arpi_capture_contract.get("arpi_stale_inputs") or []),
                    "winner_reason": "La familia ARPI se ordenó por secuencia clínica, seguridad neurológica y exposición previa.",
                    "why_not_preferred": "Los ARPI no preferentes permanecen visibles si no existe bloqueo duro, pero caen por secuencia, toxicidad o biomarcadores superiores.",
                },
            )
        if grouped.get("abiraterone_steroid_family"):
            family_profiles["abiraterone_steroid_family"] = build_family_profile(
                family_code="abiraterone_steroid_family",
                ordered_regimens=grouped["abiraterone_steroid_family"],
                context={
                    "eligibility_status": "conditional" if abiraterone_caution else ("contraindicated" if abiraterone_hard_block else "eligible"),
                    "hard_blocks": ["Riesgo hepático relevante"] if abiraterone_hard_block else [],
                    "caution_drivers": ["Riesgo cardio-metabólico o revisión DDI pendiente"] if abiraterone_caution else [],
                    "missing_inputs": list(arpi_capture_contract.get("arpi_missing_inputs") or []),
                    "stale_inputs": list(arpi_capture_contract.get("arpi_stale_inputs") or []),
                    "winner_reason": "Abiraterona compite cuando sigue siendo first-line plausible y no existe bloqueo hepático.",
                },
            )
        if grouped.get("taxane_family"):
            family_profiles["taxane_family"] = build_family_profile(
                family_code="taxane_family",
                ordered_regimens=grouped["taxane_family"],
                context={
                    "eligibility_status": str(nccn.get("docetaxel_base_eligibility") or "conditional"),
                    "hard_blocks": list(nccn.get("docetaxel_hard_stop_reasons") or []),
                    "missing_inputs": list(nccn.get("docetaxel_missing_inputs") or []),
                    "stale_inputs": list(nccn.get("docetaxel_stale_inputs") or []),
                    "winner_reason": "La familia taxano se ordenó con elegibilidad estructurada, secuencia CARD/TAX327 y exposición previa.",
                },
            )
        if grouped.get("parp_family"):
            family_profiles["parp_family"] = build_family_profile(
                family_code="parp_family",
                ordered_regimens=grouped["parp_family"],
                context={
                    "eligibility_status": "eligible" if biomarker_traceable and nccn["hrr_positive"] else "conditional",
                    "missing_inputs": [item for item in ["biomarker_source", "hrr_gene", "molecular_report_date"] if item in missing_inputs],
                    "winner_reason": "La familia PARP exige HRR trazable por gen y por fuente.",
                },
            )
        if grouped.get("psma_rlt_family"):
            family_profiles["psma_rlt_family"] = build_family_profile(
                family_code="psma_rlt_family",
                ordered_regimens=grouped["psma_rlt_family"],
                context={
                    "eligibility_status": "eligible" if vision_eligible or pre_taxane_pluvicto_candidate else "conditional",
                    "missing_inputs": [item for item in ["psma_negative_dominant_lesions"] if item in missing_inputs],
                    "caution_drivers": ["Elegibilidad PSMA parcial o discordante"] if explicit_partial_psma or psma_negative_dominant_lesions else [],
                    "winner_reason": "La familia PSMA-RLT se ordena por elegibilidad tipo VISION/PSMAfore y estructuración PSMA completa.",
                },
            )
        if grouped.get("radium223_family"):
            family_profiles["radium223_family"] = build_family_profile(
                family_code="radium223_family",
                ordered_regimens=grouped["radium223_family"],
                context={
                    "eligibility_status": "eligible" if nccn["symptomatic_bone_only"] else "conditional",
                    "winner_reason": "Radio-223 solo sube cuando domina el dolor óseo sin visceralidad.",
                },
            )
        if grouped.get("immunotherapy_family"):
            family_profiles["immunotherapy_family"] = build_family_profile(
                family_code="immunotherapy_family",
                ordered_regimens=grouped["immunotherapy_family"],
                context={
                    "eligibility_status": "eligible" if nccn["msi_high"] or nccn["tmb_high"] else "conditional",
                    "winner_reason": "La inmunoterapia exige un biomarcador inmune accionable o un racional molecular fuerte.",
                },
            )

        comparative_bundle = build_comparative_bundle(
            family_profiles=family_profiles,
            family_order=family_order,
        )
        preferred_regimen = dict(comparative_bundle.get("preferred_regimen") or {})
        sequence_transition_bundle = build_sequence_transition_bundle(
            state=self.module_id,
            preferred_regimen=preferred_regimen,
            eligible_treatments=comparative_bundle.get("eligible_treatments") or treatments,
            current_treatment=payload.get("current_treatment") or "",
            missing_critical_inputs=missing_inputs,
            progression_pattern=str(payload.get("progression_pattern") or ""),
            line_context=nccn.get("line_context") or "",
            field_values=payload,
            comparative_eligibility_matrix=comparative_bundle.get("comparative_eligibility_matrix") or {},
        )
        active_monitoring_package = build_active_regimen_monitoring_package(
            preferred_regimen.get("regimen_code"),
            family_code=preferred_regimen.get("family_code") or "observation_family",
            field_values=payload,
        )

        # ── FAUBOT Pivotal coverage 2026-04-23 ────────────────────────
        # Aplica los 10 gates centralizados (IPATential150 ipatasertib,
        # TROPIC/CARD cabazitaxel, TRITON-3 rucaparib, ERA-223/PEACE-3
        # Ra-223, CONTACT-02 cabozantinib, NCCN cardio).
        _eligible_pre_gates = comparative_bundle.get("eligible_treatments") or treatments
        _pivotal_bundle = apply_pivotal_contraindication_gates(
            payload, list(_eligible_pre_gates or [])
        )
        eligible_after_pivotal_gates = _pivotal_bundle["filtered_treatments"]
        for _msg in _pivotal_bundle["not_recommended_messages"]:
            if _msg and _msg not in not_recommended:
                not_recommended.append(_msg)
        _pivotal_gates_m1 = _pivotal_bundle["gates_triggered"]

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={"guideline": "NCCN", "version": "5.2026", "label": nccn["label"], "recommendation": nccn["recommendation"]},
            eau_comparison={"guideline": "EAU", "version": "2026", "label": eau["label"], "recommendation": eau["recommendation"], "comparison": comparison},
            eligible_treatments=eligible_after_pivotal_gates,
            not_recommended=not_recommended,
            missing_critical_inputs=missing_inputs,
            contraindications=legacy.get("contraindications", []),
            durations_and_conditions=["Prefer biomarker-directed options before recycling empiric classes when the profile supports them.", "Continue ADT backbone throughout M1 CRPC management."],
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=self._build_enriched_trial_matches(
                payload=payload,
                state=self.module_id,
                nccn=nccn,
                vision_eligible=vision_eligible,
                vision_eligibility_label=vision_eligibility_label,
                pre_taxane_pluvicto_candidate=pre_taxane_pluvicto_candidate,
                biomarker_traceable=biomarker_traceable,
                card_applicable=card_applicable,
                taxane_available_now=taxane_available_now,
                abiraterone_hard_block=abiraterone_hard_block,
                nepc_bundle=nepc_bundle,
                post_parp_bundle=post_parp_bundle,
            ),
            applicability_badge="guideline-consistent" if nccn["castrate_confirmed"] else "selected_candidate",
            report_sections={
                "summary": (
                    f"M1 CRPC sequencing and precision-oncology pathway. {metastatic_summary.get('narrative')}".strip()
                    if metastatic_summary.get("available")
                    else "M1 CRPC sequencing and precision-oncology pathway."
                ),
                "sequence_context": {
                    "line_context": nccn["line_context"],
                    "docetaxel_fit": nccn["docetaxel_fit"],
                    "docetaxel_base_eligibility": nccn.get("docetaxel_base_eligibility"),
                    "docetaxel_verification_status": nccn.get("docetaxel_verification_status"),
                    "chemotherapy_delay_candidate": nccn["chemotherapy_delay_candidate"],
                },
            },
            decision_changing_inputs=[
                "Confirmar testosterona en rango de castración antes de secuenciar como enfermedad resistente a la castración con metástasis.",
                "Confirmar gen HRR y fuente del biomarcador si se plantea PARP.",
                "Confirmar elegibilidad PSMA completa si se plantea radioligando dirigido.",
            ],
            supportive_evidence_context=supportive_context,
            benchmarking_flags=[
                {"label": "Biomarcador HRR trazable", "status": "complete" if biomarker_traceable else "missing", "rationale": "Necesario antes de olaparib."},
                {"label": "Elegibilidad radioligando documentada", "status": "complete" if vision_eligible or pre_taxane_pluvicto_candidate else "missing", "rationale": "Necesaria antes de lutecio-177 PSMA-617 (VISION/PSMAfore)."},
                {"label": "Secuencia post-docetaxel + ARPI documentada", "status": "complete" if card_applicable else "incomplete", "rationale": "Aclara si aplica la priorización de cabazitaxel tipo CARD."},
                {"label": "Contexto de línea mCRPC documentado", "status": "complete" if nccn["line_context"] else "missing", "rationale": "Ordena el uso conservador de TALAPRO-2, MAGNITUDE y PSMAfore."},
                {"label": "AR-V7 documentado", "status": "complete" if nccn["ar_v7_positive"] else "incomplete", "rationale": "AR-V7+ redirige de ARPI a quimioterapia (PROPHECY Armstrong 2019)."},
                {"label": "Panel TP53/RB1/PTEN", "status": "complete" if any([nccn["tp53_altered"], nccn["rb1_loss"], nccn["pten_loss"]]) else "incomplete", "rationale": "Detecta lineage plasticity (NEPC) y candidatura AKT."},
                {"label": "CDK12 evaluado", "status": "complete" if nccn["cdk12_biallelic"] else "incomplete", "rationale": "CDK12 bialélico abre IO independiente de MSI."},
                {"label": "ctDNA monitoreado", "status": "complete" if nccn["ctdna_detected"] or nccn["ctdna_rising"] else "incomplete", "rationale": "Sensor de resistencia emergente pre-radiográfica."},
                {"label": "Score NEPC Aggarwal evaluado", "status": "complete" if nepc_bundle.get("suspicion_score", 0) > 0 or nepc_bundle.get("nepc_confirmed") else "incomplete", "rationale": "Detecta transformación neuroendocrina temprana (Aggarwal 2018)."},
                {"label": "IHC MMR / MSI evaluado", "status": "complete" if nccn.get("dmmr_detected") or nccn["msi_high"] else "incomplete", "rationale": "dMMR / MSI-H habilitan pembrolizumab (KEYNOTE-158 / KEYNOTE-199)."},
                {"label": "Secuenciación post-PARP documentada", "status": "complete" if post_parp_bundle.get("applicable") else ("incomplete" if nccn.get("hrr_positive") else "not_applicable"), "rationale": "Orienta rutas ortogonales tras progresión a PARPi (CARD, VISION, rechallenge platino)."},
            ],
            decision_quality={
                "recommendation_family": preferred_regimen.get("family_label") or nccn.get("label") or "mCRPC",
                "confidence_category": "vigilada" if missing_inputs else "alta",
                "requires_human_review": bool(
                    missing_inputs
                    or nepc_bundle.get("nepc_suspected")
                    or nepc_bundle.get("nepc_confirmed")
                    or nepc_bundle.get("biopsy_trigger")
                    or nccn.get("ar_v7_positive")
                    or post_parp_bundle.get("applicable")
                ),
            },
        )
        result["comparative_eligibility_matrix"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        result["therapeutic_family_profiles"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        # EPIC 3 bundles (VISION/PSMAfore, NEPC, post-PARP) expuestos para profile_compass,
        # decision_input_requirements_engine y auditoría clínica.
        result["vision_eligibility_bundle"] = vision_bundle
        result["nepc_pathway_bundle"] = nepc_bundle
        result["post_parp_sequencing_bundle"] = post_parp_bundle
        result["preferred_frontline_regimen"] = preferred_regimen
        result["preferred_regimen_code"] = preferred_regimen.get("regimen_code", "")
        result["candidate_regimens_under_consideration"] = list(nccn.get("candidate_regimens_under_consideration") or []) or [
            str(item.get("regimen_code") or "")
            for item in list(result.get("eligible_treatments") or [])
            if str(item.get("regimen_code") or "")
        ]
        result["alternative_regimens"] = comparative_bundle.get("alternative_regimens") or []
        result["patient_goals_profile"] = {
            "primary_goal": str(payload.get("primary_goal") or "max_control"),
            "visit_burden_tolerance": str(payload.get("visit_burden_tolerance") or "medium"),
            "route_preference": str(payload.get("route_preference") or "no_preference"),
            "symptom_priority": str(payload.get("symptom_priority") or ("pain" if nccn["symptomatic_bone_only"] else "mixed")),
        }
        result["care_setting_contract"] = {
            "care_setting": "systemic_precision" if preferred_regimen.get("family_code") in {"parp_family", "psma_rlt_family", "immunotherapy_family"} else "systemic_intensification",
            "family_code": preferred_regimen.get("family_code") or "",
            "family_label": preferred_regimen.get("family_label") or "",
        }
        result["sequence_transition_bundle"] = sequence_transition_bundle
        result["active_regimen_monitoring_package"] = active_monitoring_package
        result["phase7_advanced_bundle"] = build_m1_crpc_phase7_bundle(payload, m1_context=nccn)
        result["arpi_required_fields"] = list(arpi_capture_contract.get("arpi_required_fields") or [])
        result["arpi_missing_inputs"] = list(arpi_capture_contract.get("arpi_missing_inputs") or [])
        result["arpi_stale_inputs"] = list(arpi_capture_contract.get("arpi_stale_inputs") or [])
        result["arpi_profile_completeness"] = str(arpi_capture_contract.get("arpi_profile_completeness") or "")
        result["arpi_preference_readiness"] = str(arpi_capture_contract.get("arpi_preference_readiness") or "")
        result["arpi_selection_contract"] = arpi_capture_contract
        scope_contract = build_systemic_regimen_scope_contract(self.module_id, result)
        result["systemic_regimen_scope"] = scope_contract["scope"]
        result["systemic_regimen_scope_contract"] = scope_contract
        # Faubot 2026-04-24 (III) — exponer trazabilidad de gates pivotal.
        if _pivotal_gates_m1:
            result["pivotal_contraindication_gates"] = [
                {
                    "code": g.get("code"),
                    "severity": g.get("severity"),
                    "message": g.get("message"),
                    "evidence_tag": g.get("evidence_tag"),
                    "trial_refs": list(g.get("trial_refs") or ()),
                }
                for g in _pivotal_gates_m1
            ]
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada de enfermedad resistente a la castración con metástasis",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                "La secuencia se redefine por el estado de reparación por recombinación homóloga, la inestabilidad microsatelital y la positividad para antígeno prostático específico de membrana.",
                "La carga mutacional tumoral alta también puede abrir inmunoterapia cuando existe trazabilidad molecular suficiente.",
                "La exposición previa a inhibidores de la vía del receptor androgénico y taxanos determina qué clases siguen activas y cuáles ya están agotadas.",
                "La presencia de metástasis óseas sintomáticas sin compromiso visceral abre opciones óseo-dirigidas específicas.",
                "AR-V7 positivo redirige la secuencia de ARPI a quimioterapia basándose en resistencia documentada al receptor androgénico.",
                "TP53 + RB1 loss activan vigilancia de lineage plasticity y transformación neuroendocrina, cambiando el esquema a platinum-based cuando se confirma.",
                "PTEN loss abre la vía PI3K/AKT como alternativa terapéutica con inhibidores AKT combinados.",
                "CDK12 bialélico genera carga neoantigénica alta e independiza la candidatura a inmunoterapia de MSI-H.",
                "ctDNA en ascenso anticipa resistencia terapéutica semanas antes que PSA, permitiendo cambio de línea proactivo.",
            ],
            alternatives=[
                "Olaparib o inmunoterapia cuando el perfil molecular lo respalda.",
                "Quimioterapia, radiofármacos o terapias dirigidas según biomarcadores, exposición previa y sitio metastásico dominante.",
            ],
            shared_decision_message=(
                "La decisión final debe armonizar biomarcadores, síntomas, reserva funcional, toxicidades acumuladas y disponibilidad real de terapias dirigidas o radiofármacos."
            ),
            comparison_message=(
                "La comparación con la Asociación Europea de Urología (EAU) 2026 sirve para confirmar si la secuencia priorizada por biomarcadores coincide o si debe discutirse en comité oncológico multidisciplinario."
            ),
        )

    @staticmethod
    def _build_enriched_trial_matches(
        *,
        payload: dict,
        state: str,
        nccn: dict,
        vision_eligible: bool,
        vision_eligibility_label: str,
        pre_taxane_pluvicto_candidate: bool,
        biomarker_traceable: bool,
        card_applicable: bool,
        taxane_available_now: bool,
        abiraterone_hard_block: bool,
        nepc_bundle: dict,
        post_parp_bundle: dict,
    ) -> list[dict]:
        """EPIC 7 — Construye la lista de trial_matches m1_crpc.

        Mantiene las keys legacy ``trial`` + ``match`` que consumen tests
        y UI, y enriquece con metadata del engine curado (``nct_id``,
        ``match_reasons``, ``ineligibility_reasons``, ``evidence_tags``,
        ``primary_reference``, ``phase``). Las entradas que el engine no
        cubre (AFFIRM, COU-AA-301/302, TAX 327, TROPIC, Post-PARP) se
        mantienen con su computación NCCN-local.
        """

        legacy_list: list[dict] = [
            {"trial": "PROfound", "match": biomarker_traceable},
            {"trial": "PROPEL", "match": nccn["hrr_positive"] and biomarker_traceable and not nccn["prior_abiraterone"]},
            {"trial": "VISION", "match": vision_eligible},
            {"trial": "PSMAfore", "match": vision_eligibility_label == "psmafore_pre_taxane" or pre_taxane_pluvicto_candidate},
            {"trial": "CARD", "match": card_applicable},
            {"trial": "TALAPRO-2", "match": nccn["line_context"] == "first_line_mcrpc" and nccn["hrr_positive"] and biomarker_traceable and not nccn["prior_enza_class"]},
            {"trial": "MAGNITUDE", "match": nccn["line_context"] == "first_line_mcrpc" and nccn["brca_pathway"] and biomarker_traceable and not nccn["prior_abiraterone"]},
            {"trial": "TRITON-3", "match": nccn["brca_pathway"] and biomarker_traceable},
            {"trial": "AFFIRM", "match": not nccn["prior_enza_class"]},
            {"trial": "COU-AA-301/302", "match": not nccn["prior_abiraterone"] and not abiraterone_hard_block},
            {"trial": "TAX 327", "match": taxane_available_now and not nccn["prior_docetaxel"]},
            {"trial": "TROPIC", "match": card_applicable},
            {"trial": "ALSYMPCA", "match": nccn["symptomatic_bone_only"]},
            {"trial": "KEYNOTE-158", "match": bool(nccn.get("pembrolizumab_candidate") or nccn["msi_high"] or nccn["tmb_high"])},
            {"trial": "KEYNOTE-199", "match": bool(nccn.get("dmmr_high_confidence") or nccn["msi_high"])},
            {"trial": "PROPHECY", "match": nccn["ar_v7_positive"]},
            {"trial": "IPATential150", "match": nccn["pten_loss"]},
            {"trial": "CAPItello-281", "match": nccn["pten_loss"]},
            {"trial": "EP-16 (Aparicio)", "match": bool(nepc_bundle.get("nepc_confirmed") or nepc_bundle.get("nepc_suspected"))},
            {"trial": "Post-PARP clinical trial", "match": bool(post_parp_bundle.get("applicable"))},
        ]

        # Enriquecer con metadata del engine curado (match por trial_code canónico).
        # Import lazy para romper ciclo research_intelligence ↔ module_registry ↔ m1_crpc.
        try:
            from prostanet.domains.research_intelligence.trial_matching_engine import (
                match_patient_to_trials,
            )
        except Exception:
            return legacy_list
        engine_payload = {**payload, "state": state}
        try:
            engine_matches = match_patient_to_trials(engine_payload)
        except Exception:
            return legacy_list
        engine_by_code = {m.trial_code.upper().replace("-", "").replace(" ", ""): m for m in engine_matches}

        def _normalize_code(code: str) -> str:
            return str(code or "").upper().replace("-", "").replace(" ", "").replace("(", "").replace(")", "").strip()

        alias_map = {
            "PROPEL": "PROPEL",
            "EP16APARICIO": "EP16NEPC",
        }
        enriched: list[dict] = []
        for entry in legacy_list:
            code_key = alias_map.get(_normalize_code(entry["trial"]), _normalize_code(entry["trial"]))
            meta = engine_by_code.get(code_key)
            enriched_entry = dict(entry)
            if meta is not None:
                enriched_entry["nct_id"] = meta.nct_id
                enriched_entry["match_reasons"] = list(meta.match_reasons)
                enriched_entry["ineligibility_reasons"] = list(meta.ineligibility_reasons)
                enriched_entry["evidence_tags"] = list(meta.evidence_tags)
                enriched_entry["primary_reference"] = meta.primary_reference
                enriched_entry["phase"] = meta.phase
                enriched_entry["status_summary"] = meta.status_summary
                enriched_entry["source"] = "catalog_curated_v1"
            else:
                enriched_entry["source"] = "legacy_static"
            enriched.append(enriched_entry)
        return enriched

    @staticmethod
    def _note_for(legacy: dict, drug_label: str) -> str:
        for item in legacy.get("recommendations", []):
            if drug_label.lower() in item.get("combination", "").lower() or drug_label.lower() in item.get("drug", "").lower():
                return item.get("evidence", "")
        return ""

    @staticmethod
    def _hydrate_treatment_item(item: dict[str, str], *, rank: int = 1) -> dict:
        name = str(item.get("name") or "").strip()
        notes = str(item.get("notes") or "").strip()
        priority = str(item.get("priority") or "eligible").strip()
        regimen_hint = {
            "Enzalutamide": "ADT_ENZALUTAMIDE",
            "Acetato de Abiraterona": "ADT_ABIRATERONE",
            "Talazoparib + Enzalutamide": "TALAZOPARIB_ENZALUTAMIDE",
            "Niraparib + Abiraterone": "NIRAPARIB_ABIRATERONE",
            "Olaparib": "OLAPARIB",
            "Pembrolizumab": "PEMBROLIZUMAB",
            "Pembrolizumab (CDK12-dirigido)": "PEMBROLIZUMAB",
            "Lu-177 PSMA-617": "LU177_PSMA617",
            "Lutecio-177 PSMA-617 (Pluvicto)": "LU177_PSMA617",
            "Radium-223": "RADIUM223",
            "Radio-223 dicloruro (Xofigo)": "RADIUM223",
            "Cabazitaxel": "CABAZITAXEL",
            "Docetaxel": "DOCETAXEL",
            "Docetaxel (AR-V7 dirigido)": "DOCETAXEL",
            "Carboplatino + Etopósido": "CARBOPLATIN_ETOPOSIDE",
            "Carboplatino + Etopósido (NEPC)": "CARBOPLATIN_ETOPOSIDE_NEPC",
            "Carboplatino + Etopósido (NEPC post-PARP)": "CARBOPLATIN_ETOPOSIDE_NEPC",
            "Carboplatino ± Etopósido (rechallenge HRR)": "CARBOPLATIN_ETOPOSIDE",
            "Cisplatino + Docetaxel (NEPC)": "CISPLATIN_DOCETAXEL_NEPC",
            "Monitoreo intensivo NEPC": "OBSERVATION",
            "Biopsia dirigida con IHC neuroendocrina": "OBSERVATION",
            "Monitoreo TMB zona gris": "OBSERVATION",
            "Ensayo clínico dirigido post-PARP": "CLINICAL_TRIAL_POST_PARP",
            "Ipatasertib + Abiraterona": "IPATASERTIB_ABIRATERONE",
            # Auditoría Pacientes Insignia 2026-04-21 (§A.4)
            "Sipuleucel-T": "SIPULEUCEL_T",
            "Cabozantinib + Atezolizumab": "CABOZANTINIB_ATEZOLIZUMAB",
        }.get(name, "")
        family_code = regimen_family_code(regimen_hint or name)
        eligibility_status = (
            "preferred"
            if priority == "preferred"
            else "eligible_with_caution"
            if priority in {"selected_candidate", "not_preferred"}
            else "eligible_nonpreferred"
        )
        hydrated = build_ranked_option(
            name=name,
            regimen_code=regimen_hint or name,
            rank=rank,
            priority=priority,
            eligibility_status=eligibility_status,
            notes=notes,
            family_code=family_code,
            molecule_or_backbone=name,
            why_this_rank=[notes] if notes else [],
            caution_flags=[] if priority == "preferred" else ([notes] if notes else []),
            selection_rationale=[notes] if notes else [],
            benefit_basis=str(item.get("benefit_basis") or ""),
            benefit_endpoint_used=str(item.get("benefit_endpoint_used") or ""),
            benefit_maturity=str(item.get("benefit_maturity") or ""),
            preference_confidence=str(item.get("preference_confidence") or "definitive"),
            required_missing_fields=list(item.get("required_missing_fields") or []),
            stale_inputs=list(item.get("stale_inputs") or []),
            safety_drivers_used=list(item.get("safety_drivers_used") or []),
        )
        if not hydrated.get("description"):
            hydrated["description"] = notes or name
        return hydrated
