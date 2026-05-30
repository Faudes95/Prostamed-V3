# -*- coding: utf-8 -*-
"""
Treatment Sequencing Optimizer — "El Estratega Terapéutico".

Determines the optimal sequence of treatments for a patient across
all future lines of therapy, accounting for:

  - Biomarker eligibility (PSMA, HRR, AR-V7, MSI-H, NEPC)
  - Prior treatment history (cross-resistance, sequencing rules)
  - CCI/ECOG fitness constraints
  - DDI profile
  - NCCN v5.2026 / EAU 2026 preferred vs alternative distinctions
  - Published OS data from pivotal trials (sequencing sub-analyses)
  - Formulary context (IMSS/ISSSTE/Privado)

Unlike single-visit treatment selection, the Sequencer plans
3-5 future lines, modeling how biomarkers and fitness evolve
through the disease course.

Sources:
  - NCCN PCa v5.2026 (sequencing section)
  - PEACE-1, ARASENS, ENZAMET, ARCHES (combination data)
  - PROfound, TRITON (HRR sequencing)
  - VISION, TheraP (Lu-177 after taxanes)
  - Cross-resistance data: enzalutamide → abiraterone (poor)
  - AR-V7+ after ARSI (taxane preferred)

Usage::

    sequencer = TreatmentSequencer()
    plan = sequencer.optimize(patient_record)
    print(plan.rationale)        # Spanish narrative
    plan.lines                   # [{line: 1, drug: ..., evidence: ..., expected_os_gain: ...}]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# Cross-resistance rules
# Source: published sequencing analyses
# ══════════════════════════════════════════════════════════════

CROSS_RESISTANCE: dict[str, list[str]] = {
    # After first drug → avoid these (reduced efficacy)
    "enzalutamide": ["abiraterone", "darolutamide", "apalutamide"],
    "abiraterone": ["enzalutamide", "darolutamide", "apalutamide"],
    "apalutamide": ["enzalutamide", "abiraterone", "darolutamide"],
    "darolutamide": ["enzalutamide", "abiraterone", "apalutamide"],
    "docetaxel": ["cabazitaxel"],  # Partial cross-resistance (not absolute)
}

# AR-V7 positive → ARSI significantly reduced; prefer taxanes
ARV7_POSITIVE_AVOID = {"enzalutamide", "abiraterone", "apalutamide", "darolutamide"}

# NEPC transformation → avoid hormone agents, prefer platinum
NEPC_TRANSFORMATION_PREFER = ["carboplatin_etoposide", "cisplatin_docetaxel"]
NEPC_TRANSFORMATION_AVOID = {"enzalutamide", "abiraterone", "apalutamide", "darolutamide", "docetaxel_adt"}


@dataclass
class TreatmentLine:
    """A single line of therapy in the sequence."""
    line_number: int
    state: str
    drug: str
    drug_label: str
    evidence_level: str       # "category_1" | "category_2A" | "category_2B"
    guideline_source: str     # "NCCN" | "EAU" | "both"
    expected_os_months: float | None
    expected_pfs_months: float | None
    eligibility_requirements: list[str]
    contraindications: list[str]
    key_trial: str
    rationale: str
    confidence: float         # 0–1
    is_preferred: bool
    biomarker_driven: bool
    formulary: list[str]      # ["IMSS", "ISSSTE", "privado"]


@dataclass
class SequencePlan:
    """Complete multi-line treatment sequence plan."""
    patient_id: int
    current_state: str
    current_line: int
    lines: list[TreatmentLine]
    biomarker_profile: dict[str, Any]
    fitness_constraints: list[str]
    cross_resistance_flags: list[str]
    rationale: str
    sequence_confidence: float
    preferred_regimen: dict[str, Any] = field(default_factory=dict)
    transition_bundle: dict[str, Any] = field(default_factory=dict)
    comparative_eligibility_matrix: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


# ══════════════════════════════════════════════════════════════
# Treatment definitions by state and line
# Each entry: (drug_id, label, evidence, guideline, OS, PFS,
#              eligibility[], contraindications[], trial, preferred)
# ══════════════════════════════════════════════════════════════

SEQUENCE_LIBRARY: dict[str, list[dict[str, Any]]] = {

    "mcspc_high_volume_sync": [
        {"drug": "adt_darolutamide_docetaxel", "label": "TDA + Darolutamida + Docetaxel",
         "evidence": "category_1", "guideline": "both", "OS": 62.7, "PFS": 28.2,
         "eligibility": ["ECOG ≤1", "Función hepática adecuada"],
         "contra": ["ECOG ≥3", "Neuropatía grado ≥2"],
         "trial": "ARASENS", "preferred": True},
        {"drug": "adt_abiraterone", "label": "TDA + Acetato de Abiraterona",
         "evidence": "category_1", "guideline": "both", "OS": 53.3, "PFS": 33.0,
         "eligibility": ["ECOG ≤2"],
         "contra": ["Falla hepática Child-Pugh B/C"],
         "trial": "LATITUDE", "preferred": True},
        {"drug": "adt_enzalutamide", "label": "TDA + Enzalutamida",
         "evidence": "category_1", "guideline": "both", "OS": None, "PFS": 33.0,
         "eligibility": ["ECOG ≤1"],
         "contra": ["Convulsiones previas", "ECOG ≥3"],
         "trial": "ARCHES", "preferred": True},
        {"drug": "adt_docetaxel", "label": "TDA + Docetaxel",
         "evidence": "category_1", "guideline": "both", "OS": 57.6, "PFS": None,
         "eligibility": ["ECOG ≤1", "Función hepática normal"],
         "contra": ["Neuropatía grado ≥2", "ECOG ≥2"],
         "trial": "CHAARTED", "preferred": False},
    ],

    "mcspc_low_volume_sync_oligo": [
        {"drug": "adt_abiraterone", "label": "TDA + Abiraterona",
         "evidence": "category_1", "guideline": "both", "OS": 83.3, "PFS": 40.0,
         "eligibility": ["ECOG ≤2"],
         "contra": ["Falla hepática"],
         "trial": "LATITUDE (bajo volumen)", "preferred": True},
        {"drug": "adt_enzalutamide", "label": "TDA + Enzalutamida",
         "evidence": "category_1", "guideline": "both", "OS": None, "PFS": None,
         "eligibility": ["ECOG ≤1"],
         "contra": ["Convulsiones previas"],
         "trial": "ARCHES", "preferred": True},
        {"drug": "adt_rt", "label": "TDA + Radioterapia a próstata primaria",
         "evidence": "category_1", "guideline": "both", "OS": None, "PFS": None,
         "eligibility": ["ECOG ≤1", "Bajo volumen metastásico", "<4 metástasis óseas"],
         "contra": ["Alto volumen", "Metástasis viscerales"],
         "trial": "STAMPEDE RT", "preferred": True},
    ],

    "m0_crpc": [
        {"drug": "apalutamide", "label": "Apalutamida",
         "evidence": "category_1", "guideline": "both", "OS": 73.9, "PFS": 40.5,
         "eligibility": ["PSADT ≤10 meses"],
         "contra": ["Convulsiones", "ECOG ≥3"],
         "trial": "SPARTAN", "preferred": True},
        {"drug": "enzalutamide", "label": "Enzalutamida",
         "evidence": "category_1", "guideline": "both", "OS": 67.0, "PFS": 36.6,
         "eligibility": ["PSADT ≤10 meses", "ECOG ≤1"],
         "contra": ["Convulsiones previas", "ECOG ≥3"],
         "trial": "PROSPER", "preferred": True},
        {"drug": "darolutamide", "label": "Darolutamida",
         "evidence": "category_1", "guideline": "both", "OS": 71.0, "PFS": 40.4,
         "eligibility": ["PSADT ≤10 meses"],
         "contra": [],
         "trial": "ARAMIS", "preferred": True},
    ],

    "m1_crpc_line_1": [
        {"drug": "abiraterone", "label": "Acetato de Abiraterona",
         "evidence": "category_1", "guideline": "both", "OS": 34.7, "PFS": 16.5,
         "eligibility": ["ECOG ≤2"],
         "contra": ["Falla hepática Child-Pugh B/C"],
         "trial": "COU-AA-302", "preferred": True},
        {"drug": "enzalutamide", "label": "Enzalutamida",
         "evidence": "category_1", "guideline": "both", "OS": 35.3, "PFS": 20.0,
         "eligibility": ["ECOG ≤1", "Sin convulsiones"],
         "contra": ["Convulsiones previas", "ECOG ≥3"],
         "trial": "PREVAIL", "preferred": True},
        {"drug": "docetaxel", "label": "Docetaxel",
         "evidence": "category_1", "guideline": "both", "OS": 18.9, "PFS": None,
         "eligibility": ["ECOG ≤2", "Función hepática normal"],
         "contra": ["Neuropatía grado ≥2", "ECOG ≥3"],
         "trial": "TAX327", "preferred": True},
    ],

    "m1_crpc_line_2_post_arsi": [
        {"drug": "docetaxel", "label": "Docetaxel (post-ARSI)",
         "evidence": "category_1", "guideline": "both", "OS": 16.5, "PFS": None,
         "eligibility": ["ECOG ≤2", "Sin neuropatía grado ≥2"],
         "contra": ["Neuropatía grado ≥2", "ECOG ≥3"],
         "trial": "TAX327 / TROPIC contextual", "preferred": True},
        {"drug": "cabazitaxel", "label": "Cabazitaxel",
         "evidence": "category_1", "guideline": "both", "OS": 15.1, "PFS": None,
         "eligibility": ["ECOG ≤2", "Post-docetaxel"],
         "contra": ["Neuropatía grado ≥2", "ECOG ≥3"],
         "trial": "TROPIC", "preferred": True},
        {"drug": "olaparib", "label": "Olaparib (HRR+)",
         "evidence": "category_1", "guideline": "both", "OS": 19.1, "PFS": 7.4,
         "eligibility": ["HRR+", "BRCA1/2 o ATM mutado"],
         "contra": ["Sin HRR", "MDS activo"],
         "trial": "PROfound", "preferred": True, "biomarker": "hrr_positive"},
        {"drug": "lu177_psma", "label": "Lu-177-PSMA-617",
         "evidence": "category_1", "guideline": "both", "OS": 15.3, "PFS": 8.7,
         "eligibility": ["PSMA+ en PET", "Post-taxane", "Post-ARSI", "ECOG ≤2"],
         "contra": ["PSMA negativo", "ECOG ≥3"],
         "trial": "VISION", "preferred": True, "biomarker": "psma_positive"},
        {"drug": "rucaparib", "label": "Rucaparib (BRCA1/2+)",
         "evidence": "category_1", "guideline": "NCCN", "OS": None, "PFS": 9.0,
         "eligibility": ["BRCA1/2 mutado", "Post-ARSI", "Post-taxane"],
         "contra": ["Sin BRCA mutation"],
         "trial": "TRITON2", "preferred": False, "biomarker": "brca_positive"},
        {"drug": "radium223", "label": "Radio-223 (metástasis óseas)",
         "evidence": "category_1", "guideline": "both", "OS": None, "PFS": None,
         "eligibility": ["≥2 metástasis óseas", "Sin metástasis viscerales", "Sin quimio reciente"],
         "contra": ["Metástasis viscerales", "Trombocitopenia"],
         "trial": "ALSYMPCA", "preferred": True},
    ],

    "recurrence_bcr": [
        {"drug": "enzalutamide_adt", "label": "Enzalutamida + TDA intermitente",
         "evidence": "category_1", "guideline": "NCCN", "OS": None, "PFS": 36.6,
         "eligibility": ["PSADT ≤9 meses", "ECOG ≤1"],
         "contra": ["Convulsiones previas"],
         "trial": "EMBARK (HR=0.58 MFS)", "preferred": True},
        {"drug": "salvage_rt", "label": "Radioterapia de rescate (post-PR)",
         "evidence": "category_1", "guideline": "both", "OS": None, "PFS": None,
         "eligibility": ["PSA detectable post-PR", "Sin metástasis", "PSADT ≥6 meses"],
         "contra": ["PSA >1.0 sin imagen", "Metástasis conocidas"],
         "trial": "RAVES, RADICALS", "preferred": True},
        {"drug": "adt_monotherapy", "label": "TDA monoterapia",
         "evidence": "category_2A", "guideline": "both", "OS": None, "PFS": None,
         "eligibility": ["BCR confirmada", "Sin contraindicaciones"],
         "contra": ["ECOG ≥3"],
         "trial": "Múltiples RCTs", "preferred": False},
    ],

    "m1_crpc_nepc_transformation": [
        {"drug": "carboplatin_etoposide_nepc", "label": "Carboplatino + Etopósido (NEPC)",
         "evidence": "category_2A", "guideline": "both", "OS": 16.0, "PFS": 5.3,
         "eligibility": ["NEPC confirmado histológicamente o sospechado score ≥5",
                         "CBC apta para mielotoxicidad"],
         "contra": ["Reserva medular inadecuada"],
         "trial": "Aparicio CCR 2013 / Aggarwal JCO 2018", "preferred": True,
         "biomarker": "nepc"},
        {"drug": "cisplatin_docetaxel_nepc", "label": "Cisplatino + Docetaxel (NEPC)",
         "evidence": "category_2A", "guideline": "both", "OS": 15.2, "PFS": 5.0,
         "eligibility": ["NEPC confirmado", "eGFR ≥60", "Sin hipoacusia",
                         "Neuropatía <grado 2", "ECOG ≤2"],
         "contra": ["eGFR <60", "Hipoacusia documentada", "Neuropatía ≥grado 2"],
         "trial": "Aparicio CCR 2013", "preferred": False,
         "biomarker": "nepc"},
        {"drug": "nepc_clinical_trial", "label": "Ensayo clínico NEPC dirigido (AURKA/MYCN/DLL3)",
         "evidence": "category_2B", "guideline": "NCCN", "OS": None, "PFS": None,
         "eligibility": ["NEPC confirmado", "Ensayo activo"],
         "contra": [],
         "trial": "NCCN PROS-J v5.2026", "preferred": False,
         "biomarker": "nepc"},
    ],
}

# Formulary map (which drugs are available in each system)
FORMULARY: dict[str, list[str]] = {
    "enzalutamide": ["IMSS", "ISSSTE", "privado"],
    "abiraterone": ["IMSS", "ISSSTE", "privado"],
    "apalutamide": ["privado"],
    "darolutamide": ["privado"],
    "docetaxel": ["IMSS", "ISSSTE", "privado"],
    "cabazitaxel": ["ISSSTE", "privado"],
    "lu177_psma": ["privado"],
    "olaparib": ["privado"],
    "rucaparib": ["privado"],
    "radium223": ["privado"],
    "adt_monotherapy": ["IMSS", "ISSSTE", "privado"],
    "adt_abiraterone": ["IMSS", "ISSSTE", "privado"],
    "adt_enzalutamide": ["IMSS", "ISSSTE", "privado"],
    "adt_darolutamide_docetaxel": ["privado"],
    "adt_rt": ["IMSS", "ISSSTE", "privado"],
    "carboplatin_etoposide_nepc": ["IMSS", "ISSSTE", "privado"],
    "cisplatin_docetaxel_nepc": ["IMSS", "ISSSTE", "privado"],
    "nepc_clinical_trial": ["privado"],
}


class TreatmentSequencer:
    """
    Generates an optimal multi-line treatment sequence for a patient.

    Integrates biomarker constraints, fitness, cross-resistance,
    and guideline preferences.
    """

    def optimize(self, patient: dict[str, Any]) -> SequencePlan:
        """Build optimal treatment sequence from current state forward."""
        identity = patient.get("identity", {}) or {}
        baseline = patient.get("baseline", {}) or {}
        follow_ups = patient.get("follow_ups", []) or []
        latest_fu = follow_ups[-1] if follow_ups else {}
        treatments = patient.get("treatments", []) or []
        genomic = patient.get("genomic_profile", {}) or {}
        latest_assessment = patient.get("latest_assessment", {}) or {}
        latest_result = dict(latest_assessment.get("result_snapshot") or {})
        patient_id = int(identity.get("id", 0))

        state = (
            patient.get("reconciled_state")
            or (patient.get("latest_assessment") or {}).get("state")
            or "diagnostic_workup"
        )

        # Build biomarker profile
        biomarkers = self._extract_biomarkers(baseline, genomic, patient)

        # Fitness constraints
        ecog = int(latest_fu.get("ecog_current") or latest_fu.get("ecog") or baseline.get("ecog_score") or 0)
        cci = (patient.get("demographics") or {}).get("cci_score") or 0
        seizure_hx = bool(latest_fu.get("seizure_history") or baseline.get("seizure_history"))
        hepatic_risk = latest_fu.get("hepatic_risk_status") or ""
        fitness = self._build_fitness_constraints(ecog, cci, seizure_hx, hepatic_risk, latest_fu)

        # Prior treatments
        prior_drugs = {t.get("drug_scheme", "") for t in treatments}

        # Cross-resistance flags
        cr_flags = self._check_cross_resistance(prior_drugs)

        # Build sequence
        lines = self._build_sequence(state, biomarkers, fitness, prior_drugs, cr_flags, ecog)

        # Current line number
        current_line = len(treatments)

        rationale = self._build_rationale(state, biomarkers, fitness, lines, cr_flags)

        confidence = self._compute_confidence(biomarkers, lines)

        return SequencePlan(
            patient_id=patient_id,
            current_state=state,
            current_line=current_line,
            lines=lines,
            biomarker_profile=biomarkers,
            fitness_constraints=fitness,
            cross_resistance_flags=cr_flags,
            rationale=rationale,
            sequence_confidence=confidence,
            preferred_regimen=dict(latest_result.get("preferred_frontline_regimen") or {}),
            transition_bundle=dict(latest_result.get("sequence_transition_bundle") or {}),
            comparative_eligibility_matrix=dict(latest_result.get("comparative_eligibility_matrix") or {}),
        )

    def _extract_biomarkers(
        self,
        baseline: dict,
        genomic: dict,
        patient: dict,
    ) -> dict[str, Any]:
        follow_ups = patient.get("follow_ups", []) or []
        latest_fu = follow_ups[-1] if follow_ups else {}
        latest_assessment = patient.get("latest_assessment") or {}
        latest_result = dict(latest_assessment.get("result_snapshot") or {})
        nepc_bundle = dict(latest_result.get("nepc_pathway_bundle") or {})
        vision_bundle = dict(latest_result.get("vision_eligibility_bundle") or {})

        return {
            "hrr_positive": bool(
                baseline.get("hrr_positive")
                or genomic.get("hrr_status") == "positive"
                or genomic.get("hrr_positive")
            ),
            "brca2_positive": bool(genomic.get("brca2_mutation")),
            "brca1_positive": bool(genomic.get("brca1_mutation")),
            "msi_high": genomic.get("msi_status") == "MSI-H"
            or bool((latest_result.get("nccn_primary") or {}).get("dmmr_high_confidence")),
            "arv7_positive": bool(
                genomic.get("arv7_positive")
                or baseline.get("arv7_positive")
                or str(baseline.get("ar_v7_status") or "").lower().startswith("pos")
            ),
            "psma_positive": bool(
                genomic.get("psma_positive")
                or baseline.get("psma_positive")
                or vision_bundle.get("eligible")
            ),
            "nepc": bool(
                genomic.get("nepc_transformation")
                or baseline.get("nepc")
                or nepc_bundle.get("nepc_confirmed")
                or nepc_bundle.get("nepc_suspected")
            ),
            "nepc_confirmed": bool(nepc_bundle.get("nepc_confirmed")),
            "nepc_biopsy_trigger": bool(nepc_bundle.get("biopsy_trigger")),
            "vision_eligibility_label": vision_bundle.get("eligibility_label"),
            "tmb_high": genomic.get("tmb_high", False),
            "psadt_months": self._get_psadt(follow_ups),
        }

    @staticmethod
    def _get_psadt(follow_ups: list) -> float | None:
        from prostanet.domains.patient_tracking.natural_history_tracker import NaturalHistoryTracker
        return NaturalHistoryTracker._compute_psadt(follow_ups)

    @staticmethod
    def _build_fitness_constraints(
        ecog: int,
        cci: int,
        seizure_hx: bool,
        hepatic_risk: str,
        latest_fu: dict,
    ) -> list[str]:
        constraints = []
        if ecog >= 3:
            constraints.append("ECOG ≥3: excluir taxanos y Lu-177")
        elif ecog == 2:
            constraints.append("ECOG 2: cautela con taxanos")
        if seizure_hx:
            constraints.append("Antecedente de convulsiones: evitar enzalutamida/apalutamida")
        if hepatic_risk in ("alto", "severe", "Child-Pugh B", "Child-Pugh C"):
            constraints.append("Riesgo hepático alto: contraindicado abiraterona")
        neuro = latest_fu.get("peripheral_neuropathy_grade")
        if neuro:
            neuro_grade = int(neuro)
            if neuro_grade >= 3:
                constraints.append("Neuropatía periférica ≥3: evitar taxanos")
            elif neuro_grade == 2:
                constraints.append("Neuropatía periférica grado 2: taxanos solo con cautela")
        hgb = latest_fu.get("hemoglobin_current") or latest_fu.get("hemoglobin")
        if hgb and float(hgb) < 9:
            constraints.append("Hemoglobina <9 g/dL: revisar elegibilidad para Lu-177")
        return constraints

    @staticmethod
    def _check_cross_resistance(prior_drugs: set[str]) -> list[str]:
        flags = []
        for prior, avoid_list in CROSS_RESISTANCE.items():
            if prior in prior_drugs:
                for avoided in avoid_list:
                    if avoided not in prior_drugs:
                        flags.append(
                            f"Resistencia cruzada: tras {prior}, {avoided} tiene eficacia reducida"
                        )
        return flags

    def _build_sequence(
        self,
        state: str,
        biomarkers: dict,
        fitness: list[str],
        prior_drugs: set[str],
        cr_flags: list[str],
        ecog: int,
    ) -> list[TreatmentLine]:
        lines: list[TreatmentLine] = []

        library_keys = self._library_keys_for_state(state, prior_drugs, biomarkers)

        line_num = len(prior_drugs) + 1
        for lib_key in library_keys:
            candidates = SEQUENCE_LIBRARY.get(lib_key, [])
            for candidate in candidates:
                drug_id = candidate["drug"]

                # Skip already used
                if drug_id in prior_drugs:
                    continue

                # Check cross-resistance
                cr_reduced = any(drug_id in CROSS_RESISTANCE.get(p, []) for p in prior_drugs)

                # Check biomarker gates
                biomarker_required = candidate.get("biomarker")
                if biomarker_required:
                    if biomarker_required == "hrr_positive" and not biomarkers.get("hrr_positive"):
                        continue
                    if biomarker_required == "psma_positive" and not biomarkers.get("psma_positive"):
                        continue
                    if biomarker_required == "brca_positive" and not (
                        biomarkers.get("brca1_positive") or biomarkers.get("brca2_positive")
                    ):
                        continue
                    if biomarker_required == "nepc" and not biomarkers.get("nepc"):
                        continue

                # Check AR-V7 constraint
                if biomarkers.get("arv7_positive") and drug_id in ARV7_POSITIVE_AVOID:
                    continue

                # Check NEPC
                if biomarkers.get("nepc") and drug_id in NEPC_TRANSFORMATION_AVOID:
                    continue

                # ECOG gate
                if ecog >= 3 and "taxan" in drug_id.lower():
                    continue
                if ecog >= 3 and drug_id in ("lu177_psma", "radium223", "cabazitaxel"):
                    continue

                # Fitness contraindications
                contra = candidate.get("contra", [])
                fitness_blocked = False
                for constraint in fitness:
                    for c in contra:
                        if any(word in constraint.lower() for word in c.lower().split()):
                            fitness_blocked = True
                if fitness_blocked:
                    continue

                confidence = 0.90 if candidate.get("preferred") else 0.70
                if cr_reduced:
                    confidence *= 0.6

                lines.append(TreatmentLine(
                    line_number=line_num,
                    state=state,
                    drug=drug_id,
                    drug_label=candidate["label"],
                    evidence_level=candidate.get("evidence", "category_2A"),
                    guideline_source=candidate.get("guideline", "NCCN"),
                    expected_os_months=candidate.get("OS"),
                    expected_pfs_months=candidate.get("PFS"),
                    eligibility_requirements=candidate.get("eligibility", []),
                    contraindications=candidate.get("contra", []),
                    key_trial=candidate.get("trial", ""),
                    rationale=self._line_rationale(candidate, biomarkers, cr_reduced),
                    confidence=round(confidence, 2),
                    is_preferred=candidate.get("preferred", False) and not cr_reduced,
                    biomarker_driven=bool(biomarker_required),
                    formulary=FORMULARY.get(drug_id, ["privado"]),
                ))
                line_num += 1

        # Sort: preferred first, then by OS benefit
        lines.sort(key=lambda l: (-int(l.is_preferred), -(l.expected_os_months or 0)))
        return lines

    @staticmethod
    def _library_keys_for_state(
        state: str,
        prior_drugs: set[str],
        biomarkers: dict | None = None,
    ) -> list[str]:
        """Determine which sequence library sections apply."""
        biomarkers = biomarkers or {}
        keys = []
        if state in ("mcspc_high_volume_sync", "mcspc_high_volume_metachronous", "mcspc_high_volume"):
            keys.append("mcspc_high_volume_sync")
        elif state in ("mcspc_low_volume_sync_oligo", "mcspc_oligo_metachronous"):
            keys.append("mcspc_low_volume_sync_oligo")
        elif state == "m0_crpc":
            keys.append("m0_crpc")
        elif state == "m1_crpc":
            if biomarkers.get("nepc"):
                keys.append("m1_crpc_nepc_transformation")
                keys.append("m1_crpc_line_2_post_arsi")
                return keys
            # Has prior ARSI? → line 2 library
            arsis = {"enzalutamide", "abiraterone", "apalutamide", "darolutamide"}
            if arsis & prior_drugs:
                keys.append("m1_crpc_line_2_post_arsi")
            else:
                keys.append("m1_crpc_line_1")
                keys.append("m1_crpc_line_2_post_arsi")  # show future options
        elif state in ("recurrence_bcr", "adt_progression_verification"):
            keys.append("recurrence_bcr")
        return keys

    @staticmethod
    def _line_rationale(
        candidate: dict,
        biomarkers: dict,
        cr_reduced: bool,
    ) -> str:
        parts = []
        if candidate.get("preferred"):
            parts.append(f"Opción preferida según {candidate.get('guideline', 'guías')} (Categoría {candidate.get('evidence', '1')})")
        if candidate.get("OS"):
            parts.append(f"OS mediana: {candidate['OS']} meses (ensayo {candidate.get('trial', '?')})")
        if candidate.get("biomarker"):
            parts.append(f"Dirigido por biomarcador: {candidate['biomarker']}")
        if cr_reduced:
            parts.append("⚠ Resistencia cruzada posible con tratamiento previo")
        return ". ".join(parts) + "."

    def _build_rationale(
        self,
        state: str,
        biomarkers: dict,
        fitness: list[str],
        lines: list[TreatmentLine],
        cr_flags: list[str],
    ) -> str:
        parts = []
        state_label = {
            "m1_crpc": "CPRC metastásico",
            "m0_crpc": "CPRC no metastásico",
            "mcspc_high_volume_sync": "CPHSm alto volumen",
            "recurrence_bcr": "Recurrencia bioquímica",
        }.get(state, state)

        parts.append(f"Secuencia terapéutica optimizada para {state_label}.")

        # Biomarker highlights
        if biomarkers.get("hrr_positive"):
            parts.append("HRR positivo: se priorizan PARP inhibidores (PROfound).")
        if biomarkers.get("psma_positive"):
            parts.append("PSMA positivo: Lu-177-PSMA-617 elegible tras ARSI + taxano (VISION).")
        if biomarkers.get("arv7_positive"):
            parts.append("AR-V7 positivo: se eliminan ARSI de la secuencia (baja eficacia). Se prioriza taxano.")
        if biomarkers.get("nepc"):
            parts.append("Transformación a CPNP (NEPC): se indican regímenes basados en platino.")

        # Cross-resistance
        if cr_flags:
            parts.append("Resistencia cruzada entre ARSI detectada. " + cr_flags[0])

        # Fitness
        if fitness:
            parts.append("Restricciones por fitness: " + "; ".join(fitness[:2]))

        # Top 3 lines
        preferred = [l for l in lines if l.is_preferred][:3]
        if preferred:
            sequence_str = " → ".join(l.drug_label for l in preferred)
            parts.append(f"Secuencia recomendada: {sequence_str}.")

        return "\n".join(parts)

    @staticmethod
    def _compute_confidence(biomarkers: dict, lines: list[TreatmentLine]) -> float:
        if not lines:
            return 0.3
        base = sum(l.confidence for l in lines[:3]) / min(3, len(lines))
        # Biomarker data boosts confidence
        if biomarkers.get("hrr_positive") or biomarkers.get("psma_positive"):
            base = min(1.0, base + 0.1)
        return round(base, 2)
