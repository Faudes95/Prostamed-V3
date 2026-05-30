import re

import pytest

from prostanet.domains.diagnostic_workup.derivations import (
    derive_dre_context,
    derive_mri_context,
    derive_psad_context,
)
from prostanet.domains.diagnostic_workup.service import DiagnosticWorkupService


def test_dre_t2b_is_suspicious_and_psad_is_derived_or_not_calculable():
    dre = derive_dre_context({"dre_finding": "T2b - Afecta >50% de un lóbulo"})
    assert dre.is_suspicious is True
    assert dre.implied_tstage == "cT2b"
    assert "sospechoso" in dre.summary_label

    legacy = derive_dre_context({"dre_suspicious": 1})
    assert legacy.is_suspicious is True
    assert legacy.source == "dre_suspicious"

    calculated = derive_psad_context({"psa": 12, "prostate_volume_ml": 40})
    assert calculated.calculable is True
    assert calculated.value == 0.3
    assert calculated.display == "0.30 ng/mL/cc"

    missing_volume = derive_psad_context({"psa": 12})
    assert missing_volume.value is None
    assert missing_volume.display == "no calculable por falta de volumen prostático"


@pytest.mark.parametrize(
    ("dre_finding", "expected_tstage"),
    [
        ("T2a - Afecta ≤50% de un lóbulo", "cT2a"),
        ("T2b - Afecta >50% de un lóbulo", "cT2b"),
        ("T2c - Afecta ambos lóbulos", "cT2c"),
        ("T3 - Extensión fuera de la cápsula", "cT3"),
        ("T4 - Invade órganos adyacentes", "cT4"),
    ],
)
def test_all_clinically_abnormal_dre_t_stages_are_suspicious(dre_finding, expected_tstage):
    dre = derive_dre_context({"dre_finding": dre_finding})

    assert dre.is_suspicious is True
    assert dre.implied_tstage == expected_tstage
    assert dre.summary_label == f"sospechoso compatible con {expected_tstage}"


@pytest.mark.parametrize(
    ("dre_finding", "expected_tstage"),
    [
        ("T2a - Afecta ≤50% de un lóbulo", "cT2a"),
        ("T2c - Afecta ambos lóbulos", "cT2c"),
        ("T4 - Invade órganos adyacentes", "cT4"),
    ],
)
def test_diagnostic_summary_does_not_downgrade_abnormal_dre_stages(dre_finding, expected_tstage):
    result = DiagnosticWorkupService().evaluate(
        {
            "age": 65,
            "psa": 12,
            "dre_finding": dre_finding,
            "mpmri_done": "0",
            "pirads_score": "No disponible",
        }
    )
    summary = result["report_sections"]["summary"]

    assert f"tacto rectal sospechoso compatible con {expected_tstage}" in summary
    assert "tacto rectal no sospechoso" not in summary


def test_mri_no_disponible_is_not_a_float_error_or_false_pirads():
    mri = derive_mri_context({"mpmri_done": "0", "pirads_score": "No disponible"})
    assert mri.done is False
    assert mri.pirads is None
    assert mri.display == "no realizada o pendiente"

    coerced_zero = derive_mri_context({"mpmri_done": 0})
    assert coerced_zero.done is False
    assert coerced_zero.display == "no realizada o pendiente"


def test_diagnostic_summary_respects_t2b_and_never_prints_psad_zero():
    result = DiagnosticWorkupService().evaluate(
        {
            "age": 65,
            "psa": 12,
            "dre_finding": "T2b - Afecta >50% de un lóbulo",
            "mpmri_done": "0",
            "pirads_score": "No disponible",
        }
    )
    summary = result["report_sections"]["summary"]

    assert "tacto rectal sospechoso compatible con cT2b" in summary
    assert "tacto rectal no sospechoso" not in summary
    assert "densidad del antígeno prostático específico de 0" not in summary
    assert "no calculable por falta de volumen prostático" in summary
    assert "resonancia magnética multiparamétrica no realizada o pendiente" in summary


