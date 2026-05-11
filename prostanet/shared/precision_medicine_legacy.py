import logging

# Configurar logger
logger = logging.getLogger(__name__)

def evaluate_patient_for_mhspc(patient_data):
    """
    Evalúa mHSPC (Metastásico Hormono-Sensible).
    Ensayos: CHAARTED, LATITUDE, STAMPEDE, TITAN, ARCHES, ENZAMET, ARASENS, PEACE-1.
    """
    recommendations = []
    contraindications = []
    
    meta_site = patient_data.get('metastasis_site', 'M0')
    meta_count = int(patient_data.get('metastasis_count', 0))
    gleason = int(patient_data.get('gleason_score', 0))
    ecog = int(patient_data.get('ecog_score', 0))
    child_pugh = patient_data.get('child_pugh_score', 'A')
    
    comorbs = patient_data.get('comorbidities', {})
    seizure_risk = comorbs.get('seizure', False)
    cardio_risk = comorbs.get('cardio', False)

    # Criterios Derivados
    is_chaarted_high = (meta_site == 'Visceral') or (meta_count >= 4)
    latitude_count = 0
    if gleason >= 8: latitude_count += 1
    if meta_count >= 3: latitude_count += 1
    if meta_site == 'Visceral': latitude_count += 1
    is_latitude_high = latitude_count >= 2
    
    fit_for_chemo = (ecog <= 2) and (child_pugh != 'C')

    # --- 1. TRIPLETES (Alto Volumen/Riesgo) ---
    if is_chaarted_high and fit_for_chemo:
        rec_text = "ADT + Docetaxel + "
        drugs = []
        if not seizure_risk: drugs.append("Darolutamida")
        if child_pugh != 'C': drugs.append("Abiraterona")
        
        if "Darolutamida" in drugs:
            recommendations.append({
                "drug": "Triplete (Darolutamida)",
                "combination": "ADT + Docetaxel + Darolutamida",
                "evidence": "En base al estudio ARASENS, se recomienda este triplete por demostrar beneficio en Supervivencia Global (HR 0.68) vs Docetaxel solo en mHSPC.",
                "priority": "Highest (Nivel 1A)"
            })
        if "Abiraterona" in drugs:
            recommendations.append({
                "drug": "Triplete (Abiraterona)",
                "combination": "ADT + Docetaxel + Abiraterona",
                "evidence": "En base al estudio PEACE-1, se recomienda este triplete por beneficio en SLP radiográfica y SG en población de alto volumen (de novo).",
                "priority": "Highest (Nivel 1A)"
            })

    # --- 2. DOBLETES (Alto y Bajo Volumen) ---
    # Enzalutamida
    if not seizure_risk:
        recommendations.append({
            "drug": "Enzalutamida",
            "combination": "ADT + Enzalutamida",
            "evidence": "En base a los estudios ARCHES y ENZAMET, se recomienda este doblete por beneficio en SG independientemente del volumen de enfermedad.",
            "priority": "High"
        })
    else:
        contraindications.append("Enzalutamida: Contraindicado por riesgo convulsivo/caídas (Historia Clínica).")

    # Apalutamida
    if not seizure_risk:
        recommendations.append({
            "drug": "Apalutamida",
            "combination": "ADT + Apalutamida",
            "evidence": "En base al estudio TITAN, se recomienda este esquema por beneficio en SG (HR 0.67) en población 'all-comers' (alto y bajo riesgo).",
            "priority": "High"
        })

    # Abiraterona
    if child_pugh == 'C':
        contraindications.append("Abiraterona: Contraindicado por Insuficiencia Hepática Severa (Child-Pugh C).")
    elif cardio_risk:
        recommendations.append({
            "drug": "Abiraterona (Precaución)",
            "combination": "ADT + Abiraterona + Prednisona",
            "evidence": "En base al estudio LATITUDE (Alto Riesgo), se recomienda con monitoreo estricto de potasio/TA dado el riesgo cardiovascular detectado.",
            "priority": "Medium"
        })
    else:
        recommendations.append({
            "drug": "Abiraterona",
            "combination": "ADT + Abiraterona + Prednisona",
            "evidence": "En base al estudio LATITUDE (Alto Riesgo) y STAMPEDE, se recomienda este esquema standard.",
            "priority": "High"
        })

    # Docetaxel (Solo High Volume)
    if is_chaarted_high and fit_for_chemo:
        recommendations.append({
            "drug": "Docetaxel",
            "combination": "ADT + Docetaxel (6 ciclos)",
            "evidence": "En base al estudio CHAARTED, se recomienda quimioterapia por beneficio robusto en SG (17 meses) exclusivamente en enfermedad de Alto Volumen.",
            "priority": "High"
        })
    elif not is_chaarted_high:
         recommendations.append({
            "drug": "Docetaxel (No Recomendado)",
            "combination": "ADT + Docetaxel",
            "evidence": "En base al sub-análisis de CHAARTED, NO se recomienda quimioterapia en Bajo Volumen por falta de beneficio en supervivencia y toxicidad.",
            "priority": "Contraindicated"
        })

    # --- 3. RADIOTERAPIA AL PRIMARIO (STAMPEDE Arm H) ---
    # Solo en Bajo Volumen
    rt_val = patient_data.get('rt_primary_received', 0)
    has_prior_rt = (rt_val == 'on' or rt_val == 1 or rt_val == '1')
    
    if not is_chaarted_high:
        if not has_prior_rt:
            recommendations.append({
                "drug": "Radioterapia al Primario",
                "combination": "RT Externa a Próstata (Estándar)",
                "evidence": "En base al estudio STAMPEDE (Arm H), la RT al primario mejora la Supervivencia Global (HR 0.68) en pacientes con Bajo Volumen Metastásico.",
                "priority": "High"
            })
        else:
            recommendations.append({
                "drug": "Omitir RT Local (Tratada Previamente)",
                "combination": "No se recomienda Re-Irradiación",
                "evidence": "Paciente con antecedente de RT primaria. La evidencia de STAMPEDE H aplica a pacientes *de novo* sin tratamiento local previo.",
                "priority": "Medium"
            })

    return {
        "status": "Evaluated",
        "scenario": "mHSPC",
        "volume_chaarted": "High" if is_chaarted_high else "Low",
        "risk_latitude": "High" if is_latitude_high else "Low",
        "recommendations": recommendations,
        "contraindications": contraindications
    }

