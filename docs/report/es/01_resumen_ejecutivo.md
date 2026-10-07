# Resumen ejecutivo

**Qué es Nexo.** Un agente de atención al cliente pequeño y verificable para la empresa ficticia Nexo Servicios, desplegado con
Docker Compose sobre Ubuntu. El agente:
- responde a partir de cuatro documentos de la empresa, con referencias (RAG sobre PostgreSQL/pgvector, embeddings de OpenRouter);
- registra incidencias y solicitudes comerciales **solo tras la confirmación explícita del resumen exacto mostrado**;
- consulta el estado de los tickets en la API de negocio;
- escala a una persona, siempre como "pendiente";
- crea solicitudes comerciales (leads) únicamente mediante un **workflow de n8n** que escribe a través de un endpoint privado del backend.

**Regla de diseño: el LLM propone; el backend autoriza y ejecuta.** `x-ai/grok-4.7` (a través de OpenRouter) solo convierte
un mensaje en una interpretación JSON estricta. La identidad, el aislamiento, la confirmación, la idempotencia y todas las
escrituras son código determinista del backend.

**Validación.**
- **Suite automatizada:** 410 pruebas del backend (PostgreSQL real) más 17 pruebas del cliente web.
- **Auditoría independiente:** cuatro hallazgos de severidad alta, todos corregidos y cerrados.
- **Ejecuciones reales en la VM** (PostgreSQL/pgvector, n8n y OpenRouter reales): ejecuciones aceptadas de 138/138 (RAG),
  129/129 (agente de solo lectura), 139/139 (acciones confirmadas), 28/28 (entorno de ejecución web) y 35/35 (despliegue
  permanente final).
- **E2E en navegador real:** 23 escenarios contra la pila real.

**Despliegue.** La solución está en funcionamiento en la VM de evaluación (FINAL-02: 35/35, incluidas caídas reales del
backend y de PostgreSQL, copia de seguridad (backup) y restauración, el cambio de 120 € → 150 € a nivel de chat, la
persistencia tras reinicio y un escaneo con cero secretos).
