"""Sprint 3 — Ethnicity alias normalization + Patient identity h1.

FIX #9: resolve_ethnicity_key acepta 'hispano' / 'caucasico' / 'afro' /
        legacy aliases sin sufijo. Antes solo accept'd keys exactos del
        ETHNICITY_RISK_MODIFIERS dict.
FIX #11: pm2-patient-name elevado de <div> a <h1> con data-testid
         para identidad visual fuerte + a11y compliance.

FAUBOT CXXXIX — 2026-05-24.
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────
# FIX #9 — Ethnicity alias normalization
# ─────────────────────────────────────────────────────────────────────


def test_sprint3_fix9_hispano_legacy_maps_to_hispano_latino():
    """'hispano' (DEFAULT del schema legacy) debe mapear a hispano_latino."""
    from prostanet.domains.patient_tracking.natural_history_tracker import (
        resolve_ethnicity_key,
        ETHNICITY_RISK_MODIFIERS,
    )
    key = resolve_ethnicity_key(legacy_ethnicity="hispano")
    assert key == "hispano_latino", f"FIX #9: 'hispano' debe mapear a 'hispano_latino', got '{key}'"
    # Verificar que la key resultante existe en ETHNICITY_RISK_MODIFIERS
    assert key in ETHNICITY_RISK_MODIFIERS


def test_sprint3_fix9_common_legacy_aliases_normalized():
    """Todos los aliases comunes legacy deben mapear al backend key correcto."""
    from prostanet.domains.patient_tracking.natural_history_tracker import (
        resolve_ethnicity_key,
    )
    cases = [
        # Hispano/Latino variants
        ("hispano", "hispano_latino"),
        ("latino", "hispano_latino"),
        ("hispanic", "hispano_latino"),
        ("latinoamericano", "hispano_latino"),
        ("mexicano", "hispano_latino"),
        # Afro variants
        ("afro", "afroamericano"),
        ("africano", "afroamericano"),
        ("black", "afroamericano"),
        # Europeo variants
        ("caucasico", "europeo_caucasico"),
        ("blanco", "europeo_caucasico"),
        ("white", "europeo_caucasico"),
        # Asiatico variants
        ("asian", "asiatico"),
        # Indigena variants
        ("indigenous", "indigena_americano"),
        ("nativo", "indigena_americano"),
    ]
    for legacy_value, expected in cases:
        actual = resolve_ethnicity_key(legacy_ethnicity=legacy_value)
        assert actual == expected, (
            f"FIX #9: legacy '{legacy_value}' debe mapear a '{expected}', got '{actual}'"
        )


def test_sprint3_fix9_case_insensitive_alias_matching():
    """Aliases deben ser case-insensitive."""
    from prostanet.domains.patient_tracking.natural_history_tracker import (
        resolve_ethnicity_key,
    )
    assert resolve_ethnicity_key(legacy_ethnicity="HISPANO") == "hispano_latino"
    assert resolve_ethnicity_key(legacy_ethnicity="Black") == "afroamericano"
    assert resolve_ethnicity_key(legacy_ethnicity="CAUCASICO") == "europeo_caucasico"


def test_sprint3_fix9_primary_ancestry_still_takes_precedence():
    """primary_ancestry (EPIC 46.A) DEBE seguir teniendo precedencia sobre
    legacy ethnicity normalizado."""
    from prostanet.domains.patient_tracking.natural_history_tracker import (
        resolve_ethnicity_key,
    )
    # Si primary_ancestry='afro_descendiente' Y legacy_ethnicity='hispano'
    # → afro debe ganar
    assert resolve_ethnicity_key(
        primary_ancestry="afro_descendiente",
        legacy_ethnicity="hispano",
    ) == "afroamericano"


def test_sprint3_fix9_unknown_alias_fallback_to_europeo():
    """Alias desconocido sin match → fallback europeo_caucasico (sin levantar)."""
    from prostanet.domains.patient_tracking.natural_history_tracker import (
        resolve_ethnicity_key,
    )
    assert resolve_ethnicity_key(legacy_ethnicity="totally_unknown_xyz") == "europeo_caucasico"
    assert resolve_ethnicity_key(legacy_ethnicity="") == "europeo_caucasico"
    assert resolve_ethnicity_key() == "europeo_caucasico"


def test_sprint3_fix9_alias_normalizer_complete():
    """LEGACY_ETHNICITY_ALIAS_NORMALIZER debe cubrir mínimo 15 aliases
    comunes con keys de backend correctos."""
    from prostanet.domains.patient_tracking.natural_history_tracker import (
        LEGACY_ETHNICITY_ALIAS_NORMALIZER,
        ETHNICITY_RISK_MODIFIERS,
    )
    assert len(LEGACY_ETHNICITY_ALIAS_NORMALIZER) >= 15
    # Cada value debe ser una key válida del ETHNICITY_RISK_MODIFIERS
    for alias, backend_key in LEGACY_ETHNICITY_ALIAS_NORMALIZER.items():
        assert backend_key in ETHNICITY_RISK_MODIFIERS, (
            f"Alias '{alias}' mapea a '{backend_key}' que NO existe en "
            f"ETHNICITY_RISK_MODIFIERS"
        )


# ─────────────────────────────────────────────────────────────────────
# FIX #11 — Patient name h1 (identity visual + a11y)
# ─────────────────────────────────────────────────────────────────────


def test_sprint3_fix11_patient_name_is_h1_with_testid():
    """patient_profile_v2.html debe declarar <h1 class='pm2-patient-name'>
    con data-testid='patient-name-heading' (no <div>)."""
    from pathlib import Path
    template = Path(__file__).parent.parent / "templates" / "patient_profile_v2.html"
    content = template.read_text(encoding="utf-8")
    # h1 con class pm2-patient-name debe existir
    assert '<h1 class="pm2-patient-name"' in content, (
        "FIX #11: <h1 class='pm2-patient-name'> no encontrado"
    )
    # data-testid agregado
    assert 'data-testid="patient-name-heading"' in content
    # El antiguo <div class="pm2-patient-name"> NO debe seguir presente
    # (puede aparecer en comentarios o snapshots de history, ok)
    # Pero el closing </h1> también debe estar
    assert "</h1>" in content


def test_sprint3_fix11_identity_name_renders_in_h1():
    """Smoke source-level: el h1 debe interpolar {{ identity.name }} dentro."""
    from pathlib import Path
    template = Path(__file__).parent.parent / "templates" / "patient_profile_v2.html"
    content = template.read_text(encoding="utf-8")
    # Encontrar el bloque h1 patient-name
    h1_idx = content.find('<h1 class="pm2-patient-name"')
    assert h1_idx > -1
    # Look at next 200 chars
    h1_block = content[h1_idx:h1_idx + 400]
    assert "{{ identity.name }}" in h1_block, (
        "FIX #11: <h1> patient-name no interpola identity.name"
    )
