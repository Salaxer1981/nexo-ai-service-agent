# AI-tool disclosure (REQ-AI-01 / REQ-AI-02)

AI tools were used throughout development. The author directed the work: they set the requirements, phases, safety rules
and acceptance gates. **No AI output was accepted on the AI's word:** every change had to pass tests, independent
review, and validation against the real stack.

| Tool | Used for | How the results were validated |
|---|---|---|
| **Claude Code** (Anthropic; Claude Opus model) | Implementation of the backend, migrations, agent, n8n workflow, web client and runtime; automated tests; VM validation harnesses; browser automation for the real E2E (Claude in Chrome extension); evidence and documentation drafts | Each phase brief set acceptance gates. The work ran in small phases with one commit each. Changes passed the automated suite on a real PostgreSQL. Defects were reproduced on the old code first, and fixes were checked with mutation tests. Owner-run VM harnesses exercised the real model, n8n and Docker. A real browser was driven against the real stack. Rejected runs are kept and labelled, never presented as passed |
| **Codex** (OpenAI) | Independent targeted security and correctness audits of high-risk phases (confirmation, cancellation, concurrency, identity, RAG) | Each finding was reproduced, fixed in a dedicated phase, and re-audited before it was closed (see [`AUDIT_FINDINGS.md`](AUDIT_FINDINGS.md)). Codex didn't validate its own suggestions: closure needed tests plus a re-audit |
| **ChatGPT** (OpenAI) | Architecture and phase planning, task briefs, documentation structure, and prompts for the visual design | Plans were turned into explicit briefs with acceptance gates; the implementation was then validated as above |
| **Google Stitch** | The visual UI design reference (NEXO_UI_FREEZE_01: customer view and evaluator view, the "Sovereign Support" design system) | Used as a visual reference only. The UI was rebuilt in code (not exported), and placeholder or invented runtime data in the mockup was replaced by the real API contract. The rendered UI was compared side by side with the references |
| **OpenRouter models** (`x-ai/grok-4.7`, `openai/text-embedding-3-small`) | Runtime components of the product: message interpretation and embeddings. Not development tools | The model is constrained to a strict JSON schema with no tools or authority. Outputs are validated, grounding is checked, and confirmation is deterministic. Behaviour was validated with real calls on the VM |

## Safeguards applied to AI-assisted work
- **Secrets:** no secret was ever put in a prompt, the code, the repository or the evidence. The OpenRouter key reached
  the VM only through the owner's encrypted SSH session, and was deleted after each run. Secret scans are part of every
  validation.
- **Owner approval:** infrastructure changes on the VM (package installs, deployments, long-running stacks) needed the
  owner's explicit approval. SSH commands that need the VM password were run by the owner.
- **Honest reporting:** labels separate real evidence from TEST stand-ins (scripted model, fixture backend, FakeN8n).
  Limitations and open LOWs are declared, not hidden.
