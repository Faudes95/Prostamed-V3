"""algorithm_version.py — FAUBOT auditoría 2026-04-25 (X).

Helper de versionado semántico del bucle Faubot. Hace explícita la
**dimensión VERSIÓN** del Clinical Decision Engine Auditable: cada
recomendación clínica queda asociada a una versión reproducible del
algoritmo (bucle Faubot release + sha del módulo de gates + lista de
los gates activos al momento de la decisión).

Aporte a auditabilidad:
  - **VERSIÓN:** sin esto, una decisión clínica futura no puede
    reproducirse exactamente porque el catálogo de gates puede haber
    crecido. Con esto, cualquier decisión queda anclada a su versión.
  - **EVIDENCIA:** la lista de gates activos + fecha de cierre Faubot
    permite trazar qué evidencia científica estaba vigente cuando se
    emitió la recomendación.

Diseño:
  - Funciones puras sin side-effects.
  - El SHA del módulo se calcula on-demand (no se cachea para que cualquier
    cambio se refleje inmediatamente).
  - El registro Faubot release se mantiene como constante actualizable
    al cierre de cada iteración del bucle.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

# Constante actualizada al cierre de cada iteración del bucle Faubot.
# Convención: "YYYY-MM-DD ROMAN_NUMERAL" (e.g., "2026-04-25 X").
#
# EPIC 31.D (GodiBot G66 HIGH) — DISCIPLINA DE VERSIONADO: cada PR que cierre
# ≥1 G-finding clínico DEBE bumpear este stamp (21 CFR Part 11 §11.10(e) +
# IEC 62304 §5.1.6 requieren trazabilidad versionada). EPIC 25-29 cerraron
# 50 hallazgos sin bump — audit trail post-hoc indistinguible.
# Histórico: 2026-04-30 LXCIX → 2026-05-15 C (pre-EPIC30) → 2026-05-16 CI
# (post-EPIC 30: PSA Tower + GodiBot pass-5) → 2026-05-16 CII (post-EPIC 31)
# → CIII-CIX (EPIC 33 + EPIC 34.A Phases 1-5) → CX (Phase 6: PSMA-PET capture)
# → CXI (EPIC 35: classifier alignment) → CXII (EPIC 37: dashboard)
# → CXIII (EPIC 36: voice quick-capture PoC) → CXIV (EPIC 36.B-ext: mic UI
# replicado en 4 cards via shared helper) → CXV (EPIC 38: STT smoke harness)
# → CXVI (EPIC 39: visual validation harness 5/5 cards+dashboard)
# → CXVII (EPIC 40: Cortana Dictation Hub — composite extractor + apply mode
# + Trial Matcher diff before/after) → CXVIII (EPIC 42: Comprehensive intake
# 47 → 104 fields, NO eliminación + cohort hygiene is_synthetic + reasoning
# trail compass + voice intake hub + real patient consent endpoint)
# → CXIX (EPIC 43: stage-specific schema completeness — 42 inline schemas
# para los 41 estados sin schema dedicado, 782 fields totales · Smart Capture
# UX single-page con sidebar nav + auto-save + Cmd-K + voice per section +
# reasoning trail inline + WCAG AA — preservando los 104 fields del intake).
# → CXX-CXXIII (EPIC 33 + decision_today + compass + template-gates fixes)
# → CXXIV (EPIC 44.A: intake friendly labels — fix template
# intake_smart_capture.html que renderizaba f.options crudo en lugar de
# f.display_options; enrich BOOLEAN_CONTEXTUAL_OPTION_LABELS + OPTION_LABELS
# con ~30 labels clínicamente densos para campos críticos NCCN/EAU 2026.
# Anti-pattern reportado por urólogo: "BCR detectada: 0/1" sin labels.
# Post-fix: "BCR detectada: Sin BCR confirmada / BCR confirmada".
# Backend compat preservado: value="0"/"1"/"unknown" sigue intacto en submit
# → voice extractors EPIC 36 + JS auto-save no rompen. 60/60 tests + 541
# regression PASS + Playwright sweep pending).
# → CXXV-CXXVIII (EPIC 44.B/C/C.2/D: Tier 1 Clasificador + Tier 2 Asistente
# + cross-cutting filter + Smart Capture banner) — DEPRECATED y revertidos
# en CXXIX. Reportado por urólogo: "TIER 2 sigue siendo demasiado extenso"
# y "los 2 TIER no son funcionales, eliminar". El 2-tier UX no resolvía la
# pérdida de lógica clínica (Tier 2 mostraba 514 fields; tras filtro
# cross-cutting bajaba a 19 pero seguía siendo insuficiente para reflejar
# la riqueza clínica del estadio). Decisión: el clínico prefiere el flujo
# completo (Smart Capture vista experta con 104 fields + display_options
# EPIC 44.A) sin segmentación artificial.
# → CXXIX (Rollback EPIC 44.B/C/C.2/D vía git revert):
#   - DELETE templates/intake_tier1.html, templates/intake_tier2.html
#   - DELETE tests/test_epic44_tier1_classifier.py,
#            tests/test_epic44_tier2_no_overlap.py,
#            tests/test_epic44d_smart_capture_banner.py
#   - REMOVE routes /intake/tier1, /api/intake/tier1/classify,
#            /intake/tier2/<state>, /api/intake/tier2/<state>
#   - REMOVE tier1_classifier_schema(), TIER1_REQUIRED_MIN_FIELDS,
#            _TIER1_FIELD_NAMES_ORDERED, _TIER2_CROSS_CUTTING_GROUPS
#   - REMOVE stage_specific_intake_schema kwargs exclude_tier1_overlap +
#            include_cross_cutting (revertido a signature original)
#   - REMOVE Smart Capture banner "Vista experta / Tier 1 Clasificador"
# PRESERVADOS (sin pérdida clínica):
#   - EPIC 44.A: friendly display labels (BCR confirmada, PSMA-positiva,
#     visceral mets contextuales, ~30 fields enriched, 60/60 tests)
#   - 9973c05 compass-aware ranking Patient Twin OS (Enzalutamida #1 mCSPC)
# 517 passed + 1 xfailed post-rollback. Próximo: revisitar value clínico
# real sin segmentación artificial — EPIC 45 ML augmentation o feedback
# directo del urólogo sobre qué pieza clínica falta.
# → CXXX (EPIC 45: FactSpec alias contradiction audit — generaliza el fix
# manual del paciente Frin a TODA la población. NUEVO módulo
# prostanet/regulatory/clinical/factspec_alias_audit.py (~570 LOC) con:
#   - get_alias_groups(): inventa 42 alias groups desde FACT_SPECS.legacy_aliases
#     (15 blocking, e.g. metastatic_stage_resolved↔m_substage_resolved que
#     fue el bug-root del Frin)
#   - detect_contradictions_for_patient(): identifica facts del mismo alias
#     group activos simultáneamente con valores no concordantes
#   - propose_resolution(): reglas precedencia auditable (más reciente +
#     tie-break por source_type: clinician_verified > classifier_derived
#     > legacy_import) + verification_note explicativo
#   - apply_resolution(): marca losers is_active=0, supersede + audit
#     entry en clinical_view_audit
#   - audit_all_patients / resolve_all_patients: poblacionales
#   - CLI: python -m prostanet.regulatory.clinical.factspec_alias_audit
#     --dry-run / --apply / --patient-id / --json
# REST endpoints (NUEVO prostanet/presentation/data_integrity_routes.py):
#   - GET  /api/data-integrity/audit           (poblacional dry-run)
#   - GET  /api/data-integrity/<nss>           (snapshot paciente)
#   - POST /api/data-integrity/<nss>/resolve   (auto-fix, requiere confirm=auto)
#   - POST /api/data-integrity/audit/apply     (poblacional, requiere
#                                                confirm=ALL_PATIENTS)
# View model integration: _build_data_integrity_snapshot() inyecta
#   `data_integrity` al bundle de build_patient_profile_view_model.
# UI panel: section data-testid="data-integrity-panel" en patient_profile_v2
#   se renderiza solo cuando contradictions_count>0 o resolutions_count>0
#   (sin agregar ruido si todo está limpio). Botón "Aplicar auto-resolución"
#   visible solo si severity=high. Detalles por contradicción con código
#   fact_key + valor + source_type + timestamp + historial colapsable.
# Hallazgo real producción: 33/425 pacientes (7.8%) tienen el mismo bug
# que Frin con severity=high (todas en alias_group metastatic_stage_resolved).
# 22/22 tests EPIC 45 PASS + 539 regression PASS).
FAUBOT_RELEASE = "2026-05-17 CXXX"

# Path al módulo de gates pivotal (SHA se calcula sobre este archivo).
_GATES_MODULE_PATH = (
    Path(__file__).parent / "pivotal_contraindication_gates.py"
)


def get_module_sha(module_path: Path | None = None) -> str:
    """Calcula el SHA-256 del módulo de gates (primeros 12 caracteres).

    Args:
        module_path: opcional override del path. Por defecto usa
            `pivotal_contraindication_gates.py`.

    Returns:
        Primeros 12 chars del SHA-256 del archivo, en hex. Si el archivo
        no existe (e.g., en tests aislados), retorna "unavailable".
    """
    path = module_path or _GATES_MODULE_PATH
    try:
        contents = path.read_bytes()
    except (OSError, FileNotFoundError):
        return "unavailable"
    return hashlib.sha256(contents).hexdigest()[:12]


def get_active_gate_codes() -> list[str]:
    """Retorna la lista ordenada de códigos de los gates pivotal activos.

    Faubot 2026-04-25 (XVIII) — Combina Python detectores + YAML loaded
    para reflejar el sistema híbrido completo. La normalización por
    `seen` evita duplicados cuando un gate vive en ambos lados (durante
    transición de migración).
    """
    seen: set[str] = set()
    codes: list[str] = []

    # 1. Python detectores
    try:
        from prostanet.shared.pivotal_contraindication_gates import _DETECTORS
    except ImportError:
        _DETECTORS = ()  # type: ignore
    # Mapping función_name → code canónico. Mayoría siguen el patrón
    # `detect_<code>`, pero algunos fueron renombrados (e.g.,
    # `detect_no_bone_protective_agent_for_radium223` → code
    # `no_bone_protective_agent`; `detect_creatinine_clearance_lt_30_for_rucaparib`
    # → code `creatinine_clearance_lt_30`).
    _FUNC_TO_CODE_OVERRIDES = {
        "no_bone_protective_agent_for_radium223": "no_bone_protective_agent",
        "creatinine_clearance_lt_30_for_rucaparib": "creatinine_clearance_lt_30",
    }
    for detector in _DETECTORS:
        name = getattr(detector, "__name__", "")
        if not name.startswith("detect_"):
            continue
        suffix = name[len("detect_"):]
        code = _FUNC_TO_CODE_OVERRIDES.get(suffix, suffix)
        if code not in seen:
            seen.add(code)
            codes.append(code)

    # 2. YAML loaded
    try:
        from prostanet.shared.pivotal_gates_yaml_loader import (
            get_loaded_yaml_codes,
        )
        for code in get_loaded_yaml_codes():
            if code not in seen:
                seen.add(code)
                codes.append(code)
    except ImportError:
        pass

    return sorted(codes)


def get_per_gate_yaml_shas() -> dict[str, str]:
    """Faubot 2026-04-25 (XI) — Retorna {gate_code: sha} de cada gate
    YAML cargado desde `pivotal_gates_catalog/`.

    Esto da **versionado granular**: cada gate tiene su propio SHA y
    puede actualizarse independientemente. Un revisor regulatorio puede
    auditar cada YAML como un artefacto versionable separado.

    Returns:
        Dict {gate_code: sha} (vacío si no hay YAMLs cargados o si el
        loader no está disponible).
    """
    try:
        from prostanet.shared.pivotal_gates_yaml_loader import (
            get_all_yaml_gate_shas,
        )
        return get_all_yaml_gate_shas()
    except ImportError:
        return {}


def get_yaml_loaded_gate_codes() -> list[str]:
    """Faubot 2026-04-25 (XI) — Lista de gates migrados a YAML."""
    try:
        from prostanet.shared.pivotal_gates_yaml_loader import (
            get_loaded_yaml_codes,
        )
        return get_loaded_yaml_codes()
    except ImportError:
        return []


def get_algorithm_version() -> dict[str, Any]:
    """Retorna el version stamp completo del algoritmo Faubot.

    Estructura JSON-serializable:
        {
            "faubot_release": "2026-04-25 XI",
            "module_sha": "a1b2c3d4e5f6",
            "module_path": "prostanet/shared/pivotal_contraindication_gates.py",
            "gates_active_count": 18,
            "gates_active_codes": [...],
            "yaml_loaded_gates_count": 4,
            "yaml_loaded_gate_codes": [...],
            "per_gate_yaml_shas": {gate_code: sha, ...},
        }
    """
    codes = get_active_gate_codes()
    yaml_codes = get_yaml_loaded_gate_codes()
    per_gate_shas = get_per_gate_yaml_shas()
    return {
        "faubot_release": FAUBOT_RELEASE,
        "module_sha": get_module_sha(),
        "module_path": "prostanet/shared/pivotal_contraindication_gates.py",
        "gates_active_count": len(codes),
        "gates_active_codes": codes,
        # Faubot 2026-04-25 (XI) — Versionado granular YAML.
        "yaml_loaded_gates_count": len(yaml_codes),
        "yaml_loaded_gate_codes": yaml_codes,
        "per_gate_yaml_shas": per_gate_shas,
    }


def is_version_compatible(
    audit_version: dict[str, Any] | None,
    current_version: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compara una versión del audit (persistida) con la versión actual.

    Útil para auditorías retrospectivas: cuando se carga un audit antiguo,
    este helper indica si los gates han cambiado desde entonces.

    Returns:
        {
            "compatible": bool,
            "release_changed": bool,
            "sha_changed": bool,
            "gate_count_delta": int,
            "added_gates": [...],
            "removed_gates": [...],
        }
    """
    audit = dict(audit_version or {})
    current = dict(current_version or get_algorithm_version())
    audit_codes = set(audit.get("gates_active_codes") or [])
    current_codes = set(current.get("gates_active_codes") or [])
    added = sorted(current_codes - audit_codes)
    removed = sorted(audit_codes - current_codes)
    release_changed = audit.get("faubot_release") != current.get("faubot_release")
    sha_changed = audit.get("module_sha") != current.get("module_sha")
    return {
        "compatible": not (release_changed or sha_changed),
        "release_changed": release_changed,
        "sha_changed": sha_changed,
        "gate_count_delta": len(current_codes) - len(audit_codes),
        "added_gates": added,
        "removed_gates": removed,
    }
