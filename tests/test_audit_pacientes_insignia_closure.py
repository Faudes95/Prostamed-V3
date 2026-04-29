"""Regresión de la Auditoría Pacientes Insignia 2026-04-21.

Cubre las cuatro brechas cerradas por el plan `immutable-napping-harp`:

* §B.4 — Gate hepático (`child_pugh_b_or_c` / `child_pugh_score`) en TODAS
  las emisiones de abiraterona (LATITUDE, PEACE-1, PROpel, COU-AA-301/302,
  IPATential150).
* §C.5 — Toxicidad RT tardía (`late_rt_toxicity_gu`/`late_rt_toxicity_gi`)
  emite derivación urología/GI y contraindica re-irradiación cuando grado ≥3.
* §D.5 — Cuatro contraindicaciones IO/hematológicas
  (`active_immunosuppression`, `active_autoimmune_disease`,
  `severe_neutropenia_grade4`, `active_inflammatory_bowel_disease`).
* §E.1 — Normalización canónica de `docetaxel_fit` (apto/no apto/marginal/
  desconocido + alias legacy 0/1/sí/no/fit/unfit).

Estos tests son el contrato vivo que impide regresiones clínicas en el
producto: si una emisión vuelve a ignorar el gate hepático, neutropenia,
inmunosupresión, autoinmunidad, EII o toxicidad RT tardía, el test rojo
expone la brecha exacta.
"""
# IEC 62304 §5.5 (Unit verification)


from __future__ import annotations

import pytest

from prostanet.application.module_registry import ModuleRegistry


# ──────────────────────────────────────────────────────────────────────
# Fixtures y helpers comunes
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def registry() -> ModuleRegistry:
    return ModuleRegistry()


def _resolve_module(registry: ModuleRegistry, payload: dict, requested: str) -> str:
    """Devuelve el módulo real al que el classifier rutea el paciente.

    El test no debe asumir alias: si el clasificador escoge
    `mcspc_high_volume_sync` cuando se pide `mcspc_high_volume`, el módulo
    real es el primero. Si el alias no existe en el registry, cae al
    requested.
    """
    classification = registry.classify_state(payload)
    actual = str(classification.get("state") or "").strip() or requested
    if actual not in registry.services:
        actual = requested
    return actual


def _evaluate(registry: ModuleRegistry, payload: dict, requested_module: str) -> dict:
    actual = _resolve_module(registry, payload, requested_module)
    return registry.evaluate_module(actual, {**payload, "state": actual})


def _treatment_names(result: dict) -> str:
    """Une los nombres de fármacos visibles para el clínico en cualquier
    superficie (legacy `treatments`, mHSPC `eligible_treatments`,
    `comparative_panel`, `ranked_options`).

    Esto evita falsos positivos por servicios que usan claves distintas
    (m1_crpc emite `treatments`; mcspc_high_volume_sync emite
    `eligible_treatments` directo).
    """
    parts: list[str] = []
    for tx in result.get("treatments") or []:
        parts.append(str(tx.get("name") or ""))
    for tx in result.get("eligible_treatments") or []:
        parts.append(str(tx.get("name") or ""))
    for tx in (result.get("comparative_panel") or {}).get("eligible_treatments") or []:
        parts.append(str(tx.get("name") or ""))
    for tx in result.get("ranked_options") or []:
        parts.append(str(tx.get("name") or tx.get("regimen_label") or ""))
    return " ".join(parts).lower()


def _not_recommended_text(result: dict) -> str:
    return " ".join(str(x) for x in (result.get("not_recommended") or [])).lower()


def _serialized_text(result: dict) -> str:
    import json

    return json.dumps(result, ensure_ascii=False, default=str).lower()


# ──────────────────────────────────────────────────────────────────────
# §B.4 — Abiraterona × Child-Pugh B/C (6 trials)
# ──────────────────────────────────────────────────────────────────────


