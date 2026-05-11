"""Faubot LXCIII (plan LXXXVII) — Progressive Disclosure Capture Engine.

Reemplaza la captura "487 fields flat" con flujo stage-aware + role-aware
+ state-routed que muestra solo fields críticos visibles + refiners
expandibles bajo demanda + clasificación en vivo.

Diseño:
1. **Stage classification**: usa StateClassifierService para rutear a 1 de
   17 disease states canónicos (NCCN/EAU).
2. **Field disclosure tier**: mapea `clinical_role` (existing FieldSpec
   attribute) → disclosure_tier:
     - required → always_visible
     - decision_refiner → expandable_refiner
     - monitoring → expandable_monitoring
     - optional → expandable_research
3. **Per-state field routing**: filtra fields relevantes al disease_state
   actual (no renderiza fields irrelevantes a otros estados).
4. **Live classification preview**: actualiza al fill de always_visible
   (D'Amico, CHAARTED, LATITUDE, PCWG3 en tiempo real).
5. **Recommendation preview**: invoca `clinical_subspecialty_engine` para
   sugerir próxima acción clínica + confidence + rationale.

Aporte a auditabilidad:
  - **CÓMO** (UI): captura ergonómica sin perder lógica clínica
  - **POR QUÉ** (gates): live preview muestra qué gates están activos
  - **DATOS** (FieldSpecs): filtrados por relevancia clínica al estado
  - **EVIDENCIA**: recommendation preview cita trial_refs de gates fired
  - **VERSIÓN**: usa pivotal_gate_supporting_fields + StateClassifier actuales

Uso:
    from prostanet.presentation.progressive_capture_builder import (
        build_stage_aware_capture,
    )

    result = build_stage_aware_capture(
        disease_state="m1_crpc",
        captured_so_far={"psa_value": 80, "gleason_score": 9},
    )
    # result["always_visible"] → 6 required fields
    # result["expandable_groups"] → [refiners, monitoring, research]
    # result["live_classification"] → {nccn_risk, chaarted_volume, ...}
    # result["recommendation_preview"] → {primary_action, confidence}
"""
from __future__ import annotations

from typing import Any, Mapping


# ──────────────────────────────────────────────────────────────────────
# Mapping: clinical_role → disclosure_tier
# ──────────────────────────────────────────────────────────────────────

CLINICAL_ROLE_TO_DISCLOSURE_TIER: dict[str, str] = {
    "required": "always_visible",
    "decision_refiner": "expandable_refiner",
    "monitoring": "expandable_monitoring",
    "optional": "expandable_research",
    "research": "expandable_research",
    # Default for unspecified roles
    "": "expandable_refiner",
}


def map_clinical_role_to_tier(clinical_role: str | None) -> str:
    """Map clinical_role string → disclosure_tier."""
    if not clinical_role:
        return "expandable_refiner"
    return CLINICAL_ROLE_TO_DISCLOSURE_TIER.get(
        clinical_role.lower(), "expandable_refiner"
    )


# ──────────────────────────────────────────────────────────────────────
# Per-state critical field whitelists (always_visible, max 4-8 fields)
# Source: NCCN v5.2026 + EAU 2026 + decision_input_requirements_engine
# ──────────────────────────────────────────────────────────────────────

