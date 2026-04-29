"""gates_ddi_cross_check.py — FAUBOT auditoría 2026-04-25 (XV) → XXXV (Tier 4 K).

Integración del rastro de gates pivotal con el motor de DDI.

**Faubot 2026-04-25 (XXXV) — Tier 4 K refactor:**
Los 3 dicts (_GATE_TO_RELATED_DDI_CATEGORIES, _GATE_TO_ONCOLOGY_DRUGS,
_GATE_SUMMARIES) ahora se cargan desde
`gates_ddi_cross_check_catalog/cross_check_mappings.yaml` via
`gates_ddi_cross_check_yaml_loader`. Los dicts module-level se mantienen
poblados al import time para preservar API pública (cualquier código que
import directly los dicts sigue funcionando).

Aporte a auditabilidad post-Tier 4 K:
  - **VERSIÓN:** SHA per-mapping permite trazar cambios en cross-check
    (forensic audit: ¿qué cross-check estaba activo cuando se emitió
    esta decisión?). Ver `gates_ddi_cross_check_yaml_loader.get_per_mapping_sha()`.
  - **CÓMO** (cadena de razonamiento): cuando un gate dispara, el motor
    cruza-verifica las medicaciones concomitantes para identificar DDIs
    que **agraven** la contraindicación. El razonamiento queda explícito
    y declarativo en YAML.
  - **DATOS** (audit input): el motor inspecciona el campo
    `current_medications` / `concomitant_medications` del payload y
    cruza con catálogos farmacológicos.

Diseño:
  - Mappings declarativos en YAML (Tier 4 K) — paridad con catálogo de gates.
  - Reusa `DDIEngine.check_interactions` (no duplica lógica DDI).
  - Sin side-effects: funciones puras que retornan listas estructuradas.
  - Backward-compatible: si un gate code no tiene mapping, se ignora.
  - Fallback: si YAML no disponible (env aislado), el módulo carga dicts
    vacíos y el cross-check degrada gracefully (no emite alerts pero no falla).
"""
from __future__ import annotations

import logging
from typing import Any

from prostanet.shared.ddi_engine import DDIEngine
from prostanet.shared.advanced_support_normalizer import parse_medication_list
from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
    build_gate_to_ddi_categories_dict,
    build_gate_to_oncology_drugs_dict,
    build_gate_summaries_dict,
    get_catalog_metadata,
    get_per_mapping_sha,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Mappings declarativos: gate code → DDI categories que ENRIQUECEN
