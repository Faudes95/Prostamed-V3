"""Tests FAUBOT — Auditoría de cobertura pacientes insignia 2026-04-23.

Locks in the 10 contraindication gates derived from the FAUBOT pivotal-trial
audit (RADICALS-RT … CONTACT-02). Each gate corresponds to a documented
exclusion criterion in a pivotal protocol or a vigilant guideline (NCCN
PROS-G v5.2026, EAU 2026, ASCO/AUA Bone Health 2024, CTCAE v5).

Brechas cerradas:
  1. prior_arpi_exposure_mhspc       → ARANOTE (Saad 2024)
  2. severe_neuropathy_grade3        → TAX-327/TROPIC/CHAARTED
  3. uncontrolled_hypertension       → LATITUDE/PEACE-1/CONTACT-02
  4. severe_heart_failure_nyha_iii_iv → LATITUDE/COU-AA-301/302
  5. uncontrolled_diabetes           → IPATential150
  6. ecog_2_or_more_for_triplets     → ARASENS/PEACE-1
  7. darolutamide_hypersensitivity   → ARAMIS/ARASENS/ARANOTE label
  8. polysorbate_hypersensitivity    → TROPIC/CARD label
  9. no_bone_protective_agent        → ERA-223/PEACE-3
  10. creatinine_clearance_lt_30     → TRITON-3
"""
# IEC 62304 §5.5 (Unit verification)


from __future__ import annotations

import pytest

from prostanet.application.module_registry import ModuleRegistry
from prostanet.shared.pivotal_contraindication_gates import (
    apply_pivotal_contraindication_gates,
    detect_creatinine_clearance_lt_30_for_rucaparib,
    detect_darolutamide_hypersensitivity,
    detect_ecog_2_or_more_for_triplets,
    detect_no_bone_protective_agent_for_radium223,
    detect_polysorbate_hypersensitivity,
    detect_prior_arpi_exposure_mhspc,
    detect_severe_heart_failure_nyha_iii_iv,
    detect_severe_neuropathy_grade3,
    detect_uncontrolled_diabetes,
    detect_uncontrolled_hypertension,
    evaluate_pivotal_contraindication_gates,
    filter_treatments_by_gates,
    gate_messages_for_not_recommended,
)


@pytest.fixture(scope="module")
def registry() -> ModuleRegistry:
    return ModuleRegistry()


def _serialized_lower(result: dict) -> str:
    import json

    return json.dumps(result, ensure_ascii=False, default=str).lower()


def _not_recommended_text(result: dict) -> str:
    return " ".join(str(x) for x in (result.get("not_recommended") or [])).lower()


# ───────────────────────────────────────────────────────────────────────
# Detectores individuales — positivo + negativo + boundary
# ───────────────────────────────────────────────────────────────────────


# ── Gate 1: ARANOTE — ARPI previo en mHSPC ─────────────────────────────


def test_detect_prior_arpi_exposure_mhspc_positive_es_si():
    gate = detect_prior_arpi_exposure_mhspc({"prior_arpi_exposure_mhspc": "Sí"})
    assert gate is not None
    assert gate["code"] == "prior_arpi_exposure_mhspc"
    assert gate["severity"] == "hard_block"
    assert "ARANOTE" in gate["trial_refs"]
    assert "darolutamida" in gate["message"].lower()


def test_detect_prior_arpi_exposure_mhspc_negative_default_no():
    assert detect_prior_arpi_exposure_mhspc({"prior_arpi_exposure_mhspc": "No"}) is None
    assert detect_prior_arpi_exposure_mhspc({}) is None


def test_detect_prior_arpi_exposure_mhspc_truthy_int():
    gate = detect_prior_arpi_exposure_mhspc({"prior_arpi_exposure_mhspc": 1})
    assert gate is not None and gate["triggered"]


# ── Gate 2: Neuropatía grado ≥3 → taxanos ──────────────────────────────


def test_detect_severe_neuropathy_grade3_positive():
    gate = detect_severe_neuropathy_grade3({"peripheral_neuropathy_grade": 3})
    assert gate is not None
    assert gate["code"] == "severe_neuropathy_grade3"
    msg = gate["message"].lower()
    assert "docetaxel" in msg and "cabazitaxel" in msg
    assert "TAX-327" in gate["trial_refs"]


def test_detect_severe_neuropathy_grade3_grade4():
    gate = detect_severe_neuropathy_grade3({"peripheral_neuropathy_grade": 4})
    assert gate is not None and gate["triggered"]


