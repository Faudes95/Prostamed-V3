"""Anti-regresión estructural profile↔FieldSpec.

Exige que toda clave incluida en `PIVOTAL_PATIENT_PROFILES.payload` esté
respaldada por:

1. una `FieldSpec` declarada en algún `schemas.py` de dominio, o
2. un alias canónico registrado en `ARPI_FIELD_ALIASES`, o
3. una clave de tracking/derivada listada en `PROFILE_EXEMPT_KEYS`.

El propósito: si alguien añade un nuevo paciente insignia con una señal
boolean nueva sin declarar el `FieldSpec`, el test falla y fuerza a
documentar el campo en el schema correspondiente. Esta es la red de
seguridad que cierra la categoría de bug que detectó la Auditoría
Pacientes Insignia 2026-04-21 (`child_pugh_b_or_c`, `docetaxel_fit`,
`late_rt_toxicity_*`, `active_*`, etc.).
"""
# IEC 62304 §5.5 (Unit verification)


from __future__ import annotations

import pytest

from prostanet.application.module_registry import ModuleRegistry
from prostanet.domains.patient_tracking.arpi_selection_engine import (
    ARPI_FIELD_ALIASES,
)
from prostanet.domains.research_intelligence.pivotal_patient_profiles import (
    PIVOTAL_PATIENT_PROFILES,
)


# Claves genéricas de tracking, ruteo o derivadas en runtime que NO
# requieren `FieldSpec` (porque las consume el classifier o se calculan
# desde otras señales) — se documentan aquí explícitamente.
PROFILE_EXEMPT_KEYS: set[str] = {
    # State / classifier wiring
    "state",
    "disease_state",
    "phenotype_state",
    "expected_state",
    # Castración (cubierto por advanced_castration_fields o classifier)
    "castration_resistant",
    "castrate_testosterone_status",
    "castrate_testosterone_confirmed",
    "systemic_progression_context",
    # Carga metastásica / volumen — derivable o canonical aún en flux
    "volume_disease",
    "metastasis_site",
    "metastatic",
    "bone_only_disease",
    "symptomatic_bone_only",
    "visceral_disease",
    "visceral_lesion_count",
    "bone_appendicular_count",
    "bone_axial_count",
    # Identificación clínica genérica común a todos los módulos
    "known_cancer_diagnosis",
    "age",
    "gleason_total",
    "gleason_primary",
    "gleason_secondary",
    "isup_grade",
    "psa",
    "ecog_score",
    # Líneas de tratamiento / contexto
    "prior_arpi",
    "prior_docetaxel",
    "prior_docetaxel_cycles",
    "prior_therapy",
    "prior_radiation",
    "prior_prostatectomy",
    "mcrpc_line_context",
    "line_context",
    # Marcadores genómicos canónicos pero declarados en módulos puntuales
    "hrr_gene",
    "hrr_gene_altered",
    "brca1_status",
    "brca2_status",
    "atm_status",
    "msi_high",
    "tmb_high",
    "ar_v7_positive",
    "psma_positive",
    "pten_loss",
    "pten_status",
    # Diagnóstico y staging
    "clinical_tstage",
    "clinical_tstage_at_treatment",
    "clinical_nstage",
    "clinical_mstage",
    "psa_at_diagnosis",
    "gleason_at_diagnosis",
    "risk_group_at_treatment",
    # Performance / fragilidad / comorbilidad genéricas
    "performance_status_ecog",
    "frailty_status",
    "charlson_index",
    # Síntomas / dolor canónico legacy
    "pain_status",
    "pain_symptoms",
    "opioid_use",
    # Adversos hematológicos no canónicos (legacy informativos)
    "anc",
    "platelets",
    "hemoglobin",
    # Hepatic
    "child_pugh_b_or_c",
    # Otros derivados / aliases
    "metachronous_metastasis",
    "bone_lesions_outside_axial",
    "bone_lesion_count",
    "visceral_metastasis_present",
    # Imágenes / staging
    "psma_pet_done",
    "imaging_negative_metastases",
    "conventional_imaging_m0",
    "conventional_imaging_status",
    # Survivorship / RT history
    "late_sexual_function",
    "smoking_status",
    "colorectal_screening_current",
    "dre_finding",
    "concurrent_adt_history",
    "adt_duration_months",
    "adt_active",
    "prior_rt_modality",
    "prior_rt_completion_date",
    "prior_rt_dose_gy",
    "prior_rt_fractions",
    "prior_rt_intent",
    # PSA kinetics
    "psa_current",
    "psa_current_date",
    "psa_nadir",
    "psa_nadir_date",
    "time_to_nadir_months",
    "phoenix_failure_confirmed",
    "psa_doubling_time_months",
    "bounce_suspected",
    "psadt_months",
    "salvage_local_feasible",
    # Late RT (legacy numéricos cubiertos por FieldSpec)
    "late_urinary_grade",
    "late_bowel_grade",
    # Misc clinical
    "testosterone_value",
    "age_current",
    # Marcadores fenotípicos misc
    "neuropathy_baseline",
    "high_risk_features",
    "high_risk_factors_count",
    # Trial-engine tracking-only signals (no UI capture obligatorio)
    "docetaxel_fit",  # canónico §E.1 con alias; FieldSpec opcional aún
    "taxane_fitness",
    "fit_for_docetaxel",
    "chemotherapy_fitness",
    # Misc reproductive/social
    "reproductive_intent",
    # ── Pre-auditoría 2026-04-21: señales DERIVADAS o legacy informativas
    # presentes en perfiles insignia antes de esta auditoría. La regla
    # operativa es: si la señal es derivable de un FieldSpec existente
    # (p.ej. `hrr_positive` de `hrr_gene_altered`, `prior_taxane` de
    # `prior_docetaxel_cycles`), basta con la exención + comentario; si
    # es informativa pura, se documenta como deuda diferida a futura
    # auditoría temática (no bloquea cierre de la actual).
    # Derivables de canónicos:
    "hrr_positive",  # ← deriva de hrr_gene_altered (ya FieldSpec)
    "brca_pathway",  # ← deriva de brca1/2_status + ATM
    "brca2_origin",  # ← refinamiento de brca2_status (germinal vs somático)
    "prior_abiraterone",  # ← deriva de prior_therapy lookup
    "prior_enzalutamide",  # ← deriva de prior_therapy lookup
    "prior_taxane",  # ← deriva de prior_docetaxel_cycles
    "bcr_confirmed",  # ← derivable de phoenix_failure_confirmed / psa kinetics
    # Legacy informativos (ya capturados parcialmente por survivorship o
    # supportive_care; se exime aquí mientras se diseña el FieldSpec
    # consolidado en una próxima fase de auditoría):
    "bone_modifying_agent",
    "denosumab_prophylaxis",
    "seizure_history",  # historial convulsivo (relevante para enzalutamida)
    # Pathology post-RP (cubierto parcialmente por adverse_pathology §E.4;
    # estas dos claves son raw legacy de RADICALS-RT):
    "pT_stage",
    "pathological_t_stage",
    "surgical_margin_status",
}


