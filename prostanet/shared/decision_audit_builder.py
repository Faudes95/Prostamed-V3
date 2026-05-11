"""decision_audit_builder.py — FAUBOT auditoría 2026-04-25 (X).

Orquestador de las **5 dimensiones de auditabilidad** del Clinical
Decision Engine. Recibe un `latest_assessment` (persistido en
`clinical_assessments`) + identidad del paciente, y construye una
estructura JSON-serializable con:

    audit_dimensions:
      como:        cadena de razonamiento (gates evaluados → regímenes
                   filtrados → preferred_regimen)
      por_que:     contraindicaciones explícitas (gates triggered + msgs)
      datos:       audit del input (snapshot, missing, stale)
      evidencia:   trazabilidad científica (trial_refs, evidence_tag,
                   guideline versions)
      version:     algorithm versioning (faubot_release + module_sha +
                   gates_active_count)

Esta es la pieza arquitectónica que **cierra Clinical Decision Engine
Auditable**. Cualquier consumidor (UI, API, auditor externo, autoridad
sanitaria) puede pedir el audit y obtener TODO el contexto reproducible
de una decisión clínica.

Aporte a auditabilidad:
  - **TODAS las 5 dimensiones simultáneamente** estructuradas y trazables.
  - Diseño JSON-first: serializable directo a HTTP response.
  - Roundtrip-safe: el audit puede persistirse y reproducir la decisión
    si el algoritmo no ha cambiado (validable con `is_version_compatible`).
"""
from __future__ import annotations

from typing import Any

from prostanet.shared.algorithm_version import get_algorithm_version


def _normalize_value(value: Any) -> Any:
    """Coerce value to JSON-serializable primitive."""
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_normalize_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _normalize_value(v) for k, v in value.items()}
    return str(value)


def _build_como_dimension(result_snapshot: dict) -> dict:
    """**CÓMO** — cadena de razonamiento del sistema.

    Compone:
      - State del paciente (m1_crpc, mhspc_high_volume, etc.)
      - Gates evaluados con sus mensajes
      - Regímenes filtrados por los gates (preferred_frontline_regimen
        + alternatives)
      - Comparative bundle (cuando aplica)
    """
    return {
        "state": result_snapshot.get("state", ""),
        "preferred_regimen_code": result_snapshot.get("preferred_regimen_code", ""),
        "preferred_regimen": _normalize_value(
            result_snapshot.get("preferred_frontline_regimen") or {}
        ),
        "alternative_regimens_count": len(
            result_snapshot.get("alternative_regimens") or []
        ),
        "applicability_badge": result_snapshot.get("applicability_badge", ""),
        "decision_quality": _normalize_value(
            result_snapshot.get("decision_quality") or {}
        ),
        "ranking_policy_version": result_snapshot.get("ranking_policy_version", ""),
    }


def _build_por_que_dimension(result_snapshot: dict) -> dict:
    """**POR QUÉ** — contraindicaciones explícitas + alternativas.

    Compone:
      - Gates pivotal triggered con su clasificación clínica
      - Mensajes en `not_recommended`
      - Contraindicaciones estructuradas
    """
    gates = list(result_snapshot.get("pivotal_contraindication_gates") or [])
    not_recommended = list(result_snapshot.get("not_recommended") or [])
    contraindications = list(result_snapshot.get("contraindications") or [])
    return {
        "active_gates_count": len(gates),
        "active_gates": _normalize_value(gates),
        "not_recommended_count": len(not_recommended),
        "not_recommended": _normalize_value(not_recommended),
        "contraindications_count": len(contraindications),
        "contraindications": _normalize_value(contraindications),
    }


