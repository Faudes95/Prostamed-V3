# -*- coding: utf-8 -*-
"""
Synthetic Spanish Clinical Document Generator.

Generates realistic Spanish-language clinical documents for:
  1. NLP extractor evaluation and regression testing
  2. Document ingestion pipeline testing
  3. Training data for future BETO fine-tuning

Document types generated:
  - pathology_report:    Biopsias de próstata con Gleason, TNM, cores, invasión
  - laboratory_bundle:   Paquetes de laboratorio con PSA, biometría, perfil bioquímico
  - imaging_report:      TAC, gammagrama óseo, PET-PSMA, RMN pelvis, RMN columna
  - genomic_report:      Perfil molecular con HRR, BRCA, MSI, AR-V7, PSMA
  - surgery_summary:     Resúmenes de prostatectomía radical con hallazgos patológicos
  - radiotherapy_summary:Resúmenes de radioterapia con dosis, volúmenes y toxicidad

Usage::

    from prostanet.ai.training.synthetic_clinical_docs import SyntheticDocumentGenerator
    gen = SyntheticDocumentGenerator(seed=42)
    docs = gen.generate_batch(n=200, document_types=None)  # All types
    gen.save_jsonl(docs, "output/synthetic_docs.jsonl")

    # Or single doc
    doc = gen.generate_one("pathology_report")
    # doc.text, doc.ground_truth, doc.document_type
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any


# ══════════════════════════════════════════════════════════════════════════════
# Clinical vocabularies
# ══════════════════════════════════════════════════════════════════════════════

_INSTITUCIONES = [
    "Hospital General de México", "IMSS CMN Siglo XXI", "Instituto Nacional de Cancerología",
    "Hospital de Oncología CMN Siglo XXI", "Hospital Ángeles Pedregal",
    "Centro Médico Nacional La Raza", "Hospital Juárez de México",
    "Hospital Regional ISSSTE", "Clínica Londres", "Hospital San Ángel Inn",
]

_PATOLOGOS = [
    "Dra. María González Reyes", "Dr. Carlos Mendoza López", "Dra. Ana Jiménez Castro",
    "Dr. Roberto Sánchez Torres", "Dra. Lucía Hernández Vega", "Dr. Ignacio Ruiz Morales",
]

_ONCOLOGOS = [
    "Dr. Alejandro Pérez Alvarado", "Dra. Patricia Ramírez Gutiérrez",
    "Dr. Sergio Flores Núñez", "Dra. Carmen Vidal Espinoza",
    "Dr. Miguel Ángel Torres Cruz",
]

_GLEASON_PATTERNS = [
    (3, 3, 1), (3, 4, 2), (4, 3, 2), (4, 4, 3), (4, 5, 4), (5, 4, 4), (5, 5, 5)
]  # (primary, secondary, isup)

_TNMS = [
    ("T1c", "N0", "M0"), ("T2a", "N0", "M0"), ("T2b", "N0", "M0"),
    ("T2c", "N0", "M0"), ("T3a", "N0", "M0"), ("T3b", "N0", "M0"),
    ("T3a", "N1", "M0"), ("T4", "N1", "M1b"), ("T3b", "N1", "M1b"),
]

_DRUGS = [
    "enzalutamida 160 mg", "abiraterona 1000 mg + prednisona 10 mg",
    "docetaxel 75 mg/m² + prednisona", "cabazitaxel 25 mg/m²",
    "apalutamida 240 mg", "darolutamida 600 mg",
    "Lu-177-PSMA-617 7.4 GBq", "Ra-223 55 kBq/kg",
    "olaparib 300 mg", "rucaparib 600 mg",
    "pembrolizumab 200 mg", "docetaxel + cabazitaxel secuencial",
]

_IMAGING_FINDINGS_BONE = [
    "lesión hipercaptante en cuerpo vertebral L4 compatible con metástasis ósea",
    "múltiples focos de hipercaptación en arco costal derecho, hueso ilíaco izquierdo y L3",
    "imagen de alta actividad en cabeza femoral derecha y sacro",
    "patrón de superscan: hipercaptación difusa esquelética sin actividad renal",
    "sin evidencia de metástasis óseas",
    "nueva lesión en T10 comparado con estudio previo",
    "tres nuevas lesiones respecto a gammagrama de hace 6 meses",
]

_IMAGING_FINDINGS_CT = [
    "adenopatías ilíacas comunes bilaterales, la mayor de 18 mm",
    "sin adenopatías patológicas. Sin metástasis viscerales",
    "lesión hepática hipodensa de 2.3 cm en segmento VI, de características indeterminadas",
    "derrame pleural mínimo bilateral. Consolidación pulmonar basal derecha",
    "masa pélvica de 4.5 cm que desplaza vejiga",
    "engrosamiento irregular de la pared vesical posterior",
]

_PSMA_FINDINGS = [
    "expresión PSMA aumentada en múltiples ganglios pélvicos y retroperitoneales (SUVmax 8.4)",
    "lesiones óseas con SUVmax 12.7 en L2, sacro y costilla izquierda. PSMA TBV estimado 145 mL",
    "sin evidencia de enfermedad con expresión PSMA significativa",
    "lesión única en ganglio ilíaco común izquierdo (SUVmax 6.2), PI-RADS-PSMA score 4",
    "múltiples depósitos en hueso axial y apendicular, SUVmean 10.3. Candidato a Lu-177",
]


# ══════════════════════════════════════════════════════════════════════════════
# Dataclass
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SyntheticDocument:
    """A synthetic clinical document with ground-truth labels."""
    document_type: str
    text:          str
    ground_truth:  dict[str, Any]   # Expected NLP extraction output
    metadata:      dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ══════════════════════════════════════════════════════════════════════════════
# Generator
# ══════════════════════════════════════════════════════════════════════════════

class SyntheticDocumentGenerator:
    """
    Generates realistic synthetic Spanish prostate cancer clinical documents.

    Each document is paired with ground_truth labels for NLP evaluation.
    Includes realistic clinical language patterns, abbreviations, and
    Spanish medical terminology from Mexican/Latin American clinical practice.
    """

    DOCUMENT_TYPES = [
        "pathology_report",
        "laboratory_bundle",
        "imaging_report",
        "genomic_report",
        "surgery_summary",
        "radiotherapy_summary",
    ]

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    def generate_batch(
        self,
        n: int = 100,
        document_types: list[str] | None = None,
    ) -> list[SyntheticDocument]:
        """Generate n synthetic documents."""
        types = document_types or self.DOCUMENT_TYPES
        docs = []
        for i in range(n):
            doc_type = types[i % len(types)]
            docs.append(self.generate_one(doc_type))
        return docs

    def generate_one(self, document_type: str) -> SyntheticDocument:
        """Generate a single synthetic document of the given type."""
        dispatch = {
            "pathology_report":      self._gen_pathology,
            "laboratory_bundle":     self._gen_labs,
            "imaging_report":        self._gen_imaging,
            "genomic_report":        self._gen_genomic,
            "surgery_summary":       self._gen_surgery,
            "radiotherapy_summary":  self._gen_radiotherapy,
        }
        generator = dispatch.get(document_type, self._gen_pathology)
        return generator()

    def save_jsonl(
        self, docs: list[SyntheticDocument], output_path: str | Path
    ) -> Path:
        """Save documents as JSONL for NLP evaluation."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for doc in docs:
                f.write(json.dumps(doc.to_dict(), ensure_ascii=False) + "\n")
        return path

    # ── Pathology Report ─────────────────────────────────────────────────────

    def _gen_pathology(self) -> SyntheticDocument:
        rng = self._rng
        g_prim, g_sec, isup = rng.choice(_GLEASON_PATTERNS)
        gleason_total = g_prim + g_sec
        cores_pos = rng.randint(2, 12)
        cores_total = rng.choice([12, 14, 16])
        pct_pos = round(cores_pos / cores_total * 100, 1)
        pct_involvement = rng.randint(15, 95)
        psa = round(rng.uniform(2.5, 45.0), 1)
        perineural = rng.choice([True, True, False])
        margins = rng.choice([True, False, False])
        lvi = rng.choice([True, False, False])
        tnm = rng.choice(_TNMS[:6])  # Pathology TNMs (M0 mostly)
        patologo = rng.choice(_PATOLOGOS)
        institucion = rng.choice(_INSTITUCIONES)
        fecha = _random_date(rng, "2022-01-01", "2025-12-31")

        margin_text = (
            "Márgenes quirúrgicos positivos en cara posterior derecha." if margins
            else "Márgenes quirúrgicos negativos."
        )
        pni_text = (
            "Se identifica invasión perineural." if perineural
            else "Sin invasión perineural."
        )
        lvi_text = (
            "Invasión linfovascular presente." if lvi
            else "Sin invasión linfovascular."
        )

        text = f"""{institucion}
DEPARTAMENTO DE ANATOMÍA PATOLÓGICA

REPORTE HISTOPATOLÓGICO
Fecha: {fecha}
Patólogo: {patologo}

MATERIAL RECIBIDO: Biopsias de próstata guiadas por ultrasonido transrectal

DATOS CLÍNICOS:
PSA basal {psa} ng/mL. Tacto rectal: lóbulo derecho indurado.
Indicación: elevación de PSA + lesión sospechosa en RMN.

DIAGNÓSTICO:
Adenocarcinoma acinar de próstata.
Gleason {g_prim}+{g_sec}={gleason_total}, Grupo ISUP {isup}.

CORES POSITIVOS: {cores_pos}/{cores_total} ({pct_pos}%)
Porcentaje máximo de invasión tumoral por core: {pct_involvement}%

ESTADIO PATOLÓGICO: {tnm[0]}  N: {tnm[1]}  M: {tnm[2]}

HALLAZGOS ADICIONALES:
{pni_text}
{lvi_text}
{margin_text}
Sin evidencia de neoplasia intraepitelial de alto grado (PIN) coexistente.

COMENTARIO: Patrón histológico compatible con adenocarcinoma de próstata
convencional acinar. {"Tumor de alto riesgo patológico." if isup >= 4 else "Tumor de riesgo intermedio."}

Firmado digitalmente: {patologo}
"""

        ground_truth = {
            "psa": psa,
            "gleason_primary": g_prim,
            "gleason_secondary": g_sec,
            "isup_grade": isup,
            "cores_positive": cores_pos,
            "cores_total": cores_total,
            "pct_cores_positive": pct_pos,
            "t_stage": tnm[0],
            "n_stage": tnm[1],
            "m_stage": tnm[2],
            "perineural_invasion": perineural,
            "positive_surgical_margins": margins,
            "lymphovascular_invasion": lvi,
        }

        return SyntheticDocument(
            document_type="pathology_report",
            text=text,
            ground_truth=ground_truth,
            metadata={"institution": institucion, "date": fecha, "pathologist": patologo},
        )

    # ── Laboratory Bundle ────────────────────────────────────────────────────

    def _gen_labs(self) -> SyntheticDocument:
        rng = self._rng
        psa = round(rng.uniform(0.01, 180.0), 2)
        testosterone = rng.choice([
            round(rng.uniform(3, 25), 0),    # castrate
            round(rng.uniform(280, 650), 0),  # normal
        ])
        hgb = round(rng.uniform(8.5, 15.5), 1)
        alp = round(rng.uniform(45, 450), 0)
        ldh = round(rng.uniform(140, 620), 0)
        albumin = round(rng.uniform(2.8, 4.5), 1)
        creatinine = round(rng.uniform(0.7, 2.8), 2)
        fecha = _random_date(rng, "2022-01-01", "2025-12-31")
        institucion = rng.choice(_INSTITUCIONES)

        text = f"""{institucion}
LABORATORIO CLÍNICO — RESULTADOS

Fecha de toma: {fecha}

═══════════════════════════════════════
MARCADORES TUMORALES
═══════════════════════════════════════
Antígeno Prostático Específico (PSA):   {psa} ng/mL
Testosterona total:                     {testosterone:.0f} ng/dL

═══════════════════════════════════════
BIOMETRÍA HEMÁTICA
═══════════════════════════════════════
Hemoglobina:                            {hgb} g/dL
{"Anemia significativa. Complementar con reticulocitos y ferritina." if hgb < 10 else ""}

═══════════════════════════════════════
PERFIL BIOQUÍMICO
═══════════════════════════════════════
Fosfatasa alcalina (ALP):              {alp:.0f} U/L   {"[ELEVADA — considerar metástasis óseas]" if alp > 250 else "[Normal]"}
Deshidrogenasa láctica (LDH):          {ldh:.0f} U/L   {"[ELEVADA]" if ldh > 300 else "[Normal]"}
Albúmina sérica:                       {albumin} g/dL   {"[BAJA — evaluar estado nutricional]" if albumin < 3.2 else ""}
Creatinina sérica:                     {creatinine} mg/dL   {"[TFG estimada reducida]" if creatinine > 1.8 else ""}

═══════════════════════════════════════
RESULTADO AUTORIZADO
═══════════════════════════════════════
Laboratorio certificado acreditado por CNBS.
"""

        ground_truth = {
            "psa": psa,
            "testosterone": testosterone,
            "hemoglobin": hgb,
            "alp": alp,
            "ldh": ldh,
            "albumin": albumin,
            "creatinine": creatinine,
        }

        return SyntheticDocument(
            document_type="laboratory_bundle",
            text=text,
            ground_truth=ground_truth,
            metadata={"institution": institucion, "date": fecha},
        )

    # ── Imaging Report ───────────────────────────────────────────────────────

    def _gen_imaging(self) -> SyntheticDocument:
        rng = self._rng
        modality = rng.choice(["bone_scan", "ct_scan", "psma_pet", "mri_pelvis", "mri_spine"])
        fecha = _random_date(rng, "2022-01-01", "2025-12-31")
        institucion = rng.choice(_INSTITUCIONES)
        oncologo = rng.choice(_ONCOLOGOS)

        if modality == "bone_scan":
            finding = rng.choice(_IMAGING_FINDINGS_BONE)
            modality_label = "GAMMAGRAMA ÓSEO CON Tc-99m MDP"
            finding_section = f"HALLAZGOS:\n{finding}"
            pi_rads = None
            suv_max = None
            ground_truth = {
                "imaging_modality": "bone_scan",
                "bone_mets_present": "sin evidencia" not in finding.lower(),
            }

        elif modality == "ct_scan":
            finding = rng.choice(_IMAGING_FINDINGS_CT)
            modality_label = "TOMOGRAFÍA COMPUTADA DE ABDOMEN Y PELVIS CON CONTRASTE"
            finding_section = f"HALLAZGOS:\n{finding}"
            pi_rads = None
            suv_max = None
            ground_truth = {
                "imaging_modality": "ct_scan",
                "lymph_node_involvement": "adenopatía" in finding.lower() or "ganglio" in finding.lower(),
            }

        elif modality == "psma_pet":
            finding = rng.choice(_PSMA_FINDINGS)
            modality_label = "PET-PSMA con 68Ga-PSMA-11"
            suv_max_val = round(rng.uniform(3.5, 18.0), 1)
            tbv = round(rng.uniform(20, 250), 0) if "múltiple" in finding.lower() else round(rng.uniform(5, 50), 0)
            finding_section = (
                f"HALLAZGOS:\n{finding}\n\n"
                f"CUANTIFICACIÓN:\nSUVmax lesión dominante: {suv_max_val}\n"
                f"PSMA-TBV estimado: {tbv} mL\nSUVmean total: {round(suv_max_val * 0.7, 1)}"
            )
            suv_max = suv_max_val
            pi_rads = None
            ground_truth = {
                "imaging_modality": "psma_pet",
                "psma_suv_max": suv_max_val,
                "psma_tbv": tbv,
            }

        elif modality == "mri_pelvis":
            pi_rads_val = rng.choice([3, 4, 4, 5, 5])
            suv_max = None
            modality_label = "RESONANCIA MAGNÉTICA DE PELVIS MULTIPARAMÉTRICA"
            finding_section = (
                f"HALLAZGOS:\nZona de transición: lesión nodular hipointensa T2, "
                f"restricción difusión, realce precoz en DCE. Tamaño: {rng.randint(12, 45)} mm.\n"
                f"Clasificación PI-RADS: {pi_rads_val}\n"
                f"Ganglio ilíaco derecho: {rng.randint(8, 22)} mm (eje corto)."
            )
            pi_rads = pi_rads_val
            ground_truth = {
                "imaging_modality": "mri_pelvis",
                "pi_rads": pi_rads_val,
            }

        else:  # mri_spine
            level = rng.choice(["C4", "T8", "T10", "L1", "L3", "L5", "S1"])
            modality_label = "RESONANCIA MAGNÉTICA DE COLUMNA VERTEBRAL"
            finding_section = (
                f"HALLAZGOS:\nLesión hipointensa T1 / hiperintensa T2 en {level} "
                f"con componente de partes blandas epidural. "
                f"{'Compresión medular parcial observada.' if rng.random() > 0.7 else 'Sin compromiso medular significativo.'}\n"
                f"Colapso vertebral de {'30-40%' if rng.random() > 0.5 else '10-20%'}."
            )
            pi_rads = None
            suv_max = None
            ground_truth = {
                "imaging_modality": "mri_spine",
                "spinal_level_involved": level,
            }

        text = f"""{institucion}
DEPARTAMENTO DE IMAGEN

{modality_label}
Fecha: {fecha}
Médico solicitante: {oncologo}
Indicación: Estadificación / seguimiento de cáncer de próstata

{finding_section}

CONCLUSIÓN:
Hallazgos descritos arriba. Correlacionar con evolución clínica y marcadores tumorales.

Médico radiólogo certificado, CMRI
"""

        return SyntheticDocument(
            document_type="imaging_report",
            text=text,
            ground_truth=ground_truth,
            metadata={"modality": modality, "institution": institucion, "date": fecha},
        )

    # ── Genomic Report ───────────────────────────────────────────────────────

    def _gen_genomic(self) -> SyntheticDocument:
        rng = self._rng
        brca2 = rng.random() < 0.12
        brca1 = rng.random() < 0.04
        hrr = brca2 or brca1 or rng.random() < 0.15
        msi_h = rng.random() < 0.05
        arv7 = rng.random() < 0.25
        tmb = round(rng.uniform(1.5, 12.0), 1)
        psma_ihc = rng.choice(["alta", "moderada", "baja", "negativa"])
        fecha = _random_date(rng, "2022-01-01", "2025-12-31")
        institucion = rng.choice(_INSTITUCIONES)

        text = f"""{institucion}
MEDICINA MOLECULAR Y GENÓMICA CLÍNICA

REPORTE MOLECULAR DE CÁNCER DE PRÓSTATA
Fecha: {fecha}
Muestra: Tejido tumoral en parafina (FFPE) — biopsia de próstata

═══════════════════════════════════════
PANEL DE REPARACIÓN HOMÓLOGA (HRR)
═══════════════════════════════════════
BRCA2: {"Mutación patogénica bialélica detectada (c.8023A>T, p.Lys2675Ter + LOH)" if brca2 else "Sin alteraciones patogénicas"}
BRCA1: {"Deleción exónica patogénica" if brca1 else "Sin alteraciones"}
Estado HRR: {"POSITIVO — elegible para PARP inhibidores" if hrr else "NEGATIVO"}

═══════════════════════════════════════
INESTABILIDAD DE MICROSATÉLITES (MSI)
═══════════════════════════════════════
Estado MSI: {"MSI-H (Alta inestabilidad) — elegible para inmunoterapia (pembrolizumab)" if msi_h else "MSS (Estable)"}
Carga mutacional tumoral (TMB): {tmb} mut/Mb {"[ALTA ≥10]" if tmb >= 10 else "[BAJA-INTERMEDIA]"}

═══════════════════════════════════════
RECEPTOR DE ANDRÓGENOS
═══════════════════════════════════════
AR-V7 en CTCs (CellSearch): {"POSITIVO — resistencia esperada a abiraterona/enzalutamida" if arv7 else "NEGATIVO — ARSI conserva actividad"}
Amplificación AR: {"Sí" if rng.random() > 0.6 else "No"}

═══════════════════════════════════════
EXPRESIÓN PSMA (IHC)
═══════════════════════════════════════
Expresión PSMA por inmunohistoquímica: {psma_ihc.upper()}
{"→ Candidato para Lu-177-PSMA si SUVmean ≥10 en PET-PSMA" if psma_ihc in ["alta", "moderada"] else "→ Beneficio limitado con terapias dirigidas a PSMA"}

═══════════════════════════════════════
INTERPRETACIÓN CLÍNICA
═══════════════════════════════════════
{"• BRCA2 patogénico: Iniciar olaparib 300 mg BID (PROfound)" if brca2 else ""}
{"• MSI-H: Pembrolizumab 200 mg q3w (aprobación tumor-agnóstica FDA)" if msi_h else ""}
{"• AR-V7+: Preferir taxano sobre ARSI en próxima línea" if arv7 else ""}

Médico molecular certificado
"""

        ground_truth = {
            "brca2_loss": brca2,
            "brca1_loss": brca1,
            "hrr_positive": hrr,
            "msi_h": msi_h,
            "tmb": tmb,
            "ar_v7": arv7,
            "psma_expression": psma_ihc,
        }

        return SyntheticDocument(
            document_type="genomic_report",
            text=text,
            ground_truth=ground_truth,
            metadata={"institution": institucion, "date": fecha},
        )

    # ── Surgery Summary ──────────────────────────────────────────────────────

    def _gen_surgery(self) -> SyntheticDocument:
        rng = self._rng
        approach = rng.choice(["laparoscópica", "robótica asistida (Da Vinci)", "abierta retropúbica"])
        g_prim, g_sec, isup = rng.choice(_GLEASON_PATTERNS)
        tnm = rng.choice(_TNMS[:6])
        margins = rng.random() < 0.35
        seminal_vesicle = rng.random() < 0.25
        psa_pre = round(rng.uniform(5, 35), 1)
        psa_post = round(rng.uniform(0.01, 0.5), 3)
        nodes_removed = rng.randint(8, 24)
        nodes_positive = rng.randint(0, 3) if rng.random() > 0.6 else 0
        fecha = _random_date(rng, "2020-01-01", "2024-12-31")
        institucion = rng.choice(_INSTITUCIONES)
        oncologo = rng.choice(_ONCOLOGOS)

        text = f"""{institucion}
SERVICIO DE UROLOGÍA

RESUMEN OPERATORIO — PROSTATECTOMÍA RADICAL
Fecha de cirugía: {fecha}
Cirujano: {oncologo}
Técnica: Prostatectomía radical {approach}
Indicación: Cáncer de próstata localizado de riesgo {'alto' if isup >= 4 else 'intermedio'}

HALLAZGOS INTRAOPERATORIOS:
PSA preoperatorio: {psa_pre} ng/mL
Próstata con volumen estimado de {rng.randint(30, 85)} cc.
{"Extensión extracapsular identificada." if tnm[0] in ["T3a", "T3b"] else "Sin extensión extracapsular macroscópica."}
{"Invasión de vesículas seminales documentada." if seminal_vesicle else "Vesículas seminales libres de tumor."}

GANGLIOS LINFÁTICOS:
Linfadenectomía pélvica bilateral extendida.
Ganglios removidos: {nodes_removed}
Ganglios positivos: {nodes_positive} {'(metástasis ganglionar confirmada)' if nodes_positive > 0 else '(sin metástasis ganglionar)'}

REPORTE PATOLÓGICO FINAL:
Adenocarcinoma de próstata Gleason {g_prim}+{g_sec}={g_prim+g_sec}, ISUP grado {isup}
pT: {tnm[0]}   pN: {tnm[1]}   pM: {tnm[2]}
{"Márgenes quirúrgicos POSITIVOS en cara posterolateral izquierda (2 mm)." if margins else "Márgenes quirúrgicos NEGATIVOS."}

EVOLUCIÓN POSTOPERATORIA:
Sin complicaciones mayores. Alta al 3er día postquirúrgico.
PSA postoperatorio (4 semanas): {psa_post} ng/mL

PLAN DE SEGUIMIENTO:
PSA cada 3 meses × 2 años. Consulta de urología en 6 semanas.
{"Considerar radioterapia adyuvante por márgenes positivos." if margins else ""}
"""

        ground_truth = {
            "gleason_primary": g_prim,
            "gleason_secondary": g_sec,
            "isup_grade": isup,
            "t_stage": tnm[0],
            "n_stage": tnm[1],
            "m_stage": tnm[2],
            "positive_surgical_margins": margins,
            "seminal_vesicle_invasion": seminal_vesicle,
            "psa": psa_pre,
            "psa_post_surgery": psa_post,
            "lymph_nodes_positive": nodes_positive,
        }

        return SyntheticDocument(
            document_type="surgery_summary",
            text=text,
            ground_truth=ground_truth,
            metadata={"approach": approach, "institution": institucion, "date": fecha},
        )

    # ── Radiotherapy Summary ─────────────────────────────────────────────────

    def _gen_radiotherapy(self) -> SyntheticDocument:
        rng = self._rng
        technique = rng.choice(["IMRT", "VMAT", "SBRT", "Radioterapia conformacional 3D"])
        dose_gy = rng.choice([45, 50, 60, 70, 74, 78])
        fractions = rng.choice([25, 28, 37, 39, 5])
        dose_per_fx = round(dose_gy / fractions, 2)
        target = rng.choice(["próstata + vesículas seminales", "lecho prostático", "lecho + ganglios pélvicos", "metástasis ósea L4"])
        psa_pre = round(rng.uniform(2, 30), 1)
        psa_nadir = round(rng.uniform(0.1, psa_pre * 0.3), 2)
        toxicity_gu = rng.choice(["grado 0", "grado 1", "grado 2", "grado 2 (polaquiuria, disuria leve)"])
        toxicity_gi = rng.choice(["grado 0", "grado 1", "grado 1 (proctitis leve)", "grado 2"])
        fecha_inicio = _random_date(rng, "2020-01-01", "2024-01-01")
        fecha_fin = (date.fromisoformat(fecha_inicio) + timedelta(weeks=fractions // 5 + 3)).isoformat()
        oncologo = rng.choice(_ONCOLOGOS)
        institucion = rng.choice(_INSTITUCIONES)

        text = f"""{institucion}
SERVICIO DE RADIO-ONCOLOGÍA

RESUMEN DE RADIOTERAPIA
Paciente sometido a radioterapia con intención {'radical' if 'próstata' in target else 'paliativa'}.
Médico tratante: {oncologo}

TÉCNICA: {technique}
VOLUMEN BLANCO: {target.title()}
DOSIS TOTAL: {dose_gy} Gy en {fractions} fracciones ({dose_per_fx} Gy/fx)
INICIO: {fecha_inicio}   FIN: {fecha_fin}

RESPUESTA BIOQUÍMICA:
PSA antes del tratamiento: {psa_pre} ng/mL
PSA nadir: {psa_nadir} ng/mL (alcanzado aprox. 18 meses post-RT)
{'PSA en ascenso — considerar criterios Phoenix (nadir + 2 ng/mL).' if rng.random() > 0.6 else 'Sin evidencia de recaída bioquímica a la fecha.'}

TOXICIDAD:
Genitourinaria: {toxicity_gu}
Gastrointestinal: {toxicity_gi}
Disfunción eréctil: {'presente' if rng.random() > 0.4 else 'no reportada'}

PLAN:
PSA + testosterona cada 6 meses. Continuar bloqueo androgénico por {rng.choice([6, 18, 24, 36])} meses total.
"""

        ground_truth = {
            "psa": psa_pre,
            "psa_nadir": psa_nadir,
            "rt_dose_gy": dose_gy,
            "rt_fractions": fractions,
            "rt_technique": technique,
        }

        return SyntheticDocument(
            document_type="radiotherapy_summary",
            text=text,
            ground_truth=ground_truth,
            metadata={"technique": technique, "institution": institucion, "date": fecha_inicio},
        )


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _random_date(rng: random.Random, start: str, end: str) -> str:
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    delta = (d1 - d0).days
    return (d0 + timedelta(days=rng.randint(0, delta))).isoformat()
