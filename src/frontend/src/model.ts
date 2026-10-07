import type { ChatTurn, PendingAction } from "./api";

export interface UserMessage {
  id: string;
  role: "user";
  text: string;
  at: Date;
}

export interface AgentMessage {
  id: string;
  role: "agent";
  at: Date;
  turn: ChatTurn;
}

export type Message = UserMessage | AgentMessage;

export interface Conversation {
  key: string; // client-side list key only
  conversationId?: string; // assigned by the backend on the first turn
  title: string;
  createdAt: Date;
  messages: Message[];
  // The draft currently awaiting confirmation: the message that displays it plus its token, kept in memory only.
  pending: { messageId: string; action: PendingAction } | null;
  lastTurn: ChatTurn | null;
  lastTicketReference?: string;
}

// Statuses after which no prepared action is waiting any more (chat_actions.py).
const ENDS_PENDING = new Set(["ticket_created", "lead_created", "cancelled", "nothing_pending", "already_completed", "not_pending"]);

let counter = 0;
export const newId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${(counter++).toString(36)}`;

export function newConversation(): Conversation {
  return { key: newId("c"), title: "New conversation", createdAt: new Date(), messages: [], pending: null, lastTurn: null };
}

export function addUserMessage(conv: Conversation, text: string): Conversation {
  const title = conv.messages.length === 0 ? text.slice(0, 60) : conv.title;
  return { ...conv, title, messages: [...conv.messages, { id: newId("u"), role: "user", text, at: new Date() }] };
}

export function addAgentTurn(conv: Conversation, turn: ChatTurn): Conversation {
  const msg: AgentMessage = { id: newId("a"), role: "agent", at: new Date(), turn };
  const { body } = turn;
  let pending = conv.pending;
  if (body.pending_action && body.pending_action.confirmation_token) {
    pending = { messageId: msg.id, action: body.pending_action };
  } else if (body.status && ENDS_PENDING.has(body.status)) {
    pending = null;
  }
  const ref = turn.httpStatus === 200 && body.status === "ticket_created" ? body.result?.reference : undefined;
  return {
    ...conv,
    conversationId: conv.conversationId ?? body.conversation_id,
    messages: [...conv.messages, msg],
    pending,
    lastTurn: turn,
    lastTicketReference: ref ?? conv.lastTicketReference,
  };
}

export const PRIORITY_LABEL: Record<string, string> = { critical: "Critical", normal: "Normal" };
export const STATUS_LABEL: Record<string, string> = {
  open: "Open",
  in_progress: "In progress",
  resolved: "Resolved",
  closed: "Closed",
  pending: "Pending",
};

export const label = (map: Record<string, string>, value?: string | null) => (value ? map[value] ?? value : "Not available");

export function clock(d: Date): string {
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

export function isToday(d: Date): boolean {
  const n = new Date();
  return d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth() && d.getDate() === n.getDate();
}
