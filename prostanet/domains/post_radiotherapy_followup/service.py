from __future__ import annotations

from datetime import datetime

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.post_radiotherapy_followup.rules_eau import (
    classify_post_rt_followup_eau,
)
from prostanet.domains.post_radiotherapy_followup.rules_nccn import (
    classify_post_rt_followup_nccn,
)
from prostanet.domains.post_radiotherapy_or_local_salvage.logic import (
    build_post_rt_failure_definition,
)
from prostanet.domains.post_radiotherapy_followup.schemas import POST_RT_FOLLOWUP_SCHEMA
from prostanet.shared.contracts import evaluation_result


def _months_since(date_str: str) -> int | None:
    if not date_str:
        return None
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
    delta = datetime.now() - d
    return int(delta.days / 30.44)


def _to_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _late_rt_tier(text: str) -> int:
    """Auditoría Pacientes Insignia 2026-04-21 (§C.2) — traduce el valor del
    FieldSpec CTCAE v5 (o alias boolean legacy) a tier 0-5.

    Tier mapping:
      0 — "Sin toxicidad"
      1 — "Grado 1 – leve"
      2 — "Grado 2 – moderado" (o alias boolean 1/Sí/yes/true)
      3 — "Grado 3 – severo"
      4 — "Grado 4 – amenaza vida"
      5 — "Grado 5 – muerte"
    """
    t = str(text or "").strip().lower()
    if not t:
        return 0
    if "grado 5" in t or "muerte" in t:
        return 5
    if "grado 4" in t:
        return 4
    if "grado 3" in t:
        return 3
    if "grado 2" in t:
        return 2
    if "grado 1" in t:
        return 1
    if t in {"sin toxicidad", "no", "0", "false"}:
        return 0
    # Alias boolean legacy (perfil insignia RADICALS-RT entrega "1" / "Sí")
    if t in {"sí", "si", "1", "yes", "true"}:
        return 2
    return 0


def _build_toxicity_management(urinary_grade: int, bowel_grade: int, payload: dict) -> list[dict]:
    actions: list[dict] = []
    if urinary_grade >= 3:
        actions.append({
            "system": "urinary",
            "grade": urinary_grade,
            "action": "Referir a urología; cistoscopía; oxígeno hiperbárico para cistitis hemorrágica refractaria.",
            "evidence": "NCCN Survivorship; Cochrane HBO 2018",
        })
    elif urinary_grade == 2:
        actions.append({
            "system": "urinary",
            "grade": 2,
            "action": "Antimuscarínicos para urgencia; alfa-bloqueador si obstrucción funcional; descartar infección.",
            "evidence": "NCCN Survivorship",
        })

    if bowel_grade >= 3:
        actions.append({
            "system": "bowel",
            "grade": bowel_grade,
            "action": "Referir gastroenterología; APC para sangrado refractario; sucralfato enemas.",
            "evidence": "NCCN Survivorship; AGA Proctitis Guidelines",
        })
    elif bowel_grade == 2:
        actions.append({
            "system": "bowel",
            "grade": 2,
            "action": "Sucralfato tópico, mesalazina, dieta baja en residuos; descartar otras causas.",
            "evidence": "NCCN Survivorship",
        })

    if str(payload.get("late_sexual_function", "")) in {"Deteriorada", "Ausente"}:
        actions.append({
            "system": "sexual",
            "action": "PDE5 inhibidores diarios o a demanda; vacuum device; inyecciones intracavernosas; referir andrología.",
            "evidence": "EAU Sexual Health Guidelines",
        })

    # Auditoría Pacientes Insignia 2026-04-21 (§C.2) — RADICALS-RT entrega
    # señales late_rt_toxicity_gu / late_rt_toxicity_gi (CTCAE v5). Traducir a
    # tier, derivar a urología/GI a partir de grado ≥2, y marcar bloqueo de
    # re-irradiación a partir de grado ≥3.
    late_gu_tier = _late_rt_tier(payload.get("late_rt_toxicity_gu"))
    late_gi_tier = _late_rt_tier(payload.get("late_rt_toxicity_gi"))

    if late_gu_tier >= 2:
        actions.append({
            "system": "late_rt_gu",
            "grade": late_gu_tier,
            "grade_tier": late_gu_tier,
            "action": "Derivación a urología por toxicidad tardía GU post-radioterapia.",
            "blocks_reirradiation": late_gu_tier >= 3,
            "category": "late_rt_toxicity",
            "evidence": (
                "RADICALS-RT / RTOG late toxicity: evaluar tratamiento sintomático, "
                "manejo estenosis, urodinamia. Grado ≥3 contraindica re-irradiación."
            ),
        })

    if late_gi_tier >= 2:
        actions.append({
            "system": "late_rt_gi",
            "grade": late_gi_tier,
            "grade_tier": late_gi_tier,
            "action": "Derivación a gastroenterología por toxicidad tardía GI post-radioterapia.",
            "blocks_reirradiation": late_gi_tier >= 3,
            "category": "late_rt_toxicity",
            "evidence": (
                "RADICALS-RT / RTOG late toxicity: evaluar proctitis, descartar fístula, "
                "manejo sintomático. Grado ≥3 contraindica re-irradiación."
            ),
        })

    return actions


