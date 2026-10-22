import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  type ChatMessage,
  type ChatToolCall,
  type Conversation,
  type KnowledgeKind,
} from "../lib/api";
import { streamChat } from "../lib/chatStream";

/** The in-product assistant. Replaces the old KnowledgeChat widget, which
 * looked like a chat but only filed knowledge snippets and replied with a
 * canned acknowledgement. This one actually answers questions by querying the
 * owner's own data (see backend/app/chat/).
 *
 * Two things are deliberate in the UI:
 *
 * - **Tool calls are shown, not hidden.** "12 customers are at risk" is only
 *   trustworthy if the interface can say where the 12 came from, so every
 *   answer lists what it read. That's also why a `fallback` answer is labelled:
 *   the owner should know when they're getting the reduced, no-model version.
 * - **A drafted campaign links straight to its review screen.** The assistant
 *   can queue outreach but never send it, so the useful next step is always
 *   "go look at what it wrote".
 */

const KIND_OPTIONS: { value: KnowledgeKind; label: string }[] = [
  { value: "brand_voice", label: "Brand voice" },
  { value: "service", label: "Service / product" },
  { value: "campaign_example", label: "Past campaign that worked" },
  { value: "note", label: "General note" },
];

type Mode = "ask" | "teach";

interface PendingTool extends ChatToolCall {
  key: string;
}