# (categorías de DDI que agravan o contextualizan la contraindicación).
# Los nombres de categoría son los emitidos por DDIEngine en `category`.
# ──────────────────────────────────────────────────────────────────────
_GATE_TO_RELATED_DDI_CATEGORIES: dict[str, tuple[str, ...]] = {
    # Gate 17 — QTc grado 3 + enzalutamida → cualquier DDI QTc agrava
    "qtc_prolongation_grade3_for_enzalutamide": ("qtc_prolongation",),
    # Gate 18 — LVEF caída + apalutamida → DDIs cardiotóxicos QTc agravan
    # (estrés arrítmico empeora función ventricular comprometida).
    "lvef_decline_for_apalutamide": ("qtc_prolongation",),
    # Gate 19 — ARSI + deterioro cognitivo → seizure_threshold (bupropion,
    # tramadol con enzalutamida/apalutamida) y CYP2C19 induction (citalopram
    # que puede empeorar síntomas neuropsiquiátricos por subdosis).
    "arsi_in_cognitive_decline_grade2": ("seizure_threshold", "cyp2c19_induction"),
    # Gate 3 — HTA no controlada + abiraterona → espironolactona
    # (pharmacodynamic_aldosterone) compite por receptor mineralocorticoide.
    "uncontrolled_hypertension": ("pharmacodynamic_aldosterone",),
    # Gate 4 — IC NYHA III-IV → DDIs QTc + aldosterone agravan.
    "severe_heart_failure_nyha_iii_iv": (
        "qtc_prolongation",
        "pharmacodynamic_aldosterone",
    ),
    # Gate 9 — Ra-223 sin agente óseo → DDIs bone_remodeling
    # (denosumab/zoledronato) cambian el manejo.
    "no_bone_protective_agent": ("bone_remodeling",),
    # Gate 11/12 — Ra-223 emergencias → bone_remodeling cruzado.
    "radium223_in_cord_compression": ("bone_remodeling",),
    "radium223_in_hypocalcemia": ("bone_remodeling",),
    # Gates 14/15/16 — PARP × hematología → CYP3A4 inhibitors
    # (ketoconazol, claritromicina, itraconazol) elevan toxicidad PARP.
    "lutetium177_in_severe_cytopenias": ("cyp3a4_inhibition",),
    "parp_inhibitor_in_severe_cytopenias": ("cyp3a4_inhibition",),
    "parp_inhibitor_in_mds_aml_history": ("cyp3a4_inhibition",),
    # Gate 10 — Ccr <30 + rucaparib → CYP3A4 inhibitors aumentan exposición.
    "creatinine_clearance_lt_30": ("cyp3a4_inhibition",),
    # Faubot 2026-04-25 (XXVI) — Tier 2/3 D-F gates 20-23.
    # Gate 20 — ARSI + convulsiones → seizure_threshold (bupropion, tramadol
    # con enzalutamida) + cyp3a4_induction (carbamazepina, fenitoína
    # antiepilépticos que reducen niveles de ARSI).
    "arsi_in_seizure_history_grade3": (
        "seizure_threshold", "cyp3a4_induction",
    ),
    # Gate 21 — Abiraterona + hepatotox → cyp3a4_inhibition (ketoconazol,
    # itraconazol, claritromicina aumentan exposición abiraterona) +
    # cyp3a4_induction (rifampin reduce niveles, no ayuda con hepatotox).
    "abiraterone_hepatotoxicity_grade3": (
        "cyp3a4_inhibition", "cyp3a4_induction",
    ),
    # Gate 22 — Niraparib + trombocitopenia → cyp3a4_inhibition (aumenta
    # exposición niraparib, agrava mielotox) + qtc_prolongation
    # (sangrado activo + arritmia compromete cardiopulm).
    "niraparib_in_severe_thrombocytopenia": (
        "cyp3a4_inhibition",
    ),
    # Gate 23 — Niraparib + HTA grado 3 → pharmacodynamic_aldosterone
    # (espironolactona compite con manejo HTA) + qtc_prolongation
    # (HTA + DAT inhibition + DDIs QTc = riesgo cardiovascular cruzado).
    "niraparib_hypertension_grade3_magnitude": (
        "pharmacodynamic_aldosterone", "qtc_prolongation",
    ),
    # Faubot 2026-04-25 (XXVII) — Auditoría #39 gate 24.
    # Gate 24 — Docetaxel + neuropatía longitudinal → cyp3a4_inhibition
    # (ketoconazol/itraconazol elevan exposición docetaxel y empeoran
    # neuropathy acumulativa) + cyp3a4_induction (rifampin reduce
    # niveles, podría enmascarar progresión sin protección).
    "docetaxel_neuropathy_longitudinal_grade2_post_4_cycles": (
        "cyp3a4_inhibition", "cyp3a4_induction",
    ),
    # Faubot 2026-04-25 (XXXIII) — Auditoría #41 gate 25.
    # Gate 25 — Ipatasertib + hiperglucemia G3 → cyp3a4_inhibition
    # (claritromicina/itraconazol elevan exposición ipatasertib AKT
    # inhibitor → empeora hiperglucemia tratamiento-emergente) +
    # cyp3a4_induction (rifampin/dexametasona reducen niveles pero
    # tampoco son safe — dexametasona empeora glycemic control).
    "ipatasertib_hyperglycemia_grade3": (
        "cyp3a4_inhibition", "cyp3a4_induction",
    ),
    # Faubot 2026-04-25 (XXXIV) — Auditoría #42 gates 26-27.
    # Gate 26 — Cabazitaxel hipersensibilidad → cyp3a4_inhibition
    # (ketoconazol/itraconazol elevan exposición cabazitaxel + amplifican
    # reacciones de hipersensibilidad) + cyp3a4_induction (rifampin
    # reduce niveles pero NO previene reacción inmunogénica).
    "cabazitaxel_hypersensitivity_grade3": (
        "cyp3a4_inhibition", "cyp3a4_induction",
    ),
    # Gate 27 — Ra-223 + alto riesgo fractura FRAX → bone_remodeling
    # (denosumab/zoledronato son la PROTECCIÓN obligatoria, no DDIs
    # adversas; el cross-check identifica que están presentes para
    # validar override bone_protection_established).
    "radium223_high_fracture_risk_frax": (
        "bone_remodeling",
    ),
    # Faubot 2026-04-25 (XXXIV) — Auditoría #43 gate 28.
    # Gate 28 — Abiraterone + insuficiencia adrenal → pharmacodynamic_aldosterone
    # (espironolactona compite con manejo mineralocorticoide) +
    # cyp3a4_inhibition (claritromicina eleva abiraterona empeorando
    # supresión adrenal axis).
    "abiraterone_adrenal_insufficiency": (
        "pharmacodynamic_aldosterone", "cyp3a4_inhibition",
    ),
}


