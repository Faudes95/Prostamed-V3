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
# → CIII-CIX (EPIC 33 + EPIC 34.A Phases 1-5) → CX (Phase 6: PSMA-PET capture).
FAUBOT_RELEASE = "2026-05-17 CX"

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
