# Technical report (PDF deliverable)

`Nexo_Technical_Report.pdf` (final, after the FINAL-02 deployment) is generated from the repository's own Markdown docs and evidence screenshots. Nothing
is written by hand, so the report can't drift from the evidence.

```bash
python docs/report/build_report.py --draft      # final: omit --draft → docs/report/nexo-technical-report.html
chrome --headless=new --no-pdf-header-footer --user-data-dir=<temp dir> \
       --print-to-pdf=docs/report/Nexo_Technical_Report.pdf docs/report/nexo-technical-report.html
```
It uses the Python standard library only, plus any Chromium-based browser for printing. Screenshots from the final VM
deployment, in `evidence/15-final-deployment/screenshots/`, are picked up automatically when present.
