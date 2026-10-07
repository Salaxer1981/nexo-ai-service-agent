# Hallazgos de auditoría y correcciones

## Proceso

Cada fase de alto riesgo recibió una **auditoría independiente y focalizada realizada por Codex**. Los hallazgos se corrigieron en fases
dedicadas (`…F1`, `…F2`, `…F3`), cada una de las cuales:
- reprodujo primero el defecto sobre el commit **antiguo** (un test que falla o una prueba conservada como evidencia);
- aplicó la corrección mínima;
- demostró la corrección con tests deterministas sobre un PostgreSQL real;
- comprobó los propios tests mediante pruebas de mutación (se deshace la corrección y los tests nuevos deben fallar).

Una **re-auditoría focalizada** decidió si cada hallazgo quedaba CLOSED. A continuación, la versión candidata final se validó en la VM real
(PostgreSQL/pgvector real, n8n real, `x-ai/grok-4.7` real) y en un navegador real.

**Significado de los estados:**
- **CLOSED:** corregido y aceptado por la re-auditoría.
- **OPEN:** documentado, no corregido. Todos los hallazgos HIGH están CLOSED; un hallazgo LOW sigue OPEN.

## A. Hallazgos del producto (orden cronológico)

| ID | Severidad | Detectado en → corregido en | Estado final |
|---|---|---|---|
| AGENT01A-01 | LOW | auditoría de AGENT-01A → AGENT-01B | **CLOSED** |
| AGENT01B-01 | **HIGH** | auditoría de AGENT-01B → AGENT-01BF1 | **CLOSED** |
| AGENT01B-02 | **HIGH** | auditoría de AGENT-01B → AGENT-01BF1 | **CLOSED** |
| AGENT01BF1-01 | **HIGH** | re-auditoría de BF1 → AGENT-01BF2 | **CLOSED** |
| AGENT01BF1-02 | LOW | re-auditoría de BF1 → AGENT-01BF2 | **CLOSED** |
| AGENT01BF2-01 | **HIGH** | re-auditoría de BF2 → AGENT-01BF3 | **CLOSED** |
| AGENT01BF2-02 | LOW | re-auditoría de BF2 → AGENT-01BF3 | **CLOSED** |
| AGENT01BF3-01 | LOW | re-auditoría de BF3 | **OPEN (documentado, aceptado)** |

### AGENT01A-01 (LOW): metadatos malformados del modelo sin endurecer
- **Problema.** El cliente de OpenRouter validaba el contenido de la respuesta, pero no metadatos auxiliares como `usage` (recuentos
  de tokens y coste).
- **Escenario de fallo.** Un proveedor o un proxy devuelve un `usage.prompt_tokens` no numérico. El código de coste y de auditoría
  falla entonces de forma abrupta o registra datos basura en lugar de fallar de forma limpia.
- **Causa raíz.** El analizador de respuestas confiaba en los tipos de los metadatos.
- **Corrección.** Validación `_usage` en `llm.parse_completion`: los metadatos malformados se tratan como salida no válida, lo que
  produce un 503 `llm_invalid_output` con `answer: null`.
- **Verificación.** Tests unitarios; matriz de stubs dentro del contenedor en la VM (AGENT-01BV1 §23, "malformed usage") PASS.
- **Estado:** CLOSED.

### AGENT01B-01 (HIGH): una confirmación podía ejecutar una versión que el usuario nunca aprobó
- **Problema.** `CONFIRMAR` ejecutaba cualquier acción a la que apuntase la conversación una vez adquirido el bloqueo.
- **Escenario de fallo.**
  - El usuario ve el borrador A (prioridad *normal*) y envía CONFIRMAR.
  - Mientras tanto, un turno de corrección vuelve a preparar B (*critical*), o el resumen de B se pierde en tránsito.
  - Se crea el ticket **B**, pero el usuario aprobó **A**. Reproducido sobre `8507448`.
- **Causa raíz.** Nada vinculaba el CONFIRMAR del usuario con el resumen que había visto. Solo el cliente sabe qué versión
  mostró.
- **Corrección (AGENT-01BF1).**
  - Con cada resumen se devuelve un **`confirmation_token`** (`sha256("nexo:chat_confirm:v1:<action_id>:<payload_hash>")[:16]`).
  - El cliente lo reenvía junto con CONFIRMAR, y se vuelve a comprobar contra la versión actual bajo el bloqueo de la conversación.
  - Un token que no coincide o que falta produce `confirmation_review_required` con el resumen actual; no se ejecuta nada.
  - Una revisión de la conversación rechaza las propuestas obsoletas del modelo.
