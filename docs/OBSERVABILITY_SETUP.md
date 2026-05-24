# Observability Setup — Rate Limit + Prometheus

> Sprint 7.C · FAUBOT CXLV · Operational monitoring para producción

## Por qué

ProstaNet en producción multi-sitio necesita:
- **Detección temprana** de degradación de performance (Grafana SLO alerts)
- **Bloqueo de abuse** intencional/accidental (loop infinito de polling)
- **Capacity planning** con métricas reales (qué endpoint consume más)
- **SaMD post-market surveillance** automatizada (FDA aprecia)

Sin esto, los problemas se descubren cuando un clínico reporta lentitud
o cuando un attacker brute-forcea por horas sin detectarse.

---

## Instalación

```bash
pip install prometheus_client flask-limiter
```

Activación via env vars:
```bash
export PROSTANET_METRICS_ENABLED=1
export PROSTANET_RATE_LIMIT_ENABLED=1
# Opcional: storage para limiter en cluster multi-instance
export PROSTANET_RATE_LIMIT_STORAGE=redis://localhost:6379
```

Si las libs no están instaladas o flags off → módulo degrada a no-op,
código existente sigue corriendo idéntico.

---

## Endpoints expuestos

### `GET /metrics`
Formato Prometheus exposition. Scraping de Prometheus server cada 15-60s.

```bash
curl http://localhost:8080/metrics
```

Métricas:
| Nombre | Tipo | Labels | Uso |
|---|---|---|---|
| `prostanet_api_requests_total` | counter | endpoint, method, status_class | tráfico + error rate |
| `prostanet_api_request_duration_seconds` | histogram | endpoint, method | latencia p50/p95/p99 |
| `prostanet_ml_inference_total` | counter | model, status | success/error rate por modelo ML |
| `prostanet_ml_inference_duration_seconds` | histogram | model | latencia ML por modelo |
| `prostanet_godibot_findings_total` | counter | status | trend findings (approved/warnings/blocked) |
| `prostanet_audit_log_failures_total` | counter | section_key | **REGULATORY signal** — alertar si >0 |
| `prostanet_auth_attempts_total` | counter | backend, outcome | brute force detection |
| `prostanet_oidc_provisions_total` | counter | — | JIT provisions OIDC |
| `prostanet_active_sessions` | gauge | — | usuarios concurrentes |
| `prostanet_db_query_duration_seconds` | histogram | query_kind | DB hotspots |

### `GET /health`
Liveness probe sin auth. Always 200 si Flask está up. Útil para load balancer.

```json
{
  "status": "healthy",
  "metrics_enabled": true,
  "rate_limit_enabled": true,
  "faubot_release": "2026-05-24 CXLV"
}
```

---

## Rate limits default

| Endpoint type | Default limit | Configurable via |
|---|---|---|
| All | 1000/min/user_id + 10k/hour | `default_limits` en `observability.py` |
| Per-endpoint custom | (puede sobreescribirse) | decorator `@limiter.limit("100/min")` en handler |

Key function: per-user_id si autenticado, sino per-IP.

---

## SLO recomendados (Grafana)

Crear alerting rules en `prometheus.yml`:

```yaml
groups:
  - name: prostanet_slos
    interval: 30s
    rules:
      - alert: ProstaNetHighErrorRate
        expr: |
          sum(rate(prostanet_api_requests_total{status_class="5xx"}[5m]))
          / sum(rate(prostanet_api_requests_total[5m])) > 0.01
        for: 5m
        annotations:
          summary: ">1% 5xx rate over 5 minutes"

      - alert: ProstaNetTrajectoryLatencyHigh
        expr: |
          histogram_quantile(0.99,
            rate(prostanet_api_request_duration_seconds_bucket{endpoint=~"api_trajectory.*"}[5m])
          ) > 0.5
        for: 5m
        annotations:
          summary: "p99 trajectory > 500ms"

      - alert: ProstaNetMLModelDown
        expr: |
          rate(prostanet_ml_inference_total{status="load_error"}[10m]) > 0
        for: 10m
        annotations:
          summary: "ML model failing to load"

      - alert: ProstaNetAuditLogFailing
        expr: increase(prostanet_audit_log_failures_total[1h]) > 0
        for: 0s
        annotations:
          summary: "REGULATORY: audit log inserts failing (§820.30 violation)"

      - alert: ProstaNetBruteForceAttempt
        expr: |
          sum by (backend) (
            rate(prostanet_auth_attempts_total{outcome=~"denied.*"}[1m])
          ) > 5
        for: 2m
        annotations:
          summary: "Brute force attempt detected (>5/min denied auth)"
```

---

## Grafana dashboard JSON

(Pendiente — incluir como artifact en `docs/grafana/prostanet_dashboard.json`
exportado de Grafana después de configurar visualmente)

---

## Instrumentación de código

Decorator para handlers:

```python
from prostanet.shared.observability import instrument_handler

@bp.route("/api/foo")
@instrument_handler("api_foo")
def my_handler():
    ...
```

Incrementadores directos:

```python
from prostanet.shared.observability import (
    inc_ml_inference, observe_ml_duration,
    inc_godibot_finding, inc_audit_failure,
)

import time
start = time.monotonic()
result = predict_treatment_response(patient_id, record)
observe_ml_duration("treatment_response", time.monotonic() - start)
inc_ml_inference("treatment_response", "success")
```

---

## Rate limit per-endpoint custom

```python
from flask import current_app

@bp.route("/api/expensive-op", methods=["POST"])
def expensive():
    limiter = current_app.extensions.get("prostanet_limiter")
    if limiter:
        # decorator dinámico
        @limiter.limit("10 per minute")
        def _impl():
            return do_work()
        return _impl()
    return do_work()
```

(En la práctica, usar el decorator estático cuando posible; el dinámico
es para casos donde el limit depende de runtime config.)

---

## Beneficios esperados

| Dimensión | Beneficio |
|---|---|
| **Operacional** | Rate limit previene saturación. Métricas detectan degradación. |
| **Regulatorio** | SaMD post-market surveillance automatizada. Audit failures alertan §820.30 compliance gaps. |
| **Seguridad** | Brute force detection. OIDC provision trend monitoreo. |
| **Capacity planning** | Tendencias temporales reales por endpoint → priorizar caching/escalado. |
| **Research** | Counters por section_key alimentan analytics cohort (qué usa el clínico realmente). |
