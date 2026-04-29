from __future__ import annotations

from prostanet.shared.phoenix import evaluate_phoenix


def classify_recurrence(payload: dict) -> dict:
    prior_prostatectomy = str(payload.get("prior_prostatectomy", "0")) == "1"
    prior_radiation = str(payload.get("prior_radiation", "0")) == "1"
    bcr2 = str(payload.get("bcr2", "0")) == "1"
    psa_current = float(payload.get("psa_current", payload.get("psa", 0)) or 0)
    psadt = float(payload.get("psadt_months", 999) or 999)
    imaging_negative = str(payload.get("imaging_negative", "0")) == "1"
    conventional_imaging_m0 = str(payload.get("conventional_imaging_m0", payload.get("imaging_negative", "0"))) == "1"
    prior_secondary_rt = str(payload.get("prior_secondary_rt", "0")) == "1"
    eligible_pelvic_therapy = str(payload.get("eligible_pelvic_therapy", "1")) == "1"
    salvage_local_feasible = str(payload.get("salvage_local_feasible", payload.get("eligible_pelvic_therapy", "1"))) == "1"
    local_salvage_candidate = str(payload.get("local_salvage_candidate", payload.get("eligible_pelvic_therapy", "1"))) == "1"
    psma_pet_done = str(payload.get("psma_pet_done", "0")) == "1"
    psma_pet_result = str(payload.get("psma_pet_result", "No realizado"))

    # Phoenix gate (NCCN PROS-10, EAU 2026 §6.3.2). Si hay radioterapia previa
    # y el paciente aún no cumple nadir+2 ng/mL, NO se etiqueta como recurrencia.
    phoenix = evaluate_phoenix(payload)
    phoenix_payload = phoenix.to_dict()

    psma_pet_recommended = False
    psma_pet_reason = ""

    if prior_prostatectomy and psa_current > 0.2 and salvage_local_feasible:
        psma_pet_recommended = True
        psma_pet_reason = "Post-RP con PSA >0.2 ng/mL donde PSMA-PET podría cambiar la estrategia de rescate."
    elif prior_radiation and local_salvage_candidate and phoenix.threshold_reached:
        psma_pet_recommended = True
        psma_pet_reason = "Post-RT con Phoenix cumplido y posibilidad de rescate local potencialmente curativo."

    if bcr2 and conventional_imaging_m0:
        high_risk = psadt <= 9
        enza_match = high_risk and not salvage_local_feasible
        return {
            "label": "BCR2 N0M0",
            "recommendation": "Use BCR high-risk systemic intensification only when the EMBARK-like pattern is documented on conventional M0 imaging and no curative local salvage path remains.",
            "enza_match": enza_match,
            "apalutamide_experimental": high_risk and prior_prostatectomy and (prior_secondary_rt or not salvage_local_feasible) and psa_current >= 0.5,
            "high_risk_bcr2": high_risk,
            "psma_pet_recommended": psma_pet_recommended,
            "psma_pet_reason": psma_pet_reason,
            "salvage_local_feasible": salvage_local_feasible,
            "local_salvage_candidate": local_salvage_candidate,
            "conventional_imaging_m0": conventional_imaging_m0,
            "psma_pet_done": psma_pet_done,
            "psma_pet_result": psma_pet_result,
            "phoenix": phoenix_payload,
        }

    if prior_prostatectomy:
        return {
            "label": "Post-RP recurrence",
            "recommendation": "Favor early salvage RT evaluation and risk-adapted ADT rather than delayed treatment; reserve PSMA-PET for settings where it can change curative-intent salvage.",
            "enza_match": False,
            "apalutamide_experimental": False,
            "high_risk_bcr2": False,
            "psma_pet_recommended": psma_pet_recommended,
            "psma_pet_reason": psma_pet_reason,
            "salvage_local_feasible": salvage_local_feasible,
            "local_salvage_candidate": local_salvage_candidate,
            "conventional_imaging_m0": conventional_imaging_m0,
            "psma_pet_done": psma_pet_done,
            "psma_pet_result": psma_pet_result,
            "phoenix": phoenix_payload,
        }

    if prior_radiation:
        if not phoenix.threshold_reached:
            return {
                "label": "Pre-Phoenix monitoring",
                "recommendation": (
                    "PSA aún no cumple criterio Phoenix (nadir + 2 ng/mL). "
                    "No detonar salvage ni re-estadificación precoz; mantener "
                    "PSA cada 3 meses hasta cumplir Phoenix o evidencia "
                    "clínica/radiográfica/biopsia de recurrencia local."
                ),
                "enza_match": False,
                "apalutamide_experimental": False,
                "high_risk_bcr2": False,
                "psma_pet_recommended": False,
                "psma_pet_reason": "Diferir PSMA-PET hasta cumplir Phoenix o confirmar recurrencia local.",
                "salvage_local_feasible": salvage_local_feasible,
                "local_salvage_candidate": local_salvage_candidate,
                "conventional_imaging_m0": conventional_imaging_m0,
                "psma_pet_done": psma_pet_done,
                "psma_pet_result": psma_pet_result,
                "phoenix": phoenix_payload,
                "phoenix_gate_blocked": True,
            }
        return {
            "label": "Post-RT recurrence",
            "recommendation": "Re-stage and consider local salvage versus systemic transition based on kinetics and whether salvage remains technically curative.",
            "enza_match": False,
            "apalutamide_experimental": False,
            "high_risk_bcr2": False,
            "psma_pet_recommended": psma_pet_recommended,
            "psma_pet_reason": psma_pet_reason,
            "salvage_local_feasible": salvage_local_feasible,
            "local_salvage_candidate": local_salvage_candidate,
            "conventional_imaging_m0": conventional_imaging_m0,
            "psma_pet_done": psma_pet_done,
            "psma_pet_result": psma_pet_result,
            "phoenix": phoenix_payload,
        }

    return {
        "label": "Recurrence assessment",
        "recommendation": "Insufficient local-therapy context; confirm recurrence setting.",
        "enza_match": False,
        "apalutamide_experimental": False,
        "high_risk_bcr2": False,
        "psma_pet_recommended": psma_pet_recommended,
        "psma_pet_reason": psma_pet_reason,
        "salvage_local_feasible": salvage_local_feasible,
        "local_salvage_candidate": local_salvage_candidate,
        "conventional_imaging_m0": conventional_imaging_m0,
        "psma_pet_done": psma_pet_done,
        "psma_pet_result": psma_pet_result,
        "phoenix": phoenix_payload,
    }
