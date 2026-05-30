"""External validation readiness worklist for ProstaMed.

This read model turns the top world-class benchmark gap, external/multicenter
validation, into an operational queue. It does not validate a claim by itself;
it shows exactly which internal-pilot, no-PHI, governance and reproducibility
items must be closed before asking another service, hospital or registry to
review ProstaMed data.
"""
from __future__ import annotations

import csv
import io
import json
import re
from typing import Any, Mapping

from prostanet.domains.platform_readiness.deidentified_export_contract import (
    build_deidentified_export_contract,
)
from prostanet.domains.platform_readiness.interoperability_map import build_interoperability_map
from prostanet.domains.platform_readiness.nas_pilot_evidence_vault import (
    build_nas_pilot_evidence_vault,
)
from prostanet.domains.platform_readiness.pilot_adoption_command_center import (
    build_pilot_adoption_command_center,
)
from prostanet.domains.platform_readiness.prospective_pilot_governance import (
    build_prospective_pilot_governance_pack,
)
from prostanet.domains.platform_readiness.real_world_sample_maturity import (
    build_real_world_sample_maturity_gate,
)
from prostanet.domains.platform_readiness.research_pack_governance import (
    build_research_pack_freeze_library,
)
from prostanet.domains.platform_readiness.research_pack_materializer import (
    build_research_pack_materializer,
)
from prostanet.domains.platform_readiness.world_class_benchmark import (
    build_world_class_benchmark_radar,
)
from prostanet.shared.utc_time import utc_now_iso


EXTERNAL_VALIDATION_WORKLIST_VERSION = "external_validation_readiness_worklist_v1"

DIRECT_IDENTIFIER_KEYS = {
    "nss",
    "patient_id",
    "patient_ref",
    "patient_name",
    "full_name",
    "dob",
    "date_of_birth",
    "profile_url",
    "local_patient_id",
}


