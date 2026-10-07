# Cobertura de requisitos (los 116 identificadores)

**Qué se mapea.** Cada requisito del PDF de la evaluación, con los identificadores de
[`ASSESSMENT_REQUIREMENTS.md`](../../ASSESSMENT_REQUIREMENTS.md), se asocia a su implementación, su evidencia y un estado. El
PDF es la referencia autorizada. Los estados significan:
- **PASS:** implementado y con evidencia.
- **PARTIAL:** queda algo pendiente, indicado en la fila.
- **PENDING (owner):** una acción que solo puede realizar el propietario.
- **N/A:** un elemento de proceso sin artefacto.

## Claves de evidencia
| Clave | Ubicación |
|---|---|
| UI02 | `evidence/14-evaluation-client/ui02-browser-e2e/ui02-report.md`: navegador real contra el stack real de la VM |
| BV1 | `evidence/13-agent-actions-vm/vm-validation.md`: AGENT-01BV1, Grok real + n8n real, 139/139 |
| AV1 | `evidence/11-agent/vm-validation.md`: AGENT-01AV1, agente de solo lectura, Grok real, 129/129 |
| RAGV | `evidence/10-rag/vm-validation.md`: RAG-01V1, embeddings reales + pgvector, 138/138 |
| A2V | `evidence/06-app02-runtime/summary.md`: APP-02V1, API de tickets en la VM, 80/80 |
| N8V | `evidence/08-n8n-foundation/`: N8N-01V1, 32/32 |
| L3V | `evidence/09-leads-n8n/`: APP-03BV1, solicitud comercial (lead) a través de n8n real, 106/106 |
| PRE | `evidence/00-preflight/`, `evidence/01-docker/`, PROJECT_STATE "VM environment" / "Docker status" |
| T | Pruebas automatizadas en `tests/` (410 passed / 8 skipped en la entrega) y `src/frontend/src/test/` (17/17) |
| AUD | [`AUDIT_FINDINGS.md`](../../AUDIT_FINDINGS.md) |
| F2 | `evidence/15-final-deployment/final-deployment-report.md`: FINAL-02, despliegue permanente + evidencia real final, 35/35 |

## Matriz

### Objetivo y alcance
| ID | Implementación | Evidencia | Estado / limitación |
|---|---|---|---|
| REQ-GEN-01 | Solución completa: RAG, tickets, solicitudes comerciales, estado de tickets, escalados humanos, en la VM Ubuntu con Docker | UI02, BV1, F2 | **PASS**. Desplegada, validada y dejada en ejecución en la VM (FINAL-02) |
| REQ-GEN-02 | Controles: autenticación, confirmación, idempotencia, auditoría, pruebas | AUD, T, BV1 | **PASS** |
| REQ-GEN-03 | Plazo de entrega | — | N/A (propietario/correo electrónico) |
| REQ-GEN-04 | Recursos y estado inicial de la VM documentados | PRE | **PASS** |
| REQ-GEN-05 | Bloqueos solicitados (clave/presupuesto/modelo de OpenRouter, autorización para instalar Docker) | PROJECT_STATE "Open blockers", "OpenRouter" | **PASS** |
| REQ-GEN-06 | Solo datos sintéticos (clientes de semilla, direcciones `example.test`); no se envían correos ni mensajes | `0002_synthetic_seed.sql`, BV1 | **PASS** |
| REQ-GEN-07 | Elementos incompletos declarados | esta matriz, `KNOWN_LIMITATIONS.md` | **PASS** |

