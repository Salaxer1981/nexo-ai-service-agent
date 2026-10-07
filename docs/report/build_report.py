"""Builds the technical report in Spanish (REQ-DELIV-03/04) from docs/report/es/*.md and the evidence screenshots.

Usage:  python docs/report/build_report.py [--draft]   → docs/report/nexo-technical-report.html
Then print to PDF with headless Chrome (see docs/report/README.md). Standard library only.
The report contains NO secrets: it is assembled from tracked, secret-scanned files.
"""
import base64
import html
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "report" / "nexo-technical-report.html"
SHOTS = ROOT / "evidence" / "14-evaluation-client" / "ui02-browser-e2e" / "screenshots"
FINAL_SHOTS = ROOT / "evidence" / "15-final-deployment" / "screenshots"


# ----------------------------------------------------------------------------------------------- minimal Markdown
def inline(text: str) -> str:
    text = re.sub(r"\[(`[^`]+`)\]\([^)]+\)", r"\1", text)  # [`file`](path) → `file`
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for p in parts:
        if p.startswith("`") and p.endswith("`") and len(p) > 1:
            out.append(f"<code>{html.escape(p[1:-1])}</code>")
            continue
        s = html.escape(p, quote=False)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", s)  # links → text (paths are listed in the evidence chapter)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", s)
        out.append(s)
    return "".join(out)


STATUS = {"PASS", "PARTIAL", "OPEN", "CLOSED", "PENDING", "N/A", "TEST", "REAL", "HIGH", "LOW", "MEDIUM", "INFO", "Estado", "ID", "#"}


def _st(cell: str) -> str:
    """Short canonical labels (status/severity) never wrap inside narrow table columns."""
    c = cell.strip().strip("*").strip()
    ident = re.fullmatch(r"(REQ-[A-Z]+-[0-9.]+(\.\.[0-9]+)?|AGENT01[A-Z0-9]*-\d+|UI02-\d+)", c)
    return ' class="st"' if c in STATUS or ident else ""


def md_to_html(md: str, shift: int = 0) -> str:
    lines = md.replace("\r\n", "\n").split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre><code>" + html.escape("\n".join(lines[i + 1:j])) + "</code></pre>")
            i = j + 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            level = min(6, len(m.group(1)) + shift)
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            i += 1
            continue
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|\s*$", lines[i + 1]):
            cells = lambda l: [c.strip() for c in l.strip().strip("|").split("|")]
            rows = ["<table><thead><tr>" + "".join(f"<th{_st(c)}>{inline(c)}</th>" for c in cells(line)) + "</tr></thead><tbody>"]
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                rows.append("<tr>" + "".join(f"<td{_st(c)}>{inline(c)}</td>" for c in cells(lines[j])) + "</tr>")
                j += 1
            out.append("".join(rows) + "</tbody></table>")
            i = j
            continue
        if line.startswith(">"):
            j, buf = i, []
            while j < len(lines) and lines[j].startswith(">"):
                buf.append(lines[j].lstrip(">").strip())
                j += 1
            out.append("<blockquote>" + md_to_html("\n".join(buf)) + "</blockquote>")
            i = j
            continue
        if re.match(r"^\s*([-*]|\d+\.)\s+", line):
            j, items = i, []
            while j < len(lines) and (re.match(r"^\s*([-*]|\d+\.)\s+", lines[j]) or (lines[j].startswith("  ") and lines[j].strip())):
                items.append(lines[j])
                j += 1
            out.append(render_list(items))
            i = j
            continue
        if line.strip() in ("---", "***"):
            out.append("<hr>")
            i += 1
            continue
        if not line.strip():
            i += 1
            continue
        j, buf = i, []
        while j < len(lines) and lines[j].strip() and not re.match(r"^(#{1,6}\s|```|\||>|\s*([-*]|\d+\.)\s)", lines[j]):
            buf.append(lines[j].strip())
            j += 1
        out.append("<p>" + inline(" ".join(buf)) + "</p>")
        i = j
    return "\n".join(out)


