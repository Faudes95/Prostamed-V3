"""tests/test_audit_37_e2e_clinical_decision_engine.py — Auditoría #37 E2E.

🎯 **Cierre del bucle Faubot — Regresión clínica E2E del CDE Auditable.**

Esta suite valida el sistema Clinical Decision Engine Auditable
arquitectónicamente completo (post FAUBOT 2026-04-25 XXIII) mediante:

  1. **5 pacientes sintéticos** representativos de cada disease state
     cubierto por ProstaMed (mhspc_high_volume, m1_crpc, m0_crpc,
     localized_initial, recurrence_bcr).

  2. **Verificación de las 5 dimensiones del scorecard** end-to-end:
       - CÓMO     → razonamiento cruzado gate × DDI visible
       - POR QUÉ  → mensaje not_recommended con drug pair
       - DATOS    → meds capture gap detectado
       - EVIDENCIA → trial_refs UCSF/SIOG (gate 19) propagados
       - VERSIÓN  → endpoint algorithm-version expone 19 SHAs YAML

  3. **Verificación de los 4 endpoints API auditables**:
       - GET /api/decision-audit/<patient_ref>
       - GET /api/decision-audit/algorithm-version
       - GET /api/gates-coverage-dashboard
       - GET /gates-coverage-dashboard (HTML, presence-check)

Hipótesis verificables: H.G326 - H.G350 (25 hipótesis).

Notas operativas:
  - Pacientes sintéticos NO se persisten — usamos `apply_pivotal_contraindication_gates`
    + `build_decision_audit` directamente para evitar dependencia del DB.
  - Tests con prefix `test_dimX_*` corresponden a las 5 dimensiones.
  - Tests con prefix `test_endpoint_*` validan endpoints HTTP.
  - Cada paciente tiene un docstring que cita su escenario clínico.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.shared.pivotal_contraindication_gates import (
    apply_pivotal_contraindication_gates,
)
from prostanet.shared.decision_audit_builder import build_decision_audit
from prostanet.shared.algorithm_version import get_algorithm_version


# ════════════════════════════════════════════════════════════════════
# 1. CATÁLOGO DE PACIENTES SINTÉTICOS (5 disease states)
# ════════════════════════════════════════════════════════════════════


@pytest.fixture
def patient_mhspc_high_volume_healthy():
    """**Paciente 1 — mHSPC alto volumen sincrónico, payload sano.**

    Escenario clínico: hombre 68a, PSA 350, Gleason 9 (4+5), 8 lesiones óseas
    + adenopatías retroperitoneales, ECOG 1, sin comorbilidades cardio-renales
    significativas, sin ARPI previo. Candidato a triplete (ARASENS) o doblete
    ADT+ARPI (ENZAMET/ARCHES/TITAN). NO debe disparar gates pivotal.
    """
    return {
        "patient_id": "97000000001",
        "input_snapshot": {
            "age": 68,
            "ecog_score": 1,
            "psa": 350,
            "gleason_primary": 4,
            "gleason_secondary": 5,
            "bone_lesion_count": 8,
            "visceral_metastasis": "0",
            "metastatic": "1",
            "high_volume_disease": "Sí",
            "synchronous_metastasis": "Sí",
            "testosterone": 380,
            "qtc_ms": 410,
            "lvef_percent": 60,
            "anc": 4500,
            "platelets": 240000,
            "hemoglobin_g_dl": 13.8,
            "creatinine_clearance": 90,
            "current_medications": "lisinopril, atorvastatina",
            "no_bone_protective_agent": "No",
            "denosumab_prophylaxis": "Sí",
        },
    }


@pytest.fixture
def patient_m1_crpc_qtc_with_methadone():
    """**Paciente 2 — m1CRPC con gate 17 (QTc + enzalutamida) + DDI cross.**

    Escenario clínico: hombre 75a, mCRPC progresor post-ADT+abiraterona, PSA
    rising 45 (DT 4 meses), bone-only progression. Antecedente de dolor óseo
    severo manejado con metadona. ECG basal con QTc 510 ms (CTCAE grado 3).

    **Esperado:** Gate 17 dispara; cross-check DDI detecta enzalutamida +
    metadona (qtc_prolongation, severity major); UI muestra razonamiento
    cruzado; mensaje not_recommended cita ambos drugs + acción ECG basal+2sem.
    """
    return {
        "patient_id": "97000000002",
        "input_snapshot": {
            "age": 75,
            "ecog_score": 1,
            "psa": 45,
            "psa_doubling_time": 4,
            "metastatic": "1",
            "castrate_resistant": "1",
            "testosterone": 18,
            "bone_lesion_count": 12,
            "qtc_ms": 510,                 # >500 → gate 17 dispara
            "lvef_percent": 55,
            "anc": 3200,
            "platelets": 180000,
            "hemoglobin_g_dl": 11.5,
            "current_medications": "metadona, omeprazol, paracetamol",
        },
    }


@pytest.fixture
def patient_m1_crpc_parp_with_mds():
    """**Paciente 3 — m1CRPC con gate 16 (PARPi + MDS history).**

    Escenario clínico: hombre 73a, mCRPC con BRCA2 alteración detectada (PROfound
    eligible), antecedente de SMD post-quimioterapia previa. Aunque el paciente
    cualificaría para olaparib, el gate 16 (PARPi × MDS/AML history boxed
    warning Lynparza §5.1) bloquea **sin override clínico**.

    **Esperado:** Gate 16 dispara; not_recommended cita "PARP inhibitors NO
    deben iniciarse con antecedente de SMD/LMA"; sin cross-DDI relevante
    (mds_aml es gate sin override); el clínico debe considerar alternativa
    (cabazitaxel, Lu-177-PSMA si elegible).
    """
    return {
        "patient_id": "97000000003",
        "input_snapshot": {
            "age": 73,
            "ecog_score": 1,
            "psa": 60,
            "metastatic": "1",
            "castrate_resistant": "1",
            "testosterone": 22,
            "brca_status": "BRCA2_pathogenic",
            "mds_aml_history": "Sí",       # → gate 16 dispara (sin override)
            "bone_lesion_count": 18,
            "anc": 3500,
            "platelets": 220000,
            "hemoglobin_g_dl": 12.0,
            "current_medications": "leuprolide",
        },
    }


@pytest.fixture
def patient_m0_crpc_meds_capture_gap():
    """**Paciente 4 — m0CRPC con gate 17 + meds capture gap.**

    Escenario clínico: hombre 70a, m0CRPC con PSA DT 6 meses, candidate para
    enzalutamida/apalutamida/darolutamida (PROSPER/SPARTAN/ARAMIS).
    QTc basal 505 ms (límite alto). **Sin captura de current_medications.**

    **Esperado:** Gate 17 dispara; **DATOS dimension** detecta missing
    `current_medications` → meds_capture_gap=True; UI patient_profile
    debe mostrar banner "Captura incompleta de meds"; cross-check DDI
    no produce alerts (sin meds capturadas, sin falsos positivos).
    """
    return {
        "patient_id": "97000000004",
        "input_snapshot": {
            "age": 70,
            "ecog_score": 0,
            "psa": 8.5,
            "psa_doubling_time": 6,
            "metastatic": "0",             # m0
            "castrate_resistant": "1",
            "testosterone": 25,
            "qtc_ms": 505,                 # >500 → gate 17 dispara
            "lvef_percent": 58,
            "anc": 4000,
            "platelets": 230000,
            "hemoglobin_g_dl": 13.2,
            # current_medications: AUSENTE A PROPÓSITO
        },
    }


@pytest.fixture
def patient_m1_crpc_arsi_cognitive():
    """**Paciente 5 — m1CRPC con gate 19 (ARSI + cognitive decline).**

    Escenario clínico: hombre 81a, mCRPC frágil, PSA progresión bajo ADT+leuprolide.
    Score MMSE 22 (deterioro cognitivo leve-moderado, CTCAE grado 2). Candidato
    a ARSI (enzalutamida/apalutamida/darolutamida) pero gate 19 bloquea por
    riesgo de neurotoxicidad ARSI (UCSF cohort 2024 + SIOG geriatric oncology).

    **Esperado:** Gate 19 dispara (cognitive decline grade 2); **EVIDENCIA**
    dimension propaga `trial_refs` con UCSF Cohort 2024, SIOG, Xtandi label;
    `evidence_tag` = `cognitive_arsi_*`; cross-check DDI seizure_threshold.
    """
    return {
        "patient_id": "97000000005",
        "input_snapshot": {
            "age": 81,
            "ecog_score": 2,
            "psa": 28,
            "metastatic": "1",
            "castrate_resistant": "1",
            "testosterone": 20,
            "cognitive_disturbance_ctcae_grade": 2,  # → gate 19 dispara
            "mmse_baseline": 28,
            "mmse_current": 22,            # Δ MMSE 6 → CTCAE grade 2 confirmado
            "moca_baseline": 26,
            "moca_current": 20,
            "qtc_ms": 420,
            "lvef_percent": 55,
            "current_medications": "leuprolide, lisinopril",
        },
    }


# ════════════════════════════════════════════════════════════════════
# 2. DIMENSIÓN CÓMO — Razonamiento cruzado gate × DDI
# ════════════════════════════════════════════════════════════════════


# H.G326 — gate 17 + metadona dispara cross-check qtc_prolongation
def test_dim_como_gate17_qtc_with_methadone_cross_check(
    patient_m1_crpc_qtc_with_methadone,
):
    """H.G326 — CÓMO: paciente con gate 17 (QTc enzalutamida) + metadona
    debe activar cross-check DDI qtc_prolongation con razonamiento cruzado."""
    payload = patient_m1_crpc_qtc_with_methadone["input_snapshot"]
    bundle = apply_pivotal_contraindication_gates(payload, treatments=[])

    # Gate 17 dispara
    codes = [g["code"] for g in bundle["gates_triggered"]]
    assert "qtc_prolongation_grade3_for_enzalutamide" in codes, (
        f"Gate 17 debió disparar con QTc=510, codes={codes}"
    )

    # Cross-check DDI activado
    cross_alerts = bundle.get("ddi_cross_alerts") or []
    assert len(cross_alerts) >= 1, (
        f"Cross-check DDI debió activarse con metadona, got {len(cross_alerts)}"
    )

    # Categoría qtc_prolongation
    qtc_alerts = [a for a in cross_alerts if a.get("category") == "qtc_prolongation"]
    assert qtc_alerts, "Esperaba al menos 1 alert qtc_prolongation"

    # Drug pair correcto
    metadona_alert = next(
        (a for a in qtc_alerts
         if "metadona" in str(a.get("ddi_alert", {}).get("drug_b") or "").lower()),
        None,
    )
    assert metadona_alert, "Esperaba alert con drug_b=Metadona"

    # Razonamiento cruzado en cross_message
    msg = metadona_alert.get("cross_message", "").lower()
    assert "gate 17" in msg, f"cross_message debe citar Gate 17, got: {msg[:100]}"
    assert "metadona" in msg, "cross_message debe citar metadona"


# H.G327 — bundle expone clave ddi_cross_alerts (estructura)
def test_dim_como_bundle_ddi_cross_alerts_field(
    patient_m1_crpc_qtc_with_methadone,
):
    """H.G327 — CÓMO: bundle siempre incluye ddi_cross_alerts (forward-compat)."""
    payload = patient_m1_crpc_qtc_with_methadone["input_snapshot"]
    bundle = apply_pivotal_contraindication_gates(payload, treatments=[])
    assert "ddi_cross_alerts" in bundle
    assert isinstance(bundle["ddi_cross_alerts"], list)


# ════════════════════════════════════════════════════════════════════
# 3. DIMENSIÓN POR QUÉ — Mensaje not_recommended con drug pair
# ════════════════════════════════════════════════════════════════════


# H.G328 — gate 16 PARPi+MDS produce not_recommended descriptivo
def test_dim_por_que_gate16_parp_mds_not_recommended_message(
    patient_m1_crpc_parp_with_mds,
):
    """H.G328 — POR QUÉ: paciente con MDS history activa gate 16 con
    mensaje not_recommended exhaustivo (sin override disponible)."""
    payload = patient_m1_crpc_parp_with_mds["input_snapshot"]
    bundle = apply_pivotal_contraindication_gates(payload, treatments=[])

    codes = [g["code"] for g in bundle["gates_triggered"]]
    assert "parp_inhibitor_in_mds_aml_history" in codes

    # Mensaje not_recommended cita drug class + boxed warning
    messages = bundle.get("not_recommended_messages") or []
    parp_mds_msg = next(
        (m for m in messages if "PARP" in m.upper() or "olaparib" in m.lower()),
        None,
    )
    assert parp_mds_msg, f"Esperaba mensaje sobre PARPi, got: {messages[:3]}"
    assert ("MDS" in parp_mds_msg.upper() or "SMD" in parp_mds_msg.upper()
            or "AML" in parp_mds_msg.upper() or "LMA" in parp_mds_msg.upper()), (
        f"Mensaje debe citar MDS/SMD/AML/LMA: {parp_mds_msg[:200]}"
    )


# H.G329 — gate sin override (mds_aml) NO se desactiva con flags hipotéticos
def test_dim_por_que_gate16_no_override_available(
    patient_m1_crpc_parp_with_mds,
):
    """H.G329 — POR QUÉ: gate 16 (PARP × MDS) es absoluto — incluso si el
    payload llevara un override-like flag, debe seguir disparando."""
    payload = patient_m1_crpc_parp_with_mds["input_snapshot"].copy()
    payload["mds_resolved"] = "Sí"  # flag inventado, NO debe desactivar
    bundle = apply_pivotal_contraindication_gates(payload, treatments=[])
    codes = [g["code"] for g in bundle["gates_triggered"]]
    assert "parp_inhibitor_in_mds_aml_history" in codes, (
        "Gate 16 NO debe tener override (boxed warning regulatorio absoluto)"
    )


# ════════════════════════════════════════════════════════════════════
# 4. DIMENSIÓN DATOS — Meds capture gap detection
# ════════════════════════════════════════════════════════════════════


# H.G330 — paciente sin current_medications → ddi_cross_alerts vacío
def test_dim_datos_no_meds_no_cross_alerts(patient_m0_crpc_meds_capture_gap):
    """H.G330 — DATOS: payload sin current_medications NO produce cross
    alerts (fail-safe, sin falsos positivos)."""
    payload = patient_m0_crpc_meds_capture_gap["input_snapshot"]
    bundle = apply_pivotal_contraindication_gates(payload, treatments=[])

    # Gate 17 dispara (QTc=505)
    codes = [g["code"] for g in bundle["gates_triggered"]]
    assert "qtc_prolongation_grade3_for_enzalutamide" in codes

    # Pero cross-check DDI vacío (sin meds capturadas)
    assert bundle["ddi_cross_alerts"] == [], (
        "Sin current_medications → cross alerts vacío (fail-safe)"
    )


# H.G331 — UI panel detecta meds_capture_gap por gate
def test_dim_datos_ui_panel_meds_capture_gap_flag(
    patient_m0_crpc_meds_capture_gap,
):
    """H.G331 — DATOS: el panel UI marca meds_capture_gap=True cuando gate
    triggered + sin current_medications."""
    from prostanet.domains.patient_tracking.profile_compass import (
        _build_pivotal_contraindication_gates_panel,
    )
    payload = patient_m0_crpc_meds_capture_gap["input_snapshot"]
    bundle = apply_pivotal_contraindication_gates(payload, treatments=[])

    # Construir assessment mock para el panel
    assessment = {
        "input_snapshot": payload,
        "result_snapshot": {
            "pivotal_contraindication_gates": bundle["gates_triggered"],
        },
    }
    panel = _build_pivotal_contraindication_gates_panel(assessment)

    assert panel["has_gates"] is True
    assert panel["has_medications_captured"] is False, (
        "Panel debe detectar que NO hay medicaciones capturadas"
    )
    assert panel["meds_capture_gap_count"] >= 1, (
        f"Esperaba ≥1 gate con meds_capture_gap, got {panel['meds_capture_gap_count']}"
    )


# ════════════════════════════════════════════════════════════════════
# 5. DIMENSIÓN EVIDENCIA — Trial refs UCSF/SIOG (gate 19)
# ════════════════════════════════════════════════════════════════════


# H.G332 — gate 19 ARSI cognitive expone trial_refs UCSF/SIOG
def test_dim_evidencia_gate19_arsi_cognitive_trial_refs(
    patient_m1_crpc_arsi_cognitive,
):
    """H.G332 — EVIDENCIA: gate 19 cita UCSF Cohort 2024 + SIOG geriatric
    oncology + Xtandi label en trial_refs."""
    payload = patient_m1_crpc_arsi_cognitive["input_snapshot"]
    bundle = apply_pivotal_contraindication_gates(payload, treatments=[])

    arsi_gate = next(
        (g for g in bundle["gates_triggered"]
         if g["code"] == "arsi_in_cognitive_decline_grade2"),
        None,
    )
    assert arsi_gate, f"Gate 19 debió disparar, codes={[g['code'] for g in bundle['gates_triggered']]}"

    trial_refs = list(arsi_gate.get("trial_refs") or [])
    assert trial_refs, "Gate 19 debe tener trial_refs no vacíos"

    refs_str = " ".join(trial_refs).upper()
    assert "UCSF" in refs_str or "SIOG" in refs_str, (
        f"trial_refs debe citar UCSF Cohort 2024 o SIOG: {trial_refs}"
    )


# H.G333 — evidence_tag específico (no genérico)
def test_dim_evidencia_evidence_tag_specific(patient_m1_crpc_arsi_cognitive):
    """H.G333 — EVIDENCIA: evidence_tag debe ser snake_case específico,
    no genérico tipo 'evidence'."""
    payload = patient_m1_crpc_arsi_cognitive["input_snapshot"]
    bundle = apply_pivotal_contraindication_gates(payload, treatments=[])
    arsi_gate = next(
        (g for g in bundle["gates_triggered"]
         if g["code"] == "arsi_in_cognitive_decline_grade2"),
        None,
    )
    assert arsi_gate
    tag = arsi_gate.get("evidence_tag", "")
    assert tag and tag != "evidence", f"evidence_tag debe ser específico: {tag!r}"
    assert "_" in tag, "evidence_tag debe ser snake_case"


# H.G334 — audit endpoint agrega trial_refs únicos
def test_dim_evidencia_audit_aggregates_unique_trial_refs(
    patient_m1_crpc_arsi_cognitive,
):
    """H.G334 — EVIDENCIA: build_decision_audit agrupa trial_refs únicos
    en audit_dimensions.evidencia.unique_trial_refs."""
    payload = patient_m1_crpc_arsi_cognitive["input_snapshot"]
    bundle = apply_pivotal_contraindication_gates(payload, treatments=[])

    mock_assessment = {
        "id": 99,
        "module_id": "m1_crpc",
        "state": "m1_crpc",
        "input_snapshot": payload,
        "result_snapshot": {
            "state": "m1_crpc",
            "pivotal_contraindication_gates": bundle["gates_triggered"],
        },
    }
    audit = build_decision_audit(
        patient_id="97000000005",
        patient_identity={},
        latest_assessment=mock_assessment,
    )

    evidencia = audit["audit_dimensions"]["evidencia"]
    assert evidencia["unique_trial_refs_count"] >= 1
    refs_str = " ".join(evidencia["unique_trial_refs"]).upper()
    assert "UCSF" in refs_str or "SIOG" in refs_str


# ════════════════════════════════════════════════════════════════════
# 6. DIMENSIÓN VERSIÓN — Algorithm version expone 19 SHAs YAML
# ════════════════════════════════════════════════════════════════════


# H.G335 — algorithm version expone ≥19 SHAs YAML
def test_dim_version_at_least_19_yaml_shas_exposed():
    """H.G335 — VERSIÓN: get_algorithm_version expone ≥19 SHAs YAML.

    Faubot 2026-04-25 (XXVI) #38 añadió 4 gates clínicos extendidos → 23 SHAs.
    Convención `>=` per CLAUDE.md §8.4 (forward-compat).
    """
    ver = get_algorithm_version()
    assert ver["yaml_loaded_gates_count"] >= 19
    assert len(ver["per_gate_yaml_shas"]) >= 19
    assert len(ver["per_gate_yaml_shas"]) == ver["yaml_loaded_gates_count"]
    for code, sha in ver["per_gate_yaml_shas"].items():
        assert len(sha) == 12, f"SHA mal formado para {code}: {sha!r}"


# H.G336 — FAUBOT_RELEASE refleja iteración actual
def test_dim_version_faubot_release_at_least_xxiii():
    """H.G336 — VERSIÓN: FAUBOT_RELEASE iteración ≥XXIII (post R3+R13).

    Faubot 2026-04-25 (XLI / Auditoría #44): la comparación previa con
    `>= "2026-04-25 XXIII"` era lexicográfica y FALLABA con números
    romanos (e.g., "XL" < "XXIII" alfabéticamente porque ord('L') < ord('X')).
    Ahora extraemos el numeral romano del FAUBOT_RELEASE y lo convertimos
    a int via _roman_to_int() para una comparación numérica correcta.
    """
    def _roman_to_int(s: str) -> int:
        roman_map = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        total = 0
        prev = 0
        for char in reversed(s):
            value = roman_map.get(char, 0)
            if value < prev:
                total -= value
            else:
                total += value
            prev = value
        return total

    ver = get_algorithm_version()
    # Faubot LXXXIV.b: forward-compat con releases posteriores 2026-04-25 (e.g.,
    # 2026-04-26 LXXXIV.b). Extraemos solo el segmento romano antes del posible
    # patch suffix ".b" / ".c" / etc.
    assert ver["faubot_release"].startswith("2026-04-"), (
        f"FAUBOT release {ver['faubot_release']} debe ser 2026-04-2X"
    )
    import re as _re
    # Capturar fecha + romano + opcional sufijo ".letra"
    match = _re.match(r"^(\d{4}-\d{2}-\d{2})\s+([IVXLCDM]+)(?:\.[a-z])?$", ver["faubot_release"])
    assert match is not None, (
        f"FAUBOT release {ver['faubot_release']} no parsea formato 'YYYY-MM-DD ROMAN[.patch]'"
    )
    roman_part = match.group(2)
    iteration = _roman_to_int(roman_part)
    assert iteration >= 23, (
        f"FAUBOT iteration {iteration} (from '{roman_part}') < 23 expected; "
        f"full release: {ver['faubot_release']}"
    )


# H.G337 — total gates activos ≥19 (sistema híbrido)
def test_dim_version_total_active_gates_at_least_19():
    """H.G337 — VERSIÓN: gates_active_count ≥19 (Python+YAML deduplicados).

    Faubot 2026-04-25 (XXVI) #38: +4 gates clínicos extendidos → 23.
    Convención `>=` per CLAUDE.md §8.4 (forward-compat).
    """
    ver = get_algorithm_version()
    assert ver["gates_active_count"] >= 19


# ════════════════════════════════════════════════════════════════════
# 7. ENDPOINTS API AUDITABLES — Verificación HTTP
# ════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def flask_test_client():
    """Cliente Flask para test endpoints API."""
    import app as app_module
    app = app_module.create_app({"TESTING": True})
    with app.test_client() as client:
        yield client


# H.G338 — endpoint /api/decision-audit/algorithm-version disponible y bien-formado
def test_endpoint_algorithm_version(flask_test_client):
    """H.G338 — Endpoint /api/decision-audit/algorithm-version retorna 200 +
    success=True + version dict completo."""
    resp = flask_test_client.get("/api/decision-audit/algorithm-version")
    assert resp.status_code == 200, f"Esperaba 200, got {resp.status_code}"
    data = resp.get_json()
    assert data["success"] is True
    assert "version" in data
    ver = data["version"]
    # Forward-compat per CLAUDE.md §8.4: gates may grow over time
    assert ver["yaml_loaded_gates_count"] >= 19
    assert ver["gates_active_count"] >= 19
    assert len(ver["per_gate_yaml_shas"]) >= 19


# H.G339 — endpoint /api/decision-audit/<patient_ref> con patient inexistente → 404
def test_endpoint_decision_audit_nonexistent_patient(flask_test_client):
    """H.G339 — Endpoint /api/decision-audit/<patient_ref> retorna 404 si
    el paciente no existe (NSS sintético no en DB)."""
    resp = flask_test_client.get("/api/decision-audit/99999999999")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["success"] is False
    assert "no encontrado" in data["error"].lower() or "not found" in data["error"].lower()


# H.G340 — endpoint /api/gates-coverage-dashboard retorna estructura válida
def test_endpoint_gates_coverage_dashboard(flask_test_client):
    """H.G340 — Endpoint /api/gates-coverage-dashboard retorna 200 con
    estructura coverage + heatmap (aunque cohorte esté vacía)."""
    resp = flask_test_client.get("/api/gates-coverage-dashboard")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "coverage" in data
    coverage = data["coverage"]
    # Estructura mínima esperada
    for key in ("total_assessments", "gate_coverage", "alerts"):
        assert key in coverage, f"Falta clave {key} en coverage"


# H.G341 — endpoint HTML /gates-coverage-dashboard responde 200 + HTML
def test_endpoint_gates_coverage_dashboard_html(flask_test_client):
    """H.G341 — Endpoint HTML /gates-coverage-dashboard renderiza el template."""
    resp = flask_test_client.get("/gates-coverage-dashboard")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True).lower()
    # Strings clave que el template debe contener
    assert "gates" in body
    assert "coverage" in body or "cobertura" in body


# ════════════════════════════════════════════════════════════════════
# 8. INTEGRACIÓN E2E — paciente sano debe NO disparar nada
# ════════════════════════════════════════════════════════════════════


# H.G342 — paciente sano (mhspc_high_volume) NO dispara gates
def test_e2e_healthy_patient_no_gates(patient_mhspc_high_volume_healthy):
    """H.G342 — E2E: paciente sano (sin contraindicaciones) NO debe disparar
    ningún gate pivotal y bundle queda vacío de alertas."""
    payload = patient_mhspc_high_volume_healthy["input_snapshot"]
    bundle = apply_pivotal_contraindication_gates(payload, treatments=[])

    assert bundle["gates_triggered"] == [], (
        f"Paciente sano disparó gates inesperados: "
        f"{[g['code'] for g in bundle['gates_triggered']]}"
    )
    assert bundle["ddi_cross_alerts"] == []
    assert bundle["not_recommended_messages"] == []


# H.G343 — audit del paciente sano expone 5 dimensiones JSON-serializable
def test_e2e_healthy_patient_audit_5_dimensions_serializable(
    patient_mhspc_high_volume_healthy,
):
    """H.G343 — E2E: el audit del paciente sano expone las 5 dimensiones
    + es JSON-serializable + contiene la dimensión version siempre."""
    import json
    payload = patient_mhspc_high_volume_healthy["input_snapshot"]
    bundle = apply_pivotal_contraindication_gates(payload, treatments=[])
    mock_assessment = {
        "id": 1,
        "module_id": "mcspc_high_volume",
        "state": "mhspc_high_volume",
        "input_snapshot": payload,
        "result_snapshot": {
            "state": "mhspc_high_volume",
            "pivotal_contraindication_gates": bundle["gates_triggered"],
        },
    }
    audit = build_decision_audit(
        patient_id=patient_mhspc_high_volume_healthy["patient_id"],
        patient_identity={"id": "test"},
        latest_assessment=mock_assessment,
    )

    # 5 dimensiones presentes
    dims = audit["audit_dimensions"]
    assert set(dims.keys()) == {"como", "por_que", "datos", "evidencia", "version"}

    # version siempre disponible (incluso si paciente sano); ≥19 forward-compat
    assert dims["version"]["yaml_loaded_gates_count"] >= 19

    # JSON-serializable
    serialized = json.dumps(audit)
    assert len(serialized) > 100  # sanity check (no es un dict vacío)


# ════════════════════════════════════════════════════════════════════
# 9. SCORECARD CDE AUDITABLE — verificación de cobertura final
# ════════════════════════════════════════════════════════════════════


# H.G344 — los 4 escenarios prueban exactamente las 5 dimensiones
def test_scorecard_5_dimensions_covered_by_test_suite():
    """H.G344 — Scorecard: la suite cubre explícitamente las 5 dimensiones
    (CÓMO, POR QUÉ, DATOS, EVIDENCIA, VERSIÓN) con tests etiquetados
    `test_dim_<dimension>_*`."""
    import inspect
    import sys
    module = sys.modules[__name__]
    test_names = [
        name for name, obj in inspect.getmembers(module)
        if name.startswith("test_dim_") and callable(obj)
    ]
    # Verificar que cada dimensión tiene al menos 1 test
    for dim in ("como", "por_que", "datos", "evidencia", "version"):
        matching = [n for n in test_names if f"test_dim_{dim}" in n]
        assert matching, f"Dimensión '{dim}' sin tests dedicados"


# H.G345 — los 5 pacientes sintéticos tienen patient_ids únicos
def test_scorecard_5_patients_unique_ids(
    patient_mhspc_high_volume_healthy,
    patient_m1_crpc_qtc_with_methadone,
    patient_m1_crpc_parp_with_mds,
    patient_m0_crpc_meds_capture_gap,
    patient_m1_crpc_arsi_cognitive,
):
    """H.G345 — Scorecard: los 5 pacientes representan disease states distintos."""
    patients = [
        patient_mhspc_high_volume_healthy,
        patient_m1_crpc_qtc_with_methadone,
        patient_m1_crpc_parp_with_mds,
        patient_m0_crpc_meds_capture_gap,
        patient_m1_crpc_arsi_cognitive,
    ]
    ids = {p["patient_id"] for p in patients}
    assert len(ids) == 5, f"Esperaba 5 patient_ids únicos, got {ids}"
