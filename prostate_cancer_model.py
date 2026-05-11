# -*- coding: utf-8 -*-
"""
Modelo Multi-Output de Deep Learning para Cáncer de Próstata — PyTorch
(Versión mejorada con campos clínicos extendidos, constraint loss,
 cross-validation, calibración y arquitectura residual)
"""
import os
import json
import logging
from datetime import datetime

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader
from sklearn.preprocessing import OneHotEncoder, StandardScaler, LabelEncoder
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.metrics import classification_report, roc_auc_score, mean_absolute_error
import joblib

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Reproducibilidad ────────────────────────────────────────────────────────
SEED = 42
np.random.seed(SEED)
torch.manual_seed(SEED)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

DEVICE = torch.device("mps" if torch.backends.mps.is_available() else "cpu")


# ============================================================================
# 1. DATOS SINTÉTICOS CON LÓGICA CLÍNICA EXTENDIDA
# ============================================================================
def _gleason_to_isup(g: int) -> int:
    """Convierte score de Gleason a ISUP Grade Group."""
    return {6: 1, 7: 2, 8: 4, 9: 5, 10: 5}.get(g, 3)  # 3+4→2, 4+3→3 (simplificado)


def generate_synthetic_data(num_samples: int = 3000) -> pd.DataFrame:
    np.random.seed(SEED)

    # ── Variables originales ─────────────────────────────────────────────
    age = np.random.randint(45, 85, num_samples)
    psa = np.random.exponential(6, num_samples) + 0.5
    ecog = np.random.choice([0, 0, 0, 1, 1, 2], num_samples)
    stage = np.random.choice([1, 1, 2, 2, 2, 3, 3, 4], num_samples)
    gleason = np.random.choice([6, 6, 7, 7, 7, 8, 8, 9, 10], num_samples)
    cci = np.random.choice([0, 0, 0, 1, 1, 2, 2, 3, 4], num_samples)
    vol = np.random.uniform(25, 90, num_samples)
    psad = psa / vol

    # ── NUEVOS CAMPOS CLÍNICOS ───────────────────────────────────────────
    isup_grade = np.array([_gleason_to_isup(g) for g in gleason])

    # PI-RADS correlacionado con stage y Gleason
    pirads_base = np.clip(stage + (gleason - 6) / 2 + np.random.normal(0, 0.5, num_samples), 1, 5)
    pirads = np.round(pirads_base).astype(int)

    # % cores positivos — correlacionado con agresividad
    pct_cores_base = 0.1 + (gleason - 6) * 0.08 + (stage - 1) * 0.05
    pct_cores_positive = np.clip(pct_cores_base + np.random.normal(0, 0.1, num_samples), 0.0, 1.0)

    # Invasión perineural — más probable en alto grado
    pni_prob = np.clip(0.05 + (gleason - 6) * 0.08 + (stage - 1) * 0.05, 0, 0.8)
    perineural_invasion = np.array([np.random.binomial(1, p) for p in pni_prob])

    # Antecedente familiar (~15% prevalencia)
    family_history = np.random.binomial(1, 0.15, num_samples)

    # IMC — distribución normal centrada en 27
    bmi = np.clip(np.random.normal(27, 4, num_samples), 18.0, 45.0)

    # Testosterona (ng/dL)
    testosterone = np.clip(np.random.normal(450, 120, num_samples), 50, 1000)

    # Ratio PSA libre — inversamente correlacionado con riesgo
    free_psa_base = 0.30 - (gleason - 6) * 0.03 - (stage - 1) * 0.02
    free_psa_ratio = np.clip(free_psa_base + np.random.normal(0, 0.06, num_samples), 0.05, 0.70)

    # Total de cores biopsiados y cores positivos
    total_cores = np.random.choice([6, 8, 10, 12, 12, 12, 14, 16], num_samples)
    num_cores_pos_frac = pct_cores_positive * total_cores
    num_cores_positive = np.clip(np.round(num_cores_pos_frac + np.random.normal(0, 0.5, num_samples)),
                                 0, total_cores).astype(int)

    # Máxima implicación de un core (% tumor en el core más afectado)
    max_core_inv_base = 0.15 + (gleason - 6) * 0.10 + (stage - 1) * 0.05
    max_core_involvement = np.clip(max_core_inv_base + np.random.normal(0, 0.12, num_samples), 0.0, 1.0)

    # Invasión linfovascular — correlacionada con grado alto
    lvi_prob = np.clip(0.03 + (gleason - 6) * 0.06 + (stage - 1) * 0.04, 0, 0.7)
    lymphovascular_invasion = np.array([np.random.binomial(1, p) for p in lvi_prob])

    # Margen quirúrgico (en contexto post-prostatectomía; simulamos para todos)
    sm_prob = np.clip(0.08 + (stage - 1) * 0.06 + (gleason - 6) * 0.04, 0, 0.6)
    surgical_margin_status = np.array([np.random.binomial(1, p) for p in sm_prob])

    # Raza / etnia — factor epidemiológico
    race_ethnicity = np.random.choice(
        ['caucasico', 'afroamericano', 'hispano', 'asiatico', 'otro'],
        num_samples, p=[0.45, 0.20, 0.20, 0.10, 0.05])

    # Hallazgos DRE (tacto rectal) — TNM clínico simplificado
    dre_map = {1: 'T1c', 2: 'T2a', 3: 'T3a', 4: 'T4'}
    dre_findings = np.array([dre_map.get(s, 'T2a') for s in stage])

    # Número de biopsias previas
    previous_biopsies = np.random.choice([0, 0, 0, 1, 1, 2, 3], num_samples)

    # Score genómico (Decipher/Prolaris-like, escala 0-1)
    genomic_base = 0.15 + (gleason - 6) * 0.08 + (stage - 1) * 0.06
    genomic_score = np.clip(genomic_base + np.random.normal(0, 0.10, num_samples), 0.0, 1.0)

    # ── Risk scoring tipo D'Amico (enriquecido) ─────────────────────────
    rs = np.zeros(num_samples)
    rs += np.where(gleason <= 6, 0, np.where(gleason == 7, 1, np.where(gleason == 8, 2, 3)))
    rs += np.where(psa < 10, 0, np.where(psa < 20, 1, 2))
    rs += np.where(stage <= 1, 0, np.where(stage == 2, 0.5, np.where(stage == 3, 1.5, 2.5)))
    rs += ecog * 0.5
    # Nuevos factores en el scoring
    rs += pct_cores_positive * 1.5
    rs += perineural_invasion * 0.4
    rs += np.where(pirads >= 4, 0.5, 0)
    rs += lymphovascular_invasion * 0.5
    rs += max_core_involvement * 0.8
    rs += genomic_score * 1.2
    rs += np.where(race_ethnicity == 'afroamericano', 0.3, 0)
    risk = np.where(rs < 3.0, 0, np.where(rs < 6.5, 1, 2))

    # ── Tratamiento ──────────────────────────────────────────────────────
    treatment = np.empty(num_samples, dtype=object)
    for i in range(num_samples):
        if risk[i] == 0:
            treatment[i] = np.random.choice(
                ['vigilancia_activa', 'radioterapia', 'prostatectomia'], p=[0.50, 0.25, 0.25])
        elif risk[i] == 1:
            treatment[i] = np.random.choice(
                ['prostatectomia', 'radioterapia', 'hormonoterapia', 'vigilancia_activa'],
                p=[0.35, 0.35, 0.20, 0.10])
        else:
            treatment[i] = np.random.choice(
                ['hormonoterapia', 'quimioterapia', 'radioterapia', 'prostatectomia'],
                p=[0.35, 0.30, 0.20, 0.15])

    # ── Salidas de supervivencia / curación ──────────────────────────────
    rs_norm = (rs - rs.min()) / (rs.max() - rs.min() + 1e-8)
    s5_base = 1.0 - rs_norm * 0.6
    age_f = np.clip((age - 45) / 40, 0, 1) * 0.15
    cci_f = cci * 0.05
    bmi_f = np.where(bmi > 35, 0.03, 0.0)   # obesidad como factor negativo
    testo_f = np.where(testosterone < 200, 0.05, 0.0)  # hipogonadismo
    lvi_f = lymphovascular_invasion * 0.04
    margin_f = surgical_margin_status * 0.03
    genomic_f = np.where(genomic_score > 0.6, 0.05, 0.0)

    survival_5y = np.clip(s5_base - age_f - cci_f - bmi_f - testo_f
                          - lvi_f - margin_f - genomic_f
                          + np.random.normal(0, 0.05, num_samples), 0.05, 0.99)
    survival_10y = np.clip(survival_5y * np.random.uniform(0.55, 0.95, num_samples),
                           0.02, survival_5y - 0.01)

    cure_base = 1.0 - rs_norm * 0.7
    surg = np.where(treatment == 'prostatectomia', 0.10, 0.0)
    cure_rate = np.clip(cure_base + surg + np.random.normal(0, 0.06, num_samples), 0.01, 0.98)

    return pd.DataFrame({
        'age': age, 'psa': psa, 'ecog': ecog, 'stage': stage,
        'gleason': gleason, 'cci': cci, 'psad': psad,
        # Campos clínicos extendidos
        'isup_grade': isup_grade, 'pirads': pirads,
        'pct_cores_positive': pct_cores_positive,
        'num_cores_positive': num_cores_positive, 'total_cores': total_cores,
        'max_core_involvement': max_core_involvement,
        'perineural_invasion': perineural_invasion,
        'lymphovascular_invasion': lymphovascular_invasion,
        'surgical_margin_status': surgical_margin_status,
        'race_ethnicity': race_ethnicity, 'dre_findings': dre_findings,
        'family_history': family_history, 'bmi': bmi,
        'testosterone': testosterone, 'free_psa_ratio': free_psa_ratio,
        'previous_biopsies': previous_biopsies, 'genomic_score': genomic_score,
        # Salidas
        'treatment': treatment, 'risk': risk.astype(int),
        'cure_rate': cure_rate, 'survival_5y': survival_5y, 'survival_10y': survival_10y,
    })


