# Reporte de Auditoría de Seguridad — ProstaMed CDE Auditable (Faubot #23–#36)

**Alcance:** Archivos NUEVOS introducidos por las auditorías Faubot #23–#36 + sus puntos de integración (rutas Flask, templates Jinja).
**Stakeholders:** Tech leadership, regulatorio (SaMD), seguridad (HIPAA / COFEPRIS NOM-024).
**Fecha:** 2026-04-25 (al cierre del Plan de Adopción AutoSkills, Paso 3.A)

## Veredicto ejecutivo

**NO APTO para beta clínica controlada en su estado actual.** Los archivos NUEVOS están bien diseñados (helpers puros, `yaml.safe_load`, sin secretos, sin SQL injection, sin XSS introducido). Sin embargo, los exponen sobre una **superficie HTTP sin autenticación, sin CSRF, sin rate-limit y sin TLS termination explícito**, expuesta al `0.0.0.0:8080`. La consecuencia es que un endpoint nuevo (`/api/decision-audit/<patient_ref>`) hace fácilmente exfiltrable el **expediente completo** de cualquier paciente cuyo NSS o ID se conozca o adivine. Los hallazgos críticos están todos en la capa de plataforma, no en la lógica clínica.

---

## 1. CRÍTICOS (P0 — bloquean beta clínica)

### CRIT-1 — Exposición masiva de PHI sin autenticación en `/api/decision-audit/<patient_ref>`
- **Archivo:** `prostanet/presentation/api.py:280-333` (endpoint) + `prostanet/shared/decision_audit_builder.py:97-118` (builder `_build_datos_dimension`).
- **Descripción:** El endpoint retorna `patient_identity = {id, nss, full_name}` (líneas 312-316) **más** `audit_dimensions.datos.input_snapshot` que es el **payload clínico completo** sin filtrado: PSA, Gleason, comorbilidades, medicaciones, antecedentes oncológicos, etc. (`decision_audit_builder.py:113` `"input_snapshot": _normalize_value(input_snapshot or {})` no aplica allowlist). No hay `@login_required`, no hay verificación de identidad del solicitante, y el path acepta NSS o `id` numérico (`tracking_db.py:683-693`) — IDs numéricos son trivialmente enumerables (1, 2, 3...).
- **Impacto:** Cualquier persona con red al servicio puede hacer `for i in range(1,10000): GET /api/decision-audit/$i` y exfiltrar el dataset completo de pacientes. Violación directa de HIPAA §164.502 (mínimo necesario), COFEPRIS NOM-024 (consentimiento + autenticación) y LFPDPPP arts. 14, 19 y 21 (datos sensibles de salud).
- **Remediación (debe completarse antes de beta):**
  1. Añadir un decorador `@require_clinical_session` que valide token JWT firmado o sesión Flask + ABAC (`patient_id ∈ panel_clinico(user_id)`).
  2. Sanear el payload del audit: en `decision_audit_builder._build_datos_dimension`, sustituir `input_snapshot` por un resumen de claves capturadas + tipos (no valores), o por un hash determinista de cada valor para reproducibilidad sin exposición.
  3. Considerar omitir `nss` y `full_name` del response y exponer solo el `assessment_id` + un `patient_token` derivado opaco.
  4. Logging de acceso (quién, cuándo, qué `patient_ref`) en tabla `audit_log` separada.

### CRIT-2 — Toda la API y la UI carecen de autenticación, sesión y CSRF
- **Archivo:** `app.py` (ausencia de `app.secret_key`, `flask_login`, `flask_wtf.CSRFProtect`, `flask_talisman`); `prostanet/presentation/bootstrap.py:9-13` registra los blueprints sin middleware de auth.
- **Descripción:** Búsqueda exhaustiva en `app.py` y `presentation/*.py`: cero coincidencias para `secret_key`, `csrf`, `login_required`, `before_request`, `talisman`, `cors`. Más de 80 rutas (incluyendo POSTs a `/api/register_patient`, `/api/biopsy/<patient_id>`, `/api/genomics/<patient_id>`, `/api/active_surveillance/<patient_id>/exit`, `/api/patients/<id>` `DELETE`) son completamente abiertas. El servidor escucha en `app.py:1932` `app.run(host="0.0.0.0", port=8080)`.
- **Impacto:** (a) Ataque CSRF trivial (formulario externo borra pacientes con `DELETE /api/patients/<id>`); (b) acceso anónimo a toda la cohorte; (c) imposibilidad de cumplir requisitos SaMD §820.30 (Design Controls) y HIPAA §164.312 (acceso técnico).
- **Remediación:**
  1. Añadir `app.secret_key = os.environ["PROSTANET_SECRET_KEY"]` (sin default, para forzar configuración).
  2. Integrar `Flask-Login` o `Authlib` (OIDC) y aplicarlo como `@app.before_request`.
  3. `Flask-WTF CSRFProtect` para todas las POST/DELETE/PUT.
  4. `Flask-Talisman` con HSTS, CSP `default-src 'self'`, `X-Frame-Options: DENY`.
  5. Servir detrás de un reverse-proxy con TLS (no exponer Flask directo); o como mínimo cambiar `host` a `127.0.0.1` y exigir túnel.

