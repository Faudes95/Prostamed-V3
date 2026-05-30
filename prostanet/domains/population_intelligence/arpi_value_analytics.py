"""Real-world ARPI value analytics.

Cruza dosis locales, gasto estimado, descenso de PSA/APE y cambio ECOG para
convertir el tracking operativo en una superficie epidemiologica trazable.
"""
from __future__ import annotations

import sqlite3
import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any, Mapping

from prostanet.domains.patient_tracking.arpi_response_window import _classify_arpi
from prostanet.domains.patient_tracking.treatment_course_tracker import regimen_intensity
from prostanet.domains.patient_tracking.therapy_catalog import normalize_regimen_code
from prostanet.domains.population_intelligence.suppression import (
    MIN_COHORT_N,
    normal_ci_mean,
    proportion_with_ci,
)
from prostanet.domains.population_intelligence.metric_provenance import (
    build_metric_provenance_binding,
)
from prostanet.shared.utc_time import utc_now_iso


ARPI_LABELS = ("ABIRATERONE", "ENZALUTAMIDE", "APALUTAMIDE", "DAROLUTAMIDE")
RESPONSE_QUALITY_FOR_VALUE = {"in_window", "closest_outside_window"}
EPIDEMIOLOGY_GAP_REVIEW_EVENT_TYPE = "epidemiology_readiness_gap_reviewed"
TREATMENT_VALUE_CAPTURE_IMPACT_VERSION = "treatment_value_capture_impact_v1"
RESEARCH_PACK_DATA_DICTIONARY = [
    ("week", "Ventana de respuesta", "integer", "arpi_response_windows.target_weeks", "Semanas desde inicio de linea evaluada."),
    ("patient_ref", "Identificador paciente", "string", "patient_identity.nss", "Clave trazable hacia perfil V2."),
    ("patient_name", "Nombre paciente", "string", "patient_identity.full_name", "Visible solo para auditoria interna local."),
    ("molecule", "Molecula ARPI", "categorical", "therapy_catalog/regimen_code", "ARPI dominante del regimen."),
    ("regimen_code", "Regimen codificado", "categorical", "treatment_history.drug_scheme", "Esquema sistemico normalizado."),
    ("baseline_state_bucket", "Bucket basal ajustado", "string", "clinical_baseline + treatment_history", "Estado clinico, linea, PSA, ECOG, edad, volumen y comorbilidad."),
    ("baseline_psa", "APE basal", "float", "arpi_response_windows.baseline_psa", "APE al inicio de linea o baseline disponible."),
    ("actual_psa", "APE de ventana", "float", "arpi_response_windows.actual_psa", "APE mas cercano a la ventana analitica."),
    ("psa_decline_pct", "Descenso APE porcentual", "float", "derived", "Porcentaje de reduccion respecto a basal."),
    ("psa50_response", "Respuesta PSA50", "boolean", "derived", "Reduccion APE >=50% cuando la ventana es evaluable."),
    ("psa90_response", "Respuesta PSA90", "boolean", "derived", "Reduccion APE >=90% cuando la ventana es evaluable."),
    ("baseline_ecog", "ECOG basal", "integer", "arpi_response_windows.baseline_ecog", "Estado funcional basal."),
    ("actual_ecog", "ECOG ventana", "integer", "arpi_response_windows.actual_ecog", "Estado funcional en ventana."),
    ("actual_ecog_date", "Fecha ECOG ventana", "date", "arpi_response_windows.actual_ecog_date", "Fecha clinica real usada para ECOG de ventana."),
    ("ecog_change_from_baseline", "Cambio ECOG", "integer", "derived", "Actual menos basal; negativo indica mejoria."),
    ("first_priced_local_dose_date_to_window", "Primera dosis costeada", "date", "treatment_dose_administrations", "Primera fecha de dosis local con costo ARPI trazable hasta la ventana."),
    ("spend_to_window_mxn", "Gasto estimado acumulado", "currency_mxn", "treatment_dose_administrations", "Costo trazable de dosis locales hasta ventana."),
    ("high_grade_toxicity_to_window", "Toxicidad G3+", "boolean", "treatment_adverse_events", "Evento CTCAE grado 3 o mayor hasta ventana."),
    ("toxicity_review_documented", "Revision toxicidad", "boolean", "treatment_adverse_events + CTCAE_TOXICITY", "Distingue ausencia revisada de ausencia de captura."),
    ("toxicity_absence_documented", "Sin toxicidad revisada", "boolean", "CTCAE_TOXICITY", "CTCAE grado 0 o revision explicita sin evento toxico."),
    ("hospitalization_toxicity_to_window", "Hospitalizacion por toxicidad", "boolean", "treatment_adverse_events", "Hospitalizacion atribuida a toxicidad hasta ventana."),
    ("referral_status", "Estado de referencia", "categorical", "treatment_dose_administrations", "Señal HGZ/HGR derivada de numero de dosis locales."),
    ("referral_delay_days", "Retraso de referencia", "integer_days", "derived", "Dias entre disparador y evento critico/ultima dosis."),
    ("discontinued_by_window", "Discontinuacion", "boolean", "treatment_history", "Linea finalizada o suspendida antes de la ventana."),
    ("time_to_psa_progression_days", "Tiempo a progresion APE", "integer_days", "patient_events", "Dias desde inicio de linea a progresion bioquimica documentada."),
    ("time_to_discontinuation_days", "Tiempo a discontinuacion", "integer_days", "treatment_history", "Dias desde inicio de linea a fin documentado."),
    ("line_persistence_days_to_window", "Persistencia de linea", "integer_days", "derived", "Dias en regimen hasta ventana o discontinuacion."),
    ("bone_event_to_window", "Evento oseo", "boolean", "patient_events", "Evento esqueletico hasta ventana si esta documentado."),
    ("death_to_window", "Muerte hasta ventana", "boolean", "patient_identity", "Defuncion documentada antes de la ventana."),
    ("evidence_quality", "Calidad de evidencia", "categorical", "arpi_response_windows", "Clasificacion de cercania/validez de ventana."),
    ("profile_url", "Perfil V2", "url", "derived", "Ruta local auditable al paciente que origina la metrica."),
]


def _db_path() -> str:
    import tracking_db

    return tracking_db.get_db_path()


def build_arpi_value_patient_rows(
    *,
    weeks: int = 24,
    real_only: bool = False,
) -> list[dict[str, Any]]:
    """Returns patient-level value rows for ARPI response and local dose cost."""
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        response_sql = """
            SELECT arw.*, pi.nss, pi.full_name, COALESCE(pi.is_synthetic, 0) AS is_synthetic
            FROM arpi_response_windows arw
            JOIN patient_identity pi ON pi.id = arw.patient_id
            WHERE arw.target_weeks = ?
        """
        params: list[Any] = [weeks]
        if real_only:
            response_sql += " AND COALESCE(pi.is_synthetic, 0) = 0"
        response_sql += " ORDER BY arw.patient_id ASC, arw.regimen_code ASC"
        response_rows = [dict(row) for row in conn.execute(response_sql, params).fetchall()]
        patient_ids = sorted({int(row["patient_id"]) for row in response_rows if row.get("patient_id")})
        dose_rows_by_patient: dict[int, list[dict[str, Any]]] = defaultdict(list)
        if patient_ids:
            placeholders = ",".join("?" for _ in patient_ids)
            dose_rows = conn.execute(
                f"""
                SELECT *
                FROM treatment_dose_administrations
                WHERE patient_id IN ({placeholders})
                  AND COALESCE(administered_in_unit, 1) = 1
                ORDER BY patient_id ASC, dose_date ASC, id ASC
                """,
                patient_ids,
            ).fetchall()
            for row in dose_rows:
                item = dict(row)
                dose_rows_by_patient[int(item["patient_id"])].append(item)
    finally:
        conn.close()

    patient_rows: list[dict[str, Any]] = []
    for row in response_rows:
        regimen_code = str(row.get("regimen_code") or "")
        arpi_label = _arpi_label_for_regimen(regimen_code)
        if arpi_label not in ARPI_LABELS:
            continue
        target_date = str(row.get("target_date") or "")[:10]
        actual_psa_date = str(row.get("actual_psa_date") or "")[:10]
        cutoff_date = actual_psa_date or target_date
        matched_doses = _match_doses_to_response(
            dose_rows_by_patient.get(int(row["patient_id"]), []),
            regimen_code=regimen_code,
            arpi_label=arpi_label,
            cutoff_date=cutoff_date,
        )
        spend_values = [
            _safe_float(dose.get("estimated_cost_mxn"), None)
            for dose in matched_doses
        ]
        priced_values = [value for value in spend_values if value is not None]
        cost_sources = [_parse_cost_source(dose.get("cost_source_json")) for dose in matched_doses]
        partial_cost_dose_count = sum(1 for item in cost_sources if item.get("is_partial"))
        stale_cost_dose_count = sum(1 for item in cost_sources if item.get("stale_price_components"))
        missing_cost_components = sorted({
            component
            for item in cost_sources
            for component in (item.get("missing_arpi_components") or item.get("missing_components") or [])
        })
        stale_price_components = sorted({
            component
            for item in cost_sources
            for component in (item.get("stale_price_components") or [])
        })
        spend_to_window = round(sum(priced_values), 2)
        local_dose_numbers = [
            _safe_int(dose.get("dose_number_local"), None)
            for dose in matched_doses
        ]
        local_dose_numbers = [value for value in local_dose_numbers if value is not None]
        local_dose_dates = _sorted_iso_dates(dose.get("dose_date") for dose in matched_doses)
        priced_local_dose_dates = _sorted_iso_dates(
            dose.get("dose_date")
            for dose in matched_doses
            if (_safe_float(dose.get("estimated_cost_mxn"), None) or 0) > 0
        )
        psa_decline = _safe_float(row.get("psa_decline_pct"), None)
        ecog_change = _safe_int(row.get("ecog_change_from_baseline"), None)
        evidence_quality = str(row.get("evidence_quality") or "")
        response_evaluable = (
            evidence_quality in RESPONSE_QUALITY_FOR_VALUE
            and psa_decline is not None
            and _safe_float(row.get("baseline_psa"), None) not in (None, 0)
            and _safe_float(row.get("actual_psa"), None) is not None
        )
        patient_rows.append(
            {
                "patient_id": row.get("patient_id"),
                "patient_ref": row.get("nss"),
                "patient_name": row.get("full_name"),
                "is_synthetic": bool(row.get("is_synthetic")),
                "arpi_agent": arpi_label,
                "regimen_code": normalize_regimen_code(regimen_code),
                "target_weeks": weeks,
                "target_date": target_date,
                "line_start_date": row.get("line_start_date"),
                "actual_psa_date": actual_psa_date or None,
                "baseline_psa": _safe_float(row.get("baseline_psa"), None),
                "actual_psa": _safe_float(row.get("actual_psa"), None),
                "psa_decline_pct": psa_decline,
                "psa50_response": bool(row.get("psa50_response")) if response_evaluable else None,
                "psa90_response": bool(row.get("psa90_response")) if response_evaluable else None,
                "baseline_ecog": _safe_int(row.get("baseline_ecog"), None),
                "baseline_ecog_date": str(row.get("baseline_ecog_date") or "")[:10] or None,
                "actual_ecog": _safe_int(row.get("actual_ecog"), None),
                "actual_ecog_date": str(row.get("actual_ecog_date") or "")[:10] or None,
                "ecog_offset_days": _safe_int(row.get("ecog_offset_days"), None),
                "ecog_evidence_quality": str(row.get("ecog_evidence_quality") or "") or None,
                "ecog_change_from_baseline": ecog_change,
                "ecog_improved": ecog_change < 0 if ecog_change is not None else None,
                "evidence_quality": evidence_quality,
                "response_evaluable": response_evaluable,
                "local_dose_count_to_window": len(matched_doses),
                "latest_local_dose_number": max(local_dose_numbers) if local_dose_numbers else None,
                "first_local_dose_date_to_window": local_dose_dates[0] if local_dose_dates else None,
                "latest_local_dose_date_to_window": local_dose_dates[-1] if local_dose_dates else None,
                "first_priced_local_dose_date_to_window": (
                    priced_local_dose_dates[0] if priced_local_dose_dates else None
                ),
                "priced_local_dose_count": len(priced_values),
                "partial_cost_dose_count": partial_cost_dose_count,
                "stale_cost_dose_count": stale_cost_dose_count,
                "missing_arpi_cost_components": missing_cost_components,
                "stale_price_components": stale_price_components,
                "spend_to_window_mxn": spend_to_window,
                "cost_per_pct_psa_decline_mxn": (
                    round(spend_to_window / psa_decline, 2)
                    if spend_to_window and psa_decline and psa_decline > 0
                    else None
                ),
            }
        )
    return patient_rows


def aggregate_arpi_value_by_response(
    *,
    weeks: int = 24,
    real_only: bool = False,
) -> dict[str, Any]:
    """Aggregates ARPI spend, local doses, PSA response and ECOG change."""
    rows = build_arpi_value_patient_rows(weeks=weeks, real_only=real_only)
    grouped: dict[str, list[dict[str, Any]]] = {label: [] for label in ARPI_LABELS}
    for row in rows:
        grouped.setdefault(row["arpi_agent"], []).append(row)

    by_arpi: dict[str, dict[str, Any]] = {}
    for label in ARPI_LABELS:
        by_arpi[label] = _summarize_value_rows(label, grouped.get(label, []))

    total_spend = round(sum(_safe_float(row.get("spend_to_window_mxn"), 0.0) or 0.0 for row in rows), 2)
    total_doses = sum(_safe_int(row.get("local_dose_count_to_window"), 0) or 0 for row in rows)
    total_priced_doses = sum(_safe_int(row.get("priced_local_dose_count"), 0) or 0 for row in rows)
    response_evaluable = [row for row in rows if row.get("response_evaluable")]
    ecog_evaluable = [row for row in rows if row.get("ecog_change_from_baseline") is not None]
    psa50_count = sum(1 for row in response_evaluable if row.get("psa50_response") is True)
    ecog_improved_count = sum(1 for row in ecog_evaluable if row.get("ecog_improved") is True)
    summary = {
        "n_patients": len(rows),
        "n_response_evaluable": len(response_evaluable),
        "n_ecog_evaluable": len(ecog_evaluable),
        "total_local_arpi_doses_to_window": total_doses,
        "priced_local_arpi_doses_to_window": total_priced_doses,
        "partial_cost_patient_count": sum(1 for row in rows if row.get("partial_cost_dose_count")),
        "stale_price_patient_count": sum(1 for row in rows if row.get("stale_cost_dose_count")),
        "estimated_spend_to_window_mxn": total_spend,
        "psa50_responder_count": psa50_count,
        "ecog_improved_count": ecog_improved_count,
        "cost_per_psa50_responder_mxn": round(total_spend / psa50_count, 2) if psa50_count else None,
        "cost_per_ecog_improved_patient_mxn": (
            round(total_spend / ecog_improved_count, 2) if ecog_improved_count else None
        ),
    }
    return {
        "kpi_id": f"arpi_value_{weeks}wk",
        "kpi_label": f"Valor clinico-economico ARPI @ {weeks} semanas",
        "category": "real_world_value",
        "target_weeks": weeks,
        "real_only": real_only,
        "summary": summary,
        "by_arpi": by_arpi,
        "patient_rows": rows,
        "computed_at": utc_now_iso(),
        "interpretation": (
            "Relaciona gasto local estimado y dosis otorgadas con respuesta PSA50/PSA90 "
            "y mejoria ECOG. Exploratorio: requiere captura sistematica de PSA, ECOG, "
            "fechas de dosis y catalogo de precios vigente."
        ),
        "suppression_note": f"Metricas por molecula con n<{MIN_COHORT_N} se suprimen.",
    }


def build_treatment_value_registry(
    *,
    weeks_list: tuple[int, ...] = (12, 24),
    real_only: bool = False,
    include_patient_rows: bool = True,
    filters: Mapping[str, Any] | None = None,
    trace_limit: int = 100,
) -> dict[str, Any]:
    """Comparative longitudinal value registry by molecule and regimen.

    This is intentionally a registry/analytics layer, not a new treatment
    engine. It reuses the clinical facts already captured by ProstaNet:
    response windows, treatment lines, local doses, CTCAE adverse events,
    referral alerts and audited ARPI cost estimates.
    """
    windows: dict[str, Any] = {}
    raw_rows_by_week: dict[str, list[dict[str, Any]]] = {}
    filtered_rows_by_week: dict[str, list[dict[str, Any]]] = {}
    normalized_filters = _normalize_registry_filters(filters or {})
    for weeks in weeks_list:
        rows = build_treatment_value_registry_rows(weeks=weeks, real_only=real_only)
        raw_rows_by_week[str(weeks)] = rows
        rows = _filter_treatment_value_rows(rows, normalized_filters)
        filtered_rows_by_week[str(weeks)] = rows
        windows[str(weeks)] = _summarize_treatment_value_window(
            weeks=weeks,
            rows=rows,
            include_patient_rows=include_patient_rows,
        )
    capture_worklist = _build_epidemiology_capture_worklist(filtered_rows_by_week)
    return {
        "kpi_id": "treatment_value_registry_12_24wk",
        "kpi_label": "Registro longitudinal comparativo tratamiento-valor @ 12/24 semanas",
        "category": "real_world_value_registry",
        "real_only": real_only,
        "active_filters": normalized_filters,
        "cohort_builder": _build_cohort_builder_descriptor(raw_rows_by_week, normalized_filters),
        "filter_options": _build_treatment_value_filter_options(raw_rows_by_week),
        "weeks_list": list(weeks_list),
        "windows": windows,
        "cohort_matrix": _build_treatment_value_cohort_matrix(windows),
        "completeness_tower": _build_epidemiology_completeness_tower(filtered_rows_by_week),
        "longitudinal_outcomes": _build_longitudinal_outcomes_summary(filtered_rows_by_week),
        "economic_layer": _build_economic_layer_summary(filtered_rows_by_week),
        "research_governance": _build_research_governance(filtered_rows_by_week),
        "capture_worklist": capture_worklist,
        "operational_gap_latency": _build_operational_gap_latency_summary(
            filtered_rows_by_week,
            capture_worklist,
        ),
        "patient_metric_trace": (
            _build_patient_metric_trace(filtered_rows_by_week, trace_limit=trace_limit)
            if include_patient_rows
            else []
        ),
        "baseline_adjustment_method": (
            "Direct standardization by baseline_state_bucket "
            "(clinical state/line context + baseline PSA band + baseline ECOG band)."
        ),
        "interpretation": (
            "Compara molecula y regimen con PSA50/PSA90, cambio ECOG, "
            "discontinuacion, toxicidad CTCAE, retraso de referencia y costo "
            "por respuesta. Exploratorio y dependiente de completitud longitudinal."
        ),
        "computed_at": utc_now_iso(),
    }