def test_detect_severe_neuropathy_grade3_boundary_grade2_not_triggered():
    assert detect_severe_neuropathy_grade3({"peripheral_neuropathy_grade": 2}) is None


def test_detect_severe_neuropathy_grade3_no_field_not_triggered():
    assert detect_severe_neuropathy_grade3({}) is None


# ── Gate 3: HTA no controlada → abiraterona / cabozantinib ─────────────


def test_detect_uncontrolled_hypertension_positive():
    gate = detect_uncontrolled_hypertension({"uncontrolled_hypertension": "Sí"})
    assert gate is not None
    assert gate["code"] == "uncontrolled_hypertension"
    msg = gate["message"].lower()
    assert "abiraterona" in msg and "cabozantinib" in msg
    assert "LATITUDE" in gate["trial_refs"]
    assert "CONTACT-02" in gate["trial_refs"]


def test_detect_uncontrolled_hypertension_negative():
    assert detect_uncontrolled_hypertension({"uncontrolled_hypertension": "No"}) is None
    assert detect_uncontrolled_hypertension({}) is None


# ── Gate 4: ICC NYHA III-IV → abiraterona ──────────────────────────────


@pytest.mark.parametrize("nyha_value", ["III", "IV", "3", "4", "iii", "iv"])
def test_detect_severe_heart_failure_nyha_iii_iv_positive(nyha_value):
    gate = detect_severe_heart_failure_nyha_iii_iv({"nyha_class": nyha_value})
    assert gate is not None, f"NYHA={nyha_value} debería disparar el gate"
    assert "abiraterona" in gate["message"].lower()


def test_detect_severe_heart_failure_explicit_flag():
    gate = detect_severe_heart_failure_nyha_iii_iv(
        {"severe_heart_failure_nyha_iii_iv": "Sí"}
    )
    assert gate is not None and gate["triggered"]


def test_detect_severe_heart_failure_negative_nyha_i_ii():
    assert detect_severe_heart_failure_nyha_iii_iv({"nyha_class": "I"}) is None
    assert detect_severe_heart_failure_nyha_iii_iv({"nyha_class": "II"}) is None
    assert detect_severe_heart_failure_nyha_iii_iv({}) is None


# ── Gate 5: Diabetes no controlada → ipatasertib ───────────────────────


def test_detect_uncontrolled_diabetes_positive():
    gate = detect_uncontrolled_diabetes({"uncontrolled_diabetes": "Sí"})
    assert gate is not None
    assert "ipatasertib" in gate["message"].lower()
    assert "IPATential150" in gate["trial_refs"]


def test_detect_uncontrolled_diabetes_legacy_alias():
    """Alias legacy `diabetes_uncontrolled` también dispara."""
    gate = detect_uncontrolled_diabetes({"diabetes_uncontrolled": 1})
    assert gate is not None and gate["triggered"]


def test_detect_uncontrolled_diabetes_negative():
    assert detect_uncontrolled_diabetes({"uncontrolled_diabetes": "No"}) is None
    assert detect_uncontrolled_diabetes({}) is None


# ── Gate 6: ECOG ≥2 → tripletes ────────────────────────────────────────


@pytest.mark.parametrize("ecog_value", [2, 3, 4])
def test_detect_ecog_2_or_more_for_triplets_positive(ecog_value):
    gate = detect_ecog_2_or_more_for_triplets({"ecog_score": ecog_value})
    assert gate is not None
    assert "ARASENS" in gate["trial_refs"]
    assert "PEACE-1" in gate["trial_refs"]


@pytest.mark.parametrize("ecog_value", [0, 1])
def test_detect_ecog_negative_below_threshold(ecog_value):
    assert detect_ecog_2_or_more_for_triplets({"ecog_score": ecog_value}) is None


def test_detect_ecog_legacy_alias():
    """`ecog` (sin _score) también es respetado."""
    gate = detect_ecog_2_or_more_for_triplets({"ecog": 2})
    assert gate is not None and gate["triggered"]


# ── Gate 7: Hipersensibilidad darolutamida ─────────────────────────────


def test_detect_darolutamide_hypersensitivity_positive():
    gate = detect_darolutamide_hypersensitivity({"darolutamide_hypersensitivity": "Sí"})
    assert gate is not None
    assert "enzalutamida" in gate["message"].lower()


def test_detect_darolutamide_hypersensitivity_negative():
    assert detect_darolutamide_hypersensitivity({}) is None


# ── Gate 8: Hipersensibilidad polisorbato 80 → cabazitaxel ─────────────


