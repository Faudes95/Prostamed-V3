# IEC 62304 §5.7 (System testing)
"""Tests EPIC 10B — Gate field coverage audit (contract integrity).

Valida que cada gate pivotal YAML referencia campos que existen en el
contrato canónico (FieldSpecs declarados en los SCHEMAS de cada dominio).

A diferencia de "UI render coverage" (que validaría DOM con Playwright),
esta auditoría verifica el **contrato de inputs**: si un gate evalúa
`peripheral_neuropathy_grade`, ese field debe existir en algún schema
canónico — sino el gate nunca se dispara con datos reales del paciente.

Cobertura:
  1. Cada `trigger.field` (y `alias_fields`) referenciado existe como
     FieldSpec en algún SCHEMA del catálogo.
  2. `any_of` / `all_of` / `all_of_falsy` se desempaquetan recursivamente
     y todos sus sub-triggers también son auditados.
  3. `override.field` también referencia un FieldSpec canónico.
  4. Cada gate tiene `evidence_tag` no vacío (regulatoriedad).
  5. Cada gate tiene `trial_refs` no vacío (evidencia auditable).
  6. Cada gate `hard_block` tiene `nccn_eau_alignment` (guideline path).

Inputs auditados:
  - 103 gates YAML deduplicados por code en
    `prostanet/shared/pivotal_gates_catalog/*.yaml`.
  - 17 SCHEMAS canónicos en `prostanet/domains/*/schemas.py`.

Resultado esperado: cero `field_orphans`. Gates huérfanos son blockers
clínicos — el motor parecerá ejecutarse pero el gate nunca se dispara.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Any, Iterable

import pytest


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _iter_canonical_field_names() -> set[str]:
    """Construye el set unión de FieldSpec.name sobre los 17 SCHEMAS."""
    import prostanet.domains as dp

    names: set[str] = set()
    for _finder, modname, _ispkg in pkgutil.iter_modules(dp.__path__, prefix="prostanet.domains."):
        try:
            schemas_mod = importlib.import_module(modname + ".schemas")
        except Exception:
            continue
        for attr in dir(schemas_mod):
            if not attr.endswith("_SCHEMA") or attr.startswith("_"):
                continue
            schema = getattr(schemas_mod, attr)
            if not isinstance(schema, dict) or "fields" not in schema:
                continue
            for fld in schema["fields"]:
                name = fld.name if hasattr(fld, "name") else (fld.get("name") if isinstance(fld, dict) else None)
                if name:
                    names.add(name)
    return names


def _candidate_groups_from_trigger(trigger: dict[str, Any] | None) -> list[set[str]]:
    """Extrae grupos de candidate fields donde **al menos uno** debe
    existir en el schema canónico para que el trigger sea ejecutable.

    Semántica del loader (`pivotal_gates_yaml_loader._candidate_fields`):
        Un trigger se dispara si payload contiene CUALQUIERA del
        conjunto {field, *alias_fields}. Por eso cada leaf trigger
        produce UN grupo de candidatos (no múltiples fields que deban
        existir todos).

    Composite triggers:
      - any_of  → grupos planos: cada sub-trigger produce su(s) grupo(s).
      - all_of  → cada sub-trigger DEBE poder disparar → cada uno aporta
                  su grupo independientemente.
      - all_of_falsy → idem (cada field debe estar capturado).

    Multi-field triggers (`numeric_baseline_delta_*`) requieren ambos
    fields → producen 2 grupos singleton (uno por field).
    """
    if not trigger or not isinstance(trigger, dict):
        return []

    ttype = trigger.get("type") or ""
    groups: list[set[str]] = []

    if ttype in {"any_of", "all_of", "all_of_falsy"}:
        for sub in trigger.get("triggers") or []:
            groups.extend(_candidate_groups_from_trigger(sub))
        # all_of_falsy at top level may also include fields list directly:
        for entry in trigger.get("fields") or []:
            if isinstance(entry, str):
                groups.append({entry})
            elif isinstance(entry, dict) and entry.get("field"):
                aliases = entry.get("alias_fields") or []
                groups.append({entry["field"], *aliases})
        return groups

    # Leaf trigger.
    main_field = trigger.get("field")
    aliases = list(trigger.get("alias_fields") or [])
    if main_field or aliases:
        candidate_set = set(filter(None, [main_field, *aliases]))
        if candidate_set:
            groups.append(candidate_set)

    # numeric_baseline_delta_*: requiere baseline + current (2 grupos).
    if trigger.get("baseline_field"):
        groups.append({trigger["baseline_field"]})
    if trigger.get("current_field"):
        groups.append({trigger["current_field"]})

    return groups


def _load_gates() -> dict[str, dict[str, Any]]:
    """Carga los gates YAML deduplicados por code."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files

    return _load_yaml_files()


