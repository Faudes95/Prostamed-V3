from __future__ import annotations

from flask import Blueprint, redirect, render_template

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
# Faubot 2026-04-25 (XXXII) — Tier 7 G5: auth gateway HTML
from prostanet.shared.security_helpers import require_clinical_session


modular_views = Blueprint("modular_views", __name__)
registry = ModuleRegistry()


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
        if v_flag == "v2_legacy":
            return redirect("/clinical-hub", code=302)
        return render_template("demos/stage_clinical_center_v2_redesign.html", **v2_data)
    return render_template(
        "clinical_hub.html",
        modules=modules,
        page_chrome=page_chrome,
        quick_classifier_config=_quick_classifier_config(),
    )


@modular_views.route("/wizard/<module_id>", methods=["GET"])
@require_clinical_session(scope="phi:write", redirect_to_login=True)
def wizard(module_id: str):
    from flask import request as _req
    schema = humanize_schema(registry.get_module_schema(module_id))
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

    wizard_form_fields = (
        _router_fields_for_wizard_form(clinical_field_router)
        if chrome_mode == "v2" and readiness_lane_arg and clinical_field_router
        else None
    )

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