def _build_datos_dimension(
    input_snapshot: dict,
    result_snapshot: dict,
) -> dict:
    """**DATOS** — audit del input clínico.

    Compone:
      - Snapshot del payload completo de entrada (CRIT-1: PHI scrubbed)
      - Missing critical inputs (qué se necesitaba y faltó)
      - Stale inputs (qué está vencido)
      - Conteo total de campos capturados

    Faubot 2026-04-25 (XXV) — CRIT-1 hardening:
    El `input_snapshot` se procesa por `scrub_phi_for_audit` que:
      - Redacta valores de campos PHI directos (nss, full_name, phone,
        email, dob, etc.)
      - Detecta y redacta valores con patrones PHI (NSS 11 dígitos,
        emails, CURPs)
      - Preserva TODOS los valores clínicos (PSA, Gleason, qtc_ms,
        gates triggered, etc.) — críticos para auditoría regulatoria.
    """
    # Lazy import para evitar circular si security_helpers no está disponible
    try:
        from prostanet.shared.security_helpers import scrub_phi_for_audit
        scrubbed_input = scrub_phi_for_audit(input_snapshot or {})
    except ImportError:
        # Fallback: si el helper no está disponible (tests aislados),
        # NO leak PHI — devolver dict vacío (fail-safe)
        scrubbed_input = {}

    missing = list(result_snapshot.get("missing_critical_inputs") or [])
    stale = list(result_snapshot.get("stale_inputs") or [])
    return {
        "input_field_count": len(input_snapshot or {}),
        "input_snapshot": _normalize_value(scrubbed_input),
        "input_phi_scrubbed": True,  # Faubot XXV — explícito para clientes
        "missing_critical_inputs": _normalize_value(missing),
        "missing_count": len(missing),
        "stale_inputs": _normalize_value(stale),
        "stale_count": len(stale),
    }


# Faubot 2026-04-25 (LXX) — Auditoría #65A
# Per-gate evidence drill-down: cuando se dispara un gate, el audit
# ahora incluye links live a referencias bibliográficas (NCCN/EAU PMC,
# PubMed, ClinicalTrials.gov) + año de la guía vigente. Esto permite a
# revisor regulatorio (FDA, COFEPRIS) seguir cada cita directamente al
# documento original sin búsqueda manual.

# Patrones de detección de tipo de referencia para construcción de URLs
_TRIAL_REF_URL_PATTERNS = [
    # PubMed PMIDs (ej. "PMID: 30157320")
    (r"^PMID:?\s*(\d+)$", "https://pubmed.ncbi.nlm.nih.gov/{0}/"),
    # ClinicalTrials.gov NCT IDs (ej. "NCT02677896")
    (r"^(NCT\d{8})$", "https://clinicaltrials.gov/study/{0}"),
    # DOI (ej. "10.1056/NEJMoa1715546")
    (r"^(10\.\d+/.+)$", "https://doi.org/{0}"),
    # Trial names sin link directo — buscar en PubMed
    (r"^(SPARTAN|PROSPER|ARAMIS|CHAARTED|LATITUDE|ENZAMET|ARCHES|PEACE-1|ARASENS|TAX-327|PREVAIL|COU-AA-302|PROfound|VISION|EMBARK|RADICALS-RT|RTOG-9601|GETUG-AFU-16|TROPIC|CARD|AFFIRM|ALSYMPCA|MAGNITUDE|TALAPRO-2|TRITON-3|PSMAfore|TheraP|PEACE-3|PROpel|IMPACT|IPATential150|CONTACT-02|AMPLITUDE|ARANOTE|TITAN|STAMPEDE|PRESTO|AFT-19)$",
     "https://pubmed.ncbi.nlm.nih.gov/?term={0}+prostate+cancer"),
]

# NCCN/EAU guideline URL templates por versión
_GUIDELINE_REFERENCE_URLS = {
    "NCCN": "https://www.nccn.org/guidelines/guidelines-detail?category=1&id=1459",
    "EAU": "https://uroweb.org/guidelines/prostate-cancer",
}


