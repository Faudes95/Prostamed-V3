from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from docx import Document


DEFAULT_REFERENCE_ROOT = Path(
    os.environ.get(
        "PROSTANET_MHSPC_REFERENCE_ROOT",
        Path.cwd() / ".prostanet_private" / "mhspc_frontline_reference",
    )
)

SOURCE_DOCUMENTS = [
    {
        "document_id": "farmacos_cancer_prostata_imss_2026",
        "title": "Fármacos cáncer de próstata",
        "document_type": "pptx",
        "path": "/Users/oscaralvarado/Downloads/FÁRMACOS CANCER DE PROSTATA .pptx",
        "role": "drug_reference",
    },
    {
        "document_id": "astellas_speak_raza_2026",
        "title": "ASTELLAS SPEAK La Raza Especialidades IMSS 17.03.2026",
        "document_type": "pptx",
        "path": "/Users/oscaralvarado/Downloads/ASTELLAS SPEAK LA RAZA ESPECIALIDADES IMSS 17.03.2026.pptx",
        "role": "trial_eligibility_context",
    },
    {
        "document_id": "resumen_mcspc_dobletes_tripletes",
        "title": "Resumen mCSPC dobletes y tripletes",
        "document_type": "docx",
        "path": "/Users/oscaralvarado/Downloads/resumen_mCSPC_dobletes_tripletes.docx",
        "role": "clinical_synthesis",
    },
]