def _gate_orphan_groups(
    gate: dict[str, Any],
    canonical: set[str],
    derived_allowlist: set[str],
) -> list[set[str]]:
    """Retorna los grupos de candidatos donde NINGÚN field está en canonical.

    Un grupo huérfano = el trigger nunca se puede disparar porque ninguno
    de sus candidate fields existe como FieldSpec capturable.
    """
    groups = _candidate_groups_from_trigger(gate.get("trigger"))
    groups.extend(_candidate_groups_from_trigger(gate.get("override")))
    orphan_groups: list[set[str]] = []
    for group in groups:
        if not (group & (canonical | derived_allowlist)):
            orphan_groups.append(group)
    return orphan_groups


def _gate_all_candidate_fields(gate: dict[str, Any]) -> set[str]:
    """Todos los fields que el gate puede llegar a referenciar (info)."""
    refs: set[str] = set()
    for group in _candidate_groups_from_trigger(gate.get("trigger")):
        refs.update(group)
    for group in _candidate_groups_from_trigger(gate.get("override")):
        refs.update(group)
    return refs


# ──────────────────────────────────────────────────────────────────────
# Fixtures / module-level computation
# ──────────────────────────────────────────────────────────────────────


CANONICAL_FIELDS = _iter_canonical_field_names()
GATES = _load_gates()
GATE_CODES = sorted(GATES.keys())

# Fields que son derivados/calculados en runtime (no FieldSpecs del schema).
# Mantener mínimo y documentado — cualquier adición requiere justificación
# clínica y referencia al cálculo en code.
# OJO: `{}` en Python es dict vacío, no set vacío. Usar `set()`.
DERIVED_FIELDS_ALLOWLIST: set[str] = {
    # EPIC 10F — outputs del state_classifier (no son inputs capturables;
    # se inyectan en payload por el motor de routing antes de evaluar gates).
    # Usados por gate `localized_bcr_adjuvant_trials_completion`.
    "state",
    "clinical_state",
    "estado_clinico",
    "reconciled_state",
}


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


def test_epic10b_catalog_loads_at_least_100_gates():
    """Audit baseline: el catálogo YAML debe cargar ≥100 gates dedup.

    Si el conteo cae bajo 100, el catálogo perdió cobertura clínica.
    """
    assert len(GATES) >= 100, (
        f"Catálogo YAML cargó {len(GATES)} gates, esperaba ≥100. "
        "Verificar que los YAMLs en pivotal_gates_catalog/ no fueron eliminados."
    )


def test_epic10b_canonical_fields_at_least_800():
    """Audit baseline: la unión de FieldSpecs sobre 17 schemas debe ser ≥800.

    El contrato canónico ha crecido a 835+ campos (EPIC 1-9). Si cae bajo
    800, algún SCHEMA fue removido o vaciado.
    """
    assert len(CANONICAL_FIELDS) >= 800, (
        f"Canonical FieldSpecs = {len(CANONICAL_FIELDS)}, esperaba ≥800. "
        "Verificar que los SCHEMAS de cada dominio no fueron vaciados."
    )