# Disease state → critical field names (always_visible, ≤8 fields)
PER_STATE_ALWAYS_VISIBLE: dict[str, list[str]] = {
    "diagnostic_workup": [
        "psa_value", "age", "dre_finding", "prior_negative_biopsy",
        "phi_value", "psa_density",
    ],
    "post_negative_biopsy_followup": [
        "psa_value", "age", "psa_doubling_time_months",
        "dre_finding", "mri_pirads_score",
    ],
    "localized_initial": [
        "psa_value", "gleason_score", "clinical_t_stage",
        "clinical_n_stage", "clinical_m_stage", "ecog_score",
        "age", "life_expectancy_years",
    ],
    "post_prostatectomy": [
        "psa_value", "psa_persistent_post_rp", "gleason_score",
        "pathological_t_stage", "surgical_margins_status", "lymph_nodes_positive",
    ],
    "post_radiotherapy_followup": [
        "psa_value", "psa_nadir_post_rt", "psa_velocity_ng_ml_year",
        "ecog_score",
    ],
    "recurrence_bcr": [
        "psa_value", "prior_prostatectomy", "prior_radiation",
        "psa_doubling_time_months", "gleason_score", "time_from_definitive_treatment_months",
    ],
    "post_radiotherapy_or_local_salvage": [
        "psa_value", "prior_radiation", "psa_nadir_post_rt",
        "psa_doubling_time_months", "ecog_score",
    ],
    "adt_progression_verification": [
        "psa_value", "testosterone_value", "current_adt_context",
        "imaging_modality_used_for_m_staging", "ecog_score",
    ],
    "mcspc_oligo_metachronous": [
        "psa_value", "metastasis_site", "bone_lesion_count_total",
        "metachronous_metastasis", "ecog_score", "gleason_score",
    ],
    "mcspc_low_volume_sync_oligo": [
        "psa_value", "metastasis_site", "bone_lesion_count_total",
        "visceral_metastasis_present", "ecog_score", "gleason_score",
    ],
    "mcspc_high_volume_sync": [
        "psa_value", "gleason_score", "bone_lesion_count_total",
        "visceral_metastasis_present", "bone_appendicular_count",
        "ecog_score", "metastasis_site",
    ],
    "mcspc_high_volume_metachronous": [
        "psa_value", "gleason_score", "bone_lesion_count_total",
        "visceral_metastasis_present", "ecog_score", "metachronous_metastasis",
    ],
    "m0_crpc": [
        "psa_value", "psa_doubling_time_months", "castrate_testosterone_status",
        "imaging_modality_used_for_m_staging", "ecog_score",
    ],
    "m1_crpc": [
        "psa_value", "castrate_testosterone_status", "prior_treatment_lines_count",
        "metastasis_site", "hrr_status", "ecog_score",
        "visceral_metastasis_present",
    ],
    "survivorship_and_toxicity_followup": [
        "psa_value", "ecog_score", "ctcae_grade_max",
        "prior_treatment_lines_count",
    ],
}

# Default for unknown states
DEFAULT_ALWAYS_VISIBLE: list[str] = [
    "psa_value", "gleason_score", "clinical_t_stage",
    "clinical_m_stage", "ecog_score", "age",
]

# Disease state → human-readable label
DISEASE_STATE_LABELS: dict[str, str] = {
    "diagnostic_workup": "Workup diagnóstico (pre-biopsia)",
    "post_negative_biopsy_followup": "Seguimiento post-biopsia negativa",
    "localized_initial": "Cáncer localizado (primer diagnóstico)",
    "post_prostatectomy": "Post-prostatectomía radical",
    "post_radiotherapy_followup": "Post-radioterapia (seguimiento)",
    "recurrence_bcr": "Recurrencia bioquímica (BCR)",
    "post_radiotherapy_or_local_salvage": "Post-RT salvage o local salvage",
    "adt_progression_verification": "Verificación progresión bajo ADT",
    "mcspc_oligo_metachronous": "mCSPC oligo-metacrónico",
    "mcspc_low_volume_sync_oligo": "mCSPC bajo volumen sincrónico",
    "mcspc_high_volume_sync": "mCSPC alto volumen sincrónico",
    "mcspc_high_volume_metachronous": "mCSPC alto volumen metacrónico",
    "m0_crpc": "nmCRPC (M0 castración resistente)",
    "m1_crpc": "mCRPC (M1 castración resistente)",
    "survivorship_and_toxicity_followup": "Survivorship + toxicidad longitudinal",
}