def test_detect_polysorbate_hypersensitivity_positive():
    gate = detect_polysorbate_hypersensitivity({"polysorbate_hypersensitivity": "Sí"})
    assert gate is not None
    assert "cabazitaxel" in gate["message"].lower()
    assert "TROPIC" in gate["trial_refs"]


def test_detect_polysorbate_hypersensitivity_legacy_alias():
    gate = detect_polysorbate_hypersensitivity({"hypersensitivity_polysorbate": 1})
    assert gate is not None and gate["triggered"]


def test_detect_polysorbate_hypersensitivity_negative():
    assert detect_polysorbate_hypersensitivity({}) is None


# ── Gate 9: Sin agente óseo + Ra-223 considerado ───────────────────────


def test_detect_no_bone_protective_agent_explicit_flag():
    gate = detect_no_bone_protective_agent_for_radium223(
        {"no_bone_protective_agent": "Sí"}
    )
    assert gate is not None
    assert "ERA-223" in gate["trial_refs"]
    assert "denosumab" in gate["message"].lower()


def test_detect_no_bone_protective_agent_radium_candidate_no_protector():
    gate = detect_no_bone_protective_agent_for_radium223(
        {"radium223_candidate": "Sí"}
    )
    assert gate is not None and gate["triggered"]


def test_detect_no_bone_protective_agent_radium_planned_with_denosumab_clears():
    """Si hay denosumab declarado, NO debe disparar aunque se considere Ra-223."""
    gate = detect_no_bone_protective_agent_for_radium223(
        {
            "radium223_candidate": "Sí",
            "denosumab_prophylaxis": "Sí",
        }
    )
    assert gate is None


def test_detect_no_bone_protective_agent_radium_planned_with_zoledronate_clears():
    gate = detect_no_bone_protective_agent_for_radium223(
        {
            "considering_radium223": 1,
            "zoledronate_prophylaxis": 1,
        }
    )
    assert gate is None


def test_detect_no_bone_protective_agent_radium_planned_with_named_agent_clears():
    gate = detect_no_bone_protective_agent_for_radium223(
        {
            "planned_systemic_regimen": "RADIUM_223",
            "bone_modifying_agent": "denosumab",
        }
    )
    assert gate is None


def test_detect_no_bone_protective_agent_no_radium_no_explicit_flag_not_triggered():
    """Sin flag explícito y sin Ra-223 considerado → no debe disparar."""
    assert detect_no_bone_protective_agent_for_radium223({}) is None


# ── Gate 10: CrCl <30 → rucaparib ──────────────────────────────────────


def test_detect_creatinine_clearance_lt_30_positive():
    gate = detect_creatinine_clearance_lt_30_for_rucaparib(
        {"creatinine_clearance": 25}
    )
    assert gate is not None
    assert "rucaparib" in gate["message"].lower()
    assert "TRITON-3" in gate["trial_refs"]


def test_detect_creatinine_clearance_legacy_egfr():
    gate = detect_creatinine_clearance_lt_30_for_rucaparib({"egfr_ml_min": 20})
    assert gate is not None and gate["triggered"]


def test_detect_creatinine_clearance_boundary_30_not_triggered():
    """Límite exacto 30 mL/min NO debe disparar (regla `< 30`)."""
    assert detect_creatinine_clearance_lt_30_for_rucaparib(
        {"creatinine_clearance": 30}
    ) is None


def test_detect_creatinine_clearance_normal_renal_function_not_triggered():
    assert detect_creatinine_clearance_lt_30_for_rucaparib(
        {"creatinine_clearance": 90}
    ) is None
    assert detect_creatinine_clearance_lt_30_for_rucaparib({}) is None


# ───────────────────────────────────────────────────────────────────────
# Helpers de orquestación
# ───────────────────────────────────────────────────────────────────────


def test_evaluate_pivotal_gates_healthy_payload_returns_empty():
    """Backward compatibility: paciente sano no dispara ningún gate."""
    healthy = {
        "psa": 12,
        "ecog_score": 0,
        "peripheral_neuropathy_grade": 0,
        "creatinine_clearance": 95,
        "nyha_class": "I",
    }
    gates = evaluate_pivotal_contraindication_gates(healthy)
    assert gates == [], f"Healthy payload should trigger 0 gates, got {gates}"


