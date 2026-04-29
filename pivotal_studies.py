# -*- coding: utf-8 -*-
"""
Motor de Confrontacion con Estudios Pivotales para Cancer de Prostata.
======================================================================

ProstaMed Fase 6 — Modulo de Evidencia Clinica

Este modulo implementa:
  1. Base de datos estructurada de ~27 estudios pivotales en cancer de prostata.
  2. Motor de elegibilidad que confronta los datos clinicos de un paciente contra
     los criterios de cada estudio, determinando cuales serian aplicables.
  3. Generador de reportes narrativos con la evidencia aplicable y consideraciones
     de validez externa para la poblacion mexicana.

Escenarios cubiertos:
  - Localizado / Vigilancia Activa (ProtecT, PIVOT, SPCG-4, PROTECT)
  - Adyuvancia post-prostatectomia (SWOG-8794, ARO 96-02, RADICALS-RT)
  - Rescate bioquimico (RAVES, GETUG-AFU 16, ARTISTIC)
  - mHSPC (CHAARTED, LATITUDE, TITAN, ARCHES, ENZAMET, ARASENS, PEACE-1, STAMPEDE)
  - nmCRPC (SPARTAN, PROSPER, ARAMIS)
  - mCRPC (COU-AA-301, AFFIRM, PROfound, VISION, KEYNOTE-158, CARD, ALSYMPCA)

Autores: Equipo ProstaMed
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from datetime import datetime
from prostanet.domains.patient_tracking.mhspc_evidence import (
    build_triplet_decision,
    is_mhspc_state,
    resolve_mhspc_state,
    visible_trials_for_mhspc_state,
)

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ===========================================================================
# TIPOS Y CONSTANTES
# ===========================================================================

# Mapeo de escenarios validos
VALID_SCENARIOS = (
    "localizado",
    "adyuvancia",
    "rescate",
    "mHSPC",
    "nmCRPC",
    "mCRPC",
)
POST_RP_SALVAGE_TRIAL_NAMES = {
    "ARTISTIC",
    "EMBARK",
    "EMPIRE-1",
    "GETUG-AFU 16",
    "RADICALS-RT",
    "RAVES",
    "RTOG 9601",
    "SPPORT",
}

# Mapeo ISUP <-> Gleason
_GLEASON_TO_ISUP: dict[int, int] = {
    6: 1,
    7: 2,   # Se refinara con patron primario cuando se disponga
    8: 4,
    9: 5,
    10: 5,
}

_STAGE_ORDER: dict[str, int] = {
    "T1A": 1, "T1B": 2, "T1C": 3,
    "T2A": 4, "T2B": 5, "T2C": 6,
    "T3A": 7, "T3B": 8,
    "T4": 9,
    "N1": 10, "M1": 11,
}


def _stage_rank(stage: str) -> int:
    """Retorna un valor numerico ordinal para comparar estadios clinicos."""
    return _STAGE_ORDER.get(stage.upper().strip(), 0)


def _coerce_bool(value: Any) -> bool | None:
    if value in (None, "", "unknown", "Unknown"):
        return None
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "si", "sí"}:
        return True
    if lowered in {"0", "false", "no"}:
        return False
    return None


# ===========================================================================
# BASE DE DATOS DE ESTUDIOS PIVOTALES
# ===========================================================================

PIVOTAL_STUDIES: list[dict[str, Any]] = [

    # ===================================================================
    # LOCALIZADOS / VIGILANCIA ACTIVA
    # ===================================================================
    {
        "name": "ProtecT",
        "phase": "III",
        "scenario": "localizado",
        "intervention": "Prostatectomia radical vs Radioterapia vs Vigilancia activa",
        "control": "Comparacion directa de tres estrategias",
        "primary_endpoint": "Mortalidad especifica por cancer de prostata a 15 anios",
        "key_result": "Mortalidad especifica por CaP <3% en los 3 brazos a 15 anios. "
                      "Vigilancia activa mostro mayor tasa de metastasis (9% vs 5% vs 4%).",
        "population": "Hombres con CaP localizado detectado por PSA (predominantemente bajo/intermedio riesgo).",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 20,
            "gleason_min": 6, "gleason_max": 7,
            "stage_min": "T1C", "stage_max": "T2C",
            "ecog_max": 1,
            "metastasis": "M0",
            "age_min": 50, "age_max": 69,
        },
        "mexican_applicability": (
            "Alta aplicabilidad. ProtecT incluyo predominantemente poblacion caucasica del Reino Unido. "
            "En Mexico, la vigilancia activa se subutiliza por barreras de seguimiento y acceso a RM "
            "multiparametrica. Debe contextualizarse con la menor disponibilidad de biopsia de fusion "
            "y los tiempos de espera institucionales (IMSS/ISSSTE). Sin embargo, las tasas de mortalidad "
            "especifica reportadas son universalmente bajas, apoyando la oferta de VA en instituciones "
            "con capacidad de seguimiento."
        ),
        "nccn_category": "1",
        "year": 2023,
    },
    {
        "name": "PIVOT",
        "phase": "III",
        "scenario": "localizado",
        "intervention": "Prostatectomia radical",
        "control": "Observacion",
        "primary_endpoint": "Mortalidad por todas las causas",
        "key_result": "No diferencia significativa en mortalidad global (HR 0.84, p=0.06). "
                      "Beneficio sugerido en subgrupo de riesgo intermedio (PSA >10) y tumores palpables.",
        "population": "Hombres con CaP localizado (era pre-PSA screening masivo). Poblacion de veteranos USA.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 50,
            "gleason_min": 6, "gleason_max": 10,
            "stage_min": "T1A", "stage_max": "T2C",
            "ecog_max": 2,
            "metastasis": "M0",
            "age_min": 40, "age_max": 75,
        },
        "mexican_applicability": (
            "Moderada aplicabilidad. El estudio PIVOT incluyo una poblacion de veteranos con "
            "comorbilidades significativas (solo 50% fallecio de CaP), lo cual puede reflejar la "
            "poblacion mexicana con comorbilidades metabolicas altas (diabetes, obesidad). "
            "La leccion principal aplica: en hombres mayores con bajo riesgo y comorbilidades, "
            "la observacion es una opcion valida."
        ),
        "nccn_category": "1",
        "year": 2012,
    },
    {
        "name": "SPCG-4",
        "phase": "III",
        "scenario": "localizado",
        "intervention": "Prostatectomia radical",
        "control": "Watchful waiting (espera vigilada)",
        "primary_endpoint": "Mortalidad especifica por cancer de prostata",
        "key_result": "Reduccion significativa en mortalidad por CaP (HR 0.56, NNT=8 a 18 anios). "
                      "Beneficio concentrado en menores de 65 anios y riesgo intermedio-alto.",
        "population": "Hombres con CaP localizado en era pre-PSA (tumores clinicamente detectados). Poblacion escandinava.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 50,
            "gleason_min": 6, "gleason_max": 10,
            "stage_min": "T1B", "stage_max": "T2C",
            "ecog_max": 2,
            "metastasis": "M0",
            "age_min": 40, "age_max": 75,
        },
        "mexican_applicability": (
            "Moderada-alta aplicabilidad para enfermedad palpable. SPCG-4 refleja tumores detectados "
            "clinicamente (no por screening), lo cual es mas comun en Mexico donde el tamizaje con PSA "
            "no es universal. El beneficio robusto de la cirugia en menores de 65 anios con enfermedad "
            "palpable es directamente extrapolable."
        ),
        "nccn_category": "1",
        "year": 2014,
    },
    {
        "name": "PROTECT",
        "phase": "III",
        "scenario": "localizado",
        "intervention": "Prostatectomia radical asistida por robot vs Abierta vs Radioterapia",
        "control": "Comparacion de modalidades de tratamiento activo",
        "primary_endpoint": "Resultados funcionales (continencia, funcion erectil) a 2 anios",
        "key_result": "Cirugia robotica mostro resultados funcionales similares a cirugia abierta. "
                      "Radioterapia con mejor preservacion funcional temprana.",
        "population": "Hombres con CaP localizado candidatos a tratamiento activo.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 20,
            "gleason_min": 6, "gleason_max": 9,
            "stage_min": "T1C", "stage_max": "T2C",
            "ecog_max": 1,
            "metastasis": "M0",
            "age_min": 45, "age_max": 75,
        },
        "mexican_applicability": (
            "Moderada aplicabilidad. La cirugia robotica tiene disponibilidad limitada en Mexico, "
            "principalmente en sector privado y centros de tercer nivel (INCan, Hospital de Especialidades "
            "CMN Siglo XXI). Los resultados apoyan que la tecnica abierta, mas accesible en el contexto "
            "mexicano, ofrece resultados oncologicos equivalentes."
        ),
        "nccn_category": "2A",
        "year": 2023,
    },

    # ===================================================================
    # ADYUVANCIA POST-PROSTATECTOMIA
    # ===================================================================
    {
        "name": "SWOG-8794",
        "phase": "III",
        "scenario": "adyuvancia",
        "intervention": "Radioterapia adyuvante inmediata post-prostatectomia (60-64 Gy)",
        "control": "Observacion con rescate diferido",
        "primary_endpoint": "Supervivencia libre de metastasis",
        "key_result": "RT adyuvante mejoro SLM (HR 0.71, p=0.016) y SG (HR 0.72, p=0.023) "
                      "en pacientes con margenes positivos o pT3. Unico estudio con beneficio en SG.",
        "population": "Post-prostatectomia con factores adversos (pT3a/b, margenes positivos, PSA detectable).",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 999,
            "gleason_min": 6, "gleason_max": 10,
            "stage_min": "T3A", "stage_max": "T4",
            "ecog_max": 2,
            "metastasis": "M0",
            "prior_prostatectomy": True,
            "pathologic_stage_min": "pT3a",
        },
        "mexican_applicability": (
            "Alta aplicabilidad. La RT adyuvante es ampliamente disponible en centros oncologicos mexicanos. "
            "La clave es la identificacion temprana de factores adversos patologicos post-cirugia. "
            "En el contexto del IMSS, donde los tiempos de referencia a radioterapia pueden ser prolongados, "
            "se debe priorizar la referencia inmediata para no perder la ventana de adyuvancia."
        ),
        "nccn_category": "1",
        "year": 2009,
    },
    {
        "name": "ARO 96-02",
        "phase": "III",
        "scenario": "adyuvancia",
        "intervention": "Radioterapia adyuvante (60 Gy)",
        "control": "Observacion con rescate diferido",
        "primary_endpoint": "Supervivencia libre de progresion bioquimica",
        "key_result": "RT adyuvante mejoro SLP bioquimica (HR 0.53, p<0.0001). "
                      "Sin diferencia significativa en SG en el seguimiento disponible.",
        "population": "Post-prostatectomia con pT3 y/o margenes positivos, PSA indetectable post-cirugia.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 0.2,
            "gleason_min": 6, "gleason_max": 10,
            "stage_min": "T3A", "stage_max": "T4",
            "ecog_max": 2,
            "metastasis": "M0",
            "prior_prostatectomy": True,
        },
        "mexican_applicability": (
            "Alta aplicabilidad. El esquema de 60 Gy adyuvante esta dentro de las capacidades "
            "de los centros de radioterapia mexicanos. El debate actual adyuvancia vs rescate temprano "
            "(informado por RADICALS/RAVES/ARTISTIC) debe considerarse en el contexto de cada paciente."
        ),
        "nccn_category": "1",
        "year": 2014,
    },
    {
        "name": "RADICALS-RT",
        "phase": "III",
        "scenario": "adyuvancia",
        "intervention": "Radioterapia adyuvante inmediata",
        "control": "Radioterapia de rescate temprano (PSA >= 0.1 ng/mL)",
        "primary_endpoint": "Supervivencia libre de progresion bioquimica",
        "key_result": "No diferencia en SLP bioquimica entre RT adyuvante y RT de rescate temprano "
                      "(HR 0.95, IC95% 0.75-1.21). Rescate temprano evita sobretratar 60% de pacientes.",
        "population": "Post-prostatectomia con al menos un factor de riesgo (pT3a/b, margenes+, Gleason >=7).",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 0.2,
            "gleason_min": 7, "gleason_max": 10,
            "stage_min": "T3A", "stage_max": "T4",
            "ecog_max": 2,
            "metastasis": "M0",
            "prior_prostatectomy": True,
        },
        "mexican_applicability": (
            "Muy alta aplicabilidad. RADICALS-RT respalda la estrategia de rescate temprano, lo cual "
            "es especialmente relevante en Mexico donde los recursos de radioterapia son limitados. "
            "Diferir la RT hasta PSA detectable (>0.1) permite optimizar el uso del recurso sin "
            "comprometer resultados oncologicos, beneficiando al sistema de salud publico."
        ),
        "nccn_category": "1",
        "year": 2020,
    },

    # ===================================================================
    # RESCATE BIOQUIMICO
    # ===================================================================
    {
        "name": "RAVES",
        "phase": "III",
        "scenario": "rescate",
        "intervention": "Radioterapia adyuvante inmediata",
        "control": "Radioterapia de rescate temprano (PSA >= 0.2 ng/mL)",
        "primary_endpoint": "Supervivencia libre de progresion bioquimica a 5 anios",
        "key_result": "Sin diferencia significativa entre RT adyuvante y rescate temprano "
                      "(SLP bioquimica 86% vs 87%). Refuerza la estrategia de rescate.",
        "population": "Post-prostatectomia con factores patologicos adversos (pT3 o margenes+), PSA indetectable.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 0.2,
            "gleason_min": 6, "gleason_max": 10,
            "stage_min": "T3A", "stage_max": "T4",
            "ecog_max": 2,
            "metastasis": "M0",
            "prior_prostatectomy": True,
        },
        "mexican_applicability": (
            "Alta aplicabilidad. Consistente con RADICALS-RT, apoya el rescate temprano como "
            "estrategia optima en contextos con recursos limitados. Se recomienda monitoreo "
            "estricto del PSA post-prostatectomia con acceso oportuno a radioterapia."
        ),
        "nccn_category": "1",
        "year": 2020,
    },
    {
        "name": "GETUG-AFU 16",
        "phase": "III",
        "scenario": "rescate",
        "intervention": "RT de rescate + Goserelina (ADT corta, 6 meses)",
        "control": "RT de rescate sola",
        "primary_endpoint": "Supervivencia libre de progresion bioquimica",
        "key_result": "La adicion de ADT corta (6 meses) a la RT de rescate mejoro la SLP "
                      "(HR 0.54, p<0.0001) y la supervivencia libre de metastasis.",
        "population": "Recurrencia bioquimica post-prostatectomia (PSA 0.2-2.0 ng/mL), sin metastasis.",
        "eligibility_criteria": {
            "psa_min": 0.2, "psa_max": 2.0,
            "gleason_min": 6, "gleason_max": 10,
            "stage_min": "T1A", "stage_max": "T4",
            "ecog_max": 1,
            "metastasis": "M0",
            "prior_prostatectomy": True,
        },
        "mexican_applicability": (
            "Alta aplicabilidad. La goserelina esta incluida en el cuadro basico del sector salud "
            "mexicano. La adicion de 6 meses de ADT a la RT de rescate es costo-efectiva y accesible. "
            "GETUG-AFU 16 respalda la practica comun mexicana de combinar hormonoterapia corta con RT."
        ),
        "nccn_category": "1",
        "year": 2016,
    },
    {
        "name": "ARTISTIC",
        "phase": "III (Meta-analisis)",
        "scenario": "rescate",
        "intervention": "Radioterapia adyuvante inmediata",
        "control": "Radioterapia de rescate temprano",
        "primary_endpoint": "Supervivencia libre de evento (meta-analisis RADICALS-RT + RAVES + GETUG-AFU 17)",
        "key_result": "Meta-analisis de 3 ensayos (n=2,153): sin diferencia en supervivencia libre de evento "
                      "(HR 0.95, IC95% 0.80-1.14). Evidencia nivel 1 favoreciendo rescate temprano.",
        "population": "Post-prostatectomia con factores adversos, PSA indetectable.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 0.2,
            "gleason_min": 6, "gleason_max": 10,
            "stage_min": "T3A", "stage_max": "T4",
            "ecog_max": 2,
            "metastasis": "M0",
            "prior_prostatectomy": True,
        },
        "mexican_applicability": (
            "Altamente aplicable. El meta-analisis ARTISTIC proporciona la evidencia mas robusta "
            "para la estrategia de rescate temprano versus adyuvancia, lo cual es particularmente "
            "relevante para la politica de salud publica en Mexico: evitar RT innecesaria ahorra "
            "recursos y reduce toxicidad sin afectar supervivencia."
        ),
        "nccn_category": "1",
        "year": 2020,
    },
    {
        "name": "RTOG 9601",
        "phase": "III",
        "scenario": "rescate",
        "intervention": "RT de rescate + bicalutamida 150 mg diaria por 24 meses",
        "control": "RT de rescate + placebo",
        "primary_endpoint": "Supervivencia global",
        "key_result": "La adición de bicalutamida prolongada a la RT de rescate mejoró supervivencia global y redujo metástasis a distancia en el escenario adecuado.",
        "population": "Recurrencia bioquímica post-prostatectomía con PSA detectable, sin metástasis.",
        "eligibility_criteria": {
            "psa_min": 0.2, "psa_max": 4.0,
            "gleason_min": 6, "gleason_max": 10,
            "stage_min": "T1A", "stage_max": "T4",
            "ecog_max": 2,
            "metastasis": "M0",
            "prior_prostatectomy": True,
        },
        "mexican_applicability": (
            "Alta aplicabilidad. La RT de rescate está ampliamente disponible y bicalutamida es accesible; "
            "el estudio respalda intensificar la RT de rescate en pacientes seleccionados con recurrencia post-RP."
        ),
        "nccn_category": "1",
        "year": 2017,
    },
    {
        "name": "SPPORT",
        "phase": "III",
        "scenario": "rescate",
        "intervention": "RT de lecho prostático + RT pélvica + ADT corta",
        "control": "RT de lecho sola o RT de lecho + ADT corta",
        "primary_endpoint": "Supervivencia libre de progresión",
        "key_result": "La combinación de RT de lecho, nodos pélvicos y ADT corta mejoró el control de progresión frente a estrategias menos intensificadas.",
        "population": "Recurrencia bioquímica post-prostatectomía con PSA detectable y sin metástasis.",
        "eligibility_criteria": {
            "psa_min": 0.1, "psa_max": 2.0,
            "gleason_min": 6, "gleason_max": 10,
            "stage_min": "T1A", "stage_max": "T4",
            "ecog_max": 2,
            "metastasis": "M0",
            "prior_prostatectomy": True,
        },
        "mexican_applicability": (
            "Alta aplicabilidad en centros con radioterapia de lecho y nodos pélvicos. Ayuda a decidir intensificación locorregional y ADT corta en salvage seleccionado."
        ),
        "nccn_category": "1",
        "year": 2022,
    },
    {
        "name": "EMPIRE-1",
        "phase": "II/III",
        "scenario": "rescate",
        "intervention": "Planificación de RT de salvage guiada por imagen molecular",
        "control": "Planificación convencional de RT de salvage",
        "primary_endpoint": "Supervivencia libre de evento",
        "key_result": "La reestadificación guiada por imagen modificó la planificación y mejoró el control del evento en el contexto de salvage.",
        "population": "Recurrencia bioquímica post-prostatectomía candidata a RT de salvage.",
        "eligibility_criteria": {
            "psa_min": 0.1, "psa_max": 10.0,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 2,
            "metastasis": "M0",
            "prior_prostatectomy": True,
        },
        "mexican_applicability": (
            "Aplicabilidad contextual. La disponibilidad de PSMA o imagen molecular aún varía, pero el estudio respalda usar reestadificación dirigida antes de cerrar la RT de rescate."
        ),
        "nccn_category": "2A",
        "year": 2021,
    },
    {
        "name": "EMBARK",
        "phase": "III",
        "scenario": "rescate",
        "intervention": "Enzalutamida con o sin leuprolida",
        "control": "Leuprolida sola",
        "primary_endpoint": "Supervivencia libre de metástasis",
        "key_result": "En recurrencia bioquímica de alto riesgo no metastásica, enzalutamida con o sin ADT mejoró la supervivencia libre de metástasis.",
        "population": "Recurrencia bioquímica de alto riesgo no metastásica, fuera de una ruta curativa local razonable.",
        "eligibility_criteria": {
            "psa_min": 1.0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M0",
            "prior_prostatectomy": True,
            "psadt_max_months": 9,
        },
        "mexican_applicability": (
            "Aplicabilidad selectiva. EMBARK corresponde a BCR no metastásica de alto riesgo cuando la ruta de salvage local ya no es la dominante o no es razonable."
        ),
        "nccn_category": "1",
        "year": 2023,
    },

    # ===================================================================
    # mHSPC (Metastatico Hormono-Sensible)
    # ===================================================================
    {
        "name": "CHAARTED",
        "phase": "III",
        "scenario": "mHSPC",
        "intervention": "ADT + Docetaxel (6 ciclos)",
        "control": "ADT sola",
        "primary_endpoint": "Supervivencia global",
        "key_result": "Beneficio en SG de 17 meses en alto volumen (HR 0.60). "
                      "Sin beneficio significativo en bajo volumen (HR 0.86, p=0.30).",
        "population": "mHSPC de novo o recurrente. Criterios de alto volumen: metastasis viscerales "
                      "Y/O >= 4 metastasis oseas (con >=1 fuera del esqueleto axial).",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "stage_min": "T1A", "stage_max": "T4",
            "ecog_max": 2,
            "metastasis": "M1",
            "fit_for_chemotherapy": True,
        },
        "mexican_applicability": (
            "Alta aplicabilidad con precauciones. Docetaxel esta disponible en la mayoria de centros "
            "oncologicos mexicanos y es una de las opciones mas costo-efectivas en mHSPC. Sin embargo, "
            "la clasificacion alto/bajo volumen requiere imagenologia adecuada (gammagrafia osea, TAC). "
            "En Mexico, dado que muchos pacientes se diagnostican en etapas avanzadas (alto volumen), "
            "la estrategia CHAARTED es especialmente relevante."
        ),
        "nccn_category": "1",
        "year": 2015,
    },
    {
        "name": "LATITUDE",
        "phase": "III",
        "scenario": "mHSPC",
        "intervention": "ADT + Abiraterona + Prednisona",
        "control": "ADT + Placebo",
        "primary_endpoint": "Supervivencia global y SLP radiografica (co-primarios)",
        "key_result": "Mejoria significativa en SG (HR 0.62) y rPFS (HR 0.47). "
                      "Beneficio demostrado solo en alto riesgo (>=2 de: Gleason >=8, >=3 mets oseas, met visceral).",
        "population": "mHSPC de novo, alto riesgo (criterios LATITUDE: >=2 de 3 factores).",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 8, "gleason_max": 10,
            "stage_min": "T1A", "stage_max": "T4",
            "ecog_max": 2,
            "metastasis": "M1",
            "de_novo": True,
            "high_risk_latitude": True,
        },
        "mexican_applicability": (
            "Alta aplicabilidad pero con retos de acceso. Abiraterona generico esta disponible en Mexico, "
            "reduciendo significativamente el costo. Requiere monitoreo de funcion hepatica, potasio y "
            "presion arterial (efectos mineralocorticoides). En poblacion mexicana con alta prevalencia "
            "de hipertension y diabetes, el monitoreo debe ser mas estricto. La prednisona concurrente "
            "puede complicar el control glucemico."
        ),
        "nccn_category": "1",
        "year": 2017,
    },
    {
        "name": "TITAN",
        "phase": "III",
        "scenario": "mHSPC",
        "intervention": "ADT + Apalutamida",
        "control": "ADT + Placebo",
        "primary_endpoint": "SLP radiografica y Supervivencia global (co-primarios)",
        "key_result": "Beneficio en SG (HR 0.67) y rPFS (HR 0.48) independientemente del volumen de enfermedad. "
                      "Beneficio en AMBOS alto y bajo volumen/riesgo.",
        "population": "mHSPC, todos los volúmenes (alto y bajo). Incluyo de novo y recurrente.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "stage_min": "T1A", "stage_max": "T4",
            "ecog_max": 1,
            "metastasis": "M1",
        },
        "mexican_applicability": (
            "Alta aplicabilidad. Apalutamida es una opcion oral que no requiere prednisona concomitante "
            "(ventaja en pacientes diabeticos). El beneficio en todos los volúmenes la hace versatil. "
            "En Mexico, el rash cutaneo (27%) debe monitorearse, especialmente en clima calido. "
            "Disponible a traves de programas de acceso en el sector salud."
        ),
        "nccn_category": "1",
        "year": 2019,
    },
    {
        "name": "ARCHES",
        "phase": "III",
        "scenario": "mHSPC",
        "intervention": "ADT + Enzalutamida",
        "control": "ADT + Placebo",
        "primary_endpoint": "SLP radiografica",
        "key_result": "Reduccion de 61% en riesgo de progresion radiografica o muerte (HR 0.39). "
                      "Beneficio en SG en seguimiento extendido (HR 0.66).",
        "population": "mHSPC, todos los volúmenes. Permitia Docetaxel previo.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "stage_min": "T1A", "stage_max": "T4",
            "ecog_max": 1,
            "metastasis": "M1",
        },
        "mexican_applicability": (
            "Alta aplicabilidad. Enzalutamida tiene amplia experiencia en Mexico. El perfil de "
            "eventos adversos incluye fatiga e hipertension, requiriendo monitoreo cardiovascular. "
            "Precaucion en pacientes con antecedente de crisis convulsivas (exclusion del estudio). "
            "El beneficio en todos los volúmenes permite su uso amplio."
        ),
        "nccn_category": "1",
        "year": 2019,
    },
    {
        "name": "ENZAMET",
        "phase": "III",
        "scenario": "mHSPC",
        "intervention": "ADT + Enzalutamida",
        "control": "ADT + Antiandrogeneo convencional (Bicalutamida)",
        "primary_endpoint": "Supervivencia global",
        "key_result": "Mejoria significativa en SG (HR 0.67). Beneficio mas claro en bajo volumen "
                      "y en pacientes sin Docetaxel concurrente.",
        "population": "mHSPC, todos los volúmenes. Permitia Docetaxel concurrente (estratificacion).",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "stage_min": "T1A", "stage_max": "T4",
            "ecog_max": 2,
            "metastasis": "M1",
        },
        "mexican_applicability": (
            "Alta aplicabilidad. ENZAMET comparo contra bicalutamida (estandar previo en Mexico), "
            "demostrando superioridad de enzalutamida. Esto es relevante porque la bicalutamida "
            "sigue siendo usada en algunos centros mexicanos por costo. El estudio valida la "
            "transicion a ARPIs de nueva generacion en el contexto nacional."
        ),
        "nccn_category": "1",
        "year": 2019,
    },
    {
        "name": "ARASENS",
        "phase": "III",
        "scenario": "mHSPC",
        "intervention": "ADT + Docetaxel + Darolutamida (triplete)",
        "control": "ADT + Docetaxel + Placebo",
        "primary_endpoint": "Supervivencia global",
        "key_result": "Reduccion de 32.5% en riesgo de muerte (HR 0.68, p<0.001). "
                      "Beneficio consistente independientemente del volumen. Perfil de seguridad favorable.",
        "population": "mHSPC candidatos a quimioterapia (ADT + Docetaxel como backbone).",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "stage_min": "T1A", "stage_max": "T4",
            "ecog_max": 1,
            "metastasis": "M1",
            "fit_for_chemotherapy": True,
        },
        "mexican_applicability": (
            "Moderada-alta aplicabilidad. El triplete requiere que el paciente sea candidato a "
            "quimioterapia, lo cual es factible en centros oncologicos mexicanos. Darolutamida "
            "tiene menor penetracion a barrera hematoencefalica, reduciendo riesgo de convulsiones "
            "y caidas (ventaja en poblacion geriatrica mexicana). El costo del triplete es una "
            "barrera, pero el acceso a darolutamida esta mejorando."
        ),
        "nccn_category": "1",
        "year": 2022,
    },
    {
        "name": "PEACE-1",
        "phase": "III",
        "scenario": "mHSPC",
        "intervention": "ADT + Docetaxel + Abiraterona (triplete) +/- RT local",
        "control": "ADT + Docetaxel",
        "primary_endpoint": "SLP radiografica y Supervivencia global (co-primarios)",
        "key_result": "Triplete con abiraterona mejoro rPFS (HR 0.50) y SG (HR 0.75, p=0.017). "
                      "Beneficio marcado en alto volumen de novo.",
        "population": "mHSPC de novo, candidatos a quimioterapia. Sub-estudio RT al primario en bajo volumen.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "stage_min": "T1A", "stage_max": "T4",
            "ecog_max": 1,
            "metastasis": "M1",
            "de_novo": True,
            "fit_for_chemotherapy": True,
        },
        "mexican_applicability": (
            "Moderada aplicabilidad. El triplete ADT+Docetaxel+Abiraterona es intensivo pero "
            "factible. Abiraterona generico reduce el costo. La RT al primario en bajo volumen "
            "(sub-estudio) es una adicion importante con buena disponibilidad en Mexico. "
            "El monitoreo hepatico y cardiovascular intensivo requerido puede ser un reto en "
            "consulta de alta demanda del sector publico."
        ),
        "nccn_category": "1",
        "year": 2022,
    },
    {
        "name": "STAMPEDE",
        "phase": "II/III (Plataforma multi-brazo)",
        "scenario": "mHSPC",
        "intervention": "Multiples brazos: ADT + Docetaxel, ADT + Abiraterona, ADT + RT local",
        "control": "ADT sola (brazo control estandar)",
        "primary_endpoint": "Supervivencia global (analisis por brazo)",
        "key_result": "Abiraterona: HR 0.63 en SG. Docetaxel: HR 0.78 en SG. RT al primario: "
                      "HR 0.68 en SG en bajo volumen. Plataforma que valido multiples intensificaciones.",
        "population": "mHSPC de novo y localmente avanzado (N+/M+). Diseno adaptativo multi-brazo.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "stage_min": "T1A", "stage_max": "T4",
            "ecog_max": 2,
            "metastasis": "M1",
        },
        "mexican_applicability": (
            "Alta aplicabilidad. STAMPEDE proporciona evidencia complementaria para todas las "
            "opciones de intensificacion disponibles en Mexico. El brazo de RT al primario en "
            "bajo volumen es especialmente relevante dada la amplia disponibilidad de RT en "
            "el pais. Los resultados de abiraterona son consistentes con LATITUDE."
        ),
        "nccn_category": "1",
        "year": 2016,
    },

    # ===================================================================
    # nmCRPC (No Metastatico, Resistente a Castracion)
    # ===================================================================
    {
        "name": "SPARTAN",
        "phase": "III",
        "scenario": "nmCRPC",
        "intervention": "Apalutamida + ADT",
        "control": "Placebo + ADT",
        "primary_endpoint": "Supervivencia libre de metastasis (MFS)",
        "key_result": "Mejoria en MFS de 40.5 vs 16.2 meses (HR 0.28, p<0.001). "
                      "Beneficio en SG en analisis final (HR 0.78).",
        "population": "nmCRPC de alto riesgo (PSADT <= 10 meses). Sin metastasis por imagen convencional.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M0",
            "castration_resistant": True,
            "psadt_max_months": 10,
        },
        "mexican_applicability": (
            "Moderada aplicabilidad. Requiere confirmacion de estado no metastatico por imagen "
            "convencional (gammagrafia + TAC), lo cual es factible en Mexico. Sin embargo, la "
            "definicion de nmCRPC puede cambiar con acceso a PET-PSMA (que reclasificaria muchos "
            "pacientes como mCRPC). El costo de apalutamida es una barrera importante en el "
            "sector publico mexicano."
        ),
        "nccn_category": "1",
        "year": 2018,
    },
    {
        "name": "PROSPER",
        "phase": "III",
        "scenario": "nmCRPC",
        "intervention": "Enzalutamida + ADT",
        "control": "Placebo + ADT",
        "primary_endpoint": "Supervivencia libre de metastasis (MFS)",
        "key_result": "MFS: 36.6 vs 14.7 meses (HR 0.29, p<0.001). "
                      "Beneficio en SG confirmado (HR 0.73).",
        "population": "nmCRPC de alto riesgo (PSADT <= 10 meses).",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M0",
            "castration_resistant": True,
            "psadt_max_months": 10,
        },
        "mexican_applicability": (
            "Moderada aplicabilidad. Enzalutamida tiene mayor experiencia clinica en Mexico. "
            "Mismas consideraciones que SPARTAN respecto a la definicion de nmCRPC y el impacto "
            "del PET-PSMA. El perfil de toxicidad (fatiga, hipertension, riesgo convulsivo) "
            "requiere monitoreo adaptado al contexto clinico."
        ),
        "nccn_category": "1",
        "year": 2018,
    },
    {
        "name": "ARAMIS",
        "phase": "III",
        "scenario": "nmCRPC",
        "intervention": "Darolutamida + ADT",
        "control": "Placebo + ADT",
        "primary_endpoint": "Supervivencia libre de metastasis (MFS)",
        "key_result": "MFS: 40.4 vs 18.4 meses (HR 0.41, p<0.001). "
                      "SG: HR 0.69. Perfil de seguridad favorable (similar a placebo en muchos EA).",
        "population": "nmCRPC de alto riesgo (PSADT <= 10 meses).",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M0",
            "castration_resistant": True,
            "psadt_max_months": 10,
        },
        "mexican_applicability": (
            "Moderada-alta aplicabilidad. Darolutamida tiene el mejor perfil de seguridad entre "
            "los ARPIs (baja penetracion BHE, menor fatiga, sin riesgo convulsivo significativo). "
            "Esto la hace ideal para poblacion geriatrica mexicana con polifarmacia y comorbilidades. "
            "Su disponibilidad en Mexico esta en expansion."
        ),
        "nccn_category": "1",
        "year": 2019,
    },

    # ===================================================================
    # mCRPC (Metastatico Resistente a Castracion)
    # ===================================================================
    {
        "name": "COU-AA-301",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Abiraterona + Prednisona",
        "control": "Placebo + Prednisona",
        "primary_endpoint": "Supervivencia global",
        "key_result": "Mejoria en SG: 15.8 vs 11.2 meses (HR 0.74, p<0.001). "
                      "Post-docetaxel. Reduccion de 26% en riesgo de muerte.",
        "population": "mCRPC post-docetaxel. Progresion bioquimica o radiografica.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 2,
            "metastasis": "M1",
            "castration_resistant": True,
            "prior_docetaxel": True,
        },
        "mexican_applicability": (
            "Alta aplicabilidad. Abiraterona generico esta ampliamente disponible en Mexico y "
            "es una de las opciones mas accesibles post-docetaxel. El monitoreo de funcion "
            "hepatica y el manejo del hipopotasemia e hipertension son factibles en el "
            "contexto clinico mexicano. Incluido en guias del IMSS."
        ),
        "nccn_category": "1",
        "year": 2011,
    },
    {
        "name": "AFFIRM",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Enzalutamida",
        "control": "Placebo",
        "primary_endpoint": "Supervivencia global",
        "key_result": "Mejoria en SG: 18.4 vs 13.6 meses (HR 0.63, p<0.001). "
                      "Post-docetaxel. Beneficio en todos los subgrupos preespecificados.",
        "population": "mCRPC post-docetaxel (1-2 lineas de quimioterapia previa).",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 2,
            "metastasis": "M1",
            "castration_resistant": True,
            "prior_docetaxel": True,
        },
        "mexican_applicability": (
            "Alta aplicabilidad. Enzalutamida es una opcion oral con buena tolerancia general. "
            "En Mexico, el costo puede ser una barrera en el sector publico. El riesgo de "
            "convulsiones (0.9%) debe discutirse. Experiencia clinica amplia en centros "
            "de referencia nacionales (INCan, CMN Siglo XXI, HGM)."
        ),
        "nccn_category": "1",
        "year": 2012,
    },
    {
        "name": "PROfound",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Olaparib (inhibidor PARP)",
        "control": "Enzalutamida o Abiraterona (eleccion del investigador)",
        "primary_endpoint": "SLP radiografica (Cohorte A: BRCA1/2, ATM)",
        "key_result": "Cohorte A: rPFS 7.4 vs 3.6 meses (HR 0.34, p<0.001). "
                      "SG: HR 0.69. Primera terapia dirigida por biomarcador aprobada en CaP.",
        "population": "mCRPC con alteraciones en genes HRR (BRCA1/2, ATM en Cohorte A; otros HRR en Cohorte B). "
                      "Progresion a ARPI previo.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 2,
            "metastasis": "M1",
            "castration_resistant": True,
            "prior_arpi": True,
            "hrr_positive": True,
        },
        "mexican_applicability": (
            "Moderada aplicabilidad. PROfound requiere pruebas genomicas (NGS para HRR) que tienen "
            "disponibilidad limitada en Mexico, principalmente en sector privado e INCan. La prevalencia "
            "de mutaciones BRCA en poblacion mestiza mexicana puede diferir de las europeas. Olaparib "
            "esta aprobado por COFEPRIS pero su acceso en sector publico es restringido. Se debe "
            "promover el acceso a pruebas genomicas en centros de referencia."
        ),
        "nccn_category": "1",
        "year": 2020,
    },
    {
        "name": "VISION",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Lu-177-PSMA-617 + Mejor tratamiento estandar (BSC)",
        "control": "Mejor tratamiento estandar solo",
        "primary_endpoint": "SLP radiografica y Supervivencia global (co-primarios)",
        "key_result": "rPFS: 8.7 vs 3.4 meses (HR 0.40). SG: 15.3 vs 11.3 meses (HR 0.62, p<0.001). "
                      "Requiere PET-PSMA positivo (al menos 1 lesion PSMA+, sin lesion PSMA- dominante).",
        "population": "mCRPC post-ARPI y post-taxano (>=1 ARPI y >=1 taxano). PSMA-PET positivo.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 2,
            "metastasis": "M1",
            "castration_resistant": True,
            "prior_arpi": True,
            "prior_docetaxel": True,
            "psma_pet_positive": True,
        },
        "mexican_applicability": (
            "Baja-moderada aplicabilidad actualmente. Lu-177-PSMA tiene disponibilidad limitada en "
            "Mexico (INCan, algunos centros de medicina nuclear privados). El PET-PSMA esta en "
            "expansion pero sigue siendo costoso y poco accesible en el sector publico. Sin embargo, "
            "Mexico tiene experiencia creciente en medicina nuclear que puede facilitar la adopcion. "
            "El acceso a Ga-68-PSMA o F-18-PSMA PET es el principal cuello de botella."
        ),
        "nccn_category": "1",
        "year": 2021,
    },
    {
        "name": "KEYNOTE-158",
        "phase": "II (Canasta)",
        "scenario": "mCRPC",
        "intervention": "Pembrolizumab (200 mg Q3W)",
        "control": "Estudio de brazo unico (no controlado)",
        "primary_endpoint": "Tasa de respuesta objetiva (ORR)",
        "key_result": "ORR del 38.1% en tumores MSI-H/dMMR (incluye CaP). "
                      "Respuestas duraderas (mediana no alcanzada). Aprobacion histology-agnostic.",
        "population": "Tumores solidos MSI-H/dMMR, incluyendo CaP. Post-progresion a terapia estandar.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M1",
            "castration_resistant": True,
            "msi_high": True,
        },
        "mexican_applicability": (
            "Baja-moderada aplicabilidad. La prevalencia de MSI-H en CaP es baja (2-3%), y las "
            "pruebas de MSI/MMR no se realizan rutinariamente en cancer de prostata en Mexico. "
            "Pembrolizumab esta disponible pero es costoso. La identificacion de pacientes MSI-H "
            "requiere inmunohistoquimica de MMR o PCR de MSI, que estan disponibles en centros "
            "de referencia. Se debe promover el tamizaje de MSI en CaP avanzado."
        ),
        "nccn_category": "2A",
        "year": 2020,
    },
    {
        "name": "CARD",
        "phase": "IV (Prospectivo)",
        "scenario": "mCRPC",
        "intervention": "Cabazitaxel + Prednisona",
        "control": "Abiraterona o Enzalutamida (ARPI alternativo)",
        "primary_endpoint": "SLP radiografica",
        "key_result": "rPFS: 8.0 vs 3.7 meses (HR 0.54, p<0.001). SG: HR 0.64. "
                      "Cabazitaxel superior a segundo ARPI secuencial post-docetaxel+ARPI.",
        "population": "mCRPC previamente tratado con docetaxel y un ARPI (abiraterona o enzalutamida). "
                      "Progresion dentro de 12 meses del inicio del ARPI previo.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 2,
            "metastasis": "M1",
            "castration_resistant": True,
            "prior_arpi": True,
            "prior_docetaxel": True,
        },
        "mexican_applicability": (
            "Moderada aplicabilidad. Cabazitaxel esta disponible en Mexico pero es mas costoso "
            "que docetaxel. CARD demuestra que un segundo ARPI secuencial es inferior a cabazitaxel "
            "en este escenario, lo cual es relevante porque la practica de secuenciar ARPIs "
            "(abiraterona -> enzalutamida o viceversa) es comun en Mexico por costo. Este estudio "
            "apoya el uso de cabazitaxel cuando el paciente progresa rapidamente a un ARPI."
        ),
        "nccn_category": "1",
        "year": 2019,
    },
    {
        "name": "ALSYMPCA",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Radium-223 (6 inyecciones mensuales)",
        "control": "Placebo + Mejor tratamiento de soporte",
        "primary_endpoint": "Supervivencia global",
        "key_result": "Mejoria en SG: 14.9 vs 11.3 meses (HR 0.70, p=0.002). "
                      "Reduccion de eventos esqueleticos. Solo metastasis oseas, sin viscerales.",
        "population": "mCRPC con metastasis oseas sintomaticas. Sin metastasis viscerales conocidas. "
                      "Post-docetaxel o no candidatos a docetaxel.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 2,
            "metastasis": "M1",
            "castration_resistant": True,
            "bone_metastases": True,
            "visceral_metastases": False,
            "symptomatic_bone": True,
        },
        "mexican_applicability": (
            "Moderada aplicabilidad. Radium-223 tiene disponibilidad limitada en Mexico, "
            "restringido a centros de medicina nuclear especializados. El costo es alto y "
            "rara vez cubierto por el sector publico. Sin embargo, es una opcion importante "
            "para pacientes con metastasis oseas sintomaticas sin enfermedad visceral. "
            "La logistica de manejo de material radiactivo es factible en centros de tercer nivel."
        ),
        "nccn_category": "1",
        "year": 2013,
    },
    {
        "name": "PRESTO / AFT-19",
        "phase": "III",
        "scenario": "rescate",
        "intervention": "ADT intensificada con apalutamida +/- abiraterona/prednisona",
        "control": "ADT sola",
        "primary_endpoint": "Supervivencia libre de progresion bioquimica",
        "key_result": "En recurrencia bioquimica de alto riesgo sensible a castracion, la intensificacion del bloqueo androgenico mejoro el control bioquimico; el triplete aumento hipertension grado >=3.",
        "population": "Recurrencia bioquimica de alto riesgo con PSADT <= 9 meses, sin metastasis documentadas.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M0",
            "castration_resistant": False,
            "psadt_max_months": 9,
        },
        "mexican_applicability": "Aplicabilidad selectiva: exige confirmar BCR M0 de alto riesgo y cerrar primero la posibilidad de salvage local curativo.",
        "nccn_category": "2A",
        "year": 2024,
    },
    {
        "name": "ARANOTE",
        "phase": "III",
        "scenario": "mHSPC",
        "intervention": "Darolutamida + ADT",
        "control": "Placebo + ADT",
        "primary_endpoint": "Supervivencia libre de progresion radiografica",
        "key_result": "Darolutamida + ADT redujo el riesgo de progresion radiografica o muerte frente a ADT sola en mHSPC.",
        "population": "mHSPC sin requerir docetaxel como backbone; alternativa de doblete cuando triplete no es ideal.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 2,
            "metastasis": "M1",
            "castration_resistant": False,
        },
        "mexican_applicability": "Alta relevancia en pacientes con mHSPC y fragilidad, neuropatia, reserva hematologica limitada o preferencia por evitar docetaxel.",
        "nccn_category": "1",
        "year": 2024,
    },
    {
        "name": "AMPLITUDE",
        "phase": "III",
        "scenario": "mHSPC",
        "intervention": "Niraparib + abiraterona/prednisona + ADT",
        "control": "Abiraterona/prednisona + ADT",
        "primary_endpoint": "Supervivencia libre de progresion radiografica",
        "key_result": "En mCSPC/mHSPC con alteraciones HRR, niraparib + abiraterona mejoro rPFS frente a abiraterona sola.",
        "population": "mHSPC/mCSPC con alteracion HRR definida por ensayo molecular central o equivalente trazable.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M1",
            "castration_resistant": False,
            "hrr_positive": True,
        },
        "mexican_applicability": "Dependiente de acceso a NGS germinal/somatico; no debe abrirse sin gen HRR, fuente y fecha del ensayo.",
        "nccn_category": "2A",
        "year": 2025,
    },
    {
        "name": "TAX-327",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Docetaxel + Prednisona cada 3 semanas",
        "control": "Mitoxantrona + Prednisona",
        "primary_endpoint": "Supervivencia global",
        "key_result": "Docetaxel cada 3 semanas mejoro supervivencia, dolor, calidad de vida y respuesta PSA frente a mitoxantrona.",
        "population": "mCRPC/hormono-refractario metastasico candidato a quimioterapia.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 2,
            "metastasis": "M1",
            "castration_resistant": True,
            "fit_for_chemotherapy": True,
        },
        "mexican_applicability": "Muy alta: docetaxel es disponible y sigue siendo columna para pacientes aptos; exige ANC, neuropatia y fragilidad.",
        "nccn_category": "1",
        "year": 2004,
    },
    {
        "name": "TROPIC",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Cabazitaxel + Prednisona",
        "control": "Mitoxantrona + Prednisona",
        "primary_endpoint": "Supervivencia global",
        "key_result": "Cabazitaxel mejoro supervivencia frente a mitoxantrona despues de progresion a docetaxel.",
        "population": "mCRPC con progresion durante o despues de docetaxel.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 2,
            "metastasis": "M1",
            "castration_resistant": True,
            "prior_docetaxel": True,
            "fit_for_chemotherapy": True,
        },
        "mexican_applicability": "Moderada: requiere acceso a cabazitaxel, G-CSF segun riesgo, ANC y evaluacion geriatrica/neuropatia.",
        "nccn_category": "1",
        "year": 2010,
    },
    {
        "name": "COU-AA-302",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Abiraterona + Prednisona",
        "control": "Placebo + Prednisona",
        "primary_endpoint": "rPFS y supervivencia global",
        "key_result": "Abiraterona retraso progresion radiografica, dolor y deterioro funcional en mCRPC sin quimioterapia previa.",
        "population": "mCRPC quimio-naive, asintomatico o minimamente sintomatico, sin visceral dominante.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M1",
            "castration_resistant": True,
        },
        "mexican_applicability": "Alta por disponibilidad de abiraterona generica; requiere control de hipertension, potasio, edema y hepatotoxicidad.",
        "nccn_category": "1",
        "year": 2013,
    },
    {
        "name": "PREVAIL",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Enzalutamida",
        "control": "Placebo",
        "primary_endpoint": "rPFS y supervivencia global",
        "key_result": "Enzalutamida mejoro rPFS y supervivencia en mCRPC quimio-naive.",
        "population": "mCRPC metastasico sin quimioterapia previa, progresando pese a ADT.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M1",
            "castration_resistant": True,
        },
        "mexican_applicability": "Alta si hay acceso; exige revisar convulsiones, caidas, fatiga, cognicion y DDI.",
        "nccn_category": "1",
        "year": 2014,
    },
    {
        "name": "PSMAfore",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Lu-177-PSMA-617",
        "control": "Cambio de ARPI",
        "primary_endpoint": "Supervivencia libre de progresion radiografica",
        "key_result": "Lu-177-PSMA-617 mejoro rPFS frente a cambio de ARPI en mCRPC PSMA+ post-ARPI apto para diferir taxano.",
        "population": "mCRPC PSMA positivo, progresion a un ARPI, taxano-naive o apropiado para diferir taxano.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M1",
            "castration_resistant": True,
            "prior_arpi": True,
            "psma_pet_positive": True,
        },
        "mexican_applicability": "Baja-moderada por acceso a PET-PSMA y radioligando; clinicamente exige documentar PSMA+ y ausencia de lesiones dominantes PSMA negativas.",
        "nccn_category": "1",
        "year": 2025,
    },
    {
        "name": "TheraP",
        "phase": "II",
        "scenario": "mCRPC",
        "intervention": "Lu-177-PSMA-617",
        "control": "Cabazitaxel",
        "primary_endpoint": "Respuesta PSA50",
        "key_result": "Lu-177-PSMA-617 produjo mayor respuesta PSA50 que cabazitaxel en mCRPC PSMA+ seleccionado por imagen.",
        "population": "mCRPC con progresion despues de docetaxel, candidato a cabazitaxel, PSMA positivo y sin enfermedad discordante FDG+/PSMA-.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 2,
            "metastasis": "M1",
            "castration_resistant": True,
            "prior_docetaxel": True,
            "psma_pet_positive": True,
        },
        "mexican_applicability": "Limitada a centros con PET-PSMA/FDG y terapia radioligando; util para discutir secuencia vs cabazitaxel.",
        "nccn_category": "2A",
        "year": 2021,
    },
    {
        "name": "PEACE-3",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Enzalutamida + Radium-223",
        "control": "Enzalutamida",
        "primary_endpoint": "rPFS; analisis final de SG reportado posteriormente",
        "key_result": "La combinacion mejoro rPFS y en analisis final reportado mostro beneficio de supervivencia; exige agente protector oseo para seguridad esqueletica.",
        "population": "mCRPC de primera linea con metastasis oseas, sin metastasis viscerales dominantes.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M1",
            "castration_resistant": True,
            "bone_metastases": True,
            "visceral_metastases": False,
        },
        "mexican_applicability": "Selectiva: solo si hay acceso a radio-223 y proteccion osea; bloquear si hay riesgo alto de fractura sin BPA.",
        "nccn_category": "2A",
        "year": 2025,
    },
    {
        "name": "PROpel",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Olaparib + Abiraterona/Prednisona",
        "control": "Placebo + Abiraterona/Prednisona",
        "primary_endpoint": "rPFS",
        "key_result": "Olaparib + abiraterona mejoro rPFS en primera linea mCRPC; beneficio clinico regulatorio se concentra en alteraciones BRCA/HRR segun jurisdiccion.",
        "population": "mCRPC primera linea, sin tratamiento sistémico previo para mCRPC.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M1",
            "castration_resistant": True,
        },
        "mexican_applicability": "Requiere trazabilidad molecular, hemograma y funcion renal; evitar abrir PARP sin biomarcador verificable cuando la regulacion local lo exige.",
        "nccn_category": "1",
        "year": 2022,
    },
    {
        "name": "MAGNITUDE",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Niraparib + Abiraterona/Prednisona",
        "control": "Placebo + Abiraterona/Prednisona",
        "primary_endpoint": "rPFS",
        "key_result": "Niraparib + abiraterona mejoro rPFS en HRR+ y especialmente BRCA1/2; el brazo HRR negativo se cerro por futilidad.",
        "population": "mCRPC primera linea con alteracion HRR, particularmente BRCA1/2.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M1",
            "castration_resistant": True,
            "hrr_positive": True,
        },
        "mexican_applicability": "Depende de prueba HRR/BRCA y vigilancia de citopenias; no debe priorizarse en HRR negativo.",
        "nccn_category": "1",
        "year": 2023,
    },
    {
        "name": "TALAPRO-2",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Talazoparib + Enzalutamida",
        "control": "Placebo + Enzalutamida",
        "primary_endpoint": "rPFS",
        "key_result": "Talazoparib + enzalutamida mejoro rPFS en mCRPC con alteraciones HRR.",
        "population": "mCRPC primera linea con alteracion HRR; sin terapia sistémica previa para mCRPC.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M1",
            "castration_resistant": True,
            "hrr_positive": True,
        },
        "mexican_applicability": "Requiere HRR trazable y control de anemia/citopenias; considerar DDI y riesgo de caidas/fatiga por enzalutamida.",
        "nccn_category": "1",
        "year": 2023,
    },
    {
        "name": "TRITON-3",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Rucaparib",
        "control": "Eleccion del medico: docetaxel o ARPI alternativo",
        "primary_endpoint": "rPFS",
        "key_result": "Rucaparib mejoro rPFS frente a eleccion del medico en mCRPC con BRCA/ATM tras ARPI.",
        "population": "mCRPC con alteracion BRCA1/2 o ATM, progresion a ARPI, sin quimioterapia para mCRPC.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M1",
            "castration_resistant": True,
            "prior_arpi": True,
            "hrr_positive": True,
        },
        "mexican_applicability": "Necesita gen BRCA/ATM con fuente/fecha y disponibilidad de rucaparib; vigilancia hematologica obligatoria.",
        "nccn_category": "2A",
        "year": 2023,
    },
    {
        "name": "IMPACT",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Sipuleucel-T",
        "control": "Placebo/procedimiento control",
        "primary_endpoint": "Supervivencia global",
        "key_result": "Sipuleucel-T mejoro supervivencia en mCRPC asintomatico o minimamente sintomatico, sin esperar respuestas PSA frecuentes.",
        "population": "mCRPC metastasico asintomatico o minimamente sintomatico, buen estado funcional.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M1",
            "castration_resistant": True,
        },
        "mexican_applicability": "Muy limitada por disponibilidad/logistica de inmunoterapia celular; util como referencia si se discute acceso internacional.",
        "nccn_category": "1",
        "year": 2010,
    },
    {
        "name": "IPATential150",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Ipatasertib + Abiraterona/Prednisolona",
        "control": "Placebo + Abiraterona/Prednisolona",
        "primary_endpoint": "rPFS en ITT y PTEN-loss",
        "key_result": "Mejoro rPFS en tumores PTEN-loss, sin beneficio final claro de supervivencia global.",
        "population": "mCRPC previamente no tratado, asintomatico o minimamente sintomatico, ECOG 0-1; subgrupo PTEN-loss.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M1",
            "castration_resistant": True,
        },
        "mexican_applicability": "Investigacional/biomarcador dependiente; no usar como recomendacion estandar sin PTEN y acceso a protocolo.",
        "nccn_category": "2B",
        "year": 2021,
    },
    {
        "name": "CONTACT-02",
        "phase": "III",
        "scenario": "mCRPC",
        "intervention": "Cabozantinib + Atezolizumab",
        "control": "Segundo tratamiento hormonal novedoso",
        "primary_endpoint": "rPFS y supervivencia global",
        "key_result": "Mejoro rPFS frente a switch hormonal en mCRPC con enfermedad de tejido blando extrapélvica medible post-ARPI; OS final no fue estadisticamente significativa.",
        "population": "mCRPC con progresion a un ARPI y metastasis de tejido blando extrapelvicas medibles.",
        "eligibility_criteria": {
            "psa_min": 0, "psa_max": 99999,
            "gleason_min": 6, "gleason_max": 10,
            "ecog_max": 1,
            "metastasis": "M1",
            "castration_resistant": True,
            "prior_arpi": True,
        },
        "mexican_applicability": "Debe tratarse como perfil de alto riesgo/ensayo o acceso regulatorio especifico; requiere documentar enfermedad medible, higado/visceral, autoinmunidad y toxicidad TKI/ICI.",
        "nccn_category": "2B",
        "year": 2025,
    },
]

# Indice por nombre para busquedas rapidas
_STUDY_INDEX: dict[str, dict[str, Any]] = {
    s["name"].upper(): s for s in PIVOTAL_STUDIES
}


# ===========================================================================
# FUNCIONES DE CONSULTA Y FILTRADO
# ===========================================================================

def get_study_details(study_name: str) -> Optional[dict[str, Any]]:
    """
    Obtiene la informacion completa de un estudio pivotal por nombre.

    Parameters
    ----------
    study_name : str
        Nombre del estudio (case-insensitive). Ejemplos: 'CHAARTED', 'ProtecT', 'VISION'.

    Returns
    -------
    dict | None
        Diccionario completo del estudio, o None si no se encuentra.
    """
    result = _STUDY_INDEX.get(study_name.upper().strip())
    if result is None:
        logger.warning("Estudio '%s' no encontrado en la base de datos pivotal.", study_name)
    return result


def get_studies_by_scenario(scenario: str) -> list[dict[str, Any]]:
    """
    Filtra los estudios pivotales por escenario clinico.

    Parameters
    ----------
    scenario : str
        Escenario clinico. Valores validos:
        'localizado', 'adyuvancia', 'rescate', 'mHSPC', 'nmCRPC', 'mCRPC'.

    Returns
    -------
    list[dict]
        Lista de estudios que corresponden al escenario solicitado.
        Lista vacia si el escenario no es valido o no hay estudios.
    """
    normalized = scenario.strip()
    # Permitir busqueda case-insensitive para escenarios en minusculas
    matches = [s for s in PIVOTAL_STUDIES if s["scenario"].lower() == normalized.lower()]
    if not matches:
        logger.warning(
            "No se encontraron estudios para el escenario '%s'. Escenarios validos: %s",
            scenario, ", ".join(VALID_SCENARIOS),
        )
    return matches


# ===========================================================================
# MOTOR DE ELEGIBILIDAD — CONFRONTACION PACIENTE vs ESTUDIOS
# ===========================================================================

def _check_numeric_range(
    patient_value: Optional[float],
    criteria: dict[str, Any],
    key_min: str,
    key_max: str,
) -> tuple[bool, str]:
    """
    Verifica si un valor numerico del paciente cae dentro del rango del estudio.

    Returns
    -------
    (cumple, detalle) : tuple[bool, str]
    """
    if patient_value is None:
        return True, "No disponible (asumido elegible)"

    c_min = criteria.get(key_min)
    c_max = criteria.get(key_max)

    if c_min is not None and patient_value < c_min:
        return False, f"Valor {patient_value} < minimo {c_min}"
    if c_max is not None and patient_value > c_max:
        return False, f"Valor {patient_value} > maximo {c_max}"
    return True, f"Valor {patient_value} dentro del rango [{c_min}-{c_max}]"


def _check_stage_range(
    patient_stage: Optional[str],
    criteria: dict[str, Any],
) -> tuple[bool, str]:
    """Verifica si el estadio clinico del paciente cae dentro del rango del estudio."""
    if not patient_stage:
        return True, "Estadio no disponible (asumido elegible)"

    stage_min = criteria.get("stage_min")
    stage_max = criteria.get("stage_max")

    p_rank = _stage_rank(patient_stage)
    if p_rank == 0:
        return True, f"Estadio '{patient_stage}' no clasificable, asumido elegible"

    if stage_min and p_rank < _stage_rank(stage_min):
        return False, f"Estadio {patient_stage} inferior al minimo {stage_min}"
    if stage_max and p_rank > _stage_rank(stage_max):
        return False, f"Estadio {patient_stage} superior al maximo {stage_max}"
    return True, f"Estadio {patient_stage} dentro del rango [{stage_min}-{stage_max}]"


def _check_boolean_criterion(
    patient_value: Optional[bool],
    criteria: dict[str, Any],
    key: str,
    label: str,
) -> tuple[bool, str]:
    """Verifica un criterio booleano del estudio contra el dato del paciente."""
    required = criteria.get(key)
    if required is None:
        return True, f"{label}: no requerido por el estudio"
    if patient_value is None:
        return True, f"{label}: dato no disponible, asumido elegible"
    if required == patient_value:
        return True, f"{label}: cumple (paciente={patient_value}, requerido={required})"
    return False, f"{label}: NO cumple (paciente={patient_value}, requerido={required})"


def match_patient_to_studies(patient_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Confronta los datos clinicos de un paciente contra todos los estudios pivotales
    y retorna aquellos para los cuales el paciente habria sido elegible.

    Parameters
    ----------
    patient_data : dict
        Diccionario con los datos clinicos del paciente. Claves esperadas:

        - age (int): Edad del paciente
        - psa (float): PSA actual en ng/mL
        - gleason_score (int): Gleason total (6-10)
        - gleason_primary (int): Patron Gleason primario
        - isup_grade (int): Grupo de grado ISUP (1-5)
        - clinical_tstage (str): Estadio T clinico (T1c, T2a, ... T4)
        - ecog_score (int): ECOG Performance Status (0-4)
        - metastasis_status (str): 'M0' o 'M1'
        - metastasis_site (str): 'Hueso', 'Visceral', 'Ganglionar', etc.
        - metastasis_count (int): Numero de metastasis oseas
        - volume_chaarted (str): 'High' o 'Low' (clasificacion CHAARTED)
        - castration_resistant (bool): Si es resistente a castracion
        - psadt_months (float): PSA doubling time en meses
        - de_novo (bool): Si es diagnostico de novo
        - hrr_status (str): 'Positivo', 'Negativo', 'Desconocido'
        - msi_status (str): 'Estable', 'Inestable', 'High', 'dMMR'
        - psma_pet_result (str): 'Positivo', 'Negativo', 'No realizado'
        - prior_therapy (list[str]): Terapias previas
        - prior_prostatectomy (bool): Si tiene prostatectomia previa
        - bone_metastases (bool): Si tiene metastasis oseas
        - visceral_metastases (bool): Si tiene metastasis viscerales
        - symptomatic_bone (bool): Si tiene metastasis oseas sintomaticas
        - fit_for_chemotherapy (bool): Si es candidato a quimioterapia
        - comorbidities (dict): Comorbilidades (seizure, cardio, etc.)

    Returns
    -------
    list[dict]
        Lista de diccionarios, cada uno con:
        - study: dict completo del estudio
        - match_score: float (0.0 - 1.0), proporcion de criterios cumplidos
        - criteria_met: list[str], criterios cumplidos
        - criteria_failed: list[str], criterios no cumplidos
        - eligible: bool, si el paciente cumple TODOS los criterios obligatorios

        Ordenados por match_score descendente.
    """
    logger.info("Iniciando confrontacion de paciente contra %d estudios pivotales.", len(PIVOTAL_STUDIES))

    # -- Extraer datos del paciente --
    age = patient_data.get("age")
    psa = patient_data.get("psa")
    gleason = patient_data.get("gleason_score")
    if gleason is None:
        gp = patient_data.get("gleason_primary", 0)
        gs = patient_data.get("gleason_secondary", 0)
        if gp and gs:
            gleason = int(gp) + int(gs)

    ecog = patient_data.get("ecog_score", patient_data.get("ecog_performance_status"))
    clinical_stage = patient_data.get("clinical_tstage", "")
    metastasis_status = patient_data.get("metastasis_status", "")
    if not metastasis_status:
        # Inferir de metastasis_site
        meta_site = patient_data.get("metastasis_site", "M0")
        metastasis_status = "M0" if meta_site in ("M0", "", None) else "M1"

    castration_resistant = patient_data.get("castration_resistant", False)
    psadt = patient_data.get("psadt_months")
    de_novo = patient_data.get("de_novo")
    prior_therapy = patient_data.get("prior_therapy", [])
    prior_therapy_str = str(prior_therapy)

    has_prior_arpi = any(
        x in prior_therapy_str
        for x in ["Enzalutamida", "Abiraterona", "Apalutamida", "Darolutamida", "ARPI"]
    )
    has_prior_docetaxel = "Docetaxel" in prior_therapy_str

    hrr_status = patient_data.get("hrr_status", "Desconocido")
    msi_status = patient_data.get("msi_status", "Estable")
    psma_result = patient_data.get("psma_pet_result", "No realizado")
    prior_prostatectomy = patient_data.get("prior_prostatectomy", False)
    salvage_local_feasible = _coerce_bool(patient_data.get("salvage_local_feasible"))
    bone_mets = patient_data.get("bone_metastases")
    visceral_mets = patient_data.get("visceral_metastases")
    symptomatic_bone = patient_data.get("symptomatic_bone")
    fit_chemo = patient_data.get("fit_for_chemotherapy")
    exact_state = resolve_mhspc_state(str(patient_data.get("state", "") or ""), patient_data)
    mhspc_triplet = build_triplet_decision(exact_state, patient_data) if is_mhspc_state(exact_state) else {}
    mhspc_visible_trials, mhspc_hidden_trials = visible_trials_for_mhspc_state(exact_state, patient_data) if is_mhspc_state(exact_state) else (set(), set())

    # Convertir tipos de forma segura
    if age is not None:
        age = int(age)
    if psa is not None:
        psa = float(psa)
    if gleason is not None:
        gleason = int(gleason)
    if ecog is not None:
        ecog = int(ecog)
    if psadt is not None:
        psadt = float(psadt)

    post_rp_salvage_context = str(patient_data.get("state") or "") == "recurrence_bcr" or bool(prior_prostatectomy and patient_data.get("post_rp_context"))
    if post_rp_salvage_context:
        recurrence_psa = (
            patient_data.get("psa_postop_current")
            or patient_data.get("psa_current")
            or patient_data.get("psa_postop")
            or patient_data.get("bcr_psa")
            or psa
        )
        psa = float(recurrence_psa) if recurrence_psa not in (None, "") else None

    results: list[dict[str, Any]] = []
    candidate_studies = (
        [study for study in PIVOTAL_STUDIES if study.get("name") in POST_RP_SALVAGE_TRIAL_NAMES]
        if post_rp_salvage_context
        else PIVOTAL_STUDIES
    )

    for study in candidate_studies:
        criteria = study.get("eligibility_criteria", {})
        met: list[str] = []
        failed: list[str] = []

        # --- 1. Edad ---
        ok, detail = _check_numeric_range(age, criteria, "age_min", "age_max")
        (met if ok else failed).append(f"Edad: {detail}")

        # --- 2. PSA ---
        ok, detail = _check_numeric_range(psa, criteria, "psa_min", "psa_max")
        (met if ok else failed).append(f"PSA: {detail}")

        # --- 3. Gleason ---
        ok, detail = _check_numeric_range(
            float(gleason) if gleason else None, criteria, "gleason_min", "gleason_max"
        )
        (met if ok else failed).append(f"Gleason: {detail}")

        # --- 4. Estadio clinico ---
        ok, detail = _check_stage_range(clinical_stage, criteria)
        (met if ok else failed).append(f"Estadio: {detail}")

        # --- 5. ECOG ---
        ecog_max = criteria.get("ecog_max")
        if ecog_max is not None and ecog is not None:
            if ecog <= ecog_max:
                met.append(f"ECOG: {ecog} <= {ecog_max} (cumple)")
            else:
                failed.append(f"ECOG: {ecog} > {ecog_max} (no cumple)")
        else:
            met.append("ECOG: No evaluable o no requerido")

        # --- 6. Estado metastasico ---
        req_meta = criteria.get("metastasis")
        if req_meta:
            if metastasis_status.upper() == req_meta.upper():
                met.append(f"Metastasis: {metastasis_status} == {req_meta} (cumple)")
            else:
                failed.append(f"Metastasis: {metastasis_status} != {req_meta} (no cumple)")

        # --- 7. Resistencia a castracion ---
        ok, detail = _check_boolean_criterion(
            castration_resistant, criteria, "castration_resistant", "Resistencia a castracion"
        )
        (met if ok else failed).append(detail)

        # --- 8. PSADT (para nmCRPC) ---
        psadt_max = criteria.get("psadt_max_months")
        if psadt_max is not None:
            if psadt is not None:
                if psadt <= psadt_max:
                    met.append(f"PSADT: {psadt} meses <= {psadt_max} (alto riesgo, cumple)")
                else:
                    failed.append(f"PSADT: {psadt} meses > {psadt_max} (bajo riesgo, no cumple)")
            else:
                met.append("PSADT: No disponible (asumido elegible)")

        # --- 9. De novo ---
        ok, detail = _check_boolean_criterion(de_novo, criteria, "de_novo", "Diagnostico de novo")
        (met if ok else failed).append(detail)

        # --- 10. Alto riesgo LATITUDE ---
        if criteria.get("high_risk_latitude"):
            # Calcular criterios LATITUDE: >=2 de (Gleason >=8, >=3 mets oseas, met visceral)
            lat_count = 0
            meta_count = int(patient_data.get("metastasis_count", 0))
            if gleason and gleason >= 8:
                lat_count += 1
            if meta_count >= 3:
                lat_count += 1
            if visceral_mets:
                lat_count += 1
            if lat_count >= 2:
                met.append(f"LATITUDE alto riesgo: {lat_count}/3 factores (cumple >=2)")
            else:
                failed.append(f"LATITUDE alto riesgo: {lat_count}/3 factores (no cumple, requiere >=2)")

        # --- 11. Prostatectomia previa ---
        ok, detail = _check_boolean_criterion(
            prior_prostatectomy, criteria, "prior_prostatectomy", "Prostatectomia previa"
        )
        (met if ok else failed).append(detail)

        # --- 12. Terapias previas (ARPI, Docetaxel) ---
        if criteria.get("prior_arpi"):
            if has_prior_arpi:
                met.append("ARPI previo: Si (cumple)")
            else:
                failed.append("ARPI previo: No (no cumple, estudio requiere ARPI previo)")

        if criteria.get("prior_docetaxel"):
            if has_prior_docetaxel:
                met.append("Docetaxel previo: Si (cumple)")
            else:
                failed.append("Docetaxel previo: No (no cumple, estudio requiere docetaxel previo)")

        # --- 13. HRR (para PROfound) ---
        if criteria.get("hrr_positive"):
            if hrr_status == "Positivo":
                met.append("HRR: Positivo (cumple, elegible para inhibidor PARP)")
            elif hrr_status == "Desconocido":
                met.append("HRR: Desconocido (requiere prueba genomica para confirmar elegibilidad)")
            else:
                failed.append("HRR: Negativo (no cumple, estudio requiere alteracion HRR)")

        # --- 14. MSI-H (para KEYNOTE-158) ---
        if criteria.get("msi_high"):
            if msi_status in ("Inestable", "High", "dMMR", "MSI-H"):
                met.append(f"MSI: {msi_status} (cumple, elegible para inmunoterapia)")
            elif msi_status == "Desconocido":
                met.append("MSI: Desconocido (requiere prueba IHQ/PCR para confirmar)")
            else:
                failed.append(f"MSI: {msi_status} (no cumple, estudio requiere MSI-H/dMMR)")

        # --- 15. PSMA-PET (para VISION) ---
        if criteria.get("psma_pet_positive"):
            if psma_result == "Positivo":
                met.append("PSMA-PET: Positivo (cumple)")
            elif psma_result in ("No realizado", "Desconocido", None):
                met.append("PSMA-PET: No realizado (requiere estudio para confirmar elegibilidad)")
            else:
                failed.append("PSMA-PET: Negativo (no cumple, estudio requiere PSMA+)")

        # --- 16. Metastasis oseas (ALSYMPCA) ---
        ok, detail = _check_boolean_criterion(
            bone_mets, criteria, "bone_metastases", "Metastasis oseas"
        )
        (met if ok else failed).append(detail)

        # --- 17. Ausencia de metastasis viscerales (ALSYMPCA) ---
        if "visceral_metastases" in criteria and criteria["visceral_metastases"] is False:
            if visceral_mets is True:
                failed.append("Metastasis viscerales: Presentes (estudio excluye met viscerales)")
            elif visceral_mets is False:
                met.append("Metastasis viscerales: Ausentes (cumple)")
            else:
                met.append("Metastasis viscerales: No evaluado (asumido elegible)")

        # --- 18. Metastasis oseas sintomaticas (ALSYMPCA) ---
        ok, detail = _check_boolean_criterion(
            symptomatic_bone, criteria, "symptomatic_bone", "Metastasis oseas sintomaticas"
        )
        (met if ok else failed).append(detail)

        # --- 19. Candidato a quimioterapia ---
        ok, detail = _check_boolean_criterion(
            fit_chemo, criteria, "fit_for_chemotherapy", "Candidato a quimioterapia"
        )
        (met if ok else failed).append(detail)

        study_name = str(study.get("name") or "")
        if is_mhspc_state(exact_state) and study.get("scenario") == "mHSPC":
            if study_name in mhspc_hidden_trials:
                failed.append(f"Subescenario mHSPC actual: {exact_state} (estudio oculto por no concordar con volumen/temporalidad)")
            elif mhspc_visible_trials and study_name not in mhspc_visible_trials:
                failed.append(f"Subescenario mHSPC actual: {exact_state} (estudio fuera de la superficie clínica priorizada)")

            if study_name == "ARASENS" and not bool(mhspc_triplet.get("is_triplet_candidate")):
                failed.append("Triplete con docetaxel no indicado o no seguro en este caso")
            if study_name == "PEACE-1":
                if exact_state != "mcspc_high_volume_sync":
                    failed.append("PEACE-1 se restringe a enfermedad de novo/sincrónica de alto volumen en esta correlación clínica")
                elif not bool(mhspc_triplet.get("is_triplet_candidate")):
                    failed.append("PEACE-1 requiere aptitud actual para triplete con docetaxel")
        if post_rp_salvage_context:
            if study_name == "EMBARK":
                if salvage_local_feasible is True:
                    failed.append("Existe una ruta de salvage local potencialmente curativa; EMBARK no lidera mientras esa vía siga abierta")
                if psadt is None:
                    failed.append("PSADT no documentado para comprobar recurrencia bioquímica de alto riesgo tipo EMBARK")
                elif psadt > 9:
                    failed.append(f"PSADT: {psadt} meses > 9 (no corresponde al riesgo alto tipo EMBARK)")
            if study_name == "EMPIRE-1" and salvage_local_feasible is False:
                failed.append("La factibilidad local ya no parece dominante; EMPIRE-1 es más útil cuando la planificación de salvage sigue abierta")

        # -- Calcular score de elegibilidad --
        total_criteria = len(met) + len(failed)
        match_score = len(met) / total_criteria if total_criteria > 0 else 0.0
        is_eligible = len(failed) == 0

        results.append({
            "study": study,
            "match_score": round(match_score, 3),
            "criteria_met": met,
            "criteria_failed": failed,
            "eligible": is_eligible,
        })

    # Ordenar por score descendente, elegibles primero
    results.sort(key=lambda x: (x["eligible"], x["match_score"]), reverse=True)

    eligible_count = sum(1 for r in results if r["eligible"])
    logger.info(
        "Confrontacion completada: %d/%d estudios elegibles para el paciente.",
        eligible_count, len(PIVOTAL_STUDIES),
    )

    return results


