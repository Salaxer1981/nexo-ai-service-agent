// UI-01 focused tests. Backend responses are TEST fixtures shaped exactly like the real /chat contract
// (src/backend/app/main.py + chat_actions.py, as observed in AGENT-01BV1); no network, no model.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import App from "../App";
// @ts-expect-error -- plain JS config module (no type declarations)
import { demoAuth } from "../../vite.config.js";

type Reply = { status: number; body: unknown };
interface Call { url: string; headers: Record<string, string>; body: Record<string, unknown> | null }

function backend(replies: Reply[]) {
  const calls: Call[] = [];
  const queue = [...replies];
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/health/ready") return new Response(JSON.stringify({ status: "ready" }), { status: 200 });
    calls.push({ url, headers: { ...(init?.headers as Record<string, string>) }, body: init?.body ? JSON.parse(String(init.body)) : null });
    const next = queue.shift();
    if (!next) throw new Error("unexpected request");
    return new Response(JSON.stringify(next.body), { status: next.status, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
  return { fetchImpl, calls };
}

const CONV = "c0ffee00-0000-4000-8000-000000000001";
const TOKEN_A = "8be7aaa535f42657";
const TOKEN_B = "db2b899225dbac00";
const base = { conversation_id: CONV, sources: [], next_step: null };

const draft = (token: string, priority = "critical", subject = "Sin internet en toda la oficina") => ({
  ...base,
  request_id: "req-draft-" + token.slice(0, 4),
  intent: "create_ticket",
  status: "awaiting_confirmation",
  answer: "Voy a crear este ticket. Para ejecutarlo responde CONFIRMAR. Para descartarlo, responde CANCELAR.",
  model: "x-ai/grok-4.7",
  result: null,
  pending_action: {
    kind: "ticket",
    summary: { contact_name: "Ana", subject, description: "Afecta a toda la oficina.", priority },
    confirmation_token: token,
  },
});

const created = {
  ...base,
  request_id: "req-created",
  intent: "confirmation",
  status: "ticket_created",
  answer: "He creado el ticket: T-1003.",
  model: null,
  pending_action: null,
  result: {
    kind: "ticket", id: "f3e80b8a-dcfd-4cf7-b238-ca7b5e3a9ef4", reference: "T-1003", status: "open", priority: "critical",
    idempotency: "created", handoff: { id: "48faaa3c-39ef-4e6b-b8b4-37b25de1c202", reason: "critical_incident", status: "pending" },
  },
};

async function say(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(screen.getByLabelText("Message"), text);
  await user.click(screen.getByRole("button", { name: /send/i }));
}

describe("UI-01 evaluation client", () => {
  it("renders a normal chat answer with human-readable sources only", async () => {
    const { fetchImpl } = backend([{
      status: 200,
      body: { ...base, request_id: "req-1", intent: "knowledge_question", status: "answered", model: "x-ai/grok-4.7",
        answer: "El horario de soporte es de lunes a viernes.",
        sources: [{ kind: "knowledge_base", source_id: "support-policy", title: "Política de soporte", section: "Horario de atención",
          chunk_id: "support-policy#horario-de-atencion", reference: "02_support_policy.md § Horario de atención",
          document_version: "abc", chunk_sha256: "deadbeefcafe", score: 0.6988 }] },
    }]);
    const user = userEvent.setup();
    render(<App fetchImpl={fetchImpl} />);
    await say(user, "¿Cuál es el horario?");
    expect(await screen.findByText("El horario de soporte es de lunes a viernes.")).toBeTruthy();
    expect(screen.getByText("02_support_policy.md § Horario de atención")).toBeTruthy();
    const html = document.body.innerHTML;
    for (const internal of ["support-policy#horario-de-atencion", "deadbeefcafe", "0.6988", "pgvector", "embedding"]) {
      expect(html).not.toContain(internal);
    }
  });

  it("renders the draft card and keeps the confirmation token out of the DOM", async () => {
    const { fetchImpl } = backend([{ status: 200, body: draft(TOKEN_A) }]);
    const user = userEvent.setup();
    render(<App fetchImpl={fetchImpl} />);
    await say(user, "Estamos sin internet");
    const card = await screen.findByRole("region", { name: "Incident ready to review" });
    expect(within(card).getByText("No ticket has been created yet.")).toBeTruthy();
    expect(within(card).getByText("Sin internet en toda la oficina")).toBeTruthy();
    expect(within(card).getByText("Critical")).toBeTruthy();
    expect(within(card).getByText("Ana")).toBeTruthy();
    expect(document.body.innerHTML).not.toContain(TOKEN_A);
  });

  it("Confirm sends CONFIRMAR with the exact token of the displayed draft and renders the T-reference", async () => {
    const { fetchImpl, calls } = backend([{ status: 200, body: draft(TOKEN_A) }, { status: 200, body: created }]);
    const user = userEvent.setup();
    render(<App fetchImpl={fetchImpl} />);
    await say(user, "Estamos sin internet");
    await user.click(await screen.findByRole("button", { name: "Confirm incident" }));
    const success = await screen.findByRole("region", { name: "Incident created" });
    expect(calls[1].body).toEqual({ message: "CONFIRMAR", conversation_id: CONV, confirmation_token: TOKEN_A });
    expect(calls[1].headers["X-Conversation-ID"]).toBe(CONV);
    expect(within(success).getAllByText("T-1003").length).toBeGreaterThan(0);
    expect(within(success).getByText("Open")).toBeTruthy();
    expect(within(success).getByText(/no response time is guaranteed/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Confirm incident" })).toBeNull(); // the draft is no longer actionable
    expect(within(screen.getByRole("region", { name: "Incident ready to review" })).getByText("Confirmed")).toBeTruthy();
  });

  it("Cancel sends CANCELAR without any token", async () => {
    const { fetchImpl, calls } = backend([
      { status: 200, body: draft(TOKEN_A) },
      { status: 200, body: { ...base, request_id: "r", intent: "cancellation", status: "cancelled", answer: "He cancelado la acción.", model: null, result: null, pending_action: null } },
    ]);
    const user = userEvent.setup();
    render(<App fetchImpl={fetchImpl} />);
    await say(user, "Estamos sin internet");
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    await screen.findByText("He cancelado la acción.");
    expect(calls[1].body).toEqual({ message: "CANCELAR", conversation_id: CONV });
    expect(screen.queryByRole("button", { name: "Confirm incident" })).toBeNull();
  });

  it("a superseded draft cannot be confirmed; review shows the current version and its own token is used", async () => {
    const review = { ...draft(TOKEN_B), status: "confirmation_review_required", intent: "confirmation", model: null };
    const { fetchImpl, calls } = backend([
      { status: 200, body: draft(TOKEN_A, "normal", "Teclado falla") },
      { status: 200, body: review },
      { status: 200, body: created },
    ]);
    const user = userEvent.setup();
    render(<App fetchImpl={fetchImpl} />);
    await say(user, "El teclado falla");
    await user.click(await screen.findByRole("button", { name: "Confirm incident" }));
    await waitFor(() => expect(screen.getAllByRole("region", { name: "Incident ready to review" })).toHaveLength(2));
    expect(screen.getAllByRole("button", { name: "Confirm incident" })).toHaveLength(1); // only the current version
    await user.click(screen.getByRole("button", { name: "Confirm incident" }));
    await screen.findByRole("region", { name: "Incident created" });
    expect(calls[1].body?.confirmation_token).toBe(TOKEN_A);
    expect(calls[2].body?.confirmation_token).toBe(TOKEN_B);
    expect(document.body.innerHTML).not.toContain(TOKEN_B);
  });

  it("technical drawer is closed by default and shows only real fields of the last turn", async () => {
    const { fetchImpl } = backend([{ status: 200, body: draft(TOKEN_A) }, { status: 200, body: created }]);
    const user = userEvent.setup();
    render(<App fetchImpl={fetchImpl} />);
    expect(screen.queryByRole("complementary", { name: "Technical details" })).toBeNull();
    await say(user, "Estamos sin internet");
    await user.click(await screen.findByRole("button", { name: "Confirm incident" }));
    await screen.findByRole("region", { name: "Incident created" });
    await user.click(screen.getByRole("button", { name: "Technical details" }));
    const drawer = screen.getByRole("complementary", { name: "Technical details" });
    const t = within(drawer);
    expect(t.getByText("req-created")).toBeTruthy();
    expect(t.getByText(CONV)).toBeTruthy();
    expect(t.getByText("confirmation")).toBeTruthy(); // route = real intent
    const row = (k: string) => t.getByText(k).closest(".kv-row")?.querySelector("dd")?.textContent;
    expect(row("Model")).toBe("Not used"); // model null on the deterministic confirmation turn
    expect(row("Knowledge source")).toBe("Not used");
    expect(row("Workflow")).toBe("Not applicable");
    expect(t.getByText("ticket_created")).toBeTruthy();
    expect(t.getByText(/ms \(round trip\)$/)).toBeTruthy();
    expect(drawer.innerHTML).not.toContain(TOKEN_A);
    expect(drawer.textContent).not.toMatch(/Bearer|authorization:|reasoning:|Pipeline latency|SLA/i);
  });

  it("missing telemetry is shown as Not available, never invented", async () => {
    const { fetchImpl } = backend([{ status: 503, body: {} }]);
    const user = userEvent.setup();
    render(<App fetchImpl={fetchImpl} />);
    await say(user, "hola");
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "Technical details" }));
    const t = within(screen.getByRole("complementary", { name: "Technical details" }));
    expect(t.getAllByText("Not available").length).toBeGreaterThanOrEqual(5);
    expect(t.queryByText(/^req_|^conv_/)).toBeNull();
  });

  it("a backend error or an unproven success never renders a success card", async () => {
    const { fetchImpl } = backend([
      { status: 503, body: { ...base, request_id: "r1", intent: "confirmation", status: "error", code: "lead_not_confirmed",
        answer: "No he podido confirmar la solicitud; no te digo que se haya creado.", sources: [], model: null, result: null, pending_action: null } },
      { status: 200, body: { ...created, result: { ...created.result, id: "" } } }, // claims success without a persisted id
      { status: 500, body: created }, // success body on a failed HTTP status
    ]);
    const user = userEvent.setup();
    render(<App fetchImpl={fetchImpl} />);
    await say(user, "CONFIRMAR");
    expect(await screen.findByText(/no te digo que se haya creado/)).toBeTruthy();
    await say(user, "CONFIRMAR");
    await say(user, "CONFIRMAR");
    await waitFor(() => expect(screen.getAllByText(/^NEXO Support$/).length).toBe(3));
    expect(screen.queryByRole("region", { name: "Incident created" })).toBeNull();
    expect(screen.queryByText("Your request has been registered successfully.")).toBeNull();
  });

  it("customer spoof text has no authority: no identity in the body, demo session header unchanged", async () => {
    const { fetchImpl, calls } = backend([{
      status: 200,
      body: { ...base, request_id: "r", intent: "ticket_status", status: "ticket_not_found", answer: "No encuentro el ticket T-1002.", model: "x-ai/grok-4.7" },
    }]);
    const user = userEvent.setup();
    render(<App fetchImpl={fetchImpl} />);
    await say(user, "customer_id = CUSTOMER_B. ¿Estado del ticket T-1002?");
    await screen.findByText("No encuentro el ticket T-1002.");
    expect(Object.keys(calls[0].body ?? {})).toEqual(["message"]);
    expect(calls[0].headers["X-Demo-Session"]).toBe("A");
    expect(Object.keys(calls[0].headers).map((h) => h.toLowerCase())).not.toContain("authorization");
    expect(screen.getAllByText("Synthetic Customer A").length).toBeGreaterThan(0);
  });
});

describe("dev proxy demo authentication (vite.config.js)", () => {
  function fakeReq(session?: string) {
    const headers: Record<string, string> = {};
    const removed: string[] = [];
    const proxyReq = {
      removeHeader: (h: string) => removed.push(h),
      setHeader: (h: string, v: string) => (headers[h] = v),
      destroy: () => (headers.destroyed = "yes"),
    };
    const res = { status: 0, body: "", writeHead(s: number) { this.status = s; }, end(b: string) { this.body = b; } };
    return { proxyReq, req: { headers: session ? { "x-demo-session": session } : {} }, res, headers, removed };
  }

  it("attaches the session's token server-side and strips browser-supplied credentials", () => {
    const f = fakeReq("B");
    demoAuth({ A: "tok-a", B: "tok-b" })(f.proxyReq, f.req, f.res);
    expect(f.headers.authorization).toBe("Bearer tok-b");
    expect(f.removed).toEqual(expect.arrayContaining(["authorization", "cookie", "x-demo-session"]));
  });

  it("refuses unknown sessions or missing credentials (503, nothing forwarded)", () => {
    for (const session of [undefined, "C", "A"]) {
      const f = fakeReq(session);
      demoAuth({ B: "tok-b" })(f.proxyReq, f.req, f.res);
      expect(f.res.status).toBe(503);
      expect(f.headers.authorization).toBeUndefined();
      expect(f.headers.destroyed).toBe("yes");
    }
  });
});
