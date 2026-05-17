"""EPIC 44.A — Display labels clínicamente densos en intake.

Garantiza que los campos anti-pattern reportados por el urólogo
("0/1" raw para BCR, PSMA, visceral_mets, etc.) ahora rendericen labels
clínicamente densos sin que el clínico tenga que abrir el help_text.

Cobertura:
  - resolve_option_label retorna labels ricos para 25+ campos críticos
  - quick_classify_schema propaga display_options con value+label
  - El template intake_smart_capture.html ya NO renderiza {{ opt }} crudo
  - Backend compat: schema sigue exportando 'options' con raw values
"""
from __future__ import annotations

from pathlib import Path

import pytest

from prostanet.shared.presentation_text import (
    BOOLEAN_CONTEXTUAL_OPTION_LABELS,
    BOOLEAN_OPTION_LABELS,
    OPTION_LABELS,
    resolve_option_label,
)


# ─────────────────────────────────────────────────────────────────────────────
# Anti-patterns críticos reportados por urólogo (visual smoke EPIC 44 phase 0).
# Cada tupla: (field_name, value, expected_label_prefix)
# ─────────────────────────────────────────────────────────────────────────────
ANTI_PATTERNS_CLINICAL_LABELS = [
    # BCR / metastasis context
    ("bcr_detected", "0", "Sin BCR confirmada"),
    ("bcr_detected", "1", "BCR confirmada"),
    ("metachronous_metastasis", "0", "Sincrónica"),
    ("metachronous_metastasis", "1", "Metacrónica"),
    ("visceral_metastasis_present", "0", "No (M ósea"),
    ("visceral_metastasis_present", "1", "Sí (hígado"),
    ("metastatic_disease_known", "0", "Sin evidencia de enfermedad metastásica"),
    ("metastatic_disease_known", "1", "Enfermedad metastásica documentada"),
    ("bone_metastasis_present", "1", "Metástasis óseas presentes"),
    ("nonregional_nodal_metastasis_present", "1", "Sí (cadena no regional"),
    # PSMA / imaging
    ("psma_positive", "0", "Sin enfermedad PSMA"),
    ("psma_positive", "1", "PSMA-positiva"),
    ("mpmri_done", "1", "Realizada"),
    ("bone_scan_done", "1", "Realizada"),
    ("ct_abdomen_pelvis_done", "1", "Realizada"),
    # Histopathology / risk markers
    ("perineural_invasion", "0", "Ausente"),
    ("perineural_invasion", "1", "Presente"),
    ("extracapsular_extension_on_biopsy", "1", "Presente"),
    ("lymphovascular_invasion", "1", "Presente"),
    ("cribriform_pattern", "1", "Presente (patrón cribiforme"),
    ("intraductal_carcinoma", "1", "Presente (componente intraductal"),
    # Comorbilidades + CV / cognitivo
    ("severe_cv_disease", "0", "Sin enfermedad CV severa"),
    ("severe_cv_disease", "1", "Sí (IC NYHA"),
    ("cognitive_impairment_documented", "1", "Deterioro cognitivo documentado"),
    ("comorbidity_seizure", "0", "Sin antecedente de convulsiones"),
    ("comorbidity_cardio", "1", "Sí (riesgo abi/enza"),
    # Family history / germline
    ("known_cancer_diagnosis", "1", "Sí, confirmado por biopsia"),
    ("known_cancer_diagnosis", "0", "No, en evaluación"),
    ("family_history_positive", "1", "Sí (1º grado"),
    ("germline_risk_mutation", "1", "Sí, mutación germline patogénica"),
    ("germline_testing_performed", "0", "No realizado"),
    ("first_degree_relative_pca_lt60", "1", "Sí, familiar 1º grado CaP"),
    ("first_degree_relative_brca_breast_ovarian", "1", "Sí, familiar 1º grado BRCA"),
    ("lynch_syndrome_features", "1", "Características de síndrome de Lynch"),
    # Castration / CRPC
    ("castration_resistant", "0", "Sensible a castración"),
    ("castration_resistant", "1", "Resistente a castración (CRPC)"),
    # Screening / biopsy context
    ("screening_context", "0", "Evaluación con sospecha"),
    ("screening_context", "1", "Screening poblacional"),
    ("biopsy_scheduled", "1", "Programada"),
    ("prior_negative_biopsy", "1", "Biopsia previa negativa"),
    ("dre_suspicious", "0", "Tacto no sospechoso"),
    ("dre_suspicious", "1", "Tacto sospechoso"),
    # Surgical pathology
    ("surgical_margin", "1", "Márgenes positivos (R1)"),
    ("ece_status", "1", "Extensión extracapsular presente"),
    ("svi_status", "1", "Invasión vesical seminal presente"),
    ("lni_status", "1", "Invasión ganglionar presente"),
    # Molecular / biomarkers
    ("hrr_pathogenic_variant", "1", "Variante HRR patogénica"),
    ("msi_high", "1", "MSI-high (candidato pembrolizumab"),
    ("tmb_high", "1", "TMB ≥10"),
]