def render_list(items: list[str]) -> str:
    def indent(l):
        return len(l) - len(l.lstrip(" "))
    base = indent(items[0])
    ordered = bool(re.match(r"^\s*\d+\.", items[0]))
    tag = "ol" if ordered else "ul"
    html_items, k = [], 0
    while k < len(items):
        text = re.sub(r"^\s*([-*]|\d+\.)\s+", "", items[k])
        k += 1
        sub = []
        while k < len(items) and (indent(items[k]) > base):
            sub.append(items[k])
            k += 1
        cont = [s.strip() for s in sub if not re.match(r"^\s*([-*]|\d+\.)\s+", s)]
        nested = [s for s in sub if re.match(r"^\s*([-*]|\d+\.)\s+", s)]
        body = inline(" ".join([text] + cont))
        if nested:
            body += render_list(nested)
        html_items.append(f"<li>{body}</li>")
    return f"<{tag}>" + "".join(html_items) + f"</{tag}>"


# ----------------------------------------------------------------------------------------------- report assembly
def doc(path: str, drop_title: bool = True, shift: int = 1) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    if drop_title:
        text = re.sub(r"^# .*\n", "", text, count=1)
    return md_to_html(text, shift)


def figure(path: Path, caption: str) -> str:
    data = base64.b64encode(path.read_bytes()).decode()
    mime = "image/png" if path.suffix == ".png" else "image/jpeg"
    return f'<figure><img src="data:{mime};base64,{data}" alt=""><figcaption>{html.escape(caption)}</figcaption></figure>'


CAPTIONS = {
    # Capturas UI-02 (entorno real; el texto de la interfaz se cita tal como aparece en pantalla).
    "01-welcome": "Estado de bienvenida: diseño NEXO, sin conversaciones inventadas, panel de detalles cerrado y disponibilidad real (la interfaz muestra \"Connected\").",
    "02-rag-drawer": "Respuesta RAG con su fuente legible; el panel \"Technical details\" muestra el identificador de solicitud, la ruta, el modelo y el resultado reales.",
    "03-critical-draft": "Borrador de incidencia crítica: tarjeta ámbar con el aviso \"No ticket has been created yet\" (PostgreSQL solo contenía los tickets semilla).",
    "04-critical-created": "Tras \"Confirm incident\" (CONFIRMAR + token oculto, sin llamada al modelo): ticket real T-1003 y escalado humano critical_incident pendiente.",
    "05-version-binding-B": "Vinculación de versión: el borrador corregido B es la única versión confirmable; A ya no puede confirmarse.",
    "06-lead-draft": "Borrador de solicitud comercial (lead): empresa, contacto, correo y necesidad; todavía no se ha registrado nada.",
    "07-lead-created-n8n": "Solicitud comercial registrada a través del workflow REAL de n8n; el panel muestra el identificador real de la ejecución de n8n.",
    "08-n8n-down-not-completed": "n8n detenido: estado rojo aprobado (la interfaz muestra \"Not completed\"), HTTP 503, sin falso éxito; recuperado después con la misma acción.",
    "09-human-handoff": "Petición explícita de atención humana: escalado pendiente, nadie lo ha recogido todavía y no se promete plazo de respuesta.",
    "10-customer-B-own-ticket": "Sesión de demostración cambiada a Customer B (credencial en el servidor): B ve su propio ticket T-1002.",
    "11-TEST-responsive-390-820-draft": "TEST (backend de pruebas, mismo código de frontend): borrador a 390 px y 820 px.",
    "12-TEST-responsive-390-820-drawer": "TEST (backend de pruebas, mismo código de frontend): panel de detalles técnicos superpuesto a 390 px y 820 px.",
    # Capturas FINAL-02 (VM real).
    "01-db-records-after-real-journeys": "Registros de PostgreSQL tras los recorridos reales en el cliente web (consulta de solo lectura sobre la VM).",
    "02-rag-price-150-chat-answer": "Precio cambiado a 150 €: el chat responde «El diagnóstico inicial cuesta 150 € más IVA.» con la misma referencia 03_commercial_policy.md § Tarifas.",
    "03-rag-price-restored-120-chat-answer": "Corpus canónico restaurado: el chat vuelve a responder 120 € con la misma referencia.",
    "04-backend-down-not-completed": "Caída real del backend: la interfaz muestra \"NOT COMPLETED\", HTTP 502 backend_unreachable, el resto de campos \"Not available\", sin tarjeta de éxito.",
    "05-db-down-unavailable-badge": "Caída real de PostgreSQL: tras recargar, el indicador muestra \"Unavailable\".",
    "06-db-down-not-completed": "Caída real de PostgreSQL: el mensaje recibe la tarjeta roja \"NOT COMPLETED\" y HTTP 503, sin datos inventados.",
    "07-backup-restore-before-restore": "Antes de restaurar: un escalado humano creado DESPUÉS de la copia de seguridad (3 escalados).",
    "08-backup-restore-after-restore": "Después de pg_restore: el escalado posterior a la copia ha desaparecido; el resto de registros es idéntico.",
    "09-restart-persistence-T1003": "Tras reiniciar toda la pila: el cliente web se reconecta y T-1003 sigue respondiéndose desde PostgreSQL.",
    "10-n8n-executions-from-n8n-db": "Ejecuciones del workflow NexoLeadCreate01 leídas de la propia base de datos de n8n.",
    "11-n8n-ui-executions": "Interfaz de n8n, pestaña de ejecuciones: nexo-lead-create 1–5, todas con éxito (la 1 es la solicitud comercial real; 2–5 son sondas de disponibilidad).",
}