def _m1_crpc_propel_payload(**overrides: object) -> dict:
    """PROpel: 1L mCRPC HRR+ candidato a abiraterona+olaparib.

    Incluye señales canónicas que el state-classifier exige para rutear
    a `m1_crpc`: enfermedad metastásica documentada + castración
    confirmada + contexto de progresión sistémica.
    """
    payload: dict = {
        "state": "m1_crpc",
        "disease_state": "m1_crpc",
        "phenotype_state": "m1_crpc",
        "known_cancer_diagnosis": 1,
        "metastatic": 1,
        "metastasis_site": "Bone",
        "bone_lesion_count": 4,
        "bone_appendicular_count": 1,
        "bone_axial_count": 3,
        "castration_resistant": 1,
        "castrate_testosterone_status": "confirmed_castrate",
        "castrate_testosterone_confirmed": 1,
        "systemic_progression_context": "confirmed_crpc",
        "prior_arpi": 0,
        "prior_docetaxel": 0,
        "prior_docetaxel_cycles": 0,
        "hrr_gene_altered": "BRCA2",
        "brca2_status": "Positivo germinal",
        "performance_status_ecog": 1,
        "psa": 25.0,
        "age": 68,
        "ecog_score": 1,
    }
    payload.update(overrides)
    return payload


def _m1_crpc_ipatential_payload(**overrides: object) -> dict:
    """IPATential150: 1L mCRPC PTEN-loss → ipatasertib + abiraterona."""
    payload = _m1_crpc_propel_payload(
        hrr_gene_altered="",
        brca2_status="Negativo",
        pten_status="Pérdida",
    )
    payload.update(overrides)
    return payload


def _m1_crpc_cou_aa_302_payload(**overrides: object) -> dict:
    """COU-AA-302: post-ARPI nada quimio → abiraterona."""
    payload = _m1_crpc_propel_payload(
        prior_arpi=1,
        prior_therapy="ADT + enzalutamida en mCSPC",
        hrr_gene_altered="",
        brca2_status="Negativo",
    )
    payload.update(overrides)
    return payload


def _m1_crpc_cou_aa_301_payload(**overrides: object) -> dict:
    """COU-AA-301: post-quimio → abiraterona."""
    payload = _m1_crpc_propel_payload(
        prior_arpi=1,
        prior_therapy="ADT + enzalutamida + docetaxel previos",
        prior_docetaxel=1,
        prior_docetaxel_cycles=6,
        hrr_gene_altered="",
        brca2_status="Negativo",
    )
    payload.update(overrides)
    return payload


def _mhspc_high_volume_latitude_payload(**overrides: object) -> dict:
    """LATITUDE: mHSPC alto volumen → ADT + abiraterona.

    Replica el paciente insignia LATITUDE de
    `pivotal_patient_profiles.py` para que pase el state-classifier hacia
    `mcspc_high_volume` con `volume_disease="high"`.
    """
    payload: dict = {
        "state": "mcspc_high_volume",
        "disease_state": "mcspc_high_volume",
        "phenotype_state": "mcspc_high_volume",
        "age": 67,
        "ecog_score": 0,
        "performance_status_ecog": 0,
        "known_cancer_diagnosis": 1,
        "metastatic": 1,
        "metastasis_site": "Bone, visceral",
        "metachronous_metastasis": "0",
        "gleason_primary": 4,
        "gleason_secondary": 5,
        "isup_grade": 5,
        "gleason_total": 9,
        "bone_lesion_count": 5,
        "bone_appendicular_count": 1,
        "bone_axial_count": 4,
        "visceral_disease": 1,
        "visceral_metastasis_present": 1,
        "visceral_lesion_count": 1,
        "volume_disease": "high",
        "psa": 50.0,
        "castration_resistant": 0,
        "docetaxel_fit": "No apto",
    }
    payload.update(overrides)
    return payload


