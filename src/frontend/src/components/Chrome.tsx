import { useState } from "react";
import type { KeyboardEvent } from "react";
import type { DemoSession } from "../api";
import type { Conversation } from "../model";
import { clock, isToday } from "../model";
import { DotsIcon, MenuIcon, PlusIcon, SendIcon, SlidersIcon, UserIcon } from "./Icons";

export const SESSION_NAME: Record<DemoSession, string> = { A: "Synthetic Customer A", B: "Synthetic Customer B" };

export function Sidebar({
  conversations,
  activeKey,
  session,
  open,
  onSelect,
  onNew,
  onSwitchSession,
}: {
  conversations: Conversation[];
  activeKey: string;
  session: DemoSession;
  open: boolean;
  onSelect: (key: string) => void;
  onNew: () => void;
  onSwitchSession: (s: DemoSession) => void;
}) {
  const [menu, setMenu] = useState(false);
  const started = conversations.filter((c) => c.messages.length > 0);
  const today = started.filter((c) => isToday(c.createdAt));
  const previous = started.filter((c) => !isToday(c.createdAt));
  const other: DemoSession = session === "A" ? "B" : "A";
  const item = (c: Conversation) => (
    <li key={c.key}>
      <button
        type="button"
        className={`conv${c.key === activeKey ? " active" : ""}`}
        onClick={() => onSelect(c.key)}
        title={c.title}
      >
        <span className="conv-dot" />
        <span className="conv-title">{c.title}</span>
        <span className="conv-time">
          {isToday(c.createdAt) ? clock(c.createdAt) : c.createdAt.toLocaleDateString("en-US", { month: "short", day: "numeric" })}
        </span>
      </button>
    </li>
  );
  return (
    <aside className={`sidebar${open ? " open" : ""}`} aria-label="Conversations">
      <div className="brand">
        <span className="brand-mark">N</span>
        <span className="brand-name">NEXO</span>
        <span className="brand-tag">Support</span>
      </div>
      <button type="button" className="btn btn-primary btn-block" onClick={onNew}>
        <PlusIcon size={15} />
        New conversation
      </button>
      <nav className="conv-list">
        {today.length > 0 && (
          <>
            <div className="group-label">Today</div>
            <ul>{today.map(item)}</ul>
          </>
        )}
        {previous.length > 0 && (
          <>
            <div className="group-label">Previous</div>
            <ul>{previous.map(item)}</ul>
          </>
        )}
      </nav>
      <div className="account">
        <span className="account-icon">
          <UserIcon size={15} />
        </span>
        <span className="account-text">
          <strong>{SESSION_NAME[session]}</strong>
          <span>Demo session {session}</span>
        </span>
        <button type="button" className="icon-btn" aria-label="Session options" onClick={() => setMenu((m) => !m)}>
          <DotsIcon size={16} />
        </button>
        {menu && (
          <div className="account-menu" role="menu">
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenu(false);
                onSwitchSession(other);
              }}
            >
              Switch to {SESSION_NAME[other]}
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}

export function TopBar({
  title,
  reference,
  ready,
  drawerOpen,
  onToggleDrawer,
  onToggleSidebar,
}: {
  title: string;
  reference?: string;
  ready: boolean | null;
  drawerOpen: boolean;
  onToggleDrawer: () => void;
  onToggleSidebar: () => void;
}) {
  return (
    <header className="topbar">
      <button type="button" className="icon-btn only-mobile" aria-label="Conversations" onClick={onToggleSidebar}>
        <MenuIcon />
      </button>
      <h1 className="topbar-title">{title}</h1>
      {reference && <span className="badge badge-ref">{reference}</span>}
      {ready !== null && (
        <span className={`conn ${ready ? "conn-ok" : "conn-down"}`}>
          <span className="dot" />
          {ready ? "Connected" : "Unavailable"}
        </span>
      )}
      <span className="spacer" />
      <button
        type="button"
        className={`btn btn-secondary btn-sm${drawerOpen ? " pressed" : ""}`}
        aria-expanded={drawerOpen}
        aria-controls="technical-drawer"
        onClick={onToggleDrawer}
      >
        <SlidersIcon size={14} />
        Technical details
      </button>
      <span className="avatar-btn" aria-hidden="true">
        <UserIcon size={15} />
      </span>
    </header>
  );
}

export function Composer({ busy, onSend }: { busy: boolean; onSend: (text: string) => void }) {
  const [text, setText] = useState("");
  const submit = () => {
    const t = text.trim();
    if (!t || busy) return;
    onSend(t);
    setText("");
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };
  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <textarea
        aria-label="Message"
        placeholder="Type your message..."
        value={text}
        maxLength={1000}
        rows={2}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
      />
      <div className="composer-bar">
        <span className="spacer" />
        <button type="submit" className="btn btn-primary btn-sm" disabled={busy || !text.trim()}>
          Send
          <SendIcon size={13} />
        </button>
      </div>
    </form>
  );
}
