# ProstaNet World-Class Platform Plan

Fecha de analisis: 2026-05-28

## Tesis

ProstaNet se ha movido de una app de recomendaciones a un sistema operativo clinico especializado en cancer de prostata. La direccion correcta ya no es "agregar mas modulos"; es convertir lo existente en una plataforma confiable, longitudinal, interoperable, auditable y capaz de producir inteligencia clinica, economica, asistencial, demografica y de investigacion.

La regla de oro queda fijada: antes de nueva logica clinica debe existir evidencia de que los hechos criticos se capturan una sola vez, persisten bien, se reutilizan en UI/backend y alimentan `DECISION HOY`, seguimiento, auditoria y cohortes.

## Alineacion con vision NAS Urologia

Fuente local analizada: `/Users/oscaralvarado/Downloads/Sistema NAS Urologia.docx`.

El documento NAS redefine el marco institucional de ProstaMed. La plataforma no debe crecer como una app aislada, sino como la capa activa de una infraestructura local de datos clinicos para el Servicio de Urologia del HE CMN La Raza. El NAS no es solo almacenamiento: es el entorno fisico-operativo donde ProstaMed debe correr, custodiar datos, auditar accesos, producir evidencia y sostener investigacion prospectiva.

Objetivos institucionales que quedan incorporados al roadmap:

- Recopilar datos clinicos estructurados de todos los pacientes atendidos, empezando por cancer de prostata y dejando el camino listo para Uromed.
- Almacenar con custodia trazable: RAID 1, respaldo automatico, snapshots, bitacora de acceso, permisos por rol y cifrado.
- Analizar en vivo la epidemiologia, procedimientos, desenlaces, costos, adherencia a guias y continuidad asistencial del servicio.
- Convertir datos estructurados en produccion academica: tesis, posters, articulos, reportes institucionales y lineas de investigacion reproducibles.
- Operar localmente dentro del hospital, sin depender de internet ni enviar datos sensibles a servidores externos por defecto.
- Preparar una expansion ordenada hacia Uromed: litiasis, cancer vesical, renal, testicular, urologia funcional, andrologia y trasplante, sin diluir primero la profundidad prostate-specific.

Traduccion directa a requisitos de ProstaMed:

- La plataforma debe tener modo de despliegue local/NAS con Docker, backups, restore drill, health checks y bitacora exportable.
- Todo tablero avanzado debe distinguir modo exploratorio vivo, freeze gobernado, snapshot firmado y paquete reproducible.
- Los endpoints de investigacion deben ser no-PHI por defecto y documentar `source_clinical_facts_mutated=false`, `external_order_created=false`, `model_trained=false` y `external_transfer_performed=false`.
- El gran tablero epidemiologico debe medir las metas del documento: pacientes capturados, adherencia prospectiva, variables por paciente, tableros activos, tesis, abstracts, articulos, perdida de seguimiento, duplicacion de estudios, tiempo de busqueda, adherencia NCCN y tiempos diagnostico-tratamiento.
- El Clinical Fact Ledger debe funcionar como sustituto moderno de libretas, USBs y archivos dispersos: una verdad canonica, buscable y reutilizable.
- La gobernanza prospectiva debe producir un paquete que sirva para jefatura/comite: roles, permisos, consentimiento/aviso, riesgos, mitigaciones, capacitacion, auditoria, protocolo y criterios de exito.

Metas temporales derivadas del documento:

- 0-3 meses: plataforma operativa local, personal capacitado, captura prospectiva inicial, primer reporte epidemiologico y deteccion de pacientes perdidos o incompletos.
- 4-6 meses: adherencia prospectiva >=90%, dashboards para jefatura/oncologia/tesis, primeros analisis por patologia mayor y presentacion institucional.
- 7-12 meses: ProstaMed operativo en NAS, 360-500 pacientes de cancer de prostata, 4-6 tableros, 2-4 tesis terminadas, 2-3 articulos sometidos y medicion de adherencia NCCN.
- 12-24 meses: 700-1,000 pacientes de cancer de prostata, validacion local de CAPRA/MSKCC/Partin, modelos predictivos propios, Uromed beta/maduro y posicionamiento nacional.

Implicacion estrategica: el siguiente salto no debe ser "mas IA", sino preparar ProstaMed para un piloto prospectivo hospitalario real sobre infraestructura local. Eso exige gobernanza de uso, seguridad, respaldo, auditoria, capacitacion y metricas de adopcion, ademas de las metricas clinicas que ya empezamos a congelar.

Relectura operativa del 29 de mayo de 2026: el documento NAS tambien fija el criterio de exito institucional. ProstaMed debe reemplazar la perdida de informacion por libretas, USB, computadoras personales y mensajeria no auditable; debe hacer que cada dato capturado alimente continuidad asistencial, analisis epidemiologico, costo/valor, investigacion y reportes a jefatura. Las metas de pacientes, tesis, articulos y tableros dejan de ser aspiracionales y pasan a ser KPIs del producto.

## Evidencia local actual

Servidor normal validado en esta corrida: `http://127.0.0.1:8093`, sin `PROSTANET_DATALLESS_SAFE_START`, con `PROSTANET_LOAD_MODEL=0` y `VOICE_STT_PREWARM=0` para evitar cargas pesadas sin activar modo seguro. El navegador in-app valido `/platform-readiness` y `/patient_profile/97000000001?v=2`; consola: 0 errores criticos y 1 warning conocido de Tailwind CDN.

Estado operativo verificado el 2026-05-28:

- `/api/platform-readiness/audit?scope=summary`: 200, read-only, `readiness_score=100`, `readiness_status=ready_for_next_layer`, `24/24` rutas criticas registradas.
- `/api/platform-readiness/ledger-release-gate?scope=summary`: 200, `142/142` facts pass, `0` watch, `0` block, `next_layer_allowed=true`.
- `/api/platform-readiness/ledger-persistence-matrix?scope=summary`: 200, `8/8` flujos V2 pass, `1076/1076` checks fact-flujo pass.
- `/api/platform-readiness/interoperability-map?scope=summary`: 200, read-only, `142` facts, `29/29` facts criticos con decision interoperable, `critical_block_count=0`, `interoperability_status=ready_for_initial_interop`.
- `/api/platform-readiness/deidentified-export-contract?scope=summary&limit=80`: 200, read-only, `80` sujetos, `142` campos en diccionario, `0` identifier keys, `0` PHI exact hits, `export_contract_status=ready_for_local_deidentified_export`.
- `/api/platform-readiness/research-pack-materializer?scope=summary&limit=80`: 200, read-only, `8` archivos CSV/JSON, `688` filas de datos, `0` identifier keys, `0` PHI exact hits, `bundle_sha256=9eda0ec3b18d528b179b5b2c2cc548c7c2ce44354bba87d37babb929bd644a7a`, `materializer_status=ready_to_freeze_or_download`.
- `/api/platform-readiness/research-pack-materializer/freezes?limit=10`: 200, read-only, `4` freezes gobernados, `4` descargables, `0` bloqueos de calidad, `current_freeze_allowed=true`.
- `/api/analytics/epidemiology-command-center?weeks=12,24,36,52&trace_limit=25`: 200, tablero V2 con `metric_provenance.source_mode=live_cohort_exploratory`, `40` metricas con provenance y `4` freezes disponibles.
- `/api/analytics/epidemiology-command-center?source_freeze_key=dxpack_550ec7c29cae`: 200, `metric_provenance.source_mode=governed_freeze_bound`, `40/40` metricas ligadas a freeze, `reconstructable_metric_count=40`, `payload_sha256=550ec7c29caeb149900f6e1adecefa486f966b8267501f8f2a81ac14cd8b6d7c`.
- `/api/analytics/epidemiology-command-center/snapshot-pack?source_freeze_key=dxpack_550ec7c29cae`: 200, `version=epidemiology_metric_snapshot_pack_v1`, hashes SHA256, archivos JSON/CSV y `no_phi_status=pass`.
- `/api/analytics/epidemiology-command-center/snapshot-pack?governance_status=audit_ready&approval_status=human_reviewed&methodology_version=epi_snapshot_methods_v1.1`: 200, `no_phi_status=pass`, firma humana presente y version metodologica persistida.
- `POST /api/analytics/epidemiology-command-center/snapshot-pack/freeze` con `poster_ready` sin `approved_research_use`: 400 controlado con `epidemiology_metric_snapshot_governance_incomplete`.
- Freeze gobernado vivo creado: `episnap_15dc90479c90`, `approval_status=human_reviewed`, `methodology_version=epi_snapshot_methods_v1.1`, ZIP con `governance.json` y sin tokens PHI probados.
- Freeze de reproduccion vivo creado: `episnap_4b1ff693ed69`; `/reproduction-pack` devuelve `statistical_reproduction_notebook_pack_v1`, `all_checks_passed=true`, `kpi_matrix_match=true`, `no_phi_status=pass`, sin `files` en JSON por defecto.
- `/reproduction-pack/download`: 200, ZIP con `snapshot.json`, CSVs, `governance.json`, `methodology.json`, `reproduce_snapshot.py`, notebook `.ipynb`, `reproduction_report.md`, `reproduction_manifest.json`; `python3 reproduce_snapshot.py` pasa sin DB viva.
- `/api/platform-readiness/prospective-pilot-governance?scope=summary&limit=20`: 200, `version=prospective_pilot_governance_pack_v1`, `15` gates, `pass_count=8`, `watch_count=7`, `block_count=0`, `pilot_block_count=0`, `pilot_status=ready_for_internal_prospective_pilot_with_watches`, `ready_for_external_deployment=false`.
- `/api/platform-readiness/prospective-pilot-governance?scope=full&limit=20`: 200, expone protocolo, matriz de responsabilidades, readiness NAS, consentimiento/datos, hitos 3/6/12/24 meses, riesgos y manifest del paquete piloto.
- `/api/modules/m1_crpc/schema?surface=wizard`: 200, `neuroendocrine_features` aparece una sola vez y `metastatic_components_capture` no contamina el wizard.
- `/api/modules/localized_initial/schema?surface=wizard`: 200, schema filtrado de wizard activo.
- `/api/patients/97000000001/clinical-fact-ledger/summary`: 200, Ledger por paciente disponible.
- `/patient_profile/97000000001?v=2`: 200, V2 contiene Ledger, PSA Compass, ARPI y canvases `psaTreatmentTimelineChart` + `psaCombinedTimelineChart`.
- `/platform-readiness`: 200, muestra Ledger gate, matriz de persistencia V2, mapa interoperable mCODE/OMOP, contrato de export desidentificado, materializador research pack y governance pack prospectivo; desktop/mobile validado por snapshot con consola limpia salvo Tailwind CDN.
- `/api/population/cohort-dashboard`: 200, tablero exploratorio con 13 KPIs calculados, supresion n<5 por molecula, 441 pacientes sinteticos/prevalidacion y ARPI value 24 semanas disponible.

Pruebas enfocadas actuales:

- `pytest tests/test_platform_readiness_audit.py -q`: `20 passed`.
- `pytest tests/test_arpi_value_analytics.py -q`: `20 passed`.
- Anti-recaptura Ledger/APE/intake + `DECISION HOY` + Autodrive: `25 passed`.

Readiness audit actual:

- Modulos escaneados: 18.
- Campos totales de modulo: 6831.
- Campos visibles por defecto en wizard: 2099.
- Campos avanzados ocultos por defecto: 4732.
- Rutas criticas registradas: 23/23.
- FactSpecs canonicos: 142.
- Cobertura canonica en schemas: 76.1%.
- Gaps altos: 0.
- Gaps moderados: 0.
- Recapture aliases: 22.
- Same-module recapture: 0.
- Estado: `ready_for_next_layer`.

Interpretacion: el proyecto salio de la fase de "necesita hardening antes de crecer" hacia una fase controlada de expansion. La condicion no es que todo sea producto comercial final; la condicion lograda es mejor: ya existe una compuerta objetiva que prueba captura, persistencia, frescura, no-recaptura, rutas V2 y matriz por flujo antes de aceptar nuevas capas.

## Actualizacion de cierre: Clinical Fact Ledger v1

Estado verificado el 2026-05-28:

- Ledger por paciente visible en perfil V2 y endpoint publico de resumen.
- Wizard V2 consume Ledger para prellenar y ocultar hechos conocidos no conflictivos.
- Draft clinico recibe `patient_ref` y `clinical_fact_ledger_wizard_context`.
- Registro longitudinal muestra panel `Clinical Fact Ledger v1`, chips de reutilizacion/conflicto y contrato read-only.
- Draft reabierto por `/api/clinical-assessments/<id>` conserva el contexto mediante `clinical_assessments.context_snapshot`, sin contaminar `input_snapshot`.
- `/patient_intake?assessment_id=...` queda compatible con el mismo contexto anti-recaptura.
- Validacion real: draft inicial y reabierto conservaron 2 facts reutilizados y 1 conflicto; `source_clinical_facts_mutated=false`, `external_order_created=false`, `model_trained=false`.

Interpretacion: Fase 1 ya no es una idea pendiente; existe un cierre v1 funcional. Aun no significa que todos los hechos clinicos de la plataforma esten perfectos. Significa que ya tenemos la capa para detectar, mostrar y gobernar recaptura/contradicciones sin seguir agregando campos a ciegas.

## Actualizacion de cierre: Ledger Release Gate v1

Estado verificado el 2026-05-28:

- Nuevo endpoint read-only `/api/platform-readiness/ledger-release-gate` con `scope=summary|full`.
- `/platform-readiness` integra la compuerta Ledger con KPIs, matriz por fact, owner, persistencia, frescura, recaptura y estado `pass|watch|block`.
- El gate no muta hechos clinicos, no crea ordenes externas y no entrena modelos.
- La compuerta distingue blockers reales de hardening: aliases/recaptura y extractores parciales quedan como `watch`, no como falsa falla clinica.
- Pruebas verdes de readiness, API y render visual del panel; regresion anti-recaptura del Ledger/intake sigue verde.

Interpretacion: el Ledger deja de ser solo un panel por paciente y pasa a ser una puerta de calidad para decidir si ProstaNet puede avanzar hacia interoperabilidad, genomica externa, patologia digital o analitica poblacional sin construir sobre datos ambiguos.

## Actualizacion de avance: Ledger Persistence QA Matrix por flujo V2

Estado verificado el 2026-05-28:

- Nuevo endpoint read-only `/api/platform-readiness/ledger-persistence-matrix` con `scope=summary|full`.
- La matriz audita flujos oficiales V2: wizard, draft clinico, registro longitudinal, perfil V2, `DECISION HOY`, schedule, redecision y cohortes/epidemiologia.
- Cada fila cruza flujo -> fact canonico -> owner -> captura -> persistencia -> frescura -> recaptura -> estado.
- `/platform-readiness` ahora muestra KPIs de QA por flujo V2 y tabla de flujos antes del gate global del Ledger.
- El contrato valida rutas reales, incluyendo `/api/patients/<patient_ref>/schedule`; no asume rutas legacy ni superficies inexistentes.
- El primer blocker detectado por la matriz quedo cerrado: registro longitudinal ya extrae `m0_crpc_state_confirmed`, `charlson_score`, `frailty_status` y `anesthesia_surgical_fitness`.
- Cierre adicional anti-recaptura: aliases legacy cubiertos por extractor se clasifican como `normalized_alias`, no como falso `watch`; PSAD/ECOG ocultos/derivados de gates pivotales quedan como alias contextual, no como recaptura simultanea.
- Cierre adicional de persistencia: 30 facts no bloqueantes con consumidores reales ya se extraen si llegan en payload, incluyendo laboratorios pronosticos, funcion renal, genómica, sitios viscerales, ADT, medicacion, prioridad del paciente y factibilidad de radioterapia.
- Estado local tras reinicio normal en `8093`: Ledger Release Gate `ready_for_next_layer` con 142 facts pass, 0 blockers, 0 watch y 0 watch de persistencia; matriz por flujo V2 `ready_for_next_layer` con 8 flujos pass y 1076 checks fact-flujo pass.

Interpretacion: ya no estamos midiendo la plataforma como una suma de pantallas. La medimos como una cadena auditable de datos clinicos reutilizables, que es la base real para el gran tablero epidemiologico y para no volver a trabajar en legacy. La matriz ya no solo observa: tambien encontro y guio el cierre de persistencia bloqueante, y ahora quedo como release gate verde antes de crecer.

## Actualizacion de cierre: Interoperability Readiness Layer v1

Estado verificado el 2026-05-28:

- Nuevo builder read-only `build_interoperability_map()` sobre `FACT_SPECS`, sin exportar pacientes ni mutar hechos clinicos.
- Nuevo endpoint `/api/platform-readiness/interoperability-map?scope=summary|full`.
- `/platform-readiness` muestra KPI y tabla V2 de mCODE/FHIR, OMOP, vocabulario, cardinalidad y estado por fact.
- Contrato critico actualizado: `/api/platform-readiness/interoperability-map` queda dentro de las rutas obligatorias del readiness audit.
- Resultado local: `142` facts Ledger, `29` criticos, `29/29` criticos listos, `0` blockers, `0` unmapped, `30` mapeados y `111` parciales que quedan como hardening semantico no bloqueante.
- Pruebas verdes: `tests/test_platform_readiness_audit.py` valida que PSA/APE, ECOG y T clinico tengan destino mCODE/OMOP y que un FactSpec critico sin decision interoperable bloquee.