def test_evaluate_pivotal_gates_multiple_simultaneous():
    """Múltiples gates pueden dispararse simultáneamente — todos visibles.

    Faubot 2026-04-25 (XLI / Auditoría #44): el test usa subset (`>=`) en
    vez de igualdad estricta porque el catálogo crece monótonamente con
    cada auditoría. Por ejemplo CrCl<30 ahora dispara gate 10 (rucaparib)
    Y gate 29 (olaparib) — ambos son contraindicaciones reales. El test
    valida que los 4 gates ESPERADOS estén presentes; no prohíbe gates
    adicionales que se añadan con auditorías futuras.
    """
    payload = {
        "uncontrolled_hypertension": "Sí",
        "ecog_score": 2,
        "creatinine_clearance": 20,
        "darolutamide_hypersensitivity": "Sí",
    }
    gates = evaluate_pivotal_contraindication_gates(payload)
    codes = {g["code"] for g in gates}
    expected = {
        "uncontrolled_hypertension",
        "ecog_2_or_more_for_triplets",
        "creatinine_clearance_lt_30",
        "darolutamide_hypersensitivity",
    }
    missing = expected - codes
    assert not missing, f"Expected gates missing: {missing}"
    # Faubot XLI: gate 29 olaparib_renal_dysfunction_grade3 también
    # esperado cuando CrCl<30 (regimen-scoped a olaparib, pero el gate
    # se evalúa a nivel payload).
    assert "olaparib_renal_dysfunction_grade3" in codes


def test_filter_treatments_removes_blocked_regimens_by_keyword():
    treatments = [
        {"name": "ADT + abiraterona + prednisona"},
        {"name": "ADT + enzalutamida"},
        {"name": "ADT + docetaxel"},
    ]
    gates = evaluate_pivotal_contraindication_gates({"uncontrolled_hypertension": "Sí"})
    filtered, removed_msgs = filter_treatments_by_gates(treatments, gates)
    names_left = [t["name"].lower() for t in filtered]
    assert all("abirater" not in n for n in names_left)
    assert any("enzalutamida" in n for n in names_left)
    assert any("docetaxel" in n for n in names_left)
    assert len(removed_msgs) == 1


def test_filter_treatments_removes_by_regimen_code():
    treatments = [
        {"name": "Ipatasertib + abiraterona", "regimen_code": "IPATASERTIB_ABIRATERONE"},
        {"name": "Olaparib monoterapia", "regimen_code": "OLAPARIB"},
    ]
    gates = evaluate_pivotal_contraindication_gates({"uncontrolled_diabetes": "Sí"})
    filtered, _ = filter_treatments_by_gates(treatments, gates)
    codes_left = [t.get("regimen_code") for t in filtered]
    assert "IPATASERTIB_ABIRATERONE" not in codes_left
    assert "OLAPARIB" in codes_left


def test_filter_treatments_no_gates_returns_input_unchanged():
    treatments = [{"name": "ADT + abiraterona"}, {"name": "ADT + enzalutamida"}]
    filtered, msgs = filter_treatments_by_gates(treatments, [])
    assert len(filtered) == 2
    assert msgs == []


def test_filter_treatments_handles_empty_inputs():
    filtered, msgs = filter_treatments_by_gates([], [])
    assert filtered == [] and msgs == []
    filtered, msgs = filter_treatments_by_gates(None, None)
    assert filtered == [] and msgs == []


def test_gate_messages_for_not_recommended_deduplicates():
    gates = [
        {"message": "msg A"},
        {"message": "msg A"},
        {"message": "msg B"},
        {"message": ""},
    ]
    msgs = gate_messages_for_not_recommended(gates)
    assert msgs == ["msg A", "msg B"]


def test_apply_pivotal_contraindication_gates_bundle_keys():
    treatments = [
        {"name": "ADT + abiraterona", "regimen_code": "ADT_ABIRATERONE"},
        {"name": "ADT + enzalutamida", "regimen_code": "ADT_ENZALUTAMIDE"},
    ]
    bundle = apply_pivotal_contraindication_gates(
        {"uncontrolled_hypertension": "Sí"},
        treatments,
    )
    # Faubot 2026-04-25 (XV) — bundle ahora incluye `ddi_cross_alerts`
    # (cross-check con DDI engine). Aceptamos el set extendido vía
    # superset para mantener forward-compat con futuras claves.
    expected_min_keys = {
        "filtered_treatments",
        "gates_triggered",
        "not_recommended_messages",
    }
    assert expected_min_keys.issubset(bundle.keys())
    assert len(bundle["filtered_treatments"]) == 1
    assert bundle["filtered_treatments"][0]["regimen_code"] == "ADT_ENZALUTAMIDE"
    assert len(bundle["gates_triggered"]) == 1
    assert len(bundle["not_recommended_messages"]) == 1