def build_treatment_value_capture_impact(
    patient_ref: str,
    *,
    weeks_list: tuple[int, ...] = (12, 24, 36, 52),
    real_only: bool = False,
    filters: Mapping[str, Any] | None = None,
    before_snapshot: Mapping[str, Any] | None = None,
    kind: str = "",
    append_result: Mapping[str, Any] | None = None,
    recompute_result: Mapping[str, Any] | None = None,
    trace_limit: int = 20,
) -> dict[str, Any]:
    """Read-only patient-to-cohort delta after longitudinal capture.

    This is the population counterpart to the patient-level APE and treatment
    economic impact panels. It answers: once APE/ECOG/dose/regimen data exists,
    where does this patient now contribute in the V2 treatment-value registry?
    No source clinical facts are edited here.
    """
    normalized_ref = str(patient_ref or "").strip()
    normalized_filters = _normalize_registry_filters(filters or {})
    normalized_filters["patient_ref"] = ""
    raw_rows_by_week: dict[str, list[dict[str, Any]]] = {}
    cohort_rows_by_week: dict[str, list[dict[str, Any]]] = {}
    patient_rows_by_week: dict[str, list[dict[str, Any]]] = {}
    windows: dict[str, Any] = {}
    active_windows: list[int] = []
    patient_metric_trace: list[dict[str, Any]] = []

    for weeks in weeks_list:
        rows = build_treatment_value_registry_rows(weeks=int(weeks), real_only=real_only)
        raw_rows_by_week[str(weeks)] = rows
        cohort_rows = _filter_treatment_value_rows(rows, normalized_filters)
        patient_rows = [
            row for row in cohort_rows
            if _same_patient_ref(row.get("patient_ref"), normalized_ref)
        ]
        cohort_rows_by_week[str(weeks)] = cohort_rows
        patient_rows_by_week[str(weeks)] = patient_rows
        if patient_rows:
            active_windows.append(int(weeks))
        windows[str(weeks)] = _capture_window_delta(
            weeks=int(weeks),
            patient_ref=normalized_ref,
            cohort_rows=cohort_rows,
            patient_rows=patient_rows,
        )

    if trace_limit != 0:
        patient_metric_trace = _build_patient_metric_trace(
            patient_rows_by_week,
            trace_limit=max(1, int(trace_limit or 20)),
        )
    else:
        patient_metric_trace = _build_patient_metric_trace(patient_rows_by_week, trace_limit=0)

    capture_worklist = _build_epidemiology_capture_worklist(patient_rows_by_week)
    after_summary = _capture_snapshot_summary(windows)
    before_summary = (
        dict((before_snapshot.get("after") or before_snapshot.get("summary") or {}))
        if before_snapshot
        else {}
    )
    return {
        "available": bool(normalized_ref),
        "version": TREATMENT_VALUE_CAPTURE_IMPACT_VERSION,
        "computed_at": utc_now_iso(),
        "patient_ref": normalized_ref,
        "kind_appended": str(kind or ""),
        "append_success": bool((append_result or {}).get("success")) if append_result else None,
        "appended_id": (append_result or {}).get("appended_id") if append_result else None,
        "recompute_success": bool((recompute_result or {}).get("success")) if recompute_result else None,
        "decision_changed": bool((recompute_result or {}).get("decision_changed")) if recompute_result else False,
        "real_only": real_only,
        "active_filters": normalized_filters,
        "weeks_list": [int(week) for week in weeks_list],
        "active_windows": active_windows,
        "primary_window_weeks": max(active_windows) if active_windows else None,
        "before": before_summary,
        "after": after_summary,
        "delta_since_before": _capture_summary_delta(before_summary, after_summary),
        "windows": windows,
        "patient_metric_trace": patient_metric_trace,
        "capture_worklist": capture_worklist,
        "refreshed_surfaces": [
            "treatment_value_registry_v2",
            "epidemiology_command_center_v2",
            "patient_profile_v2_value_summary",
            "research_pack_materializer_candidate",
        ],
        "next_surfaces": {
            "profile_v2": f"/patient_profile/{normalized_ref}?v=2" if normalized_ref else "",
            "treatment_value_registry": (
                f"/population/treatment-value-registry?patient_ref={normalized_ref}"
                if normalized_ref else "/population/treatment-value-registry"
            ),
            "epidemiology_command_center": "/population/epidemiology-command-center",
            "registry_api": (
                f"/api/analytics/treatment-value-registry?weeks={','.join(str(w) for w in weeks_list)}"
                f"&patient_ref={normalized_ref}&trace_limit=50"
                if normalized_ref else ""
            ),
        },
        "clinical_message": _capture_impact_message(after_summary, capture_worklist),
        "read_only_impact_model": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
    }


def build_patient_epidemiology_gap_sla(
    patient_ref: str,
    *,
    weeks_list: tuple[int, ...] = (12, 24),
    real_only: bool = False,
    trace_limit: int = 0,
) -> dict[str, Any]:
    """Patient-scoped operational SLA view for epidemiology registry gaps.

    This is a thin read-only layer over the treatment-value registry worklist.
    It exists so Profile V2 can show patient-specific unresolved gaps without
    duplicating capture logic or mutating clinical facts.
    """
    normalized_ref = str(patient_ref or "").strip()
    impact = build_treatment_value_capture_impact(
        normalized_ref,
        weeks_list=weeks_list,
        real_only=real_only,
        trace_limit=trace_limit,
    )
    worklist = impact.get("capture_worklist") or {}
    items = list(worklist.get("items") or [])
    active_items = [item for item in items if item.get("closure_status") != "not_applicable"]
    unreviewed_items = [item for item in active_items if not item.get("reviewed")]
    reviewed_pending = [
        item for item in active_items
        if item.get("audit_state") == "reviewed_still_missing"
    ]
    overdue_items = [
        item for item in active_items
        if str(item.get("sla_state") or "").startswith("overdue")
    ]
    due_soon_items = [
        item for item in active_items
        if str(item.get("sla_state") or "").startswith("due_soon")
    ]
    priority_order = {"high": 0, "moderate": 1, "low": 2}
    sorted_items = sorted(
        active_items,
        key=lambda item: (
            0 if str(item.get("sla_state") or "").startswith("overdue") else 1,
            priority_order.get(str(item.get("priority") or ""), 9),
            _safe_int(item.get("days_to_due"), 9999) or 9999,
            str(item.get("gap_key") or ""),
        ),
    )
    return {
        "available": bool(normalized_ref),
        "version": "patient_epidemiology_gap_sla_v1",
        "computed_at": utc_now_iso(),
        "patient_ref": normalized_ref,
        "active_window_count": len(impact.get("active_windows") or []),
        "weeks_list": list(impact.get("weeks_list") or [int(week) for week in weeks_list]),
        "summary": {
            "active_gap_count": len(active_items),
            "unreviewed_gap_count": len(unreviewed_items),
            "reviewed_still_missing_count": len(reviewed_pending),
            "sla_overdue_count": len(overdue_items),
            "sla_due_soon_count": len(due_soon_items),
            "owner_count": len(worklist.get("sla_by_owner") or []),
            "oldest_open_gap_days": worklist.get("oldest_open_gap_days"),
        },
        "items": sorted_items[:12],
        "sla_by_owner": worklist.get("sla_by_owner") or [],
        "clinical_message": impact.get("clinical_message") or "",
        "next_surfaces": {
            "profile_v2": f"/patient_profile/{normalized_ref}?v=2" if normalized_ref else "",
            "capture_registry": f"/population/treatment-value-registry?patient_ref={normalized_ref}" if normalized_ref else "",
            "epidemiology_command_center": f"/population/epidemiology-command-center?patient_ref={normalized_ref}" if normalized_ref else "",
            "api": f"/api/patients/{normalized_ref}/epidemiology-gap-sla" if normalized_ref else "",
        },
        "read_only_impact_model": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
    }


def build_treatment_value_research_pack(
    *,
    weeks_list: tuple[int, ...] = (12, 24),
    real_only: bool = False,
    filters: Mapping[str, Any] | None = None,
    trace_limit: int = 1000,
) -> dict[str, Any]:
    """Build an auditable research export package for the filtered cohort.

    The pack is a derived artifact from the V2 registry. It does not create a
    new clinical engine or mutate facts; it makes the current cohort publishable
    enough to review: data, dictionary, methods, warnings and patient trace.
    """
    registry = build_treatment_value_registry(
        weeks_list=weeks_list,
        real_only=real_only,
        include_patient_rows=True,
        filters=filters,
        trace_limit=trace_limit,
    )
    numeric_windows = sorted(int(item) for item in registry.get("windows", {}) if str(item).isdigit())
    primary_week = str(numeric_windows[-1]) if numeric_windows else ""
    primary_summary = ((registry.get("windows") or {}).get(primary_week) or {}).get("summary") or {}
    governance = registry.get("research_governance") or {}
    completeness = registry.get("completeness_tower") or {}
    active_filters = registry.get("active_filters") or {}
    trace_rows = registry.get("patient_metric_trace") or []
    cohort_label = _research_pack_cohort_label(active_filters, weeks_list)
    dictionary = _build_research_pack_dictionary()
    return {
        "version": "treatment_value_research_pack_v2",
        "kpi_id": "treatment_value_research_pack_v2",
        "title": f"Research Pack V2 · {cohort_label}",
        "generated_at": utc_now_iso(),
        "cohort_definition": {
            "label": cohort_label,
            "weeks": list(weeks_list),
            "primary_window_weeks": _safe_int(primary_week, None),
            "real_only": real_only,
            "active_filters": active_filters,
            "inclusion_criteria": [
                "Paciente con ventana ARPI calculada en arpi_response_windows.",
                "Regimen con molecula ARPI reconocida por catalogo terapeutico.",
                "Registro enlazado a patient_identity y perfil V2 local.",
            ],
            "exclusion_criteria": [
                "Regimen sin ARPI reconocible para este paquete.",
                "Ventana no solicitada o sin datos suficientes para construir fila paciente-metrica.",
                "Filtros de cohorte que excluyen el registro.",
            ],
            "patient_count_primary_window": primary_summary.get("n_patients", 0),
            "trace_row_count": len(trace_rows),
        },
        "readiness": {
            "governance_status": governance.get("status"),
            "patient_count": governance.get("patient_count"),
            "real_patient_count": governance.get("real_patient_count"),
            "synthetic_patient_count": governance.get("synthetic_patient_count"),
            "overall_completeness_pct": completeness.get("overall_completeness_pct"),
            "completeness_status": completeness.get("status"),
            "research_grade": _research_pack_grade(governance, completeness),
        },
        "methods": {
            "study_design": "Registro longitudinal hospitalario exploratorio de mundo real.",
            "exposure_definition": "Molecula ARPI y regimen sistemico normalizado al inicio de linea.",
            "outcome_windows": list(weeks_list),
            "primary_outcomes": ["PSA50", "PSA90", "cambio ECOG", "costo por respuesta"],
            "secondary_outcomes": [
                "discontinuacion",
                "toxicidad CTCAE G3+",
                "hospitalizacion",
                "retraso de referencia",
                "persistencia terapeutica",
                "evento oseo",
                "muerte si existe",
            ],
            "baseline_adjustment": registry.get("baseline_adjustment_method"),
            "statistical_note": (
                "Comparaciones crudas y estandarizacion directa por bucket basal; "
                "no inferir causalidad hasta contar con N real suficiente, completitud alta "
                "y plan causal/propensity preespecificado."
            ),
            "methods_summary": governance.get("methods_summary"),
        },
        "bias_and_completeness": {
            "bias_warnings": governance.get("bias_warnings") or [],
            "critical_gaps": completeness.get("critical_gaps") or [],
            "domain_coverage": completeness.get("domains") or [],
            "capture_worklist_summary": {
                key: (registry.get("capture_worklist") or {}).get(key)
                for key in ("open_gap_count", "unreviewed_gap_count", "reviewed_gap_count", "patient_count_with_gaps")
            },
        },
        "data_dictionary": dictionary,
        "dataset": {
            "row_count": len(trace_rows),
            "rows": trace_rows,
        },
        "registry_summary": {
            "primary_window": primary_summary,
            "cohort_matrix": registry.get("cohort_matrix") or [],
            "longitudinal_outcomes": registry.get("longitudinal_outcomes") or {},
            "economic_layer": registry.get("economic_layer") or {},
        },
        "suggested_research_questions": governance.get("suggested_research_questions") or [],
        "export_manifest": {
            "json": "/api/analytics/treatment-value-registry/research-pack",
            "csv": "/api/analytics/treatment-value-registry/research-pack?format=csv",
            "dictionary_csv": "/api/analytics/treatment-value-registry/research-pack?format=dictionary_csv",
            "patient_level_primary_key": ["patient_ref", "week", "regimen_code"],
        },
        "audit_note": (
            "Paquete derivado de datos locales V2. No sustituye protocolo aprobado, "
            "comite de investigacion, consentimiento o analisis estadistico formal."
        ),
    }


def build_epidemiology_command_center(
    *,
    weeks_list: tuple[int, ...] = (12, 24, 36, 52),
    real_only: bool = False,
    filters: Mapping[str, Any] | None = None,
    trace_limit: int = 250,
    freeze_limit: int = 6,
    source_freeze_key: str | None = None,
) -> dict[str, Any]:
    """Build the final V2 epidemiology command-center bundle.

    This is an orchestrator over the already validated registry. It does not
    calculate a new treatment recommendation, mutate clinical facts, or train
    models; it arranges the existing patient-to-metric evidence into an
    executive epidemiology, value and research-governance surface.
    """
    registry = build_treatment_value_registry(
        weeks_list=weeks_list,
        real_only=real_only,
        include_patient_rows=True,
        filters=filters,
        trace_limit=trace_limit,
    )
    windows = registry.get("windows") or {}
    primary_window = _select_primary_command_window(windows)
    freezes = _load_recent_research_freezes(limit=freeze_limit)
    capture_impact = _build_command_center_capture_impact(
        weeks_list=weeks_list,
        real_only=real_only,
        filters=filters or {},
        source_freeze_key=source_freeze_key,
    )
    bundle = {
        "version": "epidemiology_command_center_v2",
        "kpi_id": "grand_epidemiology_dashboard_v2",
        "title": "Gran tablero epidemiologico final V2",
        "generated_at": utc_now_iso(),
        "real_only": real_only,
        "weeks_list": list(weeks_list),
        "primary_window_weeks": _safe_int(primary_window, None),
        "active_filters": registry.get("active_filters") or {},
        "filter_options": registry.get("filter_options") or {},
        "cohort_builder": registry.get("cohort_builder") or {},
        "executive_kpis": _build_command_center_kpis(registry, primary_window, capture_impact),
        "outcome_matrix": _build_command_center_outcome_matrix(registry),
        "comparison_panel": _build_command_center_comparison_panel(registry, primary_window),
        "completeness_tower": registry.get("completeness_tower") or {},
        "bias_and_readiness": {
            "research_governance": registry.get("research_governance") or {},
            "causal_readiness": _build_causal_readiness_summary(registry),
            "capture_worklist": registry.get("capture_worklist") or {},
        },
        "economic_layer": _build_command_center_economic_layer(registry, primary_window),
        "longitudinal_outcomes": registry.get("longitudinal_outcomes") or {},
        "operational_gap_latency": registry.get("operational_gap_latency") or {},
        "patient_metric_trace": registry.get("patient_metric_trace") or [],
        "capture_impact_bridge": capture_impact,
        "research_workspace": {
            "recent_freezes": freezes,
            "freeze_count_visible": len(freezes),
            "next_action": "Congelar Research Pack V2 cuando la cohorte tenga filtros estables y sesgos revisados.",
        },
        "export_links": {
            "json": "/api/analytics/epidemiology-command-center",
            "csv": "/api/analytics/epidemiology-command-center?format=csv",
            "registry_json": "/api/analytics/treatment-value-registry?include_rows=1",
            "research_pack_json": "/api/analytics/treatment-value-registry/research-pack",
            "research_pack_csv": "/api/analytics/treatment-value-registry/research-pack?format=csv",
            "dictionary_csv": "/api/analytics/treatment-value-registry/research-pack?format=dictionary_csv",
        },
        "strategic_note": (
            "Superficie poblacional V2 para auditoria clinica, economia institucional "
            "e investigacion. Las comparaciones siguen siendo exploratorias hasta "
            "contar con N real suficiente, completitud alta y plan causal preespecificado."
        ),
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }
    bundle["metric_provenance"] = build_metric_provenance_binding(
        bundle,
        source_freeze_key=source_freeze_key,
        freeze_limit=freeze_limit,
    )
    return bundle