# ===========================================================================
# GENERADOR DE REPORTE NARRATIVO
# ===========================================================================

def generate_pivotal_report(patient_data: dict[str, Any]) -> str:
    """
    Genera un reporte narrativo de los estudios pivotales aplicables al paciente.

    El reporte incluye:
    - Resumen del perfil clinico del paciente.
    - Estudios para los cuales el paciente es completamente elegible.
    - Estudios parcialmente aplicables (con criterios faltantes).
    - Consideraciones de validez externa para la poblacion mexicana.

    Parameters
    ----------
    patient_data : dict
        Diccionario con los datos clinicos del paciente
        (mismas claves que match_patient_to_studies).

    Returns
    -------
    str
        Reporte narrativo en formato texto.
    """
    logger.info("Generando reporte de estudios pivotales.")

    matches = match_patient_to_studies(patient_data)
    eligible = [m for m in matches if m["eligible"]]
    partial = [m for m in matches if not m["eligible"] and m["match_score"] >= 0.7]

    report_lines: list[str] = []

    # -- Encabezado --
    report_lines.append("=" * 80)
    report_lines.append("REPORTE DE CONFRONTACION CON ESTUDIOS PIVOTALES")
    report_lines.append("ProstaMed — Motor de Evidencia Clinica")
    report_lines.append(f"Fecha de generacion: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    report_lines.append("=" * 80)
    report_lines.append("")

    # -- Perfil del paciente --
    report_lines.append("--- PERFIL CLINICO DEL PACIENTE ---")
    report_lines.append("")

    age = patient_data.get("age", "N/A")
    psa = patient_data.get("psa", "N/A")
    gleason = patient_data.get("gleason_score")
    if gleason is None:
        gp = patient_data.get("gleason_primary", "?")
        gs = patient_data.get("gleason_secondary", "?")
        gleason = f"{int(gp)+int(gs)} ({gp}+{gs})" if gp != "?" and gs != "?" else "N/A"
    stage = patient_data.get("clinical_tstage", "N/A")
    ecog = patient_data.get("ecog_score", patient_data.get("ecog_performance_status", "N/A"))
    meta = patient_data.get("metastasis_status", "N/A")
    hrr = patient_data.get("hrr_status", "Desconocido")
    msi = patient_data.get("msi_status", "No evaluado")

    report_lines.append(f"  Edad:              {age} anios")
    report_lines.append(f"  PSA:               {psa} ng/mL")
    report_lines.append(f"  Gleason:           {gleason}")
    report_lines.append(f"  Estadio clinico:   {stage}")
    report_lines.append(f"  ECOG:              {ecog}")
    report_lines.append(f"  Estado metastasico: {meta}")
    report_lines.append(f"  HRR:               {hrr}")
    report_lines.append(f"  MSI:               {msi}")
    report_lines.append("")

    # -- Estudios Elegibles --
    report_lines.append("=" * 80)
    report_lines.append(f"ESTUDIOS PIVOTALES APLICABLES ({len(eligible)} estudios)")
    report_lines.append("=" * 80)
    report_lines.append("")

    if not eligible:
        report_lines.append(
            "  No se identificaron estudios para los cuales el paciente cumpla "
            "la totalidad de los criterios de elegibilidad registrados."
        )
        report_lines.append(
            "  Nota: Esto puede deberse a datos clinicos incompletos. Se recomienda "
            "complementar la informacion del paciente."
        )
        report_lines.append("")
    else:
        for i, match in enumerate(eligible, 1):
            study = match["study"]
            report_lines.append(f"  {i}. {study['name']} (Fase {study['phase']}, {study['year']})")
            report_lines.append(f"     Escenario:        {study['scenario']}")
            report_lines.append(f"     Intervencion:     {study['intervention']}")
            report_lines.append(f"     Control:          {study['control']}")
            report_lines.append(f"     Endpoint 1rio:    {study['primary_endpoint']}")
            report_lines.append(f"     Resultado clave:  {study['key_result']}")
            report_lines.append(f"     Evidencia NCCN:   Categoria {study['nccn_category']}")
            report_lines.append(f"     Score elegibil.:  {match['match_score']*100:.0f}%")
            report_lines.append(f"     Criterios cumplidos:")
            for c in match["criteria_met"]:
                report_lines.append(f"       [OK] {c}")
            report_lines.append("")
            report_lines.append(f"     ** Aplicabilidad en Mexico:")
            # Envolver texto largo en lineas
            applicability = study.get("mexican_applicability", "No evaluada.")
            _wrap_text(report_lines, applicability, indent="        ")
            report_lines.append("")
            report_lines.append("     " + "-" * 60)
            report_lines.append("")

    # -- Estudios Parcialmente Aplicables --
    if partial:
        report_lines.append("=" * 80)
        report_lines.append(f"ESTUDIOS PARCIALMENTE APLICABLES ({len(partial)} estudios, >=70% criterios)")
        report_lines.append("=" * 80)
        report_lines.append("")

        for i, match in enumerate(partial, 1):
            study = match["study"]
            report_lines.append(f"  {i}. {study['name']} (Fase {study['phase']}, {study['year']})")
            report_lines.append(f"     Escenario:       {study['scenario']}")
            report_lines.append(f"     Intervencion:    {study['intervention']}")
            report_lines.append(f"     Score elegibil.: {match['match_score']*100:.0f}%")
            report_lines.append(f"     Criterios NO cumplidos:")
            for c in match["criteria_failed"]:
                report_lines.append(f"       [X]  {c}")
            report_lines.append("")

    # -- Resumen de evidencia por escenario --
    report_lines.append("=" * 80)
    report_lines.append("RESUMEN POR ESCENARIO CLINICO")
    report_lines.append("=" * 80)
    report_lines.append("")

    eligible_scenarios: dict[str, list[str]] = {}
    for match in eligible:
        sc = match["study"]["scenario"]
        if sc not in eligible_scenarios:
            eligible_scenarios[sc] = []
        eligible_scenarios[sc].append(match["study"]["name"])

    if eligible_scenarios:
        for scenario, studies_in_scenario in eligible_scenarios.items():
            report_lines.append(
                f"  {scenario.upper()}: {', '.join(studies_in_scenario)}"
            )
    else:
        report_lines.append("  Sin estudios elegibles por escenario.")
    report_lines.append("")

    # -- Nota final --
    report_lines.append("=" * 80)
    report_lines.append("NOTA IMPORTANTE")
    report_lines.append("=" * 80)
    report_lines.append("")
    report_lines.append(
        "  Este reporte es una herramienta de apoyo a la decision clinica y NO sustituye"
    )
    report_lines.append(
        "  el juicio del medico tratante. Los criterios de elegibilidad de los estudios"
    )
    report_lines.append(
        "  pivotales son una aproximacion; la elegibilidad real depende de factores"
    )
    report_lines.append(
        "  adicionales no capturados en esta plataforma (funcion renal, hepatica,"
    )
    report_lines.append(
        "  consentimiento informado, disponibilidad local del tratamiento, etc.)."
    )
    report_lines.append("")
    report_lines.append(
        "  Para la poblacion mexicana, se deben considerar factores de validez externa"
    )
    report_lines.append(
        "  como las diferencias en prevalencia de comorbilidades (diabetes, obesidad,"
    )
    report_lines.append(
        "  hipertension), acceso a estudios moleculares, y disponibilidad de farmacos"
    )
    report_lines.append(
        "  en el cuadro basico del sector salud."
    )
    report_lines.append("")
    report_lines.append("=" * 80)
    report_lines.append(f"Generado por ProstaMed v6.0 — {len(PIVOTAL_STUDIES)} estudios evaluados")
    report_lines.append("=" * 80)

    return "\n".join(report_lines)


def _wrap_text(lines: list[str], text: str, indent: str = "    ", width: int = 72) -> None:
    """Agrega texto con ajuste de linea a una lista de lineas del reporte."""
    words = text.split()
    current_line = indent
    for word in words:
        if len(current_line) + len(word) + 1 > width + len(indent):
            lines.append(current_line)
            current_line = indent + word
        else:
            if current_line == indent:
                current_line += word
            else:
                current_line += " " + word
    if current_line.strip():
        lines.append(current_line)


# ===========================================================================
# UTILIDADES ADICIONALES
# ===========================================================================

def get_available_scenarios() -> list[str]:
    """Retorna la lista de escenarios clinicos disponibles."""
    return list(VALID_SCENARIOS)


def get_studies_summary() -> list[dict[str, str]]:
    """
    Retorna un resumen compacto de todos los estudios pivotales.

    Returns
    -------
    list[dict]
        Lista con nombre, escenario, intervencion y anio de cada estudio.
    """
    return [
        {
            "name": s["name"],
            "scenario": s["scenario"],
            "intervention": s["intervention"],
            "year": s["year"],
            "nccn_category": s["nccn_category"],
        }
        for s in PIVOTAL_STUDIES
    ]


def count_studies_by_scenario() -> dict[str, int]:
    """Retorna un conteo de estudios por escenario clinico."""
    counts: dict[str, int] = {}
    for s in PIVOTAL_STUDIES:
        sc = s["scenario"]
        counts[sc] = counts.get(sc, 0) + 1
    return counts


# ===========================================================================
# EJECUCION DIRECTA (para pruebas rapidas)
# ===========================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")

    # Paciente de ejemplo: mHSPC alto volumen, de novo
    paciente_ejemplo: dict[str, Any] = {
        "age": 68,
        "psa": 85.0,
        "gleason_score": 9,
        "gleason_primary": 4,
        "gleason_secondary": 5,
        "clinical_tstage": "T3B",
        "ecog_score": 1,
        "metastasis_status": "M1",
        "metastasis_site": "Hueso",
        "metastasis_count": 6,
        "volume_chaarted": "High",
        "de_novo": True,
        "castration_resistant": False,
        "hrr_status": "Desconocido",
        "msi_status": "Estable",
        "psma_pet_result": "No realizado",
        "prior_therapy": [],
        "prior_prostatectomy": False,
        "bone_metastases": True,
        "visceral_metastases": False,
        "symptomatic_bone": False,
        "fit_for_chemotherapy": True,
    }

    print("\n" + "=" * 80)
    print("PRUEBA RAPIDA: Paciente mHSPC alto volumen de novo")
    print("=" * 80 + "\n")

    resultados = match_patient_to_studies(paciente_ejemplo)
    elegibles = [r for r in resultados if r["eligible"]]
    print(f"Estudios elegibles: {len(elegibles)}/{len(resultados)}")
    for r in elegibles:
        print(f"  - {r['study']['name']} (score: {r['match_score']:.0%}, "
              f"escenario: {r['study']['scenario']})")

    print("\n")
    reporte = generate_pivotal_report(paciente_ejemplo)
    print(reporte)