# ============================================================================
# 2. PREPROCESAMIENTO
# ============================================================================
def preprocess_data(df: pd.DataFrame):
    df = df.copy()
    df['psa_log'] = np.log1p(df['psa'])

    cat_cols = ['stage', 'gleason', 'isup_grade', 'pirads',
                'race_ethnicity', 'dre_findings']
    encoder = OneHotEncoder(handle_unknown='ignore', sparse_output=False)
    encoded = encoder.fit_transform(df[cat_cols].astype(str))

    num_cols = ['age', 'psa_log', 'ecog', 'cci', 'psad',
                'pct_cores_positive', 'num_cores_positive', 'total_cores',
                'max_core_involvement', 'perineural_invasion',
                'lymphovascular_invasion', 'surgical_margin_status',
                'family_history', 'bmi', 'testosterone', 'free_psa_ratio',
                'previous_biopsies', 'genomic_score']
    scaler = StandardScaler()
    scaled = scaler.fit_transform(df[num_cols])
    X = np.concatenate([scaled, encoded], axis=1)

    risk_encoder = LabelEncoder()
    y_risk = risk_encoder.fit_transform(df['risk'])
    treatment_encoder = LabelEncoder()
    y_treatment = treatment_encoder.fit_transform(df['treatment'])

    artifacts = {
        'encoder': encoder, 'scaler': scaler,
        'risk_encoder': risk_encoder, 'treatment_encoder': treatment_encoder,
        'feature_names': num_cols + list(encoder.get_feature_names_out(cat_cols)),
        'num_cols': num_cols, 'cat_cols': cat_cols,
    }
    return (X, y_risk, y_treatment,
            df['cure_rate'].values, df['survival_5y'].values, df['survival_10y'].values,
            artifacts)


