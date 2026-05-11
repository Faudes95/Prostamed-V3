from __future__ import annotations


def _adverse_pathology_flag(payload: dict) -> bool:
    """Auditoría Pacientes Insignia 2026-04-21 (§E.4) — traduce el campo
    declarado `adverse_pathology` (ES-médica, opciones "Desconocido"/"No"/"Sí")
    y alias legacy boolean del perfil insignia RADICALS-RT.
    """
    raw = str(payload.get("adverse_pathology") or "").strip().lower()
    return raw in {"sí", "si", "yes", "1", "true"}


def classify_post_rp(payload: dict) -> dict:
    psa_postop = float(payload.get("psa_postop", payload.get("psa_current", 0)) or 0)
    margin = str(payload.get("surgical_margin", "0")) == "1"
    ece = str(payload.get("ece_status", "0")) == "1"
    svi = str(payload.get("svi_status", "0")) == "1"
    lni = str(payload.get("lni_status", "0")) == "1"
    decipher_risk = str(payload.get("decipher_risk", "No realizado"))
    eligible_pelvic_therapy = str(payload.get("eligible_pelvic_therapy", "1")) == "1"
    time_to_recurrence = float(payload.get("time_to_recurrence_months", 0) or 0)
    bcr_confirmed = str(payload.get("bcr_detected", "0")).lower() in {"1", "true", "yes", "si"}
    # Auditoría Pacientes Insignia 2026-04-21 (§E.4) — el perfil RADICALS-RT
    # documenta `adverse_pathology` como un bundle (Gleason ≥8 pT3+, márgenes
    # positivos, SVI, ISUP ≥4). Cuando el clínico lo marca explícito, el flag
    # reflexiona énfasis de salvage RT temprana sin depender solo del
    # desdoblamiento booleano local de margin/ece/svi/lni.
    adverse_pathology_declared = _adverse_pathology_flag(payload)
    adverse = margin or ece or svi or lni or adverse_pathology_declared

    if bcr_confirmed or psa_postop >= 0.2:
        return {
            "label": "BCR / recurrencia bioquímica pos-RP",
            "recommendation": "Escalar a evaluación de recurrencia bioquímica o rescate en lugar de vigilancia rutinaria.",
            "adverse_features": adverse,
            "adverse_pathology_declared": adverse_pathology_declared,
            "early_salvage_emphasis": eligible_pelvic_therapy,
        }
    if psa_postop >= 0.1:
        return {
            "label": "PSA detectable bajo pos-RP",
            "recommendation": "Mantener vigilancia estrecha y confirmar si evoluciona a BCR estructurada antes de fijar el carril de rescate.",
            "adverse_features": adverse,
            "adverse_pathology_declared": adverse_pathology_declared,
            "early_salvage_emphasis": eligible_pelvic_therapy and (
                decipher_risk == "Alto"
                or 0 < time_to_recurrence <= 24
                or adverse_pathology_declared
            ),
        }
    if adverse or decipher_risk == "Alto":
        return {
            "label": "Adverse pathology under surveillance",
            "recommendation": "Prefiera monitoreo estrecho con planificación temprana de rescate; use Decipher y el tiempo a recurrencia para refinar la urgencia en lugar de tratamiento adyuvante reflejo para todo paciente.",
            "adverse_features": adverse,
            "adverse_pathology_declared": adverse_pathology_declared,
            "early_salvage_emphasis": eligible_pelvic_therapy and (
                decipher_risk == "Alto"
                or 0 < time_to_recurrence <= 24
                or adverse_pathology_declared
            ),
        }
    return {
        "label": "Post-RP surveillance",
        "recommendation": "La vigilancia posoperatoria estándar es apropiada.",
        "adverse_features": adverse,
        "adverse_pathology_declared": adverse_pathology_declared,
        "early_salvage_emphasis": False,
    }