def build_treatment_value_registry_rows(
    *,
    weeks: int,
    real_only: bool = False,
) -> list[dict[str, Any]]:
    base_rows = build_arpi_value_patient_rows(weeks=weeks, real_only=real_only)
    if not base_rows:
        return []
    patient_ids = sorted({int(row["patient_id"]) for row in base_rows if row.get("patient_id")})
    context = _load_treatment_value_context(patient_ids)
    enriched: list[dict[str, Any]] = []
    for row in base_rows:
        patient_id = int(row["patient_id"])
        regimen_code = normalize_regimen_code(row.get("regimen_code"))
        line_start = str(row.get("line_start_date") or "")[:10]
        cutoff_date = str(row.get("actual_psa_date") or row.get("target_date") or "")[:10]
        treatments = context["treatments_by_patient"].get(patient_id, [])
        treatment = _match_treatment_line(
            treatments,
            regimen_code=regimen_code,
            line_start_date=line_start,
        )
        treatment_id = _safe_int(treatment.get("id") if treatment else None, None)
        matched_doses = _match_doses_to_response(
            context["doses_by_patient"].get(patient_id, []),
            regimen_code=regimen_code,
            arpi_label=str(row.get("arpi_agent") or ""),
            cutoff_date=cutoff_date,
        )
        adverse_events = _match_adverse_events_to_window(
            context["adverse_events_by_patient"].get(patient_id, []),
            regimen_code=regimen_code,
            treatment_id=treatment_id,
            start_date=line_start,
            cutoff_date=cutoff_date,
        )
        ctcae_reviews = _match_ctcae_reviews_to_window(
            context["ctcae_reviews_by_patient"].get(patient_id, []),
            regimen_code=regimen_code,
            start_date=line_start,
            cutoff_date=cutoff_date,
        )
        referral = _derive_referral_delay(matched_doses)
        discontinuation = _derive_discontinuation_by_window(
            treatment,
            cutoff_date=cutoff_date,
        )
        toxicity = _derive_toxicity_summary(adverse_events, ctcae_reviews)
        local_dose_dates = _sorted_iso_dates(dose.get("dose_date") for dose in matched_doses)
        priced_local_dose_dates = _sorted_iso_dates(
            dose.get("dose_date")
            for dose in matched_doses
            if (_safe_float(dose.get("estimated_cost_mxn"), None) or 0) > 0
        )
        baseline_state = _baseline_state_for_row(
            row,
            prior_history=context["prior_history_by_patient"].get(patient_id, {}),
            treatment=treatment,
            baseline=context["baseline_by_patient"].get(patient_id, {}),
            identity=context["identity_by_patient"].get(patient_id, {}),
        )
        longitudinal_outcomes = _derive_longitudinal_outcomes(
            row,
            treatment=treatment,
            patient_treatments=treatments,
            patient_events=context["events_by_patient"].get(patient_id, []),
            identity=context["identity_by_patient"].get(patient_id, {}),
            toxicity=toxicity,
            referral=referral,
            cutoff_date=cutoff_date,
        )
        enriched.append(
            {
                **row,
                "molecule": row.get("arpi_agent"),
                "regimen_label": (row.get("regimen_label") or regimen_intensity(regimen_code).get("regimen_label")),
                "baseline_state_bucket": baseline_state["bucket"],
                "baseline_state_components": baseline_state,
                "treatment_history_id": treatment_id,
                "treatment_outcome": treatment.get("outcome") if treatment else "",
                "treatment_end_date": treatment.get("end_date") if treatment else None,
                "discontinued_by_window": discontinuation["discontinued_by_window"],
                "discontinuation_reason": discontinuation["discontinuation_reason"],
                "discontinuation_date": discontinuation["discontinuation_date"],
                "toxicity_event_count_to_window": toxicity["event_count"],
                "max_ctcae_grade_to_window": toxicity["max_ctcae_grade"],
                "high_grade_toxicity_to_window": toxicity["high_grade_toxicity"],
                "dose_modification_toxicity_to_window": toxicity["dose_modification_triggered"],
                "hospitalization_toxicity_to_window": toxicity["hospitalization"],
                "toxicity_review_documented": toxicity["review_documented"],
                "toxicity_absence_documented": toxicity["absence_documented"],
                "toxicity_review_date": toxicity["review_date"],
                "toxicity_review_source": toxicity["review_source"],
                "referral_trigger_date": referral["referral_trigger_date"],
                "referral_critical_date": referral["referral_critical_date"],
                "referral_delay_days": referral["referral_delay_days"],
                "referral_status": referral["referral_status"],
                "local_dose_count_to_window": len(matched_doses),
                "latest_local_dose_number": referral["latest_local_dose_number"],
                "first_local_dose_date_to_window": local_dose_dates[0] if local_dose_dates else None,
                "latest_local_dose_date_to_window": local_dose_dates[-1] if local_dose_dates else None,
                "first_priced_local_dose_date_to_window": (
                    priced_local_dose_dates[0] if priced_local_dose_dates else None
                ),
                **longitudinal_outcomes,
            }
        )
    return enriched


def _summarize_treatment_value_window(
    *,
    weeks: int,
    rows: list[dict[str, Any]],
    include_patient_rows: bool,
) -> dict[str, Any]:
    by_molecule: dict[str, Any] = {}
    by_regimen: dict[str, Any] = {}
    overall_weights = _baseline_bucket_weights(rows)
    for label in ARPI_LABELS:
        by_molecule[label] = _summarize_treatment_value_group(
            label,
            [row for row in rows if row.get("molecule") == label],
            overall_weights=overall_weights,
        )
    regimen_codes = sorted({str(row.get("regimen_code") or "") for row in rows if row.get("regimen_code")})
    for regimen_code in regimen_codes:
        by_regimen[regimen_code] = _summarize_treatment_value_group(
            regimen_code,
            [row for row in rows if row.get("regimen_code") == regimen_code],
            overall_weights=overall_weights,
            group_label=regimen_intensity(regimen_code).get("regimen_label") or regimen_code,
        )
    response_rows = [row for row in rows if row.get("response_evaluable")]
    ecog_rows = [row for row in rows if row.get("ecog_change_from_baseline") is not None]
    psa50_count = sum(1 for row in response_rows if row.get("psa50_response") is True)
    psa90_count = sum(1 for row in response_rows if row.get("psa90_response") is True)
    ecog_improved_count = sum(1 for row in ecog_rows if row.get("ecog_improved") is True)
    total_spend = round(sum(_safe_float(row.get("spend_to_window_mxn"), 0.0) or 0.0 for row in rows), 2)
    summary = {
        "target_weeks": weeks,
        "n_patients": len(rows),
        "n_response_evaluable": len(response_rows),
        "n_ecog_evaluable": len(ecog_rows),
        "baseline_bucket_count": len(overall_weights),
        "total_local_arpi_doses_to_window": sum(_safe_int(row.get("local_dose_count_to_window"), 0) or 0 for row in rows),
        "estimated_spend_to_window_mxn": total_spend,
        "psa50_responder_count": psa50_count,
        "psa90_responder_count": psa90_count,
        "ecog_improved_count": ecog_improved_count,
        "psa50_rate_pct": _rate_pct(psa50_count, len(response_rows)),
        "psa90_rate_pct": _rate_pct(psa90_count, len(response_rows)),
        "ecog_improvement_rate_pct": _rate_pct(ecog_improved_count, len(ecog_rows)),
        "discontinuation_count": sum(1 for row in rows if row.get("discontinued_by_window")),
        "high_grade_toxicity_count": sum(1 for row in rows if row.get("high_grade_toxicity_to_window")),
        "referral_delay_patient_count": sum(1 for row in rows if _safe_int(row.get("referral_delay_days"), 0) and _safe_int(row.get("referral_delay_days"), 0) > 0),
        "discontinuation_rate_pct": _rate_pct(sum(1 for row in rows if row.get("discontinued_by_window")), len(rows)),
        "high_grade_toxicity_rate_pct": _rate_pct(sum(1 for row in rows if row.get("high_grade_toxicity_to_window")), len(rows)),
        "referral_delay_rate_pct": _rate_pct(
            sum(1 for row in rows if _safe_int(row.get("referral_delay_days"), 0) and _safe_int(row.get("referral_delay_days"), 0) > 0),
            len(rows),
        ),
        "bone_event_patient_count": sum(1 for row in rows if row.get("bone_event_to_window")),
        "death_count": sum(1 for row in rows if row.get("death_to_window")),
        "line_change_count": sum(_safe_int(row.get("line_change_count_to_window"), 0) or 0 for row in rows),
        "molecule_count": len({str(row.get("molecule") or "") for row in rows if row.get("molecule")}),
        "regimen_count": len({str(row.get("regimen_code") or "") for row in rows if row.get("regimen_code")}),
        "cost_per_psa50_responder_mxn": round(total_spend / psa50_count, 2) if psa50_count else None,
        "cost_per_psa90_responder_mxn": round(total_spend / psa90_count, 2) if psa90_count else None,
        "cost_per_ecog_improved_patient_mxn": round(total_spend / ecog_improved_count, 2) if ecog_improved_count else None,
        "cost_per_non_responder_mxn": round(total_spend / (len(response_rows) - psa50_count), 2) if len(response_rows) - psa50_count else None,
        "cost_per_referral_delay_patient_mxn": (
            round(total_spend / sum(1 for row in rows if _safe_int(row.get("referral_delay_days"), 0) and _safe_int(row.get("referral_delay_days"), 0) > 0), 2)
            if sum(1 for row in rows if _safe_int(row.get("referral_delay_days"), 0) and _safe_int(row.get("referral_delay_days"), 0) > 0)
            else None
        ),
    }
    payload = {
        "kpi_id": f"treatment_value_registry_{weeks}wk",
        "kpi_label": f"Registro comparativo tratamiento-valor @ {weeks} semanas",
        "target_weeks": weeks,
        "summary": summary,
        "by_molecule": by_molecule,
        "by_regimen": by_regimen,
        "suppression_note": f"Metricas por grupo con n<{MIN_COHORT_N} se marcan como suprimidas.",
    }
    if include_patient_rows:
        payload["patient_rows"] = rows
    return payload


def _summarize_treatment_value_group(
    key: str,
    rows: list[dict[str, Any]],
    *,
    overall_weights: dict[str, float],
    group_label: str | None = None,
) -> dict[str, Any]:
    n = len(rows)
    response_rows = [row for row in rows if row.get("response_evaluable")]
    ecog_rows = [row for row in rows if row.get("ecog_change_from_baseline") is not None]
    psa50_count = sum(1 for row in response_rows if row.get("psa50_response") is True)
    psa90_count = sum(1 for row in response_rows if row.get("psa90_response") is True)
    ecog_improved = sum(1 for row in ecog_rows if row.get("ecog_improved") is True)
    total_spend = round(sum(_safe_float(row.get("spend_to_window_mxn"), 0.0) or 0.0 for row in rows), 2)
    referral_delays = [
        float(row["referral_delay_days"])
        for row in rows
        if _safe_int(row.get("referral_delay_days"), None) is not None
    ]
    return {
        "key": key,
        "label": group_label or key,
        "n": n,
        "suppressed": n < MIN_COHORT_N,
        "display": f"n<{MIN_COHORT_N} suprimido" if n < MIN_COHORT_N else "",
        "n_response_evaluable": len(response_rows),
        "n_ecog_evaluable": len(ecog_rows),
        "total_local_doses_to_window": sum(_safe_int(row.get("local_dose_count_to_window"), 0) or 0 for row in rows),
        "estimated_spend_to_window_mxn": total_spend,
        "psa50_rate": proportion_with_ci(psa50_count, len(response_rows)) if response_rows else {"successes": 0, "denominator": 0, "display": "—"},
        "psa90_rate": proportion_with_ci(psa90_count, len(response_rows)) if response_rows else {"successes": 0, "denominator": 0, "display": "—"},
        "ecog_improvement_rate": proportion_with_ci(ecog_improved, len(ecog_rows)) if ecog_rows else {"successes": 0, "denominator": 0, "display": "—"},
        "discontinuation_rate": proportion_with_ci(sum(1 for row in rows if row.get("discontinued_by_window")), n) if n else {"successes": 0, "denominator": 0, "display": "—"},
        "high_grade_toxicity_rate": proportion_with_ci(sum(1 for row in rows if row.get("high_grade_toxicity_to_window")), n) if n else {"successes": 0, "denominator": 0, "display": "—"},
        "hospitalization_rate": proportion_with_ci(sum(1 for row in rows if row.get("hospitalization_toxicity_to_window")), n) if n else {"successes": 0, "denominator": 0, "display": "—"},
        "bone_event_rate": proportion_with_ci(sum(1 for row in rows if row.get("bone_event_to_window")), n) if n else {"successes": 0, "denominator": 0, "display": "—"},
        "death_rate": proportion_with_ci(sum(1 for row in rows if row.get("death_to_window")), n) if n else {"successes": 0, "denominator": 0, "display": "—"},
        "mean_referral_delay_days": normal_ci_mean(referral_delays) if referral_delays else {"n": 0, "mean": None, "display": "—"},
        "mean_persistence_days": normal_ci_mean([
            float(row.get("line_persistence_days_to_window") or 0)
            for row in rows
            if row.get("line_persistence_days_to_window") is not None
        ]),
        "cost_per_psa50_responder_mxn": round(total_spend / psa50_count, 2) if psa50_count else None,
        "cost_per_psa90_responder_mxn": round(total_spend / psa90_count, 2) if psa90_count else None,
        "cost_per_ecog_improved_patient_mxn": round(total_spend / ecog_improved, 2) if ecog_improved else None,
        "cost_per_non_responder_mxn": round(total_spend / (len(response_rows) - psa50_count), 2) if len(response_rows) - psa50_count else None,
        "adjusted_by_baseline_state": _baseline_adjusted_metrics(rows, overall_weights),
    }


def _normalize_registry_filters(filters: Mapping[str, Any]) -> dict[str, str]:
    """Normalize optional population-dashboard filters without changing rows."""
    molecule = str(filters.get("molecule") or filters.get("arpi_agent") or "").strip().upper()
    regimen = normalize_regimen_code(filters.get("regimen") or filters.get("regimen_code") or "")
    baseline_bucket = str(filters.get("baseline_bucket") or "").strip()
    patient_ref = str(filters.get("patient_ref") or filters.get("nss") or "").strip()
    clinical_state = str(filters.get("clinical_state") or "").strip()
    line_context = str(filters.get("line_context") or "").strip()
    psa_band = str(filters.get("psa_band") or "").strip()
    ecog_band = str(filters.get("ecog_band") or "").strip()
    age_band = str(filters.get("age_band") or "").strip()
    metastatic_volume = str(filters.get("metastatic_volume") or filters.get("volume_disease") or "").strip()
    metric = str(filters.get("metric") or "").strip().lower()
    return {
        "molecule": molecule,
        "regimen": regimen,
        "baseline_bucket": baseline_bucket,
        "patient_ref": patient_ref,
        "clinical_state": clinical_state,
        "line_context": line_context,
        "psa_band": psa_band,
        "ecog_band": ecog_band,
        "age_band": age_band,
        "metastatic_volume": metastatic_volume,
        "metric": metric,
    }


def _filter_treatment_value_rows(
    rows: list[dict[str, Any]],
    filters: Mapping[str, str],
) -> list[dict[str, Any]]:
    if not rows:
        return []
    molecule = filters.get("molecule") or ""
    regimen = filters.get("regimen") or ""
    baseline_bucket = filters.get("baseline_bucket") or ""
    patient_ref = filters.get("patient_ref") or ""
    clinical_state = filters.get("clinical_state") or ""
    line_context = filters.get("line_context") or ""
    psa_band = filters.get("psa_band") or ""
    ecog_band = filters.get("ecog_band") or ""
    age_band = filters.get("age_band") or ""
    metastatic_volume = filters.get("metastatic_volume") or ""
    metric = filters.get("metric") or ""
    filtered: list[dict[str, Any]] = []
    for row in rows:
        components = row.get("baseline_state_components") or {}
        if molecule and str(row.get("molecule") or row.get("arpi_agent") or "").upper() != molecule:
            continue
        if regimen and normalize_regimen_code(row.get("regimen_code")) != regimen:
            continue
        if baseline_bucket and str(row.get("baseline_state_bucket") or "") != baseline_bucket:
            continue
        if patient_ref and patient_ref.lower() not in str(row.get("patient_ref") or "").lower():
            continue
        if clinical_state and str(components.get("clinical_state") or "") != clinical_state:
            continue
        if line_context and str(components.get("line_context") or "") != line_context:
            continue
        if psa_band and str(components.get("psa_band") or "") != psa_band:
            continue
        if ecog_band and str(components.get("ecog_band") or "") != ecog_band:
            continue
        if age_band and str(components.get("age_band") or "") != age_band:
            continue
        if metastatic_volume and str(components.get("metastatic_volume") or "") != metastatic_volume:
            continue
        if metric and not _row_matches_metric_filter(row, metric):
            continue
        filtered.append(row)
    return filtered


def _build_research_pack_dictionary() -> list[dict[str, Any]]:
    return [
        {
            "field": field,
            "label": label,
            "type": field_type,
            "source": source,
            "definition": definition,
        }
        for field, label, field_type, source, definition in RESEARCH_PACK_DATA_DICTIONARY
    ]


def _research_pack_cohort_label(filters: Mapping[str, str], weeks_list: tuple[int, ...]) -> str:
    parts = []
    if filters.get("molecule"):
        parts.append(str(filters["molecule"]))
    if filters.get("regimen"):
        parts.append(str(filters["regimen"]))
    if filters.get("clinical_state"):
        parts.append(str(filters["clinical_state"]))
    if filters.get("metric"):
        parts.append(f"metrica:{filters['metric']}")
    if filters.get("patient_ref"):
        parts.append(f"paciente:{filters['patient_ref']}")
    if not parts:
        parts.append("cohorte ARPI completa")
    return " · ".join(parts) + f" · ventanas {','.join(str(item) for item in weeks_list)} semanas"