# ============================================================================
# 3. MODELO PYTORCH  — Arquitectura configurable con Residual Connections
# ============================================================================
class ResidualBlock(nn.Module):
    """Bloque lineal con BatchNorm, ReLU, Dropout y conexión residual."""
    def __init__(self, dim: int, dropout: float = 0.25):
        super().__init__()
        self.block = nn.Sequential(
            nn.Linear(dim, dim),
            nn.BatchNorm1d(dim),
            nn.ReLU(),
            nn.Dropout(dropout),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.block(x)            # skip connection


class ProstateCancerNet(nn.Module):
    def __init__(self, input_dim: int, n_risk: int, n_treatment: int,
                 hidden_dims: list[int] | None = None, dropout: float = 0.25):
        super().__init__()
        hidden_dims = hidden_dims or [64, 128, 64]
        self.hidden_dims = hidden_dims  # guardamos para persistencia

        # Capa de entrada → primera dimensión oculta
        layers: list[nn.Module] = [
            nn.Linear(input_dim, hidden_dims[0]),
            nn.BatchNorm1d(hidden_dims[0]),
            nn.ReLU(),
            nn.Dropout(dropout),
        ]

        # Capas ocultas con residual cuando las dimensiones coinciden
        for i in range(1, len(hidden_dims)):
            if hidden_dims[i] == hidden_dims[i - 1]:
                layers.append(ResidualBlock(hidden_dims[i], dropout))
            else:
                layers.extend([
                    nn.Linear(hidden_dims[i - 1], hidden_dims[i]),
                    nn.BatchNorm1d(hidden_dims[i]),
                    nn.ReLU(),
                    nn.Dropout(dropout),
                ])

        self.shared = nn.Sequential(*layers)
        last_dim = hidden_dims[-1]

        # Heads de salida
        self.risk_head = nn.Linear(last_dim, n_risk)
        self.treatment_head = nn.Linear(last_dim, n_treatment)
        self.cure_head = nn.Sequential(nn.Linear(last_dim, 1), nn.Sigmoid())
        self.surv5_head = nn.Sequential(nn.Linear(last_dim, 1), nn.Sigmoid())
        self.surv10_head = nn.Sequential(nn.Linear(last_dim, 1), nn.Sigmoid())

    def forward(self, x: torch.Tensor):
        h = self.shared(x)
        return (
            self.risk_head(h),
            self.treatment_head(h),
            self.cure_head(h).squeeze(-1),
            self.surv5_head(h).squeeze(-1),
            self.surv10_head(h).squeeze(-1),
        )


# ============================================================================
# 3b. CALIBRACIÓN DE PROBABILIDADES — Temperature Scaling
# ============================================================================
class TemperatureScaling(nn.Module):
    """Post-hoc temperature scaling para calibrar logits."""
    def __init__(self):
        super().__init__()
        self.temperature = nn.Parameter(torch.ones(1))

    def forward(self, logits: torch.Tensor) -> torch.Tensor:
        return logits / self.temperature


def calibrate_temperature(logits: torch.Tensor, labels: torch.Tensor,
                          lr: float = 0.01, max_iter: int = 200) -> TemperatureScaling:
    ts = TemperatureScaling().to(logits.device)
    optimizer = torch.optim.LBFGS([ts.temperature], lr=lr, max_iter=max_iter)
    ce = nn.CrossEntropyLoss()

    def closure():
        optimizer.zero_grad()
        loss = ce(ts(logits), labels)
        loss.backward()
        return loss

    optimizer.step(closure)
    logger.info("Calibración T=%.4f", ts.temperature.item())
    return ts


# ============================================================================
# 4. ENTRENAMIENTO  — DataLoader, gradient clipping, constraint loss
# ============================================================================
def train_model(model, X_train, X_test, targets_train, targets_test,
                epochs=120, batch_size=64, lr=0.001, constraint_lambda=2.0):
    model.to(DEVICE)

    # ── DataLoaders ──────────────────────────────────────────────────────
    train_ds = TensorDataset(
        torch.tensor(X_train, dtype=torch.float32),
        torch.tensor(targets_train['risk'], dtype=torch.long),
        torch.tensor(targets_train['treatment'], dtype=torch.long),
        torch.tensor(targets_train['cure_rate'], dtype=torch.float32),
        torch.tensor(targets_train['survival_5y'], dtype=torch.float32),
        torch.tensor(targets_train['survival_10y'], dtype=torch.float32),
    )
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True,
                              drop_last=False)

    X_te = torch.tensor(X_test, dtype=torch.float32).to(DEVICE)
    y_risk_te = torch.tensor(targets_test['risk'], dtype=torch.long).to(DEVICE)
    y_treat_te = torch.tensor(targets_test['treatment'], dtype=torch.long).to(DEVICE)
    y_cure_te = torch.tensor(targets_test['cure_rate'], dtype=torch.float32).to(DEVICE)
    y_s5_te = torch.tensor(targets_test['survival_5y'], dtype=torch.float32).to(DEVICE)
    y_s10_te = torch.tensor(targets_test['survival_10y'], dtype=torch.float32).to(DEVICE)

    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, patience=7, factor=0.5, min_lr=1e-6)
    ce = nn.CrossEntropyLoss()
    mse = nn.MSELoss()

    w = {'risk': 2.0, 'treat': 1.5, 'cure': 1.0, 'surv5': 1.5, 'surv10': 1.0}

    best_val_loss = float('inf')
    patience_counter = 0
    best_state = None
    history: dict[str, list[float]] = {'loss': [], 'val_loss': []}

    for epoch in range(epochs):
        model.train()
        epoch_loss = 0.0

        for batch in train_loader:
            xb, yr, yt, yc, ys5, ys10 = (t.to(DEVICE) for t in batch)
            r, t, c, s5, s10 = model(xb)

            loss = (w['risk']  * ce(r, yr)
                  + w['treat'] * ce(t, yt)
                  + w['cure']  * mse(c, yc)
                  + w['surv5'] * mse(s5, ys5)
                  + w['surv10'] * mse(s10, ys10))

            # ── Constraint loss: survival_10y ≤ survival_5y ─────────────
            constraint_penalty = torch.relu(s10 - s5).mean()
            loss = loss + constraint_lambda * constraint_penalty

            optimizer.zero_grad()
            loss.backward()
            # ── Gradient clipping ────────────────────────────────────────
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            epoch_loss += loss.item()

        avg_train = epoch_loss / max(len(train_loader), 1)

        # Validación
        model.eval()
        with torch.no_grad():
            r, t, c, s5, s10 = model(X_te)
            val_loss = (w['risk']  * ce(r, y_risk_te)
                      + w['treat'] * ce(t, y_treat_te)
                      + w['cure']  * mse(c, y_cure_te)
                      + w['surv5'] * mse(s5, y_s5_te)
                      + w['surv10'] * mse(s10, y_s10_te)
                      + constraint_lambda * torch.relu(s10 - s5).mean()
                      ).item()

        history['loss'].append(avg_train)
        history['val_loss'].append(val_loss)
        scheduler.step(val_loss)

        if (epoch + 1) % 20 == 0 or epoch == 0:
            logger.info("Epoch %3d/%d — train: %.4f — val: %.4f",
                        epoch + 1, epochs, avg_train, val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
        else:
            patience_counter += 1
            if patience_counter >= 15:
                logger.info("EarlyStopping en epoch %d", epoch + 1)
                break

    if best_state:
        model.load_state_dict(best_state)
    model.eval()

    # ── Calibración de riesgo ────────────────────────────────────────────
    with torch.no_grad():
        risk_logits = model(X_te)[0]
    ts_risk = calibrate_temperature(risk_logits, y_risk_te)

    return history, ts_risk


# ============================================================================
# 5. EVALUACIÓN
# ============================================================================
def evaluate_model(model, X_test, targets_test, artifacts, ts_risk=None):
    model.eval()
    model.to(DEVICE)
    X_te = torch.tensor(X_test, dtype=torch.float32).to(DEVICE)

    with torch.no_grad():
        r, t, c, s5, s10 = model(X_te)
        if ts_risk is not None:
            r = ts_risk(r)
        risk_probs = torch.softmax(r, dim=1).cpu().numpy()
        risk_pred = np.argmax(risk_probs, axis=1)
        treat_pred = np.argmax(torch.softmax(t, dim=1).cpu().numpy(), axis=1)
        cure_pred = c.cpu().numpy()
        surv5_pred = s5.cpu().numpy()
        surv10_pred = s10.cpu().numpy()

    y_risk = targets_test['risk']
    y_treat = targets_test['treatment']
    y_cure = targets_test['cure_rate']
    y_s5 = targets_test['survival_5y']
    y_s10 = targets_test['survival_10y']

    report: dict = {}
    risk_names = [f"Riesgo_{c}" for c in artifacts['risk_encoder'].classes_]
    logger.info("\n" + "=" * 60)
    logger.info("📊 EVALUACIÓN: NIVEL DE RIESGO")
    logger.info("=" * 60)
    print(classification_report(y_risk, risk_pred, target_names=risk_names))
    report['risk_accuracy'] = float(np.mean(risk_pred == y_risk))

    try:
        auc = roc_auc_score(y_risk, risk_probs, multi_class='ovr', average='weighted')
        report['risk_auc_roc'] = float(auc)
        logger.info("AUC-ROC (weighted): %.4f", auc)
    except Exception:
        report['risk_auc_roc'] = None

    treat_names = [str(c) for c in artifacts['treatment_encoder'].classes_]
    logger.info("💊 EVALUACIÓN: TRATAMIENTO")
    print(classification_report(y_treat, treat_pred, target_names=treat_names, zero_division=0))
    report['treatment_accuracy'] = float(np.mean(treat_pred == y_treat))

    report['cure_rate_mae'] = float(mean_absolute_error(y_cure, cure_pred))
    report['survival_5y_mae'] = float(mean_absolute_error(y_s5, surv5_pred))
    report['survival_10y_mae'] = float(mean_absolute_error(y_s10, surv10_pred))
    violations = int(np.sum(surv10_pred > surv5_pred))
    report['survival_constraint_violations'] = violations

    logger.info("📈 Cure MAE:  %.4f", report['cure_rate_mae'])
    logger.info("📈 Surv5 MAE: %.4f", report['survival_5y_mae'])
    logger.info("📈 Surv10 MAE: %.4f", report['survival_10y_mae'])
    logger.info("⚕️  Constraint violations: %d/%d", violations, len(surv5_pred))
    return report


# ============================================================================
# 6. VALIDACIÓN DE INPUTS
# ============================================================================
VALID_RANGES: dict[str, tuple] = {
    'age':                      (18, 120),
    'psa':                      (0.0, 5000.0),
    'ecog':                     (0, 4),
    'stage':                    (1, 4),
    'gleason':                  (6, 10),
    'cci':                      (0, 20),
    'isup_grade':               (1, 5),
    'pirads':                   (1, 5),
    'pct_cores_positive':       (0.0, 1.0),
    'num_cores_positive':       (0, 30),
    'total_cores':              (1, 30),
    'max_core_involvement':     (0.0, 1.0),
    'perineural_invasion':      (0, 1),
    'lymphovascular_invasion':  (0, 1),
    'surgical_margin_status':   (0, 1),
    'family_history':           (0, 1),
    'bmi':                      (10.0, 70.0),
    'testosterone':             (0.0, 2000.0),
    'free_psa_ratio':           (0.01, 1.0),
    'previous_biopsies':        (0, 20),
    'genomic_score':            (0.0, 1.0),
}

REQUIRED_FIELDS = ['age', 'psa', 'ecog', 'stage', 'gleason', 'cci',
                   'isup_grade', 'pirads', 'pct_cores_positive',
                   'num_cores_positive', 'total_cores', 'max_core_involvement',
                   'perineural_invasion', 'lymphovascular_invasion',
                   'surgical_margin_status', 'race_ethnicity', 'dre_findings',
                   'family_history', 'bmi', 'testosterone', 'free_psa_ratio',
                   'previous_biopsies', 'genomic_score']


def validate_patient_input(data: dict) -> list[str]:
    """Retorna lista de errores; vacía si los datos son válidos."""
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"Campo requerido faltante: '{field}'")
    for field, value in data.items():
        if field in VALID_RANGES:
            lo, hi = VALID_RANGES[field]
            if not (lo <= value <= hi):
                errors.append(f"'{field}' = {value} fuera de rango [{lo}, {hi}]")
    return errors


