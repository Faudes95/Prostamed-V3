"""World-class benchmark and strategic radar for ProstaMed.

The radar is intentionally read-only. It translates the current readiness
stack into a product-strategy surface: where ProstaMed is already strong,
where comparable platforms are stronger, and which next moves matter before
adding more clinical logic.
"""
from __future__ import annotations

from typing import Any, Mapping

from prostanet.shared.utc_time import utc_now_iso


WORLD_CLASS_BENCHMARK_VERSION = "world_class_prostate_platform_benchmark_v1"

BENCHMARK_EVIDENCE_CONTEXT = {
    "as_of": "2026-05-30",
    "source_policy": "Official vendor, registry, standards and regulatory/public documentation; no social-media evidence for scoring.",
    "latest_local_validation": (
        "Multi-stage capture integrity closure on 2026-05-30: diagnostic, localized, BCR/post-local, mCSPC/mHSPC, "
        "m0 CRPC and m1 CRPC wizards suppress schema defaults, keep metastatic composition append-only until user input, "
        "defer taxane/PARP/PSMA-RLT noise behind explicit families, and route longitudinal fields by disease state."
    ),
    "interpretation_boundary": (
        "Benchmarking is strategic product positioning, not a claim of clinical validation, "
        "market share or regulatory equivalence."
    ),
}


BENCHMARK_SOURCES = (
    {
        "key": "flatiron_oncoemr",
        "label": "Flatiron OncoEMR / Flatiron Assist",
        "url": "https://flatiron.com/oncology/oncology-ehr",
        "evidence_note": "Oncology EHR, AJCC content, NCCN Order Templates, precision medicine and point-of-care workflows.",
    },
    {
        "key": "cancerlinq",
        "label": "CancerLinQ",
        "url": "https://www.cancerlinq.org/about",
        "evidence_note": "Longitudinal real-world cancer-care data, quality improvement and research insights.",
    },
    {
        "key": "epic_cosmos",
        "label": "Epic Cosmos",
        "url": "https://cosmos.epic.com/about",
        "evidence_note": "Community EHR real-world data including oncology visits, cancer staging, advanced labs, hospitalizations and social drivers.",
    },
    {
        "key": "tempus_lens",
        "label": "Tempus Lens",
        "url": "https://www.tempus.com/life-sciences/lens/",
        "evidence_note": "Cohort discovery over multimodal de-identified clinical, molecular and imaging data.",
    },
    {
        "key": "artera_tempus",
        "label": "ArteraAI Prostate Test in Tempus",
        "url": "https://www.tempus.com/news/pr/tempus-launches-arteraai-prostate-test-for-metastatic-patients-marking-the-first-prostate-digital-pathology-algorithm-in-the-tempus-ecosystem-available-for-clinical-use/",
        "evidence_note": "2026 mHSPC digital-pathology prognostic test integrated into the Tempus precision-medicine ecosystem.",
    },
    {
        "key": "decipher_prostate",
        "label": "Decipher Prostate",
        "url": "https://decipherbio.com/decipher-prostate/physicians/decipher-prostate-overview/",
        "evidence_note": "Genome-wide transcriptomic classifier supporting prostate risk stratification and decisions.",
    },
    {
        "key": "paige_prostate",
        "label": "Paige Prostate",
        "url": "https://info.paige.ai/prostate",
        "evidence_note": "FDA-authorized AI pathology product for prostate cancer detection.",
    },
    {
        "key": "varian_aria",
        "label": "Varian ARIA",
        "url": "https://www.varian.com/products/software/information-systems/aria-oncology-information-system",
        "evidence_note": "Oncology information system with medical/radiation oncology workflows, HL7/DICOM and chart audit.",
    },
    {
        "key": "elekta_mosaiq",
        "label": "Elekta MOSAIQ / Elekta ONE",
        "url": "https://www.elekta.com/products/oncology-informatics/interoperability/",
        "evidence_note": "Oncology informatics interoperability with HL7 and EHR workflow connectivity.",
    },
    {
        "key": "pcor_anz",
        "label": "PCOR-ANZ",
        "url": "https://prostatecancerregistry.org/clinicians/",
        "evidence_note": "Population-based prostate cancer registry using outcomes and EPIC-26 quality-of-life capture.",
    },
    {
        "key": "hl7_mcode",
        "label": "HL7 mCODE",
        "url": "https://hl7.org/fhir/us/mcode/",
        "evidence_note": "mCODE v4.0.0 STU4 defines core structured oncology data elements for interoperable EHR and research-quality oncology data.",
    },
    {
        "key": "omop_oncology",
        "label": "OMOP Oncology Extension",
        "url": "https://ohdsi.github.io/CommonDataModel/oncology.html",
        "evidence_note": "Oncology extension to OMOP CDM for disease episodes, modifiers and observational research.",
    },
)


