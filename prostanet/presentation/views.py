from __future__ import annotations

from flask import Blueprint, redirect, render_template, url_for

from prostanet.application.module_registry import ModuleRegistry
from prostanet.presentation.view_models import build_page_chrome
from prostanet.shared.metastatic_profile import (
    APPENDICULAR_BONE_SITE_KEYS,
    AXIAL_BONE_SITE_KEYS,
    BONE_SITE_LABELS,
    NONREGIONAL_NODAL_SITE_LABELS,
    VISCERAL_SITE_LABELS,
)
from prostanet.shared.presentation_text import humanize_evidence, humanize_module_listing, humanize_schema
from prostanet.shared.pivotal_gate_disclosure import (
    build_gate_family_control_state,
    filter_schema_for_wizard,
)
# Faubot 2026-04-25 (XXXII) — Tier 7 G5: auth gateway HTML
from prostanet.shared.security_helpers import require_clinical_session


modular_views = Blueprint("modular_views", __name__)
registry = ModuleRegistry()


def _load_patient_record_for_wizard_ledger(patient_ref: str) -> dict | None:
    if not patient_ref:
        return None
    try:
        import tracking_db

        core_record = tracking_db.load_patient_record_core(patient_ref)
        if core_record:
            return tracking_db.build_patient_record_derivatives(core_record)
        return tracking_db.get_patient_full_record(patient_ref, include_derivatives=False)
    except Exception:
        return None


def _quick_classifier_config() -> dict:
    def _group(label: str, keys: tuple[str, ...]) -> dict:
        return {
            "label": label,
            "options": [
                {"site_key": key, "label": BONE_SITE_LABELS[key]}
                for key in keys
            ],
        }

    return {
        "bone_site_groups": [
            _group("Esqueleto axial", AXIAL_BONE_SITE_KEYS),
            _group("Esqueleto apendicular", APPENDICULAR_BONE_SITE_KEYS),
        ],
        "visceral_site_options": [
            {"site_key": key, "label": VISCERAL_SITE_LABELS[key]}
            for key in VISCERAL_SITE_LABELS
        ],
        "nonregional_nodal_site_options": [
            {"site_key": key, "label": NONREGIONAL_NODAL_SITE_LABELS[key]}
            for key in NONREGIONAL_NODAL_SITE_LABELS
        ],
    }


def _wizard_gate_controls(module_id: str, request_args) -> dict:
    selected = request_args.getlist("gate_family")
    state = build_gate_family_control_state(module_id, requested=selected)
    preserved_args = {}
    for key in ("v", "readiness_lane"):
        value = str(request_args.get(key) or "").strip()
        if value:
            preserved_args[key] = value
    for control in state.get("controls") or []:
        control_args = dict(preserved_args)
        control_args["gate_family"] = control["key"]
        control["href"] = url_for("modular_views.wizard", module_id=module_id, **control_args)
    state["clear_href"] = url_for("modular_views.wizard", module_id=module_id, **preserved_args)
    return state


