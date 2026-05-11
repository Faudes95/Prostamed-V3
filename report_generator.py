
# -*- coding: utf-8 -*-
"""
Generador de Reportes Clínicos Narrativos para ProstaMed.
Integra datos del paciente, historial PSA, biopsia y scores validados (NCCN, CAPRA, Briganti).
"""
import datetime
from typing import Any

def generate_narrative_report(patient: dict[str, Any], scores: dict[str, Any], psa_kinetics: dict[str, Any]) -> str:
    """
    Genera el "RESUMEN CLÍNICO INTEGRADO" en formato texto.
    """
    # ── 1. Header & Datos Básicos ────────────────────────────────────────
    edad = patient.get('age', 'N/A')
    ape_actual = patient.get('psa', 'N/A')
    fecha_ape = patient.get('fecha_psa_actual', datetime.date.today().strftime('%d/%m/%Y'))
    
    reporte = []
    reporte.append("**RESUMEN CLÍNICO INTEGRADO**\n")
    reporte.append(f"Paciente de **{edad}** años con APE de **{ape_actual}** ng/mL (según última medición el {fecha_ape}).\n")

    # ── 2. Cinética de PSA ───────────────────────────────────────────────
    vel = psa_kinetics.get('velocity')
    psadt = psa_kinetics.get('psadt_months')
    
    k_text = ""
    if vel is not None and psadt is not None:
        vel_str = f"{vel:.2f}"
        psadt_str = f"{psadt}"
        
        # Interpretación dinámica
        interp = "estable"
        if vel > 0.75 or (isinstance(psadt, (int, float)) and psadt < 10):
            interp = "PROGRESIÓN RÁPIDA (>0.75 ng/mL/año o PSADT <10m), un indicador de agresividad"
        elif vel < 0:
            interp = "tendencia al descenso"
        else:
            interp = "comportamiento estable"

        k_text = (f"Según su historial de APE, que muestra una Velocidad de **{vel_str}** ng/mL/año y "
                  f"un Tiempo de Duplicación de **{psadt_str}** meses, el comportamiento bioquímico sugiere **{interp}**.")
    else:
        k_text = "No se dispone de historial suficiente para calcular cinética de APE."
    
    reporte.append(f"{k_text}\n")

    # ── 3. Riesgo NCCN & Factores ────────────────────────────────────────
    nccn = scores.get('nccn', {})
    risk_group = nccn.get('risk_group', 'NO CLASIFICADO')
    factores = nccn.get('factores', [])
    factores_list = "\n".join([f"*   **{f}**" for f in factores]) if factores else "*   Sin factores de riesgo identificados"
    
    reporte.append(f"Se clasifica como **RIESGO {risk_group}** debido a la presencia de:")
    if factores:
        for f in factores:
            reporte.append(f"*   **{f}**")  # El backend ya devuelve strings descriptivos (ej. "PSA > 20")
    else:
        reporte.append("*   Sin factores de riesgo identificados (probable Bajo Riesgo).")
    reporte.append("") # Spacer

    # ── 4. Biopsia y Estadificación ──────────────────────────────────────
    gleason_total = patient.get('gleason_total', 
                                patient.get('gleason_primary', 0) + patient.get('gleason_secondary', 0))
    p1 = patient.get('gleason_primary', '?')
    p2 = patient.get('gleason_secondary', '?')
    isup = patient.get('isup_grade', '?')
    cores_pos = patient.get('num_cores_positive', '?')
    cores_tot = patient.get('total_cores', '?')
    pct_cores = float(patient.get('pct_cores_positive', 0)) * 100
    t_stage = patient.get('clinical_tstage', 'Tx')
    
    # Análisis de correlación (Lógica simple)
    corr_msg = "riesgo estándar asociado a su grupo de grado"
    if t_stage in ('T2b', 'T2c') or pct_cores > 50:
         corr_msg = "Riesgo Elevado de extensión extraprostática por carga tumoral o palpación"
    elif t_stage == 'T1c' and pct_cores < 15:
         corr_msg = "Alta probabilidad de enfermedad confinada al órgano (indolente)"

    reporte.append(f"La biopsia reporta un **Gleason {gleason_total} ({p1}+{p2})**, correspondiente a un "
                   f"**ISUP Grade Group {isup}**, con **{cores_pos} de {cores_tot} cores positivos ({pct_cores:.1f}%)**.")
    reporte.append(f"El análisis de correlación con el **Estadio Clínico {t_stage}** y la carga tumoral sugiere **{corr_msg}**.\n")

    # ── 5. Recomendaciones NCCN ──────────────────────────────────────────
    rec = nccn.get('recomendacion', 'Consultar guías completas.')
    reporte.append(f"**SEGÚN LAS GUÍAS NCCN (5.2026), SE SUGIERE:**")
    reporte.append(f"*   **{rec}**\n")

    # ── 6. Análisis Adicional (CAPRA, Briganti) ──────────────────────────
    capra = scores.get('capra', {})
    capra_pts = capra.get('score', '?')
    capra_risk = capra.get('risk_group', '?')
    capra_pfs = capra.get('bcr_free_5y', '?')
    
    briganti = scores.get('briganti', {})
    lni_prob = briganti.get('probabilidad_raw', '?')
    eplnd = briganti.get('eplnd_recomendada', False)
    briganti_interp = ("Supera el umbral del 5% (Guias EAU 2026), por lo que la **Linfadenectomia Pelvica Extendida (ePLND) debe considerarse si se elige cirugia**." 
                       if eplnd else 
                       "Riesgo bajo (<5%), la linfadenectomia puede omitirse.")

    reporte.append(f"**ANÁLISIS DE RIESGO ADICIONAL:**")
    reporte.append(f"*   **CAPRA Score (Pre-Op)**: **{capra_pts}** puntos (**Riesgo {capra_risk}**).")
    reporte.append(f"*   **Nomograma de Briganti**: Riesgo de Invasión Linfática (LNI) del **{lni_prob}%**.")
    reporte.append(f"    *   **Interpretación**: {briganti_interp}")

    # ── 7. Pronóstico Post-Prostatectomía (CAPRA-S) ──────────────────────
    if 'capra_s' in scores:
        cs = scores['capra_s']
        score_s = cs.get('score', '?')
        risk_s = cs.get('risk_group', '?')
        pfs = cs.get('bcr_free_survival', {})
        pfs_3y = pfs.get('3y', '?')
        pfs_5y = pfs.get('5y', '?')
        
        reporte.append("\n**PRONÓSTICO POST-PROSTATECTOMÍA (CAPRA-S):**")
        reporte.append(f"El paciente presenta un **Score CAPRA-S de {score_s}**, clasificándose como **RIESGO {risk_s}** de recurrencia.")
        reporte.append(f"*   Probabilidad estimada de **No Recurrencia Bioquímica (BCR-Free Survival)**:")
        reporte.append(f"    *   A 3 años: **{pfs_3y}%**")
        reporte.append(f"    *   A 5 años: **{pfs_5y}%**")
        reporte.append(f"    *   *(Basado en Cooperberg et al., J Urol 2011)*")

    # ── 8. Esperanza de Vida y Contexto Geriátrico (NUEVO v3.0) ──────────
    le_data = scores.get('life_expectancy', {})
    le_years = le_data.get('years', '?')
    le_base = le_data.get('base_years', '?')
    le_penalty = le_data.get('cci_penalty_pct', 0)
    le_rec = le_data.get('recommendation_text', 'N/A')
    
    reporte.append(f"\n**CONTEXTO GERIÁTRICO Y EXPECTATIVA DE VIDA:**")
    reporte.append(f"Estimación ajustada por edad ({edad} años) y comorbilidades (CCI): **{le_years} años**.")
    if le_penalty > 0:
        reporte.append(f"*(Reducción del {le_penalty}% sobre la base de {le_base} años debido a carga de comorbilidad)*.")
    
    # Justificación Clínica (Requerimiento Usuario)
    if le_data.get('less_than_10y', False) and risk_group not in ('MUY ALTO', 'ALTO'):
        reporte.append(f"\n> [!IMPORTANT]\n> **RECOMENDACIÓN CLÍNICA FUNDAMENTADA:**")
        reporte.append(f"> Dado que la expectativa de vida estimada es **< 10 años**, las guías internacionales (NCCN, EAU) recomiendan fuertemente **VIGILANCIA ACTIVA / OBSERVACIÓN** sobre la intervención quirúrgica.")
        reporte.append(f"> *Justificación*: El riesgo competitivo de mortalidad supera el beneficio oncológico de la cirugía en este escenario (evitar sobretratamiento iatrogénico).")

    # ── 9. Partin Tables (NUEVO v3.0) ─────────────────────────────────────
    partin = scores.get('partin', {})
    if partin:
        reporte.append(f"\n**DISTRIBUCIÓN PATOLÓGICA ESTIMADA (PARTIN TABLES):**")
        reporte.append(f"*   Enf. Órgano-Confinada: **{partin.get('oc_prob', '?')}%**")
        reporte.append(f"*   Extensión Extracapsular (ECE): **{partin.get('ece_prob', '?')}%**")
        reporte.append(f"*   Invasión Vesículas Seminales (SVI): **{partin.get('svi_prob', '?')}%**")
        reporte.append(f"*   Invasión Ganglionar (LNI): **{partin.get('lni_prob', '?')}%**")

    # ── 10. Elegibilidad Vigilancia Activa (NUEVO v3.0) ───────────────────
    as_data = scores.get('as_eligibility', {})
    if as_data:
        protocols = as_data.get('protocols', {})
        eligible_count = as_data.get('eligible_count', 0)

        reporte.append(f"\n**ELEGIBILIDAD PARA VIGILANCIA ACTIVA:**")
        if eligible_count > 0:
            reporte.append(f"El paciente es ELEGIBLE para Vigilancia Activa en **{eligible_count}** protocolo(s):")
            for name, info in protocols.items():
                status = "ELEGIBLE" if info.get('eligible') else f"NO ({info.get('reason', '')})"
                label = name.replace('_', ' ').upper()
                reporte.append(f"*   {label}: **{status}**")
        else:
            excl = as_data.get('exclusion_reason', 'Criterios no cumplidos')
            reporte.append(f"El paciente **NO ES ELEGIBLE** para Vigilancia Activa. Motivo: {excl}")
            for name, info in protocols.items():
                label = name.replace('_', ' ').upper()
                reporte.append(f"*   {label}: NO — {info.get('reason', '')}")

    # ── 11. Imagen Avanzada (NUEVO v3.0) ──────────────────────────────────
    pirads = patient.get('pirads', 0)
    psma = patient.get('psma_resultado', 'no_realizado')
    bone = patient.get('bone_scan_result', 'no_realizado')
    has_imaging = pirads > 0 or psma != 'no_realizado' or bone != 'no_realizado'

    if has_imaging:
        reporte.append(f"\n**ESTUDIOS DE IMAGEN:**")
        if pirads > 0:
            pirads_interp = {1: 'Muy baja sospecha', 2: 'Baja sospecha', 3: 'Equívoco', 4: 'Alta sospecha', 5: 'Muy alta sospecha'}
            reporte.append(f"*   **mpMRI PI-RADS {pirads}**: {pirads_interp.get(pirads, 'N/A')}")
            lesion_mm = patient.get('tamano_lesion_mm', 0)
            if lesion_mm > 0:
                reporte.append(f"    *   Lesión dominante: **{lesion_mm} mm**")
            if patient.get('mpmri_ece_suspicion'):
                reporte.append(f"    *   Sospecha de ECE por imagen")
            if patient.get('mpmri_svi_suspicion'):
                reporte.append(f"    *   Sospecha de SVI por imagen")
        if psma != 'no_realizado':
            psma_labels = {'negativo': 'Negativo', 'positivo_local': 'Positivo local', 'positivo_ganglionar': 'Positivo ganglionar', 'positivo_oseo': 'Positivo óseo', 'positivo_visceral': 'Positivo visceral'}
            reporte.append(f"*   **PSMA-PET**: {psma_labels.get(psma, psma)}")
        if bone != 'no_realizado':
            reporte.append(f"*   **Gammagrama Óseo**: {'Positivo' if bone == 'positivo' else 'Negativo'}")

    # ── 12. Perfil Genómico (NUEVO v3.0) ──────────────────────────────────
    genomic_test = patient.get('genomic_test_type', 'ninguna')
    genomic_score = patient.get('genomic_score', 0)
    hrr = patient.get('hrr_status', 'desconocido')
    msi = patient.get('msi_status', 'desconocido')
    has_genomics = genomic_test != 'ninguna' or hrr != 'desconocido' or msi != 'desconocido'

    if has_genomics:
        reporte.append(f"\n**PERFIL GENÓMICO Y MEDICINA DE PRECISIÓN:**")
        if genomic_test != 'ninguna':
            test_name = {'decipher': 'Decipher', 'prolaris': 'Prolaris (CCP)', 'oncotype': 'Oncotype DX GPS'}.get(genomic_test, genomic_test)
            reporte.append(f"*   **{test_name}**: Score = **{genomic_score}**")
            if genomic_test == 'decipher':
                if genomic_score < 0.45:
                    reporte.append(f"    *   Riesgo Bajo (<0.45) — Favorable para Vigilancia Activa")
                elif genomic_score <= 0.60:
                    reporte.append(f"    *   Riesgo Intermedio (0.45-0.60) — Considerar tratamiento definitivo")
                else:
                    reporte.append(f"    *   Riesgo Alto (>0.60) — Sugiere enfermedad agresiva, tratamiento activo recomendado")
        if hrr != 'desconocido':
            hrr_labels = {'negativo': 'Negativo', 'positivo_brca': 'Positivo (BRCA1/2)', 'positivo_atm': 'Positivo (ATM)', 'positivo_otro': 'Positivo (otro gen HRR)'}
            reporte.append(f"*   **Estado HRR**: {hrr_labels.get(hrr, hrr)}")
            if 'positivo' in hrr:
                reporte.append(f"    *   Elegible para inhibidores de PARP (Olaparib, Rucaparib) — PROfound, TRITON3")
        if msi != 'desconocido':
            reporte.append(f"*   **MSI**: {'Inestable (MSI-H) — Elegible para Pembrolizumab (KEYNOTE-158)' if msi == 'inestable' else 'Estable (MSS)'}")

    # ── 13. Factores de Riesgo / Comorbilidades (NUEVO v3.0) ──────────────
    comorbidities = []
    if patient.get('diabetes_mellitus'): comorbidities.append('Diabetes Mellitus')
    if patient.get('hipertension'): comorbidities.append('Hipertensión Arterial')
    if patient.get('sindrome_metabolico'): comorbidities.append('Síndrome Metabólico')
    tab = patient.get('tabaquismo', 'nunca')
    if tab != 'nunca':
        tab_labels = {'exfumador': 'Exfumador', 'activo_leve': 'Fumador activo (<15 cig/día)', 'activo_severo': 'Fumador activo (>15 cig/día)'}
        comorbidities.append(tab_labels.get(tab, tab))

    if comorbidities:
        reporte.append(f"\n**FACTORES DE RIESGO Y COMORBILIDADES:**")
        for c in comorbidities:
            reporte.append(f"*   {c}")
        if tab == 'activo_severo':
            reporte.append(f"    *   Tabaquismo severo (>15 cig/día): asociado a mayor agresividad y mortalidad en CaP")

    ipss = patient.get('ipss_score', 0)
    if ipss > 0:
        ipss_sev = 'Leve' if ipss <= 7 else ('Moderado' if ipss <= 19 else 'Severo')
        reporte.append(f"*   **IPSS**: {ipss} ({ipss_sev}) — Síntomas del tracto urinario inferior")

    # ── 14. Score Integrado ProstaMed ──────────────────────────────────
    ps = scores.get('prostanet_score', {})
    if ps:
        reporte.append(f"\n**SCORE INTEGRADO PROSTAMED:**")
        reporte.append(f"Puntuación compuesta: **{ps.get('score', '?')} / 100** (Riesgo **{ps.get('risk_group', '?')}**)")
        reporte.append(f"Integra: NCCN (30%), CAPRA (25%), Briganti (15%), Kattan (15%), Cinética PSA (15%)")

    # ── 15. Densidad de PSA ───────────────────────────────────────────────
    psad = scores.get('psad', 0)
    if psad > 0:
        vol = patient.get('volumen_prostatico', 0)
        reporte.append(f"\n**DENSIDAD DE APE (PSAD):** {psad:.3f} ng/mL/cc (Vol. prostático: {vol} cc)")
        if psad >= 0.15:
            reporte.append(f"*   PSAD >=0.15: Factor desfavorable — reduce elegibilidad para vigilancia activa y aumenta riesgo de reclasificacion")
        else:
            reporte.append(f"*   PSAD <0.15: Factor favorable para vigilancia activa en contextos seleccionados")

    reporte.append(f"\n---\n*Generado por ProstaMed v3.0 — {datetime.date.today().strftime('%d/%m/%Y')}*")
    reporte.append(f"*Algoritmos: NCCN 2026 | CAPRA | CAPRA-S | Briganti 2017 | Kattan/MSK | Partin 2017 | ProstaMed Score*")

    return "\n".join(reporte)

if __name__ == "__main__":
    # Test layout
    pass
