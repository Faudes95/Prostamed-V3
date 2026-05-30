from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Iterable, Mapping
import unicodedata


PIVOTAL_GATE_GROUP = "Soportes adicionales de gates pivote"
ALL_GATE_FAMILY = "all"


GATE_FAMILY_DEFINITIONS: dict[str, dict[str, Any]] = {
    "diagnostic_pre_biopsy": {
        "label": "Diagnostico / pre-biopsia",
        "button_label": "Abrir diagnostico",
        "description": "PHI, 4Kscore, biopsia, TR avanzado y sospecha pre-histologica.",
        "group": "Gate pivote - diagnostico pre-biopsia",
        "group_order": 81.1,
        "tokens": (
            "pre_biopsy", "pre-biopsia", "pre-bx", "biopsy", "biopsia",
            "phi", "4kscore", "fourkscore", "psa_density", "psad",
            "dre_", "tacto rectal", "primary_biopsy", "histology_already",
        ),
    },
    "local_decision": {
        "label": "Decision local RP / RT",
        "button_label": "Abrir local/RP-RT",
        "description": "Campos subespecializados para RP, RT, vigilancia activa y salvage local.",
        "group": "Gate pivote - decision local",
        "group_order": 81.2,
        "tokens": (
            "rp_vs_rt", "prostatectomy", "prostatectomia", "radiotherapy",
            "radioterapia", "active_surveillance", "vigilancia activa",
            "svi", "turp", "brachy", "braquiterapia", "pelvic_rt",
            "pelvic radiation", "anticoagulant", "antiplatelet",
            "bleeding_risk", "inflammatory_bowel", "ibd", "salvage_rt",
            "re_irradiation", "local_recurrence", "palliative_intent",
        ),
    },
    "genomic": {
        "label": "Genomica",
        "button_label": "Abrir genomica",
        "description": "HRR, MSI/MMR, AR-V7, CDK12, HRD y trazabilidad molecular.",
        "group": "Gate pivote - genomica",
        "group_order": 81.3,
        "tokens": (
            "genomic", "genom", "germline", "somatic", "hrr", "brca",
            "atm", "palb2", "cdk12", "ar_v7", "ar-v7", "hrd",
            "msi", "mmr", "lynch", "molecular", "ngs", "pten",
        ),
    },
    "emergency": {
        "label": "Emergencia oncologica",
        "button_label": "Abrir emergencias",
        "description": "Compresion medular, crisis visceral, DIC, sangrado y alarmas urgentes.",
        "group": "Gate pivote - emergencia oncologica",
        "group_order": 81.4,
        "tokens": (
            "cord_compression", "spinal_cord", "epidural_compression",
            "visceral_crisis", "oncologic_emergency", "emergency",
            "dic_", "bleeding_active", "hematuria", "hypercalcemia",
            "fracture", "neurologic", "retention", "hydronephrosis",
        ),
    },
    "arpi_safety": {
        "label": "Seguridad ARPI / ADT",
        "button_label": "Abrir seguridad ARPI",
        "description": "Cardio, cognicion, convulsiones, metabolismo, higado y eventos ARPI.",
        "group": "Gate pivote - seguridad ARPI",
        "group_order": 81.5,
        "tokens": (
            "arpi", "arsi", "abiraterone", "abiraterona", "enzalutamide",
            "enzalutamida", "apalutamide", "apalutamida", "darolutamide",
            "darolutamida", "qtc", "lvef", "fevi", "seizure",
            "convulsion", "hypertension", "hipertension", "hepatotoxicity",
            "hepatotoxicidad", "hypothyroidism", "thyroid", "mobility",
            "fall_", "fall risk", "cognitive", "cognit", "adrenal",
            "cortisol", "steroid", "cholestatic", "alp_baseline_pre_abiraterone",
        ),
    },
    "taxane_safety": {
        "label": "Taxano",
        "button_label": "Abrir taxano",
        "description": "Docetaxel, cabazitaxel, neutropenia, neuropatia, diarrea e hipersensibilidad.",
        "group": "Gate pivote - taxano",
        "group_order": 81.6,
        "tokens": (
            "docetaxel", "cabazitaxel", "taxane", "taxano", "anc_",
            "rapid_anc", "neutropenia", "neutrophil", "neuropathy",
            "polysorbate", "hypersensitivity", "anaphylaxis",
            "diarrhea", "diarrea", "cumulative_docetaxel",
        ),
    },
    "parp_hrr": {
        "label": "PARP / HRR",
        "button_label": "Abrir PARP/HRR",
        "description": "PARPi, HRR, citopenias, MDS/AML, niraparib, olaparib y talazoparib.",
        "group": "Gate pivote - PARP/HRR",
        "group_order": 81.7,
        "tokens": (
            "parp", "parpi", "olaparib", "rucaparib", "niraparib",
            "talazoparib", "lynparza", "akeega", "talzenna", "rubraca",
            "mds", "aml", "smd", "lma", "bone_marrow", "blast",
            "platelet_drop_for_niraparib", "thrombocytopenia",
            "trombocitopenia", "cytopenia_for_parp", "hrr",
        ),
    },
    "psma_rlt": {
        "label": "PSMA-RLT",
        "button_label": "Abrir PSMA-RLT",
        "description": "Lu-177, Pluvicto, PSMA PET, radioligandos, actinio y clones PSMA negativos.",
        "group": "Gate pivote - PSMA-RLT",
        "group_order": 81.8,
        "tokens": (
            "psma", "lutetium", "lutecio", "lu-177", "lu177",
            "pluvicto", "radioligand", "radioligando", "actinium",
            "actinio", "xerostomia", "suvmax",
        ),
    },
    "radium_bone": {
        "label": "Ra-223 / soporte oseo",
        "button_label": "Abrir Ra-223/oseo",
        "description": "Ra-223, samario, calcio, DXA, FRAX y agentes modificadores oseos.",
        "group": "Gate pivote - Ra-223 y soporte oseo",
        "group_order": 81.9,
        "tokens": (
            "radium", "ra-223", "ra223", "xofigo", "samarium",
            "sm-153", "bone_modifying", "bone protection", "bone_protection",
            "denosumab", "zoledron", "hypocalcemia", "hipocalcemia",
            "calcium", "calcio", "fracture_risk", "fracture risk",
            "frax", "dxa", "osteoblastic",
        ),
    },
    "immunotherapy": {
        "label": "Inmunoterapia",
        "button_label": "Abrir inmunoterapia",
        "description": "Checkpoint inhibitors, sipuleucel-T y toxicidad inmunomediada.",
        "group": "Gate pivote - inmunoterapia",
        "group_order": 82.0,
        "tokens": (
            "immunotherapy", "inmunoterapia", "checkpoint", "pembrolizumab",
            "nivolumab", "ipilimumab", "sipuleucel", "provenge",
            "immune", "pneumonitis", "colitis", "hepatitis_immune",
            "hypophysitis", "thyroiditis", "immunosuppression", "hiv",
            "cd4", "irr_", "checkpoint_inhibitor", "msi", "tmb",
        ),
    },
    "progression_palliative": {
        "label": "Progresion / paliativo",
        "button_label": "Abrir progresion/paliativo",
        "description": "PCWG3, dolor, ECOG, opioides, RT paliativa, ESAS, PHQ-9, GAD-7 y caquexia.",
        "group": "Gate pivote - progresion y paliativo",
        "group_order": 82.1,
        "tokens": (
            "progression", "progresion", "pcwg3", "composite",
            "rpfs", "new_visceral", "new_liver", "new_lung", "new_cns",
            "new_lesion", "bpi_", "pain", "dolor", "opioid",
            "ecog_decline", "palliative", "paliativ", "sedation",
            "esas", "phq9", "gad7", "cachexia", "caquexia",
            "appetite", "dyspnea", "sbrt", "oligoprogression",
            "hemostatic_rt", "brain_metastases", "leptomeningeal",
        ),
    },
    "trial": {
        "label": "Ensayos / MDT",
        "button_label": "Abrir ensayos/MDT",
        "description": "Trial enrollment, protocolos, autorizaciones MDT y excepciones documentadas.",
        "group": "Gate pivote - ensayos y MDT",
        "group_order": 82.2,
        "tokens": (
            "trial", "ensayo", "protocol", "protocolo", "mdt_",
            "multidisciplinary", "consensus", "authorization", "override",
            "compassionate", "enrollment", "randomized",
        ),
    },
}