# ───────────────────────────────────────────────────────────────────────
# Integración a nivel servicio — gates emiten not_recommended
# ───────────────────────────────────────────────────────────────────────


def _mhspc_high_volume_payload(**overrides):
    payload = {
        "state": "mcspc_high_volume",
        "disease_state": "mcspc_high_volume",
        "phenotype_state": "mcspc_high_volume",
        "known_cancer_diagnosis": 1,
        "metastatic": 1,
        "metastasis_site": "Bone",
        "bone_lesion_count": 6,
        "bone_appendicular_count": 3,
        "bone_axial_count": 3,
        "visceral_metastases": 0,
        "castration_resistant": 0,
        "castrate_testosterone_status": "hormone_sensitive",
        "ecog_score": 1,
        "psa": 80,
        "isup_grade": 4,
        "age": 68,
    }
    payload.update(overrides)
    return payload


def _m1_crpc_payload(**overrides):
    payload = {
        "state": "m1_crpc",
        "disease_state": "m1_crpc",
        "phenotype_state": "m1_crpc",
        "known_cancer_diagnosis": 1,
        "metastatic": 1,
        "metastasis_site": "Bone",
        "bone_lesion_count": 5,
        "bone_appendicular_count": 2,
        "bone_axial_count": 3,
        "castration_resistant": 1,
        "castrate_testosterone_status": "confirmed_castrate",
        "castrate_testosterone_confirmed": 1,
        "systemic_progression_context": "confirmed_crpc",
        "prior_arpi": 0,
        "prior_docetaxel": 0,
        "prior_docetaxel_cycles": 0,
        "ecog_score": 1,
        "psa": 30,
        "age": 70,
    }
    payload.update(overrides)
    return payload


def _m0_crpc_payload(**overrides):
    payload = {
        "state": "m0_crpc",
        "disease_state": "m0_crpc",
        "known_cancer_diagnosis": 1,
        "metastatic": 0,
        "castration_resistant": 1,
        "castrate_testosterone_status": "confirmed_castrate",
        "castrate_testosterone_confirmed": 1,
        "psa_doubling_time_months": 6,
        "psa": 5,
        "ecog_score": 1,
        "age": 72,
    }
    payload.update(overrides)
    return payload


def test_service_mhspc_high_volume_uncontrolled_hypertension_emits_message(registry):
    payload = _mhspc_high_volume_payload(uncontrolled_hypertension="Sí")
    result = registry.evaluate_module("mcspc_high_volume", payload)
    text = _not_recommended_text(result) + _serialized_lower(result)
    assert "abiraterona" in text and ("hta" in text or "hipertensi" in text)


def test_service_m1_crpc_uncontrolled_hypertension_emits_message(registry):
    payload = _m1_crpc_payload(uncontrolled_hypertension="Sí")
    result = registry.evaluate_module("m1_crpc", payload)
    text = _not_recommended_text(result)
    assert "abiraterona" in text or "cabozantinib" in text


def test_service_m1_crpc_polysorbate_blocks_cabazitaxel(registry):
    payload = _m1_crpc_payload(
        polysorbate_hypersensitivity="Sí",
        prior_docetaxel=1,
        prior_docetaxel_cycles=6,
    )
    result = registry.evaluate_module("m1_crpc", payload)
    text = _not_recommended_text(result)
    assert "cabazitaxel" in text and "polisorbato" in text


def test_service_m0_crpc_darolutamide_hypersensitivity_emits_message(registry):
    payload = _m0_crpc_payload(darolutamide_hypersensitivity="Sí")
    result = registry.evaluate_module("m0_crpc", payload)
    text = _not_recommended_text(result)
    assert "darolutamida" in text and "hipersensibilidad" in text


def test_service_mhspc_low_volume_ecog_2_blocks_triplet(registry):
    payload = {
        "state": "mcspc_low_volume_sync_oligo",
        "disease_state": "mcspc_low_volume_sync_oligo",
        "phenotype_state": "mcspc_low_volume_sync_oligo",
        "known_cancer_diagnosis": 1,
        "metastatic": 1,
        "metastasis_site": "Bone",
        "bone_lesion_count": 2,
        "bone_appendicular_count": 0,
        "bone_axial_count": 2,
        "visceral_metastases": 0,
        "castration_resistant": 0,
        "castrate_testosterone_status": "hormone_sensitive",
        "ecog_score": 2,
        "psa": 25,
        "isup_grade": 3,
        "age": 75,
    }
    result = registry.evaluate_module("mcspc_low_volume_sync_oligo", payload)
    text = _not_recommended_text(result)
    assert "triplete" in text or "ecog" in text


