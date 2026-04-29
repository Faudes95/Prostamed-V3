"""ProstaMed v2 demo mock bundle.

Faubot 2026-04-26 LXXVII (#67D demo): construye un bundle reproduciendo el
shape real de profile_compass.py para un paciente m1CRPC en L2 ARPI
post-docetaxel con BRCA2+. Se usa SOLO en /demos/v2/* para revisión visual
del rediseño v2 antes de migrar producción.

NO toca lógica clínica real. NO accede a la base de datos. Es un fixture
inerte para que el usuario apruebe la dirección visual.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def _iso(d: date) -> str:
    return d.isoformat()


def build_demo_bundle() -> dict[str, Any]:
    """Mock bundle reproduciendo shape real de profile_compass.

    Caso clínico: Hombre 67a, m1CRPC, BRCA2 patogénico. Dx 2022-03 → RP →
    BCR 2023 → ADT + abiraterona (L1) → mCRPC 2024-08 → docetaxel 6 ciclos
    (L2) → progresión 2025-09 → enzalutamida (L3 actual) post-docetaxel.
    Lutetium-177 en evaluación. PSA actual 12.4 ng/mL en ascenso.
    """
    today = date(2026, 4, 26)

    # PSA history points (24 meses)
    psa_points = [
        {"date": _iso(today - timedelta(days=720)), "value": 0.02, "line": {"num": 0, "cls": "RP"}, "label": "Post-RP"},
        {"date": _iso(today - timedelta(days=600)), "value": 0.45, "line": {"num": 0, "cls": "RP"}, "label": "BCR"},
        {"date": _iso(today - timedelta(days=540)), "value": 1.2, "line": {"num": 1, "cls": "ARPI"}, "label": "Pre-ADT"},
        {"date": _iso(today - timedelta(days=510)), "value": 18.4, "line": {"num": 1, "cls": "ARPI"}, "label": "Mets dx"},
        {"date": _iso(today - timedelta(days=480)), "value": 4.2, "line": {"num": 1, "cls": "ARPI"}},
        {"date": _iso(today - timedelta(days=420)), "value": 1.1, "line": {"num": 1, "cls": "ARPI"}},
        {"date": _iso(today - timedelta(days=360)), "value": 0.32, "line": {"num": 1, "cls": "ARPI"}, "label": "Nadir L1"},
        {"date": _iso(today - timedelta(days=300)), "value": 0.48, "line": {"num": 1, "cls": "ARPI"}},
        {"date": _iso(today - timedelta(days=270)), "value": 1.4, "line": {"num": 1, "cls": "ARPI"}},
        {"date": _iso(today - timedelta(days=240)), "value": 4.8, "line": {"num": 1, "cls": "ARPI"}, "label": "CRPC"},
        {"date": _iso(today - timedelta(days=210)), "value": 8.6, "line": {"num": 2, "cls": "TAXANE"}},
        {"date": _iso(today - timedelta(days=180)), "value": 5.2, "line": {"num": 2, "cls": "TAXANE"}},
        {"date": _iso(today - timedelta(days=150)), "value": 2.8, "line": {"num": 2, "cls": "TAXANE"}},
        {"date": _iso(today - timedelta(days=120)), "value": 1.6, "line": {"num": 2, "cls": "TAXANE"}, "label": "Nadir L2"},
        {"date": _iso(today - timedelta(days=90)), "value": 2.4, "line": {"num": 2, "cls": "TAXANE"}},
        {"date": _iso(today - timedelta(days=60)), "value": 5.8, "line": {"num": 2, "cls": "TAXANE"}},
        {"date": _iso(today - timedelta(days=45)), "value": 9.2, "line": {"num": 3, "cls": "ARPI"}, "label": "Inicio L3"},
        {"date": _iso(today - timedelta(days=30)), "value": 10.5, "line": {"num": 3, "cls": "ARPI"}},
        {"date": _iso(today - timedelta(days=15)), "value": 11.8, "line": {"num": 3, "cls": "ARPI"}},
        {"date": _iso(today), "value": 12.4, "line": {"num": 3, "cls": "ARPI"}, "label": "Hoy"},
    ]

    forecast_per_line = {
        "3": {
            "regimen_class": "ARPI",
            "regimen_label": "Enzalutamida 160mg/d",
            "psadt_months": 1.8,
            "confidence": "low",
            "points": [
                {"date": _iso(today + timedelta(days=15)), "value": 14.2},
                {"date": _iso(today + timedelta(days=30)), "value": 16.5},
                {"date": _iso(today + timedelta(days=60)), "value": 22.4},
                {"date": _iso(today + timedelta(days=90)), "value": 29.8},
            ],
            "kinetics_classification": "rapid_progression",
        }
    }

    treatment_bands = [
        {"start_date": _iso(today - timedelta(days=540)), "end_date": _iso(today - timedelta(days=210)),
         "regimen_class": "ARPI", "label": "L1 ADT+ABI", "duration_months": 11.0},
        {"start_date": _iso(today - timedelta(days=210)), "end_date": _iso(today - timedelta(days=45)),
         "regimen_class": "TAXANE", "label": "L2 Docetaxel", "duration_months": 5.5},
        {"start_date": _iso(today - timedelta(days=45)), "end_date": _iso(today + timedelta(days=90)),
         "regimen_class": "ARPI", "label": "L3 Enzalutamida (actual)", "duration_months": 1.5},
    ]

    cohort_p25 = [
        {"date": p["date"], "value": max(0.1, p["value"] * 0.7)} for p in psa_points
    ]
    cohort_p75 = [
        {"date": p["date"], "value": p["value"] * 1.6} for p in psa_points
    ]
    cohort_median = [
        {"date": p["date"], "value": p["value"] * 1.1} for p in psa_points
    ]

    events = [
        {"date": _iso(today - timedelta(days=510)), "label": "Mets dx (PSMA-PET)", "severity": "warning", "category": "imaging"},
        {"date": _iso(today - timedelta(days=240)), "label": "CRPC declarado", "severity": "critical", "category": "state_transition"},
        {"date": _iso(today - timedelta(days=210)), "label": "Inicio docetaxel", "severity": "info", "category": "treatment"},
        {"date": _iso(today - timedelta(days=120)), "label": "Nadir L2 PSA 1.6", "severity": "success", "category": "response"},
        {"date": _iso(today - timedelta(days=60)), "label": "Progresión PCWG3", "severity": "critical", "category": "progression"},
        {"date": _iso(today - timedelta(days=15)), "label": "BRCA2 c.5946delT confirmado", "severity": "warning", "category": "genomic"},
    ]

    thresholds = [
        {"value": 0.2, "label": "Phoenix BCR", "severity": "info"},
        {"value": 50.0, "label": "PCWG3 prog", "severity": "warning"},
    ]

    timeline_payload = {
        "psa_points": psa_points,
        "forecast_per_line": forecast_per_line,
        "treatment_bands": treatment_bands,
        "cohort_p25": cohort_p25,
        "cohort_p75": cohort_p75,
        "cohort_median": cohort_median,
        "events": events,
        "thresholds": thresholds,
    }

    # Identity / classification
    identity = {
        "name": "García Hernández, Roberto Antonio",
        "mrn": "MRN-002847",
        "age": 67,
        "ecog": 1,
        "stage": "m1crpc",
        "stage_label": "m1CRPC",
        "diagnosis_date": "2022-03-14",
        "current_line": 3,
        "current_regimen": "Enzalutamida 160mg/día",
        "decision_today": "Solicitar PSMA-PET + iniciar PARP (olaparib) por BRCA2+ patogénico",
        "decision_rationale": "Falla a docetaxel + ARPI tras BRCA2 confirmado → PROfound NCCN cat 1",
        "faubot_release": "2026-04-26 LXXVII",
        "critical_alerts_count": 4,
    }

    # Gates triggered (subset relevant to this case)
    gates_triggered = [
        {
            "code": "G61", "title": "HRR confirmation HARD_BLOCK",
            "severity": "hard_block", "class_label": "PARP eligibility gate",
            "reason": "Test genómico confirmado: BRCA2 c.5946delT patogénico (Myriad MyChoice)",
            "trial_refs": [
                {"ref": "PROfound", "type": "trial", "url": "https://clinicaltrials.gov/study/NCT02987543"},
                {"ref": "33068333", "type": "PMID", "url": "https://pubmed.ncbi.nlm.nih.gov/33068333/"},
                {"ref": "10.1056/NEJMoa1911440", "type": "DOI", "url": "https://doi.org/10.1056/NEJMoa1911440"},
            ],
            "evidence_tag": "NCCN PROS-2 cat 1",
        },
        {
            "code": "G47", "title": "PSA flare ARPI pseudoprogresión",
            "severity": "soft_warning", "class_label": "Anti-misinterpretation",
            "reason": "Inicio enzalutamida hace 45d; alza PSA puede ser flare transitorio (4-12 sem)",
            "trial_refs": [
                {"ref": "AFFIRM", "type": "trial", "url": "https://clinicaltrials.gov/study/NCT00974311"},
                {"ref": "PREVAIL", "type": "trial", "url": "https://clinicaltrials.gov/study/NCT01212991"},
            ],
            "evidence_tag": "PCWG3 working group",
        },
        {
            "code": "G55", "title": "PSADT≤10m m0CRPC progresivo",
            "severity": "soft_warning", "class_label": "Kinetics anti-misinterpretation",
            "reason": "PSADT actual 1.8m sugiere kinetics agresivas — re-evaluar imagen",
            "trial_refs": [
                {"ref": "SPARTAN", "type": "trial", "url": "https://clinicaltrials.gov/study/NCT01946204"},
                {"ref": "PROSPER", "type": "trial", "url": "https://clinicaltrials.gov/study/NCT02003924"},
            ],
            "evidence_tag": "NEJM 2018 SPARTAN/PROSPER",
        },
    ]

    # Clinical alerts (50+ pero mostraremos 18 representativas)
    clinical_alerts = [
        {"id": 1, "severity": "critical", "category": "psa_kinetics", "title": "PSADT 1.8 meses",
         "message": "PSA pasó de 8.6 → 12.4 en 6 semanas. PSADT < 3m indica kinetics agresivas.",
         "guideline": "PCWG3 + NCCN PROS-3", "recommended_action": "Imagen PSMA + ctDNA + considerar switch"},
        {"id": 2, "severity": "critical", "category": "genomic", "title": "BRCA2 patogénico confirmado",
         "message": "c.5946delT (Myriad MyChoice). Elegible PARP (olaparib/rucaparib).",
         "guideline": "NCCN PROS-13", "recommended_action": "Considerar olaparib 300mg BID"},
        {"id": 3, "severity": "critical", "category": "progression", "title": "Progresión PCWG3 confirmada",
         "message": "↑ PSA + nuevas lesiones óseas en gammagrama vs basal.",
         "guideline": "PCWG3 working group", "recommended_action": "Switch línea sistémica"},
        {"id": 4, "severity": "critical", "category": "ddi", "title": "Interacción enzalutamida + apixaban",
         "message": "Enzalutamida es inductor potente CYP3A4 → ↓ apixaban 50%. Riesgo trombótico.",
         "guideline": "FDA label PI", "recommended_action": "Switch a HBPM o monitor anti-Xa"},
        {"id": 5, "severity": "warning", "category": "lab", "title": "ALP 245 U/L (↑3x)",
         "message": "Sugestivo de mets óseas activas. Considerar terapia ósea-dirigida.",
         "guideline": "NCCN PROS-7", "recommended_action": "Iniciar ácido zoledrónico/denosumab"},
        {"id": 6, "severity": "warning", "category": "bone_health", "title": "DEXA pendiente >24m",
         "message": "Bajo ADT prolongado. Riesgo osteoporosis + fractura.",
         "guideline": "NCCN PROS-G", "recommended_action": "DEXA + Ca/Vit D + bisfosfonato"},
        {"id": 7, "severity": "warning", "category": "treatment_milestone", "title": "Mes 11 ADT continuo",
         "message": "Próxima evaluación: testosterona, perfil lipídico, glucosa, DEXA.",
         "guideline": "EAU 2026", "recommended_action": "Solicitar paneles antes mes 12"},
        {"id": 8, "severity": "warning", "category": "ecog", "title": "ECOG 1 — verificar función",
         "message": "Cambio reciente desde ECOG 0. Si ECOG ≥2 limitar opciones agresivas.",
         "guideline": "NCCN PROS-4", "recommended_action": "Re-evaluar performance + comorbilidades"},
        {"id": 9, "severity": "warning", "category": "germline_testing", "title": "Familiares 1° grado: testing",
         "message": "BRCA2+ patogénico → ofrecer testing a hijos y hermanos.",
         "guideline": "NCCN GENE-1", "recommended_action": "Referir a genética clínica"},
        {"id": 10, "severity": "warning", "category": "ctcae_toxicity", "title": "Fatiga grado 2 enzalutamida",
         "message": "Reportado en última visita. Si grado ≥3 considerar dose-reduction.",
         "guideline": "CTCAE v5", "recommended_action": "Manejo sintomático + screen depresión"},
        {"id": 11, "severity": "info", "category": "imaging", "title": "PSMA-PET sugerido vs CT/bone",
         "message": "PSMA-PET superior para detectar mets oligo + viscerales pequeñas.",
         "guideline": "PROMISE/proPSMA", "recommended_action": "Solicitar PSMA-PET 68Ga o 18F"},
        {"id": 12, "severity": "info", "category": "pro_quality_life", "title": "PHQ-9 score 8 — leve depresión",
         "message": "Síntomas depresivos leves. Reevaluar ante cambios terapia.",
         "guideline": "ASCO PCO", "recommended_action": "Counseling + screening trimestral"},
        {"id": 13, "severity": "info", "category": "radiation_therapy", "title": "Dolor óseo focal L4",
         "message": "EVA 4/10 lumbar focal. Candidato RT paliativa 8 Gy×1.",
         "guideline": "ASTRO/EBM", "recommended_action": "Consulta radio-oncología"},
        {"id": 14, "severity": "info", "category": "skeletal_event", "title": "SRE risk score: alto",
         "message": "Mets óseas múltiples + ALP↑ + ADT prolongado.",
         "guideline": "Saad criteria", "recommended_action": "Bone-targeted therapy mensual"},
        {"id": 15, "severity": "info", "category": "trial_eligibility", "title": "Elegible TALAPRO-3",
         "message": "BRCA2+ + ARPI naive → talazoparib + enzalutamida.",
         "guideline": "ClinicalTrials.gov", "recommended_action": "Discutir con paciente / referir"},
        {"id": 16, "severity": "info", "category": "ai_anomaly", "title": "Anomalía longitudinal IA",
         "message": "Patrón PSA actual difiere 2σ de cohorte BRCA2+ post-docetaxel.",
         "guideline": "ML model v2", "recommended_action": "Revisar con tumor board"},
        {"id": 17, "severity": "info", "category": "survival_endpoint", "title": "rPFS proyectado 4.2m",
         "message": "Por nomograma Halabi vs literatura PROfound (mediana 7.4m).",
         "guideline": "PROfound rPFS", "recommended_action": "Optimizar línea actual + plan B"},
        {"id": 18, "severity": "info", "category": "tumor_board", "title": "Próximo TB: 2026-05-03",
         "message": "Caso preparado: imágenes, genómica, kinetics, propuestas.",
         "guideline": "Local protocol", "recommended_action": "Confirmar asistencia"},
    ]

    therapy_checkpoints = [
        {"label": "Inicio ADT (Leuprolide 22.5mg)", "due_date": _iso(today - timedelta(days=540)),
         "status": "done", "category": "milestone"},
        {"label": "Testosterona post-castración (mes 1)", "due_date": _iso(today - timedelta(days=510)),
         "status": "done", "value": "12 ng/dL"},
        {"label": "Re-evaluación ADT mes 6", "due_date": _iso(today - timedelta(days=360)),
         "status": "done", "value": "PSA nadir 0.32"},
        {"label": "Re-evaluación ADT mes 12", "due_date": _iso(today - timedelta(days=180)),
         "status": "done", "value": "Progresión CRPC"},
        {"label": "Docetaxel ciclo 6/6", "due_date": _iso(today - timedelta(days=45)),
         "status": "done", "value": "Completado"},
        {"label": "DEXA basal (osteoporosis screen)", "due_date": _iso(today - timedelta(days=60)),
         "status": "overdue", "value": "Vencida hace 60d"},
        {"label": "PSMA-PET re-stage", "due_date": _iso(today + timedelta(days=7)),
         "status": "due", "value": "Próximos 7 días"},
        {"label": "Inicio olaparib (post-confirmación HRR)", "due_date": _iso(today + timedelta(days=14)),
         "status": "due", "value": "Pendiente HRR"},
        {"label": "Re-evaluación PARP mes 3", "due_date": _iso(today + timedelta(days=104)),
         "status": "due", "value": "Por programar"},
    ]

    precision_genomics = [
        {"mutation": "BRCA2 c.5946delT", "actionable_level": "high",
         "clinical_action": "Olaparib 300mg BID (PROfound)", "evidence": "NEJM 2020 33068333"},
        {"mutation": "ATM c.7271T>G", "actionable_level": "medium",
         "clinical_action": "Considerar PARP inhibitor (rucaparib TRITON3)", "evidence": "NEJM 2023"},
        {"mutation": "TP53 wt", "actionable_level": "low",
         "clinical_action": "No accionable directo; favorable pronóstico vs TP53+RB1 NEPC", "evidence": "—"},
        {"mutation": "PTEN intact", "actionable_level": "low",
         "clinical_action": "AKT inhibitor (capivasertib) NO indicado", "evidence": "CAPItello-281"},
        {"mutation": "MSI/MMR estable", "actionable_level": "low",
         "clinical_action": "Pembrolizumab NO indicado", "evidence": "FDA TMB high label"},
    ]

    cohort_comparison = [
        {"metric": "PSA actual", "patient": 12.4, "p25": 4.2, "p50": 8.8, "p75": 18.5, "unit": "ng/mL"},
        {"metric": "PSADT", "patient": 1.8, "p25": 6.2, "p50": 3.1, "p75": 1.4, "unit": "meses"},
        {"metric": "Tiempo a CRPC", "patient": 11.0, "p25": 18.0, "p50": 13.0, "p75": 8.0, "unit": "meses"},
        {"metric": "rPFS L2 docetaxel", "patient": 5.5, "p25": 9.2, "p50": 6.8, "p75": 4.0, "unit": "meses"},
        {"metric": "ALP", "patient": 245, "p25": 95, "p50": 130, "p75": 280, "unit": "U/L"},
    ]

    risk_tools = [
        {"tool": "Halabi mCRPC nomograma", "score": 0.72, "label": "Mortalidad 1a: 28%",
         "missing_inputs": [], "fidelity": "complete"},
        {"tool": "Decipher post-RP", "score": 0.81, "label": "Alto riesgo",
         "missing_inputs": [], "fidelity": "complete"},
        {"tool": "CAPRA-S", "score": 7, "label": "Alto riesgo (5y BCR 60%)",
         "missing_inputs": [], "fidelity": "complete"},
        {"tool": "Briganti 2019 LNI", "score": 22, "label": "LN+ predicho",
         "missing_inputs": ["clinical_T_stage"], "fidelity": "partial"},
    ]

    decision_audit = {
        "como": {
            "preferred_regimen_code": "OLAPARIB_300_BID",
            "preferred_regimen_label": "Olaparib 300mg BID (PROfound)",
            "alternative_regimens_count": 3,
            "alternatives": [
                {"code": "TALAZOPARIB_ENZA", "label": "Talazoparib + Enzalutamida (TALAPRO-2)"},
                {"code": "RUCAPARIB", "label": "Rucaparib 600mg BID (TRITON3)"},
                {"code": "LU177_PSMA", "label": "Lu-177 PSMA (VISION) si PSMA+ alta"},
            ],
            "decision_quality": {"score": 0.92, "label": "Alta calidad"},
        },
        "por_que": {
            "active_gates_count": 3,
            "not_recommended_count": 2,
            "contraindications_count": 0,
            "active_gates": gates_triggered,
        },
        "datos": {
            "input_field_count": 142,
            "missing_critical_inputs": ["psma_pet_uptake_quantitative"],
            "stale_inputs": ["dexa_t_score (>24m)"],
            "snapshot_completeness": 0.87,
        },
        "evidencia": {
            "guideline_versions": {"NCCN": "5.2026", "EAU": "2026", "AUA": "2024", "ESMO": "2024"},
            "unique_trial_refs_count": 9,
            "per_gate_evidence_count": 11,
        },
        "version": {
            "faubot_release": "2026-04-26 LXXVII",
            "module_sha": "a3d5b921",
            "gates_active_count": 85,
        },
    }

    return {
        "identity": identity,
        "timeline": timeline_payload,
        "gates_triggered": gates_triggered,
        "clinical_alerts": clinical_alerts,
        "therapy_checkpoints": therapy_checkpoints,
        "precision_genomics": precision_genomics,
        "cohort_comparison": cohort_comparison,
        "risk_tools": risk_tools,
        "decision_audit": decision_audit,
    }


def build_stage_center_demo_data() -> dict[str, Any]:
    """Mock data para Centro Clínico por Estadio."""
    stages = [
        {"key": "diagnostic", "label": "Diagnóstico", "sub": "Pre-biopsia + workup",
         "count": 14, "alerts": 1, "nccn": "PROS-1", "eau": "Initial"},
        {"key": "localized", "label": "Localizado", "sub": "Riesgo bajo / int / alto",
         "count": 87, "alerts": 3, "nccn": "PROS-2..5", "eau": "Localized"},
        {"key": "mcspc", "label": "mCSPC", "sub": "HV / LV / Oligo",
         "count": 42, "alerts": 5, "nccn": "PROS-9", "eau": "mHSPC"},
        {"key": "m0crpc", "label": "m0CRPC", "sub": "Castración resistente no-mets",
         "count": 11, "alerts": 2, "nccn": "PROS-10", "eau": "nmCRPC"},
        {"key": "m1crpc", "label": "m1CRPC", "sub": "Castración resistente metastásico",
         "count": 28, "alerts": 7, "nccn": "PROS-11..13", "eau": "mCRPC"},
        {"key": "nepc", "label": "NEPC / aggressive", "sub": "Variantes neuroendocrinas",
         "count": 4, "alerts": 1, "nccn": "PROS-12", "eau": "Variants"},
        {"key": "palliative", "label": "Paliativo", "sub": "Fin de vida + síntomas",
         "count": 9, "alerts": 1, "nccn": "PROS-14", "eau": "BSC"},
    ]

    # Stage canvases — m1crpc detallado, otros placeholder
    canvases = {}
    canvases["m1crpc"] = {
        "title": "m1CRPC — Castración resistente metastásico",
        "subtitle": "Decisión sistémica condicionada a fenotipo genómico, prior taxano y estado funcional. Switch obligatorio post-docetaxel sin respuesta sostenida.",
        "stats": [
            {"label": "Activos en estadio", "value": "28", "sub": "+3 esta semana", "color": "var(--stage-m1crpc)"},
            {"label": "% cohorte total", "value": "14.6%", "sub": "192 totales", "color": "var(--clinical-info)"},
            {"label": "Alertas críticas", "value": "7", "sub": "3 PSADT, 2 DDI, 2 prog", "color": "var(--clinical-critical)"},
            {"label": "Decisiones pendientes", "value": "4", "sub": "Avg time-to-decision: 2.1d", "color": "var(--clinical-warning)"},
        ],
        "modules": [
            {"id": "advanced_therapy_decision", "label": "Decisión terapéutica avanzada",
             "desc": "Algoritmo NCCN PROS-11..13 + EAU 2026. Considera prior taxano, HRR status, performance, sitio mets.",
             "n_decisions_today": 6},
            {"id": "psma_lutetium", "label": "Eligibilidad Lu-177-PSMA (VISION)",
             "desc": "PSMA-PET avid (SUV ≥ 20) + post-ARPI + post-taxano + ECOG ≤2.",
             "n_decisions_today": 2},
            {"id": "parp_eligibility", "label": "PARP inhibitor (PROfound/TRITON)",
             "desc": "HRR confirmado: BRCA1/2, ATM, CDK12, PALB2 patogénico. Olaparib/rucaparib/talazoparib.",
             "n_decisions_today": 3},
            {"id": "radium223", "label": "Ra-223 ALSYMPCA",
             "desc": "Mets óseas predominantes + sintomáticas, sin viscerales. Sin overlapping con quimioterapia.",
             "n_decisions_today": 1},
            {"id": "nepc_screening", "label": "Screening NEPC",
             "desc": "PSA bajo + viscerales + BPI alto + LDH↑ + cromogranina↑ → biopsia.",
             "n_decisions_today": 0},
            {"id": "bone_health", "label": "Terapia ósea-dirigida",
             "desc": "Zoledronato/denosumab. Vigilar ONJ + Ca/Vit D + DEXA.",
             "n_decisions_today": 4},
        ],
        "trial_eligibility": [
            {"trial": "TALAPRO-2 (NCT03395197)", "criteria_match": 4, "criteria_total": 5,
             "status": "Eligible", "drug": "Talazoparib + Enzalutamida"},
            {"trial": "PROfound (NCT02987543)", "criteria_match": 5, "criteria_total": 5,
             "status": "Eligible", "drug": "Olaparib"},
            {"trial": "VISION (NCT03511664)", "criteria_match": 3, "criteria_total": 5,
             "status": "Pendiente PSMA-PET", "drug": "Lu-177 PSMA"},
            {"trial": "ARASENS (NCT02799602)", "criteria_match": 1, "criteria_total": 5,
             "status": "No elegible (mCRPC, no mHSPC)", "drug": "Darolutamida triplete"},
        ],
        "cohort_snapshot": {
            "psa_distribution": {"labels": ["<2", "2-5", "5-20", "20-100", ">100"], "values": [3, 6, 11, 6, 2]},
            "ecog_distribution": {"labels": ["0", "1", "2", "3", "4"], "values": [4, 14, 7, 2, 1]},
            "treatment_lines": {"labels": ["L1", "L2", "L3", "L4+"], "values": [9, 11, 6, 2]},
            "genomic": {"labels": ["BRCA1/2", "ATM", "CDK12", "Other HRR", "HRR neg"], "values": [4, 3, 2, 5, 14]},
        },
    }

    # Placeholder for other stages
    for key in ["diagnostic", "localized", "mcspc", "m0crpc", "nepc", "palliative"]:
        if key not in canvases:
            stage_meta = next(s for s in stages if s["key"] == key)
            canvases[key] = {
                "title": f"{stage_meta['label']} — vista demo",
                "subtitle": "Esta vista replica la estructura de m1CRPC con datos placeholder. En producción consume /api/stage-cohort/<stage>.",
                "stats": [
                    {"label": "Activos en estadio", "value": str(stage_meta["count"]), "sub": "demo", "color": "var(--clinical-info)"},
                    {"label": "Alertas críticas", "value": str(stage_meta["alerts"]), "sub": "demo", "color": "var(--clinical-warning)"},
                    {"label": "Decisiones pendientes", "value": "—", "sub": "—", "color": "var(--clinical-neutral)"},
                    {"label": "Avg time-to-decision", "value": "—", "sub": "—", "color": "var(--clinical-neutral)"},
                ],
                "modules": [], "trial_eligibility": [], "cohort_snapshot": {},
            }

    return {"stages": stages, "canvases": canvases, "default_stage": "m1crpc"}


def build_intake_demo_data() -> dict[str, Any]:
    """Mock schema para el demo de ingreso de paciente v2.

    PRESERVA las 4 etapas del clinical_hub quick_classifier original:
      1. Confirmación diagnóstica
      2. Tratamiento local previo
      3. Enfermedad metastásica
      4. Progresión sistémica / ADT

    AÑADE los campos críticos identificados como gaps para correct initial
    staging (NCCN/EAU/CHAARTED + risk stratification CAPRA):
      - Identidad básica + ECOG + Charlson
      - Histología detallada (PNI, SVI, % cores, max core involvement)
      - Imaging staging (PI-RADS, mpMRI, PSMA-PET avidity)
      - Labs baseline (PSA, Hb, ALP, LDH, testosterona)
      - Genómica + family history (germline trigger NCCN GENE-1)
      - PRO + BPI pain score
      - CHAARTED HV criteria explícitos
    """
    base: dict[str, Any] = {
        "presets": [
            {"id": "preset_localized_int",
             "label": "Localizado intermedio",
             "desc": "65a · PSA 8.4 · Gleason 3+4 · cT2a · ECOG 0",
             "stage_predicted": "localized"},
            {"id": "preset_mcspc_hv",
             "label": "mCSPC alto volumen",
             "desc": "72a · PSA 145 · Gleason 9 · cT3b · ≥4 mets óseas + 1 visceral",
             "stage_predicted": "mcspc"},
            {"id": "preset_m1crpc_brca",
             "label": "m1CRPC + BRCA2+",
             "desc": "67a · L3 enzalutamida · BRCA2 patogénico · PSADT 1.8m",
             "stage_predicted": "m1crpc"},
        ],
        "stages": [
            {"key": "identity", "label": "Identidad", "icon": "user", "n_fields": 7, "required": 7},
            {"key": "diagnosis", "label": "Diagnóstico", "icon": "clipboard", "n_fields": 8, "required": 5},
            {"key": "histology", "label": "Histología", "icon": "microscope", "n_fields": 12, "required": 6},
            {"key": "imaging", "label": "Imaging staging", "icon": "scan", "n_fields": 10, "required": 4},
            {"key": "labs", "label": "Labs baseline", "icon": "flask", "n_fields": 9, "required": 5},
            {"key": "metastatic", "label": "Enfermedad mets", "icon": "map", "n_fields": 14, "required": 0,
             "conditional": "if metastatic_disease_known == 'yes'"},
            {"key": "systemic", "label": "Sistémica / ADT", "icon": "pill", "n_fields": 8, "required": 0,
             "conditional": "if prior_local_treatment or metastatic"},
            {"key": "genomics", "label": "Genómica", "icon": "helix", "n_fields": 7, "required": 2},
            {"key": "performance", "label": "Performance / PRO", "icon": "activity", "n_fields": 8, "required": 4},
        ],
        # Field catalog organized by stage
        "fields": {
            "identity": [
                {"name": "given_name", "label": "Nombre(s)", "type": "text", "required": True, "placeholder": "Roberto Antonio"},
                {"name": "family_name", "label": "Apellidos", "type": "text", "required": True, "placeholder": "García Hernández"},
                {"name": "date_of_birth", "label": "Fecha nacimiento", "type": "date", "required": True},
                {"name": "mrn", "label": "MRN / Folio", "type": "text", "required": True, "placeholder": "Auto-generado si vacío"},
                {"name": "biological_sex", "label": "Sexo biológico", "type": "select", "required": True,
                 "options": [("male", "Masculino"), ("intersex_xy", "Intersexo XY")], "help": "Solo se ingresan pacientes con próstata"},
                {"name": "race_ethnicity", "label": "Raza / etnia", "type": "select", "required": False,
                 "options": [("hispanic_latino", "Hispano/Latino"), ("white", "Blanco no hispano"), ("black_african", "Negro/Afroamericano (riesgo ↑)"), ("asian", "Asiático"), ("native_indigenous", "Indígena/Nativo"), ("other", "Otro / no reportado")],
                 "help": "Negro/Afro: riesgo y agresividad ↑ (NCCN GENE-1)"},
                {"name": "primary_language", "label": "Lengua principal", "type": "select", "required": False,
                 "options": [("es", "Español"), ("en", "Inglés"), ("nahuatl", "Náhuatl"), ("maya", "Maya"), ("other", "Otra")]},
            ],
            "diagnosis": [
                {"name": "known_cancer_diagnosis", "label": "¿Diagnóstico de cáncer de próstata confirmado?", "type": "select", "required": True,
                 "options": [("yes", "Sí · biopsia positiva"), ("suspected_no_biopsy", "Sospecha · sin biopsia"), ("no", "No · workup en curso")],
                 "stage_impact": "Si NO → routing a diagnostic_workup; si suspected → screening"},
                {"name": "diagnosis_date", "label": "Fecha de diagnóstico (biopsia +)", "type": "date", "required": True,
                 "conditional": "known_cancer_diagnosis == yes"},
                {"name": "diagnosis_method", "label": "Método de confirmación", "type": "select", "required": True,
                 "conditional": "known_cancer_diagnosis == yes",
                 "options": [("trus_biopsy", "Biopsia TRUS (≥12 cilindros)"), ("mri_fusion_biopsy", "Biopsia MRI-fusión"), ("transperineal", "Transperineal templated"), ("rp_specimen", "Pieza de RP"), ("other", "Otro")]},
                {"name": "prior_negative_biopsy", "label": "¿Biopsia previa negativa?", "type": "select", "required": False,
                 "options": [("none", "Sin biopsia previa"), ("yes_one", "Sí · 1 biopsia previa neg"), ("yes_multiple", "Sí · ≥2 biopsias prev neg")]},
                {"name": "prior_prostatectomy", "label": "RP previa", "type": "select", "required": True,
                 "options": [("no", "No"), ("yes", "Sí · prostatectomía radical")]},
                {"name": "prior_radiation", "label": "RT previa", "type": "select", "required": True,
                 "options": [("no", "No"), ("yes_ebrt", "EBRT (haz externo)"), ("yes_brachy", "Braquiterapia"), ("yes_combined", "EBRT + braqui")]},
                {"name": "bcr_detected", "label": "BCR detectada (post-RP/RT)", "type": "select", "required": False,
                 "conditional": "prior_prostatectomy or prior_radiation",
                 "options": [("no", "No"), ("yes_first", "Sí · primera BCR"), ("yes_recurrent", "Sí · BCR recurrente")]},
                {"name": "bcr2", "label": "Segunda BCR (post-salvage)", "type": "select", "required": False,
                 "conditional": "bcr_detected == yes",
                 "options": [("no", "No"), ("yes", "Sí · post-salvage local")]},
            ],
            "histology": [
                {"name": "gleason_primary", "label": "Gleason primario", "type": "select", "required": True,
                 "options": [("3", "3"), ("4", "4"), ("5", "5")]},
                {"name": "gleason_secondary", "label": "Gleason secundario", "type": "select", "required": True,
                 "options": [("3", "3"), ("4", "4"), ("5", "5")]},
                {"name": "isup_grade", "label": "ISUP grade group", "type": "select", "required": True,
                 "options": [("1", "GG1 (3+3)"), ("2", "GG2 (3+4)"), ("3", "GG3 (4+3)"), ("4", "GG4 (8)"), ("5", "GG5 (9-10)")],
                 "help": "Auto-derivable de Gleason"},
                {"name": "num_cores_positive", "label": "# cilindros positivos", "type": "number", "required": True,
                 "help": "Critical para CAPRA + NCCN unfavorable"},
                {"name": "total_cores", "label": "# cilindros totales", "type": "number", "required": True},
                {"name": "max_core_involvement_pct", "label": "% máximo involucro / cilindro", "type": "number", "required": False,
                 "help": "≥50% = NCCN intermediate unfavorable criterion · GAP en intake actual"},
                {"name": "perineural_invasion", "label": "Invasión perineural (PNI)", "type": "select", "required": False,
                 "options": [("no", "No"), ("yes", "Sí"), ("unknown", "No reportado")],
                 "help": "NCCN very-high-risk descriptor · pronóstico · GAP en intake actual"},
                {"name": "intraductal_carcinoma", "label": "Carcinoma intraductal (IDC-P)", "type": "select", "required": False,
                 "options": [("no", "No"), ("yes", "Sí"), ("unknown", "No evaluado")],
                 "help": "Histología agresiva · trigger genómico"},
                {"name": "cribriform_pattern", "label": "Patrón cribiforme", "type": "select", "required": False,
                 "options": [("no", "No"), ("yes", "Sí"), ("unknown", "No reportado")]},
                {"name": "percent_pattern_4", "label": "% patrón Gleason 4", "type": "number", "required": False,
                 "help": "Decision refiner intermediate fav vs unfav"},
                {"name": "neuroendocrine_features", "label": "Features neuroendocrinas", "type": "select", "required": False,
                 "options": [("no", "No"), ("focal", "Focales"), ("diffuse", "Difusas"), ("pure_nepc", "NEPC puro")],
                 "help": "Si difusas/puras → routing NEPC pathway"},
                {"name": "atypical_variant", "label": "Variante atípica", "type": "select", "required": False,
                 "options": [("none", "Acinar clásico"), ("ductal", "Ductal"), ("squamous", "Escamoso"), ("sarcomatoid", "Sarcomatoide")]},
            ],
            "imaging": [
                {"name": "clinical_tstage", "label": "Estadio T clínico", "type": "select", "required": True,
                 "options": [("T1c", "T1c (no palpable, biop+)"), ("T2a", "T2a (≤½ lóbulo)"), ("T2b", "T2b (>½ lóbulo)"), ("T2c", "T2c (bilateral)"), ("T3a", "T3a (extracapsular)"), ("T3b", "T3b (vesículas seminales · SVI)"), ("T4", "T4 (estructuras adyacentes)")]},
                {"name": "clinical_nstage", "label": "Estadio N clínico", "type": "select", "required": True,
                 "options": [("N0", "N0 (sin nodos+)"), ("N1", "N1 (nodos pélvicos+)"), ("Nx", "Nx (no evaluado)")]},
                {"name": "clinical_mstage", "label": "Estadio M clínico", "type": "select", "required": True,
                 "options": [("M0", "M0 (sin mets)"), ("M1a", "M1a (nodos no regionales)"), ("M1b", "M1b (óseas)"), ("M1c", "M1c (viscerales)"), ("Mx", "Mx (no evaluado)")]},
                {"name": "mpmri_performed", "label": "mpMRI prostática realizada", "type": "select", "required": False,
                 "options": [("no", "No"), ("yes_pre_bx", "Sí · pre-biopsia"), ("yes_post_bx", "Sí · post-biopsia (staging)")]},
                {"name": "pi_rads_score", "label": "PI-RADS score (lesión índice)", "type": "select", "required": False,
                 "conditional": "mpmri_performed != no",
                 "options": [("1", "1 - benigno"), ("2", "2 - probable benigno"), ("3", "3 - equívoco"), ("4", "4 - sospecha"), ("5", "5 - alta sospecha")],
                 "help": "GAP en intake actual · NCCN biopsy decision"},
                {"name": "seminal_vesicle_invasion_imaging", "label": "SVI por imagen (mpMRI)", "type": "select", "required": False,
                 "options": [("no", "No"), ("suspected", "Sospechosa"), ("definite", "Definitiva (cT3b)")],
                 "help": "GAP · NCCN high-risk criterion"},
                {"name": "extracapsular_extension_imaging", "label": "Extensión extracapsular (mpMRI)", "type": "select", "required": False,
                 "options": [("no", "No"), ("suspected", "Sospechosa"), ("definite", "Definitiva (cT3a)")]},
                {"name": "psma_pet_performed", "label": "PSMA-PET realizada", "type": "select", "required": False,
                 "options": [("no", "No"), ("ga68", "Sí · 68Ga-PSMA"), ("f18", "Sí · 18F-PSMA"), ("planned", "Planeada")],
                 "help": "GAP · staging accuracy moderna"},
                {"name": "psma_suv_max", "label": "SUVmax PSMA (lesión dominante)", "type": "number", "required": False,
                 "conditional": "psma_pet_performed != no",
                 "help": "≥20 = elegible Lu-177 PSMA (VISION)"},
                {"name": "bone_scan_performed", "label": "Gammagrama óseo", "type": "select", "required": False,
                 "options": [("no", "No"), ("yes_negative", "Sí · negativo"), ("yes_positive", "Sí · positivo"), ("planned", "Planeado")]},
            ],
            "labs": [
                {"name": "psa_baseline", "label": "PSA basal (ng/mL)", "type": "number", "required": True,
                 "help": "PSA al diagnóstico, antes de cualquier tx"},
                {"name": "psa_current", "label": "PSA actual (ng/mL)", "type": "number", "required": False,
                 "help": "Para PSADT + monitor longitudinal"},
                {"name": "psa_density", "label": "PSA density (ng/mL/cc)", "type": "number", "required": False,
                 "help": "PSA / volumen prostático"},
                {"name": "testosterone_baseline", "label": "Testosterona basal (ng/dL)", "type": "number", "required": False,
                 "help": "GAP · castración confirmada <50 ng/dL (NCCN)"},
                {"name": "hemoglobin_baseline", "label": "Hemoglobina basal (g/dL)", "type": "number", "required": False,
                 "help": "GAP · prognostic biomarker (anemia <10 NCCN concern)"},
                {"name": "alkaline_phosphatase", "label": "Fosfatasa alcalina (U/L)", "type": "number", "required": False,
                 "help": "GAP · CHAARTED/LATITUDE biomarker bone disease"},
                {"name": "ldh_baseline", "label": "LDH basal (U/L)", "type": "number", "required": False,
                 "help": "GAP · NEPC signal · m1CRPC prognostic"},
                {"name": "albumin", "label": "Albúmina (g/dL)", "type": "number", "required": False,
                 "help": "Halabi nomograma input"},
                {"name": "creatinine", "label": "Creatinina (mg/dL)", "type": "number", "required": False,
                 "help": "Dose adjustments PARP, taxanos"},
            ],
            "metastatic": [
                {"name": "metastatic_disease_known", "label": "¿Enfermedad metastásica?", "type": "select", "required": True,
                 "options": [("no", "No · M0 confirmado"), ("yes", "Sí · M1"), ("unknown", "Pendiente staging")]},
                {"name": "mets_bone", "label": "Mets óseas", "type": "checkbox", "required": False, "conditional": "metastatic_disease_known == yes"},
                {"name": "mets_visceral", "label": "Mets viscerales", "type": "checkbox", "required": False, "conditional": "metastatic_disease_known == yes"},
                {"name": "mets_nodal_nonregional", "label": "Mets nodales no regionales", "type": "checkbox", "required": False, "conditional": "metastatic_disease_known == yes"},
                {"name": "mets_brain", "label": "Mets cerebrales", "type": "checkbox", "required": False, "conditional": "metastatic_disease_known == yes",
                 "help": "Critical · NEPC signal · MRI cerebral indicada"},
                {"name": "bone_lesion_count", "label": "# lesiones óseas (total)", "type": "number", "required": False,
                 "conditional": "mets_bone",
                 "help": "GAP CHAARTED · ≥4 + apendicular = HV"},
                {"name": "bone_apendicular_present", "label": "Lesiones óseas apendiculares (extra-axial)", "type": "select", "required": False,
                 "conditional": "mets_bone",
                 "options": [("no", "No · solo axial"), ("yes", "Sí · ≥1 apendicular")],
                 "help": "GAP · CHAARTED HV criterion explícito"},
                {"name": "visceral_sites", "label": "Sitios viscerales", "type": "checklist", "required": False,
                 "conditional": "mets_visceral",
                 "options": [("liver", "Hígado (peor pronóstico)"), ("lung", "Pulmón"), ("adrenal", "Adrenal"), ("other", "Otro")]},
                {"name": "metachronous_metastasis", "label": "Patrón metastásico", "type": "select", "required": False,
                 "conditional": "metastatic_disease_known == yes",
                 "options": [("synchronous", "Sincrónico (al dx inicial)"), ("metachronous", "Metacrónico (post-tx local)"), ("unknown", "Indeterminado")]},
                {"name": "oligometastatic_status", "label": "Oligometastático", "type": "select", "required": False,
                 "conditional": "metastatic_disease_known == yes",
                 "options": [("no", "No · enfermedad amplia"), ("yes_low", "Sí · ≤3 lesiones"), ("yes_intermediate", "Sí · 4-5 lesiones")],
                 "help": "Trigger MDT/SBRT (STAMPEDE M1|RT)"},
                {"name": "first_mets_diagnosis_date", "label": "Fecha primera evidencia mets", "type": "date", "required": False,
                 "conditional": "metastatic_disease_known == yes"},
                {"name": "primary_treated", "label": "Tumor primario tratado", "type": "select", "required": False,
                 "conditional": "metastatic_disease_known == yes",
                 "options": [("no", "No · primario in situ"), ("rp", "Sí · RP"), ("rt", "Sí · RT"), ("both", "RP + RT salvage")]},
                {"name": "imaging_method_used", "label": "Imaging que confirmó mets", "type": "select", "required": False,
                 "conditional": "metastatic_disease_known == yes",
                 "options": [("conventional", "Convencional (CT + bone scan)"), ("psma", "PSMA-PET"), ("both", "Convencional + PSMA")]},
                {"name": "bpi_pain_score", "label": "BPI pain worst (0-10)", "type": "number", "required": False,
                 "conditional": "metastatic_disease_known == yes",
                 "help": "GAP · symptomatic vs asymptomatic · trigger Ra-223 / RT paliativa"},
            ],
            "systemic": [
                {"name": "current_adt_context", "label": "Contexto ADT actual", "type": "select", "required": False,
                 "options": [("none", "Ninguno"), ("medical_continuous", "Médico continuo (LHRH-a/antag)"), ("orchiectomy", "Orquidectomía bilateral"), ("intermittent", "Intermitente · off-cycle")]},
                {"name": "adt_start_date", "label": "Fecha inicio ADT", "type": "date", "required": False,
                 "conditional": "current_adt_context != none"},
                {"name": "castrate_testosterone_status", "label": "Testosterona en castración", "type": "select", "required": False,
                 "options": [("unknown", "No verificada"), ("confirmed", "Confirmada <50 ng/dL"), ("not_castrate", "NO castración (≥50 ng/dL)")]},
                {"name": "systemic_progression_context", "label": "Contexto progresión sistémica", "type": "select", "required": False,
                 "options": [("none", "Sin progresión"), ("progression_verify", "Progresión · verificar castración"), ("confirmed_crpc", "CRPC confirmado")]},
                {"name": "progression_pattern", "label": "Patrón de progresión", "type": "select", "required": False,
                 "conditional": "systemic_progression_context != none",
                 "options": [("biochemical", "Bioquímica (PSA solo)"), ("radiographic", "Radiográfica"), ("clinical", "Clínica (sintomática)"), ("mixed", "Mixta")]},
                {"name": "conventional_imaging_status", "label": "Status imaging convencional", "type": "select", "required": False,
                 "options": [("not_restaged", "No re-estadiado"), ("M0", "M0 (sin mets)"), ("M1", "M1 (con mets)")]},
                {"name": "prior_lines_count", "label": "# líneas previas sistémicas", "type": "number", "required": False,
                 "help": "Para sequencing logic (CARD, post-PARP, post-Lu)"},
                {"name": "prior_taxane", "label": "Quimio previa con taxano", "type": "select", "required": False,
                 "options": [("no", "No"), ("docetaxel", "Docetaxel"), ("cabazitaxel", "Cabazitaxel"), ("both", "Doce + cabazi")]},
            ],
            "genomics": [
                {"name": "germline_testing_performed", "label": "Test germinal realizado", "type": "select", "required": True,
                 "options": [("no", "No"), ("yes_panel", "Sí · panel germinal"), ("planned", "Planeado")],
                 "help": "NCCN GENE-1 trigger · familia + Ashkenazi + agresivo"},
                {"name": "germline_pathogenic_variant", "label": "Variante patogénica germinal", "type": "select", "required": False,
                 "conditional": "germline_testing_performed == yes_panel",
                 "options": [("none", "Ninguna"), ("brca1", "BRCA1"), ("brca2", "BRCA2"), ("atm", "ATM"), ("palb2", "PALB2"), ("chek2", "CHEK2"), ("mlh1_msh2", "Lynch (MLH1/MSH2)"), ("other", "Otra HRR/MMR")]},
                {"name": "somatic_testing_performed", "label": "Test somático (tumor/ctDNA)", "type": "select", "required": False,
                 "options": [("no", "No"), ("tumor_tissue", "Tejido tumoral"), ("ctdna_liquid", "ctDNA / biopsia líquida"), ("both", "Ambos")]},
                {"name": "hrr_status", "label": "Estado HRR (homologous recombination)", "type": "select", "required": False,
                 "options": [("not_tested", "No testeado"), ("hrr_negative", "HRR negativo"), ("hrr_positive", "HRR positivo"), ("hrd_high", "HRD score alto (≥42)")]},
                {"name": "msi_mmr_status", "label": "MSI / MMR", "type": "select", "required": False,
                 "options": [("not_tested", "No testeado"), ("stable", "MSS / pMMR estable"), ("msi_high", "MSI-H / dMMR (Lynch / IO eligible)")]},
                {"name": "family_history_cancer", "label": "Historia familiar relevante", "type": "checklist", "required": True,
                 "options": [("none", "Sin historia"), ("prostate_relative", "Próstata familiar 1° grado"), ("breast_ovarian", "Mama/ovario familiar (BRCA hint)"), ("pancreatic", "Páncreas familiar"), ("lynch_spectrum", "Lynch (colon, endometrio)"), ("ashkenazi", "Ascendencia Ashkenazi")],
                 "help": "GAP · trigger NCCN GENE-1"},
                {"name": "ar_v7_tested", "label": "AR-V7 testeado (PROPHECY)", "type": "select", "required": False,
                 "options": [("no", "No"), ("negative", "Negativo"), ("positive", "Positivo · evitar ARPI")]},
            ],
            "performance": [
                {"name": "ecog_score", "label": "ECOG performance status", "type": "select", "required": True,
                 "options": [("0", "0 · totalmente activo"), ("1", "1 · ambulatorio, actividad ligera"), ("2", "2 · ambulatorio, autocuidado"), ("3", "3 · cama >50% día"), ("4", "4 · postrado completo")],
                 "help": "GAP · NCCN required · ECOG ≥3 limita opciones agresivas"},
                {"name": "charlson_score", "label": "Charlson comorbidity score", "type": "number", "required": True,
                 "help": "GAP · NCCN required · 0-2 / 3-4 / ≥5"},
                {"name": "g8_score", "label": "G8 geriatric (si ≥75a)", "type": "number", "required": False,
                 "conditional": "age >= 75",
                 "help": "Screen frailty geriátrico"},
                {"name": "frailty_status", "label": "Frailty clínico", "type": "select", "required": False,
                 "options": [("fit", "Fit"), ("vulnerable", "Vulnerable"), ("frail", "Frail")]},
                {"name": "life_expectancy_estimate", "label": "Expectativa de vida estimada", "type": "select", "required": True,
                 "options": [("more_10y", ">10 años"), ("5_to_10y", "5-10 años"), ("less_5y", "<5 años")],
                 "help": "Define elegibilidad tx local agresivo"},
                {"name": "phq9_score", "label": "PHQ-9 (depresión)", "type": "number", "required": False,
                 "help": "Screen baseline ASCO PCO"},
                {"name": "gad7_score", "label": "GAD-7 (ansiedad)", "type": "number", "required": False},
                {"name": "esas_summary", "label": "ESAS síntomas (suma 0-90)", "type": "number", "required": False,
                 "help": "Edmonton symptom assessment"},
            ],
        },
    }
    # Faubot LXXXI #audit-pre-cortana A1 — merge etapas avanzadas auto-generadas
    # desde pivotal_gate_supporting_fields() (gates 56-85). Esto cierra el GAP
    # crítico donde UI v2 NO capturaba ~50% de fields para gates pivotales nuevos.
    try:
        from prostanet.presentation.v2_advanced_capture_builder import (
            build_advanced_capture_stages,
        )
        adv_stages, adv_fields = build_advanced_capture_stages()
        if adv_stages:
            base["stages"].extend(adv_stages)
            base["fields"].update(adv_fields)
    except (ImportError, Exception):
        # No romper el intake si el builder falla — fields legacy siguen visibles
        pass
    return base


def build_clinical_result_demo_data() -> dict[str, Any]:
    """Mock data para el demo Resultado Clínico (CDE output post-intake).

    Caso m1CRPC + BRCA2+ (continúa el preset del intake `preset_m1crpc_brca`):
    falla a docetaxel + ARPI L3 → PROfound elegible → recomendar olaparib.

    Sigue patrones healthcare-cdss-patterns:
      - Gates con severity 3-tier (hard_block / soft_warning / informational)
      - Decision quality + alternatives ranked
      - Trial eligibility con criteria match
      - Risk scores con missing inputs marcados
      - Signature step REQUIRED al final (sin firma → no se confirma)
    """
    return {
        "identity": {
            "name": "García Hernández, Roberto Antonio",
            "mrn": "MRN-002847",
            "age": 67,
            "ecog": 1,
            "stage": "m1crpc",
            "stage_label": "m1CRPC",
            "diagnosis_date": "2022-03-14",
            "captured_at": "2026-04-26 14:18 CST",
            "captured_by": "Dr. Faudes Bautista · Cédula 12345678",
            "intake_completeness": 89,
        },
        "decision_today": {
            "release": "2026-04-26 LXXVII",
            "headline": "Solicitar PSMA-PET + iniciar PARP (olaparib) por BRCA2+ patogénico",
            "rationale": "Falla a docetaxel + ARPI tras BRCA2 confirmado → PROfound NCCN cat 1",
            "regimen_code": "OLAPARIB_300_BID",
            "regimen_label": "Olaparib 300 mg BID (PROfound)",
            "decision_quality_score": 0.92,
            "decision_quality_label": "Alta calidad",
            "evidence_level": "NCCN PROS-13 cat 1 · EAU 2026 §7.4 strong",
        },
        "alternatives": [
            {"code": "TALAZOPARIB_ENZA", "label": "Talazoparib + Enzalutamida (TALAPRO-2)",
             "rank": 2, "rationale": "Eficacia comparable, perfil tox diferente; TALAPRO-2 BRCA1/2 HR 0.20 OS"},
            {"code": "RUCAPARIB", "label": "Rucaparib 600 mg BID (TRITON3)",
             "rank": 3, "rationale": "Aprobado BRCA1/2; menor exp en BRCA2 vs olaparib"},
            {"code": "LU177_PSMA", "label": "Lu-177 PSMA-617 (VISION)",
             "rank": 4, "rationale": "Si PSMA-PET SUVmax ≥ 20; alternativa o secuencial post-PARP"},
        ],
        "gates_triggered": [
            {"code": "G61", "title": "HRR confirmation HARD_BLOCK · superado",
             "severity": "informational", "class_label": "PARP eligibility gate",
             "reason": "BRCA2 c.5946delT confirmado (Myriad MyChoice) → habilitado para PARP",
             "trial_refs": [
                 {"ref": "PROfound", "type": "trial", "url": "https://clinicaltrials.gov/study/NCT02987543"},
                 {"ref": "33068333", "type": "PMID", "url": "https://pubmed.ncbi.nlm.nih.gov/33068333/"},
             ],
             "evidence_tag": "NCCN PROS-13 cat 1"},
            {"code": "G55", "title": "PSADT 1.8m · kinetics rápidas",
             "severity": "soft_warning", "class_label": "Kinetics anti-misinterpretation",
             "reason": "PSADT actual 1.8m (umbral ≤3m hard prog) → switch línea sistémica",
             "trial_refs": [
                 {"ref": "SPARTAN", "type": "trial", "url": "https://clinicaltrials.gov/study/NCT01946204"},
             ],
             "evidence_tag": "PCWG3 working group"},
            {"code": "G19", "title": "Considerar Cabazitaxel post-Doce/ARPI",
             "severity": "informational", "class_label": "Sequencing decision",
             "reason": "Si PARP no tolerado o no respuesta, cabazitaxel CARD trial logic",
             "trial_refs": [
                 {"ref": "CARD", "type": "trial", "url": "https://clinicaltrials.gov/study/NCT02485691"},
             ],
             "evidence_tag": "CARD NEJM 2019"},
        ],
        "trial_eligibility": [
            {"trial": "PROfound (NCT02987543)", "drug": "Olaparib",
             "criteria_match": 5, "criteria_total": 5, "status": "Eligible",
             "criteria": [
                 ("BRCA1/2/ATM patogénico", True),
                 ("mCRPC progresivo post-ARPI", True),
                 ("ECOG ≤ 2", True),
                 ("Hb ≥ 9 g/dL", True),
                 ("Sin invasión SNC activa", True),
             ]},
            {"trial": "TALAPRO-2 (NCT03395197)", "drug": "Talazoparib + Enzalutamida",
             "criteria_match": 4, "criteria_total": 5, "status": "Eligible · BRCA cohort",
             "criteria": [
                 ("BRCA1/2 patogénico", True),
                 ("ARPI naive en mCRPC", False),  # ya en L3 ARPI
                 ("ECOG ≤ 1", True),
                 ("PSMA-PET no requerido", True),
                 ("Hb ≥ 9 g/dL", True),
             ]},
            {"trial": "VISION (NCT03511664)", "drug": "Lu-177 PSMA-617",
             "criteria_match": 3, "criteria_total": 5, "status": "Pendiente PSMA-PET",
             "criteria": [
                 ("Post-ARPI + post-taxano", True),
                 ("ECOG ≤ 2", True),
                 ("PSMA-PET SUVmax ≥ 20", None),  # pendiente
                 ("Mets medibles RECIST 1.1", True),
                 ("Sin SRE imminent", None),
             ]},
        ],
        "risk_calculators": [
            {"tool": "Halabi mCRPC nomograma", "score": 0.72, "label": "Mortalidad 1 año: 28%",
             "missing_inputs": [], "interpretation": "Riesgo intermedio-alto · monitoreo intensivo"},
            {"tool": "PROfound HR estimado", "score": "0.34", "label": "rPFS HR olaparib vs control",
             "missing_inputs": [], "interpretation": "Beneficio sustancial esperado"},
            {"tool": "CAPRA-S (post-RP histórico)", "score": 7, "label": "Alto riesgo (5y BCR 60%)",
             "missing_inputs": [], "interpretation": "Histórico desde dx 2022"},
        ],
        "next_actions": [
            {"action": "Solicitar PSMA-PET 68Ga", "due": "2026-05-03 (próximos 7 días)",
             "rationale": "Confirmar SUVmax para Lu-177 backup + re-stage", "priority": "high"},
            {"action": "Iniciar olaparib 300 mg BID", "due": "Post-confirmación PSMA-PET",
             "rationale": "Línea 4 con BRCA2+ confirmado", "priority": "high"},
            {"action": "Ajustar anticoagulación (DDI enzalutamida actual)", "due": "Pre-switch",
             "rationale": "Switch a HBPM antes de iniciar olaparib (residual ENZA inducción CYP3A4)", "priority": "medium"},
            {"action": "Counseling familiar genético", "due": "Próxima visita",
             "rationale": "BRCA2+ → testing 1° grado (NCCN GENE-1)", "priority": "medium"},
            {"action": "Re-evaluación en 12 semanas", "due": "2026-07-19",
             "rationale": "PSA + imagen + tox CTCAE", "priority": "scheduled"},
        ],
        "consent": {
            "version_code": "PROSTAMED_CONSENT_v3.2",
            "effective_at": "2026-03-01",
            "scopes": [
                ("Atención clínica primaria", True, True),  # required, default checked
                ("Procesamiento por motor CDE / IA", False, True),
                ("Comparación con cohortes pivotales (anonimizado)", False, True),
                ("Investigación secundaria (revocable)", False, False),
            ],
            "physician_witness": {"name": "Dr. Faudes Bautista", "license": "Cédula 12345678",
                                  "specialty": "Urología-Oncológica"},
        },
    }


def build_longitudinal_capture_demo_data() -> dict[str, Any]:
    """Mock data para captura longitudinal (post-intake, append-only).

    Patrón anti-duplicación: baseline READ-ONLY (de intake), solo se permite
    APPEND nuevas mediciones a series temporales. Smart hints sobre cadencia
    NCCN y datos vencidos.
    """
    return {
        "identity": {
            "name": "García Hernández, Roberto Antonio",
            "mrn": "MRN-002847",
            "age": 67,
            "ecog": 1,
            "stage": "m1crpc",
            "stage_label": "m1CRPC",
            "current_line": 3,
            "current_regimen": "Enzalutamida 160 mg/d",
            "consent_status": "signed_v3.2",
        },
        "baseline_locked": {
            # Datos capturados en intake — NO re-capturable
            "demographics": [
                ("Nombre", "García Hernández, Roberto Antonio"),
                ("Fecha nacimiento", "1958-11-04"),
                ("Sexo", "Masculino"),
                ("Etnia", "Hispano/Latino"),
            ],
            "diagnosis": [
                ("Fecha dx", "2022-03-14"),
                ("Método dx", "Pieza de RP"),
                ("Gleason", "4+5 = 9 (ISUP 5)"),
                ("PSA basal", "12.4 ng/mL"),
                ("cT/cN/cM", "T3a · N1 · M1b"),
                ("PI-RADS index", "5"),
                ("PNI", "Sí"),
            ],
            "histology": [
                ("# cilindros +", "8/12"),
                ("Max core involucro", "75%"),
                ("IDC-P", "No reportado"),
                ("Cribiforme", "No"),
            ],
            "genomics": [
                ("Test germinal", "Sí · panel"),
                ("Variante", "BRCA2 c.5946delT (patogénico)"),
                ("HRR", "Positivo"),
                ("Family hx", "Mama/ovario familiar (BRCA hint)"),
            ],
            "performance_baseline": [
                ("ECOG basal (dx)", "0"),
                ("Charlson basal", "3"),
                ("Expectativa vida", "5-10 años"),
            ],
        },
        "psa_history": [
            {"date": "2022-03-14", "value": 12.4, "context": "Basal Dx", "source": "intake_baseline", "locked": True},
            {"date": "2023-08-20", "value": 0.45, "context": "Post-RP nadir", "source": "longitudinal", "locked": False},
            {"date": "2024-06-01", "value": 8.6, "context": "BCR detectada", "source": "longitudinal", "locked": False},
            {"date": "2024-09-01", "value": 4.8, "context": "L1 ADT+ABI · mes 3", "source": "longitudinal", "locked": False},
            {"date": "2025-04-12", "value": 0.32, "context": "L1 NADIR", "source": "longitudinal", "locked": False},
            {"date": "2025-11-02", "value": 8.5, "context": "L2 docetaxel inicio", "source": "longitudinal", "locked": False},
            {"date": "2026-02-05", "value": 1.6, "context": "L2 NADIR (Doce mes 3)", "source": "longitudinal", "locked": False},
            {"date": "2026-03-12", "value": 5.8, "context": "Progresión post-Doce", "source": "longitudinal", "locked": False},
            {"date": "2026-04-12", "value": 11.8, "context": "L3 enza · semana 2", "source": "longitudinal", "locked": False},
            {"date": "2026-04-26", "value": 12.4, "context": "Hoy · pre-switch PARP", "source": "longitudinal", "locked": False},
        ],
        "lab_panels": [
            {"date": "2026-04-26", "panel": "Bioquímica completa",
             "metrics": [("Hb", "11.8 g/dL"), ("ALP", "245 U/L ↑"), ("LDH", "210 U/L"),
                        ("Albúmina", "3.6 g/dL"), ("Creatinina", "0.92 mg/dL"), ("Testo", "12 ng/dL ✓")]},
            {"date": "2026-02-05", "panel": "Bioquímica completa",
             "metrics": [("Hb", "12.4 g/dL"), ("ALP", "180 U/L"), ("LDH", "188 U/L"),
                        ("Testo", "15 ng/dL ✓")]},
            {"date": "2025-11-02", "panel": "Pre-doce baseline",
             "metrics": [("Hb", "13.1 g/dL"), ("ALP", "320 U/L ↑"), ("LDH", "242 U/L"),
                        ("Testo", "18 ng/dL ✓")]},
        ],
        "imaging_events": [
            {"date": "2026-04-26", "modality": "Pendiente", "type": "PSMA-PET planeada",
             "result": "—", "linked_decision": "Pre-Lu-177 / re-stage"},
            {"date": "2025-09-15", "modality": "CT TAP + bone scan", "type": "Re-stage post-Doce",
             "result": "Progresión ósea + 2 nuevas lesiones L4-L5", "linked_decision": "Switch L3"},
            {"date": "2024-08-20", "modality": "CT TAP + bone scan", "type": "Mets dx",
             "result": "M1b confirmado · 6 lesiones óseas axiales+apendicular", "linked_decision": "Inicio L1 ADT+ABI"},
        ],
        "treatment_lines": [
            {"line": 0, "regimen": "Prostatectomía radical", "start": "2022-04-10", "end": "2022-04-10",
             "status": "Local · histórico", "best_response": "—"},
            {"line": 1, "regimen": "ADT (leuprolide) + Abiraterona 1000mg", "start": "2024-09-01",
             "end": "2025-10-15", "status": "Falla", "best_response": "PSA −96%, DOR 7m"},
            {"line": 2, "regimen": "Docetaxel 75mg/m² × 6 ciclos", "start": "2025-11-02",
             "end": "2026-03-15", "status": "Progresión", "best_response": "PSA −81%, DOR 2m"},
            {"line": 3, "regimen": "Enzalutamida 160 mg/d (actual)", "start": "2026-04-12",
             "end": "—", "status": "Curso · 2 sem", "best_response": "Pre-switch a PARP"},
        ],
        "clinical_events": [
            {"date": "2026-04-26", "type": "Genomic", "label": "BRCA2 c.5946delT confirmado patogénico (Myriad)"},
            {"date": "2026-04-12", "type": "Treatment", "label": "Inicio L3 enzalutamida"},
            {"date": "2026-03-15", "type": "Treatment", "label": "Fin L2 docetaxel ciclo 6"},
            {"date": "2026-03-12", "type": "Progression", "label": "PCWG3 progresión confirmada (PSA + imagen)"},
            {"date": "2025-09-15", "type": "Imaging", "label": "Re-stage CT post-Doce: nuevas lesiones"},
            {"date": "2024-08-20", "type": "State_transition", "label": "Localized → mCSPC (mets dx)"},
            {"date": "2022-03-14", "type": "Diagnosis", "label": "Dx prostatectomía radical · Gleason 9"},
        ],
        "pro_scores": [
            {"date": "2026-04-26", "tool": "BPI worst", "value": 4, "interp": "Dolor leve-moderado"},
            {"date": "2026-04-26", "tool": "ESAS suma", "value": 22, "interp": "Carga sintomática moderada"},
            {"date": "2026-04-26", "tool": "PHQ-9", "value": 8, "interp": "Depresión leve"},
            {"date": "2026-04-26", "tool": "GAD-7", "value": 5, "interp": "Ansiedad mínima"},
            {"date": "2026-02-05", "tool": "BPI worst", "value": 2, "interp": "Dolor leve"},
        ],
        "smart_hints": [
            {"icon": "alert", "severity": "warning",
             "title": "DEXA vencida · 28 meses bajo ADT",
             "msg": "NCCN PROS-G recomienda DEXA basal + cada 24m. Última: nunca capturada.",
             "action": "Solicitar DEXA"},
            {"icon": "calendar", "severity": "info",
             "title": "PSMA-PET planeada para 2026-05-03",
             "msg": "Pendiente programación · pre-decisión Lu-177 vs PARP",
             "action": "Confirmar agenda"},
            {"icon": "trend",  "severity": "critical",
             "title": "PSADT 1.8m · kinetics rápidas",
             "msg": "Calculado con últimos 4 puntos. Switch línea recomendado (G55 + G61 BRCA2).",
             "action": "Ver decisión hoy"},
            {"icon": "info", "severity": "info",
             "title": "Cadencia recomendada PSA mensual",
             "msg": "Para mCRPC + L3 ARPI: PSA cada 30d hasta confirmar respuesta o switch.",
             "action": "Programar"},
        ],
        "what_can_capture": [
            {"key": "psa_new", "label": "Nueva medición PSA", "icon": "drop", "freq": "Mensual",
             "last_capture": "2026-04-26 (hoy)"},
            {"key": "lab_panel", "label": "Panel de labs (Hb · ALP · LDH · Testo)", "icon": "flask",
             "freq": "Cada 30-60 d", "last_capture": "2026-04-26 (hoy)"},
            {"key": "imaging", "label": "Evento imagen (PSMA / CT / bone)", "icon": "scan",
             "freq": "Si nueva imagen", "last_capture": "2025-09-15 (224 d)"},
            {"key": "treatment_change", "label": "Cambio línea / inicio / fin", "icon": "pill",
             "freq": "Si switch", "last_capture": "2026-04-12 (14 d)"},
            {"key": "clinical_event", "label": "Evento clínico (BCR · prog · tox · SRE)", "icon": "alert",
             "freq": "Ad-hoc", "last_capture": "2026-04-26 (hoy)"},
            {"key": "pro_scores", "label": "PRO scores (BPI · ESAS · PHQ-9 · GAD-7)", "icon": "heart",
             "freq": "Cada visita", "last_capture": "2026-04-26 (hoy)"},
            {"key": "dexa", "label": "DEXA / densidad ósea", "icon": "bone",
             "freq": "Cada 24m bajo ADT", "last_capture": "Vencida (28m)"},
            {"key": "ctcae", "label": "Toxicidad CTCAE v5", "icon": "warning",
             "freq": "Cada visita", "last_capture": "2026-04-12 (14 d)"},
        ],
    }


def build_dashboard_demo_data() -> dict[str, Any]:
    """Mock data para Tablero Clínico Ejecutivo."""
    kpis = [
        {"label": "Pacientes activos", "value": "192", "trend": "up", "trend_value": "+8 7d",
         "spark": [180, 182, 184, 186, 188, 190, 192], "variant": "info"},
        {"label": "Alertas críticas", "value": "21", "trend": "up", "trend_value": "+4 24h",
         "spark": [12, 14, 16, 17, 18, 19, 21], "variant": "critical"},
        {"label": "Decisiones pendientes", "value": "11", "trend": "flat", "trend_value": "0 24h",
         "spark": [11, 12, 11, 10, 11, 11, 11], "variant": "warning"},
        {"label": "Trial-eligible", "value": "37", "trend": "up", "trend_value": "+2 7d",
         "spark": [33, 34, 34, 35, 36, 36, 37], "variant": "success"},
        {"label": "Avg time-to-decision", "value": "2.4d", "trend": "down", "trend_value": "-0.3d",
         "spark": [3.2, 3.0, 2.9, 2.8, 2.6, 2.5, 2.4], "variant": "success"},
        {"label": "FAUBOT_RELEASE", "value": "LXXVII", "trend": "info", "trend_value": "2026-04-26",
         "spark": [70, 71, 72, 73, 74, 75, 77], "variant": "info"},
    ]

    cohort_distribution = {
        "labels": ["Localizado", "mCSPC", "m0CRPC", "m1CRPC", "NEPC", "Paliativo"],
        "values": [87, 42, 11, 28, 4, 9],
        "colors": ["#10b981", "#06b6d4", "#f59e0b", "#dc2626", "#a855f7", "#94a3b8"],
    }

    # Heatmap: 12 patients x 12 monthly bins, PSA velocity values
    import random
    random.seed(42)
    heatmap_patients = []
    for i in range(12):
        pid = f"MRN-{2800 + i*7:04d}"
        vals = [round(random.uniform(-0.5, 2.5), 2) for _ in range(12)]
        heatmap_patients.append({"id": pid, "values": vals})
    heatmap = {
        "patients": heatmap_patients,
        "timebins": ["may", "jun", "jul", "ago", "sep", "oct", "nov", "dic", "ene", "feb", "mar", "abr"],
    }

    alert_stream = [
        {"time": "hace 4m", "patient": "MRN-002847", "severity": "critical",
         "msg": "BRCA2 patogénico confirmado — elegible PARP"},
        {"time": "hace 18m", "patient": "MRN-002731", "severity": "critical",
         "msg": "PSADT 1.4m — switch línea recomendado"},
        {"time": "hace 32m", "patient": "MRN-002680", "severity": "warning",
         "msg": "ALP ↑3x — bone-targeted therapy"},
        {"time": "hace 1h", "patient": "MRN-002845", "severity": "critical",
         "msg": "Phoenix BCR post-RT — salvage workup"},
        {"time": "hace 1h", "patient": "MRN-002510", "severity": "warning",
         "msg": "DEXA vencida 28m bajo ADT"},
        {"time": "hace 2h", "patient": "MRN-002433", "severity": "info",
         "msg": "Elegible TALAPRO-2 — discutir con paciente"},
        {"time": "hace 2h", "patient": "MRN-002102", "severity": "warning",
         "msg": "Interacción enzalutamida + warfarina"},
        {"time": "hace 3h", "patient": "MRN-002001", "severity": "critical",
         "msg": "ECOG 3 — limitar opciones agresivas"},
        {"time": "hace 4h", "patient": "MRN-002770", "severity": "info",
         "msg": "PSMA-PET completado — SUV max 32"},
        {"time": "hace 5h", "patient": "MRN-002590", "severity": "warning",
         "msg": "Testosterona 75 ng/dL — verificar adherencia ADT"},
    ]

    decision_quality = {
        "calibration_score": 0.91,
        "concordance_nccn": 0.94,
        "concordance_eau": 0.89,
        "audit_completeness": 0.87,
    }

    research_intelligence = [
        {"label": "Cohort completeness", "value": "87%", "sub": "192/220 esperados"},
        {"label": "Research readiness", "value": "73%", "sub": "Endpoints FDA SaMD"},
        {"label": "Endpoint readiness", "value": "81%", "sub": "rPFS, OS, PFS-2 capturables"},
    ]

    versioning = [
        {"release": "2026-04-26 LXXVII", "diff": "+5 gates RP/RT subspecialty + #67D demo"},
        {"release": "2026-04-26 LXXVI", "diff": "+5 gates genomic critical (HRR HARD_BLOCK)"},
        {"release": "2026-04-26 LXXV", "diff": "+25 tests RP vs RT subspecialty"},
    ]

    return {
        "kpis": kpis,
        "cohort_distribution": cohort_distribution,
        "heatmap": heatmap,
        "alert_stream": alert_stream,
        "decision_quality": decision_quality,
        "research_intelligence": research_intelligence,
        "versioning": versioning,
    }