DEFAULT_GATE_FAMILIES_BY_MODULE: dict[str, set[str]] = {
    "m0_crpc": {"arpi_safety"},
    "mcspc_high_volume": {"arpi_safety"},
    "mcspc_high_volume_sync": {"arpi_safety"},
    "mcspc_high_volume_metachronous": {"arpi_safety"},
    "mcspc_low_volume_sync_oligo": {"arpi_safety"},
    "mcspc_oligo_metachronous": {"arpi_safety"},
}


CONTROL_FAMILY_ORDER = (
    "diagnostic_pre_biopsy",
    "local_decision",
    "genomic",
    "emergency",
    "arpi_safety",
    "taxane_safety",
    "parp_hrr",
    "psma_rlt",
    "radium_bone",
    "immunotherapy",
    "progression_palliative",
    "trial",
)


FIELD_FAMILY_OVERRIDES: dict[str, set[str]] = {
    "planned_systemic_regimen": {"radium_bone"},
    "considering_radium223": {"radium_bone"},
    "bone_modifying_agent": {"radium_bone"},
    "denosumab_prophylaxis": {"radium_bone"},
    "zoledronic_acid_prophylaxis": {"radium_bone"},
    "rapid_anc_drop_for_docetaxel": {"taxane_safety"},
    "anc_baseline_pre_docetaxel": {"taxane_safety"},
    "anc_recovered_post_drop_for_docetaxel": {"taxane_safety"},
    "cumulative_docetaxel_dose_mg_m2": {"taxane_safety"},
    "rapid_platelet_drop_for_niraparib": {"parp_hrr"},
    "platelets_baseline_pre_niraparib": {"parp_hrr"},
    "platelets_recovered_post_rapid_drop_for_niraparib": {"parp_hrr"},
    "bone_marrow_blasts_percent": {"parp_hrr"},
    "secondary_hematologic_malignancy": {"parp_hrr"},
    "prolonged_cytopenia_unexplained": {"parp_hrr"},
    "cytopenias_corrected_for_parp_inhibitor": {"parp_hrr"},
    "cytopenias_corrected_for_radioligand": {"psma_rlt"},
    "hypertension_grade3_for_niraparib": {"parp_hrr"},
    "hypertension_controlled_for_niraparib": {"parp_hrr"},
    "mds_aml_remission_for_parpi": {"parp_hrr"},
}