# ============================================================================
# 7. PREDICCIÓN
# ============================================================================
def predict_patient(model, artifacts, patient_data: dict,
                    ts_risk: TemperatureScaling | None = None) -> dict:
    # ── Validación de entrada ────────────────────────────────────────────
    errors = validate_patient_input(patient_data)
    if errors:
        raise ValueError("Datos de paciente inválidos:\n  • " + "\n  • ".join(errors))

    df = pd.DataFrame([patient_data])
    if 'psad' not in df.columns or pd.isna(df['psad'].iloc[0]):
        df['psad'] = df['psa'] / patient_data.get('volumen_prostatico', 40)
    df['psa_log'] = np.log1p(df['psa'])

    encoded = artifacts['encoder'].transform(df[artifacts['cat_cols']].astype(str))
    scaled = artifacts['scaler'].transform(df[artifacts['num_cols']])
    X = np.concatenate([scaled, encoded], axis=1)

    model.eval()
    model.to(DEVICE)
    with torch.no_grad():
        x_t = torch.tensor(X, dtype=torch.float32).to(DEVICE)
        r, t, c, s5, s10 = model(x_t)
        if ts_risk is not None:
            r = ts_risk(r)
        risk_probs = torch.softmax(r, dim=1).cpu().numpy()[0]
        treat_probs = torch.softmax(t, dim=1).cpu().numpy()[0]
        cure = float(c.cpu().numpy()[0])
        surv5 = float(s5.cpu().numpy()[0])
        surv10 = min(float(s10.cpu().numpy()[0]), surv5)

    risk_classes = artifacts['risk_encoder'].classes_
    treat_classes = artifacts['treatment_encoder'].classes_
    risk_labels = {0: "BAJO", 1: "INTERMEDIO", 2: "ALTO"}

    return {
        "riesgo": {
            "nivel": risk_labels.get(risk_classes[np.argmax(risk_probs)], "?"),
            "probabilidades": {risk_labels.get(int(c), str(c)): f"{p:.1%}"
                               for c, p in zip(risk_classes, risk_probs)}
        },
        "tratamiento_recomendado": {
            "principal": str(treat_classes[np.argmax(treat_probs)]),
            "probabilidades": {str(c): f"{p:.1%}"
                               for c, p in zip(treat_classes, treat_probs)}
        },
        "tasa_curacion": f"{cure:.1%}",
        "supervivencia_5_anios": f"{surv5:.1%}",
        "supervivencia_10_anios": f"{surv10:.1%}",
    }


