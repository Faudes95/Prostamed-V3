"""pivotal_gate_delta.py — FAUBOT auditoría 2026-04-25 (IX).

Helper compartido para detectar cambios visita-a-visita en
`pivotal_contraindication_gates`. Extiende el contrato de
`decision_delta_since_last_visit` y `_build_why_changed_today` para que
el clínico pueda ver:

  - Gates **recién activados** en esta visita (e.g., paciente desarrolló
    QTc prolongado tras iniciar nuevo medicamento concomitante).
  - Gates **recién desactivados** por override clínico documentado
    (e.g., `qtc_corrected_for_arpi=Sí` tras corregir hipokalemia).
  - Gates con **cambio de severity** (de soft → hard_block o viceversa).
  - Gates **persistentes** (siguen activos sin cambio).

Diseño:
  - Funciones puras sobre listas de gates (sin side-effects).
  - `compute_pivotal_gates_delta(current, previous)` — input son las dos
    listas estructuradas que emite `pivotal_contraindication_gates.py`
    (cada gate dict con `code/severity/message/evidence_tag/trial_refs`).
  - `describe_gate_delta_in_clinical_language(delta)` — humaniza el delta
    a una lista de strings ES médica para `why_changed_today` del copilot.

Aporte a auditabilidad:
  - **POR QUÉ:** sistema explica "por qué hoy sí y antes no" en lenguaje
    clínico trazable.
  - **VERSIÓN:** estado de cada gate queda documentado por visita →
    permite regresión histórica completa de la decisión.
"""
from __future__ import annotations

from typing import Any


def _gate_dict_by_code(gates: list[dict] | None) -> dict[str, dict]:
    """Construye índice {code: gate_dict} para búsqueda O(1)."""
    out: dict[str, dict] = {}
    for gate in gates or []:
        code = str(gate.get("code") or "").strip()
        if code:
            out[code] = dict(gate)
    return out


def compute_pivotal_gates_delta(
    current_gates: list[dict] | None,
    previous_gates: list[dict] | None,
) -> dict:
    """Computa el delta visita-a-visita de los gates pivotal.

    Args:
        current_gates: lista de gates de la evaluación actual (formato
            `pivotal_contraindication_gates.py`).
        previous_gates: lista de gates de la evaluación previa (mismo
            formato). Si None o vacío, todos los current se consideran
            como "persisting" (no espurios) y no se reporta delta.

    Returns:
        Dict con:
          - `available`: bool — True si hay base de comparación previa.
          - `is_first_visit`: bool — True si previous_gates vacío/None.
          - `newly_activated`: list[dict] — gates ahora activos que no
            estaban antes.
          - `newly_deactivated`: list[dict] — gates antes activos que
            ya no aparecen.
          - `severity_changed`: list[dict] — gates con cambio de severity
            (cada item: {code, previous_severity, current_severity,
            current_message, current_trial_refs, current_evidence_tag}).
          - `persisting`: list[dict] — gates activos sin cambio entre
            ambas visitas.
          - `total_change_count`: int — suma de cambios significativos.
    """
    current_idx = _gate_dict_by_code(current_gates)
    previous_idx = _gate_dict_by_code(previous_gates)

    # Caso 1: primera visita (sin previous)
    if not previous_idx:
        return {
            "available": False,
            "is_first_visit": True,
            "newly_activated": [],
            "newly_deactivated": [],
            "severity_changed": [],
            "persisting": list(current_idx.values()),
            "total_change_count": 0,
        }

    current_codes = set(current_idx.keys())
    previous_codes = set(previous_idx.keys())

    activated_codes = current_codes - previous_codes
    deactivated_codes = previous_codes - current_codes
    common_codes = current_codes & previous_codes

    newly_activated = [current_idx[c] for c in sorted(activated_codes)]
    newly_deactivated = [previous_idx[c] for c in sorted(deactivated_codes)]

    severity_changed: list[dict] = []
    persisting: list[dict] = []
    for code in sorted(common_codes):
        cur = current_idx[code]
        prev = previous_idx[code]
        cur_sev = str(cur.get("severity") or "").strip()
        prev_sev = str(prev.get("severity") or "").strip()
        if cur_sev != prev_sev:
            severity_changed.append({
                "code": code,
                "previous_severity": prev_sev,
                "current_severity": cur_sev,
                "current_message": cur.get("message"),
                "current_trial_refs": list(cur.get("trial_refs") or []),
                "current_evidence_tag": cur.get("evidence_tag"),
            })
        else:
            persisting.append(cur)

    total_change_count = (
        len(newly_activated) + len(newly_deactivated) + len(severity_changed)
    )

    return {
        "available": True,
        "is_first_visit": False,
        "newly_activated": newly_activated,
        "newly_deactivated": newly_deactivated,
        "severity_changed": severity_changed,
        "persisting": persisting,
        "total_change_count": total_change_count,
    }


