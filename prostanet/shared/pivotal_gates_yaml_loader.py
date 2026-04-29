"""pivotal_gates_yaml_loader.py — FAUBOT auditoría 2026-04-25 (XI).

Loader genérico de gates pivotal declarativos en formato YAML.

Cada gate YAML tiene esta estructura:

```yaml
code: prior_arpi_exposure_mhspc
title: "Exposición previa a ARPI en mHSPC"
faubot_added_in: "2026-04-23 I"
severity: hard_block

trigger:
  type: truthy_flag       # o: numeric_threshold | numeric_below | string_match
  field: prior_arpi_exposure_mhspc
  alias_fields: []        # campos que también activan el trigger

# Para numeric_threshold/numeric_below:
#   field: peripheral_neuropathy_grade
#   threshold: 3           # >= threshold (numeric_threshold) o < threshold (numeric_below)

# Para string_match:
#   field: nyha_class
#   match_values: [III, IV, "3", "4"]
#   case_insensitive: true
#   strip: true

override:                  # null si no hay override
  type: truthy_flag
  field: cord_compression_stabilized

regimen_codes:             # nombre canónico del catálogo en gates module
  - REGIMEN_CODES_DAROLUTAMIDE
keywords:
  - REGIMEN_KEYWORDS_DAROLUTAMIDE  # o lista literal de strings

message: |
  Mensaje clínico ES-médica (multi-línea OK).

evidence_tag: saad_lancet_oncol_2024_aranote
trial_refs:
  - ARANOTE
  - "Lynparza label"
```

**Aporte a auditabilidad:**
  - **VERSIÓN granular:** cada gate YAML tiene su propio SHA computado on-demand
  - **EVIDENCIA explícita:** la evidencia y trial_refs son campos de primera clase
  - **AUDITABILIDAD regulatoria:** un revisor FDA SaMD puede leer el YAML sin
    leer Python

**Sistema híbrido:**
  - Gates simples migrados a YAML cargados primero
  - Gates complejos (dual-trigger, calculated deltas, etc.) siguen en Python
  - Deduplicación por `code` evita doble-trigger del mismo gate
  - Todos los gates retornan el mismo formato dict que `pivotal_contraindication_gates`
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml


CATALOG_DIR = Path(__file__).parent / "pivotal_gates_catalog"


# ── Helpers de detección reutilizables ─────────────────────────────────
# Faubot 2026-04-25 (XXII) — Refactor R5 (code-simplifier report):
# Importados desde el módulo canónico para garantizar paridad bit-a-bit
# entre detectores Python y evaluadores YAML. Antes este módulo tenía
# definiciones locales duplicadas (~30 líneas) que ya estaban
# sincronizadas con el canónico, pero eran un riesgo de drift silencioso
# si el set de tokens ES-médica se extendía solo en un lado.
# Ver también: Hotfix R8 (2026-04-25 XXI) que aplicó el mismo patrón
# a `gates_ddi_cross_check.py`.
from prostanet.shared.pivotal_contraindication_gates import (
    _truthy_token,
    _safe_int,
    _safe_float,
)


# ── Resolvedores de catálogos compartidos ──────────────────────────────


_CATALOG_RESOLVER_CACHE: dict[str, Any] = {}


def _resolve_catalog(name: str) -> frozenset | tuple:
    """Resuelve un nombre canónico de catálogo (e.g., REGIMEN_CODES_DAROLUTAMIDE)
    contra los frozensets/tuples existentes en `pivotal_contraindication_gates`.

    Esto evita duplicar los catálogos en el YAML — el YAML solo cita el nombre.
    """
    if name in _CATALOG_RESOLVER_CACHE:
        return _CATALOG_RESOLVER_CACHE[name]
    try:
        from prostanet.shared import pivotal_contraindication_gates as gates_mod
        catalog = getattr(gates_mod, name, None)
        if catalog is None:
            _CATALOG_RESOLVER_CACHE[name] = frozenset()
            return frozenset()
        _CATALOG_RESOLVER_CACHE[name] = catalog
        return catalog
    except ImportError:
        return frozenset()


def _resolve_regimen_codes(refs: list) -> frozenset[str]:
    """Resuelve una lista mixta de catálogos canónicos + códigos literales."""
    out: set[str] = set()
    for ref in refs or []:
        if not ref:
            continue
        if isinstance(ref, str) and ref.startswith("REGIMEN_CODES_"):
            resolved = _resolve_catalog(ref)
            if isinstance(resolved, (frozenset, set, list, tuple)):
                out.update(str(r) for r in resolved)
        else:
            out.add(str(ref))
    return frozenset(out)


def _resolve_keywords(refs: list) -> tuple[str, ...]:
    """Resuelve una lista mixta de catálogos canónicos + keywords literales."""
    out: list[str] = []
    seen: set[str] = set()
    for ref in refs or []:
        if not ref:
            continue
        if isinstance(ref, str) and (
            ref.startswith("KEYWORDS_") or ref.startswith("REGIMEN_KEYWORDS_")
        ):
            resolved = _resolve_catalog(ref)
            if isinstance(resolved, (tuple, list, frozenset, set)):
                for kw in resolved:
                    s = str(kw)
                    if s not in seen:
                        out.append(s)
                        seen.add(s)
        else:
            s = str(ref)
            if s not in seen:
                out.append(s)
                seen.add(s)
    return tuple(out)


# ── Evaluación de triggers declarativos ────────────────────────────────


# ── Trigger handlers individuales (Faubot 2026-04-25 XXII — Refactor R6) ─
# Cada handler es una función pura que evalúa UN trigger type contra el
# payload. La función pública `_evaluate_trigger` despacha al handler
# correspondiente vía `_TRIGGER_HANDLERS` (dict de nombre → función).
#
# Beneficios de este refactor:
#   - Complejidad ciclomática de `_evaluate_trigger` ↓ de ~25 a ~3
#   - Cada handler ≤ 25 líneas, testeable individualmente
#   - Añadir nuevo trigger type = añadir 1 entry al dispatch dict
#   - Comentarios históricos por trigger preservados como docstrings
#
# Helper compartido por handlers que usan `field` + `alias_fields`:


def _candidate_fields(trigger: dict) -> list[str]:
    """Extrae lista de campos candidatos: [field] + alias_fields.

    Usado por `truthy_flag`, `numeric_threshold/above/below`, `string_match`,
    `string_contains_any` para soportar aliases canónicos ES/EN.
    """
    field = trigger.get("field", "")
    alias_fields = trigger.get("alias_fields") or []
    return [field] + list(alias_fields) if field else list(alias_fields)


def _eval_any_of(trigger: dict, payload: dict) -> bool:
    """Faubot 2026-04-25 (XIII) — Trigger compuesto OR lógico.

    Dispara si CUALQUIER sub-trigger dispara. Útil para gates con
    múltiples disparadores (e.g., QTc absoluto > 500 O ΔQTc > 60).
    """
    sub_triggers = trigger.get("triggers") or []
    return any(_evaluate_trigger(sub, payload) for sub in sub_triggers)


def _eval_all_of(trigger: dict, payload: dict) -> bool:
    """Faubot 2026-04-25 (XIX) — Trigger compuesto AND lógico.

    Mirror positivo de `any_of`. Dispara SOLO si TODOS los sub-triggers
    disparan. Usado por gate 9 (Ra-223 considerado AND ningún agente óseo
    declarado).
    """
    sub_triggers = trigger.get("triggers") or []
    if not sub_triggers:
        return False
    return all(_evaluate_trigger(sub, payload) for sub in sub_triggers)


def _eval_all_of_falsy(trigger: dict, payload: dict) -> bool:
    """Faubot 2026-04-25 (XIX) — Trigger especializado AND-NEGATIVE.

    Dispara cuando TODOS los campos especificados son "falsy" según
    semántica extendida con `negative_tokens` opcional por campo:

      - Sin `negative_tokens`: campo falsy si `not _truthy_token(value)`
      - Con `negative_tokens`: campo falsy si vacío O ∈ negative_tokens
        (lowercase strip)

    Útil para gate 9 donde `bone_modifying_agent` puede ser "zoledronato"
    (truthy) o "ninguno" (falsy con negative_token).
    """
    fields_specs = trigger.get("fields") or []
    if not fields_specs:
        return False
    for spec in fields_specs:
        if not isinstance(spec, dict):
            continue
        field_name = spec.get("field", "")
        if not field_name:
            continue
        value = payload.get(field_name)
        negative_tokens = spec.get("negative_tokens")
        if negative_tokens:
            if value in (None, ""):
                continue  # campo falsy ✓
            normalized = str(value).strip().lower()
            neg_set = {str(t).strip().lower() for t in negative_tokens}
            if normalized in neg_set:
                continue  # campo falsy ✓
            return False  # campo NO es falsy → trigger NO dispara
        else:
            if _truthy_token(value):
                return False
    return True


def _eval_numeric_baseline_delta_above(trigger: dict, payload: dict) -> bool:
    """Faubot 2026-04-25 (XIII) — Dispara si baseline - current > threshold.

    Usado para CAÍDAS (drops) — gate 18 LVEF (caída > 10 puntos absolutos),
    gate 19 MMSE/MoCA (caída ≥2 puntos), gate 33 plt drop niraparib,
    gate 34 ANC drop docetaxel. Para SUBIDAS (rises) usar
    `numeric_baseline_delta_rise_above` (Faubot LIII / #50).
    """
    threshold = trigger.get("threshold")
    baseline_field = trigger.get("baseline_field", "")
    current_field = trigger.get("current_field", "")
    if threshold is None or not baseline_field or not current_field:
        return False
    baseline = _safe_float(payload.get(baseline_field))
    current = _safe_float(payload.get(current_field))
    if baseline is None or current is None:
        return False
    return (baseline - current) > threshold


def _eval_numeric_baseline_delta_rise_above(trigger: dict, payload: dict) -> bool:
    """Faubot 2026-04-25 (LIII) — Tier 7 / #50: dispara si current - baseline > threshold.

    Inverso de `numeric_baseline_delta_above` — para detectar SUBIDAS
    rápidas (RISES) en biomarcadores cuando el daño se manifiesta como
    incremento absoluto desde basal:
      - ALP rise (gate 39 abiraterona colestasis)
      - AST/ALT rise (futuros gates DILI longitudinal)
      - Bilirubina rise (futuros gates colestasis)
      - Creatinina rise (futuros gates AKI)
      - Glucosa rise (futuros gates hiperglucemia inducida)

    Mismo schema que numeric_baseline_delta_above: requires `baseline_field`
    + `current_field` + `threshold`. Sin alias support en current_field
    (limitación heredada — usar Path B `numeric_above` aparte si se quieren
    aliases en el current).
    """
    threshold = trigger.get("threshold")
    baseline_field = trigger.get("baseline_field", "")
    current_field = trigger.get("current_field", "")
    if threshold is None or not baseline_field or not current_field:
        return False
    baseline = _safe_float(payload.get(baseline_field))
    current = _safe_float(payload.get(current_field))
    if baseline is None or current is None:
        return False
    return (current - baseline) > threshold


def _eval_truthy_flag(trigger: dict, payload: dict) -> bool:
    """Dispara si payload[field] (o cualquier alias) es truthy según
    el set canónico ES-médica (`Sí`, `documentado`, `positivo`, etc.)."""
    candidates = _candidate_fields(trigger)
    if not candidates:
        return False
    return any(_truthy_token(payload.get(f)) for f in candidates)


def _eval_numeric_compare(
    trigger: dict, payload: dict, op: str,
) -> bool:
    """Comparación numérica genérica parametrizada por operador.

    Maneja `numeric_threshold` (≥), `numeric_above` (>), `numeric_below` (<)
    con la misma lógica de candidate_fields + safe_float.
    """
    threshold = trigger.get("threshold")
    if threshold is None:
        return False
    candidates = _candidate_fields(trigger)
    if not candidates:
        return False
    for f in candidates:
        v = _safe_float(payload.get(f))
        if v is None:
            continue
        if op == "ge" and v >= threshold:
            return True
        if op == "gt" and v > threshold:
            return True
        if op == "lt" and v < threshold:
            return True
    return False


def _eval_numeric_threshold(trigger: dict, payload: dict) -> bool:
    """Dispara si payload[field] >= threshold (con igualdad)."""
    return _eval_numeric_compare(trigger, payload, "ge")


def _eval_numeric_above(trigger: dict, payload: dict) -> bool:
    """Faubot 2026-04-25 (XIII) — Dispara si payload[field] > threshold (estricto).

    Usado por gate 17 QTc (> 500 ms grado 3) y gate 18 LVEF baseline_delta.
    """
    return _eval_numeric_compare(trigger, payload, "gt")


def _eval_numeric_below(trigger: dict, payload: dict) -> bool:
    """Dispara si payload[field] < threshold (estricto)."""
    return _eval_numeric_compare(trigger, payload, "lt")


def _eval_string_match(trigger: dict, payload: dict) -> bool:
    """Dispara si payload[field] (igualdad strict) ∈ match_values/patterns.

    Default case_insensitive=True, strip=True. Usado por gate 4 (NYHA III/IV).
    Faubot LXXVII #67C — `patterns` aceptado como alias de `match_values`
    para compatibilidad con gates 56-70 catalog (#67A/B/C).
    """
    # Faubot LXXVII #67C — Aceptar `patterns` como alias de `match_values`
    raw_values = trigger.get("match_values")
    if raw_values is None:
        raw_values = trigger.get("patterns") or []
    match_values = [str(v) for v in raw_values]
    case_insensitive = bool(trigger.get("case_insensitive", True))
    strip = bool(trigger.get("strip", True))
    candidates = _candidate_fields(trigger)
    if not candidates:
        return False
    if case_insensitive:
        match_set = {v.upper() for v in match_values}
    else:
        match_set = set(match_values)
    for f in candidates:
        raw = payload.get(f)
        if raw in (None, ""):
            continue
        s = str(raw)
        if strip:
            s = s.strip()
        if case_insensitive:
            s = s.upper()
        if s in match_set:
            return True
    return False


def _eval_string_contains_any(trigger: dict, payload: dict) -> bool:
    """Faubot 2026-04-25 (XVIII) — Substring match con keywords/patterns list.

    Usado por gates 11/13 (cord compression) para detectar debilidad MMII y
    síntomas neurológicos por keywords ES-médicas (moderada, severa, paresia,
    debilidad mmii, anestesia, retención urinaria nueva, incontinencia fecal).

    Faubot LXXVII #67C — `patterns` aceptado como alias de `keywords` para
    compatibilidad con gates 56-70 catalog (#67A/B/C).
    """
    # Faubot LXXVII #67C — Aceptar `patterns` como alias de `keywords`
    raw_keywords = trigger.get("keywords")
    if raw_keywords is None:
        raw_keywords = trigger.get("patterns") or []
    keywords = [str(kw) for kw in raw_keywords]
    case_insensitive = bool(trigger.get("case_insensitive", True))
    strip = bool(trigger.get("strip", True))
    candidates = _candidate_fields(trigger)
    if not candidates:
        return False
    if case_insensitive:
        keywords_norm = [kw.lower() for kw in keywords]
    else:
        keywords_norm = keywords
    for f in candidates:
        raw = payload.get(f)
        if raw in (None, ""):
            continue
        s = str(raw)
        if strip:
            s = s.strip()
        if case_insensitive:
            s = s.lower()
        if any(kw in s for kw in keywords_norm):
            return True
    return False


# ── Dispatch table — Faubot 2026-04-25 (XXII) Refactor R6 ───────────────
# Mapping `trigger.type` → handler. Añadir un nuevo trigger type es:
#   1. Implementar `_eval_<name>(trigger, payload) -> bool`
#   2. Añadir entry aquí
#   3. Añadir el nombre a `VALID_TRIGGER_TYPES` (sección de validación)


_TRIGGER_HANDLERS = {
    "any_of": _eval_any_of,
    "all_of": _eval_all_of,
    "all_of_falsy": _eval_all_of_falsy,
    "numeric_baseline_delta_above": _eval_numeric_baseline_delta_above,
    # Faubot 2026-04-25 (LIII / #50) — RISE inverso (current - baseline)
    "numeric_baseline_delta_rise_above": _eval_numeric_baseline_delta_rise_above,
    "truthy_flag": _eval_truthy_flag,
    "numeric_threshold": _eval_numeric_threshold,
    "numeric_above": _eval_numeric_above,
    "numeric_below": _eval_numeric_below,
    "string_match": _eval_string_match,
    "string_contains_any": _eval_string_contains_any,
}


def _evaluate_trigger(trigger: dict, payload: dict) -> bool:
    """Evalúa un bloque trigger declarativo contra el payload.

    Dispatch table-driven (Refactor R6 — Faubot 2026-04-25 XXII).
    Trigger types soportados están en `_TRIGGER_HANDLERS`. Trigger
    desconocido o vacío retorna `False` (fail-safe).
    """
    if not trigger:
        return False
    handler = _TRIGGER_HANDLERS.get(trigger.get("type", ""))
    return handler(trigger, payload) if handler else False


def _evaluate_override(override: dict | None, payload: dict) -> bool:
    """Evalúa el override (si existe). Si retorna True, el gate se desactiva."""
    if not override:
        return False
    return _evaluate_trigger(override, payload)


# ── Carga de gates YAML ────────────────────────────────────────────────


_YAML_CACHE: dict[str, dict] | None = None
_YAML_PATHS_CACHE: dict[str, Path] | None = None


def _load_yaml_files(force_reload: bool = False) -> dict[str, dict]:
    """Carga todos los archivos YAML del catálogo.

    Returns:
        Dict {gate_code: gate_config_dict}.
    """
    global _YAML_CACHE, _YAML_PATHS_CACHE
    if _YAML_CACHE is not None and not force_reload:
        return _YAML_CACHE
    cache: dict[str, dict] = {}
    paths: dict[str, Path] = {}
    if not CATALOG_DIR.exists():
        _YAML_CACHE = cache
        _YAML_PATHS_CACHE = paths
        return cache
    for yaml_path in sorted(CATALOG_DIR.glob("*.yaml")):
        try:
            with yaml_path.open("r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            continue
        code = str(config.get("code") or "").strip()
        if not code:
            continue
        cache[code] = config
        paths[code] = yaml_path
    _YAML_CACHE = cache
    _YAML_PATHS_CACHE = paths
    return cache


def reset_yaml_cache() -> None:
    """Útil en tests para forzar recarga."""
    global _YAML_CACHE, _YAML_PATHS_CACHE, _CATALOG_RESOLVER_CACHE
    _YAML_CACHE = None
    _YAML_PATHS_CACHE = None
    _CATALOG_RESOLVER_CACHE = {}


def get_loaded_yaml_codes() -> list[str]:
    """Lista de códigos de gates cargados desde YAML."""
    return sorted(_load_yaml_files().keys())


def get_yaml_gate_sha(gate_code: str) -> str | None:
    """SHA-256 del archivo YAML de un gate (primeros 12 chars)."""
    _load_yaml_files()
    paths = _YAML_PATHS_CACHE or {}
    path = paths.get(gate_code)
    if not path or not path.exists():
        return None
    try:
        contents = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(contents).hexdigest()[:12]


def get_all_yaml_gate_shas() -> dict[str, str]:
    """Retorna {gate_code: sha} para todos los gates YAML cargados."""
    _load_yaml_files()
    paths = _YAML_PATHS_CACHE or {}
    return {
        code: sha
        for code in paths
        if (sha := get_yaml_gate_sha(code))
    }


# ── Detector dinámico desde YAML ───────────────────────────────────────


def evaluate_yaml_gate(config: dict, payload: dict) -> dict | None:
    """Evalúa un único gate declarativo contra el payload.

    Returns:
        Dict con la misma estructura que los detectores Python:
            {code, triggered, severity, affected_regimen_codes,
             affected_keywords, message, evidence_tag, trial_refs}
        O None si el gate no dispara (o el override lo desactiva).
    """
    if not config:
        return None
    trigger = config.get("trigger") or {}
    if not _evaluate_trigger(trigger, payload):
        return None
    # Override
    override = config.get("override")
    if _evaluate_override(override, payload):
        return None

    regimen_codes = _resolve_regimen_codes(config.get("regimen_codes") or [])
    keywords = _resolve_keywords(config.get("keywords") or [])
    return {
        "code": str(config.get("code", "")),
        "triggered": True,
        "severity": str(config.get("severity", "hard_block")),
        "affected_regimen_codes": regimen_codes,
        "affected_keywords": keywords,
        "message": str(config.get("message") or "").strip(),
        "evidence_tag": str(config.get("evidence_tag") or ""),
        "trial_refs": tuple(str(r) for r in (config.get("trial_refs") or [])),
    }


def evaluate_all_yaml_gates(payload: dict) -> list[dict]:
    """Evalúa todos los gates YAML y retorna los que disparan."""
    triggered: list[dict] = []
    for config in _load_yaml_files().values():
        result = evaluate_yaml_gate(config, payload)
        if result and result.get("triggered"):
            triggered.append(result)
    return triggered


# ── Validación de schema ───────────────────────────────────────────────


REQUIRED_FIELDS = {"code", "severity", "trigger", "message", "evidence_tag"}
# Faubot 2026-04-25 (XIII + XVIII + XIX) — Tipos de trigger soportados.
# Compuestos: any_of (OR), all_of (AND).
# Especializados: all_of_falsy (todos los campos falsy con tokens negativos opcionales).
# Numéricos: numeric_threshold (>=), numeric_above (>), numeric_below (<),
#            numeric_baseline_delta_above (baseline-current > threshold).
# Strings:   string_match (igualdad), string_contains_any (substring).
# Otros:     truthy_flag.
VALID_TRIGGER_TYPES = {
    "truthy_flag",
    "numeric_threshold",
    "numeric_above",
    "numeric_below",
    "numeric_baseline_delta_above",
    # Faubot 2026-04-25 (LIII / #50) — RISE inverso (current - baseline)
    "numeric_baseline_delta_rise_above",
    "string_match",
    "string_contains_any",
    "any_of",
    "all_of",
    "all_of_falsy",
}
VALID_SEVERITIES = {
    "hard_block",
    "soft", "high", "moderate", "low",
    # Faubot LVIII (#62) — Nuevas severities informacionales/anti-misinterpretation:
    "soft_warning",      # Gate 47 PSA flare ARPI (NO bloquea régimen, solo advierte clínico)
    "informational",     # Equivalente a soft_warning para gates educacionales puros
}


def validate_yaml_gate_config(config: dict) -> list[str]:
    """Valida un dict de configuración YAML. Retorna lista de errores
    (vacía si todo OK)."""
    errors: list[str] = []
    if not isinstance(config, dict):
        return ["Config must be a dict"]
    missing = REQUIRED_FIELDS - set(config.keys())
    if missing:
        errors.append(f"Missing required fields: {sorted(missing)}")
    if config.get("severity") and config["severity"] not in VALID_SEVERITIES:
        errors.append(f"Invalid severity: {config['severity']}")
    trigger = config.get("trigger") or {}
    if not isinstance(trigger, dict):
        errors.append("trigger must be a dict")
    elif trigger.get("type") and trigger["type"] not in VALID_TRIGGER_TYPES:
        errors.append(f"Invalid trigger.type: {trigger['type']}")
    else:
        # Faubot 2026-04-25 (XIII + XIX) — Validación específica por tipo.
        ttype = trigger.get("type")
        if ttype in {"any_of", "all_of"}:
            sub = trigger.get("triggers")
            if not isinstance(sub, list) or not sub:
                errors.append(
                    f"trigger.{ttype} requires non-empty 'triggers' list"
                )
        elif ttype == "all_of_falsy":
            fields = trigger.get("fields")
            if not isinstance(fields, list) or not fields:
                errors.append(
                    "trigger.all_of_falsy requires non-empty 'fields' list"
                )
            else:
                for spec in fields:
                    if not isinstance(spec, dict) or not spec.get("field"):
                        errors.append(
                            "trigger.all_of_falsy.fields[*] must be dict with 'field' key"
                        )
                        break
        elif ttype == "numeric_baseline_delta_above":
            if not (trigger.get("baseline_field") and trigger.get("current_field")):
                errors.append(
                    "trigger.numeric_baseline_delta_above requires "
                    "'baseline_field' and 'current_field'"
                )
        else:
            # Tipos clásicos: requieren field o alias_fields
            if not (trigger.get("field") or trigger.get("alias_fields")):
                errors.append("trigger must specify 'field' or 'alias_fields'")
    return errors


def validate_all_yaml_gates() -> dict[str, list[str]]:
    """Valida todos los gates YAML cargados. Retorna {code: [errors]}."""
    out: dict[str, list[str]] = {}
    for code, config in _load_yaml_files().items():
        errors = validate_yaml_gate_config(config)
        if errors:
            out[code] = errors
    return out