def _mhspc_high_volume_peace1_payload(**overrides: object) -> dict:
    """PEACE-1: triplete docetaxel + abiraterona + ADT (mHSPC fit alto vol)."""
    payload = _mhspc_high_volume_latitude_payload(
        docetaxel_fit="Apto (fit)",
    )
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "trial_label,module,payload_factory,requires_alternative_or_message",
    [
        # Trials que emiten abiraterona como frontline activo (1L mCRPC o
        # mHSPC) — al bloquearse por hepatopatía, debe surgir o un ARPI
        # alternativo o el mensaje canónico de contraindicación.
        ("PROpel", "m1_crpc", _m1_crpc_propel_payload, True),
        ("IPATential150", "m1_crpc", _m1_crpc_ipatential_payload, True),
        ("LATITUDE", "mcspc_high_volume", _mhspc_high_volume_latitude_payload, True),
        ("PEACE-1", "mcspc_high_volume", _mhspc_high_volume_peace1_payload, True),
        # Trials de 2L+ post-ARPI: la lógica de secuenciación correcta ya
        # impide ARPI-tras-ARPI; basta verificar que abiraterona no aparezca.
        ("COU-AA-302", "m1_crpc", _m1_crpc_cou_aa_302_payload, False),
        ("COU-AA-301", "m1_crpc", _m1_crpc_cou_aa_301_payload, False),
    ],
)
def test_abiraterona_blocked_by_child_pugh_b(
    registry: ModuleRegistry,
    trial_label: str,
    module: str,
    payload_factory,
    requires_alternative_or_message: bool,
) -> None:
    """Child-Pugh B → ninguna emisión debe contener abiraterona."""
    payload = payload_factory(child_pugh_score="B")
    result = _evaluate(registry, payload, module)
    names = _treatment_names(result)
    nr = _not_recommended_text(result)

    assert "abirater" not in names, (
        f"{trial_label}: abiraterona emitida pese a Child-Pugh B. "
        f"treatments={names[:300]}"
    )
    if requires_alternative_or_message:
        has_alternative = any(
            alt in names for alt in ("enzalutam", "darolutam", "apalutam")
        )
        has_message = (
            ("abirater" in nr) or ("hepát" in nr) or ("child" in nr) or (
                "child-pugh" in nr
            )
        )
        assert has_alternative or has_message, (
            f"{trial_label}: ni alternativa ARPI ni mensaje de contraindicación "
            f"hepática. not_recommended={nr[:300]}"
        )


@pytest.mark.parametrize(
    "trial_label,module,payload_factory",
    [
        ("LATITUDE (boolean alias)", "mcspc_high_volume", _mhspc_high_volume_latitude_payload),
        ("PEACE-1 (boolean alias)", "mcspc_high_volume", _mhspc_high_volume_peace1_payload),
    ],
)
def test_abiraterona_blocked_by_child_pugh_b_or_c_boolean_alias(
    registry: ModuleRegistry, trial_label: str, module: str, payload_factory
) -> None:
    """Alias boolean `child_pugh_b_or_c="Sí"` debe ser equivalente a B/C."""
    payload = payload_factory(child_pugh_b_or_c="Sí")
    result = _evaluate(registry, payload, module)
    names = _treatment_names(result)
    assert "abirater" not in names, (
        f"{trial_label}: abiraterona emitida pese a child_pugh_b_or_c='Sí'."
    )


def test_abiraterona_NOT_blocked_when_child_pugh_a(registry: ModuleRegistry) -> None:
    """Sanity-check: Child-Pugh A debe permitir abiraterona en LATITUDE."""
    payload = _mhspc_high_volume_latitude_payload(child_pugh_score="A")
    result = _evaluate(registry, payload, "mcspc_high_volume")
    names = _treatment_names(result)
    assert "abirater" in names, (
        f"LATITUDE Child-Pugh A: abiraterona NO emitida (regresión). "
        f"treatments={names[:300]}"
    )


# ──────────────────────────────────────────────────────────────────────
# §C.5 — Toxicidad RT tardía
# ──────────────────────────────────────────────────────────────────────


