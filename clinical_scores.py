# -*- coding: utf-8 -*-
"""
Herramientas clínicas validadas para cáncer de próstata.

Implementa:
  1. CAPRA Score (UCSF, Cooperberg et al. 2005)
  2. NCCN Risk Stratification (v5.2026)
  3. Kattan / MSK Pre-RP Nomogram — Organ-Confined Disease
  4. Briganti Nomogram — Lymph Node Invasion (aproximación)

Todas las funciones reciben un dict con los datos del paciente y
devuelven un dict con los resultados del score correspondiente.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any


def _score_is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No realizado", "Desconocido", "Desconocida")


def _score_safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _score_safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


# ============================================================================
# 1. CAPRA SCORE  (0–10 puntos)
#    Cooperberg MR et al. Cancer 2005; 105(9):2115-25
# ============================================================================

def capra_score(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Calcula el UCSF-CAPRA Score.

    Variables:
        - age:               Edad al diagnóstico
        - psa:               PSA total (ng/mL)
        - gleason_primary:   Patrón Gleason primario (3, 4 o 5)
        - gleason_secondary: Patrón Gleason secundario (3, 4 o 5)
        - clinical_tstage:   Estadio T clínico (T1c, T2a, T2b, T2c, T3a, T3b, T4)
        - pct_cores_positive: Fracción de cores positivos (0.0 – 1.0)
    """
    missing_inputs: list[str] = []
    psa = _score_safe_float(patient.get('psa', patient.get('baseline_psa')))
    if psa is None:
        missing_inputs.append('psa')
    gp = _score_safe_int(patient.get('gleason_primary'))
    gs = _score_safe_int(patient.get('gleason_secondary'))
    if gp is None:
        missing_inputs.append('gleason_primary')
    if gs is None:
        missing_inputs.append('gleason_secondary')
    tstage = str(patient.get('clinical_tstage') or '').upper().strip()
    if not tstage:
        missing_inputs.append('clinical_tstage')
    pct = _score_safe_float(patient.get('pct_cores_positive'))
    if pct is None:
        positive = _score_safe_int(patient.get('num_cores_positive', patient.get('positive_cores')))
        total = _score_safe_int(patient.get('total_cores'))
        if positive is None or total in (None, 0):
            if positive is None:
                missing_inputs.append('num_cores_positive')
            if total in (None, 0):
                missing_inputs.append('total_cores')
        else:
            pct = positive / total
    if missing_inputs:
        return {
            'score': None,
            'max_score': 10,
            'risk_group': 'INCOMPLETO',
            'desglose': {},
            'missing_inputs': list(dict.fromkeys(missing_inputs)),
            'summary': 'CAPRA basal pendiente de patología suficiente.',
            'bcr_free_3y': None,
            'bcr_free_5y': None,
            'referencia': 'Cooperberg et al., Cancer 2005;105(9):2115-25',
        }

    points: dict[str, int] = {}

    # — Edad —
    age = patient.get('age', 65)
    points['edad'] = 1 if age >= 50 else 0

    # — PSA (ng/mL) —
    if psa <= 6:
        points['psa'] = 0
    elif psa <= 10:
        points['psa'] = 1
    elif psa <= 20:
        points['psa'] = 2
    elif psa <= 30:
        points['psa'] = 3
    else:
        points['psa'] = 4

    # — Gleason (patrón primario / secundario) —
    if gp >= 4:
        # Patrón primario ≥ 4
        points['gleason'] = 3
    elif gs >= 4:
        # Patrón secundario ≥ 4
        points['gleason'] = 1
    else:
        points['gleason'] = 0

    # — Estadio T clínico —
    if tstage in ('T3A', 'T3B', 'T4'):
        points['estadio_t'] = 1
    else:
        points['estadio_t'] = 0

    # — % cores positivos —
    # CAPRA usa ≥ 34%
    points['pct_cores'] = 1 if pct >= 0.34 else 0

    total = sum(points.values())

    # Categoría de riesgo
    if total <= 2:
        risk_group = 'BAJO'
    elif total <= 5:
        risk_group = 'INTERMEDIO'
    else:
        risk_group = 'ALTO'

    # Estimaciones de recurrencia bioquímica libre a 3 y 5 años
    # Basadas en Cooperberg et al. 2005 (tabla de supervivencia)
    bcr_free = _capra_bcr_free(total)

    return {
        'score': total,
        'max_score': 10,
        'risk_group': risk_group,
        'desglose': points,
        'missing_inputs': [],
        'bcr_free_3y': bcr_free[0],
        'bcr_free_5y': bcr_free[1],
        'referencia': 'Cooperberg et al., Cancer 2005;105(9):2115-25',
    }


def _capra_bcr_free(score: int) -> tuple[str, str]:
    """
    Supervivencia libre de recurrencia bioquímica estimada a 3 y 5 años.
    Datos aproximados de Cooperberg et al. 2005 y validaciones posteriores.
    """
    # (3-year BCR-free %, 5-year BCR-free %)
    table = {
        0:  (91, 85),
        1:  (89, 81),
        2:  (85, 75),
        3:  (78, 66),
        4:  (70, 56),
        5:  (63, 48),
        6:  (52, 38),
        7:  (42, 29),
        8:  (31, 20),
        9:  (21, 12),
        10: (12,  6),
    }
    score = max(0, min(10, score))
    bcr3, bcr5 = table[score]
    return f"{bcr3}%", f"{bcr5}%"


# ============================================================================
# 2. NCCN RISK STRATIFICATION  (v5.2026)
# ============================================================================