def _build_second_primary_screening(payload: dict) -> list[dict]:
    actions = [
        {
            "screening": "Cáncer de vejiga",
            "indication": "Cistoscopía si hematuria macroscópica o microhematuria persistente.",
            "rationale": "Riesgo aumentado 1.5-2x post-RT pélvica (NCCN Survivorship).",
        },
        {
            "screening": "Cáncer colorrectal",
            "indication": "Colonoscopía según guías edad-específicas.",
            "rationale": "Riesgo aumentado ~1.5x post-RT pélvica.",
        },
    ]
    if str(payload.get("smoking_status", "")) == "Activo":
        actions.append({
            "screening": "Cesación tabáquica",
            "indication": "Programa estructurado de cesación.",
            "rationale": "Sinergismo con riesgo de cáncer de vejiga post-RT.",
        })
    return actions


def _build_adt_survivorship(payload: dict) -> list[dict]:
    return [
        {"action": "DXA basal y cada 24 meses", "rationale": "Osteoporosis ADT-inducida (NCCN Survivorship)."},
        {"action": "Calcio 1200 mg + Vit D 800-1000 UI/día", "rationale": "Profilaxis ósea."},
        {"action": "Lípidos + HbA1c anual", "rationale": "Síndrome metabólico ADT."},
        {"action": "Evaluación CV anual", "rationale": "Riesgo CV ADT-asociado (Levine 2010)."},
        {"action": "Screening depresión (PHQ-9)", "rationale": "Mayor incidencia bajo ADT."},
        {"action": "Consejería sobre sofocos, fatiga, sarcopenia, anemia", "rationale": "Calidad de vida bajo ADT."},
    ]


def _collect_missing(payload: dict) -> list[str]:
    missing: list[str] = []
    for required in ("psa_current", "psa_nadir", "prior_rt_modality", "prior_rt_completion_date"):
        value = payload.get(required)
        if value is None or str(value).strip() == "":
            missing.append(required)
    return missing