def _post_rt_followup_baseline(**overrides: object) -> dict:
    from datetime import date, timedelta

    payload: dict = {
        "state": "post_radiotherapy_followup",
        "prior_radiation": "1",
        "prior_prostatectomy": "0",
        "prior_rt_modality": "IMRT",
        "prior_rt_completion_date": (date.today() - timedelta(days=730)).isoformat(),
        "prior_rt_dose_gy": 78,
        "prior_rt_fractions": 39,
        "prior_rt_intent": "Definitive",
        "concurrent_adt_history": "Corto (4-6m)",
        "adt_duration_months": 6,
        "adt_active": "0",
        "risk_group_at_treatment": "Unfavorable Intermediate",
        "gleason_at_diagnosis": 2,
        "psa_at_diagnosis": 10,
        "clinical_tstage_at_treatment": "T2a",
        "psa_current": 0.4,
        "psa_current_date": date.today().isoformat(),
        "psa_nadir": 0.3,
        "psa_nadir_date": (date.today() - timedelta(days=540)).isoformat(),
        "time_to_nadir_months": 18,
        "phoenix_failure_confirmed": "0",
        "psa_doubling_time_months": 0,
        "bounce_suspected": "0",
        "late_urinary_grade": "0",
        "late_bowel_grade": "0",
        "late_rt_toxicity_gu": "Sin toxicidad",
        "late_rt_toxicity_gi": "Sin toxicidad",
        "late_sexual_function": "Preservada",
        "testosterone_value": 350,
        "smoking_status": "Nunca",
        "colorectal_screening_current": "1",
        "dre_finding": "Normal",
        "imaging_negative_metastases": "1",
        "age_current": 68,
        "ecog_score": "0",
        "frailty_status": "Fit",
        "charlson_index": 2,
    }
    payload.update(overrides)
    return payload


def test_late_rt_toxicity_gu_grade2_emits_urology_referral(
    registry: ModuleRegistry,
) -> None:
    payload = _post_rt_followup_baseline(late_rt_toxicity_gu="Grado 2 – moderado")
    result = _evaluate(registry, payload, "post_radiotherapy_followup")
    text = _serialized_text(result)
    assert "urolog" in text or "derivaci" in text, (
        f"late_rt_toxicity_gu=Grado 2: no se detecta derivación a urología. "
        f"text(head)={text[:600]}"
    )


def test_late_rt_toxicity_gi_grade2_emits_gastroenterology_referral(
    registry: ModuleRegistry,
) -> None:
    payload = _post_rt_followup_baseline(late_rt_toxicity_gi="Grado 2 – moderado")
    result = _evaluate(registry, payload, "post_radiotherapy_followup")
    text = _serialized_text(result)
    assert "gastroenterolog" in text or "derivaci" in text, (
        f"late_rt_toxicity_gi=Grado 2: no se detecta derivación a GI. "
        f"text(head)={text[:600]}"
    )


@pytest.mark.parametrize("axis,value", [
    ("late_rt_toxicity_gu", "Grado 3 – severo"),
    ("late_rt_toxicity_gi", "Grado 3 – severo"),
    ("late_rt_toxicity_gu", "Grado 4 – amenaza vida"),
])
def test_late_rt_toxicity_grade3_blocks_reirradiation(
    registry: ModuleRegistry, axis: str, value: str
) -> None:
    payload = _post_rt_followup_baseline(**{axis: value})
    result = _evaluate(registry, payload, "post_radiotherapy_followup")
    nr = _not_recommended_text(result)
    assert "toxicidad tardía" in nr, (
        f"{axis}={value}: no aparece gate de re-irradiación por toxicidad tardía. "
        f"not_recommended={nr[:600]}"
    )


def test_late_rt_toxicity_boolean_alias_si_acts_as_grade2(
    registry: ModuleRegistry,
) -> None:
    """Alias legacy `late_rt_toxicity_gu="Sí"` debe escalar a tier 2 (referral)."""
    payload = _post_rt_followup_baseline(late_rt_toxicity_gu="Sí")
    result = _evaluate(registry, payload, "post_radiotherapy_followup")
    text = _serialized_text(result)
    assert "urolog" in text or "derivaci" in text, (
        f"Alias boolean 'Sí' no escala a tier 2 / referral. text(head)={text[:600]}"
    )


# ──────────────────────────────────────────────────────────────────────
# §D.5 — Contraindicaciones IO / hematológicas / EII
# ──────────────────────────────────────────────────────────────────────


