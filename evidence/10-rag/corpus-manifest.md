# Corpus manifest: knowledge/ (source of truth; exactly the four PDF §5 documents, REQ-RAG-07, REQ-KB-01..04)

| source_id | title | reference (file) | document sha256 | chunks |
|---|---|---|---|---|
| `services` | Servicios | `01_services.md` | `c558f94a29885fc9ce67e5f5cbf53cf2e374348e95403386af4d1944f6d4f6b0` | 2 |
| `support-policy` | Soporte | `02_support_policy.md` | `a2955c0c16346bf113a00b8b677e4ac76421eaa6198576b4392503ec291626bb` | 3 |
| `commercial-policy` | Condiciones comerciales | `03_commercial_policy.md` | `6b9ffe106baeeb978414c667b783de5cc3540b2262c8aa005dedefe74f21e7cf` | 2 |
| `security-policy` | Seguridad | `04_security_policy.md` | `65dc1544a629d2abd5188db3b6bbe31f779ec45ae568f9eaf5fe85fc08b491e1` | 3 |

## Chunks (stable keys; reference format `<file> § <section>`)

| chunk_key | ordinal | reference | chunk sha256 (12) | chars |
|---|---|---|---|---|
| `services#catalogo-de-servicios` | 0 | 01_services.md § Catálogo de servicios | `77fe54562998` | 152 |
| `services#nuevas-implantaciones-y-plazos` | 1 | 01_services.md § Nuevas implantaciones y plazos | `da0a197383a0` | 179 |
| `support-policy#horario-de-atencion` | 0 | 02_support_policy.md § Horario de atención | `304d5875e6b5` | 155 |
| `support-policy#clasificacion-de-incidencias` | 1 | 02_support_policy.md § Clasificación de incidencias | `72b693d37b34` | 164 |
| `support-policy#limites-del-agente-y-escalado` | 2 | 02_support_policy.md § Límites del agente y escalado | `4d824b5f9f29` | 221 |
| `commercial-policy#tarifas` | 0 | 03_commercial_policy.md § Tarifas | `46645bf32612` | 133 |
| `commercial-policy#implantaciones-de-ia-y-descuentos` | 1 | 03_commercial_policy.md § Implantaciones de IA y descuentos | `e0e0042be2d5` | 169 |
| `security-policy#datos-sensibles-y-privacidad` | 0 | 04_security_policy.md § Datos sensibles y privacidad | `5840d014b8c3` | 148 |
| `security-policy#documentos-recuperados-y-secretos` | 1 | 04_security_policy.md § Documentos recuperados y secretos | `494712c61b15` | 164 |
| `security-policy#acciones-y-borrados` | 2 | 04_security_policy.md § Acciones y borrados | `72870b383438` | 165 |

Total: 4 documents, 10 chunks. Content is the PDF text verbatim; only the metadata header and `##` section headings (structure for references) were added (test_corpus_is_exactly_the_four_pdf_documents_verbatim).