# ──────────────────────────────────────────────────────────────────────
# Mapping declarativo: gate code → fármacos oncológicos (lowercase, en
# nomenclatura DDIEngine) que el gate restringe. Se pasan como
# `oncology_drugs` a DDIEngine.check_interactions.
# ──────────────────────────────────────────────────────────────────────
_GATE_TO_ONCOLOGY_DRUGS: dict[str, list[str]] = {
    "qtc_prolongation_grade3_for_enzalutamide": ["enzalutamida"],
    "lvef_decline_for_apalutamide": ["apalutamida"],
    "arsi_in_cognitive_decline_grade2": [
        "enzalutamida", "apalutamida", "darolutamida",
    ],
    "uncontrolled_hypertension": ["abiraterona"],
    "severe_heart_failure_nyha_iii_iv": [
        "abiraterona", "enzalutamida", "apalutamida", "docetaxel",
    ],
    "no_bone_protective_agent": ["radium_223"],
    "radium223_in_cord_compression": ["radium_223"],
    "radium223_in_hypocalcemia": ["radium_223"],
    "lutetium177_in_severe_cytopenias": ["olaparib", "niraparib", "rucaparib"],
    "parp_inhibitor_in_severe_cytopenias": [
        "olaparib", "niraparib", "rucaparib", "talazoparib",
    ],
    "parp_inhibitor_in_mds_aml_history": [
        "olaparib", "niraparib", "rucaparib", "talazoparib",
    ],
    "creatinine_clearance_lt_30": ["rucaparib", "olaparib"],
    # Faubot 2026-04-25 (XXVI) — Tier 2/3 D-F gates 20-23.
    "arsi_in_seizure_history_grade3": [
        "enzalutamida", "apalutamida", "darolutamida",
    ],
    "abiraterone_hepatotoxicity_grade3": ["abiraterona"],
    "niraparib_in_severe_thrombocytopenia": ["niraparib"],
    "niraparib_hypertension_grade3_magnitude": ["niraparib"],
    # Faubot 2026-04-25 (XXVII) — Auditoría #39.
    "docetaxel_neuropathy_longitudinal_grade2_post_4_cycles": [
        "docetaxel", "cabazitaxel",
    ],
    # Faubot 2026-04-25 (XXXIII) — Auditoría #41.
    "ipatasertib_hyperglycemia_grade3": ["ipatasertib"],
    # Faubot 2026-04-25 (XXXIV) — Auditoría #42-#43.
    "cabazitaxel_hypersensitivity_grade3": ["cabazitaxel"],
    "radium223_high_fracture_risk_frax": ["radium_223"],
    "abiraterone_adrenal_insufficiency": ["abiraterona"],
}


