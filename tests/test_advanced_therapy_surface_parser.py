# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

def _load_matrix60_module():
    from prostanet.domains.clinical_validation import matrix60_validation

    return matrix60_validation


def test_parse_snapshot_extracts_advanced_therapy_panel_sections(tmp_path):
    module = _load_matrix60_module()
    snapshot = tmp_path / "advanced_panel.md"
    snapshot.write_text(
        "\n".join(
            [
                'heading "Diagnóstico oficial"',
                'text: "CRPC sin metástasis"',
                'heading "Etapa / clasificación operativa"',
                'text: "CRPC sin metástasis"',
                'heading "Decisión clínica hoy"',
                'text: "Darolutamida + terapia de privación androgénica"',
                'heading "Siguiente mejor acción"',
                'text: "Darolutamida + terapia de privación androgénica"',
                'heading "Panel de decisión terapéutica avanzada"',
                'heading "Terapia seleccionada"',
                'text: "Darolutamida + ADT"',
                'text: "ARPI"',
                'text: "Revisar vigencia"',
                'text: "Actualizar evidencia: Actualizar reestadificación convencional y confirmar castración actual"',
                'heading "Prerequisito de liberación"',
                'text: "Completar perfil ARPI: current_medications, dermatitis_history"',
                'heading "Otras opciones viables"',
                'text: "Enzalutamida + ADT"',
                'heading "Opciones bloqueadas o diferidas"',
                'text: "Apalutamida + ADT"',
                'text: "Antecedente de dermatitis severa."',
                'heading "Adjuntos terapéuticos locales"',
                'text: "RT al primario"',
                'heading "Calendario de seguimiento programado"',
                'text: "PSA y testosterona cada 12 semanas"',
            ]
        ),
        encoding="utf-8",
    )

    parsed = module.parse_snapshot(snapshot)

    assert parsed["selected_therapy"][0] == "Darolutamida + ADT"
    assert "Revisar vigencia" in parsed["selected_therapy"]
    assert "Actualizar evidencia: Actualizar reestadificación convencional y confirmar castración actual" in parsed["selected_therapy"]
    assert "Completar perfil ARPI: current_medications, dermatitis_history" in parsed["prerequisite_actions"]
    assert parsed["other_viable_options"] == ["Enzalutamida + ADT"]
    assert "Apalutamida + ADT" in parsed["blocked_or_deferred_options"]
    assert parsed["local_adjuncts"] == ["RT al primario"]
