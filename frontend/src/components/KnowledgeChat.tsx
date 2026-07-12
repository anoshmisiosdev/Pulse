import { useEffect, useRef, useState } from "react";
import { api, type KnowledgeItem, type KnowledgeKind } from "../lib/api";

const KIND_OPTIONS: { value: KnowledgeKind; label: string }[] = [
  { value: "brand_voice", label: "Brand voice" },
  { value: "service", label: "Service / product" },
  { value: "campaign_example", label: "Past campaign that worked" },
  { value: "note", label: "General note" },
];

const KIND_LABEL: Record<KnowledgeKind, string> = Object.fromEntries(
  KIND_OPTIONS.map((o) => [o.value, o.label])
) as Record<KnowledgeKind, string>;

type ChatEntry =
  | { role: "assistant"; text: string }
  | { role: "user"; item: KnowledgeItem };

const INTRO =
  "Tell me about your business — your brand voice, best-selling services, or a past win-back message that worked well. I'll use it to personalize the AI-written campaigns.";

/** Floating chat button (bottom-right) for teaching the campaign-personalization
 * RAG about this business. Each message sent here is stored as a knowledge
 * snippet (app/services/rag/) and retrieved into future campaign generation. */
export default function KnowledgeChat() {
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [kind, setKind] = useState<KnowledgeKind>("brand_voice");
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || loaded) return;
    api
      .listKnowledge()
      .then((items) => {
        // Oldest first, so the chat reads top-to-bottom like a real transcript.
        const sorted = [...items].sort((a, b) => a.created_at.localeCompare(b.created_at));
        setEntries(sorted.map((item) => ({ role: "user", item })));
        setLoaded(true);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load"));
  }, [open, loaded]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [entries, sending]);

  async function send() {
    const content = draft.trim();
    if (!content || sending) return;
    setSending(true);
    setError(null);
    try {
      const item = await api.addKnowledge(kind, content);
      setEntries((prev) => [
        ...prev,
        { role: "user", item },
        { role: "assistant", text: `Got it — filed under "${KIND_LABEL[kind]}". I'll draw on this next time I write a campaign for you.` },
      ]);
      setDraft("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that");
    } finally {
      setSending(false);
    }
  }

  async function remove(item: KnowledgeItem) {
    setEntries((prev) => prev.filter((e) => !(e.role === "user" && e.item.id === item.id)));
    try {
      await api.deleteKnowledge(item.id);
    } catch {
      // Not critical enough to resurrect the row over — a stale entry is
      // harmless and the next open() reload will reconcile it.
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "Close campaign knowledge chat" : "Teach Churnary about your business"}
        className="fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full text-white shadow-lg transition hover:-translate-y-0.5"
        style={{ background: "var(--accent)", boxShadow: "0 8px 20px -6px rgba(180,83,42,.6)" }}
      >
        {open ? <CloseIcon /> : <ChatIcon />}
      </button>

      {open && (
        <div
          className="glass-strong fixed bottom-24 right-6 z-40 flex w-[22rem] max-w-[calc(100vw-3rem)] flex-col overflow-hidden rounded-2xl shadow-xl animate-fade-in"
          style={{ maxHeight: "70vh" }}
        >
          <div className="border-b px-4 py-3" style={{ borderColor: "var(--border)" }}>
            <p className="font-display text-sm font-bold" style={{ color: "var(--ink)" }}>
              Teach Churnary about your business
            </p>
            <p className="mt-0.5 text-xs leading-snug" style={{ color: "var(--muted)" }}>
              Personalizes AI-written win-back campaigns.
            </p>
          </div>

          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
            <AssistantBubble text={INTRO} />
            {entries.map((e, i) =>
              e.role === "assistant" ? (
                <AssistantBubble key={i} text={e.text} />
              ) : (
                <UserBubble key={e.item.id} item={e.item} onDelete={() => remove(e.item)} />
              )
            )}
            {sending && <AssistantBubble text="Saving…" muted />}
          </div>

          {error && (
            <p className="px-4 pb-1 text-xs" style={{ color: "var(--accent-dark)" }}>
              {error}
            </p>
          )}

          <div className="border-t p-3" style={{ borderColor: "var(--border)" }}>
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as KnowledgeKind)}
              className="mb-2 w-full rounded-lg border bg-white/70 px-2.5 py-1.5 text-xs outline-none"
              style={{ borderColor: "var(--border)", color: "var(--ink)" }}
            >
              {KIND_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <div className="flex items-end gap-2">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
                placeholder="e.g. Always sign off with 'stay caffeinated!'"
                rows={2}
                className="flex-1 resize-none rounded-xl border bg-white/70 px-3 py-2 text-sm outline-none focus:border-[#B4532A]"
                style={{ borderColor: "var(--border)", color: "var(--ink)" }}
              />
              <button
                onClick={send}
                disabled={!draft.trim() || sending}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-white transition disabled:opacity-40"
                style={{ background: "var(--accent)" }}
                aria-label="Send"
              >
                <SendIcon />
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function AssistantBubble({ text, muted }: { text: string; muted?: boolean }) {
  return (
    <div
      className="max-w-[85%] rounded-2xl rounded-bl-sm px-3 py-2 text-xs leading-relaxed"
      style={{ background: "var(--surface-2)", color: muted ? "var(--muted-2)" : "var(--ink)" }}
    >
      {text}
    </div>
  );
}

function UserBubble({ item, onDelete }: { item: KnowledgeItem; onDelete: () => void }) {
  return (
    <div className="ml-auto max-w-[85%]">
      <div
        className="group relative rounded-2xl rounded-br-sm px-3 py-2 text-xs leading-relaxed text-white"
        style={{ background: "var(--accent)" }}
      >
        {item.content}
        <button
          onClick={onDelete}
          aria-label="Remove"
          className="absolute -left-2 -top-2 hidden h-5 w-5 items-center justify-center rounded-full bg-white text-[10px] shadow group-hover:flex"
          style={{ color: "var(--muted)" }}
        >
          ✕
        </button>
      </div>
      <p className="mt-1 text-right text-[10px]" style={{ color: "var(--muted-2)" }}>
        {KIND_LABEL[item.kind]}
      </p>
    </div>
  );
}

function ChatIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  );
}