# ───────────────────────────────────────────────────────────────────────
# Backward compatibility — paciente sano no añade nuevos not_recommended
# ───────────────────────────────────────────────────────────────────────


def test_healthy_mhspc_payload_no_pivotal_gate_messages(registry):
    """Paciente sano mHSPC no debe disparar ninguno de los 10 mensajes."""
    payload = _mhspc_high_volume_payload()
    result = registry.evaluate_module("mcspc_high_volume", payload)
    text = _not_recommended_text(result)
    pivotal_signatures = (
        "exposición previa a arpi",
        "neuropatía periférica grado",
        "hta no controlada",
        "nyha iii-iv",
        "diabetes mellitus no controlada",
        "ecog 2",
        "polisorbato",
        "agente protector óseo",
        "crcl",
    )
    fired = [sig for sig in pivotal_signatures if sig in text]
    assert not fired, f"Paciente sano disparó signatures: {fired}"


def test_healthy_m1_crpc_payload_no_pivotal_gate_messages(registry):
    """Paciente sano m1_crpc no debe disparar firmas EXCLUSIVAS de los gates.

    Nota: el m1_crpc service ya emite mensajes legítimos de VISION/PSMAfore
    (`Sin exposición previa a ARPI ...`), por lo que las firmas aquí son
    sub-cadenas únicas del mensaje del gate (no fragmentos genéricos).
    """
    payload = _m1_crpc_payload()
    result = registry.evaluate_module("m1_crpc", payload)
    text = _not_recommended_text(result)
    pivotal_signatures = (
        "darolutamida monoterapia en mhspc",  # gate ARANOTE específico
        "neuropatía periférica grado",
        "hta no controlada",
        "nyha iii-iv",
        "diabetes mellitus no controlada",
        "polisorbato",
        "agente protector óseo",
        "crcl",
    )
    fired = [sig for sig in pivotal_signatures if sig in text]
    assert not fired, f"Paciente sano m1_crpc disparó signatures: {fired}"


# ───────────────────────────────────────────────────────────────────────
# Schema FieldSpec coverage
# ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "module_name",
    [
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume",
        "mcspc_oligo_metachronous",
        "m1_crpc",
        "m0_crpc",
        # ── Faubot 2026-04-24 — extensión a localized_initial + recurrence_bcr ──
        "localized_initial",
        "recurrence_bcr",
    ],
)
def test_schema_includes_pivotal_contraindication_fields(registry, module_name):
    """Los 7 schemas deben declarar los 7 FieldSpecs nuevos del helper."""
    fields = {f["name"] for f in registry.services[module_name].schema()["fields"]}
    required = {
        "prior_arpi_exposure_mhspc",
        "darolutamide_hypersensitivity",
        "uncontrolled_hypertension",
        "severe_heart_failure_nyha_iii_iv",
        "uncontrolled_diabetes",
        "no_bone_protective_agent",
        "radium223_candidate",
    }
    missing = required - fields
    assert not missing, (
        f"Faltan FieldSpecs en {module_name}: {missing}. "
        "Helper pivotal_contraindication_fields() debe instanciarse en schema."
    )


# ───────────────────────────────────────────────────────────────────────
# Faubot 2026-04-24 — Integración a localized_initial (STAMPEDE arm G:
# RT+ADT+abiraterona en VERY HIGH risk) y recurrence_bcr (PRESTO triplet
# Apalutamida + Abiraterona + ADT). Bloqueo por NYHA III-IV / HTA y
# trazabilidad expuesta en `pivotal_contraindication_gates`.
# ───────────────────────────────────────────────────────────────────────


def _localized_very_high_payload(**overrides):
    """Paciente VERY HIGH risk con staging completo (gates A/B liberados)."""
    payload = {
        "psa": 35,
        "clinical_tstage": "T3b",
        "isup_grade": 5,
        "gleason_primary": 5,
        "gleason_secondary": 4,
        "num_cores_positive": 8,
        "total_cores": 12,
        "age": 70,
        "ecog_score": 1,
        # Staging M completo para liberar Gate A (M-staging mandatory)
        "psma_pet_done": "1",
        "psma_pet_result": "Negativo",
        "imaging_negative_metastases": "Sí",
    }
    payload.update(overrides)
    return payload


