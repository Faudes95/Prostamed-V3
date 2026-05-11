"""Tests de los gates pivotal 11-12: Ra-223 × emergencias oncológicas.

Faubot 2026-04-24 (IV) — Cierra los 2 gaps clínicos identificados en la
auditoría 2026-04-24 (III):

  Gate 11 — `radium223_in_cord_compression`
    Compresión medular activa o sospechada → Ra-223 contraindicado hasta
    estabilización con dexametasona + RT 30 Gy/10 fx (Loblaw ASCO 2012)
    o cirugía descompresiva (criterios Patchell).
    Evidencia: Xofigo Bayer 2024 prescribing information; ALSYMPCA
    (Parker NEJM 2013); Loblaw ASCO 2012; NCCN Oncologic Emergencies
    v3.2026.

  Gate 12 — `radium223_in_hypocalcemia`
    Hipocalcemia no corregida (Ca total <8.5 mg/dL o iónico <4.5 mg/dL)
    → Ra-223 contraindicado por riesgo de tetania/arritmia/paro
    cardíaco. Pacientes en denosumab/zoledronato concomitante (PEACE-3)
    tienen riesgo basal elevado.
    Evidencia: Xofigo FDA prescribing information; ALSYMPCA.

Cobertura del test:
  A) Detectores aislados — positivo + negativo + override + alias
  B) Filtro de tratamientos — Ra-223 removido cuando aplica
  C) End-to-end vía m1_crpc service — rastro estructurado expuesto
  D) Backward compatibility — pacientes sanos, gates ya existentes intactos
  E) Schema coverage — total ahora 12 gates en `_DETECTORS`
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.application.module_registry import ModuleRegistry
from prostanet.shared.pivotal_contraindication_gates import (
    REGIMEN_CODES_RADIUM223,
    _DETECTORS,
    apply_pivotal_contraindication_gates,
    detect_radium223_in_cord_compression,
    detect_radium223_in_hypocalcemia,
    evaluate_pivotal_contraindication_gates,
    filter_treatments_by_gates,
)


# ── Sección A — Detectores individuales ───────────────────────────────────


class TestRadium223InCordCompressionDetector:
    """Gate 11 — `radium223_in_cord_compression`."""

    def test_explicit_spinal_cord_compression_triggers_gate(self):
        gate = detect_radium223_in_cord_compression({"spinal_cord_compression": "Sí"})
        assert gate is not None
        assert gate["code"] == "radium223_in_cord_compression"
        assert gate["severity"] == "hard_block"
        assert gate["affected_regimen_codes"] == REGIMEN_CODES_RADIUM223
        assert "ALSYMPCA" in gate["trial_refs"]
        assert "Xofigo label" in gate["trial_refs"]

    def test_epidural_compression_alias_triggers_gate(self):
        gate = detect_radium223_in_cord_compression({"epidural_compression": "1"})
        assert gate is not None
        assert gate["code"] == "radium223_in_cord_compression"

    @pytest.mark.parametrize(
        "weakness",
        ["Sí — moderada", "Sí — severa/paresia", "Sí — paresia"],
    )
    def test_severe_weakness_triggers_gate(self, weakness):
        gate = detect_radium223_in_cord_compression({"lower_limb_weakness": weakness})
        assert gate is not None
        assert gate["code"] == "radium223_in_cord_compression"

    def test_mild_weakness_does_not_trigger_gate(self):
        gate = detect_radium223_in_cord_compression({"lower_limb_weakness": "Sí — leve"})
        assert gate is None

    @pytest.mark.parametrize(
        "symptoms",
        [
            "Debilidad MMII",
            "Anestesia en silla de montar",
            "Retención urinaria nueva",
            "Incontinencia fecal",
        ],
    )
    def test_neurologic_symptoms_trigger_gate(self, symptoms):
        gate = detect_radium223_in_cord_compression(
            {"cord_compression_symptoms": symptoms}
        )
        assert gate is not None
        assert gate["code"] == "radium223_in_cord_compression"

    def test_dolor_dorsolumbar_alone_does_not_trigger_gate(self):
        """Dolor dorsolumbar es síntoma sugerente pero no específico — no
        dispara el gate por sí solo. Necesita debilidad/anestesia/retención."""
        gate = detect_radium223_in_cord_compression(
            {"cord_compression_symptoms": "Dolor dorso-lumbar progresivo"}
        )
        assert gate is None

    def test_stabilized_override_neutralizes_gate(self):
        """`cord_compression_stabilized=Sí` desactiva el gate (paciente
        post-RT/cirugía con estabilidad estructural confirmada)."""
        gate = detect_radium223_in_cord_compression(
            {
                "spinal_cord_compression": "Sí",
                "lower_limb_weakness": "Sí — severa/paresia",
                "cord_compression_stabilized": "Sí",
            }
        )
        assert gate is None

    def test_healthy_payload_does_not_trigger_gate(self):
        """Paciente sin señales de cord compression."""
        gate = detect_radium223_in_cord_compression(
            {
                "spinal_cord_compression": "No",
                "lower_limb_weakness": "No",
                "cord_compression_symptoms": "Ninguno",
            }
        )
        assert gate is None

    def test_message_includes_management_protocol(self):
        gate = detect_radium223_in_cord_compression({"spinal_cord_compression": "Sí"})
        msg = gate["message"].lower()
        assert "dexametasona" in msg or "rt" in msg
        assert "patchell" in msg or "descompresiva" in msg
        assert "stabiliz" in msg or "estabiliz" in msg

    def test_alias_compresion_medular_triggers_via_arpi_alias(self):
        """Aunque el detector lee `spinal_cord_compression`, el alias engine
        canónico (ARPI_FIELD_ALIASES) registra `compresion_medular` como
        sinónimo legacy para que payloads en español lo disparen."""
        from prostanet.domains.patient_tracking.arpi_selection_engine import (
            ARPI_FIELD_ALIASES,
        )
        assert "compresion_medular" in ARPI_FIELD_ALIASES.get(
            "spinal_cord_compression", []
        )


class TestRadium223InHypocalcemiaDetector:
    """Gate 12 — `radium223_in_hypocalcemia`."""

    def test_explicit_hypocalcemia_flag_triggers_gate(self):
        gate = detect_radium223_in_hypocalcemia({"hypocalcemia": "Sí"})
        assert gate is not None
        assert gate["code"] == "radium223_in_hypocalcemia"
        assert gate["severity"] == "hard_block"

    @pytest.mark.parametrize(
        "calcium_field,value",
        [
            ("calcium_level", 7.8),
            ("calcium_level", 8.4),
            ("corrected_calcium", 8.0),
            ("serum_calcium", 8.49),
        ],
    )
    def test_low_total_calcium_triggers_gate(self, calcium_field, value):
        gate = detect_radium223_in_hypocalcemia({calcium_field: value})
        assert gate is not None
        assert gate["code"] == "radium223_in_hypocalcemia"
        assert f"{value:.1f}" in gate["message"] or "hipocalcemia" in gate["message"].lower()

    def test_normal_total_calcium_does_not_trigger(self):
        assert detect_radium223_in_hypocalcemia({"calcium_level": 9.0}) is None
        assert detect_radium223_in_hypocalcemia({"calcium_level": 8.5}) is None

    @pytest.mark.parametrize(
        "ionized_value",
        [4.0, 4.2, 4.49, 1.05],  # Both mg/dL <4.5 and mmol/L <1.12
    )
    def test_low_ionized_calcium_triggers_gate(self, ionized_value):
        gate = detect_radium223_in_hypocalcemia({"ionized_calcium": ionized_value})
        assert gate is not None
        assert gate["code"] == "radium223_in_hypocalcemia"

    def test_normal_ionized_calcium_does_not_trigger(self):
        assert detect_radium223_in_hypocalcemia({"ionized_calcium": 4.6}) is None
        assert detect_radium223_in_hypocalcemia({"ionized_calcium": 5.2}) is None

    def test_corrected_override_neutralizes_gate(self):
        """`hypocalcemia_corrected=Sí` desactiva el gate (post-replacement
        con calcio + vitamina D documentado)."""
        gate = detect_radium223_in_hypocalcemia(
            {"calcium_level": 7.5, "hypocalcemia_corrected": "Sí"}
        )
        assert gate is None

    def test_corrected_override_with_explicit_flag(self):
        gate = detect_radium223_in_hypocalcemia(
            {"hypocalcemia": "Sí", "hypocalcemia_corrected": "Sí"}
        )
        assert gate is None

    def test_no_calcium_data_does_not_trigger(self):
        """Sin datos de calcio el gate no dispara (no hay base para
        sospechar hipocalcemia)."""
        gate = detect_radium223_in_hypocalcemia({"psa": 50})
        assert gate is None

    def test_message_cites_xofigo_label_and_correction_protocol(self):
        gate = detect_radium223_in_hypocalcemia({"calcium_level": 7.5})
        msg = gate["message"].lower()
        assert "xofigo" in msg or "prescribing information" in msg
        assert "calcio elemental" in msg or "vitamina d" in msg
        assert "denosumab" in msg or "zoledronato" in msg or "peace-3" in msg

    def test_alias_hipocalcemia_legacy_fits_via_arpi_alias(self):
        from prostanet.domains.patient_tracking.arpi_selection_engine import (
            ARPI_FIELD_ALIASES,
        )
        assert "hipocalcemia" in ARPI_FIELD_ALIASES.get("hypocalcemia", [])
        assert "calcio_serico" in ARPI_FIELD_ALIASES.get("calcium_level", [])


# ── Sección B — Filtro de tratamientos ────────────────────────────────────


def test_filter_removes_radium223_with_cord_compression():
    treatments = [
        {"name": "Radio-223", "regimen_code": "RADIUM_223", "priority": "eligible"},
        {"name": "Enzalutamida", "regimen_code": "ENZALUTAMIDE", "priority": "preferred"},
        {"name": "Cabazitaxel", "regimen_code": "CABAZITAXEL", "priority": "second_line"},
    ]
    bundle = apply_pivotal_contraindication_gates(
        {"spinal_cord_compression": "Sí"}, treatments
    )
    names = [t["name"] for t in bundle["filtered_treatments"]]
    assert "Radio-223" not in names
    assert "Enzalutamida" in names
    assert "Cabazitaxel" in names
    assert any(g["code"] == "radium223_in_cord_compression" for g in bundle["gates_triggered"])


def test_filter_removes_radium223_with_hypocalcemia():
    treatments = [
        {"name": "Radium-223 dichloride", "priority": "eligible"},  # match by keyword
        {"name": "Docetaxel", "regimen_code": "DOCETAXEL", "priority": "preferred"},
    ]
    bundle = apply_pivotal_contraindication_gates(
        {"calcium_level": 7.5}, treatments
    )
    names = [t["name"] for t in bundle["filtered_treatments"]]
    assert "Radium-223 dichloride" not in names
    assert "Docetaxel" in names


def test_filter_removes_radium223_keyword_variants():
    treatments_ra223_variants = [
        {"name": "Ra-223", "priority": "eligible"},
        {"name": "ra 223 dichloride", "priority": "eligible"},
        {"name": "Radio 223", "priority": "eligible"},
    ]
    bundle = apply_pivotal_contraindication_gates(
        {"spinal_cord_compression": "Sí"}, treatments_ra223_variants
    )
    assert bundle["filtered_treatments"] == []


# ── Sección C — End-to-end vía servicios ──────────────────────────────────


@pytest.fixture(scope="module")
def registry():
    return ModuleRegistry()


def test_m1_crpc_service_exposes_cord_compression_gate(registry):
    payload = {
        "psa": 30,
        "psa_doubling_time": 5,
        "metastatic": "1",
        "visceral_metastasis": "0",
        "bone_lesion_count": 6,
        "ecog_score": 1,
        "age": 70,
        "castrate_resistant": "1",
        "testosterone": 20,
        "spinal_cord_compression": "Sí",
        "lower_limb_weakness": "Sí — moderada",
        "denosumab_prophylaxis": "Sí",  # Tiene agente óseo (gate 9 no dispara)
        "radium223_candidate": "Sí",
    }
    res = registry.evaluate_module("m1_crpc", payload)
    gates = res.get("pivotal_contraindication_gates") or []
    codes = {g["code"] for g in gates}
    assert "radium223_in_cord_compression" in codes
    # El gate de bone-protection NO debe dispararse porque el paciente
    # ya tiene denosumab declarado
    assert "no_bone_protective_agent" not in codes


def test_m1_crpc_service_exposes_hypocalcemia_gate(registry):
    payload = {
        "psa": 30,
        "psa_doubling_time": 5,
        "metastatic": "1",
        "visceral_metastasis": "0",
        "bone_lesion_count": 4,
        "ecog_score": 1,
        "age": 70,
        "castrate_resistant": "1",
        "testosterone": 20,
        "calcium_level": 7.8,  # hipocalcemia
        "denosumab_prophylaxis": "Sí",
        "radium223_candidate": "Sí",
    }
    res = registry.evaluate_module("m1_crpc", payload)
    gates = res.get("pivotal_contraindication_gates") or []
    codes = {g["code"] for g in gates}
    assert "radium223_in_hypocalcemia" in codes


def test_m1_crpc_service_does_not_expose_gates_when_healthy(registry):
    payload = {
        "psa": 30,
        "psa_doubling_time": 5,
        "metastatic": "1",
        "visceral_metastasis": "0",
        "bone_lesion_count": 4,
        "ecog_score": 1,
        "age": 70,
        "castrate_resistant": "1",
        "testosterone": 20,
        "calcium_level": 9.5,  # normal
        "spinal_cord_compression": "No",
        "lower_limb_weakness": "No",
        "denosumab_prophylaxis": "Sí",
    }
    res = registry.evaluate_module("m1_crpc", payload)
    gates = res.get("pivotal_contraindication_gates") or []
    codes = {g["code"] for g in gates}
    assert "radium223_in_cord_compression" not in codes
    assert "radium223_in_hypocalcemia" not in codes


def test_m1_crpc_filters_radium223_when_cord_compression_active(registry):
    """End-to-end: Ra-223 NO debe aparecer en eligible_treatments cuando
    el paciente tiene compresión medular activa."""
    payload = {
        "psa": 30,
        "psa_doubling_time": 5,
        "metastatic": "1",
        "visceral_metastasis": "0",
        "bone_lesion_count": 6,
        "ecog_score": 1,
        "age": 70,
        "castrate_resistant": "1",
        "testosterone": 20,
        "spinal_cord_compression": "Sí",
        "denosumab_prophylaxis": "Sí",
    }
    res = registry.evaluate_module("m1_crpc", payload)
    eligible = res.get("eligible_treatments") or []
    blob = " ".join(
        (t.get("name", "") + " " + t.get("regimen_code", "")).lower() for t in eligible
    )
    assert "ra-223" not in blob and "radium" not in blob and "ra_223" not in blob


def test_cord_compression_stabilized_re_enables_radium223(registry):
    """Tras estabilización (`cord_compression_stabilized=Sí`), el gate 11
    se desactiva y Ra-223 puede volver a evaluarse (depende del resto de
    selectores, pero el gate específico no lo bloquea)."""
    payload = {
        "psa": 30,
        "psa_doubling_time": 5,
        "metastatic": "1",
        "visceral_metastasis": "0",
        "bone_lesion_count": 6,
        "ecog_score": 1,
        "age": 70,
        "castrate_resistant": "1",
        "testosterone": 20,
        "spinal_cord_compression": "Sí",
        "cord_compression_stabilized": "Sí",  # post-RT/cirugía
        "denosumab_prophylaxis": "Sí",
    }
    res = registry.evaluate_module("m1_crpc", payload)
    gates = res.get("pivotal_contraindication_gates") or []
    assert "radium223_in_cord_compression" not in {g["code"] for g in gates}


# ── Sección D — Backward compatibility ────────────────────────────────────


def test_total_detectors_count_is_at_least_12():
    """El módulo debe tener al menos 12 detectores tras añadir 11 + 12.
    Faubot 2026-04-24 (V) añade gates 13-14 (Lu-177), por lo que el conteo
    pasa a ≥12; el test se mantiene como guard de no regresión hacia abajo."""
    assert len(_DETECTORS) >= 12


def test_existing_gates_still_trigger_after_extension():
    """Los 10 gates anteriores siguen funcionando."""
    payload = {
        "nyha_class": "III",
        "uncontrolled_hypertension": "Sí",
    }
    gates = evaluate_pivotal_contraindication_gates(payload)
    codes = {g["code"] for g in gates}
    assert "severe_heart_failure_nyha_iii_iv" in codes
    assert "uncontrolled_hypertension" in codes


def test_simultaneous_gates_11_and_12_both_trigger():
    """Un paciente con cord compression Y hipocalcemia debe disparar ambos
    gates Ra-223 (11+12), manteniendo trazabilidad independiente.

    Nota: tras Faubot 2026-04-24 (V), los gates Lu-177 (13+14) también
    disparan en este escenario porque comparten triggers de cord compression.
    Este test verifica específicamente que los gates Ra-223 estén presentes
    y que el filtro de Ra-223 emita ambos mensajes.
    """
    payload = {
        "spinal_cord_compression": "Sí",
        "calcium_level": 7.8,
    }
    gates = evaluate_pivotal_contraindication_gates(payload)
    codes = {g["code"] for g in gates}
    assert "radium223_in_cord_compression" in codes
    assert "radium223_in_hypocalcemia" in codes
    # Filtramos solo Ra-223 (no Lu-177) para aislar el conteo de mensajes
    # de los gates 11+12 sobre el régimen objetivo.
    treatments = [{"name": "Ra-223", "regimen_code": "RADIUM_223"}]
    bundle = apply_pivotal_contraindication_gates(payload, treatments)
    # Los 2 mensajes Ra-223 deben aparecer (cord compression + hipocalcemia).
    # Lu-177 también dispara cord compression pero no afecta a este régimen.
    ra223_messages = [
        m for m in bundle["not_recommended_messages"]
        if "radio-223" in m.lower() or "ra-223" in m.lower()
    ]
    assert len(ra223_messages) == 2


def test_healthy_payload_triggers_no_gates():
    """Sano absoluto → 0 gates."""
    payload = {
        "psa": 30,
        "calcium_level": 9.5,
        "ionized_calcium": 4.8,
        "spinal_cord_compression": "No",
        "lower_limb_weakness": "No",
        "nyha_class": "I",
    }
    gates = evaluate_pivotal_contraindication_gates(payload)
    assert gates == []


# ── Sección E — Catálogo Ra-223 + filter ──────────────────────────────────


@pytest.mark.parametrize(
    "regimen_code",
    ["RADIUM_223", "RA_223", "RADIUM223"],
)
def test_radium223_canonical_codes_blocked_by_gate11(regimen_code):
    """Los 3 códigos canónicos de Ra-223 deben ser bloqueados por gate 11."""
    treatments = [{"name": "Foo", "regimen_code": regimen_code}]
    bundle = apply_pivotal_contraindication_gates(
        {"spinal_cord_compression": "Sí"}, treatments
    )
    assert bundle["filtered_treatments"] == []


@pytest.mark.parametrize(
    "regimen_code",
    ["RADIUM_223", "RA_223", "RADIUM223"],
)
def test_radium223_canonical_codes_blocked_by_gate12(regimen_code):
    """Los 3 códigos canónicos de Ra-223 deben ser bloqueados por gate 12."""
    treatments = [{"name": "Foo", "regimen_code": regimen_code}]
    bundle = apply_pivotal_contraindication_gates(
        {"calcium_level": 7.0}, treatments
    )
    assert bundle["filtered_treatments"] == []


def test_filter_does_not_block_non_radium223_treatments():
    """Los gates 11-12 NO deben bloquear regímenes no-Ra-223."""
    treatments = [
        {"name": "Enzalutamida", "regimen_code": "ENZALUTAMIDE"},
        {"name": "Apalutamida", "regimen_code": "APALUTAMIDE"},
        {"name": "Docetaxel", "regimen_code": "DOCETAXEL"},
    ]
    payload_cord = {"spinal_cord_compression": "Sí"}
    payload_hypoca = {"calcium_level": 7.0}
    for payload in (payload_cord, payload_hypoca):
        bundle = apply_pivotal_contraindication_gates(payload, treatments)
        names = {t["name"] for t in bundle["filtered_treatments"]}
        assert names == {"Enzalutamida", "Apalutamida", "Docetaxel"}