def test_diagnostic_api_accepts_t2b_and_no_disponible_without_systemic_noise(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/diagnostic_workup/evaluate",
        json={
            "age": 65,
            "psa": 12,
            "dre_finding": "T2b - Afecta >50% de un lóbulo",
            "mpmri_done": "0",
            "pirads_score": "No disponible",
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    joined = str(result)
    assert "tacto rectal sospechoso compatible con cT2b" in joined
    assert "tacto rectal no sospechoso" not in joined
    assert "could not convert string to float" not in joined
    assert "Faltan datos para ERSPC: dre_suspicious" not in joined
    assert "Caída rápida ANC para docetaxel" not in joined
    assert "Dosis cumulativa docetaxel + cabazitaxel" not in joined


def test_diagnostic_wizard_loads_systemic_pivotal_fields_only_when_opened(app_client):
    client, _ = app_client
    response = client.get("/wizard/diagnostic_workup")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert 'data-derived-psad-readout' in html
    assert 'name="psad"' in html
    assert _wrapper_for(html, "psad").group(0).find("show_psad_override") != -1
    assert _wrapper_for(html, "pirads_score").group(0).find("mpmri_done") != -1
    assert _wrapper_for(html, "psma_pet_done").group(0).find("show_staging_imaging") != -1
    assert _wrapper_for(html, "spinal_cord_compression").group(0).find("show_emergency_triage") != -1
    assert "planned_systemic_regimen" not in html
    assert "rapid_anc_drop_for_docetaxel" not in html
    assert _wrapper_for(html, "biopsy_status").group(0).find("data-conditions") == -1
    assert "setConditionalWrapperDisabled" in html

    opened = client.get("/wizard/diagnostic_workup?gate_family=taxane_safety")
    assert opened.status_code == 200
    opened_html = opened.get_data(as_text=True)
    assert "rapid_anc_drop_for_docetaxel" in opened_html
    assert "rapid_platelet_drop_for_niraparib" not in opened_html


def test_localized_wizard_derives_psad_without_manual_recapture(app_client):
    client, _ = app_client
    response = client.get("/wizard/localized_initial")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    psad_wrapper = _wrapper_for(html, "psad").group(0)
    assert "hidden" in psad_wrapper
    assert 'data-derived-psad-wrapper="1"' in psad_wrapper
    assert 'name="psad"' in html
    assert 'data-derived-psad-input="1"' in html
    assert 'Densidad del antígeno prostático específico (PSAD)</span>' not in html
    assert 'data-derived-psad-readout' in html

    result = client.post(
        "/api/modules/localized_initial/evaluate",
        json={
            "age": 65,
            "psa": 12,
            "prostate_volume_ml": 40,
            "clinical_tstage": "T2a",
            "gleason_primary": 3,
            "gleason_secondary": 4,
            "isup_grade": 2,
            "num_cores_positive": 2,
            "total_cores": 12,
        },
    )
    assert result.status_code == 200
    psad_context = result.get_json()["result"]["psad_context"]
    assert psad_context["source"] == "derived_from_psa_and_volume"
    assert psad_context["display"] == "0.30 ng/mL/cc"

    legacy_result = client.post(
        "/api/modules/localized_initial/evaluate",
        json={
            "age": 65,
            "psa": 12,
            "psad": 0.18,
            "clinical_tstage": "T2a",
            "gleason_primary": 3,
            "gleason_secondary": 4,
            "isup_grade": 2,
            "num_cores_positive": 2,
            "total_cores": 12,
        },
    )
    assert legacy_result.status_code == 200
    assert legacy_result.get_json()["result"]["psad_context"]["source"] == "explicit"


def _wrapper_for(html: str, field_name: str):
    pattern = (
        r'<div\s+class="[^"]*"\s+data-field-wrapper\s+'
        rf'data-field-name="{re.escape(field_name)}"[^>]*>'
    )
    match = re.search(pattern, html)
    assert match is not None, f"Wrapper not found for {field_name}"
    return match