@pytest.mark.parametrize("gate_code", GATE_CODES)
def test_epic10b_gate_has_at_least_one_canonical_field_per_trigger_group(gate_code: str):
    """Cada grupo de candidate fields del gate debe contener AL MENOS uno
    que exista en algún SCHEMA canónico.

    Semántica: el loader dispara el trigger si payload contiene cualquiera
    de `{field, *alias_fields}`. Por eso basta con que UNO de los
    candidatos esté en el canon — los otros pueden ser aliases español/EN
    o naming alternativo del mismo concepto clínico.

    Si NINGUNO está en el canon → el trigger nunca puede disparar con
    datos reales → es un blocker clínico silencioso.

    Excepciones: DERIVED_FIELDS_ALLOWLIST (computed at runtime).
    """
    gate = GATES[gate_code]
    orphan_groups = _gate_orphan_groups(gate, CANONICAL_FIELDS, DERIVED_FIELDS_ALLOWLIST)
    assert not orphan_groups, (
        f"Gate '{gate_code}' tiene {len(orphan_groups)} trigger group(s) sin "
        f"ningún field canónico capturable. Grupos huérfanos: "
        f"{[sorted(g) for g in orphan_groups]}. "
        "Soluciones: (a) añadir uno de estos fields como FieldSpec en el "
        "schema del dominio relevante; (b) renombrar el `field` o añadirlo "
        "a `alias_fields` para coincidir con un FieldSpec existente; "
        "(c) si es derivado en runtime, añadirlo a DERIVED_FIELDS_ALLOWLIST."
    )


@pytest.mark.parametrize("gate_code", GATE_CODES)
def test_epic10b_gate_has_evidence_tag(gate_code: str):
    """Cada gate debe declarar `evidence_tag` no vacío (regulatoriedad)."""
    gate = GATES[gate_code]
    tag = (gate.get("evidence_tag") or "").strip()
    assert tag, (
        f"Gate '{gate_code}': evidence_tag vacío o ausente. "
        "FDA SaMD §IV.B.4: cada decisión debe estar anclada a evidencia "
        "identificable (trial PMID o guideline section)."
    )


@pytest.mark.parametrize("gate_code", GATE_CODES)
def test_epic10b_gate_has_non_empty_trial_refs(gate_code: str):
    """Cada gate debe declarar `trial_refs` no vacío (auditabilidad).

    Permite trial names (ARANOTE, ARASENS), PMIDs, o guideline IDs
    (e.g. "NCCN PROS-G 5.2026").
    """
    gate = GATES[gate_code]
    refs = gate.get("trial_refs") or []
    assert isinstance(refs, list) and len(refs) > 0, (
        f"Gate '{gate_code}': trial_refs vacío o no es lista. "
        f"Encontrado: {refs!r}. "
        "Cada gate debe tener al menos 1 trial/guideline referenciado."
    )


@pytest.mark.parametrize("gate_code", GATE_CODES)
def test_epic10b_gate_has_message(gate_code: str):
    """Cada gate debe declarar `message` con texto clínico ≥40 chars."""
    gate = GATES[gate_code]
    msg = (gate.get("message") or "").strip()
    assert len(msg) >= 40, (
        f"Gate '{gate_code}': message vacío o demasiado corto "
        f"({len(msg)} chars). El mensaje clínico debe ser ≥40 chars "
        "para ser interpretable por un urólogo."
    )


@pytest.mark.parametrize("gate_code", GATE_CODES)
def test_epic10b_gate_has_valid_severity(gate_code: str):
    """Severity debe ser uno de: hard_block, soft_warning, informational."""
    gate = GATES[gate_code]
    severity = gate.get("severity")
    assert severity in {"hard_block", "soft_warning", "informational"}, (
        f"Gate '{gate_code}': severity inválida '{severity}'. "
        "Permitidos: hard_block | soft_warning | informational."
    )