def _declared_fields() -> set[str]:
    """Reúne nombres declarados como FieldSpec en cualquier módulo + alias."""
    registry = ModuleRegistry()
    declared: set[str] = set()
    for service in registry.services.values():
        try:
            schema = service.schema()
        except Exception:
            continue
        for field in schema.get("fields") or []:
            name = field.get("name")
            if name:
                declared.add(name)
    for canonical, aliases in ARPI_FIELD_ALIASES.items():
        declared.add(canonical)
        for alias in aliases or []:
            declared.add(alias)
    return declared


def test_pivotal_profile_payload_keys_have_fieldspec_or_alias() -> None:
    """Toda clave en `PIVOTAL_PATIENT_PROFILES.payload` debe ser captable.

    Captable significa: declarada como FieldSpec en un dominio del
    registry, o como alias canónico, o explícitamente exenta por ser
    señal de tracking/derivada.
    """
    declared = _declared_fields()
    missing: dict[str, list[str]] = {}
    for profile in PIVOTAL_PATIENT_PROFILES:
        for key in (profile.payload or {}).keys():
            if key in PROFILE_EXEMPT_KEYS:
                continue
            if key in declared:
                continue
            missing.setdefault(key, []).append(profile.trial_code)
    if missing:
        pretty = "\n".join(
            f"  {key!r}: trials={sorted(set(trials))[:5]}"
            for key, trials in sorted(missing.items())
        )
        pytest.fail(
            "Señales en PIVOTAL_PATIENT_PROFILES sin FieldSpec/alias/exención:\n"
            + pretty
            + "\n\nResolver añadiendo FieldSpec en el schema correspondiente, "
            + "alias en ARPI_FIELD_ALIASES, o exención explícita en "
            + "PROFILE_EXEMPT_KEYS (con justificación)."
        )


def test_audit_required_fieldspecs_present_in_registry() -> None:
    """Verifica H.12 del plan: los 10 FieldSpec añadidos por la auditoría
    están presentes en los módulos esperados."""
    registry = ModuleRegistry()
    required: dict[str, list[str]] = {
        "m1_crpc": [
            "opioid_use_for_pain",
            "extra_pelvic_nodal_metastasis",
            "not_chemotherapy_candidate",
            "active_autoimmune_disease",
            "active_immunosuppression",
            "severe_neutropenia_grade4",
        ],
        "post_radiotherapy_followup": [
            "late_rt_toxicity_gu",
            "late_rt_toxicity_gi",
        ],
        "post_prostatectomy": [
            "active_inflammatory_bowel_disease",
        ],
        "mcspc_high_volume": [
            "severe_neutropenia_grade4",
        ],
    }
    failures: list[str] = []
    for module, fields in required.items():
        if module not in registry.services:
            failures.append(f"módulo ausente: {module}")
            continue
        try:
            schema = registry.services[module].schema()
        except Exception as exc:
            failures.append(f"{module}: schema falla → {exc}")
            continue
        declared = {f.get("name") for f in schema.get("fields") or []}
        missing = [name for name in fields if name not in declared]
        if missing:
            failures.append(f"{module}: faltan {missing}")
    if failures:
        pytest.fail("FieldSpec coverage gaps:\n  " + "\n  ".join(failures))