# Per-state next-step hints (dynamic guidance for clinician)
PER_STATE_NEXT_STEP_HINT: dict[str, str] = {
    "diagnostic_workup": "Captura PSA + DRE + edad + historial biopsia para indicación de biopsia/MRI fusion",
    "localized_initial": "Captura PSA + Gleason + T/N/M + ECOG para clasificar D'Amico (low/intermediate/high/very-high)",
    "mcspc_high_volume_sync": "Captura conteo lesiones óseas + visceral mets para confirmar CHAARTED HV (≥4 óseas con apendicular OR visceral)",
    "m1_crpc": "Captura líneas previas + HRR status + visceral mets para evaluar PROfound/AMPLITUDE/VISION elegibility",
    "m0_crpc": "Captura PSADT + imaging modality (PSMA-PET preferred si PSA 0.5-2) para SPARTAN/PROSPER/ARAMIS elegibility",
    "recurrence_bcr": "Captura PSADT + tipo de tratamiento previo (RP/RT) para Phoenix vs ASTRO criteria + EMBARK/PRESTO",
}


# ──────────────────────────────────────────────────────────────────────
# Main builder
# ──────────────────────────────────────────────────────────────────────


def build_stage_aware_capture(
    disease_state: str,
    captured_so_far: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build progressive capture structure for a disease state.

    Args:
        disease_state: e.g. "m1_crpc", "localized_initial", "mcspc_high_volume_sync"
        captured_so_far: dict of fields already filled (for live classification)

    Returns:
        {
            "stage_label": str,
            "stage_key": str,
            "disease_state": str,
            "always_visible": [<field_dict>],
            "expandable_groups": [
                {"key": str, "label": str, "icon": str, "fields": [<field_dict>]},
                ...
            ],
            "next_step_hint": str,
            "live_classification": dict,
            "recommendation_preview": dict,
        }
    """
    captured = dict(captured_so_far or {})

    # Get all available FieldSpecs
    try:
        from prostanet.shared.advanced_support_fields import (
            pivotal_gate_supporting_fields,
        )
        all_fields = pivotal_gate_supporting_fields()
    except Exception:
        all_fields = []

    # Index by name
    fields_by_name = {f.name: f for f in all_fields}

    # Get always_visible field names for this state
    always_visible_names = PER_STATE_ALWAYS_VISIBLE.get(
        disease_state, DEFAULT_ALWAYS_VISIBLE
    )

    # Build always_visible field dicts (synthetic if not in pivotal helper)
    always_visible_fields: list[dict[str, Any]] = []
    for name in always_visible_names:
        if name in fields_by_name:
            always_visible_fields.append(_field_to_dict(fields_by_name[name]))
        else:
            # Synthetic field placeholder for non-pivotal fields like psa_value, age
            always_visible_fields.append(_synthetic_field(name))

    # Faubot LXCVI.F.2 — Inject demographic critical fields cross-state.
    # `etnia` + `seguridad_social` impactan clinical decision support
    # (CHAARTED+STAMPEDE subgroup) + workflow (insurance routing).
    DEMOGRAPHIC_ALWAYS_VISIBLE = ["etnia", "seguridad_social"]
    for demo_name in DEMOGRAPHIC_ALWAYS_VISIBLE:
        if demo_name not in always_visible_names:
            always_visible_fields.append(_synthetic_field(demo_name))

    # Group remaining fields by disclosure tier (excluding always_visible)
    remaining = [
        f for f in all_fields
        if f.name not in always_visible_names
    ]

    refiner_fields: list[dict[str, Any]] = []
    monitoring_fields: list[dict[str, Any]] = []
    research_fields: list[dict[str, Any]] = []

    for f in remaining:
        tier = map_clinical_role_to_tier(f.clinical_role)
        field_dict = _field_to_dict(f)
        if tier == "always_visible":
            # If clinical_role=required but not in our whitelist, still treat as refiner
            refiner_fields.append(field_dict)
        elif tier == "expandable_refiner":
            refiner_fields.append(field_dict)
        elif tier == "expandable_monitoring":
            monitoring_fields.append(field_dict)
        else:  # expandable_research
            research_fields.append(field_dict)

    # Faubot LXCVI.F.3 — Demographics + lifestyle expandable group (8 fields)
    demographics_fields = [
        _synthetic_field(name) for name in [
            "estado_residencia", "escolaridad", "ocupacion", "estado_civil",
            "tabaquismo", "paquetes_anio", "actividad_fisica",
            "ipss_score",
        ]
    ]

    expandable_groups = [
        {
            "key": "decision_refiners",
            "label": "Refinar decisión",
            "icon": "⚙️",
            "description": (
                "Variables clínicas + biomoleculares que afinan la recomendación principal. "
                "Expanda solo los relevantes a su escenario clínico."
            ),
            "fields": refiner_fields,
            "field_count": len(refiner_fields),
        },
        {
            "key": "monitoring",
            "label": "Monitoreo y benchmarking",
            "icon": "📊",
            "description": (
                "Datos longitudinales que comparan con cohortes pivotales. "
                "Útiles en seguimiento post-tratamiento."
            ),
            "fields": monitoring_fields,
            "field_count": len(monitoring_fields),
        },
        {
            "key": "demographics_lifestyle",
            "label": "Demografía + estilo de vida",
            "icon": "👤",
            "description": (
                "Datos demográficos + lifestyle que impactan toxicidad + survival "
                "(smoking, escolaridad, estado_civil, IPSS PROs baseline)."
            ),
            "fields": demographics_fields,
            "field_count": len(demographics_fields),
        },
        {
            "key": "research",
            "label": "Datos de investigación",
            "icon": "🔬",
            "description": (
                "Campos para protocolos académicos + estudios pivotales activos. "
                "Opcional para práctica clínica rutinaria."
            ),
            "fields": research_fields,
            "field_count": len(research_fields),
        },
    ]

    # Compute live classification (best-effort, returns empty dict if can't classify)
    live_classification = _compute_live_classification(captured, disease_state)

    # Compute recommendation preview (best-effort)
    recommendation_preview = _compute_recommendation_preview(captured, disease_state)

    return {
        "stage_label": DISEASE_STATE_LABELS.get(disease_state, disease_state),
        "stage_key": disease_state,
        "disease_state": disease_state,
        "always_visible": always_visible_fields,
        "expandable_groups": expandable_groups,
        "next_step_hint": PER_STATE_NEXT_STEP_HINT.get(
            disease_state,
            "Captura los datos críticos visibles para clasificar el estado y emitir recomendación.",
        ),
        "live_classification": live_classification,
        "recommendation_preview": recommendation_preview,
        "summary": {
            "total_always_visible": len(always_visible_fields),
            "total_refiners": len(refiner_fields),
            "total_monitoring": len(monitoring_fields),
            "total_research": len(research_fields),
            "total_fields_available": (
                len(always_visible_fields) + len(refiner_fields)
                + len(monitoring_fields) + len(research_fields)
            ),
        },
    }


def _field_to_dict(field_spec: Any) -> dict[str, Any]:
    """Convert FieldSpec → dict for template rendering."""
    try:
        return field_spec.to_dict()
    except Exception:
        # Fallback: extract attributes manually
        return {
            "name": getattr(field_spec, "name", ""),
            "label": getattr(field_spec, "label", ""),
            "type": getattr(field_spec, "field_type", "text"),
            "required": getattr(field_spec, "required", False),
            "options": list(getattr(field_spec, "options", []) or []),
            "default": getattr(field_spec, "default", None),
            "help": getattr(field_spec, "help_text", ""),
            "clinical_role": getattr(field_spec, "clinical_role", ""),
            "disclosure_tier": map_clinical_role_to_tier(
                getattr(field_spec, "clinical_role", "")
            ),
        }


def _synthetic_field(name: str) -> dict[str, Any]:
    """Build synthetic field dict for canonical fields not in pivotal helper."""
    # Common labels for canonical fields
    canonical_labels: dict[str, dict[str, Any]] = {
        "psa_value": {"label": "PSA actual (ng/mL)", "type": "number", "unit": "ng/mL"},
        "age": {"label": "Edad (años)", "type": "number", "unit": "años"},
        "gleason_score": {"label": "Gleason score (suma)", "type": "number"},
        "clinical_t_stage": {
            "label": "Estadio clínico T", "type": "select",
            "options": ["T1a", "T1b", "T1c", "T2a", "T2b", "T2c",
                        "T3a", "T3b", "T4"],
        },
        "clinical_n_stage": {
            "label": "Estadio clínico N", "type": "select",
            "options": ["N0", "N1", "Nx"],
        },
        "clinical_m_stage": {
            "label": "Estadio clínico M", "type": "select",
            "options": ["M0", "M1a", "M1b", "M1c", "Mx"],
        },
        "ecog_score": {
            "label": "ECOG performance status (0-4)", "type": "select",
            "options": ["0", "1", "2", "3", "4"],
        },
        "metastasis_site": {
            "label": "Sitio de metástasis", "type": "select",
            "options": ["M0", "M1a (nodos no regionales)", "M1b (óseas)",
                        "M1c (visceral)"],
        },
        "bone_lesion_count_total": {
            "label": "Número total lesiones óseas", "type": "number",
        },
        "bone_appendicular_count": {
            "label": "Lesiones óseas apendiculares (CHAARTED HV)", "type": "number",
        },
        "visceral_metastasis_present": {
            "label": "Metástasis visceral presente", "type": "select",
            "options": [{"value": "0", "label": "No"}, {"value": "1", "label": "Sí"}],
        },
        "psa_doubling_time_months": {
            "label": "PSADT (meses)", "type": "number", "unit": "meses",
        },
        "castrate_testosterone_status": {
            "label": "Estado castración testosterona", "type": "select",
            "options": ["not_castrate", "confirmed_castrate", "unknown"],
        },
        "prior_treatment_lines_count": {
            "label": "Líneas de tratamiento previas (#)", "type": "number",
        },
        "hrr_status": {
            "label": "HRR status (BRCA1/2/ATM/PALB2/etc.)", "type": "select",
            "options": ["not_tested", "negative", "hrr_positive", "vus", "pending"],
        },
        "dre_finding": {
            "label": "Tacto rectal hallazgo", "type": "select",
            "options": ["normal", "induration", "nodule", "T2_palpable",
                        "T3_extracapsular", "T4_fixed_pebbly"],
        },
        "prior_negative_biopsy": {
            "label": "Biopsia previa negativa", "type": "select",
            "options": [{"value": "0", "label": "No"}, {"value": "1", "label": "Sí"}],
        },
        "prior_prostatectomy": {
            "label": "Prostatectomía radical previa", "type": "select",
            "options": [{"value": "0", "label": "No"}, {"value": "1", "label": "Sí"}],
        },
        "prior_radiation": {
            "label": "Radioterapia primaria previa", "type": "select",
            "options": [{"value": "0", "label": "No"}, {"value": "1", "label": "Sí"}],
        },
        "psa_persistent_post_rp": {
            "label": "PSA persistente post-RP (≥0.1 ng/mL 6sem)", "type": "select",
            "options": [{"value": "0", "label": "No"}, {"value": "1", "label": "Sí"}],
        },
        "imaging_modality_used_for_m_staging": {
            "label": "Modalidad imaging para staging M", "type": "select",
            "options": ["CT_only", "CT_plus_bone_scan", "PSMA_PET",
                        "PSMA_PET_plus_CT", "MRI_whole_body", "FDG_PET",
                        "Desconocido"],
        },
        # ─── Faubot LXCVI.F demographic fields ───
        "etnia": {
            "label": "Etnia / Raza", "type": "select",
            "options": [
                {"value": "hispano", "label": "Hispano/Latino"},
                {"value": "afrodescendiente", "label": "Afrodescendiente (CHAARTED/STAMPEDE subgroup)"},
                {"value": "asiatico", "label": "Asiático"},
                {"value": "blanco", "label": "Blanco no hispano"},
                {"value": "indigena", "label": "Indígena"},
                {"value": "otros", "label": "Otros"},
                {"value": "desconocido", "label": "Desconocido"},
            ],
        },
        "seguridad_social": {
            "label": "Seguridad social / Aseguradora", "type": "select",
            "options": [
                {"value": "IMSS", "label": "IMSS"},
                {"value": "ISSSTE", "label": "ISSSTE"},
                {"value": "Seguro_Popular", "label": "Seguro Popular / IMSS-Bienestar"},
                {"value": "PEMEX", "label": "PEMEX"},
                {"value": "ISSFAM", "label": "ISSFAM (Fuerzas Armadas)"},
                {"value": "Privado", "label": "Seguro privado"},
                {"value": "Sin_seguro", "label": "Sin seguro"},
                {"value": "Otra", "label": "Otra"},
            ],
        },
        "estado_residencia": {
            "label": "Estado de residencia", "type": "select",
            "options": [
                "CDMX", "Estado de México", "Jalisco", "Nuevo León", "Puebla",
                "Guanajuato", "Veracruz", "Chihuahua", "Sonora", "Coahuila",
                "Otro estado MX", "Fuera de México",
            ],
        },
        "escolaridad": {
            "label": "Escolaridad", "type": "select",
            "options": [
                "Sin_estudios", "Primaria", "Secundaria", "Preparatoria",
                "Licenciatura", "Posgrado",
            ],
        },
        "ocupacion": {
            "label": "Ocupación", "type": "text",
        },
        "estado_civil": {
            "label": "Estado civil", "type": "select",
            "options": [
                "Soltero", "Casado", "Unión libre", "Divorciado",
                "Viudo", "Otro",
            ],
        },
        "tabaquismo": {
            "label": "Tabaquismo", "type": "select",
            "options": [
                {"value": "nunca", "label": "Nunca fumó"},
                {"value": "ex_fumador", "label": "Ex-fumador (suspendido >1a)"},
                {"value": "fumador_leve", "label": "Fumador leve (<10 cig/d)"},
                {"value": "fumador_moderado", "label": "Fumador moderado (10-20 cig/d)"},
                {"value": "fumador_severo", "label": "Fumador severo (>20 cig/d)"},
            ],
        },
        "paquetes_anio": {
            "label": "Paquetes-año (acumulado)", "type": "number",
            "unit": "paquetes-año",
        },
        "actividad_fisica": {
            "label": "Actividad física", "type": "select",
            "options": [
                {"value": "sedentario", "label": "Sedentario (<30 min/sem)"},
                {"value": "leve", "label": "Leve (30-150 min/sem)"},
                {"value": "moderada", "label": "Moderada (≥150 min/sem)"},
                {"value": "intensa", "label": "Intensa (>300 min/sem)"},
            ],
        },
        "ipss_score": {
            "label": "IPSS score (0-35) — síntomas urinarios baseline", "type": "number",
        },
    }
    info = canonical_labels.get(name, {})
    return {
        "name": name,
        "label": info.get("label", name.replace("_", " ").title()),
        "type": info.get("type", "text"),
        "required": True,  # always_visible == required
        "options": info.get("options", []),
        "default": "",
        "help": "",
        "clinical_role": "required",
        "disclosure_tier": "always_visible",
        "unit": info.get("unit", ""),
        "synthetic": True,  # Marker: not in pivotal helper
    }


def _compute_live_classification(
    captured: Mapping[str, Any], disease_state: str
) -> dict[str, Any]:
    """Best-effort live classification preview for the rail.

    Returns empty dict if not enough data to classify.
    """
    classification: dict[str, Any] = {}

    psa = _safe_float(captured.get("psa_value"))
    gleason = _safe_int(captured.get("gleason_score"))
    t_stage = str(captured.get("clinical_t_stage", "") or "").upper()

    # D'Amico risk classification (localized only)
    if disease_state == "localized_initial" and psa and gleason and t_stage:
        if psa < 10 and gleason <= 6 and t_stage in {"T1A", "T1B", "T1C", "T2A"}:
            classification["damico_risk"] = "low"
        elif psa > 20 or gleason >= 8 or t_stage in {"T3A", "T3B", "T4"}:
            classification["damico_risk"] = "very_high" if (gleason >= 9 or t_stage == "T4") else "high"
        else:
            classification["damico_risk"] = "intermediate"

    # CHAARTED HV/LV (mCSPC only)
    if disease_state.startswith("mcspc"):
        bone_count = _safe_int(captured.get("bone_lesion_count_total"))
        appendicular = _safe_int(captured.get("bone_appendicular_count"))
        visceral = _safe_bool(captured.get("visceral_metastasis_present"))
        if visceral or (bone_count and appendicular and bone_count >= 4 and appendicular >= 1):
            classification["chaarted_volume"] = "high"
            classification["chaarted_reason"] = (
                "Visceral mets" if visceral
                else f"≥4 óseas ({bone_count}) con ≥1 apendicular ({appendicular})"
            )
        elif bone_count is not None and bone_count < 4:
            classification["chaarted_volume"] = "low"
            classification["chaarted_reason"] = f"<4 óseas ({bone_count}) sin visceral"

        # LATITUDE high-risk (≥2 of 3: GS≥8, bone≥3, visceral)
        if gleason and bone_count is not None:
            criteria_met = sum([
                gleason >= 8,
                bone_count >= 3,
                bool(visceral),
            ])
            if criteria_met >= 2:
                classification["latitude_high_risk"] = True
                classification["latitude_criteria_met"] = criteria_met

    # PSADT band (m0_crpc, recurrence_bcr)
    # Boundaries per SPARTAN/PROSPER/ARAMIS NEJM 2018-2019 (PSADT ≤10m eligible)
    # + Stephenson JCO 2009 aggressive band (PSADT <3m).
    psadt = _safe_float(captured.get("psa_doubling_time_months"))
    if psadt is not None:
        if psadt < 3:
            classification["psadt_band"] = "rapid (<3m, aggressive)"
        elif psadt <= 10:
            classification["psadt_band"] = "moderate (3-10m, SPARTAN/PROSPER/ARAMIS eligible)"
        else:
            classification["psadt_band"] = "slow (>10m, low-risk)"

    return classification


def _compute_recommendation_preview(
    captured: Mapping[str, Any], disease_state: str
) -> dict[str, Any]:
    """Best-effort recommendation preview from clinical_subspecialty_engine."""
    try:
        from prostanet.shared.clinical_subspecialty_engine import (
            recommend_next_clinical_action,
        )
        # Attempt with minimal payload — engine returns [] if insufficient data
        actions = recommend_next_clinical_action(dict(captured))
        if actions:
            primary = actions[0]
            return {
                "primary_action": getattr(primary, "title", "")
                                  or getattr(primary, "action_key", ""),
                "rationale": getattr(primary, "rationale", "")
                             or getattr(primary, "description", ""),
                "urgency": getattr(primary, "urgency", "routine"),
                "evidence_tags": list(getattr(primary, "evidence_tags", []) or []),
                "confidence": getattr(primary, "confidence", 0.7),
                "additional_actions_count": len(actions) - 1,
            }
    except Exception:
        pass
    return {}


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "", []) else None
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(float(value)) if value not in (None, "", []) else None
    except (TypeError, ValueError):
        return None


def _safe_bool(value: Any) -> bool:
    if value in (None, "", [], "0", 0, False, "false", "no"):
        return False
    return True