def _research_pack_grade(governance: Mapping[str, Any], completeness: Mapping[str, Any]) -> str:
    status = str(governance.get("status") or "")
    completeness_pct = _safe_float(completeness.get("overall_completeness_pct"), None)
    if status == "poster_or_manuscript_ready":
        return "lista_para_poster_articulo"
    if status == "auditable_exploratory" and completeness_pct is not None and completeness_pct >= 75:
        return "auditable_exploratoria"
    if completeness_pct is not None and completeness_pct >= 50:
        return "requiere_captura_antes_de_inferencia"
    return "insuficiente_para_investigacion"


def _select_primary_command_window(windows: Mapping[str, Any]) -> str:
    numeric_keys = sorted([int(key) for key in windows if str(key).isdigit()])
    with_patients = [
        key for key in numeric_keys
        if (((windows.get(str(key)) or {}).get("summary") or {}).get("n_patients") or 0) > 0
    ]
    if with_patients:
        return str(max(with_patients))
    return str(max(numeric_keys)) if numeric_keys else ""


def _build_command_center_capture_impact(
    *,
    weeks_list: tuple[int, ...],
    real_only: bool,
    filters: Mapping[str, Any],
    source_freeze_key: str | None = None,
) -> dict[str, Any]:
    patient_ref = str((filters or {}).get("patient_ref") or (filters or {}).get("nss") or "").strip()
    if not patient_ref:
        return {
            "available": False,
            "version": TREATMENT_VALUE_CAPTURE_IMPACT_VERSION,
            "source_mode": "patient_filter_required",
            "clinical_message": (
                "Seleccione un paciente para ver como sus capturas APE/ECOG/dosis "
                "mueven el tablero epidemiologico sin recaptura."
            ),
            "read_only_impact_model": True,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
            "external_transfer_performed": False,
        }
    if source_freeze_key:
        return {
            "available": False,
            "version": TREATMENT_VALUE_CAPTURE_IMPACT_VERSION,
            "patient_ref": patient_ref,
            "source_mode": "disabled_for_freeze_bound_view",
            "clinical_message": (
                "El delta post-captura se calcula sobre cohorte viva; esta vista esta "
                "ligada a un freeze gobernado y no mezcla datos nuevos."
            ),
            "read_only_impact_model": True,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
            "external_transfer_performed": False,
        }
    return {
        **build_treatment_value_capture_impact(
            patient_ref,
            weeks_list=weeks_list,
            real_only=real_only,
            filters=filters,
            trace_limit=20,
        ),
        "source_mode": "live_capture_delta",
    }


