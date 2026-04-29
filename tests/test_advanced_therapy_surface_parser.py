# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import uuid


REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX60_SCRIPT = REPO_ROOT / "output/playwright/validation/matrix60-20260410/run_mcp_matrix_validation.py"


def _load_matrix60_module():
    module_name = f"matrix60_advanced_surface_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MATRIX60_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


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