def normalize_gate_families(values: Iterable[str] | str | None) -> set[str]:
    """Normalize gate family query values.

    Accepts comma-separated strings or repeated query parameters. Unknown
    values are ignored so old links cannot break schema rendering.
    """
    if values is None:
        return set()
    raw_values: Iterable[str]
    if isinstance(values, str):
        raw_values = [values]
    else:
        raw_values = values

    known = set(GATE_FAMILY_DEFINITIONS) | {ALL_GATE_FAMILY}
    normalized: set[str] = set()
    for raw in raw_values:
        for item in str(raw or "").split(","):
            key = item.strip().lower().replace("-", "_")
            if key in known:
                normalized.add(key)
    return normalized


def default_gate_families_for_module(module_id: str) -> set[str]:
    module_key = str(module_id or "").strip()
    if module_key == "screening":
        module_key = "diagnostic_workup"
    return set(DEFAULT_GATE_FAMILIES_BY_MODULE.get(module_key, set()))


def effective_gate_families(module_id: str, requested: Iterable[str] | str | None) -> set[str]:
    selected = normalize_gate_families(requested)
    if ALL_GATE_FAMILY in selected:
        return set(GATE_FAMILY_DEFINITIONS)
    return default_gate_families_for_module(module_id) | selected


def merge_conditional_visibility(existing: Mapping[str, Any] | None, required: Mapping[str, Any] | None) -> dict[str, Any]:
    if not existing:
        return deepcopy(dict(required or {}))
    if not required:
        return deepcopy(dict(existing or {}))
    return {"__all__": [deepcopy(dict(required)), deepcopy(dict(existing))]}


def drop_visibility_key(conditions: Mapping[str, Any] | None, key_to_drop: str) -> dict[str, Any]:
    """Remove a wrapper condition while preserving unrelated visibility rules."""
    if not conditions:
        return {}
    if "__any__" in conditions and isinstance(conditions.get("__any__"), list):
        branches = [
            branch
            for branch in (drop_visibility_key(branch, key_to_drop) for branch in conditions["__any__"])
            if branch
        ]
        return {"__any__": branches} if branches else {}
    if "__all__" in conditions and isinstance(conditions.get("__all__"), list):
        branches = [
            branch
            for branch in (drop_visibility_key(branch, key_to_drop) for branch in conditions["__all__"])
            if branch
        ]
        if len(branches) == 1:
            return branches[0]
        return {"__all__": branches} if branches else {}
    return {
        key: deepcopy(value)
        for key, value in dict(conditions).items()
        if key != key_to_drop
    }