def screenshots() -> str:
    parts = []
    for shot in sorted(SHOTS.glob("*.jpg")):
        parts.append(figure(shot, f"UI-02 · {shot.stem}: {CAPTIONS.get(shot.stem, '')}"))
    if FINAL_SHOTS.exists():
        for shot in sorted(list(FINAL_SHOTS.glob("*.png")) + list(FINAL_SHOTS.glob("*.jpg"))):
            parts.append(figure(shot, f"FINAL-02 (VM real) · {shot.stem}: {CAPTIONS.get(shot.stem, '')}"))
    return "\n".join(parts)


ES = ROOT / "docs" / "report" / "es"


def es(name: str) -> str:
    return doc(f"docs/report/es/{name}")


def build(draft: bool) -> str:
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    banner = ('<div class="draft">BORRADOR: pendiente de las capturas del despliegue final en la VM</div>') if draft else ""
    css = (ROOT / "docs" / "report" / "report.css").read_text(encoding="utf-8")
    sections = [
        ("Resumen ejecutivo", es("01_resumen_ejecutivo.md")),
        ("Arquitectura y diseño", es("02_arquitectura.md")),
        ("Instalación, configuración y operación", es("03_instalacion_operacion.md")),
        ("Instrucciones de evaluación autónoma", es("04_evaluacion_autonoma.md")),
        ("Resumen de pruebas y evidencias", es("05_pruebas_evidencias.md")),
        ("Casos de prueba: E2E real en navegador (UI-02)", es("06_casos_ui02.md")),
        ("Despliegue final en la VM (FINAL-02)", es("07_despliegue_final.md")),
        ("Capturas de pantalla", '<p>Las capturas son evidencia histórica y no se han editado: el texto de la interfaz aparece tal como se mostró. Las capturas marcadas como TEST usan un backend de pruebas; el resto procede del entorno real.</p>' + screenshots()),
        ("Cobertura de requisitos (los 116 identificadores)", es("08_matriz_requisitos.md")),
        ("Hallazgos de auditoría y correcciones", es("09_auditoria.md")),
        ("Limitaciones conocidas y mejoras antes de producción", es("10_limitaciones.md")),
        ("Declaración de herramientas de IA", es("11_declaracion_ia.md")),
    ]
    toc = "".join(f"<li>{html.escape(t)}</li>" for t, _ in sections)
    body = "".join(f'<section><h1>{i}. {html.escape(t)}</h1>{content}</section>' for i, (t, content) in enumerate(sections, 1))
    title = "Nexo AI Service Agent: Informe técnico" + (" (BORRADOR)" if draft else "")
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{title}</title><style>{css}</style></head>
<body>{banner}
<div class="cover"><h1>Nexo AI Service Agent</h1><p class="sub">Informe técnico: agente de atención con IA, RAG, acciones confirmadas y automatización con n8n</p>
<p>Prueba técnica BNEXIA · 2026-10-07 · commit del repositorio <code>{commit}</code>{' · <strong>BORRADOR</strong>' if draft else ''}</p>
<p>Este documento no incluye credenciales, tokens ni datos de acceso a la VM (REQ-SEC-04). Las credenciales de prueba se entregan por un canal privado.</p>
<h2>Contenido</h2><ol class="toc">{toc}</ol></div>
{body}</body></html>"""


if __name__ == "__main__":
    OUT.write_text(build("--draft" in sys.argv), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