CURRENT_CATALOG_COMPONENTS = {
    "ADT": {
        "drug_name": "ADT",
        "dose": "Según agonista/antagonista seleccionado",
        "route": "Subcutánea / intramuscular",
        "schedule": "Continuo para mantener testosterona en rango de castración",
        "imss_key": "",
        "metadata_source": "current_catalog",
        "toxicity_watchouts": [
            "Bochornos",
            "Desmineralización ósea",
            "Riesgo cardiometabólico",
        ],
        "contraindications": [],
    },
    "Docetaxel": {
        "drug_name": "Docetaxel",
        "dose": "75 mg/m²",
        "route": "Intravenosa",
        "schedule": "Cada 21 días por 6 ciclos",
        "imss_key": "",
        "metadata_source": "current_catalog",
        "toxicity_watchouts": [
            "Neutropenia",
            "Neuropatía periférica",
            "Fatiga",
            "Toxicidad hepática",
        ],
        "contraindications": [
            "ECOG > 1",
            "Neuropatía periférica grado 2 o mayor",
            "Child-Pugh C",
        ],
    },
    "Cabazitaxel": {
        "drug_name": "Cabazitaxel",
        "dose": "20-25 mg/m²",
        "route": "Intravenosa",
        "schedule": "Cada 21 días con soporte y prednisona concomitante",
        "imss_key": "",
        "metadata_source": "current_catalog",
        "toxicity_watchouts": [
            "Neutropenia",
            "Diarrea",
            "Fatiga",
            "Toxicidad hematológica",
        ],
        "contraindications": [
            "Neutropenia no controlada",
            "Fragilidad marcada",
            "Toxicidad hematológica limitante",
        ],
    },
    "Talazoparib": {
        "drug_name": "Talazoparib",
        "dose": "0.5 mg al día",
        "route": "Oral",
        "schedule": "Continuo",
        "imss_key": "",
        "metadata_source": "current_catalog",
        "toxicity_watchouts": [
            "Anemia",
            "Fatiga",
            "Trombocitopenia",
        ],
        "contraindications": [
            "Toxicidad hematológica grave",
        ],
    },
    "Niraparib": {
        "drug_name": "Niraparib",
        "dose": "200 mg al día",
        "route": "Oral",
        "schedule": "Continuo",
        "imss_key": "",
        "metadata_source": "current_catalog",
        "toxicity_watchouts": [
            "Anemia",
            "Trombocitopenia",
            "Hipertensión",
        ],
        "contraindications": [
            "Trombocitopenia no controlada",
        ],
    },
    "Rucaparib": {
        "drug_name": "Rucaparib",
        "dose": "600 mg cada 12 horas",
        "route": "Oral",
        "schedule": "Continuo",
        "imss_key": "",
        "metadata_source": "current_catalog",
        "toxicity_watchouts": [
            "Anemia",
            "Fatiga",
            "Náusea",
        ],
        "contraindications": [
            "Toxicidad hematológica severa",
        ],
    },
    "Lu177-PSMA-617": {
        "drug_name": "Lu177-PSMA-617",
        "dose": "7.4 GBq",
        "route": "Intravenosa",
        "schedule": "Cada 6 semanas hasta 6 ciclos",
        "imss_key": "",
        "metadata_source": "current_catalog",
        "toxicity_watchouts": [
            "Xerostomía",
            "Fatiga",
            "Toxicidad hematológica",
        ],
        "contraindications": [
            "Lesiones dominantes PSMA-negativas",
            "PSMA-PET no concluyente",
        ],
    },
    "Radio-223": {
        "drug_name": "Radio-223",
        "dose": "55 kBq/kg",
        "route": "Intravenosa",
        "schedule": "Cada 4 semanas por 6 dosis",
        "imss_key": "",
        "metadata_source": "current_catalog",
        "toxicity_watchouts": [
            "Trombocitopenia",
            "Anemia",
            "Dolor óseo transitorio",
        ],
        "contraindications": [
            "Metástasis viscerales",
            "Citopenias no corregidas",
        ],
    },
    "Pembrolizumab": {
        "drug_name": "Pembrolizumab",
        "dose": "200 mg",
        "route": "Intravenosa",
        "schedule": "Cada 3 semanas",
        "imss_key": "",
        "metadata_source": "current_catalog",
        "toxicity_watchouts": [
            "Eventos inmunomediados",
            "Hepatitis autoinmune",
            "Colitis",
        ],
        "contraindications": [
            "Autoinmunidad activa no controlada",
        ],
    },
    "Carboplatino": {
        "drug_name": "Carboplatino",
        "dose": "AUC 4-5",
        "route": "Intravenosa",
        "schedule": "Cada 21 días",
        "imss_key": "",
        "metadata_source": "current_catalog",
        "toxicity_watchouts": [
            "Toxicidad hematológica",
            "Fatiga",
        ],
        "contraindications": [
            "Citopenias severas",
        ],
    },
    "Etopósido": {
        "drug_name": "Etopósido",
        "dose": "100 mg/m²",
        "route": "Intravenosa / oral",
        "schedule": "Días 1-3 cada 21 días",
        "imss_key": "",
        "metadata_source": "current_catalog",
        "toxicity_watchouts": [
            "Neutropenia",
            "Mucositis",
        ],
        "contraindications": [
            "Citopenias severas",
        ],
    },
    "Ipatasertib": {
        "drug_name": "Ipatasertib",
        "dose": "400 mg al día",
        "route": "Oral",
        "schedule": "Días 1-21 de cada ciclo",
        "imss_key": "",
        "metadata_source": "current_catalog",
        "toxicity_watchouts": [
            "Diarrea",
            "Hiperglucemia",
            "Rash",
        ],
        "contraindications": [
            "Hiperglucemia descontrolada",
        ],
    },
}

