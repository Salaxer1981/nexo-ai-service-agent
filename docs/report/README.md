# Technical report (PDF deliverable, in Spanish)

`Nexo_Technical_Report.pdf` is the final technical report, **written in Spanish** to match the assessment. It is
generated from the Spanish chapter sources in `docs/report/es/` and the accepted evidence screenshots. Nothing in the PDF
is edited by hand.

- `docs/report/es/*.md`: Spanish translations of the repository docs. Technical literals (code, commands, paths,
  identifiers, model and product names) are kept exactly, and quoted UI text stays as it appears in the interface.
  - **From `docs/`:** `ARCHITECTURE.md`, `EVALUATOR_RUNBOOK.md`, `TEST_EVIDENCE_SUMMARY.md`, `REQUIREMENTS_MATRIX.md`,
    `AUDIT_FINDINGS.md`, `KNOWN_LIMITATIONS.md`, `AI_DISCLOSURE.md`.
  - **From the README:** the operations sections.
  - **From the evidence reports:** UI-02 §B and FINAL-02.
- If an English source doc changes, update the matching Spanish chapter so the two never diverge.

```bash
python docs/report/build_report.py              # → docs/report/nexo-technical-report.html (add --draft for a draft banner)
chrome --headless=new --no-pdf-header-footer --user-data-dir=<temp dir> \
       --print-to-pdf=docs/report/Nexo_Technical_Report.pdf docs/report/nexo-technical-report.html
```
It uses the Python standard library only, plus any Chromium-based browser for printing.
