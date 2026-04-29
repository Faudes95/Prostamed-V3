"""gates_ddi_cross_check_yaml_loader.py — FAUBOT 2026-04-25 (XXXV).

Tier 4 K — Loader YAML para `gates_ddi_cross_check_catalog/cross_check_mappings.yaml`.

Migra los 3 dicts Python imperativos de `gates_ddi_cross_check.py` a un
YAML declarativo único, consistente con el patrón establecido por
`pivotal_gates_yaml_loader.py` (catálogo de gates 100% YAML-native).

Aporte a auditabilidad post-Tier 4 K:
  - **VERSIÓN:** SHA per-mapping permite trazar cambios mapping-by-mapping
    (auditor regulatorio puede revisar qué versión del cross-check
    estaba activa cuando se emitió cada decisión clínica)
  - **CÓMO:** declarativo facilita grep/inspección + audit trail vs código
  - **DATOS:** schema validation automática + faubot_added_in tracking

Diseño:
  - Single consolidated YAML (vs per-gate file): fácil revisión holística
    del mapping table; audit unitario por gate sigue posible (función
    `get_mapping_for_gate`).
  - Cache module-level con SHA per-mapping: similar a JWKS cache pattern
    de jwt_verifier.
  - API pública:
      load_cross_check_catalog() → dict
      get_mapping_for_gate(code) → dict | None
      get_all_gate_codes() → list[str]
      get_catalog_sha() → str (SHA del archivo completo)
      get_per_mapping_sha(code) → str (SHA del mapping individual)
      reset_catalog_cache() → None (test-only)

Backward-compat:
  - `gates_ddi_cross_check.py` lee de YAML al import time, fallback a
    Python dicts si YAML inaccesible (permite tests aislados).
  - API pública del módulo Python NO cambia (cross_check_gates_with_ddi,
    cross_messages_for_not_recommended, get_gate_ddi_mapping_summary).
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_CATALOG_DIR = (
    Path(__file__).parent / "gates_ddi_cross_check_catalog"
)
_CATALOG_FILE = _CATALOG_DIR / "cross_check_mappings.yaml"


# ════════════════════════════════════════════════════════════════════
# Module-level cache
# ════════════════════════════════════════════════════════════════════


_CATALOG_CACHE: dict | None = None
_CATALOG_SHA_CACHE: str | None = None
_PER_MAPPING_SHA_CACHE: dict[str, str] = {}


# ════════════════════════════════════════════════════════════════════
# Loading
# ════════════════════════════════════════════════════════════════════


def _yaml_safe_load(text: str) -> dict:
    """Carga YAML usando yaml.safe_load (PyYAML). Fallback a json si yaml
    no disponible (raro pero posible en envs aislados)."""
    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError:
        # Fallback: try JSON parse (YAML is superset of JSON)
        return json.loads(text)


def load_cross_check_catalog(force_reload: bool = False) -> dict:
    """Carga (o reusa cache) el catalog YAML completo.

    Returns:
        dict con keys: faubot_release, schema_version, total_mappings,
        ddi_categories_supported, mappings (dict por gate code).

    Si el archivo YAML no existe o falla, retorna dict vacío con mappings={}
    (graceful degradation — código Python puede caer a fallback dicts).
    """
    global _CATALOG_CACHE, _CATALOG_SHA_CACHE
    if not force_reload and _CATALOG_CACHE is not None:
        return _CATALOG_CACHE

    if not _CATALOG_FILE.exists():
        logger.warning(
            f"DDI cross-check YAML catalog not found at {_CATALOG_FILE}; "
            "using empty catalog (Python module will use fallback dicts)"
        )
        _CATALOG_CACHE = {"mappings": {}}
        _CATALOG_SHA_CACHE = ""
        return _CATALOG_CACHE

    try:
        raw_text = _CATALOG_FILE.read_text(encoding="utf-8")
        catalog = _yaml_safe_load(raw_text)
        if not isinstance(catalog, dict):
            raise ValueError(
                f"YAML catalog root must be dict, got {type(catalog).__name__}"
            )
        if "mappings" not in catalog:
            raise ValueError("YAML catalog missing 'mappings' key")
        _CATALOG_CACHE = catalog
        _CATALOG_SHA_CACHE = hashlib.sha256(
            raw_text.encode("utf-8"),
        ).hexdigest()[:12]
        logger.info(
            f"DDI cross-check catalog loaded | "
            f"mappings={len(catalog.get('mappings') or {})} | "
            f"sha={_CATALOG_SHA_CACHE} | "
            f"release={catalog.get('faubot_release', 'unknown')}"
        )
        return _CATALOG_CACHE
    except Exception as exc:
        logger.error(
            f"Failed to load DDI cross-check catalog: "
            f"{type(exc).__name__}: {exc}"
        )
        _CATALOG_CACHE = {"mappings": {}}
        _CATALOG_SHA_CACHE = ""
        return _CATALOG_CACHE


def get_all_gate_codes() -> list[str]:
    """Retorna lista de todos los gate codes con mapping declarado."""
    catalog = load_cross_check_catalog()
    return list((catalog.get("mappings") or {}).keys())


def get_mapping_for_gate(gate_code: str) -> dict | None:
    """Retorna mapping completo para un gate code, None si no existe.

    El mapping incluye: ddi_categories, oncology_drugs, ui_summary,
    description, faubot_added_in.
    """
    if not gate_code:
        return None
    catalog = load_cross_check_catalog()
    return (catalog.get("mappings") or {}).get(gate_code)


def get_catalog_sha() -> str:
    """Retorna SHA-256 (12 chars) del archivo catalog completo."""
    if _CATALOG_SHA_CACHE is None:
        load_cross_check_catalog()
    return _CATALOG_SHA_CACHE or ""


def get_per_mapping_sha(gate_code: str) -> str:
    """Retorna SHA-256 (12 chars) del mapping específico para un gate.

    Calculado on-demand (cached). Útil para audit forense:
    "¿Qué versión exacta del cross-check estaba activa para este gate
    cuando se emitió esta decisión?"
    """
    if not gate_code:
        return ""
    if gate_code in _PER_MAPPING_SHA_CACHE:
        return _PER_MAPPING_SHA_CACHE[gate_code]
    mapping = get_mapping_for_gate(gate_code)
    if not mapping:
        return ""
    # Canonical JSON representation for stable SHA
    canonical = json.dumps(mapping, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    _PER_MAPPING_SHA_CACHE[gate_code] = sha
    return sha


def get_all_per_mapping_shas() -> dict[str, str]:
    """Retorna {gate_code: sha} para todos los mappings (audit summary)."""
    return {code: get_per_mapping_sha(code) for code in get_all_gate_codes()}


def reset_catalog_cache() -> None:
    """Limpia cache (test-only)."""
    global _CATALOG_CACHE, _CATALOG_SHA_CACHE
    _CATALOG_CACHE = None
    _CATALOG_SHA_CACHE = None
    _PER_MAPPING_SHA_CACHE.clear()


# ════════════════════════════════════════════════════════════════════
# Compatibility helpers (resuelven los 3 dicts originales)
# ════════════════════════════════════════════════════════════════════


def build_gate_to_ddi_categories_dict() -> dict[str, tuple[str, ...]]:
    """Reconstruye `_GATE_TO_RELATED_DDI_CATEGORIES` desde YAML.

    Returns:
        dict[str, tuple[str, ...]] — mismo formato que el dict Python original.
    """
    catalog = load_cross_check_catalog()
    mappings = catalog.get("mappings") or {}
    return {
        code: tuple(m.get("ddi_categories") or [])
        for code, m in mappings.items()
        if m.get("ddi_categories")
    }


def build_gate_to_oncology_drugs_dict() -> dict[str, list[str]]:
    """Reconstruye `_GATE_TO_ONCOLOGY_DRUGS` desde YAML."""
    catalog = load_cross_check_catalog()
    mappings = catalog.get("mappings") or {}
    return {
        code: list(m.get("oncology_drugs") or [])
        for code, m in mappings.items()
        if m.get("oncology_drugs")
    }


def build_gate_summaries_dict() -> dict[str, str]:
    """Reconstruye `_GATE_SUMMARIES` desde YAML."""
    catalog = load_cross_check_catalog()
    mappings = catalog.get("mappings") or {}
    return {
        code: m.get("ui_summary", "")
        for code, m in mappings.items()
        if m.get("ui_summary")
    }


# ════════════════════════════════════════════════════════════════════
# Schema validation (consistencia per Tier 4 K)
# ════════════════════════════════════════════════════════════════════


REQUIRED_MAPPING_FIELDS = ("ddi_categories", "oncology_drugs", "ui_summary")
OPTIONAL_MAPPING_FIELDS = ("description", "faubot_added_in")
ALLOWED_DDI_CATEGORIES = frozenset({
    "qtc_prolongation",
    "seizure_threshold",
    "cyp3a4_inhibition",
    "cyp3a4_induction",
    "cyp2c19_induction",
    "pharmacodynamic_aldosterone",
    "bone_remodeling",
})


def validate_catalog() -> list[str]:
    """Valida el catalog YAML contra schema. Retorna lista de errores
    (vacía si válido).

    Verifica:
      - Cada mapping tiene los 3 required fields
      - ddi_categories son del set ALLOWED_DDI_CATEGORIES
      - oncology_drugs es non-empty list[str]
      - ui_summary es non-empty str
    """
    errors: list[str] = []
    catalog = load_cross_check_catalog()
    mappings = catalog.get("mappings") or {}

    if not mappings:
        errors.append("Catalog has 0 mappings (expected ≥1)")
        return errors

    for code, mapping in mappings.items():
        if not isinstance(mapping, dict):
            errors.append(f"{code}: mapping is not a dict ({type(mapping).__name__})")
            continue
        for required_field in REQUIRED_MAPPING_FIELDS:
            if required_field not in mapping:
                errors.append(f"{code}: missing required field '{required_field}'")

        # Validate ddi_categories
        cats = mapping.get("ddi_categories") or []
        if not isinstance(cats, list):
            errors.append(f"{code}: ddi_categories must be list")
        else:
            unknown = [c for c in cats if c not in ALLOWED_DDI_CATEGORIES]
            if unknown:
                errors.append(
                    f"{code}: ddi_categories contains unknown values: {unknown}. "
                    f"Allowed: {sorted(ALLOWED_DDI_CATEGORIES)}"
                )

        # Validate oncology_drugs
        drugs = mapping.get("oncology_drugs") or []
        if not isinstance(drugs, list) or not drugs:
            errors.append(f"{code}: oncology_drugs must be non-empty list")
        elif not all(isinstance(d, str) for d in drugs):
            errors.append(f"{code}: oncology_drugs must be list[str]")

        # Validate ui_summary
        summary = mapping.get("ui_summary", "")
        if not isinstance(summary, str) or not summary.strip():
            errors.append(f"{code}: ui_summary must be non-empty string")

    return errors


def get_catalog_metadata() -> dict[str, Any]:
    """Retorna metadata del catalog (release, schema_version, total_mappings, etc.)."""
    catalog = load_cross_check_catalog()
    return {
        "faubot_release": catalog.get("faubot_release", ""),
        "schema_version": catalog.get("schema_version", ""),
        "total_mappings_declared": catalog.get("total_mappings", 0),
        "total_mappings_loaded": len(catalog.get("mappings") or {}),
        "ddi_categories_supported": catalog.get("ddi_categories_supported", []),
        "catalog_sha": get_catalog_sha(),
        "catalog_file_path": str(_CATALOG_FILE),
    }