### Arquitectura y responsabilidades
| ID | Implementación | Evidencia | Estado |
|---|---|---|---|
| REQ-ARCH-01 | `compose.yaml` (db, backend, n8n, web) | BV1, UI02 | **PASS** |
| REQ-ARCH-02 | Workflow de n8n `nexo-lead-create` integrado en la confirmación de la solicitud comercial | L3V, BV1 §17, UI02 #12 | **PASS** |
| REQ-ARCH-03 | RAG con pgvector y referencias `<file> § <section>` | RAGV, AV1, UI02 #2 | **PASS** |
| REQ-ARCH-04 | Agente `/chat` (FastAPI + Grok a través de OpenRouter) | AV1, BV1 | **PASS** |
| REQ-ARCH-05 | Tablas de PostgreSQL para tickets, solicitudes comerciales y escalados humanos, más la API | A2V, L3V, BV1 | **PASS** |
| REQ-ARCH-06 | Chat web (servicio `web`) | UI02 | **PASS** |
| REQ-ARCH-07 | Log de auditoría JSON por petición, correlacionado por ID de petición / conversación | BV1 §24, UI02 | **PASS** |
| REQ-RESP-01 | El agente interpreta, recupera y propone; nunca ejecuta | `docs/ARCHITECTURE.md`, AV1 | **PASS** |
| REQ-RESP-02 | RAG solo para conocimiento; datos en vivo desde la API | AV1, UI02 #16 | **PASS** |
| REQ-RESP-03 | Solicitudes comerciales solo a través del workflow de n8n → `/internal/leads` | L3V, BV1 §17 | **PASS** |
| REQ-RESP-04 | La API valida permisos, datos e idempotencia, y almacena | A2V, T | **PASS** |
| REQ-RESP-05 | El cliente web cubre el recorrido completo | UI02 | **PASS** |

### Infraestructura y LLM
| ID | Implementación | Evidencia | Estado |
|---|---|---|---|
| REQ-INFRA-01 | Estado inicial de la VM documentado | PRE | **PASS** |
| REQ-INFRA-02 | Docker + Compose instalados (con autorización del propietario) y usados en la VM | PRE, BV1 | **PASS** |
| REQ-INFRA-03 | SSH y `ufw` sin modificar; puertos solo en loopback | PRE, BV1 §6 | **PASS** |
| REQ-LLM-01 | Clave obtenida de forma privada; presupuesto de 30 EUR y selección de modelo confirmados con el contacto | PROJECT_STATE "OpenRouter" | **PASS** |
| REQ-LLM-02 | OpenRouter para chat y embeddings | AV1, RAGV | **PASS** |
| REQ-LLM-03 | Estrategia de embeddings documentada (text-embedding-3-small, 1536 d, calibración del umbral) | `evidence/10-rag/architecture.md`, `calibration.json` | **PASS** |
| REQ-LLM-04 | Modelo servido registrado en cada llamada | BV1 §24 | **PASS** |
| REQ-LLM-05 | Razonamiento excluido y no almacenado | BV1 §24, UI02 #23 | **PASS** |

### RAG y base de conocimiento
| ID | Implementación | Evidencia | Estado / limitación |
|---|---|---|---|
| REQ-RAG-01 | Preguntas sobre servicios, horarios, precios y procedimientos respondidas desde el RAG | AV1 K1–K4, UI02 #2 | **PASS** |
| REQ-RAG-02 | Referencias `<file> § <section>` | AV1, UI02 #2 | **PASS** |
| REQ-RAG-03 | Información ausente reconocida (sin respuesta del modelo por debajo del umbral) | AV1, UI02 #3 | **PASS** |
| REQ-RAG-04 | Sin precios ni plazos inventados (control de fundamentación sobre cifras y citas) | AV1 (K3, cifras inventadas bloqueadas) | **PASS** |
| REQ-RAG-05 | Documentos pasados como datos, nunca como instrucciones de sistema | AV1 P3/S5 | **PASS** |
| REQ-RAG-06 | Estado de tickets nunca desde el RAG | UI02 #16 | **PASS** |
| REQ-RAG-07 | Los cuatro documentos de `knowledge/`, indexados | RAGV (4 documentos / 10 secciones) | **PASS** |
| REQ-RAG-08 | Actualización de 120 € → 150 €: reingesta, misma referencia, precio antiguo eliminado, corpus canónico restaurado; procedimiento en README / runbook §9 | RAGV, F2 #2–3 | **PASS**: recuperación y respuesta del chat ("150 € más IVA", misma referencia), y después restaurado a 120 € |
| REQ-KB-01 | `knowledge/01_services.md` | T (pruebas de contenido literal), RAGV | **PASS** |
| REQ-KB-02 | `knowledge/02_support_policy.md` | T, RAGV, UI02 #2 | **PASS** |
| REQ-KB-03 | `knowledge/03_commercial_policy.md` | T, AV1 K3/K4 | **PASS** |
| REQ-KB-04 | `knowledge/04_security_policy.md`, y aplicado en el código (eliminación → escalado humano; sin datos ajenos) | T, UI02 #15, #17 | **PASS** |