# ──────────────────────────────────────────────────────────────────────
# Resúmenes cortos por gate (UI/clínico): se anteponen al mensaje
# cruzado para enmarcar el contexto.
# ──────────────────────────────────────────────────────────────────────
_GATE_SUMMARIES: dict[str, str] = {
    "qtc_prolongation_grade3_for_enzalutamide":
        "Gate 17 (QTc grado 3 + enzalutamida bloqueado)",
    "lvef_decline_for_apalutamide":
        "Gate 18 (FEVI <50% + apalutamida bloqueado)",
    "arsi_in_cognitive_decline_grade2":
        "Gate 19 (ARSI + deterioro cognitivo grado ≥2 bloqueado)",
    "uncontrolled_hypertension":
        "Gate 3 (HTA no controlada + abiraterona bloqueado)",
    "severe_heart_failure_nyha_iii_iv":
        "Gate 4 (IC NYHA III-IV bloqueado)",
    "no_bone_protective_agent":
        "Gate 9 (Ra-223 sin agente óseo bloqueado)",
    "radium223_in_cord_compression":
        "Gate 11 (Ra-223 + compresión medular bloqueado)",
    "radium223_in_hypocalcemia":
        "Gate 12 (Ra-223 + hipocalcemia bloqueado)",
    "lutetium177_in_severe_cytopenias":
        "Gate 14 (Lu-177 + citopenias severas bloqueado)",
    "parp_inhibitor_in_severe_cytopenias":
        "Gate 15 (PARPi + citopenias severas bloqueado)",
    "parp_inhibitor_in_mds_aml_history":
        "Gate 16 (PARPi + historia MDS/AML bloqueado)",
    "creatinine_clearance_lt_30":
        "Gate 10 (Ccr <30 + rucaparib bloqueado)",
    # Faubot 2026-04-25 (XXVI) — Tier 2/3 D-F gates 20-23.
    "arsi_in_seizure_history_grade3":
        "Gate 20 (ARSI + convulsiones grado ≥3 bloqueado)",
    "abiraterone_hepatotoxicity_grade3":
        "Gate 21 (Abiraterona + hepatotox grado 3 bloqueado)",
    "niraparib_in_severe_thrombocytopenia":
        "Gate 22 (Niraparib + trombocitopenia <150K bloqueado)",
    "niraparib_hypertension_grade3_magnitude":
        "Gate 23 (Niraparib + HTA grado ≥3 bloqueado)",
    # Faubot 2026-04-25 (XXVII) — Auditoría #39.
    "docetaxel_neuropathy_longitudinal_grade2_post_4_cycles":
        "Gate 24 (Docetaxel + neuropatía G≥2 post-4-ciclos bloqueado)",
    # Faubot 2026-04-25 (XXXIII) — Auditoría #41.
    "ipatasertib_hyperglycemia_grade3":
        "Gate 25 (Ipatasertib + hiperglucemia G≥3 bloqueado)",
    # Faubot 2026-04-25 (XXXIV) — Auditorías #42-#43.
    "cabazitaxel_hypersensitivity_grade3":
        "Gate 26 (Cabazitaxel + hipersensibilidad G≥3 bloqueado)",
    "radium223_high_fracture_risk_frax":
        "Gate 27 (Ra-223 + alto riesgo fractura FRAX bloqueado)",
    "abiraterone_adrenal_insufficiency":
        "Gate 28 (Abiraterona + insuficiencia adrenal bloqueado)",
}


