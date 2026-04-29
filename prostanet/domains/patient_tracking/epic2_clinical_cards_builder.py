"""EPIC 2 — Tarjetas clínicas del perfil oficial.

Produce cinco tarjetas para `profile_compass` que exponen los campos mínimos
introducidos en EPIC 2:

* Función renal basal (CKD-EPI 2021 + KDIGO)
* Marcadores pronósticos Halabi (albúmina, LDH, hemoglobina, ALP)
* Terapia de privación androgénica (fecha inicio, agente, intención)
* Medicamentos estructurados (+ resumen CYP)
* Genomic classifiers con score numérico (Decipher/Prolaris/Oncotype)
* Germline vs. somático (detonante NCCN PROS-H)
* Sitios viscerales discriminados (Halabi HR pulmón vs hígado)

Las tarjetas usan el mismo contrato que ``stage_specific_panels``
(title, subtitle, items[{label,value,detail,evidence_status}],
missing_inputs, bullets, sources, updated_at) para renderizar sin cambios
en ``patient_profile.html``.

Referencias:
  * Inker LA et al. NEJM 2021;385:1737 (CKD-EPI 2021, sin raza).
  * Halabi S et al. JCO 2014;32:671 (IPS mCRPC).
  * Spratt DE et al. JCO 2018;36:581 (Decipher).
  * NCCN PROS-H Version 5.2026 (germline testing triggers).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

from prostanet.shared.genomic_classifier_scores import classify_genomic_score
from prostanet.shared.medication_list import (
    normalize_medication_list,
    summarize_medication_list,
)
from prostanet.shared.renal_function import compute_egfr


# ──────────────────────────────────────────────────────────────────────
# Helpers locales
# ──────────────────────────────────────────────────────────────────────


def _safe_float(value: Any) -> float | None:
    if value in (None, "", "None"):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _safe_date(value: Any) -> date | None:
    if value in (None, "", "None"):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _months_between(start: date | None, ref: date | None = None) -> int | None:
    if start is None:
        return None
    today = ref or date.today()
    months = (today.year - start.year) * 12 + (today.month - start.month)
    if today.day < start.day:
        months -= 1
    return max(0, months)


def _patient_lookup(patient: dict[str, Any], *keys: str) -> Any:
    """Busca la primera clave presente en patient, latest_labs o baseline."""
    for key in keys:
        if patient.get(key) not in (None, "", []):
            return patient.get(key)
    latest = patient.get("latest_labs") or {}
    if isinstance(latest, dict):
        for key in keys:
            if latest.get(key) not in (None, "", []):
                return latest.get(key)
    baseline = patient.get("baseline") or {}
    if isinstance(baseline, dict):
        for key in keys:
            if baseline.get(key) not in (None, "", []):
                return baseline.get(key)
    return None


def _format_value(
    value: Any,
    *,
    unit: str = "",
    decimals: int | None = None,
    default: str = "No documentado",
) -> str:
    if value in (None, "", []):
        return default
    num = _safe_float(value)
    if num is None:
        text = str(value).strip()
        return f"{text} {unit}".strip() if text else default
    formatted = f"{num:.{decimals}f}" if decimals is not None else f"{num:g}"
    return f"{formatted} {unit}".strip()


def _evidence_status(value: Any) -> str:
    return "captured" if value not in (None, "", []) else "missing"


# ──────────────────────────────────────────────────────────────────────
# Tarjeta 1 — Función renal basal
# ──────────────────────────────────────────────────────────────────────


def _build_renal_card(patient: dict[str, Any]) -> dict[str, Any] | None:
    creatinine = _safe_float(_patient_lookup(patient, "creatinine_mg_dl", "creatinine", "serum_creatinine"))
    egfr_captured = _safe_float(_patient_lookup(patient, "egfr_ml_min", "egfr", "egfr_ml_min_1_73m2"))
    formula_captured = _patient_lookup(patient, "egfr_formula") or "ckd_epi_2021"
    egfr_date = _patient_lookup(patient, "egfr_date", "labs_baseline_date")

    age = _safe_float(_patient_lookup(patient, "age", "edad", "age_years"))
    sex = _patient_lookup(patient, "sex", "sexo", "gender")

    egfr_value = egfr_captured
    formula_used = str(formula_captured).strip().lower() or "ckd_epi_2021"
    stage_label: str | None = None
    missing: list[str] = []
    evidence_tag = "Inker 2021 NEJM (CKD-EPI 2021)"

    if egfr_value is None and creatinine is not None and age is not None and sex:
        result = compute_egfr(
            creatinine_mg_dl=creatinine,
            age=age,
            sex=sex,
            formula=formula_used,
        )
        egfr_value = result.get("egfr_ml_min_1_73m2")
        stage_label = result.get("ckd_stage_label")
        formula_used = result.get("formula") or formula_used
        missing.extend(result.get("inputs_missing") or [])
        evidence_tag = result.get("evidence_tag") or evidence_tag
    elif egfr_value is not None:
        # Reusa el clasificador para consistencia
        from prostanet.shared.renal_function import _classify_ckd_stage  # type: ignore

        _, stage_label = _classify_ckd_stage(egfr_value)

    if egfr_value is None and creatinine is None and egfr_captured is None:
        return None  # Sin ningún dato renal; no surface una tarjeta vacía.

    if creatinine is None:
        missing.append("creatinine_mg_dl")
    if age is None:
        missing.append("age")
    if not sex:
        missing.append("sex")

    tone = "ok"
    narrative = "Función renal adecuada para terapias oncológicas estándar."
    if egfr_value is not None:
        if egfr_value < 30:
            tone = "critical"
            narrative = (
                "eGFR <30 ml/min/1.73m²: contraindica Ra-223 (ALSYMPCA), "
                "requiere dose-reduce olaparib, reconsidera cabazitaxel."
            )
        elif egfr_value < 45:
            tone = "warning"
            narrative = (
                "eGFR <45 ml/min/1.73m²: ajuste de dosis para olaparib, "
                "precaución con abiraterona + hipopotasemia."
            )
        elif egfr_value < 60:
            tone = "caution"
            narrative = (
                "eGFR <60 ml/min/1.73m² (KDIGO G3a): monitoreo renal reforzado "
                "antes de contraste PSMA/PET y bifosfonatos."
            )

    items = [
        {
            "label": "eGFR",
            "value": _format_value(egfr_value, unit="ml/min/1.73m²", decimals=1),
            "detail": "Calculado (CKD-EPI 2021 sin coef. raza)" if egfr_captured is None else "Reportado",
            "evidence_status": _evidence_status(egfr_value),
        },
        {
            "label": "Creatinina sérica",
            "value": _format_value(creatinine, unit="mg/dL", decimals=2),
            "detail": f"Fecha: {egfr_date}" if egfr_date else "Sin fecha documentada",
            "evidence_status": _evidence_status(creatinine),
        },
        {
            "label": "Estadio KDIGO",
            "value": stage_label or "No clasificable",
            "detail": f"Fórmula: {formula_used.upper()}",
            "evidence_status": _evidence_status(stage_label),
        },
    ]

    bullets = []
    if tone != "ok":
        bullets.append(narrative)
    bullets.append(
        "eGFR <30: Ra-223 contraindicado (ALSYMPCA §2.4); olaparib 200→150→100 mg BID."
    )
    bullets.append(
        "eGFR <45: abiraterona + prednisona monitorizar K+/AST/ALT cada 2-4 semanas."
    )

    return {
        "title": "Función renal basal",
        "subtitle": "CKD-EPI 2021 (Inker 2021 NEJM) + estadiaje KDIGO 2024",
        "tone": tone,
        "items": items,
        "bullets": bullets[:3],
        "sources": [evidence_tag, "KDIGO 2024 CKD Guideline"],
        "updated_at": egfr_date or "",
        "missing_inputs": sorted(set(missing)),
        "key": "epic2_renal_function",
    }


# ──────────────────────────────────────────────────────────────────────
# Tarjeta 2 — Marcadores pronósticos Halabi
# ──────────────────────────────────────────────────────────────────────


_HALABI_TARGETS = {
    "albumin": {"min": 3.5, "max": 5.5, "unit": "g/dL", "direction": "higher_is_better"},
    "ldh": {"min": 140.0, "max": 271.0, "unit": "U/L", "direction": "lower_is_better"},
    "hemoglobin": {"min": 12.0, "max": 17.5, "unit": "g/dL", "direction": "higher_is_better"},
    "alkaline_phosphatase": {"min": 40.0, "max": 129.0, "unit": "U/L", "direction": "lower_is_better"},
}


def _halabi_flag(value: float | None, spec: dict[str, Any]) -> tuple[str, str]:
    if value is None:
        return "missing", "Sin captura"
    lo = spec["min"]
    hi = spec["max"]
    direction = spec["direction"]
    if direction == "higher_is_better":
        if value < lo * 0.8:
            return "critical", "Muy bajo — HR mortalidad ↑"
        if value < lo:
            return "warning", "Bajo — pronóstico adverso"
        return "ok", "Dentro de rango"
    if value > hi * 1.5:
        return "critical", "Muy elevado — HR mortalidad ↑"
    if value > hi:
        return "warning", "Elevado — pronóstico adverso"
    return "ok", "Dentro de rango"


def _build_halabi_card(patient: dict[str, Any]) -> dict[str, Any] | None:
    labs = {
        "albumin": _safe_float(_patient_lookup(patient, "albumin_g_dl", "albumin", "albumina")),
        "ldh": _safe_float(_patient_lookup(patient, "ldh_u_l", "ldh", "lactate_dehydrogenase")),
        "hemoglobin": _safe_float(_patient_lookup(patient, "hemoglobin_g_dl", "hemoglobin", "hgb", "hemoglobina")),
        "alkaline_phosphatase": _safe_float(
            _patient_lookup(patient, "alkaline_phosphatase_u_l", "alp", "alkaline_phosphatase", "fosfatasa_alcalina")
        ),
    }
    if not any(value is not None for value in labs.values()):
        return None

    labs_date = _patient_lookup(patient, "labs_baseline_date", "egfr_date")

    worst_tone = "ok"
    priority = {"ok": 0, "caution": 1, "warning": 2, "critical": 3, "missing": 0}
    items: list[dict[str, Any]] = []
    captures = {
        "albumin": {"label": "Albúmina", "key_display": "Halabi β=-0.155"},
        "ldh": {"label": "LDH", "key_display": "Halabi β=+0.652"},
        "hemoglobin": {"label": "Hemoglobina", "key_display": "Halabi β=-0.124"},
        "alkaline_phosphatase": {"label": "Fosfatasa alcalina", "key_display": "Halabi β=+0.318"},
    }
    for lab_key, meta in captures.items():
        value = labs[lab_key]
        spec = _HALABI_TARGETS[lab_key]
        tone, detail = _halabi_flag(value, spec)
        if priority.get(tone, 0) > priority.get(worst_tone, 0):
            worst_tone = tone
        items.append(
            {
                "label": meta["label"],
                "value": _format_value(value, unit=spec["unit"], decimals=2),
                "detail": f"{meta['key_display']} — {detail}",
                "evidence_status": "captured" if value is not None else "missing",
            }
        )

    missing = [f"{key}_captured" for key, value in labs.items() if value is None]

    bullets = []
    if labs["albumin"] is not None and labs["albumin"] < 3.5:
        bullets.append("Albúmina <3.5 g/dL: Halabi IPS empeora; considerar soporte nutricional.")
    if labs["ldh"] is not None and labs["ldh"] > 271:
        bullets.append("LDH elevada: marcador de carga tumoral / NEPC potencial — correlacionar con CgA/NSE.")
    if labs["hemoglobin"] is not None and labs["hemoglobin"] < 11:
        bullets.append("Hgb <11 g/dL: evaluar EPO vs transfusión vs causa (sangrado, anemia crónica).")
    if not bullets:
        bullets.append("Perfil Halabi dentro de rangos pronósticos favorables.")

    return {
        "title": "Marcadores pronósticos (Halabi IPS)",
        "subtitle": "Modelo validado mCRPC (Halabi 2014 JCO — category 1)",
        "tone": worst_tone,
        "items": items,
        "bullets": bullets[:3],
        "sources": ["Halabi 2014 JCO 32:671", "Integrated ProstaNet mCRPC IPS"],
        "updated_at": labs_date or "",
        "missing_inputs": missing,
        "key": "epic2_halabi_markers",
    }


# ──────────────────────────────────────────────────────────────────────
# Tarjeta 3 — Terapia de privación androgénica (timeline)
# ──────────────────────────────────────────────────────────────────────


def _build_adt_card(patient: dict[str, Any]) -> dict[str, Any] | None:
    start_raw = _patient_lookup(patient, "adt_start_date")
    agent = _patient_lookup(patient, "adt_primary_agent", "adt_agent")
    intent = _patient_lookup(patient, "adt_intent")

    if not start_raw and not agent and not intent:
        return None

    start = _safe_date(start_raw)
    months = _months_between(start)

    items = [
        {
            "label": "Fecha de inicio",
            "value": start.isoformat() if start else "No documentada",
            "detail": (
                f"≈ {months} meses en ADT" if months is not None else "Hito clínico para castración resistente"
            ),
            "evidence_status": _evidence_status(start_raw),
        },
        {
            "label": "Agente primario",
            "value": str(agent).title() if agent else "No documentado",
            "detail": "LHRH agonista/antagonista o terapia supresora",
            "evidence_status": _evidence_status(agent),
        },
        {
            "label": "Intención",
            "value": str(intent).title() if intent else "No documentada",
            "detail": "adyuvante / neoadyuvante / paliativa / definitiva",
            "evidence_status": _evidence_status(intent),
        },
    ]

    bullets: list[str] = []
    if months is not None:
        if months >= 12:
            bullets.append(
                "ADT ≥12 meses: NCCN PROS-I exige DXA basal + anual, calcio+vitamina D, "
                "considerar bifosfonato/denosumab si osteopenia/osteoporosis."
            )
        if months >= 6:
            bullets.append(
                "ADT prolongado: vigilar riesgo cardiovascular, sarcopenia, síndrome metabólico."
            )
    if not start:
        bullets.append(
            "Sin fecha de inicio no se puede calcular ventana castración-resistencia "
            "(T <50 ng/dL + PSA rising)."
        )

    return {
        "title": "Terapia de privación androgénica",
        "subtitle": "Timeline hormonal para trazabilidad de castración resistencia",
        "tone": "ok",
        "items": items,
        "bullets": bullets[:3],
        "sources": ["NCCN PROS-I v5.2026", "EAU 2026 §6.2"],
        "updated_at": start.isoformat() if start else "",
        "missing_inputs": [k for k, v in (("adt_start_date", start_raw), ("adt_primary_agent", agent)) if not v],
        "key": "epic2_adt_timeline",
    }


# ──────────────────────────────────────────────────────────────────────
# Tarjeta 4 — Medicamentos estructurados
# ──────────────────────────────────────────────────────────────────────


def _build_medication_card(patient: dict[str, Any]) -> dict[str, Any] | None:
    raw = _patient_lookup(patient, "medication_list", "current_medications", "medications")
    if raw in (None, "", []):
        return None
    meds = normalize_medication_list(raw)
    if not meds:
        return None
    summary = summarize_medication_list(meds)

    ddi_count = 0
    ddi_preview: list[str] = []
    try:
        from prostanet.shared.ddi_engine import DDIEngine

        alerts = DDIEngine.check_medication_list(meds, therapy_candidate=None)
        ddi_count = len(alerts)
        for alert in alerts[:3]:
            drug_a = getattr(alert, "drug_a", None) or (alert.get("drug_a") if isinstance(alert, dict) else "")
            drug_b = getattr(alert, "drug_b", None) or (alert.get("drug_b") if isinstance(alert, dict) else "")
            severity = getattr(alert, "severity", None) or (alert.get("severity") if isinstance(alert, dict) else "")
            ddi_preview.append(f"{drug_a} × {drug_b} ({severity})")
    except Exception:
        ddi_count = 0

    items = [
        {
            "label": "Total medicamentos",
            "value": str(summary.get("total", 0)),
            "detail": f"Catalogados CYP: {summary.get('catalogued', 0)}",
            "evidence_status": "captured",
        },
        {
            "label": "Fármacos mapeados",
            "value": ", ".join(summary.get("catalogued_names", [])[:6]) or "Ninguno mapeado",
            "detail": f"No catalogados: {summary.get('uncatalogued', 0)}",
            "evidence_status": "captured" if summary.get("catalogued", 0) else "missing",
        },
        {
            "label": "Alertas DDI potenciales",
            "value": str(ddi_count),
            "detail": "; ".join(ddi_preview) if ddi_preview else "Sin interacciones detectadas con el catálogo actual",
            "evidence_status": "captured",
        },
    ]

    tone = "ok"
    if ddi_count >= 3:
        tone = "warning"
    if any("contraindicated" in p for p in ddi_preview):
        tone = "critical"

    bullets = [
        "Captura estructurada habilita DDI engine (36 reglas) en tiempo real.",
    ]
    if summary.get("uncatalogued"):
        bullets.append(
            f"{summary.get('uncatalogued')} fármaco(s) sin perfil CYP — revisar antes de ARPI/PARP."
        )
    if ddi_count:
        bullets.append("Alertas DDI ordenadas por severidad: contraindicada > major > moderate.")

    return {
        "title": "Medicamentos estructurados",
        "subtitle": "Perfil CYP + DDI engine (36 reglas, PharmGKB/DrugBank)",
        "tone": tone,
        "items": items,
        "bullets": bullets[:3],
        "sources": ["FDA drug labels §7", "PharmGKB 2024", "Flockhart CYP Table 2024"],
        "updated_at": "",
        "missing_inputs": [] if summary.get("total") else ["medication_list"],
        "key": "epic2_medication_list",
    }


# ──────────────────────────────────────────────────────────────────────
# Tarjeta 5 — Genomic classifiers con score numérico
# ──────────────────────────────────────────────────────────────────────


def _build_genomic_card(patient: dict[str, Any]) -> dict[str, Any] | None:
    decipher = _safe_float(_patient_lookup(patient, "decipher_score_numeric"))
    prolaris = _safe_float(_patient_lookup(patient, "prolaris_ccp_score"))
    oncotype = _safe_float(_patient_lookup(patient, "oncotype_gps"))
    categorical = _patient_lookup(patient, "genomic_classifier_result")
    report_date = _patient_lookup(patient, "genomic_classifier_date", "genomic_classifier_report_date")

    if decipher is None and prolaris is None and oncotype is None:
        return None

    verdicts = []
    if decipher is not None:
        verdicts.append(classify_genomic_score(classifier="decipher", score=decipher, categorical_band=categorical))
    if prolaris is not None:
        verdicts.append(classify_genomic_score(classifier="prolaris", score=prolaris, categorical_band=categorical))
    if oncotype is not None:
        verdicts.append(classify_genomic_score(classifier="oncotype", score=oncotype, categorical_band=categorical))

    tone = "ok"
    priority = {"low": 0, "intermediate": 1, "high": 2}
    high_band = -1
    items: list[dict[str, Any]] = []
    for v in verdicts:
        band = v.get("band")
        if band in priority and priority[band] > high_band:
            high_band = priority[band]
        items.append(
            {
                "label": v.get("classifier", "").title(),
                "value": f"{v.get('score')} {v.get('unit', '')}".strip(),
                "detail": v.get("narrative") or "",
                "evidence_status": "captured" if v.get("score") is not None else "missing",
            }
        )
    if high_band == 2:
        tone = "warning"

    bullets = [v.get("narrative") for v in verdicts if v.get("narrative")]

    return {
        "title": "Clasificadores genómicos (score numérico)",
        "subtitle": "Decipher / Prolaris / Oncotype (bandas canónicas + concordancia con reporte)",
        "tone": tone,
        "items": items,
        "bullets": bullets[:3],
        "sources": ["Spratt 2018 JCO (Decipher)", "Cuzick 2012 BrJCancer (Prolaris)", "Klein 2014 EurUrol (Oncotype)"],
        "updated_at": report_date or "",
        "missing_inputs": [],
        "key": "epic2_genomic_classifiers",
    }


# ──────────────────────────────────────────────────────────────────────
# Tarjeta 6 — Germline vs somático (NCCN PROS-H trigger)
# ──────────────────────────────────────────────────────────────────────


_PARP_ACTIONABLE = {"BRCA1", "BRCA2", "ATM", "PALB2", "CHEK2", "CDK12"}


def _build_germline_somatic_card(patient: dict[str, Any]) -> dict[str, Any] | None:
    germ_done = _patient_lookup(patient, "germline_testing_performed")
    germ_variant = _patient_lookup(patient, "germline_pathogenic_variant")
    germ_date = _patient_lookup(patient, "germline_test_date")
    som_done = _patient_lookup(patient, "somatic_testing_performed")
    som_variant = _patient_lookup(patient, "somatic_pathogenic_variant")
    family = _patient_lookup(patient, "family_history_cancer")

    if not any([germ_done, germ_variant, germ_date, som_done, som_variant, family]):
        return None

    germ_var = str(germ_variant or "").strip()
    som_var = str(som_variant or "").strip()
    parp_eligible = germ_var.upper() in _PARP_ACTIONABLE or som_var.upper() in _PARP_ACTIONABLE

    items = [
        {
            "label": "Test germinal",
            "value": (str(germ_done).title() if germ_done else "No documentado"),
            "detail": f"Fecha: {germ_date or 's/d'}",
            "evidence_status": _evidence_status(germ_done),
        },
        {
            "label": "Variante germinal",
            "value": germ_var or "ninguna",
            "detail": "Heredable — ofrecer consejería a familiares de 1er grado.",
            "evidence_status": _evidence_status(germ_variant),
        },
        {
            "label": "Variante somática",
            "value": som_var or "ninguna",
            "detail": "Tumoral — puede cambiar con progresión; repetir si metástasis nuevas.",
            "evidence_status": _evidence_status(som_variant),
        },
        {
            "label": "Historia familiar oncológica",
            "value": str(family or "No documentada").title(),
            "detail": "NCCN PROS-H category 2A trigger para germline testing.",
            "evidence_status": _evidence_status(family),
        },
    ]

    tone = "ok"
    bullets: list[str] = []
    if parp_eligible:
        tone = "warning"
        bullets.append(
            f"Variante patogénica accionable ({germ_var or som_var}): candidato a "
            "olaparib/rucaparib/talazoparib (PROfound, TRITON3, TALAPRO-2)."
        )
    if germ_var and germ_var.upper() == "BRCA2":
        bullets.append(
            "BRCA2 germinal: consejería genética a familiares; considerar cribado "
            "mama/ovario/páncreas en portadores."
        )
    if not germ_done:
        bullets.append(
            "NCCN PROS-H recomienda germline en very-high-risk, metastático, "
            "intraductal/cribiforme o historia familiar."
        )

    return {
        "title": "Germline vs. somático",
        "subtitle": "NCCN PROS-H Version 5.2026 (category 2A) + Philadelphia consensus",
        "tone": tone,
        "items": items,
        "bullets": bullets[:3],
        "sources": ["NCCN PROS-H v5.2026", "Giri 2020 JCO Philadelphia Consensus"],
        "updated_at": germ_date or "",
        "missing_inputs": [] if germ_done else ["germline_testing_performed"],
        "key": "epic2_germline_somatic",
    }


# ──────────────────────────────────────────────────────────────────────
# Tarjeta 7 — Sitios viscerales discriminados (Halabi HR)
# ──────────────────────────────────────────────────────────────────────


_VISCERAL_LABELS = {
    "visceral_lung": ("Pulmón", "HR 1.41 (Halabi 2014)"),
    "visceral_liver": ("Hígado", "HR 2.09 (Halabi 2014) — peor pronóstico visceral"),
    "visceral_adrenal": ("Adrenal", "Documentar como M1c"),
    "visceral_cns": ("SNC", "Raro; priorizar RT focal + urgente"),
}


def _build_visceral_card(patient: dict[str, Any], state: str) -> dict[str, Any] | None:
    if not state or not any(
        tag in state for tag in ("mcspc_", "mhspc", "m1_crpc", "m0_crpc", "adt_progression")
    ):
        return None

    captured = {
        key: str(_patient_lookup(patient, key) or "").strip().lower()
        for key in _VISCERAL_LABELS
    }
    if not any(v for v in captured.values()):
        return None

    positives = [k for k, v in captured.items() if v in {"1", "true", "si", "sí", "yes", "present"}]
    items: list[dict[str, Any]] = []
    tone = "ok"
    for key, (label, detail) in _VISCERAL_LABELS.items():
        value_raw = captured.get(key, "")
        status = "Presente" if key in positives else ("Ausente" if value_raw else "No documentado")
        items.append(
            {
                "label": label,
                "value": status,
                "detail": detail,
                "evidence_status": "captured" if value_raw else "missing",
            }
        )
        if key == "visceral_liver" and key in positives:
            tone = "critical"
        elif key == "visceral_cns" and key in positives:
            tone = "critical"
        elif key in positives and tone == "ok":
            tone = "warning"

    bullets: list[str] = []
    if "visceral_liver" in positives:
        bullets.append("Hepático: peor pronóstico entre viscerales; docetaxel preferido sobre ARPI monoterapia.")
    if "visceral_lung" in positives:
        bullets.append("Pulmonar: HR intermedio; ARPI + ADT sigue siendo apropiado.")
    if "visceral_cns" in positives:
        bullets.append("SNC: urgente RT + corticoide; reevaluar sistémico tras control local.")
    if not bullets:
        bullets.append("Sin afectación visceral confirmada — clasificación M1a/M1b vigente.")

    return {
        "title": "Sitios viscerales (Halabi HR)",
        "subtitle": "Hígado vs pulmón vs adrenal/SNC — cambia selección de terapia sistémica",
        "tone": tone,
        "items": items,
        "bullets": bullets[:3],
        "sources": ["Halabi 2014 JCO (HR hepático 2.09 vs pulmón 1.41)"],
        "updated_at": "",
        "missing_inputs": [k for k, v in captured.items() if not v],
        "key": "epic2_visceral_sites",
    }


# ──────────────────────────────────────────────────────────────────────
# Entrada pública
# ──────────────────────────────────────────────────────────────────────


def build_epic2_clinical_cards(
    patient: dict[str, Any] | None,
    state: str | None = None,
) -> list[dict[str, Any]]:
    """Devuelve las tarjetas EPIC 2 aplicables al paciente/estado.

    Cada tarjeta sigue el contrato de ``stage_specific_panels`` para
    renderizarse sin cambios en ``patient_profile.html``.

    El orden de aparición está optimizado por impacto clínico decisional:

    1. Función renal basal (gatea abiraterona, cabazitaxel, Ra-223)
    2. Marcadores Halabi (IPS mCRPC)
    3. ADT timeline (hito castración-resistencia)
    4. Sitios viscerales (Halabi HR diferenciado)
    5. Genomic classifiers (score numérico — localized)
    6. Germline vs somático (PARP + consejería)
    7. Medicamentos estructurados (DDI real-time)
    """
    patient = patient or {}
    stage = str(state or patient.get("current_state") or "").strip().lower()
    cards: list[dict[str, Any]] = []
    for builder in (
        lambda: _build_renal_card(patient),
        lambda: _build_halabi_card(patient),
        lambda: _build_adt_card(patient),
        lambda: _build_visceral_card(patient, stage),
        lambda: _build_genomic_card(patient),
        lambda: _build_germline_somatic_card(patient),
        lambda: _build_medication_card(patient),
    ):
        try:
            card = builder()
        except Exception:
            card = None
        if card:
            cards.append(card)
    return cards


__all__ = ["build_epic2_clinical_cards"]