### API de negocio
| ID | Implementación | Evidencia | Estado / limitación |
|---|---|---|---|
| REQ-API-01 | `POST /tickets/prepare` + `/confirm`; `GET /tickets/{id}`; `POST /leads/prepare` + `/confirm` (→ n8n); `POST /handoffs`; `GET /health` (rutas adaptadas documentadas en el README) | A2V, L3V, T | **PASS** |
| REQ-API-02 | Validación con Pydantic (campos adicionales prohibidos), autenticación bearer | T, A2V | **PASS** |
| REQ-API-03 | Los esquemas de ticket, solicitud comercial y escalado humano tienen todos los campos mínimos, UUID generados y referencias T- | migraciones 0001–0009, BV1 | **PASS** |
| REQ-API-04 | Dos clientes sintéticos con un ticket cada uno (T-1001 / T-1002); datos iniciales, copia de seguridad/restauración y reinicialización documentados en el README | `0002_synthetic_seed.sql`, README, F2 #6–7 | **PASS**: copia de seguridad y restauración ejecutadas en la VM (un registro posterior a la copia de seguridad eliminado por la restauración, todo lo demás idéntico) |

### Tickets, solicitudes comerciales, n8n, escalados humanos
| ID | Implementación | Evidencia | Estado |
|---|---|---|---|
| REQ-TICKET-01 | Recogida de datos, clasificación, prioridad crítica/normal | BV1 §11, §13; UI02 #4, #11 | **PASS** |
| REQ-TICKET-02 | Tarjeta de resumen más confirmación antes de crear | UI02 #4–7 | **PASS** |
| REQ-TICKET-03 | UUID real y referencia T- a partir de la fila confirmada en base de datos | BV1 §11, UI02 #7 | **PASS** |
| REQ-TICKET-04 | Fallo de la API → no se afirma la creación | T (BD caída), BV1, UI02 #13/#19 | **PASS** |
| REQ-TICKET-05 | Estado desde PostgreSQL a través de la API, sigue los cambios de la base de datos | BV1 §15, UI02 #16 | **PASS** |
| REQ-LEAD-01 | Empresa, contacto, necesidad, correo electrónico (el correo debe aparecer en el mensaje) | BV1 §17, UI02 #12 | **PASS** |
| REQ-LEAD-02 | Confirmación y después workflow de n8n → escritor privado | L3V, BV1 §17, UI02 #12 | **PASS** |
| REQ-LEAD-03 | No se prometen precios, descuentos, contratos ni fechas (indicado en el resumen) | UI02 #12 | **PASS** |
| REQ-N8N-01 | Workflow de n8n funcional en la operación del agente | L3V, BV1, UI02 | **PASS** |
| REQ-N8N-02 | `n8n/workflows/nexo-lead-create.json` sin credenciales | T (`test_lead_workflow_static.py`) | **PASS** |
| REQ-HANDOFF-01 | Incidencia crítica, petición explícita, caso no seguro (eliminación) | BV1 §11/§19, UI02 #7/#14/#15 | **PASS** |
| REQ-HANDOFF-02 | Tabla `handoffs` | BV1, UI02 | **PASS** |
| REQ-HANDOFF-03 | «pendiente; nadie lo ha recogido todavía; sin plazo garantizado» | UI02 #7/#14 | **PASS** |
| REQ-HANDOFF-04 | No se envían correos ni mensajes | código, BV1 | **PASS** |

