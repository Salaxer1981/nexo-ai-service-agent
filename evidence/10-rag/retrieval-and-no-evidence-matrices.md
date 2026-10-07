# Retrieval and no-evidence matrices: REAL model calibration

Model `openai/text-embedding-3-small` (dimension 1536), 10 chunks, 24 queries. Cosine similarity = pgvector `1 - (a <=> b)` (the live smoke reproduced the same 0.6988 score through pgvector). Source: `calibrate.py` → `calibration.json`.

## Threshold methodology
- Lowest expected-chunk score among supported queries (known + paraphrases): **0.4195**
- Highest top-1 score among unrelated queries: 0.2505; among in-domain-but-ABSENT queries: **0.369**
- Unrelated-only midpoint would be 0.33: it would accept the absent query "¿Tenéis oficina en Barcelona?" (0.369) as evidence, so rejected.
- **Chosen threshold = midpoint between the highest non-supported score and the lowest supported score = 0.39** (gap 0.0505, margin ≈ ±0.025–0.03: thin).
- Result at 0.39: supported queries with the expected chunk accepted **15/15**; non-supported queries with ANY accepted chunk **0/9**; top-1 correct 14/15.

## Retrieval matrix (supported queries)

| category | query | expected chunk | top-1 | top-1 score | expected score | accepted at threshold |
|---|---|---|---|---|---|---|
| known | ¿Cuál es el horario de atención del soporte? | `support-policy#horario-de-atencion` | ✓ | 0.6989 | 0.6989 | `support-policy#horario-de-atencion`, `support-policy#limites-del-agente-y-escalado`, `services#catalogo-de-servicios` |
| known | ¿Cuánto cuesta el diagnóstico inicial? | `commercial-policy#tarifas` | ✓ | 0.5371 | 0.5371 | `commercial-policy#tarifas` |
| known | ¿Qué servicios ofrecéis? | `services#catalogo-de-servicios` | ✓ | 0.5169 | 0.5169 | `services#catalogo-de-servicios`, `commercial-policy#tarifas` |
| known | ¿Cuándo se considera crítica una incidencia? | `support-policy#clasificacion-de-incidencias` | ✓ | 0.5048 | 0.5048 | `support-policy#clasificacion-de-incidencias`, `support-policy#limites-del-agente-y-escalado` |
| known | ¿El agente puede reiniciar un servidor? | `support-policy#limites-del-agente-y-escalado` | ✓ | 0.5457 | 0.5457 | `support-policy#limites-del-agente-y-escalado` |
| known | ¿Puedo darle mi contraseña al agente? | `security-policy#datos-sensibles-y-privacidad` | ✗ `support-policy#limites-del-agente-y-escalado` | 0.4503 | 0.437 | `support-policy#limites-del-agente-y-escalado`, `security-policy#datos-sensibles-y-privacidad`, `security-policy#acciones-y-borrados` |
| known | ¿Cuánto cuesta una implantación de IA? | `commercial-policy#implantaciones-de-ia-y-descuentos` | ✓ | 0.5721 | 0.5721 | `commercial-policy#implantaciones-de-ia-y-descuentos`, `services#nuevas-implantaciones-y-plazos` |
| known | ¿Cuándo estará lista una nueva implantación? | `services#nuevas-implantaciones-y-plazos` | ✓ | 0.6806 | 0.6806 | `services#nuevas-implantaciones-y-plazos` |
| paraphrase | ¿A qué hora puedo contactar con vosotros entre semana? | `support-policy#horario-de-atencion` | ✓ | 0.5153 | 0.5153 | `support-policy#horario-de-atencion` |
| paraphrase | precio mensual del soporte gestionado | `commercial-policy#tarifas` | ✓ | 0.6085 | 0.6085 | `commercial-policy#tarifas`, `support-policy#limites-del-agente-y-escalado`, `services#catalogo-de-servicios` |
| paraphrase | toda la oficina se ha quedado sin internet, ¿qué prioridad tiene? | `support-policy#clasificacion-de-incidencias` | ✓ | 0.4195 | 0.4195 | `support-policy#clasificacion-de-incidencias`, `support-policy#limites-del-agente-y-escalado` |
| paraphrase | ¿me podéis hacer un descuento? | `commercial-policy#implantaciones-de-ia-y-descuentos` | ✓ | 0.4205 | 0.4205 | `commercial-policy#implantaciones-de-ia-y-descuentos`, `commercial-policy#tarifas` |
| paraphrase | ¿cuánto tardáis en resolver una incidencia? | `support-policy#limites-del-agente-y-escalado` | ✓ | 0.4811 | 0.4811 | `support-policy#limites-del-agente-y-escalado`, `support-policy#clasificacion-de-incidencias`, `services#nuevas-implantaciones-y-plazos` |
| paraphrase | quiero que borréis mis datos | `security-policy#acciones-y-borrados` | ✓ | 0.4359 | 0.4359 | `security-policy#acciones-y-borrados`, `security-policy#datos-sensibles-y-privacidad` |
| paraphrase | what are your support hours? | `support-policy#horario-de-atencion` | ✓ | 0.511 | 0.511 | `support-policy#horario-de-atencion` |

## No-evidence matrix

| category | query | best score | accepted | evidence state |
|---|---|---|---|---|
| unrelated | receta de paella valenciana | 0.1674 | 0 | insufficient |
| unrelated | ¿Quién ganó el mundial de fútbol de 2010? | 0.1447 | 0 | insufficient |
| unrelated | ¿Cuál es la capital de Australia? | 0.0664 | 0 | insufficient |
| unrelated | cómo cambiar el aceite del coche | 0.2209 | 0 | insufficient |
| unrelated | precio del bitcoin hoy | 0.2505 | 0 | insufficient |
| unrelated | escríbeme un poema sobre el mar | 0.1681 | 0 | insufficient |
| absent_in_domain | ¿Tenéis oficina en Barcelona? | 0.369 | 0 | insufficient |
| absent_in_domain | ¿Cuál es vuestro número de teléfono? | 0.3067 | 0 | insufficient |
| absent_in_domain | ¿Desarrolláis aplicaciones móviles? | 0.3181 | 0 | insufficient |

Note: the one top-1 miss ("¿Puedo darle mi contraseña al agente?") ranks `security-policy#datos-sensibles-y-privacidad` 2nd (0.437), still accepted.
Small evaluation set (24 queries) and a thin margin: the threshold is a calibrated, conservative default (`RAG_MIN_SCORE`), not a guarantee.
The later agent must still check that accepted evidence actually answers the question (REQ-RAG-03/04).
