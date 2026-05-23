"""Tests EPIC 46.A — Latin Decision-Impacting Fields.

Valida los 4 cambios:
1. FACT_SPECS contiene los 4 fact_keys nuevos con configuración correcta
2. Intake schema (registration_fragment) renderiza los 4 widgets
3. resolve_ethnicity_key() puentea primary_ancestry → backend keys correctamente
4. Filter de acceso regional en arbiter re-rankea (no esconde) Lu-PSMA cuando inaccesible
5. Ancestría Afro-descendiente cambia el ethnicity_modifier vs Europeo (smoke clínico)

FAUBOT CXXXII — 2026-05-22.
"""
from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — FACT_SPECS inventory
# ─────────────────────────────────────────────────────────────────────────────


def test_epic46a_fact_specs_contains_4_new_keys():
    """Los 4 fact_keys nuevos deben estar registrados con metadata correcta."""
    from prostanet.shared.clinical_fact_registry import FACT_SPECS

    expected = {
        "primary_ancestry": {
            "domain": "systemic_context",
            "value_type": "text",
            "blocking": False,
        },
        "psma_pet_local_access": {
            "domain": "systemic_context",
            "value_type": "boolean",
            "blocking": False,
        },
        "lu_psma_local_access": {
            "domain": "systemic_context",
            "value_type": "boolean",
            "blocking": False,
        },
        "arsi_local_access": {
            "domain": "systemic_context",
            "value_type": "boolean",
            "blocking": False,
        },
    }

    for key, expected_attrs in expected.items():
        assert key in FACT_SPECS, f"FACT_SPECS missing '{key}'"
        spec = FACT_SPECS[key]
        assert spec.domain == expected_attrs["domain"], (
            f"{key} domain mismatch: {spec.domain} != {expected_attrs['domain']}"
        )
        assert spec.value_type == expected_attrs["value_type"], (
            f"{key} value_type mismatch: {spec.value_type}"
        )
        assert spec.blocking == expected_attrs["blocking"], (
            f"{key} blocking mismatch: {spec.blocking}"
        )
        # Cada uno debe declarar al menos un consumer del decision arbiter o profile
        assert any(
            c in spec.consumers
            for c in ("decision_arbiter", "natural_history",
                      "treatment_access_filter", "ethnicity_risk_modifier",
                      "profile", "decision_input_requirements")
        ), f"{key} sin consumer registrado relevante: {spec.consumers}"

    # primary_ancestry debe declarar legacy_aliases para retro-compat
    assert "ethnicity" in FACT_SPECS["primary_ancestry"].legacy_aliases, (
        "primary_ancestry debe alias-mapear a 'ethnicity' legacy"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — Intake schema renderiza widgets
# ─────────────────────────────────────────────────────────────────────────────


def test_epic46a_intake_schema_renders_4_widgets():
    """El fragment "Cohorte México" + "Acceso regional" debe exponer los 4
    fields nuevos con friendly labels y help_text explicativo."""
    from prostanet.domains.patient_tracking.service import _mexico_fragment

    fragment = _mexico_fragment()
    fields = list(getattr(fragment, "fields", None) or [])
    field_names = {
        (f.name if hasattr(f, "name") else f.get("name"))
        for f in fields
    }

    for required in (
        "primary_ancestry",
        "psma_pet_local_access",
        "lu_psma_local_access",
        "arsi_local_access",
    ):
        assert required in field_names, (
            f"_mexico_fragment() no expone '{required}'. "
            f"Found fields: {sorted(field_names)}"
        )

    # primary_ancestry debe estar en grupo "Cohorte México"
    # Los 3 access flags deben estar en grupo "Acceso regional a tratamientos"
    by_name = {
        (f.name if hasattr(f, "name") else f.get("name")): f
        for f in fields
    }
    ancestry = by_name["primary_ancestry"]
    assert getattr(ancestry, "group", None) == "Cohorte México", (
        f"primary_ancestry group debe ser 'Cohorte México', got {getattr(ancestry, 'group', None)!r}"
    )

    # Help text debe existir y NO contener lenguaje discriminatorio
    help_text = getattr(ancestry, "help_text", "") or ""
    assert "no afecta acceso a tratamiento" in help_text.lower() or "no restringe acceso" in help_text.lower(), (
        "primary_ancestry help_text debe aclarar explícitamente que NO afecta "
        "acceso a tratamiento (anti-discrimination disclaimer)"
    )

    for access_field in ("psma_pet_local_access", "lu_psma_local_access", "arsi_local_access"):
        f = by_name[access_field]
        assert getattr(f, "group", None) == "Acceso regional a tratamientos", (
            f"{access_field} group debe ser 'Acceso regional a tratamientos', "
            f"got {getattr(f, 'group', None)!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — resolve_ethnicity_key bridge
# ─────────────────────────────────────────────────────────────────────────────


def test_epic46a_resolve_ethnicity_key_maps_ui_to_backend():
    """resolve_ethnicity_key debe puentear UI labels → backend keys correctos."""
    from prostanet.domains.patient_tracking.natural_history_tracker import (
        resolve_ethnicity_key,
        ETHNICITY_RISK_MODIFIERS,
        PRIMARY_ANCESTRY_TO_ETHNICITY_KEY,
    )

    # UI value → expected backend key
    mappings = {
        "mestizo": "hispano_latino",
        "afro_descendiente": "afroamericano",
        "indigena": "indigena_americano",
        "europeo": "europeo_caucasico",
        "asiatico": "asiatico",
        "otro": "hispano_latino",
        "no_declarado": "europeo_caucasico",
    }

    for ui_value, expected_backend_key in mappings.items():
        result = resolve_ethnicity_key(primary_ancestry=ui_value)
        assert result == expected_backend_key, (
            f"UI '{ui_value}' debe resolver a backend '{expected_backend_key}', "
            f"got '{result}'"
        )
        # El backend key debe existir en ETHNICITY_RISK_MODIFIERS
        assert result in ETHNICITY_RISK_MODIFIERS, (
            f"Backend key '{result}' no existe en ETHNICITY_RISK_MODIFIERS"
        )

    # Legacy fallback: si no hay primary_ancestry, usa legacy_ethnicity
    assert resolve_ethnicity_key(legacy_ethnicity="afroamericano") == "afroamericano"
    # Ambos vacíos: fallback europeo
    assert resolve_ethnicity_key() == "europeo_caucasico"
    # primary_ancestry tiene precedencia sobre legacy
    assert resolve_ethnicity_key(
        primary_ancestry="mestizo",
        legacy_ethnicity="europeo_caucasico",
    ) == "hispano_latino"


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — Filter de acceso regional en arbiter
# ─────────────────────────────────────────────────────────────────────────────


def test_epic46a_arbiter_marks_lu_psma_as_access_restricted():
    """Si lu_psma_local_access='0', Lu-PSMA debe re-rankearse al final
    + marcarse con access_restricted=True + access_warnings populado.
    NO debe ser eliminado del ranking (clínico mantiene control)."""
    from prostanet.domains.decision_arbiter.recommendation_arbiter import (
        arbitrate_recommendations,
    )

    twin_ranking = [
        {"rank": 1, "regimen_name": "Lu-PSMA-617 (Pluvicto)",
         "primary_drug": "lutetium_177_psma_617", "expected_os_gain_mo": 4.0},
        {"rank": 2, "regimen_name": "Cabazitaxel",
         "primary_drug": "cabazitaxel", "expected_os_gain_mo": 2.5},
        {"rank": 3, "regimen_name": "Enzalutamide",
         "primary_drug": "enzalutamide", "expected_os_gain_mo": 5.0},
    ]
    facts = {
        "lu_psma_local_access": "0",
        "arsi_local_access": "1",
        "psma_pet_local_access": "1",
    }

    decision = arbitrate_recommendations(
        cards=[], twin_ranking=twin_ranking, facts=facts,
    )

    # Lu-PSMA debe seguir presente (no eliminado)
    drugs_in_ranking = [
        str(r.get("regimen_name") or r.get("primary_drug")).lower()
        for r in decision.arbitrated_ranking
    ]
    assert any("lu-psma" in d or "lutetium" in d for d in drugs_in_ranking), (
        "Lu-PSMA NO debe eliminarse del ranking, solo re-rankear al final"
    )

    # Lu-PSMA debe estar en última posición
    last_item = decision.arbitrated_ranking[-1]
    last_drug = str(last_item.get("regimen_name") or last_item.get("primary_drug")).lower()
    assert "lu-psma" in last_drug or "lutetium" in last_drug, (
        f"Lu-PSMA debe ir al final del ranking, got last={last_drug}"
    )

    # El item Lu-PSMA debe tener access_restricted=True
    assert last_item.get("access_restricted") is True, (
        "Lu-PSMA item debe tener access_restricted=True"
    )
    assert "sin acceso local" in (last_item.get("access_note") or "").lower(), (
        f"Lu-PSMA debe tener access_note explicativo, got {last_item.get('access_note')!r}"
    )

    # access_warnings debe contener entry para lu_psma
    assert any(w.get("drug") == "lu_psma_617" for w in decision.access_warnings), (
        f"access_warnings sin entry lu_psma_617: {decision.access_warnings}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — Ancestría cambia ethnicity_modifier (smoke clínico)
# ─────────────────────────────────────────────────────────────────────────────


def test_epic46a_afro_ancestry_modifies_risk_vs_europeo():
    """Smoke clínico: el mismo paciente con primary_ancestry='afro_descendiente'
    debe producir un ethnicity_modifier distinto que con 'europeo'. Específicamente
    incidence_rr=1.73 para Afro vs 1.00 para Europeo."""
    from prostanet.domains.patient_tracking.natural_history_tracker import (
        ETHNICITY_RISK_MODIFIERS,
        resolve_ethnicity_key,
    )

    afro_key = resolve_ethnicity_key(primary_ancestry="afro_descendiente")
    europeo_key = resolve_ethnicity_key(primary_ancestry="europeo")

    afro_modifier = ETHNICITY_RISK_MODIFIERS[afro_key]
    europeo_modifier = ETHNICITY_RISK_MODIFIERS[europeo_key]

    # Afro-descendiente debe tener mayor incidence_rr y mortality_rr (evidencia SEER)
    assert afro_modifier["incidence_rr"] > europeo_modifier["incidence_rr"], (
        f"Afro incidence_rr ({afro_modifier['incidence_rr']}) debe ser mayor "
        f"que Europeo ({europeo_modifier['incidence_rr']})"
    )
    assert afro_modifier["mortality_rr"] > europeo_modifier["mortality_rr"], (
        f"Afro mortality_rr ({afro_modifier['mortality_rr']}) debe ser mayor "
        f"que Europeo ({europeo_modifier['mortality_rr']})"
    )

    # Mestizo (hispano_latino) debe tener riesgo intermedio o menor que europeo
    mestizo_key = resolve_ethnicity_key(primary_ancestry="mestizo")
    mestizo_modifier = ETHNICITY_RISK_MODIFIERS[mestizo_key]
    assert mestizo_modifier["incidence_rr"] < europeo_modifier["incidence_rr"], (
        f"Mestizo (hispano_latino) incidence_rr ({mestizo_modifier['incidence_rr']}) "
        f"debe ser < Europeo ({europeo_modifier['incidence_rr']}) por evidencia PCBaSe"
    )

    # Indígena debe tener entrada propia (EPIC 46.A nueva)
    indigena_key = resolve_ethnicity_key(primary_ancestry="indigena")
    assert indigena_key == "indigena_americano"
    assert indigena_key in ETHNICITY_RISK_MODIFIERS, (
        "ETHNICITY_RISK_MODIFIERS debe tener entrada indigena_americano "
        "(creada en EPIC 46.A para visibilidad clínica)"
    )
    # Debe estar flagged como model_extrapolated (transparencia regulatoria)
    indigena_modifier = ETHNICITY_RISK_MODIFIERS[indigena_key]
    assert indigena_modifier.get("data_quality_flag") == (
        "model_extrapolated_pending_local_recalibration"
    ), "Indígena debe estar flagged para futuro re-calibration con cohorte propia"
