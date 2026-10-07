# Chunking example: knowledge/02_support_policy.md

Rule: one chunk per `## ` section (sections are short; paragraphs are grouped up to 1200 chars only if a section is longer; no overlap). Chunk text = `<title> — <section>` + section body, so the embedding carries the document/section context. Keys are `<source_id>#<slug(section)>`: stable across edits to other sections.

## chunk `support-policy#horario-de-atencion` (ordinal 0, sha256 `304d5875e6b5a442…`)

```
Soporte — Horario de atención

Horario ordinario: lunes a viernes, 09:00–18:00, Europe/Madrid. Fuera de horario se registran las solicitudes para revisión.
```

## chunk `support-policy#clasificacion-de-incidencias` (ordinal 1, sha256 `72b693d37b34c5b7…`)

```
Soporte — Clasificación de incidencias

Caída total que afecta a toda la empresa: crítica. Problema que afecta a una persona sin bloquear toda su actividad: normal.
```

## chunk `support-policy#limites-del-agente-y-escalado` (ordinal 2, sha256 `4d824b5f9f296b73…`)

```
Soporte — Límites del agente y escalado

El agente no ejecuta cambios de red, reinicios de servidores ni modificaciones de permisos. Las incidencias críticas se escalan a un humano. No se garantiza un plazo de resolución.
```
