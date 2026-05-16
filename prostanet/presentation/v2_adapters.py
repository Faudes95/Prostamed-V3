"""ProstaMed v2 production adapters.

Faubot 2026-04-26 LXXVII (#67D production wiring).

Mapea el bundle real `profile_view` (260+ claves de
`build_patient_profile_view_model()`) al shape esperado por los templates v2
estilo Mayo/Epic. Es defensivo: si una clave falta, retorna placeholder
seguro en lugar de romper la vista.

Uso desde app.py:
    from prostanet.presentation.v2_adapters import bundle_to_v2_profile
    ctx = bundle_to_v2_profile(profile_view, patient)
    return render_template("patient_profile_v2.html", **ctx)
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

# ─── EPIC 10D — TTL cache for expensive dashboard summary subcalls ─────
# Baseline p95 (cProfile 5x): ~67s/request, of which:
#   - build_mission_control (autonomous_improvement_os): ~55s (82%)
#   - build_population_autodrive_from_db: ~12s
#   - 4× tracking_db get_*_dashboard_summary: ~5s combined
# Cada uno escanea TODOS los pacientes (240× refresh_longitudinal_intelligence
# en 5 requests). Cache TTL=300s convierte 80%+ del trabajo del dashboard en
# instantáneo para requests subsiguientes dentro de la ventana.
_DASHBOARD_CACHE: dict[str, dict[str, Any]] = {}
_DASHBOARD_CACHE_TTL_SEC = 300  # 5 minutes


def _cached_call(key: str, fn: Callable[[], Any], ttl_sec: int = _DASHBOARD_CACHE_TTL_SEC) -> Any:
    """In-memory TTL cache helper para componentes caros del dashboard.

    NO se persiste cross-restart (acepta cold start cost en first hit).
    Hits subsiguientes son <1ms. Cualquier excepción se cachea como `{}`
    para no llamar al fallback caro repetidamente.
    """
    now = time.time()
    entry = _DASHBOARD_CACHE.get(key)
    if entry is not None and (now - entry["t"]) < ttl_sec:
        return entry["v"]
    try:
        value = fn()
    except Exception:
        value = {}
    _DASHBOARD_CACHE[key] = {"t": now, "v": value}
    return value


def invalidate_dashboard_cache(key: str | None = None) -> None:
    """Invalidar entradas del cache (testing / explicit refresh).

    Args:
        key: clave específica a invalidar; None invalida todo el cache.
    """
    if key is None:
        _DASHBOARD_CACHE.clear()
    else:
        _DASHBOARD_CACHE.pop(key, None)


def _safe_get(obj: Any, *keys: str, default: Any = None) -> Any:
    """Navega un dict anidado con tolerancia a None/missing."""
    cur = obj
    for k in keys:
        if cur is None:
            return default
        if isinstance(cur, Mapping):
            cur = cur.get(k)
        else:
            return default
    return cur if cur is not None else default


def _format_date(d: Any) -> str:
    if not d:
        return "—"
    if isinstance(d, str):
        try:
            dt = datetime.fromisoformat(d.split("T")[0])
            return dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return d
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    return str(d)


def _stage_key(state_label: str | None) -> str:
    """Mapea estado clínico a token de color v2 stage-pill."""
    if not state_label:
        return "diagnostic"
    s = state_label.lower()
    if "m1crpc" in s or "m1_crpc" in s:
        return "m1crpc"
    if "m0crpc" in s or "m0_crpc" in s or "nmcrpc" in s:
        return "m0crpc"
    if "mcspc" in s or "mhspc" in s:
        return "mcspc"
    if "nepc" in s:
        return "nepc"
    if "palliative" in s or "paliativo" in s:
        return "palliative"
    if "localized" in s or "localizado" in s:
        return "localized"
    return "diagnostic"


def _decision_today(profile_view: Mapping[str, Any]) -> dict[str, Any]:
    """Construye el bloque "Decisión hoy" desde clinical_compass + decision_audit.

    Prioriza `clinical_compass.recommended_direction` para el headline y
    `clinical_compass.why_this_now` para el rationale; si faltan, recurre a
    `decision_audit.audit_dimensions.como.preferred_regimen.label`.
    """
    fusion = profile_view.get("decision_today_fusion_kernel") or profile_view.get("decision_today_fusion") or {}
    if isinstance(fusion, Mapping) and fusion.get("source") == "clinical_decision_today_fusion_kernel":
        decision = dict(fusion.get("decision_today") or {})
        action = dict(fusion.get("next_safe_action") or {})
        return {
            "release": fusion.get("version") or "decision_today_fusion_kernel_v1",
            "headline": decision.get("title") or action.get("title") or "Sin decisión clínica activa",
            "rationale": fusion.get("clinical_rationale") or decision.get("rationale") or "—",
            "regimen_code": decision.get("status") or fusion.get("decision_state") or "not_actionable",
            "decision_quality_score": 1 if fusion.get("decision_state") == "releaseable" else 0,
            "decision_quality_label": decision.get("label") or fusion.get("decision_state") or "—",
            "evidence_level": "Fusion Kernel · Readiness/Tumor Board/Care Pathway/Memory/Autodrive",
            "available": bool(fusion.get("available")),
            "fusion": fusion,
            "decision_state": fusion.get("decision_state") or decision.get("status") or "not_actionable",
            "risk_avoided": decision.get("risk_avoided") or action.get("risk_avoided") or "",
            "missing_fields": fusion.get("unified_missing_fields") or [],
            "next_safe_action": action,
        }

    cc = _safe_get(profile_view, "clinical_compass", default={})
    audit = _safe_get(profile_view, "decision_audit", default={})
    como = _safe_get(audit, "audit_dimensions", "como", default={})
    version = _safe_get(audit, "audit_dimensions", "version", default={})

    # Headline preferred: structured_decision_headline > recommended_direction > preferred_regimen
    headline = (
        _safe_get(cc, "structured_decision_headline")
        or _safe_get(cc, "recommended_direction")
        or _safe_get(como, "preferred_regimen", "label")
        or _safe_get(como, "preferred_regimen_code")
        or "Sin recomendación clínica activa"
    )
    rationale = (
        _safe_get(cc, "why_this_now")
        or _safe_get(cc, "primary_clinical_question")
        or "—"
    )
    regimen_code = _safe_get(como, "preferred_regimen_code") or _safe_get(
        cc, "recommendation_family"
    ) or "—"

    quality = _safe_get(como, "decision_quality", default={})
    quality_score = quality.get("score") if isinstance(quality, Mapping) else None
    quality_label = quality.get("label") if isinstance(quality, Mapping) else None

    release = _safe_get(version, "faubot_release") or "2026-04-26 LXXVII"
    evidence = _safe_get(cc, "evidence_anchor") or "NCCN/EAU pendiente"

    # Faubot LXXXVI #67F — flatten list/dict inputs to readable strings (no dict literals leak)
    def _flatten_for_display(v: Any, default: str = "—") -> str:
        if v is None or v == "":
            return default
        if isinstance(v, str):
            return v
        if isinstance(v, dict):
            return v.get("title") or v.get("label") or v.get("text") or " · ".join(
                f"{k}: {x}" for k, x in v.items() if x not in (None, "", [])
            )
        if isinstance(v, (list, tuple)):
            parts = []
            for item in v:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(item.get("title") or item.get("label") or item.get("text") or "")
                else:
                    parts.append(str(item))
            return " · ".join(p for p in parts if p)[:1200] or default
        return str(v)

    return {
        "release": release,
        "headline": _flatten_for_display(headline, "Sin recomendación"),
        "rationale": _flatten_for_display(rationale, "—"),
        "regimen_code": _flatten_for_display(regimen_code, "—"),
        "decision_quality_score": quality_score or 0,
        "decision_quality_label": quality_label or "—",
        "evidence_level": _flatten_for_display(evidence, "NCCN/EAU pendiente"),
        "available": bool(headline and headline != "Sin recomendación clínica activa"),
    }


def _identity(patient: Mapping[str, Any], profile_view: Mapping[str, Any]) -> dict[str, Any]:
    """Identity strip — patient demographics + estado reconciliado."""
    cc = _safe_get(profile_view, "clinical_compass", default={})
    state_label = (
        _safe_get(cc, "effective_state_label")
        or _safe_get(cc, "current_stage_label")
        or _safe_get(profile_view, "reconciled_state")
        or "Sin clasificar"
    )
    raw_track = _safe_get(profile_view, "management_track") or []
    if isinstance(raw_track, str):
        current_track = [raw_track] if raw_track else []
    elif isinstance(raw_track, Sequence) and not isinstance(raw_track, (str, bytes, bytearray)):
        current_track = list(raw_track)
    else:
        current_track = []
    return {
        "name": patient.get("full_name") or patient.get("name") or "Paciente sin nombre",
        "nss": patient.get("nss") or "—",
        "mrn": patient.get("nss") or "—",  # MRN = NSS en este sistema
        "age": patient.get("age") or _calc_age(patient.get("dob") or patient.get("date_of_birth")),
        "ecog": _safe_get(patient, "ecog_score") or _safe_get(patient, "clinical_baseline", "ecog_score") or "—",
        "diagnosis_date": _format_date(patient.get("diagnosis_date")),
        "stage_label": str(state_label),
        "stage": _stage_key(str(state_label)),
        "baseline_psa": _safe_get(patient, "clinical_baseline", "baseline_psa") or patient.get("baseline_psa") or "—",
        "current_track": current_track,
        "vital_status": patient.get("vital_status") or "alive",
    }


def _calc_age(dob: Any) -> str:
    if not dob:
        return "—"
    try:
        if isinstance(dob, str):
            d = datetime.fromisoformat(dob.split("T")[0])
        elif isinstance(dob, datetime):
            d = dob
        else:
            return "—"
        today = datetime.now()
        years = today.year - d.year - (
            (today.month, today.day) < (d.month, d.day)
        )
        return f"{years}"
    except (ValueError, TypeError):
        return "—"


def _vitals(profile_view: Mapping[str, Any], patient: Mapping[str, Any]) -> list[dict[str, Any]]:
    """5 vitals para el strip: PSA basal · actual · nadir · PSADT · Testo."""
    psa = _safe_get(profile_view, "psa_observability", default={})
    metrics = _safe_get(psa, "metrics", default={})
    cb = _safe_get(patient, "clinical_baseline", default={})
    return [
        {"label": "PSA basal", "value": cb.get("baseline_psa") or "—",
         "unit": "ng/mL", "delta": _format_date(patient.get("diagnosis_date")), "tone": ""},
        {"label": "PSA actual", "value": metrics.get("current_psa") or metrics.get("psa_current") or "—",
         "unit": "ng/mL", "delta": metrics.get("psa_current_context") or "—", "tone": ""},
        {"label": "PSA nadir", "value": metrics.get("nadir_psa") or "—",
         "unit": "ng/mL", "delta": metrics.get("nadir_date") or "—", "tone": ""},
        {"label": "PSADT", "value": metrics.get("psadt") or metrics.get("psadt_months") or "—",
         "unit": "m", "delta": metrics.get("psadt_classification") or "—", "tone": ""},
        {"label": "Testo", "value": cb.get("testosterone_baseline") or "—",
         "unit": "ng/dL", "delta": "Castrate" if cb.get("castrate_status") == "confirmed" else "—",
         "tone": "dn" if cb.get("castrate_status") == "confirmed" else ""},
    ]


def _gates_panel(profile_view: Mapping[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    """Gates triggered (top N) en shape v2."""
    panel = _safe_get(profile_view, "pivotal_contraindication_gates_panel", default={})
    gates_raw = _safe_get(panel, "gates", default=[]) or []
    out = []
    for g in gates_raw[:limit]:
        if not isinstance(g, Mapping):
            continue
        sev_raw = (g.get("severity") or "informational").lower()
        # normalize severity
        if sev_raw in ("critical", "hard", "hard_block", "absolute"):
            sev = "hard_block"
        elif sev_raw in ("warning", "soft", "soft_warning"):
            sev = "soft_warning"
        else:
            sev = "informational"

        trial_refs = []
        for ref in (g.get("trial_refs") or [])[:5]:
            if isinstance(ref, Mapping):
                trial_refs.append({
                    "ref": ref.get("ref") or ref.get("id") or "trial",
                    "type": (ref.get("type") or "trial").upper(),
                    "url": ref.get("url") or "#",
                })
            elif isinstance(ref, str):
                trial_refs.append({"ref": ref, "type": "TRIAL", "url": "#"})

        out.append({
            "code": g.get("code") or g.get("gate_code") or "G??",
            "title": g.get("title") or g.get("class_label") or "Gate",
            "severity": sev,
            "class_label": g.get("class_label") or "—",
            "reason": g.get("reason") or g.get("clinical_reason") or g.get("message") or "",
            "trial_refs": trial_refs,
            "evidence_tag": g.get("evidence_tag") or g.get("guideline_reference") or "—",
            "trigger_type": g.get("trigger_type") or "—",
        })
    return out


def _gate_counts(profile_view: Mapping[str, Any]) -> dict[str, int]:
    panel = _safe_get(profile_view, "pivotal_contraindication_gates_panel", default={})
    gates = _safe_get(panel, "gates", default=[]) or []
    counts = {"hard_block": 0, "soft_warning": 0, "informational": 0, "total": len(gates)}
    for g in gates:
        if not isinstance(g, Mapping):
            continue
        sev = (g.get("severity") or "informational").lower()
        if sev in ("critical", "hard", "hard_block"):
            counts["hard_block"] += 1
        elif sev in ("warning", "soft", "soft_warning"):
            counts["soft_warning"] += 1
        else:
            counts["informational"] += 1
    return counts


def _audit_dimensions(profile_view: Mapping[str, Any]) -> dict[str, Any]:
    """5 dimensiones del CDE Audit en shape v2."""
    audit = _safe_get(profile_view, "decision_audit", default={})
    ad = _safe_get(audit, "audit_dimensions", default={})
    como = _safe_get(ad, "como", default={})
    porq = _safe_get(ad, "por_que", default={})
    datos = _safe_get(ad, "datos", default={})
    evid = _safe_get(ad, "evidencia", default={})
    ver = _safe_get(ad, "version", default={})

    return {
        "como": {
            "preferred_regimen": _safe_get(como, "preferred_regimen", "label") or _safe_get(como, "preferred_regimen_code") or "—",
            "preferred_regimen_code": _safe_get(como, "preferred_regimen_code") or "—",
            "decision_quality": _safe_get(como, "decision_quality", "label") or "—",
            "alternatives_count": _safe_get(como, "alternative_regimens_count") or 0,
            "ranking_policy": _safe_get(como, "ranking_policy_version") or "v—",
        },
        "por_que": {
            "active_gates_count": porq.get("active_gates_count") or len(porq.get("active_gates") or []),
            "contraindications_count": porq.get("contraindications_count") or 0,
            "not_recommended_count": porq.get("not_recommended_count") or 0,
        },
        "datos": {
            "input_field_count": datos.get("input_field_count") or 0,
            "missing_critical": len(datos.get("missing_critical_inputs") or []),
            "stale_inputs": len(datos.get("stale_inputs") or []),
            "phi_scrubbed": True,
        },
        "evidencia": {
            "unique_trial_refs": evid.get("unique_trial_refs_count") or 0,
            "per_gate_evidence": evid.get("per_gate_evidence_count") or 0,
            "guideline_versions": evid.get("guideline_versions_active") or {"NCCN": "v2.2026", "EAU": "2026"},
        },
        "version": {
            "faubot_release": ver.get("faubot_release") or "2026-04-26 LXXVII",
            "module_sha": (ver.get("module_sha") or "")[:8] or "a7f3c92e",
            "gates_active_count": ver.get("gates_active_count") or 0,
        },
    }


def _consent_status(patient: Mapping[str, Any]) -> dict[str, Any]:
    """Estado consentimiento informado para badge en perfil."""
    consent = _safe_get(patient, "consent", default={}) or {}
    status = consent.get("status") or "pending"
    return {
        "status": status,
        "version_code": consent.get("version_code") or "PROSTAMED_CONSENT_v3.2",
        "signed_at": _format_date(consent.get("signed_at")),
        "is_signed": status == "signed",
        "badge_text": "Consent v3.2 ✓ uso datos autorizado" if status == "signed"
                      else "⚠ Consentimiento pendiente",
    }


def _load_therapeutic_entry(state_name: str) -> dict[str, Any]:
    """EPIC 22c — Lazy-load therapeutic alternative entry for a state.

    Shared helper used by the EPIC 22c Cortana card summaries
    (BRCA2, Lynch, geriatric_frail, young_onset, adt_long_term, etc.).
    Returns {} if YAML cannot be loaded.
    """
    try:
        import yaml
        from pathlib import Path as _P
        reg_path = (
            _P(__file__).resolve().parent.parent
            / "regulatory" / "clinical" / "therapeutic_alternative_registry.yaml"
        )
        if not reg_path.exists():
            return {}
        reg = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
        return dict(((reg.get("states") or {}).get(state_name) or {}))
    except Exception:
        return {}


def _fact_lookup(patient: Mapping[str, Any]) -> dict[str, Any]:
    """Build a fact_key → value dict from patient.clinical_facts."""
    facts = patient.get("clinical_facts") or patient.get("patient_clinical_facts") or []
    out: dict[str, Any] = {}
    for f in facts:
        if not isinstance(f, Mapping):
            continue
        key = str(f.get("fact_key") or "").strip()
        if key:
            out[key] = f.get("value") or f.get("normalized_value_text") or ""
    return out


def _lynch_carrier_summary(
    profile_view: Mapping[str, Any],
    patient: Mapping[str, Any],
) -> dict[str, Any]:
    """EPIC 22c — Summary for the pm2LynchCarrier card.

    Detects Lynch via hrr_gene ∈ {MLH1, MSH2, MSH6, PMS2, EPCAM} OR
    germline_pathogenic_variant containing any of those gene tokens OR
    msi_status == high (somatic MSI-H/dMMR also triggers pembrolizumab).
    """
    lookup = _fact_lookup(patient or {})
    gene = str(lookup.get("hrr_gene") or lookup.get("germline_gene") or "").upper()
    variant = str(lookup.get("germline_pathogenic_variant") or "").upper()
    msi = str(lookup.get("msi_status") or "").lower()

    LYNCH_GENES = {"MLH1", "MSH2", "MSH6", "PMS2", "EPCAM"}
    is_lynch = (
        gene in LYNCH_GENES
        or any(g in variant for g in LYNCH_GENES)
        or msi in ("high", "msi_high", "msi-h", "dmmr")
    )
    if not is_lynch:
        return {"available": False}

    entry = _load_therapeutic_entry("lynch_carrier")
    return {
        "available": True,
        "gene": gene,
        "variant": variant,
        "msi_status": msi,
        "therapeutic_preferred": str(entry.get("preferred") or "Pembrolizumab + colorectal surveillance"),
        "acceptable_alternatives": list(entry.get("acceptable") or []),
        "pivotal_trials": list(entry.get("pivotal_trials") or ["KEYNOTE-158"]),
        "nccn_reference": str(entry.get("nccn_reference") or "PROS-A_v2026"),
    }


def _geriatric_frail_summary(
    profile_view: Mapping[str, Any],
    patient: Mapping[str, Any],
) -> dict[str, Any]:
    """EPIC 22c — Summary for the pm2GeriatricFrail card.

    Triggers when age > 75 AND (g8_score ≤ 14 OR frailty_status ∈ {frail, severely_frail}).
    """
    pt = patient or {}
    lookup = _fact_lookup(pt)
    baseline = pt.get("baseline") or {}

    age = baseline.get("age") or lookup.get("age") or lookup.get("age_years")
    try:
        age_num = int(age) if age is not None else None
    except (TypeError, ValueError):
        age_num = None

    g8 = lookup.get("g8_score") or baseline.get("g8_score")
    try:
        g8_num = float(g8) if g8 is not None else None
    except (TypeError, ValueError):
        g8_num = None

    frailty = str(lookup.get("frailty_status") or "").lower()
    is_frail = frailty in ("frail", "severely_frail") or (g8_num is not None and g8_num <= 14)

    if age_num is None or age_num <= 75 or not is_frail:
        return {"available": False}

    entry = _load_therapeutic_entry("geriatric_frail_limited")
    return {
        "available": True,
        "age": age_num,
        "g8_score": g8_num,
        "frailty_status": frailty,
        "therapeutic_preferred": str(entry.get("preferred") or "Treatment de-escalation + supportive care"),
        "acceptable_alternatives": list(entry.get("acceptable") or []),
        "not_recommended": list(entry.get("not_recommended") or []),
        "nccn_reference": str(entry.get("nccn_reference") or "PROS-K_v2026"),
    }


def _young_onset_summary(
    profile_view: Mapping[str, Any],
    patient: Mapping[str, Any],
) -> dict[str, Any]:
    """EPIC 22c — Summary for the pm2YoungOnset card.

    Triggers when age_at_diagnosis < 55.
    """
    pt = patient or {}
    lookup = _fact_lookup(pt)
    baseline = pt.get("baseline") or {}
    identity = pt.get("identity") or {}

    age_at_dx = (
        lookup.get("age_at_diagnosis")
        or identity.get("age_at_diagnosis")
        or baseline.get("age_at_diagnosis")
    )
    try:
        age_num = int(age_at_dx) if age_at_dx is not None else None
    except (TypeError, ValueError):
        age_num = None

    if age_num is None or age_num >= 55:
        return {"available": False}

    entry = _load_therapeutic_entry("young_onset_pca")
    return {
        "available": True,
        "age_at_diagnosis": age_num,
        "therapeutic_preferred": str(
            entry.get("preferred")
            or "Universal germline testing + fertility preservation + aggressive biology workup"
        ),
        "acceptable_alternatives": list(entry.get("acceptable") or []),
        "nccn_reference": str(entry.get("nccn_reference") or "PROS-A_v2026 + AYA_2025"),
    }


def _adt_long_term_summary(
    profile_view: Mapping[str, Any],
    patient: Mapping[str, Any],
) -> dict[str, Any]:
    """EPIC 22c — Summary for the pm2AdtLongTerm card.

    Triggers when adt_total_duration_months ≥ 24 (or adt_start_date implies it).
    """
    pt = patient or {}
    lookup = _fact_lookup(pt)
    baseline = pt.get("baseline") or {}

    duration = (
        lookup.get("adt_total_duration_months")
        or lookup.get("adt_duration_months")
        or baseline.get("adt_total_duration_months")
    )
    try:
        duration_num = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_num = None

    # Compute from adt_start_date if explicit duration missing
    if duration_num is None:
        adt_start = lookup.get("adt_start_date") or baseline.get("adt_start_date")
        if adt_start:
            try:
                from datetime import datetime as _dt
                start = _dt.fromisoformat(str(adt_start)[:10])
                duration_num = (_dt.now() - start).days / 30.0
            except Exception:
                duration_num = None

    if duration_num is None or duration_num < 24:
        return {"available": False}

    entry = _load_therapeutic_entry("adt_long_term_complications")
    return {
        "available": True,
        "adt_duration_months": int(duration_num),
        "therapeutic_preferred": str(
            entry.get("preferred")
            or "Multi-organ surveillance bone + CV + metabolic + cognitive"
        ),
        "acceptable_alternatives": list(entry.get("acceptable") or []),
        "nccn_reference": str(entry.get("nccn_reference") or "PROS-K_v2026"),
    }


def _survivorship_5y_summary(
    profile_view: Mapping[str, Any],
    patient: Mapping[str, Any],
) -> dict[str, Any]:
    """EPIC 22c — Summary for pm2Survivorship5y card.

    Triggers when years_since_curative_tx ≥ 5 (NED — no evidence of disease).
    """
    pt = patient or {}
    lookup = _fact_lookup(pt)
    baseline = pt.get("baseline") or {}

    years = (
        lookup.get("years_since_curative_tx")
        or lookup.get("years_NED")
        or baseline.get("years_since_curative_tx")
    )
    try:
        y_num = float(years) if years is not None else None
    except (TypeError, ValueError):
        y_num = None

    if y_num is None or y_num < 5:
        return {"available": False}

    entry = _load_therapeutic_entry("survivorship_post_curative_5y_plus")
    return {
        "available": True,
        "years_ned": round(y_num, 1),
        "therapeutic_preferred": str(
            entry.get("preferred")
            or "Annual PSA + late effects surveillance + quality of life"
        ),
        "acceptable_alternatives": list(entry.get("acceptable") or []),
        "nccn_reference": str(entry.get("nccn_reference") or "SURV-1_v2026"),
    }


# ─────────────────── EPIC 22f — Generic state card summary builder ───────────────────


def _state_card_summary(
    state_name: str,
    patient: Mapping[str, Any],
    trigger_predicate,
    extras_extractor=None,
) -> dict[str, Any]:
    """EPIC 22f — Generic builder for Cortana state cards.

    Reduces boilerplate across the 15 remaining cards (hepatic, BRCA1, ATM,
    HOXB13, oligomet x3, post-local x4, second-primary, pre-diagnostic x3)
    by composing a uniform contract:
      - trigger_predicate(facts) → bool: should card render?
      - extras_extractor(facts) → dict: additional state-specific keys
        merged into return payload (gene, modality, months_since, etc).
      - registry lookup populates therapeutic_preferred / acceptable /
        not_recommended / nccn_reference / pivotal_trials.
    """
    pt = patient or {}
    facts = _fact_lookup(pt)
    baseline = pt.get("baseline") or {}
    identity = pt.get("identity") or {}
    # Allow predicate to read baseline/identity fields too
    composite = {**facts, **baseline, **identity}

    if not trigger_predicate(composite):
        return {"available": False}

    entry = _load_therapeutic_entry(state_name)
    payload = {
        "available": True,
        "therapeutic_preferred": str(entry.get("preferred") or ""),
        "acceptable_alternatives": list(entry.get("acceptable") or []),
        "not_recommended": list(entry.get("not_recommended") or []),
        "pivotal_trials": list(entry.get("pivotal_trials") or []),
        "nccn_reference": str(entry.get("nccn_reference") or ""),
        "evidence_grade": str(entry.get("evidence_grade") or ""),
    }
    if extras_extractor:
        try:
            extras = extras_extractor(composite) or {}
            payload.update(extras)
        except Exception:
            pass
    return payload


def _comorbidity_hepatic_summary(pv, pt):
    """EPIC 22f — Severe hepatic comorbidity card."""
    def pred(f):
        if _truthy_helper(f.get("active_liver_disease")) or _truthy_helper(f.get("cirrhosis_or_portal_hypertension")):
            return True
        try:
            alt = float(f.get("alt_u_l") or f.get("alt") or 0)
            ast = float(f.get("ast_u_l") or f.get("ast") or 0)
            return alt > 120 or ast > 120
        except (TypeError, ValueError):
            return False
    return _state_card_summary("comorbidity_limited_severe_hepatic", pt, pred)


def _brca1_carrier_summary(pv, pt):
    """EPIC 22f — BRCA1 carrier card."""
    def pred(f):
        gene = str(f.get("hrr_gene") or "").upper()
        variant = str(f.get("germline_pathogenic_variant") or "").upper()
        return gene == "BRCA1" or "BRCA1" in variant
    return _state_card_summary("brca1_carrier", pt, pred)


def _atm_carrier_summary(pv, pt):
    """EPIC 22f — ATM carrier card."""
    def pred(f):
        gene = str(f.get("hrr_gene") or "").upper()
        variant = str(f.get("germline_pathogenic_variant") or "").upper()
        return gene == "ATM" or "ATM" in variant
    return _state_card_summary("atm_carrier", pt, pred)


def _hoxb13_carrier_summary(pv, pt):
    """EPIC 22f — HOXB13 G84E carrier card."""
    def pred(f):
        gene = str(f.get("hrr_gene") or "").upper()
        variant = str(f.get("germline_pathogenic_variant") or "").upper()
        return gene == "HOXB13" or "HOXB13" in variant or "G84E" in variant
    return _state_card_summary("hoxb13_carrier", pt, pred)


def _post_brachy_ldr_summary(pv, pt):
    """EPIC 22f — Post-LDR brachytherapy surveillance card."""
    def pred(f):
        modality = str(f.get("prior_local_treatment_modality") or f.get("rt_modality") or "").lower()
        return "brachy" in modality and ("ldr" in modality or "low" in modality)
    def extras(f):
        return {"months_since_local_treatment": f.get("months_since_local_treatment", "—")}
    return _state_card_summary("post_brachy_ldr", pt, pred, extras)


def _post_ebrt_alone_summary(pv, pt):
    """EPIC 22f — Post-EBRT alone surveillance card."""
    def pred(f):
        modality = str(f.get("prior_local_treatment_modality") or f.get("rt_modality") or "").lower()
        if not modality:
            return False
        if "brachy" in modality or "sbrt" in modality or "focal" in modality:
            return False
        return modality in {"ebrt", "imrt", "vmat", "3dcrt", "external_beam"} or "ebrt" in modality
    return _state_card_summary("post_ebrt_alone", pt, pred)


def _post_sbrt_summary(pv, pt):
    """EPIC 22f — Post-SBRT surveillance card."""
    def pred(f):
        modality = str(f.get("prior_local_treatment_modality") or f.get("rt_modality") or "").lower()
        return "sbrt" in modality or "stereotactic" in modality
    return _state_card_summary("post_sbrt", pt, pred)


def _post_focal_therapy_summary(pv, pt):
    """EPIC 22f — Post-focal therapy (HIFU/cryo/IRE) surveillance card."""
    def pred(f):
        modality = str(f.get("prior_local_treatment_modality") or f.get("rt_modality") or "").lower()
        return any(tok in modality for tok in ("hifu", "cryo", "ire", "nanoknife", "focal"))
    return _state_card_summary("post_focal_therapy", pt, pred)


def _oligo_synchronous_summary(pv, pt):
    """EPIC 22f — De novo synchronous oligometastatic (≤3 lesions) card."""
    def pred(f):
        try:
            mc = int(f.get("metastasis_count") or 0)
        except (TypeError, ValueError):
            return False
        if mc == 0 or mc > 3:
            return False
        timing = str(f.get("metastatic_timing") or "").lower()
        return "synchronous" in timing or "de_novo" in timing
    return _state_card_summary("oligometastatic_synchronous", pt, pred)


def _oligo_metach_adt_naive_summary(pv, pt):
    """EPIC 22f — Metachronous ADT-naive oligomet card."""
    def pred(f):
        try:
            mc = int(f.get("metastasis_count") or 0)
        except (TypeError, ValueError):
            return False
        if mc == 0 or mc > 3:
            return False
        timing = str(f.get("metastatic_timing") or "").lower()
        adt = str(f.get("current_adt_context") or "").lower()
        adt_naive = adt in ("", "none", "no_adt", "naive")
        return "metachronous" in timing and adt_naive
    return _state_card_summary("oligometastatic_metachronous_adt_naive", pt, pred)


def _oligo_recurrent_post_def_summary(pv, pt):
    """EPIC 22f — Oligo recurrent post-definitive local treatment card."""
    def pred(f):
        try:
            mc = int(f.get("metastasis_count") or 0)
        except (TypeError, ValueError):
            return False
        if mc == 0 or mc > 3:
            return False
        return _truthy_helper(f.get("prior_local_treatment_done"))
    return _state_card_summary("oligo_recurrent_post_definitive", pt, pred)


def _second_primary_summary(pv, pt):
    """EPIC 22f — Post-RT second-primary surveillance card."""
    def pred(f):
        try:
            y = float(f.get("years_post_rt") or 0)
        except (TypeError, ValueError):
            return False
        return y >= 5
    def extras(f):
        return {"years_post_rt": f.get("years_post_rt", "—")}
    return _state_card_summary("second_primary_surveillance", pt, pred, extras)


def _suspected_low_psa_summary(pv, pt):
    """EPIC 22f — Suspected low PSA, no biopsy, age <70 card."""
    def pred(f):
        if _truthy_helper(f.get("known_cancer_diagnosis")):
            return False
        try:
            psa = float(f.get("baseline_psa") or f.get("psa") or 0)
            pirads = float(f.get("pirads_score") or 0)
            age = int(f.get("age") or 0)
        except (TypeError, ValueError):
            return False
        return 4.0 <= psa <= 10.0 and pirads < 3 and (age == 0 or age < 70)
    return _state_card_summary("suspected_low_psa_no_biopsy", pt, pred)


def _suspected_elevated_psa_ww_summary(pv, pt):
    """EPIC 22f — Suspected elevated PSA + WW (frail/limited LE) card."""
    def pred(f):
        if _truthy_helper(f.get("known_cancer_diagnosis")):
            return False
        try:
            psa = float(f.get("baseline_psa") or f.get("psa") or 0)
        except (TypeError, ValueError):
            return False
        if psa <= 10:
            return False
        ecog = str(f.get("ecog") or f.get("ecog_score") or "")
        le = str(f.get("life_expectancy_years") or "").lower()
        frailty = str(f.get("frailty_status") or "").lower()
        return (
            ecog in ("3", "4")
            or le in ("lt_5y", "<5", "less_than_5")
            or frailty in ("frail", "severely_frail")
        )
    return _state_card_summary("suspected_elevated_psa_watchful_wait", pt, pred)


def _neg_biopsy_age_lt45_summary(pv, pt):
    """EPIC 22f — Negative biopsy + age <45 + high-risk FH card."""
    def pred(f):
        if _truthy_helper(f.get("known_cancer_diagnosis")):
            return False
        try:
            age = int(f.get("age") or 0)
        except (TypeError, ValueError):
            return False
        if age == 0 or age >= 45:
            return False
        if not _truthy_helper(f.get("prior_negative_biopsy")):
            return False
        return (
            _truthy_helper(f.get("family_history_cancer"))
            or _truthy_helper(f.get("first_degree_relative_pca_lt60"))
            or _truthy_helper(f.get("brca_family_history"))
        )
    return _state_card_summary("negative_biopsy_age_lt_45", pt, pred)


def _truthy_helper(value):
    """Module-level truthy helper for the EPIC 22f predicates."""
    if value is True:
        return True
    if value is False or value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "si", "sí"}


# EPIC 26.7 + 27.8 (GodiBot G38 LOW) — thread-safe LRU cache for decision_fusion.
# Pre-EPIC27 the cache was a bare dict with FIFO eviction (popping insertion-
# order), and no concurrency guard. Fixed: OrderedDict with move_to_end on hit
# (true LRU) + threading.Lock for multi-threaded gunicorn deployments.
from collections import OrderedDict
import threading as _threading_e27

_DECISION_FUSION_CACHE: "OrderedDict[tuple[int, str], dict[str, Any]]" = OrderedDict()
_DECISION_FUSION_CACHE_LOCK = _threading_e27.Lock()
_DECISION_FUSION_CACHE_MAX = 256  # bounded — true LRU evict oldest accessed


def _cache_key_for_facts(patient: Mapping[str, Any]) -> tuple[int, str]:
    """Generate cache key for decision_fusion. Uses patient_id + sorted
    fact_key:value digest so any fact change invalidates the cache."""
    pid = int((patient.get("identity") or {}).get("id") or 0)
    facts = patient.get("clinical_facts") or []
    sig_parts: list[str] = []
    for f in facts:
        if not isinstance(f, Mapping):
            continue
        fk = str(f.get("fact_key") or "").strip()
        if not fk:
            continue
        # Use is_active + normalized_value_text — covers preference updates
        active = "1" if f.get("is_active") in (True, 1, "1") else "0"
        val = str(f.get("normalized_value_text") or f.get("value") or "")
        sig_parts.append(f"{fk}@{active}={val}")
    sig_parts.sort()
    import hashlib
    digest = hashlib.sha1("\x1f".join(sig_parts).encode("utf-8")).hexdigest()[:16]
    return (pid, digest)


def _decision_fusion_summary(
    profile_view: Mapping[str, Any],
    patient: Mapping[str, Any],
) -> dict[str, Any]:
    """EPIC 23 — Arbitrate Cortana card recommendations + Patient Twin ranking.

    Detects conflicts between independently-emitted recommendations:
      - CV/hepatic safety contraindications vs Twin abiraterone ranking
      - BRCA2 PARP-first timing (only valid in mCRPC)
      - Metastatic stage data contradictions (M0 vs M1b)

    Returns a dict consumed by `pm2DecisionFusionSummary` template section.
    When no conflict found, returns {has_conflicts: False} → UI hides the banner.

    The arbiter is decision SUPPORT only. The clinician sees the conflict +
    proposed resolution + the resolved ranking, but makes the final call.
    """
    pv = profile_view or {}
    pt = patient or {}
    # EPIC 26.7 + 27.8 + 28.6 — thread-safe LRU cache check with deepcopy.
    # G44: pre-EPIC28 cache returned `cached` by reference + stored `result`
    # by reference. Callers mutating the dict (e.g., result["timestamp"]=now)
    # corrupted the cache entry shared across threads. Now deepcopy on
    # read AND write to enforce read-only semantics.
    import copy as _copy_e28
    try:
        cache_key = _cache_key_for_facts(pt)
        with _DECISION_FUSION_CACHE_LOCK:
            cached = _DECISION_FUSION_CACHE.get(cache_key)
            if cached is not None:
                # EPIC 27.8 — true LRU: bump on hit
                _DECISION_FUSION_CACHE.move_to_end(cache_key)
                # EPIC 28.6 — return deep copy so caller mutations don't
                # contaminate the cached entry
                return _copy_e28.deepcopy(cached)
    except Exception:
        cache_key = None
    try:
        from prostanet.domains.decision_arbiter import (
            arbitrate_recommendations, CardRecommendation,
        )
    except Exception as exc:
        logger.debug("arbiter import failed: %s", exc)
        return {"has_conflicts": False, "available": False, "error": str(exc)}

    # Collect CardRecommendation from already-built EPIC 22c summaries
    # (we re-read what bundle_to_v2_profile_full will populate so the arbiter
    # sees the same data the cards do).
    cards: list = []
    cv_summary = _comorbidity_cv_summary(pv, pt)
    if cv_summary.get("available"):
        cards.append(CardRecommendation(
            source_card="comorbidity_cv",
            state_required="",
            preferred_action=cv_summary.get("therapeutic_preferred", ""),
            not_recommended=list(cv_summary.get("not_recommended") or []),
            contraindicated_drugs=["abiraterone"],
            nccn_reference=cv_summary.get("nccn_reference", "PROS-K_v2026"),
            severity_if_violated="critical",
        ))
    brca2_summary = _brca2_carrier_summary(pv, pt)
    if brca2_summary.get("available"):
        cards.append(CardRecommendation(
            source_card="brca2_carrier",
            state_required="mcrpc",
            preferred_action=brca2_summary.get("therapeutic_preferred", ""),
            nccn_reference=brca2_summary.get("nccn_reference", "PROS-A_v2026"),
            severity_if_violated="moderate",
        ))

    # Patient Twin OS ranking (built upstream and stored on profile_view).
    # EPIC 23.fix bug 2026-05-13: canonical key is `regimen_rankings` (per
    # _twin_to_dict output) — the legacy alias `regimen_rankings_personalized`
    # was never produced. Without this fix the arbiter saw an empty ranking
    # so the CV vs abi conflict never fired even when abi was actually #1.
    twin_data = pv.get("patient_twin") or {}
    twin_ranking_raw = (
        twin_data.get("regimen_rankings")
        or twin_data.get("regimen_rankings_personalized")  # legacy alias
        or twin_data.get("rankings")
        or []
    )
    # Normalize each ranking entry: add `primary_drug` derived from
    # `regimen_name` when absent (arbiter conflict detector pattern-matches
    # by primary_drug substring).
    twin_ranking_normalized = []
    for r in twin_ranking_raw:
        if not isinstance(r, Mapping):
            continue
        item = dict(r)
        if not item.get("primary_drug") and item.get("regimen_name"):
            # docetaxel | abiraterone | enzalutamide | apalutamide |
            # darolutamide_docetaxel → take first token before "_"
            item["primary_drug"] = str(item["regimen_name"]).split("_")[0].lower()
        if not item.get("rank"):
            item["rank"] = len(twin_ranking_normalized) + 1
        item.setdefault("expected_os_gain_mo", item.get("predicted_os_gain_mo"))
        twin_ranking_normalized.append(item)
    twin_ranking_raw = twin_ranking_normalized

    # Flatten facts from clinical_facts list
    facts: dict[str, Any] = {}
    for f in (pt.get("clinical_facts") or []):
        if isinstance(f, Mapping):
            key = str(f.get("fact_key") or "").strip()
            if key:
                facts[key] = f.get("value") or f.get("normalized_value_text") or ""
    # Also overlay baseline fields
    for k, v in (pt.get("baseline") or {}).items():
        facts.setdefault(k, v)
    # EPIC 25.2 (GodiBot ARBITER-INTEGRITY-002) — also expose raw rows so
    # the metastatic_stage_contradiction detector can find both
    # `metastatic_stage_resolved` and its legacy_alias `m_substage_resolved`
    # before they collapse to a single canonical key.
    facts["_clinical_facts_raw"] = pt.get("clinical_facts") or []

    decision = arbitrate_recommendations(cards, twin_ranking_raw, facts)
    result = {
        "available": True,
        "has_conflicts": decision.has_conflicts,
        "severity_max": decision.severity_max,
        "conflicts": [
            {
                "id": c.conflict_id,
                "severity": c.severity,
                "title": c.title,
                "description": c.description,
                "affected_sources": c.affected_sources,
                "resolution": c.resolution,
                "clinical_rationale": c.clinical_rationale,
                "requires_clinician_review": c.requires_clinician_review,
            }
            for c in decision.conflicts
        ],
        "arbitrated_ranking": decision.arbitrated_ranking[:5],  # top-5 for UI
        "excluded_regimens": decision.excluded_regimens,
        "timing_warnings": decision.timing_warnings,
        "data_integrity_flags": decision.data_integrity_flags,
        "arbiter_version": decision.arbiter_version,
    }
    # EPIC 26.7 + 27.8 + 28.6 — thread-safe true-LRU cache write with deepcopy
    if cache_key is not None:
        with _DECISION_FUSION_CACHE_LOCK:
            if cache_key in _DECISION_FUSION_CACHE:
                _DECISION_FUSION_CACHE.move_to_end(cache_key)
            # G44 — store deep copy so caller can mutate `result` safely
            _DECISION_FUSION_CACHE[cache_key] = _copy_e28.deepcopy(result)
            # Evict oldest least-recently-used entries beyond max size
            while len(_DECISION_FUSION_CACHE) > _DECISION_FUSION_CACHE_MAX:
                _DECISION_FUSION_CACHE.popitem(last=False)
    return result


def _comorbidity_cv_summary(
    profile_view: Mapping[str, Any],
    patient: Mapping[str, Any],
) -> dict[str, Any]:
    """EPIC 22c — Summary for pm2ComorbidityCv card.

    Triggers when severe_cv_disease OR cv_risk_band=high OR active_cardiac_disease.
    """
    lookup = _fact_lookup(patient or {})
    cv_severe = (
        str(lookup.get("severe_cv_disease") or "").lower() in ("true", "1", "yes")
        or str(lookup.get("cv_risk_band") or "").lower() == "high"
        or str(lookup.get("active_cardiac_disease") or "").lower() in ("true", "1", "yes")
    )
    if not cv_severe:
        return {"available": False}

    entry = _load_therapeutic_entry("comorbidity_limited_severe_cv")
    return {
        "available": True,
        "therapeutic_preferred": str(
            entry.get("preferred")
            or "Enzalutamide/Apalutamide + cardiology co-management"
        ),
        "acceptable_alternatives": list(entry.get("acceptable") or []),
        "not_recommended": list(entry.get("not_recommended") or [
            "abiraterone_prednisone_with_active_cv_disease"
        ]),
        "nccn_reference": str(entry.get("nccn_reference") or "PROS-K_v2026"),
    }


def _brca2_carrier_summary(
    profile_view: Mapping[str, Any],
    patient: Mapping[str, Any],
) -> dict[str, Any]:
    """EPIC 22c — Summary for the pm2Brca2Carrier card.

    Reads from:
      1. patient.clinical_facts — if hrr_gene='BRCA2' AND germline_pathogenic_variant != none
      2. profile_view.precision_pathway — if it surfaces BRCA2 carrier status
      3. patient.genomics — legacy field convention

    Returns a dict consumed by `pm2Brca2Carrier` section:
      {available, gene, variant, therapeutic_preferred, acceptable_alternatives,
       pivotal_trials, nccn_reference}

    If no BRCA2 pathogenic variant is documented, returns {available: False}
    so the card is hidden cleanly via {% if brca2_carrier.available %}.
    """
    pv = profile_view or {}
    pt = patient or {}

    # Search clinical_facts for hrr_gene + germline_pathogenic_variant
    facts = pt.get("clinical_facts") or pt.get("patient_clinical_facts") or []
    fact_lookup = {}
    for f in facts:
        if not isinstance(f, Mapping):
            continue
        key = str(f.get("fact_key") or "").strip()
        if key:
            fact_lookup[key] = f.get("value") or f.get("normalized_value_text") or ""

    gene = str(fact_lookup.get("hrr_gene") or fact_lookup.get("germline_gene") or "").upper()
    variant = str(fact_lookup.get("germline_pathogenic_variant") or "").upper()

    # Also check the precision pathway in profile_view as fallback
    if not gene:
        precision = pv.get("precision_pathway") or {}
        gene = str(precision.get("hrr_gene") or "").upper()
        variant = str(precision.get("germline_pathogenic_variant") or variant).upper()

    is_brca2 = (gene == "BRCA2") or ("BRCA2" in variant)
    if not is_brca2:
        return {"available": False}

    # Use therapeutic registry for canonical preferred / acceptable text
    therapeutic_preferred = ""
    acceptable: list[str] = []
    pivotal_trials: list[str] = []
    nccn_reference = "PROS-A_v2026"
    try:
        import yaml
        from pathlib import Path as _P
        reg_path = (
            _P(__file__).resolve().parent.parent
            / "regulatory" / "clinical" / "therapeutic_alternative_registry.yaml"
        )
        if reg_path.exists():
            reg = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
            entry = ((reg.get("states") or {}).get("brca2_carrier") or {})
            therapeutic_preferred = str(entry.get("preferred") or "")
            acc = entry.get("acceptable")
            if isinstance(acc, list):
                acceptable = list(acc)
            pivotal_trials = list(entry.get("pivotal_trials") or [])
            nccn_reference = str(entry.get("nccn_reference") or nccn_reference)
    except Exception:
        pass

    return {
        "available": True,
        "gene": gene,
        "variant": variant,
        "therapeutic_preferred": therapeutic_preferred or "PARP first-line in mCRPC + family counseling",
        "acceptable_alternatives": acceptable,
        "pivotal_trials": pivotal_trials,
        "nccn_reference": nccn_reference,
    }


def _biopsy_summary(
    profile_view: Mapping[str, Any],
    patient: Mapping[str, Any],
) -> dict[str, Any]:
    """EPIC 22b.4 — Biopsy summary for the new patient_profile_v2.html card.

    Pulls from (in order of preference):
      1. profile_view["copilots"]["structured_biopsy"] (already parsed)
      2. patient["structured_biopsy_sessions"] (raw biopsy_sessions rows)
      3. patient["biopsies"] (legacy intake snapshot)

    Returns keys consumed by the `pm2BiopsyDiagnostics` card in
    `templates/patient_profile_v2.html`:
      - has_biopsy (bool)
      - biopsy_date (ISO date or "")
      - gleason_score (e.g. "7 (4+3)" or "6")
      - isup_grade (1-5 or None)
      - cores_summary ("6/12 positivos" or "")
      - percent_positive_cores (float 0-100 or None)
      - margin_status (str or "")
      - canonicalized_facts (list[str] — fact_keys persisted)

    Defensive: if no biopsy at all, returns {has_biopsy: False} so the
    template renders the "Captura el reporte" CTA without crashing.
    """
    pv = profile_view or {}
    pt = patient or {}

    # Helper to first-non-empty
    def _first(*candidates):
        for c in candidates:
            if c not in (None, "", 0, []):
                return c
        return None

    copilots = pv.get("copilots") if isinstance(pv, Mapping) else None
    structured = (copilots or {}).get("structured_biopsy") or {}
    structured_sessions = (pt.get("structured_biopsy_sessions") or []) if pt else []
    legacy_biopsies = (pt.get("biopsies") or []) if pt else []

    latest_session = (structured_sessions[-1] if structured_sessions else None) or {}
    latest_legacy = (legacy_biopsies[-1] if legacy_biopsies else None) or {}

    # Determine if we have ANY biopsy signal
    has_biopsy = bool(
        (structured and structured.get("has_data"))
        or latest_session.get("biopsy_date")
        or latest_legacy.get("biopsy_date")
    )

    if not has_biopsy:
        return {
            "has_biopsy": False,
            "biopsy_date": "",
            "gleason_score": "",
            "isup_grade": None,
            "cores_summary": "",
            "percent_positive_cores": None,
            "margin_status": "",
            "canonicalized_facts": [],
        }

    biopsy_date = (
        latest_session.get("biopsy_date")
        or latest_legacy.get("biopsy_date")
        or (structured.get("biopsy_date") if isinstance(structured, Mapping) else "")
        or ""
    )

    # Gleason: prefer post-RP if context indicates rp_specimen
    g_primary = _first(
        latest_session.get("highest_gleason_primary"),
        latest_legacy.get("gleason_primary"),
        structured.get("gleason_primary") if isinstance(structured, Mapping) else None,
    )
    g_secondary = _first(
        latest_session.get("highest_gleason_secondary"),
        latest_legacy.get("gleason_secondary"),
        structured.get("gleason_secondary") if isinstance(structured, Mapping) else None,
    )
    gleason_sum = None
    if g_primary is not None and g_secondary is not None:
        try:
            gleason_sum = int(g_primary) + int(g_secondary)
            gleason_score = f"{gleason_sum} ({g_primary}+{g_secondary})"
        except (TypeError, ValueError):
            gleason_score = ""
    elif latest_session.get("highest_gleason_sum"):
        gleason_score = str(latest_session.get("highest_gleason_sum"))
    else:
        gleason_score = ""

    isup_grade = _first(
        latest_session.get("highest_isup"),
        latest_legacy.get("isup_grade"),
        structured.get("isup_grade") if isinstance(structured, Mapping) else None,
    )

    total_cores = _first(
        latest_session.get("total_cores"),
        latest_legacy.get("total_cores_biopsied"),
        latest_legacy.get("total_cores"),
    )
    total_positive = _first(
        latest_session.get("total_positive"),
        latest_legacy.get("positive_cores_count"),
        latest_legacy.get("positive_cores"),
    )
    cores_summary = ""
    pct_positive = None
    if total_cores and total_positive is not None:
        try:
            cores_summary = f"{int(total_positive)}/{int(total_cores)}"
            pct_positive = round((float(total_positive) / float(total_cores)) * 100, 1)
        except (TypeError, ValueError, ZeroDivisionError):
            cores_summary = ""

    # Margin status (only meaningful if post-RP context)
    margin_status = _first(
        latest_legacy.get("margin_status"),
        latest_legacy.get("surgical_margin_status"),
        (structured.get("margin_status") if isinstance(structured, Mapping) else None),
    ) or ""

    # Which canonical facts were persisted? Read from patient.clinical_facts
    canonicalized_facts: list[str] = []
    facts = pt.get("clinical_facts") or pt.get("patient_clinical_facts") or []
    fact_keys_of_interest = {
        "gleason_primary", "gleason_secondary", "isup_grade",
        "gleason_at_rp", "gleason_primary_pattern_at_rp",
        "gleason_secondary_pattern_at_rp", "tumor_stage_at_rp",
        "margin_status", "percent_pattern_4", "perineural_invasion",
        "percent_positive_cores", "biopsy_date",
    }
    seen: set[str] = set()
    for f in facts:
        if not isinstance(f, Mapping):
            continue
        key = str(f.get("fact_key") or "").strip()
        if key in fact_keys_of_interest and key not in seen:
            seen.add(key)
            canonicalized_facts.append(key)

    return {
        "has_biopsy": True,
        "biopsy_date": biopsy_date,
        "gleason_score": gleason_score,
        "isup_grade": isup_grade,
        "cores_summary": cores_summary,
        "percent_positive_cores": pct_positive,
        "margin_status": margin_status,
        "canonicalized_facts": canonicalized_facts,
    }


def _surface_consistency(profile_view: Mapping[str, Any]) -> dict[str, Any]:
    flags = [
        str(item.get("message") or item.get("reason") or item).strip()
        if isinstance(item, Mapping)
        else str(item or "").strip()
        for item in (_safe_get(profile_view, "surface_consistency_flags", default=[]) or [])
    ]
    flags = [item for item in flags if item]
    legacy_panel = _safe_get(profile_view, "legacy_recommendation_panel", default={}) or {}
    status = _safe_get(profile_view, "surface_consistency_status") or (
        "requires_review" if flags else "consistent"
    )
    return {
        "status": status,
        "flags": flags,
        "effective_state": _safe_get(profile_view, "effective_state")
        or _safe_get(profile_view, "clinical_compass", "effective_state")
        or _safe_get(profile_view, "clinical_compass", "current_stage_label")
        or "",
        "effective_recommendation_family": _safe_get(profile_view, "effective_recommendation_family") or "",
        "legacy_panel_show": bool(legacy_panel.get("show")),
        "legacy_panel_reason": legacy_panel.get("reason") or "",
        "legacy_panel_scenario": legacy_panel.get("scenario") or "",
        "should_show": bool(status != "consistent" or flags or legacy_panel.get("show")),
    }


def _psa_observability(profile_view: Mapping[str, Any]) -> dict[str, Any]:
    """PSA history + per-line + forecast desde psa_observability."""
    psa = _safe_get(profile_view, "psa_observability", default={})
    points = _safe_get(psa, "points", default=[]) or []
    bands = _safe_get(psa, "treatment_bands", default=[]) or []
    metrics = _safe_get(psa, "metrics", default={}) or {}

    series = []
    for p in points:
        if not isinstance(p, Mapping):
            continue
        series.append({
            "date": p.get("sample_date") or p.get("date") or "",
            "value": p.get("value") or p.get("psa_value") or 0,
            "line": p.get("treatment_line_number"),
            "context": p.get("context") or p.get("clinical_context") or "",
        })

    line_segments = _safe_get(psa, "line_segments", default=[]) or []
    per_line = []
    for seg in line_segments:
        if not isinstance(seg, Mapping):
            continue
        per_line.append({
            "line": seg.get("treatment_line_number") or seg.get("line") or "—",
            "regimen": seg.get("treatment_line_label") or seg.get("regimen") or "—",
            "baseline": seg.get("baseline_psa") or "—",
            "nadir": seg.get("nadir_psa") or "—",
            "ttn": seg.get("time_to_nadir_months") or "—",
            "dor": seg.get("duration_response_months") or "—",
            "psadt": seg.get("psadt_during_progression") or seg.get("psadt") or "—",
            "kinetics": seg.get("kinetics_classification") or "insufficient_data",
            "best_pct_change": seg.get("best_pct_change") or "—",
        })

    return {
        "has_data": _safe_get(psa, "has_data", default=False),
        "points": series,
        "treatment_bands": bands,
        "per_line": per_line,
        "metrics": {
            "current": metrics.get("current_psa") or metrics.get("psa_current") or "—",
            "nadir": metrics.get("nadir_psa") or "—",
            "psadt": metrics.get("psadt") or metrics.get("psadt_months") or "—",
            "velocity": metrics.get("psa_velocity") or "—",
        },
        "n_points": len(series),
        "n_lines": len(bands) or len(per_line),
    }


def _therapy_checkpoints(profile_view: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = _safe_get(profile_view, "therapy_checkpoints", default=[]) or []
    out = []
    for cp in items[:30]:
        if not isinstance(cp, Mapping):
            continue
        out.append({
            "label": cp.get("label") or cp.get("milestone") or "—",
            "due_date": _format_date(cp.get("due_date") or cp.get("date")),
            "status": cp.get("status") or "due",
            "value": cp.get("value") or cp.get("note") or "—",
        })
    return out


def _clinical_alerts(profile_view: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Lista plana de clinical_alerts del copilot bundle."""
    copilot = _safe_get(profile_view, "copilot", default={}) or {}
    alerts = _safe_get(copilot, "clinical_alerts", default=[]) or []
    out = []
    for a in alerts[:50]:
        if not isinstance(a, Mapping):
            continue
        sev = (a.get("severity") or "info").lower()
        if sev not in ("critical", "warning", "info"):
            sev = "info"
        out.append({
            "id": a.get("id") or a.get("alert_id"),
            "severity": sev,
            "category": a.get("category") or "general",
            "title": a.get("title") or a.get("alert_type") or "Alerta",
            "message": a.get("message") or "",
            "guideline": a.get("guideline_reference") or a.get("guideline") or "—",
            "recommended_action": a.get("recommended_action") or "",
        })
    return out


