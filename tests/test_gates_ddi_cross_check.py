"""tests/test_gates_ddi_cross_check.py — FAUBOT 2026-04-25 (XV).

Cobertura del cross-check entre gates pivotal y DDI engine.

Aporte de esta suite:
  - Verifica el helper `cross_check_gates_with_ddi` con casos pivotal por
    cada categoría DDI relevante.
  - Verifica la integración bidireccional con
    `apply_pivotal_contraindication_gates` (cross alerts añadidos al
    `not_recommended_messages`).
  - Verifica el catálogo de mappings (`get_gate_ddi_mapping_summary`)
    para que cualquier gate nuevo se documente formalmente.

Hipótesis cubiertas: H.G179 - H.G203 (25 tests dedicadas).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.shared.gates_ddi_cross_check import (
    cross_check_gates_with_ddi,
    cross_messages_for_not_recommended,
    get_gate_ddi_mapping_summary,
    _GATE_TO_RELATED_DDI_CATEGORIES,
    _GATE_TO_ONCOLOGY_DRUGS,
    _GATE_SUMMARIES,
)
from prostanet.shared.pivotal_contraindication_gates import (
    apply_pivotal_contraindication_gates,
    evaluate_pivotal_contraindication_gates,
)


# ── Fixtures comunes ────────────────────────────────────────────────────


@pytest.fixture
def gate_qtc_triggered():
    return {"code": "qtc_prolongation_grade3_for_enzalutamide", "triggered": True,
            "severity": "contraindicated"}


@pytest.fixture
def gate_lvef_triggered():
    return {"code": "lvef_decline_for_apalutamide", "triggered": True,
            "severity": "contraindicated"}


@pytest.fixture
def gate_cognitive_triggered():
    return {"code": "arsi_in_cognitive_decline_grade2", "triggered": True,
            "severity": "contraindicated"}


@pytest.fixture
def gate_hta_triggered():
    return {"code": "uncontrolled_hypertension", "triggered": True,
            "severity": "contraindicated"}


@pytest.fixture
def gate_unknown():
    return {"code": "no_existe_este_gate", "triggered": True,
            "severity": "contraindicated"}


# ──────────────────────────────────────────────────────────────────────
# H.G179 — Sin gates → sin cross alerts.
# ──────────────────────────────────────────────────────────────────────


def test_no_gates_returns_empty_list():
    """H.G179 — Sin gates triggered → cross_alerts vacía."""
    payload = {"current_medications": "metadona, ondansetrón"}
    out = cross_check_gates_with_ddi([], payload)
    assert out == []


def test_none_gates_returns_empty_list():
    """H.G179.b — gates_triggered=None → cross_alerts vacía."""
    payload = {"current_medications": "metadona"}
    out = cross_check_gates_with_ddi(None, payload)
    assert out == []


# ──────────────────────────────────────────────────────────────────────
# H.G180 — Sin medicaciones → sin cross alerts.
# ──────────────────────────────────────────────────────────────────────


def test_no_medications_returns_empty(gate_qtc_triggered):
    """H.G180 — Sin medicaciones concomitantes → 0 cross alerts."""
    out = cross_check_gates_with_ddi([gate_qtc_triggered], {})
    assert out == []


def test_empty_medications_string(gate_qtc_triggered):
    """H.G180.b — current_medications="" → 0 cross alerts."""
    out = cross_check_gates_with_ddi(
        [gate_qtc_triggered],
        {"current_medications": ""},
    )
    assert out == []


# ──────────────────────────────────────────────────────────────────────
# H.G181 — Gate desconocido → ignorado (sin error).
# ──────────────────────────────────────────────────────────────────────


def test_unknown_gate_code_is_ignored(gate_unknown):
    """H.G181 — Gate code sin mapping → ignorado, no crash."""
    out = cross_check_gates_with_ddi(
        [gate_unknown],
        {"current_medications": "metadona, ondansetrón"},
    )
    assert out == []


# ──────────────────────────────────────────────────────────────────────
# H.G182 — Gate 17 QTc + metadona → cross alert qtc_prolongation.
# ──────────────────────────────────────────────────────────────────────


def test_gate_qtc_with_methadone_triggers_cross(gate_qtc_triggered):
    """H.G182 — Gate 17 + metadona concomitante → cross alert."""
    out = cross_check_gates_with_ddi(
        [gate_qtc_triggered],
        {"current_medications": "metadona, omeprazol"},
    )
    assert len(out) == 1
    assert out[0]["gate_code"] == "qtc_prolongation_grade3_for_enzalutamide"
    assert out[0]["category"] == "qtc_prolongation"
    assert out[0]["severity"] == "major"
    assert "metadona" in out[0]["cross_message"].lower()
    assert "Gate 17" in out[0]["cross_message"]


def test_gate_qtc_with_ondansetron_triggers_cross(gate_qtc_triggered):
    """H.G182.b — Gate 17 + ondansetrón → cross alert moderate."""
    out = cross_check_gates_with_ddi(
        [gate_qtc_triggered],
        {"current_medications": "ondansetrón"},
    )
    assert len(out) == 1
    assert out[0]["category"] == "qtc_prolongation"
    assert out[0]["severity"] == "moderate"


def test_gate_qtc_with_moxifloxacin_triggers_cross(gate_qtc_triggered):
    """H.G182.c — Gate 17 + moxifloxacino → cross qtc."""
    out = cross_check_gates_with_ddi(
        [gate_qtc_triggered],
        {"current_medications": "moxifloxacino"},
    )
    assert len(out) >= 1
    assert any(a["category"] == "qtc_prolongation" for a in out)


# ──────────────────────────────────────────────────────────────────────
# H.G183 — Gate 17 sin medicaciones DDI relevantes → no cross.
# ──────────────────────────────────────────────────────────────────────


def test_gate_qtc_with_unrelated_med_no_cross(gate_qtc_triggered):
    """H.G183 — Gate 17 + paracetamol (sin DDI QTc) → 0 cross."""
    out = cross_check_gates_with_ddi(
        [gate_qtc_triggered],
        {"current_medications": "paracetamol, vitamina_d"},
    )
    assert out == []


# ──────────────────────────────────────────────────────────────────────
# H.G184 — Gate 19 + bupropion → cross seizure_threshold.
# ──────────────────────────────────────────────────────────────────────


def test_gate_cognitive_with_bupropion_triggers_seizure_cross(gate_cognitive_triggered):
    """H.G184 — Gate 19 (cognitive) + bupropion → cross seizure."""
    out = cross_check_gates_with_ddi(
        [gate_cognitive_triggered],
        {"current_medications": "bupropion"},
    )
    seizure_alerts = [a for a in out if a["category"] == "seizure_threshold"]
    assert len(seizure_alerts) >= 1
    assert any("bupropion" in a["cross_message"].lower() for a in seizure_alerts)


def test_gate_cognitive_forces_seizure_history(gate_cognitive_triggered):
    """H.G184.b — Gate 19 fuerza seizure_history=True → activa reglas
    extras (Historia de convulsiones + ARSI)."""
    out = cross_check_gates_with_ddi(
        [gate_cognitive_triggered],
        {"current_medications": "bupropion"},
    )
    # Debe haber alertas con drug_b="Historia de convulsiones" porque
    # forzamos seizure_history=True para el gate 19.
    history_alerts = [
        a for a in out
        if "convulsiones" in str(a.get("ddi_alert", {}).get("drug_b") or "").lower()
    ]
    assert len(history_alerts) >= 1


# ──────────────────────────────────────────────────────────────────────
# H.G185 — Gate 3 HTA + espironolactona → cross aldosterone.
# ──────────────────────────────────────────────────────────────────────


def test_gate_hta_with_spironolactone_triggers_aldosterone_cross(gate_hta_triggered):
    """H.G185 — Gate 3 (HTA) + espironolactona → cross
    pharmacodynamic_aldosterone (contraindicated)."""
    out = cross_check_gates_with_ddi(
        [gate_hta_triggered],
        {"current_medications": "espironolactona"},
    )
    assert len(out) == 1
    assert out[0]["category"] == "pharmacodynamic_aldosterone"
    assert out[0]["severity"] == "contraindicated"
    assert "espironolactona" in out[0]["cross_message"].lower()


# ──────────────────────────────────────────────────────────────────────
# H.G186 — Múltiples gates → múltiples cross alerts (deduplicados).
# ──────────────────────────────────────────────────────────────────────


def test_multiple_gates_with_meds_aggregates_cross(
    gate_qtc_triggered, gate_lvef_triggered,
):
    """H.G186 — Gates 17+18 + meds → cross alerts agregados."""
    out = cross_check_gates_with_ddi(
        [gate_qtc_triggered, gate_lvef_triggered],
        {"current_medications": "metadona, ondansetrón"},
    )
    # Gate 17 (enzalutamida + metadona/ondansetrón) genera 2 cross.
    # Gate 18 (apalutamida) no tiene reglas QTc en DDIEngine → 0.
    qtc_alerts = [a for a in out if a["gate_code"] == "qtc_prolongation_grade3_for_enzalutamide"]
    assert len(qtc_alerts) == 2


def test_dedup_same_gate_same_drug_pair(gate_qtc_triggered):
    """H.G186.b — Gate disparado 2 veces con misma med → 1 cross alert."""
    out = cross_check_gates_with_ddi(
        [gate_qtc_triggered, gate_qtc_triggered],  # mismo gate duplicado
        {"current_medications": "metadona"},
    )
    assert len(out) == 1


# ──────────────────────────────────────────────────────────────────────
# H.G187 — Estructura de retorno completa.
# ──────────────────────────────────────────────────────────────────────


def test_cross_alert_has_required_fields(gate_qtc_triggered):
    """H.G187 — Cada cross alert tiene los 5 campos requeridos."""
    out = cross_check_gates_with_ddi(
        [gate_qtc_triggered],
        {"current_medications": "metadona"},
    )
    assert len(out) == 1
    alert = out[0]
    for field in ("gate_code", "severity", "category", "cross_message", "ddi_alert"):
        assert field in alert, f"Campo {field} ausente"
    # ddi_alert tiene los campos de DDIAlert serializada.
    for ddi_field in ("drug_a", "drug_b", "mechanism", "clinical_impact",
                      "recommended_action", "reference"):
        assert ddi_field in alert["ddi_alert"]


def test_cross_message_includes_gate_summary(gate_qtc_triggered):
    """H.G187.b — cross_message comienza con el resumen del gate."""
    out = cross_check_gates_with_ddi(
        [gate_qtc_triggered],
        {"current_medications": "metadona"},
    )
    assert out[0]["cross_message"].startswith("Gate 17")


# ──────────────────────────────────────────────────────────────────────
# H.G188 — cross_messages_for_not_recommended sin duplicados.
# ──────────────────────────────────────────────────────────────────────


def test_cross_messages_extractor_dedupes(gate_qtc_triggered):
    """H.G188 — Helper extractor remueve mensajes duplicados."""
    out = cross_check_gates_with_ddi(
        [gate_qtc_triggered],
        {"current_medications": "metadona, ondansetrón"},
    )
    # Forzar duplicado artificial
    out_dup = out + out
    msgs = cross_messages_for_not_recommended(out_dup)
    assert len(msgs) == len(set(msgs))


def test_cross_messages_extractor_empty_input():
    """H.G188.b — Input vacío → lista vacía."""
    assert cross_messages_for_not_recommended([]) == []
    assert cross_messages_for_not_recommended(None) == []


# ──────────────────────────────────────────────────────────────────────
# H.G189 — Integración bidireccional: apply_pivotal_contraindication_gates
# ──────────────────────────────────────────────────────────────────────


def test_apply_pivotal_returns_ddi_cross_alerts_field():
    """H.G189 — apply_pivotal_contraindication_gates expone
    ddi_cross_alerts en el bundle."""
    result = apply_pivotal_contraindication_gates(
        {"qtc_ms": 520, "current_medications": "metadona"},
        treatments=[],
    )
    assert "ddi_cross_alerts" in result
    assert isinstance(result["ddi_cross_alerts"], list)
    assert len(result["ddi_cross_alerts"]) >= 1


def test_apply_pivotal_appends_cross_messages_to_not_recommended():
    """H.G190 — Los cross messages se anexan a not_recommended."""
    result = apply_pivotal_contraindication_gates(
        {"qtc_ms": 520, "current_medications": "metadona"},
        treatments=[],
    )
    msgs = result["not_recommended_messages"]
    # Debe haber el mensaje base del gate + el mensaje cruzado
    assert len(msgs) >= 2
    assert any("Gate 17" in m and "Metadona" in m for m in msgs)


def test_apply_pivotal_preserves_base_messages_when_no_meds():
    """H.G191 — Sin medicaciones, messages = base only (no extras)."""
    result = apply_pivotal_contraindication_gates(
        {"qtc_ms": 520},
        treatments=[],
    )
    assert result["ddi_cross_alerts"] == []
    msgs = result["not_recommended_messages"]
    assert len(msgs) == 1
    assert all(not m.startswith("Gate 17 (QTc grado 3") or "concomitante" not in m
               for m in msgs)


def test_apply_pivotal_no_gates_no_cross():
    """H.G191.b — Healthy payload → no gates, no cross."""
    result = apply_pivotal_contraindication_gates(
        {"qtc_ms": 400, "lvef_percent": 65,
         "current_medications": "metadona"},
        treatments=[],
    )
    assert result["gates_triggered"] == []
    assert result["ddi_cross_alerts"] == []
    assert result["not_recommended_messages"] == []


def test_apply_pivotal_filters_treatments_unaffected_by_cross():
    """H.G192 — El cross-check NO filtra treatments adicionales (solo
    enriquece messages); el filtrado lo hace filter_treatments_by_gates."""
    treatments = [
        {"name": "Enzalutamida", "regimen_code": "ADT_ENZALUTAMIDE"},
        {"name": "Docetaxel", "regimen_code": "ADT_DOCETAXEL"},
    ]
    result = apply_pivotal_contraindication_gates(
        {"qtc_ms": 520, "current_medications": "metadona"},
        treatments,
    )
    # Enzalutamida bloqueada por gate 17; docetaxel no
    filtered_codes = {t["regimen_code"] for t in result["filtered_treatments"]}
    assert "ADT_ENZALUTAMIDE" not in filtered_codes
    assert "ADT_DOCETAXEL" in filtered_codes


# ──────────────────────────────────────────────────────────────────────
# H.G193 — Catálogo de mappings exposed para auditoría
# ──────────────────────────────────────────────────────────────────────


def test_get_gate_ddi_mapping_summary_structure():
    """H.G193 — get_gate_ddi_mapping_summary retorna estructura completa."""
    summary = get_gate_ddi_mapping_summary()
    assert "total_gates_with_ddi_crosscheck" in summary
    assert "mappings" in summary
    assert summary["total_gates_with_ddi_crosscheck"] >= 12


def test_mapping_summary_each_gate_has_categories_and_drugs():
    """H.G193.b — Cada entrada tiene categories + oncology_drugs + summary."""
    summary = get_gate_ddi_mapping_summary()
    for code, entry in summary["mappings"].items():
        assert "categories" in entry, f"{code} sin categories"
        assert "oncology_drugs" in entry, f"{code} sin oncology_drugs"
        assert "summary" in entry, f"{code} sin summary"


def test_all_gate_codes_have_summary():
    """H.G194 — Todos los gates en _GATE_TO_RELATED_DDI_CATEGORIES tienen
    entrada en _GATE_SUMMARIES (rastro humano para UI/clínico)."""
    for code in _GATE_TO_RELATED_DDI_CATEGORIES:
        assert code in _GATE_SUMMARIES, (
            f"Gate {code} sin summary humano definido"
        )


def test_all_gate_codes_have_oncology_drugs():
    """H.G194.b — Todos los gates con DDI cross tienen oncology_drugs no vacío
    (o categories vacías que indican opt-out)."""
    for code, cats in _GATE_TO_RELATED_DDI_CATEGORIES.items():
        if not cats:
            continue  # opt-out explícito
        drugs = _GATE_TO_ONCOLOGY_DRUGS.get(code, [])
        assert drugs, f"Gate {code} con categorías {cats} pero sin oncology_drugs"


# ──────────────────────────────────────────────────────────────────────
# H.G195 — Robustez: alias del campo medications.
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("med_field", [
    "current_medications",
    "concomitant_medications",
    "medications",
])
def test_payload_medication_field_aliases(gate_qtc_triggered, med_field):
    """H.G195 — Helper acepta 3 aliases para el campo medications."""
    out = cross_check_gates_with_ddi(
        [gate_qtc_triggered],
        {med_field: "metadona"},
    )
    assert len(out) == 1


def test_medication_list_format_accepted(gate_qtc_triggered):
    """H.G196 — Helper acepta lista (además de string)."""
    out = cross_check_gates_with_ddi(
        [gate_qtc_triggered],
        {"current_medications": ["metadona", "omeprazol"]},
    )
    assert len(out) == 1


# ──────────────────────────────────────────────────────────────────────
# H.G197 — Categorías filtran correctamente (no contamina con DDIs
# ajenas a la categoría del gate).
# ──────────────────────────────────────────────────────────────────────


def test_qtc_gate_filters_out_non_qtc_ddis(gate_qtc_triggered):
    """H.G197 — Gate 17 (qtc_prolongation) NO incluye DDIs de otras
    categorías aunque las haya con enzalutamida (ej. CYP3A4 con apixaban).
    """
    out = cross_check_gates_with_ddi(
        [gate_qtc_triggered],
        {"current_medications": "apixaban, atorvastatina"},
    )
    # apixaban+enzalutamida = cyp3a4_induction (NO qtc) → no debe aparecer
    assert all(a["category"] == "qtc_prolongation" for a in out)


# ──────────────────────────────────────────────────────────────────────
# H.G198 — Gate 4 (NYHA III-IV) cruza con qtc + aldosterone.
# ──────────────────────────────────────────────────────────────────────


def test_gate_nyha_iii_iv_cross_with_metadona_and_spironolactone():
    """H.G198 — Gate 4 (NYHA III-IV) tiene 2 categorías mapeadas
    (qtc_prolongation + pharmacodynamic_aldosterone)."""
    gate = {"code": "severe_heart_failure_nyha_iii_iv", "triggered": True,
            "severity": "contraindicated"}
    out = cross_check_gates_with_ddi(
        [gate],
        {"current_medications": "metadona, espironolactona"},
    )
    categories = {a["category"] for a in out}
    # Esperamos al menos qtc_prolongation (abiraterona+metadona)
    # y pharmacodynamic_aldosterone (abiraterona+espironolactona)
    assert "qtc_prolongation" in categories
    assert "pharmacodynamic_aldosterone" in categories


# ──────────────────────────────────────────────────────────────────────
# H.G199 — End-to-end con evaluate_pivotal_contraindication_gates.
# ──────────────────────────────────────────────────────────────────────


def test_e2e_evaluate_then_cross_check():
    """H.G199 — Pipeline completo: evaluate → cross_check funciona sin
    perder información."""
    payload = {
        "qtc_ms": 520,
        "uncontrolled_hypertension": "Sí",
        "current_medications": "metadona, espironolactona",
    }
    gates = evaluate_pivotal_contraindication_gates(payload)
    assert len(gates) >= 2
    cross = cross_check_gates_with_ddi(gates, payload)
    # Debe haber al menos 2 cross alerts (uno por gate)
    assert len(cross) >= 2
    gate_codes_with_cross = {a["gate_code"] for a in cross}
    assert "qtc_prolongation_grade3_for_enzalutamide" in gate_codes_with_cross
    assert "uncontrolled_hypertension" in gate_codes_with_cross


# ──────────────────────────────────────────────────────────────────────
# H.G200 — Backward-compat: bundle bundle["ddi_cross_alerts"] siempre
# presente (incluso vacío) para callers que dependan de él.
# ──────────────────────────────────────────────────────────────────────


def test_apply_pivotal_always_includes_ddi_cross_alerts_key():
    """H.G200 — `ddi_cross_alerts` siempre está en el bundle."""
    # Sin gates
    r1 = apply_pivotal_contraindication_gates({}, treatments=[])
    assert "ddi_cross_alerts" in r1
    assert r1["ddi_cross_alerts"] == []
    # Con gate sin meds
    r2 = apply_pivotal_contraindication_gates(
        {"qtc_ms": 520}, treatments=[],
    )
    assert "ddi_cross_alerts" in r2
    assert r2["ddi_cross_alerts"] == []
    # Con gate + meds
    r3 = apply_pivotal_contraindication_gates(
        {"qtc_ms": 520, "current_medications": "metadona"}, treatments=[],
    )
    assert "ddi_cross_alerts" in r3
    assert len(r3["ddi_cross_alerts"]) >= 1


# ──────────────────────────────────────────────────────────────────────
# H.G201 — seizure_history=True externamente activa cascade en
# gate ARSI.
# ──────────────────────────────────────────────────────────────────────


def test_external_seizure_history_amplifies_gate_19(gate_cognitive_triggered):
    """H.G201 — Si payload trae seizure_history=Sí, gate 19 captura el
    triple riesgo (ARSI + tramadol + seizure history)."""
    out = cross_check_gates_with_ddi(
        [gate_cognitive_triggered],
        {
            "current_medications": "tramadol",
            "seizure_history": "Sí",
        },
    )
    triple = [
        a for a in out
        if "tramadol" in str(a.get("ddi_alert", {}).get("drug_a") or "").lower()
        or "tramadol" in str(a.get("cross_message") or "").lower()
    ]
    assert len(triple) >= 1


# ──────────────────────────────────────────────────────────────────────
# H.G202 — Catálogo coherente con detectores Python actuales.
# ──────────────────────────────────────────────────────────────────────


def test_mapping_codes_are_subset_of_known_gate_codes():
    """H.G202 — Todos los codes del mapping deben ser gates conocidos
    (Python detectors o YAML loader).

    Faubot 2026-04-25 (XVIII) — Tras la migración de gates 11-15 a YAML,
    este test ahora consume `algorithm_version.get_active_gate_codes()`
    que combina Python+YAML para garantizar que el universo de gates
    conocidos refleje el sistema híbrido completo (no solo Python)."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    all_known = set(get_active_gate_codes())
    # Renombre histórico: detect_no_bone_protective_agent_for_radium223
    # produce code "no_bone_protective_agent" (no termina en _for_radium223).
    # detect_creatinine_clearance_lt_30_for_rucaparib produce code
    # "creatinine_clearance_lt_30". Permitimos ambas variantes.
    aliases = {
        "no_bone_protective_agent_for_radium223": "no_bone_protective_agent",
        "creatinine_clearance_lt_30_for_rucaparib": "creatinine_clearance_lt_30",
    }
    all_known |= set(aliases.values())

    for code in _GATE_TO_RELATED_DDI_CATEGORIES:
        assert code in all_known, (
            f"Mapping incluye gate {code} desconocido (no es detector Python "
            f"ni YAML loaded)"
        )


