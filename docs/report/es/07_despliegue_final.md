# Despliegue final en la VM (FINAL-02)

**Resultado: PASS, 35/35 comprobaciones del harness de validación** (`vm-run-accepted.txt`). El stack se **dejó en ejecución en la VM para la evaluación**.

**Qué se desplegó.** El commit `16c587f`, con código de aplicación idéntico al de `85781cf`, validado en UI-02.
Todo es real: PostgreSQL 17.11 + pgvector 0.8.7, el backend, **n8n 2.42.3**, OpenRouter `x-ai/grok-4.7`
más embeddings, y el cliente web.

**Cómo se condujo.** El cliente web real en el Chrome del propietario, a través de túneles SSH, más un endpoint de control con lista de
permitidos y protegido por token en el loopback de la VM (solo acciones fijas, ningún comando arbitrario).

## Estado de entrega (dejado en ejecución)
| Elemento | Estado |
|---|---|
| Servicios | db, backend, n8n, web: todos **healthy**, `restart: unless-stopped` (vuelven tras un reinicio de la VM; Docker está habilitado en el arranque) |
| Exposición | Solo `127.0.0.1:8000`, `:8080`, `:5678`; db no tiene puerto; único listener público `:9922` (SSH) |
| Ubicación | `~/nexo-eval/repo` (checkout de `16c587f`), `.env` en modo **600**: la clave de OpenRouter y las credenciales sintéticas, ignorado por git |
| Copias de seguridad | `~/nexo-eval-backups` (modo 700): `nexo-db-20261007T171527.dump`, `n8n-state-20261007T171527/`, `snapshot-….json` |
| Conocimiento | Corpus canónico (árbol de git limpio), 4 documentos / 10 secciones indexados |
| Datos en la entrega | Tickets 3 (T-1001, T-1002 semilla; T-1003 critical), solicitudes comerciales (leads) 1, escalados humanos 2 |
| Eliminado | Bundle, token de control, token en claro del lead-writer (vive solo en el almacén cifrado de credenciales de n8n), logs, script de control; el endpoint de control se detuvo (`:8099` no está escuchando) |
| Administración de n8n | Cuenta de propietario creada por el propietario durante la ejecución; sus credenciales son privadas y no se almacenan aquí |

## Escenarios (stack real)
| # | Escenario | Evidencia | Resultado |
|---|---|---|---|
| 1 | Recorridos reales a través del cliente web: ticket crítico → **T-1003** + escalado humano `critical_incident`; solicitud comercial → ejecución 1 de n8n; escalado humano | `screenshots/01-db-records-after-real-journeys.jpg`, `data/records-1.json` | PASS |
| 2 | **120 € → 150 €**: una línea de diff, ingesta `updated 1 / embedded 1 / unchanged 3`, **0 filas con 120 €**, la coincidencia principal `03_commercial_policy.md § Tarifas` contiene 150 €. **Respuesta del chat: «El diagnóstico inicial cuesta 150 € más IVA.»**, misma referencia | `02-rag-price-150-chat-answer.jpg`, `data/price150.json` | PASS |
| 3 | **Restauración del corpus canónico**: `git checkout`, árbol limpio, ingesta `updated 1`, 0 filas con 150 €; el chat vuelve a responder 120 €, misma referencia | `03-rag-price-restored-120-chat-answer.jpg`, `data/rag-restore.json` | PASS |
| 4 | **Caída real del backend** (contenedor del backend detenido): **NOT COMPLETED** en rojo, HTTP 502 `backend_unreachable` desde la frontera web, todos los demás campos "Not available", sin tarjeta de éxito. Backend reiniciado → healthy | `04-backend-down-not-completed.jpg` | PASS |
| 5 | **Caída real de PostgreSQL** (contenedor db detenido): insignia **Unavailable** al recargar; mensaje → **NOT COMPLETED** en rojo, HTTP 503, nada inventado. BD reiniciada → los **mismos datos** (3/1/2); el backend vuelve a estar healthy por sí solo en unos 10 s, sin reinicio | `05-db-down-unavailable-badge.jpg`, `06-db-down-not-completed.jpg` | PASS |
| 6 | **Copia de seguridad**: `pg_dump -Fc` con código de salida 0 (118,701 bytes) + copia del estado de n8n (n8n detenido brevemente, webhook listo de nuevo tras 0.6 s) | `data/backup.json` | PASS |
| 7 | **Restauración**: se creó un escalado humano `unsafe_to_resolve` *después* de la copia de seguridad (escalados humanos 3). `pg_restore --clean --if-exists` con código de salida 0, sin errores → escalados humanos **2**, ese escalado humano desaparece, todo lo demás idéntico | `07-backup-restore-before-restore.jpg`, `08-backup-restore-after-restore.jpg`, `data/restore.json` | PASS |
| 8 | **Reinicio / persistencia**: `docker compose restart`, todo healthy, webhook listo en 0.5 s; datos idénticos; el cliente web se reconecta y responde T-1003 desde PostgreSQL | `09-restart-persistence-T1003.jpg`, `data/records-4-after-restart.json` | PASS |
| 9 | **Ejecuciones de n8n**: la interfaz de n8n lista las ejecuciones 1–5 de `nexo-lead-create`, todas Success. La ejecución 1 es la solicitud comercial real; las 2–5 son las sondas de disponibilidad del webhook que lanza el endpoint tras cada reinicio (`400 invalid_envelope`, no se escribe nada). La misma lista se leyó de la propia base de datos de n8n | `11-n8n-ui-executions.jpg`, `10-n8n-executions-from-n8n-db.jpg` | PASS |
| 10 | **Escaneo final de secretos**: **0 apariciones** de los 7 secretos en los logs de backend, web, n8n y db, el log de la ejecución, el bundle servido, el sistema de archivos/historial/configuración de la imagen web y las instantáneas de copia de seguridad; comprobación del harness de validación sobre el log de la ejecución y los logs de los contenedores: 7/7 PASS | `data/scan.json`, `vm-run-accepted.txt` §10 | PASS |

Las capturas de registros de la base de datos y de la base de datos de n8n (01, 07, 08, 10) se generan a partir de la VM en vivo mediante
consultas de **solo lectura** a través del endpoint de control (JSON en `data/`). Todas las demás capturas muestran el cliente web real o la
interfaz real de n8n.

## Nueva observación (LOW solo de interfaz, no bloqueante)
**UI02-04.** La insignia "Connected" comprueba la disponibilidad solo cuando se carga la página. Durante la caída del backend siguió
mostrando "Connected" hasta una recarga, tras la cual mostró "Unavailable". Las propias peticiones siempre informaron de la caída
con honestidad.

## Uso del modelo
**7 turnos con llamada al modelo:**
- la incidencia crítica y la solicitud comercial;
- la petición de hablar con una persona y la petición de borrado;
- 2 preguntas de precio;
- la consulta posterior al reinicio.

**Sin llamada al modelo:** las 2 confirmaciones y los 2 turnos enviados durante las caídas.

**Embeddings:** el índice inicial, más 1 sección re-embebida para el cambio de precio y 1 para su restauración.
