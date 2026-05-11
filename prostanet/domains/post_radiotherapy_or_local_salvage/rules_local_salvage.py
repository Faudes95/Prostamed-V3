from __future__ import annotations

from typing import Any


_YES = {"1", "true", "yes", "si", "sí", "positive", "positivo", "confirmed", "confirmado"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    return _text(value).lower() in _YES


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _text(value)
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _stage_localized(stage: Any) -> bool:
    normalized = _text(stage).upper().replace(" ", "")
    if not normalized:
        return True
    return normalized.startswith(("T1", "T2")) or normalized in {"LOCAL", "LOCALIZED", "LOCALIZADO"}


def _option(
    *,
    regimen_code: str,
    name: str,
    base_score: float,
    eligible: bool,
    hard_blocks: list[str] | None = None,
    caution_flags: list[str] | None = None,
    why_this_rank: list[str] | None = None,
) -> dict[str, Any]:
    hard_blocks = _dedupe(list(hard_blocks or []))
    caution_flags = _dedupe(list(caution_flags or []))
    score = base_score - (45 if hard_blocks else 0) - (8 * len(caution_flags))
    if hard_blocks:
        priority = "blocked"
    elif caution_flags:
        priority = "eligible"
    else:
        priority = "eligible"
    return {
        "regimen_code": regimen_code,
        "name": name,
        "eligible": bool(eligible and not hard_blocks),
        "priority": priority,
        "score": round(score, 1),
        "hard_blocks": hard_blocks,
        "caution_flags": caution_flags,
        "why_this_rank": _dedupe(list(why_this_rank or [])),
    }


def evaluate_local_salvage_options(payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload or {})
    biopsy_confirmed = (
        _truthy(payload.get("biopsy_proven_local_recurrence"))
        or _truthy(payload.get("local_recurrence_biopsy_confirmed"))
        or _truthy(payload.get("biopsy_confirmed"))
    )
    months_since_rt = _safe_float(payload.get("months_since_rt") or payload.get("months_from_rt"))
    psa = _safe_float(payload.get("psa") or payload.get("psa_current"))
    psadt = _safe_float(payload.get("psadt_months") or payload.get("psa_doubling_time_months"))
    ecog = _safe_int(payload.get("ecog_score") or payload.get("ecog"))
    life_expectancy = _safe_float(payload.get("life_expectancy_years"))
    prostate_volume = _safe_float(payload.get("prostate_volume") or payload.get("prostate_volume_cc"))
    unilateral = _truthy(payload.get("lesion_unilateral")) or _truthy(payload.get("unilateral_lesion"))
    focal_local = (
        unilateral
        or _truthy(payload.get("mpmri_localized_recurrence"))
        or _truthy(payload.get("focal_local_recurrence"))
        or "focal" in _text(payload.get("local_recurrence_site")).lower()
    )
    distant_negative = (
        _truthy(payload.get("psma_pet_negative_distant"))
        or _truthy(payload.get("no_distant_metastases"))
        or _text(payload.get("psma_stage_after_psma")).upper() in {"", "M0"}
    )
    disseminated = (
        _truthy(payload.get("visceral_metastasis"))
        or _truthy(payload.get("distant_metastasis"))
        or _text(payload.get("psma_stage_after_psma")).upper() in {"M1B", "M1C"}
        or _text(payload.get("psma_uptake_pattern")).lower() in {"diseminado", "disseminated"}
    )
    oligomet = (
        _text(payload.get("psma_stage_after_psma")).upper() == "M1A"
        or _text(payload.get("psma_uptake_pattern")).lower() in {"oligometastatic", "oligometastatico", "oligometastásico"}
    )
    localized_stage = _stage_localized(payload.get("local_recurrence_stage"))

    global_blocks: list[str] = []
    missing_inputs: list[str] = []
    if not biopsy_confirmed:
        missing_inputs.append("biopsy_proven_local_recurrence")
        global_blocks.append("Falta biopsia confirmatoria de recurrencia local antes de abrir rescate curativo post-radioterapia.")
    if disseminated:
        global_blocks.append("La enfermedad diseminada o M1b/M1c no sostiene rescate local aislado.")
    if months_since_rt is not None and months_since_rt < 24:
        global_blocks.append("El intervalo desde radioterapia es corto; descartar bounce y confirmar recurrencia persistente.")
    if psadt is not None and psadt < 6:
        global_blocks.append("PSADT corto sugiere biología sistémica y exige reestadificación antes de rescate local aislado.")
    if ecog is not None and ecog > 2:
        global_blocks.append("ECOG >2 reduce factibilidad de procedimientos de rescate local.")
    if life_expectancy is not None and life_expectancy < 5:
        global_blocks.append("Expectativa de vida limitada reduce beneficio esperado de rescate local curativo.")
    if not distant_negative and not oligomet:
        global_blocks.append("Falta documentar ausencia de enfermedad a distancia por PSMA-PET o imagen equivalente.")

    general_candidate = biopsy_confirmed and not global_blocks
    surgery_fit = (ecog is None or ecog <= 1) and (life_expectancy is None or life_expectancy >= 10)
    volume_ok_for_hifu = prostate_volume is None or prostate_volume <= 40
    volume_ok_for_ablation = prostate_volume is None or prostate_volume <= 60
    local_stage_ok = localized_stage

    options = [
        _option(
            regimen_code="SALVAGE_RP",
            name="Prostatectomía de rescate",
            base_score=72,
            eligible=general_candidate and surgery_fit and local_stage_ok,
            hard_blocks=[] if general_candidate and surgery_fit and local_stage_ok else _dedupe(global_blocks + ([] if surgery_fit else ["Aptitud quirúrgica no óptima para prostatectomía de rescate."])),
            caution_flags=[] if surgery_fit else ["Discutir morbilidad urinaria/rectal y referencia a centro experto."],
            why_this_rank=["Opción curativa local cuando biopsia confirma recurrencia confinada y el paciente es quirúrgicamente apto."],
        ),
        _option(
            regimen_code="SALVAGE_HIFU",
            name="HIFU de rescate",
            base_score=74 if unilateral else 66,
            eligible=general_candidate and focal_local and volume_ok_for_hifu and local_stage_ok,
            hard_blocks=[]
            if general_candidate and focal_local and volume_ok_for_hifu and local_stage_ok
            else _dedupe(
                global_blocks
                + ([] if focal_local else ["HIFU requiere recurrencia focal/localizada bien delimitada."])
                + ([] if volume_ok_for_hifu else ["Volumen prostático alto limita HIFU de rescate."])
            ),
            caution_flags=[] if unilateral else ["HIFU es más fuerte si la lesión es unilateral o focal."],
            why_this_rank=["Lesión unilateral/focal favorece una estrategia ablativa con menor carga que cirugía mayor."],
        ),
        _option(
            regimen_code="SALVAGE_CRYOTHERAPY",
            name="Crioterapia de rescate",
            base_score=68,
            eligible=general_candidate and focal_local and volume_ok_for_ablation,
            hard_blocks=[]
            if general_candidate and focal_local and volume_ok_for_ablation
            else _dedupe(global_blocks + ([] if focal_local else ["Crioterapia requiere recurrencia local delimitable."])),
            caution_flags=[] if volume_ok_for_ablation else ["Volumen prostático alto aumenta toxicidad/limitaciones técnicas."],
            why_this_rank=["Alternativa ablativa cuando existe recurrencia intraprostática confirmada."],
        ),
        _option(
            regimen_code="SALVAGE_BRACHYTHERAPY",
            name="Braquiterapia de rescate",
            base_score=62,
            eligible=general_candidate and local_stage_ok,
            hard_blocks=[] if general_candidate and local_stage_ok else _dedupe(global_blocks),
            caution_flags=["Requiere revisar dosis/campos previos y toxicidad rectal/urinaria antes de reirradiar."],
            why_this_rank=["Puede considerarse si la recurrencia es local y la toxicidad previa permite reirradiación."],
        ),
        _option(
            regimen_code="PSMA_GUIDED_MDT",
            name="MDT/SBRT guiada por PSMA",
            base_score=76 if oligomet else 50,
            eligible=biopsy_confirmed and oligomet and not disseminated,
            hard_blocks=[] if biopsy_confirmed and oligomet and not disseminated else _dedupe(([] if biopsy_confirmed else global_blocks) + ([] if oligomet else ["MDT requiere patrón oligorrecurrente en PSMA."])),
            caution_flags=[],
            why_this_rank=["El patrón oligorrecurrente favorece tratamiento dirigido a lesiones."],
        ),
        _option(
            regimen_code="SYSTEMIC_RESTAGING",
            name="Reestadificación / redirección sistémica",
            base_score=90 if global_blocks or disseminated else 38,
            eligible=True,
            hard_blocks=[],
            caution_flags=[] if global_blocks else ["Debe permanecer visible si la factibilidad local se cierra por toxicidad o enfermedad a distancia."],
            why_this_rank=["Ruta necesaria cuando no se puede sostener rescate local curativo aislado."],
        ),
    ]
    options.sort(key=lambda item: item["score"], reverse=True)
    first_eligible = next((item for item in options if item["eligible"] and item["regimen_code"] != "SYSTEMIC_RESTAGING"), None)
    if first_eligible:
        first_eligible["priority"] = "preferred"
    elif options:
        options[0]["priority"] = "preferred"

    summary = (
        "Candidato a rescate local post-radioterapia con biopsia confirmada y sin enfermedad a distancia documentada."
        if general_candidate
        else "No liberar rescate local todavía: " + " ".join(global_blocks or ["faltan datos críticos, incluyendo biopsia confirmatoria."])
    )
    return {
        "general_candidate_for_local_salvage": bool(general_candidate),
        "summary": summary,
        "missing_inputs": _dedupe(missing_inputs),
        "blocking_reasons": _dedupe(global_blocks),
        "local_salvage_options": options,
        "dominant_option": next((item for item in options if item.get("priority") == "preferred"), options[0] if options else {}),
        "version": "source_recovered_v1",
    }


__all__ = ["evaluate_local_salvage_options"]