### Autenticación, aislamiento, confirmación, idempotencia
| ID | Implementación | Evidencia | Estado |
|---|---|---|---|
| REQ-AUTH-01 | Identidad = solo búsqueda por SHA-256(bearer) | T, BV1 §16 | **PASS** |
| REQ-AUTH-02 | El `customer_id` del chat no tiene autoridad | BV1 §16, UI02 #17 | **PASS** |
| REQ-AUTH-03 | Dos clientes sintéticos con tokens | semilla + `.env` | **PASS** |
| REQ-AUTH-04 | La API valida autenticación y permisos en cada petición | T, A2V | **PASS** |
| REQ-AUTH-05 | Tokens generados en el despliegue y compartidos de forma privada; nunca en la documentación ni en el PDF | README, escaneos de secretos | **PASS** |
| REQ-ISO-01 | Consultas acotadas al propietario en el backend | T, BV1 §16 | **PASS** |
| REQ-ISO-02 | Ticket ajeno = inexistente, sin filtrar contenido | A2V, BV1 §16, UI02 #17 | **PASS** |
| REQ-ISO-03 | No se muestran tickets ni contactos ajenos (tampoco bajo inyección) | UI02 #17/#18 | **PASS** |
| REQ-CONF-01 | Control de confirmación de tickets | UI02 #4–7 | **PASS** |
| REQ-CONF-02 | Token de versión; los datos modificados requieren una nueva confirmación | AUD (AGENT01B-01), BV1 §21, UI02 #9 | **PASS** |
| REQ-CONF-03 | Control de confirmación de solicitudes comerciales | UI02 #12 | **PASS** |
| REQ-CONF-04 | Ningún registro antes; ID real después | BV1 §11, UI02 #4–7 | **PASS** |
| REQ-IDEMP-01 | Claves de idempotencia (API `Idempotency-Key`; chat `chat:<conversation>:<action>`) | A2V, BV1 §12/§14, UI02 #8 | **PASS** |
| REQ-IDEMP-02 | Aplicada por la API / los servicios | T | **PASS** |

### Fallos, inyección, persistencia
| ID | Implementación | Evidencia | Estado / limitación |
|---|---|---|---|
| REQ-FAIL-01 | Timeouts, errores y caídas devuelven 503/502 + código (LLM, DB, backend, n8n) | T (matriz de stubs), BV1 §18, UI02 #13, F2 #4–5 | **PASS**: caídas reales de n8n, backend y PostgreSQL en la VM; timeout/429/5xx del LLM mediante stubs TEST |
| REQ-FAIL-02 | Respuesta perdida: el reenvío devuelve el mismo objeto; documentado | BV1 §14, `ARCHITECTURE.md` §3 | **PASS** |
| REQ-FAIL-03 | Sin falsos éxitos | BV1 §18, UI02 #13/#19 | **PASS** |
| REQ-INJ-01 | Documento de prueba `05_injection_test.md` (temporal) recuperado en top-1 y sin autorizar nada | AV1 P3 | **PASS** |
| REQ-INJ-02 | Los documentos son datos | AV1 S5, UI02 #18 | **PASS** |
| REQ-PERS-01 | Volúmenes con nombre | BV1 §22 | **PASS** |
| REQ-PERS-02 | Reinicio → datos conservados, servicio recuperado | BV1 §22, UI02 #22 | **PASS** |
| REQ-PERS-03 | Copia de seguridad, restauración y parada/arranque documentados (README) y ejecutados | README, F2 #6–8 | **PASS** |

### Docker, trazabilidad, seguridad
| ID | Implementación | Evidencia | Estado |
|---|---|---|---|
| REQ-DOCKER-01 | `compose.yaml`, Dockerfiles, `.env.example` (solo marcadores de posición) | T (`test_compose.py`) | **PASS** |
| REQ-DOCKER-02 | Imágenes con versión fijada (sin `latest`) | T | **PASS** |
| REQ-DOCKER-03 | Volúmenes, `restart: unless-stopped`, healthchecks | T, BV1 | **PASS** |
| REQ-DOCKER-04 | Solo puertos en loopback; DB no publicada; UI de n8n mediante un túnel | T, BV1 §6, UI02 | **PASS** |
| REQ-DOCKER-05 | Sin contenedores privilegiados ni socket de Docker; usuarios y permisos documentados | T, `ARCHITECTURE.md` §9 | **PASS** |
| REQ-TRACE-01 | Mensaje → recuperación → decisión → confirmación → workflow de n8n → API → resultado, un único ID de petición | BV1 §24, UI02 #12 | **PASS** |
| REQ-TRACE-02 | ID de petición, fuentes, acción, resultado, error, duración, modelo | BV1 §24 | **PASS** |
| REQ-TRACE-03 | Correlacionado por petición y conversación | BV1 §24 | **PASS** |
| REQ-SEC-01 | Sin credenciales en el código, capturas de pantalla, logs ni documentación (escaneos en cada ejecución, más un escaneo final del repositorio) | BV1 §24, UI02 #23, escaneo FINAL-01 | **PASS** |
| REQ-SEC-02 | Los secretos nunca se registran en logs | ídem | **PASS** |
| REQ-SEC-03 | Datos mínimos enviados a OpenRouter (sin IDs, tokens ni filas); documentado | AV1, `ARCHITECTURE.md` §9 | **PASS** |
| REQ-SEC-04 | Ni clave de OpenRouter ni acceso a la VM en la documentación o los adjuntos | escaneo FINAL-01 | **PASS** para los ficheros actuales (la dirección de la VM aparece en 3 commits antiguos, sin credenciales: véanse las limitaciones) |