def _build_per_gate_evidence_drill_down(gate: dict) -> dict:
    """Faubot 2026-04-25 (LXX) — Auditoría #65A.

    Construye drill-down de evidencia per-gate: para cada trial_ref +
    evidence_tag del gate, intenta resolver una URL live (PubMed,
    ClinicalTrials.gov, DOI) + metadata de citation.

    Args:
        gate: dict del gate triggered con trial_refs + evidence_tag fields

    Returns:
        Dict con:
            trial_refs_with_links: [{ref, url, type}]
            evidence_tag_link: {tag, url, source}
            citation_count: int
    """
    import re

    trial_refs = list(gate.get("trial_refs") or [])
    refs_with_links: list[dict] = []
    for ref in trial_refs:
        if not ref:
            continue
        ref_str = str(ref).strip()
        url = ""
        ref_type = "unknown"
        for pattern, url_template in _TRIAL_REF_URL_PATTERNS:
            match = re.match(pattern, ref_str, re.IGNORECASE)
            if match:
                url = url_template.format(*match.groups())
                if "pubmed" in url:
                    ref_type = "pmid" if "PMID" in pattern else "trial_search"
                elif "clinicaltrials" in url:
                    ref_type = "nct"
                elif "doi.org" in url:
                    ref_type = "doi"
                break
        refs_with_links.append({
            "ref": ref_str,
            "url": url,
            "type": ref_type,
        })

    evidence_tag = gate.get("evidence_tag", "")
    evidence_tag_link = {}
    if evidence_tag:
        # Mapping evidence_tag → guideline reference URL
        eg_str = str(evidence_tag).upper()
        if "NCCN" in eg_str:
            evidence_tag_link = {
                "tag": str(evidence_tag),
                "url": _GUIDELINE_REFERENCE_URLS["NCCN"],
                "source": "NCCN Prostate Cancer Guidelines",
            }
        elif "EAU" in eg_str:
            evidence_tag_link = {
                "tag": str(evidence_tag),
                "url": _GUIDELINE_REFERENCE_URLS["EAU"],
                "source": "EAU-EANM-ESTRO-ESUR-ISUP-SIOG Prostate Cancer Guidelines",
            }
        else:
            evidence_tag_link = {
                "tag": str(evidence_tag),
                "url": "",
                "source": "literature",
            }

    return {
        "trial_refs_with_links": refs_with_links,
        "evidence_tag_link": evidence_tag_link,
        "citation_count": len(refs_with_links) + (1 if evidence_tag else 0),
    }


def _build_evidencia_dimension(
    result_snapshot: dict,
    guideline_versions: dict,
) -> dict:
    """**EVIDENCIA** — trazabilidad científica.

    Compone:
      - Guideline versions activas al momento de la decisión (NCCN, EAU)
      - Trial refs únicos citados por los gates triggered
      - Evidence tags únicos citados
      - Trial matches del módulo
      - Per-gate evidence drill-down (Faubot LXX #65A): URLs live para
        cada trial_ref + evidence_tag, permitiendo seguimiento directo
        a la fuente bibliográfica.
    """
    gates = list(result_snapshot.get("pivotal_contraindication_gates") or [])
    # Agregar trial_refs y evidence_tags únicos de todos los gates
    trial_refs_set: set[str] = set()
    evidence_tags_set: set[str] = set()
    per_gate_evidence: list[dict] = []
    for gate in gates:
        for ref in gate.get("trial_refs") or []:
            if ref:
                trial_refs_set.add(str(ref))
        et = gate.get("evidence_tag")
        if et:
            evidence_tags_set.add(str(et))
        # Faubot LXX #65A — drill-down per gate
        gate_evidence = _build_per_gate_evidence_drill_down(gate)
        per_gate_evidence.append({
            "gate_code": gate.get("code", ""),
            "gate_class_label": gate.get("class_label", ""),
            **gate_evidence,
        })
    trial_matches = list(result_snapshot.get("trial_matches") or [])
    nccn_primary = result_snapshot.get("nccn_primary") or {}
    eau_comparison = result_snapshot.get("eau_comparison") or {}
    return {
        "guideline_versions": _normalize_value(guideline_versions or {}),
        "nccn_primary_label": nccn_primary.get("label", ""),
        "nccn_primary_version": nccn_primary.get("version", ""),
        "eau_comparison_label": eau_comparison.get("label", ""),
        "eau_comparison_version": eau_comparison.get("version", ""),
        "unique_trial_refs": sorted(trial_refs_set),
        "unique_trial_refs_count": len(trial_refs_set),
        "unique_evidence_tags": sorted(evidence_tags_set),
        "unique_evidence_tags_count": len(evidence_tags_set),
        "trial_matches_count": len(trial_matches),
        "trial_matches": _normalize_value(trial_matches),
        # Faubot LXX #65A — Per-gate evidence drill-down
        "per_gate_evidence": _normalize_value(per_gate_evidence),
        "per_gate_evidence_count": len(per_gate_evidence),
    }