def evaluate_patient_for_nmcrpc(patient_data):
    """
    Evalúa nmCRPC (Resistente a Castración No Metastásico).
    Criterio Clave: PSADT (Tiempo de duplicación de PSA) <= 10 meses.
    Ensayos: SPARTAN, PROSPER, ARAMIS.
    """
    # Nota: Asumimos High Risk (PSADT <= 10 mo) por defecto si llega aquí,
    # idealmente deberíamos calcularlo, pero para el registro inicial sugerimos el estándar.
    
    recommendations = []
    contraindications = []
    
    comorbs = patient_data.get('comorbidities', {})
    seizure = comorbs.get('seizure', False)
    
    # 1. Apalutamida (SPARTAN)
    if not seizure:
        recommendations.append({
            "drug": "Apalutamida",
            "combination": "Apalutamida + ADT continuado",
            "evidence": "En base al estudio SPARTAN, se recomienda por retrasar metástasis (MFS) en >2 años vs placebo en nmCRPC de alto riesgo (PSADT <= 10m).",
            "priority": "High (Nivel 1)"
        })
        
        # 2. Enzalutamida (PROSPER)
        recommendations.append({
            "drug": "Enzalutamida",
            "combination": "Enzalutamida + ADT continuado",
            "evidence": "En base al estudio PROSPER, se recomienda por mejora significativa en Supervivencia Libre de Metástasis y SG.",
            "priority": "High (Nivel 1)"
        })
    else:
        contraindications.append("Apalutamida/Enzalutamida: Evitar por riesgo convulsivo.")

    # 3. Darolutamida (ARAMIS)
    # Perfil de toxicidad bajo (baja penetración BHE). Ideal para riesgo neurológico.
    recommendations.append({
        "drug": "Darolutamida",
        "combination": "Darolutamida + ADT continuado",
        "evidence": "En base al estudio ARAMIS, se recomienda este ARPI por eficacia en MFS y menor tasa de fatiga/caídas/deterioro cognitivo vs otros ARPIs.",
        "priority": "High (Preferido en Fragilidad/Neurológico)"
    })

    return {
        "status": "Evaluated",
        "scenario": "nmCRPC (Non-Metastatic CRPC)",
        "risk_group": "High Risk (PSADT <= 10mo assumed)",
        "recommendations": recommendations,
        "contraindications": contraindications
    }