# ── Catálogos de clasificación de gates (Faubot 2026-04-25 XXIII — R13) ─
# Refactor R13 (code-simplifier report): convertir el if-chain de 13 ramas
# de `_classify_gate_for_message` en 3 dispatch dicts (exact / prefix /
# suffix). Datos-como-código facilita: (a) añadir nuevos gates sin tocar
# lógica, (b) auditar de un vistazo el mapping completo gate → clase
# farmacológica, (c) sincronizar manualmente con
# `profile_compass._build_pivotal_contraindication_gates_panel`.

_GATE_EXACT_CLASSES: dict[str, str] = {
    "severe_heart_failure_nyha_iii_iv":   "Cardiotoxicidad genérica",
    "uncontrolled_hypertension":          "Cardiotoxicidad genérica",
    "uncontrolled_diabetes":              "Metabólicas",
    "severe_neuropathy_grade3":           "Neurológicas",
    "no_bone_protective_agent":           "Hueso",
    "ecog_2_or_more_for_triplets":        "Performance status",
    "creatinine_clearance_lt_30":         "Renal",
    "prior_arpi_exposure_mhspc":          "Exposición previa",
    # Faubot XIV+XXVI — ARSI specific differentiated classes
    "arsi_in_cognitive_decline_grade2":   "ARSI deterioro cognitivo",
    "arsi_in_seizure_history_grade3":     "ARSI convulsiones",
    # Faubot XXVI — abiraterone hepatotox separate from HTA
    "abiraterone_hepatotoxicity_grade3":  "Hepatotoxicidad abiraterona",
    # Faubot XXXIV — abiraterone adrenal axis
    "abiraterone_adrenal_insufficiency":  "Adrenal axis abiraterona",
    # Faubot XXVII — taxanes longitudinal
    "docetaxel_neuropathy_longitudinal_grade2_post_4_cycles": "Taxanes neuropathy longitudinal",
    # Faubot XXXIII — PI3K/AKT inhibitors
    "ipatasertib_hyperglycemia_grade3":   "PI3K/AKT metabólico",
    # Faubot XXXIV — cabazitaxel hipersensibilidad
    "cabazitaxel_hypersensitivity_grade3": "Hipersensibilidad cabazitaxel",
    # Faubot XXXIV — Ra-223 FRAX numeric
    "radium223_high_fracture_risk_frax":  "Hueso (FRAX score)",
    # Faubot XLII (#45.1) — Auditoría #44 gates 29-30 con class_label
    # específico. Importante: AMBOS son exact-matches (no prefix) porque:
    #   - olaparib_renal_dysfunction_grade3 NO comparte prefix con otros
    #     gates renales (gate 10 creatinine_clearance_lt_30 es exact-match
    #     separado para rucaparib).
    #   - lutetium177_fatigue_grade3 sí empieza con `lutetium177_` PREFIX
    #     pero el dict lookup ocurre ANTES del prefix scan, así que el
    #     exact-match gana → "Fatigue Lu-177" en vez de "Lu-177-PSMA"
    #     genérico.
    "olaparib_renal_dysfunction_grade3":  "Renal olaparib (PROfound + Lynparza §2.3)",
    "lutetium177_fatigue_grade3":         "Fatigue Lu-177 (VISION + Pluvicto §6)",
    # Faubot XLIII (#46) — Gate 31 enzalutamide × cognitive elderly
    # (compound trigger all_of: edad ≥75 + MMSE/MoCA marginal o concerns).
    # Class label menciona UCSF cohort + Marcum para que el clínico vea
    # citation académica directa al motivo del block.
    "enzalutamide_cognitive_decline_elderly": "Enzalutamida cognitive elderly (UCSF 2024 + Marcum JAMA Oncol)",
    # Faubot XLIV (#47) — Gate 32 darolutamide hepatotox G3 hepatocelular
    # (distinto del patrón colestásico de gate 21 abiraterona; preserva
    # diferenciación clínica importante entre los 2 ARSI con hepatotox).
    "darolutamide_hepatotoxicity_grade3": "Hepatotox darolutamida (ARANOTE/ARASENS + Nubeqa §6)",
    # Faubot XLVII (#48) — Gate 33 niraparib caída rápida plt LONGITUDINAL
    # (signal longitudinal vs gates 22-23 que son baseline absoluto).
    # Exact-match precede prefix `niraparib_` que mapea a "PARPi específico
    # niraparib" genérico — diferenciación importante para clínico.
    "niraparib_thrombocytopenia_rapid_drop": "Niraparib caída plt longitudinal (MAGNITUDE Chi NEJM 2023)",
    # Faubot XLVIII (#49) — Gate 34 docetaxel caída ANC longitudinal
    "docetaxel_neutropenia_rapid_drop": "Docetaxel caída ANC longitudinal (TAX-327 + STAMPEDE Arm C)",
    # Faubot XLIX (#56) — Gate 35 ARSI/abi VTE risk
    "arsi_abiraterone_vte_risk_high": "TEV ARSI/abiraterona (COU-AA-302 + LATITUDE + Klil-Drori 2019)",
    # Faubot L (#60) — Gate 36 triplete frailty G8
    "triplete_frailty_g8_low": "Triplete + frailty G8 ≤14 (PEACE-1/ARASENS elderly subset)",
    # Faubot LI (#53) — Gates 37+38 Sipuleucel-T immunoterapia (clase nueva)
    "sipuleucel_t_severe_irr": "Sipuleucel-T IRR severo (IMPACT + Provenge §5.1)",
    "sipuleucel_t_febrile_neutropenia_post_leukapheresis": "Sipuleucel-T febrile neutropenia (IMPACT + Provenge §5.2)",
    # Faubot LIII (#50) — Gate 39 abiraterona ALP rise LONGITUDINAL colestásico
    # (cuarto gate longitudinal del catálogo; primer uso de
    # numeric_baseline_delta_rise_above trigger type)
    "abiraterone_alp_rapid_rise_longitudinal": "ALP rise abiraterona longitudinal (LATITUDE + Zytiga §5.1)",
    # Faubot LIV (#51) — Gate 40 Lu-177 Hb drop LONGITUDINAL anemia
    # (quinto gate longitudinal; reutiliza numeric_baseline_delta_above DROP).
    # Exact-match precede prefix `lutetium177_` que mapea a "Lu-177-PSMA"
    # genérico — diferenciación importante con gates 13/14 baseline.
    "lutetium177_hb_rapid_drop_longitudinal": "Hb drop Lu-177 longitudinal (VISION supplementary + Pluvicto §6)",
    # Faubot LV (#52) — Gate 41 cabazitaxel Hb drop LONGITUDINAL anemia
    # (sexto gate longitudinal; completa serie hematológica longitudinal).
    "cabazitaxel_hb_rapid_drop_longitudinal": "Hb drop cabazitaxel longitudinal (TROPIC + CARD + Jevtana §6)",
    # Faubot LVI (#57) — Gate 42 apalutamida SJS/TEN (PRIMER gate
    # dermatológico del catálogo; PRIMER gate sin override por
    # contraindicación absoluta irreversible per Erleada §5.2).
    "apalutamide_severe_rash_sjs_ten": "SJS/TEN apalutamida (Erleada §5.2 + SPARTAN/TITAN)",
    # Faubot LVII (#54) — Gates 43-46 Checkpoint inhibitors irAE
    # (2da clase IO del catálogo post Sipuleucel-T #53; KEYNOTE-365/921 +
    # NCCN IO Toxicity 2024). 4 gates simultáneos cubren irAE poliórgano.
    "checkpoint_inhibitor_pneumonitis_grade2_plus": "Pneumonitis IO (KEYNOTE + NCCN §PNEU-1)",
    "checkpoint_inhibitor_hepatitis_grade3_plus": "Hepatitis IO (KEYNOTE/CheckMate + NCCN §HEP-1)",
    "checkpoint_inhibitor_colitis_grade3_plus": "Colitis IO (KEYNOTE/CheckMate + NCCN §GI-1)",
    "checkpoint_inhibitor_endocrinopathy_new_onset": "Endocrinopatías IO (KEYNOTE/Sznol + NCCN §END-1)",
    # Faubot LVIII (#62) — Gate 47 PSA flare ARPI pseudo-progresión
    # (PRIMER gate informacional/anti-misinterpretation, severity=soft_warning,
    # NO bloquea ARPI — solo advierte clínico contra discontinuación prematura).
    "psa_flare_arpi_pseudoprogression": "PSA flare ARPI (PCWG3 2016 — anti-misinterpretation)",
    # Faubot LIX (#58) — Gate 48 enzalutamida hyponatremia/SIADH
    # (PRIMER gate electrólitos críticos del catálogo, hard_block).
    # Sienta arquitectura electrólitos preparada para gates futuros
    # (#59 hipokalemia abi, hipocalcemia extendida, hipofosfatemia).
    "enzalutamide_hyponatremia_siadh": "Hiponatremia/SIADH enzalutamida (PREVAIL+AFFIRM + Bartter-Schwartz)",
    # Faubot LX (#59) — Gate 49 abiraterona hipokalemia/pseudo-aldosteronismo
    # (SEGUNDO gate electrólitos críticos del catálogo, completa eje Na+K).
    # Mecanismo CYP17 inhibition → ↑DOC → activación MR → retención Na +
    # excreción K + alcalosis metabólica (pseudo-aldosteronismo).
    "abiraterone_hypokalemia_grade3": "Hipokalemia abiraterona (COU-AA-302+LATITUDE + pseudo-aldosteronismo CYP17)",
    # Faubot LXI (#64) — Gate 50 hipocalcemia EXTENDIDA bone-targeted
    # (EXTIENDE gate 12 Ra-223 limitado → clase entera bone-modifying agents).
    # Sienta categoría bone-targeted completa (Ra-223 + Lu-177 + denosumab +
    # bisfosfonatos). ASCO Bone Health 2024 + Henry/Fizazi 2011 foundational.
    "bone_targeted_hypocalcemia_extended": "Hipocalcemia bone-targeted EXTENDIDA (ASCO Bone Health 2024 + Henry/Fizazi 2011)",
    # Faubot LXII (#65) — Gate 51 ONJ post-bisfos+denosumab (AAOMS 2022)
    # (2do gate bone-targeted post #64; reusa REGIMEN_CODES_BONE_TARGETED).
    # Definición AAOMS 2022 (Ruggiero JOMS 2022): hueso expuesto >8 sem +
    # sin radiación H&N + tratamiento bone-targeted activo o reciente.
    "bone_targeted_osteonecrosis_jaw": "ONJ bone-targeted (AAOMS 2022 + ASCO Bone Health 2024)",
    # Faubot LXIII (#66) — Gate 52 PARP MDS/AML longitudinal emergente
    # (6° gate longitudinal del catálogo; cubre MDS/AML EMERGENTE
    # durante tratamiento PARPi vs gate 16 que cubre history pre-tratamiento).
    # MAGNITUDE Chi NEJM 2023 + PROfound de Bono NEJM 2020 + WHO 2022.
    "parp_inhibitor_mds_aml_longitudinal": "MDS/AML PARP longitudinal (MAGNITUDE+PROfound + WHO 2022)",
    # Faubot LXIV (#63A) — Gates 53/54/55 PSA Kinetics (post-RP/RT/m0CRPC).
    # 3 gates informacionales/anti-misinterpretation (soft_warning).
    # Sienta categoría kinetics PSA (1ros del catálogo en BCR post-RP/RT
    # y m0CRPC ARPI eligibility).
    "psa_velocity_bcr_aggressive": "BCR agresivo post-RP (Stephenson JCO 2009 + RTOG-9601)",
    "psa_bounce_post_rt_pseudoprogression": "PSA bounce post-RT (Crook IJROBP 2010 + Phoenix 2006 — anti-misinterpretation)",
    "psa_doubling_time_progressive": "PSADT progresivo m0CRPC → ARPI (SPARTAN/PROSPER/ARAMIS pivotal)",
}