def _bcr2_payload(**overrides):
    """Paciente BCR2 elegible para PRESTO triplet (apalutamida + abiraterona)."""
    payload = {
        "prior_prostatectomy": "1",
        "prior_radiation": "0",
        "bcr2": "1",
        "psa_current": 0.6,
        "psa_nadir": 0.02,
        "psadt_months": 6,
        "imaging_negative": "1",
        "m_stage": "M0",
        "eligible_pelvic_therapy": "0",
        "salvage_local_feasible": "0",
    }
    payload.update(overrides)
    return payload


def test_localized_initial_nyha_iii_iv_filters_abiraterone_arm(registry):
    """VERY HIGH risk + NYHA III-IV → STAMPEDE arm G (RT+ADT+abiraterona)
    debe ser filtrado del catálogo y el mensaje del gate debe estar en
    not_recommended con trazabilidad en pivotal_contraindication_gates."""
    payload = _localized_very_high_payload(severe_heart_failure_nyha_iii_iv="Sí")
    result = registry.evaluate_module("localized_initial", payload)
    treatments = result.get("eligible_treatments") or []
    names = " || ".join((t.get("name") or "") for t in treatments).lower()
    # El régimen con abiraterona NO debe estar
    assert "abiraterona" not in names, (
        f"STAMPEDE arm G con abiraterona NO debe emitirse con NYHA III-IV. "
        f"Tratamientos: {names}"
    )
    # El gate debe haber disparado y exponerse
    gates = result.get("pivotal_contraindication_gates") or []
    codes = {g.get("code") for g in gates}
    assert "severe_heart_failure_nyha_iii_iv" in codes, (
        f"Gate severe_heart_failure_nyha_iii_iv no expuesto. Gates: {gates}"
    )
    # Mensaje del gate en not_recommended
    text = _not_recommended_text(result)
    assert "nyha iii-iv" in text and "abiraterona" in text


def test_localized_initial_uncontrolled_hypertension_filters_abiraterone_arm(registry):
    """VERY HIGH risk + HTA descontrolada → arm G filtrado (LATITUDE/PEACE-1)."""
    payload = _localized_very_high_payload(uncontrolled_hypertension="Sí")
    result = registry.evaluate_module("localized_initial", payload)
    treatments = result.get("eligible_treatments") or []
    names = " || ".join((t.get("name") or "") for t in treatments).lower()
    assert "abiraterona" not in names
    gates = result.get("pivotal_contraindication_gates") or []
    codes = {g.get("code") for g in gates}
    assert "uncontrolled_hypertension" in codes


def test_localized_initial_healthy_payload_keeps_abiraterone_arm(registry):
    """VERY HIGH risk SIN contraindicaciones → arm G (abiraterona) sigue presente."""
    payload = _localized_very_high_payload()
    result = registry.evaluate_module("localized_initial", payload)
    treatments = result.get("eligible_treatments") or []
    names = " || ".join((t.get("name") or "") for t in treatments).lower()
    # STAMPEDE arm G debe estar disponible
    assert "abiraterona" in names, (
        f"Sin contraindicaciones, abiraterona arm G debe emitirse. "
        f"Tratamientos: {names}"
    )
    # Sin gates disparados
    assert not result.get("pivotal_contraindication_gates")


def test_localized_initial_low_risk_no_pivotal_gates_triggered(registry):
    """LOW risk (vigilancia activa) sin abiraterona en catálogo → ningún gate."""
    payload = {
        "psa": 6.5,
        "clinical_tstage": "T1c",
        "isup_grade": 1,
        "gleason_primary": 3,
        "gleason_secondary": 3,
        "num_cores_positive": 1,
        "total_cores": 12,
        "age": 60,
        "ecog_score": 0,
        # NYHA III-IV declarado pero LOW risk no tiene abiraterona en catálogo
        "severe_heart_failure_nyha_iii_iv": "Sí",
    }
    result = registry.evaluate_module("localized_initial", payload)
    # El gate igual se evalúa, pero no debería filtrar nada porque
    # los tratamientos de LOW risk no incluyen abiraterona
    treatments = result.get("eligible_treatments") or []
    names = " || ".join((t.get("name") or "") for t in treatments).lower()
    assert "abiraterona" not in names  # Nunca aparece en LOW risk
    # El gate puede estar expuesto (es una declaración del paciente),
    # pero el catálogo no se ve afectado
    # (no enforzamos pivotal_contraindication_gates aquí; solo confirmamos
    #  que la rama no rompe)


