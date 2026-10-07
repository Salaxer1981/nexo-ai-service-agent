// TEST-ONLY fixture backend for UI visual checks (UI-01). NOT the Nexo backend: no model, no database, no n8n.
// It answers /health/ready and /chat on 127.0.0.1 with fixed responses shaped like the real /chat contract
// (src/backend/app/main.py), so draft / created / error states can be compared with the Stitch references.
// Usage:  node scripts/fixture-backend.mjs   then   AUTH_TOKEN_CUSTOMER_A=fixture AUTH_TOKEN_CUSTOMER_B=fixture npm run dev
import { createServer } from "node:http";
import { randomUUID } from "node:crypto";

const PORT = Number(process.env.FIXTURE_PORT || 8000);
const TOKEN = "7c31a734c4f2d27c"; // fixed TEST token: the real one is computed by the backend
const send = (res, status, body) => {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
};

createServer((req, res) => {
  if (req.url === "/health/ready") return send(res, 200, { status: "ready", database: "ok", schema_version: "fixture" });
  if (req.url !== "/chat" || req.method !== "POST") return send(res, 404, { detail: "Not Found" });
  if (!String(req.headers.authorization || "").startsWith("Bearer ")) return send(res, 401, { detail: "unauthenticated" });
  let raw = "";
  req.on("data", (c) => (raw += c));
  req.on("end", () => {
    const body = JSON.parse(raw || "{}");
    const env = { conversation_id: body.conversation_id || randomUUID(), request_id: randomUUID(), sources: [], next_step: null };
    const msg = String(body.message || "");
    if (msg === "CONFIRMAR") {
      if (body.confirmation_token !== TOKEN) {
        return send(res, 200, { ...env, intent: "confirmation", status: "nothing_pending", answer: "No hay ninguna acción pendiente.", model: null, result: null, pending_action: null });
      }
      return send(res, 200, {
        ...env, intent: "confirmation", status: "ticket_created", model: null, pending_action: null,
        answer: "He creado el ticket: T-1003, prioridad crítica, estado «abierto». Queda pendiente de atención humana; no se garantiza un plazo.",
        result: { kind: "ticket", id: randomUUID(), reference: "T-1003", status: "open", priority: "critical", idempotency: "created",
          handoff: { id: randomUUID(), reason: "critical_incident", status: "pending" } },
      });
    }
    if (msg === "CANCELAR") {
      return send(res, 200, { ...env, intent: "cancellation", status: "cancelled", answer: "He cancelado la acción pendiente.", model: null, result: null, pending_action: null });
    }
    if (/error/i.test(msg)) {
      return send(res, 503, { ...env, intent: null, status: "error", code: "llm_unavailable", answer: null });
    }
    return send(res, 200, {
      ...env, intent: "create_ticket", status: "awaiting_confirmation", model: "x-ai/grok-4.7", result: null,
      answer: "He preparado este ticket. Revísalo y confírmalo para que nuestro equipo de soporte pueda actuar.",
      pending_action: { kind: "ticket", confirmation_token: TOKEN,
        summary: { contact_name: "Ana", subject: "Sin conexión a internet", description: "Toda la oficina", priority: "critical" } },
    });
  });
}).listen(PORT, "127.0.0.1", () => process.stdout.write(`TEST fixture backend on 127.0.0.1:${PORT}\n`));