### CRIT-3 — Dashboard `/api/gates-coverage-dashboard` revela telemetría poblacional sin auth
- **Archivo:** `prostanet/presentation/api.py:340-369`; agregador `prostanet/shared/gates_coverage_aggregator.py:159-419`.
- **Descripción:** Aunque el agregador NO retorna identificadores individuales (solo conteos por gate y por estado), expone: `total_assessments`, distribución por estado clínico, y `field_capture_coverage` que filtra `qtc_ms`, `lvef_percent`, etc. Sin auth, un competidor o atacante puede polleo periódico para inferir tamaño/composición/tasa de captura de la cohorte. Combinado con CRIT-1 puede usarse para scoping del ataque enumerativo.
- **Remediación:** Aplicar mismo middleware de auth de CRIT-2 + restringir a rol `auditor` o `compliance_officer`.

### CRIT-4 — Exposición de excepciones sin sanitizar (`error_response(str(exc), 500)`)
- **Archivo:** `prostanet/presentation/api.py:329-333` (endpoint decision-audit), `:368-369` (gates-coverage), `app.py:493-494, 521-522, 552-554` (varios).
- **Descripción:** El catch-all `except Exception as exc` retorna `str(exc)` al cliente. SQLite, Python, traceback strings pueden filtrar nombres de tablas, paths absolutos, versiones de bibliotecas (info para un atacante).
- **Remediación:** Sustituir por `return jsonify({"success": False, "error": "internal_error", "trace_id": <uuid4>}), 500` y registrar `exc` en el logger junto al `trace_id`.

---

## 2. ALTOS (P1 — corregir antes de beta)

### ALT-1 — `nss` y `full_name` viajan en respuesta JSON sin necesidad
- **Archivo:** `prostanet/presentation/api.py:312-316`.
- **Descripción:** El comentario dice "sin PHI sensible más allá de lo necesario" pero `full_name` + `nss` son identificadores directos HIPAA-clase. Si el consumidor de `/api/decision-audit` es solo el clínico tratante, basta con un `display_label` derivado.
- **Remediación:** Reducir `patient_identity` a `{display_label}` o, si se requieren para reconciliación, marcarlos en una sub-clave `restricted_phi: true` y exigir scope `phi:read`.

### ALT-2 — Sin rate-limiting en endpoints de lectura
- **Archivo:** Toda la API (sin Flask-Limiter ni equivalente).
- **Descripción:** Sin rate-limit, los endpoints son enumerables por `patient_id` (1..N) en segundos. Aún con auth, el rate-limit reduce daño de tokens robados.
- **Remediación:** `Flask-Limiter` con cuotas por user/IP (e.g., 60 req/min para audit endpoints).

### ALT-3 — `validate_yaml_gate_config()` existe pero **no se invoca** durante carga
- **Archivo:** `prostanet/shared/pivotal_gates_yaml_loader.py:370-398` (`_load_yaml_files`) vs `:511-559` (`validate_yaml_gate_config`).
- **Descripción:** El loader hace `yaml.safe_load()` y mete el dict en cache sin pasar por `validate_yaml_gate_config()`. Un YAML mal formado o malicioso (e.g., con `severity: hacker`, `trigger.type` desconocido, claves inesperadas) se cargaría silenciosamente y `evaluate_yaml_gate` retornaría `None` en lugar de fallar. Para un Clinical Decision Engine, **fallar silencioso = fallar abierto**: una regla clínica que debió disparar puede desaparecer sin alerta.
- **Remediación:** En `_load_yaml_files`, llamar `validate_yaml_gate_config(config)` antes de cachear; si retorna errores, **rechazar el gate y emitir log de error nivel CRITICAL** con `gate_code` + `errors`. Considerar fallar el arranque del proceso (`fail-closed`) si algún YAML del catálogo es inválido.

