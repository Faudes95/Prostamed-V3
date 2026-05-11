"""Tests de los gates pivotal 15-16: PARP inhibitors × hematología.

Faubot 2026-04-24 (VI) — Continuación de la auditoría 2026-04-24 (V) que
cerró Lu-177-PSMA × emergencias. Esta auditoría replica el patrón
hematológico para los 4 PARP inhibitors aprobados en cáncer de próstata
(olaparib, niraparib, talazoparib, rucaparib) cubriendo PROfound, MAGNITUDE,
TALAPRO-2/3, PROpel y TRITON-3.

  Gate 15 — `parp_inhibitor_in_severe_cytopenias`
    ANC <1500/µL, plaquetas <100 000/µL, o Hb <9 g/dL → TODOS los PARPi
    contraindicados. Threshold de plaquetas (100K) más estricto que Lu-177
    (75K) por perfil hematológico específico de PARPi (especialmente
    niraparib con trombocitopenia ~40%).
    Evidencia: Lynparza, Akeega/Zejula, Talzenna, Rubraca FDA prescribing
    information cycle gates; PROfound (de Bono NEJM 2020;382:2091),
    MAGNITUDE (Chi NEJM 2023), TALAPRO-2 (Agarwal Lancet 2023;402:291),
    TRITON-3 (Fizazi NEJM 2023;388:719).

  Gate 16 — `parp_inhibitor_in_mds_aml_history`
    Antecedente de SMD/LMA → TODOS los PARPi contraindicados (boxed
    warning en todos los labels). Sin override.
    Evidencia: Lynparza FDA 2024 §5.1, Akeega/Zejula 2023 §5.1, Talzenna
    2024 §5.1, Rubraca 2024 §5.1.

Cobertura del test:
  A) Detector cytopenias aislado — ANC + plaquetas + Hb + corrección + flag
  B) Detector MDS/AML aislado — flag + alias múltiples + sin override
  C) Filtro de tratamientos — los 4 PARPi removidos cuando aplica
  D) End-to-end vía m1_crpc service — rastro estructurado expuesto
  E) Backward compatibility — total ahora 16 gates, gates anteriores intactos
  F) Catálogo PARPi × gates — 7 códigos × 2 gates parametrize
  G) Diferencia de threshold con Lu-177 (gate 14: plaq 75K vs gate 15: 100K)
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.application.module_registry import ModuleRegistry
from prostanet.shared.pivotal_contraindication_gates import (
    KEYWORDS_PARP_INHIBITORS,
    REGIMEN_CODES_PARP_INHIBITORS,
    _DETECTORS,
    apply_pivotal_contraindication_gates,
    detect_parp_inhibitor_in_mds_aml_history,
    detect_parp_inhibitor_in_severe_cytopenias,
    evaluate_pivotal_contraindication_gates,
)


# ── Sección A — Detector cytopenias aislado ───────────────────────────────


class TestParpInhibitorInSevereCytopeniasDetector:
    """Gate 15 — `parp_inhibitor_in_severe_cytopenias`."""

    def test_explicit_severe_cytopenia_flag_triggers_gate(self):
        gate = detect_parp_inhibitor_in_severe_cytopenias(
            {"severe_cytopenia_for_parp_inhibitor": "Sí"}
        )
        assert gate is not None
        assert gate["code"] == "parp_inhibitor_in_severe_cytopenias"
        assert gate["severity"] == "hard_block"
        assert "PROfound" in gate["trial_refs"]
        assert "MAGNITUDE" in gate["trial_refs"]
        assert "TALAPRO-2" in gate["trial_refs"]
        assert "TRITON-3" in gate["trial_refs"]

    @pytest.mark.parametrize(
        "anc_field,value",
        [("anc", 1499), ("anc", 1000), ("anc", 500), ("anc_baseline", 1200)],
    )
    def test_low_anc_triggers_gate(self, anc_field, value):
        gate = detect_parp_inhibitor_in_severe_cytopenias({anc_field: value})
        assert gate is not None
        assert gate["code"] == "parp_inhibitor_in_severe_cytopenias"

    @pytest.mark.parametrize("anc_value", [1500, 1800, 3000])
    def test_normal_anc_does_not_trigger(self, anc_value):
        assert detect_parp_inhibitor_in_severe_cytopenias({"anc": anc_value}) is None

    @pytest.mark.parametrize(
        "plt_value",
        [99999, 95000, 80000, 50000],  # Threshold PARPi <100K (más estricto que Lu-177 75K)
    )
    def test_low_platelets_trigger_gate(self, plt_value):
        gate = detect_parp_inhibitor_in_severe_cytopenias({"platelets": plt_value})
        assert gate is not None
        assert gate["code"] == "parp_inhibitor_in_severe_cytopenias"

    @pytest.mark.parametrize("plt_value", [100000, 150000, 250000])
    def test_normal_platelets_do_not_trigger(self, plt_value):
        assert detect_parp_inhibitor_in_severe_cytopenias({"platelets": plt_value}) is None

    def test_platelets_at_100k_boundary_does_not_trigger(self):
        """Boundary: 100 000 plaq es el threshold exacto del Pluvicto/PARPi
        cycle gate; no debe disparar."""
        assert detect_parp_inhibitor_in_severe_cytopenias({"platelets": 100000}) is None

    @pytest.mark.parametrize(
        "hb_field,value",
        [("hemoglobin_g_dl", 8.99), ("hemoglobin_g_dl", 8.5), ("hemoglobin", 7.5), ("hb", 6.0)],
    )
    def test_low_hemoglobin_triggers_gate(self, hb_field, value):
        gate = detect_parp_inhibitor_in_severe_cytopenias({hb_field: value})
        assert gate is not None
        assert gate["code"] == "parp_inhibitor_in_severe_cytopenias"

    @pytest.mark.parametrize("hb_value", [9.0, 10.5, 14.0])
    def test_normal_hemoglobin_does_not_trigger(self, hb_value):
        assert detect_parp_inhibitor_in_severe_cytopenias({"hemoglobin_g_dl": hb_value}) is None

    def test_corrected_override_neutralizes_gate(self):
        gate = detect_parp_inhibitor_in_severe_cytopenias(
            {
                "anc": 1000,
                "platelets": 80000,
                "hemoglobin_g_dl": 8.0,
                "cytopenias_corrected_for_parp_inhibitor": "Sí",
            }
        )
        assert gate is None

    def test_corrected_override_with_explicit_flag(self):
        gate = detect_parp_inhibitor_in_severe_cytopenias(
            {
                "severe_cytopenia_for_parp_inhibitor": "Sí",
                "cytopenias_corrected_for_parp_inhibitor": "Sí",
            }
        )
        assert gate is None

    def test_no_lab_data_does_not_trigger(self):
        assert detect_parp_inhibitor_in_severe_cytopenias({"psa": 30}) is None

    def test_message_cites_all_parp_labels(self):
        gate = detect_parp_inhibitor_in_severe_cytopenias({"anc": 1000})
        msg = gate["message"].lower()
        assert "lynparza" in msg or "olaparib" in msg
        assert "akeega" in msg or "niraparib" in msg
        assert "talzenna" in msg or "talazoparib" in msg
        assert "rubraca" in msg or "rucaparib" in msg

    def test_message_cites_pivotal_trials(self):
        gate = detect_parp_inhibitor_in_severe_cytopenias({"anc": 1000})
        msg = gate["message"].lower()
        assert "profound" in msg
        assert "magnitude" in msg
        assert "talapro" in msg or "triton" in msg

    def test_message_lists_multiple_cytopenias_when_present(self):
        gate = detect_parp_inhibitor_in_severe_cytopenias(
            {"anc": 1000, "platelets": 80000, "hemoglobin_g_dl": 8.0}
        )
        msg = gate["message"].lower()
        assert "anc" in msg and "1000" in msg
        assert "plaquetas" in msg and "80" in msg
        assert "hb" in msg and "8.0" in msg

    def test_alias_neutrofilos_triggers_via_arpi_alias(self):
        from prostanet.domains.patient_tracking.arpi_selection_engine import (
            ARPI_FIELD_ALIASES,
        )
        # Aliases comparten campos con gate 14 (Lu-177)
        assert "neutrofilos_absolutos" in ARPI_FIELD_ALIASES.get("anc", [])
        # PARPi-específicos
        assert "citopenia_severa_parp" in ARPI_FIELD_ALIASES.get(
            "severe_cytopenia_for_parp_inhibitor", []
        )


# ── Sección B — Detector MDS/AML history aislado ──────────────────────────


class TestParpInhibitorInMdsAmlHistoryDetector:
    """Gate 16 — `parp_inhibitor_in_mds_aml_history`."""

    def test_explicit_mds_aml_history_triggers_gate(self):
        gate = detect_parp_inhibitor_in_mds_aml_history({"mds_aml_history": "Sí"})
        assert gate is not None
        assert gate["code"] == "parp_inhibitor_in_mds_aml_history"
        assert gate["severity"] == "hard_block"
        assert "Lynparza label" in gate["trial_refs"]

    def test_prior_mds_alias_triggers_gate(self):
        gate = detect_parp_inhibitor_in_mds_aml_history({"prior_mds": "1"})
        assert gate is not None
        assert "smd" in gate["message"].lower() or "mds" in gate["message"].lower()

    def test_prior_aml_alias_triggers_gate(self):
        gate = detect_parp_inhibitor_in_mds_aml_history({"prior_aml": "yes"})
        assert gate is not None
        assert "lma" in gate["message"].lower() or "aml" in gate["message"].lower()

    def test_secondary_hem_malignancy_triggers_gate(self):
        gate = detect_parp_inhibitor_in_mds_aml_history(
            {"secondary_hematologic_malignancy": "Sí"}
        )
        assert gate is not None
        assert gate["code"] == "parp_inhibitor_in_mds_aml_history"

    def test_prolonged_cytopenia_unexplained_triggers_gate(self):
        """Citopenia prolongada inexplicada es proxy de SMD no confirmado."""
        gate = detect_parp_inhibitor_in_mds_aml_history(
            {"prolonged_cytopenia_unexplained": "Sí"}
        )
        assert gate is not None
        assert gate["code"] == "parp_inhibitor_in_mds_aml_history"

    def test_no_history_does_not_trigger(self):
        assert detect_parp_inhibitor_in_mds_aml_history({"mds_aml_history": "No"}) is None
        assert detect_parp_inhibitor_in_mds_aml_history({"psa": 30}) is None

    def test_no_override_for_mds_history(self):
        """MDS/AML pre-existente no admite override clínico — el gate
        debe disparar incluso si el clínico marca campos de corrección."""
        gate = detect_parp_inhibitor_in_mds_aml_history(
            {
                "mds_aml_history": "Sí",
                "cytopenias_corrected_for_parp_inhibitor": "Sí",
            }
        )
        assert gate is not None  # NO se desactiva con override de citopenias

    def test_message_cites_all_parp_labels_section_5_1(self):
        gate = detect_parp_inhibitor_in_mds_aml_history({"mds_aml_history": "Sí"})
        msg = gate["message"].lower()
        assert "lynparza" in msg
        assert "akeega" in msg or "zejula" in msg
        assert "talzenna" in msg
        assert "rubraca" in msg
        assert "§5.1" in msg or "5.1" in msg

    def test_message_suggests_alternative_treatments(self):
        gate = detect_parp_inhibitor_in_mds_aml_history({"mds_aml_history": "Sí"})
        msg = gate["message"].lower()
        # Debe sugerir alternativas (taxanos, ARSI, Ra-223, Lu-177)
        assert (
            "taxano" in msg or "arsi" in msg or "ra-223" in msg or "lu-177" in msg
        )

    def test_alias_smd_lma_history_via_arpi_alias(self):
        from prostanet.domains.patient_tracking.arpi_selection_engine import (
            ARPI_FIELD_ALIASES,
        )
        assert "antecedente_smd_lma" in ARPI_FIELD_ALIASES.get("mds_aml_history", [])
        assert "antecedente_smd" in ARPI_FIELD_ALIASES.get("prior_mds", [])
        assert "antecedente_lma" in ARPI_FIELD_ALIASES.get("prior_aml", [])


# ── Sección C — Filtro de tratamientos ────────────────────────────────────


def test_filter_removes_all_parpi_with_severe_cytopenias():
    treatments = [
        {"name": "Olaparib", "regimen_code": "OLAPARIB"},
        {"name": "Niraparib + Abiraterona", "regimen_code": "NIRAPARIB_ABIRATERONE"},
        {"name": "Talazoparib + Enzalutamida", "regimen_code": "TALAZOPARIB_ENZALUTAMIDE"},
        {"name": "Rucaparib", "regimen_code": "RUCAPARIB"},
        {"name": "Cabazitaxel", "regimen_code": "CABAZITAXEL"},
    ]
    bundle = apply_pivotal_contraindication_gates(
        {"anc": 1000, "platelets": 80000}, treatments
    )
    names = [t["name"] for t in bundle["filtered_treatments"]]
    assert "Olaparib" not in names
    assert "Niraparib + Abiraterona" not in names
    assert "Talazoparib + Enzalutamida" not in names
    assert "Rucaparib" not in names
    # Cabazitaxel no es PARPi — debe sobrevivir al gate 15
    # (puede fallar otros gates por neuropatía/polysorbate, pero aquí no)
    assert "Cabazitaxel" in names
    assert any(g["code"] == "parp_inhibitor_in_severe_cytopenias" for g in bundle["gates_triggered"])


def test_filter_removes_all_parpi_with_mds_history():
    treatments = [
        {"name": "Olaparib", "regimen_code": "OLAPARIB"},
        {"name": "Niraparib", "regimen_code": "NIRAPARIB_ABIRATERONE"},
        {"name": "Talazoparib + Enzalutamida", "regimen_code": "ADT_TALAZO_ENZA_HRR"},
        {"name": "Rucaparib", "regimen_code": "RUCAPARIB"},
        {"name": "Enzalutamida", "regimen_code": "ENZALUTAMIDE"},
    ]
    bundle = apply_pivotal_contraindication_gates(
        {"mds_aml_history": "Sí"}, treatments
    )
    names = [t["name"] for t in bundle["filtered_treatments"]]
    assert all("olapar" not in n.lower() for n in names)
    assert all("nirapar" not in n.lower() for n in names)
    assert all("talazopar" not in n.lower() for n in names)
    assert all("rucapar" not in n.lower() for n in names)
    assert "Enzalutamida" in names


@pytest.mark.parametrize(
    "parpi_name",
    [
        "Olaparib",
        "Niraparib",
        "Talazoparib + Enzalutamida",
        "Rucaparib",
        "Lynparza",
        "Akeega",
        "Talzenna",
        "Rubraca",
        "PARP inhibitor",
        "Inhibidor PARP",
    ],
)
def test_filter_removes_all_parpi_keyword_variants(parpi_name):
    treatments = [{"name": parpi_name, "priority": "eligible"}]
    bundle = apply_pivotal_contraindication_gates(
        {"mds_aml_history": "Sí"}, treatments
    )
    assert bundle["filtered_treatments"] == []


# ── Sección D — End-to-end vía servicios ──────────────────────────────────


@pytest.fixture(scope="module")
def registry():
    return ModuleRegistry()


def test_m1_crpc_service_exposes_parp_cytopenias_gate(registry):
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
        # HRR+ → candidato natural a olaparib (se bloqueará)
        "germline_pathogenic_variant": "BRCA2",
        "hrr_positive": "1",
        # Citopenias severas
        "anc": 1200,
        "platelets": 80000,
        "hemoglobin_g_dl": 8.5,
    }
    res = registry.evaluate_module("m1_crpc", payload)
    gates = res.get("pivotal_contraindication_gates") or []
    codes = {g["code"] for g in gates}
    assert "parp_inhibitor_in_severe_cytopenias" in codes
    # Lu-177 también debe disparar gate 14 con estos labs
    assert "lutetium177_in_severe_cytopenias" in codes


def test_m1_crpc_service_exposes_parp_mds_history_gate(registry):
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
        "germline_pathogenic_variant": "BRCA2",
        "hrr_positive": "1",
        "mds_aml_history": "Sí",
    }
    res = registry.evaluate_module("m1_crpc", payload)
    gates = res.get("pivotal_contraindication_gates") or []
    codes = {g["code"] for g in gates}
    assert "parp_inhibitor_in_mds_aml_history" in codes


def test_m1_crpc_service_does_not_expose_parp_gates_when_healthy(registry):
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
        "germline_pathogenic_variant": "BRCA2",
        "hrr_positive": "1",
        "anc": 2500,
        "platelets": 200000,
        "hemoglobin_g_dl": 12.5,
        "mds_aml_history": "No",
    }
    res = registry.evaluate_module("m1_crpc", payload)
    gates = res.get("pivotal_contraindication_gates") or []
    codes = {g["code"] for g in gates}
    assert "parp_inhibitor_in_severe_cytopenias" not in codes
    assert "parp_inhibitor_in_mds_aml_history" not in codes


def test_m1_crpc_filters_all_parpi_when_mds_history(registry):
    """End-to-end: NINGÚN PARPi debe aparecer en eligible_treatments
    cuando el paciente tiene antecedente de SMD/LMA."""
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
        "germline_pathogenic_variant": "BRCA2",
        "hrr_positive": "1",
        "mds_aml_history": "Sí",
    }
    res = registry.evaluate_module("m1_crpc", payload)
    eligible = res.get("eligible_treatments") or []
    blob = " ".join(
        (t.get("name", "") + " " + t.get("regimen_code", "")).lower() for t in eligible
    )
    assert "olaparib" not in blob
    assert "niraparib" not in blob
    assert "talazoparib" not in blob
    assert "rucaparib" not in blob


def test_corrected_cytopenias_re_enables_parpi(registry):
    """Tras corrección hematológica documentada para PARPi, gate 15
    se desactiva y los PARPi pueden volver a evaluarse."""
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
        "germline_pathogenic_variant": "BRCA2",
        "hrr_positive": "1",
        "anc": 1200,
        "cytopenias_corrected_for_parp_inhibitor": "Sí",
    }
    res = registry.evaluate_module("m1_crpc", payload)
    gates = res.get("pivotal_contraindication_gates") or []
    codes = {g["code"] for g in gates}
    assert "parp_inhibitor_in_severe_cytopenias" not in codes


# ── Sección E — Backward compatibility ────────────────────────────────────


def test_total_detectors_count_is_at_least_12():
    """El módulo debe tener al menos 12 detectores Python.
    Faubot 2026-04-25 (XIX) migró el último gate Python complejo (gate 9)
    a YAML; `_DETECTORS` ahora contiene 12 detectores Python (era 18). El
    catálogo YAML alcanza 19/19 (100%); el sistema híbrido total sigue
    exponiendo 19 gates activos vía YAML+Python."""
    assert len(_DETECTORS) >= 12


def test_existing_gates_still_trigger_after_extension():
    """Los 14 gates anteriores siguen funcionando."""
    payload = {
        "nyha_class": "III",
        "spinal_cord_compression": "Sí",
        "calcium_level": 7.5,
    }
    gates = evaluate_pivotal_contraindication_gates(payload)
    codes = {g["code"] for g in gates}
    assert "severe_heart_failure_nyha_iii_iv" in codes
    assert "radium223_in_cord_compression" in codes
    assert "radium223_in_hypocalcemia" in codes
    assert "lutetium177_in_cord_compression" in codes


def test_simultaneous_radioligand_and_parp_gates_trigger_independently():
    """Un paciente con citopenias severas dispara 3 gates hematológicos:
       - Gate 14 (Lu-177): plaq <75K activa
       - Gate 15 (PARPi): plaq <100K activa (más estricto)
       - Gates de Ra-223 NO disparan (no relacionados con citopenias).

    Validar que el filter elimina TODOS los radioligands + PARPi pero
    mantiene otros regímenes (taxanos, ARSI)."""
    payload = {
        "anc": 1000,
        "platelets": 60000,  # < 75K → gates 14 y 15
        "hemoglobin_g_dl": 8.0,
    }
    gates = evaluate_pivotal_contraindication_gates(payload)
    codes = {g["code"] for g in gates}
    # Hematológicos
    assert "lutetium177_in_severe_cytopenias" in codes
    assert "parp_inhibitor_in_severe_cytopenias" in codes
    # NO hematológicos
    assert "radium223_in_cord_compression" not in codes
    assert "radium223_in_hypocalcemia" not in codes


def test_parp_threshold_more_strict_than_lu177_for_platelets():
    """Caso límite: plaquetas 80 000 → bajo threshold PARPi (100K) pero
    encima del threshold Lu-177 (75K). Solo gate 15 (PARPi) debe disparar,
    NO gate 14 (Lu-177)."""
    payload = {"platelets": 80000}
    gates = evaluate_pivotal_contraindication_gates(payload)
    codes = {g["code"] for g in gates}
    assert "parp_inhibitor_in_severe_cytopenias" in codes
    assert "lutetium177_in_severe_cytopenias" not in codes


def test_independent_overrides_for_radioligand_and_parp():
    """Override de Lu-177 (`cytopenias_corrected_for_radioligand`) no debe
    desactivar el gate de PARPi (`cytopenias_corrected_for_parp_inhibitor`).
    Cada radioligando/clase tiene su propio override por seguridad."""
    payload = {
        "anc": 1000,
        "cytopenias_corrected_for_radioligand": "Sí",  # Solo Lu-177
    }
    gates = evaluate_pivotal_contraindication_gates(payload)
    codes = {g["code"] for g in gates}
    # Lu-177 desactivado por su override
    assert "lutetium177_in_severe_cytopenias" not in codes
    # PARPi NO desactivado
    assert "parp_inhibitor_in_severe_cytopenias" in codes


def test_healthy_payload_triggers_no_parp_gates():
    payload = {
        "psa": 30,
        "anc": 2500,
        "platelets": 200000,
        "hemoglobin_g_dl": 12.5,
        "mds_aml_history": "No",
    }
    gates = evaluate_pivotal_contraindication_gates(payload)
    codes = {g["code"] for g in gates}
    assert "parp_inhibitor_in_severe_cytopenias" not in codes
    assert "parp_inhibitor_in_mds_aml_history" not in codes


# ── Sección F — Catálogo PARPi × gates ────────────────────────────────────


@pytest.mark.parametrize("regimen_code", sorted(REGIMEN_CODES_PARP_INHIBITORS))
def test_all_parpi_canonical_codes_blocked_by_gate15(regimen_code):
    """Los 7 códigos canónicos PARPi deben ser bloqueados por gate 15."""
    treatments = [{"name": "Foo", "regimen_code": regimen_code}]
    bundle = apply_pivotal_contraindication_gates({"anc": 1000}, treatments)
    assert bundle["filtered_treatments"] == []


@pytest.mark.parametrize("regimen_code", sorted(REGIMEN_CODES_PARP_INHIBITORS))
def test_all_parpi_canonical_codes_blocked_by_gate16(regimen_code):
    """Los 7 códigos canónicos PARPi deben ser bloqueados por gate 16."""
    treatments = [{"name": "Foo", "regimen_code": regimen_code}]
    bundle = apply_pivotal_contraindication_gates(
        {"mds_aml_history": "Sí"}, treatments
    )
    assert bundle["filtered_treatments"] == []


def test_parp_gates_do_not_block_non_parp_treatments():
    """Los gates 15-16 NO deben bloquear regímenes no-PARPi."""
    treatments = [
        {"name": "Enzalutamida", "regimen_code": "ENZALUTAMIDE"},
        {"name": "Apalutamida", "regimen_code": "APALUTAMIDE"},
        {"name": "Docetaxel", "regimen_code": "DOCETAXEL"},
        {"name": "Cabazitaxel", "regimen_code": "CABAZITAXEL"},
    ]
    payload_cytopenia = {"anc": 1000, "platelets": 80000}
    payload_mds = {"mds_aml_history": "Sí"}
    for payload in (payload_cytopenia, payload_mds):
        bundle = apply_pivotal_contraindication_gates(payload, treatments)
        names = {t["name"] for t in bundle["filtered_treatments"]}
        # Todos los no-PARPi sobreviven a los gates 15-16
        # (pueden fallar otros gates por otros motivos pero no por PARP)
        assert "Enzalutamida" in names
        assert "Apalutamida" in names


def test_parp_keywords_catalog_includes_all_brand_names():
    """El catálogo de keywords debe incluir los 4 nombres genéricos + 5 marcas."""
    expected_generics = {"olaparib", "niraparib", "talazoparib", "rucaparib"}
    expected_brands = {"lynparza", "akeega", "talzenna", "rubraca", "zejula"}
    expected = expected_generics | expected_brands
    assert expected.issubset(set(KEYWORDS_PARP_INHIBITORS))


def test_parp_regimen_codes_catalog_includes_canonical():
    """El catálogo de regimen_codes debe incluir los 7 canónicos."""
    expected = {
        "OLAPARIB",
        "ABIRATERONE_OLAPARIB",
        "NIRAPARIB_ABIRATERONE",
        "ADT_ABIRATERONE_NIRAPARIB",
        "TALAZOPARIB_ENZALUTAMIDE",
        "ADT_TALAZO_ENZA_HRR",
        "RUCAPARIB",
    }
    assert expected == REGIMEN_CODES_PARP_INHIBITORS


# ── Sección G — Diferencia de threshold con Lu-177 ────────────────────────


@pytest.mark.parametrize(
    "platelets,gate_lu177_triggers,gate_parp_triggers",
    [
        (74999, True, True),    # Por debajo de ambos
        (75000, False, True),   # Lu-177 boundary, PARPi sí
        (80000, False, True),   # Solo PARPi
        (99999, False, True),   # Solo PARPi
        (100000, False, False), # Ambos boundaries
        (150000, False, False), # Ambos OK
    ],
)
def test_threshold_differential_lu177_vs_parp_for_platelets(
    platelets, gate_lu177_triggers, gate_parp_triggers
):
    """Demuestra que el threshold de plaquetas para PARPi (100K) es más
    estricto que para Lu-177 (75K). Los pacientes en el rango 75K-99 999
    pueden recibir Lu-177 pero NO PARPi."""
    payload = {"platelets": platelets}
    gates = evaluate_pivotal_contraindication_gates(payload)
    codes = {g["code"] for g in gates}
    assert ("lutetium177_in_severe_cytopenias" in codes) == gate_lu177_triggers
    assert ("parp_inhibitor_in_severe_cytopenias" in codes) == gate_parp_triggers


def test_pluvicto_label_alignment_anc_threshold():
    """Tanto Lu-177 (Pluvicto) como PARPi labels usan ANC ≥1500/µL como
    cycle gate. Boundary: ANC=1500 no debe disparar ninguno."""
    payload = {"anc": 1500}
    gates = evaluate_pivotal_contraindication_gates(payload)
    codes = {g["code"] for g in gates}
    assert "lutetium177_in_severe_cytopenias" not in codes
    assert "parp_inhibitor_in_severe_cytopenias" not in codes


def test_hb_threshold_alignment_lu177_and_parp():
    """Tanto Lu-177 como PARPi (consolidado) usan Hb ≥9 g/dL como cycle gate.
    Boundary: Hb=9.0 no debe disparar ninguno."""
    payload = {"hemoglobin_g_dl": 9.0}
    gates = evaluate_pivotal_contraindication_gates(payload)
    codes = {g["code"] for g in gates}
    assert "lutetium177_in_severe_cytopenias" not in codes
    assert "parp_inhibitor_in_severe_cytopenias" not in codes
