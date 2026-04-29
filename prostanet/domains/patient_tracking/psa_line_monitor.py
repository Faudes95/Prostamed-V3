from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from prostanet.domains.patient_tracking.therapy_catalog import regimen_label

LINE_COLORS = [
    "rgba(59, 130, 246, 0.12)",
    "rgba(16, 185, 129, 0.12)",
    "rgba(245, 158, 11, 0.12)",
    "rgba(236, 72, 153, 0.12)",
    "rgba(168, 85, 247, 0.12)",
    "rgba(14, 165, 233, 0.12)",
]

LINE_CONTEXT_LABELS = {
    "mHSPC_initial": "mHSPC inicial",
    "mHSPC_post_docetaxel": "mHSPC post-docetaxel",
    "m0_CRPC_first_line": "m0 CRPC primera línea",
    "mCRPC_first_line": "mCRPC primera línea",
    "mCRPC_post_ARPI_pre_taxane": "mCRPC post-ARPI pre-taxano",
    "mCRPC_post_taxane": "mCRPC post-taxano",
    "mCRPC_post_PARP": "mCRPC post-PARP",
    "mCRPC_post_Lu177": "mCRPC post-Lu177",
    "later_line": "Líneas posteriores",
}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No realizado", "Desconocido", "Desconocida")


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _fmt_date(value: date | None) -> str:
    return value.isoformat() if value else ""


def _line_label(number: Any, context: Any, scheme: Any) -> str:
    number_label = f"L{number}" if _is_present(number) else "Línea"
    context_label = LINE_CONTEXT_LABELS.get(str(context or ""), context or "")
    scheme_label = regimen_label(scheme) if _is_present(scheme) else ""
    if context_label and scheme_label:
        return f"{number_label} · {context_label} · {scheme_label}"
    if context_label:
        return f"{number_label} · {context_label}"
    if scheme_label:
        return f"{number_label} · {scheme_label}"
    return number_label