@pytest.mark.parametrize("field,value,expected_prefix", ANTI_PATTERNS_CLINICAL_LABELS)
def test_anti_pattern_field_renders_clinical_label(field, value, expected_prefix):
    """Cada anti-pattern field renderiza un label clínicamente denso."""
    raw_options = [{"value": "0"}, {"value": "1"}]
    label = resolve_option_label(field, value, raw_options)
    assert label.startswith(expected_prefix), (
        f"EPIC 44.A regression: field={field!r} value={value!r} "
        f"expected prefix {expected_prefix!r}, got {label!r}. "
        f"Urólogo escanea {field} y debe ver {expected_prefix!r}, NO '0'/'1' raw."
    )


# ─────────────────────────────────────────────────────────────────────────────
# "unknown" / "pending" fallbacks claros (evita opaco "unknown" en UI)
# ─────────────────────────────────────────────────────────────────────────────
UNKNOWN_FALLBACKS = [
    ("perineural_invasion", "unknown", "No documentada"),
    ("severe_cv_disease", "unknown", "No documentado"),
    ("germline_testing_performed", "unknown", "No documentado"),
    ("germline_testing_performed", "pending", "Resultado pendiente"),
    ("psma_positive", "unknown", "No documentado"),  # via _uses_boolean detection
]


