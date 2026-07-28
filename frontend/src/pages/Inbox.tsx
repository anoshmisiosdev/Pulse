import { useEffect, useMemo, useState } from "react";
import {
  social,
  type Briefing,
  type CommentIntent,
  type ReplyVariant,
  type SocialComment,
} from "../lib/social";

type Filter =
  | "all"
  | "needs_reply"
  | "high_risk"
  | "sales_lead"
  | "product_question"
  | "approved_today"
  | "resolved";

const INTENT_LABELS: Record<CommentIntent, string> = {
  product_question: "Question",
  sales_lead: "Lead",
  complaint: "Complaint",
  praise: "Praise",
  feedback: "Feedback",
  spam: "Spam",
};

const VARIANTS: { id: ReplyVariant; label: string }[] = [
  { id: "standard", label: "Regenerate" },
  { id: "shorter", label: "Shorter" },
  { id: "warmer", label: "Warmer" },
];

function isToday(iso: string): boolean {
  return iso.slice(0, 10) === new Date().toISOString().slice(0, 10);
}

function Pill({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "risk" | "good" }) {
  const palette = {
    muted: { background: "var(--surface-3)", color: "var(--muted)" },
    risk: { background: "#FBEAE4", color: "var(--accent-dark)" },
    good: { background: "#E8F0E3", color: "var(--sage-text)" },
  }[tone];
  return (
    <span className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold" style={palette}>
      {children}
    </span>
  );
}

