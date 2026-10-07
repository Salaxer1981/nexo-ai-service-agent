# Resumen de pruebas y evidencias

Cada recuento pertenece a **una** ejecución, de un tipo, sobre un commit. **No** se suman para obtener una cifra global.

**Etiquetas:**
- **REAL:** PostgreSQL / pgvector / n8n / OpenRouter reales.
- **TEST:** fixtures o sustitutos guionizados, usados para forzar fallos y condiciones de carrera de forma determinista. Los resultados TEST
  nunca cuentan como evidencia de modelo real ni de n8n real.

## 1. Suites automatizadas (locales, sin llamadas de pago)

| Suite | Commit / fase | Resultado | Evidencia |
|---|---|---|---|
| Suite completa del backend (clúster desechable con PostgreSQL 17.11 + pgvector 0.8.7 reales; LLM guionizado, embedder por hashing, FakeN8n = TEST) | **HEAD en la entrega (FINAL-01)** | **410 passed, 8 skipped** (pruebas en vivo/de evidencia opcionales) | Ejecutada durante FINAL-01; incluye 2 nuevas comprobaciones estáticas para el servicio `web` |
| Suite completa del backend | AGENT-01BF3 `61774c6` (candidato final del backend) | 408 passed, 8 skipped | `evidence/12-agent-actions/agent01bf3/pytest-full.txt` |
| Suite completa del backend | AGENT-01A `aa1713b` | 318 passed, 7 skipped | `evidence/11-agent/pytest-full.txt` |
| Suite completa del backend | RAG-01 | 248 passed, 4 skipped | `evidence/10-rag/pytest-full.txt` |
| Pruebas de mutación (cada corrección se deshace y las pruebas deben fallar) | BF1, BF2, BF3, AGENT-01B, RAG | Todos los mutantes detectados | `evidence/12-agent-actions/**/mutation-checks.txt`, `evidence/10-rag/mutation-checks.txt` |
| Cliente web: comprobación de tipos, lint, Vitest (11 pruebas de UI + 6 de frontera de ejecución), build de producción | UI-02 `85781cf` | **17/17**, build OK | `evidence/14-evaluation-client/ui02-browser-e2e/checks.txt` |

## 2. Validaciones reales en la VM (despliegues temporales, desmontaje completo tras cada una)

| Fase | Candidato | Ejecución aceptada | Qué demostró | Evidencia |
|---|---|---|---|---|
| APP-02V1 | `1284f98` | ejecución 2: **80/80** | API de tickets: prepare/confirm, reenvío/conflicto de idempotencia, aislamiento, persistencia tras reinicio | `evidence/06-app02-runtime/` |
| N8N-01V1 | `e23679d` | ejecución 2: **32/32** | Base de n8n, fronteras de red, prueba de humo de escalado humano | `evidence/08-n8n-foundation/` |
| APP-03BV1 | REAL n8n 2.42.3 | ejecución 2: **106/106** | Solicitud comercial (lead) a través del workflow de n8n real y del escritor privado | `evidence/09-leads-n8n/` |
| RAG-01V1 | `fce4580` | **138/138** | Embeddings reales, pgvector, referencias, umbral, **actualización de 120 € → 150 € y restauración** | `evidence/10-rag/vm-validation.md` |
| AGENT-01AV1 | `aa1713b` | ejecución 2: **129/129** (incl. suite TEST dentro del contenedor 47/47) | Agente de solo lectura con Grok 4.7 real: respuestas fundamentadas, información ausente, estado de tickets, aislamiento, inyección (mensaje y documento) | `evidence/11-agent/vm-validation.md` |
| AGENT-01BV1 | `61774c6` | ejecución 2: **139/139** (incl. suite TEST dentro del contenedor 29/29) | Acciones confirmadas con Grok real + n8n real: tickets críticos/normales, reenvío, **respuesta perdida**, vinculación de versión, cancelación, solicitud comercial + fallo/recuperación de n8n, escalados humanos, reinicio, logs/secretos | `evidence/13-agent-actions-vm/vm-validation.md` |
| FINAL-02 | `16c587f` (código = `85781cf`) | **35/35** (stack dejado en ejecución) | Despliegue permanente; 120 € → 150 € a nivel de chat + restauración; caídas reales del backend y de PostgreSQL; copia de seguridad + restauración; reinicio; ejecuciones de n8n (UI); escaneo final de secretos 0 | `evidence/15-final-deployment/final-deployment-report.md` |
| UI-02 | `ca86d7c` (código = `85781cf`) | ejecución 2: **28/28** comprobaciones del harness de validación + **23 escenarios de navegador** | El cliente web de evaluación en un navegador real contra el stack real (ver abajo) | `evidence/14-evaluation-client/ui02-browser-e2e/ui02-report.md` |