CURATED_COMPONENTS = {
    "Abiraterona": {
        "drug_name": "Abiraterona",
        "dose": "1000 mg al día",
        "route": "Oral",
        "schedule": "Diario, en ayuno; acompañar con prednisona 5 mg VO cada 12 horas",
        "imss_key": "010.00.5657.00",
        "metadata_source": "institutional_ingested_document",
        "toxicity_watchouts": [
            "Fatiga",
            "Hipertensión",
            "Hipokalemia",
            "Edema periférico",
            "Elevación de transaminasas",
        ],
        "contraindications": [
            "Cardiopatía o evento vascular cerebral relevante",
            "Child-Pugh B o C",
            "Uso de diurético de asa",
            "Diabetes mal controlada con mala tolerancia a esteroides",
            "Pacientes propensos a edema periférico",
        ],
        "source_documents": [
            "farmacos_cancer_prostata_imss_2026",
            "astellas_speak_raza_2026",
        ],
    },
    "Apalutamida": {
        "drug_name": "Apalutamida",
        "dose": "240 mg al día",
        "route": "Oral",
        "schedule": "4 tabletas juntas cada 24 horas",
        "imss_key": "010.000.6350.00",
        "metadata_source": "institutional_ingested_document",
        "toxicity_watchouts": [
            "Fatiga",
            "Hipertensión",
            "Rash cutáneo",
            "Hipotiroidismo",
            "Trastornos cognitivos",
        ],
        "contraindications": [
            "Antecedentes de convulsiones",
            "Antecedente de rash cutáneo severo",
        ],
        "source_documents": [
            "farmacos_cancer_prostata_imss_2026",
            "resumen_mcspc_dobletes_tripletes",
        ],
    },
    "Enzalutamida": {
        "drug_name": "Enzalutamida",
        "dose": "160 mg al día",
        "route": "Oral",
        "schedule": "4 cápsulas juntas cada 24 horas",
        "imss_key": "010.000.6097.00",
        "metadata_source": "institutional_ingested_document",
        "toxicity_watchouts": [
            "Fatiga",
            "Hipertensión",
            "Bochornos",
            "Mareo y caídas",
            "Trastornos cognitivos",
        ],
        "contraindications": [
            "Antecedentes de convulsiones",
            "Evento vascular cerebral o lesión cerebral previa",
            "Riesgo cardiovascular elevado",
        ],
        "source_documents": [
            "farmacos_cancer_prostata_imss_2026",
            "resumen_mcspc_dobletes_tripletes",
        ],
    },
    "Darolutamida": {
        "drug_name": "Darolutamida",
        "dose": "1200 mg al día",
        "route": "Oral",
        "schedule": "2 tabletas cada 12 horas",
        "imss_key": "010.000.7076.00",
        "metadata_source": "institutional_ingested_document",
        "toxicity_watchouts": [
            "Fatiga",
            "Hipertensión",
            "Caídas",
            "Trastornos cognitivos",
        ],
        "contraindications": [
            "Insuficiencia renal grave (15-29 mL/min/1.73m²)",
            "Child-Pugh B o C",
        ],
        "source_documents": [
            "farmacos_cancer_prostata_imss_2026",
            "resumen_mcspc_dobletes_tripletes",
        ],
    },
    "Olaparib": {
        "drug_name": "Olaparib",
        "dose": "300 mg cada 12 horas",
        "route": "Oral",
        "schedule": "Continuo",
        "imss_key": "010.000.6358.00 / 010.000.6359.00",
        "metadata_source": "institutional_ingested_document",
        "toxicity_watchouts": [
            "Anemia",
            "Fatiga",
            "Náusea / anorexia",
            "Trombocitopenia",
            "Neutropenia",
        ],
        "contraindications": [
            "Síndrome mielodisplásico previo",
            "Hipersensibilidad al fármaco",
        ],
        "source_documents": [
            "farmacos_cancer_prostata_imss_2026",
        ],
    },
}

REGIMEN_PIVOTAL_TRIALS = {
    "ADT_DAROLUTAMIDE": ["ARANOTE"],
    "ADT_ENZALUTAMIDE": ["ARCHES", "ENZAMET"],
    "ADT_APALUTAMIDE": ["TITAN"],
    "ADT_ABIRATERONE": ["LATITUDE"],
    "ADT_DOCETAXEL_DAROLUTAMIDE": ["ARASENS"],
    "ADT_DOCETAXEL_ABIRATERONE": ["PEACE-1"],
    "RT_PRIMARY_LOW_VOLUME": ["STAMPEDE RT"],
    "ADT_DOCETAXEL": ["CHAARTED"],
}

_REFERENCE_CACHE: dict[tuple[str, tuple[tuple[str, bool, int, int], ...]], dict[str, Any]] = {}


def _normalize_text(value: str) -> str:
    return " ".join((value or "").split())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _extract_pptx_text(path: Path) -> dict[str, Any]:
    slides: list[dict[str, Any]] = []
    with ZipFile(path) as archive:
        slide_names = sorted(
            name
            for name in archive.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )
        for slide_name in slide_names:
            root = ET.fromstring(archive.read(slide_name))
            namespace = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
            texts = [_normalize_text(node.text or "") for node in root.findall(".//a:t", namespace) if _normalize_text(node.text or "")]
            slides.append(
                {
                    "slide_id": slide_name,
                    "texts": texts,
                    "joined_text": " | ".join(texts),
                }
            )
    return {"slides": slides}


