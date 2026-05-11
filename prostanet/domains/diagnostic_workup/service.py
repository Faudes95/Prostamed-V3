from __future__ import annotations

from prostanet.domains.diagnostic_workup.rules_eau import classify_diagnostic_workup_eau
from prostanet.domains.diagnostic_workup.rules_nccn import classify_diagnostic_workup
from prostanet.domains.diagnostic_workup.schemas import DIAGNOSTIC_WORKUP_SCHEMA
from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


class DiagnosticWorkupService:
    module_id = "diagnostic_workup"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return DIAGNOSTIC_WORKUP_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        nccn = classify_diagnostic_workup(payload)
        eau = classify_diagnostic_workup_eau(payload)
        comparison = self.comparison.compare(nccn, eau)

        psa = float(payload.get("psa", 0) or 0)
        psad = float(payload.get("psad", 0) or 0)
        pirads = int(float(payload.get("pirads_score", 0) or 0))
        dre_suspicious = str(payload.get("dre_suspicious", "0"))
        erspc_ready = all(
            payload.get(field) not in (None, "")
            for field in ("age", "psa", "dre_suspicious")
        )

        treatments = []
        if nccn["biopsy_indicated"]:
            treatments.append(
                {
                    "name": "Biopsia dirigida más biopsia sistemática",
                    "priority": "preferred",
                    "notes": "La sospecha clínica supera el umbral de observación aislada y justifica confirmación histológica.",
                }
            )
        if nccn["repeat_high_quality_mri"]:
            treatments.append(
                {
                    "name": "Repetir resonancia magnética multiparamétrica de alta calidad",
                    "priority": "selected_candidate",
                    "notes": "Una MRI subóptima no debe sustentar una falsa tranquilidad diagnóstica.",
                }
            )
        treatments.append(
            {
                "name": "Resonancia magnética multiparamétrica con revisión dirigida",
                "priority": "eligible",
                "notes": "Sirve para precisar la localización de lesiones y evitar una decisión ciega basada solo en antígeno prostático específico.",
            }
        )
        if not nccn["biopsy_indicated"]:
            treatments.append(
                {
                    "name": "Repetición estructurada de antígeno prostático específico y densidad del antígeno prostático específico",
                    "priority": "eligible",
                    "notes": "Adecuado cuando la sospecha es baja y no existe una señal clínica fuerte.",
                }
            )

        # Brecha M-staging gate — 2026-04-22 (§D.2):
        # Cuando el riesgo (PSA>20, cT2b-T4 o ISUP≥4) exige imagenología de
        # extensión, diagnostic_workup emite explícitamente PSMA PET/CT (preferente
        # ProPSMA) y/o GGO+TAC abdomino-pélvico (NCCN PROS-2 cat 1). NO bloquea
        # diagnóstico ni biopsia (ese es el rol del módulo); sirve para que el
        # médico planee staging desde la consulta inicial y no llegue al módulo
        # localized_initial sin imagen.
        staging_gap = nccn.get("staging_gap")
        not_recommended_extra: list[str] = []
        if staging_gap:
            for item in staging_gap.get("recommended") or []:
                treatments.append({
                    "name": item.get("name") or "Imagenología de estadificación M",
                    "priority": item.get("priority", "first_line"),
                    "category": "staging_imaging",
                    "notes": item.get("rationale") or "",
                })
            risk_band = (staging_gap.get("risk_band") or "").upper() or "ALTO/MUY ALTO"
            staging_reasons = "; ".join(staging_gap.get("reasons") or [])
            staging_missing = ", ".join(staging_gap.get("missing_modalities") or [])
            not_recommended_extra.append(
                f"Tratamiento curativo (prostatectomía radical o radioterapia definitiva) no debe iniciarse "
                f"hasta completar la estadificación M en este perfil de riesgo {risk_band}. "
                f"Motivos: {staging_reasons}. Pendiente: {staging_missing}. "
                f"Referencia: NCCN PROS-2 v5.2026 cat 1; EAU 2026 §6.4.1-6.4.3; ProPSMA Hofman 2020."
            )

        # ── Brecha 2026-04-23: 3 ramas paralelas pre-biopsia ───────────────
        # NCCN PROS-G v5.2026 + EAU §6.5.4 + Loblaw 2012 + Briganti.
        # Ante PSA extremo + cT4 fijo+pétreo (caso 2026-04-23) ProstaNet
        # debe emitir 3 tracks paralelos (emergencia / provisional / ADT
        # empírico) sin desplazar la rama de biopsia ni la de staging M.
        # `not_recommended_emergency` se acumula y se inyecta abajo.
        not_recommended_emergency: list[str] = []

        # RAMA 1 — EMERGENCIA ONCOLÓGICA (máxima prioridad — insert(0))
        emergency = nccn.get("oncologic_emergency")
        if emergency:
            critical_count = emergency.get("critical_count", 0)
            high_count = emergency.get("high_count", 0)
            min_tta = emergency.get("min_tta_hours", 24)
            max_severity = emergency.get("max_severity", "high")
            severity_label = max_severity.upper()
            treatments.insert(
                0,
                {
                    "name": (
                        f"⚠ TRIAJE DE EMERGENCIA ONCOLÓGICA — severidad {severity_label}"
                    ),
                    "priority": "emergency",
                    "category": "oncologic_emergency",
                    "tta_hours": min_tta,
                    "notes": (
                        f"Detectadas {critical_count} crítica(s) + {high_count} alta(s). "
                        f"Tiempo a acción mínimo: {min_tta} h. "
                        "REFERIR INMEDIATAMENTE a oncología/urología de urgencia."
                    ),
                    "details": [
                        {
                            "name": e.get("name"),
                            "code": e.get("code"),
                            "severity": e.get("severity"),
                            "tta_hours": e.get("tta_hours"),
                            "actions": e.get("actions") or [],
                            "evidence_tag": e.get("evidence_tag"),
                        }
                        for e in (emergency.get("emergencies") or [])
                    ],
                },
            )
            not_recommended_emergency.append(
                "NO diferir el manejo de la emergencia oncológica esperando "
                "biopsia o estadificación: la demora se asocia a complicaciones "
                "irreversibles (paraplejía si compresión medular, "
                "insuficiencia renal definitiva si hidronefrosis bilateral). "
                "Referencia: NCCN Oncologic Emergencies v3.2026; Loblaw ASCO 2012."
            )

        # RAMA 2 — DIAGNÓSTICO PROVISIONAL CLÍNICO
        provisional = nccn.get("provisional_diagnosis") or {}
        tier = provisional.get("tier", "none")
        if tier and tier != "none":
            confidence_pct = (provisional.get("confidence") or 0) * 100
            tier_es = {
                "possible": "POSIBLE",
                "probable": "PROBABLE",
                "highly_probable": "ALTAMENTE PROBABLE",
                "virtually_certain": "VIRTUALMENTE CIERTO",
            }.get(tier, tier.upper())
            basis = provisional.get("basis") or []
            treatments.append(
                {
                    "name": f"Diagnóstico provisional clínico — {tier_es}",
                    "priority": "first_line",
                    "category": "provisional_diagnosis",
                    "notes": (
                        f"Confianza {confidence_pct:.0f}%. "
                        f"Fundamento: {'; '.join(basis)}. "
                        "Activa workflows downstream (mHSPC empírico, "
                        "paliativo, emergencias) sin esperar histología "
                        "(NCCN PROS-G v5.2026; EAU §6.5.4; Briganti)."
                    ),
                    "tier": tier,
                    "confidence": provisional.get("confidence"),
                    "basis": basis,
                    "evidence_tag": "nccn_pros_g",
                }
            )
            # Plan de biopsia urgente (acoplado al tier)
            biopsy_priority = provisional.get("biopsy_priority", "standard")
            biopsy_plans = {
                "urgent_or_alternative_site": (
                    "Biopsia transperineal urgente (próstata fija — vía "
                    "transrectal con contraindicación relativa) O biopsia de "
                    "sitio metastásico accesible (ósea, ganglionar, hepática) "
                    "en <72 h."
                ),
                "urgent_within_7d": (
                    "Biopsia transperineal o transrectal en <7 días + "
                    "estadificación PSMA PET/CT preferente."
                ),
                "within_2_weeks": (
                    "Biopsia programada en <2 semanas + estadificación M completa."
                ),
                "standard": "Biopsia estándar según workflow habitual.",
            }
            treatments.append(
                {
                    "name": (
                        f"Plan de biopsia: prioridad "
                        f"{biopsy_priority.replace('_', ' ')}"
                    ),
                    "priority": "first_line",
                    "category": "biopsy_plan",
                    "notes": biopsy_plans.get(
                        biopsy_priority, biopsy_plans["standard"]
                    ),
                }
            )

        # RAMA 3 — ADT EMPÍRICO PRE-HISTOLOGÍA
        adt_protocol = nccn.get("empiric_adt_protocol")
        if adt_protocol:
            treatments.append(
                {
                    "name": "ADT empírico pre-histología (recomendado)",
                    "priority": "first_line",
                    "category": "empiric_systemic_therapy",
                    "regimen": adt_protocol.get("regimen"),
                    "alternative": adt_protocol.get("alternative"),
                    "notes": adt_protocol.get("rationale"),
                    "duration": adt_protocol.get("duration"),
                    "monitoring": adt_protocol.get("monitoring"),
                    "evidence_tag": adt_protocol.get("evidence_tag"),
                }
            )
            not_recommended_emergency.append(
                "NO diferir el manejo sistémico esperando histología perfecta "
                "cuando la probabilidad clínica de cáncer avanzado es "
                "highly_probable / virtually_certain (>93%) y existe "
                "sintomatología activa o emergencia oncológica. "
                "Referencia: NCCN PROS-G v5.2026; EAU 2026 §6.5.4; STAMPEDE 2017."
            )

        not_recommended = [
            "No usar la tomografía por emisión de positrones dirigida al antígeno prostático específico de membrana como sustituto de la confirmación histológica.",
            "No diferir indefinidamente la biopsia si persisten densidad elevada del antígeno prostático específico, tacto rectal sospechoso o una lesión PI-RADS 4 o 5.",
            *not_recommended_extra,
            *not_recommended_emergency,
        ]
        durations = [
            "Si la sospecha es baja, repetir antígeno prostático específico y densidad del antígeno prostático específico en 6 a 12 semanas antes de descartar la vía diagnóstica.",
            "Si la sospecha es intermedia o alta, priorizar resonancia magnética y biopsia sin demoras prolongadas.",
        ]

        case_summary = (
            f"El paciente se encuentra en estudio diagnóstico sin confirmación histológica previa, con antígeno prostático específico de {psa:g} ng/mL, "
            f"densidad del antígeno prostático específico de {psad:g}, tacto rectal {'sospechoso' if dre_suspicious in {'1', 'true'} else 'no sospechoso'} "
            f"y resonancia magnética multiparamétrica con PI-RADS {pirads if pirads else 'no disponible'}. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 lo sitúa en {nccn['label'].lower()} y la Asociación Europea de Urología (EAU) 2026 lo compara como {eau['label'].lower()}."
        )

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
                "recommendation": eau["recommendation"],
                "comparison": comparison,
            },
            eligible_treatments=treatments,
            not_recommended=not_recommended,
            missing_critical_inputs=[field for field in ["psa"] if str(payload.get(field, "")).strip() == ""],
            contraindications=[],
            durations_and_conditions=durations,
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=[],
            applicability_badge="guideline-consistent",
            report_sections={
                "summary": case_summary,
                "diagnostic_risk_pct": nccn["significant_risk_pct"],
                "validated_algorithms": {
                    "erspc_ready": erspc_ready,
                },
            },
        )
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada de estudio diagnóstico",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                *nccn["reasons"],
                f"Riesgo estimado de cáncer clínicamente significativo: {nccn['significant_risk_pct']}%.",
                "El pathway MRI + PSAD y la velocidad de PSA ya modifican la intensidad diagnóstica cuando el caso es limítrofe.",
                (
                    "Las entradas estan listas para correr ERSPC Risk Calculator como refinador libre de deteccion temprana."
                    if erspc_ready
                    else "ERSPC Risk Calculator sigue incompleto porque faltan entradas basales clave."
                ),
                "La confirmación histológica sigue siendo el punto de entrada obligatorio antes de una ruta terapéutica formal.",
            ],
            alternatives=[
                "Repetir antígeno prostático específico y densidad del antígeno prostático específico cuando la sospecha es baja y no hay disparadores clínicos mayores.",
                "Revisar la resonancia magnética multiparamétrica antes de indicar una biopsia repetida si existe una biopsia benigna previa.",
            ],
            shared_decision_message=(
                "La decisión entre biopsia inmediata y revaluación corta debe integrar el grado de sospecha, la ansiedad diagnóstica del paciente, la expectativa de vida y la calidad de la resonancia magnética disponible."
            ),
            comparison_message=(
                "La comparación con la Asociación Europea de Urología (EAU) 2026 ayuda a confirmar si la sospecha es suficiente para avanzar a biopsia o si aún puede mantenerse una revaloración estructurada."
            ),
        )
