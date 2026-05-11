from __future__ import annotations

from typing import Any


PRO_BAND_DEFINITIONS: dict[str, dict[str, Any]] = {
    "eq5d_vas_band": {
        "numeric_field": "eq5d_vas",
        "default_band": "60_79",
        "bands": {
            "80_100": {
                "representative_value": 90,
                "min": 80,
                "max": 100,
                "label": "80-100 - Calidad de vida alta - tolerancia funcional global alta",
            },
            "60_79": {
                "representative_value": 70,
                "min": 60,
                "max": 79,
                "label": "60-79 - Compromiso leve - compromiso funcional leve",
            },
            "40_59": {
                "representative_value": 50,
                "min": 40,
                "max": 59,
                "label": "40-59 - Compromiso moderado - compromiso funcional moderado",
            },
            "lt_40": {
                "representative_value": 20,
                "min": None,
                "max": 39,
                "label": "<40 - Calidad de vida muy baja - tolerancia funcional críticamente comprometida",
            },
        },
    },
    "fact_p_total_band": {
        "numeric_field": "fact_p_total",
        "default_band": "90_109",
        "bands": {
            "gte_110": {
                "representative_value": 115,
                "min": 110,
                "max": None,
                "label": ">=110 - Bien conservado - carga sintomática y funcional baja",
            },
            "90_109": {
                "representative_value": 100,
                "min": 90,
                "max": 109,
                "label": "90-109 - Afectación leve - compromiso sintomático leve",
            },
            "70_89": {
                "representative_value": 80,
                "min": 70,
                "max": 89,
                "label": "70-89 - Afectación moderada - carga sintomática y funcional intermedia",
            },
            "lt_70": {
                "representative_value": 60,
                "min": None,
                "max": 69,
                "label": "<70 - Afectación marcada - carga sintomática y funcional alta",
            },
        },
    },
    "bpi_worst_pain_band": {
        "numeric_field": "bpi_worst_pain",
        "default_band": "0_3",
        "bands": {
            "0_3": {
                "representative_value": 2,
                "min": 0,
                "max": 3,
                "label": "0-3 - Dolor leve - controlable con analgesia habitual",
            },
            "4_6": {
                "representative_value": 5,
                "min": 4,
                "max": 6,
                "label": "4-6 - Dolor moderado - requiere escalamiento analgésico y reevaluación",
            },
            "7_10": {
                "representative_value": 8,
                "min": 7,
                "max": 10,
                "label": "7-10 - Dolor severo - exige control sintomático urgente",
            },
        },
    },
    "fatigue_score_band": {
        "numeric_field": "fatigue_score",
        "default_band": "0_3",
        "bands": {
            "0_3": {
                "representative_value": 2,
                "min": 0,
                "max": 3,
                "label": "0-3 - Fatiga leve - actividad global conservada",
            },
            "4_6": {
                "representative_value": 5,
                "min": 4,
                "max": 6,
                "label": "4-6 - Fatiga moderada - limita parcialmente actividad y tolerancia",
            },
            "7_10": {
                "representative_value": 8,
                "min": 7,
                "max": 10,
                "label": "7-10 - Fatiga severa - limita de forma importante actividad y tratamiento",
            },
        },
    },
}

PRO_BAND_OPTIONS: dict[str, list[str]] = {
    key: list(config["bands"].keys())
    for key, config in PRO_BAND_DEFINITIONS.items()
}

DDI_REVIEW_STATUS_OPTIONS = ["not_started", "in_progress", "completed"]
DDI_REVIEW_STATUS_LABELS = {
    "not_started": "No iniciada - falta revisión formal de interacciones",
    "in_progress": "En curso - revisión parcial, aún no cerrada",
    "completed": "Completada - revisión formal cerrada",
}

MINI_COG_OPTIONS = ["0", "1", "2", "3", "4", "5"]
MINI_COG_OPTION_LABELS = {
    "0": "0 - Severamente anormal - deterioro cognitivo altamente probable",
    "1": "1 - Muy alterado - deterioro cognitivo probable",
    "2": "2 - Alterado - cribado positivo, requiere cautela clínica",
    "3": "3 - Límite / conservado - cribado generalmente no sugestivo",
    "4": "4 - Conservado - función cognitiva preservada",
    "5": "5 - Conservado óptimo - función cognitiva preservada",
}

COGNITIVE_SCREEN_SOURCE_OPTIONS = [
    "bedside_clinic",
    "caregiver_supported",
    "document_imported",
    "external_assessment",
]
COGNITIVE_SCREEN_SOURCE_LABELS = {
    "bedside_clinic": "Tamiz en consulta",
    "caregiver_supported": "Tamiz con apoyo de cuidador",
    "document_imported": "Importado de documento clínico",
    "external_assessment": "Valoración externa previa",
}

ADVANCED_VARIANT_HISTOLOGY_OPTIONS = [
    "none",
    "ductal_predominant",
    "sarcomatoid",
    "signet_ring",
    "adenosquamous_or_squamous",
    "basal_cell",
    "mucinous_colloid",
    "small_cell_neuroendocrine",
    "mixed_multiple",
    "other_aggressive",
    "other_aggressive_unspecified",
]