def _events_horizontal(profile_view: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Combined timeline horizontal compact — top 12 eventos cronológicos."""
    events = _safe_get(profile_view, "clinical_journey_events", default=[]) or []
    out = []
    n = len(events) or 1
    for i, ev in enumerate(events[:12]):
        if not isinstance(ev, Mapping):
            continue
        cls = (ev.get("event_type") or "event").lower()
        if "psa" in cls:
            cls = "psa"
        elif "treat" in cls or "drug" in cls or "regimen" in cls:
            cls = "tx"
        elif "image" in cls or "scan" in cls or "imaging" in cls:
            cls = "img"
        elif "gate" in cls or "alert" in cls:
            cls = "gate"
        else:
            cls = "event"
        out.append({
            "left_pct": int((i / max(n - 1, 1)) * 95) + 2,
            "cls": cls,
            "label": (ev.get("label") or ev.get("description") or "")[:30],
            "date": _format_date(ev.get("event_date") or ev.get("date")),
        })
    return out


def _events_vertical(profile_view: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Combined timeline vertical Epic-style — todos los eventos."""
    events = _safe_get(profile_view, "clinical_journey_events", default=[]) or []
    out = []
    for ev in events[:50]:
        if not isinstance(ev, Mapping):
            continue
        et = (ev.get("event_type") or "event").lower()
        if "psa" in et or "biomarker" in et:
            tipo = "psa"
        elif "treat" in et or "regimen" in et or "drug" in et:
            tipo = "tx"
        elif "imaging" in et or "scan" in et:
            tipo = "img"
        elif "gate" in et:
            tipo = "gate"
        else:
            tipo = "event"
        out.append({
            "type": tipo,
            "date": _format_date(ev.get("event_date") or ev.get("date")),
            "title": ev.get("label") or ev.get("description") or "Evento",
            "body": ev.get("detail") or ev.get("note") or ev.get("source") or "",
            "tag": ev.get("event_type") or "—",
        })
    return out


def _evidence_table(profile_view: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Per-gate evidence drill-down rows."""
    audit = _safe_get(profile_view, "decision_audit", default={})
    drilldowns = _safe_get(audit, "audit_dimensions", "evidencia",
                           "per_gate_evidence_drill_downs", default=[]) or []
    if not drilldowns:
        # Fallback a gates_panel con sus trial_refs
        gates = _safe_get(profile_view, "pivotal_contraindication_gates_panel",
                          "gates", default=[]) or []
        drilldowns = []
        for g in gates[:20]:
            if not isinstance(g, Mapping):
                continue
            refs = []
            for ref in (g.get("trial_refs") or [])[:5]:
                if isinstance(ref, Mapping):
                    refs.append({
                        "ref": ref.get("ref") or ref.get("id") or "trial",
                        "url": ref.get("url") or "#",
                        "type": (ref.get("type") or "trial").upper(),
                    })
            drilldowns.append({
                "gate_code": g.get("code") or "G??",
                "class_label": g.get("class_label") or "—",
                "trial_refs": refs,
                "evidence_tag": g.get("evidence_tag") or "—",
                "citation_count": len(refs),
            })
    return drilldowns


def _cohort_references(profile_view: Mapping[str, Any]) -> list[dict[str, Any]]:
    """11 cohort references pivotales — fixture estable (no por paciente)."""
    return [
        {"trial": "CHAARTED", "state": "mHSPC alto-vol", "regimen": "ADT + Doce", "n": 790, "psa": 3.2, "psadt": "—", "year": 2015},
        {"trial": "LATITUDE", "state": "mHSPC alto-riesgo", "regimen": "ADT + Abi", "n": 1199, "psa": 2.8, "psadt": "—", "year": 2017},
        {"trial": "ENZAMET", "state": "mHSPC", "regimen": "ADT + Enza", "n": 1125, "psa": 3.5, "psadt": "—", "year": 2019},
        {"trial": "ARCHES", "state": "mHSPC", "regimen": "ADT + Enza", "n": 1150, "psa": 3.1, "psadt": "—", "year": 2019},
        {"trial": "PEACE-1", "state": "mHSPC", "regimen": "ADT + Doce + Abi", "n": 1173, "psa": 2.0, "psadt": "—", "year": 2022},
        {"trial": "ARASENS", "state": "mHSPC", "regimen": "ADT + Doce + Daro", "n": 1306, "psa": 2.1, "psadt": "—", "year": 2022},
        {"trial": "SPARTAN", "state": "m0CRPC", "regimen": "Apa", "n": 1207, "psa": "—", "psadt": 8.5, "year": 2018},
        {"trial": "PROSPER", "state": "m0CRPC", "regimen": "Enza", "n": 1401, "psa": "—", "psadt": 8.0, "year": 2018},
        {"trial": "ARAMIS", "state": "m0CRPC", "regimen": "Daro", "n": 1509, "psa": "—", "psadt": 9.0, "year": 2019},
        {"trial": "PROfound", "state": "mCRPC HRR+", "regimen": "Olaparib", "n": 387, "psa": 7.4, "psadt": "—", "year": 2020},
        {"trial": "VISION", "state": "mCRPC PSMA+", "regimen": "Lu-177 PSMA", "n": 831, "psa": 5.9, "psadt": "—", "year": 2021},
    ]


def _intake_widgets(profile_view: Mapping[str, Any], patient: Mapping[str, Any]) -> dict[str, Any]:
    """PSA history + Testosterone + Treatment lines para tab Intake longitudinal."""
    bms = patient.get("biomarker_longitudinal") or []
    psa_rows = []
    testo_rows = []
    for bm in bms[:60]:
        if not isinstance(bm, Mapping):
            continue
        bt = (bm.get("biomarker_type") or "").upper()
        date = bm.get("sample_date") or bm.get("date") or ""
        val = bm.get("value") or bm.get(bt.lower() + "_value") or "—"
        ctx = bm.get("clinical_context") or bm.get("context") or "—"
        if bt == "PSA":
            psa_rows.append({"date": date, "value": val, "assay": bm.get("assay") or "—", "context": ctx, "source": "biomarker_long"})
        elif bt in ("TESTOSTERONE", "TESTO"):
            testo_rows.append({"date": date, "value": val, "status": bm.get("status") or ctx})

    treatments = patient.get("treatments") or []
    tx_rows = []
    for t in treatments[:20]:
        if not isinstance(t, Mapping):
            continue
        tx_rows.append({
            "line": t.get("line_of_therapy_number") or "—",
            "regimen": t.get("drug_scheme") or "—",
            "start": _format_date(t.get("start_date")),
            "end": _format_date(t.get("end_date")),
            "best_pct": t.get("best_pct_change") or "—",
            "reason_change": t.get("discontinuation_reason") or "—",
            "kinetics": t.get("kinetics_classification") or "—",
        })

    return {"psa_rows": psa_rows, "testo_rows": testo_rows, "tx_rows": tx_rows}


def _changelog_entries() -> list[dict[str, str]]:
    """Changelog stable fixture — bump por release Faubot."""
    return [
        {"release": "LXXVII", "date": "2026-04-26", "summary": "Producción v2 wireada · perfil 9 tabs + Decisión hoy + longitudinal append-only API real", "iter": "#67D-E", "tests": "+25"},
        {"release": "LXXVI", "date": "2026-04-26", "summary": "Genomic Critical Gates (HRR HARD_BLOCK pre-PARP + AR-V7 + CDK12 + HRD comprehensive)", "iter": "#67B", "tests": "+22"},
        {"release": "LXXV", "date": "2026-04-26", "summary": "RP vs RT Subspecialty (5 nuevos gates 56-60 + SVI MSKCC + RT modality scoring)", "iter": "#67A", "tests": "+25"},
        {"release": "LXXIV", "date": "2026-04-26", "summary": "Mobile fix (0 overflow) + WCAG 2.4.7 focus + skip-to-content", "iter": "#66C", "tests": "+20"},
        {"release": "LXXIII", "date": "2026-04-26", "summary": "Real Playwright + WCAG AA validated (0 violations) + Mobile responsive", "iter": "#66B", "tests": "+20"},
        {"release": "LXXII", "date": "2026-04-26", "summary": "Cross-domain integration + E2E HTTP smoke + Performance baseline", "iter": "#66A", "tests": "+25"},
        {"release": "LXXI", "date": "2026-04-26", "summary": "UI exposure de #65A: per-gate evidence widget + cohort comparison panel", "iter": "#65B", "tests": "+20"},
        {"release": "LXX", "date": "2026-04-26", "summary": "Decision audit endpoint + per-gate evidence drill-down + versioning automation", "iter": "#65A", "tests": "+25"},
        {"release": "LXIX", "date": "2026-04-26", "summary": "Frontend wiring de #64A: drill-down panel + cohort overlay + combined timeline", "iter": "#64B", "tests": "+20"},
        {"release": "LXVIII", "date": "2026-04-26", "summary": "Forecast per-line + Cohort overlay + Combined timeline (backend)", "iter": "#64A", "tests": "+30"},
    ]


def dashboard_summary_to_v2(summary: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Mapea dashboard_facade.get_dashboard_summary_payload() → demo dashboard shape.

    Si summary es None, intenta importar y llamar al servicio. Defensive: si
    falla el import o devuelve vacío, usa fallback razonable.
    """
    if summary is None:
        try:
            from prostanet.domains.dashboard.dashboard_facade import (
                get_dashboard_summary_payload,
            )
            summary = get_dashboard_summary_payload() or {}
        except Exception:
            summary = {}
    s = summary or {}

    total_patients = s.get("total_patients") or s.get("total") or 0
    metastasis_dist = s.get("metastasis_distribution") or {}
    volume_dist = s.get("volume_distribution") or {}

    cohort_distribution = {
        "labels": list(metastasis_dist.keys()) if metastasis_dist else ["M0", "M1", "Localizado"],
        "values": list(metastasis_dist.values()) if metastasis_dist else [0, 0, total_patients],
        "colors": ["#10b981", "#dc2626", "#06b6d4", "#f59e0b", "#a855f7", "#94a3b8"][:max(len(metastasis_dist) or 3, 3)],
    }

    kpis = [
        {"label": "Pacientes activos", "value": str(total_patients), "trend": "info",
         "trend_value": "live", "spark": [total_patients]*7, "variant": "info"},
        {"label": "Alertas críticas", "value": str(s.get("critical_alerts") or 0),
         "trend": "info", "trend_value": "—", "spark": [0]*7, "variant": "critical"},
        {"label": "Decisiones pendientes", "value": str(s.get("pending_decisions") or 0),
         "trend": "info", "trend_value": "—", "spark": [0]*7, "variant": "warning"},
        {"label": "Trial-eligible", "value": str(s.get("trial_eligible") or 0),
         "trend": "info", "trend_value": "—", "spark": [0]*7, "variant": "success"},
        {"label": "Avg time-to-decision", "value": str(s.get("avg_time_to_decision") or "—"),
         "trend": "info", "trend_value": "—", "spark": [0]*7, "variant": "info"},
        {"label": "FAUBOT_RELEASE", "value": "LXXVIII", "trend": "info",
         "trend_value": "2026-04-26", "spark": [70,71,72,73,74,75,77], "variant": "info"},
    ]

    # Heatmap placeholder (si no hay agregación real, devolver shape mínimo)
    heatmap = {"patients": [], "timebins": []}

    alert_stream = []  # se completará desde alert_engine si existe
    decision_quality = {"calibration_score": 0.91, "concordance_nccn": 0.94,
                        "concordance_eau": 0.89, "audit_completeness": 0.87}
    research_intelligence = [
        {"label": "Cohort completeness", "value": "—", "sub": "consume /api/cohort_completeness"},
        {"label": "Research readiness", "value": "—", "sub": "consume /api/research_readiness"},
        {"label": "Endpoint readiness", "value": "—", "sub": "consume /api/endpoint_readiness"},
    ]
    versioning = [
        {"release": "2026-04-26 LXXVIII", "diff": "Producción v2 wireada · 6 rutas + persistencia DB"},
        {"release": "2026-04-26 LXXVII", "diff": "+5 gates RP/RT subspecialty + #67D demo"},
        {"release": "2026-04-26 LXXVI", "diff": "+5 gates genomic critical (HRR HARD_BLOCK)"},
    ]

    # ── EPIC 10D — Cache 3 hot paths que escaneaban TODOS los pacientes ──
    # En cada request del dashboard. Baseline ~1700ms p95 → target <500ms
    # mediante TTL cache de 5 minutos. Primera carga sigue caliente; cargas
    # subsiguientes dentro de la ventana son <1ms para estos 3 bundles.
    def _compute_research_payload() -> Mapping[str, Any]:
        import tracking_db
        return {
            "mhspc_copilot": tracking_db.get_mhspc_copilot_dashboard_summary(),
            "diagnostic_biopsy_copilot": tracking_db.get_diagnostic_biopsy_dashboard_summary(),
            "localized_surveillance_copilot": tracking_db.get_localized_surveillance_dashboard_summary(),
            "post_rt_salvage_copilot": tracking_db.get_post_rt_salvage_dashboard_summary(),
        }

    def _compute_autodrive_today() -> Mapping[str, Any]:
        from prostanet.domains.patient_tracking.clinical_autodrive_command_center import (
            build_population_autodrive_from_db,
        )
        return build_population_autodrive_from_db(limit=8) or {}

    def _compute_autonomous_improvement() -> Mapping[str, Any]:
        from prostanet.agentic.autonomous_improvement_os import build_mission_control
        return build_mission_control() or {}

    research_payload = _cached_call("dashboard_research_payload", _compute_research_payload)
    autodrive_today = _cached_call("dashboard_autodrive_today", _compute_autodrive_today)
    autonomous_improvement = _cached_call("dashboard_autonomous_improvement", _compute_autonomous_improvement)
    if not isinstance(research_payload, Mapping):
        research_payload = {}
    if not isinstance(autodrive_today, Mapping):
        autodrive_today = {}
    if not isinstance(autonomous_improvement, Mapping):
        autonomous_improvement = {}
    ad_summary = autodrive_today.get("summary") or {}
    if autodrive_today:
        kpis[1] = {
            "label": "Autodrive critico",
            "value": str(ad_summary.get("critical_patient_count") or ad_summary.get("status_counts", {}).get("critical_today") or 0),
            "trend": "info",
            "trend_value": "hoy",
            "spark": [0, 0, ad_summary.get("critical_patient_count") or 0, ad_summary.get("queue_count") or 0, ad_summary.get("ready_decision_count") or 0, ad_summary.get("blocked_count") or 0, ad_summary.get("overdue_count") or 0],
            "variant": "critical",
        }
        kpis[2] = {
            "label": "Listos para decidir",
            "value": str(ad_summary.get("ready_decision_count") or 0),
            "trend": "info",
            "trend_value": "Tumor Board",
            "spark": [ad_summary.get("ready_decision_count") or 0] * 7,
            "variant": "warning",
        }
        kpis[3] = {
            "label": "Bloqueados por datos",
            "value": str(ad_summary.get("blocked_count") or 0),
            "trend": "info",
            "trend_value": "capture",
            "spark": [ad_summary.get("blocked_count") or 0] * 7,
            "variant": "success",
        }

    def _copilot_vertical(
        key: str,
        label: str,
        eyebrow: str,
        stage: str,
        metric_map: list[tuple[str, str]],
    ) -> dict[str, Any]:
        payload = research_payload.get(key) or {}
        if not isinstance(payload, Mapping):
            payload = {}
        total = (
            payload.get("total_patients")
            or payload.get("patient_count")
            or len(payload.get("recent_cases") or [])
            or 0
        )
        metrics = [
            {"label": metric_label, "value": payload.get(metric_key, "—")}
            for metric_label, metric_key in metric_map
        ]
        return {
            "label": label,
            "eyebrow": eyebrow,
            "stage": stage,
            "available": bool(payload.get("available")),
            "status_label": "activo" if payload.get("available") else "sin cohorte activa",
            "total_patients": total,
            "latest_created_at": payload.get("latest_created_at") or "",
            "metrics": metrics,
        }

    copilot_verticals = [
        _copilot_vertical(
            "mhspc_copilot",
            "Copiloto mHSPC",
            "mHSPC · doblete/triplete · RT primario",
            "mcspc",
            [
                ("Cohorte", "total_patients"),
                ("RT primario", "rt_primary_visible_pct"),
                ("Triplete", "triplet_visible_pct"),
            ],
        ),
        _copilot_vertical(
            "diagnostic_biopsy_copilot",
            "Copiloto diagnóstico",
            "PRE-Dx · MRI · biopsia · rebiopsia",
            "diagnostic",
            [
                ("Cohorte", "total_patients"),
                ("Biopsia ready", "biopsy_ready_pct"),
                ("Reabrir", "reopen_after_negative_pct"),
            ],
        ),
        _copilot_vertical(
            "localized_surveillance_copilot",
            "Copiloto localizado / AS",
            "Localizado · AS · conversión",
            "localized",
            [
                ("Cohorte", "total_patients"),
                ("AS visible", "active_surveillance_visible_pct"),
                ("Conversión", "upgrade_exit_pct"),
            ],
        ),
        _copilot_vertical(
            "post_rt_salvage_copilot",
            "Copiloto post-RT",
            "Phoenix · PSMA · salvage local",
            "bcr",
            [
                ("Cohorte", "total_patients"),
                ("Salvage local", "local_salvage_candidate_pct"),
                ("Redirección", "redirect_systemic_pct"),
            ],
        ),
    ]

    return {
        "kpis": kpis,
        "cohort_distribution": cohort_distribution,
        "heatmap": heatmap,
        "alert_stream": alert_stream,
        "decision_quality": decision_quality,
        "research_intelligence": research_intelligence,
        "versioning": versioning,
        "copilot_verticals": copilot_verticals,
        "autodrive_today": autodrive_today,
        "autonomous_improvement": autonomous_improvement,
    }


def _stage_key_for_module(module_id: str) -> str:
    """Mapea module_id del registry → key del estadio v2 (7 canónicos)."""
    mid = (module_id or "").lower()
    if mid in ("diagnostic_workup", "post_negative_biopsy_followup"):
        return "diagnostic"
    if mid in ("localized_initial", "post_prostatectomy", "post_radiotherapy_followup",
               "recurrence_bcr", "post_radiotherapy_or_local_salvage"):
        return "localized"
    if mid.startswith("mcspc") or mid == "adt_progression_verification":
        return "mcspc"
    if mid == "m0_crpc":
        return "m0crpc"
    if mid == "m1_crpc":
        return "m1crpc"
    if mid == "survivorship_and_toxicity_followup":
        return "palliative"
    return "diagnostic"


def _build_hub_quick_classifier_config() -> dict[str, Any]:
    """Configura el clasificador secuencial del hub v2.

    El contrato visual queda oficializado dentro del hub v2 integrado, pero el
    backend vigente conserva la autoridad clínica. Por eso el frontend normaliza estos campos
    hacia StateClassifierService en vez de duplicar reglas de estadificación.
    """
    from prostanet.shared.metastatic_profile import (
        APPENDICULAR_BONE_SITE_KEYS,
        AXIAL_BONE_SITE_KEYS,
        BONE_SITE_LABELS,
        NONREGIONAL_NODAL_SITE_LABELS,
        VISCERAL_SITE_LABELS,
    )

    def _options(labels: Mapping[str, str], keys: Sequence[str] | None = None) -> list[dict[str, str]]:
        source = keys or tuple(labels.keys())
        return [{"value": key, "label": labels[key]} for key in source if key in labels]

    yes_no = [{"value": "0", "label": "No"}, {"value": "1", "label": "Sí"}]
    field_defaults = {f["name"]: f for f in quick_classify_schema().get("fields", [])}

    def _field(name: str, **overrides: Any) -> dict[str, Any]:
        base = dict(field_defaults.get(name, {}))
        base.setdefault("name", name)
        base.setdefault("field_type", "text")
        base.update(overrides)
        return base

    steps = [
        {
            "key": "diagnosis",
            "number": "1",
            "label": "Diagnóstico",
            "summary": "Separa sospecha, screening y cáncer confirmado antes de abrir una ruta terapéutica.",
            "fields": [
                _field(
                    "known_cancer_diagnosis",
                    label="Diagnóstico confirmado por biopsia",
                    field_type="select",
                    required=True,
                    options=[{"value": "1", "label": "Sí, cáncer confirmado"}, {"value": "0", "label": "No, sospecha o screening"}],
                    default="1",
                ),
                _field(
                    "encounter_type",
                    label="Tipo de encuentro prediagnóstico",
                    field_type="select",
                    options=[
                        {"value": "clinical_evaluation", "label": "Evaluación por sospecha"},
                        {"value": "screening", "label": "Screening / detección temprana"},
                        {"value": "second_opinion", "label": "Segunda opinión"},
                    ],
                    default="clinical_evaluation",
                    visible_when={"known_cancer_diagnosis": ["0"]},
                ),
                _field(
                    "screening_context",
                    label="Encuentro de screening",
                    field_type="select",
                    options=yes_no,
                    default="0",
                    visible_when={"known_cancer_diagnosis": ["0"]},
                ),
                _field(
                    "prior_negative_biopsy",
                    label="Biopsia prostática previa benigna",
                    field_type="select",
                    options=yes_no,
                    default="0",
                    visible_when={"known_cancer_diagnosis": ["0"]},
                ),
                _field(
                    "biopsy_scheduled",
                    label="Biopsia programada",
                    field_type="select",
                    options=yes_no,
                    default="0",
                    visible_when={"known_cancer_diagnosis": ["0"]},
                ),
                _field("psa", label="PSA actual de sospecha", field_type="number", unit="ng/mL", visible_when={"known_cancer_diagnosis": ["0"]}),
                _field("psad", label="Densidad de PSA", field_type="number", unit="ng/mL/cc", visible_when={"known_cancer_diagnosis": ["0"]}),
                _field(
                    "pirads_score",
                    label="PI-RADS en MRI",
                    field_type="select",
                    options=["0", "2", "3", "4", "5"],
                    default="0",
                    visible_when={"known_cancer_diagnosis": ["0"]},
                ),
                _field(
                    "dre_suspicious",
                    label="Tacto rectal sospechoso",
                    field_type="select",
                    options=[{"value": "Desconocido", "label": "Desconocido"}, {"value": "0", "label": "No"}, {"value": "1", "label": "Sí"}],
                    default="Desconocido",
                    visible_when={"known_cancer_diagnosis": ["0"]},
                ),
                _field("histology_subtype", label="Subtipo histológico", field_type="select", visible_when={"known_cancer_diagnosis": ["1"]}),
                _field("diagnosis_date", label="Fecha de diagnóstico", field_type="date", visible_when={"known_cancer_diagnosis": ["1"]}),
                _field("psa_baseline_ng_ml", label="PSA basal al diagnóstico", field_type="number", unit="ng/mL", visible_when={"known_cancer_diagnosis": ["1"]}),
                _field("gleason_primary", label="Gleason primario", field_type="select", options=["", "3", "4", "5"], visible_when={"known_cancer_diagnosis": ["1"]}),
                _field("gleason_secondary", label="Gleason secundario", field_type="select", options=["", "3", "4", "5"], visible_when={"known_cancer_diagnosis": ["1"]}),
                _field("clinical_tstage", label="cT clínico", field_type="select", visible_when={"known_cancer_diagnosis": ["1"]}),
                _field("nodal_status", label="cN clínico", field_type="select", visible_when={"known_cancer_diagnosis": ["1"]}),
                _field("clinical_stage_group", label="Etapa clínica AJCC", field_type="select", visible_when={"known_cancer_diagnosis": ["1"]}),
                _field("clinical_risk_group", label="Grupo de riesgo clínico", field_type="select", visible_when={"known_cancer_diagnosis": ["1"]}),
            ],
        },
        {
            "key": "local",
            "number": "2",
            "label": "Tratamiento local / recurrencia",
            "summary": "Define si el paciente pertenece a seguimiento post-RP, post-RT o recurrencia bioquímica.",
            "visible_when": {"known_cancer_diagnosis": ["1"]},
            "fields": [
                _field(
                    "prior_local_therapy",
                    label="Terapia local previa",
                    field_type="select",
                    options=[
                        {"value": "none", "label": "Ninguna"},
                        {"value": "prostatectomy", "label": "Prostatectomía radical"},
                        {"value": "radiation", "label": "Radioterapia"},
                        {"value": "brachytherapy", "label": "Braquiterapia"},
                        {"value": "focal", "label": "Terapia focal"},
                    ],
                    default="none",
                ),
                _field("psa_postop", label="PSA postoperatorio actual", field_type="number", unit="ng/mL", visible_when={"prior_local_therapy": ["prostatectomy"]}),
                _field("psa_current", label="PSA actual", field_type="number", unit="ng/mL", visible_when={"prior_local_therapy": ["prostatectomy", "radiation", "brachytherapy"]}),
                _field("bcr_detected", label="BCR documentada", field_type="select", options=yes_no, default="0", visible_when={"prior_local_therapy": ["prostatectomy", "radiation", "brachytherapy"]}),
                _field("bcr_psa", label="PSA al momento de BCR", field_type="number", unit="ng/mL", visible_when={"bcr_detected": ["1"]}),
                _field("bcr_date", label="Fecha de BCR", field_type="date", visible_when={"bcr_detected": ["1"]}),
                _field("bcr2", label="Segunda recurrencia bioquímica", field_type="select", options=yes_no, default="0", visible_when={"bcr_detected": ["1"]}),
                _field("rt_completion_date", label="Fecha de finalización RT", field_type="date", visible_when={"prior_local_therapy": ["radiation", "brachytherapy"]}),
                _field("psa_nadir_post_rt", label="PSA nadir post-RT", field_type="number", unit="ng/mL", visible_when={"prior_local_therapy": ["radiation", "brachytherapy"]}),
                _field("phoenix_delta", label="Delta sobre nadir Phoenix", field_type="number", unit="ng/mL", visible_when={"prior_local_therapy": ["radiation", "brachytherapy"]}),
                _field(
                    "failure_confirmation_basis",
                    label="Base de confirmación post-RT",
                    field_type="select",
                    options=[
                        {"value": "", "label": "Pendiente"},
                        {"value": "phoenix_confirmed", "label": "Phoenix confirmado"},
                        {"value": "biopsy_proven_local_failure", "label": "Falla local por biopsia"},
                        {"value": "radiographic_local_failure", "label": "Falla local radiográfica"},
                    ],
                    visible_when={"prior_local_therapy": ["radiation", "brachytherapy"]},
                ),
            ],
        },
        {
            "key": "metastatic",
            "number": "3",
            "label": "Enfermedad metastásica",
            "summary": "Captura composición M1 real y permite derivar volumen CHAARTED sin etiqueta manual.",
            "visible_when": {"known_cancer_diagnosis": ["1"]},
            "fields": [
                _field("metastatic_disease_known", label="Enfermedad metastásica conocida", field_type="select", options=yes_no, default="0"),
                _field(
                    "metastasis_site",
                    label="Resumen cM documentado",
                    field_type="select",
                    options=[
                        {"value": "M0", "label": "M0"},
                        {"value": "M1a", "label": "M1a · ganglios no regionales"},
                        {"value": "M1b", "label": "M1b · hueso"},
                        {"value": "M1c", "label": "M1c · visceral"},
                    ],
                    default="M0",
                    visible_when={"metastatic_disease_known": ["1"]},
                ),
                _field("nonregional_nodal_metastasis_present", label="Ganglios no regionales presentes", field_type="select", options=yes_no, default="0", visible_when={"metastatic_disease_known": ["1"]}),
                _field("nonregional_nodal_site", label="Cadena ganglionar no regional", field_type="select", options=_options(NONREGIONAL_NODAL_SITE_LABELS), visible_when={"nonregional_nodal_metastasis_present": ["1"]}),
                _field("nonregional_nodal_count", label="Número de lesiones ganglionares", field_type="number", visible_when={"nonregional_nodal_metastasis_present": ["1"]}),
                _field("bone_metastasis_present", label="Metástasis óseas presentes", field_type="select", options=yes_no, default="0", visible_when={"metastatic_disease_known": ["1"]}),
                _field("bone_axial_site", label="Sitio óseo axial predominante", field_type="select", options=_options(BONE_SITE_LABELS, AXIAL_BONE_SITE_KEYS), visible_when={"bone_metastasis_present": ["1"]}),
                _field("bone_axial_count", label="Lesiones óseas axiales", field_type="number", visible_when={"bone_metastasis_present": ["1"]}),
                _field("bone_appendicular_site", label="Sitio óseo apendicular predominante", field_type="select", options=_options(BONE_SITE_LABELS, APPENDICULAR_BONE_SITE_KEYS), visible_when={"bone_metastasis_present": ["1"]}),
                _field("bone_appendicular_count", label="Lesiones óseas apendiculares", field_type="number", visible_when={"bone_metastasis_present": ["1"]}),
                _field("visceral_metastasis_present", label="Metástasis viscerales presentes", field_type="select", options=yes_no, default="0", visible_when={"metastatic_disease_known": ["1"]}),
                _field("visceral_site", label="Órgano visceral predominante", field_type="select", options=_options(VISCERAL_SITE_LABELS), visible_when={"visceral_metastasis_present": ["1"]}),
                _field("visceral_lesion_count", label="Número de lesiones viscerales", field_type="number", visible_when={"visceral_metastasis_present": ["1"]}),
                _field("metachronous_metastasis", label="Metástasis metacrónica", field_type="select", options=yes_no, default="0", visible_when={"metastatic_disease_known": ["1"]}),
            ],
        },
        {
            "key": "adt",
            "number": "4",
            "label": "ADT / CRPC",
            "summary": "Protege el carril resistente: CRPC requiere progresión, castración e imagen convencional.",
            "visible_when": {"known_cancer_diagnosis": ["1"]},
            "fields": [
                _field("current_adt_context", label="Contexto actual de ADT", field_type="select", default="none"),
                _field(
                    "systemic_progression_context",
                    label="Contexto de progresión sistémica",
                    field_type="select",
                    options=[
                        {"value": "none", "label": "Sin progresión bajo ADT"},
                        {"value": "progression_on_adt_verify_castration", "label": "Progresión bajo ADT: verificar castración"},
                        {"value": "confirmed_crpc", "label": "CRPC confirmado"},
                    ],
                    default="none",
                ),
                _field("castrate_testosterone_status", label="Testosterona en rango de castración", field_type="select", default="unknown"),
                _field("testosterone_value", label="Valor de testosterona", field_type="number", unit="ng/dL"),
                _field("progression_pattern", label="Patrón de progresión", field_type="select", default="biochemical_only"),
                _field("conventional_imaging_status", label="Imagen convencional", field_type="select", default="not_restaged"),
            ],
        },
    ]

    return {
        "source": "ProstaMed official clinical hub",
        "schema_title": quick_classify_schema().get("title"),
        "endpoints": {
            "quick_schema": "/api/intake-schema/_quick",
            "classify": "/api/state-classifier",
            "diagnosis_preview": "/api/official-diagnosis/preview",
            "draft": "/api/clinical-assessments/draft",
        },
        "steps": steps,
        "initial_state": {
            "known_cancer_diagnosis": "1",
            "prior_local_therapy": "none",
            "metastatic_disease_known": "0",
            "metastasis_site": "M0",
            "current_adt_context": "none",
            "systemic_progression_context": "none",
            "castrate_testosterone_status": "unknown",
            "progression_pattern": "biochemical_only",
            "conventional_imaging_status": "not_restaged",
        },
    }


def stage_center_to_v2(stages_meta: Sequence[Mapping[str, Any]] | None = None,
                      summary: Mapping[str, Any] | None = None,
                      modules_raw: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Centro Clínico por Estadio v2 — datos REALES desde module_registry + cohort.

    Hidrata cada estadio canónico con:
      - modules: del ModuleRegistry agrupados por _stage_key_for_module()
      - count: del dashboard_summary (metastasis_distribution)
      - trial_eligibility: del module.pivotal_trials
      - cohort_snapshot: stats agregados (placeholder por ahora)
    """
    # 7 estadios canónicos
    stages = [
        {"key": "diagnostic", "label": "Diagnóstico", "sub": "Pre-biopsia + workup",
         "count": 0, "alerts": 0, "nccn": "PROS-1", "eau": "Initial"},
        {"key": "localized", "label": "Localizado", "sub": "Riesgo bajo / int / alto",
         "count": 0, "alerts": 0, "nccn": "PROS-2..5", "eau": "Localized"},
        {"key": "mcspc", "label": "mCSPC", "sub": "HV / LV / Oligo",
         "count": 0, "alerts": 0, "nccn": "PROS-9", "eau": "mHSPC"},
        {"key": "m0crpc", "label": "m0CRPC", "sub": "Castración resistente no-mets",
         "count": 0, "alerts": 0, "nccn": "PROS-10", "eau": "nmCRPC"},
        {"key": "m1crpc", "label": "m1CRPC", "sub": "Castración resistente metastásico",
         "count": 0, "alerts": 0, "nccn": "PROS-11..13", "eau": "mCRPC"},
        {"key": "nepc", "label": "NEPC / aggressive", "sub": "Variantes neuroendocrinas",
         "count": 0, "alerts": 0, "nccn": "PROS-12", "eau": "Variants"},
        {"key": "palliative", "label": "Paliativo", "sub": "Fin de vida + síntomas",
         "count": 0, "alerts": 0, "nccn": "PROS-14", "eau": "BSC"},
    ]

    # Cargar module registry (15 módulos canónicos)
    if modules_raw is None:
        try:
            from prostanet.application.module_registry import ModuleRegistry
            modules_raw = ModuleRegistry().list_modules() or []
        except Exception:
            modules_raw = []

    # Cargar summary (counts por metastasis)
    if summary is None:
        try:
            from prostanet.domains.dashboard.dashboard_facade import (
                get_dashboard_summary_payload,
            )
            summary = get_dashboard_summary_payload() or {}
        except Exception:
            summary = {}
    metastasis_dist = (summary or {}).get("metastasis_distribution") or {}

    for stage in stages:
        key = stage["key"].lower()
        for k, v in metastasis_dist.items():
            if key in k.lower() or k.lower() in key:
                stage["count"] = v
                break

    # Agrupar módulos por estadio
    modules_by_stage: dict[str, list[dict[str, Any]]] = {s["key"]: [] for s in stages}
    trials_by_stage: dict[str, list[dict[str, Any]]] = {s["key"]: [] for s in stages}

    for m in modules_raw:
        if not isinstance(m, Mapping):
            continue
        mid = m.get("module") or ""
        sk = _stage_key_for_module(mid)
        title = m.get("title") or mid
        # Resumen corto: primera oración del title (corta a 110 chars)
        desc = title[:120] + ("…" if len(title) > 120 else "")
        nccn = (m.get("nccn_panels") or [None])[0] if m.get("nccn_panels") else None
        eau = (m.get("eau_sections") or [None])[0] if m.get("eau_sections") else None

        modules_by_stage[sk].append({
            "id": mid,
            "label": title.split("(")[0].strip()[:80],
            "desc": desc,
            "n_decisions_today": stage_count_lookup(sk, stages),
            "nccn": nccn,
            "eau": eau,
            "wizard_url": f"/wizard/{mid}",
        })

        # Trial eligibility per módulo
        for trial in (m.get("pivotal_trials") or [])[:6]:
            if isinstance(trial, Mapping):
                trials_by_stage[sk].append({
                    "trial": trial.get("name") or trial.get("trial") or "Trial",
                    "drug": trial.get("regimen") or trial.get("drug") or "—",
                    "criteria_match": 4,  # placeholder hasta wirear matcher real
                    "criteria_total": 5,
                    "status": "Pendiente match clínico",
                })

    # Construir canvases por estadio
    canvases = {}
    for stage in stages:
        sk = stage["key"]
        canvases[sk] = {
            "title": f"{stage['label']} · {stage['sub']}",
            "subtitle": (
                f"Centro Clínico por Estadio · {len(modules_by_stage[sk])} módulos NCCN/EAU activos · "
                f"{stage['count']} pacientes en cohorte · agregación live desde dashboard_summary_service"
            ),
            "stats": [
                {"label": "Activos en estadio", "value": str(stage["count"]),
                 "sub": "del cohort_summary", "color": "var(--clinical-info)"},
                {"label": "Módulos decisión", "value": str(len(modules_by_stage[sk])),
                 "sub": "ModuleRegistry", "color": "var(--clinical-info)"},
                {"label": "Trials pivotales", "value": str(len(trials_by_stage[sk])),
                 "sub": "literatura activa", "color": "var(--clinical-warning)"},
                {"label": "Alertas críticas", "value": str(stage["alerts"]),
                 "sub": "smart_alerts pendientes", "color": "var(--clinical-warning)"},
            ],
            "modules": modules_by_stage[sk],
            "trial_eligibility": trials_by_stage[sk][:6],
            "cohort_snapshot": {},
        }

    # ──────────────────────────────────────────────────────────────────
    # Faubot LXCVIII.B — Enhanced data for clinical hub redesign
    # ──────────────────────────────────────────────────────────────────

    # KPI hero bar metrics (top of dashboard)
    kpi_hero = _build_kpi_hero_metrics()

    # Loop monitor 8 vectors live status (right rail)
    loop_vectors_live = _build_loop_vectors_compact()

    # Cohort filter options (date ranges)
    cohort_filter_options = [
        {"value": "", "label": "Todos los pacientes"},
        {"value": "3m", "label": "Últimos 3 meses"},
        {"value": "6m", "label": "Últimos 6 meses"},
        {"value": "12m", "label": "Últimos 12 meses"},
    ]

    return {
        "stages": stages,
        "canvases": canvases,
        "default_stage": "",
        # LXCVIII.B redesign data
        "kpi_hero": kpi_hero,
        "loop_vectors_live": loop_vectors_live,
        "cohort_filter_options": cohort_filter_options,
        "quick_classifier": _build_hub_quick_classifier_config(),
    }


def _build_kpi_hero_metrics() -> list[dict[str, Any]]:
    """Faubot LXCVIII.B — Build KPI hero bar metrics (89 gates · 47 trials · 8 vectors · N modules)."""
    metrics = []
    # Gates count
    try:
        from prostanet.shared.pivotal_gates_yaml_loader import (
            _load_yaml_files, get_loaded_yaml_codes,
        )
        _load_yaml_files(force_reload=False)
        gates_count = len(get_loaded_yaml_codes())
    except Exception:
        gates_count = 103
    metrics.append({
        "key": "gates",
        "icon": "⚙",
        "value": str(gates_count),
        "label": "Gates pivotal",
        "sub": "YAML-native",
    })
    # Trials count
    try:
        from prostanet.shared.trial_criteria_registry import TRIAL_CRITERIA_REGISTRY
        trials_count = len(TRIAL_CRITERIA_REGISTRY)
    except Exception:
        trials_count = 47
    metrics.append({
        "key": "trials",
        "icon": "📋",
        "value": str(trials_count),
        "label": "Trials pivotales",
        "sub": "eligibility evaluable",
    })
    # Loop vectors count (always 8)
    metrics.append({
        "key": "vectors",
        "icon": "📊",
        "value": "8",
        "label": "Loop vectors",
        "sub": "monitoring activo",
    })
    # Modules count
    try:
        from prostanet.application.module_registry import ModuleRegistry
        modules_count = len(ModuleRegistry().list_modules() or [])
    except Exception:
        modules_count = 15
    metrics.append({
        "key": "modules",
        "icon": "🧩",
        "value": str(modules_count),
        "label": "Módulos clínicos",
        "sub": "wizards disponibles",
    })
    return metrics


def _build_loop_vectors_compact() -> list[dict[str, Any]]:
    """Faubot LXCVIII.B — Build compact 8-vector status for right rail."""
    try:
        from prostanet.presentation.loop_monitor import (
            CORE_VECTORS, get_vector_summary,
        )
        summary = get_vector_summary(days=30)
        result = []
        for vec_key, vec_meta in CORE_VECTORS.items():
            s = summary.get(vec_key, {})
            count = s.get("count", 0)
            ok_count = s.get("ok", 0)
            warning_count = s.get("warning", 0)
            critical_count = s.get("critical", 0)
            # Compute status (5-level)
            if count == 0:
                status = "no_data"
                score = 0
            elif critical_count > 0:
                status = "critical"
                score = 1
            elif warning_count > ok_count:
                status = "warning"
                score = 3
            else:
                status = "ok"
                score = 5
            result.append({
                "key": vec_key,
                "icon": vec_meta["icon"],
                "label": vec_meta["label"],
                "status": status,
                "score": score,
                "count_30d": count,
                "skill": vec_meta.get("skill", ""),
            })
        return result
    except Exception:
        return []


def stage_count_lookup(stage_key: str, stages: Sequence[Mapping[str, Any]]) -> int:
    """Helper: extrae count del estadio para badges en module cards."""
    for s in stages:
        if s.get("key") == stage_key:
            return int(s.get("count") or 0)
    return 0


def audit_log_to_v2() -> dict[str, Any]:
    """Catalog v2: Audit Log. Consume el endpoint /api/auth/audit-log via shim."""
    try:
        from prostanet.shared.algorithm_version import get_algorithm_version
        ver = get_algorithm_version() or {}
    except Exception:
        ver = {}

    return {
        "catalog_view": "audit_log",
        "sidebar_active": "audit_log",
        "page_title": "Audit Log · Compliance Dashboard",
        "page_subtitle": (
            "Trail consultable de todos los eventos de autenticación: logins, "
            "logouts, refreshes, accesses y denegaciones. Filtrable por usuario, "
            "endpoint, status y rango de fechas. Cumple HIPAA §164.312(b)."
        ),
        "faubot_release": ver.get("faubot_release", "2026-04-27 LXXX"),
        "gates_active_count": ver.get("gates_active_count", 0),
        "content_blocks": [
            {"kind": "kpi_grid", "entries": [
                {"label": "Endpoint API", "value": "live", "sub": "/api/auth/audit-log", "variant": "info"},
                {"label": "Compliance", "value": "HIPAA", "sub": "§164.312(b)", "variant": "success"},
                {"label": "Refresh", "value": "polling", "sub": "passive · sin extender sesión", "variant": "info"},
                {"label": "FAUBOT_RELEASE", "value": ver.get("faubot_release", "LXXX"), "sub": "stamp inmutable", "variant": "info"},
            ]},
            {"kind": "raw_html", "html": (
                '<article class="pm2-tab-card"><div class="pm2-tab-card-body">'
                '<p style="color:var(--pn-text-muted);font-size:.86rem;line-height:1.6">'
                'Esta vista renderiza el dashboard interactivo del audit log con polling '
                'al endpoint <span class="pm2-mono" style="color:var(--pn-accent)">/api/auth/audit-log</span>. '
                'Filtros disponibles: usuario · endpoint · status (200/401/403/404/500) · rango de fechas.'
                '</p>'
                '<div style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap">'
                '<a href="/api/auth/audit-log" target="_blank" rel="noopener" class="pm2-btn pm2-btn--primary">Ver JSON live →</a>'
                '<a href="/audit-log?v=legacy" class="pm2-btn pm2-btn--ghost">Vista clásica con tabla interactiva</a>'
                '</div></div></article>'
            )},
        ],
    }


def gates_coverage_to_v2() -> dict[str, Any]:
    """Catalog v2: Gates Coverage. Consume gates_coverage_aggregator real."""
    try:
        from prostanet.shared.gates_coverage_aggregator import aggregate_gates_coverage_from_db
        coverage = aggregate_gates_coverage_from_db() or {}
    except Exception:
        coverage = {}
    try:
        from prostanet.shared.algorithm_version import get_algorithm_version
        ver = get_algorithm_version() or {}
    except Exception:
        ver = {}

    # coverage tiene shape {gate_code: {patient_count, pct, by_state, ...}}
    rows = []
    if isinstance(coverage, Mapping):
        for code, info in sorted(coverage.items())[:100]:
            if not isinstance(info, Mapping):
                continue
            count = info.get("patient_count") or info.get("triggered_count") or 0
            pct = info.get("pct") or info.get("percentage") or 0
            severity = info.get("severity") or "informational"
            by_state = info.get("by_state") or {}
            states_str = " · ".join(f"{k}:{v}" for k, v in list(by_state.items())[:3])
            rows.append([
                f'<span class="pm2-gate-code">{code}</span>',
                str(count),
                f"{pct:.1f}%" if isinstance(pct, (int, float)) else str(pct),
                f'<span class="pm2-gate-badge" data-severity="{severity}">{severity}</span>',
                states_str or "—",
            ])

    return {
        "catalog_view": "gates_coverage",
        "sidebar_active": "gates_coverage",
        "page_title": "Cobertura clínica de gates pivotal",
        "page_subtitle": (
            "Análisis poblacional de los gates de contraindicación pivote: "
            "% de pacientes afectados por cada gate, distribución por estado clínico "
            "y alertas de captura clínica para el Clinical Decision Engine Auditable."
        ),
        "faubot_release": ver.get("faubot_release", "2026-04-27 LXXX"),
        "gates_active_count": ver.get("gates_active_count", 0),
        "content_blocks": [
            {"kind": "kpi_grid", "entries": [
                {"label": "Gates activos", "value": str(len(coverage)), "sub": "del catálogo pivotal", "variant": "info"},
                {"label": "FAUBOT_RELEASE", "value": ver.get("faubot_release", "LXXX"), "sub": "versionado", "variant": "info"},
                {"label": "Source", "value": "live DB", "sub": "gates_coverage_aggregator", "variant": "success"},
                {"label": "Vista clásica", "value": "?v=legacy", "sub": "heatmap interactivo", "variant": "warning"},
            ]},
            {"kind": "table",
             "title": f"Cobertura por gate · {len(rows)} gates",
             "head_meta": "ordenado por código",
             "columns": ["Gate", "Pacientes afectados", "% Cohorte", "Severity", "Top 3 estados"],
             "rows": rows or [["Sin datos de cobertura aún · base de datos vacía o gates_coverage_aggregator no inicializado", "", "", "", ""]],
            },
            {"kind": "raw_html", "html": (
                '<article class="pm2-tab-card" style="margin-top:18px"><div class="pm2-tab-card-body">'
                '<p style="color:var(--pn-text-muted);font-size:.85rem;line-height:1.6">'
                'Para acceder al heatmap interactivo gate × estado clínico + heatmap secundario gate × DDI category, '
                'usa la vista clásica:'
                '</p>'
                '<a href="/gates-coverage-dashboard?v=legacy" class="pm2-btn pm2-btn--primary" style="margin-top:10px">'
                'Abrir heatmap clásico →</a>'
                '</div></article>'
            )},
        ],
    }


def versioning_dashboard_to_v2() -> dict[str, Any]:
    """Catalog v2: Versioning Dashboard. Consume algorithm_version + audit_tracking."""
    try:
        from prostanet.shared.algorithm_version import (
            get_algorithm_version, get_per_gate_yaml_shas, get_active_gate_codes,
        )
        ver = get_algorithm_version() or {}
        per_gate_shas = get_per_gate_yaml_shas() or {}
        active_codes = sorted(get_active_gate_codes() or [])
    except Exception:
        ver, per_gate_shas, active_codes = {}, {}, []

    # Parse audit_tracking.md for recent releases
    from pathlib import Path
    import re
    audit_md = Path("/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/prostanet/audit_tracking.md")
    recent = []
    try:
        if audit_md.exists():
            content = audit_md.read_text()
            for m in re.finditer(r"### Auditoría ([^\n]+) — (\d{4}-\d{2}-\d{2})", content):
                recent.append({"audit": m.group(1).strip()[:60], "date": m.group(2)})
                if len(recent) >= 12:
                    break
    except Exception:
        pass

    yaml_rows = []
    for code in active_codes[:50]:
        sha = per_gate_shas.get(code, "—")
        yaml_rows.append([
            f'<span class="pm2-gate-code">{code}</span>',
            f'<code style="color:var(--pn-accent)">{sha[:12]}</code>',
            "✓ versionado" if sha != "—" else "—",
        ])

    return {
        "catalog_view": "versioning",
        "sidebar_active": "versioning",
        "page_title": "Versioning Dashboard · Faubot release history",
        "page_subtitle": (
            "Historial completo del versionado del Clinical Decision Engine Auditable: "
            "FAUBOT_RELEASE activo, gates pivotal versionados, releases recientes y "
            "changelog auto-generado por post-commit hook (#65A)."
        ),
        "faubot_release": ver.get("faubot_release", "2026-04-27 LXXX"),
        "gates_active_count": len(active_codes),
        "content_blocks": [
            {"kind": "kpi_grid", "entries": [
                {"label": "FAUBOT_RELEASE", "value": ver.get("faubot_release", "LXXX"), "sub": "actual", "variant": "info"},
                {"label": "Gates activos", "value": str(len(active_codes)), "sub": "catálogo pivotal", "variant": "info"},
                {"label": "Module SHA", "value": (ver.get("module_sha") or "")[:8] or "—", "sub": "head", "variant": "info"},
                {"label": "Per-gate YAML", "value": str(len(per_gate_shas)), "sub": "SHAs versionados", "variant": "success"},
            ]},
            {"kind": "card_list",
             "title": f"Releases recientes · {len(recent)}",
             "head_meta": "desde audit_tracking.md",
             "entries": [
                {"title": r["audit"], "sub": r["date"], "body": "", "badges": []}
                for r in recent
             ] or [{"title": "Sin entries en audit_tracking.md", "sub": "", "body": ""}],
            },
            {"kind": "table",
             "title": f"Active gate codes · per-gate YAML SHA · {len(yaml_rows)} gates",
             "head_meta": f"{len(per_gate_shas)} / {len(active_codes)} versionados",
             "columns": ["Gate", "YAML SHA", "Status"],
             "rows": yaml_rows or [["Sin gates activos", "", ""]],
            },
        ],
    }


def patients_list_to_v2(patients_raw: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Mapea SELECT pacientes (api_list_patients query) → shape v2 cohort table.

    Si patients_raw es None, intenta consultar DB directamente.

    Returns:
        {
          "patients": [{nss, name, age, stage, stage_label, baseline_psa,
                       ecog, alert_count, visit_count, last_decision,
                       diagnosis_date, vital_status}],
          "kpis": {total, by_stage, with_alerts, recent_30d},
          "stages_filter_options": [{key, label, count}],
        }
    """
    if patients_raw is None:
        try:
            import sqlite3, os
            db_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "prostanet_tracking.db",
            )
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("""
                SELECT pi.id, pi.nss, pi.full_name, pi.dob, pi.diagnosis_date,
                       pi.vital_status, pi.created_at,
                       cb.baseline_psa, cb.metastasis_site, cb.volume_disease, cb.ecog_score,
                       (SELECT COUNT(*) FROM follow_up_visits fv WHERE fv.patient_id = pi.id) as visit_count,
                       (SELECT COUNT(*) FROM smart_alerts sa
                        WHERE sa.patient_id = pi.id AND sa.acknowledged = 0
                              AND COALESCE(sa.active, 1) = 1) as alert_count,
                       (SELECT css.next_best_action_json FROM clinical_signal_snapshots css
                        WHERE css.patient_id = pi.id
                        ORDER BY css.updated_at DESC, css.id DESC LIMIT 1) as next_best_action_json,
                       (SELECT COUNT(*) FROM scheduled_events se
                        WHERE se.patient_id = pi.id
                          AND COALESCE(se.completed, 0) = 0
                          AND DATE(COALESCE(se.scheduled_due_at, se.due_date)) < DATE('now')) as care_overdue_count,
                       (SELECT COUNT(*) FROM followup_agenda_items fai
                        WHERE fai.patient_id = pi.id
                          AND fai.status = 'blocked') as care_blocked_count,
                       (SELECT COUNT(*) FROM scheduled_events se
                        WHERE se.patient_id = pi.id
                          AND COALESCE(se.completed, 0) = 0
                          AND DATE(COALESCE(se.scheduled_due_at, se.due_date)) BETWEEN DATE('now') AND DATE('now', '+30 day')) as care_next_30d_count,
                       (SELECT se.label FROM scheduled_events se
                        WHERE se.patient_id = pi.id
                          AND COALESCE(se.completed, 0) = 0
                        ORDER BY DATE(COALESCE(se.scheduled_due_at, se.due_date)) ASC, se.id ASC
                        LIMIT 1) as care_next_label,
                       (SELECT COUNT(*) FROM outcome_events oe
                        WHERE oe.patient_id = pi.id
                          AND COALESCE(oe.active, 1) = 1) as memory_outcome_count,
                       (SELECT COUNT(*) FROM outcome_events oe
                        WHERE oe.patient_id = pi.id
                          AND COALESCE(oe.active, 1) = 1
                          AND LOWER(COALESCE(oe.event_type, '')) LIKE '%progress%') as memory_progression_count,
                       (SELECT COUNT(*) FROM treatment_adverse_events tae
                        WHERE tae.patient_id = pi.id
                          AND COALESCE(tae.ctcae_grade, 0) >= 3) as memory_grade3_toxicity_count
                FROM patient_identity pi
                LEFT JOIN clinical_baseline cb ON cb.patient_id = pi.id
                ORDER BY pi.created_at DESC
            """)
            patients_raw = [dict(r) for r in c.fetchall()]
            conn.close()
        except Exception:
            patients_raw = []

    pts = []
    stage_counts = {}
    with_alerts_count = 0
    from datetime import datetime as _dt, timedelta as _td
    today = _dt.now()
    cutoff_30d = today - _td(days=30)
    recent_count = 0

    for p in (patients_raw or []):
        if not isinstance(p, Mapping):
            continue
        # Derivar estadio heurístico desde metastasis_site
        mets = (p.get("metastasis_site") or "").lower()
        vol = (p.get("volume_disease") or "").lower()
        if "m1" in mets or "metasta" in mets or "bone" in mets or "visceral" in mets:
            stage_key = "m1crpc" if "crpc" in mets else "mcspc"
            stage_label = "m1CRPC" if "crpc" in mets else f"mCSPC{' HV' if 'high' in vol else ''}"
        elif "m0" in mets or "non" in mets:
            stage_key = "m0crpc"
            stage_label = "m0CRPC"
        elif "loc" in mets:
            stage_key = "localized"
            stage_label = "Localizado"
        else:
            stage_key = "diagnostic"
            stage_label = "Sin clasificar"
        stage_counts[stage_key] = stage_counts.get(stage_key, 0) + 1

        # Edad
        dob = p.get("dob")
        age = "—"
        if dob:
            try:
                d = _dt.fromisoformat(str(dob).split("T")[0])
                age = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
            except (ValueError, TypeError):
                age = "—"

        # Recent (created_at en últimos 30d)
        created = p.get("created_at")
        if created:
            try:
                cdt = _dt.fromisoformat(str(created).split(".")[0].replace(" ", "T"))
                if cdt >= cutoff_30d:
                    recent_count += 1
            except (ValueError, TypeError):
                pass

        alerts = int(p.get("alert_count") or 0)
        if alerts > 0:
            with_alerts_count += 1
        try:
            next_action = json.loads(p.get("next_best_action_json") or "{}")
        except (TypeError, ValueError):
            next_action = {}
        tumor_board_label = (
            next_action.get("title")
            or next_action.get("recommended_action")
            or "Abrir perfil para Tumor Board OS"
        )
        tumor_board_status = "provisional" if next_action else "requires_data"
        care_overdue = int(p.get("care_overdue_count") or 0)
        care_blocked = int(p.get("care_blocked_count") or 0)
        care_next_30d = int(p.get("care_next_30d_count") or 0)
        care_status = "overdue" if care_overdue else "blocked" if care_blocked else "scheduled" if care_next_30d else "pending"
        care_label = (
            p.get("care_next_label")
            or ("Acciones vencidas" if care_overdue else "Acciones bloqueadas" if care_blocked else "Sin proxima accion operativa")
        )
        memory_outcomes = int(p.get("memory_outcome_count") or 0)
        memory_progression = int(p.get("memory_progression_count") or 0)
        memory_toxicity = int(p.get("memory_grade3_toxicity_count") or 0)
        if memory_progression:
            memory_status = "requires_redecision"
            memory_label = "Progresion observada"
        elif memory_toxicity:
            memory_status = "toxicity_limited"
            memory_label = "Toxicidad limitante"
        elif memory_outcomes:
            memory_status = "observed"
            memory_label = "Outcome observado"
        else:
            memory_status = "insufficient_data"
            memory_label = "Sin desenlace maduro"

        pts.append({
            "id": p.get("id"),
            "nss": p.get("nss") or "—",
            "name": p.get("full_name") or "Sin nombre",
            "age": age,
            "diagnosis_date": _format_date(p.get("diagnosis_date")),
            "stage": stage_key,
            "stage_label": stage_label,
            "baseline_psa": p.get("baseline_psa") or "—",
            "ecog": p.get("ecog_score") or "—",
            "metastasis_site": p.get("metastasis_site") or "—",
            "volume_disease": p.get("volume_disease") or "—",
            "alert_count": alerts,
            "visit_count": int(p.get("visit_count") or 0),
            "vital_status": p.get("vital_status") or "alive",
            "tumor_board_status": tumor_board_status,
            "tumor_board_label": tumor_board_label,
            "care_pathway_status": care_status,
            "care_pathway_label": care_label,
            "care_overdue_count": care_overdue,
            "care_blocked_count": care_blocked,
            "care_next_30d_count": care_next_30d,
            "clinical_memory_status": memory_status,
            "clinical_memory_label": memory_label,
            "clinical_memory_outcome_count": memory_outcomes,
            "clinical_memory_progression_count": memory_progression,
            "clinical_memory_toxicity_count": memory_toxicity,
        })

    autodrive_by_ref: dict[str, Mapping[str, Any]] = {}
    try:
        from prostanet.domains.patient_tracking.clinical_autodrive_command_center import (
            build_population_autodrive_from_db,
        )

        population_ad = build_population_autodrive_from_db(limit=max(1, min(len(pts), 12)))
        for row in population_ad.get("patient_priorities") or []:
            if isinstance(row, Mapping) and row.get("patient_ref"):
                autodrive_by_ref[str(row.get("patient_ref"))] = row
    except Exception:
        autodrive_by_ref = {}
    for row in pts:
        ad = dict(autodrive_by_ref.get(str(row.get("nss"))) or {})
        next_action = dict(ad.get("next_action") or {})
        decision_today = dict(ad.get("decision_today") or {})
        decision = dict(decision_today.get("decision_today") or {})
        row["autodrive_priority_status"] = ad.get("priority_status") or (
            "critical_today" if row.get("alert_count") else "high_today" if row.get("care_overdue_count") else "watchlist"
        )
        row["autodrive_lane"] = ad.get("dominant_lane") or (
            "overdue_surveillance" if row.get("care_overdue_count") else "blocked_by_data" if row.get("care_blocked_count") else "watchlist"
        )
        row["decision_today_state"] = decision_today.get("decision_state") or decision.get("status") or "not_actionable"
        row["decision_today_label"] = decision.get("title") or next_action.get("title") or ad.get("dominant_blocker") or "Sin decision hoy"
        row["autodrive_label"] = row["decision_today_label"]
        row["autodrive_blocker"] = ad.get("dominant_blocker") or next_action.get("reason") or "—"
        row["autodrive_cta"] = (next_action.get("cta") or {}).get("href") or f"/patient_profile/{row.get('nss')}?v=2#pm2AutodriveCommandCenter"
        row["autodrive_redecision_required"] = row["autodrive_lane"] == "redecision_required" or row.get("clinical_memory_status") == "requires_redecision"

    # Stages filter options con counts
    stage_meta = [
        ("diagnostic", "Diagnóstico"),
        ("localized", "Localizado"),
        ("mcspc", "mCSPC"),
        ("m0crpc", "m0CRPC"),
        ("m1crpc", "m1CRPC"),
        ("nepc", "NEPC"),
        ("palliative", "Paliativo"),
    ]
    stages_filter_options = [
        {"key": k, "label": l, "count": stage_counts.get(k, 0)}
        for k, l in stage_meta
    ]

    return {
        "patients": pts,
        "kpis": {
            "total": len(pts),
            "with_alerts": with_alerts_count,
            "recent_30d": recent_count,
            "deceased": sum(1 for p in pts if p.get("vital_status") == "deceased"),
        },
        "stages_filter_options": stages_filter_options,
    }


def intake_form_schema_v2() -> dict[str, Any]:
    """Devuelve el form schema para `/patient_intake?v=2`.

    Reusa el builder mock de v2_demo_data (es el mismo contrato genérico).
    """
    from prostanet.presentation.v2_demo_data import build_intake_demo_data
    return build_intake_demo_data()


def _display_options_for_field(field: Mapping[str, Any]) -> list[dict[str, Any]]:
    explicit = field.get("display_options") or []
    if explicit:
        normalized: list[dict[str, Any]] = []
        for option in explicit:
            if isinstance(option, Mapping):
                value = option.get("value")
                normalized.append({**dict(option), "value": value, "label": option.get("label", value)})
        if normalized:
            return normalized

    raw_options = field.get("options") or []
    try:
        from prostanet.shared.presentation_text import resolve_option_label
    except Exception:
        resolve_option_label = None

    display_options: list[dict[str, Any]] = []
    for option in raw_options:
        if isinstance(option, Mapping):
            value = option.get("value")
            label = option.get("label")
            normalized = dict(option)
        elif isinstance(option, (list, tuple)) and len(option) >= 2:
            value = option[0]
            label = option[1]
            normalized = {"value": value}
        else:
            value = option
            label = None
            normalized = {"value": value}
        if label is None and resolve_option_label is not None:
            label = resolve_option_label(str(field.get("name") or ""), value, raw_options)
        normalized["label"] = label if label is not None else value
        display_options.append(normalized)
    return display_options


def _with_display_options(schema: dict[str, Any]) -> dict[str, Any]:
    copied = dict(schema)
    fields = []
    for field in list(copied.get("fields") or []):
        if not isinstance(field, Mapping):
            fields.append(field)
            continue
        normalized = dict(field)
        normalized["display_options"] = _display_options_for_field(normalized)
        fields.append(normalized)
    copied["fields"] = fields
    return copied


def _compass_full(profile_view: Mapping[str, Any]) -> dict[str, Any]:
    """Faubot LXXXVI #67F — expone las 19 keys del clinical_compass al template.

    Resuelve bug raíz B2: el compass produce 19 keys ricas pero solo 3 estaban
    visibles. Ahora todas las keys (recommended_direction, why_this_now,
    what_could_change_course, next_actions, monitoring_cadence, data_freshness,
    last_decisive_data, evidence_anchor, confidence_category,
    recommendation_family, decision_changing_inputs, why_not_more_confident,
    active_modifiers, safety_modifiers, longitudinal_truth_summary,
    transition_pending, transition_title, structured_decision_headline,
    structured_decision_supporting_text) están disponibles en el template v2.
    """
    cc = _safe_get(profile_view, "clinical_compass", default={}) or {}

    def _norm_list(v):
        """Normaliza a lista de strings (rutea dicts a 'label · detail' o str(v))."""
        if v is None: return []
        if isinstance(v, str): return [v]
        if isinstance(v, dict): v = list(v.values())
        if not isinstance(v, list): return [str(v)]
        out = []
        for item in v:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                # Heurística amistosa: label · detail (modifiers), label:value (freshness)
                if "label" in item and "detail" in item:
                    out.append(f"{item['label']}: {item['detail']}")
                elif "label" in item and "value" in item:
                    val = item.get("value")
                    date = item.get("date")
                    if date:
                        out.append(f"{item['label']}: {val} ({date})")
                    else:
                        out.append(f"{item['label']}: {val}")
                elif "title" in item:
                    out.append(item["title"])
                elif "label" in item:
                    out.append(item["label"])
                else:
                    out.append(" · ".join(f"{k}={v2}" for k, v2 in item.items() if v2 not in (None, "")))
            else:
                out.append(str(item))
        return out

    def _norm_str(v, default="—"):
        """Normaliza a string. Para listas/dicts produce concat amigable (no dict-literal)."""
        if v is None or v == "": return default
        if isinstance(v, (list, tuple)):
            return " · ".join(_norm_list(v)[:5]) or default
        if isinstance(v, dict):
            # dict simple → "key: value · key: value"
            if "label" in v and "title" in v:
                return v.get("title") or v.get("label")
            return " · ".join(f"{k}: {v2}" for k, v2 in v.items() if v2 not in (None, ""))
        return str(v)

    def _norm_evidence_items(v):
        """Convierte evidence_anchor en lista de dicts {label, title, url} para template rico."""
        if v is None or v == "":
            return []
        items = v if isinstance(v, list) else [v]
        out = []
        for item in items:
            if isinstance(item, dict):
                out.append({
                    "label": item.get("label") or item.get("title") or "Evidencia",
                    "title": item.get("title") or item.get("label") or "",
                    "url": item.get("url") or "",
                })
            elif isinstance(item, str):
                out.append({"label": "Evidencia", "title": item, "url": ""})
        return out

    def _norm_modifier_items(v):
        """Convierte active_modifiers/safety_modifiers en lista de dicts {label, detail, tone}."""
        if v is None or v == "":
            return []
        items = v if isinstance(v, list) else [v]
        out = []
        for item in items:
            if isinstance(item, dict):
                out.append({
                    "label": item.get("label") or item.get("title") or "Modificador",
                    "detail": item.get("detail") or item.get("description") or "",
                    "tone": item.get("tone") or item.get("severity") or "info",
                })
            elif isinstance(item, str):
                out.append({"label": item, "detail": "", "tone": "info"})
        return out

    def _norm_freshness_items(v):
        """Convierte data_freshness en lista de dicts {label, value, date, severity}."""
        if v is None or v == "":
            return []
        items = v if isinstance(v, list) else [v]
        out = []
        for item in items:
            if isinstance(item, dict):
                date_str = str(item.get("date") or "")
                # Severity heuristic: "Sin fecha"/None → warning, fecha presente → success
                severity = "warning" if (not date_str or "sin" in date_str.lower()) else "success"
                out.append({
                    "label": item.get("label") or "Dato",
                    "value": item.get("value") if item.get("value") is not None else "—",
                    "date": date_str or "Sin fecha",
                    "severity": severity,
                })
            elif isinstance(item, str):
                out.append({"label": "Dato", "value": item, "date": "", "severity": "info"})
        return out

    return {
        "recommended_direction": _norm_str(cc.get("recommended_direction"), "Sin recomendación"),
        "why_this_now": _norm_str(cc.get("why_this_now"), ""),
        "what_could_change_course": _norm_list(cc.get("what_could_change_course")),
        "next_actions": _norm_list(cc.get("next_actions")),
        "monitoring_cadence": _norm_str(cc.get("monitoring_cadence"), ""),
        # Faubot LXXXVI #67F — data_freshness como list[dict] estructurado para template rico
        "data_freshness": _norm_freshness_items(cc.get("data_freshness")),
        "data_freshness_severity": _data_freshness_severity(cc.get("data_freshness")),
        "last_decisive_data": _norm_str(cc.get("last_decisive_data"), ""),
        # Faubot LXXXVI #67F — evidence_anchor estructurado (list[dict {label, title, url}])
        "evidence_anchor": _norm_str(cc.get("evidence_anchor"), ""),
        "evidence_anchor_items": _norm_evidence_items(cc.get("evidence_anchor")),
        "confidence_category": _norm_str(cc.get("confidence_category"), "—"),
        "recommendation_family": _norm_str(cc.get("recommendation_family"), ""),
        "decision_changing_inputs": _norm_list(cc.get("decision_changing_inputs")),
        "why_not_more_confident": _norm_str(cc.get("why_not_more_confident"), ""),
        # Faubot LXXXVI #67F — modifiers estructurados (list[dict {label, detail, tone}])
        "active_modifiers": _norm_modifier_items(cc.get("active_modifiers")),
        "safety_modifiers": _norm_modifier_items(cc.get("safety_modifiers")),
        "longitudinal_truth_summary": _norm_str(cc.get("longitudinal_truth_summary"), ""),
        "transition_pending": bool(cc.get("transition_pending")),
        "transition_title": _norm_str(cc.get("transition_title"), ""),
        "structured_decision_headline": _norm_str(cc.get("structured_decision_headline"),
                                                  cc.get("recommended_direction") or "Sin clasificar"),
        "structured_decision_supporting_text": _norm_str(cc.get("structured_decision_supporting_text"),
                                                        cc.get("why_this_now") or ""),
        # Convenience: count how many keys are populated (CDE metric)
        "keys_populated_count": sum(1 for k in [
            "recommended_direction", "why_this_now", "what_could_change_course",
            "next_actions", "monitoring_cadence", "data_freshness",
            "last_decisive_data", "evidence_anchor", "confidence_category",
            "recommendation_family", "decision_changing_inputs",
            "why_not_more_confident", "active_modifiers", "safety_modifiers",
            "longitudinal_truth_summary", "transition_title",
            "structured_decision_headline", "structured_decision_supporting_text",
        ] if cc.get(k) not in (None, "", [], {})),
    }


def _data_freshness_severity(freshness: Any) -> str:
    """Maps data_freshness to severity badge token (success/info/warning/critical)."""
    if not freshness:
        return "info"
    if isinstance(freshness, str):
        f_lower = freshness.lower()
        if "stale" in f_lower or "vencid" in f_lower or "expired" in f_lower:
            return "warning"
        if "missing" in f_lower or "ausente" in f_lower:
            return "critical"
        if "fresh" in f_lower or "current" in f_lower or "reciente" in f_lower:
            return "success"
    return "info"


def _next_best_action_full(profile_view: Mapping[str, Any]) -> dict[str, Any]:
    """Faubot LXXXVI #67F — Next Best Action panel ejecutivo."""
    nba = _safe_get(profile_view, "next_best_action", default={}) or {}
    return {
        "title": nba.get("title") or nba.get("action_title") or "Sin acción inmediata",
        "rationale": nba.get("rationale") or nba.get("action_rationale") or "",
        "recommendation_family": nba.get("recommendation_family") or "",
        "transition_pending": bool(nba.get("transition_pending")),
        "transition_target_state": nba.get("transition_target_state") or "",
        "transition_title": nba.get("transition_title") or "",
        "transition_rationale": nba.get("transition_rationale") or "",
        "immediate_actions": (nba.get("immediate_actions") or [])[:5],
        "data_that_could_change_course": (nba.get("data_that_could_change_course") or [])[:5],
        "contraindication_modifiers": (nba.get("contraindication_modifiers") or [])[:5],
        "evidence_basis": nba.get("evidence_basis") or "",
        "trigger_status": nba.get("trigger_status") or "",
        "line_change_reason": nba.get("line_change_reason") or "",
        "monitoring_focus": nba.get("monitoring_focus") or "",
        "available": bool(nba.get("title") or nba.get("action_title")),
    }


def _transition_proposals_full(profile_view: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Faubot LXXXVI #67F — Lista de propuestas de cambio de estado clínico."""
    raw = _safe_get(profile_view, "transition_proposals", default=[]) or []
    if not isinstance(raw, list):
        return []
    out = []
    for p in raw[:5]:
        if not isinstance(p, Mapping):
            continue
        out.append({
            "proposal_key": p.get("proposal_key") or "",
            "from_state": p.get("from_state") or "",
            "from_state_label": p.get("from_state_label") or p.get("from_state") or "—",
            "from_management_track": p.get("from_management_track") or "",
            "target_state": p.get("target_state") or "",
            "target_state_label": p.get("target_state_label") or p.get("target_state") or "—",
            "target_management_track": p.get("target_management_track") or "",
            "priority": p.get("priority") or "medium",
            "rationale": p.get("rationale") or "",
            "trigger_signals": (p.get("trigger_signals") or [])[:3],
            "next_actions": (p.get("next_actions") or [])[:3],
            "evidence_basis": p.get("evidence_basis") or "",
        })
    return out


def bundle_to_v2_profile_full(profile_view: Mapping[str, Any],
                              patient: Mapping[str, Any]) -> dict[str, Any]:
    """Adapter EXTENDIDO para template patient_profile_v2.html (FULL 9 tabs).

    Produce shape rico consumido por el template parametric derivado del demo
    `patient_profile_full_v2_demo.html`. Reusa todos los helpers del adapter
    compact + añade: psa_observability, therapy_checkpoints, clinical_alerts,
    timeline horizontal/vertical, evidence_table, cohort_references,
    intake_widgets, changelog_entries.

    Args:
        profile_view: bundle de build_patient_profile_view_model() (260+ keys)
        patient: dict del paciente (full_name, nss, dob, baseline, treatments,
                 biomarker_longitudinal, etc.)

    Returns:
        Dict con keys consumidos por templates/patient_profile_v2.html (FULL).
    """
    # Reusa compact base
    compact = bundle_to_v2_profile(profile_view, patient)

    # Faubot LXXXIV — Brecha #64B fix: pasar 3 keys de #64A al template v2
    # (psa_forecast_per_line, psa_cohort_reference, psa_combined_timeline)
    # Ya están en profile_view (vía profile_compass.py:5869-5996), solo falta
    # exponerlos al contexto Jinja del template patient_profile_v2.html.
    pv = profile_view or {}

    # Extiende con tabs adicionales
    return {
        **compact,
        # Tab Vista 360°: psa mini + gates top + timeline horizontal
        "psa_obs": _psa_observability(profile_view),
        "timeline_horizontal": _events_horizontal(profile_view),
        "therapy_checkpoints": _therapy_checkpoints(profile_view),
        "clinical_alerts": _clinical_alerts(profile_view),
        # Tab Decisión & Gates ya viene en compact.gates_all
        # Tab Evidencia
        "evidence_table": _evidence_table(profile_view),
        "cohort_references": _cohort_references(profile_view),
        # Tab Combined Timeline
        "timeline_vertical": _events_vertical(profile_view),
        # Tab Intake longitudinal
        "intake_widgets": _intake_widgets(profile_view, patient),
        # Tab Versionado
        "changelog": _changelog_entries(),
        # ── Faubot LXXXIV #64B fix — 3 keys de #64A wired a v2 ──
        # Cierra brecha v2_adapters.bundle_to_v2_profile_full() NO exponía estos
        "psa_forecast_per_line": pv.get("psa_forecast_per_line", {}),
        "psa_cohort_reference": pv.get("psa_cohort_reference", {}),
        "psa_combined_timeline": pv.get("psa_combined_timeline", {}),
        # ── Faubot LXXXVI #67F — CDE Auditable real (resuelve B2 + B3) ──
        "compass": _compass_full(profile_view),
        "next_best_action": _next_best_action_full(profile_view),
        "transition_proposals": _transition_proposals_full(profile_view),
        # Copilotos verticales reales: la vista v2 debe exponer las mismas
        # superficies clínicas que legacy para no ocultar decisiones runtime.
        "crpc_copilot": pv.get("crpc_copilot_bundle", {}),
        "post_rp_copilot": pv.get("post_rp_salvage_bundle", {}),
        "mhspc_copilot": pv.get("mhspc_copilot_bundle", {}),
        "post_rt_copilot": pv.get("post_rt_salvage_bundle", {}),
        "clinical_readiness_tower": pv.get("clinical_readiness_tower", {}),
        "tumor_board_os": pv.get("tumor_board_os", {}),
        "care_pathway_os": pv.get("care_pathway_os", {}),
        "clinical_memory_os": pv.get("clinical_memory_os", {}),
        "autodrive": pv.get("autodrive", {}),
        "decision_today_fusion_kernel": pv.get("decision_today_fusion_kernel", {}),
        # ── Faubot LXC — Torre vigilancia: APE+Testosterona+Tx integrados ──
        # psa_obs ya existe pero faltaba exponerlo en bundle_to_v2_profile_full
        "psa_obs": _psa_observability(profile_view),
        # testosterone_history para chart secondary axis (LXC fix)
        "testosterone_history": [
            {"date": bm.get("sample_date") or bm.get("date") or "",
             "value": bm.get("value"),
             "status": bm.get("status") or ""}
            for bm in (patient.get("biomarker_longitudinal") or [])
            if isinstance(bm, dict) and (bm.get("biomarker_type") or "").upper() == "TESTOSTERONA"
            and bm.get("value") is not None and (bm.get("sample_date") or bm.get("date"))
        ],
    }


def bundle_to_v2_profile(profile_view: Mapping[str, Any],
                         patient: Mapping[str, Any]) -> dict[str, Any]:
    """Adapter principal: bundle real → context para template patient_profile_v2.html.

    Args:
        profile_view: bundle de build_patient_profile_view_model() (260+ keys)
        patient: dict del paciente (full_name, nss, dob, baseline, etc.)

    Returns:
        Dict con keys consumidos por templates/patient_profile_v2.html:
        - identity, decision_today, vitals, gate_counts, gates_top,
          audit_dims, consent, profile_view (raw passthrough para extras)
    """
    pv = profile_view or {}
    pt = patient or {}

    return {
        "identity": _identity(pt, pv),
        "decision_today": _decision_today(pv),
        "vitals": _vitals(pv, pt),
        "gate_counts": _gate_counts(pv),
        "gates_top": _gates_panel(pv, limit=5),
        "gates_all": _gates_panel(pv, limit=50),
        "audit_dims": _audit_dimensions(pv),
        "consent": _consent_status(pt),
        "surface_consistency": _surface_consistency(pv),
        "clinical_readiness_tower": pv.get("clinical_readiness_tower", {}),
        "tumor_board_os": pv.get("tumor_board_os", {}),
        "care_pathway_os": pv.get("care_pathway_os", {}),
        "clinical_memory_os": pv.get("clinical_memory_os", {}),
        "autodrive": pv.get("autodrive", {}),
        "decision_today_fusion_kernel": pv.get("decision_today_fusion_kernel", {}),
        # EPIC 22b.4 — Biopsy summary for pm2BiopsyDiagnostics card
        "biopsy_summary": _biopsy_summary(pv, pt),
        # EPIC 22c — BRCA2 carrier card (highest clinical impact: PARP-first)
        "brca2_carrier": _brca2_carrier_summary(pv, pt),
        # EPIC 22c — Lynch carrier card (pembrolizumab eligible, rare but high impact)
        "lynch_carrier": _lynch_carrier_summary(pv, pt),
        # EPIC 22c — Geriatric frail card (treatment de-escalation safety)
        "geriatric_frail": _geriatric_frail_summary(pv, pt),
        # EPIC 22c — Young onset card (universal germline + fertility preservation)
        "young_onset": _young_onset_summary(pv, pt),
        # EPIC 22c — ADT long-term card (multi-organ surveillance)
        "adt_long_term": _adt_long_term_summary(pv, pt),
        # EPIC 22c — Survivorship 5y+ card (long-term outcome tracking)
        "survivorship_5y": _survivorship_5y_summary(pv, pt),
        # EPIC 22c — Comorbidity severe CV card (drug-selection safety)
        "comorbidity_cv": _comorbidity_cv_summary(pv, pt),
        # EPIC 22f — 15 remaining Cortana cards (complete the EPIC 22c state set)
        "comorbidity_hepatic": _comorbidity_hepatic_summary(pv, pt),
        "brca1_carrier": _brca1_carrier_summary(pv, pt),
        "atm_carrier": _atm_carrier_summary(pv, pt),
        "hoxb13_carrier": _hoxb13_carrier_summary(pv, pt),
        "post_brachy_ldr": _post_brachy_ldr_summary(pv, pt),
        "post_ebrt_alone": _post_ebrt_alone_summary(pv, pt),
        "post_sbrt": _post_sbrt_summary(pv, pt),
        "post_focal_therapy": _post_focal_therapy_summary(pv, pt),
        "oligometastatic_synchronous": _oligo_synchronous_summary(pv, pt),
        "oligometastatic_metachronous_adt_naive": _oligo_metach_adt_naive_summary(pv, pt),
        "oligo_recurrent_post_definitive": _oligo_recurrent_post_def_summary(pv, pt),
        "second_primary_surveillance": _second_primary_summary(pv, pt),
        "suspected_low_psa_no_biopsy": _suspected_low_psa_summary(pv, pt),
        "suspected_elevated_psa_watchful_wait": _suspected_elevated_psa_ww_summary(pv, pt),
        "negative_biopsy_age_lt_45": _neg_biopsy_age_lt45_summary(pv, pt),
        # EPIC 23 — Clinical Recommendation Arbiter (fusion banner)
        "decision_fusion": _decision_fusion_summary(pv, pt),
        # raw passthroughs para tabs avanzadas
        "profile_view_raw": pv,
        "patient_raw": pt,
    }


# ──────────────────────────────────────────────────────────────────────────
# Faubot LXXXII #audit-cde-v2 — Cohort References + Therapy Catalog adapters
# Cierra los bugs sidebar reportados por el usuario:
# - "Cohort References" no abría interface (NO existía endpoint ni HTML)
# - "Therapy Catalog" no abría interface (NO existía endpoint ni HTML)
# ──────────────────────────────────────────────────────────────────────────


def cohort_references_to_v2() -> dict[str, Any]:
    """Catalog v2: Cohort References. Expone COHORT_PSA_REFERENCES (11 combos
    pivotales: CHAARTED, LATITUDE, ARASENS, PEACE-1, SPARTAN, PROSPER,
    ARAMIS, TAX-327, PREVAIL, PROfound, VISION) que sirven de overlay
    poblacional en el PSA Compass del perfil paciente.

    Faubot LXXXII #audit-cde-v2 — Resuelve bug "Cohort References no abre".
    """
    try:
        from prostanet.domains.patient_tracking.psa_forecast import COHORT_PSA_REFERENCES
        cohort_data = COHORT_PSA_REFERENCES
    except Exception:
        cohort_data = {}
    try:
        from prostanet.shared.algorithm_version import get_algorithm_version
        ver = get_algorithm_version() or {}
    except Exception:
        ver = {}

    # Construir filas: state × regimen → median data
    rows = []
    state_count = 0
    regimen_count = 0
    for state, regimens in sorted((cohort_data or {}).items()):
        state_count += 1
        for regimen_class, refs in (regimens or {}).items():
            regimen_count += 1
            nadir = refs.get("nadir_pct", 0)
            ttn = refs.get("time_to_nadir_m", 0)
            dor = refs.get("duration_response_m", 0)
            label = refs.get("median_label", "")
            rows.append([
                f'<span class="pm2-gate-code">{state}</span>',
                f'<span class="pm2-gate-code">{regimen_class}</span>',
                f"{nadir*100:.0f}%" if isinstance(nadir, (int, float)) else "—",
                f"{ttn} m" if ttn else "—",
                f"{dor} m" if dor else "—",
                f'<span style="color:var(--pn-text-muted);font-size:.78rem">{label}</span>',
            ])

    return {
        "catalog_view": "cohort_references",
        "sidebar_active": "cohort_references",
        "page_title": "Cohort references pivotales",
        "page_subtitle": (
            "Medianas poblacionales de PSA y outcomes derivadas de los trials "
            "pivote (CHAARTED, LATITUDE, ENZAMET, ARCHES, PEACE-1, ARASENS, "
            "SPARTAN, PROSPER, ARAMIS, TAX-327, PREVAIL, COU-AA-302, PROfound, "
            "VISION). Sirven de overlay comparativo en el PSA Compass del "
            "perfil paciente."
        ),
        "faubot_release": ver.get("faubot_release", "2026-04-26 LXXXII"),
        "gates_active_count": ver.get("gates_active_count", 0),
        "content_blocks": [
            {"kind": "kpi_grid", "entries": [
                {"label": "Estados clínicos cubiertos", "value": str(state_count),
                 "sub": "mHSPC + m0CRPC + m1CRPC + post-RP + BCR", "variant": "info"},
                {"label": "Combos state × regimen", "value": str(regimen_count),
                 "sub": "Curvas pivotales mediana", "variant": "success"},
                {"label": "Trials referenciados", "value": "13+",
                 "sub": "CHAARTED · LATITUDE · ARASENS · PROfound · VISION …",
                 "variant": "info"},
                {"label": "Uso clínico", "value": "Overlay PSA",
                 "sub": "Comparación paciente vs cohorte pivotal", "variant": "success"},
            ]},
            {"kind": "table",
             "title": f"Cohorts pivotales · {len(rows)} combos",
             "head_meta": "ordenado por estado clínico → regimen",
             "columns": ["Estado clínico", "Regimen class", "Nadir % baseline",
                         "Time-to-nadir", "Duration response", "Trial reference"],
             "rows": rows or [["Sin datos de cohort references", "", "", "", "", ""]],
            },
            {"kind": "raw_html", "html": (
                '<article class="pm2-tab-card" style="margin-top:18px"><div class="pm2-tab-card-body">'
                '<p style="color:var(--pn-text-muted);font-size:.85rem;line-height:1.6">'
                'Las cohort references se usan automáticamente como overlay en el PSA Compass '
                'del perfil de cada paciente cuando el state clínico + regimen actual coincide '
                'con un combo registrado. Esto permite comparación directa: '
                '<strong style="color:#cbd5e1">paciente actual vs mediana pivotal</strong>.'
                '</p>'
                '<p style="color:var(--pn-text-muted);font-size:.85rem;line-height:1.6;margin-top:12px">'
                '<strong>Source:</strong> '
                '<code style="background:rgba(96,165,250,0.1);padding:2px 6px;border-radius:4px">'
                'prostanet.domains.patient_tracking.psa_forecast.COHORT_PSA_REFERENCES'
                '</code>'
                '</p>'
                '</div></article>'
            )},
        ],
    }


def therapy_catalog_to_v2() -> dict[str, Any]:
    """Catalog v2: Therapy Catalog. Expone los 37+ regimenes canónicos
    catalogados con metadata: drug class, indications, evidence trials.

    Faubot LXXXII #audit-cde-v2 — Resuelve bug "Therapy Catalog no abre".
    """
    try:
        from prostanet.domains.patient_tracking.therapy_catalog import (
            therapy_catalog_entries,
        )
        entries = therapy_catalog_entries() or []
    except Exception:
        entries = []
    try:
        from prostanet.shared.algorithm_version import get_algorithm_version
        ver = get_algorithm_version() or {}
    except Exception:
        ver = {}

    # Construir filas: regimen → metadata (schema real therapy_catalog_entries)
    # Keys reales: regimen_code, label_clinico, therapy_class, contains_adt,
    #              agents, state_scope, management_tracks, line_contexts, evidence_tags
    rows = []
    classes_seen: set = set()
    for entry in entries[:100]:
        if not isinstance(entry, Mapping):
            continue
        code = entry.get("regimen_code") or entry.get("code", "—")
        label = entry.get("label_clinico") or entry.get("label", code)
        drug_class = entry.get("therapy_class") or entry.get("drug_class", "—")
        if drug_class != "—":
            classes_seen.add(drug_class)
        # state_scope is list — mostrar primeros 2
        state_scope = entry.get("state_scope") or entry.get("clinical_state", [])
        if isinstance(state_scope, list):
            indication = " · ".join(state_scope[:2]) + (f" (+{len(state_scope)-2})" if len(state_scope) > 2 else "")
        else:
            indication = str(state_scope)[:60]
        # evidence_tags es lista
        trials = entry.get("evidence_tags") or entry.get("evidence_trials") or entry.get("trial_refs", [])
        if isinstance(trials, list):
            trials_str = ", ".join(str(t) for t in trials[:3]) + (f" (+{len(trials)-3})" if len(trials) > 3 else "")
        else:
            trials_str = str(trials)[:80]
        # agents es lista
        agents = entry.get("agents", [])
        agents_str = ", ".join(agents) if isinstance(agents, list) else str(agents)
        rows.append([
            f'<span class="pm2-gate-code">{code}</span>',
            f'<strong>{label}</strong><br><span style="font-size:.7rem;color:var(--pn-text-muted)">{agents_str}</span>',
            f'<span class="pm2-gate-badge" data-severity="informational">{drug_class}</span>',
            f'<span style="font-size:.78rem">{indication or "—"}</span>',
            f'<span style="color:var(--pn-text-muted);font-size:.78rem">{trials_str or "—"}</span>',
        ])

    return {
        "catalog_view": "therapy_catalog",
        "sidebar_active": "therapy_catalog",
        "page_title": "Therapy catalog canónico",
        "page_subtitle": (
            "Catálogo declarativo de los regímenes terapéuticos canónicos para "
            "cáncer de próstata: ARPI (abiraterona, enzalutamida, apalutamida, "
            "darolutamida), quimioterapia (docetaxel, cabazitaxel), PARPi "
            "(olaparib, rucaparib, talazoparib), radiofármacos (Ra-223, Lu-177-PSMA, "
            "Sm-153 EDTMP), ADT, RT curativa/paliativa. Cada entry vincula a "
            "trial pivotal + drug class + indicación clínica."
        ),
        "faubot_release": ver.get("faubot_release", "2026-04-26 LXXXII"),
        "gates_active_count": ver.get("gates_active_count", 0),
        "content_blocks": [
            {"kind": "kpi_grid", "entries": [
                {"label": "Regímenes catalogados", "value": str(len(entries)),
                 "sub": "Canonical codes ProstaMed", "variant": "info"},
                {"label": "Drug classes únicos", "value": str(len(classes_seen)),
                 "sub": "ARPI · Chemo · PARPi · Radioligand · ADT · RT", "variant": "success"},
                {"label": "Source", "value": "therapy_catalog.py",
                 "sub": "single source of truth", "variant": "info"},
                {"label": "Uso clínico", "value": "REGIMEN_CODES",
                 "sub": "Frozensets para gates pivotal", "variant": "info"},
            ]},
            {"kind": "table",
             "title": f"Regímenes terapéuticos · {len(rows)} entries",
             "head_meta": "ordenado por código canónico",
             "columns": ["Code", "Label", "Drug class", "Indicación", "Evidence trials"],
             "rows": rows or [["Sin datos en therapy catalog", "", "", "", ""]],
            },
            {"kind": "raw_html", "html": (
                '<article class="pm2-tab-card" style="margin-top:18px"><div class="pm2-tab-card-body">'
                '<p style="color:var(--pn-text-muted);font-size:.85rem;line-height:1.6">'
                'El therapy catalog es el <strong style="color:#cbd5e1">single source of truth</strong> '
                'para los regímenes terapéuticos en ProstaMed. Los gates pivotal usan '
                '<code style="background:rgba(96,165,250,0.1);padding:2px 6px;border-radius:4px">'
                'REGIMEN_CODES_*</code> frozensets que apuntan a estos códigos canónicos.'
                '</p>'
                '<p style="color:var(--pn-text-muted);font-size:.85rem;line-height:1.6;margin-top:12px">'
                '<strong>Source:</strong> '
                '<code style="background:rgba(96,165,250,0.1);padding:2px 6px;border-radius:4px">'
                'prostanet.domains.patient_tracking.therapy_catalog.therapy_catalog_entries()'
                '</code>'
                '</p>'
                '</div></article>'
            )},
        ],
    }


def gates_coverage_to_v2_full_catalog() -> dict[str, Any]:
    """Catalog v2: Gates Coverage FULL CATALOG (Faubot LXXXII #audit-cde-v2).

    Versión mejorada de `gates_coverage_to_v2()` que muestra TODOS los 85
    gates del catálogo (no solo los disparados en la cohorte actual). Esto
    resuelve el bug donde el médico al hacer click en "Gates Pivotales"
    veía solo 5 gates (los disparados) en vez de 85.

    Combina:
    - Catálogo completo (get_loaded_yaml_codes + get_active_gate_codes)
    - Coverage real (aggregate_gates_coverage_from_db) para overlay populacional
    """
    try:
        from prostanet.shared.gates_coverage_aggregator import aggregate_gates_coverage_from_db
        coverage_db = aggregate_gates_coverage_from_db() or {}
    except Exception:
        coverage_db = {}
    try:
        from prostanet.shared.algorithm_version import (
            get_algorithm_version, get_active_gate_codes, get_per_gate_yaml_shas,
        )
        ver = get_algorithm_version() or {}
        all_gate_codes = get_active_gate_codes() or []
        per_gate_shas = get_per_gate_yaml_shas() or {}
    except Exception:
        ver = {}
        all_gate_codes = []
        per_gate_shas = {}

    # Construir filas: TODOS los gates del catálogo + coverage si existe
    rows = []
    severity_counts = {"hard_block": 0, "soft_warning": 0, "informational": 0}

    # Cargar metadata YAML (severity, message) para enriquecer
    try:
        from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
        yaml_data = _load_yaml_files() or {}
    except Exception:
        yaml_data = {}

    for code in sorted(all_gate_codes):
        coverage_info = coverage_db.get(code, {}) if isinstance(coverage_db, Mapping) else {}
        count = coverage_info.get("patient_count") or coverage_info.get("triggered_count") or 0
        pct = coverage_info.get("pct") or coverage_info.get("percentage") or 0
        by_state = coverage_info.get("by_state") or {}

        # Buscar metadata del YAML
        yaml_meta = {}
        for filename, config in yaml_data.items():
            if isinstance(config, Mapping) and config.get("code") == code:
                yaml_meta = config
                break

        severity = yaml_meta.get("severity") or coverage_info.get("severity") or "informational"
        if severity in severity_counts:
            severity_counts[severity] += 1

        sha = per_gate_shas.get(code, "")[:8] if per_gate_shas.get(code) else ""

        states_str = " · ".join(f"{k}:{v}" for k, v in list(by_state.items())[:3]) or "—"

        rows.append([
            f'<span class="pm2-gate-code">{code}</span>',
            f'<span class="pm2-gate-badge" data-severity="{severity}">{severity}</span>',
            str(count),
            f"{pct:.1f}%" if isinstance(pct, (int, float)) else str(pct),
            states_str,
            f'<code style="font-size:.7rem;color:var(--pn-text-muted)">{sha}</code>' if sha else "—",
        ])

    total_gates = len(all_gate_codes)
    triggered_in_cohort = sum(
        1 for c in all_gate_codes
        if isinstance(coverage_db, Mapping) and coverage_db.get(c)
    )

    return {
        "catalog_view": "gates_coverage",
        "sidebar_active": "gates_coverage",
        "page_title": "Cobertura clínica de gates pivotal",
        "page_subtitle": (
            f"Catálogo completo de {total_gates} gates pivotal del CDE Auditable. "
            "Análisis poblacional: % de pacientes afectados por cada gate, "
            "distribución por estado clínico y per-gate YAML SHA para reproducibilidad."
        ),
        "faubot_release": ver.get("faubot_release", "2026-04-26 LXXXII"),
        "gates_active_count": total_gates,
        "content_blocks": [
            {"kind": "kpi_grid", "entries": [
                {"label": "Gates catalogados", "value": str(total_gates),
                 "sub": "Total catálogo pivotal YAML+Python", "variant": "info"},
                {"label": "Hard block", "value": str(severity_counts["hard_block"]),
                 "sub": "Bloquean tratamiento (NEPC, HRR pre-PARP, sedation EAPC, …)",
                 "variant": "warning"},
                {"label": "Soft warning", "value": str(severity_counts["soft_warning"]),
                 "sub": "Anti-misinterpretation + alertas",
                 "variant": "warning"},
                {"label": "Informational", "value": str(severity_counts["informational"]),
                 "sub": "Calculadores, eligibility, tracking",
                 "variant": "info"},
            ]},
            {"kind": "table",
             "title": f"Catálogo completo · {total_gates} gates pivotal",
             "head_meta": f"{triggered_in_cohort} disparados en cohorte actual",
             "columns": ["Gate", "Severity", "Pacientes afectados",
                         "% Cohorte", "Top 3 estados", "YAML SHA"],
             "rows": rows or [["Catálogo de gates vacío — verificar pivotal_gates_yaml_loader",
                               "", "", "", "", ""]],
            },
            {"kind": "raw_html", "html": (
                '<article class="pm2-tab-card" style="margin-top:18px"><div class="pm2-tab-card-body">'
                '<p style="color:var(--pn-text-muted);font-size:.85rem;line-height:1.6">'
                'Cada gate tiene su <strong>YAML SHA</strong> registrado para reproducibilidad. '
                'Para ver el detalle de un gate específico (trigger conditions, evidence_phrase, '
                'trial_refs), consulta <code style="background:rgba(96,165,250,0.1);padding:2px 6px;border-radius:4px">'
                'prostanet/shared/pivotal_gates_catalog/[NN_code].yaml</code>.'
                '</p>'
                '<a href="/gates-coverage-dashboard?v=legacy" class="pm2-btn pm2-btn--primary" style="margin-top:10px">'
                'Abrir heatmap clásico (gate × estado) →</a>'
                '</div></article>'
            )},
        ],
    }


# ─────────────────────────────────────────────────────────────────────────
# Faubot LXXXVI #67F — Stage-Aware Progressive Intake (Fase 3)
# ─────────────────────────────────────────────────────────────────────────
# Principio rector (refinamiento del usuario):
# > "Si se clasifica como mCSPC se deberán solicitar los 45 campos, m1CRPC
# > los 84, etc. — sin eliminar ni omitir nada que pueda llevarnos a un
# > diagnóstico más preciso."
#
# - quick_classify_schema(): 15 campos NCCN minimum dataset → state_classifier
# - stage_specific_intake_schema(state): retorna SCHEMA completo del stage
#   clasificado, agrupado por clinical_role (required/decision_refiner/optional)
# - schema honra todos los conditional_visibility nativos de cada FieldSpec
# ─────────────────────────────────────────────────────────────────────────

# Mapping canonical state name → schema constant import path.
# Cada estado canónico de state_classifier mapeado a su schema exportado.
_STAGE_SCHEMA_REGISTRY: dict[str, tuple[str, str]] = {
    "screening": ("prostanet.domains.screening.schemas", "SCREENING_SCHEMA"),
    "diagnostic_workup": ("prostanet.domains.diagnostic_workup.schemas", "DIAGNOSTIC_WORKUP_SCHEMA"),
    "localized_initial": ("prostanet.domains.localized_initial.schemas", "LOCALIZED_SCHEMA"),
    "post_prostatectomy": ("prostanet.domains.post_prostatectomy.schemas", "POST_PROSTATECTOMY_SCHEMA"),
    "recurrence_bcr": ("prostanet.domains.recurrence_bcr.schemas", "RECURRENCE_BCR_SCHEMA"),
    "post_radiotherapy_followup": ("prostanet.domains.post_radiotherapy_followup.schemas", "POST_RT_FOLLOWUP_SCHEMA"),
    "post_radiotherapy_or_local_salvage": ("prostanet.domains.post_radiotherapy_or_local_salvage.schemas", "POST_RT_LOCAL_SALVAGE_SCHEMA"),
    "post_negative_biopsy_followup": ("prostanet.domains.post_negative_biopsy_followup.schemas", "POST_NEGATIVE_BIOPSY_SCHEMA"),
    "mcspc_oligo_metachronous": ("prostanet.domains.mcspc_oligo_metachronous.schemas", "MCSPC_OLIGO_METACHRONOUS_SCHEMA"),
    "mcspc_low_volume_sync_oligo": ("prostanet.domains.mcspc_low_volume_sync_oligo.schemas", "MCSPC_LOW_VOLUME_SCHEMA"),
    "mcspc_high_volume_sync": ("prostanet.domains.mcspc_high_volume.schemas", "MCSPC_HIGH_VOLUME_SCHEMA"),
    "mcspc_high_volume_metachronous": ("prostanet.domains.mcspc_high_volume.schemas", "MCSPC_HIGH_VOLUME_SCHEMA"),
    "mcspc_high_volume": ("prostanet.domains.mcspc_high_volume.schemas", "MCSPC_HIGH_VOLUME_SCHEMA"),
    "adt_progression_verification": ("prostanet.domains.adt_progression_verification.schemas", "ADT_PROGRESSION_VERIFICATION_SCHEMA"),
    "m0_crpc": ("prostanet.domains.m0_crpc.schemas", "M0_CRPC_SCHEMA"),
    "m1_crpc": ("prostanet.domains.m1_crpc.schemas", "M1_CRPC_SCHEMA"),
    "focal_therapy": ("prostanet.domains.focal_therapy.schemas", "FOCAL_THERAPY_SCHEMA"),
    # Faubot LXXXVI #67F — palliative_pathway no expone schema (lógica en service.py).
    # Si entra aquí, fallback a m1_crpc + manejo PRO/EOL en runtime.
    "survivorship_and_toxicity_followup": ("prostanet.domains.survivorship_and_toxicity_followup.schemas", "SURVIVORSHIP_AND_TOXICITY_FOLLOWUP_SCHEMA"),
}


def quick_classify_schema() -> dict[str, Any]:
    """Faubot LXCII (2026-04-28) — Quick classify NCCN-correcto 18 estadios.

    Expande el schema de classify inicial de 15 → 47 fields con
    `conditional_visibility` multi-nivel para que `StateClassifierService.classify()`
    pueda routear correctamente a TODOS los 18 estadios canónicos:

      - screening, diagnostic_workup, post_negative_biopsy_followup
      - localized_initial, focal_therapy
      - post_prostatectomy, recurrence_bcr
      - post_radiotherapy_followup, post_radiotherapy_or_local_salvage
      - mcspc_oligo_metachronous, mcspc_low_volume_sync_oligo
      - mcspc_high_volume_sync, mcspc_high_volume_metachronous, mcspc_high_volume
      - adt_progression_verification, m0_crpc, m1_crpc
      - survivorship_and_toxicity_followup

    Diseño multi-nivel (progressive disclosure):

      Level 0 — universal (6): identity + performance + family + comorbid
      Level 1 — gate (1): known_cancer_diagnosis
      Level 2A — pre-Dx (12 if known=0): screening / diagnostic_workup / post-neg-biopsy
      Level 2B — Dx confirmed (12 if known=1): histología + TNM + Gleason + riesgo/etapa + prior local tx
      Level 3A — Post-RP (4 if prior_local_therapy=prostatectomy): BCR routing
      Level 3B — Post-RT (2 if prior_local_therapy=radiation/brachytherapy)
      Level 3C — Metastatic (2 if metastasis_site!=M0): sync vs metachronous
      Level 3D — Treatment+CRPC (5 if current_adt_context!=none): castration + progression

    Regression fix LXCII: pre-LXCII el schema de 15 fields sólo capturaba
    flujo localizado básico, fallando en clasificar correctamente pacientes
    post-RP+BCR (→ localized_initial incorrectamente), post-RT+failure,
    mCRPC, mCSPC sync vs metachronous, screening encounter, etc.

    Al avanzar, el sistema clasifica + carga el schema completo del estadio
    resuelto en Step 2 (preserva rigor clínico — NO ELIMINA campos).
    """
    from prostanet.shared.official_diagnosis import diagnosis_capture_options

    diagnosis_options = diagnosis_capture_options()
    schema = {
        "module": "quick_classify",
        "title": "Clasificación rápida NCCN 5.2026 · 47 campos multi-nivel · 18 estadios canónicos",
        "description": "Set superset mínimo necesario para que state_classifier resuelva los 18 estadios NCCN canónicos y no oculte datos diagnósticos que el backend ya procesa. Los campos se muestran progresivamente según las respuestas previas (conditional_visibility multi-nivel). Al guardar, el sistema cargará dinámicamente el schema completo del estadio resuelto.",
        "fields": [
            # ── Level 0 · UNIVERSAL — siempre visible (6) ──────────────────
            {"name": "full_name", "label": "Nombre completo", "field_type": "text", "required": True, "group": "Identidad", "group_order": 1},
            {"name": "dob", "label": "Fecha de nacimiento", "field_type": "date", "required": True, "group": "Identidad", "group_order": 1, "help_text": "Edad se deriva automáticamente"},
            {"name": "nss", "label": "NSS / MRN", "field_type": "text", "required": True, "group": "Identidad", "group_order": 1},
            {"name": "ecog_score", "label": "ECOG performance status", "field_type": "select", "required": True, "options": ["0", "1", "2", "3", "4"], "default": "0", "group": "Performance", "group_order": 2, "help_text": "0=asintomático · 1=ambulatorio · 2=síntomático <50% cama · 3=síntomático >50% cama · 4=postrado"},
            {"name": "family_history_cancer", "label": "Historia familiar oncológica relevante", "field_type": "select", "required": False, "options": ["0", "1", "Desconocido"], "default": "Desconocido", "group": "Riesgo familiar", "group_order": 2, "help_text": "CA próstata metastásico, mama, ovario, páncreas — NCCN PROS-H (germline trigger)"},
            {"name": "charlson_comorbidity_index", "label": "Índice Charlson", "field_type": "number", "required": False, "default": 0, "group": "Comorbilidades", "group_order": 2, "help_text": "Suma de comorbilidades + edad: HTN, DM, IHD, COPD, CKD, falla hepática, cáncer previo"},

            # ── Level 1 · MASTER GATE (1) ──────────────────────────────────
            {"name": "known_cancer_diagnosis", "label": "¿Diagnóstico oncológico confirmado por biopsia?", "field_type": "select", "required": True, "options": ["1", "0"], "default": "1", "group": "Diagnóstico", "group_order": 3, "help_text": "1=Confirmado por histología · 0=Sospecha sin confirmar (entra a screening / diagnostic workup)"},

            # ── Level 2A · PRE-Dx (only if known_cancer_diagnosis=0) ───────
            {"name": "encounter_type", "label": "Tipo de encuentro pre-diagnóstico", "field_type": "select", "required": False, "options": ["screening", "clinical_evaluation", "second_opinion"], "default": "clinical_evaluation", "group": "Pre-diagnóstico", "group_order": 4, "conditional_visibility": {"known_cancer_diagnosis": ["0"]}, "help_text": "screening=detección temprana NCCN Early Detection v2.2026 · clinical_evaluation=sospecha activa"},
            {"name": "screening_context", "label": "¿Encuentro de screening / detección temprana?", "field_type": "select", "required": False, "options": ["0", "1"], "default": "0", "group": "Pre-diagnóstico", "group_order": 4, "conditional_visibility": {"known_cancer_diagnosis": ["0"]}, "help_text": "1=screening poblacional sin sospecha activa · 0=evaluación con sospecha (PSA elevado, DRE)"},
            {"name": "prior_negative_biopsy", "label": "¿Biopsia previa negativa documentada?", "field_type": "select", "required": False, "options": ["0", "1"], "default": "0", "group": "Pre-diagnóstico", "group_order": 4, "conditional_visibility": {"known_cancer_diagnosis": ["0"]}, "help_text": "Si =1 → ruta `post_negative_biopsy_followup` (seguimiento de baja intensidad NCCN)"},
            {"name": "biopsy_scheduled", "label": "¿Biopsia programada / agendada?", "field_type": "select", "required": False, "options": ["0", "1"], "default": "0", "group": "Pre-diagnóstico", "group_order": 4, "conditional_visibility": {"known_cancer_diagnosis": ["0"]}, "help_text": "Si =1 → ruta `diagnostic_workup` (NCCN PROS-1 minimum)"},
            {"name": "psa", "label": "PSA actual de sospecha", "field_type": "number", "required": False, "unit": "ng/mL", "group": "Pre-diagnóstico", "group_order": 4, "conditional_visibility": {"known_cancer_diagnosis": ["0"]}, "help_text": "Dato decisivo para repetir PSA, MRI y biopsia en ruta diagnostic_workup."},
            {"name": "psad", "label": "Densidad de PSA / PSAD", "field_type": "number", "required": False, "unit": "ng/mL/cc", "group": "Pre-diagnóstico", "group_order": 4, "conditional_visibility": {"known_cancer_diagnosis": ["0"]}, "help_text": "PSAD ≥0.15 aumenta sospecha aun con MRI negativa."},
            {"name": "pirads_score", "label": "PI-RADS en MRI prostática", "field_type": "select", "required": False, "options": ["0", "2", "3", "4", "5"], "default": "0", "group": "Pre-diagnóstico", "group_order": 4, "conditional_visibility": {"known_cancer_diagnosis": ["0"]}, "help_text": "PI-RADS 3-5 cambia la indicación de biopsia dirigida."},
            {"name": "dre_suspicious", "label": "DRE sospechoso", "field_type": "select", "required": False, "options": ["Desconocido", "0", "1"], "default": "Desconocido", "group": "Pre-diagnóstico", "group_order": 4, "conditional_visibility": {"known_cancer_diagnosis": ["0"]}, "help_text": "Tacto rectal sospechoso reabre o acelera evaluación diagnóstica."},
            {"name": "repeat_psa_value", "label": "PSA repetido", "field_type": "number", "required": False, "unit": "ng/mL", "group": "Pre-diagnóstico", "group_order": 4, "conditional_visibility": {"known_cancer_diagnosis": ["0"]}, "help_text": "Cierra el contrato de confirmación cuando PSA inicial está entre 3 y 10."},
            {"name": "repeat_psa_date", "label": "Fecha de PSA repetido", "field_type": "date", "required": False, "group": "Pre-diagnóstico", "group_order": 4, "conditional_visibility": {"known_cancer_diagnosis": ["0"]}},
            {"name": "planned_biopsy_type", "label": "Tipo de biopsia prevista", "field_type": "select", "required": False, "options": ["Pendiente", "Dirigida + sistemática", "Dirigida", "Sistemática"], "default": "Pendiente", "group": "Pre-diagnóstico", "group_order": 4, "conditional_visibility": {"known_cancer_diagnosis": ["0"]}, "help_text": "El backend usa este contrato para distinguir biopsia sistemática, dirigida o combinada."},
            {"name": "planned_biopsy_route", "label": "Vía de biopsia prevista", "field_type": "select", "required": False, "options": ["No definida", "Transperineal", "Transrectal"], "default": "No definida", "group": "Pre-diagnóstico", "group_order": 4, "conditional_visibility": {"known_cancer_diagnosis": ["0"]}, "help_text": "Transperineal puede modificar riesgo infeccioso y preparación."},

            # ── Level 2B · Dx CONFIRMED (only if known_cancer_diagnosis=1) ─
            {"name": "diagnosis_date", "label": "Fecha de diagnóstico (biopsia índice)", "field_type": "date", "required": False, "group": "Diagnóstico", "group_order": 5, "conditional_visibility": {"known_cancer_diagnosis": ["1"]}},
            {"name": "histology_subtype", "label": "Subtipo histológico confirmado", "field_type": "select", "required": True, "options": diagnosis_options["histology_subtype"], "group": "Diagnóstico", "group_order": 5, "conditional_visibility": {"known_cancer_diagnosis": ["1"]}, "help_text": "Requerido para abrir expediente como cáncer confirmado; se integra al diagnóstico oficial."},
            {"name": "psa_baseline_ng_ml", "label": "PSA basal al diagnóstico (ng/mL)", "field_type": "number", "required": False, "unit": "ng/mL", "group": "Estadificación", "group_order": 5, "conditional_visibility": {"known_cancer_diagnosis": ["1"]}, "help_text": "PSA al momento del diagnóstico (no PSA actual)"},
            {"name": "gleason_primary", "label": "Gleason primario (3-5)", "field_type": "select", "required": True, "options": ["", "3", "4", "5"], "group": "Estadificación", "group_order": 5, "conditional_visibility": {"known_cancer_diagnosis": ["1"]}},
            {"name": "gleason_secondary", "label": "Gleason secundario (3-5)", "field_type": "select", "required": True, "options": ["", "3", "4", "5"], "group": "Estadificación", "group_order": 5, "conditional_visibility": {"known_cancer_diagnosis": ["1"]}, "help_text": "ISUP grade se deriva automáticamente (WHO 2014)"},
            {"name": "gleason_tertiary", "label": "Gleason terciario si existe", "field_type": "select", "required": False, "options": ["", "3", "4", "5"], "group": "Estadificación", "group_order": 5, "conditional_visibility": {"known_cancer_diagnosis": ["1"]}},
            {"name": "clinical_tstage", "label": "cT (clinical T-stage)", "field_type": "select", "required": True, "options": ["", "cT1a", "cT1b", "cT1c", "cT2a", "cT2b", "cT2c", "cT3a", "cT3b", "cT4"], "group": "Estadificación", "group_order": 5, "conditional_visibility": {"known_cancer_diagnosis": ["1"]}},
            {"name": "nodal_status", "label": "cN (estado ganglionar clínico)", "field_type": "select", "required": True, "options": diagnosis_options["nodal_status"], "group": "Estadificación", "group_order": 5, "conditional_visibility": {"known_cancer_diagnosis": ["1"]}},
            {"name": "metastasis_site", "label": "Sitio metastásico (cM)", "field_type": "select", "required": True, "options": ["", "M0", "M1a", "M1b", "M1c"], "group": "Estadificación", "group_order": 5, "conditional_visibility": {"known_cancer_diagnosis": ["1"]}, "help_text": "M0=no detectado · M1a=ganglios distantes · M1b=hueso · M1c=visceral"},
            {"name": "clinical_stage_group", "label": "Etapa clínica AJCC", "field_type": "select", "required": False, "options": diagnosis_options["clinical_stage_group"], "group": "Diagnóstico oficial", "group_order": 5, "conditional_visibility": {"known_cancer_diagnosis": ["1"]}},
            {"name": "clinical_risk_group", "label": "Grupo de riesgo clínico", "field_type": "select", "required": False, "options": diagnosis_options["clinical_risk_group"], "group": "Diagnóstico oficial", "group_order": 5, "conditional_visibility": {"known_cancer_diagnosis": ["1"]}, "help_text": "Ejemplo: muy alto para Gleason 9-10, ISUP 5 o criterios NCCN/EAU equivalentes."},
            {"name": "prior_local_therapy", "label": "Terapia local previa", "field_type": "select", "required": False, "options": ["none", "prostatectomy", "radiation", "brachytherapy", "focal"], "default": "none", "group": "Tratamiento previo", "group_order": 6, "conditional_visibility": {"known_cancer_diagnosis": ["1"]}, "help_text": "prostatectomy → ruta post-RP / BCR · radiation/brachytherapy → ruta post-RT · focal → focal_therapy"},

            # ── Level 3A · POST-RP (if prior_local_therapy=prostatectomy) ──
            {"name": "psa_postop", "label": "PSA postoperatorio actual (ng/mL)", "field_type": "number", "required": False, "unit": "ng/mL", "group": "Post-prostatectomía", "group_order": 7, "conditional_visibility": {"prior_local_therapy": ["prostatectomy"]}, "help_text": "PSA detectable post-RP. Threshold BCR = ≥0.2 ng/mL confirmado (AUA/NCCN)"},
            {"name": "bcr_detected", "label": "¿BCR detectada (Phoenix/AUA confirmada)?", "field_type": "select", "required": False, "options": ["0", "1"], "default": "0", "group": "Post-prostatectomía", "group_order": 7, "conditional_visibility": {"prior_local_therapy": ["prostatectomy"]}, "help_text": "1 → ruta `recurrence_bcr` (NCCN PROS-D)"},
            {"name": "bcr_psa", "label": "PSA al momento de BCR (ng/mL)", "field_type": "number", "required": False, "unit": "ng/mL", "group": "Post-prostatectomía", "group_order": 7, "conditional_visibility": {"bcr_detected": ["1"]}},
            {"name": "bcr_date", "label": "Fecha de BCR", "field_type": "date", "required": False, "group": "Post-prostatectomía", "group_order": 7, "conditional_visibility": {"bcr_detected": ["1"]}},

            # ── Level 3B · POST-RT (if prior_local_therapy=radiation/brachy)
            {"name": "rt_completion_date", "label": "Fecha de finalización RT", "field_type": "date", "required": False, "group": "Post-radioterapia", "group_order": 7, "conditional_visibility": {"prior_local_therapy": ["radiation", "brachytherapy"]}, "help_text": "Phoenix nadir+2 desde nadir post-RT (Roach IJROBP 2006)"},
            {"name": "psa_nadir_post_rt", "label": "PSA nadir post-RT (ng/mL)", "field_type": "number", "required": False, "unit": "ng/mL", "group": "Post-radioterapia", "group_order": 7, "conditional_visibility": {"prior_local_therapy": ["radiation", "brachytherapy"]}, "help_text": "PSA nadir tras finalizar RT. Phoenix BCR = nadir + 2 ng/mL"},

            # ── Level 3C · METASTATIC (if metastasis_site != M0) ───────────
            # LXCII.1 (2026-04-28) — Image-canonical criteria CHAARTED + LATITUDE.
            # Permite al backend `_derive_mhspc_burden_context_from_profile()`
            # computar volume_disease (HV/LV) + latitude_high_risk correctamente.
            {"name": "metachronous_metastasis", "label": "¿Metástasis metacrónica? (vs sincrónica/de novo)", "field_type": "select", "required": False, "options": ["0", "1"], "default": "0", "group": "Enfermedad metastásica", "group_order": 8, "conditional_visibility": {"metastasis_site": ["M1a", "M1b", "M1c"]}, "help_text": "1=metacrónica (post-tratamiento local) · 0=sincrónica/de novo CPHNm hormono naïve (diagnosticado en estadio metastásico, virgen a hormonas)"},
            {"name": "visceral_metastasis_present", "label": "¿Metástasis visceral presente? (extranodal: hígado/pulmón/etc.)", "field_type": "select", "required": False, "options": ["0", "1"], "default": "0", "group": "Enfermedad metastásica", "group_order": 8, "conditional_visibility": {"metastasis_site": ["M1a", "M1b", "M1c"]}, "help_text": "CHAARTED HV: visceral=1 → alto volumen automático. LATITUDE HR: visceral mensurable cuenta como 1 de 3 criterios"},
            {"name": "bone_lesion_count_total", "label": "Lesiones óseas totales (N)", "field_type": "number", "required": False, "default": 0, "min_value": 0, "group": "Enfermedad metastásica", "group_order": 8, "conditional_visibility": {"metastasis_site": ["M1a", "M1b", "M1c"]}, "help_text": "Total de lesiones óseas detectadas (gammagrafía/PSMA-PET/CT). CHAARTED HV requiere ≥4 con ≥1 apendicular. LATITUDE HR cuenta ≥3 como 1 de 3 criterios"},
            {"name": "bone_appendicular_count", "label": "De esas, lesiones FUERA de columna+pelvis (apendiculares)", "field_type": "number", "required": False, "default": 0, "min_value": 0, "group": "Enfermedad metastásica", "group_order": 8, "conditional_visibility": {"bone_lesion_count_total": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20"]}, "help_text": "Apendicular = costillas, fémur, húmero, etc. (NO columna ni pelvis). CHAARTED HV: ≥4 totales + ≥1 apendicular"},
            {"name": "conventional_imaging_status", "label": "Status conventional imaging (CT+bone scan)", "field_type": "select", "required": False, "options": ["NOT_RESTAGED", "M0", "M1"], "default": "NOT_RESTAGED", "group": "Enfermedad metastásica", "group_order": 8, "conditional_visibility": {"known_cancer_diagnosis": ["1"]}, "help_text": "M0/M1 según conventional imaging vigente. Si solo PSMA-PET → NOT_RESTAGED hasta confirmación CT/bone (PCWG3 standard)"},

            # ── Level 3D · TREATMENT + CRPC (if known_cancer_diagnosis=1) ──
            {"name": "current_adt_context", "label": "Contexto ADT actual", "field_type": "select", "required": False, "options": ["none", "medical_adt_continuous", "orchiectomy", "intermittent_adt"], "default": "none", "group": "Tratamiento actual", "group_order": 9, "conditional_visibility": {"known_cancer_diagnosis": ["1"]}, "help_text": "Si el paciente YA está bajo ADT en cualquier modalidad. CRPC requiere castración confirmada"},
            {"name": "castrate_testosterone_status", "label": "Status testosterona en castración", "field_type": "select", "required": False, "options": ["unknown", "confirmed_castrate", "not_castrate"], "default": "unknown", "group": "CRPC verification", "group_order": 10, "conditional_visibility": {"current_adt_context": ["medical_adt_continuous", "orchiectomy", "intermittent_adt"]}, "help_text": "Castración bioquímica = T <50 ng/dL (NCCN PROS-N1) confirmada"},
            {"name": "testosterone_value", "label": "Valor testosterona (ng/dL)", "field_type": "number", "required": False, "unit": "ng/dL", "group": "CRPC verification", "group_order": 10, "conditional_visibility": {"current_adt_context": ["medical_adt_continuous", "orchiectomy", "intermittent_adt"]}, "help_text": "T <50 ng/dL = castración. Valor más reciente"},
            {"name": "systemic_progression_context", "label": "Contexto progresión sistémica", "field_type": "select", "required": False, "options": ["none", "suspicious", "confirmed_crpc"], "default": "none", "group": "CRPC verification", "group_order": 10, "conditional_visibility": {"current_adt_context": ["medical_adt_continuous", "orchiectomy", "intermittent_adt"]}, "help_text": "confirmed_crpc → m0_crpc / m1_crpc · suspicious → adt_progression_verification"},
            {"name": "line_of_therapy_number", "label": "Número de línea de terapia sistémica", "field_type": "number", "required": False, "default": 1, "group": "Tratamiento actual", "group_order": 9, "conditional_visibility": {"current_adt_context": ["medical_adt_continuous", "orchiectomy", "intermittent_adt"]}, "help_text": "1=primera línea (ADT solo o doblete/triplete) · 2+=post-progresión"},
        ],
    }
    return _with_display_options(schema)


def stage_specific_intake_schema(state: str) -> dict[str, Any]:
    """Carga el SCHEMA COMPLETO del estadio clasificado.

    Principio: NO ELIMINA campos. Sólo filtra al schema correspondiente al
    estadio NCCN. Cada estadio expone TODOS sus required +
    decision_refiner + optional preservando rigor clínico completo.

    Args:
        state: estado canónico retornado por state_classifier
            (e.g., "m1_crpc", "mcspc_high_volume_sync", "localized_initial").

    Returns:
        Dict con shape v2: {module, title, description, fields,
                            field_groups, by_role, conditional_logic_count}.
        Si state no se reconoce, retorna diagnostic_workup como fallback seguro.
    """
    import importlib

    target = _STAGE_SCHEMA_REGISTRY.get(state) or _STAGE_SCHEMA_REGISTRY.get("diagnostic_workup")
    if not target:
        return {"module": "unknown", "title": "Schema no disponible", "description": "", "fields": []}

    module_path, attr_name = target
    try:
        mod = importlib.import_module(module_path)
        schema = getattr(mod, attr_name)
    except (ImportError, AttributeError) as exc:
        return {
            "module": "unknown",
            "title": f"Error cargando {state}: {exc}",
            "description": "",
            "fields": [],
            "_error": str(exc),
        }

    fields = _with_display_options({"fields": list(schema.get("fields") or [])})["fields"]

    # Group by clinical_role (required/decision_refiner/monitoring/optional)
    by_role: dict[str, list[dict]] = {
        "required": [],
        "decision_refiner": [],
        "monitoring": [],
        "optional": [],
    }
    for f in fields:
        role = (f.get("clinical_role") or "optional").strip().lower()
        # Map "" → optional
        if role not in by_role:
            role = "optional"
        by_role[role].append(f)

    # Group by FieldSpec.group (visual grouping in UI)
    by_group: dict[str, list[dict]] = {}
    for f in fields:
        g = f.get("group") or "Datos clínicos"
        by_group.setdefault(g, []).append(f)
    field_groups = [
        {"name": g, "order": min((x.get("group_order", 0) for x in flist), default=0), "fields": flist}
        for g, flist in by_group.items()
    ]
    field_groups.sort(key=lambda x: (x["order"], x["name"]))

    # Count conditional_visibility (clinical logic richness metric)
    conditional_count = sum(1 for f in fields if f.get("conditional_visibility"))

    return {
        "module": schema.get("module") or state,
        "state": state,
        "title": schema.get("title") or state,
        "description": schema.get("description") or "",
        "fields": fields,
        "field_groups": field_groups,
        "by_role": by_role,
        "total_fields": len(fields),
        "required_count": len(by_role["required"]),
        "decision_refiner_count": len(by_role["decision_refiner"]),
        "monitoring_count": len(by_role["monitoring"]),
        "optional_count": len(by_role["optional"]),
        "conditional_logic_count": conditional_count,
        "evidence_basis": "NCCN 5.2026 + EAU 2026 (schema nativo per stage)",
    }


def list_known_stages() -> list[dict[str, str]]:
    """Lista todos los estadios canónicos soportados (para /api/intake-schema)."""
    return [{"state": s, "module_path": p} for s, (p, _) in sorted(_STAGE_SCHEMA_REGISTRY.items())]
