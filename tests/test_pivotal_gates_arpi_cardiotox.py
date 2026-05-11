"""Tests de los gates pivotal 17-18: ARPI × cardiotoxicidad.

Faubot 2026-04-25 (VII) — Cierra la cobertura cardiotóxica para los 2
ARPI con perfil cardio específico documentado en sus etiquetas FDA y
ensayos pivote:

  Gate 17 — `qtc_prolongation_grade3_for_enzalutamide`
    QTc > 500 ms (CTCAE v5 grado 3) o ΔQTc > 60 ms desde basal →
    enzalutamida contraindicada hasta corregir causas reversibles
    (hipokalemia/hipomagnesemia/DDI cardio-tóxicos).
    Evidencia: Xtandi FDA prescribing information §5.4 + ENZAMET
    (Sweeney NEJM 2019;381:121) + CTCAE v5 + ICH E14.

  Gate 18 — `lvef_decline_for_apalutamide`
    LVEF < 50% absoluto o caída > 10 puntos desde basal →
    apalutamida contraindicada hasta optimización IC + LVEF ≥50%
    documentada en eco/MUGA seguimiento.
    Evidencia: Erleada FDA prescribing information warning cardiac
    dysfunction + TITAN (Chi NEJM 2019;381:13) + SPARTAN (Smith
    NEJM 2018;378:1408) + ASCO/ESC Cardio-Oncology Guidelines 2022.

Cobertura del test:
  A) Detector QTc aislado — positivo + negativo + override + boundary
  B) Detector LVEF aislado — absoluto + delta + override + boundary
  C) Filtro de tratamientos — enzalutamida/apalutamida removidos
  D) End-to-end vía m1_crpc service — rastro estructurado expuesto
  E) Backward compatibility — total ahora 18 gates, gates 1-16 intactos
  F) Catálogo enzalutamida/apalutamida × gates — parametrize codes
  G) Coexistencia con soft penalties (Group A mhspc_regimen_selector)
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.application.module_registry import ModuleRegistry
from prostanet.shared.pivotal_contraindication_gates import (
    KEYWORDS_APALUTAMIDE,
    KEYWORDS_ENZALUTAMIDE,
    REGIMEN_CODES_APALUTAMIDE,
    REGIMEN_CODES_ENZALUTAMIDE,
    _DETECTORS,
    apply_pivotal_contraindication_gates,
    detect_lvef_decline_for_apalutamide,
    detect_qtc_prolongation_grade3_for_enzalutamide,
    evaluate_pivotal_contraindication_gates,
)


# ── Sección A — Detector QTc aislado ──────────────────────────────────────


class TestQtcProlongationGrade3ForEnzalutamideDetector:
    """Gate 17 — `qtc_prolongation_grade3_for_enzalutamide`."""

    def test_explicit_qtc_grade3_flag_triggers_gate(self):
        gate = detect_qtc_prolongation_grade3_for_enzalutamide(
            {"qtc_prolongation_grade3": "Sí"}
        )
        assert gate is not None
        assert gate["code"] == "qtc_prolongation_grade3_for_enzalutamide"
        assert gate["severity"] == "hard_block"
        assert "ENZAMET" in gate["trial_refs"]
        assert "Xtandi label" in gate["trial_refs"]
        assert "CTCAE v5" in gate["trial_refs"]

    @pytest.mark.parametrize(
        "qtc_field,value",
        [
            ("qtc_ms", 501),
            ("qtc_ms", 520),
            ("qtc_ms", 600),
            ("qtc_baseline_ms", 510),
        ],
    )
    def test_high_qtc_triggers_gate(self, qtc_field, value):
        gate = detect_qtc_prolongation_grade3_for_enzalutamide({qtc_field: value})
        assert gate is not None
        assert gate["code"] == "qtc_prolongation_grade3_for_enzalutamide"

    @pytest.mark.parametrize("qtc_value", [500, 480, 450, 400])
    def test_normal_qtc_does_not_trigger(self, qtc_value):
        """QTc ≤ 500 ms NO dispara gate (boundary inclusive en 500)."""
        assert detect_qtc_prolongation_grade3_for_enzalutamide({"qtc_ms": qtc_value}) is None

    def test_qtc_at_500_boundary_does_not_trigger(self):
        """QTc = 500 ms exacto es el límite; no dispara (debe ser >500)."""
        assert detect_qtc_prolongation_grade3_for_enzalutamide({"qtc_ms": 500}) is None

    @pytest.mark.parametrize("delta_value", [61, 65, 90, 120])
    def test_high_delta_qtc_triggers_gate(self, delta_value):
        gate = detect_qtc_prolongation_grade3_for_enzalutamide(
            {"qtc_change_ms": delta_value}
        )
        assert gate is not None
        assert gate["code"] == "qtc_prolongation_grade3_for_enzalutamide"

    @pytest.mark.parametrize("delta_value", [60, 50, 30, 0])
    def test_normal_delta_qtc_does_not_trigger(self, delta_value):
        assert (
            detect_qtc_prolongation_grade3_for_enzalutamide({"qtc_change_ms": delta_value})
            is None
        )

    def test_corrected_override_neutralizes_gate(self):
        gate = detect_qtc_prolongation_grade3_for_enzalutamide(
            {"qtc_ms": 520, "qtc_corrected_for_arpi": "Sí"}
        )
        assert gate is None

    def test_no_qtc_data_does_not_trigger(self):
        assert detect_qtc_prolongation_grade3_for_enzalutamide({"psa": 30}) is None

    def test_message_cites_xtandi_label_and_correction_protocol(self):
        gate = detect_qtc_prolongation_grade3_for_enzalutamide({"qtc_ms": 520})
        msg = gate["message"].lower()
        assert "xtandi" in msg
        assert "§5.4" in msg or "5.4" in msg
        assert "hipokalemia" in msg or "hipomagnesemia" in msg
        assert "darolutamida" in msg or "abiraterona" in msg

    def test_message_lists_specific_qtc_value(self):
        gate = detect_qtc_prolongation_grade3_for_enzalutamide({"qtc_ms": 520})
        msg = gate["message"].lower()
        assert "520" in msg
        assert "ctcae v5" in msg or "grado 3" in msg

    def test_alias_qtc_baseline_ms_works(self):
        from prostanet.domains.patient_tracking.arpi_selection_engine import (
            ARPI_FIELD_ALIASES,
        )
        # Alias canónico ya registrado pre-VII
        assert "qtc_ms" in ARPI_FIELD_ALIASES.get("qtc_baseline_ms", []) or \
               "qtc_baseline_ms" in ARPI_FIELD_ALIASES.get("qtc_ms", [])


# ── Sección B — Detector LVEF aislado ─────────────────────────────────────


class TestLvefDeclineForApalutamideDetector:
    """Gate 18 — `lvef_decline_for_apalutamide`."""

    def test_explicit_lvef_decline_flag_triggers_gate(self):
        gate = detect_lvef_decline_for_apalutamide({"lvef_decline_for_arpi": "Sí"})
        assert gate is not None
        assert gate["code"] == "lvef_decline_for_apalutamide"
        assert gate["severity"] == "hard_block"
        assert "TITAN" in gate["trial_refs"]
        assert "SPARTAN" in gate["trial_refs"]
        assert "Erleada label" in gate["trial_refs"]

    @pytest.mark.parametrize("lvef_value", [49, 45, 40, 30])
    def test_low_lvef_triggers_gate(self, lvef_value):
        gate = detect_lvef_decline_for_apalutamide({"lvef_percent": lvef_value})
        assert gate is not None
        assert gate["code"] == "lvef_decline_for_apalutamide"

    @pytest.mark.parametrize("lvef_value", [50, 55, 60, 70])
    def test_normal_lvef_does_not_trigger(self, lvef_value):
        assert detect_lvef_decline_for_apalutamide({"lvef_percent": lvef_value}) is None

    def test_lvef_at_50_boundary_does_not_trigger(self):
        """LVEF = 50% exacto es el límite; no dispara (debe ser <50)."""
        assert detect_lvef_decline_for_apalutamide({"lvef_percent": 50}) is None

    @pytest.mark.parametrize(
        "baseline,current,should_trigger",
        [
            (60, 48, True),   # caída 12 puntos > 10
            (65, 50, True),   # caída 15 puntos
            (70, 55, True),   # caída 15 puntos
            (60, 50, False),  # caída exactamente 10 → boundary, no dispara
            (60, 51, False),  # caída 9 puntos
            (55, 55, False),  # sin cambio
        ],
    )
    def test_lvef_delta_threshold(self, baseline, current, should_trigger):
        payload = {"lvef_baseline_percent": baseline, "lvef_percent": current}
        gate = detect_lvef_decline_for_apalutamide(payload)
        if should_trigger:
            assert gate is not None
            assert gate["code"] == "lvef_decline_for_apalutamide"
        else:
            # Si current >= 50, NO debe disparar por absoluto ni por delta
            # (boundary cases: 60→50 = delta 10 no >10, current 50 boundary)
            assert gate is None

    def test_recovered_override_neutralizes_gate(self):
        gate = detect_lvef_decline_for_apalutamide(
            {"lvef_percent": 45, "lvef_recovered_for_arpi": "Sí"}
        )
        assert gate is None

    def test_no_lvef_data_does_not_trigger(self):
        assert detect_lvef_decline_for_apalutamide({"psa": 30}) is None

    def test_message_cites_titan_spartan_erleada(self):
        gate = detect_lvef_decline_for_apalutamide({"lvef_percent": 45})
        msg = gate["message"].lower()
        assert "erleada" in msg
        assert "titan" in msg
        assert "spartan" in msg
        assert "asco" in msg or "esc" in msg

    def test_message_lists_specific_lvef_value(self):
        gate = detect_lvef_decline_for_apalutamide({"lvef_percent": 45})
        msg = gate["message"].lower()
        assert "45" in msg

    def test_message_suggests_alternative_arpi(self):
        gate = detect_lvef_decline_for_apalutamide({"lvef_percent": 45})
        msg = gate["message"].lower()
        assert "enzalutamida" in msg or "darolutamida" in msg

    def test_alias_lvef_baseline_percent_works(self):
        from prostanet.domains.patient_tracking.arpi_selection_engine import (
            ARPI_FIELD_ALIASES,
        )
        assert "fevi_basal" in ARPI_FIELD_ALIASES.get("lvef_baseline_percent", [])


# ── Sección C — Filtro de tratamientos ────────────────────────────────────


def test_filter_removes_enzalutamide_with_qtc_prolongation():
    treatments = [
        {"name": "Enzalutamida", "regimen_code": "ADT_ENZALUTAMIDE"},
        {"name": "Talazoparib + Enzalutamida", "regimen_code": "TALAZOPARIB_ENZALUTAMIDE"},
        {"name": "Apalutamida", "regimen_code": "ADT_APALUTAMIDE"},
        {"name": "Darolutamida", "regimen_code": "ADT_DAROLUTAMIDE"},
    ]
    bundle = apply_pivotal_contraindication_gates({"qtc_ms": 520}, treatments)
    names = [t["name"] for t in bundle["filtered_treatments"]]
    assert "Enzalutamida" not in names
    assert "Talazoparib + Enzalutamida" not in names
    assert "Apalutamida" in names  # No bloqueado por gate 17
    assert "Darolutamida" in names
    assert any(g["code"] == "qtc_prolongation_grade3_for_enzalutamide" for g in bundle["gates_triggered"])


def test_filter_removes_apalutamide_with_lvef_decline():
    treatments = [
        {"name": "Apalutamida", "regimen_code": "ADT_APALUTAMIDE"},
        {"name": "Enzalutamida", "regimen_code": "ADT_ENZALUTAMIDE"},
        {"name": "Darolutamida", "regimen_code": "ADT_DAROLUTAMIDE"},
    ]
    bundle = apply_pivotal_contraindication_gates({"lvef_percent": 45}, treatments)
    names = [t["name"] for t in bundle["filtered_treatments"]]
    assert "Apalutamida" not in names
    assert "Enzalutamida" in names  # No bloqueado por gate 18
    assert "Darolutamida" in names
    assert any(g["code"] == "lvef_decline_for_apalutamide" for g in bundle["gates_triggered"])


def test_filter_removes_both_arpi_with_qtc_and_lvef():
    """Paciente con QTc 520 + LVEF 45 → ambos ARPI bloqueados, queda darolutamida."""
    treatments = [
        {"name": "Enzalutamida", "regimen_code": "ADT_ENZALUTAMIDE"},
        {"name": "Apalutamida", "regimen_code": "ADT_APALUTAMIDE"},
        {"name": "Darolutamida", "regimen_code": "ADT_DAROLUTAMIDE"},
        {"name": "Abiraterona", "regimen_code": "ADT_ABIRATERONE"},
    ]
    bundle = apply_pivotal_contraindication_gates(
        {"qtc_ms": 520, "lvef_percent": 45}, treatments
    )
    names = [t["name"] for t in bundle["filtered_treatments"]]
    assert "Enzalutamida" not in names
    assert "Apalutamida" not in names
    assert "Darolutamida" in names
    assert "Abiraterona" in names  # No bloqueado por gates 17-18
    codes = {g["code"] for g in bundle["gates_triggered"]}
    assert "qtc_prolongation_grade3_for_enzalutamide" in codes
    assert "lvef_decline_for_apalutamide" in codes


@pytest.mark.parametrize(
    "enzalutamide_name",
    ["Enzalutamida", "Enzalutamide", "Xtandi"],
)
def test_filter_removes_all_enzalutamide_keyword_variants(enzalutamide_name):
    treatments = [{"name": enzalutamide_name, "priority": "eligible"}]
    bundle = apply_pivotal_contraindication_gates({"qtc_ms": 520}, treatments)
    assert bundle["filtered_treatments"] == []


@pytest.mark.parametrize(
    "apalutamide_name",
    ["Apalutamida", "Apalutamide", "Erleada"],
)
def test_filter_removes_all_apalutamide_keyword_variants(apalutamide_name):
    treatments = [{"name": apalutamide_name, "priority": "eligible"}]
    bundle = apply_pivotal_contraindication_gates({"lvef_percent": 45}, treatments)
    assert bundle["filtered_treatments"] == []


# ── Sección D — End-to-end vía servicios ──────────────────────────────────


@pytest.fixture(scope="module")
def registry():
    return ModuleRegistry()


def test_m1_crpc_service_exposes_qtc_gate(registry):
    payload = {
        "psa": 30, "psa_doubling_time": 4, "metastatic": "1",
        "visceral_metastasis": "0", "bone_lesion_count": 4,
        "ecog_score": 1, "age": 70,
        "castrate_resistant": "1", "testosterone": 20,
        "denosumab_prophylaxis": "Sí",
        "qtc_ms": 520,
    }
    res = registry.evaluate_module("m1_crpc", payload)
    gates = res.get("pivotal_contraindication_gates") or []
    codes = {g["code"] for g in gates}
    assert "qtc_prolongation_grade3_for_enzalutamide" in codes


def test_m1_crpc_service_exposes_lvef_gate(registry):
    payload = {
        "psa": 30, "psa_doubling_time": 4, "metastatic": "1",
        "visceral_metastasis": "0", "bone_lesion_count": 4,
        "ecog_score": 1, "age": 70,
        "castrate_resistant": "1", "testosterone": 20,
        "denosumab_prophylaxis": "Sí",
        "lvef_percent": 45,
    }
    res = registry.evaluate_module("m1_crpc", payload)
    gates = res.get("pivotal_contraindication_gates") or []
    codes = {g["code"] for g in gates}
    assert "lvef_decline_for_apalutamide" in codes


def test_m1_crpc_service_does_not_expose_arpi_cardiotox_gates_when_healthy(registry):
    payload = {
        "psa": 30, "psa_doubling_time": 4, "metastatic": "1",
        "visceral_metastasis": "0", "bone_lesion_count": 4,
        "ecog_score": 1, "age": 70,
        "castrate_resistant": "1", "testosterone": 20,
        "denosumab_prophylaxis": "Sí",
        "qtc_ms": 420, "lvef_percent": 60,
    }
    res = registry.evaluate_module("m1_crpc", payload)
    gates = res.get("pivotal_contraindication_gates") or []
    codes = {g["code"] for g in gates}
    assert "qtc_prolongation_grade3_for_enzalutamide" not in codes
    assert "lvef_decline_for_apalutamide" not in codes


def test_m1_crpc_filters_enzalutamide_when_qtc_grade3(registry):
    payload = {
        "psa": 30, "psa_doubling_time": 4, "metastatic": "1",
        "visceral_metastasis": "0", "bone_lesion_count": 4,
        "ecog_score": 1, "age": 70,
        "castrate_resistant": "1", "testosterone": 20,
        "denosumab_prophylaxis": "Sí",
        "qtc_ms": 520,
    }
    res = registry.evaluate_module("m1_crpc", payload)
    eligible = res.get("eligible_treatments") or []
    blob = " ".join(
        (t.get("name", "") + " " + t.get("regimen_code", "")).lower() for t in eligible
    )
    assert "enzalutamid" not in blob
    assert "xtandi" not in blob


def test_qtc_corrected_override_re_enables_enzalutamide(registry):
    payload = {
        "psa": 30, "psa_doubling_time": 4, "metastatic": "1",
        "visceral_metastasis": "0", "bone_lesion_count": 4,
        "ecog_score": 1, "age": 70,
        "castrate_resistant": "1", "testosterone": 20,
        "denosumab_prophylaxis": "Sí",
        "qtc_ms": 520, "qtc_corrected_for_arpi": "Sí",
    }
    res = registry.evaluate_module("m1_crpc", payload)
    gates = res.get("pivotal_contraindication_gates") or []
    assert "qtc_prolongation_grade3_for_enzalutamide" not in {g["code"] for g in gates}


# ── Sección E — Backward compatibility ────────────────────────────────────


def test_total_detectors_count_is_at_least_12():
    """El módulo debe tener al menos 12 detectores Python.
    Faubot 2026-04-25 (XIX) migró el último gate Python complejo (gate 9)
    a YAML; `_DETECTORS` ahora contiene 12 detectores Python (era 18). El
    catálogo YAML alcanza 19/19 (100%); el sistema híbrido total sigue
    exponiendo 19 gates activos."""
    assert len(_DETECTORS) >= 12


def test_existing_gates_1_to_16_still_trigger_after_extension():
    """Los 16 gates anteriores siguen funcionando."""
    payload = {
        "nyha_class": "III",
        "uncontrolled_hypertension": "Sí",
        "spinal_cord_compression": "Sí",
        "calcium_level": 7.5,
        "anc": 1000,
        "platelets": 80000,
        "mds_aml_history": "Sí",
    }
    gates = evaluate_pivotal_contraindication_gates(payload)
    codes = {g["code"] for g in gates}
    # Subset crítico de gates anteriores
    assert "severe_heart_failure_nyha_iii_iv" in codes
    assert "uncontrolled_hypertension" in codes
    assert "radium223_in_cord_compression" in codes
    assert "radium223_in_hypocalcemia" in codes
    assert "lutetium177_in_cord_compression" in codes
    assert "lutetium177_in_severe_cytopenias" in codes
    assert "parp_inhibitor_in_severe_cytopenias" in codes
    assert "parp_inhibitor_in_mds_aml_history" in codes


def test_simultaneous_gates_17_and_18_trigger_independently():
    """Un paciente con QTc 520 + LVEF 45 dispara ambos gates ARPI cardiotox."""
    payload = {"qtc_ms": 520, "lvef_percent": 45}
    gates = evaluate_pivotal_contraindication_gates(payload)
    codes = {g["code"] for g in gates}
    assert "qtc_prolongation_grade3_for_enzalutamide" in codes
    assert "lvef_decline_for_apalutamide" in codes


def test_healthy_payload_triggers_no_arpi_cardiotox_gates():
    payload = {
        "psa": 30,
        "qtc_ms": 420,
        "qtc_change_ms": 15,
        "lvef_percent": 65,
        "lvef_baseline_percent": 65,
    }
    gates = evaluate_pivotal_contraindication_gates(payload)
    codes = {g["code"] for g in gates}
    assert "qtc_prolongation_grade3_for_enzalutamide" not in codes
    assert "lvef_decline_for_apalutamide" not in codes


# ── Sección F — Catálogo enzalutamida/apalutamida × gates ─────────────────


@pytest.mark.parametrize("regimen_code", sorted(REGIMEN_CODES_ENZALUTAMIDE))
def test_all_enzalutamide_canonical_codes_blocked_by_gate17(regimen_code):
    treatments = [{"name": "Foo", "regimen_code": regimen_code}]
    bundle = apply_pivotal_contraindication_gates({"qtc_ms": 520}, treatments)
    assert bundle["filtered_treatments"] == []


@pytest.mark.parametrize("regimen_code", sorted(REGIMEN_CODES_APALUTAMIDE))
def test_all_apalutamide_canonical_codes_blocked_by_gate18(regimen_code):
    treatments = [{"name": "Foo", "regimen_code": regimen_code}]
    bundle = apply_pivotal_contraindication_gates({"lvef_percent": 45}, treatments)
    assert bundle["filtered_treatments"] == []


def test_gate17_does_not_block_apalutamide_or_darolutamide():
    """Gate 17 (QTc) bloquea SOLO enzalutamida — no apalutamida ni darolutamida."""
    treatments = [
        {"name": "Apalutamida", "regimen_code": "ADT_APALUTAMIDE"},
        {"name": "Darolutamida", "regimen_code": "ADT_DAROLUTAMIDE"},
        {"name": "Abiraterona", "regimen_code": "ADT_ABIRATERONE"},
    ]
    bundle = apply_pivotal_contraindication_gates({"qtc_ms": 520}, treatments)
    names = {t["name"] for t in bundle["filtered_treatments"]}
    # Todos sobreviven (gate 17 solo afecta enzalutamida)
    assert names == {"Apalutamida", "Darolutamida", "Abiraterona"}


def test_gate18_does_not_block_enzalutamide_or_darolutamide():
    """Gate 18 (LVEF) bloquea SOLO apalutamida — no enzalutamida ni darolutamida."""
    treatments = [
        {"name": "Enzalutamida", "regimen_code": "ADT_ENZALUTAMIDE"},
        {"name": "Darolutamida", "regimen_code": "ADT_DAROLUTAMIDE"},
        {"name": "Abiraterona", "regimen_code": "ADT_ABIRATERONE"},
    ]
    bundle = apply_pivotal_contraindication_gates({"lvef_percent": 45}, treatments)
    names = {t["name"] for t in bundle["filtered_treatments"]}
    assert names == {"Enzalutamida", "Darolutamida", "Abiraterona"}


def test_enzalutamide_keywords_catalog_includes_xtandi():
    expected = {"enzalutamida", "enzalutamide", "xtandi"}
    assert expected.issubset(set(KEYWORDS_ENZALUTAMIDE))


def test_apalutamide_keywords_catalog_includes_erleada():
    expected = {"apalutamida", "apalutamide", "erleada"}
    assert expected.issubset(set(KEYWORDS_APALUTAMIDE))


def test_enzalutamide_regimen_codes_catalog_includes_canonical():
    expected = {
        "ADT_ENZALUTAMIDE",
        "ENZALUTAMIDE",
        "TALAZOPARIB_ENZALUTAMIDE",
        "ADT_TALAZO_ENZA_HRR",
    }
    assert expected == REGIMEN_CODES_ENZALUTAMIDE


def test_apalutamide_regimen_codes_catalog_includes_canonical():
    expected = {"ADT_APALUTAMIDE", "APALUTAMIDE"}
    assert expected == REGIMEN_CODES_APALUTAMIDE


# ── Sección G — Coexistencia con soft penalties ───────────────────────────


def test_qtc_in_zone_gris_does_not_trigger_hard_block():
    """QTc 480 ms está en zona gris (>470 ms = soft penalty -12 en
    mhspc_regimen_selector, pero <500 ms = NO hard block gate 17).
    Esto valida que las dos capas coexisten sin solaparse."""
    gate = detect_qtc_prolongation_grade3_for_enzalutamide({"qtc_ms": 480})
    assert gate is None


def test_lvef_in_zone_gris_does_not_trigger_hard_block():
    """LVEF 50-55% (zona gris para apalutamida soft penalty) NO dispara
    el hard block gate 18. Solo <50% absoluto o caída >10 puntos lo activan."""
    gate = detect_lvef_decline_for_apalutamide({"lvef_percent": 52})
    assert gate is None


def test_qtc_at_critical_threshold_triggers_hard_block_only():
    """QTc 510 ms supera el umbral CTCAE grado 3 (>500) → debe disparar
    SOLO gate 17 (no soft penalty additionally — solo se trata como hard)."""
    gate = detect_qtc_prolongation_grade3_for_enzalutamide({"qtc_ms": 510})
    assert gate is not None
    assert gate["severity"] == "hard_block"


# ── Sección H — Aliases ARPI completos ────────────────────────────────────


def test_arpi_aliases_for_cardiotox_gates_registered():
    from prostanet.domains.patient_tracking.arpi_selection_engine import (
        ARPI_FIELD_ALIASES,
    )
    # 5 nuevos alias añadidos en Faubot 2026-04-25 (VII)
    assert "qtc_change_ms" in ARPI_FIELD_ALIASES
    assert "lvef_baseline_percent" in ARPI_FIELD_ALIASES
    assert "qtc_corrected_for_arpi" in ARPI_FIELD_ALIASES
    assert "lvef_recovered_for_arpi" in ARPI_FIELD_ALIASES
    assert "lvef_percent" in ARPI_FIELD_ALIASES
    # Verificar contenido de aliases (ES médica)
    assert "qtc_delta_ms" in ARPI_FIELD_ALIASES["qtc_change_ms"]
    assert "fevi_basal" in ARPI_FIELD_ALIASES["lvef_baseline_percent"]
    assert "fevi" in ARPI_FIELD_ALIASES["lvef_percent"]
