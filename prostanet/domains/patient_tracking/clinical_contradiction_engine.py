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