@modular_views.route("/clinical-hub", methods=["GET"])
@require_clinical_session(scope="phi:read", redirect_to_login=True)
def clinical_hub():
    from flask import request as _req
    modules = [humanize_module_listing(module) for module in registry.list_modules()]
    page_chrome = build_page_chrome(
        "clinical_hub",
        "Centro clínico por estadio",
        "Clasificación clínica guiada por la Red Nacional Integral del Cáncer (NCCN) 5.2026 con comparación paralela de la Asociación Europea de Urología (EAU) 2026.",
    )
    # Faubot LXXX #67E — v2 es DEFAULT. Legacy v1 disponible vía ?v=legacy.
    # Faubot C — v2_legacy retirado: el hub oficial es el rediseño integrado.
    v_flag = _req.args.get("v")
    if v_flag != "legacy":
        from prostanet.presentation.v2_adapters import stage_center_to_v2
        v2_data = stage_center_to_v2()
        real_world_launch_requested = str(_req.args.get("real_world_enrollment") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "si",
            "sí",
        }
        v2_data["real_world_launch_requested"] = real_world_launch_requested
        v2_data["real_world_first_patient_launch_mode"] = None
        if real_world_launch_requested:
            try:
                from prostanet.domains.platform_readiness.real_world_first_patient_launch_mode import (
                    build_real_world_first_patient_launch_mode,
                )

                v2_data["real_world_first_patient_launch_mode"] = build_real_world_first_patient_launch_mode(
                    scope="summary",
                    limit=5,
                )
            except Exception as exc:
                v2_data["real_world_first_patient_launch_mode"] = {
                    "available": False,
                    "version": "real_world_first_patient_launch_mode_v1",
                    "summary": {
                        "launch_mode_status": "launch_mode_unavailable",
                        "dry_run_contract_status": "unknown",
                        "real_patient_count": 0,
                        "registry_ready_real_count": 0,
                        "next_operator_action": "Abrir readiness y restaurar el modo de lanzamiento.",
                    },
                    "error": str(exc),
                    "source_clinical_facts_mutated": False,
                    "external_order_created": False,
                    "model_trained": False,
                }
        if v_flag == "v2_legacy":
            return redirect("/clinical-hub", code=302)
        return render_template("demos/stage_clinical_center_v2_redesign.html", **v2_data)
    return render_template(
        "clinical_hub.html",
        modules=modules,
        page_chrome=page_chrome,
        quick_classifier_config=_quick_classifier_config(),
    )