def _build_version_dimension() -> dict:
    """**VERSIÓN** — algorithm versioning.

    Reusa `get_algorithm_version()` que computa SHA on-demand.
    """
    return get_algorithm_version()


def _empty_audit_skeleton(
    patient_id: int | str,
    patient_identity: dict | None,
) -> dict:
    """Faubot 2026-04-25 (XXIII) — Refactor R3 (code-simplifier report):
    Construye el esqueleto base del audit con valores neutros para todas
    las claves. Usado por `build_decision_audit` para garantizar **schema
    bit-a-bit consistente** entre la rama "no assessment available" y la
    rama completa.

    La dimensión VERSIÓN está SIEMPRE disponible (no depende del
    assessment) — útil para clientes que necesitan saber qué algoritmo
    está activo aunque no haya decisión clínica reciente.

    Antes (pre-R3): el bloque `if not latest_assessment` y la rama
    completa duplicaban claves manualmente, con riesgo de drift si una
    rama añadía un campo y la otra no.
    """
    return {
        "available": False,
        "patient_id": patient_id,
        "patient_identity": _normalize_value(patient_identity or {}),
        "audit_metadata": {
            "assessment_id": None,
            "module_id": "",
            "state": "",
            "evaluated_at": "",
        },
        "audit_dimensions": {
            "como": {},
            "por_que": {},
            "datos": {},
            "evidencia": {},
            "version": _build_version_dimension(),
        },
        "summary": {
            "total_gates_active": 0,
            "total_inputs_captured": 0,
            "total_trial_refs_cited": 0,
            "decision_state": "",
            "audit_status": "no_assessment_available",
        },
    }


# Faubot 2026-04-25 (LXX) — Auditoría #65A
# Per-line analytics + cohort comparison embed: el audit ahora puede
# incluir analytics longitudinales del paciente (build_psa_forecast_per_line
# + build_psa_cohort_reference_overlay + build_combined_patient_timeline
# del #64A) cuando se pasa el patient record completo. Esto permite que
# revisor regulatorio acceda a TODO en un solo audit JSON.
def _build_per_line_analytics_section(patient: dict | None) -> dict:
    """Faubot 2026-04-25 (LXX) — Auditoría #65A.

    Embed per-line analytics + cohort comparison data del #64A en el audit.
    Lazy import + try/except defensivo para evitar romper el audit si los
    helpers no están disponibles (e.g., en tests aislados o import lock).

    Returns dict vacío si patient no provisto o si falla algún helper.
    """
    if not patient:
        return {
            "available": False,
            "per_line_forecasts": {},
            "cohort_reference": {},
            "combined_timeline_summary": {},
            "_reason": "patient_record_not_provided",
        }
    result = {
        "available": True,
        "per_line_forecasts": {},
        "cohort_reference": {},
        "combined_timeline_summary": {},
    }
    try:
        from prostanet.domains.patient_tracking.psa_forecast import (
            build_psa_forecast_per_line,
            build_psa_cohort_reference_overlay,
            build_combined_patient_timeline,
        )
        per_line = build_psa_forecast_per_line(patient)
        result["per_line_forecasts"] = _normalize_value(per_line)
        cohort = build_psa_cohort_reference_overlay(patient)
        result["cohort_reference"] = _normalize_value(cohort)
        # Solo summary del timeline (full data sería redundante con per_line)
        timeline = build_combined_patient_timeline(patient)
        result["combined_timeline_summary"] = _normalize_value(
            timeline.get("summary", {})
        )
    except Exception as e:
        # Defensive: si falla cualquier helper, no romper el audit
        result["available"] = False
        result["_reason"] = f"helper_exception: {type(e).__name__}"
    return result


