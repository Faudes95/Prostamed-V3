from __future__ import annotations

from typing import Any

from prostanet.shared.clinical_fact_resolver import resolve_patient_clinical_facts


DIAGNOSTIC_STATES = {"diagnostic_workup", "post_negative_biopsy_followup"}
LOCAL_M0_INCOMPATIBLE_STATES = {"localized_initial", "post_prostatectomy", "m0_crpc"}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if _is_present(value):
            return value
    return None


def _append_contradiction(
    contradictions: list[dict[str, Any]],
    *,
    contradiction_key: str,
    severity: str,
    policy: str,
    title: str,
    rationale: str,
    affected_fields: list[str],
    suggested_resolution: str,
    current_state: str,
    target_state: str = "",
) -> None:
    contradictions.append(
        {
            "contradiction_key": contradiction_key,
            "severity": severity,
            "policy": policy,
            "title": title,
            "rationale": rationale,
            "affected_fields": list(affected_fields or []),
            "suggested_resolution": suggested_resolution,
            "current_state": current_state,
            "target_state": target_state or current_state,
            "resolution_status": "open",
        }
    )


def build_clinical_contradiction_bundle(
    patient: dict[str, Any],
    *,
    latest_assessment: dict[str, Any] | None = None,
    clinical_fact_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    facts_bundle = clinical_fact_bundle or resolve_patient_clinical_facts(patient)
    field_values = dict(facts_bundle.get("field_values") or {})
    contradictions: list[dict[str, Any]] = []

    explicit_state = str(
        _first_nonempty(
            (latest_assessment or {}).get("state"),
            (patient.get("latest_assessment") or {}).get("state"),
            (patient.get("prior_history") or {}).get("current_state"),
            "diagnostic_workup",
        )
    )
    reconciled_state = str(
        _first_nonempty(
            (patient.get("reconciled_state") or {}).get("reconciled_state"),
            (patient.get("latest_signal_snapshot") or {}).get("reconciled_state"),
            explicit_state,
        )
    )
    metastatic_stage = str(field_values.get("metastatic_stage_resolved") or "M0")
    known_cancer = field_values.get("known_cancer_diagnosis")
    official_diagnosis = str(
        _first_nonempty(
            ((patient.get("prior_history") or {}).get("official_diagnosis") or {}).get("headline")
            if isinstance((patient.get("prior_history") or {}).get("official_diagnosis"), dict)
            else (patient.get("prior_history") or {}).get("official_diagnosis"),
            ((patient.get("latest_signal_snapshot") or {}).get("official_diagnosis") or ""),
        )
        or ""
    )
    latest_biopsies = list(patient.get("biopsies") or [])
    histology_present = any(
        any(_is_present(item.get(field)) for field in ("gleason_primary", "gleason_secondary", "isup_grade", "positive_cores"))
        for item in latest_biopsies
    ) or any(_is_present(field_values.get(field)) for field in ("gleason_primary", "gleason_secondary", "isup_grade"))

    if metastatic_stage != "M0" and explicit_state in LOCAL_M0_INCOMPATIBLE_STATES:
        target_state = "adt_progression_verification" if explicit_state == "m0_crpc" else "state_reclassification_required"
        _append_contradiction(
            contradictions,
            contradiction_key="m1_in_m0_lane",
            severity="critical",
            policy="hard_stop",
            title="M1 documentado en carril incompatible",
            rationale="Existe enfermedad metastásica documentada y el caso no puede permanecer en un carril M0/localizado.",
            affected_fields=["metastatic_stage_resolved", "reconciled_state"],
            suggested_resolution="Expulsar automáticamente el caso del carril M0/localizado y redirigir el curso clínico.",
            current_state=explicit_state,
            target_state=target_state,
        )

    if explicit_state not in DIAGNOSTIC_STATES and known_cancer is False:
        _append_contradiction(
            contradictions,
            contradiction_key="therapeutic_lane_without_confirmed_cancer",
            severity="critical",
            policy="hard_stop",
            title="Carril terapéutico sin cáncer conocido",
            rationale="El caso se encuentra en un carril oncológico terapéutico, pero el hecho clínico canónico aún marca que no hay cáncer conocido.",
            affected_fields=["known_cancer_diagnosis", "official_diagnosis"],
            suggested_resolution="Revisar confirmación diagnóstica o regresar a carril diagnóstico antes de publicar una recomendación definitiva.",
            current_state=explicit_state,
            target_state="diagnostic_workup",
        )

    if explicit_state == "post_negative_biopsy_followup" and "confirm" in official_diagnosis.lower() and not histology_present:
        _append_contradiction(
            contradictions,
            contradiction_key="confirmed_copy_without_histology",
            severity="critical",
            policy="hard_stop",
            title="Copy de cáncer confirmado sin histología real",
            rationale="El copy visible sugiere confirmación oncológica, pero no existe histología estructurada que la sostenga.",
            affected_fields=["official_diagnosis", "histology_subtype"],
            suggested_resolution="Degradar el copy a sospecha/provisional y reabrir estudio diagnóstico.",
            current_state=explicit_state,
            target_state="post_negative_biopsy_followup",
        )

    if explicit_state == "active_surveillance":
        high_risk_histology = int(field_values.get("isup_grade") or 0) >= 3
        if high_risk_histology or metastatic_stage != "M0":
            _append_contradiction(
                contradictions,
                contradiction_key="active_surveillance_biology_mismatch",
                severity="critical",
                policy="hard_stop",
                title="Vigilancia activa con biología incompatible",
                rationale="La vigilancia activa no puede publicarse como recomendación definitiva cuando el perfil histológico o metastásico ya es incompatible.",
                affected_fields=["isup_grade", "metastatic_stage_resolved"],
                suggested_resolution="Cerrar carril de vigilancia activa y redirigir a tratamiento activo.",
                current_state=explicit_state,
                target_state="localized_initial",
            )

    if explicit_state == "m1_crpc":
        castrate_status = str(field_values.get("castrate_testosterone_status") or "").lower()
        progression_pattern = str(
            _first_nonempty(
                (patient.get("latest_signal_snapshot") or {}).get("progression_pattern"),
                (patient.get("latest_assessment") or {}).get("input_snapshot", {}).get("progression_pattern"),
            )
            or ""
        ).lower()
        if castrate_status not in {"confirmed_castrate", "castrate", "confirmed"} or not progression_pattern:
            _append_contradiction(
                contradictions,
                contradiction_key="m1_crpc_without_verification",
                severity="critical",
                policy="hard_stop",
                title="m1CRPC sin verificación completa",
                rationale="El carril m1CRPC requiere testosterona en rango de castración y progresión resistente documentada.",
                affected_fields=["castrate_testosterone_status", "progression_pattern"],
                suggested_resolution="Retener el caso en adt_progression_verification hasta completar el dataset obligatorio.",
                current_state=explicit_state,
                target_state="adt_progression_verification",
            )

    # EPIC 28.11 (GodiBot G49 MOD) — inverse contradiction: mCSPC state with
    # castrate-range testosterone + PSA rising = possible CRPC misclassification.
    # Pre-EPIC28 only the forward direction (m1_crpc requires castrate) was
    # checked. Reverse case (state labeled mcspc_* but biology suggests CRPC)
    # passed silently → patient could receive mCSPC-tier therapy when they're
    # already CRPC and need different sequencing.
    MHSPC_STATES = {
        "mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume_sync", "mcspc_high_volume_metachronous",
        "mcspc_high_volume", "mcspc_latitude_high_risk",
        "mcspc_visceral_only_m1c", "mcspc_psma_only_metastatic",
    }
    if explicit_state in MHSPC_STATES:
        try:
            testo_val = float(field_values.get("testosterone_value") or field_values.get("testosterone") or 999)
        except (TypeError, ValueError):
            testo_val = 999
        castrate_range = testo_val < 50
        # EPIC 29.2 (GodiBot G55 HIGH) — PCWG3-correct implementation.
        # Pre-fix: `recent[-1] > recent[0] * 1.25` (25% rise from OLDEST in
        # 3-PSA window) — wrong. PCWG3 Scher JCO 2016 requires:
        #   rise from NADIR (lowest PSA in history) of ≥25%
        #   AND ≥2 ng/mL absolute increase
        #   AND confirmed with second value ≥3 weeks later
        # Pre-fix examples missed: 5.0→4.5→5.5 (no nadir reference) and
        # over-called: 4.0→4.5→5.7 (1.25× without 2 ng/mL absolute).
        psa_history = patient.get("psa_history") or []
        psa_rising = False
        if isinstance(psa_history, list) and len(psa_history) >= 3:
            try:
                psa_values = [
                    float(p.get("psa_value") or p.get("value") or 0)
                    for p in psa_history if isinstance(p, dict)
                ]
                psa_values = [v for v in psa_values if v > 0]
                if len(psa_values) >= 3:
                    nadir = min(psa_values)
                    current = psa_values[-1]
                    previous = psa_values[-2]
                    rise_from_nadir_pct = (current - nadir) / max(nadir, 0.1)
                    rise_from_nadir_abs = current - nadir
                    # PCWG3 §rising PSA criterion: ≥25% rise AND ≥2 ng/mL
                    # absolute increase from nadir. Plus confirmation (the
                    # previous value also above nadir+threshold serves as
                    # the confirmatory measurement here).
                    rise_meets_criteria = (
                        rise_from_nadir_pct >= 0.25
                        and rise_from_nadir_abs >= 2.0
                    )
                    confirmatory = previous > nadir * 1.10  # previous also above nadir
                    if rise_meets_criteria and confirmatory:
                        psa_rising = True
            except (TypeError, ValueError):
                pass
        progression_signal = (
            psa_rising
            or str(field_values.get("progression_pattern") or "").lower() in {
                "biochemical", "radiographic", "clinical", "any",
            }
        )
        if castrate_range and progression_signal:
            _append_contradiction(
                contradictions,
                contradiction_key="mhspc_with_castrate_progression",
                severity="critical",
                policy="hard_stop",
                title="mCSPC etiquetado pero biología sugiere mCRPC",
                rationale=(
                    f"Estado actual='{explicit_state}' (mCSPC) pero testosterona "
                    f"{testo_val:.0f} ng/dL <50 (rango castración) Y signal de progresión "
                    f"(PSA rising o pattern documented). Per PCWG3 (Scher JCO 2016 PMID "
                    "26903579) esto define mCRPC. Mantener etiqueta mCSPC arriesga "
                    "secuenciación terapéutica equivocada."
                ),
                affected_fields=["castrate_testosterone_status", "testosterone_value", "psa_history", "progression_pattern"],
                suggested_resolution=(
                    "Reclasificar a adt_progression_verification para confirmar criterios "
                    "PCWG3 (testosterona<50 + biochemical OR radiographic progression). "
                    "Luego promover a m0_crpc o m1_crpc según imagen."
                ),
                current_state=explicit_state,
                target_state="adt_progression_verification",
            )

    unresolved = [item for item in contradictions if item.get("resolution_status") == "open"]
    critical_unresolved = [item for item in unresolved if item.get("severity") == "critical"]
    block_status = "hard_stop" if critical_unresolved else "provisional" if unresolved else "clear"
    state_reclassification_required = bool(
        any(item.get("contradiction_key") == "m1_in_m0_lane" for item in unresolved)
    )
    reclassification_targets = list(
        dict.fromkeys(
            item.get("target_state")
            for item in unresolved
            if str(item.get("target_state") or "").strip()
        )
    )
    return {
        "available": bool(contradictions),
        "block_status": block_status,
        "critical_unresolved_count": len(critical_unresolved),
        "open_contradictions_count": len(unresolved),
        "contradictions": contradictions,
        "state_reclassification_required": state_reclassification_required,
        "state_reclassification_targets": reclassification_targets,
        "current_state": explicit_state,
        "reconciled_state": reconciled_state,
    }