Interpretacion: ProstaNet ya no solo sabe si captura y reutiliza datos; ahora sabe si esos datos tienen destino semantico para hablar con FHIR/mCODE y OMOP. Aun no es export productivo, pero ya es la compuerta correcta para evitar que genetica externa, patologia digital o el gran tablero epidemiologico crezcan sobre facts no interoperables.

## Actualizacion de cierre: De-identified Cohort Export Contract v1

Estado verificado el 2026-05-28:

- Nuevo builder read-only `build_deidentified_export_contract()` sobre el Ledger, eventos, tratamientos, biomarcadores y mapa interoperable.
- Nuevo endpoint `/api/platform-readiness/deidentified-export-contract?scope=summary|full&limit=`.
- `/platform-readiness` muestra KPI y tabla V2 del paquete de export: manifest, facts+lineage, eventos, tratamientos, biomarcadores y scan de PHI.
- Contrato critico actualizado: `/api/platform-readiness/deidentified-export-contract` queda dentro de las rutas obligatorias del readiness audit.
- Resultado local en `8093`: `80` sujetos muestreados, `128` fact rows, `128` lineage rows, `218` event rows, `14` treatment rows, `200` biomarker rows, `142` campos en diccionario, `0` direct identifier keys, `0` exact PHI hits, `0` variables sin mapa.
- El paquete no escribe archivos, no transfiere datos fuera del entorno local, no muta hechos clinicos, no crea ordenes y no entrena modelos.
- Pruebas verdes: `tests/test_platform_readiness_audit.py` valida supresion de NSS/nombre/DOB, ausencia de `patient_id` como llave exportada, `subject_id` hash, lineage por `baseline_psa`, y destino mCODE/OMOP.

Interpretacion: ProstaNet ya puede probar que su cohorte es exportable de forma reproducible sin soltar PHI directo. Este contrato quedo como la compuerta que protege cualquier freeze, descarga o conector posterior.

## Actualizacion de cierre: Research Pack Materializer v1

Estado verificado el 2026-05-28:

- Nuevo materializador read-only sobre `build_deidentified_export_contract()`, con manifest, bundle JSON y CSVs para diccionario, facts, lineage, eventos, tratamientos y biomarcadores.
- Nuevos endpoints publicos locales: preview, freeze, detalle de freeze y descarga ZIP de `/api/platform-readiness/research-pack-materializer`.
- `/platform-readiness` muestra KPI, estado, hash del bundle, PHI gate y tabla de archivos del pack.
- Resultado local en `8093`: `80` sujetos, `8` archivos, `688` filas de datos, `0` identifier keys, `0` exact PHI hits, `0` blockers de interoperabilidad, `0` campos no mapeados.
- Freeze real creado: `dxpack_583967de7f52`, `payload_sha256=583967de7f52bdce56d3cd3df561d524866f2527454e695b48c95083a78a85c8`.
- ZIP descargado y validado con `manifest.json`, `bundle.json`, `data_dictionary.csv`, `fact_rows.csv`, `lineage_rows.csv`, `events.csv`, `treatments.csv` y `biomarkers.csv`.
- El pack no contiene NSS, nombre, DOB, `patient_id` ni tokens PHI exactos en los archivos revisados.
- El flujo no muta hechos clinicos, no crea ordenes externas, no entrena modelos, no escribe export externo y no hace transferencia externa.
- Validacion visual desktop/mobile de `/platform-readiness`: 0 errores de consola y 1 warning conocido de Tailwind CDN.

Interpretacion: ProstaNet ya no solo demuestra que una cohorte puede desidentificarse; ahora puede congelarla como artefacto local reproducible, hasheado, auditable y descargable. Esta es la primera base tecnica concreta para posters, auditorias, data rooms clinicos, conectores FHIR/OMOP y tablero epidemiologico defendible.

## Actualizacion de cierre: Cohort Freeze Library + Governance UI v1

Estado verificado el 2026-05-28:

- Nueva capa read-only de biblioteca gobernada para freezes `deidentified_research_pack_v1`.
- Nuevo endpoint `/api/platform-readiness/research-pack-materializer/freezes?limit=` con resumen, tags de gobernanza, hashes, conteos, calidad y URLs de detalle/descarga.
- `/platform-readiness` integra KPI, formulario V2 de freeze y tabla de freezes gobernados; no usa perfil legacy.
- `POST /api/platform-readiness/research-pack-materializer/freeze` acepta `governance_status`, objetivo clinico, pregunta de investigacion, nota metodologica y responsable.
- Tags v1 disponibles: `exploratory`, `audit_ready`, `poster_ready`, `publication_ready`, `insufficient_quality`.
- Validacion local en `8093`: `4` freezes gobernados, `4` descargables, `0` bloqueos de calidad y `23/23` rutas criticas registradas.
- Freeze limpio creado: `dxpack_11cf36828c59`, con ZIP sin NSS, nombres, DOB, `patient_id` literal ni tokens PHI probados.
- Validacion UI: el formulario V2 creo `dxpack_550ec7c29cae` desde `/platform-readiness` y devolvio link de detalle.
- Validacion visual desktop/mobile: biblioteca, formulario, botones Detalle/ZIP y KPI visibles; consola con 0 errores y 1 warning conocido de Tailwind CDN.

Interpretacion: ProstaNet ya tiene una biblioteca institucional de packs congelados, gobernados y descargables. Esto convierte readiness tecnico en flujo usable para auditoria, investigacion, posters y data rooms clinicos.

## Actualizacion de cierre: Metric Provenance Binding v1

Estado verificado el 2026-05-28:

- Nuevo builder `metric_provenance_binding_v1` para ligar cada KPI principal del gran tablero epidemiologico con fuente viva o freeze gobernado.
- `/api/analytics/epidemiology-command-center` expone `metric_provenance` sin cambiar la logica estadistica existente.
- Nuevo endpoint hijo `/api/analytics/epidemiology-command-center/provenance` para consultar solo la capa de provenance.
- La UI V2 en `epidemiology_command_center_v2.html` agrega selector de freeze y panel `Procedencia auditable de metricas`.
- Modo vivo queda marcado explicitamente como `live_cohort_exploratory`.
- Modo freeze con `dxpack_550ec7c29cae` liga `40/40` metricas a `freeze_key`, `payload_sha256`, `n`, politica de supresion, diccionario, lineage y familias de filas.
- Validacion visual desktop/mobile: panel visible, selector funcional, transicion a `governed_freeze_bound`, 0 errores de consola y 1 warning conocido de Tailwind CDN.
- Pruebas verdes: `tests/test_arpi_value_analytics.py` valida provenance vivo, binding a freeze gobernado, API hijo, no-PHI en provenance, template V2 y ruta poblacional.

Interpretacion: el gran tablero ya no es solo una visualizacion viva. Ahora cada metrica puede declararse exploratoria o anclada a un pack gobernado, con hash y trazabilidad suficiente para auditoria institucional y preparacion de investigacion.

## Actualizacion de cierre: Epidemiology Metric Snapshot Pack v1

Estado verificado el 2026-05-28:

- Nuevo dominio `epidemiology_metric_snapshot_pack_v1` para congelar la fotografia del gran tablero epidemiologico V2 sin PHI directo.
- Nuevos endpoints: preview, CSV de componentes, freeze, lista, detalle y descarga ZIP bajo `/api/analytics/epidemiology-command-center/snapshot-pack`.
- El snapshot conserva KPIs ejecutivos, matriz 12/24/36/52, comparacion molecula/regimen, completitud, economia, metodologia, hashes y procedencia metrica.
- Las filas paciente-a-metrica se omiten del snapshot no-PHI; quedan solo resumen agregado y `metric_provenance`.
- Freeze reproducible con prefijo `episnap_`, `registry_type=epidemiology_metric_snapshot_v1`, hash estable e idempotencia protegida aunque existan snapshots previos.
- Gobernanza humana integrada: `governance_status`, `approval_status`, responsable, rol, nota, firma, `approval_signature_sha256` y `methodology_version`.
- Uso de alta gobernanza protegido: `poster_ready` y `publication_ready` requieren `approved_research_use`; aprobaciones formales requieren responsable y nota metodologica.
- UI V2 agrega workspace `Snapshot reproducible del tablero`, controles de gobernanza/aprobacion, boton `Congelar snapshot`, links JSON/ZIP y biblioteca de snapshots recientes.
- Pruebas verdes: no-PHI, ZIP sin tokens de paciente seed, endpoints, template V2 e idempotencia del freeze.

Interpretacion: el tablero epidemiologico ya puede producir un artefacto metodologico reproducible y gobernado: no solo filas crudas ni solo pantalla viva, sino la matriz calculada exacta con filtros, hashes, metodo, provenance y firma humana para auditoria interna.

## Actualizacion de cierre: Statistical Reproduction Notebook Pack v1

Estado verificado el 2026-05-28:

- Nuevo paquete `statistical_reproduction_notebook_pack_v1` generado desde freezes `episnap_`.
- Incluye `snapshot.json`, `governance.json`, `methodology.json`, CSVs, `reconstructed_kpi_matrix.json`, `reproduction_report.md`, `reproduction_manifest.json`, `reproduce_snapshot.py` y `reproduction_notebook.ipynb`.
- `run_statistical_reproduction_checks` recalcula sin DB viva `kpi_matrix_sha256`, `filters_sha256` y `provenance_sha256`, mas checks no-PHI y revision de supresion n<5.
- Nuevo endpoint JSON `/api/analytics/epidemiology-command-center/snapshot-pack/freezes/<freeze_key>/reproduction-pack`.
- Nuevo endpoint ZIP `/api/analytics/epidemiology-command-center/snapshot-pack/freezes/<freeze_key>/reproduction-pack/download`.
- UI V2 agrega link `Reproducir` en la biblioteca de snapshots.
- Validacion automatizada extrae el ZIP y ejecuta `python3 reproduce_snapshot.py`; el script genera `reproduction_report.md` y `reconstructed_kpi_matrix.json` con `all_checks_passed=true`.
- Validacion live en `8093`: ZIP sin tokens PHI probados, consola UI sin errores criticos y solo warning conocido de Tailwind CDN.

Interpretacion: ProstaNet ya puede entregar no solo una fotografia firmada del tablero, sino un paquete que reproduce localmente los numeros agregados sin tocar la base viva. Esto es la base de un Research OS defendible para auditoria, comite, posters, articulo y data room institucional.

## Actualizacion de cierre: Prospective Pilot Governance Pack v1

Estado verificado el 2026-05-28:

- Nuevo dominio read-only `prospective_pilot_governance_pack_v1`, alineado al documento NAS Urologia.
- Nuevo endpoint `/api/platform-readiness/prospective-pilot-governance?scope=summary|full&limit=`.
- `/platform-readiness` integra KPI y panel `Governance pack prospectivo` con 15 gates: Ledger, matriz V2, no-recaptura, interoperabilidad, export no-PHI, freezes, snapshots, boundary clinico, NAS/local operations, backup/restore, roles, consentimiento, capacitacion, incidente y aprobacion de protocolo.
- Resultado live en `8093`: `pass_count=8`, `watch_count=7`, `block_count=0`, `pilot_block_count=0`, `pilot_status=ready_for_internal_prospective_pilot_with_watches`, `ready_for_external_deployment=false`.
- Los watches son operacionales, no clinicos: NAS deployment proof, restore drill, clinical auth, consentimiento, capacitacion, incidente y aprobacion formal del protocolo.
- El paquete full expone protocolo, criterios de inclusion/exclusion, endpoints primarios/secundarios, matriz de responsabilidades, readiness NAS, hitos 0-3/4-6/7-12/12-24 meses, riesgos, entrenamiento, consentimiento/data use y manifest de evidencia.
- Se corrigio un falso bloqueo causado por reusar un iterador de rutas Flask agotado; ahora los builders reciben una lista estable de rutas y el audit reporta `24/24` rutas criticas registradas.
- Pruebas verdes: `tests/test_platform_readiness_audit.py` 20/20, `tests/test_arpi_value_analytics.py` 20/20 y regresion anti-recaptura/Decision Hoy/Autodrive 25/25.
- Validacion visual desktop/mobile: panel visible, link JSON visible, ruta en tabla de contratos registrada y consola con 0 errores criticos mas el warning conocido de Tailwind CDN.

Interpretacion: el siguiente paso comercial/regulatorio ya dejo de ser abstracto. ProstaMed puede declarar que esta listo para un piloto prospectivo interno con watches operacionales, mientras bloquea honestamente despliegue externo hasta cerrar seguridad, respaldo, consentimiento, capacitacion e incidente. Esto conecta el software con la propuesta NAS real.

## Actualizacion de cierre: Operational Gap Latency v1

Estado verificado el 2026-05-28:

- Nuevo bloque read-only `operational_gap_latency_v1` dentro de `build_treatment_value_registry()` y del Gran Tablero Epidemiologico V2.
- La metrica mide, por ventana activa no vacia, disponibilidad y latencia de dato util en dominios: APE de ventana, ECOG de ventana, dosis/costo, referencia tras cuarta dosis local, vigilancia de toxicidad CTCAE y revision auditada de brechas epidemiologicas.
- Se corrigio un defecto de tablero: cuando se solicitaban ventanas `12,24,36,52`, `_latest_window_rows()` elegia 52 aunque estuviera vacia. Ahora selecciona la ventana mas tardia con filas reales, preservando la lista completa de ventanas para la matriz.
- La UI V2 en `/population/epidemiology-command-center` agrega tarjeta `Latencia operativa de brechas` y KPI ejecutivo `Latencia dato util`.
- El snapshot no-PHI del tablero ahora sanea `capture_url` y `missing_patient_refs`, conservando agregados y evitando que la correccion de ventana real introduzca tokens PHI en paquetes reproducibles.
- Validacion live en `8093` con `patient_ref=TXVALUE006984`: `primary_window_weeks=24`, `latency_status=needs_capture_operations`, `5/6` dominios cerrados, `1` brecha abierta, `no_phi_status=pass`.
- Validacion visual desktop/mobile: tarjeta de latencia renderizada, sin overflow horizontal, consola sin errores criticos y solo warning conocido de Tailwind CDN.
- Pruebas verdes: `pytest tests/test_arpi_value_analytics.py -q` devuelve `21 passed`.

Interpretacion: el tablero empieza a medir la operacion clinica como sistema, no solo resultados. Esta capa permite saber donde se pierde valor por retraso de captura, brecha no revisada o dato que todavia no llega al registro poblacional. Es una pieza clave para piloto NAS, calidad asistencial, jefatura, investigacion prospectiva y reduccion real de recaptura.

## Actualizacion de cierre: Operational Gap Latency fechas reales v1.1

Estado verificado el 2026-05-28:

- `compute_arpi_response_at_window()` ahora devuelve y persiste `actual_ecog_date`, `baseline_ecog_date`, `ecog_offset_days` y `ecog_evidence_quality` en `arpi_response_windows`.
- `init_tracking_db()` migra bases existentes agregando esas columnas sin romper snapshots ARPI previos.
- `build_arpi_value_patient_rows()` y `build_treatment_value_registry_rows()` exponen `first_local_dose_date_to_window`, `latest_local_dose_date_to_window` y `first_priced_local_dose_date_to_window`.
- `operational_gap_latency_v1` deja de usar `actual_psa_date` como proxy para ECOG: si existe fecha ECOG real, mide con `actual_ecog_date`; si la fila antigua solo tiene valor ECOG, cuenta cobertura pero no latencia.
- La latencia de dosis/costo ya usa la primera dosis local con costo trazable, en vez de reportar solo cobertura sin fecha.
- Validacion live en `8093` sobre `TXVALUE006984`: `actual_ecog_date=2026-04-18`, `first_priced_local_dose_date_to_window=2025-11-01`, dominios ECOG y dosis/costo con `median_days_to_close=0`, `source` real y `latency_observation_count=1`.
- Snapshot no-PHI sigue pasando: `no_phi_status=pass`, `0` direct identifiers y `0` PHI exact hits.
- Validacion visual desktop/mobile: KPI `Latencia dato util` y tarjeta `Latencia operativa de brechas` muestran APE, ECOG, dosis/costo y referencia sin overflow horizontal; consola sin errores criticos, solo warnings conocidos de Tailwind CDN.
- Pruebas verdes: `pytest tests/test_arpi_value_analytics.py -q` devuelve `21 passed`.

Interpretacion: cerramos una ambiguedad importante. La plataforma ya no solo dice "hay ECOG"; ahora sabe cuando se capturo clinicamente y puede medir oportunidad real de captura. Esto fortalece el tablero como instrumento de calidad asistencial, auditoria de proceso y readiness prospectivo.

## Actualizacion de cierre: Toxicity Surveillance Semantics v1

Estado verificado el 2026-05-28:

- El registro poblacional V2 ya distingue tres estados de toxicidad sistemica:
  - evento CTCAE documentado,
  - revision CTCAE documentada sin evento,
  - toxicidad no revisada/no capturada.