@modular_views.route("/platform-readiness", methods=["GET"])
@require_clinical_session(scope="phi:read", redirect_to_login=True)
def platform_readiness():
    from flask import current_app, request as _req
    from prostanet.domains.platform_readiness.ape_longitudinal_completion_sprint import (
        build_ape_longitudinal_completion_sprint,
    )
    from prostanet.domains.platform_readiness.audit import build_platform_readiness_audit
    from prostanet.domains.platform_readiness.capture_integrity import (
        build_capture_integrity_readiness,
    )
    from prostanet.domains.platform_readiness.v2_persistence_closure import (
        build_v2_initial_staging_persistence_closure,
    )
    from prostanet.domains.platform_readiness.v2_treatment_value_closure import (
        build_v2_treatment_value_closure,
    )
    from prostanet.domains.platform_readiness.deidentified_export_contract import (
        build_deidentified_export_contract,
    )
    from prostanet.domains.platform_readiness.external_validation_worklist import (
        build_external_validation_worklist,
    )
    from prostanet.domains.platform_readiness.interoperability_map import (
        build_interoperability_map,
    )
    from prostanet.domains.platform_readiness.ledger_release_gate import build_ledger_release_gate
    from prostanet.domains.platform_readiness.ledger_persistence_matrix import (
        build_ledger_persistence_matrix,
    )
    from prostanet.domains.platform_readiness.nas_pilot_evidence_vault import (
        build_nas_pilot_evidence_vault,
    )
    from prostanet.domains.platform_readiness.pilot_adoption_command_center import (
        build_pilot_adoption_command_center,
    )
    from prostanet.domains.platform_readiness.prospective_gap_closure_huddle import (
        build_prospective_gap_closure_huddle,
    )
    from prostanet.domains.platform_readiness.prospective_pilot_governance import (
        build_prospective_pilot_governance_pack,
    )
    from prostanet.domains.platform_readiness.prospective_real_world_completion_queue import (
        build_prospective_real_world_completion_queue,
    )
    from prostanet.domains.platform_readiness.real_world_first_patient_launch_mode import (
        build_real_world_first_patient_launch_mode,
    )
    from prostanet.domains.platform_readiness.real_world_launch_flow_verifier import (
        build_real_world_launch_flow_verifier,
    )
    from prostanet.domains.platform_readiness.real_world_pilot_execution_log import (
        build_real_world_pilot_execution_log,
    )
    from prostanet.domains.platform_readiness.real_world_pilot_packet import (
        build_real_world_pilot_packet,
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
    from prostanet.domains.population_intelligence.arpi_value_analytics import (
        build_epidemiology_command_center,
    )

    scope = "summary" if str(_req.args.get("scope") or "").lower() == "summary" else "full"
    audit = build_platform_readiness_audit(
        registry,
        registered_rules=current_app.url_map.iter_rules(),
        scope=scope,
        field_limit=250,
    )
    capture_integrity = build_capture_integrity_readiness(
        registry,
        scope="full",
    )
    v2_persistence_closure = build_v2_initial_staging_persistence_closure(
        registered_rules=current_app.url_map.iter_rules(),
        capture_integrity=capture_integrity,
        scope="full",
    )
    v2_treatment_value_closure = build_v2_treatment_value_closure(
        registered_rules=current_app.url_map.iter_rules(),
        scope="full",
    )
    ledger_gate = build_ledger_release_gate(
        registry,
        registered_rules=current_app.url_map.iter_rules(),
        scope="full",
        field_limit=160,
        readiness_audit=audit,
    )
    ledger_persistence_matrix = build_ledger_persistence_matrix(
        registry,
        registered_rules=current_app.url_map.iter_rules(),
        scope="full",
        row_limit=260,
        release_gate=ledger_gate,
    )
    interoperability_map = build_interoperability_map(
        scope="full",
        field_limit=180,
    )
    deidentified_export_contract = build_deidentified_export_contract(
        scope="full",
        limit=80,
    )
    research_pack_materializer = build_research_pack_materializer(
        scope="summary",
        limit=80,
    )
    research_pack_freeze_library = build_research_pack_freeze_library(
        limit=25,
        include_payload=False,
        include_current_preview=False,
    )
    nas_pilot_evidence_vault = build_nas_pilot_evidence_vault(
        scope="summary",
        limit=100,
    )
    pilot_adoption_command_center = build_pilot_adoption_command_center(
        scope="full",
        limit=100,
        nas_pilot_evidence_vault=nas_pilot_evidence_vault,
    )
    real_only_pilot_adoption_command_center = build_pilot_adoption_command_center(
        scope="full",
        limit=100,
        real_only=True,
        nas_pilot_evidence_vault=nas_pilot_evidence_vault,
    )
    prospective_gap_closure_huddle = build_prospective_gap_closure_huddle(
        scope="full",
        limit=100,
        adoption_command_center=pilot_adoption_command_center,
    )
    ape_longitudinal_completion_sprint = build_ape_longitudinal_completion_sprint(
        scope="full",
        limit=100,
        adoption_command_center=pilot_adoption_command_center,
        gap_huddle=prospective_gap_closure_huddle,
    )
    prospective_pilot_governance = build_prospective_pilot_governance_pack(
        registry,
        registered_rules=current_app.url_map.iter_rules(),
        scope="summary",
        limit=80,
        readiness_audit=audit,
        ledger_release_gate=ledger_gate,
        ledger_persistence_matrix=ledger_persistence_matrix,
        interoperability_map=interoperability_map,
        deidentified_export_contract=deidentified_export_contract,
        research_pack_materializer=research_pack_materializer,
        research_pack_freeze_library=research_pack_freeze_library,
        nas_pilot_evidence_vault=nas_pilot_evidence_vault,
    )
    real_world_sample_maturity = build_real_world_sample_maturity_gate(
        scope="full",
        limit=100,
        registry=registry,
        registered_rules=current_app.url_map.iter_rules(),
        pilot_adoption_command_center=pilot_adoption_command_center,
        nas_pilot_evidence_vault=nas_pilot_evidence_vault,
        prospective_pilot_governance=prospective_pilot_governance,
    )
    real_only_ape_longitudinal_completion_sprint = build_ape_longitudinal_completion_sprint(
        scope="full",
        limit=100,
        real_only=True,
        adoption_command_center=real_only_pilot_adoption_command_center,
    )
    prospective_real_world_completion_queue = build_prospective_real_world_completion_queue(
        scope="full",
        limit=100,
        real_world_sample_maturity=real_world_sample_maturity,
        pilot_adoption_command_center=real_only_pilot_adoption_command_center,
        ape_longitudinal_completion_sprint=real_only_ape_longitudinal_completion_sprint,
    )
    real_world_pilot_packet = build_real_world_pilot_packet(
        scope="full",
        limit=100,
        real_world_sample_maturity=real_world_sample_maturity,
        prospective_real_world_completion_queue=prospective_real_world_completion_queue,
    )
    real_world_pilot_execution_log = build_real_world_pilot_execution_log(
        scope="full",
        limit=100,
        real_world_sample_maturity=real_world_sample_maturity,
        prospective_real_world_completion_queue=prospective_real_world_completion_queue,
        real_world_pilot_packet=real_world_pilot_packet,
    )
    real_world_first_patient_launch_mode = build_real_world_first_patient_launch_mode(
        scope="full",
        limit=100,
        real_world_sample_maturity=real_world_sample_maturity,
        prospective_real_world_completion_queue=prospective_real_world_completion_queue,
        real_world_pilot_packet=real_world_pilot_packet,
        real_world_pilot_execution_log=real_world_pilot_execution_log,
    )
    real_world_launch_flow_verifier = build_real_world_launch_flow_verifier(
        scope="full",
        limit=100,
        registered_rules=current_app.url_map.iter_rules(),
        real_world_sample_maturity=real_world_sample_maturity,
        prospective_real_world_completion_queue=prospective_real_world_completion_queue,
        real_world_first_patient_launch_mode=real_world_first_patient_launch_mode,
    )
    try:
        epidemiology_command_center = build_epidemiology_command_center(
            weeks_list=(12, 24, 36, 52),
            trace_limit=25,
            freeze_limit=6,
        )
    except Exception as exc:
        epidemiology_command_center = {
            "available": False,
            "version": "epidemiology_command_center_v2",
            "error": str(exc),
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
        }
    world_class_benchmark = build_world_class_benchmark_radar(
        readiness_audit=audit,
        ledger_release_gate=ledger_gate,
        ledger_persistence_matrix=ledger_persistence_matrix,
        interoperability_map=interoperability_map,
        deidentified_export_contract=deidentified_export_contract,
        research_pack_materializer=research_pack_materializer,
        research_pack_freeze_library=research_pack_freeze_library,
        prospective_pilot_governance=prospective_pilot_governance,
        v2_treatment_value_closure=v2_treatment_value_closure,
        epidemiology_command_center=epidemiology_command_center,
        scope="full",
    )
    external_validation_worklist = build_external_validation_worklist(
        scope="full",
        limit=100,
        world_class_benchmark=world_class_benchmark,
        prospective_pilot_governance=prospective_pilot_governance,
        nas_pilot_evidence_vault=nas_pilot_evidence_vault,
        pilot_adoption_command_center=pilot_adoption_command_center,
        prospective_gap_closure_huddle=prospective_gap_closure_huddle,
        ape_longitudinal_completion_sprint=ape_longitudinal_completion_sprint,
        real_world_sample_maturity=real_world_sample_maturity,
        deidentified_export_contract=deidentified_export_contract,
        research_pack_materializer=research_pack_materializer,
        research_pack_freeze_library=research_pack_freeze_library,
        interoperability_map=interoperability_map,
    )
    return render_template(
        "platform_readiness.html",
        audit=audit,
        capture_integrity=capture_integrity,
        v2_persistence_closure=v2_persistence_closure,
        v2_treatment_value_closure=v2_treatment_value_closure,
        ledger_gate=ledger_gate,
        ledger_persistence_matrix=ledger_persistence_matrix,
        interoperability_map=interoperability_map,
        deidentified_export_contract=deidentified_export_contract,
        research_pack_materializer=research_pack_materializer,
        research_pack_freeze_library=research_pack_freeze_library,
        prospective_pilot_governance=prospective_pilot_governance,
        nas_pilot_evidence_vault=nas_pilot_evidence_vault,
        pilot_adoption_command_center=pilot_adoption_command_center,
        prospective_gap_closure_huddle=prospective_gap_closure_huddle,
        ape_longitudinal_completion_sprint=ape_longitudinal_completion_sprint,
        real_world_sample_maturity=real_world_sample_maturity,
        prospective_real_world_completion_queue=prospective_real_world_completion_queue,
        real_world_pilot_packet=real_world_pilot_packet,
        real_world_pilot_execution_log=real_world_pilot_execution_log,
        real_world_first_patient_launch_mode=real_world_first_patient_launch_mode,
        real_world_launch_flow_verifier=real_world_launch_flow_verifier,
        world_class_benchmark=world_class_benchmark,
        external_validation_worklist=external_validation_worklist,
        scope=scope,
    )


@modular_views.route("/wizard/<module_id>", methods=["GET"])
@require_clinical_session(scope="phi:write", redirect_to_login=True)
def wizard(module_id: str):
    from flask import request as _req
    module_id = registry.canonical_module_id(module_id)
    raw_schema = registry.get_module_schema(module_id)
    gate_family_args = _req.args.getlist("gate_family")
    gate_control_state = _wizard_gate_controls(module_id, _req.args)
    wizard_schema_raw = filter_schema_for_wizard(
        raw_schema,
        module_id,
        gate_families=gate_family_args,
    )
    schema = humanize_schema(wizard_schema_raw)
    evidence = humanize_evidence(registry.get_module_evidence(module_id))
    readiness_lane_arg = (_req.args.get("readiness_lane") or "").strip()
    try:
        from prostanet.presentation.clinical_field_router import (
            build_clinical_field_router,
        )
        clinical_field_router = build_clinical_field_router(
            module_id,
            phase="initial_wizard",
            readiness_lane=readiness_lane_arg or None,
        )
    except Exception:
        clinical_field_router = None

    # Faubot LXXXV.b — v2 chrome es DEFAULT (mismo patrón LXXX para hub/dashboard/profile).
    # Legacy disponible vía ?v=legacy. v2 envuelve con pm2_sidebar + actionbar moderno
    # preservando 100% del form internal legacy (widgets + draft + consent + JS).
    chrome_mode = "legacy" if _req.args.get("v") == "legacy" else "v2"

    # En v2 mode: full-width layout (sidebar ocupa columna izquierda).
    # En legacy mode: ancho legacy max-w-7xl.
    width_class = "max-w-none px-0 py-0 sm:px-0 lg:px-0" if chrome_mode == "v2" else "max-w-7xl"
    real_world_launch_requested = str(_req.args.get("real_world_enrollment") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "si",
        "sí",
    }

    page_chrome = build_page_chrome(
        "clinical_hub",
        schema["title"],
        schema["description"],
        content_width_class=width_class,
        uses_v2_shell=(chrome_mode == "v2"),
    )

    # Hidratar audit_dims para sidebar v2 (FAUBOT_RELEASE + gates_count)
    audit_dims_v2 = None
    if chrome_mode == "v2":
        try:
            from prostanet.shared.algorithm_version import get_algorithm_version
            v = get_algorithm_version()
            audit_dims_v2 = {
                "version": {
                    "faubot_release": v.get("faubot_release", "LXXXV.b"),
                    "gates_active_count": v.get("gates_active_count", 89),
                }
            }
        except Exception:
            audit_dims_v2 = {"version": {"faubot_release": "LXXXV.b", "gates_active_count": 89}}

    real_world_first_patient_launch_mode = None
    if chrome_mode == "v2" and real_world_launch_requested:
        try:
            from prostanet.domains.platform_readiness.real_world_first_patient_launch_mode import (
                build_real_world_first_patient_launch_mode,
            )

            real_world_first_patient_launch_mode = build_real_world_first_patient_launch_mode(
                scope="summary",
                limit=5,
            )
        except Exception:
            real_world_first_patient_launch_mode = {
                "summary": {
                    "launch_mode_status": "launch_context_unavailable",
                    "dry_run_contract_status": "unknown",
                    "real_patient_count": 0,
                    "registry_ready_real_count": 0,
                    "next_operator_action": "Verificar readiness antes de registrar paciente real.",
                },
                "source_clinical_facts_mutated": False,
                "external_order_created": False,
                "model_trained": False,
            }

    wizard_form_fields = (
        _router_fields_for_wizard_form(clinical_field_router)
        if (
            chrome_mode == "v2"
            and readiness_lane_arg
            and not gate_control_state.get("requested_families")
            and clinical_field_router
        )
        else None
    )
    patient_ref_arg = (
        _req.args.get("patient_ref")
        or _req.args.get("nss")
        or _req.args.get("patient")
        or ""
    ).strip()
    clinical_fact_ledger_wizard_context = None
    if chrome_mode == "v2" and patient_ref_arg:
        try:
            from prostanet.domains.clinical_fact_ledger import (
                build_patient_clinical_fact_ledger,
                build_patient_clinical_fact_ledger_wizard_context,
            )

            patient_record = _load_patient_record_for_wizard_ledger(patient_ref_arg)
            if patient_record:
                ledger = build_patient_clinical_fact_ledger(patient_record)
                clinical_fact_ledger_wizard_context = build_patient_clinical_fact_ledger_wizard_context(
                    patient_record,
                    ledger=ledger,
                    module_schema=wizard_schema_raw,
                    module_id=module_id,
                )
        except Exception:
            clinical_fact_ledger_wizard_context = {
                "available": False,
                "version": "clinical_fact_ledger_wizard_context_v1",
                "field_prefills": {},
                "source_clinical_facts_mutated": False,
                "external_order_created": False,
                "model_trained": False,
            }

    return render_template(
        "clinical_wizard.html",
        schema=schema,
        evidence=evidence,
        page_chrome=page_chrome,
        metastatic_capture_config=_quick_classifier_config(),
        chrome_mode=chrome_mode,
        audit_dims_v2=audit_dims_v2,
        clinical_field_router=clinical_field_router,
        wizard_form_fields=wizard_form_fields,
        pivotal_gate_control_state=gate_control_state,
        clinical_fact_ledger_wizard_context=clinical_fact_ledger_wizard_context,
        real_world_launch_requested=real_world_launch_requested,
        real_world_first_patient_launch_mode=real_world_first_patient_launch_mode,
    )


def _router_fields_for_wizard_form(clinical_field_router: dict | None) -> list[dict]:
    """Flatten Clinical Field Router groups into fields compatible with the wizard template."""
    if not clinical_field_router:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for group in clinical_field_router.get("group_order") or []:
        group_key = str(group.get("key") or "")
        group_label = str(group.get("label") or group_key or "Datos clinicos")
        for raw_field in group.get("fields") or []:
            field = dict(raw_field or {})
            name = str(field.get("name") or "")
            if not name or name in seen:
                continue
            seen.add(name)
            field_type = str(field.get("field_type") or field.get("type") or "text")
            display_options = []
            for option in field.get("display_options") or field.get("options") or []:
                if isinstance(option, dict):
                    display_options.append({
                        "value": str(option.get("value", option.get("key", ""))),
                        "label": str(option.get("label", option.get("value", option.get("key", "")))),
                    })
                else:
                    display_options.append({"value": str(option), "label": str(option)})
            field.update({
                "group": group_label,
                "field_type": field_type,
                "type": field_type,
                "required": bool(field.get("required") or group_key == "required"),
                "default": field.get("default", ""),
                "display_options": display_options,
                "unit": field.get("unit", ""),
                "help_text": field.get("help_text", ""),
                "benchmark_note": field.get("benchmark_note", ""),
                "conditional_visibility": field.get("conditional_visibility") or {},
                "clinical_role": field.get("clinical_role") or (
                    "minimum_decision" if group_key == "required" else "decision_refiner"
                ),
                "clinical_role_label": field.get("clinical_role_label") or group_label,
            })
            out.append(field)
    return out
