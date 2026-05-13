#!/usr/bin/env python3
"""EPIC 10B — Gate field coverage auditor.

Genera un reporte Markdown con el estado de cobertura entre gates YAML
y los FieldSpecs canónicos del CDE Auditable.

Uso:
  PROSTANET_LOAD_MODEL=0 python3 scripts/epic10b_audit_gate_coverage.py
  PROSTANET_LOAD_MODEL=0 python3 scripts/epic10b_audit_gate_coverage.py \\
    --output output/epic10/gate_field_coverage_report.md

Reporte incluye:
  1. Summary: # gates, # canonical fields, # huérfanos, # unused
  2. Lista de gates con fields huérfanos (con scrutiny clínica sugerida)
  3. Lista de FieldSpecs sin uso (legacy / dead spec candidates)
  4. Cobertura por severidad (hard_block / soft_warning / informational)
  5. Cobertura por trigger type
"""
from __future__ import annotations

import argparse
import importlib
import os
import pkgutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# Sin LOAD_MODEL para evitar warnings de PyTorch.
os.environ.setdefault("PROSTANET_LOAD_MODEL", "0")

# Ajustar path para imports si el script se ejecuta desde otro directorio.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _iter_canonical_field_names() -> tuple[set[str], dict[str, list[str]]]:
    """Construye el set unión + mapa field_name → [schemas que lo contienen]."""
    import prostanet.domains as dp

    names: set[str] = set()
    by_schema: dict[str, list[str]] = defaultdict(list)
    for _f, modname, _ip in pkgutil.iter_modules(dp.__path__, prefix="prostanet.domains."):
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
                    by_schema[name].append(f"{modname.split('.')[-1]}.{attr}")
    return names, by_schema


def _candidate_groups_from_trigger(trigger: dict[str, Any] | None) -> list[set[str]]:
    """Mismo semántico que tests/test_epic10b_gate_field_coverage.py.

    Un grupo de candidatos = conjunto de fields donde AL MENOS uno debe
    existir en algún schema canónico para que el trigger sea ejecutable.
    Soporta any_of/all_of/all_of_falsy/leaf triggers/baseline-delta.
    """
    if not trigger or not isinstance(trigger, dict):
        return []
    ttype = trigger.get("type") or ""
    groups: list[set[str]] = []
    if ttype in {"any_of", "all_of", "all_of_falsy"}:
        for sub in trigger.get("triggers") or []:
            groups.extend(_candidate_groups_from_trigger(sub))
        for entry in trigger.get("fields") or []:
            if isinstance(entry, str):
                groups.append({entry})
            elif isinstance(entry, dict) and entry.get("field"):
                groups.append({entry["field"], *(entry.get("alias_fields") or [])})
        return groups
    main_field = trigger.get("field")
    aliases = list(trigger.get("alias_fields") or [])
    if main_field or aliases:
        cand = set(filter(None, [main_field, *aliases]))
        if cand:
            groups.append(cand)
    if trigger.get("baseline_field"):
        groups.append({trigger["baseline_field"]})
    if trigger.get("current_field"):
        groups.append({trigger["current_field"]})
    return groups


