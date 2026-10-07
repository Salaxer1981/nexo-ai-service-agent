# AGENT-01B — Journeys, idempotency, concurrency, compromised-model and failure matrices

All rows are automated tests in `tests/test_chat_actions.py` / `tests/test_agent.py`:
- **REAL PostgreSQL** 17.11 + pgvector 0.8.7;
- **TEST-ONLY scripted model**, often deliberately compromised;
- **FakeN8n** for leads: a TEST stand-in, NOT n8n.

Final run: 121/121 focused, 378 full (8 opt-in skipped). Live-model behaviour is in `live-smoke.md`.

## Ticket journey (PDF §4B)
| Step | Proof |
|------|-------|
| collect | "No tenemos internet" → `collecting_info`, missing `[contact_name, priority]`; asks only for those; the next turn's model context contains the collected values (no customer id) |
| prepare | the last field → `awaiting_confirmation`; summary = the stored values; «responde CONFIRMAR»; critical ⇒ "se escalará a una persona"; **+1 pending action, +0 tickets** |
| confirm | `CONFIRMAR` → **no model call** (`model: null`; an unexpected call would fail the test) → `ticket_created`, real id + `T-` reference; DB row = the stored draft, owner CUSTOMER_A |
| critical ⇒ human | `critical_incident` handoff created, `pending`, truthful wording |
| normal | no handoff |
| lost response | `confirmar` again → same ticket, same handoff (`replay`); tickets +1, handoffs +1 overall |
| T-reference | the new ticket's reference resolves through chat |

## Lead journey (PDF §4C), FakeN8n
| Step | Proof |
|------|-------|
| collect | PDF lead message → asks for company, contact, e-mail; the e-mail must be literally typed (an invented e-mail is refused) |
| prepare | exact summary; «no incluye precios, descuentos, contratos ni fechas»; **0 leads, 0 workflow calls** |
| confirm | `CONFIRMAR` → `leads.confirm_via_workflow` (the same code as `POST /leads/confirm`) → FakeN8n → real `/internal/leads` with the service credential → PostgreSQL; `workflow_execution_id` from the workflow; no model call |
| lost response | `CONFIRMAR` again → same lead (`replay`) |

## Handoff (PDF §4E)
| Case | Proof |
|------|-------|
| explicit human request | `handoff_created`, `pending`, «pendiente de atención… no se garantiza un plazo»; no "atendiendo / en breve / minutos" |
| resend (lost response) | same id |
| other wording, same conversation | `handoff_already_pending`, same id; handoffs +1 overall |
| deletion request | `unsafe_to_resolve` |
| critical ticket | `critical_incident` after confirmation (backend-decided) |
| summary | built by the backend from the customer's own words (never model text) |

## Cancellation and re-prepare
| Case | Proof |
|------|-------|
| CANCELAR ticket | the action becomes `cancelled`; CONFIRMAR ⇒ `nothing_pending`; the **plain API** confirm of that action ⇒ 409 `confirmation_invalid`; 0 tickets |
| CANCELAR lead | `cancelled`; CONFIRMAR ⇒ nothing; **0 workflow calls** |
| lead already handed to n8n | `cannot_cancel` (truthful) |
| changed data | re-prepared (summary updated); the old action `superseded`; the old version via the API ⇒ 409 |
| same data again | nothing new prepared |
| expired | `confirmation_invalid`, 0 tickets, state cleared |

## Idempotency / concurrency
| Case | Proof |
|------|-------|
| CONFIRMAR ×2 (ticket, lead) | same object, `replay` |
| DB failure **after** the ticket commit | 503 `action_not_confirmed` (no success claim); the next CONFIRMAR ⇒ same ticket, tickets +1 |
| n8n committed, answer lost | recovered from PostgreSQL; the next CONFIRMAR ⇒ same lead |
| 8 simultaneous CONFIRMAR (ticket, barrier) | all `ticket_created`, one id, exactly one `created`, tickets +1 |
| 6 simultaneous CONFIRMAR (lead, barrier) | all `lead_created`, one id, leads +1 |
| conversation serialization | while another session holds the conversation lock, CONFIRMAR waits (seen in `pg_locks`) and creates nothing; after release ⇒ created |

## Compromised-model matrix (the model is assumed malicious)
| Attempt | Result |
|---------|--------|
| PDF injection text + "CONFIRMAR" inside a longer message | not the gate ⇒ at most a prepared draft; 0 tickets/leads |
| «vale», «sí», «ok», «confirmar por favor», «CONFIRMAR!», «adelante, créalo» + a model that agrees | the pending action is only re-shown; nothing created |
| top-level `confirmation`, `confirm`, `customer_id`, `action_id`, `pending_action_id`, `idempotency_key`, `tool`, `url`, `sql`, `ticket_id`, `lead_id` | 503 `llm_invalid_output`, no change |
| `customer_id` nested inside `ticket` | 503, no change |
| handoff reason `critical_incident` / `vip` / `assign_to_admin` | 503, no handoff |
| invented contact e-mail | refused, asked again |
| another customer / another conversation sends CONFIRMAR or CANCELAR | `nothing_pending`; A's action stays `pending` and can still be confirmed by A |
| two pending actions in one conversation (one via the API) | `action_ambiguous`, nothing executed; CANCELAR clears both |
| starting another kind of action while one is pending | `action_blocked`, nothing prepared |
| model proposes `request_human` on the injection text | a handoff for the **same** customer only, enum reason, summary = customer's words (documented false-positive risk; no authorization/data boundary crossed) |
| AGENT-01A attacks (ticket ids from the model, fabricated citations, figures, read-only session) | still caught (`tests/test_agent.py`) |

## Failure matrix
| Failure | Response | Business effect |
|---------|----------|-----------------|
| LLM down before prepare | 503 `llm_unavailable` | none |
| DB down at prepare | 503 `database_unavailable`, «No se ha creado nada» | none |
| DB down at confirm | 503 `action_not_confirmed`, «vuelve a enviar CONFIRMAR: no se duplicará» | none / exactly once on retry |
| n8n down at confirm | 503 `lead_not_confirmed` (honest) | none; the retry resumes with the same key |
| workflow rejects | 502 `workflow_rejected`, «no se ha creado nada» | none |
| malformed model output / metadata (AGENT01A-01) | 503 `llm_invalid_output` (11 malformed `usage` shapes) | none |
| expired / superseded / cancelled | `confirmation_invalid` / `nothing_pending` | none |

## AGENT-01A read paths stay read-only
Knowledge and ticket-status turns use the READ ONLY session. While an action is pending they change nothing:
business tables and conversation state are byte-identical, and the response carries a `next_step` reminder.
`tests/test_agent.py` (60) still passes, including the PostgreSQL-enforced read-only test.