# ──────────────────────────────────────────────────────────────────────
# H.G203 — Filosofía: cross-check es OPT-IN; gates sin mapping NO
# generan cross alerts (no falsos positivos).
# ──────────────────────────────────────────────────────────────────────


def test_gate_without_mapping_silently_ignored():
    """H.G203 — Gate sin mapping no produce error ni cross alert."""
    # Inventar un gate ficticio que no está en el mapping.
    out = cross_check_gates_with_ddi(
        [{"code": "future_gate_42", "triggered": True}],
        {"current_medications": "metadona, ondansetrón"},
    )
    assert out == []


# ──────────────────────────────────────────────────────────────────────
# H.G204 — Fix R8 (Faubot 2026-04-25): Paridad ES-médica entre
# `_is_truthy` del cross-check y `_truthy_token` canónico de los
# detectores Python. Antes el módulo tenía un set local con 7 tokens;
# le faltaban "positivo", "documented", "documentado" — causando
# inconsistencia silenciosa: `seizure_history="documentado"` activaba
# detectores Python pero NO el cross-check DDI.
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("token", [
    "1", "true", "yes", "si", "sí",
    "present", "positive", "positivo",
    "documented", "documentado",
])
def test_is_truthy_recognizes_full_es_medica_canonical_set(token):
    """H.G204 — _is_truthy reconoce los 9+ tokens canónicos ES-médica
    del set `_TRUTHY` definido en `pivotal_contraindication_gates.py`."""
    from prostanet.shared.gates_ddi_cross_check import _is_truthy
    assert _is_truthy(token) is True, (
        f"Token canónico {token!r} no reconocido — "
        "rompe paridad ES-médica con detectores Python (regresión Fix R8)"
    )


def test_is_truthy_is_imported_from_canonical_source():
    """H.G204.b — _is_truthy debe ser importado desde
    `pivotal_contraindication_gates._truthy_token` (no definido localmente).
    Garantiza que cualquier futura extensión del set canónico se propaga
    automáticamente al cross-check."""
    from prostanet.shared.gates_ddi_cross_check import _is_truthy
    from prostanet.shared.pivotal_contraindication_gates import _truthy_token
    assert _is_truthy is _truthy_token, (
        "_is_truthy debe ser alias de _truthy_token canónico — "
        "si tienes implementación local, restaura el import (Fix R8)"
    )


@pytest.mark.parametrize("falsy_input", [
    "", "0", "false", "no", "ninguno", "n/a", None, 0, False,
])
def test_is_truthy_rejects_falsy_consistently(falsy_input):
    """H.G204.c — Falsy se mantiene falsy tras Fix R8."""
    from prostanet.shared.gates_ddi_cross_check import _is_truthy
    assert _is_truthy(falsy_input) is False, (
        f"Valor falsy {falsy_input!r} mal clasificado como truthy"
    )