# ════════════════════════════════════════════════════════════════════
# Faubot 2026-04-25 (XXXV) — Tier 4 K: YAML override at module import
# ════════════════════════════════════════════════════════════════════
# Los 3 dicts Python arriba son **fallback values** en caso de que el
# YAML loader falle (env aislado, archivo missing, parse error). En
# operación normal (YAML disponible), los dicts se OVERWRITEAN con los
# valores cargados desde gates_ddi_cross_check_catalog/cross_check_mappings.yaml.
#
# Esto garantiza:
#   1. YAML es source of truth (consistente con catálogo de gates)
#   2. API pública preservada (callers que import los dicts directamente
#      siguen funcionando)
#   3. Backward-compat completa (graceful degradation si YAML falla)
#   4. SHA per-mapping disponible para audit forense (vía loader)
def _override_with_yaml_catalog():
    """Override module-level dicts con valores del YAML catalog.

    Llamado al import time. Si YAML loader falla, mantiene dicts Python
    originales como fallback (logged warning).
    """
    global _GATE_TO_RELATED_DDI_CATEGORIES
    global _GATE_TO_ONCOLOGY_DRUGS
    global _GATE_SUMMARIES

    try:
        yaml_categories = build_gate_to_ddi_categories_dict()
        yaml_drugs = build_gate_to_oncology_drugs_dict()
        yaml_summaries = build_gate_summaries_dict()

        if yaml_categories:
            _GATE_TO_RELATED_DDI_CATEGORIES = yaml_categories
        if yaml_drugs:
            _GATE_TO_ONCOLOGY_DRUGS = yaml_drugs
        if yaml_summaries:
            _GATE_SUMMARIES = yaml_summaries

        loaded_count = max(len(yaml_categories), len(yaml_drugs), len(yaml_summaries))
        if loaded_count > 0:
            logger.info(
                f"gates_ddi_cross_check: loaded {loaded_count} mappings from YAML "
                f"(catalog SHA via loader.get_catalog_sha())"
            )
        else:
            logger.warning(
                "gates_ddi_cross_check: YAML catalog loaded but empty; "
                "using Python fallback dicts"
            )
    except Exception as exc:
        logger.warning(
            f"gates_ddi_cross_check: YAML load failed ({type(exc).__name__}: {exc}); "
            "using Python fallback dicts"
        )


# Execute override at module import
_override_with_yaml_catalog()


# Faubot 2026-04-25 — Fix R8 (code-simplifier report):
# Importar el helper canónico desde `pivotal_contraindication_gates` para
# garantizar paridad ES-médica con los detectores Python. Antes este módulo
# tenía un set local `_TRUTHY` con 7 tokens (le faltaban "positivo",
# "documented", "documentado") que causaba inconsistencia silenciosa:
# `seizure_history="documentado"` activaba detectores Python pero NO el
# cross-check DDI. El alias `_is_truthy` se mantiene como public API
# para no romper callers existentes.
from prostanet.shared.pivotal_contraindication_gates import (
    _truthy_token as _is_truthy,
)


def _extract_concomitant_medications(payload: dict) -> list[str]:
    """Extrae lista de medicaciones del payload, robusta a formatos.

    Acepta `current_medications` o `concomitant_medications` (lista o str).
    """
    raw = (
        payload.get("current_medications")
        or payload.get("concomitant_medications")
        or payload.get("medications")
    )
    if not raw:
        return []
    return parse_medication_list(raw)


def _build_cross_message(gate: dict, alert: Any) -> str:
    """Construye un mensaje clínico que cruza el gate con la DDI.

    El mensaje es trazable: cita gate code, fármaco oncológico, fármaco
    concomitante, impacto, acción y referencia.
    """
    code = str(gate.get("code") or "")
    summary = _GATE_SUMMARIES.get(code, code)
    return (
        f"{summary} + concomitante {alert.drug_b}: "
        f"{alert.clinical_impact}. {alert.recommended_action} "
        f"(DDI {alert.severity}; ref: {alert.reference})."
    )