- La fuente `CTCAE_TOXICITY` de `biomarker_longitudinal`, ya usada por `/api/longitudinal/<nss>/append` con `kind=ctcae`, ahora alimenta `build_treatment_value_registry_rows()` junto con `treatment_adverse_events`.
- CTCAE grado 0 o estado explicito `sin toxicidad` cierra vigilancia como `toxicity_absence_documented=true`, sin crear un evento toxico positivo.
- Si no existe evento ni revision CTCAE, `toxicity_event_count_to_window=None`, lo que mantiene la brecha `toxicity_ctcae` abierta en la worklist epidemiologica.
- `operational_gap_latency_v1` mide `toxicity_surveillance` con `toxicity_review_date`, fuente `treatment_adverse_events + CTCAE_TOXICITY` y policy explicita: ausencia revisada no equivale a ausencia no capturada.
- `/api/longitudinal/<nss>/append` con `kind=ctcae` ya devuelve `treatment_value_capture_impact`, cerrando el puente paciente-a-tablero tambien para toxicidad.
- Validacion live en `8093` sobre `TXVALUE006984`: antes de CTCAE existia brecha `toxicity_ctcae`; despues de capturar CTCAE grado 0 en `2026-04-18`, el trace muestra `toxicity_event_count_to_window=0`, `toxicity_review_documented=true`, `toxicity_absence_documented=true` y `toxicity_review_date=2026-04-18`.
- Snapshot no-PHI sigue pasando: `no_phi_status=pass`, `0` direct identifiers y `0` PHI exact hits.
- Validacion visual desktop/mobile: `Toxicidad CTCAE revisada · 100.0% · med 0 d`, sin overflow horizontal y consola sin errores criticos.
- Pruebas verdes: `pytest tests/test_arpi_value_analytics.py -q` devuelve `21 passed`.

Interpretacion: cerramos una falsa seguridad metodologica. El tablero ya no puede interpretar automaticamente "no hay evento adverso registrado" como "el paciente no tuvo toxicidad". Para investigacion, calidad y compras, esta diferencia protege conclusiones y permite medir trabajo clinico real de farmacovigilancia.

## Direccion lograda

- Centro clinico por estadio con flujo para sospecha diagnostica, localizado, recurrencia, mCSPC, m0 CRPC, m1 CRPC y seguimiento.
- Derivacion unica para DRE/TR, PSAD y MRI en diagnostico, evitando narrativas falsas como TR no sospechoso cuando el usuario captura T2a/T2b/T2c/T4.
- Disclosure progresivo de gates pivotales: no se elimina capacidad avanzada, pero los gates sistemicos no contaminan etapas donde no son clinicamente pertinentes.
- Captura unica de APE: el scalar APE no se recaptura en intake, pero `psa_history` queda disponible para serie longitudinal; `clinical_baseline.baseline_psa` y `biomarker_longitudinal` quedan sincronizados.
- Re-Decision Closure Loop: cola poblacional, workbench individual, cierre auditable en `patient_events`, sin mutar hechos clinicos ni crear ordenes externas.
- Analitica clinico-economica inicial: cursos terapeuticos, dosis locales, catalogo de precios, ARPI real-world value y cohort dashboard.
- Platform Readiness Audit v1: primer tablero para medir rutas, schemas, canonical facts, aliases, recaptura y readiness antes de crecer.
- Interoperability Readiness v1: mapa read-only mCODE/FHIR y OMOP sobre el Ledger, con compuerta para facts criticos.
- De-identified Export Contract v1: paquete reproducible local con diccionario, subject ids, fechas a precision mensual y lineage fact-a-estandar sin PHI directo.
- Research Pack Materializer v1: freeze/download local CSV+JSON con SHA256, manifest, no-PHI gate y trazabilidad suficiente para auditoria e investigacion.
- Cohort Freeze Library + Governance UI v1: biblioteca V2 de packs congelados con estado de gobernanza, pregunta de investigacion, responsable, detalle y descarga ZIP local.
- Metric Provenance Binding v1: cada KPI del gran tablero puede citar fuente viva o freeze gobernado, hash, diccionario, lineage, supresion y reconstruccion desde filas crudas.
- Epidemiology Metric Snapshot Pack v1: congelamiento reproducible no-PHI de la fotografia del tablero V2 con KPIs, matriz, metodologia versionada, aprobacion humana, hashes, provenance y ZIP descargable.
- Statistical Reproduction Notebook Pack v1: paquete ejecutable sin DB viva que recalcula hashes/KPIs, verifica no-PHI, supresion y genera reporte de reproduccion.
- Prospective Pilot Governance Pack v1: paquete de piloto institucional local/NAS con gates clinicos, operacionales, seguridad, consentimiento, adopcion y protocolo.

## Fortalezas

- Profundidad prostate-specific: ProstaNet modela estados reales de cancer de prostata, no oncologia generica.
- Logica por suficiencia de datos: cuando falta un dato que cambia conducta, el sistema puede bloquear y pedir captura dirigida.
- Seguimiento longitudinal: APE, testosterona, ECOG, eventos, dosis, tratamientos, redecision y seguimiento pueden convertirse en linea de vida clinica.
- Auditoria fuerte: `latest_assessment`, `prior_history`, `patient_events`, `clinical_signal_snapshots`, cache invalidation y read models.
- Contexto mexicano/latinoamericano: referencia por unidad, disponibilidad, costo, retrasos, acceso a ARPI/RLT y utilidad para auditoria institucional.
- Base de investigacion: estructura suficiente para cohortes, outcomes, valor, demografia y lineas de investigacion.

## Areas de oportunidad

- Worktree y release train: hay mucha deuda y cambios simultaneos; necesitamos congelar baseline, separar entregables y evitar que hallazgos buenos queden mezclados con artefactos.
- Ledger canonico listo como compuerta, pero aun joven como producto: ya no hay gaps moderados ni same-module recapture, pero falta convertir el diccionario canonico en contrato de interoperabilidad, training set y analitica causal.
- Readiness verde no equivale a producto comercial: falta endurecer seguridad, roles, consentimiento, pilotos prospectivos, backups, monitoreo productivo y documentacion regulatoria.
- Interoperabilidad: ya existe mapa inicial mCODE/FHIR/OMOP, contrato desidentificado, materializacion CSV/JSON local, biblioteca gobernada de freezes, provenance por metrica y snapshot firmado; faltan conectores HL7/DICOM/LIS/pathology/laboratorio y validacion multiinstitucional.
- Investigación: ya hay binding metrica-a-pack, snapshot exacto no-PHI, firma humana, version metodologica y paquete de reproduccion estadistica; falta convertirlo en protocolo/comite/poster/manuscrito asistido y piloto prospectivo.
- Producto comercial: faltan roles duros, consentimiento, desidentificacion, backups, auditoria legal, monitoreo productivo y piloto prospectivo.
- Evidencia viva: NCCN, EAU, FDA, precios y disponibilidad local deben tener version, fecha, impacto y responsable de aprobacion humana.

## Benchmarking

Fuentes verificadas el 2026-05-28: Flatiron OncoEMR, CancerLinQ, Tempus Lens, ArteraAI, Decipher, Paige Prostate, Varian ARIA, Epic Beacon, PCOR-ANZ, HL7 mCODE y OMOP Oncology Extension.

| Referente | Fortaleza externa | Ventaja potencial de ProstaNet | Que debemos copiar o superar |
| --- | --- | --- | --- |
| Flatiron OncoEMR / Flatiron Assist | EHR oncologico con workflows, NCCN Order Templates, AJCC, precision medicine, reporting, portal e integraciones. | Ser mas profundo en prostata, seguimiento por estado, valor local y decision longitudinal. | Integraciones, certificacion, conectividad, portal paciente, reporting comercial y red de partners. |
| Epic Beacon | Modulo oncologico dentro del EHR dominante, con protocolos de quimioterapia, administracion, radioterapia y staging para registros. | Ser la capa especialista que interpreta prostata encima del EHR, no competir por reemplazarlo. | Integracion EHR, ordenes seguras, staging estructurado y transferencia a registros. |
| CancerLinQ | Red multi-centro; transfiere datos desde EHR y otros sistemas, los cura/armoniza y ofrece calidad, CDS, trial matching e insights. | Unir calidad, decision clinica y economia operativa en tiempo real, desde la consulta uro-oncologica. | Gobernanza de datos, estandarizacion, red institucional, quality measures, QOPI/ASCO-like workflows. |
| Tempus Lens | Cohort builder multimodal, filtros moleculares/clinicos, datos desidentificados, visualizaciones, IA y workspace de investigacion. | Ser accionable al lado del urologo/uro-oncologo, no solo analitico retrospectivo. | Cohort builder self-service, filtros moleculares, workspace reproducible, export y analisis sobre datos no estructurados. |
| ArteraAI Prostate Test | Test IA predictivo/prognostico en localizado; reporta beneficio terapeutico y outcomes a largo plazo. | Orquestar estos reportes dentro de una decision longitudinal completa, no competir como test unico. | Ingestion de reportes externos y explicacion clara de impacto terapeutico. |
| Decipher Prostate | Clasificador genomico tisular para riesgo de metastasis/progresion y guia de tratamiento; adopcion y evidencia amplias. | Convertir score en ruta, seguimiento, costo, agenda, auditoria y cohortes. | Ingestion molecular versionada, reporte trazable y decision impact. |
| Paige Prostate / pathology AI | IA de patologia para biopsia de prostata con autorizacion FDA, orientada a reducir errores y mejorar eficiencia diagnostica. | Consumir patologia digital y cerrar decision clinica con Gleason, cores, volumen tumoral y PNI. | Integracion LIS/pathology, trazabilidad por core, auditoria de discrepancias. |
| Varian ARIA / Elekta MOSAIQ | OIS industrial para radioterapia/oncologia, interoperabilidad HL7/DICOM, prescripcion, imagenes, QA, toxicidad y chart audit. | Ser la capa inteligente prostate-specific por encima de OIS/EHR, no reemplazarlos. | Interoperabilidad, workflow safety, chart audit, scheduling, DICOM/RT y compliance. |
| PCOR-ANZ | Registro poblacional de outcomes de prostata, tratamientos y calidad de vida, con benchmarking de variacion y resultados. | Capturar outcomes desde la decision, no retrospectivamente. | Conjunto minimo de variables, consentimiento, PROs, reporte institucional y benchmark externo. |
| HL7 mCODE | Modelo FHIR oncologico minimo con grupos de paciente, enfermedad, assessment, genomica, tratamientos y outcomes. | Traducir profundidad prostate-specific a un lenguaje interoperable. | Mapas FHIR/mCODE, perfiles, codigos, versionado y export compartible. |
| OMOP Oncology | Extension que representa episodios oncologicos, tratamientos y eventos para investigacion observacional. | Convertir operacion diaria en datasets reproducibles para estudios y valor real. | ETL, episode/episode_event, vocabularios, data quality dashboard y reproducibilidad. |

Lectura competitiva: los lideres externos ganan por escala, integracion, certificacion y red. ProstaNet puede ganar por profundidad clinica en prostata, secuencia logica, decision de hoy, captura dirigida de faltantes, economia local, auditoria y generacion de investigacion desde la operacion diaria. La estrategia correcta es integrarnos con EHR/OIS/LIS/genomica, no pelear frontalmente contra ellos.

Actualizacion competitiva 2026-05-28:

- Flatiron/OncoEMR y Epic/Beacon son sistemas de ejecucion clinica y ordenes; ProstaNet debe ser capa especialista de inteligencia y auditoria, no reemplazo inmediato del EHR.
- CancerLinQ y PCOR-ANZ muestran que el valor institucional real aparece cuando la captura diaria se convierte en calidad, outcomes, variacion, supervivencia y PROs.
- Tempus Lens muestra la direccion de investigacion: cohort builder clinico-molecular, filtros multimodales y datos desidentificados reutilizables.
- ARIA/MOSAIQ muestran el nivel de interoperabilidad y audit trail que necesitaremos para radioterapia: HL7, DICOM, QA, toxicidad, scheduling y chart audit.
- Paige, Decipher y ArteraAI muestran que la IA/prognostico de prostata no debe ser recreada a ciegas; debe ser ingerida, versionada, explicada y convertida en decision, seguimiento, costo y outcome.
- mCODE y OMOP Oncology muestran el camino tecnico: convertir el Ledger interno en datos intercambiables y analizables fuera de ProstaNet.

Actualizacion operativa 2026-05-29:

- El benchmarking ya no queda solo como texto estrategico; se materializo como radar read-only `world_class_prostate_platform_benchmark_v1`.
- Nueva API: `/api/platform-readiness/world-class-benchmark?scope=summary|full`.
- Nuevo panel V2 en `/platform-readiness`: `Radar ProstaMed frente a plataformas lideres`, con score mundial, fortalezas, brechas, matriz competitiva y ruta por fases.
- La matriz compara clases de plataformas: EHR/CDS oncologico, redes RWD, cohort builders multimodales, genómica/patología digital, OIS radioterapia, registros de outcomes, mCODE y OMOP Oncology.
- El radar usa evidencia interna viva: readiness audit, Ledger release gate, matriz de persistencia V2, interop, export desidentificado, research pack, freeze library y governance prospectivo.
- Contrato seguro: `source_clinical_facts_mutated=false`, `external_order_created=false`, `model_trained=false`, `external_transfer_performed=false`.
- Decision estratégica codificada: ProstaMed debe ser la capa prostate-specific de inteligencia clinica, calidad de dato, valor y Research OS sobre EHR/OIS, no un EHR generico.

Actualizacion operativa 2026-05-29 B:

- La brecha principal del radar, `external_validation`, ya tiene worklist operativo read-only: `external_validation_readiness_worklist_v1`.
- Nueva API: `/api/platform-readiness/external-validation-worklist?scope=summary|full&limit=`.
- Nuevo export no-PHI: `/api/platform-readiness/external-validation-worklist/export`.
- Nuevo panel V2 en `/platform-readiness`: `Worklist para cerrar la brecha multicentro`.
- El worklist no declara validacion externa; muestra preflight y bloqueos para que la plataforma no infle claims antes de tener revision firmada.
- Cubre Ledger/persistencia V2, anti-recaptura, paquete no-PHI, diccionario mCODE/OMOP, completitud prospectiva, muestra real, huddle de brechas, APE longitudinal, NAS operacional, protocolo/consentimiento y trazabilidad del benchmark.
- Beneficio esperado: convertir la ambicion multicentro en una cola accionable con dueños, evidencia, rutas y criterio de cierre.

Actualizacion operativa 2026-05-29 C:

- El bloqueo `real_world_sample_maturity` ya tiene compuerta propia: `real_world_sample_maturity_gate_v1`.
- Nueva API: `/api/platform-readiness/real-world-sample-maturity?scope=summary|full&limit=`.
- Nuevo export no-PHI: `/api/platform-readiness/real-world-sample-maturity/export`.
- Nuevo panel V2 en `/platform-readiness`: `Compuerta de madurez de muestra real`.
- La compuerta separa pacientes sinteticos/QA de evidencia hospitalaria real; conserva los sinteticos para smoke, visual validation y fixtures, pero los excluye de inferencia, claims economicos/clinicos y validacion externa.
- Contrato de evidencia real: `is_synthetic=0`, `real_patient_consent_signed_at`, `actor_user_id`, completitud registry-ready real, NAS/protocolo sin bloqueos y umbrales n>=30/n>=50/n>=100 para señal interna, preflight externo y multicentro.
- Estado live actual: 0 pacientes reales y 445 sinteticos/QA; por tanto la plataforma bloquea correctamente claims de evidencia hospitalaria hasta iniciar captura prospectiva real.

Actualizacion operativa 2026-05-29 D:

- El ingreso prospectivo real ya tiene superficie V2 explicita: `templates/components/real_world_enrollment_panel.html`.
- El panel se integra en el wizard clinico V2 y en `patient_intake`, pero queda desactivado por defecto para proteger QA/smoke.
- Para que un paciente entre a muestra real debe activarse `is_real_patient=1`, pasar por consentimiento electronico y documentar `actor_user_id`.
- `register_new_patient(...)` rechaza el modo real sin consentimiento firmado o sin actor clinico; el modo normal sigue creando QA/sintetico por defecto.
- `real_world_sample_maturity_gate_v1` documenta la superficie V2 de enrolamiento y el CTA de captura real apunta al centro clinico con contexto `real_world_enrollment=1`.
- Prueba de cierre: un draft de consentimiento con `is_real_patient=1`, `consent_signed=1` y `actor_user_id=77` finaliza con `is_synthetic=0`, consentimiento/actor en `patient_identity` y la compuerta pasa de 0 a 1 real en base aislada.

## Posicionamiento ganador

La mejor plataforma mundial no sera otro EHR ni otro test genomico. Debe ser un `Prostate Cancer Intelligence OS` que:

- Captura hechos clinicos una vez.
- Los convierte en timeline longitudinal.
- Calcula decision segura hoy.
- Explica que dato falta y por que cambia conducta.
- Audita decisiones, desviaciones, retrasos, costos y resultados.
- Convierte la operacion diaria en investigacion responsable.
- Se integra con EHR/OIS/LIS/lab/genomica en lugar de intentar reemplazarlos desde el dia 1.

