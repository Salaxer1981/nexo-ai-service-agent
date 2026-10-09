import { isCreated } from "../api";
import type { Source } from "../api";
import type { AgentMessage, Conversation, Message } from "../model";
import { clock, isToday } from "../model";
import { CreatedCard, DraftCard, ErrorCard, HandoffCard } from "./Cards";
import { CheckCircleIcon } from "./Icons";

/** Human-readable references only (never chunk ids, hashes or scores). */
function sourceLabel(s: Source): string | null {
  if (s.kind === "knowledge_base") return s.reference ?? s.title ?? null;
  if (s.kind === "business_api" && s.reference) return `${s.reference} · Ticket record`;
  if (s.kind === "web" && s.domain) return `Web · ${s.domain}`; // plain text: web URLs are never rendered as links
  return null;
}

/** What became of a draft that is no longer actionable, from the first later turn that settled it. */
function draftOutcome(conv: Conversation, msg: AgentMessage): string {
  const later = conv.messages.slice(conv.messages.indexOf(msg) + 1);
  for (const m of later) {
    if (m.role !== "agent") continue;
    const b = m.turn.body;
    if (isCreated(m.turn)) return "Confirmed";
    if (m.turn.httpStatus === 200 && b.status === "cancelled") return "Cancelled";
    if (b.pending_action?.confirmation_token) return "Replaced";
  }
  return "Draft";
}

function AgentBody({
  msg,
  conv,
  busy,
  onConfirm,
  onCancel,
}: {
  msg: AgentMessage;
  conv: Conversation;
  busy: boolean;
  onConfirm: (msg: AgentMessage) => void;
  onCancel: () => void;
}) {
  const { turn } = msg;
  const b = turn.body;
  const created = isCreated(turn);
  const failed = turn.httpStatus !== 200 || b.status === "error";
  const sources = (b.sources ?? []).map(sourceLabel).filter((x): x is string => Boolean(x));
  const draft = b.pending_action && b.pending_action.confirmation_token ? b.pending_action : null;
  const actionable = Boolean(draft && conv.pending && conv.pending.messageId === msg.id);
  const outcome = actionable ? "Draft" : draftOutcome(conv, msg);

  if (failed) {
    const text =
      b.answer ||
      (b.code === "demo_session_unavailable"
        ? "The demo session is not configured on this server."
        : "The service could not complete this request. Please try again in a moment.");
    return <ErrorCard text={text} />;
  }
  return (
    <>
      {b.answer && <p className="agent-text">{b.answer}</p>}
      {draft && (
        <DraftCard
          action={draft}
          actionable={actionable}
          outcome={outcome}
          busy={busy}
          onConfirm={() => onConfirm(msg)}
          onCancel={onCancel}
        />
      )}
      {created && b.result && <CreatedCard result={b.result} />}
      {b.status === "handoff_created" && b.result?.kind === "handoff" && <HandoffCard result={b.result} />}
      {sources.length > 0 && (
        <div className="sources">
          <span className="sources-label">Sources</span>
          {sources.map((s) => (
            <span key={s} className="source-chip">
              {s}
            </span>
          ))}
        </div>
      )}
    </>
  );
}

export function MessageList({
  conv,
  sessionName,
  busy,
  onConfirm,
  onCancel,
}: {
  conv: Conversation;
  sessionName: string;
  busy: boolean;
  onConfirm: (msg: AgentMessage) => void;
  onCancel: () => void;
}) {
  const first = conv.messages[0];
  return (
    <div className="messages">
      {first && (
        <div className="day-divider">
          <span>
            {isToday(first.at) ? "Today" : first.at.toLocaleDateString("en-US", { month: "short", day: "numeric" })} •{" "}
            {clock(first.at)}
          </span>
        </div>
      )}
      {conv.messages.map((m: Message) =>
        m.role === "user" ? (
          <div key={m.id} className="msg">
            <div className="avatar avatar-user">{sessionName.slice(-1)}</div>
            <div className="msg-main">
              <div className="msg-meta">
                <strong>You</strong>
                <span className="sep">•</span>
                <span className="accent">{sessionName}</span>
                <span className="sep">•</span>
                <span>{clock(m.at)}</span>
              </div>
              <div className="bubble">{m.text}</div>
            </div>
          </div>
        ) : (
          <div key={m.id} className="msg">
            {isCreated(m.turn) ? (
              <div className="avatar avatar-ok">
                <CheckCircleIcon size={16} />
              </div>
            ) : (
              <div className="avatar avatar-agent">N</div>
            )}
            <div className="msg-main">
              <div className="msg-meta">
                <strong>NEXO Support</strong>
                <span className="sep">•</span>
                <span>{clock(m.at)}</span>
              </div>
              <AgentBody msg={m} conv={conv} busy={busy} onConfirm={onConfirm} onCancel={onCancel} />
            </div>
          </div>
        ),
      )}
      {busy && (
        <div className="msg" aria-live="polite">
          <div className="avatar avatar-agent">N</div>
          <div className="msg-main">
            <div className="typing">NEXO Support is replying…</div>
          </div>
        </div>
      )}
    </div>
  );
}