export default function AskChurnary() {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("ask");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [showThreads, setShowThreads] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);
  const [status, setStatus] = useState<string>("");
  const [liveTools, setLiveTools] = useState<PendingTool[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [draftedCampaign, setDraftedCampaign] = useState<string | null>(null);

  // Knowledge ("teach") mode state.
  const [kind, setKind] = useState<KnowledgeKind>("brand_voice");
  const [taught, setTaught] = useState<string[]>([]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!open || suggestions.length) return;
    api
      .chatSuggestions()
      .then((r) => setSuggestions(r.suggestions))
      .catch(() => setSuggestions([]));
  }, [open, suggestions.length]);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, thinking, liveTools, taught]);

  // Abandoning a turn (closing the panel, unmounting) should stop the request
  // rather than leave it streaming into nothing.
  useEffect(() => () => abortRef.current?.abort(), []);

  const loadThreads = useCallback(() => {
    api
      .conversations()
      .then(setConversations)
      .catch(() => setConversations([]));
  }, []);

  async function ask(question: string) {
    const text = question.trim();
    if (!text || thinking) return;

    setDraft("");
    setError(null);
    setDraftedCampaign(null);
    setLiveTools([]);
    setStatus("");
    setThinking(true);
    // Shown immediately with a temporary id; the server's persisted copy
    // arrives with the answer and the thread is reloaded from it.
    setMessages((prev) => [
      ...prev,
      {
        id: `local-${Date.now()}`,
        role: "user",
        content: text,
        tool_calls: [],
        generated_by: "owner",
        model: null,
        created_at: new Date().toISOString(),
      },
    ]);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamChat(
        { message: text, conversationId },
        {
          onStatus: setStatus,
          onTool: (tool, summary) =>
            setLiveTools((prev) => [...prev, { tool, summary, key: `${tool}-${prev.length}` }]),
          onMessage: (payload) => {
            setConversationId(payload.conversation_id);
            setMessages((prev) => [...prev, payload.message]);
            setDraftedCampaign(payload.drafted_campaign_id);
            loadThreads();
          },
          onError: setError,
        },
        controller.signal
      );
    } catch (e) {
      if (!controller.signal.aborted) {
        setError(e instanceof Error ? e.message : "Couldn't reach the assistant.");
      }
    } finally {
      setThinking(false);
      setStatus("");
      setLiveTools([]);
    }
  }

  async function teach() {
    const content = draft.trim();
    if (!content || thinking) return;
    setThinking(true);
    setError(null);
    try {
      await api.addKnowledge(kind, content);
      setTaught((prev) => [...prev, content]);
      setDraft("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that.");
    } finally {
      setThinking(false);
    }
  }

  function newThread() {
    abortRef.current?.abort();
    setConversationId(null);
    setMessages([]);
    setDraftedCampaign(null);
    setError(null);
    setShowThreads(false);
  }

  async function openThread(id: string) {
    setShowThreads(false);
    setError(null);
    try {
      const detail = await api.conversation(id);
      setConversationId(detail.id);
      setMessages(detail.messages);
      setDraftedCampaign(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't open that conversation.");
    }
  }

  const submit = () => (mode === "ask" ? ask(draft) : teach());

  return (
    <>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "Close the assistant" : "Ask Churnary"}
        className="fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full text-white shadow-lg transition hover:-translate-y-0.5"
        style={{ background: "var(--accent)", boxShadow: "0 8px 20px -6px rgba(180,83,42,.6)" }}
      >
        {open ? <CloseIcon /> : <ChatIcon />}
      </button>

      {open && (
        <div
          className="glass-strong animate-fade-in fixed bottom-24 right-6 z-40 flex w-[26rem] max-w-[calc(100vw-3rem)] flex-col overflow-hidden rounded-2xl shadow-xl"
          style={{ maxHeight: "76vh" }}
        >
          <div
            className="flex items-start justify-between gap-2 border-b px-4 py-3"
            style={{ borderColor: "var(--border)" }}
          >
            <div>
              <p className="font-display text-sm font-bold" style={{ color: "var(--ink)" }}>
                Ask Churnary
              </p>
              <p className="mt-0.5 text-xs leading-snug" style={{ color: "var(--muted)" }}>
                {mode === "ask"
                  ? "Answers from your own customer data."
                  : "Teach me about your business to personalize campaigns."}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <IconButton
                label="Past conversations"
                onClick={() => {
                  setShowThreads((v) => !v);
                  if (!showThreads) loadThreads();
                }}
              >
                <HistoryIcon />
              </IconButton>
              <IconButton label="New conversation" onClick={newThread}>
                <PlusIcon />
              </IconButton>
            </div>
          </div>

          <div className="flex gap-1 px-4 pt-3">
            {(["ask", "teach"] as Mode[]).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className="rounded-full px-3 py-1 text-[11px] font-semibold transition"
                style={
                  mode === m
                    ? { background: "var(--accent)", color: "#fff" }
                    : { background: "var(--surface-2)", color: "var(--muted)" }
                }
              >
                {m === "ask" ? "Ask" : "Teach"}
              </button>
            ))}
          </div>

          {showThreads && (
            <div
              className="mx-4 mt-3 max-h-40 overflow-y-auto rounded-xl border"
              style={{ borderColor: "var(--border)", background: "var(--surface-2)" }}
            >
              {conversations.length === 0 ? (
                <p className="px-3 py-2 text-xs" style={{ color: "var(--muted-2)" }}>
                  No past conversations yet.
                </p>
              ) : (
                conversations.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => openThread(c.id)}
                    className="block w-full truncate px-3 py-2 text-left text-xs transition hover:bg-black/5"
                    style={{ color: "var(--ink)" }}
                  >
                    {c.title}
                  </button>
                ))
              )}
            </div>
          )}

          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
            {mode === "teach" ? (
              <>
                <Bubble
                  from="assistant"
                  text="Tell me about your brand voice, your best-selling services, or a past win-back message that worked. I'll draw on it when writing campaigns."
                />
                {taught.map((t, i) => (
                  <Bubble key={i} from="user" text={t} />
                ))}
                {taught.length > 0 && (
                  <Bubble from="assistant" text="Got it — saved. Ask me anything whenever you like." />
                )}
              </>
            ) : (
              <>
                {messages.length === 0 && (
                  <>
                    <Bubble
                      from="assistant"
                      text="Ask me who's about to stop coming in, what to send them, or how your win-backs are doing. I read your real customer data — I don't guess."
                    />
                    {suggestions.map((s) => (
                      <button
                        key={s}
                        onClick={() => ask(s)}
                        className="block w-full rounded-xl border px-3 py-2 text-left text-xs transition hover:-translate-y-px"
                        style={{
                          borderColor: "var(--border)",
                          color: "var(--ink)",
                          background: "rgba(255,255,255,.5)",
                        }}
                      >
                        {s}
                      </button>
                    ))}
                  </>
                )}

                {messages.map((m) => (
                  <div key={m.id}>
                    <Bubble from={m.role} text={m.content} />
                    {m.role === "assistant" && m.tool_calls.length > 0 && (
                      <ToolCitations calls={m.tool_calls} />
                    )}
                    {m.role === "assistant" && m.generated_by === "fallback" && (
                      <p className="mt-1 text-[10px]" style={{ color: "var(--muted-2)" }}>
                        Answered without the AI model — reduced mode.
                      </p>
                    )}
                  </div>
                ))}

                {thinking && (
                  <div>
                    <Bubble from="assistant" text={status || "Thinking…"} muted />
                    {liveTools.length > 0 && <ToolCitations calls={liveTools} />}
                  </div>
                )}

                {draftedCampaign && (
                  <Link
                    to={`/campaigns/${draftedCampaign}`}
                    onClick={() => setOpen(false)}
                    className="block rounded-xl px-3 py-2 text-xs font-semibold text-white transition hover:-translate-y-px"
                    style={{ background: "var(--accent)" }}
                  >
                    Review the drafted messages →
                  </Link>
                )}
              </>
            )}
          </div>

          {error && (
            <p className="px-4 pb-1 text-xs" style={{ color: "var(--accent-dark)" }}>
              {error}
            </p>
          )}

          <div className="border-t p-3" style={{ borderColor: "var(--border)" }}>
            {mode === "teach" && (
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
            )}
            <div className="flex items-end gap-2">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    submit();
                  }
                }}
                placeholder={
                  mode === "ask"
                    ? "Who's about to stop coming in?"
                    : "e.g. Always sign off with 'stay caffeinated!'"
                }
                rows={2}
                className="flex-1 resize-none rounded-xl border bg-white/70 px-3 py-2 text-sm outline-none focus:border-[#B4532A]"
                style={{ borderColor: "var(--border)", color: "var(--ink)" }}
              />
              <button
                onClick={submit}
                disabled={!draft.trim() || thinking}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-white transition disabled:opacity-40"
                style={{ background: "var(--accent)" }}
                aria-label={mode === "ask" ? "Ask" : "Save"}
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