## Plan maestro

### Fase -1: Infraestructura local y soberania de datos

Objetivo: que ProstaMed pueda vivir en el NAS del servicio con seguridad, continuidad y trazabilidad institucional.

- Despliegue local reproducible en Docker/NAS con variables de entorno documentadas, health checks y modo normal sin depender de internet.
- Politica de respaldo: RAID 1 no cuenta como backup; se requiere respaldo diario a medio independiente, prueba periodica de restauracion y registro del ultimo backup valido.
- Roles minimos: jefe/administrador, adscrito, residente mayor, residente menor, investigador y auditor, con permisos separados para PHI, captura, export y freezes.
- Bitacora institucional: acceso, modificacion, export local, freeze, aprobacion humana, descarga ZIP y reproduccion estadistica.
- Checklist operativo NAS: UPS, SMART/RAID health, cifrado, snapshot, IP estatica, firewall, procedimiento de reemplazo de disco y plan de contingencia.
- Criterio de salida: ProstaMed puede demostrar en `/platform-readiness` que esta listo para piloto local sobre NAS o explicar que bloqueo operacional falta cerrar.

### Fase 0: Baseline confiable

Objetivo: que lo existente funcione antes de crecer.

- Mantener localhost normal y suite smoke viva.
- Cerrar recapturas moderadas detectadas por readiness.
- Contratos por flujo: schema -> UI visible -> payload -> persistencia -> perfil -> decision_today -> schedule.
- Release gate: si readiness tiene gaps altos, no se agrega logica clinica.
- Criterio de salida: rutas criticas 18/18, gaps altos 0, gaps moderados 0, recaptura same-module 0, Ledger Release Gate verde, matriz V2 verde y pruebas E2E por estado.

### Fase 1: Clinical Fact Ledger

Objetivo: una verdad clinica canonica.

- Cada hecho tendra `fact_key`, aliases, unidad, tipo, fuente, fecha, frescura, derivacion, owner, consumidores y surfaces.
- Distinguir scalar basal, valor actual y serie longitudinal: por ejemplo APE basal vs APE actual vs historial APE.
- Documentar hechos derivados: PSAD, metastatic_stage_resolved, metastatic_detection_basis, risk group, decision_state.
- Endpoint por paciente: "que se sabe", "de donde viene", "que falta", "que decision cambia".

### Fase 2: Interoperabilidad

Objetivo: abrir ProstaNet al mundo.

- mCODE/FHIR para paciente oncologico, ECOG, staging, tratamientos, genomica y outcomes.
- OMOP Oncology para investigacion observacional, episodios y tratamientos.
- Conectores futuros: laboratorio, patologia, DICOM/PSMA PET, OIS, EHR.
- Export desidentificado con data dictionary y lineage.

### Fase 3: Outcomes y valor

Objetivo: medir beneficio real, costo y seguridad.

- Extender tratamiento-valor a localizado, salvage, mCSPC, m0 CRPC, m1 CRPC y paliativo.
- PROs: IPSS, IIEF-5, EPIC-26, PRO-CTCAE, dolor, fatiga, salud osea, metabolismo ADT.
- Medir retrasos: sospecha -> MRI -> biopsia -> histologia -> tratamiento -> respuesta -> progresion.
- Panel institucional: calidad, costos, equidad, demografia, seguridad, adherencia a guia y productividad academica.

### Fase 4: Evidencia viva

Objetivo: que el sistema no envejezca clinicamente.

- Watchers versionados para NCCN, EAU, FDA, NCI, precios y disponibilidad local.
- Registro de evidencia por regla: fuente, version, fuerza, campo requerido, impacto y fecha.
- Alertas de drift: recomendacion dependiente de guia o aprobacion nueva.
- Validacion humana obligatoria antes de cambiar conducta clinica.

### Fase 5: Research OS

Objetivo: convertir cada paciente consentido en aprendizaje responsable.

- Cohort builder con criterios reproducibles.
- Feasibility de estudios y lineas de investigacion automaticas.
- Export academico: tablas, STROBE-like checklist, diccionario y trazabilidad.
- Auditoria por servicio, medico, etapa, tratamiento, demografia, acceso y costos.
- Metas NAS: tesis, posters, articulos, reportes a jefatura, presentaciones AMU/SMU/EAU/AUA y validaciones locales de modelos internacionales.

### Fase 6: Producto comercial

Objetivo: vender una plataforma segura y defendible.

- Roles, permisos, MFA/OIDC, consentimiento, desidentificacion, logs inmutables y backups.
- Piloto prospectivo institucional.
- Reporte de valor: ahorro, tiempos, adherencia a guia, seguridad, outcomes y produccion academica.
- Paquetes comerciales: hospital, grupo uro-oncologico, pagador/institucion, investigacion.
- Paquete NAS/Uro-oncologia: hardware local, plataforma, protocolos, data room, capacitacion, tableros y produccion academica como oferta integral.

## Ruta operativa de 90 dias

### Dias 0-14: Baseline confiable

- Congelar V2 como superficie oficial: `/clinical-hub`, `/wizard/*`, `/patients`, `/patient_profile/<nss>?v=2`, `/redecision-workbench`, `/loop-monitor`, `/platform-readiness`.
- Ejecutar smoke E2E por estado antes de cada salto: schema -> UI visible -> payload -> persistencia -> perfil V2 -> `DECISION HOY` -> schedule/agenda.
- Mantener la alerta de frescura APE como KPI longitudinal: probar baseline APE + historial APE + torre APE sin recaptura en cada nuevo flujo.
- Mantener en cero same-module recapture y convertir alias contextuales en diccionario interoperable, no en captura duplicada.
- Agregar checklist NAS en readiness: Docker/localhost normal, backup, restore drill, permisos, bitacora, UPS/RAID/SMART y politica de contingencia.

### Dias 15-45: Clinical Fact Ledger v1

- Implementar endpoint/panel por paciente con `fact_key`, alias, unidad, fuente, fecha, frescura, derivacion, propietario, consumidores y superficies.
- Marcar lineage visible en V2: que el clinico sepa si un dato viene de intake, historial longitudinal, tratamiento, laboratorio, patologia o derivacion.
- Crear `no-recapture score` por modulo y por paciente.
- Fallar el release gate si un hecho critico nuevo no tiene owner, persistencia y consumidor definidos.

### Dias 46-75: Interoperabilidad y export reproducible

- Mapear hechos canonicos a mCODE/FHIR y OMOP Oncology: paciente, staging, ECOG, APE, testosterona, patologia, genomica, tratamiento, outcomes y eventos.
- Crear export desidentificado con diccionario, lineage y version de evidencia.
- Preparar ingestores futuros para laboratorio, patologia, DICOM/PSMA PET, EHR/OIS y reportes genomicos externos.

### Dias 76-90: Valor institucional e investigacion

- Dashboard institucional de tiempos, adherencia, costos, acceso, demografia, seguridad y resultados.
- Cohort builder reproducible con criterios guardables.
- Reporte piloto: valor clinico, economico, asistencial y academico.
- Paquete comercial inicial: demo V2, seguridad, auditoria, data dictionary y caso prospectivo.
- Metricas de adopcion del documento NAS: pacientes capturados, adherencia prospectiva, variables medianas por paciente, tableros activos, proyectos de tesis, abstracts y reduccion de tiempos de busqueda.

## Siguiente implementacion de mayor valor

`Huddle-Driven APE Longitudinal Completion Sprint v1`.

Por que ahora:

- El huddle ya convierte brechas en cola accionable; la mayor brecha local sigue siendo APE longitudinal.
- La cohorte visible mantiene solo `26.0%` de cobertura de historial APE, lo que bloquea outcomes, response windows, PSA50/PSA90, progresion bioquimica y evidencia real.
- El salto no debe agregar reglas terapeuticas; debe cerrar el dato longitudinal mas reutilizable de toda la plataforma.
- Completar APE primero aumenta valor clinico, epidemiologico, economico y de investigacion sin tocar motores de recomendacion.

Alcance v1:

- Crear vista filtrada de huddle para brechas APE: sin APE, APE aislado, historial insuficiente, fecha faltante o serie no interpretable.
- Añadir CTA directo a `longitudinal-capture` con `decision_field=psa_history`, precargando fuente y evitando recaptura del APE ya existente.
- Mostrar antes/despues por paciente: puntos APE, baseline seleccionado, fuente Ledger y si desbloquea registry-ready.
- Generar resumen semanal no-PHI de recuperacion APE: pacientes revisados, puntos añadidos, gaps persistentes y cohortes desbloqueadas.
- Mantener cierre event-only para revision; los nuevos valores APE se capturan solo en la superficie longitudinal oficial.

Criterio de salida v1:

- La torre de adopcion muestra aumento medible de cobertura APE cuando se capturan series.
- Cada paciente con brecha APE tiene ruta unica a longitudinal capture y lineage Ledger visible en Perfil V2.
- El sistema no crea puntos APE duplicados si baseline e historial ya contienen el mismo valor/fecha.
- Export semanal no-PHI muestra impacto de cierre APE sobre registry-ready, research packs y tablero epidemiologico.

Beneficios esperados:

- Desbloquear la metrica longitudinal mas importante del cancer de prostata.
- Mejorar Decision Today, perfiles V2, ARPI value, registro epidemiologico y research packs con el mismo dato.
- Convertir el huddle en productividad visible: menos gaps, mas cohortes listas y mas evidencia hospitalaria.
- Mantener foco quirurgico: arreglar lo ya existente antes de mas logica clinica.

## Actualizacion de cierre: Huddle-Driven APE Longitudinal Completion Sprint v1

Estado al 28 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nuevas rutas: `/api/platform-readiness/ape-longitudinal-completion-sprint?scope=summary|full&limit=` y `/api/platform-readiness/ape-longitudinal-completion-sprint/export`.
- Panel V2 en `/platform-readiness`: `Sprint de completitud APE longitudinal`, KPIs, worklist, lineage Ledger, CTA unico a `/longitudinal-capture/<patient_ref>?decision_field=psa_history` y CSV no-PHI.
- Contratos criticos registrados: `32/32`, sin rutas faltantes.
- Cohorte local visible: `100` pacientes, `26.0%` con historial APE longitudinal, `74` con brecha APE, `34` sin APE reutilizable, `33` con punto unico, `7` con snapshot aislado y `45` potenciales desbloqueos registry-ready.
- Resumen no-PHI validado: `summary_no_phi_scan=no_phi_status: pass`; el payload `summary` ya no incluye CTAs con identificador de paciente.
- Perfil V2: la torre APE expone `psaMini`, `psaFull`, `psaTreatmentTimelineChart`, mediciones APE renderizadas y bloque `v2-psa-current-treatment-line` con linea actual, regimen, ventana de tratamiento, dosis locales/globales y conteo APE.
- Validacion visual/DOM desktop y movil: `/platform-readiness#ape-longitudinal-completion-sprint` visible, `17` CTAs a captura longitudinal en la cohorte local, sin overflow horizontal; `/patient_profile/97000000001?v=2` muestra `14` mediciones APE y linea `L1 first_line_metastatic`, regimen `ADT + abiraterona`, timeline terapeutico visible. Consola: `0` errores criticos, solo warning conocido de Tailwind CDN.
- Pruebas verdes: `tests/test_platform_readiness_audit.py` + checks V2 APE `33 passed`, `tests/test_arpi_value_analytics.py` `20 passed`, regresion APE/Ledger/Decision Today/Autodrive `25 passed`.

## Actualizacion de cierre: APE Capture Impact Loop v1

Estado al 28 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nuevo read model paciente-especifico: `build_patient_ape_completion_snapshot(patient_ref)` para leer estado APE sin escribir hechos clinicos.
- Nuevo comparador de impacto: `build_ape_capture_impact(patient_ref, before_snapshot=...)`, que reporta `before`, `after`, `point_count_delta`, `gap_closed`, `registry_ready_after_capture`, superficies refrescadas y enlaces a Perfil V2, sprint y Decision Today.
- Nueva ruta read-only: `/api/patients/<patient_ref>/ape-capture-impact`.
- `POST /api/longitudinal/<patient_ref>/append` con `kind=psa` ahora devuelve `ape_capture_impact` dentro del mismo response exitoso; el flujo sigue append-only sobre `biomarker_longitudinal`.
- El recompute post-write ahora invalida read models de `patient_decision_today`, `patient_autodrive`, `autodrive_population`, `population_cohort_dashboard`, `epidemiology_command_center` y perfil V2, sin mutar hechos fuente ni entrenar modelos.
- UI V2 en `/longitudinal-capture/<patient_ref>?decision_field=psa_history`: panel `ape-capture-impact-panel` muestra estado APE, puntos validos, registry-ready y superficies recalculadas; el panel se actualiza en vivo tras guardar APE.
- Validacion live con paciente sintetico `99888006209`: antes `single_psa_point` con 1 punto; tras append de APE `2026-06-01 = 9.4 ng/mL`, `gap_closed=true`, despues `history_ready` con 2 puntos; perfil V2 y sprint respondieron 200.
- Validacion DOM desktop/movil: panel visible, `data-ape-status=history_ready`, sin overflow horizontal (`scrollWidth=clientWidth`), consola con 0 errores y solo warning conocido de Tailwind CDN.
- Pruebas verdes: `tests/test_platform_readiness_audit.py` `33 passed`, `tests/test_arpi_value_analytics.py` `20 passed`, regresion APE/Ledger/Decision Today/Autodrive `25 passed`.

Interpretacion: ya no solo sabemos que falta APE longitudinal; ahora cada captura APE puede demostrar que cerro o no cerro una brecha y que el cambio se refleja en Perfil V2, sprint poblacional y motores de decision/analitica. Esto transforma la captura diaria en progreso medible del piloto.

## Actualizacion de verificacion: Torre APE V2 + linea terapeutica vigente

Estado al 28 de mayo de 2026: validacion clinica limpia sobre Perfil V2, no legacy.

- Paciente sintetico coherente: `TXAPE006983`, mCSPC de alto volumen sincronico, triplete `ADT_DOCETAXEL_DAROLUTAMIDE`.
- Captura APE longitudinal por ruta oficial append-only: basal `2026-05-28 = 55.0 ng/mL`, seguimiento `2026-07-15 = 18.2`, `2026-08-20 = 20.0`, `2026-09-15 = 7.4`, `2026-11-12 = 5.5`, `2026-11-15 = 3.1`.
- Perfil V2 `/patient_profile/TXAPE006983?v=2`: torre APE muestra `6 puntos APE`, todos asociados a `L1 · mHSPC inicial · ADT + docetaxel + darolutamida`.
- Banda terapeutica V2: `start=2026-05-28`, `end=2026-11-15`, `line=1`, `scheme=ADT_DOCETAXEL_DAROLUTAMIDE`, `line_type=Triplete (ADT+ARPI+Docetaxel)`.
- Bloque `v2-psa-current-treatment-line`: linea actual `L1`, regimen activo `ADT + docetaxel + darolutamida`, ventana de tratamiento correcta, `6 locales · 8 globales` y `6 mediciones APE renderizadas`.
- Validacion API: `/api/patients/TXAPE006983/ape-capture-impact` devuelve `history_ready`, `valid_psa_point_count=6`, `source_clinical_facts_mutated=false`; `/api/patients/TXAPE006983/treatment-course/current` devuelve gasto ARPI `285,000 MXN`, alerta `critical` y mensaje de envio HGZ/HGR.
- Validacion Chart.js desktop/mobile: `psaMini`, `psaFull`, `psaTreatmentTimelineChart` y `psaCombinedTimelineChart` renderizan sin errores criticos; `psaTreatmentTimelineChart` contiene dataset de linea terapeutica y dataset scatter con `6` mediciones APE; `psaCombinedTimelineChart` contiene APE, banda L1 y eventos clinicos.
- Consola: `0` errores criticos; solo warning conocido de Tailwind CDN.

Interpretacion: la seccion APE del Perfil V2 ya no es decorativa. Esta usando mediciones persistidas, asignacion temporal por linea terapeutica y regimen activo real. Esta es la base correcta para PSA50/PSA90, progresion bioquimica, costo por respuesta y auditoria paciente-a-cohorte.

## Actualizacion de cierre: Treatment Value Capture Impact Delta v1