def _gate_all_candidate_fields(gate: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for grp in _candidate_groups_from_trigger(gate.get("trigger")):
        refs.update(grp)
    for grp in _candidate_groups_from_trigger(gate.get("override")):
        refs.update(grp)
    return refs


_DERIVED_FIELDS_ALLOWLIST: set[str] = {
    # Outputs del state_classifier inyectados en payload, no inputs capturables.
    "state",
    "clinical_state",
    "estado_clinico",
    "reconciled_state",
}


def _gate_orphan_groups(gate: dict[str, Any], canonical: set[str]) -> list[set[str]]:
    groups = _candidate_groups_from_trigger(gate.get("trigger"))
    groups.extend(_candidate_groups_from_trigger(gate.get("override")))
    return [g for g in groups if not (g & (canonical | _DERIVED_FIELDS_ALLOWLIST))]


def _load_gates() -> dict[str, dict[str, Any]]:
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    return _load_yaml_files()


def _audit() -> dict[str, Any]:
    gates = _load_gates()
    canonical, by_schema = _iter_canonical_field_names()

    gates_with_orphan_groups: dict[str, list[set[str]]] = {}
    all_candidate_fields: set[str] = set()
    severity_counter: Counter = Counter()
    trigger_type_counter: Counter = Counter()
    severity_with_orphans: Counter = Counter()
    gates_missing_evidence: list[str] = []
    gates_missing_trial_refs: list[str] = []
    gates_missing_alignment_hard_block: list[str] = []
    gates_short_message: list[tuple[str, int]] = []

    for code, gate in gates.items():
        severity = gate.get("severity", "?")
        severity_counter[severity] += 1
        trigger = gate.get("trigger") or {}
        trigger_type_counter[trigger.get("type", "?")] += 1

        all_candidate_fields.update(_gate_all_candidate_fields(gate))

        orphan_groups = _gate_orphan_groups(gate, canonical)
        if orphan_groups:
            gates_with_orphan_groups[code] = orphan_groups
            severity_with_orphans[severity] += 1

        if not (gate.get("evidence_tag") or "").strip():
            gates_missing_evidence.append(code)
        if not (gate.get("trial_refs") or []):
            gates_missing_trial_refs.append(code)
        msg = (gate.get("message") or "").strip()
        if len(msg) < 40:
            gates_short_message.append((code, len(msg)))
        if severity == "hard_block":
            align = gate.get("nccn_eau_alignment") or {}
            refs_str = " ".join(gate.get("references") or [])
            if not (align.get("nccn_section") or align.get("eau_section")):
                if not any(t in refs_str for t in ("FDA label", "PI", "Prescribing")):
                    gates_missing_alignment_hard_block.append(code)

    unused = canonical - all_candidate_fields

    # Top fields with closest-name candidates in canonical (Levenshtein-ish via
    # simple substring overlap) — útil para sugerencias de renaming.
    return {
        "gates_count": len(gates),
        "canonical_count": len(canonical),
        "candidate_field_count": len(all_candidate_fields),
        "gates_with_orphan_groups": {
            code: [sorted(g) for g in groups]
            for code, groups in gates_with_orphan_groups.items()
        },
        "gates_with_orphan_groups_count": len(gates_with_orphan_groups),
        "severity_with_orphans": dict(severity_with_orphans),
        "unused_fields_count": len(unused),
        "unused_fields_sample": sorted(list(unused))[:50],
        "severity_distribution": dict(severity_counter),
        "trigger_type_distribution": dict(trigger_type_counter),
        "gates_missing_evidence": sorted(gates_missing_evidence),
        "gates_missing_trial_refs": sorted(gates_missing_trial_refs),
        "gates_missing_alignment_hard_block": sorted(gates_missing_alignment_hard_block),
        "gates_short_message": sorted(gates_short_message, key=lambda x: x[1]),
        "canonical_by_schema": {k: sorted(v) for k, v in sorted(by_schema.items())},
    }


def _render_markdown(audit: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# EPIC 10B — Gate Field Coverage Audit Report")
    lines.append("")
    lines.append("> Generado por `scripts/epic10b_audit_gate_coverage.py`.  ")
    lines.append("> Audita la integridad del contrato entre los gates YAML "
                 "(`prostanet/shared/pivotal_gates_catalog/`) y los FieldSpecs "
                 "canónicos declarados en los 17 SCHEMAS del CDE Auditable.")
    lines.append("")
    lines.append("## Resumen ejecutivo")
    lines.append("")
    lines.append(f"- **Gates YAML cargados (dedup por code):** {audit['gates_count']}")
    lines.append(f"- **FieldSpecs canónicos (unión 17 SCHEMAS):** {audit['canonical_count']}")
    lines.append(f"- **Fields candidatos referenciados (cualquier alias):** {audit['candidate_field_count']}")
    lines.append(f"- **Gates con ≥1 trigger group huérfano:** {audit['gates_with_orphan_groups_count']}")
    lines.append(f"- **FieldSpecs sin uso (legacy/info):** {audit['unused_fields_count']}")
    lines.append("")
    lines.append("> **Semántica del audit (correcta):** un trigger group "
                 "es huérfano si NINGUNO de sus candidate fields "
                 "(`field` + `alias_fields`) existe en algún schema canónico. "
                 "El loader dispara el trigger si payload contiene cualquiera "
                 "del conjunto — por eso basta con UNO presente para ser "
                 "ejecutable. Esta métrica es la única clínicamente correcta.")
    lines.append("")
    lines.append("### Distribución por severity")
    lines.append("")
    for sev, count in sorted(audit["severity_distribution"].items()):
        orphans = audit["severity_with_orphans"].get(sev, 0)
        lines.append(f"- `{sev}`: {count} gates ({orphans} con grupos huérfanos)")
    lines.append("")
    lines.append("### Distribución por trigger type")
    lines.append("")
    for t, count in sorted(audit["trigger_type_distribution"].items()):
        lines.append(f"- `{t}`: {count}")
    lines.append("")
    lines.append("## Gates con grupos huérfanos (blockers clínicos silenciosos)")
    lines.append("")
    lines.append("Un gate con grupo huérfano tiene al menos un trigger que "
                 "**nunca puede disparar** porque ninguno de sus candidate "
                 "fields existe como FieldSpec capturable. Esto significa "
                 "que el motor parece evaluar el gate pero la contraindicación "
                 "jamás se aplica con datos reales. **Cada uno es un riesgo "
                 "clínico real.**")
    lines.append("")
    if not audit["gates_with_orphan_groups"]:
        lines.append("✅ **Ningún gate tiene grupos huérfanos.** Contract integrity 100%.")
    else:
        lines.append("| Gate code | Severity | Grupos huérfanos (candidate sets) |")
        lines.append("|---|---|---|")
        gates_dict = _load_gates()
        for code, groups in sorted(audit["gates_with_orphan_groups"].items()):
            sev = gates_dict.get(code, {}).get("severity", "?")
            groups_str = "; ".join("{" + ", ".join(f"`{f}`" for f in g) + "}" for g in groups)
            lines.append(f"| `{code}` | `{sev}` | {groups_str} |")
    lines.append("")
    lines.append("## Auditoría de metadatos regulatorios")
    lines.append("")
    lines.append(f"### Gates sin `evidence_tag`: {len(audit['gates_missing_evidence'])}")
    for code in audit["gates_missing_evidence"][:30]:
        lines.append(f"- `{code}`")
    if len(audit["gates_missing_evidence"]) > 30:
        lines.append(f"- ... ({len(audit['gates_missing_evidence']) - 30} más)")
    lines.append("")
    lines.append(f"### Gates sin `trial_refs`: {len(audit['gates_missing_trial_refs'])}")
    for code in audit["gates_missing_trial_refs"][:30]:
        lines.append(f"- `{code}`")
    if len(audit["gates_missing_trial_refs"]) > 30:
        lines.append(f"- ... ({len(audit['gates_missing_trial_refs']) - 30} más)")
    lines.append("")
    lines.append(f"### Hard-blocks sin `nccn_eau_alignment` ni FDA-label fallback: {len(audit['gates_missing_alignment_hard_block'])}")
    for code in audit["gates_missing_alignment_hard_block"][:30]:
        lines.append(f"- `{code}`")
    if len(audit["gates_missing_alignment_hard_block"]) > 30:
        lines.append(f"- ... ({len(audit['gates_missing_alignment_hard_block']) - 30} más)")
    lines.append("")
    lines.append(f"### Gates con `message` < 40 chars: {len(audit['gates_short_message'])}")
    for code, length in audit["gates_short_message"][:20]:
        lines.append(f"- `{code}`: {length} chars")
    lines.append("")
    lines.append("## FieldSpecs sin uso (muestra primeros 50)")
    lines.append("")
    lines.append("Fields declarados en algún SCHEMA pero **ninguno de los "
                 f"{audit['gates_count']} gates los referencia**. Pueden ser "
                 "(a) inputs canónicos para algoritmos sin gate (legítimos), "
                 "(b) campos legacy candidatos a remover, (c) campos que "
                 "deberían tener gate pero no se modeló.")
    lines.append("")
    for fld in audit["unused_fields_sample"]:
        lines.append(f"- `{fld}`")
    if audit["unused_fields_count"] > 50:
        lines.append(f"- ... ({audit['unused_fields_count'] - 50} más)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Próximos pasos sugeridos")
    lines.append("")
    if audit["gates_with_orphan_groups_count"]:
        lines.append("1. **Priorizar fix por severity:** los gates `hard_block` "
                     "con grupos huérfanos son los más críticos (su fallo silencioso permite "
                     "que regímenes contraindicados pasen sin alerta).")
        lines.append("2. **Reconciliar naming entre gates y schemas:** muchos huérfanos "
                     "suelen ser variantes de naming (e.g. `psa_doubling_time` vs "
                     "`psa_doubling_time_months`, o `edad` vs `patient_age`).")
        lines.append("3. **Añadir un alias** al gate o al schema para resolver el match — "
                     "típicamente más barato que crear FieldSpec nuevo.")
        lines.append("4. **Re-correr este audit** después de cada batch: target = 0 grupos "
                     "huérfanos antes de FDA Pre-Sub.")
    else:
        lines.append("✅ **Contract integrity 100%.** Avanzar a EPIC 10C "
                     "(performance + WCAG accessibility baseline).")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="EPIC 10B audit")
    parser.add_argument(
        "--output",
        default="output/epic10/gate_field_coverage_report.md",
        help="Path to write the Markdown report (relative to repo root).",
    )
    parser.add_argument(
        "--print-summary",
        action="store_true",
        help="Print summary stats to stdout.",
    )
    args = parser.parse_args()

    audit = _audit()
    md = _render_markdown(audit)

    out_path = REPO_ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")

    print(f"EPIC 10B report → {out_path}")
    print(
        f"Summary: {audit['gates_count']} gates, "
        f"{audit['canonical_count']} canonical fields, "
        f"{audit['candidate_field_count']} candidate fields referenced, "
        f"{audit['gates_with_orphan_groups_count']} gates with orphan group(s), "
        f"{audit['unused_fields_count']} unused fields."
    )
    if args.print_summary and audit["gates_with_orphan_groups"]:
        print("\nGates with orphan groups (by severity):")
        gates = _load_gates()
        from collections import defaultdict as _dd
        by_sev = _dd(list)
        for code in audit["gates_with_orphan_groups"]:
            sev = gates.get(code, {}).get("severity", "?")
            by_sev[sev].append(code)
        for sev in ("hard_block", "soft_warning", "informational", "?"):
            codes = by_sev.get(sev, [])
            if codes:
                print(f"  {sev}: {len(codes)} gates")
                for code in codes[:5]:
                    print(f"    - {code}")
                if len(codes) > 5:
                    print(f"    ... ({len(codes) - 5} more)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
