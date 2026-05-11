from __future__ import annotations

from prostanet.presentation.v2_adapters import quick_classify_schema, stage_specific_intake_schema
from prostanet.shared.contracts import FieldSpec
from prostanet.shared.presentation_text import humanize_schema


def _assert_no_raw_zero_one_labels(fields: list[dict]) -> None:
    offenders: list[str] = []
    for field in fields:
        if field.get("field_type") != "select":
            continue
        for option in field.get("display_options") or []:
            if str(option.get("value")) in {"0", "1"} and str(option.get("label")) in {"0", "1"}:
                offenders.append(f"{field.get('name')}={option.get('label')}")
    assert offenders == []


def test_fieldspec_binary_options_get_clinical_display_labels() -> None:
    field = FieldSpec("psma_pet_done", "PSMA-PET realizado", "select", options=["0", "1"], default="0").to_dict()

    labels = {str(option["value"]): option["label"] for option in field["display_options"]}

    assert labels == {"0": "No realizado", "1": "Realizado"}


def test_stage_aware_quick_schema_does_not_expose_raw_binary_labels() -> None:
    schema = quick_classify_schema()

    _assert_no_raw_zero_one_labels(schema["fields"])


def test_stage_specific_schema_does_not_expose_raw_binary_labels() -> None:
    schema = stage_specific_intake_schema("m1_crpc")

    _assert_no_raw_zero_one_labels(schema["fields"])


def test_humanized_module_schema_preserves_explicit_display_options() -> None:
    schema = humanize_schema(
        {
            "module": "localized_initial",
            "title": "Localized",
            "description": "",
            "fields": [
                FieldSpec(
                    "confirmatory_biopsy_planned",
                    "Biopsia confirmatoria planeada",
                    "select",
                    options=["0", "1"],
                    display_options=[
                        {"value": "0", "label": "No planificada"},
                        {"value": "1", "label": "Sí, planificada"},
                    ],
                ).to_dict()
            ],
        }
    )

    labels = {str(option["value"]): option["label"] for option in schema["fields"][0]["display_options"]}
    assert labels == {"0": "No planificada", "1": "Sí, planificada"}