export default function Inbox() {
  const [comments, setComments] = useState<SocialComment[]>([]);
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [capturing, setCapturing] = useState(false);

  const load = async () => {
    setError(null);
    try {
      const [list, brief] = await Promise.all([social.listInbox(), social.inboxBriefing()]);
      setComments(list.data);
      setBriefing(brief);
      setSelectedId((current) => current ?? list.data[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load your inbox");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const selected = comments.find((c) => c.id === selectedId) ?? null;

  useEffect(() => {
    setDraft(selected?.approved_reply ?? selected?.suggested_reply ?? "");
    setCopied(false);
  }, [selectedId, selected?.suggested_reply, selected?.approved_reply]);

  const counts = useMemo(() => {
    const active = comments.filter((c) => c.status !== "resolved");
    return {
      all: comments.length,
      needs_reply: comments.filter((c) => c.status === "needs_reply" || c.status === "drafted").length,
      high_risk: active.filter((c) => c.risk === "high").length,
      sales_lead: active.filter((c) => c.intent === "sales_lead").length,
      product_question: active.filter((c) => c.intent === "product_question").length,
      approved_today: comments.filter((c) => c.status === "approved" && isToday(c.updated_at)).length,
      resolved: comments.filter((c) => c.status === "resolved").length,
    };
  }, [comments]);

  const visible = useMemo(() => {
    const active = (c: SocialComment) => c.status !== "resolved";
    switch (filter) {
      case "needs_reply":
        return comments.filter((c) => c.status === "needs_reply" || c.status === "drafted");
      case "high_risk":
        return comments.filter((c) => active(c) && c.risk === "high");
      case "sales_lead":
        return comments.filter((c) => active(c) && c.intent === "sales_lead");
      case "product_question":
        return comments.filter((c) => active(c) && c.intent === "product_question");
      case "approved_today":
        return comments.filter((c) => c.status === "approved" && isToday(c.updated_at));
      case "resolved":
        return comments.filter((c) => c.status === "resolved");
      default:
        return comments;
    }
  }, [comments, filter]);

  const run = async (fn: () => Promise<SocialComment>) => {
    setPending(true);
    setError(null);
    try {
      const updated = await fn();
      setComments((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
      setBriefing(await social.inboxBriefing());
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't work");
    } finally {
      setPending(false);
    }
  };

  const copyReply = async () => {
    if (!selected) return;
    try {
      await navigator.clipboard.writeText(selected.approved_reply || draft);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setError("Clipboard unavailable — select the text and copy it manually.");
    }
  };

  if (loading) {
    return (
      <div className="grid place-items-center py-16" style={{ color: "var(--muted)" }}>
        Loading your inbox…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-bold" style={{ color: "var(--ink)" }}>
            Engagement inbox
          </h1>
          <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
            Triage comments on your posts and approve a reply before it goes anywhere.
          </p>
        </div>
        <button
          onClick={() => setCapturing((v) => !v)}
          className="rounded-full px-5 py-2.5 text-sm font-semibold text-white transition hover:brightness-95"
          style={{ background: "var(--accent)" }}
        >
          {capturing ? "Close" : "Capture a comment"}
        </button>
      </header>

      <div
        className="rounded-xl px-4 py-2.5 text-sm"
        style={{ background: "#FDF4E7", color: "#8A6224", border: "1px solid #EFD9B4" }}
      >
        <b>Demo mode.</b> These are sample comments or ones you pasted in yourself. Churnary
        doesn't read from LinkedIn or X, and it never posts a reply for you — you approve the
        text and copy it across.
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-xl px-4 py-2.5 text-sm"
          style={{ background: "#FBEAE4", color: "var(--accent-dark)" }}
        >
          {error}
        </div>
      )}

      {capturing && <CaptureForm onDone={async () => { setCapturing(false); await load(); }} />}

      {briefing && (
        <section className="glass p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-display text-xl font-bold" style={{ color: "var(--ink)" }}>
              Today's opportunities
            </h2>
            <span className="text-xs" style={{ color: "var(--muted-2)" }}>
              <b style={{ color: "var(--sage-text)" }}>{briefing.estimated_minutes_saved} min saved</b>
              {" · "}estimated from triage and drafting
            </span>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {(
              [
                ["sales_lead", "Leads", briefing.leads],
                ["high_risk", "Needs care", briefing.high_risk],
                ["needs_reply", "Awaiting reply", briefing.awaiting_reply],
                ["approved_today", "Approved today", briefing.approved_today],
              ] as [Filter, string, number][]
            ).map(([key, label, value]) => (
              <button
                key={key}
                onClick={() => setFilter(key)}
                className="rounded-xl px-4 py-3 text-left transition hover:brightness-95"
                style={{
                  background: filter === key ? "var(--surface-3)" : "var(--surface-2)",
                  border: "1px solid var(--border)",
                }}
              >
                <div className="font-display text-2xl font-bold" style={{ color: "var(--ink)" }}>
                  {value}
                </div>
                <div className="text-xs font-semibold" style={{ color: "var(--muted)" }}>
                  {label}
                </div>
              </button>
            ))}
          </div>

          <p className="mt-4 text-sm" style={{ color: "var(--ink)" }}>
            {briefing.recommended_action}
          </p>
          {briefing.top_topic && briefing.top_topic_count > 1 && (
            <p className="mt-1 text-xs" style={{ color: "var(--muted-2)" }}>
              People keep asking about <b>{briefing.top_topic}</b> — {briefing.top_topic_count}{" "}
              conversations. Might be worth a post.
            </p>
          )}
        </section>
      )}

      <div className="flex flex-wrap gap-2">
        {(
          [
            ["all", "All"],
            ["needs_reply", "Awaiting reply"],
            ["high_risk", "Needs care"],
            ["sales_lead", "Leads"],
            ["product_question", "Questions"],
            ["approved_today", "Approved today"],
            ["resolved", "Resolved"],
          ] as [Filter, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className="rounded-full px-3.5 py-1.5 text-sm transition"
            style={
              filter === key
                ? { background: "var(--ink-strong)", color: "var(--cream-text)", fontWeight: 700 }
                : { background: "var(--surface-2)", color: "var(--muted)", fontWeight: 600 }
            }
          >
            {label} · {counts[key]}
          </button>
        ))}
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <ul className="space-y-2.5">
          {visible.length === 0 && (
            <li className="glass p-6 text-sm" style={{ color: "var(--muted)" }}>
              Nothing here right now.
            </li>
          )}
          {visible.map((c) => (
            <li key={c.id}>
              <button
                onClick={() => setSelectedId(c.id)}
                className="w-full rounded-2xl p-4 text-left transition hover:brightness-[.98]"
                style={{
                  background: c.id === selectedId ? "var(--surface-3)" : "var(--surface)",
                  border: `1px solid ${c.id === selectedId ? "var(--muted-2)" : "var(--border)"}`,
                }}
              >
                <div className="flex items-center gap-2">
                  <span className="font-semibold" style={{ color: "var(--ink)" }}>
                    {c.author}
                  </span>
                  <Pill tone={c.risk === "high" ? "risk" : "muted"}>{INTENT_LABELS[c.intent]}</Pill>
                  {c.source === "demo" && <Pill>demo</Pill>}
                  {c.status === "approved" && <Pill tone="good">approved</Pill>}
                </div>
                <p className="mt-1.5 line-clamp-2 text-sm" style={{ color: "var(--muted)" }}>
                  {c.comment}
                </p>
              </button>
            </li>
          ))}
        </ul>

        {selected ? (
          <section className="glass h-fit p-6">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-display text-lg font-bold" style={{ color: "var(--ink)" }}>
                {selected.author}
              </h3>
              <Pill>{selected.platform}</Pill>
              <Pill>{selected.source}</Pill>
              {selected.post_url && (
                <a
                  href={selected.post_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs underline"
                  style={{ color: "var(--muted-2)" }}
                >
                  view post
                </a>
              )}
            </div>

            {selected.original_post_excerpt && (
              <p className="mt-2 text-xs italic" style={{ color: "var(--muted-2)" }}>
                on “{selected.original_post_excerpt}”
              </p>
            )}

            <p className="mt-3 text-sm leading-relaxed" style={{ color: "var(--ink)" }}>
              {selected.comment}
            </p>

            <div
              className="mt-4 rounded-xl px-3.5 py-2.5 text-sm"
              style={
                selected.risk === "high"
                  ? { background: "#FBEAE4", color: "var(--accent-dark)" }
                  : { background: "var(--surface-2)", color: "var(--muted)" }
              }
            >
              <b>Recommended:</b> {selected.recommended_action}
            </div>

            {selected.intent === "spam" ? (
              <p
                className="mt-4 rounded-xl px-3.5 py-3 text-sm"
                style={{ background: "var(--surface-2)", color: "var(--muted)" }}
              >
                No reply recommended. Resolve this one as spam.
              </p>
            ) : (
              <>
                <div className="mt-4 flex flex-wrap gap-2">
                  {VARIANTS.map((v) => (
                    <button
                      key={v.id}
                      disabled={pending}
                      onClick={() =>
                        run(() => social.suggestReply(selected.id, v.id))
                      }
                      className="rounded-full px-3.5 py-1.5 text-sm font-semibold transition hover:brightness-95 disabled:opacity-50"
                      style={{ background: "var(--surface-3)", color: "var(--ink-strong)" }}
                    >
                      {v.label}
                    </button>
                  ))}
                </div>

                <textarea
                  aria-label="Suggested reply"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  rows={6}
                  placeholder="Generate a reply, or write your own."
                  className="mt-3 w-full rounded-xl px-3.5 py-3 text-sm"
                  style={{
                    background: "var(--surface-2)",
                    border: "1px solid var(--border)",
                    color: "var(--ink)",
                  }}
                />

                {selected.evidence.length > 0 && (
                  <p className="mt-2 text-xs" style={{ color: "var(--muted-2)" }}>
                    Based on: {selected.evidence.join(" · ")}
                  </p>
                )}
              </>
            )}

            <div className="mt-4 flex flex-wrap gap-2">
              {selected.intent !== "spam" && selected.status !== "resolved" && (
                <button
                  disabled={pending || !draft.trim()}
                  onClick={() =>
                    run(() =>
                      social.updateComment(selected.id, {
                        status: "approved",
                        suggested_reply: draft.trim(),
                      })
                    )
                  }
                  className="rounded-full px-5 py-2.5 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-50"
                  style={{ background: "var(--accent)" }}
                >
                  {selected.status === "approved" ? "Re-approve edited reply" : "Approve reply"}
                </button>
              )}

              <button
                disabled={pending || selected.status !== "approved"}
                onClick={copyReply}
                className="rounded-full border px-5 py-2.5 text-sm font-semibold transition hover:brightness-95 disabled:opacity-40"
                style={{ borderColor: "var(--border)", color: "var(--ink-strong)" }}
              >
                {copied ? "Copied" : "Copy approved reply"}
              </button>

              {selected.status !== "resolved" && (
                <button
                  disabled={pending}
                  onClick={() => run(() => social.updateComment(selected.id, { status: "resolved" }))}
                  className="rounded-full px-5 py-2.5 text-sm font-semibold transition hover:brightness-95 disabled:opacity-50"
                  style={{ background: "var(--surface-3)", color: "var(--muted)" }}
                >
                  Mark resolved
                </button>
              )}
            </div>

            <p className="mt-3 text-xs" style={{ color: "var(--muted-2)" }}>
              Approving keeps the reply here. Paste it into {selected.platform} yourself when
              you're happy with it.
            </p>
          </section>
        ) : (
          <section className="glass grid h-40 place-items-center text-sm" style={{ color: "var(--muted)" }}>
            Pick a conversation to see the draft.
          </section>
        )}
      </div>
    </div>
  );
}

function CaptureForm({ onDone }: { onDone: () => void }) {
  const [platform, setPlatform] = useState("linkedin");
  const [author, setAuthor] = useState("");
  const [comment, setComment] = useState("");
  const [postUrl, setPostUrl] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await social.captureComment({
        platform,
        author: author.trim(),
        comment: comment.trim(),
        post_url: postUrl.trim() || null,
      });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save that comment");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="glass space-y-3 p-6">
      <h2 className="font-display text-lg font-bold" style={{ color: "var(--ink)" }}>
        Capture a comment
      </h2>
      {error && (
        <p className="text-sm" style={{ color: "var(--accent-dark)" }}>
          {error}
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm" style={{ color: "var(--muted)" }}>
          Platform
          <select
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
            className="mt-1 w-full rounded-xl px-3 py-2 text-sm"
            style={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--ink)" }}
          >
            <option value="linkedin">LinkedIn</option>
            <option value="x">X</option>
            <option value="other">Other</option>
          </select>
        </label>
        <label className="text-sm" style={{ color: "var(--muted)" }}>
          Who wrote it
          <input
            value={author}
            onChange={(e) => setAuthor(e.target.value)}
            maxLength={120}
            required
            className="mt-1 w-full rounded-xl px-3 py-2 text-sm"
            style={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--ink)" }}
          />
        </label>
      </div>
      <label className="block text-sm" style={{ color: "var(--muted)" }}>
        Link to the post (optional)
        <input
          type="url"
          value={postUrl}
          onChange={(e) => setPostUrl(e.target.value)}
          className="mt-1 w-full rounded-xl px-3 py-2 text-sm"
          style={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--ink)" }}
        />
      </label>
      <label className="block text-sm" style={{ color: "var(--muted)" }}>
        What they said
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={3}
          maxLength={4000}
          required
          className="mt-1 w-full rounded-xl px-3 py-2 text-sm"
          style={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--ink)" }}
        />
      </label>
      <button
        type="submit"
        disabled={saving || !author.trim() || !comment.trim()}
        className="rounded-full px-5 py-2.5 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-50"
        style={{ background: "var(--accent)" }}
      >
        {saving ? "Saving…" : "Add to inbox"}
      </button>
    </form>
  );
}