ADVANCED_VARIANT_HISTOLOGY_LABELS = {
    "none": "Sin variante adversa adicional",
    "ductal_predominant": "Predominio ductal",
    "sarcomatoid": "Sarcomatoide",
    "signet_ring": "Células en anillo de sello",
    "adenosquamous_or_squamous": "Adenoescamoso o escamoso",
    "basal_cell": "Células basales",
    "mucinous_colloid": "Mucinoso / coloide",
    "small_cell_neuroendocrine": "Neuroendocrino de célula pequeña",
    "mixed_multiple": "Mixta / múltiple",
    "other_aggressive": "Otra agresiva",
    "other_aggressive_unspecified": "Otra agresiva no especificada",
}

REGIMEN_ONCOLOGY_DRUGS: dict[str, list[str]] = {
    "ADT_DAROLUTAMIDE": ["darolutamida"],
    "ADT_ENZALUTAMIDE": ["enzalutamida"],
    "ADT_APALUTAMIDE": ["apalutamida"],
    "ADT_ABIRATERONE": ["abiraterona"],
    "ADT_DOCETAXEL": ["docetaxel"],
    "ADT_DOCETAXEL_DAROLUTAMIDE": ["docetaxel", "darolutamida"],
    "ADT_DOCETAXEL_ABIRATERONE": ["docetaxel", "abiraterona"],
    "DOCETAXEL": ["docetaxel"],
    "OLAPARIB": ["olaparib"],
}

STATE_CANDIDATE_REGIMENS: dict[str, list[str]] = {
    "m0_crpc": ["ADT_DAROLUTAMIDE", "ADT_ENZALUTAMIDE", "ADT_APALUTAMIDE"],
    "m1_crpc": ["ADT_ENZALUTAMIDE", "ADT_ABIRATERONE", "DOCETAXEL"],
    "mcspc_low_volume_sync_oligo": ["ADT_DAROLUTAMIDE", "ADT_ENZALUTAMIDE", "ADT_APALUTAMIDE", "ADT_ABIRATERONE"],
    "mcspc_oligo_metachronous": ["ADT_DAROLUTAMIDE", "ADT_ENZALUTAMIDE", "ADT_APALUTAMIDE", "ADT_ABIRATERONE"],
    "mcspc_high_volume": [
        "ADT_DOCETAXEL_DAROLUTAMIDE",
        "ADT_DOCETAXEL_ABIRATERONE",
        "ADT_DAROLUTAMIDE",
        "ADT_ENZALUTAMIDE",
        "ADT_APALUTAMIDE",
        "ADT_ABIRATERONE",
    ],
    "mcspc_high_volume_sync": [
        "ADT_DOCETAXEL_DAROLUTAMIDE",
        "ADT_DOCETAXEL_ABIRATERONE",
        "ADT_DAROLUTAMIDE",
        "ADT_ENZALUTAMIDE",
        "ADT_APALUTAMIDE",
        "ADT_ABIRATERONE",
    ],
    "mcspc_high_volume_metachronous": [
        "ADT_DOCETAXEL_DAROLUTAMIDE",
        "ADT_DOCETAXEL_ABIRATERONE",
        "ADT_DAROLUTAMIDE",
        "ADT_ENZALUTAMIDE",
        "ADT_APALUTAMIDE",
        "ADT_ABIRATERONE",
    ],
    "recurrence_bcr": ["ADT_ENZALUTAMIDE"],
}


def pro_band_numeric_field(band_field: str) -> str | None:
    return PRO_BAND_DEFINITIONS.get(band_field, {}).get("numeric_field")


def pro_band_label_map(band_field: str) -> dict[str, str]:
    config = PRO_BAND_DEFINITIONS.get(band_field, {})
    return {
        band_key: str(band_meta.get("label") or band_key)
        for band_key, band_meta in dict(config.get("bands") or {}).items()
    }


def pro_band_representative_value(band_field: str, band_value: Any) -> int | None:
    config = PRO_BAND_DEFINITIONS.get(band_field, {})
    band_meta = dict(config.get("bands") or {}).get(str(band_value or ""))
    if not band_meta:
        return None
    try:
        return int(float(band_meta.get("representative_value")))
    except (TypeError, ValueError):
        return None


def derive_pro_band_from_numeric(band_field: str, numeric_value: Any) -> str:
    config = PRO_BAND_DEFINITIONS.get(band_field, {})
    try:
        score = float(numeric_value)
    except (TypeError, ValueError):
        return str(config.get("default_band") or "")
    for band_key, band_meta in dict(config.get("bands") or {}).items():
        minimum = band_meta.get("min")
        maximum = band_meta.get("max")
        if minimum is not None and score < float(minimum):
            continue
        if maximum is not None and score > float(maximum):
            continue
        return str(band_key)
    return str(config.get("default_band") or "")