function Bubble({
  from,
  text,
  muted,
}: {
  from: "user" | "assistant";
  text: string;
  muted?: boolean;
}) {
  if (from === "user") {
    return (
      <div
        className="ml-auto max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm px-3 py-2 text-xs leading-relaxed text-white"
        style={{ background: "var(--accent)" }}
      >
        {text}
      </div>
    );
  }
  return (
    <div
      className="max-w-[90%] whitespace-pre-wrap rounded-2xl rounded-bl-sm px-3 py-2 text-xs leading-relaxed"
      style={{
        background: "var(--surface-2)",
        color: muted ? "var(--muted-2)" : "var(--ink)",
      }}
    >
      {text}
    </div>
  );
}

/** What the assistant actually read, under the answer it produced. The point
 * is auditability: a number with no visible source is a number to distrust. */
function ToolCitations({ calls }: { calls: ChatToolCall[] }) {
  return (
    <ul className="mt-1 space-y-0.5 pl-1">
      {calls.map((c, i) => (
        <li
          key={`${c.tool}-${i}`}
          className="flex items-start gap-1.5 text-[10px] leading-snug"
          style={{ color: "var(--muted-2)" }}
        >
          <span aria-hidden="true">·</span>
          <span>{c.summary || c.tool}</span>
        </li>
      ))}
    </ul>
  );
}

function IconButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      title={label}
      className="flex h-7 w-7 items-center justify-center rounded-lg transition hover:bg-black/5"
      style={{ color: "var(--muted)" }}
    >
      {children}
    </button>
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

function HistoryIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 3v5h5" />
      <path d="M3.05 13A9 9 0 1 0 6 5.3L3 8" />
      <path d="M12 7v5l4 2" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}