def _impact_eligible_payload(**overrides: object) -> dict:
    """IMPACT eligible: mCRPC asintomático sin viscerales pre-quimio."""
    payload: dict = {
        "state": "m1_crpc",
        "disease_state": "m1_crpc",
        "phenotype_state": "m1_crpc",
        "known_cancer_diagnosis": 1,
        "metastatic": 1,
        "metastasis_site": "Bone",
        "bone_lesion_count": 3,
        "bone_appendicular_count": 0,
        "bone_axial_count": 3,
        "castration_resistant": 1,
        "castrate_testosterone_status": "confirmed_castrate",
        "castrate_testosterone_confirmed": 1,
        "systemic_progression_context": "confirmed_crpc",
        "prior_arpi": 0,
        "prior_docetaxel": 0,
        "prior_docetaxel_cycles": 0,
        "visceral_metastasis_present": 0,
        "pain_status": "Asintomatico",
        "pain_symptoms": "Asintomatico",
        "opioid_use_for_pain": "Ninguno",
        "performance_status_ecog": 0,
        "psa": 12.0,
        "age": 70,
        "ecog_score": 0,
    }
    payload.update(overrides)
    return payload


def _contact02_eligible_payload(**overrides: object) -> dict:
    """CONTACT-02 eligible: mCRPC post-ARPI con enfermedad visceral.

    `prior_therapy` debe contener token textual reconocido por
    `evaluate_m1_crpc` (abirater/enzalut/apalut/darolut/rezvilut).
    """
    payload: dict = {
        "state": "m1_crpc",
        "disease_state": "m1_crpc",
        "phenotype_state": "m1_crpc",
        "known_cancer_diagnosis": 1,
        "metastatic": 1,
        "metastasis_site": "Visceral, Bone",
        "bone_lesion_count": 3,
        "bone_appendicular_count": 0,
        "bone_axial_count": 3,
        "visceral_disease": 1,
        "visceral_metastasis_present": 1,
        "visceral_lesion_count": 1,
        "castration_resistant": 1,
        "castrate_testosterone_status": "confirmed_castrate",
        "castrate_testosterone_confirmed": 1,
        "systemic_progression_context": "confirmed_crpc",
        "prior_arpi": 1,
        "prior_therapy": "ADT + abiraterona en mCSPC",
        "prior_docetaxel": 0,
        "prior_docetaxel_cycles": 0,
        "extra_pelvic_nodal_metastasis": "Sí",
        "not_chemotherapy_candidate": "Sí",
        "performance_status_ecog": 1,
        "psa": 18.0,
        "age": 70,
        "ecog_score": 1,
    }
    payload.update(overrides)
    return payload


def test_sipuleucel_t_blocked_by_active_immunosuppression(
    registry: ModuleRegistry,
) -> None:
    payload = _impact_eligible_payload(active_immunosuppression="Sí")
    result = _evaluate(registry, payload, "m1_crpc")
    names = _treatment_names(result)
    nr = _not_recommended_text(result)
    assert "sipuleucel" not in names, (
        f"Sipuleucel-T emitido pese a inmunosupresión activa. "
        f"treatments={names[:300]}"
    )
    assert "sipuleucel" in nr or "inmunosupr" in nr, (
        f"Falta mensaje de contraindicación por inmunosupresión. "
        f"not_recommended={nr[:300]}"
    )


def test_atezolizumab_blocked_by_active_autoimmune(registry: ModuleRegistry) -> None:
    payload = _contact02_eligible_payload(active_autoimmune_disease="Sí")
    result = _evaluate(registry, payload, "m1_crpc")
    names = _treatment_names(result)
    nr = _not_recommended_text(result)
    assert "atezolizumab" not in names, (
        f"Atezolizumab emitido pese a autoinmunidad activa. "
        f"treatments={names[:300]}"
    )
    assert "autoinmun" in nr or "atezolizumab" in nr, (
        f"Falta mensaje de contraindicación por autoinmunidad. "
        f"not_recommended={nr[:300]}"
    )


