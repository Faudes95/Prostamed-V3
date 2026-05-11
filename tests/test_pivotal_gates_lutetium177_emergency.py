"""Tests de los gates pivotal 13-14: Lu-177-PSMA × emergencias oncológicas.

Faubot 2026-04-24 (V) — Continuación de la auditoría 2026-04-24 (IV) que
cerró Ra-223 × emergencias. Esta auditoría replica el patrón para
lutetium-177-PSMA-617 (Pluvicto, Novartis 2022), el otro radioligando
canónico aprobado en mCRPC. Los criterios de exclusión de VISION
(Sartor NEJM 2021;385:2197), PSMAfore (Sartor ESMO 2024) y TheraP
(Hofman Lancet 2021) + Pluvicto FDA prescribing information motivan los
2 gates añadidos:

  Gate 13 — `lutetium177_in_cord_compression`
    Compresión medular activa o sospechada → Lu-177-PSMA contraindicado
    hasta estabilización con dexametasona + RT 30 Gy/10 fx (Loblaw ASCO
    2012) o cirugía descompresiva (criterios Patchell). VISION criterio
    de exclusión E.4.6.

  Gate 14 — `lutetium177_in_severe_cytopenias`
    ANC <1500/µL, plaquetas <75 000/µL, o Hb <9 g/dL → Lu-177-PSMA
    contraindicado por riesgo de mielosupresión acumulativa irreversible
    (Pluvicto label cycle gate; VISION exclusión).

Cobertura del test:
  A) Detector cord compression aislado — positivo + negativo + override + alias
  B) Detector cytopenias aislado — ANC + plaquetas + Hb + corrección + flag
  C) Filtro de tratamientos — Lu-177 / Pluvicto removidos cuando aplica
  D) End-to-end vía m1_crpc service — rastro estructurado expuesto
  E) Backward compatibility — total ahora 14 gates, gates anteriores intactos
  F) Catálogo Lu-177-PSMA × gates — 4 códigos × 2 gates parametrize
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.application.module_registry import ModuleRegistry
from prostanet.shared.pivotal_contraindication_gates import (
    KEYWORDS_LUTETIUM177,
    REGIMEN_CODES_LUTETIUM177,
    _DETECTORS,
    apply_pivotal_contraindication_gates,
    detect_lutetium177_in_cord_compression,
    detect_lutetium177_in_severe_cytopenias,
    evaluate_pivotal_contraindication_gates,
    filter_treatments_by_gates,
)


# ── Sección A — Detector cord compression aislado ─────────────────────────


class TestLutetium177InCordCompressionDetector:
    """Gate 13 — `lutetium177_in_cord_compression`."""

    def test_explicit_spinal_cord_compression_triggers_gate(self):
        gate = detect_lutetium177_in_cord_compression({"spinal_cord_compression": "Sí"})
        assert gate is not None
        assert gate["code"] == "lutetium177_in_cord_compression"
        assert gate["severity"] == "hard_block"
        assert gate["affected_regimen_codes"] == REGIMEN_CODES_LUTETIUM177
        assert "VISION" in gate["trial_refs"]
        assert "Pluvicto label" in gate["trial_refs"]
        assert "PSMAfore" in gate["trial_refs"]
        assert "TheraP" in gate["trial_refs"]

    def test_epidural_compression_alias_triggers_gate(self):
        gate = detect_lutetium177_in_cord_compression({"epidural_compression": "1"})
        assert gate is not None
        assert gate["code"] == "lutetium177_in_cord_compression"

    @pytest.mark.parametrize(
        "weakness",
        ["Sí — moderada", "Sí — severa/paresia", "Sí — paresia"],
    )
    def test_severe_weakness_triggers_gate(self, weakness):
        gate = detect_lutetium177_in_cord_compression({"lower_limb_weakness": weakness})
        assert gate is not None
        assert gate["code"] == "lutetium177_in_cord_compression"

    def test_mild_weakness_does_not_trigger_gate(self):
        gate = detect_lutetium177_in_cord_compression({"lower_limb_weakness": "Sí — leve"})
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
        gate = detect_lutetium177_in_cord_compression(
            {"cord_compression_symptoms": symptoms}
        )
        assert gate is not None
        assert gate["code"] == "lutetium177_in_cord_compression"

    def test_dolor_dorsolumbar_alone_does_not_trigger_gate(self):
        """Síntoma sugerente pero no específico — no dispara aislado."""
        gate = detect_lutetium177_in_cord_compression(
            {"cord_compression_symptoms": "Dolor dorso-lumbar progresivo"}
        )
        assert gate is None

    def test_stabilized_override_neutralizes_gate(self):
        """`cord_compression_stabilized=Sí` desactiva el gate."""
        gate = detect_lutetium177_in_cord_compression(
            {
                "spinal_cord_compression": "Sí",
                "lower_limb_weakness": "Sí — severa/paresia",
                "cord_compression_stabilized": "Sí",
            }
        )
        assert gate is None

    def test_healthy_payload_does_not_trigger_gate(self):
        gate = detect_lutetium177_in_cord_compression(
            {
                "spinal_cord_compression": "No",
                "lower_limb_weakness": "No",
                "cord_compression_symptoms": "Ninguno",
            }
        )
        assert gate is None

    def test_message_includes_management_protocol_and_vision_reference(self):
        gate = detect_lutetium177_in_cord_compression({"spinal_cord_compression": "Sí"})
        msg = gate["message"].lower()
        assert "pluvicto" in msg
        assert "vision" in msg
        assert "dexametasona" in msg or "rt" in msg
        assert "patchell" in msg or "descompresiva" in msg
        assert "loblaw" in msg

    def test_message_cites_myelosuppression_rates_from_vision(self):
        """Mensaje debe enseñar al clínico los rates de mielosupresión."""
        gate = detect_lutetium177_in_cord_compression({"spinal_cord_compression": "Sí"})
        msg = gate["message"].lower()
        assert "anemia" in msg or "trombocitopenia" in msg or "neutropenia" in msg
        assert "32%" in msg or "17%" in msg or "9%" in msg


# ── Sección B — Detector severe cytopenias aislado ────────────────────────


class TestLutetium177InSevereCytopeniasDetector:
    """Gate 14 — `lutetium177_in_severe_cytopenias`."""

    def test_explicit_severe_cytopenia_flag_triggers_gate(self):
        gate = detect_lutetium177_in_severe_cytopenias(
            {"severe_cytopenia_for_radioligand": "Sí"}
        )
        assert gate is not None
        assert gate["code"] == "lutetium177_in_severe_cytopenias"
        assert gate["severity"] == "hard_block"

    @pytest.mark.parametrize(
        "anc_field,value",
        [
            ("anc", 1499),
            ("anc", 1000),
            ("anc", 500),
            ("anc_baseline", 1200),
        ],
    )
    def test_low_anc_triggers_gate(self, anc_field, value):
        gate = detect_lutetium177_in_severe_cytopenias({anc_field: value})
        assert gate is not None
        assert gate["code"] == "lutetium177_in_severe_cytopenias"
        assert "anc" in gate["message"].lower()

    @pytest.mark.parametrize("anc_value", [1500, 1800, 2500])
    def test_normal_anc_does_not_trigger(self, anc_value):
        assert detect_lutetium177_in_severe_cytopenias({"anc": anc_value}) is None

    @pytest.mark.parametrize("plt_value", [74999, 50000, 30000, 10000])
    def test_low_platelets_trigger_gate(self, plt_value):
        gate = detect_lutetium177_in_severe_cytopenias({"platelets": plt_value})
        assert gate is not None
        assert gate["code"] == "lutetium177_in_severe_cytopenias"
        assert "plaq" in gate["message"].lower()

    @pytest.mark.parametrize("plt_value", [75000, 100000, 250000])
    def test_normal_platelets_do_not_trigger(self, plt_value):
        assert detect_lutetium177_in_severe_cytopenias({"platelets": plt_value}) is None

    @pytest.mark.parametrize(
        "hb_field,value",
        [
            ("hemoglobin_g_dl", 8.99),
            ("hemoglobin_g_dl", 8.5),
            ("hemoglobin", 7.5),
            ("hb", 6.0),
        ],
    )
    def test_low_hemoglobin_triggers_gate(self, hb_field, value):
        gate = detect_lutetium177_in_severe_cytopenias({hb_field: value})
        assert gate is not None
        assert gate["code"] == "lutetium177_in_severe_cytopenias"
        assert "hb" in gate["message"].lower() or "hemoglobina" in gate["message"].lower()

    @pytest.mark.parametrize("hb_value", [9.0, 10.5, 14.0])
    def test_normal_hemoglobin_does_not_trigger(self, hb_value):
        assert detect_lutetium177_in_severe_cytopenias({"hemoglobin_g_dl": hb_value}) is None

    def test_corrected_override_neutralizes_gate(self):
        """`cytopenias_corrected_for_radioligand=Sí` desactiva el gate."""
        gate = detect_lutetium177_in_severe_cytopenias(
            {
                "anc": 1000,
                "platelets": 60000,
                "hemoglobin_g_dl": 8.0,
                "cytopenias_corrected_for_radioligand": "Sí",
            }
        )
        assert gate is None

    def test_corrected_override_with_explicit_flag(self):
        gate = detect_lutetium177_in_severe_cytopenias(
            {
                "severe_cytopenia_for_radioligand": "Sí",
                "cytopenias_corrected_for_radioligand": "Sí",
            }
        )
        assert gate is None

    def test_no_lab_data_does_not_trigger(self):
        """Sin datos hematológicos el gate no dispara."""
        assert detect_lutetium177_in_severe_cytopenias({"psa": 30}) is None

    def test_message_cites_pluvicto_label_thresholds(self):
        gate = detect_lutetium177_in_severe_cytopenias({"anc": 1000})
        msg = gate["message"].lower()
        assert "pluvicto" in msg
        assert "1.5" in msg or "1500" in msg
        assert "75" in msg
        assert "9 g/dl" in msg or "9.0 g/dl" in msg
        assert "vision" in msg

    def test_message_lists_multiple_cytopenias_when_present(self):
        gate = detect_lutetium177_in_severe_cytopenias(
            {"anc": 1000, "platelets": 50000, "hemoglobin_g_dl": 8.0}
        )
        msg = gate["message"].lower()
        # Debe mencionar las 3 anormalidades
        assert "anc" in msg and "1000" in msg
        assert "plaquetas" in msg and "50" in msg
        assert "hb" in msg and "8.0" in msg

    def test_alias_neutrofilos_triggers_via_arpi_alias(self):
        from prostanet.domains.patient_tracking.arpi_selection_engine import (
            ARPI_FIELD_ALIASES,
        )
        assert "neutrofilos_absolutos" in ARPI_FIELD_ALIASES.get("anc", [])
        assert "plaquetas" in ARPI_FIELD_ALIASES.get("platelets", [])
        assert "hemoglobina" in ARPI_FIELD_ALIASES.get("hemoglobin_g_dl", [])


# ── Sección C — Filtro de tratamientos ────────────────────────────────────


def test_filter_removes_lutetium177_with_cord_compression():
    treatments = [
        {"name": "Lu-177-PSMA-617", "regimen_code": "LU177_PSMA617", "priority": "eligible"},
        {"name": "Pluvicto", "priority": "eligible"},  # match by keyword
        {"name": "Enzalutamida", "regimen_code": "ENZALUTAMIDE", "priority": "preferred"},
    ]
    bundle = apply_pivotal_contraindication_gates(
        {"spinal_cord_compression": "Sí"}, treatments
    )
    names = [t["name"] for t in bundle["filtered_treatments"]]
    assert "Lu-177-PSMA-617" not in names
    assert "Pluvicto" not in names
    assert "Enzalutamida" in names
    assert any(g["code"] == "lutetium177_in_cord_compression" for g in bundle["gates_triggered"])


def test_filter_removes_lutetium177_with_severe_cytopenias():
    treatments = [
        {"name": "Lutecio-177 PSMA-617", "regimen_code": "LU177_PSMA617"},
        {"name": "Cabazitaxel", "regimen_code": "CABAZITAXEL"},
    ]
    bundle = apply_pivotal_contraindication_gates(
        {"anc": 1000, "platelets": 60000}, treatments
    )
    names = [t["name"] for t in bundle["filtered_treatments"]]
    assert "Lutecio-177 PSMA-617" not in names
    assert "Cabazitaxel" in names


@pytest.mark.parametrize(
    "lu177_name",
    [
        "Lu-177-PSMA-617",
        "Lu 177 PSMA 617",
        "Lutetium-177 PSMA-617",
        "Lutecio-177 PSMA-617",
        "Pluvicto",
        "PSMA-617 dirigido",
    ],
)
def test_filter_removes_all_lutetium177_keyword_variants(lu177_name):
    treatments = [{"name": lu177_name, "priority": "eligible"}]
    bundle = apply_pivotal_contraindication_gates(
        {"spinal_cord_compression": "Sí"}, treatments
    )
    assert bundle["filtered_treatments"] == []


# ── Sección D — End-to-end vía servicios ──────────────────────────────────


@pytest.fixture(scope="module")
def registry():
    return ModuleRegistry()


def test_m1_crpc_service_exposes_lu177_cord_compression_gate(registry):
    payload = {
        "psa": 50,
        "psa_doubling_time": 4,
        "metastatic": "1",
        "visceral_metastasis": "0",
        "bone_lesion_count": 5,
        "ecog_score": 1,
        "age": 70,
        "castrate_resistant": "1",
        "testosterone": 20,
        "denosumab_prophylaxis": "Sí",
        "spinal_cord_compression": "Sí",
        "lower_limb_weakness": "Sí — moderada",
        # PSMA positive — Lu-177 candidato natural si no fuera por cord compression
        "psma_pet_done": "1",
        "psma_positive": "Sí",
        "psma_lesion_suvmax_minimum": 12,
        "psma_suvmean_liver": 6,
    }
    res = registry.evaluate_module("m1_crpc", payload)
    gates = res.get("pivotal_contraindication_gates") or []
    codes = {g["code"] for g in gates}
    assert "lutetium177_in_cord_compression" in codes
    # Ra-223 también debe estar bloqueado (gate 11) en este escenario
    assert "radium223_in_cord_compression" in codes


def test_m1_crpc_service_exposes_lu177_cytopenias_gate(registry):
    payload = {
        "psa": 50,
        "psa_doubling_time": 4,
        "metastatic": "1",
        "visceral_metastasis": "0",
        "bone_lesion_count": 5,
        "ecog_score": 1,
        "age": 70,
        "castrate_resistant": "1",
        "testosterone": 20,
        "denosumab_prophylaxis": "Sí",
        "anc": 1200,
        "platelets": 60000,
        "hemoglobin_g_dl": 8.5,
        "psma_pet_done": "1",
        "psma_positive": "Sí",
    }
    res = registry.evaluate_module("m1_crpc", payload)
    gates = res.get("pivotal_contraindication_gates") or []
    codes = {g["code"] for g in gates}
    assert "lutetium177_in_severe_cytopenias" in codes


def test_m1_crpc_service_does_not_expose_lu177_gates_when_healthy(registry):
    payload = {
        "psa": 50,
        "psa_doubling_time": 4,
        "metastatic": "1",
        "visceral_metastasis": "0",
        "bone_lesion_count": 5,
        "ecog_score": 1,
        "age": 70,
        "castrate_resistant": "1",
        "testosterone": 20,
        "denosumab_prophylaxis": "Sí",
        "anc": 2500,
        "platelets": 200000,
        "hemoglobin_g_dl": 12.5,
        "spinal_cord_compression": "No",
        "lower_limb_weakness": "No",
    }
    res = registry.evaluate_module("m1_crpc", payload)
    gates = res.get("pivotal_contraindication_gates") or []
    codes = {g["code"] for g in gates}
    assert "lutetium177_in_cord_compression" not in codes
    assert "lutetium177_in_severe_cytopenias" not in codes


def test_m1_crpc_filters_lu177_when_cytopenias_severe(registry):
    """End-to-end: Lu-177 NO debe aparecer en eligible_treatments cuando
    el paciente tiene citopenias severas."""
    payload = {
        "psa": 50,
        "psa_doubling_time": 4,
        "metastatic": "1",
        "visceral_metastasis": "0",
        "bone_lesion_count": 5,
        "ecog_score": 1,
        "age": 70,
        "castrate_resistant": "1",
        "testosterone": 20,
        "denosumab_prophylaxis": "Sí",
        "anc": 1000,
        "platelets": 50000,
        "hemoglobin_g_dl": 8.0,
        "psma_pet_done": "1",
        "psma_positive": "Sí",
        "psma_lesion_suvmax_minimum": 12,
        "psma_suvmean_liver": 6,
    }
    res = registry.evaluate_module("m1_crpc", payload)
    eligible = res.get("eligible_treatments") or []
    blob = " ".join(
        (t.get("name", "") + " " + t.get("regimen_code", "")).lower() for t in eligible
    )
    assert "lu-177" not in blob and "lu177" not in blob and "pluvicto" not in blob


def test_cytopenias_corrected_re_enables_lu177(registry):
    """Tras corrección hematológica, el gate 14 se desactiva y Lu-177 puede
    volver a evaluarse (depende del resto de selectores, pero el gate
    específico ya no lo bloquea)."""
    payload = {
        "psa": 50,
        "psa_doubling_time": 4,
        "metastatic": "1",
        "visceral_metastasis": "0",
        "bone_lesion_count": 5,
        "ecog_score": 1,
        "age": 70,
        "castrate_resistant": "1",
        "testosterone": 20,
        "denosumab_prophylaxis": "Sí",
        "anc": 1000,
        "cytopenias_corrected_for_radioligand": "Sí",  # post-G-CSF/transfusión
    }
    res = registry.evaluate_module("m1_crpc", payload)
    gates = res.get("pivotal_contraindication_gates") or []
    codes = {g["code"] for g in gates}
    assert "lutetium177_in_severe_cytopenias" not in codes


# ── Sección E — Backward compatibility ────────────────────────────────────


def test_total_detectors_count_is_at_least_12():
    """El módulo debe tener al menos 12 detectores Python.
    Faubot 2026-04-25 (XIX) migró el último gate Python complejo (gate 9)
    a YAML; `_DETECTORS` ahora contiene 12 detectores Python (era 13 tras
    XVIII, era 18 originalmente). El catálogo YAML alcanza 19/19 (100%).
    El sistema híbrido total sigue exponiendo 19 gates activos."""
    assert len(_DETECTORS) >= 12


def test_existing_gates_still_trigger_after_extension():
    """Los 12 gates anteriores siguen funcionando."""
    payload = {
        "nyha_class": "III",
        "uncontrolled_hypertension": "Sí",
        "spinal_cord_compression": "Sí",
        "calcium_level": 7.5,
    }
    gates = evaluate_pivotal_contraindication_gates(payload)
    codes = {g["code"] for g in gates}
    # Gates anteriores
    assert "severe_heart_failure_nyha_iii_iv" in codes
    assert "uncontrolled_hypertension" in codes
    assert "radium223_in_cord_compression" in codes
    assert "radium223_in_hypocalcemia" in codes
    # Gates nuevos
    assert "lutetium177_in_cord_compression" in codes


def test_simultaneous_radioligand_gates_all_trigger():
    """Un paciente con cord compression Y citopenias severas Y hipocalcemia
    debe disparar los 4 gates radioligand (11, 12, 13, 14).

    Nota: tras Faubot 2026-04-24 (VI), el gate 15 (PARPi cytopenias)
    también dispara con ANC bajo y Hb baja porque comparte triggers
    hematológicos. Este test verifica específicamente los 4 radioligand
    gates (Ra-223 + Lu-177); el bundle filtra solo radioligands para
    aislar el conteo de mensajes."""
    payload = {
        "spinal_cord_compression": "Sí",
        "calcium_level": 7.5,
        "anc": 1000,
        "hemoglobin_g_dl": 8.0,
    }
    gates = evaluate_pivotal_contraindication_gates(payload)
    codes = {g["code"] for g in gates}
    assert "radium223_in_cord_compression" in codes
    assert "radium223_in_hypocalcemia" in codes
    assert "lutetium177_in_cord_compression" in codes
    assert "lutetium177_in_severe_cytopenias" in codes
    # Filtramos solo radioligands (no PARPi) para aislar el conteo de
    # mensajes a los gates radioligand 11-14.
    treatments = [
        {"name": "Ra-223", "regimen_code": "RADIUM_223"},
        {"name": "Lu-177-PSMA-617", "regimen_code": "LU177_PSMA617"},
    ]
    bundle = apply_pivotal_contraindication_gates(payload, treatments)
    # Ambos radioligands removidos
    assert bundle["filtered_treatments"] == []
    # Mensajes únicos por radioligand: cord compression Ra-223 + hipocalcemia
    # Ra-223 + cord compression Lu-177 + cytopenias Lu-177 = 4 mensajes
    # radioligand-específicos. PARPi también dispara su gate 15 con estos
    # labs, lo que añade 1 mensaje adicional.
    radioligand_msgs = [
        m for m in bundle["not_recommended_messages"]
        if "radio-223" in m.lower() or "lu-177" in m.lower() or "pluvicto" in m.lower()
    ]
    assert len(radioligand_msgs) == 4


def test_healthy_payload_triggers_no_radioligand_gates():
    payload = {
        "psa": 30,
        "calcium_level": 9.5,
        "anc": 2500,
        "platelets": 200000,
        "hemoglobin_g_dl": 12.5,
        "spinal_cord_compression": "No",
        "lower_limb_weakness": "No",
    }
    gates = evaluate_pivotal_contraindication_gates(payload)
    codes = {g["code"] for g in gates}
    assert "radium223_in_cord_compression" not in codes
    assert "radium223_in_hypocalcemia" not in codes
    assert "lutetium177_in_cord_compression" not in codes
    assert "lutetium177_in_severe_cytopenias" not in codes


# ── Sección F — Catálogo Lu-177-PSMA × gates ──────────────────────────────


@pytest.mark.parametrize("regimen_code", sorted(REGIMEN_CODES_LUTETIUM177))
def test_all_lu177_canonical_codes_blocked_by_gate13(regimen_code):
    """Todos los códigos canónicos de Lu-177 deben ser bloqueados por gate 13."""
    treatments = [{"name": "Foo", "regimen_code": regimen_code}]
    bundle = apply_pivotal_contraindication_gates(
        {"spinal_cord_compression": "Sí"}, treatments
    )
    assert bundle["filtered_treatments"] == []


@pytest.mark.parametrize("regimen_code", sorted(REGIMEN_CODES_LUTETIUM177))
def test_all_lu177_canonical_codes_blocked_by_gate14(regimen_code):
    """Todos los códigos canónicos de Lu-177 deben ser bloqueados por gate 14."""
    treatments = [{"name": "Foo", "regimen_code": regimen_code}]
    bundle = apply_pivotal_contraindication_gates(
        {"anc": 1000}, treatments
    )
    assert bundle["filtered_treatments"] == []


def test_lu177_gates_do_not_block_non_lu177_treatments():
    """Los gates 13-14 NO deben bloquear regímenes no-Lu-177."""
    treatments = [
        {"name": "Enzalutamida", "regimen_code": "ENZALUTAMIDE"},
        {"name": "Apalutamida", "regimen_code": "APALUTAMIDE"},
        {"name": "Docetaxel", "regimen_code": "DOCETAXEL"},
    ]
    payload_cord = {"spinal_cord_compression": "Sí"}
    payload_cytopenia = {"anc": 1000, "platelets": 50000}
    for payload in (payload_cord, payload_cytopenia):
        bundle = apply_pivotal_contraindication_gates(payload, treatments)
        names = {t["name"] for t in bundle["filtered_treatments"]}
        # Todos los regímenes no-Lu-177 sobreviven
        assert names == {"Enzalutamida", "Apalutamida", "Docetaxel"}


def test_lu177_keywords_catalog_includes_all_canonical_aliases():
    """El catálogo de keywords debe incluir las variantes principales."""
    expected = {
        "lu-177", "lu 177", "lu177",
        "lutetium-177", "lutetium 177",
        "lutecio-177", "lutecio 177",
        "psma-617", "psma 617", "psma617",
        "pluvicto",
    }
    assert expected.issubset(set(KEYWORDS_LUTETIUM177))


def test_lu177_regimen_codes_catalog_includes_canonical():
    """El catálogo de regimen_codes debe incluir el canónico Pluvicto."""
    assert "LU177_PSMA617" in REGIMEN_CODES_LUTETIUM177
    assert "PLUVICTO" in REGIMEN_CODES_LUTETIUM177
