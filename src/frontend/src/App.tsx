import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { backendReady, sendChat } from "./api";
import type { DemoSession } from "./api";
import { Composer, SESSION_NAME, Sidebar, TopBar } from "./components/Chrome";
import { MessageList } from "./components/MessageList";
import { TechnicalDrawer } from "./components/TechnicalDrawer";
import { addAgentTurn, addUserMessage, newConversation } from "./model";
import type { AgentMessage, Conversation } from "./model";

type Store = Record<DemoSession, { list: Conversation[]; active: string }>;

const fresh = () => {
  const c = newConversation();
  return { list: [c], active: c.key };
};

export default function App({ fetchImpl = fetch }: { fetchImpl?: typeof fetch }) {
  const [session, setSession] = useState<DemoSession>("A");
  const [store, setStore] = useState<Store>(() => ({ A: fresh(), B: fresh() }));
  const [drawerOpen, setDrawerOpen] = useState(false); // closed by default (NEXO_UI_FREEZE_01 customer view)
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState<boolean | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const { list, active } = store[session];
  const conv = useMemo(() => list.find((c) => c.key === active) ?? list[0], [list, active]);

  useEffect(() => {
    let live = true;
    backendReady(fetchImpl).then((ok) => live && setReady(ok));
    return () => {
      live = false;
    };
  }, [fetchImpl]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [conv.messages.length, busy]);

  const update = useCallback(
    (key: string, fn: (c: Conversation) => Conversation) =>
      setStore((s) => ({ ...s, [session]: { ...s[session], list: s[session].list.map((c) => (c.key === key ? fn(c) : c)) } })),
    [session],
  );

  const send = useCallback(
    async (message: string, confirmationToken?: string) => {
      const key = conv.key;
      const conversationId = conv.conversationId;
      update(key, (c) => addUserMessage(c, message));
      setBusy(true);
      try {
        const turn = await sendChat(session, { message, conversationId, confirmationToken }, fetchImpl);
        update(key, (c) => addAgentTurn(c, turn));
      } catch {
        update(key, (c) => addAgentTurn(c, { httpStatus: 0, body: { status: "error" }, durationMs: 0 }));
      } finally {
        setBusy(false);
      }
    },
    [conv.key, conv.conversationId, session, update, fetchImpl],
  );

  // Confirm executes ONLY the draft that is displayed and still current: its own token, echoed unchanged.
  const confirm = (msg: AgentMessage) => {
    const token = msg.turn.body.pending_action?.confirmation_token;
    if (!token || !conv.pending || conv.pending.messageId !== msg.id) return;
    void send("CONFIRMAR", token);
  };
  const cancel = () => void send("CANCELAR");

  const startNew = () => {
    const c = newConversation();
    setStore((s) => ({ ...s, [session]: { list: [c, ...s[session].list.filter((x) => x.messages.length > 0)], active: c.key } }));
    setSidebarOpen(false);
  };

  return (
    <div className={`app${drawerOpen ? " with-drawer" : ""}`}>
      <Sidebar
        conversations={list}
        activeKey={conv.key}
        session={session}
        open={sidebarOpen}
        onSelect={(key) => {
          setStore((s) => ({ ...s, [session]: { ...s[session], active: key } }));
          setSidebarOpen(false);
        }}
        onNew={startNew}
        onSwitchSession={(s) => {
          setSession(s);
          setSidebarOpen(false);
        }}
      />
      <main className="main">
        <TopBar
          title={conv.messages.length ? conv.title : "New conversation"}
          reference={conv.lastTicketReference}
          ready={ready}
          drawerOpen={drawerOpen}
          onToggleDrawer={() => setDrawerOpen((o) => !o)}
          onToggleSidebar={() => setSidebarOpen((o) => !o)}
        />
        <div className="scroll" ref={scrollRef}>
          <div className="column">
            {conv.messages.length === 0 ? (
              <div className="empty">
                <span className="brand-mark brand-mark-lg">N</span>
                <h2>How can we help?</h2>
                <p>Ask about our services, report an incident, check a ticket such as T-1001, or ask to talk to a person.</p>
              </div>
            ) : (
              <MessageList conv={conv} sessionName={SESSION_NAME[session]} busy={busy} onConfirm={confirm} onCancel={cancel} />
            )}
          </div>
        </div>
        <div className="column composer-wrap">
          <Composer busy={busy} onSend={(t) => void send(t)} />
        </div>
      </main>
      {drawerOpen && <TechnicalDrawer turn={conv.lastTurn} onClose={() => setDrawerOpen(false)} />}
    </div>
  );
}