@pytest.mark.parametrize("field,value,expected", UNKNOWN_FALLBACKS)
def test_unknown_pending_have_clear_fallback(field, value, expected):
    """unknown / pending no se renderizan crudos — el clínico ve un label claro."""
    raw_options = [{"value": "unknown"}, {"value": "0"}, {"value": "1"}]
    label = resolve_option_label(field, value, raw_options)
    assert label == expected, (
        f"EPIC 44.A: field={field!r} value={value!r} "
        f"expected {expected!r}, got {label!r}. "
        "unknown/pending crudo en UI es opaco para el urólogo."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Schema propagation: display_options llega al template
# ─────────────────────────────────────────────────────────────────────────────
def test_quick_classify_schema_propagates_display_options():
    """quick_classify_schema() retorna fields con display_options enriquecidos."""
    from prostanet.presentation.v2_adapters import quick_classify_schema

    schema = quick_classify_schema()
    by_name = {f["name"]: f for f in schema["fields"]}

    critical_fields = [
        "bcr_detected", "psma_positive", "visceral_metastasis_present",
        "metachronous_metastasis", "known_cancer_diagnosis",
    ]
    for fn in critical_fields:
        if fn not in by_name:
            continue  # field might be conditionally hidden — skip
        f = by_name[fn]
        assert "display_options" in f, (
            f"EPIC 44.A: schema field {fn!r} missing display_options key "
            "(_with_display_options() debería poblarlo)"
        )
        disp = f["display_options"]
        assert isinstance(disp, list) and len(disp) > 0, (
            f"EPIC 44.A: {fn!r} display_options vacío o malformado: {disp!r}"
        )
        for opt in disp:
            assert isinstance(opt, dict) and "value" in opt and "label" in opt, (
                f"EPIC 44.A: {fn!r} option malformada: {opt!r}"
            )


def test_backward_compat_options_key_preserved():
    """Schema export sigue incluyendo 'options' con raw values (backend compat).

    Voice extractors EPIC 36 + smart_capture.js esperan 'options' con valores
    canónicos. display_options es PARALELO, no reemplazo.
    """
    from prostanet.presentation.v2_adapters import quick_classify_schema

    schema = quick_classify_schema()
    for f in schema["fields"]:
        if f.get("field_type") == "select":
            assert "options" in f, (
                f"EPIC 44.A: field {f.get('name')!r} perdió la key 'options' — "
                "rompería voice extractors EPIC 36 y JS auto-save."
            )


# ─────────────────────────────────────────────────────────────────────────────
# Template anti-pattern check: el HTML ya no itera f.options raw
# ─────────────────────────────────────────────────────────────────────────────
def test_intake_smart_capture_template_renders_display_options():
    """intake_smart_capture.html debe iterar f.display_options, no f.options."""
    template_path = (
        Path(__file__).resolve().parent.parent
        / "templates"
        / "intake_smart_capture.html"
    )
    assert template_path.exists(), f"Template no encontrado: {template_path}"
    content = template_path.read_text(encoding="utf-8")

    # Anti-pattern: iterar f.options + renderizar {{ opt }} como label
    # (forma exacta que el bug pre-EPIC 44.A tenía)
    assert "{% for opt in f.options %}" not in content, (
        "EPIC 44.A regression: intake_smart_capture.html sigue iterando "
        "f.options raw — debe usar f.display_options"
    )
    assert ">{{ opt }}</option>" not in content, (
        "EPIC 44.A regression: intake_smart_capture.html sigue renderizando "
        "{{ opt }} crudo como label — debe usar el label del display_option"
    )

    # Patrón positivo esperado: display_options con value y label separados
    assert "f.display_options" in content, (
        "EPIC 44.A: intake_smart_capture.html debe leer f.display_options"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Coverage census: cuántos fields anti-pattern tienen label rico ahora
# ─────────────────────────────────────────────────────────────────────────────
def test_coverage_census_min_25_clinical_fields_have_rich_labels():
    """Census: ≥25 fields clínicos críticos tienen label rico en BOOLEAN_CONTEXTUAL.

    Si este test falla con count<25, alguien removió labels recientes y
    el clínico volverá a ver "0/1" raw.
    """
    rich = sum(
        1 for f, m in BOOLEAN_CONTEXTUAL_OPTION_LABELS.items()
        if isinstance(m, dict) and ("0" in m or "1" in m)
    )
    assert rich >= 25, (
        f"EPIC 44.A: solo {rich} fields tienen labels ricos en "
        f"BOOLEAN_CONTEXTUAL_OPTION_LABELS — esperaba ≥25. "
        "Pre-fix había ~5 (mostly hepático). Si bajó, hubo regresión."
    )


def test_boolean_option_labels_baseline_still_sí_no():
    """Sanity: el fallback genérico boolean sigue "No"/"Sí" para fields sin override."""
    assert BOOLEAN_OPTION_LABELS == {"0": "No", "1": "Sí"}


def test_known_cancer_diagnosis_overrides_baseline():
    """OPTION_LABELS gana sobre BOOLEAN_OPTION_LABELS (resolve_option_label orden)."""
    label_0 = resolve_option_label("known_cancer_diagnosis", "0", [{"value": "0"}, {"value": "1"}])
    label_1 = resolve_option_label("known_cancer_diagnosis", "1", [{"value": "0"}, {"value": "1"}])
    assert "evaluación" in label_0.lower()
    assert "biopsia" in label_1.lower()