Las **ejecuciones rechazadas** se conservan y etiquetan en cada carpeta de evidencias; véase [`AUDIT_FINDINGS.md`](../../AUDIT_FINDINGS.md) §B.

## 3. E2E en navegador real (UI-02)

El Chrome del propietario, controlado mediante la extensión del navegador, se ejecutó contra el stack de la VM: modelo real y n8n real, viewport
de escritorio. Los 23 escenarios dan PASS:

| # | Escenario |
|---|---|
| 1 | Estado de bienvenida (diseño NEXO, panel lateral cerrado, disponibilidad real) |
| 2–3 | RAG con una referencia; información ausente |
| 4–8 | Incidencia crítica: ningún ticket antes de Confirm; CONFIRMAR con el token oculto y sin llamada al modelo; T-1003 más un escalado humano pendiente; reenvío |
| 9–10 | Vinculación de versión y revisión; Cancel; Confirm tras Cancel no hace nada |
| 11 | Ticket normal |
| 12–13 | Solicitud comercial a través de n8n real (id de ejecución + escritor privado + 1 fila); n8n caído devuelve Not completed y después recuperación con la misma acción |
| 14–15 | Escalado humano; escalado humano por eliminación de datos |
| 16–17 | T-1001 desde PostgreSQL; aislamiento A/B mediante la tarjeta de cuenta; suplantación de `customer_id` |
| 18–19 | Inyección de prompt; estado de error controlado |
| 20 | El panel técnico muestra solo valores reales |
| 21 | Responsive (390/820 px con código idéntico en local, fixture TEST; véanse las limitaciones) |
| 22 | Reinicio y persistencia |
| 23 | Escaneo de secretos del navegador, el bundle, los logs y el sistema de ficheros de la imagen web (0 apariciones) |

Capturas de pantalla: `evidence/14-evaluation-client/ui02-browser-e2e/screenshots/` (01–10 stack real; 11–12 responsive TEST).

## 4. Matriz de pruebas de la evaluación (§7 del PDF)

| Prueba del PDF | Estado | Evidencia |
|---|---|---|
| Horario / precio de IA / dato ausente | PASS | AV1 K1–K4 + ausente; UI-02 #2–3 |
| Ticket sin confirmación / confirmado | PASS | BV1 §11; UI-02 #4–7 |
| Reenvío con la misma clave | PASS | APP-02V1 (reenvío de `Idempotency-Key` en la API); BV1 §12; UI-02 #8 |
| Ticket de otro cliente | PASS | AV1; BV1 §16; UI-02 #17 |
| API no disponible | PASS | REAL en la VM: n8n caído (BV1 §18; UI-02 #13), backend caído y PostgreSQL caído (FINAL-02 #4–5). Timeout/429/5xx del LLM: TEST (matriz de stubs dentro del contenedor AV1/BV1) |
| Petición de humano / incidencia crítica | PASS | BV1 §11, §19; UI-02 #7, #14–15 |
| Inyección en la documentación | PASS | AV1 P3 (`05_injection_test.md` temporal recuperado en top-1, no autorizó nada) y TEST S5 |
| Reinicio del stack | PASS | BV1 §22; UI-02 #22; FINAL-02 #8 |
| 120 € → 150 € | PASS | RAG-01V1 (recuperación) y FINAL-02 #2–3 (respuesta del chat "150 € más IVA", misma referencia; restaurado) |
| Solicitud comercial confirmada a través de n8n | PASS | APP-03BV1; BV1 §17; UI-02 #12 |
