import type { ChatTurn, Source } from "../api";
import { CloseIcon, ShieldIcon, SlidersIcon } from "./Icons";

const NA = "Not available";
const PLACEHOLDERS = new Set([NA, "Not used", "Not applicable"]);

const HTTP_TEXT: Record<number, string> = { 200: "OK", 400: "Bad Request", 401: "Unauthorized", 422: "Unprocessable", 503: "Unavailable" };

function knowledge(sources: Source[] | undefined): string {
  const list = sources ?? [];
  if (list.length === 0) return "Not used";
  return list
    .map((s) => (s.kind === "knowledge_base" ? s.reference ?? s.title : s.kind === "business_api" ? "Business API (ticket)" : null))
    .filter(Boolean)
    .join("; ");
}

/**
 * Evaluator view of the LAST turn, built only from the real /chat response (+ the client-measured round trip).
 * Never shows tokens, headers, credentials or model reasoning: none of them exist in this data.
 */
export function TechnicalDrawer({ turn, onClose }: { turn: ChatTurn | null; onClose: () => void }) {
  const b = turn?.body;
  const rows: [string, string, string?][] = turn
    ? [
        ["Request ID", b?.request_id ?? NA, "mono"],
        ["Conversation ID", b?.conversation_id ?? NA, "mono"],
        ["Route", b?.intent ?? NA, "chip"],
        // A null model on a 200 turn means the deterministic gate answered (CONFIRMAR / CANCELAR): no model call.
        ["Model", b?.model ?? (turn.httpStatus === 200 && b?.status ? "Not used" : NA), "mono"],
        ["Knowledge source", turn.httpStatus === 200 ? knowledge(b?.sources) : NA],
        [
          "Workflow",
          b?.result?.workflow_execution_id ? `n8n execution ${b.result.workflow_execution_id}` : b?.result?.kind === "lead" ? NA : "Not applicable",
        ],
        ["Duration", `${turn.durationMs} ms (round trip)`, "mono"],
        ["Result", b?.status ?? b?.code ?? NA, "result"],
      ]
    : [];
  const ok = turn ? turn.httpStatus === 200 : false;
  return (
    <aside id="technical-drawer" className="drawer" aria-label="Technical details">
      <header className="drawer-head">
        <span className="drawer-icon">
          <SlidersIcon size={15} />
        </span>
        <span className="drawer-titles">
          <span className="drawer-title">
            Technical details <span className="badge badge-trace">Trace</span>
          </span>
          <span className="drawer-sub">Evaluator execution log</span>
        </span>
        <button type="button" className="icon-btn" aria-label="Close technical details" onClick={onClose}>
          <CloseIcon size={15} />
        </button>
      </header>
      <section className="panel">
        <div className="panel-head">
          <span className="panel-label">Execution status</span>
          {turn && (
            <span className={`badge ${ok ? "badge-ok" : "badge-error"}`}>
              <span className="dot" />
              {turn.httpStatus} {HTTP_TEXT[turn.httpStatus] ?? ""}
            </span>
          )}
        </div>
        {turn ? (
          <dl className="kv">
            {rows.map(([k, v, kind]) => (
              <div key={k} className="kv-row">
                <dt>{k}</dt>
                <dd className={kind && !PLACEHOLDERS.has(v) ? `kv-${kind}${kind === "result" && !ok ? " kv-result-bad" : ""}` : undefined}>{v}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="panel-empty">No request yet. Send a message to see its trace.</p>
        )}
      </section>
      <section className="panel panel-note">
        <ShieldIcon size={15} />
        <div>
          <strong>Data protection</strong>
          <p>
            Sensitive runtime data is not displayed. API credentials, authorization headers and model reasoning are excluded
            from this view.
          </p>
        </div>
      </section>
    </aside>
  );
}