- **Verificación.** Prueba sobre el código antiguo más tests nuevos; comprobaciones de mutación; VM: un CONFIRMAR con el token de A
  mientras B es la versión actual produce una revisión con el resumen de B y ningún ticket (AGENT-01BV1 §21); navegador: un borrador
  obsoleto no tiene botones, y un CONFIRMAR sin vincular produce una revisión (UI-02 #9).
- **Estado:** CLOSED (re-auditoría).

### AGENT01B-02 (HIGH): la cancelación podía declarar éxito a partir de un estado obsoleto del chat
- **Problema.** CANCELAR decidía su respuesta a partir del estado del chat almacenado en caché.
- **Escenario de fallo.** Una confirmación directa por API consume la acción justo antes de CANCELAR. La cancelación del servicio
  afecta a 0 filas, y aun así el chat responde «He cancelado… No se ha creado ningún ticket» mientras existe un ticket. Reproducido
  sobre `8507448`.
- **Causa raíz.** La respuesta no dependía del resultado autoritativo de la cancelación.
- **Corrección (BF1).** Solo hay éxito si la llamada movió la acción de pendiente a cancelada (1 fila). En caso contrario, se vuelve a
  leer el estado autoritativo: `consumed` produce `already_completed` con el objeto real, y una solicitud comercial (lead) en curso
  produce `cannot_cancel`.
- **Verificación.** Tests (carrera en la que gana la confirmación por API); VM S4 (`already_completed`); VM y navegador: cancelar un
  ticket o una solicitud comercial ya completados produce `already_completed` (AGENT-01BV1 §21; UI-02 #10).
- **Estado:** CLOSED.

### AGENT01BF1-01 (HIGH): una propuesta obsoleta podía sustituir un puntero de recuperación
- **Problema.** BF1 rechazaba las propuestas obsoletas únicamente por la revisión de la conversación, que solo cambia cuando el
  guardado propio del chat tiene éxito.
- **Escenarios de fallo.**
  - Se confirma (commit) el ticket A y después falla la sincronización del chat.
  - La solicitud comercial A pasa a confirmada y después falla n8n.
  - Una confirmación directa por API completa A.

  En cada caso, una corrección interpretada con la revisión antigua preparaba B y sustituía el puntero de A, con lo que se perdía la
  referencia de repetición (replay) o de recuperación. En el caso de las solicitudes comerciales, aparecía una segunda acción junto a la
  que estaba en curso. Reproducido sobre `0b4f6c8`.
- **Causa raíz.** La caché del chat se trataba como autoritativa en lugar de la fila de la acción de negocio.
- **Corrección (AGENT-01BF2).** `reconcile()` vuelve a leer la acción apuntada (cliente + conversación + acción) antes de publicar
  cualquier propuesta. Una acción completada produce `already_completed`; una solicitud comercial en curso produce
  `action_in_progress` (se conserva el puntero). Confirmar y cancelar avanzan la revisión **antes** de cualquier mutación de negocio.
- **Verificación.** Tests T1–T3 más el caso en curso; comprobaciones de mutación; VM: fallo de n8n → recuperación sobre la misma acción
  (AGENT-01BV1 §18; UI-02 #13).
- **Estado:** CLOSED.

### AGENT01BF1-02 (LOW): CANCELAR mutaba antes de demostrar la pertenencia a la conversación
- **Problema.** La cancelación acotada al propietario se ejecutaba antes de comprobar que la acción apuntada pertenecía a esta
  conversación.
- **Escenario de fallo.** Un puntero corrupto en la conversación Y hacia una acción de la conversación X (mismo cliente) cancela X.
- **Corrección (BF2).** Desreferenciar primero con cliente + conversación + acción. Si no es válido, se borra el puntero corrupto y
  se responde `not_pending` con **cero** llamadas de cancelación.
- **Verificación.** Tests T4/T5 (con espía: cero llamadas); VM S5.
- **Estado:** CLOSED.

### AGENT01BF2-01 (HIGH): hueco entre comprobación y uso (TOCTOU) entre la lectura autoritativa y la nueva preparación
- **Problema.** `reconcile()` leía el estado de A, y el `prepare()` posterior se ejecutaba en una transacción **separada** sin
  bloqueo de fila.
- **Escenario de fallo.** Reconcile ve A pendiente, una confirmación directa por API consume A, y después prepare no sustituye nada e
  inserta B. El resultado es "A consumida **y** B pendiente". Reproducido sobre `c693a5a`.
- **Causa raíz.** La comprobación y la acción no eran atómicas.
- **Corrección (AGENT-01BF3).** `propose()` es **una sola transacción**. Toma el bloqueo consultivo (advisory lock) del grupo de
  preparación, después hace `SELECT … FOR UPDATE` sobre A, vuelve a comprobar, ejecuta la preparación del servicio como un savepoint,
  publica y confirma (commit). El orden de bloqueo coincide con el de la ruta de preparación de la API (sin interbloqueo), y la llamada
  al modelo queda fuera de cualquier transacción.
- **Verificación.** Tests deterministas con esperas de bloqueo observadas (gana la propuesta y gana la confirmación, para ticket y para
  solicitud comercial); 5 rondas de nueva preparación concurrente sin interbloqueo; mutaciones H1–H5 detectadas; 408 superados.
  VM: AGENT-01BV1 139/139.
- **Estado:** CLOSED.

### AGENT01BF2-02 (LOW): CANCELAR cancelaba otras acciones pendientes antes de validar el puntero
- **Corrección (BF3).** El orden es ahora: validar el puntero, después avanzar la revisión, después cancelar las demás acciones
  pendientes y, por último, cancelar la acción apuntada.
- **Verificación.** Test X/Z: un puntero corrupto produce `not_pending` y **0** llamadas de cancelación; X y Z siguen pendientes.
- **Estado:** CLOSED.

### AGENT01BF3-01 (LOW): `_touch()` no crea ninguna fila cuando no existe fila de conversación
- **Problema.** La función auxiliar de "avanzar la revisión antes de la mutación" actualiza una fila existente de
  `chat_conversations`, pero no crea ninguna.
- **Impacto.** En una conversación que nunca tuvo fila de estado de chat, el incremento anticipado de la revisión no tiene efecto.
  Eso solo afecta a la señal secundaria de concurrencia. La nueva comprobación autoritativa de AGENT01BF1-01 sigue protegiendo la
  corrección.
- **Decisión.** Documentado como LOW conocido. Ni la ejecución en la VM ni el E2E en navegador revelaron ningún bloqueante derivado de él.
- **Estado:** **OPEN**.

## B. Defectos del harness de validación y de infraestructura (no son defectos del producto)

| Ejecución | Qué ocurrió | Clasificación | Corrección |
|---|---|---|---|
| AGENT-01AV1 ejecución 1 | La suite dentro del contenedor no podía importar `app`: un archivo de script añade su propia carpeta a `sys.path` | Harness | `-e PYTHONPATH=/srv`; simulación local fiel; la ejecución 2 se aceptó con 129/129 |
| AGENT-01BV1 ejecución 1 | **Rechazada.** El test de respuesta perdida falló (`AttributeError`): la función auxiliar `http()` del driver ocultaba el módulo `http`, por lo que el escenario nunca llegó a ejecutarse | Harness | `import http.client as httpclient` más una búsqueda de otras colisiones de nombres; la ejecución 2 se aceptó con 139/139 |
| UI-02 ejecución 1 | **Rechazada.** La red reinició la sesión SSH del propietario justo después de la preparación (21/21 comprobaciones superadas); no se ejecutó ningún test en navegador. Al no haber gestión de desconexiones, el stack y los secretos quedaron en la VM | Infraestructura + harness | Limpieza de recuperación; nueva ejecución con keepalives de SSH, SIGPIPE ignorado y un heartbeat del endpoint de control que dispara el desmontaje automático si se pierde la sesión |
| UI-02 limpieza v1 | **Fallida.** Su patrón `pkill -f` coincidía con su propia línea de comandos, por lo que se mató a sí misma antes de limpiar | Harness | v2: un patrón con corchete de regex más exclusión explícita de sí misma y de su proceso padre; se verificaron 0 contenedores, volúmenes, procesos y listeners, y el directorio de trabajo eliminado |
| UI-02 ejecución 2 | **Aceptada.** 28/28 comprobaciones del harness; 23 escenarios en navegador; desmontaje completo | — | — |
| UI-02 (navegador) | El registrador de peticiones en el lado de la página no pudo interceptar `fetch`: el JavaScript de la extensión se ejecuta en un mundo aislado y la CSP bloquea los scripts en línea. No se pudo redimensionar la ventana | Límites de la automatización | El transporte del token se demostró a partir del comportamiento del backend y de las líneas de auditoría; el diseño responsive se comprobó en local sobre código idéntico (etiquetado TEST) |
| FINAL-01 | Dos tests de `tests/test_compose.py` seguían esperando los conjuntos de servicios y redes anteriores a UI-02 | Expectativas de test desactualizadas (el runtime se había validado en la VM) | Actualizados a la topología validada, más 2 nuevas salvaguardas estáticas para `web`; suite: 410 superados / 8 omitidos |

Toda ejecución rechazada se conserva como evidencia (`vm-run1-*.txt`) y nunca se presenta como superada.