### Pruebas, evidencias, entrega, IA
| ID | Implementación | Evidencia | Estado / limitación |
|---|---|---|---|
| REQ-TEST-01..10 | Matriz mínima de pruebas | [`TEST_EVIDENCE_SUMMARY.md`](../../TEST_EVIDENCE_SUMMARY.md) §4 | **PASS** |
| REQ-TEST-11 | Pruebas automatizadas más harnesses de validación reproducibles | T, `evidence/*/vm-*.sh` | **PASS** |
| REQ-TEST-12 | Por caso: pasos, resultado esperado, resultado obtenido, estado, evidencia | Runbook; tablas de escenarios de UI02 y F2; PDF final | **PASS** |
| REQ-TEST-13 | Fallos declarados; ejecuciones rechazadas conservadas | AUD §B | **PASS** |
| REQ-EVID-01 | Capturas de pantalla legibles: recorridos, fuentes del RAG, ejecuciones de n8n, registros persistidos, controles de acceso, errores, reinicio, actualización del conocimiento | UI02 `screenshots/`, F2 `screenshots/`, PDF final | **PASS** |
| REQ-EVID-02 | Capturas de pantalla explicadas (pies de imagen y tablas de escenarios) | UI02, F2, PDF final | **PASS** |
| REQ-EVID-03 | Sin secretos en las evidencias ni en las capturas de pantalla | escaneos | **PASS** |
| REQ-DELIV-01 | Solución operativa en la VM, accesible mediante el procedimiento documentado (túnel SSH a `127.0.0.1:8080`) | F2 (35/35; dejada en ejecución, `restart: unless-stopped`) | **PASS** |
| REQ-DELIV-02 | Repositorio: Compose, dependencias, `.env.example`, documentos del RAG, exportación de n8n | repositorio | **PASS** |
| REQ-DELIV-03 | Documentación técnica **en PDF** | `docs/report/Nexo_Technical_Report.pdf` (generado a partir de la documentación y las evidencias del repositorio) | **PASS** |
| REQ-DELIV-04 | Instrucciones de evaluación autónoma en el README **y** en el PDF | README, [`EVALUATOR_RUNBOOK.md`](../../EVALUATOR_RUNBOOK.md), capítulo 4 del PDF | **PASS** |
| REQ-DELIV-05 | Los 9 elementos: acceso, arranque/parada/estado, credenciales privadas, identidades sintéticas, pasos con resultados esperados, errores/duplicados/acceso ajeno, actualización del RAG, logs/n8n/registros, recuperación/restauración | README + runbook | **PASS** |
| REQ-DELIV-06 | Lista de completados y pendientes, más limitaciones | esta matriz, `KNOWN_LIMITATIONS.md` | **PASS** |
| REQ-DELIV-07 | Responder al correo de invitación con el PDF y el acceso | — | **PENDING (owner)** |
| REQ-AI-01 / REQ-AI-02 | Herramientas de IA, finalidad y validación declaradas | [`AI_DISCLOSURE.md`](../../AI_DISCLOSURE.md) | **PASS** (pendiente de que el propietario confirme la lista de herramientas) |

## Resumen
- **Implementación:** todos los requisitos funcionales, de seguridad, de fiabilidad, de Docker y de artefactos de entrega están implementados
  y cuentan con evidencia con el stack real. La solución está en ejecución en la VM (FINAL-02).
- **Acciones pendientes del propietario (sin código de producto):**
  - publicar el repositorio (acceso de DELIV-02);
  - responder al correo de invitación con el PDF y los datos de acceso (DELIV-07);
  - confirmar la lista de herramientas de IA (AI-01/02).
