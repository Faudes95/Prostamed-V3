from __future__ import annotations

from prostanet.shared.clinical_provisional_diagnosis_engine import (
    PSA_EXTREME,
    PSA_HIGH,
    PSA_VERY_HIGH,
    PSA_VIRTUALLY_CERTAIN,
    assess_provisional_diagnosis,
    empiric_adt_protocol,
)
from prostanet.shared.oncologic_emergency_triage_engine import (
    emergency_triage_descriptor,
)
from prostanet.shared.staging_requirements_engine import staging_gap_descriptor
from prostanet.domains.diagnostic_workup.derivations import (
    derive_dre_context,
    derive_mri_context,
    derive_psad_context,
)


def classify_diagnostic_workup(payload: dict) -> dict:
    psa_raw = _safe_float(payload.get("psa"), default=0.0)
    # EPIC 9 Group F (GAP-12) — Confundentes del PSA (EAU Diagnostic Evaluation 2026).
    # 5-ARI (finasteride/dutasteride) reduce PSA ~50% tras 6-12 meses de uso;
    # el PSA "efectivo" para scoring diagnóstico se multiplica ×2 cuando hay
    # 5-ARI activo (Roehrborn Eur Urol 2006, Andriole J Urol 2006, NCCN PROS-A).
    # Los otros confundentes (UTI/prostatitis aguda, retención urinaria reciente,
    # eyaculación en 48h) NO multiplican el PSA pero emiten caveat narrativo;
    # same-lab assay diferente también es caveat cuando PSA es la señal decisiva.
    ari_active = _is_true(payload.get("ari_medication_active"))
    uti_prostatitis = _is_true(payload.get("uti_prostatitis_recent"))
    urinary_retention = _is_true(payload.get("urinary_retention_recent"))
    recent_ejaculation = _is_true(payload.get("recent_ejaculation_48h"))
    same_lab_assay = str(payload.get("psa_same_lab_assay", "1")).strip()
    if same_lab_assay == "":
        same_lab_assay = "1"
    psa = psa_raw * 2.0 if ari_active else psa_raw
    psa_correction_applied = ari_active
    psad_context = derive_psad_context(payload, psa_value=psa)
    psad = psad_context.value or 0.0
    mri_context = derive_mri_context(payload)
    pirads = mri_context.pirads or 0
    dre_context = derive_dre_context(payload)
    dre_suspicious = dre_context.is_suspicious
    dre_implied_tstage = dre_context.implied_tstage
    family_history = _is_true(payload.get("family_history_positive"))
    family_history_detail = str(payload.get("family_history_detail", "")).strip()
    germline_risk = _is_true(payload.get("germline_risk_mutation"))
    germline_status = str(payload.get("germline_status", "Desconocido"))
    prior_negative_biopsy = _is_true(payload.get("prior_negative_biopsy"))
    psa_velocity = _safe_float(payload.get("psa_velocity_ng_ml_year"), default=0.0)
    risk_pathway = str(payload.get("risk_calculator_pathway", "No usado"))
    mpmri_quality = mri_context.quality
    lesion_size = _safe_float(payload.get("index_lesion_size_mm"), default=0.0)
    planned_biopsy_route = str(payload.get("planned_biopsy_route", "No definida"))
    ipss_score = _safe_float(payload.get("ipss_score"), default=0.0)

    score = 0
    reasons: list[str] = []

    if psa_correction_applied:
        reasons.append(
            f"Paciente bajo inhibidor 5-α-reductasa activo: el PSA reportado ({psa_raw:.1f} ng/mL) "
            f"se corrige ×2 a {psa:.1f} ng/mL para el scoring diagnóstico (EAU 2026 / NCCN PROS-A)."
        )
    # ── Brecha 2026-04-23: stratified PSA scoring ──────────────────────────
    # NCCN PROS-G v5.2026 + EAU 2026 §6.5.4 + Briganti / ProsTIC nomograms.
    # El umbral antiguo `psa>=10 → +2` saturaba: PSA 12 y PSA 5000 obtenían
    # el mismo score y ProstaNet emitía las mismas recomendaciones para
    # ambos pacientes. La evidencia muestra >97% probabilidad de M1 cuando
    # PSA ≥ 5000, ~93% cuando PSA ≥ 1000, ~80-90% cuando PSA ≥ 500 y
    # ~60-75% cuando PSA ≥ 100. La nueva estratificación discrimina las
    # 4 órdenes de magnitud y permite a service.py emitir 3 ramas
    # paralelas (emergencia / provisional / ADT empírico) ante PSA extremo.
    if psa >= PSA_VIRTUALLY_CERTAIN:  # 5000 ng/mL
        score += 7
        reasons.append(
            f"Antígeno prostático específico extremo {psa:.0f} ng/mL "
            f"(≥{PSA_VIRTUALLY_CERTAIN:.0f}) — probabilidad de enfermedad "
            "metastásica >97% (Briganti / ProsTIC). Considerar diagnóstico "
            "provisional clínico + ADT empírico mientras se completa biopsia."
        )
    elif psa >= PSA_EXTREME:  # 1000 ng/mL
        score += 6
        reasons.append(
            f"Antígeno prostático específico extremo {psa:.0f} ng/mL "
            f"(≥{PSA_EXTREME:.0f}) — probabilidad de M1 >93% (Briganti). "
            "Estadificación M obligatoria sin demoras."
        )
    elif psa >= PSA_VERY_HIGH:  # 500 ng/mL
        score += 5
        reasons.append(
            f"Antígeno prostático específico muy elevado {psa:.0f} ng/mL "
            f"(≥{PSA_VERY_HIGH:.0f}) — probabilidad de M1 80-90%."
        )
    elif psa >= PSA_HIGH:  # 100 ng/mL
        score += 4
        reasons.append(
            f"Antígeno prostático específico alto {psa:.0f} ng/mL "
            f"(≥{PSA_HIGH:.0f}) — probabilidad de M1 60-75%; "
            "estadificación M obligatoria."
        )
    elif psa >= 20:
        score += 3
        reasons.append(
            f"Antígeno prostático específico {psa:.0f} ng/mL >20 — "
            "alta sospecha; estadificación M obligatoria."
        )
    elif psa >= 10:
        score += 2
        reasons.append("El antígeno prostático específico es igual o mayor de 10 ng/mL.")
    elif psa >= 4:
        score += 1
        reasons.append("El antígeno prostático específico se encuentra por encima del umbral de vigilancia.")

    if uti_prostatitis or urinary_retention or recent_ejaculation:
        confounders_present: list[str] = []
        if uti_prostatitis:
            confounders_present.append("ITU o prostatitis aguda reciente")
        if urinary_retention:
            confounders_present.append("retención urinaria o sondaje reciente")
        if recent_ejaculation:
            confounders_present.append("eyaculación en las últimas 48 h")
        reasons.append(
            "Se documentan confundentes del PSA (" + ", ".join(confounders_present) +
            "): considerar repetir PSA a distancia del evento antes de decidir biopsia."
        )

    if same_lab_assay == "0" and psa >= 4:
        reasons.append(
            "El PSA comparado se obtuvo en distinto laboratorio o técnica: el delta puede reflejar "
            "variabilidad analítica, conviene repetir con el mismo ensayo antes de confirmar tendencia."
        )

    if psad >= 0.15:
        score += 2
        reasons.append("La densidad del antígeno prostático específico es 0.15 o mayor.")
    elif psad >= 0.10:
        score += 1
        reasons.append("La densidad del antígeno prostático específico es intermedia y merece contexto adicional.")
    elif not psad_context.calculable and "prostate_volume_ml" in psad_context.missing_inputs:
        reasons.append("La densidad del antígeno prostático específico debe calcularse al disponer del volumen prostático; no se interpreta como cero.")

    if dre_suspicious:
        score += 2
        reasons.append("El tacto rectal es sospechoso.")

    if pirads >= 4:
        score += 2
        reasons.append("La resonancia magnética multiparamétrica muestra una lesión PI-RADS 4 o 5.")
    elif pirads == 3:
        score += 1
        reasons.append("La resonancia magnética multiparamétrica muestra una lesión PI-RADS 3.")

    if family_history or germline_risk or family_history_detail:
        score += 1
        reasons.append("Existe un modificador hereditario o familiar que eleva la sospecha clínica.")
    if germline_status in {"Sospechado", "Conocido"} and not germline_risk:
        score += 1
        reasons.append("La sospecha o confirmación germinal obliga a sostener una ruta diagnóstica de menor tolerancia al retraso.")
    if psa_velocity >= 0.75:
        score += 1
        reasons.append("La velocidad del antígeno prostático específico es clínicamente relevante y refuerza la sospecha.")
    if lesion_size >= 10 and pirads >= 3:
        score += 1
        reasons.append("El tamaño de la lesión índice es relevante y aumenta la urgencia de confirmación histológica.")
    if risk_pathway != "No usado" and pirads <= 3 and psad < 0.15 and not dre_suspicious:
        score = max(0, score - 1)
        reasons.append("El pathway MRI + PSAD o la calculadora de riesgo reduce ligeramente la urgencia en un caso limítrofe.")
    if mpmri_quality == "Subóptima":
        reasons.append("La resonancia magnética disponible es subóptima y no debe usarse para tranquilizar falsamente un caso limítrofe.")
    if planned_biopsy_route == "Transperineal":
        reasons.append("La vía transperineal ya está identificada y favorece una planificación diagnóstica más robusta si se decide biopsia.")
    if ipss_score >= 20:
        reasons.append("El componente sintomático basal justifica alinear la decisión diagnóstica con impacto clínico y no solo con biomarcadores.")

    if score >= 6:
        label = "Alta sospecha diagnóstica"
        recommendation = "Realizar biopsia dirigida más biopsia sistemática sin diferir el estudio; si la histología confirma enfermedad de alto riesgo o regional, preparar imagen avanzada para estadificación."
        risk_group = "DIAGNOSTIC_HIGH"
    elif score >= 3:
        label = "Sospecha diagnóstica intermedia"
        recommendation = "Completar resonancia magnética multiparamétrica y avanzar a biopsia dirigida más sistemática si persiste la sospecha por densidad del antígeno prostático específico, tacto rectal o PI-RADS 3 o mayor."
        risk_group = "DIAGNOSTIC_INTERMEDIATE"
    else:
        label = "Sospecha diagnóstica baja"
        recommendation = "Repetir antígeno prostático específico, calcular densidad del antígeno prostático específico al disponer de volumen prostático, confirmar técnica de medición y reservar la biopsia para elevación persistente o nueva señal clínica."
        risk_group = "DIAGNOSTIC_LOW"

    significant_risk_pct = min(85, max(10, 12 + score * 10))
    if prior_negative_biopsy:
        reasons.append("Existe antecedente de biopsia benigna, por lo que la decisión debe integrar el nuevo nivel de sospecha y no repetir biopsia de forma automática.")

    payload_with_derivations = dict(payload)
    if dre_implied_tstage:
        payload_with_derivations.setdefault("clinical_tstage", dre_implied_tstage.removeprefix("c"))
        payload_with_derivations.setdefault("clinical_tstage_dre_estimate", dre_implied_tstage.removeprefix("c"))
    if psad_context.value is not None:
        payload_with_derivations.setdefault("psad", psad_context.value)

    # Brecha M-staging gate — 2026-04-22 (§D.1):
    # Calcula descriptor de gap de estadificación para que el service emita
    # PSMA/GGO/TAC explícitos cuando PSA>20, cT2b-T4 o ISUP≥4 lo exigen
    # (NCCN PROS-2 v5.2026 cat 1; EAU 2026 §6.4.1-6.4.3). En diagnostic_workup
    # NO bloquea (no hay tratamiento curativo); informa qué falta.
    staging_gap = staging_gap_descriptor(payload_with_derivations)

    # ── Brecha 2026-04-23: triaje pre-biopsia (emergencia + provisional + ADT) ─
    # NCCN PROS-G v5.2026 + EAU 2026 §6.5.4 + Loblaw 2012 + Briganti.
    # `emergency_triage_descriptor` retorna None si no hay emergencia, o
    # un dict con conteos por severidad y lista detallada de emergencias.
    # `assess_provisional_diagnosis` retorna tier (none/possible/probable/
    # highly_probable/virtually_certain) + basis + confidence + biopsy
    # priority + flag allow_empiric_adt. `empiric_adt_protocol` decide
    # si emitir agonista LHRH + bicalutamida o antagonista (degarelix)
    # según presencia de compresión medular o uropatía obstructiva severa.
    # Estos descriptores los consume `service.py` para insertar 3 ramas
    # paralelas en el bundle de tratamientos sin contaminar la lógica
    # actual de scoring / staging.
    payload_for_engines = dict(payload_with_derivations)
    payload_for_engines["psa"] = psa  # usa PSA corregido por 5-ARI
    emergency = emergency_triage_descriptor(payload_for_engines)
    provisional = assess_provisional_diagnosis(payload_for_engines)
    adt_protocol = empiric_adt_protocol(payload_for_engines, provisional)

    if provisional.get("tier") in ("highly_probable", "virtually_certain"):
        reasons.append(
            f"Diagnóstico provisional clínico nivel '{provisional['tier']}' "
            f"(confianza {provisional['confidence'] * 100:.0f}%): permite "
            "activar workflows downstream (mHSPC empírico, paliativo, ADT) "
            "sin esperar histología confirmatoria — NCCN PROS-G v5.2026, "
            "EAU §6.5.4."
        )
    elif provisional.get("tier") in ("probable", "possible"):
        reasons.append(
            f"Diagnóstico provisional clínico nivel '{provisional['tier']}' "
            f"(confianza {provisional['confidence'] * 100:.0f}%): mantener "
            "biopsia urgente + estadificación M sin diferir."
        )

    if emergency:
        reasons.append(
            f"Triaje de emergencia oncológica: {emergency['critical_count']} "
            f"crítica(s) y {emergency['high_count']} alta(s) detectadas "
            f"(severidad máxima {emergency['max_severity']}, tiempo a "
            f"acción {emergency['min_tta_hours']}h). Requiere referencia "
            "inmediata."
        )

    return {
        "label": label,
        "risk_group": risk_group,
        "score": score,
        "significant_risk_pct": significant_risk_pct,
        "biopsy_indicated": score >= 3 or dre_suspicious or pirads >= 4,
        "repeat_high_quality_mri": mpmri_quality == "Subóptima" and score >= 2,
        "recommendation": recommendation,
        "reasons": reasons,
        "dre_implied_tstage": dre_implied_tstage,
        "dre_context": dre_context.to_dict(),
        "psad_context": psad_context.to_dict(),
        "mri_context": mri_context.to_dict(),
        # EPIC 9 Group F (GAP-12) — Propagación de la corrección PSA y los
        # confundentes al bundle clínico para que profile_compass y copilots
        # puedan surface el delta al usuario.
        "psa_raw_reported": psa_raw,
        "psa_effective_for_scoring": psa,
        "psa_correction_applied": psa_correction_applied,
        "psa_confounders_active": {
            "ari_medication_active": ari_active,
            "uti_prostatitis_recent": uti_prostatitis,
            "urinary_retention_recent": urinary_retention,
            "recent_ejaculation_48h": recent_ejaculation,
            "psa_same_lab_assay": same_lab_assay == "1",
        },
        # Staging M flags (NCCN PROS-2 / EAU §6.4)
        "staging_imaging_recommended": bool(staging_gap),
        "staging_gap": staging_gap,
        # Brecha PSA extremo + cT4 fijo + sin biopsia (2026-04-23)
        # NCCN PROS-G v5.2026 + EAU §6.5.4 + Briganti + Loblaw 2012
        "extreme_psa": psa >= PSA_EXTREME,
        "very_high_psa": psa >= PSA_VERY_HIGH,
        "high_psa": psa >= PSA_HIGH,
        "psa_metastatic_probability": (
            ">97%" if psa >= PSA_VIRTUALLY_CERTAIN else
            ">93%" if psa >= PSA_EXTREME else
            "80-90%" if psa >= PSA_VERY_HIGH else
            "60-75%" if psa >= PSA_HIGH else
            "10-35%" if psa >= 20 else
            "<10%"
        ),
        "oncologic_emergency": emergency,
        "provisional_diagnosis": provisional,
        "empiric_adt_protocol": adt_protocol,
    }


def _is_true(value) -> bool:
    return str(value).lower() in {"1", "true", "yes", "si", "on"}


def _safe_float(value, *, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default