def build_decision_audit(
    *,
    patient_id: int | str,
    patient_identity: dict | None = None,
    latest_assessment: dict | None = None,
    patient_record: dict | None = None,
) -> dict:
    """Construye el audit completo de una decisión clínica con las 5
    dimensiones de auditabilidad.

    Args:
        patient_id: identificador del paciente (id numérico o NSS).
        patient_identity: dict opcional con metadatos del paciente
            (nombre, fecha nacimiento, etc.) para el header del audit.
            NO incluye PHI sensible más allá de identificadores básicos.
        latest_assessment: dict del último clinical_assessment
            persistido. Si None o vacío, retorna audit con
            `available=False`.

    Returns:
        Dict JSON-serializable con la estructura:
            {
              "available": bool,
              "patient_id": <id>,
              "patient_identity": {...},
              "audit_metadata": {
                "assessment_id": int,
                "module_id": str,
                "state": str,
                "evaluated_at": str,
              },
              "audit_dimensions": {
                "como": {...},
                "por_que": {...},
                "datos": {...},
                "evidencia": {...},
                "version": {...},
              },
              "summary": {
                "total_gates_active": int,
                "total_inputs_captured": int,
                "total_trial_refs_cited": int,
                "decision_state": str,
              },
            }
    """
    # Faubot 2026-04-25 (XXIII) — Refactor R3:
    # Esqueleto compartido garantiza paridad de schema entre las dos
    # ramas (no_assessment vs complete). Solo se sobrescriben los
    # campos poblados por las dimensiones cuando hay assessment.
    audit = _empty_audit_skeleton(patient_id, patient_identity)
    if not latest_assessment:
        return audit

    input_snapshot = latest_assessment.get("input_snapshot") or {}
    result_snapshot = latest_assessment.get("result_snapshot") or {}
    guideline_versions = latest_assessment.get("guideline_versions") or {}
    como = _build_como_dimension(result_snapshot)
    por_que = _build_por_que_dimension(result_snapshot)
    datos = _build_datos_dimension(input_snapshot, result_snapshot)
    evidencia = _build_evidencia_dimension(result_snapshot, guideline_versions)
    # version dimension ya está poblada por _empty_audit_skeleton

    audit["available"] = True
    audit["audit_metadata"] = {
        "assessment_id": latest_assessment.get("id"),
        "module_id": latest_assessment.get("module_id", ""),
        "state": latest_assessment.get("state", ""),
        "evaluated_at": latest_assessment.get("created_at", ""),
    }
    audit["audit_dimensions"]["como"] = como
    audit["audit_dimensions"]["por_que"] = por_que
    audit["audit_dimensions"]["datos"] = datos
    audit["audit_dimensions"]["evidencia"] = evidencia
    # version dimension ya estaba poblada por _empty_audit_skeleton
    # Faubot 2026-04-25 (LXX) — Auditoría #65A
    # Per-line analytics + cohort comparison embed (opcional, si patient_record provisto)
    audit["per_line_analytics"] = _build_per_line_analytics_section(patient_record)
    audit["summary"] = {
        "total_gates_active": por_que.get("active_gates_count", 0),
        "total_inputs_captured": datos.get("input_field_count", 0),
        "total_trial_refs_cited": evidencia.get("unique_trial_refs_count", 0),
        "decision_state": como.get("state", ""),
        "audit_status": "complete",
        # Faubot LXX #65A — extended summary
        "per_gate_evidence_count": evidencia.get("per_gate_evidence_count", 0),
        "per_line_analytics_available": audit["per_line_analytics"].get("available", False),
    }
    return audit