def _build_command_center_kpis(
    registry: Mapping[str, Any],
    primary_window: str,
    capture_impact: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    windows = registry.get("windows") or {}
    primary = (windows.get(str(primary_window)) or {}).get("summary") or {}
    completeness = registry.get("completeness_tower") or {}
    governance = registry.get("research_governance") or {}
    worklist = registry.get("capture_worklist") or {}
    economics = _build_command_center_economic_layer(registry, primary_window)
    longitudinal = registry.get("longitudinal_outcomes") or {}
    persistence = longitudinal.get("line_persistence_days") or {}
    impact_after = (capture_impact or {}).get("after") or {}
    operational = registry.get("operational_gap_latency") or {}
    operational_summary = operational.get("summary") or {}
    return [
        {
            "key": "primary_patients",
            "label": f"Pacientes @{primary_window or '-'} sem",
            "value": primary.get("n_patients", 0),
            "subvalue": f"{primary.get('n_response_evaluable', 0)} evaluables respuesta",
            "status": "neutral",
        },
        {
            "key": "psa50_psa90",
            "label": "PSA50 / PSA90",
            "value": f"{primary.get('psa50_rate_pct')}% / {primary.get('psa90_rate_pct')}%",
            "subvalue": f"{primary.get('psa50_responder_count', 0)} / {primary.get('psa90_responder_count', 0)} respondedores",
            "status": "clinical",
        },
        {
            "key": "completeness",
            "label": "Completitud epidemiologica",
            "value": completeness.get("overall_completeness_pct"),
            "unit": "%",
            "subvalue": completeness.get("status"),
            "status": completeness.get("status"),
        },
        {
            "key": "open_gaps",
            "label": "Brechas accionables",
            "value": worklist.get("open_gap_count", 0),
            "subvalue": f"{worklist.get('patient_count_with_gaps', 0)} pacientes",
            "status": "warning" if worklist.get("open_gap_count") else "good",
        },
        {
            "key": "spend",
            "label": "Gasto estimado",
            "value": economics.get("estimated_spend_mxn"),
            "unit": "MXN",
            "subvalue": f"{economics.get('priced_doses', 0)} dosis costeadas",
            "status": "economic",
        },
        {
            "key": "cost_per_psa50",
            "label": "Costo / PSA50",
            "value": economics.get("cost_per_psa50_responder_mxn"),
            "unit": "MXN",
            "subvalue": "respondedor bioquimico",
            "status": "economic",
        },
        {
            "key": "persistence",
            "label": "Persistencia terapeutica",
            "value": persistence.get("mean"),
            "unit": "dias",
            "subvalue": f"n={persistence.get('n', 0)}",
            "status": "longitudinal",
        },
        {
            "key": "capture_impact",
            "label": "Impacto post-captura",
            "value": "Si" if impact_after.get("patient_contributes_to_registry") else "No",
            "subvalue": (
                f"{impact_after.get('active_window_count', 0)} ventanas activas"
                if (capture_impact or {}).get("available")
                else (capture_impact or {}).get("source_mode") or "seleccione paciente"
            ),
            "status": "good" if impact_after.get("patient_contributes_to_registry") else "warning",
        },
        {
            "key": "operational_latency",
            "label": "Latencia dato util",
            "value": operational_summary.get("median_days_to_close"),
            "unit": "dias",
            "subvalue": (
                f"{operational_summary.get('closed_domain_count', 0)}/"
                f"{operational_summary.get('eligible_domain_count', 0)} dominios cerrados"
            ),
            "status": operational_summary.get("status") or "no_data",
        },
        {
            "key": "research_grade",
            "label": "Gobernanza",
            "value": governance.get("status") or "sin clasificar",
            "subvalue": f"real={governance.get('real_patient_count', 0)} / total={governance.get('patient_count', 0)}",
            "status": "governance",
        },
    ]


def _build_command_center_outcome_matrix(registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    matrix = []
    for week in sorted([int(key) for key in (registry.get("windows") or {}) if str(key).isdigit()]):
        summary = (((registry.get("windows") or {}).get(str(week)) or {}).get("summary") or {})
        matrix.append(
            {
                "week": week,
                "n_patients": summary.get("n_patients", 0),
                "psa50_rate_pct": summary.get("psa50_rate_pct"),
                "psa90_rate_pct": summary.get("psa90_rate_pct"),
                "ecog_improvement_rate_pct": summary.get("ecog_improvement_rate_pct"),
                "discontinuation_rate_pct": summary.get("discontinuation_rate_pct"),
                "high_grade_toxicity_rate_pct": summary.get("high_grade_toxicity_rate_pct"),
                "referral_delay_rate_pct": summary.get("referral_delay_rate_pct"),
                "estimated_spend_to_window_mxn": summary.get("estimated_spend_to_window_mxn"),
                "cost_per_psa50_responder_mxn": summary.get("cost_per_psa50_responder_mxn"),
            }
        )
    return matrix


def _build_command_center_comparison_panel(registry: Mapping[str, Any], primary_window: str) -> dict[str, Any]:
    window = ((registry.get("windows") or {}).get(str(primary_window)) or {})
    return {
        "primary_window_weeks": _safe_int(primary_window, None),
        "by_molecule": window.get("by_molecule") or {},
        "by_regimen": window.get("by_regimen") or {},
        "cohort_matrix": registry.get("cohort_matrix") or [],
        "adjustment_method": registry.get("baseline_adjustment_method"),
        "interpretation_guardrail": (
            "Comparacion ajustada visible por bucket basal; no declarar superioridad causal "
            "sin N real suficiente, completitud alta y control de confusores."
        ),
    }


def _build_command_center_economic_layer(registry: Mapping[str, Any], primary_window: str) -> dict[str, Any]:
    primary = (((registry.get("windows") or {}).get(str(primary_window)) or {}).get("summary") or {})
    fallback = registry.get("economic_layer") or {}
    if not primary.get("n_patients"):
        return dict(fallback)
    return {
        "version": "institutional_economic_layer_v2",
        "primary_window_weeks": _safe_int(primary_window, None),
        "estimated_spend_mxn": primary.get("estimated_spend_to_window_mxn"),
        "local_doses": primary.get("total_local_arpi_doses_to_window", fallback.get("local_doses", 0)),
        "priced_doses": fallback.get("priced_doses", 0),
        "partial_cost_patient_count": fallback.get("partial_cost_patient_count", 0),
        "stale_price_patient_count": fallback.get("stale_price_patient_count", 0),
        "cost_per_psa50_responder_mxn": primary.get("cost_per_psa50_responder_mxn"),
        "cost_per_ecog_improved_patient_mxn": primary.get("cost_per_ecog_improved_patient_mxn"),
        "cost_per_non_responder_mxn": primary.get("cost_per_non_responder_mxn"),
        "cost_per_referral_delay_patient_mxn": primary.get("cost_per_referral_delay_patient_mxn"),
        "audit_note": (
            "Capa economica anclada a la ventana primaria con pacientes; la matriz conserva "
            "ventanas futuras vacias sin borrar el costo ya trazable."
        ),
    }


def _build_causal_readiness_summary(registry: Mapping[str, Any]) -> dict[str, Any]:
    governance = registry.get("research_governance") or {}
    completeness = registry.get("completeness_tower") or {}
    domains = completeness.get("domains") or []
    confounder_keys = {"baseline_psa", "baseline_ecog", "treatment_line", "metastatic_context", "comorbidity"}
    confounder_domains = [item for item in domains if item.get("key") in confounder_keys]
    weak_confounders = [
        item for item in confounder_domains
        if item.get("coverage_pct") is None or float(item.get("coverage_pct") or 0) < 80
    ]
    real_count = _safe_int(governance.get("real_patient_count"), 0) or 0
    completeness_pct = _safe_float(completeness.get("overall_completeness_pct"), None)
    if real_count >= 50 and completeness_pct is not None and completeness_pct >= 85 and not weak_confounders:
        status = "propensity_ready_candidate"
        next_step = "Preespecificar propensity score / inverse probability weighting."
    elif real_count >= MIN_COHORT_N and completeness_pct is not None and completeness_pct >= 70:
        status = "adjusted_exploratory_ready"
        next_step = "Mantener ajuste por bucket basal y cerrar confusores <80%."
    else:
        status = "descriptive_only"
        next_step = "Completar cohorte real, APE/ECOG basal, carga metastasica y comorbilidad antes de inferencia."
    return {
        "version": "causal_readiness_v2",
        "status": status,
        "real_patient_count": real_count,
        "overall_completeness_pct": completeness_pct,
        "confounder_domains": confounder_domains,
        "weak_confounders": weak_confounders,
        "next_step": next_step,
    }


def _load_recent_research_freezes(*, limit: int) -> list[dict[str, Any]]:
    try:
        import tracking_db

        return tracking_db.list_research_cohort_freezes(limit=limit)
    except Exception:
        return []


def _build_treatment_value_filter_options(rows_by_week: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    all_rows = [row for rows in rows_by_week.values() for row in rows]
    molecules = sorted({str(row.get("molecule") or row.get("arpi_agent") or "") for row in all_rows if row.get("molecule") or row.get("arpi_agent")})
    regimen_map: dict[str, str] = {}
    baseline_map: dict[str, dict[str, Any]] = {}
    patient_refs = set()
    clinical_states = Counter()
    line_contexts = Counter()
    psa_bands = Counter()
    ecog_bands = Counter()
    age_bands = Counter()
    metastatic_volumes = Counter()
    for row in all_rows:
        components = row.get("baseline_state_components") or {}
        regimen_code = normalize_regimen_code(row.get("regimen_code"))
        if regimen_code:
            regimen_map.setdefault(regimen_code, row.get("regimen_label") or regimen_intensity(regimen_code).get("regimen_label") or regimen_code)
        bucket = str(row.get("baseline_state_bucket") or "")
        if bucket:
            baseline_map.setdefault(
                bucket,
                {
                    "bucket": bucket,
                    "clinical_state": (row.get("baseline_state_components") or {}).get("clinical_state") or "",
                    "line_context": (row.get("baseline_state_components") or {}).get("line_context") or "",
                    "psa_band": (row.get("baseline_state_components") or {}).get("psa_band") or "",
                    "ecog_band": (row.get("baseline_state_components") or {}).get("ecog_band") or "",
                    "n": 0,
                },
            )
            baseline_map[bucket]["n"] += 1
        if row.get("patient_ref"):
            patient_refs.add(str(row.get("patient_ref")))
        for value, counter in (
            (components.get("clinical_state"), clinical_states),
            (components.get("line_context"), line_contexts),
            (components.get("psa_band"), psa_bands),
            (components.get("ecog_band"), ecog_bands),
            (components.get("age_band"), age_bands),
            (components.get("metastatic_volume"), metastatic_volumes),
        ):
            if value:
                counter[str(value)] += 1
    return {
        "molecules": molecules,
        "regimens": [
            {"code": code, "label": label}
            for code, label in sorted(regimen_map.items(), key=lambda item: item[1])
        ],
        "baseline_buckets": sorted(baseline_map.values(), key=lambda item: (-item["n"], item["bucket"])),
        "patient_refs": sorted(patient_refs),
        "clinical_states": _counter_options(clinical_states),
        "line_contexts": _counter_options(line_contexts),
        "psa_bands": _counter_options(psa_bands),
        "ecog_bands": _counter_options(ecog_bands),
        "age_bands": _counter_options(age_bands),
        "metastatic_volumes": _counter_options(metastatic_volumes),
        "metrics": [
            {"code": "psa50", "label": "PSA50"},
            {"code": "psa90", "label": "PSA90"},
            {"code": "non_response", "label": "Sin PSA50"},
            {"code": "ecog_improved", "label": "ECOG mejoro"},
            {"code": "toxicity_g3", "label": "Toxicidad G3+"},
            {"code": "hospitalization", "label": "Hospitalizacion"},
            {"code": "referral_delay", "label": "Retraso referencia"},
            {"code": "discontinuation", "label": "Discontinuacion"},
            {"code": "bone_event", "label": "Evento oseo"},
            {"code": "death", "label": "Defuncion"},
        ],
        "windows": sorted([int(key) for key in rows_by_week.keys() if str(key).isdigit()]),
    }


def _counter_options(counter: Counter) -> list[dict[str, Any]]:
    return [
        {"code": key, "label": key, "n": count}
        for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def _build_cohort_builder_descriptor(
    raw_rows_by_week: Mapping[str, list[dict[str, Any]]],
    filters: Mapping[str, str],
) -> dict[str, Any]:
    all_rows = [row for rows in raw_rows_by_week.values() for row in rows]
    unique_patients = {str(row.get("patient_ref") or row.get("patient_id") or "") for row in all_rows}
    unique_patients.discard("")
    return {
        "version": "cohort_builder_v2",
        "mode": "read_only_dynamic",
        "active_filters": dict(filters),
        "source_windows": sorted([int(key) for key in raw_rows_by_week.keys() if str(key).isdigit()]),
        "source_row_count": len(all_rows),
        "source_patient_count": len(unique_patients),
        "supported_filters": [
            "molecule",
            "regimen",
            "clinical_state",
            "line_context",
            "psa_band",
            "ecog_band",
            "age_band",
            "metastatic_volume",
            "baseline_bucket",
            "metric",
            "patient_ref",
            "real_only",
        ],
        "audit_note": "Constructor dinamico; no crea ni muta cohortes persistidas en v2.",
    }


def _build_treatment_value_cohort_matrix(windows: Mapping[str, Any]) -> list[dict[str, Any]]:
    matrix: dict[tuple[str, str, str], dict[str, Any]] = {}
    for week, payload in windows.items():
        for group_type, groups in (("molecule", payload.get("by_molecule") or {}), ("regimen", payload.get("by_regimen") or {})):
            for key, summary in groups.items():
                if not summary or summary.get("n", 0) == 0:
                    continue
                row_key = (group_type, str(key), str(summary.get("label") or key))
                item = matrix.setdefault(
                    row_key,
                    {
                        "group_type": group_type,
                        "key": str(key),
                        "label": str(summary.get("label") or key),
                        "windows": {},
                    },
                )
                item["windows"][str(week)] = {
                    "n": summary.get("n", 0),
                    "psa50_rate": summary.get("psa50_rate", {}).get("display"),
                    "psa90_rate": summary.get("psa90_rate", {}).get("display"),
                    "ecog_improvement_rate": summary.get("ecog_improvement_rate", {}).get("display"),
                    "discontinuation_rate": summary.get("discontinuation_rate", {}).get("display"),
                    "high_grade_toxicity_rate": summary.get("high_grade_toxicity_rate", {}).get("display"),
                    "cost_per_psa50_responder_mxn": summary.get("cost_per_psa50_responder_mxn"),
                    "adjusted_psa50_rate": (
                        summary.get("adjusted_by_baseline_state", {})
                        .get("metrics", {})
                        .get("psa50_rate", {})
                        .get("display")
                    ),
                    "suppressed": summary.get("suppressed"),
                }
    return sorted(matrix.values(), key=lambda item: (item["group_type"], item["label"]))


def _same_patient_ref(left: Any, right: Any) -> bool:
    return str(left or "").strip().lower() == str(right or "").strip().lower()


def _capture_window_delta(
    *,
    weeks: int,
    patient_ref: str,
    cohort_rows: list[dict[str, Any]],
    patient_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    without_rows = [
        row for row in cohort_rows
        if not _same_patient_ref(row.get("patient_ref"), patient_ref)
    ]
    cohort_summary = _summarize_capture_rows(cohort_rows)
    without_summary = _summarize_capture_rows(without_rows)
    contribution = _summarize_capture_rows(patient_rows)
    return {
        "target_weeks": weeks,
        "patient_contributes": bool(patient_rows),
        "cohort_with_patient": cohort_summary,
        "cohort_without_patient": without_summary,
        "patient_contribution": contribution,
        "population_delta": _capture_summary_delta(without_summary, cohort_summary),
        "patient_delta": contribution,
        "patient_metric_flags": _capture_patient_metric_flags(patient_rows),
        "patient_regimens": sorted({str(row.get("regimen_code") or "") for row in patient_rows if row.get("regimen_code")}),
        "patient_molecules": sorted({str(row.get("molecule") or row.get("arpi_agent") or "") for row in patient_rows if row.get("molecule") or row.get("arpi_agent")}),
    }


def _summarize_capture_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    patient_refs = {str(row.get("patient_ref") or "") for row in rows if row.get("patient_ref")}
    response_rows = [row for row in rows if row.get("response_evaluable")]
    ecog_rows = [row for row in rows if row.get("ecog_change_from_baseline") is not None]
    psa50_count = sum(1 for row in response_rows if row.get("psa50_response") is True)
    psa90_count = sum(1 for row in response_rows if row.get("psa90_response") is True)
    ecog_improved = sum(1 for row in ecog_rows if row.get("ecog_improved") is True)
    spend = round(sum(_safe_float(row.get("spend_to_window_mxn"), 0.0) or 0.0 for row in rows), 2)
    local_doses = sum(_safe_int(row.get("local_dose_count_to_window"), 0) or 0 for row in rows)
    priced_doses = sum(_safe_int(row.get("priced_local_dose_count"), 0) or 0 for row in rows)
    return {
        "patient_count": len(patient_refs),
        "row_count": len(rows),
        "response_evaluable_count": len(response_rows),
        "ecog_evaluable_count": len(ecog_rows),
        "psa50_responder_count": psa50_count,
        "psa90_responder_count": psa90_count,
        "ecog_improved_count": ecog_improved,
        "estimated_spend_mxn": spend,
        "local_dose_count": local_doses,
        "priced_dose_count": priced_doses,
        "high_grade_toxicity_count": sum(1 for row in rows if row.get("high_grade_toxicity_to_window") is True),
        "hospitalization_count": sum(1 for row in rows if row.get("hospitalization_toxicity_to_window") is True),
        "referral_delay_patient_count": sum(1 for row in rows if _safe_int(row.get("referral_delay_days"), 0) and _safe_int(row.get("referral_delay_days"), 0) > 0),
        "discontinuation_count": sum(1 for row in rows if row.get("discontinued_by_window") is True),
        "bone_event_count": sum(1 for row in rows if row.get("bone_event_to_window") is True),
        "death_count": sum(1 for row in rows if row.get("death_to_window") is True),
        "psa50_rate_pct": _rate_pct(psa50_count, len(response_rows)),
        "psa90_rate_pct": _rate_pct(psa90_count, len(response_rows)),
        "ecog_improvement_rate_pct": _rate_pct(ecog_improved, len(ecog_rows)),
        "cost_per_psa50_responder_mxn": round(spend / psa50_count, 2) if psa50_count else None,
    }


def _capture_snapshot_summary(windows: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    active = [
        (int(week), payload)
        for week, payload in windows.items()
        if str(week).isdigit() and payload.get("patient_contributes")
    ]
    if not active:
        return {
            "patient_contributes_to_registry": False,
            "active_window_count": 0,
            "primary_window_weeks": None,
            "row_count": 0,
            "response_evaluable_count": 0,
            "estimated_spend_mxn": 0.0,
            "local_dose_count": 0,
            "psa50_responder_count": 0,
            "psa90_responder_count": 0,
            "ecog_improved_count": 0,
        }
    primary_week, primary = max(active, key=lambda item: item[0])
    contribution = dict(primary.get("patient_contribution") or {})
    return {
        "patient_contributes_to_registry": True,
        "active_window_count": len(active),
        "active_windows": [week for week, _payload in active],
        "primary_window_weeks": primary_week,
        "row_count": contribution.get("row_count", 0),
        "response_evaluable_count": contribution.get("response_evaluable_count", 0),
        "estimated_spend_mxn": contribution.get("estimated_spend_mxn", 0.0),
        "local_dose_count": contribution.get("local_dose_count", 0),
        "priced_dose_count": contribution.get("priced_dose_count", 0),
        "psa50_responder_count": contribution.get("psa50_responder_count", 0),
        "psa90_responder_count": contribution.get("psa90_responder_count", 0),
        "ecog_improved_count": contribution.get("ecog_improved_count", 0),
        "high_grade_toxicity_count": contribution.get("high_grade_toxicity_count", 0),
        "referral_delay_patient_count": contribution.get("referral_delay_patient_count", 0),
        "discontinuation_count": contribution.get("discontinuation_count", 0),
    }


def _capture_summary_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    numeric_keys = [
        "patient_count",
        "active_window_count",
        "row_count",
        "response_evaluable_count",
        "estimated_spend_mxn",
        "local_dose_count",
        "priced_dose_count",
        "psa50_responder_count",
        "psa90_responder_count",
        "ecog_improved_count",
        "high_grade_toxicity_count",
        "referral_delay_patient_count",
        "discontinuation_count",
    ]
    delta: dict[str, Any] = {}
    for key in numeric_keys:
        before_value = _safe_float(before.get(key), 0.0) or 0.0
        after_value = _safe_float(after.get(key), 0.0) or 0.0
        diff = round(after_value - before_value, 2)
        delta[f"{key}_delta"] = diff
    before_contributes = bool(before.get("patient_contributes_to_registry"))
    after_contributes = bool(after.get("patient_contributes_to_registry"))
    delta["new_registry_contribution"] = (not before_contributes) and after_contributes
    delta["lost_registry_contribution"] = before_contributes and not after_contributes
    return delta


def _capture_patient_metric_flags(rows: list[dict[str, Any]]) -> list[str]:
    flags: set[str] = set()
    for row in rows:
        if row.get("response_evaluable"):
            flags.add("response_evaluable")
        if row.get("psa50_response") is True:
            flags.add("PSA50")
        if row.get("psa90_response") is True:
            flags.add("PSA90")
        if row.get("ecog_improved") is True:
            flags.add("ECOG_mejoro")
        if row.get("high_grade_toxicity_to_window") is True:
            flags.add("toxicidad_G3")
        if row.get("discontinued_by_window") is True:
            flags.add("discontinuacion")
        if _safe_int(row.get("referral_delay_days"), 0) and _safe_int(row.get("referral_delay_days"), 0) > 0:
            flags.add("retraso_referencia")
    return sorted(flags)


def _capture_impact_message(after_summary: Mapping[str, Any], capture_worklist: Mapping[str, Any]) -> str:
    if not after_summary.get("patient_contributes_to_registry"):
        return (
            "El paciente aun no contribuye al registro tratamiento-valor; faltan ventana ARPI "
            "o datos longitudinales suficientes."
        )
    if _safe_int(capture_worklist.get("open_gap_count"), 0):
        return (
            "El paciente ya contribuye al registro, pero conserva brechas epidemiologicas "
            "accionables antes de usarlo para inferencia."
        )
    return "El paciente contribuye al registro tratamiento-valor V2 con trazabilidad completa para la cohorte filtrada."


def _build_patient_metric_trace(
    rows_by_week: Mapping[str, list[dict[str, Any]]],
    *,
    trace_limit: int,
) -> list[dict[str, Any]]:
    trace_rows: list[dict[str, Any]] = []
    for week, rows in rows_by_week.items():
        for row in rows:
            metric_flags = []
            if row.get("psa50_response") is True:
                metric_flags.append("PSA50")
            if row.get("psa90_response") is True:
                metric_flags.append("PSA90")
            if row.get("ecog_improved") is True:
                metric_flags.append("ECOG mejoro")
            if row.get("high_grade_toxicity_to_window") is True:
                metric_flags.append("Toxicidad G3+")
            if row.get("discontinued_by_window") is True:
                metric_flags.append("Discontinuacion")
            if _safe_int(row.get("referral_delay_days"), 0) and _safe_int(row.get("referral_delay_days"), 0) > 0:
                metric_flags.append("Retraso referencia")
            patient_ref = str(row.get("patient_ref") or "")
            trace_rows.append(
                {
                    "week": _safe_int(week, None),
                    "patient_id": row.get("patient_id"),
                    "patient_ref": patient_ref,
                    "patient_name": row.get("patient_name"),
                    "profile_url": f"/patient_profile/{patient_ref}?v=2" if patient_ref else "",
                    "molecule": row.get("molecule") or row.get("arpi_agent"),
                    "regimen_code": row.get("regimen_code"),
                    "regimen_label": row.get("regimen_label"),
                    "baseline_state_bucket": row.get("baseline_state_bucket"),
                    "baseline_state_components": row.get("baseline_state_components") or {},
                    "baseline_psa": row.get("baseline_psa"),
                    "actual_psa": row.get("actual_psa"),
                    "psa_decline_pct": row.get("psa_decline_pct"),
                    "psa50_response": row.get("psa50_response"),
                    "psa90_response": row.get("psa90_response"),
                    "baseline_ecog": row.get("baseline_ecog"),
                    "baseline_ecog_date": row.get("baseline_ecog_date"),
                    "actual_ecog": row.get("actual_ecog"),
                    "actual_ecog_date": row.get("actual_ecog_date"),
                    "ecog_evidence_quality": row.get("ecog_evidence_quality"),
                    "ecog_change_from_baseline": row.get("ecog_change_from_baseline"),
                    "first_local_dose_date_to_window": row.get("first_local_dose_date_to_window"),
                    "first_priced_local_dose_date_to_window": row.get("first_priced_local_dose_date_to_window"),
                    "latest_local_dose_date_to_window": row.get("latest_local_dose_date_to_window"),
                    "spend_to_window_mxn": row.get("spend_to_window_mxn"),
                    "cost_per_pct_psa_decline_mxn": row.get("cost_per_pct_psa_decline_mxn"),
                    "toxicity_event_count_to_window": row.get("toxicity_event_count_to_window"),
                    "max_ctcae_grade_to_window": row.get("max_ctcae_grade_to_window"),
                    "toxicity_review_documented": row.get("toxicity_review_documented"),
                    "toxicity_absence_documented": row.get("toxicity_absence_documented"),
                    "toxicity_review_date": row.get("toxicity_review_date"),
                    "toxicity_review_source": row.get("toxicity_review_source"),
                    "referral_status": row.get("referral_status"),
                    "referral_delay_days": row.get("referral_delay_days"),
                    "discontinued_by_window": row.get("discontinued_by_window"),
                    "time_to_psa_progression_days": row.get("time_to_psa_progression_days"),
                    "time_to_discontinuation_days": row.get("time_to_discontinuation_days"),
                    "line_persistence_days_to_window": row.get("line_persistence_days_to_window"),
                    "line_change_count_to_window": row.get("line_change_count_to_window"),
                    "hospitalization_toxicity_to_window": row.get("hospitalization_toxicity_to_window"),
                    "bone_event_to_window": row.get("bone_event_to_window"),
                    "death_to_window": row.get("death_to_window"),
                    "evidence_quality": row.get("evidence_quality"),
                    "metric_flags": metric_flags,
                    "is_synthetic": row.get("is_synthetic"),
                }
            )
    trace_rows = sorted(
        trace_rows,
        key=lambda item: (
            str(item.get("patient_ref") or ""),
            int(item.get("week") or 0),
            str(item.get("regimen_code") or ""),
        ),
    )
    if trace_limit <= 0:
        return trace_rows
    return trace_rows[:trace_limit]


def _build_epidemiology_completeness_tower(rows_by_week: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rows = _latest_window_rows(rows_by_week)
    specs = [
        ("identity", "Identidad/NSS", lambda r: bool(r.get("patient_ref"))),
        ("baseline_psa", "APE basal", lambda r: r.get("baseline_psa") is not None),
        ("response_psa", "APE ventana", lambda r: r.get("actual_psa") is not None and r.get("psa_decline_pct") is not None),
        ("baseline_ecog", "ECOG basal", lambda r: r.get("baseline_ecog") is not None),
        ("actual_ecog", "ECOG ventana", lambda r: r.get("actual_ecog") is not None),
        ("treatment_line", "Linea/regimen", lambda r: bool(r.get("regimen_code") and r.get("line_start_date"))),
        ("dose_trace", "Dosis locales", lambda r: _safe_int(r.get("local_dose_count_to_window"), 0) > 0),
        ("cost_trace", "Costo trazable", lambda r: _safe_float(r.get("spend_to_window_mxn"), 0.0) > 0),
        ("toxicity_review", "Toxicidad CTCAE", lambda r: r.get("toxicity_review_documented") is True),
        ("discontinuation", "Discontinuacion/persistencia", lambda r: r.get("line_persistence_days_to_window") is not None),
        ("referral_signal", "Referencia HGZ/HGR", lambda r: r.get("referral_status") not in (None, "")),
        ("survival", "Estado vital/contacto", lambda r: r.get("survival_status_available") is True),
        ("metastatic_context", "Carga metastasica", lambda r: (r.get("baseline_state_components") or {}).get("metastatic_volume") not in ("volume_unknown", "", None)),
        ("comorbidity", "Comorbilidad basal", lambda r: (r.get("baseline_state_components") or {}).get("comorbidity_band") not in ("comorbidity_unknown", "", None)),
    ]
    domains = []
    gaps: list[dict[str, Any]] = []
    for key, label, predicate in specs:
        present = sum(1 for row in rows if predicate(row))
        pct_value = _rate_pct(present, len(rows))
        domains.append({
            "key": key,
            "label": label,
            "present": present,
            "total": len(rows),
            "coverage_pct": pct_value,
            "status": _coverage_status(pct_value),
        })
        if pct_value is not None and pct_value < 80:
            missing_refs = [row.get("patient_ref") for row in rows if not predicate(row)][:10]
            gaps.append({
                "key": key,
                "label": label,
                "coverage_pct": pct_value,
                "missing_patient_refs": missing_refs,
            })
    total_present = sum(item["present"] for item in domains)
    total_possible = sum(item["total"] for item in domains)
    overall = round((total_present / total_possible) * 100, 1) if total_possible else None
    return {
        "version": "epidemiology_completeness_tower_v2",
        "patient_count": len(rows),
        "overall_completeness_pct": overall,
        "status": _coverage_status(overall),
        "domains": domains,
        "critical_gaps": gaps[:8],
        "audit_note": "Cobertura calculada sobre la ventana activa mas tardia disponible; no interpreta ausencias como eventos negativos.",
    }


def _build_operational_gap_latency_summary(
    rows_by_week: Mapping[str, list[dict[str, Any]]],
    capture_worklist: Mapping[str, Any],
) -> dict[str, Any]:
    """Derived V2 view of how quickly registry gaps become useful data."""
    rows = _latest_window_rows(rows_by_week)
    if not rows:
        return {
            "version": "operational_gap_latency_v1",
            "status": "no_data",
            "summary": {
                "patient_count": 0,
                "eligible_domain_count": 0,
                "closed_domain_count": 0,
                "open_domain_count": 0,
                "median_days_to_close": None,
                "p90_days_to_close": None,
                "open_gap_count": 0,
            },
            "domains": [],
            "audit_note": "Sin filas en ventana activa; no se derivan latencias.",
            "read_only_impact_model": True,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
        }

    row_by_patient_week = {
        (str(row.get("patient_ref") or ""), _safe_int(row.get("target_weeks") or row.get("week"), None)): row
        for row in rows
        if row.get("patient_ref")
    }
    domains: list[dict[str, Any]] = []

    def append_domain(
        *,
        key: str,
        label: str,
        eligible_count: int,
        closed_count: int,
        latency_days: list[int | None],
        date_policy: str,
        source: str,
        open_count: int | None = None,
        warning: str = "",
    ) -> None:
        clean_latencies = [
            int(value) for value in latency_days
            if value is not None and int(value) >= 0
        ]
        open_value = max(eligible_count - closed_count, 0) if open_count is None else max(int(open_count), 0)
        coverage_pct = _rate_pct(closed_count, eligible_count)
        stats = _latency_stats(clean_latencies)
        if not eligible_count:
            status = "not_applicable"
        elif open_value:
            status = "open_gaps"
        elif stats["p90_days"] is not None and stats["p90_days"] > 14:
            status = "slow_closure"
        else:
            status = "operational_ready"
        domains.append(
            {
                "key": key,
                "label": label,
                "eligible_count": eligible_count,
                "closed_count": closed_count,
                "open_count": open_value,
                "coverage_pct": coverage_pct,
                "median_days_to_close": stats["median_days"],
                "p90_days_to_close": stats["p90_days"],
                "max_days_to_close": stats["max_days"],
                "latency_observation_count": len(clean_latencies),
                "status": status,
                "date_policy": date_policy,
                "source": source,
                "warning": warning,
            }
        )

    append_domain(
        key="psa_response_window",
        label="APE util en ventana",
        eligible_count=len(rows),
        closed_count=sum(1 for row in rows if row.get("actual_psa_date")),
        latency_days=[
            _nonnegative_days_between(row.get("target_date"), row.get("actual_psa_date"))
            for row in rows
            if row.get("actual_psa_date")
        ],
        date_policy="actual_psa_date - target_date; capturas previas o el mismo dia cuentan como 0 dias.",
        source="arpi_response_windows.actual_psa_date",
    )
    append_domain(
        key="ecog_response_window",
        label="ECOG funcional en ventana",
        eligible_count=len(rows),
        closed_count=sum(1 for row in rows if row.get("actual_ecog") is not None),
        latency_days=[
            _nonnegative_days_between(row.get("target_date"), row.get("actual_ecog_date"))
            for row in rows
            if row.get("actual_ecog") is not None and row.get("actual_ecog_date")
        ],
        date_policy="actual_ecog_date - target_date; sin proxy APE cuando la fecha ECOG no esta persistida.",
        source="arpi_response_windows.actual_ecog_date",
        warning="Filas antiguas pueden tener valor ECOG sin fecha; cuentan cobertura pero no latencia.",
    )
    append_domain(
        key="dose_cost_trace",
        label="Dosis y costo costeable",
        eligible_count=len(rows),
        closed_count=sum(
            1 for row in rows
            if (_safe_int(row.get("local_dose_count_to_window"), 0) or 0) > 0
            and (_safe_float(row.get("spend_to_window_mxn"), 0.0) or 0.0) > 0
        ),
        latency_days=[
            _nonnegative_days_between(row.get("target_date"), row.get("first_priced_local_dose_date_to_window"))
            for row in rows
            if row.get("first_priced_local_dose_date_to_window")
        ],
        date_policy="first_priced_local_dose_date_to_window - target_date; dosis costeadas previas cuentan como 0 dias.",
        source="treatment_dose_administrations + medication_price_catalog",
        warning="Usa primera dosis local con costo ARPI trazable dentro de la ventana analitica.",
    )
    referral_rows = [row for row in rows if row.get("referral_trigger_date")]
    append_domain(
        key="referral_after_dose4",
        label="Referencia tras cuarta dosis local",
        eligible_count=len(referral_rows),
        closed_count=sum(1 for row in referral_rows if row.get("referral_status") not in (None, "", "not_triggered")),
        latency_days=[
            _safe_int(row.get("referral_delay_days"), None)
            for row in referral_rows
            if _safe_int(row.get("referral_delay_days"), None) is not None
        ],
        date_policy="referral_delay_days derivado entre disparador de dosis 4 y dosis critica/ultima dosis local.",
        source="treatment_dose_administrations",
    )
    append_domain(
        key="toxicity_surveillance",
        label="Toxicidad CTCAE revisada",
        eligible_count=len(rows),
        closed_count=sum(1 for row in rows if row.get("toxicity_review_documented") is True),
        latency_days=[
            _nonnegative_days_between(row.get("target_date"), row.get("toxicity_review_date"))
            for row in rows
            if row.get("toxicity_review_documented") is True and row.get("toxicity_review_date")
        ],
        date_policy="toxicity_review_date - target_date; revision CTCAE previa o el mismo dia cuenta como 0 dias.",
        source="treatment_adverse_events + CTCAE_TOXICITY",
        warning="CTCAE grado 0 documenta ausencia revisada; sin revision queda como brecha abierta.",
    )

    worklist_items = list((capture_worklist or {}).get("items") or [])
    reviewed_items = [item for item in worklist_items if item.get("reviewed")]
    review_latencies: list[int | None] = []
    for item in reviewed_items:
        row = row_by_patient_week.get(
            (str(item.get("patient_ref") or ""), _safe_int(item.get("week"), None))
        )
        reviewed_at = ((item.get("closure_state") or {}).get("reviewed_at") or "")
        review_latencies.append(
            _safe_int(item.get("review_latency_days"), None)
            if item.get("review_latency_days") is not None
            else _nonnegative_days_between(item.get("detected_at") or (row or {}).get("target_date"), reviewed_at)
        )
    open_worklist_items = [
        item for item in worklist_items
        if item.get("closure_status") not in ("not_applicable",) and not item.get("reviewed")
    ]
    overdue_items = [
        item for item in worklist_items
        if str(item.get("sla_state") or "").startswith("overdue")
    ]
    due_soon_items = [
        item for item in worklist_items
        if str(item.get("sla_state") or "").startswith("due_soon")
    ]
    opened_days = [
        _safe_int(item.get("days_open"), None)
        for item in open_worklist_items
        if _safe_int(item.get("days_open"), None) is not None
    ]
    append_domain(
        key="epidemiology_gap_review",
        label="Revision auditada de brechas",
        eligible_count=len(worklist_items),
        closed_count=len(reviewed_items),
        open_count=sum(1 for item in worklist_items if not item.get("reviewed")),
        latency_days=review_latencies,
        date_policy="reviewed_at - target_date cuando la brecha fue revisada y sigue auditada en patient_events.",
        source="patient_events.epidemiology_readiness_gap_reviewed",
    )

    eligible_domains = [item for item in domains if item["eligible_count"] > 0]
    closed_domains = [item for item in eligible_domains if item["open_count"] == 0]
    open_domains = [item for item in eligible_domains if item["open_count"] > 0]
    all_latencies = [
        value
        for item in domains
        for value in (item.get("median_days_to_close"), item.get("p90_days_to_close"))
        if value is not None
    ]
    aggregate_stats = _latency_stats([int(value) for value in all_latencies])
    open_gap_count = sum(_safe_int(item.get("open_count"), 0) or 0 for item in domains)
    if not eligible_domains:
        status = "no_data"
    elif open_gap_count:
        status = "needs_capture_operations"
    elif aggregate_stats["p90_days"] is not None and aggregate_stats["p90_days"] > 14:
        status = "slow_but_complete"
    else:
        status = "operational_ready"
    return {
        "version": "operational_gap_latency_v1",
        "status": status,
        "summary": {
            "patient_count": len({row.get("patient_ref") for row in rows if row.get("patient_ref")}),
            "eligible_domain_count": len(eligible_domains),
            "closed_domain_count": len(closed_domains),
            "open_domain_count": len(open_domains),
            "median_days_to_close": aggregate_stats["median_days"],
            "p90_days_to_close": aggregate_stats["p90_days"],
            "max_days_to_close": aggregate_stats["max_days"],
            "open_gap_count": open_gap_count,
            "open_capture_worklist_count": (capture_worklist or {}).get("open_gap_count", 0),
            "reviewed_capture_worklist_count": (capture_worklist or {}).get("reviewed_gap_count", 0),
            "open_unreviewed_gap_count": (capture_worklist or {}).get("unreviewed_gap_count", 0),
            "reviewed_still_missing_gap_count": (capture_worklist or {}).get("reviewed_still_missing_count", 0),
            "oldest_open_gap_days": max(opened_days) if opened_days else None,
            "sla_overdue_gap_count": len(overdue_items),
            "sla_due_soon_gap_count": len(due_soon_items),
            "sla_owner_count": len((capture_worklist or {}).get("sla_by_owner") or []),
        },
        "domains": domains,
        "audit_note": (
            "Capa operacional derivada y read-only. Mide disponibilidad y latencia de dato util; "
            "no muta hechos clinicos ni convierte ausencias en desenlaces negativos."
        ),
        "read_only_impact_model": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


def _build_longitudinal_outcomes_summary(rows_by_week: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rows = _latest_window_rows(rows_by_week)
    return {
        "version": "longitudinal_outcomes_v2",
        "patient_count": len(rows),
        "time_to_psa_progression_days": normal_ci_mean([
            float(row["time_to_psa_progression_days"])
            for row in rows
            if row.get("time_to_psa_progression_days") is not None
        ]),
        "time_to_discontinuation_days": normal_ci_mean([
            float(row["time_to_discontinuation_days"])
            for row in rows
            if row.get("time_to_discontinuation_days") is not None
        ]),
        "line_persistence_days": normal_ci_mean([
            float(row["line_persistence_days_to_window"])
            for row in rows
            if row.get("line_persistence_days_to_window") is not None
        ]),
        "ecog_improved_count": sum(1 for row in rows if row.get("ecog_improved") is True),
        "high_grade_toxicity_count": sum(1 for row in rows if row.get("high_grade_toxicity_to_window") is True),
        "hospitalization_count": sum(1 for row in rows if row.get("hospitalization_toxicity_to_window") is True),
        "referral_delay_patient_count": sum(1 for row in rows if _safe_int(row.get("referral_delay_days"), 0) and _safe_int(row.get("referral_delay_days"), 0) > 0),
        "bone_event_count": sum(1 for row in rows if row.get("bone_event_to_window") is True),
        "death_count": sum(1 for row in rows if row.get("death_to_window") is True),
        "line_change_count": sum(_safe_int(row.get("line_change_count_to_window"), 0) or 0 for row in rows),
        "interpretation": "Extiende el tablero mas alla de PSA50/PSA90 con persistencia, progresion, toxicidad, hospitalizacion, referencia, eventos oseos y supervivencia si existen.",
    }


def _build_economic_layer_summary(rows_by_week: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rows = _latest_window_rows(rows_by_week)
    response_rows = [row for row in rows if row.get("response_evaluable")]
    psa50_count = sum(1 for row in response_rows if row.get("psa50_response") is True)
    non_response_count = len(response_rows) - psa50_count
    ecog_improved = sum(1 for row in rows if row.get("ecog_improved") is True)
    referral_delay = sum(1 for row in rows if _safe_int(row.get("referral_delay_days"), 0) and _safe_int(row.get("referral_delay_days"), 0) > 0)
    total_spend = round(sum(_safe_float(row.get("spend_to_window_mxn"), 0.0) or 0.0 for row in rows), 2)
    return {
        "version": "institutional_economic_layer_v2",
        "estimated_spend_mxn": total_spend,
        "local_doses": sum(_safe_int(row.get("local_dose_count_to_window"), 0) or 0 for row in rows),
        "priced_doses": sum(_safe_int(row.get("priced_local_dose_count"), 0) or 0 for row in rows),
        "partial_cost_patient_count": sum(1 for row in rows if _safe_int(row.get("partial_cost_dose_count"), 0) > 0),
        "stale_price_patient_count": sum(1 for row in rows if _safe_int(row.get("stale_cost_dose_count"), 0) > 0),
        "cost_per_psa50_responder_mxn": round(total_spend / psa50_count, 2) if psa50_count else None,
        "cost_per_ecog_improved_patient_mxn": round(total_spend / ecog_improved, 2) if ecog_improved else None,
        "cost_per_non_responder_mxn": round(total_spend / non_response_count, 2) if non_response_count else None,
        "cost_per_referral_delay_patient_mxn": round(total_spend / referral_delay, 2) if referral_delay else None,
        "audit_note": "Costo operativo estimado desde dosis locales y catalogo trazable; no sustituye auditoria formal de compras.",
    }


def _build_research_governance(rows_by_week: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rows = _latest_window_rows(rows_by_week)
    n = len(rows)
    real_count = sum(1 for row in rows if not row.get("is_synthetic"))
    completeness = _build_epidemiology_completeness_tower(rows_by_week)
    completeness_pct = completeness.get("overall_completeness_pct")
    if n >= 30 and real_count >= 30 and completeness_pct is not None and completeness_pct >= 85:
        status = "poster_or_manuscript_ready"
    elif n >= MIN_COHORT_N and completeness_pct is not None and completeness_pct >= 70:
        status = "auditable_exploratory"
    else:
        status = "exploratory_insufficient_for_inference"
    questions = [
        "¿Que regimen logra mayor PSA50/PSA90 a 24 semanas con menor costo por respuesta?",
        "¿El retraso de referencia despues de la cuarta dosis se asocia con mayor gasto o menor persistencia?",
        "¿La mejoria ECOG acompaña la respuesta APE o identifica beneficio clinico independiente?",
    ]
    if any(row.get("high_grade_toxicity_to_window") for row in rows):
        questions.append("¿Que molecula/regimen concentra toxicidad CTCAE G3+ ajustada por estado basal?")
    return {
        "version": "research_governance_v2",
        "status": status,
        "patient_count": n,
        "real_patient_count": real_count,
        "synthetic_patient_count": n - real_count,
        "minimum_group_n": MIN_COHORT_N,
        "completeness_pct": completeness_pct,
        "bias_warnings": _research_bias_warnings(rows, completeness_pct),
        "suggested_research_questions": questions,
        "methods_summary": (
            "Registro longitudinal retrospectivo/prospectivo de mundo real; "
            "comparacion por molecula/regimen con estandarizacion directa por estado basal. "
            "Usar como exploratorio hasta contar con N real suficiente y completitud alta."
        ),
    }


def _build_epidemiology_capture_worklist(rows_by_week: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rows = _latest_window_rows(rows_by_week)
    missing_specs = [
        {
            "key": "survival_status",
            "label": "Estado vital/contacto",
            "priority": "high",
            "sla_days": 7,
            "owner_role": "navegacion_clinica",
            "missing": lambda r: r.get("survival_status_available") is not True,
            "decision_field": "vital_status",
            "rationale": "Necesario para supervivencia, censura y seguridad del registro longitudinal.",
        },
        {
            "key": "metastatic_context",
            "label": "Carga metastasica",
            "priority": "high",
            "sla_days": 7,
            "owner_role": "uro_oncologia",
            "missing": lambda r: (r.get("baseline_state_components") or {}).get("metastatic_volume") in ("volume_unknown", "", None),
            "decision_field": "volume_disease",
            "rationale": "Ajusta comparaciones entre doblete/triplete y evita mezclar bajo/alto volumen.",
        },
        {
            "key": "comorbidity",
            "label": "Comorbilidad basal",
            "priority": "moderate",
            "sla_days": 14,
            "owner_role": "enfermeria_oncologica",
            "missing": lambda r: (r.get("baseline_state_components") or {}).get("comorbidity_band") in ("comorbidity_unknown", "", None),
            "decision_field": "comorbidities",
            "rationale": "Reduce sesgo por fragilidad cardiovascular/metabolica y permite ajuste basal.",
        },
        {
            "key": "actual_ecog",
            "label": "ECOG de ventana",
            "priority": "high",
            "sla_days": 7,
            "owner_role": "enfermeria_oncologica",
            "missing": lambda r: r.get("actual_ecog") is None,
            "decision_field": "ecog",
            "rationale": "Necesario para beneficio clinico funcional y costo por ECOG mejorado.",
        },
        {
            "key": "toxicity_ctcae",
            "label": "Toxicidad CTCAE",
            "priority": "moderate",
            "sla_days": 14,
            "owner_role": "enfermeria_oncologica",
            "missing": lambda r: r.get("toxicity_review_documented") is not True,
            "decision_field": "ctcae_toxicity",
            "rationale": "Distingue seguridad real de ausencia no documentada.",
        },
        {
            "key": "cost_trace",
            "label": "Costo trazable",
            "priority": "moderate",
            "sla_days": 14,
            "owner_role": "farmacia_administracion",
            "missing": lambda r: _safe_float(r.get("spend_to_window_mxn"), 0.0) <= 0,
            "decision_field": "treatment_dose_cost",
            "rationale": "Indispensable para HEOR hospitalario y costo por respuesta.",
        },
    ]
    items: list[dict[str, Any]] = []
    for row in rows:
        patient_ref = str(row.get("patient_ref") or "")
        if not patient_ref:
            continue
        reviews = row.get("epidemiology_gap_reviews") or {}
        detected_at = str(
            row.get("target_date")
            or row.get("actual_psa_date")
            or row.get("line_start_date")
            or ""
        )[:10]
        generated_at = utc_now_iso()
        days_since_detection = _nonnegative_days_between(detected_at, generated_at) if detected_at else None
        for spec in missing_specs:
            if not spec["missing"](row):
                continue
            closure_state = reviews.get(spec["key"]) or {}
            closure_status = str(closure_state.get("closure_status") or "open").strip() or "open"
            reviewed = closure_status != "open"
            reviewed_at = str(closure_state.get("reviewed_at") or "").strip()
            review_latency_days = (
                _nonnegative_days_between(
                    closure_state.get("detected_at") or detected_at,
                    reviewed_at,
                )
                if reviewed_at
                else None
            )
            if closure_status == "open":
                audit_state = "open_unreviewed"
            elif closure_status == "not_applicable":
                audit_state = "reviewed_not_applicable"
            else:
                audit_state = "reviewed_still_missing"
            owner_role = str(
                closure_state.get("owner_role")
                or closure_state.get("assigned_to")
                or spec.get("owner_role")
                or "registro_clinico"
            )
            assigned_to = str(closure_state.get("assigned_to") or owner_role)
            sla_days = _safe_int(closure_state.get("sla_days") or spec.get("sla_days"), 14) or 14
            due_date = str(closure_state.get("due_date") or _add_days(detected_at, sla_days) or "")[:10]
            days_to_due = _days_between(str(generated_at)[:10], due_date) if due_date else None
            sla_state = _derive_gap_sla_state(
                closure_status=closure_status,
                audit_state=audit_state,
                days_to_due=days_to_due,
            )
            items.append(
                {
                    "patient_ref": patient_ref,
                    "patient_name": row.get("patient_name"),
                    "week": row.get("target_weeks") or row.get("week"),
                    "target_weeks": row.get("target_weeks") or row.get("week"),
                    "target_date": row.get("target_date"),
                    "line_start_date": row.get("line_start_date"),
                    "regimen_code": row.get("regimen_code"),
                    "molecule": row.get("molecule") or row.get("arpi_agent"),
                    "gap_key": spec["key"],
                    "gap_label": spec["label"],
                    "priority": spec["priority"],
                    "rationale": spec["rationale"],
                    "closure_status": closure_status,
                    "closure_state": closure_state,
                    "reviewed": reviewed,
                    "audit_state": audit_state,
                    "detected_at": closure_state.get("detected_at") or detected_at,
                    "detection_anchor": closure_state.get("detection_anchor") or "response_window_target_date",
                    "days_open": None if reviewed else days_since_detection,
                    "reviewed_at": reviewed_at,
                    "reviewed_by": closure_state.get("reviewed_by") or "",
                    "review_latency_days": review_latency_days,
                    "next_followup_date": closure_state.get("next_followup_date") or "",
                    "selected_action_key": closure_state.get("selected_action_key") or "",
                    "acknowledged_missing_fields": closure_state.get("acknowledged_missing_fields") or [],
                    "assigned_to": assigned_to,
                    "owner_role": owner_role,
                    "due_date": due_date,
                    "days_to_due": days_to_due,
                    "sla_days": sla_days,
                    "sla_policy": closure_state.get("sla_policy") or f"{spec['priority']}_{sla_days}d",
                    "sla_state": sla_state,
                    "still_structurally_missing": True,
                    "profile_url": f"/patient_profile/{patient_ref}?v=2",
                    "capture_url": (
                        f"/longitudinal-capture/{patient_ref}"
                        f"?decision_lane=epidemiology_registry&decision_field={spec['decision_field']}"
                        f"&gap_key={spec['key']}"
                    ),
                }
            )
    priority_order = {"high": 0, "moderate": 1, "low": 2}
    items = sorted(items, key=lambda item: (priority_order.get(item["priority"], 9), item["patient_ref"], item["gap_key"]))
    counts = Counter(item["gap_key"] for item in items)
    active_items = [item for item in items if item.get("closure_status") != "not_applicable"]
    reviewed_items = [item for item in items if item.get("reviewed")]
    reviewed_still_missing = [
        item for item in active_items
        if item.get("audit_state") == "reviewed_still_missing"
    ]
    owner_counts: dict[str, dict[str, Any]] = {}
    for item in active_items:
        owner = str(item.get("owner_role") or item.get("assigned_to") or "registro_clinico")
        bucket = owner_counts.setdefault(
            owner,
            {
                "owner_role": owner,
                "active_count": 0,
                "overdue_count": 0,
                "due_soon_count": 0,
                "reviewed_still_missing_count": 0,
            },
        )
        bucket["active_count"] += 1
        if str(item.get("sla_state") or "").startswith("overdue"):
            bucket["overdue_count"] += 1
        if str(item.get("sla_state") or "").startswith("due_soon"):
            bucket["due_soon_count"] += 1
        if item.get("audit_state") == "reviewed_still_missing":
            bucket["reviewed_still_missing_count"] += 1
    sla_by_owner = sorted(
        owner_counts.values(),
        key=lambda item: (-int(item["overdue_count"]), -int(item["active_count"]), str(item["owner_role"])),
    )
    overdue_items = [
        item for item in active_items
        if str(item.get("sla_state") or "").startswith("overdue")
    ]
    due_soon_items = [
        item for item in active_items
        if str(item.get("sla_state") or "").startswith("due_soon")
    ]
    return {
        "version": "epidemiology_capture_worklist_v2",
        "open_gap_count": len(active_items),
        "unreviewed_gap_count": sum(1 for item in active_items if not item.get("reviewed")),
        "reviewed_gap_count": len(reviewed_items),
        "reviewed_still_missing_count": len(reviewed_still_missing),
        "sla_overdue_count": len(overdue_items),
        "sla_due_soon_count": len(due_soon_items),
        "sla_by_owner": sla_by_owner,
        "oldest_open_gap_days": max(
            [
                _safe_int(item.get("days_open"), 0) or 0
                for item in active_items
                if not item.get("reviewed")
            ],
            default=0,
        ),
        "not_applicable_count": sum(1 for item in items if item.get("closure_status") == "not_applicable"),
        "patient_count_with_gaps": len({item["patient_ref"] for item in items}),
        "by_gap": [{"gap_key": key, "count": count} for key, count in sorted(counts.items())],
        "items": items[:100],
        "audit_note": "Cola de captura derivada de brechas; revisiones se auditan en patient_events y no mutan hechos clinicos.",
    }


def _research_bias_warnings(rows: list[dict[str, Any]], completeness_pct: float | None) -> list[str]:
    warnings: list[str] = []
    if len(rows) < MIN_COHORT_N:
        warnings.append(f"n<{MIN_COHORT_N}; no usar para inferencia comparativa.")
    if sum(1 for row in rows if row.get("is_synthetic")):
        warnings.append("La cohorte incluye pacientes sintéticos; separar antes de reporte institucional formal.")
    if completeness_pct is None or completeness_pct < 80:
        warnings.append("Completitud epidemiologica <80%; priorizar captura faltante antes de conclusiones.")
    buckets = {str(row.get("baseline_state_bucket") or "") for row in rows}
    if len(buckets) > 1:
        warnings.append("Heterogeneidad basal detectada; interpretar comparaciones crudas con ajuste visible.")
    return warnings


def _rate_pct(successes: int, denominator: int) -> float | None:
    if not denominator:
        return None
    return round((successes / denominator) * 100, 1)


def _summarize_value_rows(label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    total_spend = round(sum(_safe_float(row.get("spend_to_window_mxn"), 0.0) or 0.0 for row in rows), 2)
    total_doses = sum(_safe_int(row.get("local_dose_count_to_window"), 0) or 0 for row in rows)
    total_priced_doses = sum(_safe_int(row.get("priced_local_dose_count"), 0) or 0 for row in rows)
    response_rows = [row for row in rows if row.get("response_evaluable")]
    ecog_rows = [row for row in rows if row.get("ecog_change_from_baseline") is not None]
    psa50_count = sum(1 for row in response_rows if row.get("psa50_response") is True)
    psa90_count = sum(1 for row in response_rows if row.get("psa90_response") is True)
    ecog_improved = sum(1 for row in ecog_rows if row.get("ecog_improved") is True)
    if n < MIN_COHORT_N:
        return {
            "arpi_agent": label,
            "n": n,
            "suppressed": True,
            "display": f"n<{MIN_COHORT_N} suprimido",
            "n_response_evaluable": len(response_rows),
            "n_ecog_evaluable": len(ecog_rows),
        }
    return {
        "arpi_agent": label,
        "n": n,
        "suppressed": False,
        "n_response_evaluable": len(response_rows),
        "n_ecog_evaluable": len(ecog_rows),
        "total_local_doses_to_window": total_doses,
        "priced_local_doses_to_window": total_priced_doses,
        "partial_cost_patient_count": sum(1 for row in rows if row.get("partial_cost_dose_count")),
        "stale_price_patient_count": sum(1 for row in rows if row.get("stale_cost_dose_count")),
        "estimated_spend_to_window_mxn": total_spend,
        "mean_local_doses_to_window": normal_ci_mean([
            float(row.get("local_dose_count_to_window") or 0) for row in rows
        ]),
        "mean_spend_to_window_mxn": normal_ci_mean([
            float(row.get("spend_to_window_mxn") or 0.0) for row in rows
        ]),
        "mean_psa_decline_pct": normal_ci_mean([
            float(row["psa_decline_pct"])
            for row in response_rows
            if row.get("psa_decline_pct") is not None
        ]),
        "psa50_rate": proportion_with_ci(psa50_count, len(response_rows)),
        "psa90_rate": proportion_with_ci(psa90_count, len(response_rows)),
        "ecog_improvement_rate": proportion_with_ci(ecog_improved, len(ecog_rows)),
        "cost_per_psa50_responder_mxn": round(total_spend / psa50_count, 2) if psa50_count else None,
        "cost_per_ecog_improved_patient_mxn": round(total_spend / ecog_improved, 2) if ecog_improved else None,
    }


def _match_doses_to_response(
    dose_rows: list[dict[str, Any]],
    *,
    regimen_code: str,
    arpi_label: str,
    cutoff_date: str,
) -> list[dict[str, Any]]:
    normalized_regimen = normalize_regimen_code(regimen_code)
    matched: list[dict[str, Any]] = []
    for dose in dose_rows:
        dose_regimen = str(dose.get("regimen_code") or "")
        dose_arpi_label = _arpi_label_for_regimen(dose_regimen)
        if dose_arpi_label != arpi_label:
            continue
        same_regimen = normalize_regimen_code(dose_regimen) == normalized_regimen
        if not same_regimen and normalized_regimen and normalize_regimen_code(dose_regimen):
            # Same ARPI agent is enough when historic rows used a legacy regimen alias.
            pass
        dose_date = str(dose.get("dose_date") or "")[:10]
        if cutoff_date and dose_date and dose_date > cutoff_date:
            continue
        matched.append(dose)
    return matched


def _load_treatment_value_context(patient_ids: list[int]) -> dict[str, Any]:
    context = {
        "treatments_by_patient": defaultdict(list),
        "doses_by_patient": defaultdict(list),
        "adverse_events_by_patient": defaultdict(list),
        "ctcae_reviews_by_patient": defaultdict(list),
        "prior_history_by_patient": {},
        "baseline_by_patient": {},
        "identity_by_patient": {},
        "events_by_patient": defaultdict(list),
    }
    if not patient_ids:
        return context
    placeholders = ",".join("?" for _ in patient_ids)
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        for row in conn.execute(
            f"""
            SELECT id, nss, full_name, dob, diagnosis_date, vital_status,
                   date_of_death, cause_of_death, last_contact_date,
                   last_contact_status, death_source, COALESCE(is_synthetic, 0) AS is_synthetic
            FROM patient_identity
            WHERE id IN ({placeholders})
            """,
            patient_ids,
        ).fetchall():
            item = dict(row)
            context["identity_by_patient"][int(item["id"])] = item
        for row in conn.execute(
            f"""
            SELECT *
            FROM clinical_baseline
            WHERE patient_id IN ({placeholders})
            ORDER BY patient_id ASC, id DESC
            """,
            patient_ids,
        ).fetchall():
            item = dict(row)
            item["comorbidities"] = _parse_cost_source(item.get("comorbidities_json"))
            context["baseline_by_patient"].setdefault(int(item["patient_id"]), item)
        for row in conn.execute(
            f"""
            SELECT *
            FROM treatment_history
            WHERE patient_id IN ({placeholders})
            ORDER BY patient_id ASC, COALESCE(start_date, '') ASC, id ASC
            """,
            patient_ids,
        ).fetchall():
            item = dict(row)
            item["regimen"] = _parse_cost_source(item.get("regimen_json"))
            context["treatments_by_patient"][int(item["patient_id"])].append(item)
        for row in conn.execute(
            f"""
            SELECT *
            FROM treatment_dose_administrations
            WHERE patient_id IN ({placeholders})
              AND COALESCE(administered_in_unit, 1) = 1
            ORDER BY patient_id ASC, COALESCE(dose_date, '') ASC, id ASC
            """,
            patient_ids,
        ).fetchall():
            item = dict(row)
            context["doses_by_patient"][int(item["patient_id"])].append(item)
        for row in conn.execute(
            f"""
            SELECT *
            FROM treatment_adverse_events
            WHERE patient_id IN ({placeholders})
            ORDER BY patient_id ASC, COALESCE(event_date, '') ASC, id ASC
            """,
            patient_ids,
        ).fetchall():
            item = dict(row)
            context["adverse_events_by_patient"][int(item["patient_id"])].append(item)
        for row in conn.execute(
            f"""
            SELECT *
            FROM biomarker_longitudinal
            WHERE patient_id IN ({placeholders})
              AND UPPER(COALESCE(biomarker_type, '')) = 'CTCAE_TOXICITY'
            ORDER BY patient_id ASC, COALESCE(sample_date, '') ASC, id ASC
            """,
            patient_ids,
        ).fetchall():
            item = dict(row)
            item["lab_source_payload"] = _parse_cost_source(item.get("lab_source"))
            context["ctcae_reviews_by_patient"][int(item["patient_id"])].append(item)
        for row in conn.execute(
            f"""
            SELECT *
            FROM patient_events
            WHERE patient_id IN ({placeholders})
            ORDER BY patient_id ASC, COALESCE(event_date, '') ASC, id ASC
            """,
            patient_ids,
        ).fetchall():
            item = dict(row)
            item["payload"] = _parse_cost_source(item.get("payload_json"))
            context["events_by_patient"][int(item["patient_id"])].append(item)
        for row in conn.execute(
            f"""
            SELECT patient_id, assessment_state, current_state, assessment_module
            FROM prior_clinical_history
            WHERE patient_id IN ({placeholders})
            ORDER BY patient_id ASC, id DESC
            """,
            patient_ids,
        ).fetchall():
            item = dict(row)
            context["prior_history_by_patient"].setdefault(int(item["patient_id"]), item)
    finally:
        conn.close()
    return context


def _match_treatment_line(
    treatments: list[dict[str, Any]],
    *,
    regimen_code: str,
    line_start_date: str,
) -> dict[str, Any]:
    normalized = normalize_regimen_code(regimen_code)
    exact = [
        row for row in treatments
        if normalize_regimen_code(row.get("drug_scheme")) == normalized
        and str(row.get("start_date") or "")[:10] == line_start_date
    ]
    if exact:
        return exact[-1]
    same_regimen = [
        row for row in treatments
        if normalize_regimen_code(row.get("drug_scheme")) == normalized
    ]
    if same_regimen:
        return same_regimen[-1]
    return treatments[-1] if treatments else {}


def _match_adverse_events_to_window(
    events: list[dict[str, Any]],
    *,
    regimen_code: str,
    treatment_id: int | None,
    start_date: str,
    cutoff_date: str,
) -> list[dict[str, Any]]:
    normalized = normalize_regimen_code(regimen_code)
    matched: list[dict[str, Any]] = []
    for event in events:
        if treatment_id and _safe_int(event.get("treatment_id"), None) not in (None, treatment_id):
            continue
        event_regimen = normalize_regimen_code(event.get("regimen_code"))
        if event_regimen and normalized and event_regimen != normalized:
            continue
        event_date = str(event.get("event_date") or "")[:10]
        if start_date and event_date and event_date < start_date:
            continue
        if cutoff_date and event_date and event_date > cutoff_date:
            continue
        matched.append(event)
    return matched


def _match_ctcae_reviews_to_window(
    reviews: list[dict[str, Any]],
    *,
    regimen_code: str,
    start_date: str,
    cutoff_date: str,
) -> list[dict[str, Any]]:
    normalized = normalize_regimen_code(regimen_code)
    matched: list[dict[str, Any]] = []
    for review in reviews:
        review_date = str(review.get("sample_date") or "")[:10]
        if start_date and review_date and review_date < start_date:
            continue
        if cutoff_date and review_date and review_date > cutoff_date:
            continue
        payload = review.get("lab_source_payload") or {}
        extra = payload.get("extra_data") or {}
        review_regimen = normalize_regimen_code(
            extra.get("regimen_code")
            or extra.get("drug_scheme")
            or payload.get("drug_scheme")
        )
        if review_regimen and normalized and review_regimen != normalized:
            continue
        matched.append(review)
    return matched


def _ctcae_review_grade(review: Mapping[str, Any]) -> int | None:
    payload = review.get("lab_source_payload") or {}
    extra = payload.get("extra_data") or {}
    return _safe_int(
        extra.get("grade")
        or extra.get("ctcae_grade")
        or extra.get("toxicity_grade")
        or review.get("value"),
        None,
    )


def _ctcae_review_documents_absence(review: Mapping[str, Any]) -> bool:
    payload = review.get("lab_source_payload") or {}
    extra = payload.get("extra_data") or {}
    grade = _ctcae_review_grade(review)
    absence_tokens = {
        "none",
        "no",
        "absent",
        "sin toxicidad",
        "sin evento",
        "no_event",
        "reviewed_none",
    }
    explicit = str(
        extra.get("toxicity_status")
        or extra.get("review_status")
        or extra.get("event_status")
        or extra.get("ctcae_status")
        or ""
    ).strip().lower()
    no_toxicity_flag = str(extra.get("no_toxicity") or extra.get("toxicity_absent") or "").strip().lower()
    return (
        grade == 0
        or explicit in absence_tokens
        or no_toxicity_flag in {"1", "true", "yes", "si", "sí"}
    )


def _derive_toxicity_summary(
    events: list[dict[str, Any]],
    ctcae_reviews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    reviews = list(ctcae_reviews or [])
    grades = [
        _safe_int(event.get("ctcae_grade"), None)
        for event in events
    ]
    grades = [grade for grade in grades if grade is not None]
    review_grades = [
        grade for grade in (_ctcae_review_grade(review) for review in reviews)
        if grade is not None
    ]
    positive_review_grades = [grade for grade in review_grades if grade > 0]
    all_observed_grades = grades + review_grades
    max_grade = max(all_observed_grades) if all_observed_grades else None
    event_count = (
        len(events) + len(positive_review_grades)
        if events or reviews
        else None
    )
    review_dates = _sorted_iso_dates(
        [event.get("event_date") for event in events]
        + [review.get("sample_date") for review in reviews]
    )
    absence_documented = bool(
        not events
        and not positive_review_grades
        and any(_ctcae_review_documents_absence(review) for review in reviews)
    )
    review_sources: list[str] = []
    if events:
        review_sources.append("treatment_adverse_events")
    if reviews:
        review_sources.append("CTCAE_TOXICITY")
    return {
        "event_count": event_count,
        "max_ctcae_grade": max_grade,
        "high_grade_toxicity": bool(max_grade is not None and max_grade >= 3),
        "dose_modification_triggered": any(bool(event.get("dose_modification_triggered")) for event in events),
        "hospitalization": any(bool(event.get("hospitalization")) for event in events),
        "review_documented": bool(events or reviews),
        "absence_documented": absence_documented,
        "review_date": review_dates[-1] if review_dates else None,
        "review_source": "+".join(review_sources),
    }


def _derive_discontinuation_by_window(
    treatment: dict[str, Any],
    *,
    cutoff_date: str,
) -> dict[str, Any]:
    if not treatment:
        return {
            "discontinued_by_window": False,
            "discontinuation_reason": "",
            "discontinuation_date": None,
        }
    end_date = str(treatment.get("end_date") or "")[:10]
    outcome = str(treatment.get("outcome") or "").strip()
    outcome_lower = outcome.lower()
    reason = (
        str(treatment.get("discontinuation_reason") or "").strip()
        or str((treatment.get("regimen") or {}).get("reason_for_change") or "").strip()
        or outcome
    )
    discontinuation_like = any(
        token in outcome_lower
        for token in ("discontinu", "toxic", "progress", "changed", "suspend")
    )
    ended_by_window = bool(end_date and (not cutoff_date or end_date <= cutoff_date))
    return {
        "discontinued_by_window": bool(ended_by_window and (discontinuation_like or outcome_lower not in {"", "ongoing", "activo"})),
        "discontinuation_reason": reason,
        "discontinuation_date": end_date or None,
    }


def _derive_referral_delay(doses: list[dict[str, Any]]) -> dict[str, Any]:
    local_doses = [
        {
            **dose,
            "_local": _safe_int(dose.get("dose_number_local"), None),
            "_date": str(dose.get("dose_date") or "")[:10],
        }
        for dose in doses
    ]
    local_doses = [dose for dose in local_doses if dose["_local"] is not None]
    if not local_doses:
        return {
            "referral_trigger_date": None,
            "referral_critical_date": None,
            "referral_delay_days": None,
            "referral_status": "not_triggered",
            "latest_local_dose_number": None,
        }
    latest = max(local_doses, key=lambda item: item["_local"])
    trigger = next((dose for dose in local_doses if dose["_local"] >= 4), None)
    critical = next((dose for dose in local_doses if dose["_local"] >= 6), None)
    if not trigger:
        return {
            "referral_trigger_date": None,
            "referral_critical_date": None,
            "referral_delay_days": None,
            "referral_status": "not_triggered",
            "latest_local_dose_number": latest["_local"],
        }
    delay_anchor = critical or latest
    delay_days = _days_between(trigger["_date"], delay_anchor["_date"])
    if critical:
        status = "delayed_to_critical" if delay_days and delay_days > 0 else "critical_same_day"
    elif latest["_local"] > 4:
        status = "ongoing_after_trigger"
    else:
        status = "triggered_no_delay"
    return {
        "referral_trigger_date": trigger["_date"] or None,
        "referral_critical_date": (critical or {}).get("_date") or None,
        "referral_delay_days": delay_days,
        "referral_status": status,
        "latest_local_dose_number": latest["_local"],
    }


def _derive_longitudinal_outcomes(
    row: dict[str, Any],
    *,
    treatment: dict[str, Any],
    patient_treatments: list[dict[str, Any]],
    patient_events: list[dict[str, Any]],
    identity: dict[str, Any],
    toxicity: dict[str, Any],
    referral: dict[str, Any],
    cutoff_date: str,
) -> dict[str, Any]:
    start_date = str(treatment.get("start_date") or row.get("line_start_date") or "")[:10]
    end_date = str(treatment.get("end_date") or "")[:10]
    progression_events = _events_matching(patient_events, ("psa_progression", "biochemical_progression", "biochemical_recurrence", "radiographic_progression"))
    bone_events = _events_matching(patient_events, ("bone_event", "skeletal_event", "sre", "pathologic_fracture", "spinal_cord_compression"))
    first_progression = _first_event_date(progression_events, cutoff_date=cutoff_date)
    first_bone = _first_event_date(bone_events, cutoff_date=cutoff_date)
    death_date = str(identity.get("date_of_death") or "")[:10]
    latest_line_number = _safe_int(treatment.get("line_of_therapy"), 0) or 0
    later_lines = [
        item for item in patient_treatments
        if _safe_int(item.get("line_of_therapy"), 0)
        and latest_line_number
        and (_safe_int(item.get("line_of_therapy"), 0) or 0) > latest_line_number
        and _date_lte(str(item.get("start_date") or "")[:10], cutoff_date)
    ]
    persistence_end = end_date if end_date and _date_lte(end_date, cutoff_date) else cutoff_date
    return {
        "time_to_psa_progression_days": _days_between(start_date, first_progression) if first_progression else None,
        "time_to_discontinuation_days": _days_between(start_date, end_date) if end_date and _date_lte(end_date, cutoff_date) else None,
        "line_persistence_days_to_window": _days_between(start_date, persistence_end) if start_date and persistence_end else None,
        "line_change_count_to_window": len(later_lines),
        "hospitalization_toxicity_to_window": toxicity.get("hospitalization"),
        "bone_event_to_window": bool(first_bone),
        "first_bone_event_date": first_bone,
        "death_to_window": bool(death_date and _date_lte(death_date, cutoff_date)),
        "date_of_death": death_date or None,
        "survival_status_available": bool(identity.get("vital_status") or identity.get("last_contact_date") or identity.get("date_of_death")),
        "referral_delay_days": referral.get("referral_delay_days"),
        "epidemiology_gap_reviews": _latest_epidemiology_gap_reviews(patient_events),
    }


def _events_matching(events: list[dict[str, Any]], tokens: tuple[str, ...]) -> list[dict[str, Any]]:
    matched = []
    for event in events:
        event_type = str(event.get("event_type") or "").lower()
        payload = event.get("payload") or {}
        payload_type = str(payload.get("anchor_type") or payload.get("event_type") or "").lower()
        if any(token in event_type or token in payload_type for token in tokens):
            matched.append(event)
    return matched


def _latest_epidemiology_gap_reviews(events: list[dict[str, Any]]) -> dict[str, Any]:
    reviews: dict[str, Any] = {}
    for event in events:
        if str(event.get("event_type") or "") != EPIDEMIOLOGY_GAP_REVIEW_EVENT_TYPE:
            continue
        payload = event.get("payload") or {}
        gap_key = str(payload.get("gap_key") or "").strip()
        if not gap_key:
            continue
        reviews[gap_key] = {
            "event_id": event.get("id"),
            "closure_status": payload.get("closure_status") or event.get("status") or "",
            "clinical_note": payload.get("clinical_note") or "",
            "reviewed_by": payload.get("reviewed_by") or "",
            "next_followup_date": payload.get("next_followup_date") or "",
            "detected_at": payload.get("detected_at") or "",
            "detection_anchor": payload.get("detection_anchor") or "",
            "target_weeks": payload.get("target_weeks") or "",
            "regimen_code": payload.get("regimen_code") or "",
            "molecule": payload.get("molecule") or "",
            "selected_action_key": payload.get("selected_action_key") or "",
            "assigned_to": payload.get("assigned_to") or "",
            "owner_role": payload.get("owner_role") or "",
            "due_date": payload.get("due_date") or "",
            "sla_days": payload.get("sla_days") or "",
            "sla_policy": payload.get("sla_policy") or "",
            "acknowledged_missing_fields": payload.get("acknowledged_missing_fields") or [],
            "reviewed_at": payload.get("reviewed_at") or event.get("created_at") or event.get("event_date") or "",
        }
        reviews[gap_key]["review_latency_days"] = _nonnegative_days_between(
            reviews[gap_key].get("detected_at"),
            reviews[gap_key].get("reviewed_at"),
        )
    return reviews


def _first_event_date(events: list[dict[str, Any]], *, cutoff_date: str) -> str | None:
    dates = []
    for event in events:
        payload = event.get("payload") or {}
        event_date = (
            str(event.get("event_date") or "")[:10]
            or str(payload.get("anchor_date") or "")[:10]
            or str(payload.get("event_date") or "")[:10]
        )
        if event_date and _date_lte(event_date, cutoff_date):
            dates.append(event_date)
    return sorted(dates)[0] if dates else None


def _date_lte(value: str, cutoff: str) -> bool:
    if not value:
        return False
    if not cutoff:
        return True
    try:
        return date.fromisoformat(str(value)[:10]) <= date.fromisoformat(str(cutoff)[:10])
    except ValueError:
        return False


def _baseline_state_for_row(
    row: dict[str, Any],
    *,
    prior_history: dict[str, Any],
    treatment: dict[str, Any],
    baseline: dict[str, Any],
    identity: dict[str, Any],
) -> dict[str, str]:
    state = (
        prior_history.get("current_state")
        or prior_history.get("assessment_state")
        or treatment.get("line_of_therapy_context")
        or row.get("line_of_therapy_context")
        or "unknown_state"
    )
    psa = _safe_float(row.get("baseline_psa"), None)
    ecog = _safe_int(row.get("baseline_ecog"), None)
    psa_band = (
        "psa_unknown" if psa is None
        else "psa_lt20" if psa < 20
        else "psa_20_99" if psa < 100
        else "psa_ge100"
    )
    ecog_band = (
        "ecog_unknown" if ecog is None
        else "ecog_0_1" if ecog <= 1
        else "ecog_ge2"
    )
    age = _age_at(identity.get("dob"), treatment.get("start_date") or row.get("line_start_date"))
    age_band = (
        "age_unknown" if age is None
        else "age_lt65" if age < 65
        else "age_65_74" if age < 75
        else "age_ge75"
    )
    metastatic_volume = str(baseline.get("volume_disease") or "").strip() or "volume_unknown"
    metastasis_site = str(baseline.get("metastasis_site") or baseline.get("m_substage_resolved") or "").strip() or "metastasis_unknown"
    comorbidity_count = _comorbidity_count(baseline.get("comorbidities"))
    comorbidity_band = (
        "comorbidity_unknown" if comorbidity_count is None
        else "comorbidity_0" if comorbidity_count == 0
        else "comorbidity_1_2" if comorbidity_count <= 2
        else "comorbidity_ge3"
    )
    line_context = str(treatment.get("line_of_therapy_context") or row.get("line_of_therapy_context") or "")
    disease_context = str(state or line_context or "unknown_state")
    return {
        "clinical_state": disease_context,
        "line_context": line_context,
        "psa_band": psa_band,
        "ecog_band": ecog_band,
        "age_band": age_band,
        "metastatic_volume": metastatic_volume,
        "metastasis_site": metastasis_site,
        "comorbidity_band": comorbidity_band,
        "bucket": "|".join([
            disease_context,
            line_context or "no_line_context",
            psa_band,
            ecog_band,
            age_band,
            metastatic_volume,
            comorbidity_band,
        ]),
    }


def _baseline_bucket_weights(rows: list[dict[str, Any]]) -> dict[str, float]:
    buckets = [str(row.get("baseline_state_bucket") or "unknown") for row in rows]
    total = len(buckets)
    if not total:
        return {}
    counts = Counter(buckets)
    return {bucket: count / total for bucket, count in counts.items()}


def _latest_window_rows(rows_by_week: Mapping[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    numeric_weeks = sorted(int(key) for key in rows_by_week.keys() if str(key).isdigit())
    if not numeric_weeks:
        return []
    for week in reversed(numeric_weeks):
        rows = list(rows_by_week.get(str(week), []))
        if rows:
            return rows
    return list(rows_by_week.get(str(numeric_weeks[-1]), []))


def _baseline_adjusted_metrics(
    rows: list[dict[str, Any]],
    overall_weights: dict[str, float],
) -> dict[str, Any]:
    metric_specs = {
        "psa50_rate": "psa50_response",
        "psa90_rate": "psa90_response",
        "ecog_improvement_rate": "ecog_improved",
        "discontinuation_rate": "discontinued_by_window",
        "high_grade_toxicity_rate": "high_grade_toxicity_to_window",
    }
    adjusted: dict[str, Any] = {
        "method": "direct_standardization_by_baseline_state_bucket",
        "standard_bucket_weights": overall_weights,
        "metrics": {},
    }
    for metric_name, field in metric_specs.items():
        value, coverage = _direct_standardized_rate(rows, field, overall_weights)
        adjusted["metrics"][metric_name] = {
            "adjusted_rate": value,
            "weight_coverage": coverage,
            "display": "—" if value is None else f"{round(value * 100, 1)}%",
        }
    return adjusted


def _direct_standardized_rate(
    rows: list[dict[str, Any]],
    field: str,
    overall_weights: dict[str, float],
) -> tuple[float | None, float]:
    if not rows or not overall_weights:
        return None, 0.0
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("baseline_state_bucket") or "unknown")].append(row)
    weighted_sum = 0.0
    covered_weight = 0.0
    for bucket, standard_weight in overall_weights.items():
        bucket_rows = [row for row in grouped.get(bucket, []) if row.get(field) is not None]
        if not bucket_rows:
            continue
        rate = sum(1 for row in bucket_rows if row.get(field) is True) / len(bucket_rows)
        weighted_sum += standard_weight * rate
        covered_weight += standard_weight
    if covered_weight == 0:
        return None, 0.0
    return round(weighted_sum / covered_weight, 4), round(covered_weight, 4)


def _arpi_label_for_regimen(regimen_code: Any) -> str:
    label = _classify_arpi(str(regimen_code or ""))
    if label:
        return label
    intensity = regimen_intensity(regimen_code)
    for agent in intensity.get("agents") or []:
        label = _classify_arpi(str(agent))
        if label:
            return label
    return ""


def _row_matches_metric_filter(row: Mapping[str, Any], metric: str) -> bool:
    if metric == "psa50":
        return row.get("psa50_response") is True
    if metric == "psa90":
        return row.get("psa90_response") is True
    if metric == "non_response":
        return row.get("response_evaluable") is True and row.get("psa50_response") is False
    if metric == "ecog_improved":
        return row.get("ecog_improved") is True
    if metric == "toxicity_g3":
        return row.get("high_grade_toxicity_to_window") is True
    if metric == "hospitalization":
        return row.get("hospitalization_toxicity_to_window") is True
    if metric == "referral_delay":
        return bool(_safe_int(row.get("referral_delay_days"), 0) and _safe_int(row.get("referral_delay_days"), 0) > 0)
    if metric == "discontinuation":
        return row.get("discontinued_by_window") is True
    if metric == "bone_event":
        return row.get("bone_event_to_window") is True
    if metric == "death":
        return row.get("death_to_window") is True
    return True


def _parse_cost_source(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _age_at(dob: Any, anchor_date: Any) -> int | None:
    try:
        dob_date = date.fromisoformat(str(dob)[:10])
        anchor = date.fromisoformat(str(anchor_date)[:10]) if anchor_date else date.today()
    except (TypeError, ValueError):
        return None
    years = anchor.year - dob_date.year - ((anchor.month, anchor.day) < (dob_date.month, dob_date.day))
    return years if years >= 0 else None


def _comorbidity_count(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, list):
        return len([item for item in value if item])
    if isinstance(value, dict):
        if not value:
            return None
        return sum(1 for item in value.values() if item not in (None, "", False, [], {}))
    text = str(value).strip()
    if not text:
        return None
    return len([item for item in text.replace(";", ",").split(",") if item.strip()])


def _coverage_status(value: float | None) -> str:
    if value is None:
        return "no_data"
    if value >= 90:
        return "research_ready"
    if value >= 75:
        return "auditable"
    if value >= 50:
        return "needs_capture"
    return "not_ready"


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int | None = 0) -> int | None:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _sorted_iso_dates(values: Any) -> list[str]:
    dates: list[str] = []
    for value in values or []:
        text = str(value or "")[:10]
        if not text:
            continue
        try:
            date.fromisoformat(text)
        except ValueError:
            continue
        dates.append(text)
    return sorted(dates)


def _latency_stats(values: list[int]) -> dict[str, int | None]:
    clean = sorted(int(value) for value in values if value is not None)
    if not clean:
        return {"median_days": None, "p90_days": None, "max_days": None}
    mid = len(clean) // 2
    if len(clean) % 2:
        median = clean[mid]
    else:
        median = round((clean[mid - 1] + clean[mid]) / 2)
    p90_index = min(len(clean) - 1, max(0, int(round((len(clean) - 1) * 0.9))))
    return {
        "median_days": median,
        "p90_days": clean[p90_index],
        "max_days": clean[-1],
    }


def _nonnegative_days_between(start: Any, end: Any) -> int | None:
    days = _days_between(str(start or "")[:10], str(end or "")[:10])
    if days is None:
        return None
    return max(days, 0)


def _days_between(start: str, end: str) -> int | None:
    try:
        return (date.fromisoformat(str(end)[:10]) - date.fromisoformat(str(start)[:10])).days
    except (TypeError, ValueError):
        return None


def _add_days(value: Any, days: int | None) -> str | None:
    try:
        return (date.fromisoformat(str(value or "")[:10]) + timedelta(days=int(days or 0))).isoformat()
    except (TypeError, ValueError):
        return None


def _derive_gap_sla_state(*, closure_status: str, audit_state: str, days_to_due: int | None) -> str:
    if closure_status == "not_applicable":
        return "not_applicable"
    if days_to_due is None:
        return "sla_unknown"
    suffix = "reviewed_still_missing" if audit_state == "reviewed_still_missing" else "unreviewed"
    if days_to_due < 0:
        return f"overdue_{suffix}"
    if days_to_due <= 3:
        return f"due_soon_{suffix}"
    if audit_state == "reviewed_still_missing":
        return "reviewed_pending_capture"
    return "on_track_unreviewed"


__all__ = [
    "aggregate_arpi_value_by_response",
    "build_epidemiology_command_center",
    "build_patient_epidemiology_gap_sla",
    "build_treatment_value_research_pack",
    "build_treatment_value_registry",
    "build_treatment_value_registry_rows",
    "build_arpi_value_patient_rows",
]
