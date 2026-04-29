# IEC 62304 Software Safety Class Assignment — ProstaMed

> **Estándar**: IEC 62304:2006/AMD 1:2015 — *Medical device software — Software life cycle processes*.

---

## Asignación oficial

**ProstaMed/ProstaNet** se clasifica como **Software Safety Class B** bajo
IEC 62304 §4.3.

### Justificación

Per IEC 62304 §4.3 (clases A/B/C):

- **Class A**: No injury or damage to health is possible.
- **Class B**: Non-serious injury is possible. ✅ **ProstaMed**
- **Class C**: Death or serious injury is possible.

ProstaMed da recomendaciones clínicas que el clínico revisa antes de actuar.
El sistema NO administra fármacos ni controla dispositivos hardware. El peor
escenario realista es:

1. Recomendación incorrecta de tratamiento (e.g., omisión de PARP inhibitor
   por test HRR no realizado) → retraso en tratamiento óptimo, NO muerte
   inmediata. Mitigado por gates pivotales (e.g., G61 HRR HARD_BLOCK).
2. Falsa clasificación de riesgo (e.g., D'Amico low cuando es intermediate) →
   subtratamiento, mitigado por revisión humana.
3. Falla de captura longitudinal → decisión stale, mitigada por gate `data_freshness_severity`.

NINGUNO de estos escenarios → muerte directa por falla del software (Class C
threshold).

---

## Componentes que pueden escalar a Class C

Durante refinamiento de FMEA (Pilar 4), los siguientes módulos son candidatos
a re-clasificación a Class C si análisis revela riesgo de muerte:

| Módulo | Posible escalación | Razón |
|--------|---|-----|
| `prostanet/shared/dose_calculation.py` | Class B → C | Si cálculo de dosis taxano o bone-modifying tiene unit-mismatch que cause overdose |
| `prostanet/agentic/improvement_loop.py` (auto-merge) | Class B → C | Si auto-merge introduce regresión clínica que retrase decisión crítica |

Estos serán evaluados formalmente en FMEA (`prostanet/regulatory/risk/fmea-prostanet-2026.yaml`).

---

## Implicaciones IEC 62304 Class B

Bajo Class B, ProstaMed debe ejecutar (per §5):

- §5.1 Software development planning (ver `sdp_software_development_plan.md`)
- §5.2 Software requirements analysis (SRS = `prostanet/CLINICAL_EVIDENCE_2026.md`)
- §5.3 Software architectural design
- §5.4 Software detailed design (per-module)
- §5.5 Software unit implementation and verification (tests/test_*.py)
- §5.6 Software integration and integration testing
- §5.7 Software system testing (smoke E2E + Playwright suite LXXXVIII)
- §5.8 Software release (FAUBOT_RELEASE versioning)
- §6 Software maintenance process (audit_tracking.md + CHANGELOG)
- §7 Software risk management (Pilar 4 FMEA + ISO 14971)
- §8 Software configuration management (git + tags)
- §9 Software problem resolution (CAPA SOP)

**Class A NO sería viable** — ProstaMed sí puede causar lesión no-seria
(retraso de tratamiento por recomendación incorrecta no detectada por clínico).

---

## Segregación arquitectónica

Per IEC 62304 §4.4, segregación permite bajar la clase efectiva de componentes
no críticos. ProstaMed segregará:

- **Class B core**: motor de decisión clínica (`prostanet/domains/`, gates, audit).
- **Class A periphery**: dashboards de admin, versioning UI, demos, intake widgets
  (no toman decisiones clínicas, solo display/forms).

Documentación de segregación: pendiente en LXXXVIII iteración +N (FDA SaMD loop
producirá architectural diagram).

---

**Versión**: 1.0 · 2026-04-27 (Faubot LXXXVIII bootstrap)
**Aprobado por**: pendiente firma regulatorio + ingeniería + clínico.
**Próxima revisión**: tras FMEA Pilar 4 completo (15+ peligros analizados).