Estado al 28 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nuevo read model poblacional: `build_treatment_value_capture_impact(patient_ref, before_snapshot=...)`, read-only, sin mutar hechos clinicos, sin orden externa y sin entrenar modelos.
- Nueva ruta: `/api/analytics/treatment-value-registry/capture-impact?patient_ref=&weeks=&trace_limit=`.
- Integracion post-captura: `POST /api/longitudinal/<patient_ref>/append` con `kind=psa|treatment_change|treatment_dose|epidemiology_gap`, `POST /api/patients/<patient_ref>/ecog-capture`, `POST /api/patients/<patient_ref>/treatment-course` y `POST /api/patients/<patient_ref>/treatment-course/<course_id>/dose` devuelven `treatment_value_capture_impact` cuando la captura afecta registro 12/24 semanas.
- UI V2 en `/population/treatment-value-registry`: panel `Impacto de captura paciente-a-cohorte` lee `patient_ref` desde la URL y muestra ventanas activas, filas trazables, gasto, dosis locales, PSA50/PSA90, ECOG y brechas abiertas.
- Validacion live con paciente sintetico maduro `TXVALUE006984`: inicio `ADT_ABIRATERONE` `2025-11-01`, APE `100.0 -> 35.0`, ECOG `2 -> 1`, `active_windows=[12,24]`, `patient_contributes_to_registry=true`, `row_count=1`, gasto `39,000 MXN`, `PSA50=1`, `ECOG mejoro=1`, safety flags en `false`.
- Validacion visual desktop/movil: `/population/treatment-value-registry?patient_ref=TXVALUE006984` precarga el paciente, renderiza el panel sin overflow horizontal y sin errores criticos de consola.
- Pruebas verdes focales ampliadas: `30 passed` para ARPI value capture impact, refresh 12/24, contrato template V2, treatment-course/dose y torre APE V2.

Interpretacion: cada dato longitudinal capturado ya puede demostrar no solo que mejora el perfil individual, sino tambien que agrega evidencia paciente-a-cohorte para el gran tablero epidemiologico. Este es el puente directo entre captura diaria, costo por respuesta y trazabilidad metodologica.

## Actualizacion de cierre: Epidemiology Capture Impact Bridge v1

Estado al 28 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- El Gran Tablero Epidemiologico V2 integra ahora `capture_impact_bridge`, un puente read-only desde `build_treatment_value_capture_impact` hacia `/api/analytics/epidemiology-command-center`.
- Cuando se abre el tablero con `patient_ref`, el backend calcula si ese paciente aporta a ventanas 12/24/36/52, filas trazables, PSA50/PSA90, ECOG, gasto atribuible, dosis locales y brechas abiertas.
- La UI `/population/epidemiology-command-center?patient_ref=TXVALUE006984` precarga el paciente desde la URL y muestra el panel `Impacto post-captura paciente-a-tablero`, ademas del KPI ejecutivo `Impacto post-captura`.
- Validacion live con `TXVALUE006984`: `source_mode=live_capture_delta`, `active_window_count=2`, `row_count=1`, `response_evaluable_count=1`, `estimated_spend_mxn=39,000`, `local_dose_count=4`, `psa50_responder_count=1`, `ecog_improved_count=1`, safety flags en `false`.
- Seguridad metodologica: si la vista esta ligada a un freeze gobernado, el delta live queda desactivado para no mezclar datos nuevos con snapshot congelado.
- Validacion visual desktop/movil: panel visible, `patient_ref` precargado, sin overflow horizontal, consola con `0` errores criticos y solo warning conocido de Tailwind CDN.
- Pruebas verdes: `tests/test_arpi_value_analytics.py` `21 passed`.

Interpretacion: el tablero final ya no solo resume cohortes; ahora muestra de forma directa como una captura longitudinal individual mueve evidencia poblacional auditable. Esto cierra el circuito captura diaria -> perfil V2 -> registro tratamiento-valor -> gran tablero epidemiologico.

## Actualizacion de cierre: Treatment-Dose Economic Impact Loop v1

Estado al 28 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nuevo read model paciente-especifico: `build_patient_treatment_economic_snapshot(patient_ref)`, read-only, sin mutar hechos clinicos, sin orden externa, sin entrenar modelos y sin transferencia externa.
- Nuevo comparador de impacto: `build_treatment_economic_capture_impact(patient_ref, before_snapshot=...)`, que reporta cambio de dosis local/global, cambio de gasto ARPI, cambio de gasto farmacologico trazable, cambio de alerta operativa y superficies V2 refrescadas.
- Nueva ruta read-only: `/api/patients/<patient_ref>/treatment-economic-impact`.
- `POST /api/patients/<patient_ref>/treatment-course`, `POST /api/patients/<patient_ref>/treatment-course/<course_id>/dose`, y `POST /api/longitudinal/<patient_ref>/append` con `kind=treatment_change|treatment_dose` devuelven `treatment_economic_impact`.
- UI V2 en `/longitudinal-capture/<patient_ref>` muestra `treatment-economic-impact-panel` con regimen actual, dosis locales/globales, gasto ARPI y alerta HGZ/HGR.
- Escenario validado: triplete `ADT_DOCETAXEL_DAROLUTAMIDE`; con `4` dosis locales + `2` previas aparece alerta `warning` y gasto ARPI estimado `190,000 MXN`; al registrar dosis local `6`, alerta `critical`, mensaje "Paciente con maximo de dosis otorgadas en esta unidad. Priorizar envio a HGZ o HGR.", gasto ARPI acumulado `285,000 MXN`.
- Perfil V2 refleja el triplete, la alerta critica, la banda de tratamiento, `6 locales · 8 globales`, gasto ARPI `285,000 MXN` y costo farmacologico trazable parcial `286,802.58 MXN`.
- Pruebas verdes: `tests/test_treatment_course_dose_tracking.py` `7 passed`, `tests/test_arpi_value_analytics.py` `20 passed`, regresion APE/Ledger/Decision Today/Autodrive `25 passed`, readiness `tests/test_platform_readiness_audit.py` `33 passed`.

Interpretacion: la plataforma ya conecta ejecucion terapeutica real con impacto economico y alerta operativa local. Esto convierte la captura de dosis en una senal clinico-financiera auditable, lista para agregarse al tablero epidemiologico por molecula/regimen y costo por respuesta.

## Actualizacion de cierre: Prospective Gap Closure Huddle Workbench v1

Estado al 28 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nuevas rutas: `/api/platform-readiness/prospective-gap-closure-huddle`, `/api/platform-readiness/prospective-gap-closure-huddle/close` y `/api/platform-readiness/prospective-gap-closure-huddle/export`.
- Panel V2 en `/platform-readiness`: `Workbench de cierre prospectivo de brechas`, KPIs, tabla accionable, formulario de cierre y descarga CSV no-PHI.
- Contratos criticos registrados: `30/30`, sin rutas faltantes.
- Cierre auditado probado: `POST /close` escribe `patient_events.event_type=pilot_gap_reviewed`, devuelve `reviewed_still_open` y mantiene la brecha visible si el dato sigue faltando.
- Cohorte local visible: `212` brechas de huddle, `211` abiertas, `1` revisada tras validacion, `40` pacientes con brecha, `summary_no_phi_scan=pass`.
- Pruebas verdes: `tests/test_platform_readiness_audit.py` `28 passed`, `tests/test_arpi_value_analytics.py` `20 passed`, regresion APE/Ledger/Decision Today/Autodrive `25 passed`.
- Validacion visual desktop/movil: huddle visible, submit real desde UI con evento `485`, consola sin errores criticos; solo warning conocido de Tailwind CDN.

## Actualizacion de cierre: Pilot Adoption and Completeness Command Center v1

Estado al 28 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nueva ruta: `/api/platform-readiness/pilot-adoption-command-center?scope=summary|full&limit=`.
- Panel V2 en `/platform-readiness`: `Torre de adopcion y completitud prospectiva`, KPIs, brechas dominantes, serie semanal y worklist con drill-down a Perfil V2.
- Resumen no-PHI validado: `summary_no_phi_scan=no_phi_status: pass`.
- Contratos criticos registrados: `27/27`, sin rutas faltantes.
- Cohorte local visible: `100` pacientes inspeccionados, `26.0%` con historial APE longitudinal, `1.0%` registry-ready, estado `needs_capture_hardening`.
- Pruebas verdes: `tests/test_platform_readiness_audit.py` `25 passed`, `tests/test_arpi_value_analytics.py` `20 passed`, regresion APE/Ledger/Decision Today/Autodrive `25 passed`.
- Validacion visual desktop/movil: panel de adopcion visible, links `Perfil V2` presentes, consola sin errores criticos; solo warning conocido de Tailwind CDN.

## Actualizacion de cierre: NAS Pilot Operations Evidence Vault v1

Estado al 28 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nuevas rutas: `/api/platform-readiness/nas-pilot-evidence-vault`, `/api/platform-readiness/nas-pilot-evidence-vault/attest` y `/api/platform-readiness/nas-pilot-evidence-vault/download`.
- Contratos criticos registrados al cierre del vault: `26/26`, sin rutas faltantes; tras el command center de adopcion la matriz subio a `27/27`.
- Vault inicial: `7` gates operacionales, `1` pass, `6` watch, `0` block, `2` evidencias no-PHI en la base local tras validacion.
- El gate `nas_local_operations` ya puede pasar a `pass` y el Prospective Pilot Governance Pack lo refleja.
- Pruebas verdes: `tests/test_platform_readiness_audit.py` `23 passed`, `tests/test_arpi_value_analytics.py` `20 passed`, regresion APE/Ledger/Decision Today/Autodrive `25 passed`.
- Validacion visual desktop/movil en `/platform-readiness`: panel `Evidence vault operacional`, formulario de attestation y submit real funcionando; consola sin errores criticos, solo warning conocido de Tailwind CDN.

## Actualizacion de cierre: Epidemiology Gap Review Audit Loop v1

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- La cola `capture_worklist` del registro tratamiento-valor ahora expone deteccion, responsable, estado auditado, dias abiertos, fecha de revision, latencia de revision, accion seleccionada y campos faltantes reconocidos.
- `POST /api/analytics/treatment-value-registry/gap-review` conserva su naturaleza read-only sobre hechos clinicos: escribe solo `patient_events.event_type=epidemiology_readiness_gap_reviewed`, con `source_clinical_facts_mutated=false`, `external_order_created=false` y `model_trained=false`.
- El tablero `/population/treatment-value-registry` muestra una columna `Auditoria` con `Detectada`, `Revisada`/`Abierta`, y `audit_state` (`open_unreviewed`, `reviewed_still_missing`, `reviewed_not_applicable`).
- El Gran Tablero Epidemiologico V2 muestra en `Latencia operativa de brechas` las brechas sin revisar, la brecha abierta mas antigua y las revisiones que siguen estructuralmente faltantes.
- Validacion live: se reviso una brecha real `survival_status` de `TEST-ARPI-AUTO-LOCAL-0527`, generando evento `512`, con `detected_at=2026-04-18`, `target_weeks=24`, `reviewed_by=codex_validation`, `review_latency_days=41` y safety flags en `false`.
- Snapshot no-PHI validado: `/api/analytics/epidemiology-command-center/snapshot-pack?weeks=12,24&trace_limit=20` devuelve `no_phi_status=pass`, `direct_identifier_key_count=0`, `exact_phi_hit_count=0` y traza paciente-nivel omitida.
- Pruebas verdes: `tests/test_arpi_value_analytics.py` `21 passed`.
- Validacion visual desktop/movil: cola auditable visible, sin overflow horizontal, consola sin errores criticos; solo warning conocido de Tailwind CDN.

Interpretacion: la plataforma ya puede tratar las brechas epidemiologicas como trabajo clinico-operativo auditable, sin recaptura innecesaria ni mutacion silenciosa de hechos. Esto prepara el siguiente nivel: asignacion/resolucion por responsable, SLA operativo y cierre transversal desde paciente, cohorte y tablero institucional.

## Actualizacion de cierre: Epidemiology Gap SLA Operations v1

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Cada brecha de `capture_worklist` ahora deriva responsable operativo, fecha compromiso, politica SLA, dias a vencimiento y `sla_state` (`overdue_unreviewed`, `overdue_reviewed_still_missing`, `due_soon_*`, `on_track_unreviewed`, `reviewed_pending_capture`).
- La asignacion no crea tabla nueva ni muta hechos clinicos: `POST /api/analytics/treatment-value-registry/gap-review` persiste `assigned_to`, `owner_role`, `due_date`, `sla_days` y `sla_policy` dentro del evento auditable `patient_events.event_type=epidemiology_readiness_gap_reviewed`.
- Reglas base v1: brechas de alta prioridad vencen en 7 dias; moderadas en 14 dias. Responsables sugeridos: navegacion clinica, uro-oncologia, enfermeria oncologica y farmacia/administracion segun el tipo de brecha.
- El Registro tratamiento-valor V2 muestra en la columna `Auditoria`: responsable, vencimiento y estado SLA, ademas de deteccion y revision.
- El Gran Tablero Epidemiologico V2 agrega KPI `SLA vencidas`, con conteo por vencer y numero de responsables activos.
- Validacion live: brecha `survival_status` de `TXVALUE006984` quedo asignada a `registro_epidemiologia`, `owner_role=navegacion_clinica`, `due_date=2026-04-25`, `sla_state=overdue_reviewed_still_missing`, evento `513`, safety flags en `false`.
- Snapshot no-PHI validado: `no_phi_status=pass`, `direct_identifier_key_count=0`, `exact_phi_hit_count=0`, traza paciente-nivel omitida.
- Pruebas verdes: `tests/test_arpi_value_analytics.py` `21 passed`.
- Validacion visual desktop/movil: responsable, vencimiento y SLA visibles en `/population/treatment-value-registry`; KPI SLA visible en `/population/epidemiology-command-center`; sin overflow horizontal; consola sin errores criticos, solo warning conocido de Tailwind CDN.

Interpretacion: ProstaNet ya no solo detecta brechas: las convierte en una cola operativa gobernable por responsable y fecha limite. Esto acerca el tablero epidemiologico a una herramienta real de jefatura/servicio, porque permite gestionar calidad de dato, auditoria y oportunidad operativa antes de publicar resultados o inferencias.

## Actualizacion de cierre: Profile V2 Epidemiology Gap SLA Bridge v1

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nuevo read-model paciente-especifico: `build_patient_epidemiology_gap_sla(patient_ref)`, derivado del mismo `capture_worklist` del registro tratamiento-valor. No duplica logica de captura ni muta hechos clinicos.
- Nueva API: `/api/patients/<patient_ref>/epidemiology-gap-sla`, con safety flags `source_clinical_facts_mutated=false`, `external_order_created=false`, `model_trained=false` y `external_transfer_performed=false`.
- Perfil V2 ahora incluye `data-testid="v2-epidemiology-gap-sla-panel"` con brechas activas, SLA vencidas, brechas sin revisar, responsables, estado SLA, CTAs a captura longitudinal y boton `Revisar SLA`.
- El endpoint de revision de brechas invalida el cache HTML de Perfil V2 y caches de read-model asociados para evitar UI vieja despues de una reasignacion/revision.
- Validacion live con `TXVALUE006984`: `active_gap_count=1`, `sla_overdue_count=1`, `gap_key=survival_status`, `owner_role=navegacion_clinica`, `assigned_to=registro_epidemiologia`, `due_date=2026-04-25`, `sla_state=overdue_reviewed_still_missing`, `capture_url=/longitudinal-capture/TXVALUE006984?...`.
- Pruebas verdes: `tests/test_arpi_value_analytics.py` `22 passed`.
- Validacion visual desktop/movil: panel visible en `/patient_profile/TXVALUE006984?v=2&refresh=1`, CTAs `Capturar dato` y `Revisar SLA` visibles, sin overflow horizontal, consola sin errores criticos; solo warning conocido de Tailwind CDN.

Interpretacion: el circuito paciente -> captura -> cohorte -> tablero ya es bidireccional. El perfil clinico muestra que dato falta para que el paciente contribuya correctamente a evidencia poblacional, y desde ahi puede saltar a captura o cierre auditado sin recaptura innecesaria.

## Actualizacion de cierre: Profile V2 SLA Capture Closure Loop v1

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- `POST /api/longitudinal/<patient_ref>/append` con `kind=epidemiology_gap` ahora devuelve el snapshot actualizado `epidemiology_gap_sla` del paciente y `next_surfaces` hacia Perfil V2, registro tratamiento-valor, Gran Tablero Epidemiologico y API paciente.
- La captura sigue siendo estructurada y auditable: persiste el dato faltante en la fuente clinica correspondiente, no crea orden externa y no entrena modelos.
- La UI V2 de `/longitudinal-capture/<patient_ref>` muestra `epidemiology-gap-sla-after-capture`, recalcula la torre tras guardar y ofrece saltos directos a Perfil V2 y cohorte.
- Correccion anti-recaptura: el builder JS de captura longitudinal ahora incluye `textarea` en payload, validacion y limpieza post-save, cerrando el bug donde campos largos visibles como comorbilidad basal no viajaban al backend.
- Contrato nuevo: despues de capturar `survival_status`, la brecha debe desaparecer simultaneamente del snapshot paciente, del registro tratamiento-valor filtrado por paciente y del Gran Tablero Epidemiologico filtrado por paciente.
- Validacion live: `TXVALUE006984` cerro `survival_status` con evento `514`, `active_gap_count=0`, registry y Gran Tablero sin brechas para ese paciente.
- Validacion UI live: `TEST-ARPI-AUTO-LOCAL-0527` cerro `comorbidity` desde `/longitudinal-capture/...`, el panel cambio a `Torre epidemiologica recalculada`, la cola bajo de `4` a `3` brechas y `comorbidity` desaparecio de Perfil SLA, registry y Gran Tablero.
- Pruebas verdes: `tests/test_arpi_value_analytics.py` `22 passed`, incluyendo cierre de `survival_status`, `metastatic_context` y `comorbidity`, mas contrato de `textarea` en captura longitudinal.