def cross_check_gates_with_ddi(
    gates_triggered: list[dict] | None,
    payload: dict,
) -> list[dict]:
    """Cruza cada gate disparado con DDIs concomitantes relevantes.

    Por cada gate triggered:
      1. Identifica la(s) categoría(s) de DDI relevante(s) según el mapping.
      2. Extrae los fármacos oncológicos que el gate restringe.
      3. Llama a `DDIEngine.check_interactions` con esos fármacos vs las
         medicaciones concomitantes del payload.
      4. Filtra las alertas DDI por las categorías relevantes para el gate.
      5. Construye un mensaje clínico cruzado que enriquece el rastro.

    Args:
        gates_triggered: lista de gates disparados (output de
            `evaluate_pivotal_contraindication_gates`).
        payload: payload del paciente (debe contener
            `current_medications` o `concomitant_medications`).

    Returns:
        Lista de cross-alerts. Cada elemento tiene:
            - `gate_code`: código del gate origen.
            - `severity`: severity heredada de la DDI alert.
            - `category`: categoría DDI cruzada.
            - `cross_message`: mensaje clínico para `not_recommended`.
            - `ddi_alert`: dict completo de la DDIAlert (drug_a, drug_b,
              mechanism, clinical_impact, etc.).
    """
    if not gates_triggered:
        return []
    meds = _extract_concomitant_medications(payload)
    if not meds:
        return []

    cross_alerts: list[dict] = []
    seen_keys: set[tuple[str, str, str]] = set()

    # Heurística: si el paciente tiene historia de convulsiones, lo
    # propagamos a DDIEngine.check_interactions para activar reglas
    # específicas (enzalutamida + tramadol triple, etc.).
    seizure_history = _is_truthy(
        payload.get("seizure_history")
        or payload.get("prior_seizure_history")
        or payload.get("antecedente_convulsiones")
    )

    for gate in gates_triggered:
        code = str(gate.get("code") or "")
        if code not in _GATE_TO_RELATED_DDI_CATEGORIES:
            continue
        relevant_categories = set(_GATE_TO_RELATED_DDI_CATEGORIES[code])
        if not relevant_categories:
            continue
        oncology_drugs = list(_GATE_TO_ONCOLOGY_DRUGS.get(code, []))
        if not oncology_drugs:
            continue

        # Para gate 19 (cognitive decline), forzamos seizure_history=True
        # porque el deterioro cognitivo es factor de riesgo convulsivo
        # documentado y queremos que dispare las reglas seizure cascade.
        gate_seizure = seizure_history or (code == "arsi_in_cognitive_decline_grade2")

        ddi_alerts = DDIEngine.check_interactions(
            oncology_drugs=oncology_drugs,
            concomitant_medications=meds,
            seizure_history=gate_seizure,
        )

        # Filtrar por categorías relevantes para este gate.
        for alert in ddi_alerts:
            cat = str(alert.category or "").strip().lower()
            if cat not in relevant_categories:
                continue
            key = (code, alert.drug_a, alert.drug_b)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            cross_alerts.append({
                "gate_code": code,
                "severity": alert.severity,
                "category": alert.category,
                "cross_message": _build_cross_message(gate, alert),
                "ddi_alert": alert.to_dict(),
            })

    return cross_alerts


def cross_messages_for_not_recommended(
    cross_alerts: list[dict] | None,
) -> list[str]:
    """Extrae mensajes únicos de cross-alerts para concatenar al
    `not_recommended` del bundle.

    Útil para que `apply_pivotal_contraindication_gates` los devuelva
    sin que el caller necesite procesar la estructura completa.
    """
    if not cross_alerts:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for alert in cross_alerts:
        msg = str(alert.get("cross_message") or "")
        if msg and msg not in seen:
            out.append(msg)
            seen.add(msg)
    return out


def get_gate_ddi_mapping_summary() -> dict[str, Any]:
    """Faubot 2026-04-25 (XV → XXXV) — Helper de auditoría: retorna el catálogo
    de mappings activos {gate_code: {categories, oncology_drugs, summary, sha}}.

    Faubot 2026-04-25 (XXXV) — Tier 4 K: ahora incluye SHA per-mapping
    desde YAML loader para audit forense ("¿qué cross-check estaba activo
    cuando se emitió esta decisión?").

    Útil para endpoint `/api/decision-audit/algorithm-version` que reporte
    qué gates tienen cross-check DDI activo y cuáles no (gap analysis).
    """
    summary: dict[str, dict[str, Any]] = {}
    for code, cats in _GATE_TO_RELATED_DDI_CATEGORIES.items():
        summary[code] = {
            "categories": sorted(cats),
            "oncology_drugs": sorted(_GATE_TO_ONCOLOGY_DRUGS.get(code, [])),
            "summary": _GATE_SUMMARIES.get(code, code),
            "yaml_sha": get_per_mapping_sha(code),  # Tier 4 K: per-mapping SHA
        }
    catalog_meta = get_catalog_metadata()
    return {
        "total_gates_with_ddi_crosscheck": len(summary),
        "mappings": summary,
        # Tier 4 K — catalog-level metadata
        "catalog_metadata": catalog_meta,
    }
