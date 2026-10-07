# Declaración de herramientas de IA

Declaración conforme a REQ-AI-01 / REQ-AI-02.

Se utilizaron herramientas de IA a lo largo de todo el desarrollo. El autor dirigió el trabajo: estableció los requisitos,
las fases, las reglas de seguridad y los criterios de aceptación. **Ninguna salida de IA se aceptó por la palabra de la
IA:** cada cambio tuvo que superar pruebas, una revisión independiente y la validación contra la pila real.

| Herramienta | Uso | Cómo se validaron los resultados |
|---|---|---|
| **Claude Code** (Anthropic; modelo Claude Opus) | Implementación del backend, las migraciones, el agente, el workflow de n8n, el cliente web y su entorno de ejecución; pruebas automatizadas; harness de validación en la VM; automatización del navegador para el E2E real (extensión Claude in Chrome); borradores de evidencias y documentación | Cada encargo de fase fijaba criterios de aceptación. El trabajo se realizó en fases pequeñas con un commit cada una. Los cambios superaron la suite automatizada sobre un PostgreSQL real. Los defectos se reprodujeron primero sobre el código antiguo, y las correcciones se comprobaron con pruebas de mutación. Los harness de validación en la VM, ejecutados por el propietario, ejercitaron el modelo real, n8n y Docker. Se controló un navegador real contra la pila real. Las ejecuciones rechazadas se conservan y se etiquetan, nunca se presentan como superadas |
| **Codex** (OpenAI) | Auditorías independientes y focalizadas de seguridad y corrección de las fases de alto riesgo (confirmación, cancelación, concurrencia, identidad, RAG) | Cada hallazgo se reprodujo, se corrigió en una fase dedicada y se volvió a auditar antes de cerrarlo (véase [`AUDIT_FINDINGS.md`](../../AUDIT_FINDINGS.md)). Codex no validó sus propias sugerencias: el cierre requería pruebas más una nueva auditoría |
| **ChatGPT** (OpenAI) | Planificación de la arquitectura y de las fases, encargos de tareas, estructura de la documentación y prompts para el diseño visual | Los planes se convirtieron en encargos explícitos con criterios de aceptación; después, la implementación se validó como se indica arriba |
| **Google Stitch** | La referencia de diseño visual de la UI (NEXO_UI_FREEZE_01: vista de cliente y vista de evaluador, el sistema de diseño "Sovereign Support") | Se usó solo como referencia visual. La UI se reconstruyó en código (no se exportó), y los datos de ejecución provisionales o inventados de la maqueta se sustituyeron por el contrato real de la API. La UI renderizada se comparó en paralelo con las referencias |
| **Modelos de OpenRouter** (`x-ai/grok-4.7`, `openai/text-embedding-3-small`) | Componentes de ejecución del producto: interpretación de mensajes y embeddings. No son herramientas de desarrollo | El modelo está restringido a un esquema JSON estricto, sin herramientas ni autoridad. Las salidas se validan, se comprueba la fundamentación y la confirmación es determinista. El comportamiento se validó con llamadas reales en la VM |

## Salvaguardas aplicadas al trabajo asistido por IA
- **Secretos:** nunca se introdujo ningún secreto en un prompt, en el código, en el repositorio ni en las evidencias. La
  clave de OpenRouter llegó a la VM únicamente a través de la sesión SSH cifrada del propietario y se eliminó tras cada
  ejecución. Los escaneos de secretos forman parte de todas las validaciones.
- **Aprobación del propietario:** los cambios de infraestructura en la VM (instalación de paquetes, despliegues, pilas de
  larga duración) requerían la aprobación explícita del propietario. Los comandos SSH que necesitan la contraseña de la VM
  los ejecutó el propietario.
- **Información honesta:** las etiquetas separan la evidencia real de los sustitutos TEST (modelo con guion, backend de
  fixture, FakeN8n). Las limitaciones y los hallazgos LOW abiertos se declaran, no se ocultan.
