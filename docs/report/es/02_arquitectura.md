# Arquitectura y diseño

> **El LLM propone; el backend autoriza y ejecuta.**

**Qué hace el modelo.** Grok devuelve una única interpretación en JSON estricto por turno: una intención más los campos del
borrador. No tiene herramientas, ni conexión a la base de datos, ni noción de quién es el cliente.

**De qué se encarga el backend:**
- **Identidad:** únicamente a partir del token bearer.
- **Acceso a datos:** las rutas de lectura se ejecutan en una transacción `READ ONLY` de PostgreSQL.
- **Escrituras:** solo a través de los servicios existentes.
- **Confirmación:** una puerta determinista `CONFIRMAR` más un token de versión.
- **Idempotencia, auditoría y redacción veraz.**

## 1. Recorrido de una solicitud

```
Browser (React bundle; no credentials, no customer_id)
  │  POST /api/chat  {message, conversation_id?, confirmation_token?}   header X-Demo-Session: A|B
  ▼
web  (src/frontend/server/server.mjs, Node stdlib, 127.0.0.1:8080, network "web")
  │  allowlist: POST /chat, GET /health/ready only; drops browser Authorization/Cookie;
  │  adds  Authorization: Bearer <synthetic token A|B>  from its runtime environment
  ▼
backend  (FastAPI, uid 10001, 127.0.0.1:8000, networks internal + automation + web)
  │  sha256(token) → customer_id   ·   request_id / conversation_id   ·   one JSON audit line per request
  ├─► PostgreSQL 17 + pgvector (no host port; network "internal")
  ├─► OpenRouter (HTTPS): x-ai/grok-4.7 interpretation · openai/text-embedding-3-small embeddings
  └─► n8n 2.42.3 (network "automation") ─► POST /internal/leads (service credential) ─► PostgreSQL
```

## 2. Conocimiento (RAG)

```
knowledge/*.md ── python -m app.rag_ingest ──► OpenRouter embeddings (1536 d) ──► pgvector (knowledge_chunks)
question ──► backend embeds query ──► cosine top-k ≥ 0.39 ──► sections as DATA ──► Grok answer (strict JSON)
         ──► grounding guard (citations + figures must come from the retrieved sections) ──► answer + references
```

**Indexación:**
- Cada sección `##` es un fragmento (chunk). Su referencia es `<file> § <section>`.
- La ingesta es atómica (todo o nada) y solo vuelve a generar los embeddings de las secciones modificadas. La versión del
  documento es el SHA-256 de su archivo.

**Responder de forma segura:**
- **Por debajo del umbral:** «no he encontrado información suficiente», sin ninguna respuesta del modelo.
- **El texto recuperado son datos:** se pasa en el turno del usuario, nunca en el prompt de sistema, de modo que las
  instrucciones inyectadas en un documento no autorizan nada.
- **Las cifras deben estar fundamentadas:** se bloquea toda respuesta que cite una fuente no recuperada o una cifra que no
  figure en las fuentes.

**El estado de un ticket nunca procede del RAG.** Procede de la tabla de tickets (fuente `business_api`).

## 3. Ticket (acción confirmada)

```
chat message ─► Grok proposes {intent: create_ticket, ticket: {contact, subject, description, priority}}
             ─► backend validates the draft ─► ticket service PREPARE (pending action, payload hash) ─► NO ticket yet
             ─► summary + confirmation_token = sha256("nexo:chat_confirm:v1:<action_id>:<payload_hash>")[:16]
UI "Confirm" ─► {"message":"CONFIRMAR","confirmation_token":<token of the summary shown>}
             ─► deterministic gate (whole message; NO model call) ─► token == current version? (under the conversation lock)
                   no  → confirmation_review_required: current summary shown again, nothing executed
                   yes → ticket service CONFIRM (idempotency key chat:<conversation>:<action>) ─► PostgreSQL
                         critical → pending handoff "critical_incident" (idempotent per ticket)
             ─► real T-reference + status from the committed row
```

**Vinculación de versión.** Una corrección vuelve a preparar la acción: la versión anterior queda sustituida y se emite un
token nuevo. Un token obsoleto o ausente nunca puede ejecutar la nueva versión. La cancelación es autoritativa: solo se
informa de éxito si la acción pasó realmente de pendiente a cancelada; en caso contrario, el backend informa
`already_completed` o `cannot_cancel`.

**Respuesta perdida.** La creación se confirma en la base de datos (commit) aunque el cliente nunca reciba la respuesta.
Volver a confirmar con el mismo token reproduce el **mismo** ticket (clave de idempotencia); nunca crea un duplicado. Esto
se validó en la VM cerrando el socket antes de leer la respuesta y reintentando después.

## 4. Solicitud comercial (lead): n8n obligatorio

```
chat ─► Grok proposes {intent: create_lead, lead: {company, contact, email, need}} (the e-mail must appear in the message)
     ─► leads PREPARE (no lead) ─► summary + token ─► UI "Confirm" ─► CONFIRMAR gate (no model call)
     ─► leads.begin_confirm (pending → confirmed) ─► HTTP POST n8n webhook (private network)
     ─► n8n workflow "nexo-lead-create" ─► POST backend /internal/leads (n8n service credential; customer tokens rejected)
     ─► the ONLY insert path for leads ─► PostgreSQL ─► n8n returns {lead_id, execution_id}
     ─► backend reads the row back ─► finish_confirm ─► "lead_created" + workflow execution id
```

**n8n caído o fallando.** La respuesta es 503 `lead_not_confirmed` («no te digo que se haya creado»). La acción permanece
en `confirmed` y el chat conserva una referencia a ella. Volver a confirmar más tarde completa la **misma** acción
exactamente una vez.