_GATE_PREFIX_CLASSES: dict[str, str] = {
    "radium223_":       "Radio-223",
    "lutetium177_":     "Lu-177-PSMA",
    "parp_inhibitor_":  "PARP inhibitors",
    # Faubot XXVI — niraparib específico (después de parp_inhibitor_ general)
    "niraparib_":       "PARPi específico niraparib",
    "qtc_":             "ARPI cardiotoxicidad",
    "lvef_":            "ARPI cardiotoxicidad",
    "arsi_":            "ARPI neurocognitiva",
}

_GATE_SUFFIX_CLASSES: dict[str, str] = {
    "_hypersensitivity": "Hipersensibilidad",
}


def _classify_gate_for_message(code: str) -> str:
    """Mapea `gate.code` → clase farmacológica humanizada para mensaje.

    Reusa el mismo mapping que `profile_compass._build_pivotal_contraindication_gates_panel`
    para mantener consistencia UI ↔ delta narrative.

    Faubot 2026-04-25 (XXIII) — Refactor R13: dispatch dicts (exact +
    prefix + suffix) en vez de if-chain. Complejidad ciclomática ↓ de
    ~14 a ~5. Catálogo declarativo legible de un vistazo.
    """
    c = (code or "").lower()
    # 1. Exact match (más específico, prioridad)
    if c in _GATE_EXACT_CLASSES:
        return _GATE_EXACT_CLASSES[c]
    # 2. Prefix match (clases farmacológicas con familias de gates)
    for prefix, cls in _GATE_PREFIX_CLASSES.items():
        if c.startswith(prefix):
            return cls
    # 3. Suffix match (e.g., *_hypersensitivity)
    for suffix, cls in _GATE_SUFFIX_CLASSES.items():
        if c.endswith(suffix):
            return cls
    return "Otros"