def evaluate_patient_for_mcrpc(patient_data):
    """
    Evalúa mCRPC (Metastásico Resistente a Castración).
    Ensayos: COU-AA-301/302, AFFIRM/PREVAIL, PROfound, KEYNOTE-158, CARD, VISION, ALSYMPCA, TROPIC.
    """
    recommendations = []
    contraindications = []
    
    hrr_status = patient_data.get('hrr_status', 'Desconocido')
    msi_status = patient_data.get('msi_status', 'Estable')
    pain = patient_data.get('pain_symptoms', 'Asintomatico')
    meta_site = patient_data.get('metastasis_site', 'M0')
    prior_tx = patient_data.get('prior_therapy', []) 
    prior_tx_str = str(prior_tx)

    has_prior_arpi = any(x in prior_tx_str for x in ['Enzalutamida', 'Abiraterona', 'Apalutamida', 'Darolutamida'])
    has_prior_docetaxel = 'Docetaxel' in prior_tx_str
    
    # --- MEDICINA DE PRECISIÓN ---
    
    # 1. Inhibidores PARP (PROfound)
    if hrr_status == 'Positivo':
        if has_prior_arpi:
            recommendations.append({
                "drug": "Olaparib",
                "combination": "Olaparib Monoterapia",
                "evidence": "En base al estudio PROfound (Cohorte A), se recomienda Olaparib tras progresión a ARPI en pacientes con alteraciones BRCA1/2 o ATM.",
                "priority": "Highest (Biomarker Driven)"
            })
            
    # 2. Inmunoterapia (KEYNOTE-158)
    if msi_status in ['Inestable', 'High', 'dMMR']:
        recommendations.append({
            "drug": "Pembrolizumab",
            "combination": "Pembrolizumab (200mg Q3W)",
            "evidence": "En base al estudio KEYNOTE-158, se recomienda inmunoterapia en tumores sólidos con inestabilidad microsatelital (MSI-H) tras progresar a terapia estándar.",
            "priority": "Highest (Biomarker Driven)"
        })

    # --- TERAPIAS DIRIGIDAS (Radiofármacos) ---

    # 3. Lu-177 PSMA (VISION / TheraP)
    # Post-ARPI y Post-Taxano (FDA label). 
    if has_prior_arpi and has_prior_docetaxel:
        recommendations.append({
            "drug": "Lu-177 PSMA-617",
            "combination": "Lu-177 PSMA (6 ciclos)",
            "evidence": "En base al estudio VISION, se recomienda tras progresión a ARPI y Taxano, demostrando beneficio en SG y rPFS (Requiere PET-PSMA positivo).",
            "priority": "High"
        })
    elif has_prior_arpi and not has_prior_docetaxel:
         recommendations.append({
            "drug": "Lu-177 PSMA-617 (Considerar)",
            "combination": "Lu-177 PSMA",
            "evidence": "En base al estudio PSMAfore, podría considerarse en pacientes taxane-naive (pre-quimio) que no son candidatos a taxanos.",
            "priority": "Medium (Emerging Standard)"
        })

    # 4. Radium-223 (ALSYMPCA)
    if (meta_site == 'Hueso') and (meta_site != 'Visceral') and (pain != 'Asintomatico'):
        recommendations.append({
            "drug": "Radium-223",
            "combination": "Ra-223 (6 inyecciones)",
            "evidence": "En base al estudio ALSYMPCA, se recomienda en mCRPC con metástasis óseas sintomáticas, sin enfermedad visceral, mejorando SG y SREs.",
            "priority": "High"
        })

    # --- QUIMIOTERAPIA & ARPI STANDARD ---

    # 5. Taxanos (Docetaxel / Cabazitaxel)
    # Preferido tras progresión rápida a ARPI, o post-Docetaxel.
    
    # [CORRECCION] Lógica unificada para taxanos
    ecog = patient_data.get('ecog_performance_status', 0)
    fit_for_chemo = (ecog <= 2)
    prior_docetaxel_cycles = int(patient_data.get('prior_docetaxel_cycles', 0))
    
    if fit_for_chemo:
        if prior_docetaxel_cycles >= 6:
            recommendations.append({
                "drug": "Cabazitaxel",
                "combination": "Cabazitaxel + Prednisona",
                "evidence": "En base al estudio CARD, Cabazitaxel es superior a un segundo ARPI en pacientes que progresaron a Docetaxel (Resistencia a Taxanos) y un ARPI previo.",
                "priority": "High"
            })
            contraindications.append("Docetaxel: No re-challenge inmediato (Posible Resistencia/Progresión tras 6 ciclos previos).")
        else:
            recommendations.append({
                "drug": "Docetaxel",
                "combination": "Docetaxel + Prednisona",
                "evidence": "En base al estudio TAX-327, Docetaxel es primera línea en mCRPC si no se recibió previamente o si hubo buena respuesta (>12 meses libre).",
                "priority": "High"
            })

    return {
        "status": "Evaluated",
        "scenario": "mCRPC (Metastatic Castration Resistant)",
        "molecular_profile": f"HRR: {hrr_status}, MSI: {msi_status}",
        "recommendations": recommendations,
        "contraindications": contraindications
    }