ACHIEVEMENT_ROWS = (
    {
        "key": "v2_no_recapture_foundation",
        "label": "Captura V2 sin recaptura innecesaria",
        "proof_surface": "/api/platform-readiness/capture-integrity",
        "why_it_matters": "Evita que APE/PSAD/TR y campos por etapa se pidan dos veces o contaminen decisiones posteriores.",
    },
    {
        "key": "multistage_capture_integrity",
        "label": "Captura multiestadio sin defaults clinicos falsos",
        "proof_surface": "/wizard/localized_initial + /wizard/recurrence_bcr + /wizard/mcspc_high_volume_sync + /wizard/m0_crpc + /wizard/m1_crpc + tests/test_multistage_capture_sequence.py",
        "why_it_matters": "Prueba que PSA, TR, PSAD, metastasis, BCR, castracion, ECOG y toxicidad se piden segun estadio, sin recaptura ni campos fuera de estado.",
    },
    {
        "key": "clinical_fact_ledger",
        "label": "Clinical Fact Ledger como fuente auditable",
        "proof_surface": "/api/patients/<patient_ref>/clinical-fact-ledger/summary",
        "why_it_matters": "Convierte datos repetidos en procedencia reconciliada antes de conectar patologia, genomica o FHIR/OMOP.",
    },
    {
        "key": "profile_v2_treatment_value",
        "label": "Perfil V2 con curso terapeutico, dosis, costo y timelines",
        "proof_surface": "/api/platform-readiness/v2-treatment-value-closure",
        "why_it_matters": "Une tratamiento real, APE, costos, alertas de referencia y trazabilidad en la superficie clinica oficial.",
    },
    {
        "key": "population_value_registry",
        "label": "Registro longitudinal comparativo 12/24/36/52 semanas",
        "proof_surface": "/api/analytics/epidemiology-command-center",
        "why_it_matters": "Empieza a producir evidencia hospitalaria con respuesta, toxicidad, discontinuacion, costo y sesgo basal.",
    },
    {
        "key": "governed_research_freezes",
        "label": "Research packs y snapshots congelables",
        "proof_surface": "/api/analytics/epidemiology-command-center/snapshot-pack",
        "why_it_matters": "Permite convertir cohortes vivas en artefactos reproducibles para auditoria, poster o articulo.",
    },
)


WORLD_CLASS_OPERATING_PRINCIPLES = (
    {
        "key": "verify_before_expand",
        "principle": "Primero cerrar captura, persistencia y UI/API; luego agregar logica clinica.",
        "benefit": "Reduce deuda clinica y evita recomendaciones basadas en datos ambiguos.",
    },
    {
        "key": "no_silent_default_facts",
        "principle": "Ningun valor de ejemplo puede convertirse en hecho clinico por defecto.",
        "benefit": "Protege estadificacion inicial, consentimiento real-world, cohortes y analitica economica contra evidencia fabricada por UI.",
    },
    {
        "key": "specialist_layer_not_generic_ehr",
        "principle": "Ser capa prostate-specific de inteligencia, valor y auditoria sobre EHR/OIS existentes.",
        "benefit": "Compite donde somos unicos sin intentar reemplazar sistemas empresariales maduros.",
    },
    {
        "key": "auditable_every_number",
        "principle": "Cada KPI debe bajar a paciente, hecho, fecha, fuente y metrica.",
        "benefit": "Hace defendible la plataforma ante jefatura, investigacion, compras y revision externa.",
    },
    {
        "key": "no_false_precision",
        "principle": "Costo o evidencia incompleta se etiqueta como parcial/no auditada; no se inventa.",
        "benefit": "Aumenta confianza institucional y evita conclusiones economicas falsas.",
    },
)