def test_audit_required_aliases_present() -> None:
    """Verifica H.13 del plan: alias canónicos de la auditoría registrados."""
    expected_pairs: list[tuple[str, str]] = [
        ("pain_symptoms", "pain_status"),
        ("opioid_use_for_pain", "opioid_use"),
        ("extra_pelvic_nodal_metastasis", "nodal_extrapelvic"),
        ("child_pugh_score", "child_pugh_b_or_c"),
        ("visceral_metastasis_present", "visceral_mets"),
        ("docetaxel_fit", "taxane_fitness"),
    ]
    failures: list[str] = []
    for canonical, expected_alias in expected_pairs:
        aliases = ARPI_FIELD_ALIASES.get(canonical) or []
        if expected_alias not in aliases:
            failures.append(
                f"  {canonical!r} debe tener alias {expected_alias!r} "
                f"(actual: {aliases})"
            )
    if failures:
        pytest.fail("Alias coverage gaps en ARPI_FIELD_ALIASES:\n" + "\n".join(failures))


# ── Auditoría Faubot 2026-04-23: cobertura de AE + contraindicaciones ──
# Cada paciente insignia debe tener al menos 1 adverse_event_signal y 1
# contraindication_signal documentado, para que el motor de selección
# ARPI/DDI pueda reaccionar a las señales adversas y contraindicaciones
# publicadas en el trial. Auditoría 2026-04-23 detectó 2 brechas
# (ARANOTE, ARAMIS sin CI) que fueron cerradas con las referencias:
# Saad Lancet Oncol 2024;25:1422 (ARANOTE) y Fizazi NEJM 2019;380:1235
# (ARAMIS). Este test evita que esas brechas vuelvan a abrirse.
def test_all_pivotal_profiles_have_adverse_event_signals() -> None:
    """Cada paciente insignia debe documentar ≥1 adverse_event_signal."""
    gaps = [p.trial_code for p in PIVOTAL_PATIENT_PROFILES if not p.adverse_event_signals]
    assert not gaps, (
        f"Pacientes insignia sin adverse_event_signals documentados: {gaps}. "
        "Cada trial debe listar al menos los AEs clave del perfil publicado."
    )


def test_all_pivotal_profiles_have_contraindication_signals() -> None:
    """Cada paciente insignia debe documentar ≥1 contraindication_signal."""
    gaps = [p.trial_code for p in PIVOTAL_PATIENT_PROFILES if not p.contraindication_signals]
    assert not gaps, (
        f"Pacientes insignia sin contraindication_signals documentados: {gaps}. "
        "Cada trial debe listar al menos las contraindicaciones absolutas "
        "del fármaco/régimen según ficha técnica y criterios de exclusión publicados."
    )


def test_faubot_audit_37_pivotal_trials_present() -> None:
    """Auditoría Faubot 2026-04-23: los 36 trials declarados están presentes.

    Nota: el plan faubot lista 37 nombres pero PRESTO/AFT-19 es el mismo
    trial publicado con dos identificadores (Aggarwal JCO 2023;41:3253).
    La entrada canónica del catálogo es ``PRESTO``.
    """
    expected = {
        "RADICALS-RT", "EMBARK", "PRESTO", "CHAARTED", "LATITUDE", "STAMPEDE",
        "ENZAMET", "ARCHES", "TITAN", "PEACE-1", "ARASENS", "ARANOTE",
        "AMPLITUDE", "SPARTAN", "PROSPER", "ARAMIS", "TAX-327", "TROPIC",
        "CARD", "COU-AA-301", "COU-AA-302", "AFFIRM", "PREVAIL", "ALSYMPCA",
        "VISION", "PSMAfore", "TheraP", "PEACE-3", "PROfound", "PROpel",
        "MAGNITUDE", "TALAPRO-2", "TRITON-3", "IMPACT", "IPATential150",
        "CONTACT-02",
    }
    present = {p.trial_code for p in PIVOTAL_PATIENT_PROFILES}
    missing = expected - present
    assert not missing, (
        f"Trials faubot faltantes en PIVOTAL_PATIENT_PROFILES: {sorted(missing)}"
    )