def test_docetaxel_blocked_by_grade4_neutropenia_in_mhspc(
    registry: ModuleRegistry,
) -> None:
    payload = _mhspc_high_volume_peace1_payload(
        severe_neutropenia_grade4="Sí",
        docetaxel_fit="Apto (fit)",
    )
    result = _evaluate(registry, payload, "mcspc_high_volume")
    names = _treatment_names(result)
    nr = _not_recommended_text(result)
    assert "docetaxel" not in names, (
        f"Docetaxel emitido pese a neutropenia grado 4 activa. "
        f"treatments={names[:300]}"
    )
    assert "neutropeni" in nr or "aplaz" in nr, (
        f"Falta mensaje de aplazamiento de docetaxel por neutropenia. "
        f"not_recommended={nr[:300]}"
    )


def test_salvage_rt_blocked_by_active_ibd_in_recurrence_bcr(
    registry: ModuleRegistry,
) -> None:
    """En recurrence_bcr con EII activa, salvage RT no debe emitirse."""
    payload = {
        "state": "recurrence_bcr",
        "disease_state": "recurrence_bcr",
        "prior_prostatectomy": 1,
        "prior_radiation": 0,
        "psa_current": 0.4,
        "psa_doubling_time_months": 5,
        "salvage_local_feasible": 1,
        "conventional_imaging_m0": 1,
        "psma_pet_done": 0,
        "performance_status_ecog": 0,
        "active_inflammatory_bowel_disease": "Sí",
    }
    result = _evaluate(registry, payload, "recurrence_bcr")
    nr = _not_recommended_text(result)
    text = _serialized_text(result)
    # El gate IBD debe surgir en not_recommended y bloquear salvage_rt_family.
    assert any(token in nr for token in ("inflamatoria", "ibd", "crohn", "colitis")), (
        f"EII activa: no aparece mensaje de contraindicación de RT pélvica. "
        f"not_recommended={nr[:600]}"
    )
    # Si se emite salvage_rt_family seguimos rojos.
    assert "salvage_rt_family" not in text or (
        "rt pélvica contraindicada" in text or "rt salvage contraindicada" in text
        or "salvage rt" in nr or "rt pélvica" in nr
    ), (
        "EII activa: salvage_rt_family aparece sin mensaje de contraindicación."
    )


# ──────────────────────────────────────────────────────────────────────
# §E.1 — Normalización canónica de docetaxel_fit
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "input_value,fit_expected,override_expected",
    [
        ("Apto (fit)", True, True),
        ("Apto", True, True),
        ("fit", True, True),
        ("1", True, True),
        ("Sí", True, True),
        ("yes", True, True),
        ("No apto", False, False),
        ("unfit", False, False),
        ("0", False, False),
        ("No", False, False),
        ("Marginal", False, False),
        ("Desconocido", False, None),
        ("", False, None),
    ],
)
def test_resolve_docetaxel_fit_normalization(
    input_value: str, fit_expected: bool, override_expected: object
) -> None:
    """Toda variante semántica ES-médica + alias legacy debe mapear a un único contrato."""
    from prostanet.shared.advanced_support_normalizer import (
        resolve_docetaxel_fit,
        resolve_docetaxel_fit_override,
    )

    got_fit = resolve_docetaxel_fit({"docetaxel_fit": input_value})
    got_override = resolve_docetaxel_fit_override({"docetaxel_fit": input_value})

    assert got_fit is fit_expected, (
        f"resolve_docetaxel_fit({input_value!r}) → {got_fit} (esperado {fit_expected})"
    )
    assert got_override == override_expected, (
        f"resolve_docetaxel_fit_override({input_value!r}) → {got_override} "
        f"(esperado {override_expected})"
    )


def test_resolve_docetaxel_fit_taxane_fitness_alias() -> None:
    """`taxane_fitness` debe actuar como alias de `docetaxel_fit`."""
    from prostanet.shared.advanced_support_normalizer import resolve_docetaxel_fit

    assert resolve_docetaxel_fit({"taxane_fitness": "Apto (fit)"}) is True
    assert resolve_docetaxel_fit({"taxane_fitness": "No apto"}) is False
    # docetaxel_fit primario gana sobre taxane_fitness alias.
    assert resolve_docetaxel_fit(
        {"docetaxel_fit": "Apto (fit)", "taxane_fitness": "No apto"}
    ) is True