### ALT-4 — Cache de YAML compartida entre tests/runtime sin invalidación por mtime
- **Archivo:** `prostanet/shared/pivotal_gates_yaml_loader.py:366-398`.
- **Descripción:** `_YAML_CACHE` es un global de módulo. Si un operador edita un YAML del catálogo en caliente, no se recarga hasta reinicio. Para una **regla clínica regulada**, la falta de mecanismo de hot-reload + checksum continuo permite drift no detectado entre el SHA reportado por `algorithm_version.get_per_gate_yaml_shas()` y el SHA realmente evaluado.
- **Remediación:** Cachear `mtime` por archivo; invalidar entry si `mtime` cambió.

### ALT-5 — `subprocess`-style template strings en SQL (defensa en profundidad)
- **Archivo:** `tracking_db.py:611, 613` (`PRAGMA table_info({table_name})`, `DELETE FROM {table_name} WHERE patient_id = ?`).
- **Descripción:** Aunque `table_name` viene de `sqlite_master` (DB-controlado, no usuario), el patrón `f"DELETE FROM {table_name}"` se acerca peligrosamente a inyección si alguien añade en el futuro una ruta que reciba `table_name` de un payload.
- **Remediación:** `if table_name not in ALLOWED_PATIENT_CHILD_TABLES: continue`.

### ALT-6 — `decision_audit` filtra `audit_dimensions.evidencia.guideline_versions` y `nccn_primary` sin filtro de versión confidencial
- **Archivo:** `prostanet/shared/decision_audit_builder.py:121-159`.
- **Descripción:** Si en futuro se incluyen versiones internas de guías (no publicadas) en `guideline_versions`, viajarían sin redacción.
- **Remediación:** Allowlist de campos en cada `_build_*_dimension`; o validador de schema sobre el output.

---

## 3. MEDIOS (P2 — hardening recomendado)

### MED-1 — Sin Content-Security-Policy en templates
- **Archivos:** `templates/patient_profile.html` (~9268 líneas, mucho `innerHTML` en JS), `templates/gates_coverage_dashboard.html`.
- **Remediación:** Adjuntar Talisman con CSP estricta + reemplazar `innerHTML` por `textContent` o usar `DOMPurify`.

### MED-2 — Tailwind class interpolation con datos del backend
- **Archivo:** `templates/patient_profile.html:4665, 4669, 4672, 4722, 4724` — patrón `bg-{{ gate.severity_color }}-500/30`.
- **Remediación:** En `_severity_color` añadir un `assert s in {"rose","amber","orange","slate"}` final.

### MED-3 — `requirements.txt` sin pins de versión
- **Archivo:** `requirements.txt` (8 líneas, todas sin versión).
- **Remediación:** Generar `requirements.txt` pinned con `pip-compile` (pip-tools), añadir `pyyaml>=6.0.1`, `flask>=3.0.3`, `jinja2>=3.1.4`, `werkzeug>=3.0.3`, configurar Dependabot/Renovate.

### MED-4 — `decision_audit_builder._normalize_value` recursión sin límite de profundidad
- **Archivo:** `prostanet/shared/decision_audit_builder.py:36-46`.
- **Remediación:** Añadir `_normalize_value(v, depth=0, max_depth=20)`.

### MED-5 — `gates_coverage_aggregator.aggregate_gates_coverage_from_db` carga TODOS los assessments sin paginación
- **Archivo:** `prostanet/shared/gates_coverage_aggregator.py:438-468`.
- **Remediación:** Cachear el resultado por 5–10 min; añadir rate-limit; o pre-computar offline.

### MED-6 — Excepciones genéricas swallowed sin telemetría
- **Archivo:** Múltiples archivos.
- **Remediación:** Sustituir por `except Exception as exc: logger.warning("...")`.