# ============================================================================
# 8. PERSISTENCIA
# ============================================================================
def save_all(model, artifacts, report, ts_risk=None, output_dir=None):
    out = output_dir or OUTPUT_DIR
    os.makedirs(out, exist_ok=True)
    torch.save(model.state_dict(), os.path.join(out, "model_weights.pt"))
    meta = {
        'input_dim': model.shared[0].in_features,
        'n_risk': model.risk_head.out_features,
        'n_treatment': model.treatment_head.out_features,
        'hidden_dims': model.hidden_dims,
        'training_date': datetime.now().isoformat(),
        'seed': SEED,
    }
    save_data: dict = {'artifacts': artifacts, 'model_meta': meta}
    if ts_risk is not None:
        save_data['ts_risk_state'] = ts_risk.state_dict()
    joblib.dump(save_data, os.path.join(out, "artifacts.pkl"))
    with open(os.path.join(out, "evaluation_report.json"), "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info("✅ Modelo y artefactos guardados en %s", out)


def load_all(output_dir=None):
    out = output_dir or OUTPUT_DIR
    data = joblib.load(os.path.join(out, "artifacts.pkl"))
    meta = data['model_meta']
    hidden_dims = meta.get('hidden_dims', [64, 128, 64])
    model = ProstateCancerNet(meta['input_dim'], meta['n_risk'], meta['n_treatment'],
                              hidden_dims=hidden_dims)
    model.load_state_dict(torch.load(os.path.join(out, "model_weights.pt"), weights_only=True))
    model.eval()
    ts_risk = None
    if 'ts_risk_state' in data:
        ts_risk = TemperatureScaling()
        ts_risk.load_state_dict(data['ts_risk_state'])
    return model, data['artifacts'], ts_risk


# ============================================================================
# 9. MAIN — Cross-validation (StratifiedKFold)
# ============================================================================
def _pack_targets(y_risk, y_treatment, cure, s5, s10):
    return {
        'risk': y_risk, 'treatment': y_treatment,
        'cure_rate': cure, 'survival_5y': s5, 'survival_10y': s10,
    }


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("  Modelo Multi-Output — Cáncer de Próstata (v2)")
    logger.info("  Device: %s", DEVICE)
    logger.info("=" * 60)

    # 1. Generar datos
    df = generate_synthetic_data(3000)
    logger.info("Dataset: %d muestras, %d columnas", *df.shape)

    # 2. Preprocesar
    X, y_risk, y_treat, cure, s5, s10, artifacts = preprocess_data(df)
    logger.info("Features: %d", X.shape[1])

    # 3. Cross-validation (StratifiedKFold 3 folds sobre riesgo)
    N_FOLDS = 3
    skf = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)
    fold_reports: list[dict] = []

    for fold, (train_idx, test_idx) in enumerate(skf.split(X, y_risk), 1):
        logger.info("\n🔁 FOLD %d/%d", fold, N_FOLDS)

        X_train, X_test = X[train_idx], X[test_idx]
        targets_train = _pack_targets(y_risk[train_idx], y_treat[train_idx],
                                      cure[train_idx], s5[train_idx], s10[train_idx])
        targets_test = _pack_targets(y_risk[test_idx], y_treat[test_idx],
                                     cure[test_idx], s5[test_idx], s10[test_idx])

        model = ProstateCancerNet(
            input_dim=X.shape[1],
            n_risk=len(np.unique(y_risk)),
            n_treatment=len(np.unique(y_treat)),
            hidden_dims=[64, 128, 128, 64],
            dropout=0.25,
        )
        history, ts_risk = train_model(model, X_train, X_test,
                                       targets_train, targets_test,
                                       epochs=120, batch_size=64)
        report = evaluate_model(model, X_test, targets_test, artifacts, ts_risk)
        report['fold'] = fold
        fold_reports.append(report)

    # 4. Métricas promediadas
    avg_report: dict = {}
    metric_keys = ['risk_accuracy', 'risk_auc_roc', 'treatment_accuracy',
                   'cure_rate_mae', 'survival_5y_mae', 'survival_10y_mae',
                   'survival_constraint_violations']
    for k in metric_keys:
        vals = [r[k] for r in fold_reports if r.get(k) is not None]
        avg_report[k] = float(np.mean(vals)) if vals else None

    logger.info("\n" + "=" * 60)
    logger.info("📊 MÉTRICAS PROMEDIADAS (%d folds)", N_FOLDS)
    logger.info("=" * 60)
    for k, v in avg_report.items():
        logger.info("  %-35s %s", k, f"{v:.4f}" if v is not None else "N/A")

    # 5. Entrenar modelo final con ALL data (80/20 para calibración)
    logger.info("\n🏁 Entrenando modelo final con todo el dataset…")
    X_tr, X_cal, idx_tr, idx_cal = train_test_split(
        X, np.arange(len(X)), test_size=0.2, random_state=SEED, stratify=y_risk)
    targets_tr = _pack_targets(y_risk[idx_tr], y_treat[idx_tr],
                               cure[idx_tr], s5[idx_tr], s10[idx_tr])
    targets_cal = _pack_targets(y_risk[idx_cal], y_treat[idx_cal],
                                cure[idx_cal], s5[idx_cal], s10[idx_cal])

    final_model = ProstateCancerNet(
        input_dim=X.shape[1],
        n_risk=len(np.unique(y_risk)),
        n_treatment=len(np.unique(y_treat)),
        hidden_dims=[64, 128, 128, 64],
    )
    h_final, ts_risk_final = train_model(final_model, X_tr, X_cal,
                                         targets_tr, targets_cal,
                                         epochs=120, batch_size=64)
    final_report = evaluate_model(final_model, X_cal, targets_cal, artifacts, ts_risk_final)
    final_report['cv_average'] = avg_report
    final_report['folds'] = fold_reports

    # 6. Guardar
    save_all(final_model, artifacts, final_report, ts_risk_final)

    # 7. Predicción de ejemplo
    logger.info("\n🧪 Predicción de ejemplo:")
    ejemplo = {
        'age': 68, 'psa': 12.5, 'ecog': 1, 'stage': 2,
        'gleason': 7, 'cci': 1, 'psad': 0.31,
        'isup_grade': 2, 'pirads': 4,
        'pct_cores_positive': 0.35,
        'num_cores_positive': 4, 'total_cores': 12,
        'max_core_involvement': 0.45,
        'perineural_invasion': 1, 'lymphovascular_invasion': 0,
        'surgical_margin_status': 0,
        'race_ethnicity': 'hispano', 'dre_findings': 'T2a',
        'family_history': 0, 'bmi': 28.5,
        'testosterone': 380.0, 'free_psa_ratio': 0.15,
        'previous_biopsies': 1, 'genomic_score': 0.42,
    }
    result = predict_patient(final_model, artifacts, ejemplo, ts_risk_final)
    logger.info(json.dumps(result, indent=2, ensure_ascii=False))

    logger.info("\n✅ Pipeline completo finalizado.")