**El backend nunca inserta una solicitud comercial por sí mismo.** Solo guarda el SHA-256 del token de servicio de n8n; el
token en claro reside únicamente en el almacén cifrado de credenciales de n8n.

## 5. Escalado humano (handoff)

```
explicit human request / data deletion / unsafe case ─► Grok intent request_human (+ reason)
critical ticket confirmed                              ─► automatic "critical_incident"
  ─► handoff service (idempotent key) ─► PostgreSQL handoffs(status = pending)
  ─► "pendiente de atención humana: todavía no lo ha recogido ninguna persona y no se garantiza un plazo"
```

No se envía ningún correo electrónico ni mensaje. El estado es siempre `pending`: nada afirma que una persona lo haya
aceptado.

## 6. Identidad, aislamiento y el cliente de evaluación

- **Identidad:** el backend resuelve `customer_id` únicamente como `sha256(bearer token)` → `customers`. El texto, la
  salida del modelo, las cabeceras y los cuerpos de las peticiones nunca otorgan autoridad.
- **Aislamiento:** toda lectura y escritura está limitada al propietario. Un ticket ajeno y un ticket inexistente reciben
  la misma respuesta; la diferencia solo se registra en la auditoría (`denied_not_owner` / `not_found`).
- **Identidad de demostración:** la frontera del lado del servidor del cliente web asigna a la **sesión de demostración A
  o B** la credencial sintética correspondiente de su entorno de ejecución. Ni el navegador, ni el bundle JS, ni la imagen
  contienen ninguna. Cualquiera que pueda acceder al puerto web de loopback actúa como uno de los dos clientes sintéticos;
  es así por diseño, solo para evaluación.

## 7. Fiabilidad y comportamiento ante fallos

| Fallo | Comportamiento |
|---|---|
| Timeout / 429 / 5xx de OpenRouter | 503 `llm_unavailable`, `answer: null` |
| Salida malformada, truncada o con campos adicionales, o metadatos de uso malformados | 503 `llm_invalid_output` |
| Modelo servido incorrecto | 503 `llm_model_mismatch` (sin modelos de respaldo) |
| Base de datos no disponible | 503 `database_unavailable`; readiness 503 |
| Intento de escritura en la ruta de lectura | Rechazado por PostgreSQL (`READ ONLY`) → 503 |
| n8n caído | 503 `lead_not_confirmed`; recuperable con la misma acción |
| Respuesta perdida tras el commit | La repetición devuelve el mismo objeto (idempotencia) |
| Reinicio de contenedores | Datos en volúmenes con nombre; los servicios vuelven a estar sanos; validado |

## 8. Trazabilidad

Hay una línea de auditoría JSON por solicitud. Contiene:
- el identificador de solicitud (request ID), el identificador de conversación, el cliente, la ruta y el estado HTTP;
- la intención, la puerta, el comando y el resultado;
- el resultado de la recuperación y los identificadores de las fuentes;
- para cada llamada al modelo: la etapa, el modelo servido y el coste;
- la decisión de consulta del ticket, los identificadores de la solicitud comercial y de la ejecución del workflow, la
  huella de la clave de idempotencia, la duración y el resultado.

La línea de chat de una solicitud comercial y la línea `/internal/leads` del escritor privado comparten el **mismo
identificador de solicitud**, de modo que la cadena es: mensaje → recuperación → decisión → confirmación → workflow → API
→ resultado. No se registran secretos, texto de los mensajes, datos de contacto ni el razonamiento del modelo.

## 9. Despliegue y permisos (Docker)

**Imágenes y ejecución:**
- **Imágenes fijadas:** `pgvector/pgvector:0.8.7-pg17-bookworm`, `n8nio/n8n:2.42.3`, `python:3.12.15-slim-bookworm`,
  `node:22.16.0-alpine`. Las dependencias npm del cliente web están bloqueadas (lockfile).
- **Reinicio y salud:** `restart: unless-stopped`, y todos los servicios tienen un healthcheck. El backend solo arranca
  cuando la base de datos está sana, y el cliente web solo cuando lo está el backend.

**Usuarios y privilegios:**
- el backend se ejecuta como uid 10001, n8n como `node` y web como `node` (raíz de solo lectura, `cap_drop: ALL`,
  `no-new-privileges`);
- ningún contenedor es privilegiado y ninguno monta el socket de Docker.

**Exposición:**
- Solo se publican puertos de loopback (8000, 5678, 8080); la base de datos no publica ninguno. Los puertos publicados por
  Docker eluden `ufw`, por eso solo se usa loopback.
- El acceso de administración a n8n se realiza a través de un túnel SSH; la cuenta de propietario de n8n la crea el
  operador.

**Datos enviados a servicios externos (OpenRouter / xAI):**
- el mensaje del usuario;
- las secciones de conocimiento recuperadas;
- un contexto mínimo de la conversación.

**Nunca se envían:** identificadores de cliente, tokens, credenciales de la base de datos ni filas de tickets.

## 10. Dónde ampliar información

- **Diseño del agente y de las acciones:** `evidence/11-agent/architecture.md`, `evidence/12-agent-actions/architecture.md`,
  `evidence/12-agent-actions/agent01bf{1,2,3}/root-cause-and-design.md`.
- **Diseño y calibración del RAG:** `evidence/10-rag/architecture.md`, `evidence/10-rag/calibration.json`.
- **Entorno de ejecución web:** `src/frontend/README.md`, `evidence/14-evaluation-client/ui02-browser-e2e/ui02-report.md`.
