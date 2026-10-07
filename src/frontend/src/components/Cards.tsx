import type { ActionResult, LeadSummary, PendingAction, TicketSummary } from "../api";
import { PRIORITY_LABEL, STATUS_LABEL, label } from "../model";
import { AlertIcon, CheckCircleIcon, ClipboardIcon, HandIcon, InfoIcon } from "./Icons";

function Field({ name, value, tone }: { name: string; value: string; tone?: "critical" | "ok" | "normal" }) {
  return (
    <div className="field">
      <div className="field-label">{name}</div>
      <div className={`field-value${tone ? ` tone-${tone}` : ""}`} title={value}>
        {tone && <span className="dot" />}
        {value}
      </div>
    </div>
  );
}

const priorityTone = (p?: string) => (p === "critical" ? "critical" : "normal");

/** Amber draft card (Stitch "INCIDENT READY TO REVIEW"). The confirmation token is NOT rendered anywhere. */
export function DraftCard({
  action,
  actionable,
  outcome,
  busy,
  onConfirm,
  onCancel,
}: {
  action: PendingAction;
  actionable: boolean;
  outcome: string;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const isTicket = action.kind === "ticket";
  const t = action.summary as TicketSummary;
  const l = action.summary as LeadSummary;
  return (
    <section className="card card-draft" aria-label={isTicket ? "Incident ready to review" : "Request ready to review"}>
      <header className="card-head">
        <span className="card-title">
          <ClipboardIcon size={15} />
          {isTicket ? "Incident ready to review" : "Request ready to review"}
        </span>
        <span className="badge badge-draft">{outcome}</span>
      </header>
      <div className="notice">
        <InfoIcon size={14} />
        <span>
          <strong>Notice:</strong> {isTicket ? "No ticket has been created yet." : "No request has been registered yet."}
        </span>
      </div>
      {isTicket ? (
        <div className="fields fields-4">
          <Field name="Issue" value={t.subject} />
          <Field name="Impact" value={t.description} />
          <Field name="Priority" value={label(PRIORITY_LABEL, t.priority)} tone={priorityTone(t.priority)} />
          <Field name="Reported by" value={t.contact_name} />
        </div>
      ) : (
        <div className="fields fields-4">
          <Field name="Company" value={l.company_name} />
          <Field name="Contact" value={l.contact_name} />
          <Field name="Email" value={l.contact_email} />
          <Field name="Need" value={l.need} />
        </div>
      )}
      {actionable && (
        <footer className="card-actions">
          <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" onClick={onConfirm} disabled={busy}>
            <CheckCircleIcon size={14} />
            {isTicket ? "Confirm incident" : "Confirm request"}
          </button>
        </footer>
      )}
    </section>
  );
}

/** Green success card. Rendered only for an authoritative persisted result (see api.isCreated). */
export function CreatedCard({ result }: { result: ActionResult }) {
  if (result.kind === "ticket") {
    return (
      <section className="card card-success" aria-label="Incident created">
        <header className="card-head">
          <span className="card-title">
            <CheckCircleIcon size={15} />
            Incident created
          </span>
          <span className="badge badge-ref">{result.reference}</span>
        </header>
        <div className="fields fields-3">
          <Field name="Ticket" value={result.reference ?? "Not available"} />
          <Field name="Priority" value={label(PRIORITY_LABEL, result.priority)} tone={priorityTone(result.priority)} />
          <Field name="Status" value={label(STATUS_LABEL, result.status)} tone="ok" />
        </div>
        {result.handoff && (
          <div className="handoff-row">
            <span className="badge badge-pending">
              <span className="dot" />
              Pending
            </span>
            <span>Escalated to a person. It is waiting for human attention; no response time is guaranteed.</span>
          </div>
        )}
        <footer className="card-foot">
          <span className="muted">
            {result.idempotency === "replay" ? "This request was already registered." : "Your request has been registered successfully."}
          </span>
        </footer>
      </section>
    );
  }
  return (
    <section className="card card-success" aria-label="Request registered">
      <header className="card-head">
        <span className="card-title">
          <CheckCircleIcon size={15} />
          Request registered
        </span>
      </header>
      <div className="fields fields-1">
        <Field name="Status" value="Registered for follow-up" tone="ok" />
      </div>
      {result.status_message && (
        <footer className="card-foot">
          <span className="muted">{result.status_message}</span>
        </footer>
      )}
    </section>
  );
}

export function HandoffCard({ result }: { result: ActionResult }) {
  const reason = result.reason === "unsafe_to_resolve" ? "Needs a person to handle it safely" : "You asked to talk to a person";
  return (
    <section className="card card-neutral" aria-label="Escalated to a person">
      <header className="card-head">
        <span className="card-title">
          <HandIcon size={15} />
          Escalated to a person
        </span>
        <span className="badge badge-pending">
          <span className="dot" />
          {label(STATUS_LABEL, result.status)}
        </span>
      </header>
      <div className="card-body muted">{reason}. Nobody has picked it up yet and no response time is guaranteed.</div>
    </section>
  );
}

export function ErrorCard({ text }: { text: string }) {
  return (
    <section className="card card-error" role="alert">
      <header className="card-head">
        <span className="card-title">
          <AlertIcon size={15} />
          Not completed
        </span>
      </header>
      <div className="card-body">{text}</div>
    </section>
  );
}