Interpretacion: ya no basta con documentar que una brecha fue revisada; cuando el dato se captura, el sistema prueba que la brecha se cierra transversalmente en paciente, cohorte y tablero. Este es el comportamiento anti-recaptura que necesitamos antes de agregar mas logica clinica o analitica.

## Actualizacion de cierre: Torre APE V2 Persistencia y Linea Terapeutica v1

Estado al 29 de mayo de 2026: validado en localhost normal `127.0.0.1:8093`.

- API fuente de verdad: `/api/patient/TXVALUE006984/psa-unified` expone `n_points=4`, ultimo APE `28.0 ng/mL` del `2026-05-29`, `has_data=true`, `1` banda terapeutica y `1` segmento.
- Captura real: `POST /api/longitudinal/TXVALUE006984/append` con `kind=psa` guardo APE `28.0`, `appended_id=756`, `ape_status=history_ready`, `valid_psa_point_count=4`, `registry_ready_after_capture=true` y `recompute_success=true`.
- Linea terapeutica: los cuatro puntos APE quedaron asignados a `L1 · mHSPC inicial · ADT + abiraterona`; la banda `ADT_ABIRATERONE` se extendio hasta `2026-05-29` sin inventar regimenes.
- Perfil V2: `/patient_profile/TXVALUE006984?v=2&refresh=1` muestra `4 puntos APE`, la linea actual `ADT + abiraterona`, y renderiza `psaTreatmentTimelineChart` visible al abrir `PSA Compass`.
- `Combined Timeline`: al abrir la pestana `Combined Timeline`, `psaCombinedTimelineChart` renderiza con dimensiones reales y sin errores de consola.
- Pruebas verdes: `tests/test_audit_lxc1_psa_unified_torre_integration.py` + `tests/test_audit63a_psa_history_intake_to_tower.py` `36 passed`.

Interpretacion: la torre APE V2 ya cumple el contrato clinico central: una medicion capturada una vez persiste, recalcula, se muestra en Perfil V2 y queda correlacionada con la linea terapeutica real actual.

## Actualizacion de cierre: Clinical Fact Ledger V2 CTA Governance v1

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nueva capa read-only: `build_patient_profile_v2_capture_governance(...)` decide, desde el Ledger, si una CTA de Perfil V2 debe reutilizar dato, refrescar dato vencido, capturar faltante o bloquear captura ciega por conflicto.
- CTAs gobernadas en V2: `castration_capture_cta`, `psma_pet_capture_cta`, `hrr_capture_cta` y `ecog_capture_cta`; no toca legacy ni cambia rutas de captura existentes.
- Regla anti-recaptura: si el Ledger tiene un hecho vigente y no contradictorio, la CTA se suprime en Perfil V2 y se muestra como reutilizada; si hay conflicto, la captura rapida se bloquea para evitar sobrescritura silenciosa.
- Perfil V2 ahora muestra `data-testid="ledger-capture-governance-panel"` con conteos de `sin recaptura`, `actualizar` y `conflictos`, mas tarjetas `ledger-governed-<gate>`.
- Validacion live con `TXVALUE006984`: Perfil V2 renderiza Ledger, panel de gobernanza, `ledger-governed-ecog_quick_capture`, suprime `ecog-quick-capture-card`, mantiene `psaTreatmentTimelineChart`, `psaCombinedTimelineChart`, `4 puntos APE` y linea `ADT + abiraterona`.
- Validacion visual desktop/movil: consola con `0` errores criticos y solo warning conocido de Tailwind CDN; screenshots guardados fuera del repo en `/tmp/prostanet_profile_v2_ledger_governance_desktop.png` y `/tmp/prostanet_profile_v2_ledger_governance_mobile.png`.
- Pruebas verdes focales: `tests/test_modular_engine.py::test_clinical_fact_ledger_exposes_ape_lineage_without_source_mutation`, dos nuevos tests de gobernanza CTA V2 y readiness Ledger `5 passed`; static V2 Ledger closure `3 passed`; `py_compile` verde.

Interpretacion: el Ledger ya no es solo un panel informativo. Ahora gobierna el comportamiento de Perfil V2 para cortar recaptura, evitar contradicciones UI/backend y mantener una ruta de captura dirigida solo cuando el dato realmente falta o esta vencido.

## Actualizacion de cierre: Longitudinal Capture Ledger Governance v1

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nueva capa read-only: `build_longitudinal_capture_ledger_context(...)`, orientada a la superficie `/longitudinal-capture/<patient_ref>`.
- La capa distingue captura longitudinal legitima de recaptura: APE/PSA conserva `append_longitudinal_measurement`, mientras ECOG, testosterona, biopsia, MRI/PI-RADS, PSMA-PET y HRR pueden reutilizar, refrescar, capturar faltante o bloquear conflicto segun Ledger.
- La UI de captura longitudinal muestra `data-testid="longitudinal-ledger-context-panel"` y expone el JSON auditable en `longitudinalClinicalFactLedgerContext`.
- El JS aplica el contrato en runtime: cuando `suppress_recapture=true` o `capture_allowed=false`, deshabilita inputs/botones del formulario afectado y muestra aviso de Ledger antes de que el usuario intente guardar.
- Validacion live ECOG: `/longitudinal-capture/TXVALUE006984?decision_field=ecog&readiness_lane=adt_arpi_safety_readiness` muestra panel Ledger, `ecogAction=resolve_conflict_before_capture`, `ecogAllowed=false`, `ecogSuppressed=true` y formulario ECOG deshabilitado.
- Validacion live APE: `/longitudinal-capture/TXVALUE006984?decision_field=psa_history` mantiene `psaAction=append_longitudinal_measurement`, `psaAllowed=true`, `psaSuppressed=false`, formulario APE habilitado y panel `ape-capture-impact-panel` visible.
- Validacion visual desktop/movil: consola con `0` errores criticos y solo warning conocido de Tailwind CDN; screenshots guardados fuera del repo en `/tmp/prostanet_longitudinal_ledger_ecog_desktop.png`, `/tmp/prostanet_longitudinal_ledger_psa_desktop.png` y `/tmp/prostanet_longitudinal_ledger_psa_mobile.png`.
- Pruebas verdes: pruebas focales de gobernanza Perfil V2 + captura longitudinal `3 passed`, regresion Ledger/readiness cercana `5 passed`, `py_compile` verde.

Interpretacion: la proteccion anti-recaptura ya cubre Perfil V2 y captura longitudinal V2. La plataforma empieza a comportarse como expediente clinico inteligente: permite agregar nueva evidencia temporal, pero evita pedir de nuevo datos vigentes o capturar encima de contradicciones sin revision.

## Actualizacion de cierre: Longitudinal Field Ledger Chips v1

Estado al 29 de mayo de 2026: implementado en V2 y validado por pruebas focales.

- `build_longitudinal_capture_ledger_context(...)` ahora incluye decisiones por campo (`field_decisions`) ademas de la decision por formulario.
- APE/PSA mantiene politica longitudinal: `psa_value` y `psa_date` quedan como `append_new_measurement`, por lo que nunca se bloquea una nueva medicion fechada por existir un APE previo.
- Escalares como ECOG pueden bloquear recaptura dirigida a nivel de campo y formulario cuando el Ledger ya tiene dato vigente o conflicto.
- Reportes mixtos como biopsia, MRI/PI-RADS, PSMA-PET, HRR y metastasis visceral pueden proteger campos conocidos y dejar capturar brechas o eventos nuevos sin eliminar capacidad clinica.
- La UI `/longitudinal-capture/<patient_ref>` agrega chips `longitudinal-ledger-field-<form>-<field>` y datasets `ledgerFieldAction`/`ledgerFactKey` en cada control mapeado.
- El navegador envia `ledger_context` al endpoint de append y `POST /api/longitudinal/<patient_ref>/append` rechaza recaptura dirigida con `error=ledger_recapture_blocked` si el campo viene bloqueado por Ledger.
- Validacion live REST: intento dirigido de ECOG para `TXVALUE006984` respondio `409`, `blocked_fields=[score/ecog_score]`, sin mutar facts clinicos, sin orden externa y sin entrenamiento.
- Pruebas verdes: `py_compile`, pruebas focales de Perfil V2 + captura longitudinal `3 passed`, y regresion Ledger/readiness cercana `6 passed`.

Interpretacion: pasamos de anti-recaptura por pantalla a anti-recaptura granular y defendida por REST. Esto reduce duplicidad y contradicciones sin romper el principio longitudinal: los datos seriados se agregan; los hechos clinicos vigentes se reutilizan; los conflictos se revisan.

## Actualizacion de cierre: Clinical Fact Reconciliation V2 v1

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nueva cola read-only: `build_patient_clinical_fact_reconciliation_bundle(...)` convierte conflictos del Clinical Fact Ledger en una cola accionable por paciente.
- Nueva superficie V2: `/clinical-fact-reconciliation/<patient_ref>` y alias `/patient_profile/<patient_ref>/fact-reconciliation`.
- Nuevas APIs:
  - `GET /api/patients/<patient_ref>/clinical-fact-ledger/reconciliation`
  - `POST /api/patients/<patient_ref>/clinical-fact-ledger/reconcile`
- Perfil V2 agrega CTA `Reconciliar V2` cuando `clinical_fact_ledger_summary.summary.conflict_count > 0`.
- El cierre escribe un fact canónico `clinician_verified` con `source_record_type=ledger_reconciliation`, registra `patient_events.event_type=clinical_fact_reconciled` y crea lineage `reconciled_by_clinician`.
- Las fuentes originales no se mutan: la resolución genera una fuente canónica nueva y auditada; no edita assessment, biomarcadores, documentos ni legacy shadows.
- El Ledger reconoce facts reconciliados como canónicos: discordancias históricas quedan en `resolved_watch`, pero ya no bloquean CTAs ni captura dirigida.
- Validación live con `TXVALUE006984`: la cola muestra `ecog_score` crítico, 2 fuentes candidatas, Perfil V2 muestra `ledger-reconciliation-v2-link`, y la pantalla no presenta overflow en desktop/móvil.
- Pruebas verdes: `py_compile`, prueba de reconciliación end-to-end con conflicto ECOG, static wiring V2 y regresión Ledger/readiness cercana `8 passed`.
- Evidencia visual: `/tmp/prostanet_clinical_fact_reconciliation_v2_desktop.png` y `/tmp/prostanet_clinical_fact_reconciliation_v2_mobile.png`.

Interpretacion: ya no solo detectamos y bloqueamos contradicciones; ahora la plataforma tiene un circuito clinico para resolverlas de forma auditable. Esto reduce ambigüedad UI/backend y prepara integraciones futuras de patologia digital, genomica y FHIR/OMOP con una verdad clinica reconciliada.

## Actualizacion de cierre: Clinical Fact Reconciliation Decision Refresh v1

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- `POST /api/patients/<patient_ref>/clinical-fact-ledger/reconcile` ahora construye snapshots antes/despues de la reconciliacion.
- El endpoint fuerza recomputo con `_recompute_after_append(..., kind="clinical_fact_reconciliation")`, invalida Perfil V2, `patient_decision_today`, Autodrive y read-models poblacionales relacionados.
- La respuesta agrega `reconciliation_impact.version=clinical_fact_reconciliation_decision_refresh_v1`, con delta de conflictos, cierre de fact, estado/titulo de `DECISION HOY`, recompute, cache invalidation y links a superficies refrescadas.
- La pantalla `/clinical-fact-reconciliation/<patient_ref>` agrega panel `Impacto sobre DECISION HOY`, mostrando despues de firmar si el conflicto se cerro, si hubo cambio estructural de decision y links al Perfil V2 refrescado y API Decision Today.
- Se mantiene el contrato de seguridad: el cierre crea un fact clinico canónico verificado, no muta fuentes originales, no crea orden externa y no entrena modelos.
- Validacion live con `TXVALUE006984`: panel de impacto renderizado, cola `ecog_score` intacta para revision, 2 formularios de fuente ganadora, sin overflow desktop/movil y consola con 0 errores criticos.
- Pruebas verdes: `py_compile`, prueba end-to-end de reconciliacion con `reconciliation_impact`, static wiring V2 y regresion Ledger/readiness cercana `6 passed`.

Interpretacion: la reconciliacion ya no termina en "se firmo el dato". Ahora la plataforma demuestra que recalculo la verdad operativa que consume Perfil V2 y DECISION HOY, cerrando el circuito UI/backend/auditoria.

## Actualizacion de cierre: DECISION HOY Ledger Quality v1

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nueva capa pura: `build_decision_today_ledger_quality(...)` clasifica la calidad de hechos clinicos que sostienen `DECISION HOY`.
- Estados expuestos:
  - `clear`: sin conflictos abiertos.
  - `blocked_by_critical_conflict`: conflicto Ledger bloqueante que puede cambiar decision.
  - `conditioned_by_open_conflict`: contradiccion no bloqueante que requiere revision.
  - `uses_reconciled_facts`: sin conflicto abierto, pero con facts reconciliados bajo vigilancia.
- `build_decision_today(...)` ahora incluye `ledger_quality`, lo propaga a `source_alignment.clinical_fact_ledger`, `audit.ledger_quality` y al item de Autodrive.
- La API `/api/patients/<patient_ref>/decision-today?refresh=1` entrega el contrato Ledger con `source_clinical_facts_mutated=false`, `external_order_created=false` y `model_trained=false`.
- Perfil V2 agrega banner `decision-today-ledger-quality-banner` dentro del hero de `DECISION HOY`, con conteo de conflictos criticos/abiertos, facts reconciliados y CTA a `/clinical-fact-reconciliation/<patient_ref>` cuando aplica.
- Validacion live con `TXVALUE006984`: `ledger_quality=blocked_by_critical_conflict`, `conflict_count=1`, `critical_conflict_count=1`; Perfil V2 renderiza el banner y enlaza a reconciliacion.
- Validacion visual desktop/movil: 0 errores de consola, solo warning conocido de Tailwind CDN, sin overflow horizontal.
- Pruebas verdes: `py_compile`, pruebas focales `4 passed`, regresion completa Decision Today + Ledger cercano `20 passed`.

Interpretacion: `DECISION HOY` ya no es una recomendacion flotando sobre datos opacos. Ahora declara la calidad del Ledger que la sostiene, separando decision clinica, conflicto de datos, reconciliacion y auditoria.

## Actualizacion de cierre: Ledger-Gated DECISION HOY Operability v1

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Si `ledger_quality.critical_conflict_count > 0`, el `next_safe_action` de `DECISION HOY` se redirige a reconciliacion clinica antes de cualquier cierre operativo.
- El gate no cambia el motor terapeutico ni inventa tratamiento: cambia la accion segura primaria a `action_mode=reconcile_clinical_fact`.
- La API `/api/patients/<patient_ref>/decision-today?refresh=1` ahora retorna:
  - `next_safe_action.label=Reconciliar conflicto critico Ledger`
  - `cta.href=/clinical-fact-reconciliation/<patient_ref>`
  - `cta.decision_field=<fact_key>`
  - `ledger_quality_gate.status=blocked_by_critical_conflict`
  - contrato seguro sin mutar fuentes, sin orden externa y sin entrenamiento.
- Perfil V2 muestra `autodrive-ledger-quality-gate` dentro de Autodrive Command Center y el boton primario abre la reconciliacion.
- Validacion live con `TXVALUE006984`: conflicto critico `ecog_score`; action primaria `/clinical-fact-reconciliation/TXVALUE006984`; banner y gate visibles en desktop/movil; sin overflow.
- Pruebas verdes: focales `3 passed`, regresion Decision Today + Ledger cercano `20 passed`.

Interpretacion: la plataforma dejo de solo advertir al clinico; ahora protege el flujo operativo. Si la verdad clinica esta contradictoria en un fact bloqueante, ProstaMed prioriza resolver la contradiccion antes de seguir capturando o decidiendo.

## Actualizacion de cierre: Reconciliation Gate-Clear Proof v1

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- `reconciliation_impact` ahora incluye snapshot compacto de `ledger_quality` y `next_safe_action` antes/despues de firmar una reconciliacion.
- El delta reporta:
  - `ledger_gate_was_active`
  - `ledger_gate_is_active`
  - `ledger_gate_cleared`
  - `next_action_before`
  - `next_action_after`
- El snapshot pre-reconciliacion fuerza recomputo para evitar leer un `DECISION HOY` viejo desde cache.
- La UI de reconciliacion agrega el bloque `Gate DECISION HOY` dentro del panel de impacto post-firma, mostrando si el gate quedo limpio o sigue activo.
- Prueba end-to-end: conflicto critico ECOG activa `action_mode=reconcile_clinical_fact`; al reconciliar, el conflicto desaparece, `critical_conflict_count=0`, `ledger_gate_cleared=true` y la accion primaria deja de ser reconciliacion.
- Validacion live sin mutar el paciente: `/api/patients/TXVALUE006984/decision-today?refresh=1` conserva gate activo por `ecog_score`; `/clinical-fact-reconciliation/TXVALUE006984` renderiza contrato de impacto y JS de `ledger_gate_cleared`; desktop/movil sin overflow y consola sin errores criticos.
- Pruebas verdes: focales `2 passed`, regresion Decision Today + Ledger cercano `20 passed`.