def _extract_docx_text(path: Path) -> dict[str, Any]:
    document = Document(str(path))
    paragraphs = []
    for index, paragraph in enumerate(document.paragraphs, start=1):
        text = _normalize_text(paragraph.text)
        if text:
            paragraphs.append({"paragraph": index, "text": text})
    return {"paragraphs": paragraphs}


def build_raw_ingestion_snapshot() -> dict[str, Any]:
    snapshot = {
        "version": "mhspc_frontline_reference_v1",
        "documents": [],
    }
    for source in SOURCE_DOCUMENTS:
        path = Path(source["path"])
        item = {
            "document_id": source["document_id"],
            "title": source["title"],
            "document_type": source["document_type"],
            "role": source["role"],
            "source_path": str(path),
        }
        if not path.exists() or not path.is_file():
            item["status"] = "missing_source"
            snapshot["documents"].append(item)
            continue
        item["status"] = "loaded"
        item["sha256"] = _sha256(path)
        if source["document_type"] == "pptx":
            item["extracted"] = _extract_pptx_text(path)
        elif source["document_type"] == "docx":
            item["extracted"] = _extract_docx_text(path)
        else:
            item["extracted"] = {}
        snapshot["documents"].append(item)
    return snapshot


def build_curated_treatment_reference() -> dict[str, Any]:
    curated = {
        "version": "mhspc_frontline_reference_v1",
        "components": {},
        "current_catalog_components": CURRENT_CATALOG_COMPONENTS,
        "regimen_trials": REGIMEN_PIVOTAL_TRIALS,
        "selection_principles": [
            "El tratamiento del mCSPC se selecciona por fenotipo clínico, aptitud para docetaxel y perfil de toxicidad.",
            "Darolutamida no debe liderar por default; solo cuando el perfil neurológico, cognitivo o cardiovascular la favorece.",
            "La evidencia de doblete/triplete debe mapearse al subescenario trial-like y no extrapolarse sin contexto.",
        ],
    }
    for component_name, metadata in CURATED_COMPONENTS.items():
        curated["components"][component_name] = metadata
    return curated


def _reference_signature() -> tuple[tuple[str, bool, int, int], ...]:
    signature: list[tuple[str, bool, int, int]] = []
    for source in SOURCE_DOCUMENTS:
        path = Path(source["path"])
        if path.exists() and path.is_file():
            stat = path.stat()
            signature.append((str(path), True, int(stat.st_mtime_ns), int(stat.st_size)))
        else:
            signature.append((str(path), False, 0, 0))
    return tuple(signature)


def ensure_mhspc_frontline_reference(root: Path | None = None) -> dict[str, Any]:
    reference_root = Path(root or DEFAULT_REFERENCE_ROOT)
    reference_root.mkdir(parents=True, exist_ok=True)
    cache_key = (str(reference_root), _reference_signature())
    cached = _REFERENCE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    raw_snapshot = build_raw_ingestion_snapshot()
    curated_reference = build_curated_treatment_reference()
    raw_path = reference_root / "raw_ingestion_snapshot.json"
    curated_path = reference_root / "curated_treatment_reference.json"
    raw_path.write_text(json.dumps(raw_snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    curated_path.write_text(json.dumps(curated_reference, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {
        "root": str(reference_root),
        "raw_snapshot_path": str(raw_path),
        "curated_reference_path": str(curated_path),
        "raw_snapshot": raw_snapshot,
        "curated_reference": curated_reference,
    }
    _REFERENCE_CACHE.clear()
    _REFERENCE_CACHE[cache_key] = result
    return result


def get_mhspc_frontline_reference() -> dict[str, Any]:
    return ensure_mhspc_frontline_reference()["curated_reference"]


def component_metadata(drug_name: str) -> dict[str, Any]:
    curated = get_mhspc_frontline_reference()
    components = dict(curated.get("components") or {})
    fallback = dict(curated.get("current_catalog_components") or {})
    if drug_name in components:
        return dict(components[drug_name])
    if drug_name in fallback:
        return dict(fallback[drug_name])
    return {
        "drug_name": drug_name,
        "dose": "",
        "route": "",
        "schedule": "",
        "imss_key": "",
        "metadata_source": "current_catalog",
        "toxicity_watchouts": [],
        "contraindications": [],
    }