class PostRadiotherapyFollowupService:
    module_id = "post_radiotherapy_followup"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return POST_RT_FOLLOWUP_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        failure_definition = build_post_rt_failure_definition(payload)
        psa_current = _to_float(failure_definition.get("psa_current"))
        psa_nadir = _to_float(failure_definition.get("psa_nadir"))
        phoenix_threshold = _to_float(failure_definition.get("phoenix_threshold"))
        phoenix_delta = _to_float(failure_definition.get("phoenix_delta"))
        phoenix_failure = bool(failure_definition.get("phoenix_threshold_reached"))

        months_post_rt = _months_since(str(payload.get("prior_rt_completion_date") or ""))
        modality = str(payload.get("prior_rt_modality") or "")
        is_brachy = modality in {"Brachy LDR", "Brachy HDR", "EBRT + Brachy boost"}
        bounce_window = months_post_rt is not None and 12 <= months_post_rt <= 36 and is_brachy
        bounce_likely = bool(failure_definition.get("bounce_suspected"))

        psadt = _to_float(failure_definition.get("psadt_months") or payload.get("psa_doubling_time_months"))
        high_risk_phoenix = phoenix_failure and psadt > 0 and psadt < 9

        if months_post_rt is None or months_post_rt < 24:
            psa_cadence = "Cada 3 meses"
            dre_cadence = "Cada 6 meses"
        elif months_post_rt < 60:
            psa_cadence = "Cada 6 meses"
            dre_cadence = "Anual"
        else:
            psa_cadence = "Anual"
            dre_cadence = "Anual"

        urinary_grade = _to_int(payload.get("late_urinary_grade"))
        bowel_grade = _to_int(payload.get("late_bowel_grade"))
        toxicity_actions = _build_toxicity_management(urinary_grade, bowel_grade, payload)
        second_primary_actions = _build_second_primary_screening(payload)

        adt_active = str(payload.get("adt_active", "0")) == "1"
        adt_duration = _to_float(payload.get("adt_duration_months"))
        adt_actions = _build_adt_survivorship(payload) if (adt_active or adt_duration >= 12) else []

        nccn = classify_post_rt_followup_nccn(payload)
        eau = classify_post_rt_followup_eau(payload)
        comparison = self.comparison.compare(nccn, eau)

        eligible_treatments: list[dict] = [
            {
                "name": "Vigilancia activa post-RT",
                "cadence": psa_cadence,
                "evidence": "NCCN PROS-9",
            },
            {
                "name": "Examen rectal digital",
                "cadence": dre_cadence,
                "evidence": "NCCN PROS-9 / EAU 2026",
            },
            {
                "name": "Manejo de toxicidad tardía",
                "actions": toxicity_actions,
            },
            {
                "name": "Vigilancia de segundos primarios pélvicos",
                "actions": second_primary_actions,
            },
        ]
        if adt_actions:
            eligible_treatments.append({
                "name": "Survivorship asociado a ADT",
                "actions": adt_actions,
            })

        not_recommended: list[str] = []
        if not phoenix_failure:
            not_recommended.append(
                "No iniciar terapia de salvage local (prostatectomía, criocirugía, HIFU, re-irradiación) "
                "sin haber documentado fallo bioquímico Phoenix y biopsia prostática confirmatoria."
            )

        # Auditoría Pacientes Insignia 2026-04-21 (§C.3) — gate de re-irradiación:
        # toxicidad tardía GU/GI CTCAE v5 grado ≥3 contraindica re-irradiación
        # local, priorizando manejo sintomático multidisciplinar y rutas
        # sistémicas alternativas (RADICALS-RT / RTOG late toxicity).
        late_gu_tier = _late_rt_tier(payload.get("late_rt_toxicity_gu"))
        late_gi_tier = _late_rt_tier(payload.get("late_rt_toxicity_gi"))
        if late_gu_tier >= 3 or late_gi_tier >= 3:
            _system_label = "GU" if late_gu_tier >= 3 else "GI"
            not_recommended.append(
                "Re-irradiación local contraindicada por toxicidad tardía "
                f"{_system_label} grado ≥3 (CTCAE v5). Priorizar manejo sintomático "
                "multidisciplinar y evaluar terapias sistémicas alternativas "
                "(RADICALS-RT / RTOG late toxicity)."
            )

        restaging_plan = None
        if phoenix_failure and not bounce_likely:
            restaging_plan = {
                "imaging": "PSMA-PET/CT preferente; alternativa CT abdomen-pelvis + bone scan.",
                "mpmri": "mpMRI prostático antes de la biopsia para localizar la recurrencia.",
                "biopsy": "Biopsia prostática transperineal si es candidato a salvage.",
                "lab": "Testosterona si recibió ADT previo.",
                "transition_state": "post_radiotherapy_or_local_salvage",
                "salvage_release_status": failure_definition.get("salvage_release_status"),
            }

        durations = [
            f"Phoenix threshold: {phoenix_threshold:.2f} ng/mL" if phoenix_threshold is not None else "Phoenix threshold: no calculable",
            f"PSA actual: {psa_current:.2f} ng/mL" if psa_current is not None else "PSA actual: no informado",
            f"Phoenix delta: {phoenix_delta:+.2f} ng/mL" if phoenix_delta is not None else "Phoenix delta: no calculable",
            f"Tiempo post-RT: {months_post_rt} meses" if months_post_rt is not None else "Tiempo post-RT: no informado",
            f"Bounce probable: {'Sí' if bounce_likely else 'No'}",
            f"Fallo bioquímico Phoenix: {'Sí' if phoenix_failure else 'No'}",
        ]
        confirmation_status = str(failure_definition.get("phoenix_confirmation_status") or "not_met")
        if confirmation_status:
            durations.append(f"Confirmación longitudinal Phoenix: {confirmation_status}")
        if high_risk_phoenix:
            durations.append("PSADT <9 meses sobre Phoenix positivo: priorizar restadificación urgente.")

        report_sections = {
            "summary": (
                f"Seguimiento post-radioterapia ({modality or 'modalidad no informada'}): "
                f"{nccn['label']}. Cinética PSA y toxicidad tardía RTOG/EORTC monitoreadas."
            ),
            "phoenix_assessment": {
                "phoenix_threshold": phoenix_threshold,
                "phoenix_delta": phoenix_delta,
                "phoenix_failure": phoenix_failure,
                "phoenix_threshold_reached": failure_definition.get("phoenix_threshold_reached"),
                "phoenix_confirmation_status": failure_definition.get("phoenix_confirmation_status"),
                "psa_nadir": psa_nadir,
                "psa_nadir_date": failure_definition.get("psa_nadir_date"),
                "psadt_months": failure_definition.get("psadt_months"),
                "bounce_likely": bounce_likely,
                "bounce_suspected": failure_definition.get("bounce_suspected"),
                "high_risk_phoenix": high_risk_phoenix,
                "salvage_release_status": failure_definition.get("salvage_release_status"),
            },
            "surveillance_protocol": {
                "psa_cadence": psa_cadence,
                "dre_cadence": dre_cadence,
                "imaging_cadence": "Solo si síntomas o Phoenix positivo",
            },
            "toxicity_management": toxicity_actions,
            "restaging_plan": restaging_plan,
            "second_primary_screening": second_primary_actions,
            "adt_survivorship": adt_actions,
            "post_rt_failure_definition": failure_definition,
        }

        missing_inputs = _collect_missing(payload) + list(failure_definition.get("required_missing_fields") or [])

        return evaluation_result(
            state=self.module_id,
            nccn_primary={
                "guideline": "NCCN",
                "version": "5.2026",
                "label": nccn["label"],
                "recommendation": nccn["recommendation"],
                "panel": nccn.get("panel", ""),
            },
            eau_comparison={
                "guideline": "EAU",
                "version": "2026",
                "label": eau["label"],
                "recommendation": eau["recommendation"],
                "comparison": comparison,
            },
            eligible_treatments=eligible_treatments,
            not_recommended=not_recommended,
            missing_critical_inputs=list(dict.fromkeys(missing_inputs)),
            contraindications=[],
            durations_and_conditions=durations,
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=[],
            applicability_badge="guideline-consistent",
            report_sections=report_sections,
            decision_quality={
                "recommendation_family": "Vigilancia post-RT",
                "confidence_category": "vigilada" if missing_inputs else "alta",
                "requires_human_review": bool(phoenix_failure and not bounce_likely),
            },
        )