### MED-7 — Path absoluto del DB derivado de env var sin validación
- **Archivo:** `app.py:53`.
- **Remediación:** Validar que el path está dentro de un directorio configurable.

---

## 4. POSITIVOS (controles bien hechos — preservar)

| # | Control | Evidencia |
|---|---------|-----------|
| POS-1 | `yaml.safe_load` correctamente usado | `pivotal_gates_yaml_loader.py:388` (no `yaml.load`) |
| POS-2 | SQL parametrizado en todas las queries del aggregator nuevo | `gates_coverage_aggregator.py:442-449`, `tracking_db.py:683-693` (`?` placeholders) |
| POS-3 | Path traversal infactible en YAML loader | `CATALOG_DIR` hardcoded; `glob("*.yaml")` no recursivo |
| POS-4 | Sin secretos hardcoded en archivos NUEVOS | grep contra `password|api_key|secret|token|aws_|sk-` retorna 0 hits |
| POS-5 | `debug=False` en `app.run` | `app.py:1932` — no expone Werkzeug debugger |
| POS-6 | Funciones puras sin side-effects en helpers críticos | decision_audit_builder, gates_ddi_cross_check, pivotal_gate_delta, algorithm_version |
| POS-7 | Jinja2 autoescape activo (default Flask para `.html`) | XSS server-side mitigado |
| POS-8 | Lazy imports para evitar circulares + degradación graciosa | `apply_pivotal_contraindication_gates` cae a `pass` si `gates_ddi_cross_check` no está |
| POS-9 | Versionado granular per-gate con SHA-256 | `algorithm_version.get_per_gate_yaml_shas()` — cumple criterio FDA SaMD §IV.B.4 |
| POS-10 | `evaluate_yaml_gate` retorna `None` ante config malformado | Coexiste seguro con sistema híbrido Python+YAML |
| POS-11 | DDI cross-check NO produce falsos positivos cuando faltan medicaciones | `gates_ddi_cross_check.py:200-202` retorna `[]` si `meds` vacío |
| POS-12 | `.gitignore` excluye `*.db`, `*.log`, `__pycache__` | Reduce riesgo de leaks accidentales |

---

## 5. Resumen accionable para tech leadership

| Severidad | Hallazgos | Estado para beta clínica |
|-----------|-----------|--------------------------|
| **CRÍTICOS (P0)** | 4 (CRIT-1..4) | **BLOQUEAN beta — todos relacionados con autenticación/exposición PHI** |
| **ALTOS (P1)** | 6 (ALT-1..6) | Corregir antes de beta; ALT-3 y ALT-4 son críticos para preservar la dimensión VERSIÓN del scorecard CDE Auditable |
| **MEDIOS (P2)** | 7 (MED-1..7) | Hardening recomendado para piloto multi-sitio o cualquier despliegue público |
| **POSITIVOS** | 12 controles bien implementados — el diseño defensive-by-default de los helpers nuevos es ejemplar |

### Hoja de ruta recomendada (orden de implementación)
1. **Semana 1 (BLOQUEANTE):** CRIT-2 (auth + CSRF + Talisman + reverse-proxy TLS) + CRIT-1 (PHI scrubbing del audit endpoint) + CRIT-4 (sanitización de excepciones).
2. **Semana 2:** CRIT-3 (auth en dashboard) + ALT-1 (reducir identity payload) + ALT-3 (validación YAML al cargar) + ALT-4 (cache mtime).
3. **Semana 3 (hardening pre-beta):** ALT-2 (rate-limit), ALT-5 (allowlist tablas), ALT-6 (validador schema audit).
4. **Continuo:** MED-3 (pinning + Dependabot), MED-1 (CSP), MED-6 (logging de excepciones swallowed).

**Conclusión SaMD/HIPAA:** Los archivos NUEVOS de las auditorías Faubot #23–#36 son de **alta calidad de seguridad intrínseca** — no introducen vulnerabilidades nuevas en su lógica. Sin embargo, el sistema host (Flask `app.py`) carece de los controles de plataforma exigidos por HIPAA §164.312 y NOM-024-SSA3. Los hallazgos críticos son **superficie de exposición**, no defectos de los nuevos componentes. La remediación de los P0 es de alcance acotado (~2 semanas-equivalente) y, una vez aplicada, el CDE Auditable estará en posición sólida para beta clínica controlada.
