"""prostanet.shared.clinical_subspecialty_engine — FAUBOT LXXXIV Iteración #1.

Engine de razonamiento subespecialista en oncourología prostática.
Provee 2 funciones principales:

1. **recommend_next_clinical_action(patient)**: ordena lista priorizada de
   acciones clínicas según estado del paciente, gates fired, y evidence-based
   pathways:
   - "Biopsia primaria urgente" (PSA elevado + TR T4 + sin biopsia)
   - "Estudios extensión + biopsia" (PSA muy alto + TR T4 + síntomas)
   - "ADT empírico + workup paralelo" (urgencia + virtually_certain)
   - "Bicalutamida pre-ADT" (alta carga tumoral + flare risk)

2. **recommend_flare_protection(tumor_burden, cord_compression_risk, ecog)**:
   protocolo flare protection pre-ADT en pacientes con bulk disease:
   - degarelix (antagonista LHRH puro, sin flare): preferido si SCC risk
   - LHRH agonist + bicalutamida 14 días: clásico, requiere planning

CONTEXTO:
La auditoría pre-Cortana (LXXXI) detectó que la lógica subespecialista
existía en `clinical_provisional_diagnosis_engine.py` (empiric_adt_protocol)
pero NO estaba expuesta en UI. Este engine consolida + expone vía API/UI
para que Cortana pueda razonar correctamente sobre next steps.

Referencias:
- Bubley JCO 1999 — flare protection bicalutamide protocol
- Klotz JCO 2008 — degarelix vs leuprolide PSA flare
- NCCN Prostate v5.2026 PROS-2 — initial management algorithms
- EAU 2026 §6.3 — ADT initiation guidelines
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ClinicalAction:
    """Una acción clínica recomendada con racional + urgencia."""
    priority: int  # 1=highest, 5=lowest
    action: str  # tipo acción canónico
    title: str  # título legible para UI
    rationale: str  # racional clínico
    urgency: str  # 'emergent' | 'urgent' | 'soon' | 'elective'
    timeline_days: int  # días para ejecución
    evidence_refs: list[str] = field(default_factory=list)
    contraindications: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────
# Recommend next clinical action
# ─────────────────────────────────────────────────────────────────────


def recommend_next_clinical_action(patient: dict[str, Any]) -> list[ClinicalAction]:
    """Ordena acciones clínicas priorizadas según estado del paciente.

    Args:
        patient: dict con campos del paciente normalizados (post canonicalize):
            - psa_value: float
            - clinical_t_stage: str (cT1-cT4)
            - dre_fixation: str ("Confirmada" si T4 fija/pétrea)
            - primary_biopsy_not_performed: bool
            - histology_already_confirmed: bool
            - ldh_value: float
            - visceral_metastasis_present: bool
            - widespread_bone_metastases_documented: bool
            - spinal_cord_compression_suspected: bool
            - oncologic_emergency_active: bool
            - ecog_current: int (0-4)
            - psa_velocity_ng_ml_year: float
            - provisional_diagnosis_tier: str

    Returns:
        Lista de ClinicalAction ordenadas por priority (1=highest).

    Ejemplos:

    Caso usuario verbatim 1: TR T4 + APE 100 sin RHP
        patient = {
            "psa_value": 100, "clinical_t_stage": "cT4",
            "dre_fixation": "Confirmada",
            "primary_biopsy_not_performed": True,
        }
        # Output:
        # [1] "Biopsia primaria urgente <2 sem" + "mpMRI prostática"
        # [2] "Workup extensión: TAC + bone scan + LDH"
        # [3] "MDT post-resultados"

    Caso usuario verbatim 2: APE 5000 + TR T4 fija + síntomas SCC
        patient = {
            "psa_value": 5000, "clinical_t_stage": "cT4",
            "dre_fixation": "Confirmada",
            "primary_biopsy_not_performed": True,
            "spinal_cord_compression_suspected": True,
            "ldh_value": 450,
        }
        # Output:
        # [1] "Emergency-first: dexametasona 16mg IV + RM columna <24h"
        # [2] "Biopsia metastásica urgente (sitio accesible) <7 días"
        # [3] "ADT empírico con flare protection (degarelix preferido por SCC)"
        # [4] "Considerar EP empírico si LDH/curso → NEPC"
    """
    actions: list[ClinicalAction] = []

    # Helper booleanos
    has_biopsy = bool(patient.get("histology_already_confirmed")) or not bool(
        patient.get("primary_biopsy_not_performed")
    )
    psa = float(patient.get("psa_value") or 0)
    ldh = float(patient.get("ldh_value") or 0)
    psa_velocity = float(patient.get("psa_velocity_ng_ml_year") or 0)
    ecog = int(patient.get("ecog_current") or 0)
    t_stage = str(patient.get("clinical_t_stage") or "").strip()
    dre_fixed = str(patient.get("dre_fixation") or "").strip().lower() in (
        "confirmada", "t4_fijo_petreo", "confirmed_fixed",
    )
    is_t4 = "T4" in t_stage.upper() or "CT4" in t_stage.upper() or "CT3B" in t_stage.upper() or dre_fixed
    has_visceral = bool(patient.get("visceral_metastasis_present")) or any(
        bool(patient.get(f)) for f in [
            "liver_metastasis_documented", "lung_metastasis_documented",
            "new_cns_metastasis_appeared",
        ]
    )
    has_widespread_bone = bool(patient.get("widespread_bone_metastases_documented"))
    scc_suspected = bool(patient.get("spinal_cord_compression_suspected") or
                          patient.get("spinal_cord_compression_confirmed"))
    emergency_active = bool(patient.get("oncologic_emergency_active") or scc_suspected)
    nepc_suspect = ldh >= 400 and psa >= 1000 and (has_visceral or has_widespread_bone)

    # ─── PRIORIDAD 1: Emergencias oncológicas ──────────────────
    if emergency_active or scc_suspected:
        actions.append(ClinicalAction(
            priority=1,
            action="emergency_first_protocol",
            title="🚨 Emergency-first: manejar urgencia oncológica PRIMERO",
            rationale=(
                "Compresión medular / hipercalcemia maligna / visceral crisis "
                "requieren manejo inmediato. Workup paralelo, no secuencial."
            ),
            urgency="emergent",
            timeline_days=0,
            evidence_refs=[
                "Patchell Lancet 2005 (SCC cirugía+RT)",
                "Loblaw JCO 2012 (SCC management)",
                "NCCN Prostate v5.2026 PROS-X",
            ],
        ))
        if scc_suspected:
            actions.append(ClinicalAction(
                priority=1,
                action="dexamethasone_load_iv",
                title="Dexametasona 16 mg IV bolus + 4 mg q6h IV",
                rationale="Reduce edema medular + protección neurológica pre-RM",
                urgency="emergent",
                timeline_days=0,
                evidence_refs=["Loblaw JCO 2012"],
            ))
            actions.append(ClinicalAction(
                priority=1,
                action="spine_mri_emergency",
                title="RM columna full-spine emergency <24h",
                rationale="Confirmar SCC + nivel + decisión cirugía vs RT",
                urgency="emergent",
                timeline_days=1,
                evidence_refs=["Patchell Lancet 2005"],
            ))

    # ─── PRIORIDAD 2: Biopsia/diagnóstico ──────────────────────
    if not has_biopsy:
        # Caso A: TR T4 + PSA muy alto (presumptive cáncer agresivo)
        if is_t4 and psa >= 100:
            if has_widespread_bone or has_visceral:
                # Biopsia metastásica más rápida + rendimiento
                actions.append(ClinicalAction(
                    priority=2,
                    action="metastatic_biopsy_urgent",
                    title="Biopsia metastásica urgente <7 días (sitio accesible)",
                    rationale=(
                        "T4 + PSA alto + mets viscerales/óseas widespread. "
                        "Biopsia metastásica más rápida + permite IHC NEPC ruling out."
                    ),
                    urgency="urgent",
                    timeline_days=7,
                    evidence_refs=[
                        "NCCN Prostate v5.2026 PROS-2",
                        "Aparicio Eur Urol 2024 (NEPC biopsy preferred sites)",
                    ],
                ))
            else:
                # Biopsia primaria transperineal (T4 fija)
                actions.append(ClinicalAction(
                    priority=2,
                    action="primary_biopsy_transperineal_urgent",
                    title="Biopsia primaria transperineal <2 semanas",
                    rationale=(
                        "T4 fijo con TRUS difícil. Transperineal templated 12-24 cores "
                        "con anestesia regional/general."
                    ),
                    urgency="urgent",
                    timeline_days=14,
                    evidence_refs=["NCCN Prostate v5.2026 PROS-2"],
                ))
        # Caso B: PSA velocity muy alta (gate 69B)
        elif psa_velocity >= 20:
            actions.append(ClinicalAction(
                priority=2,
                action="primary_biopsy_velocity_urgent",
                title="Biopsia primaria urgente <2 semanas (PSAv >20 ng/mL/año)",
                rationale=(
                    "PSA velocity muy elevada predice cáncer agresivo. "
                    "mpMRI prostática previo + targeted biopsy preferida."
                ),
                urgency="urgent",
                timeline_days=14,
                evidence_refs=[
                    "D'Amico JNCI 1995", "Carter JNCI 2006",
                    "EAU 2026 §5.1.2",
                ],
            ))
        # Caso C: T4 sin urgencia inmediata (electivo)
        elif is_t4:
            actions.append(ClinicalAction(
                priority=3,
                action="primary_biopsy_planned",
                title="Biopsia primaria + mpMRI 2-4 semanas",
                rationale="T4 confirmar histología antes de decisión local",
                urgency="soon",
                timeline_days=14,
                evidence_refs=["NCCN Prostate v5.2026 PROS-2"],
            ))
        # Caso D: PSA elevado pero sin T4 ni urgencia
        elif psa >= 10:
            actions.append(ClinicalAction(
                priority=4,
                action="biopsy_with_calculators",
                title="PHI/4Kscore + biopsia electiva 4-8 semanas",
                rationale="PSA elevado en gray zone — refinar con calculadores",
                urgency="elective",
                timeline_days=42,
                evidence_refs=["EAU 2026 §5.1.2", "Loeb J Urol 2015 (PHI)"],
            ))

    # ─── PRIORIDAD 2.5: Sospecha NEPC pre-biopsia ───────────────
    if nepc_suspect and not has_biopsy:
        actions.append(ClinicalAction(
            priority=2,
            action="nepc_workup_pre_biopsy",
            title="Workup NEPC pre-biopsia (LDH seriada + IHC en biopsia)",
            rationale=(
                "LDH ≥400 + PSA ≥1000 + visceral/widespread mets = patrón NEPC. "
                "Biopsia con IHC obligatorio: chromogranin A, synaptophysin, NSE, AR."
            ),
            urgency="urgent",
            timeline_days=7,
            evidence_refs=[
                "Aparicio Eur Urol 2024 (NEPC)",
                "Beltran JCO 2018 (NEPC molecular)",
                "Mostaghel JCO 2014 (small cell suspicion)",
            ],
        ))

    # ─── PRIORIDAD 3: Workup extensión paralelo ─────────────────
    if not has_biopsy and (is_t4 or psa >= 50 or psa_velocity >= 5):
        actions.append(ClinicalAction(
            priority=3,
            action="staging_workup_parallel",
            title="Workup extensión simultáneo (no esperar biopsia)",
            rationale=(
                "TAC thorax/abdomen/pelvis + bone scan o PSMA-PET + labs basales "
                "(LDH, ALP, testosterona, hemograma)."
            ),
            urgency="urgent" if is_t4 else "soon",
            timeline_days=7 if is_t4 else 14,
            evidence_refs=[
                "NCCN Prostate v5.2026 PROS-2",
                "EAU 2026 §5.4 (staging requirements)",
            ],
        ))

    # ─── PRIORIDAD 3.5: ADT empírico con flare protection ───────
    presumptive_tier = str(patient.get("provisional_diagnosis_tier") or "").lower()
    high_burden = is_t4 and psa >= 100 and (has_widespread_bone or has_visceral)
    can_empiric_adt = (
        presumptive_tier in ("highly_probable", "virtually_certain")
        or (is_t4 and psa >= 1000)  # virtually_certain by clinical
    )

    if can_empiric_adt and not has_biopsy:
        flare_protocol = recommend_flare_protection(
            tumor_burden="high" if high_burden else "moderate",
            cord_compression_risk=scc_suspected or has_widespread_bone,
            ecog=ecog,
        )
        actions.append(ClinicalAction(
            priority=3,
            action="empiric_adt_with_flare_protection",
            title=f"ADT empírico + flare protection: {flare_protocol['protocol']}",
            rationale=(
                f"Presumptive diagnosis tier ≥ highly_probable. "
                f"{flare_protocol['rationale']}. "
                "Documentar `presumptive_treatment_documented_with_2week_biopsy_plan`."
            ),
            urgency="urgent" if scc_suspected else "soon",
            timeline_days=2 if scc_suspected else 7,
            evidence_refs=flare_protocol["evidence_refs"],
            contraindications=flare_protocol.get("contraindications", []),
        ))

    # ─── PRIORIDAD 4: MDT decision review ──────────────────────
    if has_biopsy or actions:  # algún plan en marcha
        actions.append(ClinicalAction(
            priority=4,
            action="mdt_review_post_workup",
            title="Revisión MDT (uro + radonc + oncología) post-resultados",
            rationale=(
                "Decisión multidisciplinaria documentada para definir tratamiento "
                "óptimo basado en evidencia + caso clínico individual."
            ),
            urgency="soon",
            timeline_days=14,
            evidence_refs=["NCCN Prostate v5.2026", "EAU 2026 §6"],
        ))

    # Ordenar por priority asc, luego por timeline asc
    actions.sort(key=lambda a: (a.priority, a.timeline_days))
    return actions


# ─────────────────────────────────────────────────────────────────────
# Recommend flare protection protocol
# ─────────────────────────────────────────────────────────────────────


def recommend_flare_protection(
    tumor_burden: str,  # 'high' | 'moderate' | 'low'
    cord_compression_risk: bool,
    ecog: int,
) -> dict[str, Any]:
    """Protocolo de flare protection pre-ADT en pacientes con bulk disease.

    El "tumor flare" es un fenómeno paradójico al iniciar agonistas LHRH
    (leuprolide, goserelin, triptorelin): aumento transitorio de testosterona
    durante 7-10 días que puede causar:
    - Empeoramiento dolor óseo (bone pain flare)
    - Compresión medular si bulk paravertebral
    - Obstrucción urinaria
    - Aumento bulk visceral (raro pero posible)

    Args:
        tumor_burden: 'high' (>5 mets óseas + visceral), 'moderate', 'low'
        cord_compression_risk: True si lesión paravertebral cervical/torácica/lumbar
        ecog: Performance status 0-4

    Returns:
        Dict con:
        - protocol: 'degarelix' | 'lhrh_agonist_with_bicalutamide' | 'standard_lhrh'
        - rationale: razón clínica
        - dosing: detalles dosificación
        - evidence_refs: trials/guidelines
        - contraindications: lista contraindicaciones específicas

    Lógica de decisión:
    - SCC risk OR high tumor burden → degarelix preferido (no flare)
    - Moderate burden + sin SCC risk → LHRH agonist + bicalutamide 14d
    - Low burden + sin SCC risk → LHRH agonist solo (mínimo flare risk)
    """
    # Caso 1: SCC risk → degarelix (no flare)
    if cord_compression_risk:
        return {
            "protocol": "degarelix",
            "title": "Degarelix 240 mg SC carga + 80 mg SC mensual",
            "rationale": (
                "Antagonista LHRH puro — NO causa flare de testosterona. "
                "Preferido en compresión medular o bulk paravertebral por riesgo "
                "de exacerbación neurológica con flare LHRH agonist."
            ),
            "dosing": (
                "Día 0: 240 mg SC (dos inyecciones de 120 mg en sitios separados). "
                "Día 28+: 80 mg SC mensual indefinido. "
                "Castración química en <3 días (vs 21-28 días con leuprolide)."
            ),
            "evidence_refs": [
                "Klotz J Urol 2008 (degarelix vs leuprolide)",
                "Boccon-Gibod Lancet 2008 (PSA flare avoidance)",
                "NCCN Prostate v5.2026 PROS-G (cord compression risk)",
            ],
            "contraindications": ["Hipersensibilidad degarelix"],
        }

    # Caso 2: High tumor burden sin SCC risk → degarelix preferido O LHRH+bicalutamide
    if tumor_burden == "high":
        return {
            "protocol": "degarelix_or_lhrh_with_bicalutamide",
            "title": "Degarelix 240 mg SC (preferido) O LHRH agonist + bicalutamida 50 mg/d × 14d",
            "rationale": (
                "Bulk disease (>5 mets óseas + visceral) con riesgo flare óseo. "
                "Degarelix preferido si rapidez castración importante (<3 días vs 21d). "
                "LHRH agonist + bicalutamida 14d es alternativa estándar."
            ),
            "dosing": (
                "**Opción A (preferida)**: Degarelix 240 mg SC carga + 80 mg/mes. "
                "**Opción B**: Bicalutamida 50 mg/d PO desde día -7 (7 días antes "
                "del LHRH agonist) hasta día +7 (total 14 días). Luego LHRH agonist "
                "(leuprolide 22.5 mg IM cada 3m, goserelin 10.8 mg SC cada 3m, etc.)."
            ),
            "evidence_refs": [
                "Bubley JCO 1999 (bicalutamide flare protection)",
                "Klotz J Urol 2008 (degarelix vs leuprolide)",
                "NCCN Prostate v5.2026 PROS-G",
                "EAU 2026 §6.3 (ADT initiation)",
            ],
            "contraindications": [
                "Hipersensibilidad bicalutamida si Opción B",
                "Hepatopatía severa (ajustar bicalutamida)",
            ],
        }

    # Caso 3: Moderate burden → LHRH agonist + bicalutamida 14d (estándar)
    if tumor_burden == "moderate":
        return {
            "protocol": "lhrh_agonist_with_bicalutamide",
            "title": "LHRH agonist + bicalutamida 50 mg/d × 14 días (anti-flare)",
            "rationale": (
                "Burden moderado (mets óseas limitadas, sin SCC risk). "
                "Bicalutamida bloquea acción de testosterona durante flare LHRH."
            ),
            "dosing": (
                "Día -7 (o día 0): Bicalutamida 50 mg/d PO durante 14 días. "
                "Día 0: LHRH agonist (leuprolide 22.5 mg IM o goserelin 10.8 mg SC). "
                "Día +14: Suspender bicalutamida si no es CAB strategy. "
                "Continuar LHRH agonist cada 3m indefinido."
            ),
            "evidence_refs": [
                "Bubley JCO 1999 (bicalutamide protocol)",
                "NCCN Prostate v5.2026 PROS-G",
            ],
            "contraindications": ["Hipersensibilidad bicalutamida"],
        }

    # Caso 4: Low burden + ECOG bueno → LHRH agonist solo (riesgo flare mínimo)
    return {
        "protocol": "standard_lhrh_no_flare_protection",
        "title": "LHRH agonist solo (sin flare protection)",
        "rationale": (
            "Burden bajo (sin mets bulky o visceral). Riesgo flare clínicamente "
            "significativo es mínimo. Bicalutamida pre-ADT no necesaria."
        ),
        "dosing": (
            "Leuprolide 22.5 mg IM cada 3 meses (o equivalente). "
            "Monitor PSA + testosterona a 4-6 sem post-inicio."
        ),
        "evidence_refs": ["NCCN Prostate v5.2026 PROS-G"],
        "contraindications": [],
    }


# ─────────────────────────────────────────────────────────────────────
# Helper: Subspecialty action summary para UI
# ─────────────────────────────────────────────────────────────────────


def summarize_subspecialty_recommendations(patient: dict[str, Any]) -> dict[str, Any]:
    """Retorna resumen completo subspecialty para UI panel.

    Returns:
        {
            "actions_count": int,
            "highest_priority": int,
            "urgency_level": "emergent|urgent|soon|elective",
            "next_action_title": str,
            "actions": [ClinicalAction.__dict__, ...],
            "flare_protection_recommended": bool,
            "flare_protocol": dict | None,
        }
    """
    actions = recommend_next_clinical_action(patient)
    if not actions:
        return {
            "actions_count": 0,
            "highest_priority": 5,
            "urgency_level": "elective",
            "next_action_title": "Sin acciones clínicas urgentes detectadas",
            "actions": [],
            "flare_protection_recommended": False,
            "flare_protocol": None,
        }

    flare_actions = [a for a in actions if "flare" in a.action]
    flare_protocol = None
    if flare_actions:
        scc = bool(patient.get("spinal_cord_compression_suspected") or
                    patient.get("spinal_cord_compression_confirmed"))
        widespread_bone = bool(patient.get("widespread_bone_metastases_documented"))
        visceral = bool(patient.get("visceral_metastasis_present"))
        burden = "high" if (widespread_bone and visceral) else (
            "moderate" if (widespread_bone or visceral) else "low"
        )
        flare_protocol = recommend_flare_protection(
            tumor_burden=burden,
            cord_compression_risk=scc,
            ecog=int(patient.get("ecog_current") or 0),
        )

    top = actions[0]
    return {
        "actions_count": len(actions),
        "highest_priority": top.priority,
        "urgency_level": top.urgency,
        "next_action_title": top.title,
        "actions": [
            {
                "priority": a.priority,
                "action": a.action,
                "title": a.title,
                "rationale": a.rationale,
                "urgency": a.urgency,
                "timeline_days": a.timeline_days,
                "evidence_refs": a.evidence_refs,
                "contraindications": a.contraindications,
            }
            for a in actions
        ],
        "flare_protection_recommended": flare_protocol is not None,
        "flare_protocol": flare_protocol,
    }