def filter_schema_for_wizard(
    schema: Mapping[str, Any],
    module_id: str,
    *,
    gate_families: Iterable[str] | str | None = None,
) -> dict[str, Any]:
    """Return a wizard-safe schema without deleting the public schema contract.

    Only presentation copies are filtered. Evaluation, audit coverage and the
    default schema endpoint can keep consuming the complete FieldSpec catalog.
    """
    filtered = deepcopy(dict(schema))
    selected = normalize_gate_families(gate_families)
    effective = effective_gate_families(module_id, selected)
    include_all = ALL_GATE_FAMILY in selected
    retained_fields: list[dict[str, Any]] = []
    removed_count = 0
    retained_pivotal_count = 0
    duplicate_count = 0
    seen_names: set[str] = set()

    for raw_field in list(filtered.get("fields") or []):
        field = deepcopy(dict(raw_field))
        field_name = str(field.get("name") or "")
        if field_name and field_name in seen_names:
            duplicate_count += 1
            continue
        if field_name:
            seen_names.add(field_name)
        if not is_pivotal_gate_support_field(field):
            retained_fields.append(field)
            continue

        families = classify_pivotal_gate_field(field)
        should_keep = include_all or bool(families & effective)
        if not should_keep:
            removed_count += 1
            continue

        retained_pivotal_count += 1
        family_key = _selected_family_for_field(families, effective, include_all=include_all)
        family_def = GATE_FAMILY_DEFINITIONS.get(family_key, {})
        if family_def:
            field["group"] = family_def["group"]
            field["group_order"] = family_def["group_order"]
            field["pivotal_gate_family"] = family_key
            field["pivotal_gate_family_label"] = family_def["label"]
        field["conditional_visibility"] = drop_visibility_key(
            field.get("conditional_visibility") or {},
            "show_advanced_pivotal_gates",
        )
        retained_fields.append(field)

    filtered["fields"] = retained_fields
    filtered["pivotal_gate_disclosure"] = {
        "surface": "wizard",
        "requested_families": sorted(selected),
        "default_families": sorted(default_gate_families_for_module(module_id)),
        "effective_families": sorted(effective),
        "include_all": include_all,
        "removed_pivotal_fields": removed_count,
        "retained_pivotal_fields": retained_pivotal_count,
        "removed_duplicate_fields": duplicate_count,
    }
    return filtered


def build_gate_family_control_state(
    module_id: str,
    *,
    requested: Iterable[str] | str | None = None,
) -> dict[str, Any]:
    selected = normalize_gate_families(requested)
    defaults = default_gate_families_for_module(module_id)
    effective = effective_gate_families(module_id, selected)
    include_all = ALL_GATE_FAMILY in selected
    controls = []
    for key in CONTROL_FAMILY_ORDER:
        family_def = GATE_FAMILY_DEFINITIONS[key]
        controls.append({
            "key": key,
            "label": family_def["button_label"],
            "family_label": family_def["label"],
            "description": family_def["description"],
            "active": include_all or key in effective,
            "selected": key in selected,
            "default_active": key in defaults,
        })
    controls.append({
        "key": ALL_GATE_FAMILY,
        "label": "Ver todos los gates avanzados",
        "family_label": "Todos",
        "description": "Abre todo el catalogo pivotal para auditoria o captura excepcional.",
        "active": include_all,
        "selected": include_all,
        "default_active": False,
    })
    return {
        "requested_families": sorted(selected),
        "default_families": sorted(defaults),
        "effective_families": sorted(effective),
        "include_all": include_all,
        "controls": controls,
    }


def is_pivotal_gate_support_field(field: Mapping[str, Any]) -> bool:
    return str(field.get("group") or "").strip() == PIVOTAL_GATE_GROUP


def classify_pivotal_gate_field(field: Mapping[str, Any]) -> set[str]:
    field_name = str(field.get("name") or "").strip()
    if field_name in FIELD_FAMILY_OVERRIDES:
        return set(FIELD_FAMILY_OVERRIDES[field_name])

    name = _normalize_text(field.get("name", ""))
    text = _field_search_text(field)
    families: set[str] = set()
    for key, family_def in GATE_FAMILY_DEFINITIONS.items():
        tokens = tuple(family_def.get("tokens") or ())
        if name in {_normalize_text(token) for token in tokens}:
            families.add(key)
            continue
        if any(_token_matches_family_text(token, text) for token in tokens):
            families.add(key)
    if not families:
        families.add("trial")
    return families


def _selected_family_for_field(
    families: set[str],
    effective: set[str],
    *,
    include_all: bool,
) -> str:
    preferred = families if include_all else families & effective
    for key in CONTROL_FAMILY_ORDER:
        if key in preferred:
            return key
    return next(iter(preferred or families or {"trial"}))


def _field_search_text(field: Mapping[str, Any]) -> str:
    evidence_tags = field.get("evidence_tags") or []
    if isinstance(evidence_tags, (list, tuple, set)):
        tags_text = " ".join(str(item) for item in evidence_tags)
    else:
        tags_text = str(evidence_tags)
    parts = [
        field.get("name", ""),
        field.get("label", ""),
        field.get("help_text", ""),
        field.get("group", ""),
        tags_text,
    ]
    return _normalize_text(" ".join(str(part or "") for part in parts))


def _token_matches_family_text(token: Any, normalized_text: str) -> bool:
    normalized_token = _normalize_text(token)
    if not normalized_token:
        return False
    if normalized_token in {"arpi", "arsi"}:
        return re.search(rf"(?<![a-z0-9]){re.escape(normalized_token)}(?![a-z0-9])", normalized_text) is not None
    return normalized_token in normalized_text


def _normalize_text(value: Any) -> str:
    text = str(value or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text.replace("-", "_")