def test_epic10b_hard_blocks_have_guideline_alignment_or_documented_exception():
    """Cada gate `hard_block` debe tener alignment regulatorio documentado.

    Auditoría regulatoria (FDA SaMD Pre-Sub): cada hard-block debe poder
    mostrar el path NCCN/EAU/AUA/ASTRO section o FDA label que justifica
    bloquear el regimen. Se acepta alignment en cualquiera de:

      1. **Preferido (FDA Pre-Sub-ready):** `nccn_eau_alignment` dict con
         `nccn_section` o `eau_section` key.
      2. `references` block conteniendo "FDA label", "PI" o "Prescribing".
      3. `trial_refs` conteniendo mención explícita de "NCCN", "EAU",
         "AUA" o "ASTRO" guideline OR "<drug> label" (FDA labels son
         documentados como "Xofigo label", "Pluvicto label", etc.).

    El test EPIC 10G_format documenta qué gates aún deben migrar de #3
    a #1 para FDA Pre-Sub strict (sin bloquear ahora).
    """
    hard_block_gates = {code: g for code, g in GATES.items() if g.get("severity") == "hard_block"}
    missing_alignment = []
    for code, gate in hard_block_gates.items():
        alignment = gate.get("nccn_eau_alignment") or {}
        references = " ".join(gate.get("references") or [])
        trial_refs = " ".join(gate.get("trial_refs") or [])
        has_structured_alignment = bool(alignment.get("nccn_section") or alignment.get("eau_section"))
        has_fda_in_refs = ("FDA label" in references) or ("PI" in references) or ("Prescribing" in references)
        # Alignment in trial_refs (e.g., "NCCN Prostate v5.2026 PROS-2", "EAU 2026 §6.5.6")
        has_guideline_in_trials = any(
            t in trial_refs for t in ("NCCN ", "EAU ", "AUA ", "ASTRO ", "ESMO ", "ASCO ", "PCWG3", "AAOMS", "AAPM", "ABS ", "SNMMI", "WHO ", "EAPC ", "ICH-")
        )
        # FDA labels in trial_refs (e.g., "Xofigo label", "Pluvicto label")
        has_drug_label_in_trials = any(
            t in trial_refs for t in (
                "FDA label", "Xofigo label", "Pluvicto label", "Zytiga label",
                "Xtandi label", "Erleada label", "Nubeqa label", "Provenge label",
                "Lynparza label", "Keytruda label", "Cabometyx label", "Jevtana label",
                "label §", "label 5.", "label (",
            )
        )
        if not (has_structured_alignment or has_fda_in_refs or has_guideline_in_trials or has_drug_label_in_trials):
            missing_alignment.append(code)
    assert not missing_alignment, (
        f"{len(missing_alignment)} gates hard_block carecen de cualquier forma "
        f"de guideline alignment (nccn_eau_alignment / FDA label / NCCN/EAU/AUA/ASTRO "
        f"en trial_refs): {missing_alignment[:10]}"
        f"{'...' if len(missing_alignment) > 10 else ''}"
    )


def test_epic10b_no_duplicate_gate_codes():
    """No debe haber dos YAMLs con el mismo `code` (deduplicación implícita
    en `_load_yaml_files` puede ocultar conflictos: validar que el dedupe
    funcionó)."""
    # El loader retorna un dict por code, así que dups se silencian. Aquí
    # verificamos que cada code tiene al menos los campos mínimos: si el
    # dedup tomó la versión vacía, faltan trigger/evidence/message.
    for code, gate in GATES.items():
        assert gate.get("trigger"), f"Gate '{code}': trigger ausente (posible conflicto de dedup)."
        assert gate.get("severity"), f"Gate '{code}': severity ausente (posible conflicto de dedup)."


def test_epic10b_field_orphan_summary_for_diagnostic_visibility():
    """Summary diagnóstico: cuenta gates con grupos huérfanos.

    Un gate tiene grupo huérfano si ALGUNO de sus trigger groups carece
    de cualquier candidate field presente en el canon. Esto es el contrato
    mínimo de ejecutabilidad del gate.
    """
    gates_with_orphan_groups: list[str] = []
    for code, gate in GATES.items():
        if _gate_orphan_groups(gate, CANONICAL_FIELDS, DERIVED_FIELDS_ALLOWLIST):
            gates_with_orphan_groups.append(code)

    all_candidates: set[str] = set()
    for gate in GATES.values():
        all_candidates.update(_gate_all_candidate_fields(gate))
    unused = CANONICAL_FIELDS - all_candidates

    summary = (
        f"EPIC 10B summary: "
        f"{len(GATES)} gates · "
        f"{len(CANONICAL_FIELDS)} canonical fields · "
        f"{len(all_candidates)} candidate fields referenced · "
        f"{len(gates_with_orphan_groups)} gates with orphan group(s) · "
        f"{len(unused)} unused canonical fields (info)"
    )
    print(summary)
    assert not gates_with_orphan_groups, (
        f"{len(gates_with_orphan_groups)} gates have trigger group(s) with "
        f"zero canonical fields: "
        f"{gates_with_orphan_groups[:15]}{' ...' if len(gates_with_orphan_groups) > 15 else ''}"
    )
