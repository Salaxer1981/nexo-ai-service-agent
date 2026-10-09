// /chat contract (src/backend/app/main.py). The client never sends identity: the dev/preview proxy attaches the
// selected demo session's credential server-side. A body customer_id would be rejected (422) by the backend anyway.

export type DemoSession = "A" | "B";

export interface TicketSummary {
  contact_name: string;
  subject: string;
  description: string;
  priority: string;
}

export interface LeadSummary {
  company_name: string;
  contact_name: string;
  contact_email: string;
  need: string;
}

export interface PendingAction {
  kind: "ticket" | "lead";
  summary: TicketSummary | LeadSummary;
  confirmation_token: string;
}

export interface Source {
  kind: string;
  reference?: string;
  title?: string;
  resource?: string;
  status?: string;
  domain?: string; // kind "web": host of a provider citation (shown as text, never as a link)
  url?: string;
}

export interface ActionResult {
  kind: "ticket" | "lead" | "handoff";
  id: string;
  reference?: string;
  status?: string;
  priority?: string;
  reason?: string;
  idempotency?: string;
  workflow_execution_id?: string;
  status_message?: string;
  handoff?: { id: string; reason: string; status: string } | null;
}

export interface ChatResponse {
  conversation_id?: string;
  request_id?: string;
  intent?: string | null;
  status?: string;
  answer?: string | null;
  sources?: Source[];
  next_step?: string | null;
  model?: string | null;
  result?: ActionResult | null;
  pending_action?: PendingAction | null;
  code?: string;
  detail?: unknown;
}

export interface ChatTurn {
  httpStatus: number;
  body: ChatResponse;
  durationMs: number;
}

export interface ChatRequest {
  message: string;
  conversationId?: string;
  confirmationToken?: string;
}

const TOKEN_PATTERN = /^[0-9a-f]{16}$/;

/** One /chat turn. The confirmation token is forwarded byte-for-byte as received; it is never generated here. */
export async function sendChat(session: DemoSession, req: ChatRequest, fetchImpl: typeof fetch = fetch): Promise<ChatTurn> {
  const body: Record<string, string> = { message: req.message };
  if (req.conversationId) body.conversation_id = req.conversationId;
  if (req.confirmationToken !== undefined) {
    if (!TOKEN_PATTERN.test(req.confirmationToken)) throw new Error("invalid confirmation token");
    body.confirmation_token = req.confirmationToken;
  }
  const headers: Record<string, string> = { "Content-Type": "application/json", "X-Demo-Session": session };
  if (req.conversationId) headers["X-Conversation-ID"] = req.conversationId;
  const started = performance.now();
  const res = await fetchImpl("/api/chat", { method: "POST", headers, body: JSON.stringify(body) });
  let parsed: ChatResponse;
  try {
    parsed = ((await res.json()) as ChatResponse | null) ?? {};
  } catch {
    parsed = {};
  }
  return { httpStatus: res.status, body: parsed, durationMs: Math.round(performance.now() - started) };
}

/** Readiness of the backend behind the proxy (real /health/ready; no session needed). */
export async function backendReady(fetchImpl: typeof fetch = fetch): Promise<boolean> {
  try {
    const res = await fetchImpl("/api/health/ready", { headers: { "X-Demo-Session": "A" } });
    return res.ok;
  } catch {
    return false;
  }
}

/** A success card may render only with HTTP 200 AND an authoritative persisted object in `result`. */
export function isCreated(turn: ChatTurn): boolean {
  const { httpStatus, body } = turn;
  if (httpStatus !== 200 || !body.result || !body.result.id) return false;
  if (body.status === "ticket_created") return body.result.kind === "ticket" && Boolean(body.result.reference);
  if (body.status === "lead_created") return body.result.kind === "lead";
  return false;
}