Interpretacion: ahora el circuito no solo bloquea por conflicto; tambien prueba auditadamente que la reconciliacion limpio el gate antes de que el clinico vuelva al Perfil V2 o a `DECISION HOY`.

## Actualizacion de cierre: Clinical Fact Ledger Population Queue v1

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nueva capa pura: `build_clinical_fact_reconciliation_population(...)` crea una cola poblacional read-only a partir de los mismos bundles Ledger por paciente.
- Nueva UI V2: `/clinical-fact-reconciliation` muestra pacientes priorizados por conflictos criticos, campo dominante, estado de calidad Ledger y CTA a `/clinical-fact-reconciliation/<patient_ref>`.
- Nueva API: `/api/clinical-fact-ledger/reconciliation/today?limit=&scan_limit=&include_clear=` y alias `/api/clinical-fact-ledger/reconciliation/population`.
- El Perfil V2 agrega CTA `Cola poblacional` desde el panel `Clinical Fact Ledger v1`.
- La cola conserva contrato seguro: `source_clinical_facts_mutated=false`, `external_order_created=false`, `model_trained=false`.
- Rendimiento corregido: el primer corte con hidratacion completa tardaba ~16s para 25 pacientes; se reemplazo por loader ligero Ledger-only y el mismo corte queda en ~2s sobre la base local real.
- Validacion live: `/clinical-fact-reconciliation?limit=25` responde 200, 13 filas en la base local, CTAs a reconciliacion por paciente, sin overflow desktop/movil y consola sin errores criticos.
- Pruebas verdes: `py_compile`, focales `3 passed` y regresion Decision Today + Ledger cercano `20 passed`.

Interpretacion: la plataforma ya no depende de abrir pacientes uno por uno para descubrir contradicciones. El Ledger empieza a comportarse como una torre hospitalaria de calidad de datos clinicos, con trazabilidad paciente-a-conflicto y cierre operativo hacia reconciliacion.

## Actualizacion de cierre: Prospective Real-World Completion Queue v1

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nueva capa read-only: `build_prospective_real_world_completion_queue(...)` reutiliza adopcion prospectiva, sprint APE y compuerta de madurez de muestra real para responder si un paciente real puede alimentar evidencia hospitalaria.
- Nueva API: `/api/platform-readiness/prospective-real-world-completion-queue?scope=summary|full&limit=` y export no-PHI `/api/platform-readiness/prospective-real-world-completion-queue/export`.
- `scope=summary` queda sin identificadores ni rutas PHI; `scope=full` conserva drill-down interno a Perfil V2 y captura longitudinal.
- Nueva UI en `/platform-readiness`: KPI `Completitud real-only` y panel `Cola real-only de completitud prospectiva` con estado, prioridad, brecha dominante y CTA V2.
- Contrato seguro: no muta hechos clinicos, no crea orden externa, no entrena modelos, no exporta PHI.
- Validacion live en la base local: `0` pacientes reales, `445` QA/sinteticos, estado `no_real_patients_enrolled`; la plataforma bloquea claims real-world y recomienda capturar el primer paciente real prospectivo con consentimiento y actor clinico.
- Validacion visual desktop/movil: seccion y KPI visibles, 0 errores de consola, solo warning conocido de Tailwind CDN, sin overflow horizontal en 390px.
- Pruebas verdes: `py_compile`, focales `2 passed`, regresion completa de readiness `44 passed`.

Interpretacion: ProstaMed ya distingue tres mundos que antes podian mezclarse: QA/smoke test, paciente real capturado y paciente real listo para evidencia. Este gate evita que la ambicion epidemiologica avance sobre datos incompletos o no consentidos.

## Actualizacion de cierre: Real-World First Patient Pilot Packet v1

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nueva capa no-PHI: `build_real_world_pilot_packet(...)` convierte la estrategia de muestra real en un runbook operativo para capturar el primer paciente real prospectivo.
- Nueva API: `/api/platform-readiness/real-world-pilot-packet?scope=summary|full&limit=`.
- Nuevo download markdown no-PHI: `/api/platform-readiness/real-world-pilot-packet/download`.
- Nueva UI en `/platform-readiness`: KPI `Paquete primer real` y panel `Paquete operativo de primer paciente real`.
- El paquete declara gates operativos: panel V2 disponible, guardia backend consentimiento/actor, primer real pendiente, consentimiento/actor, APE longitudinal, registry-ready y export no-PHI.
- El flujo oficial queda anclado a V2: Centro clinico, wizard, registro con `real_world_enrollment_panel`, historial APE, Perfil V2 y cola real-only.
- Contrato seguro: no muta hechos clinicos, no crea orden externa, no entrena modelos, no exporta PHI.
- Validacion live en base local: `packet_status=ready_to_capture_first_real_patient`, `0` reales, `445` QA/sinteticos, `no_phi_scan=pass`.
- Validacion visual desktop/movil: panel y KPI visibles, 0 errores de consola, solo warning conocido de Tailwind CDN, sin overflow horizontal.
- Pruebas verdes: `py_compile`, focales `2 passed`, regresion completa de readiness `46 passed`.

Interpretacion: ya no solo sabemos que faltan pacientes reales; ahora el equipo tiene una ruta operacional cerrada para capturar el primero sin contaminar evidencia, sin recaptura APE aislada y sin trabajar sobre legacy.

## Actualizacion de verificacion: First Real Patient Dry-Run V2

Estado al 29 de mayo de 2026: validado en base aislada de pruebas, sin tocar la base local real.

- Nuevo dry-run end-to-end: `test_first_real_patient_dry_run_v2_persists_consent_ape_profile_and_gates`.
- El flujo crea un draft `localized_initial`, abre consentimiento, firma electronicamente, finaliza el registro real y verifica persistencia.
- Se prueba que `patient_identity` queda con `is_synthetic=0`, `real_patient_consent_signed_at` y `real_patient_consent_actor_user_id`.
- Se prueba que el assessment queda ligado al paciente real como `linked`.
- Se prueba que dos mediciones APE se persisten en `biomarker_longitudinal`, evitando el modelo de APE aislado.
- Se prueba que existen `patient_consents` y `consent_signature_evidence`.
- Se prueba que Perfil V2 renderiza consentimiento, firma electronica, hash de evidencia, `psaTreatmentTimelineChart` y `psaCombinedTimelineChart`.
- Se prueba que `real_world_sample_maturity` detecta 1 paciente real, 0 sinteticos y 0 faltantes de actor/consentimiento.
- Se prueba que la cola real-only summary no filtra PHI y que `scope=full` muestra el paciente con APE `history_ready`.
- Se prueba que el paquete operativo deja de estar en `ready_to_capture_first_real_patient` al existir un primer real.
- Pruebas verdes: focal `1 passed`, regresion completa de readiness `47 passed`.

Interpretacion: el flujo V2 para el primer paciente real ya tiene prueba operacional completa. El siguiente paso ya puede ser preparar una pantalla/bitacora de ejecucion del piloto real, pero manteniendo la regla: ningun claim real-world hasta tener datos reales consentidos y registry-ready.

## Actualizacion de cierre: Real-World Pilot Execution Log v1

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nueva capa no-PHI: `build_real_world_pilot_execution_log(...)` consolida evidencia operacional del piloto real.
- Nueva API: `/api/platform-readiness/real-world-pilot-execution-log?scope=summary|full&limit=`.
- Nuevo download markdown no-PHI: `/api/platform-readiness/real-world-pilot-execution-log/download`.
- Nueva UI en `/platform-readiness`: KPI `Bitacora piloto real` y panel `Bitacora operacional del piloto real`.
- La bitacora separa evidencia de operabilidad de evidencia clinica real: dry-run V2 puede estar en `pass` aunque la base viva siga sin pacientes reales.
- Entradas actuales: dry-run V2 pass, compuerta QA vs real pass, primer paciente real institucional block, cola real-only watch, paquete operativo pass, no-PHI exports pass, claims governance block.
- Contrato seguro: no muta hechos clinicos, no crea orden externa, no entrena modelos, no exporta PHI.
- Validacion live en base local: `log_status=dry_run_verified_waiting_first_real_patient`, `dry_run_contract_status=pass`, `0` reales, `445` QA/sinteticos, `no_phi_scan=pass`.
- Validacion visual desktop/movil: panel y KPI visibles, 0 errores de consola, solo warning conocido de Tailwind CDN, sin overflow horizontal.
- Pruebas verdes: focales `2 passed`, regresion completa de readiness `49 passed`.

Interpretacion: ahora ProstaMed puede mostrar con honestidad quirurgica que el circuito real-world esta probado, pero que el uso de evidencia clinica real sigue bloqueado hasta capturar el primer paciente institucional real y cerrar su completitud.

## Actualizacion de cierre: First Real Patient Institutional Launch Mode v1

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nueva capa no-PHI: `build_real_world_first_patient_launch_mode(...)` convierte runbook y bitacora en una consola de ejecucion institucional guiada.
- Nueva API: `/api/platform-readiness/real-world-first-patient-launch-mode?scope=summary|full&limit=`.
- Nuevo download markdown no-PHI: `/api/platform-readiness/real-world-first-patient-launch-mode/download`.
- Nueva UI en `/platform-readiness`: KPI `Modo primer real` y panel `Modo de ejecucion institucional del primer real`.
- El modo declara pasos operatorios: confirmar V2, seleccionar modulo, guardar evaluacion minima, firmar consentimiento/actor, capturar historia APE, verificar Perfil V2, revisar cola real-only y congelar evidencia no-PHI solo si corresponde.
- Agrega verificaciones post-captura esperadas: incremento de muestra real, consentimiento/actor, APE no aislado, verdad del Perfil V2, cierre de cola real-only y claims gobernados.
- Contrato seguro: no muta hechos clinicos, no crea orden externa, no entrena modelos, no exporta PHI y no captura valores clinicos desde readiness.
- Validacion live en base local: `launch_mode_status=ready_for_institutional_first_real_capture`, `dry_run_contract_status=pass`, `0` reales, `445` QA/sinteticos, `no_phi_scan=pass`.
- Validacion visual desktop/movil: panel y KPI visibles, 0 errores de consola, solo warning conocido de Tailwind CDN, sin overflow horizontal.
- Pruebas verdes: `py_compile`, focales `7 passed`, regresion completa de readiness `51 passed`.

Interpretacion: el primer paciente real ya no depende de memoria operativa del equipo. ProstaMed tiene una lista viva de ejecucion y de verificaciones automaticas para que el primer real alimente Perfil V2, APE longitudinal, Decision Hoy y futura evidencia sin recaptura ni mezcla con QA.

## Actualizacion de cierre: First Real Patient V2 Launch Handoff

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- El enlace operativo del Launch Mode (`/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier`) ahora activa una banda V2 en el Centro clinico.
- Nueva banda UI no-PHI: `data-testid="first-real-v2-launch-strip"` con estado del lanzamiento, dry-run, muestra real, CTA al clasificador, readiness y guia markdown.
- La banda es query-gated: `/clinical-hub` normal no la muestra; solo aparece cuando se invoca el flujo de primer real.
- No captura datos, no muta facts, no escribe consentimiento y no expone identificadores; solo orienta al operador dentro de V2.
- Validacion live: `/clinical-hub` sin strip; `/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier` con strip, `ready_for_institutional_first_real_capture`, sin `patient_ref` ni `NSS`.
- Validacion visual desktop/movil: strip visible, sin overflow horizontal, 0 errores de consola, solo warning conocido de Tailwind CDN.
- Pruebas verdes: `py_compile` Python, focales `3 passed`, regresion completa de readiness `52 passed`.

Interpretacion: ya no hay salto ciego entre readiness y la captura real. El modo de lanzamiento aterriza en la superficie V2 correcta, con contexto operacional y sin convertir readiness en un segundo expediente.

## Actualizacion de cierre: First Real Patient V2 Launch Flow Verifier v1

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nueva capa no-PHI: `build_real_world_launch_flow_verifier(...)` audita el handoff V2 antes de capturar el primer paciente real.
- Nueva API: `/api/platform-readiness/real-world-launch-flow-verifier?scope=summary|full&limit=`.
- Nuevo download markdown no-PHI: `/api/platform-readiness/real-world-launch-flow-verifier/download`.
- Nueva UI en `/platform-readiness`: KPI `Flujo primer real` y panel `Verificador del flujo V2 del primer real`.
- El verificador comprueba rutas, UI y persistencia: Clinical Hub V2, wizard, draft clinico, consentimiento draft/firma/finalizacion, Perfil V2 interno, compuerta de muestra real, cola real-only, Launch Mode, panel de registro real, JS que activa consentimiento/actor, charts APE-tratamiento y pruebas de dry-run.
- El verificador detecto y corrigio un supuesto incorrecto: `consent_signed=1` no vive estatico en HTML; se deriva por JS desde `data-real-world-consent-flag` al activar paciente real. El contrato ahora valida el comportamiento real del panel.
- Contrato seguro: no crea pacientes, no muta facts clinicos, no entrena modelos, no crea orden externa, no exporta PHI.
- Validacion live: `flow_verifier_status=launch_flow_verified_waiting_first_real`, `ui_backend_sync_status=pass`, `23` pass, `2` watch esperados por ausencia de pacientes reales, `0` blocks, `no_phi_scan=pass`.
- Validacion visual desktop/movil: panel y KPI visibles, sin overflow horizontal, sin `patient_ref` ni `NSS` dentro del panel, 0 errores de consola y solo warning conocido de Tailwind CDN.
- Pruebas verdes: `py_compile`, focales del verificador y ensayo, regresion completa de readiness `55 passed`.

Interpretacion: ahora ProstaMed tiene una prueba operacional visible de que el primer real puede avanzar por V2 sin salto ciego entre UI y backend. Este es el tipo de cimiento que necesitamos antes de intentar evidencia real-world, costos o investigacion multicentro.

## Actualizacion de cierre: First Real Institutional Launch Rehearsal V2

Estado al 29 de mayo de 2026: implementado, validado en base aislada de pruebas y reflejado en localhost normal `127.0.0.1:8093`.

- Nuevo ensayo end-to-end: `test_first_real_institutional_launch_rehearsal_v2_from_strip_to_profile`.
- El ensayo inicia en `/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier` y verifica que el launch strip V2 esta visible, sin `patient_ref` ni `NSS`.
- Abre `/wizard/localized_initial?real_world_enrollment=1` y confirma panel real-world, JS de enrollment, `consent_signed` oculto en 0 por defecto y `actor_user_id`.
- Crea draft clinico `localized_initial`, firma consentimiento, finaliza registro real en DB aislada y confirma `is_synthetic=0`, consentimiento y actor.
- Verifica que APE longitudinal no se duplica: exactamente 2 filas PSA en `biomarker_longitudinal` pese a existir PSA basal en el draft.
- Abre Perfil V2 y confirma consentimiento, firma electronica, `psaTreatmentTimelineChart` y `psaCombinedTimelineChart`.
- Revisa sample maturity y cola real-only: 1 real, 0 sinteticos, actor/consentimiento presentes, summary no-PHI y fila full con `ape_status=history_ready`.
- Revisa el verificador post-captura: UI/backend `pass`, claims externos bloqueados y summary no-PHI.
- Agrega el contrato `institutional_launch_rehearsal_contract` al verificador del handoff, para que readiness falle si se rompe este ensayo.
- Validacion live del verificador: `flow_verifier_status=launch_flow_verified_waiting_first_real`, `ui_backend_sync_status=pass`, `23` pass, `2` watch, `0` blocks, `no_phi_scan=pass`, `source_clinical_facts_mutated=false`, `external_order_created=false`, `model_trained=false`.
- Validacion visual live: `/platform-readiness#real-world-launch-flow-verifier` muestra el KPI, el contrato de ensayo y el panel sin PHI ni overflow horizontal en desktop/movil.
- Artefactos visuales: `output/playwright/prostanet-real-world-launch-flow-verifier-rehearsal-desktop.png` y `output/playwright/prostanet-real-world-launch-flow-verifier-rehearsal-mobile.png`.
- Pruebas verdes: focales `3 passed`, regresion completa de readiness `55 passed`.

Interpretacion: ahora no solo tenemos piezas conectadas; tenemos un ensayo institucional que prueba el recorrido como lo usara el equipo. Esto reduce riesgo de recaptura, de divergencia UI/backend y de creer que tenemos evidencia real-world cuando solo tenemos operabilidad QA.