BENCHMARK_ROWS = (
    {
        "platform_class": "Oncology EHR / CDS",
        "examples": ("Flatiron OncoEMR", "Flatiron Assist", "Epic Beacon-like workflows"),
        "market_strength": "Execution-grade oncology workflow: orders, templates, compliance, portal, reporting and integrations.",
        "prostanet_strength": "Deeper prostate-specific longitudinal reasoning, DECISION HOY, Ledger, APE tower, value/cost and research freeze loops.",
        "gap_to_world_class": "Certified order/CPOE layer, patient portal, payer/registry interfaces and enterprise support.",
        "strategic_response": "Stay as specialist intelligence/audit layer first; integrate with EHR/OIS before attempting certified order execution.",
        "priority": "medium",
    },
    {
        "platform_class": "Real-world oncology data network",
        "examples": ("CancerLinQ", "Epic Cosmos", "quality registries"),
        "market_strength": "Multicenter/community EHR data aggregation, curation, quality measures, patient similarity, trial matching and research insights.",
        "prostanet_strength": "Real-time capture and closure at the uro-oncology visit, not only retrospective aggregation.",
        "gap_to_world_class": "Multisite governance, external benchmarking, institutional consent pack and quality-measure certification.",
        "strategic_response": "Use NAS pilot, no-PHI freezes and huddle closure to build a defensible local registry before multicenter expansion.",
        "priority": "high",
    },
    {
        "platform_class": "Multimodal research/cohort builder",
        "examples": ("Tempus Lens", "Tempus One"),
        "market_strength": "Self-service cohorts over large de-identified clinical, molecular, imaging and document datasets.",
        "prostanet_strength": "Clinician-facing prostate pathway, cohort traceability, metric provenance and local reproducible research packs.",
        "gap_to_world_class": "Molecular/pathology/imaging ingestion at scale, natural-language document mining and external data lake connectors.",
        "strategic_response": "After Ledger closure, add LIS/pathology/genomics connectors and freeze-bound cohort builder filters.",
        "priority": "high",
    },
    {
        "platform_class": "Prostate genomic / digital-pathology decision products",
        "examples": ("Decipher Prostate", "ArteraAI", "Paige Prostate"),
        "market_strength": "Regulated or clinically validated prostate-specific assays and AI outputs tied to prognosis or diagnosis.",
        "prostanet_strength": "Can convert external scores into treatment lane, follow-up, cost, adherence and outcome monitoring.",
        "gap_to_world_class": "No live assay/pathology ingestion, no versioned external report parser and no regulatory claims.",
        "strategic_response": "Do not recreate these models blindly; ingest, version, explain and audit their impact inside the clinical workflow.",
        "priority": "high",
    },
    {
        "platform_class": "Radiation / oncology information system",
        "examples": ("Varian ARIA", "Elekta MOSAIQ"),
        "market_strength": "HL7/DICOM, scheduling, RT chart audit, prescription workflows, QA and radiation oncology operations.",
        "prostanet_strength": "Prostate-specific salvage/intensification intelligence, longitudinal APE and economic/outcomes overlay.",
        "gap_to_world_class": "DICOM-RT, OIS interoperability, RT course import, scheduling and treatment-delivery audit.",
        "strategic_response": "Position ProstaMed as prostate intelligence above OIS/EHR; add RT import/readiness before replacing any workflow.",
        "priority": "medium",
    },
    {
        "platform_class": "Prostate outcomes registry",
        "examples": ("PCOR-ANZ", "institutional registries"),
        "market_strength": "Minimum datasets, outcomes, treatment variation, PROs, longitudinal reporting and external benchmark culture.",
        "prostanet_strength": "Captures decision context, cost, doses, APE response and gaps from the start of care.",
        "gap_to_world_class": "External benchmark network, formal registry dictionary, patient-reported workflows and survival completeness at scale.",
        "strategic_response": "Turn the NAS pilot into the first institutional prostate outcomes registry with PRO/EPIC-26 and survival closure.",
        "priority": "high",
    },
    {
        "platform_class": "Interoperability standard / observational model",
        "examples": ("HL7 mCODE", "OMOP Oncology"),
        "market_strength": "Shared language for oncology facts, disease episodes, treatments, outcomes and research reproducibility.",
        "prostanet_strength": "Canonical Ledger, FHIR/OMOP readiness map, no-PHI export contract and reproducible research packs.",
        "gap_to_world_class": "Actual FHIR resources, OMOP ETL, vocabulary validation, data-quality dashboard and external conformance testing.",
        "strategic_response": "Use the Ledger as source of truth; build validated FHIR/OMOP projections only after persistence gates stay green.",
        "priority": "high",
    },
)


