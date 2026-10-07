"""Builds the technical report (REQ-DELIV-03/04) from the repository's Markdown docs and evidence screenshots.

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
            rows = ["<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in cells(line)) + "</tr></thead><tbody>"]
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                rows.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells(lines[j])) + "</tr>")
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


def readme_operations() -> str:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    start = text.index("## Prerequisites")
    end = text.index("## Evidence")
    return md_to_html(text[start:end], 1)


def figure(path: Path, caption: str) -> str:
    data = base64.b64encode(path.read_bytes()).decode()
    mime = "image/png" if path.suffix == ".png" else "image/jpeg"
    return f'<figure><img src="data:{mime};base64,{data}" alt=""><figcaption>{html.escape(caption)}</figcaption></figure>'


CAPTIONS = {
    "01-welcome": "Welcome state: NEXO layout, no invented conversations, drawer closed, real readiness ('Connected').",
    "02-rag-drawer": "RAG answer with the human-readable source; drawer with the real request id, route, model and result.",
    "03-critical-draft": "Critical incident draft: amber card, 'No ticket has been created yet' (PostgreSQL held only the seed tickets).",
    "04-critical-created": "After Confirm (CONFIRMAR + hidden token, no model call): real T-1003 and a pending critical_incident handoff.",
    "05-version-binding-B": "Version binding: the corrected draft B is the only actionable version; A is no longer confirmable.",
    "06-lead-draft": "Commercial lead draft (company, contact, email, need); nothing registered yet.",
    "07-lead-created-n8n": "Lead registered through the REAL n8n workflow; the drawer shows the real n8n execution id.",
    "08-n8n-down-not-completed": "n8n stopped: approved red 'Not completed' state, 503, no false success; recovered later with the same action.",
    "09-human-handoff": "Explicit human request: pending escalation, nobody has picked it up, no response time promised.",
    "10-customer-B-own-ticket": "Demo session switched to Customer B (server-side credential): B sees its own T-1002.",
    "11-TEST-responsive-390-820-draft": "TEST (fixture backend, identical frontend code): draft at 390 px and 820 px.",
    "12-TEST-responsive-390-820-drawer": "TEST (fixture backend, identical frontend code): technical drawer overlay at 390 px and 820 px.",
}


def screenshots() -> str:
    parts = []
    for shot in sorted(SHOTS.glob("*.jpg")):
        parts.append(figure(shot, f"{shot.stem}: {CAPTIONS.get(shot.stem, '')}"))
    if FINAL_SHOTS.exists():
        for shot in sorted(list(FINAL_SHOTS.glob("*.png")) + list(FINAL_SHOTS.glob("*.jpg"))):
            parts.append(figure(shot, "FINAL-02 (real VM): " + shot.stem.split("-", 1)[1].replace("-", " ")))
    return "\n".join(parts)


def ui02_cases() -> str:
    text = (ROOT / "evidence/14-evaluation-client/ui02-browser-e2e/ui02-report.md").read_text(encoding="utf-8")
    start = text.index("## B. Browser E2E matrix")
    end = text.index("## R. Responsive")
    return md_to_html(text[start:end], 1)


def build(draft: bool) -> str:
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    banner = ('<div class="draft">DRAFT: pending final VM deployment captures (n8n executions UI, DB records, restart, '
              '120 € → 150 €, backup/restore)</div>') if draft else ""
    css = (ROOT / "docs" / "report" / "report.css").read_text(encoding="utf-8")
    sections = [
        ("Executive summary", md_to_html(re.search(r"## 1\. Executive summary\n(.*?)\n## 2\.", (ROOT / "docs/TECHNICAL_REPORT_SOURCE.md").read_text(encoding="utf-8"), re.S).group(1), 1)),
        ("Architecture and design", doc("docs/ARCHITECTURE.md")),
        ("Installation, configuration and operation", readme_operations()),
        ("Autonomous evaluation instructions", doc("docs/EVALUATOR_RUNBOOK.md")),
        ("Test and evidence summary", doc("docs/TEST_EVIDENCE_SUMMARY.md")),
        ("Test cases: real browser end-to-end (UI-02)", ui02_cases()),
        ("Final deployment on the VM (FINAL-02)", doc("evidence/15-final-deployment/final-deployment-report.md")),
        ("Screenshots", screenshots()),
        ("Requirements coverage (all 116 IDs)", doc("docs/REQUIREMENTS_MATRIX.md")),
        ("Audit findings and remediations", doc("docs/AUDIT_FINDINGS.md")),
        ("Known limitations and improvements before production", doc("docs/KNOWN_LIMITATIONS.md")),
        ("AI-tool disclosure", doc("docs/AI_DISCLOSURE.md")),
    ]
    toc = "".join(f"<li>{html.escape(t)}</li>" for t, _ in sections)
    body = "".join(f'<section><h1>{i}. {html.escape(t)}</h1>{content}</section>' for i, (t, content) in enumerate(sections, 1))
    title = "Nexo AI Service Agent: Technical report" + (" (DRAFT)" if draft else "")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title><style>{css}</style></head>
<body>{banner}
<div class="cover"><h1>Nexo AI Service Agent</h1><p class="sub">Technical report: AI customer-service agent with RAG, confirmed actions and n8n automation</p>
<p>BNEXIA technical assessment · {date.today().isoformat()} · repository commit <code>{commit}</code>{' · <strong>DRAFT</strong>' if draft else ''}</p>
<p>No credentials, tokens or VM access details are included in this document (REQ-SEC-04). Test credentials are provided through a private channel.</p>
<h2>Contents</h2><ol class="toc">{toc}</ol></div>
{body}</body></html>"""


if __name__ == "__main__":
    OUT.write_text(build("--draft" in sys.argv), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