## Actualizacion de cierre: First Real Context Propagation V2

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Brecha detectada: el launch strip activaba el modo de primer real, pero el link dinamico del clasificador rapido podia abrir el wizard sin preservar explicitamente `real_world_enrollment=1`.
- Correccion V2: `clinical_hub_quick_classifier.js` ahora construye el enlace con `prefill_source=clinical_hub` y conserva `real_world_enrollment=1` cuando el hub se abre desde el launch strip.
- Correccion V2 adicional: las tarjetas de modulo en el Clinical Hub tambien agregan `?real_world_enrollment=1` cuando el modo institucional esta activo.
- Nuevo contrato en el verificador: `quick_classifier_real_world_handoff_v2`.
- Validacion live: `/clinical-hub?real_world_enrollment=1` muestra launch strip, todas las tarjetas de wizard preservan el parametro real-world, el verificador reporta `contract_count=25`, `pass_count=23`, `watch_count=2`, `block_count=0`.
- Validacion Playwright: clasificacion localizada desde el launch strip genero `/wizard/localized_initial?prefill_source=clinical_hub&real_world_enrollment=1`; el wizard conservo el panel real-world, `consent_signed=0` por defecto y actor deshabilitado hasta activacion humana.
- Artefacto visual: `output/playwright/prostanet-first-real-classifier-to-wizard-handoff.png`.
- Pruebas verdes focales: `4 passed`.

Interpretacion: el primer real ya no pierde contexto entre el Clinical Hub V2 y el wizard. El flujo sigue siendo seguro: el contexto operativo viaja, pero el consentimiento y actor no se autoactivan sin accion humana.

## Actualizacion de cierre: First Real Wizard Guard V2

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Brecha detectada: aunque el contexto `real_world_enrollment=1` ya viajaba del Clinical Hub al wizard, dentro del wizard podia no ser suficientemente visible para el operador antes de preparar el registro longitudinal.
- Correccion V2: el wizard muestra una guardia no-PHI `first-real-wizard-handoff-guard` cuando llega desde el launch strip, con estado de launch mode, dry-run, muestra real y CTAs a launch strip/verificador.
- Correccion V2 adicional: el bloque de registro longitudinal muestra `first-real-wizard-registration-guard` antes del panel real-world, recordando que `Paciente real` solo debe activarse con consentimiento firmado, actor clinico e historia APE longitudinal.
- Seguridad preservada: la guardia no escribe hechos clinicos, no crea orden externa, no entrena modelo y no firma consentimiento. El panel conserva `consent_signed=0` por defecto y actor deshabilitado hasta accion humana.
- Ajuste visual movil: los valores largos de selects clinicos (`pn-select-value`) ahora pueden partirse en linea dentro del control, evitando overflow visual en el wizard movil.
- Validacion live: `/wizard/localized_initial?prefill_source=clinical_hub&real_world_enrollment=1` responde `200`, renderiza ambas guardias y el panel real-world; el verificador sigue en `contract_count=25`, `pass_count=23`, `watch_count=2`, `block_count=0`, `no_phi_scan=pass`.
- Validacion Playwright desktop/movil: guardias visibles, panel presente, `consent_signed=0`, actor deshabilitado, `source_clinical_facts_mutated=false`, `external_order_created=false`, `model_trained=false`, `0` errores de consola y solo warning conocido de Tailwind CDN.
- Artefactos visuales: `output/playwright/prostanet-first-real-wizard-guard-desktop.png` y `output/playwright/prostanet-first-real-wizard-guard-mobile.png`.
- Pruebas verdes focales: `4 passed`.

Interpretacion: el primer real ya tiene continuidad operacional visible desde Clinical Hub V2 hasta wizard y registro longitudinal. Este cierre reduce el riesgo de que el operador capture el primer real como QA por accidente, sin relajar el control humano de consentimiento.

## Actualizacion de cierre: First Real Visual Dry-Run V2

Estado al 29 de mayo de 2026: ejecutado en localhost normal `127.0.0.1:8093` con navegador real y persistencia validada en base aislada.

- Flujo visual ejecutado: `/wizard/localized_initial?prefill_source=clinical_hub&real_world_enrollment=1` con paciente localizado sintetico de validacion, evaluacion del modulo, preparacion de registro longitudinal y activacion manual del panel `Paciente real`.
- Resultado clinico visible: el wizard genero recomendacion localizada trazable y habilito `Preparar registro longitudinal`.
- Registro preparado: `registrationPhase` visible, `first-real-wizard-registration-guard` presente, `real-world-enrollment-panel` presente y `42` variables importadas sin recaptura manual del modulo.
- Seguridad antes de activacion: `consent_signed=0`, toggle real apagado y actor deshabilitado.
- Activacion manual validada: al marcar `Paciente real`, `consent_signed=1`, actor requerido/habilitado y payload visual con `is_real_patient=1`, `actor_user_id=99`.
- APE en UI: el payload visual conserva un solo `psa_history` importado desde el PSA basal del wizard (`source=wizard_imported_psa`), sin crear multiples mediciones en UI.
- No se finalizo paciente real en localhost: sample maturity live permanece `real_patient_count=0`, cola real-only en `no_real_patients_enrolled` y claims externos bloqueados.
- Persistencia/no duplicacion comprobada en base aislada: contratos `test_first_real_patient_dry_run_v2_persists_consent_ape_profile_and_gates` y `test_first_real_institutional_launch_rehearsal_v2_from_strip_to_profile` siguen verdes; prueban consentimiento, actor, Perfil V2, cola real-only y APE longitudinal sin duplicar la medicion basal del draft.
- Verificador live: `contract_count=25`, `pass_count=23`, `watch_count=2`, `block_count=0`, `no_phi_scan=pass`.
- Artefactos visuales: `output/playwright/prostanet-first-real-visual-dry-run-registration-desktop.png` y `output/playwright/prostanet-first-real-visual-dry-run-registration-mobile.png`.
- Pruebas verdes focales: `2 passed` para persistencia de primer real y ensayo institucional.

Interpretacion: ya tenemos evidencia de que un operador puede llegar desde el contexto institucional hasta el registro longitudinal, activar manualmente el modo real y construir el payload correcto sin finalizar un paciente accidentalmente. La persistencia real queda cubierta en base aislada para proteger la base local mientras seguimos preparando el primer real institucional.

## Actualizacion de cierre: First Real Operator Checklist V2

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Nueva checklist operatoria dentro del launch strip V2: `first-real-v2-operator-checklist`.
- La checklist muestra dos capas: pasos guiados de readiness y estado local de sesion.
- Estado local cubierto: launch strip abierto, clasificador visible, modulo clasificado, wizard con contexto, registro preparado, panel real activado, actor presente e historia APE lista.
- El estado local vive en `sessionStorage`; no guarda PHI, no firma consentimiento, no muta hechos clinicos, no crea orden externa y no entrena modelos.
- El wizard V2 registra pasos locales al abrir con `real_world_enrollment=1`, preparar registro longitudinal, activar Paciente real, documentar actor y detectar payload APE.
- El clasificador rapido marca `module_classified` y preserva el contexto hacia `/wizard/<module>?prefill_source=clinical_hub&real_world_enrollment=1`.
- Correccion visual detectada en navegador: se elimino el texto basura de Jinja `<built-in method copy...>` usando acceso explicito a diccionario en la plantilla.
- Validacion live: el verificador reporta `contract_count=26`, `pass_count=24`, `watch_count=2`, `block_count=0`, `ui_backend_sync_status=pass` y `no_phi_scan=pass`.
- Validacion Playwright desktop: flujo Clinical Hub -> wizard -> evaluacion -> registro longitudinal -> activacion visual de panel real -> retorno al hub con `8/8 pasos locales`.
- Validacion Playwright movil 390px: checklist visible, `8/8 pasos locales`, sin overflow horizontal.
- Artefactos visuales: `output/playwright/prostanet-first-real-operator-checklist-initial.png`, `output/playwright/prostanet-first-real-operator-checklist-after-dry-run.png`, `output/playwright/prostanet-first-real-operator-checklist-mobile.png`.
- Pruebas verdes: `py_compile`, focales `4 passed`, regresion completa de readiness `55 passed`.

Interpretacion: el primer real ya tiene un tablero operativo inmediato, no solo contratos dispersos. El equipo puede ver que el flujo V2 fue recorrido de forma segura antes de finalizar paciente, y cada paso sigue bajo control humano.

## Actualizacion de cierre: First Real APE Series Guard V2

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Brecha detectada: el checklist podia marcar `ape_payload_ready` con una sola medicion importada, aunque el contrato clinico dice historia APE longitudinal.
- Correccion UI V2: `first_real_launch_checklist.js` exige 2 mediciones APE validas con fecha para poner `APE listo` en pass; si falta serie, queda en `watch`.
- Correccion wizard V2: antes de abrir consentimiento del primer real, `requireFirstRealApeSeriesBeforeConsent` bloquea el flujo si `Paciente real` esta activo y hay menos de 2 mediciones APE fechadas.
- Correccion backend: `create_consent_draft` rechaza el contexto `first_real_wizard_v2` o `real_world_enrollment_mode=prospective_v2` con paciente real si no hay 2 puntos APE validos.
- Compatibilidad preservada: no cambia `/api/register_patient` ni la capacidad de registrar pacientes reales incompletos para que la cola real-only los marque como `needs_ape_history`; el bloqueo aplica al flujo prospectivo de primer real con consentimiento.
- Validacion Playwright: con un solo APE importado, el wizard muestra error y no abre modal de consentimiento; con dos mediciones fechadas, abre el consentimiento institucional y marca `ape_payload_ready=pass`.
- Nuevo contrato de verificacion: `first_real_ape_series_guard_contract`.
- Artefactos visuales: `output/playwright/prostanet-first-real-ape-series-guard-blocked.png` y `output/playwright/prostanet-first-real-ape-series-guard-consent-ready.png`.
- Pruebas verdes focales: `4 passed`; sub-suite de primer real con dry-run y ensayo institucional: `6 passed`; regresion completa de readiness `56 passed`; `py_compile` verde.

Interpretacion: APE deja de ser una casilla cosmetica. Para el primer real prospectivo, ProstaMed ya fuerza una serie minima antes de generar consentimiento y evidencia real-world, lo cual protege la torre APE, outcomes 12/24 semanas y el futuro tablero epidemiologico.

## Actualizacion de cierre: Profile V2 APE History Readiness

Estado al 29 de mayo de 2026: implementado y validado en localhost normal `127.0.0.1:8093`.

- Brecha detectada en validacion live: un paciente registrado con una sola medicion APE podia aparecer como `history_ready` porque el pipeline auto-seed agregaba un basal bloqueado con el mismo valor. Ese basal debe renderizarse por auditoria, pero no cuenta como segunda medicion longitudinal.
- Correccion backend V2: `psa_obs.ape_history_readiness` clasifica `missing_psa`, `uninterpretable_series`, `missing_sample_date`, `single_psa_point`, `insufficient_history` y `history_ready`.
- Correccion anti-recaptura: el conteo longitudinal excluye duplicados `intake_baseline (auto-seed unified)` cuando repiten el mismo APE ya capturado por el clinico.
- Correccion UI V2: `patient_profile_v2.html` muestra un banner `profile-v2-ape-history-readiness` dentro de la torre APE con estado, conteo 1/2 o 2/2, mensaje clinico, politica anti-recaptura y CTA a `/longitudinal-capture/<nss>?decision_field=psa_history`.
- Seguridad preservada: el read model no muta hechos clinicos, no crea orden externa y no entrena modelo.
- Validacion HTTP: paciente sintetico con un APE + basal auto-seed queda `single_psa_point`; tras anexar APE de seguimiento via `/api/longitudinal/<nss>/append`, cambia a `history_ready` y refresca `patient_profile_v2_psa_tower`.
- Validacion Playwright desktop/movil: banner visible, sin errores de consola, solo warning conocido de Tailwind CDN; existen 4 canvases de torre/timelines en V2.
- Artefactos visuales: `output/playwright/prostanet-profile-v2-ape-readiness-single-point.png`, `output/playwright/prostanet-profile-v2-ape-readiness-history-ready.png` y `output/playwright/prostanet-profile-v2-ape-readiness-mobile.png`.
- Pruebas verdes: `tests/test_v2_adapters.py` completo `28 passed`; focales de template/costos/timeline `3 passed`; captura longitudinal APE `2 passed`; `py_compile` verde.

Interpretacion: el Perfil V2 ya no confunde APE aislado con historia longitudinal. Esto protege la torre APE, el registro 12/24 semanas y el futuro tablero epidemiologico contra evidencia inflada por auto-baselines.

## Actualizacion de cierre: Multi-Stage Capture Integrity V2

Estado al 30 de mayo de 2026: validado en localhost normal `127.0.0.1:8093` con pruebas focales, API/DOM y flujo visual en navegador.

- Brecha detectada: no bastaba cerrar captura inicial; tambien habia que garantizar localizado, falla bioquimica/post-local, mCSPC/mHSPC, m0 CRPC y m1 CRPC antes de agregar mas logica clinica.
- Correccion UI V2: todos los wizards clinicos relevantes ahora suprimen defaults clinicos del schema; los selects arrancan en `No documentado` real y los numericos quedan vacios.
- Correccion OCCAM: el widget sigue disponible, pero queda `occamTouched=false` y no produce expectativa de vida ni campos derivados hasta que el clinico capture entradas del modelo.
- Correccion payload: `buildWizardPayload` ignora campos OCCAM y distribucion metastasica no tocados, evitando que el borrador clinico importe expectativa de vida, M0, conteos cero u otros derivados falsos.
- Correccion PSAD: el campo no se pide manualmente en la superficie principal; se deriva de PSA + volumen prostatico. En la prueba PSA 12 y volumen 40 ml generaron PSAD `0.30`.
- Correccion APE longitudinal: al preparar registro, el wizard no pide APE dos veces; crea una sola serie `psa_history` importada desde el PSA capturado y deja el historial abierto para seguimiento.
- Correccion de linea terapeutica: en localizado/diagnostico el contexto de APE queda limitado a `Sin linea documentada`; m0/mCSPC/mCRPC abren opciones terapeuticas solo cuando el estado clinico lo justifica.
- Correccion de gates fuera de estado: localizado, BCR/post-local, mCSPC/mHSPC, m0 CRPC y m1 CRPC no cargan por defecto `rapid_anc_drop_for_docetaxel`, `rapid_platelet_drop_for_niraparib`, `bone_marrow_blasts_percent`, `cumulative_docetaxel_dose_mg_m2`, citopenias PARP/RLT ni banderas especificas de niraparib fuera de familia/trigger.
- Correccion del router longitudinal: BCR abre PSA actual, PSA al momento de BCR y PSMA de rescate sin testosterona/CTCAE; mCSPC, m0 CRPC y m1 CRPC abren PSA, testosterona, ECOG y toxicidad cuando si corresponde.
- Validacion visual: rutas `/wizard/localized_initial`, `/wizard/recurrence_bcr`, `/wizard/post_radiotherapy_or_local_salvage`, `/wizard/mcspc_high_volume_sync`, `/wizard/m0_crpc` y `/wizard/m1_crpc` cargan en `127.0.0.1:8093`, sin errores de consola, sin defaults falsos y con composicion metastasica vacia hasta interaccion del clinico.
- Pruebas verdes: `tests/test_multistage_capture_sequence.py`, `tests/test_initial_staging_capture_sequence.py`, `tests/test_pivotal_gate_progressive_disclosure_v2.py`, `tests/test_modular_engine.py`, `tests/test_diagnostic_workup_progressive_sequence.py` y `tests/test_v2_initial_staging_persistence_closure.py`: `101 passed`.
- Radar actualizado: `world_class_prostate_platform_benchmark_v1` incorpora `multistage_capture_integrity` como logro y `no_silent_default_facts` como principio operativo.

Interpretacion: esta es una compuerta esencial para la meta mundial. Antes de conectar patologia digital, genomica, FHIR/OMOP o analitica causal, ProstaMed debe demostrar que ningun estadio fabrica hechos por defecto, recaptura APE o arrastra campos terapeuticos irrelevantes. Con este cierre, la plataforma se mueve de "mucho poder clinico" hacia "poder clinico gobernado".

## Fuentes externas

- Flatiron OncoEMR: https://flatiron.com/oncology/oncology-ehr
- CancerLinQ: https://www.cancerlinq.org/about
- Epic Cosmos: https://cosmos.epic.com/about
- Tempus Lens: https://www.tempus.com/life-sciences/lens/
- ArteraAI Prostate Test mHSPC launch in Tempus ecosystem: https://www.tempus.com/news/pr/tempus-launches-arteraai-prostate-test-for-metastatic-patients-marking-the-first-prostate-digital-pathology-algorithm-in-the-tempus-ecosystem-available-for-clinical-use/
- Decipher Prostate: https://decipherbio.com/decipher-prostate/physicians/decipher-prostate-overview/
- Paige Prostate: https://info.paige.ai/prostate
- Varian ARIA: https://www.varian.com/products/software/information-systems/aria-oncology-information-system
- Elekta MOSAIQ: https://www.elekta.com/products/oncology-informatics/elekta-one/oncology-care/medical-oncology/
- PCOR-ANZ: https://prostatecancerregistry.org/
- HL7 mCODE: https://hl7.org/fhir/us/mcode/
- OMOP Oncology Extension: https://ohdsi.github.io/CommonDataModel/oncology.html
- NCCN Prostate Cancer v3.2026 summary: https://pubmed.ncbi.nlm.nih.gov/41213253/
- FDA Pluvicto indication expansion: https://www.fda.gov/drugs/resources-information-approved-drugs/fda-expands-pluvictos-metastatic-castration-resistant-prostate-cancer-indication