CAPABILITY_WEIGHTS = {
    "clinical_reliability": 1.2,
    "prostate_specific_depth": 1.2,
    "longitudinal_outcomes": 1.1,
    "economic_value": 1.0,
    "research_reproducibility": 1.0,
    "interoperability": 1.0,
    "multimodal_ingestion": 0.9,
    "enterprise_deployment": 0.9,
    "external_validation": 0.9,
}


BASE_CAPABILITY_SCORES = {
    "clinical_reliability": 4,
    "prostate_specific_depth": 5,
    "longitudinal_outcomes": 4,
    "economic_value": 4,
    "research_reproducibility": 4,
    "interoperability": 3,
    "multimodal_ingestion": 2,
    "enterprise_deployment": 2,
    "external_validation": 1,
}


PEER_TARGET_SCORES = {
    "clinical_reliability": 4,
    "prostate_specific_depth": 3,
    "longitudinal_outcomes": 4,
    "economic_value": 3,
    "research_reproducibility": 5,
    "interoperability": 5,
    "multimodal_ingestion": 5,
    "enterprise_deployment": 5,
    "external_validation": 5,
}


CAPABILITY_LABELS = {
    "clinical_reliability": "Confiabilidad clinica UI/backend",
    "prostate_specific_depth": "Profundidad prostate-specific",
    "longitudinal_outcomes": "Outcomes longitudinales",
    "economic_value": "Costo/valor institucional",
    "research_reproducibility": "Investigacion reproducible",
    "interoperability": "Interoperabilidad FHIR/OMOP",
    "multimodal_ingestion": "Ingestion multimodal",
    "enterprise_deployment": "Despliegue/compliance empresarial",
    "external_validation": "Validacion externa/multicentro",
}


STRATEGIC_PHASES = (
    {
        "phase": 1,
        "name": "Cierre de confiabilidad V2 y captura inicial",
        "status": "active_gate",
        "why": "Sin verdad clinica canonica ni captura inicial libre de defaults falsos, todo modulo nuevo aumenta recaptura y contradiccion.",
        "benefit": "Datos persistentes, reutilizables, auditables y alineados entre backend y UI.",
        "exit_evidence": ("Ledger release gate verde", "Persistence matrix V2 verde", "Initial staging capture integrity verde", "Reconciliation queue operable"),
    },
    {
        "phase": 2,
        "name": "Piloto prospectivo NAS",
        "status": "next_operational_layer",
        "why": "La plataforma necesita demostrar adopcion real, completitud y gobierno local antes de escalar.",
        "benefit": "Primer registro hospitalario vivo con evidencia para jefatura, tesis y reportes institucionales.",
        "exit_evidence": ("NAS evidence vault firmado", "Adopcion prospectiva semanal", "Huddle de brechas cerrado"),
    },
    {
        "phase": 3,
        "name": "Registro longitudinal de outcomes/valor",
        "status": "in_progress",
        "why": "La ventaja comercial aparece cuando ProstaMed produce evidencia hospitalaria, no solo recomendaciones.",
        "benefit": "PSA50/90, ECOG, toxicidad, discontinuacion, hospitalizacion, eventos oseos, supervivencia y costo-respuesta.",
        "exit_evidence": ("Cohortes 12/24/36/52 semanas", "Drill-down paciente-a-metrica", "Costo por respuesta"),
    },
    {
        "phase": 4,
        "name": "Interoperabilidad y multimodalidad",
        "status": "gated_after_ledger",
        "why": "Genomica, patologia digital, laboratorio e imagen deben entrar versionados y reconciliables.",
        "benefit": "Conectores FHIR/OMOP/LIS/pathology/genomics sin romper la verdad clinica interna.",
        "exit_evidence": ("mCODE resources validables", "OMOP ETL inicial", "Parser de reportes genomicos/pathology versionado"),
    },
    {
        "phase": 5,
        "name": "Research OS y evidencia viva",
        "status": "build_on_freezes",
        "why": "El valor diferencial es automatizar preguntas, cohortes, metodos, freezes y manuscritos auditables.",
        "benefit": "Lineas de investigacion reproducibles, posters/articulos y data rooms no-PHI.",
        "exit_evidence": ("Freeze aprobado", "Notebook reproducible", "Resumen metodologico automatico"),
    },
    {
        "phase": 6,
        "name": "Producto comercial defendible",
        "status": "requires_externalization",
        "why": "Para monetizar se necesita seguridad, soporte, despliegue, compliance, validacion externa y ventas institucionales.",
        "benefit": "Plataforma vendible como capa prostate-specific de inteligencia clinica, valor y auditoria.",
        "exit_evidence": ("Hardening seguridad", "Piloto multicentro", "Casos de valor documentados", "Soporte/SLAs"),
    },
)