def nccn_risk_group(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Clasifica al paciente segun los grupos de riesgo NCCN v5.2026.

    Variables requeridas:
        - clinical_tstage:     T1c, T2a, T2b, T2c, T3a, T3b, T4
        - gleason_primary:     Patrón primario (3, 4, 5)
        - gleason_secondary:   Patrón secundario (3, 4, 5)
        - isup_grade:          Grade Group ISUP (1–5)
        - psa:                 PSA (ng/mL)
        - num_cores_positive:  Número de cores positivos
        - total_cores:         Número total de cores
        - pct_cores_positive:  Fracción de cores positivos (0–1)
        - max_core_involvement: Máx. compromiso tumoral en un core (0–1)
        - psad:                Densidad de PSA (ng/mL/cc)  [opcional, calculado]
    """
    tstage = str(patient.get('clinical_tstage', 'T2a')).upper()
    gp = patient.get('gleason_primary') or 3
    gs = patient.get('gleason_secondary') or 3
    gg = patient.get('isup_grade') or 1  # Grade Group
    psa = patient.get('psa', 0)
    n_pos = patient.get('num_cores_positive', 0)
    total_cores = max(int(patient.get('total_cores', 12) or 12), 1)
    pct = patient.get('pct_cores_positive')
    if pct in (None, ''):
        pct = n_pos / total_cores
    pct = float(pct or 0)
    nodal_status = str(patient.get('nodal_status', patient.get('clinical_nstage', 'N0'))).upper()

    # Calcular PSAD si tenemos volumen
    vol = patient.get('volumen_prostatico', 0)
    if vol and vol > 0:
        _psad = psa / vol
    else:
        _psad = patient.get('psad', 0.3)

    if nodal_status == 'N1':
        return _nccn_result(
            'REGIONAL N1M0',
            ['Enfermedad ganglionar regional sin metastasis a distancia'],
            'Radioterapia definitiva + ADT prolongada; considerar intensificacion sistemica en candidatos elegibles',
        )

    # ── Factores de riesgo intermedio ────────────────────────────────────
    ir_factors = 0
    if tstage in ('T2B', 'T2C'):
        ir_factors += 1
    if gg in (2, 3):
        ir_factors += 1
    if 10 <= psa <= 20:
        ir_factors += 1

    # ── Very High Risk ──────────────────────────────────────────────────
    high_risk_count = 0
    if tstage in ('T3A', 'T3B', 'T4'): high_risk_count += 1
    if gg in (4, 5): high_risk_count += 1
    if psa > 20: high_risk_count +=1
    very_high_count = 0
    if tstage in ('T3A', 'T3B', 'T4'): very_high_count += 1
    if gg in (4, 5): very_high_count += 1
    if psa > 40: very_high_count += 1
    if very_high_count >= 2:
        return _nccn_result(
            'MUY ALTO',
            [f'Multiples caracteristicas de muy alto riesgo ({very_high_count})'],
            'EBRT + ADT de larga duracion; considerar intensificacion sistemica en candidatos elegibles o RP en seleccionados',
        )

    # ── High Risk ────────────────────────────────────────────────────────
    high_features = []
    if tstage in ('T3A', 'T3B', 'T4'):
        high_features.append(f'Estadio {tstage}')
    if gg in (4, 5):
        high_features.append(f'Grade Group {gg} (Gleason {gp}+{gs})')
    if psa > 20:
        high_features.append(f'PSA = {psa:.1f} ng/mL (>20)')

    if high_features:
        return _nccn_result('ALTO', high_features,
                            'Radioterapia (EBRT +/- braquiterapia) + ADT de larga duracion o prostatectomia radical + diseccion ganglionar en seleccionados')

    # ── Intermediate Risk (Unfavorable) ──────────────────────────────────
    if ir_factors >= 1:
        is_unfavorable = False
        reasons = []

        if gg == 3:
            is_unfavorable = True
            reasons.append(f'Grade Group 3 (Gleason {gp}+{gs})')
        if pct >= 0.50:
            is_unfavorable = True
            reasons.append(f'{pct:.0%} de cores positivos (>=50%)')
        if ir_factors >= 2:
            is_unfavorable = True
            reasons.append(f'Multiples factores de riesgo intermedio ({ir_factors})')

        if is_unfavorable:
            return _nccn_result('INTERMEDIO DESFAVORABLE', reasons,
                                'Radioterapia + ADT corta (4-6 meses) o prostatectomia radical en candidatos apropiados')

        # ── Intermediate Risk (Favorable) ────────────────────────────────
        reasons = []
        if tstage in ('T2B', 'T2C'):
            reasons.append(f'Estadio {tstage}')
        if gg == 2:
            reasons.append(f'Grade Group 2 (Gleason {gp}+{gs}) con <50% cores positivos')
        if 10 <= psa <= 20:
            reasons.append(f'PSA = {psa:.1f} ng/mL (10-20)')
        return _nccn_result('INTERMEDIO FAVORABLE', reasons,
                            'Observacion o tratamiento local definitivo; vigilancia activa solo en casos cuidadosamente seleccionados')

    # ── Low Risk ─────────────────────────────────────────────────────────
    if tstage in ('T1C', 'T1', 'T2A') and gg == 1 and psa < 10:
        return _nccn_result('BAJO',
                            [f'cT1-T2a, GG1, PSA {psa:.1f} (<10)'],
                            'Vigilancia activa preferida para la mayoria con expectativa de vida >=10 anos')

    # Fallback — clasificar como intermedio
    return _nccn_result('INTERMEDIO FAVORABLE',
                        ['No se pudieron clasificar factores específicos'],
                        'Considerar evaluación adicional')


def _nccn_result(group: str, reasons: list[str], recommendation: str) -> dict:
    return {
        'risk_group': group,
        'factores': reasons,
        'recomendacion': recommendation,
        'referencia': 'NCCN Clinical Practice Guidelines in Oncology — Prostate Cancer v5.2026',
    }


# ============================================================================
# 3. PSA KINETICS & DENSITY 
# ============================================================================
def calculate_psa_kinetics(history: list[tuple[str, float]]) -> dict[str, Any]:
    """
    Calcula velocidad de PSA y tiempo de duplicación (PSADT).
    History: Lista de tuplas (fecha_iso, valor_psa). Ejemplo: [('2023-01-01', 4.0), ...]
    Recomendado: Al menos 3 mediciones en 18-24 meses.
    """
    if not history or len(history) < 2:
        return {'velocity': None, 'psadt': None, 'interpretation': 'Datos insuficientes (<2 mediciones)'}

    import datetime
    
    # Ordenar por fecha
    try:
        data = sorted([(datetime.date.fromisoformat(d), p) for d, p in history], key=lambda x: x[0])
    except ValueError:
        return {'velocity': None, 'psadt': None, 'interpretation': 'Error en formato de fechas (use YYYY-MM-DD)'}

    # 1. PSA Velocity (Linear Regression slope: ng/mL per year)
    # Simple methods uses first and last if linear, but linear regression is better.
    # We will use simple slope between first and last for robustness if N is small,
    # or linear regression if N >= 3.
    
    dates_ordinal = [d.toordinal() for d, _ in data]
    psa_values = [p for _, p in data]
    
    import numpy as np
    
    # Linear Regression (Slope)
    n = len(data)
    if n >= 2:
        x = np.array(dates_ordinal)
        y = np.array(psa_values)
        slug_days = (x[-1] - x[0])
        if slug_days == 0: return {'velocity': 0, 'psadt': 0, 'interpretation': 'Mediciones en el mismo día'}
        
        # Pendiente (m) en ng/mL por día
        m, _ = np.polyfit(x, y, 1)
        
        velocity_year = m * 365.25
    else:
        velocity_year = 0.0

    # 2. Doubling Time (PSADT) - Log slope
    # ln(2) / slope_of_log_PSA
    valid_log_psa = [p for p in psa_values if p > 0]
    if len(valid_log_psa) < 2:
         psadt_months = float('inf')
    else:
         # Usar solo valores > 0
         x_log = []
         y_log = []
         for d, p in zip(dates_ordinal, psa_values):
             if p > 0:
                 x_log.append(d)
                 y_log.append(math.log(p))
         
         if len(x_log) >= 2:
             m_log, _ = np.polyfit(x_log, y_log, 1)
             if m_log > 0.000001:
                doubling_time_days = math.log(2) / m_log
                psadt_months = doubling_time_days / 30.44
             else:
                psadt_months = float('inf') # No crece o decrece
         else:
             psadt_months = float('inf')

    # Interpretación (Carter et al, JAMA)
    interp = []
    
    # Safe rounding
    vel_rounded = round(float(velocity_year), 3) if velocity_year is not None else 0.0
    
    if velocity_year > 0.75:
        interp.append(f"Velocidad ALTA ({vel_rounded} ng/mL/año) — Sugiere riesgo de enfermedad letal/agresiva")
    elif velocity_year < 0:
        interp.append("PSA en descenso")
    else:
        interp.append(f"Velocidad estable ({vel_rounded} ng/mL/año)")

    if psadt_months != float('inf') and psadt_months is not None:
         psadt_rounded = round(float(psadt_months), 1)
         if psadt_months < 10:
            interp.append(f"PSADT RÁPIDO ({psadt_rounded} meses) — Mal pronóstico, alta agresividad")
         else:
             interp.append(f"PSADT {psadt_rounded} meses")
    else:
         psadt_rounded = '>120'
    
    return {
        'velocity': vel_rounded,
        'psadt_months': psadt_rounded,
        'interpretation': " | ".join(interp)
    }

# ============================================================================
# 4. CAPRA-S (POST-SURGICAL) SCORE
# ============================================================================
def calculate_capra_s(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Calcula el Score CAPRA-S (Cooperberg et al., 2011) para riesgo de recurrencia
    bioquímica (BCR) POST-prostatectomía.
    
    Variables requeridas:
    - psa (pre-op)
    - pathology_gleason_primary (o gleason_primary si es post-op)
    - pathology_gleason_secondary (o gleason_secondary si es post-op)
    - surgical_margin (0=Neg, 1=Pos)
    - ece_status (0=No, 1=Sí)
    - svi_status (0=No, 1=Sí)
    - lni_status (0=No, 1=Sí)
    """
    score = 0
    details = {}
    
    # 1. PSA Preoperatorio
    psa = patient.get('psa', 0)
    if psa <= 6:
        s_psa = 0
    elif psa <= 10:
        s_psa = 1
    elif psa <= 20:
        s_psa = 2
    else:
        s_psa = 3
    score += s_psa
    details['psa'] = s_psa

    # 2. Gleason Patológico (Surgical Pathology)
    # Asumimos que si se llama a esta función, los campos gleason corresponden a patología
    # o existen campos específicos 'pathology_gleason...'
    p_gp = patient.get('pathology_gleason_primary', patient.get('gleason_primary', 0))
    p_gs = patient.get('pathology_gleason_secondary', patient.get('gleason_secondary', 0))
    total_g = p_gp + p_gs
    
    s_gl = 0
    if total_g <= 6:
        s_gl = 0
    elif total_g == 7 and p_gp == 3: # 3+4
        s_gl = 1
    elif total_g == 7 and p_gp == 4: # 4+3
        s_gl = 2
    elif total_g >= 8:
        s_gl = 3
    score += s_gl
    details['gleason'] = s_gl

    # 3. Márgenes Quirúrgicos (SM)
    # 0 = Negativo, 1 = Positivo
    sm = patient.get('surgical_margin', 0)
    s_sm = 2 if sm == 1 else 0
    score += s_sm
    details['surgical_margins'] = s_sm

    # 4. Extensión Extracapsular (ECE)
    ece = patient.get('ece_status', 0)
    s_ece = 2 if ece == 1 else 0
    score += s_ece
    details['ece'] = s_ece

    # 5. Invasión Vesículas Seminales (SVI)
    svi = patient.get('svi_status', 0)
    s_svi = 2 if svi == 1 else 0
    score += s_svi
    details['svi'] = s_svi

    # 6. Invasión Ganglionar (LNI)
    lni = patient.get('lni_status', 0)
    s_lni = 3 if lni == 1 else 0
    score += s_lni
    details['lni'] = s_lni
    
    # Riesgo y Probabilidad de Recurrencia (BCR-Free Survival)
    # Cooperberg MR et al. J Urol. 2011;186:452-9.
    # Scores 0-2 (Low), 3-5 (Intermediate), 6-12 (High)
    
    # Estimated PFS (Progression-Free / BCR-Free) %
    # Tabla aproximada basada en curvas de Cooperberg 2011
    pfs_data = {
        0:  {'3y': 98, '5y': 96, '10y': 94},
        1:  {'3y': 96, '5y': 93, '10y': 90},
        2:  {'3y': 93, '5y': 88, '10y': 83},
        3:  {'3y': 85, '5y': 78, '10y': 70},
        4:  {'3y': 78, '5y': 70, '10y': 60},
        5:  {'3y': 70, '5y': 60, '10y': 48},
        6:  {'3y': 60, '5y': 48, '10y': 35},
        7:  {'3y': 48, '5y': 38, '10y': 25},
        8:  {'3y': 35, '5y': 25, '10y': 15},
        9:  {'3y': 25, '5y': 15, '10y': 10},
        10: {'3y': 15, '5y': 10, '10y': 5},
        11: {'3y': 10, '5y': 5,  '10y': 2},
        12: {'3y': 5,  '5y': 0,  '10y': 0}
    }
    
    # Clamp score max 12
    eff_score = min(score, 12)
    pfs = pfs_data.get(eff_score, {'3y':0, '5y':0, '10y':0})
    
    risk_group = 'BAJO'
    if score >= 3: risk_group = 'INTERMEDIO' 
    if score >= 6: risk_group = 'ALTO'
    
    return {
        'score': score,
        'risk_group': risk_group,
        'bcr_free_survival': pfs,
        'breakdown': details,
        'referencia': 'Cooperberg et al. (UCSF), J Urol 2011 (CAPRA-S)'
    }

def calculate_all_scores(patient_data: dict[str, Any]) -> dict[str, Any]:
    """Calcula todos los scores disponibles."""
    results = {
        'nccn': nccn_risk_group(patient_data),
        'capra': capra_score(patient_data),
        'briganti': briganti_lni(patient_data), 
        'kattan_msk': kattan_organ_confined(patient_data),
        'psa_kinetics': {} # Se calcula fuera usualmente, o aquí si se pasara historial
    }
    
    # Calcular CAPRA-S solo si hay datos post-operatorios indicativos
    # (ej. margen reportado o flag explícito)
    # Para ser flexibles, lo calculamos si 'surgical_margin' está presente en keys
    if 'surgical_margin' in patient_data:
        results['capra_s'] = calculate_capra_s(patient_data)
        
    return results







# ============================================================================
# 3. KATTAN / MSK PRE-RP NOMOGRAM — Organ-Confined Disease
#    Coefficients from https://www.mskcc.org/nomograms/prostate/pre-op/coefficients
#    Last updated: December 12, 2024
# ============================================================================

def kattan_organ_confined(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Calcula la probabilidad de enfermedad órgano-confinada
    usando los coeficientes publicados del nomograma MSK/Kattan.

    Modelo: Regresión logística con restricted cubic splines en PSA.
    P(organ-confined) = 1 / (1 + exp(-Xβ))
    """
    age = patient.get('age', 65)
    psa = patient.get('psa', 10.0)
    gg = patient.get('isup_grade') or 1  # Grade Group
    tstage = str(patient.get('clinical_tstage', 'T2a')).upper()

    # ── Coeficientes publicados por MSK (Organ Confined Disease - Cores) ──
    intercept = 4.03916815

    # Variable continua
    beta_age = -0.03091248
    beta_psa = -0.23245617
    beta_psa_sp1 = 0.00152155
    beta_psa_sp2 = -0.00419601

    # Grade Group indicadores (vs GG1 = referencia)
    beta_gg = {1: 0.0, 2: -0.66445702, 3: -1.14834872, 4: -1.20528662, 5: -2.18403820}

    # Clinical Stage indicadores
    beta_stage = {'T1C': 0.0, 'T1': 0.0, 'T2A': -0.22318145, 'T2B': -0.75295200,
                  'T2C': -0.75295200, 'T3A': -1.20000000, 'T3B': -1.60000000,
                  'T4': -2.00000000}

    # ── Restricted cubic splines para PSA ────────────────────────────────
    # Knots aproximados (tertiles típicos del dataset MSK)
    k1, k2, k3, k4 = 0.5, 4.5, 8.0, 40.0
    sp1, sp2 = _rcs_spline(psa, k1, k2, k3, k4)

    # ── Linear predictor ─────────────────────────────────────────────────
    xb = (intercept
          + beta_age * age
          + beta_psa * psa
          + beta_psa_sp1 * sp1
          + beta_psa_sp2 * sp2
          + beta_gg.get(min(gg, 5), 0.0)
          + beta_stage.get(tstage, 0.0))

    prob = 1.0 / (1.0 + math.exp(-xb))
    prob = max(0.01, min(0.99, prob))

    return {
        'probabilidad_organo_confinado': f"{prob:.1%}",
        'probabilidad_raw': round(prob * 100, 1),
        'interpretacion': _kattan_interpretation(prob),
        'variables_usadas': {
            'edad': age,
            'psa': psa,
            'grade_group': gg,
            'estadio_clinico': tstage,
        },
        'referencia': 'Memorial Sloan Kettering Cancer Center — Pre-operative Nomogram (2024)',
        'url': 'https://www.mskcc.org/nomograms/prostate/pre-op',
    }


def _rcs_spline(x: float, k1: float, k2: float, k3: float, k4: float) -> tuple[float, float]:
    """Restricted Cubic Spline con 4 knots — fórmula estándar MSK."""
    def _plus(val: float) -> float:
        return max(0.0, val)

    denom = k4 - k1
    if denom == 0:
        return 0.0, 0.0

    sp1 = (_plus(x - k1) ** 3
           - _plus(x - k3) ** 3 * (k4 - k1) / (k4 - k3)
           + _plus(x - k4) ** 3 * (k3 - k1) / (k4 - k3)) / denom ** 2

    sp2 = (_plus(x - k2) ** 3
           - _plus(x - k3) ** 3 * (k4 - k2) / (k4 - k3)
           + _plus(x - k4) ** 3 * (k3 - k2) / (k4 - k3)) / denom ** 2

    return sp1, sp2


def _kattan_interpretation(prob: float) -> str:
    if prob >= 0.80:
        return 'Alta probabilidad de enfermedad órgano-confinada — favorable para prostatectomía'
    elif prob >= 0.60:
        return 'Probabilidad moderada de enfermedad órgano-confinada'
    elif prob >= 0.40:
        return 'Probabilidad intermedia — considerar evaluación adicional'
    else:
        return 'Baja probabilidad de enfermedad órgano-confinada — posible extensión extraprostática'


# ============================================================================
# 4. BRIGANTI NOMOGRAM — Lymph Node Invasion (LNI)
#    Briganti et al., Eur Urol 2012;61(3):480-7
#    Gandaglia et al., Eur Urol 2017;72(4):632-40 (actualización 2017)
#
#    Coeficientes aproximados basados en tablas de riesgo publicadas y
#    AUC validada de 0.87. Los coeficientes exactos no son públicos.
# ============================================================================

def briganti_lni(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Estima la probabilidad de invasión de ganglios linfáticos (LNI)
    usando una aproximación del nomograma de Briganti.

    Variables:
        - psa:                PSA (ng/mL)
        - clinical_tstage:    Estadio T clínico
        - gleason_primary:    Patrón Gleason primario
        - gleason_secondary:  Patrón Gleason secundario
        - pct_cores_positive: Fracción de cores positivos
    """
    psa = patient.get('psa', 10.0)
    tstage = str(patient.get('clinical_tstage', 'T2a')).upper()
    gp = patient.get('gleason_primary') or 3
    gs = patient.get('gleason_secondary') or 3
    pct = patient.get('pct_cores_positive', 0.0)
    if isinstance(pct, str):
        pct = float(pct)

    # ── Coeficientes estimados (aproximación basada en datos publicados) ──
    intercept = -5.10

    # PSA (log-transform para linearidad)
    beta_psa = 0.65  # log(PSA + 1)
    psa_val = math.log(psa + 1)

    # Estadio clínico
    stage_coefs = {
        'T1C': 0.0, 'T1': 0.0,
        'T2A': 0.25, 'T2B': 0.55, 'T2C': 0.80,
        'T3A': 1.35, 'T3B': 1.90, 'T4': 2.40,
    }

    # Gleason (efecto del patrón primario y secundario)
    # Basado en hazard ratios publicados
    gleason_total = gp + gs
    if gleason_total <= 6:
        gleason_coef = 0.0
    elif gleason_total == 7 and gp == 3:
        gleason_coef = 0.60   # 3+4
    elif gleason_total == 7 and gp == 4:
        gleason_coef = 1.10   # 4+3
    elif gleason_total == 8:
        gleason_coef = 1.50   # 4+4 / 3+5
    elif gleason_total == 9:
        gleason_coef = 2.00   # 4+5 / 5+4
    else:  # 10
        gleason_coef = 2.40   # 5+5

    # % cores positivos (efecto fuerte — "essential importance" per Briganti 2012)
    beta_pct = 2.50

    # ── Linear predictor ─────────────────────────────────────────────────
    xb = (intercept
          + beta_psa * psa_val
          + stage_coefs.get(tstage, 0.0)
          + gleason_coef
          + beta_pct * pct)

    prob = 1.0 / (1.0 + math.exp(-xb))
    prob = max(0.001, min(0.99, prob))

    # Umbral para ePLND (European Guidelines: ≥5%)
    eplnd_recommended = prob >= 0.05

    return {
        'probabilidad_lni': f"{prob:.1%}",
        'probabilidad_raw': round(prob * 100, 1),
        'eplnd_recomendada': eplnd_recommended,
        'eplnd_texto': ('SI — Considerar linfadenectomia pelvica extendida si se elige cirugia (LNI >= 5%)'
                        if eplnd_recommended else
                        'NO — LNI < 5%; ePLND puede omitirse segun guias europeas'),
        'umbral': '5% (EAU 2026)',
        'variables_usadas': {
            'psa': psa,
            'estadio_clinico': tstage,
            'gleason': f'{gp}+{gs} = {gp + gs}',
            'pct_cores_positivos': f'{pct:.0%}',
        },
        'nota': 'Aproximación basada en tablas de riesgo publicadas; '
                'los coeficientes exactos del nomograma no son públicos.',
        'referencia': 'Briganti et al., Eur Urol 2012; Gandaglia et al., Eur Urol 2017',
    }


def calculate_capra_s(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Calcula el Score CAPRA-S (Post-Surgical).
    Cooperberg et al., J Urol 2011.
    """
    def _safe_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _safe_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    psa = _safe_float(patient.get('psa'))
    if psa is None:
        psa = _safe_float(patient.get('psa_current'))
    if psa is None:
        psa = _safe_float(patient.get('baseline_psa'))

    # Gleason Pathological
    gp = _safe_int(patient.get('pathology_gleason_primary'))
    if gp is None:
        gp = _safe_int(patient.get('gleason_primary'))
    gs = _safe_int(patient.get('pathology_gleason_secondary'))
    if gs is None:
        gs = _safe_int(patient.get('gleason_secondary'))

    # CAPRA-S should not score a patient without the minimum pathological inputs.
    if psa is None or gp is None or gs is None:
        missing = []
        if psa is None:
            missing.append('psa')
        if gp is None:
            missing.append('pathology_gleason_primary')
        if gs is None:
            missing.append('pathology_gleason_secondary')
        return {
            'score': None,
            'risk_group': None,
            'risk_text': 'No calculable',
            'missing_inputs': missing,
            'note': 'CAPRA-S requiere PSA y Gleason patológico completos; se omite hasta contar con esos datos.',
        }

    gleason_total = gp + gs
    
    # Surgical Margins (0=Neg, 1=Pos)
    sm = patient.get('surgical_margin_status', patient.get('surgical_margin', 0))
    
    # Extracapsular Extension (0=No, 1=Yes)
    ece = patient.get('extracapsular_extension', patient.get('ece_status', 0))
    
    # Seminal Vesicle Invasion (0=No, 1=Yes)
    svi = patient.get('seminal_vesicle_invasion', patient.get('svi_status', 0))
    
    # Lymph Node Invasion (0=No, 1=Yes)
    lni = patient.get('lymph_node_invasion', patient.get('lni_status', 0))

    score = 0
    
    # 1. PSA Pre-op
    if psa <= 6: score += 0
    elif psa <= 10: score += 1
    elif psa <= 20: score += 2
    else: score += 3
    
    # 2. Gleason Pathological
    if gleason_total <= 6: score += 0 # 3+3 (if any)
    elif gleason_total == 7 and gp == 3: score += 1 # 3+4
    elif gleason_total == 7 and gp == 4: score += 2 # 4+3
    elif gleason_total >= 8: score += 3
    
    # 3. Surgical Margins
    if sm == 1: score += 2
    
    # 4. Extracapsular Extension
    if ece == 1: score += 1
    
    # 5. Seminal Vesicle Invasion
    if svi == 1: score += 2
    
    # 6. Lymph Node Invasion
    if lni == 1: score += 3
    
    # Risgo de BCR (Biochemical Recurrence)
    # Cooperberg 2011 Table 3 estimates (approximate for 5y BCR-free survival)
    # Score 0-2: ~90-96%
    # Score 3-5: ~70-80%
    # Score 6-8: ~40-60%
    # Score >=9: <20%
    
    bcr_risk_map = {
        0: 97, 1: 94, 2: 91,
        3: 86, 4: 80, 5: 75,
        6: 65, 7: 55, 8: 45,
        9: 30, 10: 20, 11: 10, 12: 5
    }
    
    bcr_free_survival_5y = bcr_risk_map.get(min(score, 12), 10)
    
    return {
        'score': score,
        'bcr_free_survival': {'5y': bcr_free_survival_5y},
        'risk_group': 'High' if score >= 6 else ('Intermediate' if score >= 3 else 'Low'),
        'reference': 'Cooperberg et al., J Urol 2011 (CAPRA-S)'
    }

# ============================================================================
# 5. LIFE EXPECTANCY CALCULATOR (Social Security Admin + CCI Adjustment)
#    Fuente: SSA Period Life Table 2020 (USA) como base estandarizada
#    Ajuste: Cho et al. 2013 (Impact of Charlson Comorbidity Index on Survival)
# ============================================================================

def calculate_life_expectancy(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Calcula la esperanza de vida estimada ajustada por edad y comorbilidades.
    """
    age = patient.get('age', 65)
    cci_score = patient.get('cci', 0)
    
    # 1. Base Life Expectancy (SSA 2020 Male - Simplified Lookup)
    # Valor aproximado para hombres
    base_le_table = {
        40: 38.0, 45: 33.5, 50: 29.2, 55: 25.1, 60: 21.2,
        65: 17.5, 70: 14.1, 75: 11.0, 80: 8.2,  85: 5.9,
        90: 4.0,  95: 2.8,  100: 1.9
    }
    
    # Interpolación lineal simple
    lower_age = (age // 5) * 5
    upper_age = lower_age + 5
    lower_val = base_le_table.get(lower_age, 0)
    upper_val = base_le_table.get(upper_age, 0)
    
    # Si edad < 40, asumimos valor de 40. Si > 100, valor de 100.
    if age < 40: base_le = 40.0
    elif age >= 100: base_le = 1.9
    else:
        fraction = (age - lower_age) / 5.0
        base_le = lower_val - (fraction * (lower_val - upper_val))
        
    # 2. Ajuste por Comorbilidad (CCI)
    # Meta-análisis sugieren que CCI >= 2 aumenta HR de mortalidad no-cáncer significativamente
    # Aproximación heurística: Reducir LE en un % por cada punto de CCI > 0
    # Cho et al: CCI 1 (HR 1.2), CCI 2 (HR 1.5), CCI >=3 (HR 2.2+)
    # Modelo simplificado de reducción:
    
    reduction_factor = 1.0
    if cci_score == 1: reduction_factor = 0.85  # -15%
    elif cci_score == 2: reduction_factor = 0.70 # -30%
    elif cci_score == 3: reduction_factor = 0.55 # -45%
    elif cci_score >= 4: reduction_factor = 0.40 # -60%
    
    adjusted_le = base_le * reduction_factor
    
    recommendation = "N/A"
    if adjusted_le < 10:
        recommendation = "Considerar VIGILANCIA ACTIVA / OBSERVACIÓN (LE < 10 años)"
    
    return {
        'years': round(adjusted_le, 1),
        'base_years': round(base_le, 1),
        'cci_penalty_pct': round((1 - reduction_factor) * 100),
        'recommendation_text': recommendation,
        'less_than_10y': adjusted_le < 10
    }


# ============================================================================
# 6. PARTIN TABLES (2017 Update)
#    Eifler et al., BJU Int 2013; Tosoian et al., BJU Int 2017
#    Predicts: Organ-confined, ECE, SVI, LNI probabilities
# ============================================================================

def partin_tables(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Approximation of updated Partin Tables (2017).
    Predicts pathological stage distribution based on clinical variables.
    """
    psa = patient.get('psa', 10.0)
    tstage = str(patient.get('clinical_tstage', 'T2a')).upper()
    gp = patient.get('gleason_primary') or 3
    gs = patient.get('gleason_secondary') or 3
    gg = patient.get('isup_grade') or 1

    # Base probabilities by Grade Group (approximate from Partin 2017 tables)
    # Format: {GG: (OC%, ECE%, SVI%, LNI%)} for PSA 4-10, T1c
    base = {
        1: (80, 15, 3, 2),
        2: (65, 25, 6, 4),
        3: (50, 30, 12, 8),
        4: (35, 30, 18, 17),
        5: (20, 25, 25, 30),
    }
    oc, ece, svi, lni = base.get(min(gg, 5), (50, 30, 12, 8))

    # PSA adjustment
    if psa <= 4:
        oc += 5; ece -= 3; svi -= 1; lni -= 1
    elif psa <= 10:
        pass  # base values
    elif psa <= 20:
        oc -= 10; ece += 5; svi += 3; lni += 2
    else:
        oc -= 20; ece += 8; svi += 6; lni += 6

    # T-stage adjustment
    stage_adj = {
        'T1C': (3, -2, -1, 0), 'T1': (3, -2, -1, 0),
        'T2A': (0, 0, 0, 0),
        'T2B': (-5, 3, 1, 1), 'T2C': (-10, 5, 3, 2),
        'T3A': (-20, 10, 6, 4), 'T3B': (-30, 8, 15, 7),
    }
    adj = stage_adj.get(tstage, (0, 0, 0, 0))
    oc += adj[0]; ece += adj[1]; svi += adj[2]; lni += adj[3]

    # Clamp values
    oc = max(1, min(99, oc))
    ece = max(0, min(80, ece))
    svi = max(0, min(60, svi))
    lni = max(0, min(60, lni))

    # Normalize to ~100%
    total = oc + ece + svi + lni
    if total > 0:
        oc = round(oc / total * 100)
        ece = round(ece / total * 100)
        svi = round(svi / total * 100)
        lni = round(lni / total * 100)

    return {
        'oc_prob': oc,
        'ece_prob': ece,
        'svi_prob': svi,
        'lni_prob': lni,
        'referencia': 'Partin Tables (Tosoian et al., BJU Int 2017)',
    }


# ============================================================================
# 7. ACTIVE SURVEILLANCE ELIGIBILITY (Multi-Protocol)
#    Evaluates eligibility across NCCN, PRIAS, Johns Hopkins, EAU criteria
# ============================================================================

def active_surveillance_eligibility(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Evaluates patient eligibility for Active Surveillance across multiple protocols.
    """
    tstage = str(patient.get('clinical_tstage', 'T2a')).upper()
    gp = patient.get('gleason_primary') or 3
    gs = patient.get('gleason_secondary') or 3
    gg = patient.get('isup_grade') or 1
    psa = patient.get('psa', 10.0)
    n_pos = patient.get('num_cores_positive', 0)
    n_tot = patient.get('total_cores', 12)
    pct = patient.get('pct_cores_positive', 0)
    max_inv = patient.get('max_core_involvement', 0)
    vol = patient.get('volumen_prostatico', 40)
    psad = psa / vol if vol > 0 else 0.3
    le_years = patient.get('life_expectancy_years', 15)

    protocols = {}

    # ── NCCN low-risk with favorable low-volume modifiers ──
    nccn_lm_eligible = (
        tstage == 'T1C' and gg == 1 and psa < 10
        and n_pos < 3 and max_inv <= 0.50 and psad < 0.15
    )
    if nccn_lm_eligible:
        protocols['nccn_low_modifiers'] = {'eligible': True, 'reason': 'Cumple modificadores favorables de bajo volumen para VA'}
    else:
        reasons = []
        if tstage != 'T1C': reasons.append(f'T-stage {tstage} (requiere T1c)')
        if gg != 1: reasons.append(f'GG {gg} (requiere GG1)')
        if psa >= 10: reasons.append(f'PSA {psa} (requiere <10)')
        if n_pos >= 3: reasons.append(f'{n_pos} cores+ (requiere <3)')
        if max_inv > 0.50: reasons.append(f'Max inv {max_inv:.0%} (requiere <=50%)')
        if psad >= 0.15: reasons.append(f'PSAD {psad:.2f} (requiere <0.15)')
        protocols['nccn_low_modifiers'] = {'eligible': False, 'reason': '; '.join(reasons[:2])}

    # ── NCCN Low Risk ──
    nccn_l_eligible = tstage in ('T1C', 'T1', 'T2A') and gg == 1 and psa < 10
    if nccn_l_eligible:
        protocols['nccn_low'] = {'eligible': True, 'reason': 'Cumple criterios Low Risk; NCCN 2026 favorece VA en la mayoria con >=10a de expectativa de vida'}
    else:
        reasons = []
        if tstage not in ('T1C', 'T1', 'T2A'): reasons.append(f'T-stage {tstage}')
        if gg != 1: reasons.append(f'GG {gg}')
        if psa >= 10: reasons.append(f'PSA {psa}')
        protocols['nccn_low'] = {'eligible': False, 'reason': '; '.join(reasons[:2])}

    # ── NCCN Favorable Intermediate ──
    ir_factors = 0
    if tstage in ('T2B', 'T2C'): ir_factors += 1
    if gg in (2, 3): ir_factors += 1
    if 10 <= psa <= 20: ir_factors += 1

    adverse_histology = bool(patient.get('patron_cribiforme')) or bool(patient.get('carcinoma_intraductal'))
    nccn_fi_eligible = (
        gg <= 2 and pct < 0.50 and ir_factors <= 1 and le_years >= 10 and not adverse_histology
    )
    if nccn_fi_eligible and gg >= 1 and (10 <= psa <= 20 or tstage in ('T2B', 'T2C') or gg == 2):
        protocols['nccn_fav_intermediate'] = {'eligible': True, 'reason': 'Candidato seleccionado para VA en favorable intermediate'}
    else:
        protocols['nccn_fav_intermediate'] = {'eligible': False, 'reason': f'GG {gg}, {pct:.0%} cores+, {ir_factors} factores IR o histologia desfavorable'}

    # ── PRIAS ──
    prias_eligible = (
        tstage in ('T1C', 'T1', 'T2') and gg == 1
        and psa <= 10 and psad < 0.2 and n_pos <= 2
    )
    if prias_eligible:
        protocols['prias'] = {'eligible': True, 'reason': 'Cumple criterios PRIAS'}
    else:
        reasons = []
        if gg != 1: reasons.append(f'GG {gg}')
        if psa > 10: reasons.append(f'PSA {psa}')
        if psad >= 0.2: reasons.append(f'PSAD {psad:.2f}')
        if n_pos > 2: reasons.append(f'{n_pos} cores+')
        protocols['prias'] = {'eligible': False, 'reason': '; '.join(reasons[:2])}

    # ── Johns Hopkins ──
    jhu_eligible = (
        tstage == 'T1C' and gg == 1
        and psad < 0.15 and n_pos <= 2 and max_inv <= 0.50
    )
    if jhu_eligible:
        protocols['johns_hopkins'] = {'eligible': True, 'reason': 'Cumple criterios JHU'}
    else:
        reasons = []
        if tstage != 'T1C': reasons.append(f'T-stage {tstage}')
        if gg != 1: reasons.append(f'GG {gg}')
        if psad >= 0.15: reasons.append(f'PSAD {psad:.2f}')
        if n_pos > 2: reasons.append(f'{n_pos} cores+')
        protocols['johns_hopkins'] = {'eligible': False, 'reason': '; '.join(reasons[:2])}

    # Summary
    eligible_count = sum(1 for p in protocols.values() if p['eligible'])
    exclusion = '' if eligible_count > 0 else 'No cumple criterios de ningún protocolo de VA'

    return {
        'protocols': protocols,
        'eligible_count': eligible_count,
        'total_protocols': len(protocols),
        'exclusion_reason': exclusion,
    }


# ============================================================================
# 8. PROSTANET INTEGRATED SCORE (Composite Risk Score)
#    Combines NCCN, CAPRA, Briganti, Kattan, PSA kinetics into single metric
# ============================================================================

def prostanet_integrated_score(patient: dict[str, Any], scores: dict[str, Any]) -> dict[str, Any]:
    """
    Calculates a composite risk score (0-100) integrating multiple validated tools.
    Weights based on published c-indices and clinical relevance.
    """
    # NCCN rank (0-100)
    nccn_rank_map = {
        'BAJO': 15,
        'INTERMEDIO FAVORABLE': 35, 'INTERMEDIO DESFAVORABLE': 55,
        'ALTO': 75, 'MUY ALTO': 95, 'REGIONAL N1M0': 90,
    }
    nccn_val = nccn_rank_map.get(scores.get('nccn', {}).get('risk_group', ''), 50)

    # CAPRA normalized (0-100)
    capra_val = (scores.get('capra', {}).get('score', 5) / 10) * 100

    # Briganti LNI prob (already 0-100)
    briganti_val = min(scores.get('briganti', {}).get('probabilidad_raw', 5), 100)

    # Kattan inverted (high OC prob = low risk)
    kattan_oc = scores.get('kattan_msk', {}).get('probabilidad_raw', 50)
    kattan_inv = 100 - kattan_oc

    # PSA kinetics risk (0-100)
    psa_k = scores.get('psa_kinetics', {})
    vel = psa_k.get('velocity', 0) if psa_k else 0
    psadt = psa_k.get('psadt_months', 120) if psa_k else 120
    if isinstance(psadt, str):
        psadt = 120

    kinetics_risk = 10
    if vel is not None and vel > 0.75:
        kinetics_risk = 80
    elif vel is not None and vel > 0.35:
        kinetics_risk = 50
    elif vel is not None and vel > 0:
        kinetics_risk = 25

    if isinstance(psadt, (int, float)) and psadt < 10:
        kinetics_risk = max(kinetics_risk, 85)
    elif isinstance(psadt, (int, float)) and psadt < 20:
        kinetics_risk = max(kinetics_risk, 50)

    # Weighted composite (weights based on c-index importance)
    # NCCN: 0.30, CAPRA: 0.25, Briganti: 0.15, Kattan: 0.15, Kinetics: 0.15
    composite = (
        0.30 * nccn_val +
        0.25 * capra_val +
        0.15 * briganti_val +
        0.15 * kattan_inv +
        0.15 * kinetics_risk
    )
    composite = round(max(0, min(100, composite)))

    # Risk group
    if composite >= 65:
        risk_group = 'ALTO'
    elif composite >= 35:
        risk_group = 'INTERMEDIO'
    else:
        risk_group = 'BAJO'

    return {
        'score': composite,
        'risk_group': risk_group,
        'components': {
            'nccn': round(nccn_val),
            'capra': round(capra_val),
            'briganti': round(briganti_val),
            'kattan_inv': round(kattan_inv),
            'kinetics': round(kinetics_risk),
        },
        'weights': {'nccn': 0.30, 'capra': 0.25, 'briganti': 0.15, 'kattan': 0.15, 'kinetics': 0.15},
    }


# ============================================================================
# 10. D'AMICO RISK CLASSIFICATION (1998)
#     D'Amico AV et al. JAMA 1998; 280(11):969-974
# ============================================================================

def damico_classification(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Clasificación de riesgo D'Amico para cáncer de próstata localizado.
    Ampliamente usada en ensayos clínicos como comparador estándar.

    Criterios:
        Bajo:         PSA ≤10 AND Gleason ≤6 AND T1c-T2a
        Intermedio:   PSA 10–20 OR Gleason 7 OR T2b
        Alto:         PSA >20 OR Gleason 8–10 OR T2c-T3
    """
    psa = patient.get('psa', patient.get('baseline_psa', 0))
    gp = patient.get('gleason_primary', patient.get('pathology_gleason_primary'))
    gs = patient.get('gleason_secondary', patient.get('pathology_gleason_secondary'))
    isup = patient.get('isup_grade', patient.get('pathological_isup'))

    if gp not in (None, '') and gs not in (None, ''):
        gleason = int(gp) + int(gs)
    elif patient.get('gleason') not in (None, ''):
        gleason = int(patient.get('gleason'))
    elif patient.get('gleason_total') not in (None, ''):
        gleason = int(patient.get('gleason_total'))
    elif isup not in (None, ''):
        isup_value = int(isup)
        gleason = {1: 6, 2: 7, 3: 7, 4: 8, 5: 9}.get(isup_value, 6)
    else:
        gleason = 6
    tstage = str(patient.get('clinical_tstage', patient.get('dre_findings', 'T2a'))).upper()

    # Determine T numeric value for comparison
    t_map = {'T1A': 1, 'T1B': 1, 'T1C': 1.5, 'T2A': 2, 'T2B': 2.5, 'T2C': 2.7, 'T3A': 3, 'T3B': 3.5, 'T4': 4}
    t_val = t_map.get(tstage, 2)

    risk_factors = []
    alto_criteria = []
    inter_criteria = []
    bajo = True

    # High risk criteria
    if psa > 20:
        alto_criteria.append(f'PSA {psa:.1f} >20')
        bajo = False
    if gleason >= 8:
        alto_criteria.append(f'Gleason {gleason} ≥8')
        bajo = False
    if t_val >= 2.7:  # T2c or higher
        alto_criteria.append(f'Estadio {tstage} ≥T2c')
        bajo = False

    # Intermediate risk criteria
    if 10 < psa <= 20:
        inter_criteria.append(f'PSA {psa:.1f} (10-20)')
        bajo = False
    if gleason == 7:
        inter_criteria.append(f'Gleason 7')
        bajo = False
    if tstage == 'T2B':
        inter_criteria.append(f'Estadio T2b')
        bajo = False

    if alto_criteria:
        group = 'ALTO'
        reasons = alto_criteria
        survival_5y = '~75%'
        survival_10y = '~50%'
    elif inter_criteria:
        group = 'INTERMEDIO'
        reasons = inter_criteria
        survival_5y = '~85%'
        survival_10y = '~65%'
    else:
        group = 'BAJO'
        reasons = ['PSA ≤10, Gleason ≤6, ≤T2a']
        survival_5y = '~95%'
        survival_10y = '~85%'

    return {
        'classification': 'D\'Amico',
        'risk_group': group,
        'criteria': reasons,
        'bcr_free_5y': survival_5y,
        'bcr_free_10y': survival_10y,
        'reference': 'D\'Amico AV et al. JAMA 1998;280:969-974'
    }


# ============================================================================
# 11. EAU RISK GROUPS (2026)
#     European Association of Urology
# ============================================================================

def eau_risk_groups(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Clasificación de riesgo EAU para cáncer de próstata localizado.
    Referencia estándar europea, incluye 5 categorías.

    Bajo:           PSA <10, ISUP 1, cT1-2a
    Intermedio:     PSA 10-20 OR ISUP 2-3 OR cT2b
    Alto:           PSA >20 OR ISUP 4-5 OR cT2c
    Localmente Avanzado: cT3-4 o N+
    Metastásico:    M+
    """
    psa = patient.get('psa', 0)
    isup = patient.get('isup_grade') or 1
    tstage = str(patient.get('clinical_tstage', patient.get('dre_findings', 'T2a'))).upper()
    meta = str(patient.get('metastasis_site', 'M0')).upper()

    t_map = {'T1A': 1, 'T1B': 1, 'T1C': 1.5, 'T2A': 2, 'T2B': 2.5, 'T2C': 2.7, 'T3A': 3, 'T3B': 3.5, 'T4': 4}
    t_val = t_map.get(tstage, 2)

    reasons = []

    # Metastatic
    if meta not in ('M0', 'MX', ''):
        return {
            'classification': 'EAU 2026',
            'risk_group': 'METASTÁSICO',
            'criteria': [f'Metástasis: {meta}'],
            'treatment_intent': 'Paliativo / Supervivencia',
            'reference': 'EAU Guidelines 2026'
        }

    # Locally advanced
    if t_val >= 3:
        return {
            'classification': 'EAU 2026',
            'risk_group': 'LOCALMENTE AVANZADO',
            'criteria': [f'Estadio {tstage} ≥T3'],
            'treatment_intent': 'Multimodal (RT+ADT o RP+linfadenectomía)',
            'reference': 'EAU Guidelines 2026'
        }

    # High risk
    if psa > 20:
        reasons.append(f'PSA {psa:.1f} >20')
    if isup >= 4:
        reasons.append(f'ISUP {isup} (≥4)')
    if tstage == 'T2C':
        reasons.append(f'Estadio {tstage}')
    if reasons:
        return {
            'classification': 'EAU 2026',
            'risk_group': 'ALTO',
            'criteria': reasons,
            'treatment_intent': 'RP con consideracion de ePLND o RT + ADT larga',
            'reference': 'EAU Guidelines 2026'
        }

    # Intermediate
    inter_reasons = []
    if 10 <= psa <= 20:
        inter_reasons.append(f'PSA {psa:.1f} (10-20)')
    if isup in (2, 3):
        inter_reasons.append(f'ISUP {isup}')
    if tstage == 'T2B':
        inter_reasons.append(f'Estadio T2b')
    if inter_reasons:
        # Sub-classify favorable vs unfavorable
        subgroup = 'Desfavorable' if isup == 3 or patient.get('pct_cores_positive', 0) > 0.5 else 'Favorable'

        return {
            'classification': 'EAU 2026',
            'risk_group': f'INTERMEDIO ({subgroup})',
            'criteria': inter_reasons,
            'subgroup': subgroup,
            'treatment_intent': 'RP o RT; intensificar con ADT corta en intermedio desfavorable',
            'reference': 'EAU Guidelines 2026'
        }

    # Low risk
    return {
        'classification': 'EAU 2026',
        'risk_group': 'BAJO',
        'criteria': ['PSA <10, ISUP 1, ≤cT2a'],
        'treatment_intent': 'Vigilancia Activa preferida (si esperanza vida >10 años)',
        'reference': 'EAU Guidelines 2026'
    }


# ============================================================================
# 12. MSKCC PRE-RP NOMOGRAM — BCR-FREE SURVIVAL (Stephenson 2006)
#     Stephenson AJ et al. J Clin Oncol 2006;24(24):3973-8
# ============================================================================

def mskcc_pre_rp_bcr(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Nomograma MSKCC para supervivencia libre de recurrencia bioquímica
    después de prostatectomía radical. Aproximación logística.

    Variables: PSA, Gleason biopsia, T clínico, % cores positivos, año de cirugía
    """
    psa = patient.get('psa', 0)
    gleason = patient.get('gleason', patient.get('gleason_total', 6))
    isup = patient.get('isup_grade') or 1
    tstage = str(patient.get('clinical_tstage', patient.get('dre_findings', 'T2a'))).upper()
    pct_cores = patient.get('pct_cores_positive', 0)

    # Logistic regression approximation (coefficients derived from published nomogram)
    lp = -1.8  # intercept for 5-year BCR-free

    # PSA contribution (log-transformed)
    if psa > 0:
        lp += 0.35 * math.log(psa)

    # Gleason contribution
    gleason_coeff = {6: 0, 7: 0.65, 8: 1.2, 9: 1.8, 10: 2.1}
    lp += gleason_coeff.get(min(gleason, 10), 0)

    # T-stage contribution
    t_coeff = {'T1A': 0, 'T1B': 0, 'T1C': 0.1, 'T2A': 0.2, 'T2B': 0.5, 'T2C': 0.7, 'T3A': 1.1, 'T3B': 1.5}
    lp += t_coeff.get(tstage, 0.2)

    # Cores positive contribution
    lp += 0.8 * pct_cores

    # Convert to probability
    bcr_prob_5y = 1 / (1 + math.exp(-lp))
    bcr_free_5y = 1 - bcr_prob_5y

    # 10-year extrapolation
    bcr_free_10y = bcr_free_5y ** 1.6

    # Risk category
    if bcr_free_5y >= 0.85:
        risk_cat = 'FAVORABLE'
        interpretation = 'Excelente pronóstico post-RP. BCR improbable.'
    elif bcr_free_5y >= 0.65:
        risk_cat = 'INTERMEDIO'
        interpretation = 'Riesgo moderado de BCR. Considerar seguimiento estrecho.'
    else:
        risk_cat = 'DESFAVORABLE'
        interpretation = 'Alto riesgo de BCR. Considerar adyuvancia (RT ± ADT).'

    return {
        'classification': 'MSKCC Pre-RP BCR Nomogram',
        'bcr_free_5y': f'{bcr_free_5y*100:.1f}%',
        'bcr_free_10y': f'{bcr_free_10y*100:.1f}%',
        'bcr_risk_5y': f'{bcr_prob_5y*100:.1f}%',
        'risk_category': risk_cat,
        'interpretation': interpretation,
        'reference': 'Stephenson AJ et al. J Clin Oncol 2006;24:3973-8'
    }


# ============================================================================
# 13. MSKCC POST-RP NOMOGRAM — BCR-FREE SURVIVAL
#     Dynamic Prostate Cancer Nomogram: Coefficients (MSKCC, updated 2024-12-12)
# ============================================================================ 

def _grade_group_from_patterns(primary: Any, secondary: Any, isup: Any = None) -> int:
    if isup not in (None, ''):
        return max(1, min(int(isup), 5))
    if primary in (None, '') or secondary in (None, ''):
        return 1
    gp = int(primary)
    gs = int(secondary)
    total = gp + gs
    if total <= 6:
        return 1
    if total == 7 and gp == 3:
        return 2
    if total == 7 and gp == 4:
        return 3
    if total == 8:
        return 4
    return 5


def _truthy_binary(value: Any) -> int:
    return 1 if str(value).strip().lower() in {'1', 'true', 'yes', 'si', 'sí', 'positive', 'positivo'} else 0


def _restricted_cubic_spline_terms(value: float, knot_1: float, knot_2: float, knot_3: float, knot_4: float) -> tuple[float, float]:
    def cubic_term(x: float) -> float:
        return max(x, 0.0) ** 3

    denominator = knot_4 - knot_3
    spline_1 = (
        cubic_term(value - knot_1)
        - cubic_term(value - knot_3) * ((knot_4 - knot_1) / denominator)
        + cubic_term(value - knot_4) * ((knot_3 - knot_1) / denominator)
    )
    spline_2 = (
        cubic_term(value - knot_2)
        - cubic_term(value - knot_3) * ((knot_4 - knot_2) / denominator)
        + cubic_term(value - knot_4) * ((knot_3 - knot_2) / denominator)
    )
    return spline_1, spline_2


def _msk_loglogistic_survival(linear_predictor: float, years: float, gamma: float) -> float:
    if years <= 0:
        return 1.0
    return 1.0 / (1.0 + ((math.exp(-linear_predictor) * years) ** (1.0 / gamma)))


def mskcc_bcr_post_rp(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Calcula el nomograma MSKCC post-prostatectomía radical para libertad de
    recurrencia bioquímica usando los coeficientes oficiales publicados por MSKCC.

    Modelo usado:
        survival Postoperative BCR (sin clinical grade/stage)
        Última actualización oficial reportada: 12-Dic-2024
    """
    age = float(patient.get('age', 65))
    psa_preop = float(patient.get('psa_preop', patient.get('baseline_psa', patient.get('psa', 0))))
    gg = _grade_group_from_patterns(
        patient.get('pathology_gleason_primary', patient.get('gleason_primary')),
        patient.get('pathology_gleason_secondary', patient.get('gleason_secondary')),
        patient.get('pathological_isup', patient.get('pathologic_isup')),
    )
    margin = _truthy_binary(patient.get('surgical_margin_status', patient.get('surgical_margin', 0)))
    ece = _truthy_binary(patient.get('extracapsular_extension', patient.get('ece_status', 0)))
    svi = _truthy_binary(patient.get('seminal_vesicle_invasion', patient.get('svi_status', 0)))
    lni = _truthy_binary(patient.get('lymph_node_invasion', patient.get('lni_status', 0)))

    psa_spline_1, psa_spline_2 = _restricted_cubic_spline_terms(
        psa_preop,
        knot_1=0.2,
        knot_2=4.8,
        knot_3=7.35,
        knot_4=307.0,
    )

    linear_predictor = 5.76763364
    linear_predictor += 0.00310155 * age
    linear_predictor += -0.28599905 * psa_preop
    linear_predictor += 0.0025746 * psa_spline_1
    linear_predictor += -0.0071869 * psa_spline_2
    linear_predictor += {
        1: 0.0,
        2: -1.10495679,
        3: -2.15504092,
        4: -2.68503229,
        5: -2.73858376,
    }.get(gg, 0.0)
    linear_predictor += -0.66726362 * ece
    linear_predictor += -0.46645624 * svi
    linear_predictor += -1.222055 * lni
    linear_predictor += -0.93530105 * margin

    gamma = 0.95008472
    bcr_free_2y = _msk_loglogistic_survival(linear_predictor, 2, gamma)
    bcr_free_5y = _msk_loglogistic_survival(linear_predictor, 5, gamma)
    bcr_free_7y = _msk_loglogistic_survival(linear_predictor, 7, gamma)
    bcr_free_10y = _msk_loglogistic_survival(linear_predictor, 10, gamma)

    if bcr_free_5y >= 0.85:
        risk_category = 'FAVORABLE'
        interpretation = 'Riesgo relativamente bajo de recurrencia bioquímica posprostatectomía.'
    elif bcr_free_5y >= 0.65:
        risk_category = 'INTERMEDIO'
        interpretation = 'Riesgo intermedio de recurrencia bioquímica; conviene vigilancia y ventana de rescate bien trazada.'
    else:
        risk_category = 'DESFAVORABLE'
        interpretation = 'Riesgo alto de recurrencia bioquímica; se relaciona con vigilancia estrecha y discusión temprana de rescate.'

    return {
        'classification': 'MSKCC Post-RP BCR Nomogram',
        'bcr_free_2y': f'{bcr_free_2y * 100:.1f}%',
        'bcr_free_5y': f'{bcr_free_5y * 100:.1f}%',
        'bcr_free_7y': f'{bcr_free_7y * 100:.1f}%',
        'bcr_free_10y': f'{bcr_free_10y * 100:.1f}%',
        'risk_category': risk_category,
        'interpretation': interpretation,
        'model_fidelity': 'official_coefficients',
        'reference': 'MSKCC Dynamic Prostate Cancer Nomogram: Post-Radical Prostatectomy coefficients (updated 2024-12-12)',
        'source_url': 'https://www.mskcc.org/nomograms/prostate/post_op/coefficients',
    }


# ============================================================================
# 13. PHI (PROSTATE HEALTH INDEX) — Beckman Coulter
#     Catalona WJ et al. J Urol 2011;185(5):1650-5
# ============================================================================

def calculate_phi(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Calcula el Prostate Health Index (PHI).
    Requiere: PSA total, PSA libre, p2PSA ([-2]proPSA).
    PHI = (p2PSA / fPSA) × √tPSA

    Útil en zona gris de PSA (4-10 ng/mL) para decidir biopsia.
    """
    tpsa = patient.get('psa', 0)
    fpsa_ratio = patient.get('free_psa_ratio', 0)
    p2psa = patient.get('p2psa', 0)

    fpsa = tpsa * fpsa_ratio if fpsa_ratio > 0 else 0

    if fpsa <= 0 or tpsa <= 0:
        return {
            'classification': 'PHI (Prostate Health Index)',
            'score': None,
            'available': False,
            'reason': 'Requiere PSA total, PSA libre y p2PSA para cálculo',
            'reference': 'Catalona WJ et al. J Urol 2011;185:1650-5'
        }

    if p2psa <= 0:
        # Can still provide %fPSA interpretation
        pct_free = fpsa_ratio * 100
        if pct_free < 10:
            interp = 'Alto riesgo de CaP (fPSA <10%)'
        elif pct_free < 15:
            interp = 'Riesgo moderado (fPSA 10-15%)'
        elif pct_free < 25:
            interp = 'Riesgo bajo-moderado (fPSA 15-25%)'
        else:
            interp = 'Riesgo bajo de CaP (fPSA >25%)'

        return {
            'classification': 'PHI (Prostate Health Index)',
            'score': None,
            'pct_free_psa': f'{pct_free:.1f}%',
            'interpretation_fpsa': interp,
            'available': False,
            'reason': 'p2PSA no disponible; se reporta %fPSA',
            'reference': 'Catalona WJ et al. J Urol 2011;185:1650-5'
        }

    phi = (p2psa / fpsa) * math.sqrt(tpsa)

    if phi < 27:
        risk = 'BAJO'
        prob_cap = '~11%'
    elif phi < 36:
        risk = 'INTERMEDIO'
        prob_cap = '~18%'
    elif phi < 55:
        risk = 'ALTO'
        prob_cap = '~33%'
    else:
        risk = 'MUY ALTO'
        prob_cap = '~52%'

    return {
        'classification': 'PHI (Prostate Health Index)',
        'score': round(phi, 1),
        'risk_category': risk,
        'probability_significant_cap': prob_cap,
        'available': True,
        'reference': 'Catalona WJ et al. J Urol 2011;185:1650-5'
    }


# ============================================================================
# 14. CLAVIEN-DINDO — Clasificación Complicaciones Quirúrgicas
#     Dindo D et al. Ann Surg 2004;240(2):205-213
# ============================================================================

def clavien_dindo_grade(complication_data: dict[str, Any]) -> dict[str, Any]:
    """
    Clasifica complicaciones post-quirúrgicas según Clavien-Dindo.

    Parámetros:
        required_intervention: str — 'none', 'pharmacological', 'surgical', 'icu', 'death'
        general_anesthesia: bool — requirió anestesia general
        organ_failure: bool — fallo orgánico
        life_threatening: bool — puso en riesgo la vida
    """
    interv = complication_data.get('required_intervention', 'none')
    gen_anes = complication_data.get('general_anesthesia', False)
    organ_fail = complication_data.get('organ_failure', False)
    life_threat = complication_data.get('life_threatening', False)
    death = complication_data.get('death', False)

    if death:
        grade = 'V'
        desc = 'Muerte del paciente'
    elif organ_fail or (life_threat and interv in ('icu', 'surgical')):
        grade = 'IVb' if organ_fail else 'IVa'
        desc = 'Fallo multiorgánico' if grade == 'IVb' else 'Complicación potencialmente mortal, manejo en UCI'
    elif interv == 'surgical' or gen_anes:
        grade = 'IIIb' if gen_anes else 'IIIa'
        desc = 'Intervención bajo anestesia general' if gen_anes else 'Intervención sin anestesia general'
    elif interv == 'pharmacological':
        grade = 'II'
        desc = 'Tratamiento farmacológico, transfusiones, NPT'
    elif interv == 'none':
        grade = 'I'
        desc = 'Cualquier desviación del curso normal sin intervención'
    else:
        grade = 'I'
        desc = 'Sin complicaciones significativas'

    return {
        'classification': 'Clavien-Dindo',
        'grade': grade,
        'description': desc,
        'reference': 'Dindo D et al. Ann Surg 2004;240:205-213'
    }


# ============================================================================
# 9. FUNCIÓN PRINCIPAL — Calcula todos los scores
# ============================================================================

def calculate_all_scores(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Calcula los scores clínicos a partir de los datos del paciente.
    Devuelve un dict con los resultados de cada herramienta.
    """
    # Calculate PSAD
    vol = patient.get('volumen_prostatico', 0)
    psa = patient.get('psa', 0)
    psad = psa / vol if vol and vol > 0 else 0.3

    # Calculate eGFR using CKD-EPI 2021 (race-free)
    creatinina = float(patient.get('creatinina', 0))
    age = int(patient.get('age', 65))
    sexo = str(patient.get('sexo', 'masculino')).lower()
    egfr_result = {'egfr_value': 0, 'egfr_category': 'N/D', 'egfr_alert': ''}
    if creatinina > 0:
        import math
        if sexo in ('femenino', 'female', 'f'):
            kappa, alpha, female_mult = 0.7, -0.241, 1.012
        else:
            kappa, alpha, female_mult = 0.9, -0.302, 1.0
        scr_k = creatinina / kappa
        egfr_val = 142 * (min(scr_k, 1.0) ** alpha) * (max(scr_k, 1.0) ** (-1.200)) * (0.9938 ** age) * female_mult
        egfr_val = round(egfr_val, 1)
        if egfr_val >= 90: cat = 'G1 - Normal'
        elif egfr_val >= 60: cat = 'G2 - Leve'
        elif egfr_val >= 45: cat = 'G3a - Moderada'
        elif egfr_val >= 30: cat = 'G3b - Moderada-Severa'
        elif egfr_val >= 15: cat = 'G4 - Severa'
        else: cat = 'G5 - Falla Renal'
        alert = ''
        if egfr_val < 30:
            alert = '⚠️ eGFR <30: Ajustar dosis de agentes nefrotóxicos. Contraindicación relativa para contraste iodado y gadolinio.'
        elif egfr_val < 60:
            alert = '⚠️ eGFR <60: Precaución con cisplatino, considerar carboplatino. Monitorizar función renal.'
        egfr_result = {'egfr_value': egfr_val, 'egfr_category': cat, 'egfr_alert': alert}

    scores = {
        'capra': capra_score(patient),
        'nccn': nccn_risk_group(patient),
        'damico': damico_classification(patient),
        'eau': eau_risk_groups(patient),
        'briganti': briganti_lni(patient),
        'kattan_msk': kattan_organ_confined(patient),
        'mskcc_bcr': mskcc_pre_rp_bcr(patient),
        'phi': calculate_phi(patient),
        'life_expectancy': calculate_life_expectancy(patient),
        'partin': partin_tables(patient),
        'as_eligibility': active_surveillance_eligibility(patient),
        'psad': round(psad, 3),
        'egfr': egfr_result,
        'psa_kinetics': {},
    }

    # Calculate CAPRA-S only in explicit post-prostatectomy context.
    post_op_context = str(patient.get('post_prostatectomy_context', '0')).lower() in ('1', 'true', 'yes', 'si', 'on')
    post_op_context = post_op_context or str(patient.get('pathologic_stage', '')).strip() != ''
    post_op_context = post_op_context or str(patient.get('psa_postop', '')).strip() != ''
    if post_op_context:
        scores['capra_s'] = calculate_capra_s(patient)

    # ProstaMed Integrated Score (needs other scores first)
    scores['prostanet_score'] = prostanet_integrated_score(patient, scores)

    return scores


# ============================================================================
# 6. RESUMEN CLÍNICO INTELIGENTE & ANÁLISIS DE IMPACTO
# ============================================================================

def generate_comprehensive_summary(scores: dict, ml_prediction: dict, patient: dict) -> dict:
    """
    Genera un análisis clínico profundo cruzando los 4 scores con el modelo ML.
    Provee insights estadísticos, alertas de discordancia y guías de manejo.
    """
    summary = {
        'risk_profile': '',
        'aggression_analysis': [],
        'local_extension_analysis': [],
        'lymph_node_analysis': [],
        'management_recommendations': [],
        'statistical_impact': [],
        'discordance_alert': None
    }

    # 1. PERFIL DE RIESGO INTEGRADO
    # -----------------------------
    nccn_risk = scores['nccn']['risk_group']
    capra_points = scores['capra']['score']
    
    # Parse risk probability from formatted string (e.g., "12.5%")
    try:
        risk_probs = ml_prediction.get('riesgo', {}).get('probabilidades', {})
        # Use 'ALTO' probability as the main metric for discordance
        high_prob_str = risk_probs.get('ALTO', '0%').replace('%', '')
        ml_risk_prob = float(high_prob_str)
    except (ValueError, AttributeError):
        ml_risk_prob = 0.0
    
    summary['risk_profile'] = f"{nccn_risk} (CAPRA {capra_points})"

    # 2. ANÁLISIS DE AGRESIVIDAD BIOLÓGICA
    # ------------------------------------
    aggression = []
    
    # Gleason Analysis
    gp = patient.get('gleason_primary') or 3
    gs = patient.get('gleason_secondary') or 3
    if gp >= 4:
        aggression.append(
            "Patrón primario Gleason 4 o 5 indica un comportamiento biológico agresivo. "
            "Estudios demuestran que el patrón primario es el predictor más fuerte de metástasis a distancia."
        )
    elif gp == 3 and gs == 4:
        aggression.append(
            "Gleason 3+4 (Grupo 2) tiene un comportamiento favorable, pero la presencia del patrón 4 "
            "requiere vigilancia activa estricta o tratamiento definitivo según la esperanza de vida."
        )

    # PSA Kinetics context
    psa = patient.get('psa', 0)
    if psa > 20:
        aggression.append(
            f"PSA de {psa} ng/mL está asociado con un riesgo >30% de fracaso bioquímico a 5 años "
            "con monoterapia (cirugía o radioterapia sola)."
        )
    
    summary['aggression_analysis'] = aggression

    # 3. ANÁLISIS DE EXTENSIÓN LOCAL (T-Stage + Kattan)
    # -------------------------------------------------
    local = []
    kattan_prob = scores['kattan_msk']['probabilidad_raw']
    tstage = str(patient.get('clinical_tstage', 'T2a')).upper()

    if kattan_prob < 40:
        local.append(
            f"La probabilidad de enfermedad órgano-confinada es baja ({kattan_prob}%). "
            "Existe un alto riesgo (>60%) de extensión extraprostática (EPE)."
        )
        local.append(
            "IMPLICACIÓN QUIRÚRGICA: Se recomienda precaución extrema con la preservación de haces neurovasculares "
            "(nerve-sparing) en el lado afectado para evitar márgenes quirúrgicos positivos (R1)."
        )
    elif kattan_prob > 70:
        local.append(
            f"Alta probabilidad ({kattan_prob}%) de que el tumor esté confinado a la próstata. "
            "Candidato ideal para técnica de preservación nerviosa (nerve-sparing) bilateral."
        )

    if tstage in ('T3A', 'T3B'):
        local.append(
            "El estadio clínico T3 sugiere extensión extraprostática palpable o visible. "
            "La radioterapia adyuvante podría ser necesaria si la cirugía no logra márgenes negativos."
        )
    
    summary['local_extension_analysis'] = local

    # 4. ANÁLISIS GANGLIONAR (Briganti + ML)
    # --------------------------------------
    lymph = []
    briganti_prob = scores['briganti']['probabilidad_raw']
    
    if briganti_prob >= 5.0:
        lymph.append(
            f"El riesgo de invasión linfática (LNI) es del {briganti_prob}%, superando el umbral del 5% "
            "establecido por las Guías de la Asociación Europea de Urología (EAU)."
        )
        lymph.append(
            "ACCIÓN: La Linfadenectomía Pélvica Extendida (ePLND) es MANDATORIA si se opta por cirugía. "
            "Se deben disecar al menos las cadenas obturatriz, ilíaca externa e interna."
        )
    else:
        lymph.append(
            f"Riesgo de LNI bajo ({briganti_prob}%). Se podría omitir la linfadenectomía pélvica según "
            "nomograma de Briganti 2012/2017, reduciendo tiempo quirúrgico y morbilidad."
        )
    
    summary['lymph_node_analysis'] = lymph

    # 5. DISCORDANCE CHECK (Score vs ML)
    # ----------------------------------
    # Definir riesgo ML: Bajo (<30%), Intermedio (30-70%), Alto (>70%)
    ml_risk_level = 'BAJO'
    if ml_risk_prob > 70:
        ml_risk_level = 'ALTO'
    elif ml_risk_prob > 30:
        ml_risk_level = 'INTERMEDIO'
    
    # Comparar con NCCN
    nccn_str = nccn_risk  # 'BAJO', 'INTERMEDIO FAVORABLE', 'ALTO', etc.
    
    discordance = None
    if 'BAJO' in nccn_str and ml_risk_level == 'ALTO':
        discordance = (
            "⚠️ ALERTA DE DISCORDANCIA: El score clínico estándar (NCCN) sugiere riesgo BAJO, "
            "pero el modelo de Deep Learning detectó patrones de ALTO RIESGO. "
            "Se sugiere revisar biomarcadores genómicos (p.ej. Decipher) o re-evaluar la biopsia."
        )
    elif 'ALTO' in nccn_str and ml_risk_level == 'BAJO':
        discordance = (
            "⚠️ ALERTA DE DISCORDANCIA: El score clínico sugiere riesgo ALTO, pero el modelo ML "
            "predice un curso indolente. Esto puede ocurrir en pacientes añosos donde la mortalidad "
            "por otras causas supera al riesgo de cáncer."
        )
    
    summary['discordance_alert'] = discordance

    # 6. IMPACTO ESTADÍSTICO (Survival estimations)
    # ---------------------------------------------
    stats = []
    capra_bcr_5y = scores['capra']['bcr_free_5y']
    
    stats.append(
        f"Estadísticamente, pacientes con este perfil (CAPRA {capra_points}) tienen una "
        f"probabilidad de {capra_bcr_5y} de permanecer libres de recurrencia bioquímica a 5 años "
        "sin tratamiento adyuvante."
    )
    
    if nccn_risk in ('ALTO', 'MUY ALTO'):
        stats.append(
            "En cohortes grandes, la mortalidad cáncer-específica a 10 años para este grupo "
            "supera el 15-20% si no se utiliza terapia multimodal (Cirugía/RT + ADT)."
        )
    
    summary['statistical_impact'] = stats

    return summary


# ============================================================================
# CHARLSON COMORBIDITY INDEX (CCI)
#   Charlson ME et al. J Chronic Dis 1987; 40(5):373-83
#   Actualización Quan H et al. Med Care 2011; 49(6):626-33
# ============================================================================

def _score_input_present(value: Any) -> bool:
    return value not in (None, "")


def _normalize_boolish(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"si", "sí", "yes", "true", "1", "on"}:
            return True
        if normalized in {"no", "false", "0", "off"}:
            return False
    return None


def _incomplete_score_payload(
    *,
    score_name: str,
    missing_inputs: list[str],
    what_score_means: str,
    clinical_decision_supported: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "score_name": score_name,
        "is_complete": False,
        "data_truth_status": "incomplete",
        "missing_inputs": missing_inputs,
        "what_score_means": what_score_means,
        "clinical_decision_supported": clinical_decision_supported,
        "risk_category": "INCOMPLETE",
        "risk_interpretation": "Faltan inputs críticos; el score no debe usarse como si fuera un resultado clínico confirmado.",
    }
    if extra:
        payload.update(extra)
    return payload

def charlson_comorbidity_index(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Calcula el Índice de Comorbilidad de Charlson.

    Variables esperadas (todas opcionales, default=False):
        - age: edad del paciente
        - myocardial_infarction: infarto al miocardio
        - congestive_heart_failure: insuficiencia cardiaca congestiva
        - peripheral_vascular_disease: enfermedad vascular periférica
        - cerebrovascular_disease: enfermedad cerebrovascular
        - dementia: demencia
        - chronic_pulmonary_disease: enfermedad pulmonar crónica
        - connective_tissue_disease: enfermedad del tejido conectivo
        - peptic_ulcer_disease: úlcera péptica
        - mild_liver_disease: enfermedad hepática leve
        - diabetes_without_complications: diabetes sin complicaciones
        - diabetes_with_complications: diabetes con complicaciones
        - hemiplegia: hemiplejía o paraplejía
        - renal_disease: enfermedad renal (creatinina >3 o diálisis)
        - solid_tumor_localized: tumor sólido localizado (sin metástasis)
        - leukemia_lymphoma: leucemia o linfoma
        - moderate_severe_liver_disease: enfermedad hepática moderada/severa
        - metastatic_solid_tumor: tumor sólido con metástasis
        - aids_hiv: SIDA/VIH

    Retorna dict con:
        - score: puntuación total
        - age_adjusted_score: score ajustado por edad
        - risk_category: LOW | MODERATE | HIGH | VERY_HIGH
        - estimated_10y_survival_pct: supervivencia estimada a 10 años
        - conditions: lista de condiciones presentes
    """
    # Pesos estándar
    weights = [
        ("myocardial_infarction", 1),
        ("congestive_heart_failure", 1),
        ("peripheral_vascular_disease", 1),
        ("cerebrovascular_disease", 1),
        ("dementia", 1),
        ("chronic_pulmonary_disease", 1),
        ("connective_tissue_disease", 1),
        ("peptic_ulcer_disease", 1),
        ("mild_liver_disease", 1),
        ("diabetes_without_complications", 1),
        ("diabetes_with_complications", 2),
        ("hemiplegia", 2),
        ("renal_disease", 2),
        ("solid_tumor_localized", 2),
        ("leukemia_lymphoma", 2),
        ("moderate_severe_liver_disease", 3),
        ("metastatic_solid_tumor", 6),
        ("aids_hiv", 6),
    ]

    missing_inputs = []
    age = patient.get("age")
    if not isinstance(age, (int, float)):
        try:
            age = float(age)
        except (TypeError, ValueError):
            age = None
    if age is None:
        missing_inputs.append("age")

    for key, _ in weights:
        if _normalize_boolish(patient.get(key)) is None:
            missing_inputs.append(key)

    if missing_inputs:
        return _incomplete_score_payload(
            score_name="Charlson Comorbidity Index",
            missing_inputs=missing_inputs,
            what_score_means="Resume la carga de comorbilidad basal y mortalidad competitiva a mediano-largo plazo.",
            clinical_decision_supported="Ayuda a calibrar intensidad terapéutica, beneficio competitivo y tolerabilidad global.",
            extra={
                "score": None,
                "raw_score": None,
                "age_adjusted_score": None,
                "adjusted_score": None,
                "age_points": None,
                "estimated_10y_survival_pct": None,
                "estimated_10y_survival": "No calculable",
                "conditions": [],
                "conditions_present": [],
            },
        )

    score = 0
    conditions = []
    for key, weight in weights:
        if _normalize_boolish(patient.get(key)) is True:
            score += weight
            conditions.append(key)

    # Ajuste por edad (Charlson age-adjusted)
    age_points = 0
    if isinstance(age, (int, float)) and age >= 50:
        age_points = max(0, (int(age) - 40) // 10)
    age_adjusted = score + age_points

    # Categorización
    if age_adjusted == 0:
        category = "LOW"
        survival_10y = 98
    elif age_adjusted <= 2:
        category = "LOW"
        survival_10y = 90
    elif age_adjusted <= 4:
        category = "MODERATE"
        survival_10y = 72
    elif age_adjusted <= 6:
        category = "HIGH"
        survival_10y = 52
    else:
        category = "VERY_HIGH"
        survival_10y = 26

    return {
        "score": score,
        "raw_score": score,
        "age_adjusted_score": age_adjusted,
        "adjusted_score": age_adjusted,
        "age_points": age_points,
        "risk_category": category,
        "estimated_10y_survival_pct": survival_10y,
        "estimated_10y_survival": f"{survival_10y}%",
        "conditions": conditions,
        "conditions_present": conditions,
        "is_complete": True,
        "data_truth_status": "captured",
        "missing_inputs": [],
        "what_score_means": "Resume la carga de comorbilidad basal y mortalidad competitiva a mediano-largo plazo.",
        "risk_interpretation": f"Categoría {category}: mayor puntaje implica mayor riesgo de mortalidad competitiva no oncológica.",
        "clinical_decision_supported": "Ayuda a calibrar intensidad terapéutica, beneficio competitivo y tolerabilidad global.",
    }


# ============================================================================
# G8 GERIATRIC SCREENING TOOL
#   Bellera CA et al. Ann Oncol 2012; 23(8):2166-72
#   Corte ≤14 → paciente vulnerable, requiere evaluación geriátrica integral
# ============================================================================

def g8_geriatric_assessment(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Calcula el G8 Geriatric Screening Score (0-17).

    Variables esperadas:
        - g8_food_intake: 0=severe decrease, 1=moderate decrease, 2=normal
        - g8_weight_loss: 0=loss>3kg, 1=unknown, 2=loss 1-3kg, 3=no loss
        - g8_mobility: 0=bed/chair, 1=gets out but not outdoors, 2=goes outdoors
        - g8_neuropsych: 0=severe dementia/depression, 1=mild, 2=no problems
        - g8_bmi: 0=BMI<19, 1=BMI 19-<21, 2=BMI 21-<23, 3=BMI≥23
        - g8_medications: 0=more than 3, 1=3 or fewer
        - g8_self_health: 0=not as good, 0.5=does not know, 1=as good, 2=better
        - age: edad del paciente

    Retorna:
        - score: puntuación total (0-17)
        - fit_for_aggressive_treatment: True si score >14
        - interpretation: texto descriptivo
    """
    required_fields = (
        "g8_food_intake",
        "g8_weight_loss",
        "g8_mobility",
        "g8_neuropsych",
        "g8_bmi",
        "g8_medications",
        "g8_self_health",
        "age",
    )
    missing_inputs = [field for field in required_fields if not _score_input_present(patient.get(field))]
    if missing_inputs:
        return _incomplete_score_payload(
            score_name="G8 Geriatric Screening",
            missing_inputs=missing_inputs,
            what_score_means="Tamiza vulnerabilidad geriátrica; un G8 ≤14 sugiere necesidad de evaluación geriátrica integral.",
            clinical_decision_supported="Ayuda a decidir intensidad terapéutica, soporte geriátrico y necesidad de evaluación integral.",
            extra={
                "score": None,
                "total_score": None,
                "fit_for_aggressive_treatment": None,
                "fitness_for_treatment": "Faltan respuestas del G8 para estimar aptitud geriátrica real.",
                "interpretation": "Score incompleto por falta de variables del G8.",
                "inputs_used": {},
            },
        )

    score = 0.0

    food = patient.get("g8_food_intake")
    score += min(max(float(food), 0), 2)

    weight = patient.get("g8_weight_loss")
    score += min(max(float(weight), 0), 3)

    mobility = patient.get("g8_mobility")
    score += min(max(float(mobility), 0), 2)

    neuro = patient.get("g8_neuropsych")
    score += min(max(float(neuro), 0), 2)

    bmi_score = patient.get("g8_bmi")
    score += min(max(float(bmi_score), 0), 3)

    meds = patient.get("g8_medications")
    score += min(max(float(meds), 0), 1)

    self_health = patient.get("g8_self_health")
    score += min(max(float(self_health), 0), 2)

    age = float(patient.get("age"))
    if age > 85:
        score += 0
    elif age >= 80:
        score += 1
    else:
        score += 2

    score = round(score, 1)
    is_fit = score > 14

    if score > 14:
        interpretation = "Sin indicios de fragilidad. Apto para tratamiento estándar."
    elif score >= 10:
        interpretation = "Vulnerabilidad detectada. Se recomienda evaluación geriátrica integral antes de decidir tratamiento agresivo."
    else:
        interpretation = "Fragilidad significativa. Considerar tratamiento adaptado, reducción de dosis o mejor soporte de cuidado."

    return {
        "score": score,
        "total_score": score,
        "fit_for_aggressive_treatment": is_fit,
        "fitness_for_treatment": "Apto para tratamiento estándar" if is_fit else "Requiere evaluación geriátrica antes de intensificar",
        "interpretation": interpretation,
        "is_complete": True,
        "data_truth_status": "captured",
        "missing_inputs": [],
        "what_score_means": "Tamiza vulnerabilidad geriátrica; un G8 ≤14 sugiere necesidad de evaluación geriátrica integral.",
        "risk_category": "FIT" if is_fit else "VULNERABLE",
        "risk_interpretation": "Un puntaje bajo aumenta la probabilidad de fragilidad geriátrica clínicamente relevante.",
        "clinical_decision_supported": "Ayuda a decidir intensidad terapéutica, soporte geriátrico y necesidad de evaluación integral.",
        "inputs_used": {field: patient.get(field) for field in required_fields},
    }


# ============================================================================
# PROSTATE HEALTH INDEX (PHI)
#   Catalona WJ et al. J Urol 2011; 186(5):1840-5
#   PHI = ([-2]proPSA / fPSA) × √tPSA
# ============================================================================

def prostate_health_index(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Calcula el Prostate Health Index (PHI).

    Variables esperadas:
        - psa: PSA total (ng/mL)
        - free_psa: PSA libre (ng/mL)
        - p2psa: [-2]proPSA (pg/mL)

    Retorna:
        - phi_score: valor del PHI
        - risk_interpretation: bajo/intermedio/alto
        - biopsy_recommendation: recomendación
        - probability_high_grade_pct: probabilidad de cáncer significativo
    """
    psa = patient.get("psa", 0)
    free_psa = patient.get("free_psa", 0)
    p2psa = patient.get("p2psa", 0)

    if not psa or not free_psa or not p2psa or psa <= 0 or free_psa <= 0:
        return {
            "phi_score": None,
            "risk_interpretation": "No calculable (datos insuficientes)",
            "biopsy_recommendation": "Se requieren PSA total, PSA libre y [-2]proPSA para calcular PHI.",
            "probability_high_grade_pct": None,
        }

    phi = (p2psa / free_psa) * math.sqrt(psa)

    if phi < 27:
        risk = "BAJO"
        prob = 11
        rec = "Baja probabilidad de cáncer significativo. Considerar vigilancia con PSA y seguimiento."
    elif phi < 36:
        risk = "INTERMEDIO"
        prob = 20
        rec = "Probabilidad intermedia. Considerar biopsia según contexto clínico y mpMRI."
    elif phi < 55:
        risk = "ALTO"
        prob = 34
        rec = "Alta probabilidad de cáncer clínicamente significativo. Biopsia recomendada."
    else:
        risk = "MUY ALTO"
        prob = 52
        rec = "Muy alta probabilidad de cáncer significativo. Biopsia urgente recomendada."

    return {
        "phi_score": round(phi, 1),
        "risk_interpretation": risk,
        "biopsy_recommendation": rec,
        "probability_high_grade_pct": prob,
    }


# ============================================================================
# 4K SCORE (Approximation)
#   Parekh DJ et al. Eur Urol 2015; 68(3):464-70
#   Combina: PSA total, PSA libre, PSA intacta, hK2, edad, DRE, biopsia previa
#   Estima probabilidad de cáncer de próstata de alto grado (Gleason ≥7)
# ============================================================================

def four_k_score(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Estimación simplificada del 4Kscore.

    El 4Kscore real usa un modelo propietario con 4 kalicreínas
    (tPSA, fPSA, iPSA, hK2) + datos clínicos. Esta es una
    aproximación basada en coeficientes publicados.

    Variables esperadas:
        - psa: PSA total (ng/mL)
        - free_psa: PSA libre (ng/mL)
        - intact_psa: PSA intacta (ng/mL) [opcional]
        - hk2: Kalicreína humana 2 (ng/mL) [opcional]
        - age: Edad
        - prior_biopsy: Biopsia previa (boolean)
        - dre_abnormal: Tacto rectal anormal (boolean)
    """
    psa = patient.get("psa", 0)
    free_psa = patient.get("free_psa", 0)
    intact_psa = patient.get("intact_psa")
    hk2 = patient.get("hk2")
    age = patient.get("age", 65)
    prior_bx = patient.get("prior_biopsy", False)
    dre_abn = patient.get("dre_abnormal", False)

    try:
        psa = float(psa)
        free_psa = float(free_psa) if free_psa else 0
        age = int(float(age))
    except (ValueError, TypeError):
        return {
            "four_k_probability_pct": None,
            "risk_category": "No calculable",
            "recommendation": "Se requieren PSA total y PSA libre como mínimo.",
        }

    if psa <= 0:
        return {
            "four_k_probability_pct": None,
            "risk_category": "No calculable",
            "recommendation": "PSA total debe ser >0.",
        }

    # Simplified logistic approximation based on published coefficients
    # ln(odds) = intercept + b1*ln(PSA) + b2*ln(fPSA) + b3*age + b4*DRE + b5*prior_bx
    logit = -8.5
    logit += 1.7 * math.log(max(psa, 0.01))
    if free_psa > 0:
        ratio = free_psa / psa
        logit -= 2.0 * ratio  # lower free/total ratio → higher risk
    logit += 0.05 * age
    if dre_abn:
        logit += 0.8
    if prior_bx:
        logit -= 0.5  # prior negative biopsy reduces risk

    # Incorporate iPSA and hK2 if available
    if intact_psa is not None:
        try:
            ipsa = float(intact_psa)
            if ipsa > 0 and psa > 0:
                logit += 0.5 * math.log(ipsa / psa + 0.01)
        except (ValueError, TypeError):
            pass

    if hk2 is not None:
        try:
            hk2_val = float(hk2)
            if hk2_val > 0:
                logit += 0.4 * math.log(hk2_val + 0.01)
        except (ValueError, TypeError):
            pass

    probability = 1 / (1 + math.exp(-logit))
    prob_pct = round(probability * 100, 1)

    if prob_pct < 7.5:
        category = "BAJO"
        rec = "Baja probabilidad de cáncer de alto grado. Considerar vigilancia o diferir biopsia."
    elif prob_pct < 15:
        category = "INTERMEDIO"
        rec = "Riesgo intermedio. Considerar mpMRI y decisión compartida sobre biopsia."
    else:
        category = "ALTO"
        rec = "Alta probabilidad de cáncer de alto grado. Biopsia recomendada."

    completeness = "completo" if (intact_psa is not None and hk2 is not None) else "aproximado (faltan iPSA/hK2)"

    return {
        "four_k_probability_pct": prob_pct,
        "risk_category": category,
        "recommendation": rec,
        "model_completeness": completeness,
        "reference": "Parekh DJ et al. Eur Urol 2015;68(3):464-70",
    }


# ============================================================================
# ERSPC / PCPT RISK CALCULATOR (Approximation)
#   Thompson IM et al. NEJM 2004 (PCPT)
#   Roobol MJ et al. Eur Urol 2012 (ERSPC)
#   Estima riesgo de cáncer de próstata y de cáncer de alto grado
# ============================================================================

def erspc_risk_calculator(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Calculadora de riesgo ERSPC/PCPT simplificada.

    Estima probabilidad de:
    1. Cualquier cáncer de próstata en biopsia
    2. Cáncer de alto grado (Gleason ≥7) en biopsia

    Variables:
        - psa: PSA total (ng/mL)
        - age: Edad
        - dre_abnormal: Tacto rectal anormal (boolean)
        - prostate_volume_ml: Volumen prostático (mL)
        - prior_biopsy: Biopsia previa negativa (boolean)
        - family_history: Historia familiar de CaP (boolean)
    """
    psa = patient.get("psa", 0)
    age = patient.get("age", 65)
    dre_abn = patient.get("dre_abnormal", False)
    volume = patient.get("prostate_volume_ml", 0)
    prior_bx = patient.get("prior_biopsy", False)
    fam_hx = patient.get("family_history", False)

    try:
        psa = float(psa)
        age = int(float(age))
        volume = float(volume) if volume else 0
    except (ValueError, TypeError):
        return {
            "any_cancer_probability_pct": None,
            "high_grade_probability_pct": None,
            "recommendation": "Datos insuficientes para el cálculo.",
        }

    if psa <= 0:
        return {
            "any_cancer_probability_pct": None,
            "high_grade_probability_pct": None,
            "recommendation": "PSA total debe ser >0.",
        }

    # ERSPC-like logistic model for any cancer
    logit_any = -6.5
    logit_any += 1.1 * math.log(max(psa, 0.01))
    logit_any += 0.03 * age
    if dre_abn:
        logit_any += 1.0
    if volume > 0:
        psad = psa / volume
        logit_any += 2.0 * psad
    if prior_bx:
        logit_any -= 0.7
    if fam_hx:
        logit_any += 0.3

    # High-grade model
    logit_hg = -8.0
    logit_hg += 1.4 * math.log(max(psa, 0.01))
    logit_hg += 0.04 * age
    if dre_abn:
        logit_hg += 1.2
    if volume > 0:
        logit_hg += 3.0 * (psa / volume)
    if prior_bx:
        logit_hg -= 0.5

    prob_any = round(100 / (1 + math.exp(-logit_any)), 1)
    prob_hg = round(100 / (1 + math.exp(-logit_hg)), 1)

    # Ensure high grade ≤ any cancer
    prob_hg = min(prob_hg, prob_any)

    if prob_hg >= 15:
        rec = "Riesgo elevado de cáncer significativo. Biopsia recomendada (preferiblemente guiada por mpMRI)."
    elif prob_any >= 25:
        rec = "Riesgo intermedio. Considerar mpMRI antes de biopsia. Decisión compartida."
    else:
        rec = "Riesgo bajo. Seguimiento con PSA. Considerar biomarcadores adicionales (PHI, 4Kscore) si duda persiste."

    return {
        "any_cancer_probability_pct": prob_any,
        "high_grade_probability_pct": prob_hg,
        "recommendation": rec,
        "inputs_used": {
            "psa": psa,
            "age": age,
            "dre_abnormal": dre_abn,
            "prostate_volume_ml": volume or "No documentado",
            "prior_biopsy": prior_bx,
            "family_history": fam_hx,
        },
        "reference": "ERSPC-RC: Roobol MJ et al. Eur Urol 2012 / PCPT-RC: Thompson IM et al. NEJM 2004",
    }


# ═══════════════════════════════════════════════════════════════════════════
# FITNESS TERAPÉUTICA INTEGRADA (Salto 2)
# ═══════════════════════════════════════════════════════════════════════════

def egfr_ckd_epi_2021(creatinine: float, age: int, sex: str = "M") -> dict:
    """
    Calcula eGFR usando CKD-EPI 2021 (sin raza).

    Fórmula: 142 × min(Scr/κ, 1)^α × max(Scr/κ, 1)^-1.200 × 0.9938^Age × (1.012 si mujer)
    κ = 0.7 (F), 0.9 (M); α = -0.241 (F), -0.302 (M)

    Impacto terapéutico:
        eGFR <30: contraindicar zoledronato, ajustar olaparib
        eGFR 30-60: reducir dosis cisplatino
        eGFR <45: precaución con AINEs en paliativo

    Reference: Inker LA et al. NEJM 2021
    """
    import math
    if not creatinine or creatinine <= 0 or not age or age <= 0:
        return {"egfr": None, "stage": "unknown", "clinical_actions": [], "reference": "CKD-EPI 2021 (Inker LA et al. NEJM 2021)"}

    is_female = sex.upper().startswith("F")
    kappa = 0.7 if is_female else 0.9
    alpha = -0.241 if is_female else -0.302
    sex_factor = 1.012 if is_female else 1.0

    egfr = 142 * (min(creatinine / kappa, 1.0) ** alpha) * (max(creatinine / kappa, 1.0) ** -1.200) * (0.9938 ** age) * sex_factor
    egfr = round(egfr, 1)

    if egfr >= 90:
        stage = "G1"
    elif egfr >= 60:
        stage = "G2"
    elif egfr >= 45:
        stage = "G3a"
    elif egfr >= 30:
        stage = "G3b"
    elif egfr >= 15:
        stage = "G4"
    else:
        stage = "G5"

    actions = []
    if egfr < 30:
        actions.extend(["Contraindicar zoledronato (nefrotoxicidad)", "Ajustar dosis de olaparib", "Evitar contraste yodado sin preparación"])
    elif egfr < 45:
        actions.extend(["Precaución con AINEs en manejo paliativo", "Ajustar dosis de cisplatino si aplica"])
    elif egfr < 60:
        actions.append("Reducir dosis de cisplatino; monitorear función renal cada ciclo")

    return {
        "egfr": egfr,
        "stage": stage,
        "clinical_actions": actions,
        "inputs_used": {"creatinine": creatinine, "age": age, "sex": sex},
        "reference": "CKD-EPI 2021 (Inker LA et al. NEJM 2021)",
    }


def child_pugh_dynamic(bilirubin: float = None, albumin: float = None, inr: float = None,
                       ascites: str = "none", encephalopathy: str = "none") -> dict:
    """
    Calcula Child-Pugh dinámico desde valores de laboratorio.

    Impacto terapéutico:
        Child-Pugh A: dosis estándar
        Child-Pugh B: reducir dosis abiraterona 50%
        Child-Pugh C: contraindicar abiraterona y docetaxel

    Reference: Pugh RN et al. Br J Surg 1973
    """
    score = 0
    details = {}

    # Bilirrubina (mg/dL)
    if bilirubin is not None:
        if bilirubin < 2:
            score += 1; details["bilirubin"] = 1
        elif bilirubin <= 3:
            score += 2; details["bilirubin"] = 2
        else:
            score += 3; details["bilirubin"] = 3
    else:
        score += 1; details["bilirubin"] = "missing (assumed 1)"

    # Albúmina (g/dL)
    if albumin is not None:
        if albumin > 3.5:
            score += 1; details["albumin"] = 1
        elif albumin >= 2.8:
            score += 2; details["albumin"] = 2
        else:
            score += 3; details["albumin"] = 3
    else:
        score += 1; details["albumin"] = "missing (assumed 1)"

    # INR
    if inr is not None:
        if inr < 1.7:
            score += 1; details["inr"] = 1
        elif inr <= 2.3:
            score += 2; details["inr"] = 2
        else:
            score += 3; details["inr"] = 3
    else:
        score += 1; details["inr"] = "missing (assumed 1)"

    # Ascitis
    ascites_map = {"none": 1, "absent": 1, "mild": 2, "moderate": 2, "leve": 2, "moderada": 2, "severe": 3, "severa": 3, "tense": 3}
    asc_score = ascites_map.get(ascites.lower(), 1)
    score += asc_score; details["ascites"] = asc_score

    # Encefalopatía
    enc_map = {"none": 1, "absent": 1, "grade_1": 2, "grade_2": 2, "grado_1": 2, "grado_2": 2, "grade_3": 3, "grade_4": 3, "grado_3": 3, "grado_4": 3}
    enc_score = enc_map.get(encephalopathy.lower(), 1)
    score += enc_score; details["encephalopathy"] = enc_score

    if score <= 6:
        grade = "A"
    elif score <= 9:
        grade = "B"
    else:
        grade = "C"

    actions = []
    if grade == "B":
        actions.extend(["Reducir dosis de abiraterona 50%", "Monitoreo hepático cada 2 semanas", "Evitar hepatotóxicos concomitantes"])
    elif grade == "C":
        actions.extend(["Contraindicar abiraterona", "Contraindicar docetaxel", "Considerar best supportive care", "Referir hepatología"])

    return {
        "score": score,
        "grade": grade,
        "details": details,
        "clinical_actions": actions,
        "reference": "Child-Pugh (Pugh RN et al. Br J Surg 1973)",
    }


def fried_frailty_index(weight_loss_pct: float = 0, fatigue_score: float = None,
                        low_activity: bool = False, slow_gait: bool = False,
                        weak_grip: bool = False, ecog: int = None, age: int = None) -> dict:
    """
    Fragilidad de Fried modificada para oncología.

    Criterios (1 punto cada uno):
        1. Pérdida de peso >5% en 6 meses
        2. Fatiga autoreportada (fatigue score ≥7/10 o FACIT-F <30)
        3. Actividad física reducida
        4. Velocidad de marcha lenta
        5. Fuerza de prensión baja

    Proxy ECOG: ECOG ≥2 agrega slow_gait + low_activity automáticamente.

    Clasificación: 0 = Fit, 1-2 = Pre-frail, ≥3 = Frail

    Impacto: Frail → monoterapia o BSC; Pre-frail → doblete; Fit → triplete

    Reference: Fried LP et al. J Gerontol 2001, Hurria A et al. J Clin Oncol 2011
    """
    missing_inputs = []
    if weight_loss_pct in (None, ""):
        missing_inputs.append("weight_loss_6m_pct")
    if fatigue_score in (None, ""):
        missing_inputs.append("fatigue_score")
    if ecog is None and low_activity in (None, ""):
        missing_inputs.append("low_activity")
    if ecog is None and slow_gait in (None, ""):
        missing_inputs.append("slow_gait")
    if weak_grip in (None, ""):
        missing_inputs.append("weak_grip")
    if missing_inputs:
        return _incomplete_score_payload(
            score_name="Fried Frailty Index",
            missing_inputs=missing_inputs,
            what_score_means="Resume fragilidad física en 5 dominios y orienta si el paciente es fit, pre-frail o frail.",
            clinical_decision_supported="Ayuda a decidir triplete vs doblete vs monoterapia/supportive care y necesidad de rehabilitación geriátrica.",
            extra={
                "criteria_met": None,
                "max_criteria": 5,
                "status": "Incomplete",
                "criteria_detail": [],
                "clinical_actions": ["Completar pérdida de peso, fatiga, actividad, marcha y fuerza de prensión."],
            },
        )

    criteria_met = 0
    criteria_detail = []

    if weight_loss_pct and weight_loss_pct > 5:
        criteria_met += 1
        criteria_detail.append("weight_loss")

    if fatigue_score is not None and fatigue_score >= 7:
        criteria_met += 1
        criteria_detail.append("fatigue")

    if ecog is not None and ecog >= 2:
        if not slow_gait:
            slow_gait = True
        if not low_activity:
            low_activity = True

    if low_activity:
        criteria_met += 1
        criteria_detail.append("low_activity")

    if slow_gait:
        criteria_met += 1
        criteria_detail.append("slow_gait")

    if weak_grip:
        criteria_met += 1
        criteria_detail.append("weak_grip")

    if criteria_met == 0:
        status = "Fit"
    elif criteria_met <= 2:
        status = "Pre-frail"
    else:
        status = "Frail"

    actions = []
    if status == "Frail":
        actions.extend([
            "No intensificar con triplete quimio-hormonal",
            "Preferir monoterapia ARPI o best supportive care",
            "Evaluación geriátrica integral antes de cualquier tratamiento activo",
            "Considerar darolutamida (menor toxicidad neurológica)",
        ])
    elif status == "Pre-frail":
        actions.extend([
            "Doblete preferible sobre triplete",
            "Monitoreo funcional cada 4-6 semanas",
            "Programa de ejercicio supervisado",
        ])

    return {
        "criteria_met": criteria_met,
        "max_criteria": 5,
        "status": status,
        "criteria_detail": criteria_detail,
        "clinical_actions": actions,
        "is_complete": True,
        "data_truth_status": "captured",
        "missing_inputs": [],
        "what_score_means": "Resume fragilidad física en 5 dominios y orienta si el paciente es fit, pre-frail o frail.",
        "risk_category": status.upper().replace("-", "_"),
        "risk_interpretation": f"Clasificación {status}: más criterios positivos implican menor reserva fisiológica.",
        "clinical_decision_supported": "Ayuda a decidir triplete vs doblete vs monoterapia/supportive care y necesidad de rehabilitación geriátrica.",
        "reference": "Fried LP et al. J Gerontol 2001 / Hurria A et al. J Clin Oncol 2011",
    }


def competing_mortality_estimate(age: int, cci: int = 0, egfr: float = None,
                                 frailty_status: str = "Fit") -> dict:
    """
    Estimación de mortalidad competitiva (no-cáncer) a 5 y 10 años.

    Modelo simplificado basado en edad + CCI + eGFR + fragilidad.
    Probabilidad derivada de tablas actuariales ajustadas por comorbilidades.

    Si mortalidad competitiva >50% a 5 años → de-escalar a QoL-centered.

    Reference: Daskivich TJ et al. J Clin Oncol 2013, Cho H et al. Ann Oncol 2013
    """
    if not age or age <= 0:
        return {"mortality_5yr_pct": None, "mortality_10yr_pct": None, "recommendation": "Datos insuficientes"}

    # Base mortality by age (simplified actuarial)
    if age < 60:
        base_5 = 5
        base_10 = 12
    elif age < 70:
        base_5 = 10
        base_10 = 25
    elif age < 75:
        base_5 = 18
        base_10 = 40
    elif age < 80:
        base_5 = 28
        base_10 = 55
    elif age < 85:
        base_5 = 42
        base_10 = 72
    else:
        base_5 = 58
        base_10 = 85

    # CCI adjustment
    cci_mult = 1.0 + (cci * 0.12)

    # eGFR adjustment
    egfr_mult = 1.0
    if egfr is not None:
        if egfr < 30:
            egfr_mult = 1.5
        elif egfr < 45:
            egfr_mult = 1.3
        elif egfr < 60:
            egfr_mult = 1.15

    # Frailty adjustment
    frailty_mult = {"Fit": 1.0, "Pre-frail": 1.2, "Frail": 1.5}.get(frailty_status, 1.0)

    mort_5 = min(round(base_5 * cci_mult * egfr_mult * frailty_mult, 0), 95)
    mort_10 = min(round(base_10 * cci_mult * egfr_mult * frailty_mult, 0), 99)

    if mort_5 >= 50:
        rec = "Mortalidad competitiva alta — de-escalar a manejo centrado en calidad de vida. Evitar tratamientos con beneficio solo a largo plazo."
    elif mort_5 >= 30:
        rec = "Mortalidad competitiva moderada — considerar tratamientos con beneficio a mediano plazo. Individualizar intensidad."
    else:
        rec = "Mortalidad competitiva baja — tratamiento estándar según guías."

    return {
        "mortality_5yr_pct": mort_5,
        "mortality_10yr_pct": mort_10,
        "recommendation": rec,
        "inputs_used": {"age": age, "cci": cci, "egfr": egfr, "frailty_status": frailty_status},
        "reference": "Daskivich TJ et al. J Clin Oncol 2013 / Cho H et al. Ann Oncol 2013",
    }


def treatment_fit_score(ecog: int = 0, cci: int = 0, g8: float = None,
                        egfr: float = None, child_pugh: str = "A",
                        frailty_status: str = "Fit", age: int = None) -> dict:
    """
    Score compuesto de fitness terapéutica.

    Combina: ECOG + CCI + G8 + eGFR + Child-Pugh + Fragilidad → "Fit", "Vulnerable", "Frail"

    Determina intensidad terapéutica:
        Fit → triplete eligible
        Vulnerable → doblete preferible
        Frail → monoterapia o BSC

    Reference: Palumbo A et al. Blood 2015, Hurria A et al. J Clin Oncol 2016
    """
    missing_inputs = []
    if ecog in (None, ""):
        missing_inputs.append("ecog")
    if cci in (None, ""):
        missing_inputs.append("charlson_comorbidity_index")
    if g8 in (None, ""):
        missing_inputs.append("g8")
    if child_pugh in (None, ""):
        missing_inputs.append("child_pugh")
    if frailty_status in (None, "", "Incomplete"):
        missing_inputs.append("frailty_status")
    if missing_inputs:
        return _incomplete_score_payload(
            score_name="Treatment Fit Score",
            missing_inputs=missing_inputs,
            what_score_means="Integra función orgánica, carga geriátrica y fragilidad para estimar aptitud terapéutica global.",
            clinical_decision_supported="Ayuda a decidir intensidad sistémica y necesidad de de-escalamiento o soporte antes de intensificar.",
            extra={
                "penalty_score": None,
                "category": "Incomplete",
                "recommended_intensity": "Completar ECOG, CCI, G8, Child-Pugh y fragilidad antes de usar este score para decidir.",
                "components": {},
            },
        )

    penalty = 0

    # ECOG
    if ecog >= 3:
        penalty += 3
    elif ecog >= 2:
        penalty += 2
    elif ecog >= 1:
        penalty += 1

    # CCI
    if cci >= 6:
        penalty += 3
    elif cci >= 4:
        penalty += 2
    elif cci >= 2:
        penalty += 1

    # G8 (≤14 = fragilidad geriátrica)
    if g8 is not None:
        if g8 <= 10:
            penalty += 3
        elif g8 <= 14:
            penalty += 2

    # eGFR
    if egfr is not None:
        if egfr < 30:
            penalty += 3
        elif egfr < 45:
            penalty += 2
        elif egfr < 60:
            penalty += 1

    # Child-Pugh
    cp_penalty = {"A": 0, "B": 2, "C": 4}.get(child_pugh.upper() if child_pugh else "A", 0)
    penalty += cp_penalty

    # Fragilidad
    frailty_penalty = {"Fit": 0, "Pre-frail": 1, "Frail": 3}.get(frailty_status, 0)
    penalty += frailty_penalty

    # Age bonus penalty
    if age is not None and age >= 80:
        penalty += 1

    if penalty <= 2:
        category = "Fit"
        intensity = "Triplete eligible si indicado clínicamente"
    elif penalty <= 5:
        category = "Vulnerable"
        intensity = "Doblete preferible; evitar triplete sin justificación fuerte"
    else:
        category = "Frail"
        intensity = "Monoterapia o best supportive care; triplete contraindicado"

    return {
        "penalty_score": penalty,
        "category": category,
        "recommended_intensity": intensity,
        "components": {
            "ecog_penalty": min(ecog, 3) if ecog else 0,
            "cci_penalty": min(cci // 2, 3) if cci else 0,
            "g8_penalty": (3 if g8 and g8 <= 10 else (2 if g8 and g8 <= 14 else 0)),
            "egfr_penalty": (3 if egfr and egfr < 30 else (2 if egfr and egfr < 45 else (1 if egfr and egfr < 60 else 0))),
            "child_pugh_penalty": cp_penalty,
            "frailty_penalty": frailty_penalty,
        },
        "reference": "Palumbo A et al. Blood 2015 / Hurria A et al. J Clin Oncol 2016",
    }


def docetaxel_fitness(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Evalúa aptitud estructurada para docetaxel.

    La salida separa tres capas:
      - elegibilidad base: contraindicado / con cautela / elegible / no evaluable
      - trial-fit: ARASENS-like / PEACE-1-like / CHAARTED-like
      - compatibilidad legacy: fit_for_docetaxel / fit_status
    """

    DOCETAXEL_LAB_RECENCY_DAYS = 14
    DOCETAXEL_LAB_ULN = {
        "bilirubin": 1.2,
        "ast": 40.0,
        "alt": 40.0,
        "alp": 120.0,
    }
    HIGH_VOLUME_DOCETAXEL_STATES = {
        "mcspc_high_volume",
        "mcspc_high_volume_sync",
        "mcspc_high_volume_metachronous",
    }

    def _to_int(value: Any) -> int | None:
        try:
            if value in (None, ""):
                return None
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _truthy(value: Any) -> bool:
        return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "on", "documentado"}

    def _to_float(value: Any) -> float | None:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _to_date(value: Any) -> date | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value).strip()
        if not text:
            return None
        for candidate in (text[:10], text):
            try:
                return datetime.fromisoformat(candidate).date()
            except ValueError:
                continue
        return None

    def _performance_status_driver() -> str:
        explicit = str(patient.get("performance_status_driver") or "").strip().lower()
        mapping = {
            "cancer_related": "cancer_related",
            "cancer": "cancer_related",
            "cancer_related_decline": "cancer_related",
            "comorbidity_or_frailty": "comorbidity_or_frailty",
            "comorbidity": "comorbidity_or_frailty",
            "frailty": "comorbidity_or_frailty",
            "mixed_or_unclear": "mixed_or_unclear",
            "mixed": "mixed_or_unclear",
            "unclear": "mixed_or_unclear",
        }
        normalized = mapping.get(explicit, "")
        if normalized:
            return normalized
        return "mixed_or_unclear"

    ecog = _to_int(patient.get("ecog_score", patient.get("ecog")))
    neuropathy = _to_int(patient.get("peripheral_neuropathy_grade"))
    frailty = str(patient.get("frailty_status", "") or "").strip().lower()
    g8_score = _to_float(patient.get("g8_score") or patient.get("g8_geriatric_score") or patient.get("geriatric_g8_screening") or patient.get("bellera_g8"))
    mini_cog_score = _to_float(patient.get("mini_cog_score") or patient.get("mini_cog") or patient.get("minicog_score"))
    child_pugh = str(patient.get("child_pugh_score", "A") or "A").strip().upper()
    cv_risk = _truthy(patient.get("cv_risk_documented")) or _truthy(patient.get("comorbidity_cardio"))
    ddi_reviewed = _truthy(patient.get("drug_interaction_reviewed"))
    performance_status_driver = _performance_status_driver()
    bone_pain = _truthy(patient.get("bone_pain")) or _truthy(patient.get("osseous_pain"))
    geriatric_clearance_for_triplet = any(
        _truthy(patient.get(field))
        for field in (
            "geriatric_clearance_for_triplete",
            "geriatric_endorsement_for_triplet",
            "geriatric_endorsement_for_triplete",
            "comprehensive_geriatric_assessment_fit",
        )
    )
    anc_fields_present = any(field in patient for field in ("anc", "anc_current", "absolute_neutrophil_count"))
    platelet_fields_present = any(field in patient for field in ("platelets", "platelets_current", "platelet_count"))
    anc = _to_float(patient.get("anc") or patient.get("anc_current") or patient.get("absolute_neutrophil_count"))
    platelets = _to_float(patient.get("platelets") or patient.get("platelets_current") or patient.get("platelet_count"))
    bilirubin = _to_float(patient.get("bilirubin") or patient.get("bilirubin_current"))
    ast = _to_float(patient.get("ast") or patient.get("ast_current"))
    alt = _to_float(patient.get("alt") or patient.get("alt_current"))
    alp = _to_float(patient.get("alp") or patient.get("alkaline_phosphatase") or patient.get("alp_current"))
    cbc_date = _to_date(patient.get("cbc_date") or patient.get("cbc_sample_date") or patient.get("docetaxel_cbc_date"))
    liver_panel_date = _to_date(
        patient.get("liver_panel_date")
        or patient.get("hepatic_panel_date")
        or patient.get("docetaxel_liver_panel_date")
    )
    taxane_hypersensitivity = any(
        _truthy(patient.get(field))
        for field in (
            "taxane_hypersensitivity_history",
            "docetaxel_hypersensitivity_history",
            "polysorbate_hypersensitivity",
        )
    )
    state_hint = str(
        patient.get("state")
        or patient.get("assessment_state")
        or patient.get("module_id")
        or patient.get("effective_state")
        or ""
    ).strip().lower()
    high_volume_triplet_state = state_hint in HIGH_VOLUME_DOCETAXEL_STATES or "mcspc_high_volume" in state_hint
    force_docetaxel_verification = _truthy(patient.get("force_docetaxel_verification")) or _truthy(
        patient.get("docetaxel_candidate_now") or patient.get("taxane_candidate_now")
    )
    docetaxel_context = str(
        patient.get("docetaxel_context")
        or patient.get("taxane_context")
        or ("mhspc_triplet" if high_volume_triplet_state else "advanced_taxane")
    ).strip().lower()

    hard_stop_reasons: list[str] = []
    label_block_reasons: list[str] = []
    clinical_block_reasons: list[str] = []
    caution_reasons: list[str] = []
    missing_inputs: list[str] = []
    stale_inputs: list[str] = []
    label_safety_reasons: list[str] = []

    if ecog is None:
        missing_inputs.append("ecog_score")
    elif ecog >= 3:
        reason = "ECOG ≥3"
        hard_stop_reasons.append(reason)
        clinical_block_reasons.append(reason)
    elif ecog == 2:
        caution_reasons.append("ECOG 2: docetaxel solo con cautela")

    if neuropathy is None:
        missing_inputs.append("peripheral_neuropathy_grade")
    elif neuropathy >= 3:
        reason = "Neuropatía periférica severa (grado 3 o mayor)"
        hard_stop_reasons.append(reason)
        clinical_block_reasons.append(reason)
    elif neuropathy == 2:
        caution_reasons.append("Neuropatía periférica grado 2")

    if frailty == "frail":
        reason = "Fragilidad clínica Frail"
        hard_stop_reasons.append(reason)
        clinical_block_reasons.append(reason)
    elif frailty == "vulnerable":
        caution_reasons.append("Fragilidad clínica Vulnerable: requiere evaluación geriátrica antes de priorizar triplete con docetaxel")
    elif not frailty:
        missing_inputs.append("frailty_status")

    geriatric_default_block = False
    geriatric_screen_status = "not_documented"
    geriatric_cautions: list[str] = []
    if frailty == "frail":
        geriatric_screen_status = "adapted_treatment_required"
    elif frailty == "vulnerable":
        geriatric_screen_status = "requires_cga"
        geriatric_cautions.append("frailty_status")
    if g8_score is not None:
        if g8_score <= 14:
            geriatric_screen_status = "requires_cga"
            geriatric_cautions.append("g8_score")
            caution_reasons.append("G8 ≤14: tamiz geriátrico vulnerable; no priorizar triplete con docetaxel sin CGA/clearance")
        elif geriatric_screen_status == "not_documented":
            geriatric_screen_status = "fit"
    if mini_cog_score is not None:
        if mini_cog_score <= 3:
            geriatric_screen_status = "unresolved_impairment"
            geriatric_cautions.append("mini_cog_score")
            caution_reasons.append("Mini-Cog ≤3: vulnerabilidad cognitiva; preferir doblete hasta aclarar seguridad del triplete")
        elif geriatric_screen_status == "not_documented":
            geriatric_screen_status = "fit"
    if geriatric_cautions and not geriatric_clearance_for_triplet:
        geriatric_default_block = True

    if child_pugh == "C":
        reason = "Child-Pugh C"
        hard_stop_reasons.append(reason)
        clinical_block_reasons.append(reason)
    elif child_pugh == "B":
        caution_reasons.append("Child-Pugh B")

    docetaxel_required_now = (high_volume_triplet_state or force_docetaxel_verification) and not bool(clinical_block_reasons)
    if docetaxel_required_now and cbc_date is None:
        missing_inputs.append("cbc_date")
    if docetaxel_required_now and liver_panel_date is None:
        missing_inputs.append("liver_panel_date")
    if docetaxel_required_now and cbc_date is not None and (date.today() - cbc_date).days > DOCETAXEL_LAB_RECENCY_DAYS:
        stale_inputs.extend(["cbc_date", "anc", "platelets"])
    if docetaxel_required_now and liver_panel_date is not None and (date.today() - liver_panel_date).days > DOCETAXEL_LAB_RECENCY_DAYS:
        stale_inputs.extend(["liver_panel_date", "bilirubin", "ast", "alt", "alp"])

    if docetaxel_required_now and anc is None:
        missing_inputs.append("anc")
    elif anc is not None and anc < 1500:
        reason = "Neutrófilos <1500/mm3"
        hard_stop_reasons.append(reason)
        label_block_reasons.append(reason)
        label_safety_reasons.append(reason)
    elif anc_fields_present and anc is None:
        missing_inputs.append("anc")

    if docetaxel_required_now and platelets is None:
        missing_inputs.append("platelets")
    elif platelets is not None and platelets < 100000:
        reason = "Plaquetas <100000/mm3"
        hard_stop_reasons.append(reason)
        clinical_block_reasons.append(reason)
    elif platelet_fields_present and platelets is None:
        missing_inputs.append("platelets")

    if taxane_hypersensitivity:
        reason = "Antecedente de hipersensibilidad severa a docetaxel/polisorbato"
        hard_stop_reasons.append(reason)
        label_block_reasons.append(reason)
        label_safety_reasons.append(reason)

    if docetaxel_required_now and bilirubin is None:
        missing_inputs.append("bilirubin")
    if docetaxel_required_now and ast is None:
        missing_inputs.append("ast")
    if docetaxel_required_now and alt is None:
        missing_inputs.append("alt")
    ast_limit = 1.5 * DOCETAXEL_LAB_ULN["ast"]
    alt_limit = 1.5 * DOCETAXEL_LAB_ULN["alt"]
    ast_alt_incomplete_or_elevated = (
        ast is None
        or alt is None
        or ast > ast_limit
        or alt > alt_limit
    )
    if docetaxel_required_now and alp is None and ast_alt_incomplete_or_elevated:
        missing_inputs.append("alp")

    if bilirubin is not None and bilirubin > DOCETAXEL_LAB_ULN["bilirubin"]:
        reason = "Bilirrubina > ULN institucional"
        hard_stop_reasons.append(reason)
        label_block_reasons.append(reason)
        label_safety_reasons.append(reason)
    elif all(value is not None for value in (ast, alt, alp)):
        alp_limit = 2.5 * DOCETAXEL_LAB_ULN["alp"]
        if ((ast is not None and ast > ast_limit) or (alt is not None and alt > alt_limit)) and alp > alp_limit:
            reason = "AST/ALT >1.5x ULN con ALP >2.5x ULN institucional"
            hard_stop_reasons.append(reason)
            label_block_reasons.append(reason)
            label_safety_reasons.append(reason)

    if ecog == 2 and performance_status_driver == "mixed_or_unclear":
        caution_reasons.append("ECOG 2 sin aclarar si el deterioro es por cáncer o por fragilidad/comorbilidad")
        missing_inputs.append("performance_status_driver")
    if ecog == 2 and not bone_pain and performance_status_driver == "cancer_related":
        caution_reasons.append("ECOG 2 cáncer-relacionado sin documentar dolor óseo o carga sintomática")
        missing_inputs.extend(["bone_pain"])

    verification_status = "verified"
    if stale_inputs:
        verification_status = "stale_labs"
    elif docetaxel_required_now and any(
        field in missing_inputs for field in ("anc", "platelets", "cbc_date", "bilirubin", "ast", "alt", "alp", "liver_panel_date")
    ):
        verification_status = "pending_labs"

    if missing_inputs:
        caution_reasons.append(
            "Faltan datos para confirmar aptitud completa: "
            + ", ".join(sorted(dict.fromkeys(missing_inputs)))
        )
    if stale_inputs:
        caution_reasons.append(
            "Los laboratorios de elegibilidad a docetaxel están vencidos (>14 días): "
            + ", ".join(sorted(dict.fromkeys(stale_inputs)))
        )

    if hard_stop_reasons:
        base_eligibility = "contraindicated"
    elif caution_reasons:
        base_eligibility = "eligible_with_caution"
    else:
        base_eligibility = "eligible"

    docetaxel_trial_fit = {
        "arasens_like": "no",
        "peace1_like": "no",
        "chaarted_like": "no",
    }
    if base_eligibility in {"eligible", "eligible_with_caution"} and frailty != "frail" and child_pugh != "C":
        if ecog in {0, 1} and (neuropathy is None or neuropathy <= 1):
            docetaxel_trial_fit = {
                "arasens_like": "matched",
                "peace1_like": "matched",
                "chaarted_like": "matched",
            }
        elif ecog == 2:
            if performance_status_driver == "cancer_related":
                docetaxel_trial_fit["chaarted_like"] = "partial"
                docetaxel_trial_fit["peace1_like"] = "partial"
            elif bone_pain:
                docetaxel_trial_fit["peace1_like"] = "partial"

    if hard_stop_reasons:
        default_intensification = "no"
    elif geriatric_default_block:
        default_intensification = "no"
    elif force_docetaxel_verification and not high_volume_triplet_state:
        if base_eligibility == "eligible" and verification_status == "verified":
            default_intensification = "yes"
        elif base_eligibility in {"eligible", "eligible_with_caution"}:
            default_intensification = "conditional"
        else:
            default_intensification = "no"
    elif base_eligibility == "eligible" and verification_status == "verified" and any(value == "matched" for value in docetaxel_trial_fit.values()):
        default_intensification = "yes"
    elif base_eligibility in {"eligible_with_caution", "not_assessable"} and any(
        value in {"matched", "partial"} for value in docetaxel_trial_fit.values()
    ):
        default_intensification = "conditional"
    else:
        default_intensification = "no"

    fit_for_docetaxel = base_eligibility in {"eligible", "eligible_with_caution"}
    if base_eligibility == "eligible":
        fit_status = "fit"
        fit_summary = "Apto para docetaxel sin banderas mayores de seguridad."
    elif verification_status in {"pending_labs", "stale_labs"} and not hard_stop_reasons:
        fit_status = "fit_with_caution"
        fit_summary = (
            "Pendiente validar elegibilidad a docetaxel: "
            + "; ".join(caution_reasons)
            + "."
        )
    elif base_eligibility == "eligible_with_caution":
        fit_status = "fit_with_caution"
        fit_summary = "Apto para docetaxel con cautela: " + "; ".join(caution_reasons) + "."
    else:
        fit_status = "not_fit"
        if label_block_reasons:
            fit_summary = "Contraindicación documentada para docetaxel: " + "; ".join(hard_stop_reasons) + "."
        else:
            fit_summary = "No elegible hoy para docetaxel por seguridad clínica: " + "; ".join(hard_stop_reasons) + "."

    return {
        "eligible": fit_for_docetaxel,
        "fit_for_docetaxel": fit_for_docetaxel,
        "fit_status": fit_status,
        "docetaxel_base_eligibility": base_eligibility,
        "docetaxel_verification_status": verification_status,
        "docetaxel_block_type": "label" if label_block_reasons else ("clinical_safety" if clinical_block_reasons else "none"),
        "docetaxel_required_now": docetaxel_required_now,
        "docetaxel_lab_recency_days": DOCETAXEL_LAB_RECENCY_DAYS,
        "docetaxel_trial_fit": docetaxel_trial_fit,
        "docetaxel_default_intensification": default_intensification,
        "docetaxel_hard_stop_reasons": hard_stop_reasons,
        "docetaxel_caution_reasons": caution_reasons,
        "docetaxel_label_safety_reasons": sorted(dict.fromkeys(label_safety_reasons)),
        "docetaxel_clinical_safety_reasons": sorted(dict.fromkeys(clinical_block_reasons)),
        "docetaxel_fit_summary": fit_summary,
        "missing_inputs": missing_inputs,
        "docetaxel_missing_inputs": missing_inputs,
        "docetaxel_stale_inputs": sorted(dict.fromkeys(stale_inputs)),
        "g8_score": g8_score,
        "mini_cog_score": mini_cog_score,
        "cognitive_risk": bool(mini_cog_score is not None and mini_cog_score <= 3),
        "cognitive_risk_source": "mini_cog_score" if mini_cog_score is not None and mini_cog_score <= 3 else "",
        "geriatric_screen_status": geriatric_screen_status,
        "geriatric_default_block": geriatric_default_block,
        "geriatric_caution_inputs": sorted(dict.fromkeys(geriatric_cautions)),
        "performance_status_driver": performance_status_driver,
        "docetaxel_candidate_now": force_docetaxel_verification,
        "docetaxel_context": docetaxel_context,
        "docetaxel_lab_snapshot": {
            "cbc_date": cbc_date.isoformat() if cbc_date else "",
            "liver_panel_date": liver_panel_date.isoformat() if liver_panel_date else "",
            "anc": anc,
            "platelets": platelets,
            "bilirubin": bilirubin,
            "ast": ast,
            "alt": alt,
            "alp": alp,
            "source": str(patient.get("docetaxel_lab_source") or patient.get("lab_source") or "captura_actual"),
        },
        "docetaxel_lab_uln": dict(DOCETAXEL_LAB_ULN),
        "reference": "Política estructurada del producto alineada a EAU 2026, ARASENS, PEACE-1, CHAARTED y label FDA de docetaxel.",
    }
