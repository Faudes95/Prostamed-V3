"""Sprint 1 validation fixes — tests dedicados de los 5 fixes críticos.

FIX A: Deprecación Smart Capture (302 redirect)
FIX #2: register_new_patient persiste 4 fact_keys EPIC 46.A
FIX #3 + #4: Pipeline metastatic_visceral acepta aliases + clasifica M1c high-vol
FIX #5: Confidence honest (vacuous truth → ≤35% si fallback path)
FIX #8: Banner warning visible en template cuando is_contextual_fallback

FAUBOT CXXXVII — 2026-05-24.
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────
# FIX A — Smart Capture deprecation
# ─────────────────────────────────────────────────────────────────────


def test_sprint1_fixA_intake_smart_redirects_to_clasificador_oficial():
    """GET /intake/smart debe retornar 302 → /clinical-hub#pm2OfficialClassifier."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "app.py"
    content = src.read_text(encoding="utf-8")
    # Source-level guard: el handler debe contener el redirect
    assert "/intake/smart" in content
    # Buscar la cadena específica del redirect (multi-line tolerant)
    has_redirect = (
        'redirect("/clinical-hub#pm2OfficialClassifier", code=302)' in content
        or "redirect('/clinical-hub#pm2OfficialClassifier', code=302)" in content
    )
    assert has_redirect, "Smart Capture handler no contiene redirect a clasificador oficial"
    # Y NO debe hacer render_template del template original
    handler_section = content[content.find("@app.route(\"/intake/smart\""):]
    handler_section = handler_section[:handler_section.find("@app.route", 50)]
    assert "render_template" not in handler_section or "DEPRECATED" in handler_section, (
        "Smart Capture handler aún renderiza template — debe SOLO redirigir"
    )


# ─────────────────────────────────────────────────────────────────────
# FIX #2 — EPIC 46.A fields extracted by canonical fact pipeline
# ─────────────────────────────────────────────────────────────────────


def test_sprint1_fix2_epic46a_fields_in_canonical_extractor():
    """Los 4 fact_keys EPIC 46.A deben estar en extract_canonical_fact_candidates."""
    from prostanet.shared.clinical_fact_registry import extract_canonical_fact_candidates

    payload = {
        "primary_ancestry": "afro_descendiente",
        "psma_pet_local_access": "1",
        "lu_psma_local_access": "0",
        "arsi_local_access": "1",
        "ecog_score": "1",
    }
    facts = extract_canonical_fact_candidates(
        payload,
        source_type="wizard_or_intake",
        source_record_type="patient_registration",
        source_record_id=999,
        source_date="2026-05-24",
    )
    fact_keys = {f.get("fact_key") for f in facts if isinstance(f, dict)}
    for required in ("primary_ancestry", "psma_pet_local_access",
                     "lu_psma_local_access", "arsi_local_access"):
        assert required in fact_keys, (
            f"FIX #2: {required} no extraído por extract_canonical_fact_candidates"
        )


# ─────────────────────────────────────────────────────────────────────
# FIX #3 + #4 — Metastatic visceral pipeline + alias acceptance
# ─────────────────────────────────────────────────────────────────────


def test_sprint1_fix4_metastatic_visceral_accepts_alias_metastasis_visceral_present():
    """metastasis_visceral_present (alias) debe ser aceptado igual que
    visceral_metastasis_present (canonical)."""
    from prostanet.shared.metastatic_profile import build_metastatic_profile as compute_metastatic_profile

    payload_canonical = {"visceral_metastasis_present": "1"}
    payload_alias = {"metastasis_visceral_present": "1"}  # orden invertido

    profile_canonical = compute_metastatic_profile(payload_canonical)
    profile_alias = compute_metastatic_profile(payload_alias)

    assert profile_canonical.get("visceral_metastasis_present") is True, (
        "Canonical key debe seguir funcionando"
    )
    assert profile_alias.get("visceral_metastasis_present") is True, (
        "FIX #4: alias metastasis_visceral_present (orden invertido) debe ser aceptado"
    )


def test_sprint1_fix4_visceral_mets_classifies_high_volume_m1c():
    """Paciente con visceral mets debe clasificarse M1c + high volume."""
    from prostanet.shared.metastatic_profile import build_metastatic_profile as compute_metastatic_profile

    payload = {
        "visceral_metastasis_present": "1",
        "visceral_lesion_count": 2,
        "visceral_sites": ["liver"],
    }
    profile = compute_metastatic_profile(payload)
    assert profile["m_substage_resolved"] == "M1c"
    assert profile["visceral_metastasis_present"] is True
    assert profile["oligometastatic_operational"] is False, (
        "Visceral mets ≠ oligometastatic (CHAARTED criterion)"
    )


# ─────────────────────────────────────────────────────────────────────
# FIX #5 — Confidence honesty (vacuous truth penalty)
# ─────────────────────────────────────────────────────────────────────