def describe_gate_delta_in_clinical_language(delta: dict) -> list[str]:
    """Humaniza el delta de gates a una lista de strings ES médica para
    `why_changed_today` del copilot.

    Cada string:
      - Empieza con un símbolo (⊕ activado, ⊖ desactivado, ↻ severity).
      - Cita el código del gate y su clase farmacológica.
      - Si hay trial_refs, los menciona como "(según ENZAMET, Xtandi label)".

    Si `delta.is_first_visit=True` o `delta.total_change_count=0`, retorna
    lista vacía (no añade ruido a `why_changed_today`).
    """
    if not delta or not delta.get("available"):
        return []
    if delta.get("total_change_count", 0) == 0:
        return []

    lines: list[str] = []

    # Newly activated → ⊕ (más urgente clínicamente)
    for gate in delta.get("newly_activated") or []:
        code = str(gate.get("code") or "")
        cls = _classify_gate_for_message(code)
        trial_refs = gate.get("trial_refs") or []
        trials_label = ", ".join(trial_refs[:3]) if trial_refs else ""
        suffix = f" (según {trials_label})" if trials_label else ""
        lines.append(
            f"⊕ NUEVO gate pivotal activado: {cls} — `{code}`{suffix}. "
            "Régimen(es) afectado(s) ahora bloqueado(s)."
        )

    # Newly deactivated → ⊖ (alivio clínico, override exitoso)
    for gate in delta.get("newly_deactivated") or []:
        code = str(gate.get("code") or "")
        cls = _classify_gate_for_message(code)
        lines.append(
            f"⊖ Gate pivotal desactivado desde la visita previa: {cls} — `{code}`. "
            "Régimen(es) que estaba(n) bloqueado(s) ahora vuelve(n) a estar disponible(s)."
        )

    # Severity changes → ↻
    for change in delta.get("severity_changed") or []:
        code = str(change.get("code") or "")
        cls = _classify_gate_for_message(code)
        prev_sev = change.get("previous_severity") or "—"
        cur_sev = change.get("current_severity") or "—"
        lines.append(
            f"↻ Gate pivotal cambió severidad: {cls} — `{code}` "
            f"({prev_sev} → {cur_sev})."
        )

    return lines


