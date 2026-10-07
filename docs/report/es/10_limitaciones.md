# Limitaciones conocidas y mejoras antes de producción

## Hallazgos abiertos
| ID | Severidad | Limitación |
|---|---|---|
| AGENT01BF3-01 | LOW (backend) | `_touch()` (avanza la revisión de la conversación antes de una mutación) no crea una fila en `chat_conversations` cuando no existe ninguna. Solo afecta a la señal secundaria de concurrencia; la comprobación autoritativa de la acción sigue garantizando la corrección. No se observó ningún bloqueo en las ejecuciones en la VM ni en el navegador |
| UI02-01 | LOW (UI) | Cuando el backend vuelve a mostrar el *mismo* borrador (`confirmation_review_required`), la copia anterior se marca con la etiqueta "Replaced". Correctamente no es accionable, pero la etiqueta exagera la situación |
| UI02-02 | LOW (UI) | La hora de una entrada de la barra lateral es la de creación de su hueco de conversación vacío, no la del envío de su primer mensaje |
| UI02-04 | LOW (UI) | La insignia "Connected" comprueba la disponibilidad (readiness) solo al cargar la página; durante una caída se actualiza al recargar. Las solicitudes siempre informan del fallo con honestidad |
| UI02-03 | LOW (UI) | En torno a 820 px con la barra lateral visible, los cuatro recuadros del borrador miden unos 100 px de ancho y los valores largos se truncan (el valor completo aparece en el tooltip) |

## Alcance de la validación
- **Diseño adaptable (responsive):**
  - **escritorio:** validado en un navegador real contra la pila real;
  - **390 px y 820 px:** comprobados sobre el **código frontend idéntico**, en local, contra un backend de fixture TEST.
    No era posible redimensionar la ventana del navegador automatizado, y el entorno de ejecución web de producción
    prohíbe correctamente su inclusión en marcos (framing). El diseño es CSS puro, independiente de los datos del backend.
- **Actualización de precio (120 € → 150 €):** validada en la VM a nivel de recuperación y de chat, y después restaurada
  (FINAL-02).
- **La copia de seguridad (backup) y la restauración** se ejecutaron en la VM (FINAL-02). El reinicio destructivo
  (`down -v`) está documentado, pero deliberadamente no se ejecutó en el despliegue de evaluación.
- **Caídas:** se ejercitaron en la VM caídas reales de n8n, del backend y de PostgreSQL. Los timeout/429/5xx del LLM se
  demostraron con servidores stub (TEST).
- **Despliegues:** las ejecuciones de validación (AV1, BV1, UI-02) fueron temporales. FINAL-02 dejó la pila en
  funcionamiento en la VM para la evaluación (autorizado por el propietario), con copias de seguridad en
  `~/nexo-eval-backups`.

## Modelo de seguridad e identidad (solo para evaluación)
- **Dos clientes de demostración:** dos clientes sintéticos con tokens bearer estáticos. Sin caducidad, rotación, cuentas
  de usuario ni MFA. **No es una plataforma de identidad de producción.**
- **El puerto web es el inicio de sesión de demostración:** la frontera del lado del servidor del cliente web adjunta la
  credencial de demostración correspondiente a la sesión que selecciona el navegador. Cualquiera que pueda acceder al
  puerto web de **loopback** (en el host, o a través de un túnel SSH) puede actuar como cualquiera de los dos clientes
  sintéticos. Esto es aceptable únicamente para evaluación.
- **Secretos:** residen en un `.env` del host (modo 600), sin gestor de secretos de producción. Nada está certificado (no
  se afirma cumplimiento ISO/SOC).
- **Datos enviados a OpenRouter / xAI:** mensajes del usuario, secciones de conocimiento recuperadas y un contexto mínimo
  de la conversación. Nunca identificadores de cliente, tokens, credenciales ni filas de tickets.
- **Dirección de la VM en el historial de git:** apareció en 3 commits anteriores (sin credenciales). Está suprimida de
  los archivos actuales.

## Funcionales
- **Sin SLA:** no se promete ningún tiempo de respuesta ni de resolución; los escalados humanos (handoffs) son siempre
  "pendientes".
- **Sin historial restaurado:** el historial de la conversación no se restaura tras recargar la página (no es una función
  del backend). Los registros del lado del servidor (tickets, solicitudes comerciales (leads), handoffs) persisten.
- **Latencia del modelo:** un turno suele tardar 2–15 s. Los turnos de más de 30 s responden 503 `llm_unavailable`; es
  seguro, sin éxito falso. La clasificación de la intención depende del modelo y puede pedir aclaraciones.
- **Sin implicación lógica en la fundamentación:** la validación comprueba citas y cifras, no la implicación lógica
  completa.
- **Sin límites de tasa:** no hay límite de tasa ni presupuesto de LLM por cliente (solo el límite de la cuenta de
  OpenRouter).
- **Sin pool de conexiones:** una conexión a la base de datos por operación, lo cual es suficiente para la carga de la
  evaluación.
- **Lockfile de Python:** solo se fijan las dependencias directas de Python (sin lockfile con hashes). Las dependencias
  npm están bloqueadas (lockfile).

## Mejoras antes de producción
- **Identidad:** autenticación real (OIDC), sesiones por usuario y rotación de tokens.
- **Secretos:** un gestor de secretos.
- **Perímetro de red:** terminación TLS y un proxy inverso con limitación de tasa.
- **Operaciones:** un pool de conexiones, logs centralizados con retención, alertas y copias de seguridad programadas con
  restauraciones probadas.
- **UI:** corregir UI02-01..04 y, si fuera necesario, persistir el historial de conversaciones en el servidor.
- **Backend:** corregir AGENT01BF3-01 (crear la fila en `_touch()`).