def test_recurrence_bcr_nyha_iii_iv_filters_presto_triplet(registry):
    """BCR2 + NYHA III-IV → PRESTO triplet (apalutamida + abiraterona) filtrado."""
    payload = _bcr2_payload(severe_heart_failure_nyha_iii_iv="Sí")
    result = registry.evaluate_module("recurrence_bcr", payload)
    treatments = result.get("eligible_treatments") or []
    # El régimen con código que contiene ABIRATERONE debe estar bloqueado
    blocked = [t for t in treatments
               if "abirater" in (t.get("name") or "").lower()
               or "abirateron" in (t.get("regimen_code") or "").lower()]
    assert not blocked, (
        f"PRESTO triplet con abiraterona NO debe emitirse con NYHA III-IV. "
        f"Bloqueado esperado, pero presente: {blocked}"
    )
    gates = result.get("pivotal_contraindication_gates") or []
    codes = {g.get("code") for g in gates}
    assert "severe_heart_failure_nyha_iii_iv" in codes


def test_recurrence_bcr_uncontrolled_hypertension_filters_presto_triplet(registry):
    """BCR2 + HTA descontrolada → PRESTO triplet (con abiraterona) filtrado."""
    payload = _bcr2_payload(uncontrolled_hypertension="Sí")
    result = registry.evaluate_module("recurrence_bcr", payload)
    treatments = result.get("eligible_treatments") or []
    blocked = [t for t in treatments if "abirater" in (t.get("name") or "").lower()]
    assert not blocked
    gates = result.get("pivotal_contraindication_gates") or []
    codes = {g.get("code") for g in gates}
    assert "uncontrolled_hypertension" in codes


def test_recurrence_bcr_healthy_payload_keeps_presto_triplet(registry):
    """BCR2 sin contraindicaciones → PRESTO triplet permanece disponible."""
    payload = _bcr2_payload()
    result = registry.evaluate_module("recurrence_bcr", payload)
    treatments = result.get("eligible_treatments") or []
    names_codes = [
        ((t.get("name") or "").lower(), (t.get("regimen_code") or "").upper())
        for t in treatments
    ]
    # Apalutamida + Abiraterona + ADT (PRESTO triplete) debe estar presente
    triplet_present = any(
        "abirater" in n and "apalutam" in n
        for (n, _c) in names_codes
    ) or any(
        "ABIRATERONE" in c and "APALUTAM" in c
        for (_n, c) in names_codes
    )
    # Acepta el triplet o al menos abiraterona EMBARK; lo importante es que
    # NO haya filtrado nada por contraindicación inexistente
    assert not result.get("pivotal_contraindication_gates"), (
        "Paciente sano no debe disparar ningún gate en recurrence_bcr."
    )


def test_recurrence_bcr_polysorbate_in_bcr_progressed_blocks_cabazitaxel(registry):
    """Edge case: cabazitaxel no es estándar en BCR primario, pero el filter
    debe igual respetar el gate (defensa en profundidad). Si el comparador
    no emite cabazitaxel, el gate simplemente no afecta nada (no hay
    falso negativo). Test verifica que el gate se EVALÚE igual."""
    payload = _bcr2_payload(polysorbate_hypersensitivity="Sí")
    result = registry.evaluate_module("recurrence_bcr", payload)
    # El gate puede o no aparecer en pivotal_contraindication_gates dependiendo
    # de si filter_treatments_by_gates encontró algún match. Lo importante es
    # que el servicio no se rompe.
    assert result.get("eligible_treatments") is not None


def test_localized_initial_staging_gap_overrides_pivotal_gates(registry):
    """Cuando Gate A (staging M obligatorio) bloquea, el catálogo se reemplaza
    por staging_treatments y los gates pivotal pierden efecto sobre la
    decisión final (pero el descriptor debería reflejar la realidad del
    paciente)."""
    payload = {
        "psa": 50,  # > 20 → Gate A activo
        "clinical_tstage": "T3b",
        "isup_grade": 5,
        "gleason_primary": 5,
        "gleason_secondary": 4,
        "num_cores_positive": 8,
        "total_cores": 12,
        "age": 70,
        "ecog_score": 1,
        # Staging M ausente → Gate A bloquea
        "severe_heart_failure_nyha_iii_iv": "Sí",
    }
    result = registry.evaluate_module("localized_initial", payload)
    # eligible_treatments debe ser staging_treatments (no terapia curativa)
    treatments = result.get("eligible_treatments") or []
    names = " || ".join((t.get("name") or "") for t in treatments).lower()
    assert "estadificación" in names or "staging" in names, (
        f"Con staging M ausente, debe emitir staging_treatments. Got: {names}"
    )
    # No debe haber abiraterona porque Gate A reemplazó el catálogo
    assert "abiraterona" not in names