def extract_previous_pivotal_gates(latest_assessment: dict | None) -> list[dict]:
    """Extrae la lista de gates pivotal del `latest_assessment` previo.

    Args:
        latest_assessment: dict con `result_snapshot.pivotal_contraindication_gates`,
            tal como persiste el sistema de assessments.

    Returns:
        Lista de gates (vacía si no hay assessment previo o si el
        snapshot no expone el campo).
    """
    if not latest_assessment:
        return []
    snapshot = latest_assessment.get("result_snapshot") or {}
    return list(snapshot.get("pivotal_contraindication_gates") or [])


def build_pivotal_gates_delta_summary(delta: dict) -> str:
    """Texto resumen corto del delta para mostrar como header.

    e.g., "1 gate nuevo · 1 gate desactivado · 0 cambios de severidad"
    """
    if not delta or not delta.get("available") or delta.get("is_first_visit"):
        return ""
    parts: list[str] = []
    activated = len(delta.get("newly_activated") or [])
    deactivated = len(delta.get("newly_deactivated") or [])
    changed = len(delta.get("severity_changed") or [])
    if activated:
        parts.append(f"{activated} gate{'s' if activated != 1 else ''} nuevo{'s' if activated != 1 else ''}")
    if deactivated:
        parts.append(f"{deactivated} gate{'s' if deactivated != 1 else ''} desactivado{'s' if deactivated != 1 else ''}")
    if changed:
        parts.append(f"{changed} cambio{'s' if changed != 1 else ''} de severidad")
    if not parts:
        return "Sin cambios en gates pivotal desde la visita previa."
    return " · ".join(parts)