def _status_ok(value: str | None) -> bool:
    return str(value or "").strip().lower() in {
        "ready_for_next_layer",
        "ready_for_initial_interop",
        "ready_for_local_deidentified_export",
        "ready_to_freeze_or_download",
        "ready",
        "pass",
    }


def _derive_capability_scores(
    *,
    readiness_audit: Mapping[str, Any] | None = None,
    ledger_release_gate: Mapping[str, Any] | None = None,
    ledger_persistence_matrix: Mapping[str, Any] | None = None,
    interoperability_map: Mapping[str, Any] | None = None,
    deidentified_export_contract: Mapping[str, Any] | None = None,
    research_pack_materializer: Mapping[str, Any] | None = None,
    research_pack_freeze_library: Mapping[str, Any] | None = None,
    prospective_pilot_governance: Mapping[str, Any] | None = None,
    v2_treatment_value_closure: Mapping[str, Any] | None = None,
    epidemiology_command_center: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    scores = dict(BASE_CAPABILITY_SCORES)
    readiness_summary = dict((readiness_audit or {}).get("summary") or {})
    ledger_summary = dict((ledger_release_gate or {}).get("summary") or {})
    flow_summary = dict((ledger_persistence_matrix or {}).get("summary") or {})
    interop_summary = dict((interoperability_map or {}).get("summary") or {})
    export_summary = dict((deidentified_export_contract or {}).get("summary") or {})
    pack_summary = dict((research_pack_materializer or {}).get("summary") or {})
    freeze_summary = dict((research_pack_freeze_library or {}).get("summary") or {})
    pilot_summary = dict((prospective_pilot_governance or {}).get("summary") or {})
    treatment_value_summary = dict((v2_treatment_value_closure or {}).get("summary") or {})
    epidemiology = dict(epidemiology_command_center or {})

    if (
        _status_ok(readiness_summary.get("readiness_status"))
        and _status_ok(ledger_summary.get("release_gate_status"))
        and _status_ok(flow_summary.get("matrix_status"))
    ):
        scores["clinical_reliability"] = 5
    if _status_ok(interop_summary.get("interoperability_status")) and int(interop_summary.get("critical_block_count") or 0) == 0:
        scores["interoperability"] = 4
    if _status_ok(export_summary.get("export_contract_status")) and _status_ok(pack_summary.get("materializer_status")):
        scores["research_reproducibility"] = 5
    if int(freeze_summary.get("freeze_count") or 0) > 0 and int(freeze_summary.get("quality_block_count") or 0) == 0:
        scores["research_reproducibility"] = 5
    if str(pilot_summary.get("pilot_status") or "").startswith("ready_for_internal"):
        scores["enterprise_deployment"] = max(scores["enterprise_deployment"], 3)
    if treatment_value_summary.get("v2_treatment_value_closure_status") == "v2_treatment_value_closure_ready":
        scores["economic_value"] = 5
    if (
        epidemiology.get("version") == "epidemiology_command_center_v2"
        and epidemiology.get("kpi_id") == "grand_epidemiology_dashboard_v2"
    ):
        scores["longitudinal_outcomes"] = 5
        if (epidemiology.get("metric_provenance") or {}).get("version") == "metric_provenance_binding_v1":
            scores["research_reproducibility"] = max(scores["research_reproducibility"], 5)
    return {key: max(0, min(5, int(value))) for key, value in scores.items()}


def _capability_rows(scores: Mapping[str, int]) -> list[dict[str, Any]]:
    rows = []
    for key, score in scores.items():
        peer_target = int(PEER_TARGET_SCORES.get(key, 5))
        gap = max(0, peer_target - int(score or 0))
        rows.append({
            "key": key,
            "label": CAPABILITY_LABELS.get(key, key),
            "prostanet_score": int(score or 0),
            "world_class_target": peer_target,
            "gap_score": gap,
            "status": "strength" if gap == 0 else "opportunity" if gap <= 1 else "strategic_gap",
            "weight": CAPABILITY_WEIGHTS.get(key, 1.0),
        })
    rows.sort(key=lambda row: (row["gap_score"] * row["weight"], row["world_class_target"]), reverse=True)
    return rows


def build_world_class_benchmark_radar(
    *,
    readiness_audit: Mapping[str, Any] | None = None,
    ledger_release_gate: Mapping[str, Any] | None = None,
    ledger_persistence_matrix: Mapping[str, Any] | None = None,
    interoperability_map: Mapping[str, Any] | None = None,
    deidentified_export_contract: Mapping[str, Any] | None = None,
    research_pack_materializer: Mapping[str, Any] | None = None,
    research_pack_freeze_library: Mapping[str, Any] | None = None,
    prospective_pilot_governance: Mapping[str, Any] | None = None,
    v2_treatment_value_closure: Mapping[str, Any] | None = None,
    epidemiology_command_center: Mapping[str, Any] | None = None,
    scope: str = "full",
) -> dict[str, Any]:
    """Build a strategic benchmark bundle from current platform evidence."""
    scope_key = "summary" if str(scope or "").strip().lower() == "summary" else "full"
    has_readiness_evidence = any(
        bool(item)
        for item in (
            readiness_audit,
            ledger_release_gate,
            ledger_persistence_matrix,
            interoperability_map,
            deidentified_export_contract,
            research_pack_materializer,
            research_pack_freeze_library,
            prospective_pilot_governance,
            v2_treatment_value_closure,
            epidemiology_command_center,
        )
    )
    scores = _derive_capability_scores(
        readiness_audit=readiness_audit,
        ledger_release_gate=ledger_release_gate,
        ledger_persistence_matrix=ledger_persistence_matrix,
        interoperability_map=interoperability_map,
        deidentified_export_contract=deidentified_export_contract,
        research_pack_materializer=research_pack_materializer,
        research_pack_freeze_library=research_pack_freeze_library,
        prospective_pilot_governance=prospective_pilot_governance,
        v2_treatment_value_closure=v2_treatment_value_closure,
        epidemiology_command_center=epidemiology_command_center,
    )
    capability_rows = _capability_rows(scores)
    strengths = [row for row in capability_rows if row["status"] == "strength"]
    opportunities = [row for row in capability_rows if row["status"] != "strength"]
    weighted_total = sum(CAPABILITY_WEIGHTS.get(key, 1.0) * 5 for key in scores)
    weighted_score = sum(CAPABILITY_WEIGHTS.get(key, 1.0) * score for key, score in scores.items())
    readiness_score = round((weighted_score / weighted_total) * 100, 1) if weighted_total else 0
    top_gap = opportunities[0] if opportunities else {}
    payload = {
        "version": WORLD_CLASS_BENCHMARK_VERSION,
        "generated_at": utc_now_iso(),
        "scope": scope_key,
        "summary": {
            "world_class_readiness_score": readiness_score,
            "strength_count": len(strengths),
            "opportunity_count": len(opportunities),
            "benchmark_class_count": len(BENCHMARK_ROWS),
            "source_count": len(BENCHMARK_SOURCES),
            "achievement_count": len(ACHIEVEMENT_ROWS),
            "top_gap_key": top_gap.get("key") or "",
            "top_gap_label": top_gap.get("label") or "",
            "recommended_next_move": _recommended_next_move(top_gap.get("key") or ""),
            "strategic_position": "ProstaMed debe ser la capa prostate-specific de inteligencia clinica, calidad de dato, valor y research OS sobre EHR/OIS, no un EHR generico.",
            "direction_of_travel": (
                "De recomendador clinico modular hacia learning-health-system prostate-specific: "
                "captura confiable, Ledger, perfil V2, valor economico, cohortes, research OS e interoperabilidad."
            ),
        },
        "evidence_context": dict(BENCHMARK_EVIDENCE_CONTEXT),
        "achievements": list(ACHIEVEMENT_ROWS),
        "operating_principles": list(WORLD_CLASS_OPERATING_PRINCIPLES),
        "capability_radar": capability_rows,
        "strengths": [
            {
                "key": row["key"],
                "label": row["label"],
                "score": row["prostanet_score"],
                "why_it_matters": "Diferenciador defendible frente a plataformas genericas si se mantiene probado en V2.",
            }
            for row in strengths
        ],
        "opportunities": [
            {
                "key": row["key"],
                "label": row["label"],
                "gap_score": row["gap_score"],
                "next_action": _opportunity_action(row["key"]),
            }
            for row in opportunities
        ],
        "benchmark_matrix": list(BENCHMARK_ROWS),
        "strategic_phases": list(STRATEGIC_PHASES),
        "sources": list(BENCHMARK_SOURCES),
        "ui_contract": {
            "read_only": True,
            "benchmarking_surface": True,
            "uses_current_readiness_evidence": has_readiness_evidence,
            "uses_v2_treatment_value_evidence": bool(v2_treatment_value_closure),
            "uses_epidemiology_command_center_evidence": bool(epidemiology_command_center),
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
            "external_transfer_performed": False,
        },
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
    }
    if scope_key == "summary":
        payload.pop("benchmark_matrix", None)
        payload.pop("strategic_phases", None)
        payload.pop("sources", None)
        payload.pop("achievements", None)
        payload.pop("operating_principles", None)
    return payload


def _recommended_next_move(top_gap_key: str) -> str:
    if top_gap_key == "external_validation":
        return "Convertir el primer paquete audit-ready en revision externa controlada antes de reclamar superioridad clinica."
    if top_gap_key == "multimodal_ingestion":
        return "Disenar conectores LIS/patologia/genomica como ingesta versionada sobre Ledger, sin crear datos paralelos."
    if top_gap_key == "enterprise_deployment":
        return "Cerrar NAS evidence vault, roles, consentimiento, backup/restore y bitacora operativa para piloto institucional."
    if top_gap_key == "interoperability":
        return "Generar proyecciones FHIR/mCODE y OMOP desde facts Ledger ya reconciliados.";
    return "Mantener V2 verde y avanzar solo con incrementos que mejoren trazabilidad paciente-a-metrica."


def _opportunity_action(key: str) -> str:
    return {
        "multimodal_ingestion": "Disenar preflight LIS/pathology/genomics con versionado y reconciliacion Ledger antes de ingesta real.",
        "enterprise_deployment": "Cerrar evidence vault NAS, backup/restore drill, roles, consentimiento y bitacora operacional.",
        "external_validation": "Preparar primer paquete audit_ready y protocolo multicentro con variables minimas y no-PHI freeze.",
        "interoperability": "Construir proyeccion FHIR/mCODE y OMOP ETL sobre facts Ledger ya verdes.",
        "longitudinal_outcomes": "Completar supervivencia, discontinuacion, toxicidad G3+, hospitalizacion y eventos oseos 12/24/52 semanas.",
        "economic_value": "Ampliar catalogo costeado trazable mas alla de ARPI/docetaxel cuando exista fuente institucional.",
    }.get(key, "Mantener gate V2 verde y convertir brecha en worklist operativa.")