def build_external_validation_worklist(
    *,
    registry: Any | None = None,
    registered_rules: Any | None = None,
    scope: str = "summary",
    limit: int = 100,
    world_class_benchmark: Mapping[str, Any] | None = None,
    prospective_pilot_governance: Mapping[str, Any] | None = None,
    nas_pilot_evidence_vault: Mapping[str, Any] | None = None,
    pilot_adoption_command_center: Mapping[str, Any] | None = None,
    prospective_gap_closure_huddle: Mapping[str, Any] | None = None,
    ape_longitudinal_completion_sprint: Mapping[str, Any] | None = None,
    deidentified_export_contract: Mapping[str, Any] | None = None,
    research_pack_materializer: Mapping[str, Any] | None = None,
    research_pack_freeze_library: Mapping[str, Any] | None = None,
    interoperability_map: Mapping[str, Any] | None = None,
    real_world_sample_maturity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the external validation queue without mutating platform state."""
    scope_key = "summary" if str(scope or "").strip().lower() == "summary" else "full"
    safe_limit = max(1, min(int(limit or 100), 500))
    registered_rule_list = list(registered_rules or [])

    interop = dict(interoperability_map or build_interoperability_map(scope="summary", field_limit=240))
    export_contract = dict(
        deidentified_export_contract
        or build_deidentified_export_contract(scope="summary", limit=safe_limit)
    )
    materializer = dict(
        research_pack_materializer
        or build_research_pack_materializer(scope="summary", limit=safe_limit)
    )
    freeze_library = dict(
        research_pack_freeze_library
        or build_research_pack_freeze_library(
            limit=25,
            include_payload=False,
            include_current_preview=False,
        )
    )
    nas_vault = dict(
        nas_pilot_evidence_vault
        or build_nas_pilot_evidence_vault(scope="summary", limit=safe_limit)
    )
    pilot = dict(
        prospective_pilot_governance
        or build_prospective_pilot_governance_pack(
            registry,
            registered_rules=registered_rule_list,
            scope="summary",
            limit=safe_limit,
            interoperability_map=interop,
            deidentified_export_contract=export_contract,
            research_pack_materializer=materializer,
            research_pack_freeze_library=freeze_library,
            nas_pilot_evidence_vault=nas_vault,
        )
    )
    adoption = dict(
        pilot_adoption_command_center
        or build_pilot_adoption_command_center(
            scope="summary",
            limit=safe_limit,
            nas_pilot_evidence_vault=nas_vault,
        )
    )
    huddle = dict(prospective_gap_closure_huddle or _derive_huddle_summary_from_adoption(adoption))
    ape_sprint = dict(ape_longitudinal_completion_sprint or _derive_ape_summary_from_adoption(adoption, huddle))
    real_sample = dict(
        real_world_sample_maturity
        or build_real_world_sample_maturity_gate(
            scope="summary",
            limit=safe_limit,
            registry=registry,
            registered_rules=registered_rule_list,
            pilot_adoption_command_center=adoption,
            nas_pilot_evidence_vault=nas_vault,
            prospective_pilot_governance=pilot,
        )
    )
    benchmark = dict(world_class_benchmark or build_world_class_benchmark_radar(scope="summary"))

    gate_by_key = {
        str(gate.get("gate_key")): dict(gate)
        for gate in (pilot.get("gate_matrix") or [])
        if gate.get("gate_key")
    }
    items = _build_worklist_items(
        gate_by_key=gate_by_key,
        benchmark=benchmark,
        pilot=pilot,
        nas_vault=nas_vault,
        adoption=adoption,
        huddle=huddle,
        ape_sprint=ape_sprint,
        real_sample=real_sample,
        interop=interop,
        export_contract=export_contract,
        materializer=materializer,
        freeze_library=freeze_library,
    )
    ordered = sorted(
        items,
        key=lambda item: (
            _priority_rank(item.get("priority")),
            _status_rank(item.get("status")),
            item.get("target_level") or "",
            item.get("key") or "",
        ),
    )
    summary = _build_summary(ordered, benchmark, pilot, adoption, nas_vault)
    payload: dict[str, Any] = {
        "available": True,
        "source": "prostanet_external_validation_readiness_worklist",
        "version": EXTERNAL_VALIDATION_WORKLIST_VERSION,
        "computed_at": utc_now_iso(),
        "scope": scope_key,
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "deidentified": True,
        "external_validation_claim_made": False,
        "summary": summary,
        "worklist_preview": ordered[: min(8, safe_limit)],
        "evidence_bundle_manifest": _build_evidence_bundle_manifest(pilot, freeze_library),
        "next_validation_packet": _build_next_validation_packet(summary),
        "ui_contract": {
            "surface": "platform_readiness_v2",
            "read_only": True,
            "uses_patient_identifiers": False,
            "opens_source_routes": True,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
            "external_transfer_performed": False,
        },
    }
    if scope_key == "full":
        payload.update(
            {
                "worklist": ordered[:safe_limit],
                "readiness_lanes": _build_readiness_lanes(ordered),
                "partner_site_packet_requirements": _build_partner_site_packet_requirements(),
                "external_protocol_outline": _build_external_protocol_outline(summary),
                "no_phi_scan": _scan_for_phi(
                    {
                        "summary": summary,
                        "worklist": ordered[:safe_limit],
                        "evidence_bundle_manifest": payload["evidence_bundle_manifest"],
                        "next_validation_packet": payload["next_validation_packet"],
                    }
                ),
            }
        )
    return payload


def build_external_validation_worklist_csv_bytes(
    worklist: Mapping[str, Any] | None = None,
) -> bytes:
    """Return a no-PHI CSV representation of the external validation queue."""
    payload = dict(worklist or build_external_validation_worklist(scope="full", limit=500))
    rows = payload.get("worklist") or payload.get("worklist_preview") or []
    output = io.StringIO()
    fieldnames = [
        "key",
        "title",
        "status",
        "priority",
        "target_level",
        "owner",
        "blocking_for_multicenter",
        "evidence",
        "action",
        "route",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for item in rows:
        writer.writerow({name: item.get(name, "") for name in fieldnames})
    return output.getvalue().encode("utf-8")


def _build_worklist_items(
    *,
    gate_by_key: Mapping[str, Mapping[str, Any]],
    benchmark: Mapping[str, Any],
    pilot: Mapping[str, Any],
    nas_vault: Mapping[str, Any],
    adoption: Mapping[str, Any],
    huddle: Mapping[str, Any],
    ape_sprint: Mapping[str, Any],
    real_sample: Mapping[str, Any],
    interop: Mapping[str, Any],
    export_contract: Mapping[str, Any],
    materializer: Mapping[str, Any],
    freeze_library: Mapping[str, Any],
) -> list[dict[str, Any]]:
    pilot_summary = pilot.get("summary") or {}
    nas_summary = nas_vault.get("summary") or {}
    adoption_summary = adoption.get("summary") or {}
    huddle_summary = huddle.get("summary") or {}
    ape_summary = ape_sprint.get("summary") or {}
    real_sample_summary = real_sample.get("summary") or {}
    interop_summary = interop.get("summary") or {}
    export_summary = export_contract.get("summary") or {}
    pack_summary = materializer.get("summary") or {}
    freeze_summary = freeze_library.get("summary") or {}
    benchmark_summary = benchmark.get("summary") or {}

    items = [
        _from_gates(
            key="clinical_fact_ledger_v2_flow",
            title="Cerrar Ledger y persistencia V2 antes de validacion externa",
            owner="clinical_fact_steward",
            target_level="internal_pilot",
            priority="critical",
            gates=[
                gate_by_key.get("clinical_fact_ledger"),
                gate_by_key.get("v2_persistence_matrix"),
            ],
            evidence=(
                f"pilot_status={pilot_summary.get('pilot_status', 'unknown')}; "
                f"pilot_block_count={pilot_summary.get('pilot_block_count', 0)}"
            ),
            why="La validacion externa no es defendible si UI y backend aun pueden contradecirse.",
            action="Cerrar cualquier bloque de Ledger/persistencia V2 y repetir readiness antes de invitar revisores externos.",
            route="/platform-readiness#main-content",
            blocking_for_multicenter=True,
        ),
        _from_gates(
            key="no_recapture_alias_contract",
            title="Congelar contrato anti-recaptura y aliases canonicos",
            owner="clinical_fact_steward",
            target_level="internal_pilot",
            priority="high",
            gates=[gate_by_key.get("no_recapture_contract")],
            evidence="El mismo dato debe alimentar intake, wizard, perfil V2, decision, cohortes y exports.",
            why="Un sitio externo no debe capturar APE, estadio, patologia o tratamiento dos veces.",
            action="Mantener alias nuevos dentro del Ledger antes de agregar campos o conectores.",
            route="/api/platform-readiness/ledger-release-gate?scope=full",
            blocking_for_multicenter=True,
        ),
        _item(
            key="no_phi_research_pack",
            title="Paquete no-PHI audit-ready para revision externa",
            owner="privacy_data_steward",
            target_level="external_review",
            priority="critical" if _has_phi_or_export_block(export_summary, pack_summary) else "high",
            status=_status_for_export(export_summary, pack_summary, freeze_summary),
            evidence=(
                f"identifiers={export_summary.get('direct_identifier_key_count', 0)}; "
                f"exact_phi={export_summary.get('exact_phi_hit_count', 0)}; "
                f"freezes={freeze_summary.get('freeze_count', 0)}; "
                f"download_ready={freeze_summary.get('download_ready_count', 0)}"
            ),
            why="El primer intercambio con un revisor externo debe ser desidentificado, reproducible y trazable.",
            action="Generar o verificar un freeze audit_ready con diccionario, manifest, hashes y scan PHI en cero.",
            route="/api/platform-readiness/research-pack-materializer/freezes",
            blocking_for_multicenter=True,
        ),
        _item(
            key="mcode_omop_dictionary",
            title="Diccionario minimo mCODE/OMOP listo para comparacion externa",
            owner="interoperability_owner",
            target_level="external_review",
            priority="high",
            status=(
                "block" if int(interop_summary.get("critical_block_count") or 0) else
                "pass" if _truthy(interop_summary.get("next_layer_allowed")) else
                "watch"
            ),
            evidence=(
                f"critical_ready={interop_summary.get('critical_ready_count', 0)}/"
                f"{interop_summary.get('critical_fact_count', 0)}; "
                f"overall={interop_summary.get('overall_mapping_coverage_pct', 0)}%"
            ),
            why="La comparacion externa exige semantica compartida, aunque el primer pack aun no sea FHIR/OMOP completo.",
            action="Mantener los facts criticos en 100% y priorizar los partial mappings antes de FHIR/OMOP real.",
            route="/api/platform-readiness/interoperability-map?scope=full",
            blocking_for_multicenter=True,
        ),
        _item(
            key="prospective_capture_completeness",
            title="Completitud prospectiva suficiente para cohorte defendible",
            owner="platform_quality_owner",
            target_level="internal_pilot",
            priority="high",
            status=_status_for_capture(adoption_summary),
            evidence=(
                f"registry_ready={adoption_summary.get('registry_ready_pct', 0)}%; "
                f"patients={adoption_summary.get('patient_count', 0)}; "
                f"real={adoption_summary.get('real_patient_count', 0)}; "
                f"high_priority_gaps={adoption_summary.get('high_priority_gap_count', 0)}"
            ),
            why="Antes de comparar resultados necesitamos saber si los pacientes visibles estan completos.",
            action="Usar la torre de adopcion y el huddle semanal hasta lograr >=80% registry-ready y sin brechas altas.",
            route="/api/platform-readiness/pilot-adoption-command-center?scope=full",
            blocking_for_multicenter=True,
        ),
        _item(
            key="real_world_sample_maturity",
            title="Madurez de muestra real/prospectiva",
            owner="principal_investigator",
            target_level="multicenter",
            priority="critical",
            status=_status_for_real_sample(real_sample_summary, adoption_summary),
            evidence=(
                f"status={real_sample_summary.get('sample_maturity_status', 'unknown')}; "
                f"real={real_sample_summary.get('real_patient_count', adoption_summary.get('real_patient_count', 0))}; "
                f"synthetic={real_sample_summary.get('synthetic_patient_count', adoption_summary.get('synthetic_patient_count', 0))}; "
                f"real_registry_ready={real_sample_summary.get('real_patient_registry_ready_pct', 0)}%"
            ),
            why="Los datos sinteticos sirven para QA, pero no prueban impacto hospitalario ni valor comercial.",
            action=real_sample_summary.get("recommended_next_move")
            or "Iniciar captura prospectiva real con consentimiento/aviso y separar dashboards sinteticos de evidencia hospitalaria.",
            route="/api/platform-readiness/real-world-sample-maturity?scope=full",
            blocking_for_multicenter=True,
        ),
        _item(
            key="huddle_gap_closure",
            title="Huddle semanal de brechas cerrado o bajo control",
            owner="clinical_operations_owner",
            target_level="internal_pilot",
            priority="high" if int(huddle_summary.get("high_priority_gap_count") or 0) else "medium",
            status=(
                "pass" if int(huddle_summary.get("open_gap_count") or 0) == 0 else
                "watch"
            ),
            evidence=(
                f"open={huddle_summary.get('open_gap_count', 0)}; "
                f"reviewed={huddle_summary.get('reviewed_gap_count', 0)}; "
                f"high_priority={huddle_summary.get('high_priority_gap_count', 0)}"
            ),
            why="La calidad prospectiva debe tener una rutina de cierre, no depender de heroicidad manual.",
            action="Cerrar o documentar brechas abiertas sin ocultarlas mientras el dato siga faltando.",
            route="/api/platform-readiness/prospective-gap-closure-huddle?scope=full",
            blocking_for_multicenter=False,
        ),
        _item(
            key="ape_longitudinal_registry_signal",
            title="Serie longitudinal APE reutilizable",
            owner="uro_oncology_clinical_lead",
            target_level="internal_pilot",
            priority="high",
            status=(
                "pass"
                if float(ape_summary.get("psa_history_coverage_pct") or 0) >= 80
                and int(ape_summary.get("ape_gap_patient_count") or 0) == 0
                else "watch"
            ),
            evidence=(
                f"psa_history={ape_summary.get('psa_history_coverage_pct', 0)}%; "
                f"ape_gaps={ape_summary.get('ape_gap_patient_count', 0)}; "
                f"unlock={ape_summary.get('potential_registry_unlock_count', 0)}"
            ),
            why="APE es la columna vertebral para respuesta, progresion, vigilancia y costo por respuesta.",
            action="Cerrar capturas APE con fecha y linea terapeutica antes de congelar cohortes de respuesta.",
            route="/api/platform-readiness/ape-longitudinal-completion-sprint?scope=full",
            blocking_for_multicenter=False,
        ),
        _from_gates(
            key="operational_nas_evidence",
            title="Evidencia operacional NAS firmada",
            owner="it_nas_owner",
            target_level="internal_pilot",
            priority="high",
            gates=[
                gate_by_key.get("nas_local_operations"),
                gate_by_key.get("backup_restore_drill"),
                gate_by_key.get("access_control_roles"),
            ],
            evidence=(
                f"vault_completion={nas_summary.get('completion_pct', 0)}%; "
                f"verified={nas_summary.get('verified_gate_count', 0)}/"
                f"{nas_summary.get('gate_count', 0)}"
            ),
            why="El NAS local es la base operacional para piloto real, continuidad y auditoria.",
            action="Firmar runbook, backup/restore, roles y evidencia de salud operacional en el vault.",
            route="/api/platform-readiness/nas-pilot-evidence-vault?scope=full",
            blocking_for_multicenter=True,
        ),
        _from_gates(
            key="ethics_protocol_clearance",
            title="Protocolo, consentimiento y frontera de uso",
            owner="principal_investigator",
            target_level="external_review",
            priority="critical",
            gates=[
                gate_by_key.get("consent_and_data_use"),
                gate_by_key.get("incident_response_contingency"),
                gate_by_key.get("prospective_protocol_approval"),
            ],
            evidence="Debe existir aprobacion local antes de reportar resultados o abrir multicentro.",
            why="La plataforma debe ser defendible ante comite, jefatura, privacidad e investigacion.",
            action="Cerrar aviso/consentimiento, contingencia, protocolo y calendario de revision.",
            route="/api/platform-readiness/prospective-pilot-governance?scope=full",
            blocking_for_multicenter=True,
        ),
        _item(
            key="world_class_gap_tracking",
            title="Trazabilidad del benchmark mundial a acciones locales",
            owner="product_strategy_owner",
            target_level="multicenter",
            priority="medium",
            status="pass" if benchmark_summary.get("top_gap_key") == "external_validation" else "watch",
            evidence=(
                f"top_gap={benchmark_summary.get('top_gap_key', 'unknown')}; "
                f"score={benchmark_summary.get('world_class_readiness_score', 0)}"
            ),
            why="La estrategia debe cambiar el trabajo diario, no quedarse como presentacion.",
            action="Revisar este worklist semanalmente hasta que el top gap ya no sea validacion externa.",
            route="/api/platform-readiness/world-class-benchmark?scope=full",
            blocking_for_multicenter=False,
        ),
    ]
    return items


def _from_gates(
    *,
    key: str,
    title: str,
    owner: str,
    target_level: str,
    priority: str,
    gates: list[Mapping[str, Any] | None],
    evidence: str,
    why: str,
    action: str,
    route: str,
    blocking_for_multicenter: bool,
) -> dict[str, Any]:
    present = [dict(gate) for gate in gates if gate]
    if not present:
        status = "watch"
        gate_evidence = evidence
    elif any(gate.get("status") == "block" for gate in present):
        status = "block"
        gate_evidence = "; ".join(
            f"{gate.get('gate_key')}={gate.get('status')} ({gate.get('next_action')})"
            for gate in present
        )
    elif any(gate.get("status") == "watch" for gate in present):
        status = "watch"
        gate_evidence = "; ".join(f"{gate.get('gate_key')}={gate.get('status')}" for gate in present)
    else:
        status = "pass"
        gate_evidence = "; ".join(f"{gate.get('gate_key')}=pass" for gate in present)
    return _item(
        key=key,
        title=title,
        owner=owner,
        target_level=target_level,
        priority=priority if status != "pass" else "low",
        status=status,
        evidence=gate_evidence or evidence,
        why=why,
        action=action,
        route=route,
        blocking_for_multicenter=blocking_for_multicenter,
    )


def _item(
    *,
    key: str,
    title: str,
    owner: str,
    target_level: str,
    priority: str,
    status: str,
    evidence: str,
    why: str,
    action: str,
    route: str,
    blocking_for_multicenter: bool,
) -> dict[str, Any]:
    status_key = status if status in {"pass", "watch", "block"} else "watch"
    return {
        "key": key,
        "title": title,
        "owner": owner,
        "target_level": target_level,
        "priority": priority,
        "status": status_key,
        "blocking_for_multicenter": bool(blocking_for_multicenter),
        "evidence": evidence,
        "why": why,
        "action": action,
        "route": route,
        "benefit": _benefit_for_level(target_level),
    }


def _build_summary(
    items: list[Mapping[str, Any]],
    benchmark: Mapping[str, Any],
    pilot: Mapping[str, Any],
    adoption: Mapping[str, Any],
    nas_vault: Mapping[str, Any],
) -> dict[str, Any]:
    item_count = len(items)
    pass_count = sum(1 for item in items if item.get("status") == "pass")
    watch_count = sum(1 for item in items if item.get("status") == "watch")
    block_count = sum(1 for item in items if item.get("status") == "block")
    multicenter_block_count = sum(
        1 for item in items if item.get("status") == "block" and item.get("blocking_for_multicenter")
    )
    score = round((pass_count / item_count) * 100, 1) if item_count else 0.0
    if multicenter_block_count:
        status = "external_validation_blocked_by_readiness_gates"
    elif watch_count:
        status = "ready_for_internal_external_review_not_multicenter"
    else:
        status = "ready_for_external_validation_packet"
    top_item = next((item for item in items if item.get("status") == "block"), None)
    if not top_item:
        top_item = next((item for item in items if item.get("status") == "watch"), None)
    benchmark_summary = benchmark.get("summary") or {}
    pilot_summary = pilot.get("summary") or {}
    adoption_summary = adoption.get("summary") or {}
    nas_summary = nas_vault.get("summary") or {}
    return {
        "external_validation_status": status,
        "external_validation_score_pct": score,
        "item_count": item_count,
        "pass_count": pass_count,
        "watch_count": watch_count,
        "block_count": block_count,
        "multicenter_block_count": multicenter_block_count,
        "top_blocker_key": top_item.get("key") if top_item else "",
        "top_blocker_title": top_item.get("title") if top_item else "",
        "world_class_top_gap_key": benchmark_summary.get("top_gap_key"),
        "world_class_top_gap_label": benchmark_summary.get("top_gap_label"),
        "pilot_status": pilot_summary.get("pilot_status"),
        "pilot_gate_score": pilot_summary.get("pilot_gate_score", 0),
        "registry_ready_pct": adoption_summary.get("registry_ready_pct", 0),
        "real_patient_count": adoption_summary.get("real_patient_count", 0),
        "nas_evidence_completion_pct": nas_summary.get("completion_pct", 0),
        "external_validation_claim_made": False,
        "recommended_next_move": (
            top_item.get("action")
            if top_item
            else "Congelar paquete audit_ready y preparar revision externa con protocolo firmado."
        ),
    }


def _build_evidence_bundle_manifest(
    pilot: Mapping[str, Any],
    freeze_library: Mapping[str, Any],
) -> list[dict[str, Any]]:
    manifest = [
        {
            "component": "External validation worklist",
            "kind": "json_contract",
            "url": "/api/platform-readiness/external-validation-worklist?scope=full",
            "required": True,
        },
        {
            "component": "World-class benchmark radar",
            "kind": "json_contract",
            "url": "/api/platform-readiness/world-class-benchmark?scope=full",
            "required": True,
        },
    ]
    manifest.extend(dict(item) for item in (pilot.get("pilot_packet_manifest") or [])[:8])
    latest_freeze = (freeze_library.get("freezes") or [None])[0]
    if latest_freeze:
        manifest.append(
            {
                "component": "Latest governed no-PHI freeze",
                "kind": "download",
                "url": latest_freeze.get("download_url"),
                "freeze_key": latest_freeze.get("freeze_key"),
                "required": True,
            }
        )
    return manifest


def _build_next_validation_packet(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "packet_name": "ProstaMed external validation preflight packet",
        "current_status": summary.get("external_validation_status"),
        "claim_boundary": "Preflight/readiness only; no external validation claim until signed review exists.",
        "minimum_packet": [
            "Readiness JSON with Ledger and V2 persistence evidence",
            "No-PHI research pack freeze with hash manifest",
            "Data dictionary with mCODE/OMOP target semantics",
            "Prospective pilot protocol and consent/data-use boundary",
            "Adoption/completeness report with synthetic patients separated",
            "Methodology note for outcomes, cost and statistical adjustment",
        ],
        "benefit": "Permite pedir revision externa con evidencia reproducible, sin exponer PHI ni inflar claims.",
    }


def _build_readiness_lanes(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    lanes: dict[str, list[Mapping[str, Any]]] = {}
    for item in items:
        lanes.setdefault(str(item.get("target_level") or "external_review"), []).append(item)
    result = []
    for key in ("internal_pilot", "external_review", "multicenter"):
        lane_items = lanes.get(key, [])
        result.append(
            {
                "lane": key,
                "item_count": len(lane_items),
                "pass_count": sum(1 for item in lane_items if item.get("status") == "pass"),
                "watch_count": sum(1 for item in lane_items if item.get("status") == "watch"),
                "block_count": sum(1 for item in lane_items if item.get("status") == "block"),
            }
        )
    return result


def _build_partner_site_packet_requirements() -> list[dict[str, str]]:
    return [
        {
            "requirement": "Site onboarding letter",
            "owner": "principal_investigator",
            "reason": "Defines who reviews the no-PHI pack and what claims are allowed.",
        },
        {
            "requirement": "Data-use and privacy boundary",
            "owner": "ethics_privacy_owner",
            "reason": "Prevents accidental external PHI transfer and defines publication rules.",
        },
        {
            "requirement": "Minimum dataset dictionary",
            "owner": "interoperability_owner",
            "reason": "Allows another site to map equivalent prostate-cancer facts.",
        },
        {
            "requirement": "Statistical analysis plan",
            "owner": "biostatistics_owner",
            "reason": "Avoids changing endpoints after outcomes are seen.",
        },
        {
            "requirement": "Reproducible frozen package",
            "owner": "research_governance_owner",
            "reason": "Each number must be traceable back to a frozen, hashable artifact.",
        },
    ]


def _build_external_protocol_outline(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "study_type": "Prospective local pilot followed by external no-PHI validation review",
        "current_gate": summary.get("external_validation_status"),
        "primary_preflight_endpoint": "Proportion of registry-ready V2 patients with reusable Ledger facts and no direct PHI in research pack.",
        "secondary_preflight_endpoints": [
            "APE longitudinal coverage",
            "Treatment-line completeness",
            "NCCN/EAU decision traceability",
            "Cost-response readiness",
            "Huddle closure velocity",
        ],
        "multicenter_gate": "Requires real patients, signed protocol, local governance and external site onboarding.",
    }


def _derive_huddle_summary_from_adoption(adoption: Mapping[str, Any]) -> dict[str, Any]:
    summary = adoption.get("summary") or {}
    gap_rows = adoption.get("capture_gap_summary") or []
    open_count = sum(int(row.get("patient_count") or row.get("count") or 0) for row in gap_rows)
    high_count = int(summary.get("high_priority_gap_count") or 0)
    if open_count <= 0:
        open_count = high_count
    return {
        "available": True,
        "source": "derived_from_pilot_adoption_summary",
        "summary": {
            "huddle_item_count": open_count,
            "patient_with_gap_count": max(
                0,
                int(summary.get("patient_count") or 0)
                - int(summary.get("registry_ready_patient_count") or 0),
            ),
            "open_gap_count": open_count,
            "reviewed_gap_count": 0,
            "high_priority_gap_count": high_count,
            "adoption_registry_ready_pct": summary.get("registry_ready_pct", 0),
            "huddle_status": "derived_needs_exact_huddle" if open_count else "derived_no_open_gap",
        },
    }


def _derive_ape_summary_from_adoption(
    adoption: Mapping[str, Any],
    huddle: Mapping[str, Any],
) -> dict[str, Any]:
    summary = adoption.get("summary") or {}
    huddle_summary = huddle.get("summary") or {}
    patient_count = int(summary.get("patient_count") or 0)
    history_ready = int(summary.get("psa_history_patient_count") or 0)
    coverage = float(summary.get("psa_history_coverage_pct") or 0)
    gap_count = max(0, patient_count - history_ready)
    return {
        "available": True,
        "source": "derived_from_pilot_adoption_summary",
        "summary": {
            "patient_count": patient_count,
            "ape_gap_patient_count": gap_count,
            "missing_psa_patient_count": max(0, patient_count - int(summary.get("psa_any_patient_count") or 0)),
            "single_psa_patient_count": 0,
            "isolated_psa_snapshot_patient_count": 0,
            "missing_sample_date_patient_count": 0,
            "uninterpretable_series_patient_count": 0,
            "history_ready_patient_count": history_ready,
            "psa_history_coverage_pct": coverage,
            "adoption_psa_history_coverage_pct": coverage,
            "potential_registry_unlock_count": gap_count,
            "high_priority_ape_gap_count": gap_count,
            "huddle_open_gap_count": huddle_summary.get("open_gap_count", 0),
            "sprint_status": "derived_ape_history_ready" if gap_count == 0 else "derived_ape_completion_needed",
        },
    }


def _status_for_export(
    export_summary: Mapping[str, Any],
    pack_summary: Mapping[str, Any],
    freeze_summary: Mapping[str, Any],
) -> str:
    if _has_phi_or_export_block(export_summary, pack_summary):
        return "block"
    if (
        _truthy(export_summary.get("next_layer_allowed"))
        and _truthy(pack_summary.get("next_layer_allowed"))
        and int(freeze_summary.get("download_ready_count") or 0) > 0
    ):
        return "pass"
    return "watch"


def _has_phi_or_export_block(export_summary: Mapping[str, Any], pack_summary: Mapping[str, Any]) -> bool:
    return any(
        int(summary.get(key) or 0) > 0
        for summary in (export_summary, pack_summary)
        for key in ("direct_identifier_key_count", "exact_phi_hit_count", "critical_interop_block_count")
    )


def _status_for_capture(summary: Mapping[str, Any]) -> str:
    if int(summary.get("patient_count") or 0) == 0:
        return "block"
    if (
        float(summary.get("registry_ready_pct") or 0) >= 80
        and int(summary.get("high_priority_gap_count") or 0) == 0
    ):
        return "pass"
    return "watch"


def _status_for_real_sample(
    real_sample_summary: Mapping[str, Any],
    adoption_summary: Mapping[str, Any],
) -> str:
    status = str(real_sample_summary.get("sample_maturity_status") or "")
    if status.startswith("ready_for_multicenter"):
        return "pass"
    if status in {"ready_for_internal_real_world_signal", "ready_for_external_preflight_not_multicenter"}:
        return "watch"
    real_count = int(real_sample_summary.get("real_patient_count") or adoption_summary.get("real_patient_count") or 0)
    if real_count <= 0:
        return "block"
    if real_count < 50:
        return "watch"
    return "pass"


def _benefit_for_level(level: str) -> str:
    return {
        "internal_pilot": "Hace confiable el piloto local y evita recaptura o contradicciones.",
        "external_review": "Permite revision externa no-PHI con evidencia reproducible.",
        "multicenter": "Prepara expansion multicentro y comparabilidad institucional.",
    }.get(str(level or ""), "Aumenta auditabilidad y valor institucional.")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"true", "1", "yes", "si", "pass", "ready"}


def _priority_rank(value: Any) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(str(value or ""), 9)


def _status_rank(value: Any) -> int:
    return {"block": 0, "watch": 1, "pass": 2}.get(str(value or ""), 9)


def _scan_for_phi(payload: Mapping[str, Any]) -> dict[str, Any]:
    hits: list[str] = []
    direct_keys: list[str] = []

    def walk(value: Any, path: str = "") -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                key_text = str(key)
                nested_path = f"{path}.{key_text}" if path else key_text
                if key_text.lower() in DIRECT_IDENTIFIER_KEYS:
                    direct_keys.append(nested_path)
                walk(nested, nested_path)
        elif isinstance(value, list | tuple):
            for index, nested in enumerate(value):
                walk(nested, f"{path}[{index}]")
        elif isinstance(value, str):
            if re.search(r"/patient_profile/|\\b\\d{10,}\\b|\\bNSS\\b", value, re.IGNORECASE):
                hits.append(path)

    walk(payload)
    return {
        "no_phi_status": "pass" if not hits and not direct_keys else "block",
        "direct_identifier_key_count": len(direct_keys),
        "phi_like_value_count": len(hits),
        "direct_identifier_keys": direct_keys[:20],
        "phi_like_value_paths": hits[:20],
    }


__all__ = [
    "EXTERNAL_VALIDATION_WORKLIST_VERSION",
    "build_external_validation_worklist",
    "build_external_validation_worklist_csv_bytes",
]