def test_sprint1_fix5_confidence_capped_for_compass_context_fallback():
    """Si primary_source_engine='compass_context_fallback', confianza ≤35%
    aunque concordances retornen all-True."""
    from prostanet.domains.decisions.decision_narrative_builder import _compute_confidence

    # Caso 1: fallback path → cap a 0.35 incluso con todas concordancias True
    full_concordance = {
        "compass_twin_concordant": True,
        "fusion_no_conflicts": True,
        "ml_concordant": True,
        "trajectory_corroborates": True,
        "godibot_no_blocks": True,
    }
    conf_fallback = _compute_confidence(
        full_concordance, n_anchors=5, n_discordances=0,
        primary_source_engine="compass_context_fallback",
        n_substantive_engines=0,
    )
    assert conf_fallback <= 0.35, (
        f"FIX #5: fallback path debe cap a 0.35, got {conf_fallback}"
    )


def test_sprint1_fix5_confidence_capped_when_few_substantive_engines():
    """Si <50% de engines opinaron, confidence ≤0.5 (vacuous truth)."""
    from prostanet.domains.decisions.decision_narrative_builder import _compute_confidence

    full_concordance = {f"engine_{i}": True for i in range(5)}
    conf_few = _compute_confidence(
        full_concordance, n_anchors=3, n_discordances=0,
        primary_source_engine="decision_fusion",
        n_substantive_engines=1,  # solo 1/5 = 20%
    )
    assert conf_few <= 0.5, (
        f"FIX #5: <50% substantive → cap 0.5, got {conf_few}"
    )


def test_sprint1_fix5_full_confidence_when_engines_substantive():
    """Si TODOS los engines opinaron substantivamente, confianza puede ser >0.5."""
    from prostanet.domains.decisions.decision_narrative_builder import _compute_confidence

    full_concordance = {f"engine_{i}": True for i in range(5)}
    conf_full = _compute_confidence(
        full_concordance, n_anchors=5, n_discordances=0,
        primary_source_engine="decision_fusion",
        n_substantive_engines=5,  # 5/5 = 100%
    )
    assert conf_full > 0.7, (
        f"FIX #5: full substantive engines + concordancia debe ≥0.7, got {conf_full}"
    )


def test_sprint1_fix5_count_substantive_engines_helper():
    """_count_substantive_engines clasifica correctamente engines populated vs vacíos."""
    from prostanet.domains.decisions.decision_narrative_builder import _count_substantive_engines

    # Todos vacíos
    assert _count_substantive_engines({}, {}, {}, {}, {}, {}) == 0
    # Compass populated
    assert _count_substantive_engines(
        {"next_best_action": {"label": "X"}}, {}, {}, {}, {}, {}
    ) == 1
    # Twin populated
    assert _count_substantive_engines(
        {}, {"regimen_rankings_personalized": [{"a": 1}]}, {}, {}, {}, {}
    ) == 1
    # ML populated
    assert _count_substantive_engines(
        {}, {}, {}, {"available": True, "models": {"a": {"available": True}}}, {}, {}
    ) == 1


# ─────────────────────────────────────────────────────────────────────
# FIX #8 — Banner warning template
# ─────────────────────────────────────────────────────────────────────


def test_sprint1_fix8_template_has_fallback_banner_with_cta():
    """patient_profile_v2.html declara banner + CTA al clasificador oficial."""
    from pathlib import Path
    template = Path(__file__).parent.parent / "templates" / "patient_profile_v2.html"
    content = template.read_text(encoding="utf-8")
    # Banner data-testid presente
    assert 'data-testid="decision-narrative-fallback-banner"' in content
    # CTA al clasificador
    assert 'data-testid="decision-narrative-classifier-cta"' in content
    assert "/clinical-hub#pm2OfficialClassifier" in content
    # Condicional sobre is_contextual_fallback
    assert "is_contextual_fallback" in content
    # Texto "Clasificación incompleta"
    assert "Clasificación incompleta" in content or "ClasificaciÃ³n incompleta" in content


# ─────────────────────────────────────────────────────────────────────
# Integration smoke — narrative builder produce is_contextual_fallback
# en bundle vacío
# ─────────────────────────────────────────────────────────────────────


def test_sprint1_fix5and8_integration_empty_bundle_triggers_fallback_lowconfidence():
    """Bundle con solo compass.effective_state_label (sin engines populados) →
    is_contextual_fallback=True + confidence ≤0.35 + banner condition met."""
    from prostanet.domains.decisions.decision_narrative_builder import build_decision_narrative

    bundle = {
        "clinical_compass": {
            "effective_state_label": "Enfermedad localizada",
            "current_diagnosis": "Diagnóstico en consolidación",
        },
        # Twin / fusion / ml todos vacíos
    }
    result = build_decision_narrative(bundle)
    assert result["available"] is True
    primary = result["primary_recommendation"]
    assert primary.get("is_contextual_fallback") is True, (
        "Bundle minimal debe activar contextual fallback"
    )
    assert primary.get("source_engine") == "compass_context_fallback"
    # Confidence HARD-CAPPED a 0.35
    assert result["confidence_score"] <= 0.35, (
        f"FIX #5: fallback path confidence debe ≤0.35, got {result['confidence_score']}"
    )