def _extract_psa_points(patient: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Extract PSA timeline para torre de vigilancia.

    LXC fix B1: usa `psa_unified.unified_psa_timeline()` como fuente autoritativa.
    Ventajas:
      - baseline_psa del intake siempre se auto-seedea como punto Dx (idempotente)
      - biomarker_longitudinal rows se merguean correctamente
      - follow_ups legacy psa_current se incluyen como fallback solo si vacío
      - Una sola fuente → torre de vigilancia inicia desde Dx siempre
    """
    # Try unified source first (LXC fix B1)
    try:
        from prostanet.shared.psa_unified import unified_psa_timeline
        unified = unified_psa_timeline(patient)
        if unified:
            points = []
            for u in unified:
                v = _safe_float(u.get("value"))
                if v is None or not u.get("date"):
                    continue
                points.append({
                    "date": str(u["date"])[:10],
                    "psa": v,
                    "source": u.get("source") or "psa_unified",
                })
            if points:
                # Deduplicate by (date, value) — preserves locked baseline + longitudinal merge
                deduped = {}
                for p in points:
                    deduped[(p["date"], p["psa"])] = p
                # Determine canonical source label
                sources = {p["source"] for p in deduped.values()}
                if "intake_baseline (auto-seed unified)" in sources and len(sources) > 1:
                    canonical = "psa_unified (baseline + longitudinal)"
                elif "biomarker_longitudinal" in sources:
                    canonical = "biomarker_longitudinal"
                else:
                    canonical = next(iter(sources), "psa_unified")
                return sorted(deduped.values(), key=lambda item: item["date"]), canonical
    except ImportError:
        pass  # fallback below

    # Fallback (legacy path — only reached if psa_unified import fails)
    biomarker_rows = [
        row
        for row in (patient.get("biomarker_longitudinal") or [])
        if str(row.get("biomarker_type") or "").upper() == "PSA" and _is_present(row.get("value")) and _is_present(row.get("sample_date"))
    ]
    if biomarker_rows:
        points = [
            {"date": str(row.get("sample_date"))[:10],
             "psa": _safe_float(row.get("value")),
             "source": "biomarker_longitudinal"}
            for row in biomarker_rows
            if _safe_float(row.get("value")) is not None
        ]
        return sorted(points, key=lambda item: item["date"]), "biomarker_longitudinal"

    points = []
    baseline_psa = (patient.get("baseline") or {}).get("baseline_psa")
    diagnosis_date = (patient.get("identity") or {}).get("diagnosis_date")
    if _is_present(baseline_psa) and _is_present(diagnosis_date):
        points.append({
            "date": str(diagnosis_date)[:10],
            "psa": _safe_float(baseline_psa),
            "source": "clinical_baseline",
        })
    for visit in patient.get("follow_ups") or []:
        psa_value = _safe_float(visit.get("psa_current"))
        if psa_value is None or not _is_present(visit.get("visit_date")):
            continue
        points.append({
            "date": str(visit.get("visit_date"))[:10],
            "psa": psa_value,
            "source": "follow_up_visits",
        })
    deduped = {}
    for point in points:
        deduped[(point["date"], point["psa"])] = point
    return sorted(deduped.values(), key=lambda item: item["date"]), "follow_up_visits" if points else "missing"


def _extract_treatment_bands(patient: dict[str, Any], points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    treatments = [
        row
        for row in (patient.get("treatments") or [])
        if _is_present(row.get("start_date")) and any(
            _is_present(row.get(field))
            for field in ("line_of_therapy_number", "line_of_therapy_context", "drug_scheme", "current_treatment")
        )
    ]
    if not treatments:
        return []

    treatments = sorted(treatments, key=lambda item: str(item.get("start_date")))
    point_dates = [_parse_iso_date(point.get("date")) for point in points if point.get("date")]
    last_known_date = max([item for item in point_dates if item is not None], default=date.today())
    bands = []
    for index, treatment in enumerate(treatments):
        start_date = _parse_iso_date(treatment.get("start_date"))
        if not start_date:
            continue
        explicit_end = _parse_iso_date(treatment.get("end_date"))
        next_start = _parse_iso_date(treatments[index + 1].get("start_date")) if index + 1 < len(treatments) else None
        if explicit_end:
            end_date = explicit_end
        elif next_start:
            end_date = next_start - timedelta(days=1)
        else:
            end_date = last_known_date
        label = _line_label(
            treatment.get("line_of_therapy_number"),
            treatment.get("line_of_therapy_context"),
            treatment.get("drug_scheme") or treatment.get("current_treatment"),
        )
        scheme = treatment.get("drug_scheme") or treatment.get("current_treatment") or ""
        # LXC.1.1 — Clasificación tipo línea: ADT solo / Doblete / Triplete
        line_type = _classify_line_type(scheme)
        bands.append(
            {
                "start_date": _fmt_date(start_date),
                "end_date": _fmt_date(end_date),
                "line_of_therapy_number": treatment.get("line_of_therapy_number"),
                "line_of_therapy_context": treatment.get("line_of_therapy_context"),
                "drug_scheme": scheme,
                "drug_scheme_label": regimen_label(scheme),
                "line_type": line_type["category"],  # adt_solo|doblete|triplete|otro
                "line_type_label": line_type["label"],  # human-readable
                "components_count": line_type["components_count"],
                "label": label,
                "color": LINE_COLORS[index % len(LINE_COLORS)],
                "source": "treatment_history",
            }
        )
    return bands


def _classify_line_type(drug_scheme: str | None) -> dict[str, Any]:
    """Categoriza línea tx en ADT-solo / Doblete / Triplete / Otro.

    Heurística basada en componentes en el scheme code:
      ADT solo                       → 'ADT_LHRH', 'ADT_DEGARELIX', etc.
      Doblete (ADT+ARPI)             → 'ADT_ENZALUTAMIDE', 'ADT_ABIRATERONE', etc.
      Doblete (ADT+Doce)             → 'ADT_DOCETAXEL'
      Triplete (ADT+ARPI+Doce)       → 'ADT_DAROLUTAMIDE_DOCETAXEL' (ARASENS)
                                       'ADT_ABIRATERONE_DOCETAXEL' (PEACE-1)
      Post-mCRPC mono                → 'OLAPARIB', 'CABAZITAXEL', etc.
    """
    if not drug_scheme:
        return {"category": "otro", "label": "Sin clasificar", "components_count": 0}
    s = str(drug_scheme).upper()

    # ARPIs
    arpis = ["ENZALUTAMIDE", "ABIRATERONE", "APALUTAMIDE", "DAROLUTAMIDE"]
    has_adt = "ADT" in s or "LHRH" in s or "DEGARELIX" in s or "ORCHIECTOMY" in s
    has_arpi = any(a in s for a in arpis)
    has_doce = "DOCETAXEL" in s
    has_caba = "CABAZITAXEL" in s
    has_parp = "OLAPARIB" in s or "TALAZOPARIB" in s or "NIRAPARIB" in s or "RUCAPARIB" in s
    has_radio = "LU177" in s or "RA223" in s or "LUTECIO" in s

    if has_adt and has_arpi and has_doce:
        return {"category": "triplete", "label": "Triplete (ADT+ARPI+Docetaxel)",
                "components_count": 3, "evidence_trial": "ARASENS / PEACE-1"}
    if has_adt and has_arpi:
        return {"category": "doblete", "label": "Doblete (ADT+ARPI)",
                "components_count": 2, "evidence_trial": "ENZAMET / TITAN / LATITUDE / ARCHES"}
    if has_adt and has_doce:
        return {"category": "doblete", "label": "Doblete (ADT+Docetaxel)",
                "components_count": 2, "evidence_trial": "CHAARTED / STAMPEDE"}
    if has_adt and not (has_arpi or has_doce):
        return {"category": "adt_solo", "label": "ADT solo",
                "components_count": 1, "evidence_trial": "Standard ADT"}
    if has_caba:
        return {"category": "post_mcrpc_taxano", "label": "Cabazitaxel (post-mCRPC)",
                "components_count": 1, "evidence_trial": "CARD / TROPIC"}
    if has_parp:
        return {"category": "post_mcrpc_parp", "label": "PARP inhibitor",
                "components_count": 1, "evidence_trial": "PROfound / TRITON3 / MAGNITUDE"}
    if has_radio:
        return {"category": "radiopharm", "label": "Radiopharm (Lu-177 / Ra-223)",
                "components_count": 1, "evidence_trial": "VISION / TheraP / ALSYMPCA"}
    return {"category": "otro", "label": str(drug_scheme), "components_count": 0}


def _calculate_per_line_granular_kinetics(
    segment_points: list[dict[str, Any]],
    baseline_psa: float | None,
    nadir_psa: float | None,
    start_date: date,
) -> dict[str, Any]:
    """Faubot 2026-04-25 (LXVI) — Auditoría #63C.

    Calcula métricas kinetics granulares por treatment line:

    - `time_to_nadir_months`: meses desde inicio línea hasta nadir
    - `duration_response_months`: meses desde nadir hasta progresión PSA
        (definida como rebote ≥25% desde nadir o >2 ng/mL absoluto)
    - `psadt_during_progression`: PSADT calculado SOLO sobre la fase
        de progresión post-nadir (más clínicamente relevante para BCR/CRPC
        que el PSADT global de la línea, que mezcla respuesta + progresión)
    - `kinetics_classification`: clasificación clínica per-line:
        `response` (best_pct_change ≤ -50, sin progresión)
        `partial_response` (best_pct_change ≤ -30, sin progresión)
        `stable` (best_pct_change > -30 y < +25, sin progresión PSADT)
        `progression` (rebote post-nadir documentado)
        `insufficient_data` (<2 points)

    Sin estos cálculos granulares, todas las métricas kinetics se aplican
    al rango completo [start, end], confundiendo respuesta inicial con
    progresión tardía. Por línea es la unidad clínica correcta para
    decisiones de cambio terapéutico.
    """
    result = {
        "time_to_nadir_months": None,
        "duration_response_months": None,
        "psadt_during_progression": None,
        "kinetics_classification": "insufficient_data",
    }
    if not segment_points or baseline_psa is None or nadir_psa is None:
        return result
    if len(segment_points) < 2:
        return result

    valid_points = [
        p for p in segment_points
        if _is_present(p.get("psa")) and _parse_iso_date(p.get("date")) is not None
    ]
    if len(valid_points) < 2:
        return result

    # Encontrar nadir point (primer point con psa == nadir_psa)
    nadir_point = next(
        (p for p in valid_points if p.get("psa") == nadir_psa),
        None,
    )
    if nadir_point is None:
        return result
    nadir_date = _parse_iso_date(nadir_point.get("date"))
    if nadir_date is None:
        return result

    # time_to_nadir_months
    days_to_nadir = (nadir_date - start_date).days
    result["time_to_nadir_months"] = round(days_to_nadir / 30.4375, 2)

    # Identificar fase post-nadir (progresión potencial)
    post_nadir_points = [
        p for p in valid_points
        if _parse_iso_date(p.get("date")) > nadir_date
    ]

    # Definición de progresión PSA: rebote ≥25% desde nadir O >2 ng/mL absoluto
    # (criterio PCWG3 simplificado)
    progression_threshold = max(nadir_psa * 1.25, nadir_psa + 2.0)
    progression_points = [
        p for p in post_nadir_points
        if p.get("psa") >= progression_threshold
    ]

    has_progression = len(progression_points) >= 1

    # duration_response_months (nadir → 1ra evidencia de progresión)
    if has_progression:
        first_prog_date = _parse_iso_date(progression_points[0].get("date"))
        days_response = (first_prog_date - nadir_date).days
        result["duration_response_months"] = round(days_response / 30.4375, 2)
    elif post_nadir_points:
        # No progresión documentada; duración respuesta = hasta último point
        last_post_date = _parse_iso_date(post_nadir_points[-1].get("date"))
        days_response = (last_post_date - nadir_date).days
        result["duration_response_months"] = round(days_response / 30.4375, 2)

    # PSADT durante fase de progresión (post-nadir + prog points)
    if len(progression_points) >= 2:
        try:
            from clinical_scores import calculate_psa_kinetics  # noqa
            prog_kinetics = calculate_psa_kinetics(
                [(p.get("date"), p.get("psa")) for p in progression_points]
            )
            result["psadt_during_progression"] = prog_kinetics.get("psadt")
        except (ImportError, Exception):
            pass
    elif len(progression_points) == 1 and len(post_nadir_points) >= 2:
        # Si solo 1 point ≥ threshold pero ≥2 post-nadir, calcular PSADT
        # sobre todos los post-nadir (más conservador)
        try:
            from clinical_scores import calculate_psa_kinetics  # noqa
            post_kinetics = calculate_psa_kinetics(
                [(p.get("date"), p.get("psa")) for p in post_nadir_points]
            )
            result["psadt_during_progression"] = post_kinetics.get("psadt")
        except (ImportError, Exception):
            pass

    # Clasificación clínica per-line
    if baseline_psa > 0:
        best_pct = ((nadir_psa - baseline_psa) / baseline_psa) * 100
    else:
        best_pct = 0
    if has_progression:
        result["kinetics_classification"] = "progression"
    elif best_pct <= -50:
        result["kinetics_classification"] = "response"
    elif best_pct <= -30:
        result["kinetics_classification"] = "partial_response"
    elif best_pct < 25:
        result["kinetics_classification"] = "stable"
    else:
        # Aumento ≥25% sin nadir respuesta — primary refractory
        result["kinetics_classification"] = "primary_refractory"
    return result


def _segment_points_by_line(points: list[dict[str, Any]], bands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from clinical_scores import calculate_psa_kinetics

    segments = []
    for band in bands:
        start_date = _parse_iso_date(band.get("start_date"))
        end_date = _parse_iso_date(band.get("end_date"))
        if not start_date:
            continue
        segment_points = [
            point
            for point in points
            if _parse_iso_date(point.get("date")) and start_date <= _parse_iso_date(point.get("date")) <= (end_date or date.today())
        ]
        values = [point.get("psa") for point in segment_points if _is_present(point.get("psa"))]
        baseline_psa = values[0] if values else None
        nadir_psa = min(values) if values else None
        current_psa = values[-1] if values else None
        best_pct_change = None
        if baseline_psa not in (None, 0) and nadir_psa is not None:
            best_pct_change = ((nadir_psa - baseline_psa) / baseline_psa) * 100
        kinetics = calculate_psa_kinetics(
            [(point.get("date"), point.get("psa")) for point in segment_points if point.get("date") and _is_present(point.get("psa"))]
        ) if len(segment_points) >= 2 else {}
        # Faubot LXVI #63C — Granular per-line kinetics
        granular = _calculate_per_line_granular_kinetics(
            segment_points=segment_points,
            baseline_psa=baseline_psa,
            nadir_psa=nadir_psa,
            start_date=start_date,
        )
        segments.append(
            {
                **band,
                "baseline_psa": baseline_psa,
                "nadir_psa": nadir_psa,
                "current_psa": current_psa,
                "best_pct_change": round(best_pct_change, 1) if best_pct_change is not None else None,
                "psa50_achieved": bool(best_pct_change is not None and best_pct_change <= -50),
                "psa_velocity": kinetics.get("velocity"),
                "psadt": kinetics.get("psadt"),
                "point_count": len(segment_points),
                # Faubot LXVI #63C — métricas granulares per-line
                "time_to_nadir_months": granular["time_to_nadir_months"],
                "duration_response_months": granular["duration_response_months"],
                "psadt_during_progression": granular["psadt_during_progression"],
                "kinetics_classification": granular["kinetics_classification"],
            }
        )
    return segments


def _annotate_points_with_treatment_line(
    points: list[dict[str, Any]],
    bands: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Faubot 2026-04-25 (LXV) — Auditoría #63B.

    Auto-asigna a cada PSA point su `treatment_line_number` +
    `treatment_line_label` + `treatment_band_index` + `treatment_color`
    basado en la fecha del point dentro del rango [start_date, end_date]
    de cada banda. Si el point cae fuera de cualquier banda, se etiqueta
    como `pretreatment` (antes de la 1ra línea) o `between_lines`
    (gap temporal). Esto habilita drill-down per treatment line en el
    chart Chart.js sin lógica adicional de filtrado client-side.

    El point original NUNCA se muta; siempre se retorna copia. Esto
    preserva inmutabilidad clínica del payload entrante.
    """
    if not points:
        return []
    if not bands:
        # Sin bandas: marcar todos los points como sin línea documentada
        return [
            {
                **point,
                "treatment_line_number": None,
                "treatment_line_label": "Sin línea documentada",
                "treatment_band_index": None,
                "treatment_color": None,
                "treatment_assignment_origin": "no_bands",
            }
            for point in points
        ]

    # Pre-cómputo de rangos de fechas por banda (parseo único)
    band_ranges: list[tuple[date | None, date | None, dict[str, Any], int]] = []
    for index, band in enumerate(bands):
        start = _parse_iso_date(band.get("start_date"))
        end = _parse_iso_date(band.get("end_date"))
        band_ranges.append((start, end, band, index))

    annotated: list[dict[str, Any]] = []
    for point in points:
        point_date = _parse_iso_date(point.get("date"))
        if point_date is None:
            annotated.append(
                {
                    **point,
                    "treatment_line_number": None,
                    "treatment_line_label": "Fecha inválida",
                    "treatment_band_index": None,
                    "treatment_color": None,
                    "treatment_assignment_origin": "invalid_date",
                }
            )
            continue

        # Buscar banda que contiene la fecha del point
        matched_band: dict[str, Any] | None = None
        matched_index: int | None = None
        for start, end, band, idx in band_ranges:
            if start is None:
                continue
            band_end = end or date.today()
            if start <= point_date <= band_end:
                matched_band = band
                matched_index = idx
                break

        if matched_band is not None:
            annotated.append(
                {
                    **point,
                    "treatment_line_number": matched_band.get("line_of_therapy_number"),
                    "treatment_line_label": matched_band.get("label", ""),
                    "treatment_band_index": matched_index,
                    "treatment_color": matched_band.get("color"),
                    "treatment_assignment_origin": "auto_by_date",
                }
            )
        else:
            # Point fuera de cualquier banda: clasificar como pretreatment
            # o between_lines según posición temporal
            first_band_start = next(
                (rng[0] for rng in band_ranges if rng[0] is not None), None
            )
            if first_band_start is not None and point_date < first_band_start:
                origin = "pretreatment"
                label = "Pretratamiento"
            else:
                origin = "between_lines"
                label = "Entre líneas (gap)"
            annotated.append(
                {
                    **point,
                    "treatment_line_number": None,
                    "treatment_line_label": label,
                    "treatment_band_index": None,
                    "treatment_color": None,
                    "treatment_assignment_origin": origin,
                }
            )
    return annotated


def build_psa_by_treatment_line(patient: dict[str, Any]) -> dict[str, Any]:
    try:
        from clinical_scores import calculate_psa_kinetics
    except Exception:
        calculate_psa_kinetics = _fallback_psa_kinetics

    points, source = _extract_psa_points(patient)
    if not points:
        return {
            "has_data": False,
            "points": [],
            "treatment_bands": [],
            "line_segments": [],
            "line_events": [],
            "metrics": {},
            "source": source,
        }

    bands = _extract_treatment_bands(patient, points)
    # Faubot LXV #63B — anotar cada point con su treatment line por fecha
    annotated_points = _annotate_points_with_treatment_line(points, bands)
    segments = _segment_points_by_line(points, bands)
    kinetics = calculate_psa_kinetics(
        [(point.get("date"), point.get("psa")) for point in points if point.get("date") and _is_present(point.get("psa"))]
    )
    psa_values = [point.get("psa") for point in points if _is_present(point.get("psa"))]
    line_events = [
        {
            "date": segment.get("start_date"),
            "title": segment.get("label"),
            "decision": "Inicio o cambio de línea terapéutica",
            "origin": "treatment_history",
            "line_of_therapy_number": segment.get("line_of_therapy_number"),
            "line_of_therapy_context": segment.get("line_of_therapy_context"),
        }
        for segment in segments
    ]
    # Faubot LXV #63B — points_by_line: estructura drill-down ready para chart
    points_by_line: dict[str, list[dict[str, Any]]] = {}
    for point in annotated_points:
        line_key = (
            str(point.get("treatment_line_number"))
            if point.get("treatment_line_number") is not None
            else point.get("treatment_assignment_origin", "unassigned")
        )
        points_by_line.setdefault(line_key, []).append(point)
    return {
        "has_data": True,
        "points": annotated_points,
        "treatment_bands": bands,
        "line_segments": segments,
        "line_events": line_events,
        # Faubot LXV #63B — drill-down structure
        "points_by_line": points_by_line,
        "metrics": {
            "current_psa": psa_values[-1] if psa_values else None,
            "nadir_psa": min(psa_values) if psa_values else None,
            "psa_velocity": kinetics.get("velocity"),
            "psadt": kinetics.get("psadt"),
            "interpretation": kinetics.get("interpretation"),
            "current_line_label": segments[-1].get("label") if segments else "",
            # Faubot LXV #63B — métricas adicionales drill-down
            "lines_with_points_count": len([k for k, v in points_by_line.items() if v]),
            "points_pretreatment_count": len(points_by_line.get("pretreatment", [])),
            "points_between_lines_count": len(points_by_line.get("between_lines", [])),
        },
        "source": source,
    }


def _fallback_psa_kinetics(points: list[tuple[Any, Any]]) -> dict[str, Any]:
    """Small local fallback used when the large scoring module is unavailable.

    The canonical implementation still lives in `clinical_scores.py`; this
    preserves the PSA tower when that module is temporarily not materialized by
    the filesystem provider.
    """
    parsed: list[tuple[date, float]] = []
    for raw_date, raw_value in points:
        point_date = _parse_iso_date(raw_date)
        value = _safe_float(raw_value)
        if point_date is not None and value is not None:
            parsed.append((point_date, value))
    parsed.sort(key=lambda item: item[0])
    if len(parsed) < 2:
        return {"velocity": None, "psadt": None, "interpretation": "insufficient_data"}

    first_date, first_value = parsed[0]
    last_date, last_value = parsed[-1]
    elapsed_years = max((last_date - first_date).days / 365.25, 0.001)
    velocity = (last_value - first_value) / elapsed_years
    psadt = None
    if first_value > 0 and last_value > first_value:
        import math

        elapsed_months = max((last_date - first_date).days / 30.4375, 0.001)
        psadt = elapsed_months * math.log(2) / math.log(last_value / first_value)
    if psadt is not None and psadt <= 10:
        interpretation = "high_risk_rising_psa"
    elif velocity > 0:
        interpretation = "rising_psa"
    else:
        interpretation = "stable_or_declining_psa"
    return {"velocity": velocity, "psadt": psadt, "interpretation": interpretation}
