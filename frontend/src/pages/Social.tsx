import { useEffect, useMemo, useState } from "react";
import {
  social,
  type PostStatus,
  type SocialCampaign,
  type SocialPlatform,
  type SocialPost,
  type SocialStatus,
} from "../lib/social";

const QUEUE_FILTERS: [PostStatus | "all", string][] = [
  ["all", "All"],
  ["draft", "Needs review"],
  ["approved", "Approved"],
  ["staged", "Scheduled"],
  ["posted", "Posted"],
];

const REVISE_REASONS: [string, string][] = [
  ["too_generic", "too generic"],
  ["unsupported", "not backed up"],
  ["different_angle", "different angle"],
];

const REJECT_REASONS: [string, string][] = [
  ["too_promotional", "too salesy"],
  ["wrong_audience", "wrong audience"],
  ["repetitive", "repetitive"],
];

const STATUS_LABEL: Record<PostStatus, string> = {
  draft: "Needs review",
  approved: "Approved",
  rejected: "Rejected",
  staged: "Scheduled",
  posted: "Posted",
  failed: "Failed",
};

function nextMondayAt9(): string {
  const d = new Date();
  d.setDate(d.getDate() + ((8 - d.getDay()) % 7 || 7));
  d.setHours(9, 0, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const fmt = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

export default function Social() {
  const [status, setStatus] = useState<SocialStatus | null>(null);
  const [campaigns, setCampaigns] = useState<SocialCampaign[]>([]);
  const [posts, setPosts] = useState<SocialPost[]>([]);
  const [filter, setFilter] = useState<PostStatus | "all">("all");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = async () => {
    setError(null);
    try {
      const [s, c, p] = await Promise.all([
        social.status(),
        social.listCampaigns(),
        social.listPosts(),
      ]);
      setStatus(s);
      setCampaigns(c);
      setPosts(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load your campaigns");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const counts = useMemo(() => {
    const by = (s: PostStatus) => posts.filter((p) => p.status === s).length;
    return {
      all: posts.length,
      draft: by("draft"),
      approved: by("approved"),
      staged: by("staged"),
      posted: by("posted"),
      rejected: by("rejected"),
      failed: by("failed"),
    } as Record<PostStatus | "all", number>;
  }, [posts]);

  const visible = filter === "all" ? posts : posts.filter((p) => p.status === filter);

  const ready = status && status.brand_kit_version > 0 && status.public_context_count > 0;

  const generate = async (campaign: SocialCampaign) => {
    setBusy(campaign.id);
    setError(null);
    try {
      await social.generateCampaign(campaign.id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setBusy(null);
    }
  };

  const togglePause = async (campaign: SocialCampaign) => {
    const next = campaign.status === "paused" ? "active" : "paused";
    setBusy(campaign.id);
    try {
      const updated = await social.setCampaignStatus(campaign.id, next);
      setCampaigns((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't update that campaign");
    } finally {
      setBusy(null);
    }
  };

  if (loading) {
    return (
      <div className="grid min-h-[50vh] place-items-center" style={{ color: "var(--muted)" }}>
        Loading your campaigns…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-bold" style={{ color: "var(--ink)" }}>
            Social campaigns
          </h1>
          <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
            One brief becomes a run of weekly drafts. Nothing goes out until you approve it.
          </p>
        </div>
        <button
          onClick={() => setCreating((v) => !v)}
          className="rounded-full px-5 py-2.5 text-sm font-semibold text-white transition hover:brightness-95"
          style={{ background: "var(--accent)" }}
        >
          {creating ? "Close" : "New campaign"}
        </button>
      </header>

      {!ready && (
        <div
          className="rounded-xl px-4 py-2.5 text-sm"
          style={{ background: "#FDF4E7", color: "#8A6224", border: "1px solid #EFD9B4" }}
        >
          Before Churnary can write posts:{" "}
          {status?.brand_kit_version === 0 && <b>save your brand kit</b>}
          {status?.brand_kit_version === 0 && status?.public_context_count === 0 && " and "}
          {status?.public_context_count === 0 && (
            <b>approve at least one fact for public use</b>
          )}
          . Both live on the Brand &amp; knowledge page.
        </div>
      )}

      {status && !status.buffer_configured && (
        <div
          className="rounded-xl px-4 py-2.5 text-sm"
          style={{ background: "var(--surface-2)", color: "var(--muted)" }}
        >
          Buffer isn't connected, so publishing is turned off. You can still generate, review,
          and approve posts.
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="rounded-xl px-4 py-2.5 text-sm"
          style={{ background: "#FBEAE4", color: "var(--accent-dark)" }}
        >
          {error}
        </div>
      )}

      {creating && (
        <NewCampaign
          onDone={async () => {
            setCreating(false);
            await load();
          }}
          onError={setError}
        />
      )}

      <section className="space-y-3">
        {campaigns.length === 0 && (
          <div className="glass p-6 text-sm" style={{ color: "var(--muted)" }}>
            No campaigns yet. Start one and Churnary will draft a post for every week you pick.
          </div>
        )}
        {campaigns.map((c) => (
          <article key={c.id} className="glass p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-display text-lg font-bold" style={{ color: "var(--ink)" }}>
                  {c.name}
                </h2>
                <p className="mt-0.5 text-sm" style={{ color: "var(--muted)" }}>
                  {c.brief}
                </p>
                <p className="mt-1 text-xs" style={{ color: "var(--muted-2)" }}>
                  {c.occurrences} weeks · every {c.interval_weeks === 1 ? "week" : `${c.interval_weeks} weeks`} ·{" "}
                  {c.platforms.join(" + ")} · {c.timezone} · {c.post_count} posts
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className="rounded-full px-3 py-1 text-xs font-semibold"
                  style={{
                    background: c.status === "active" ? "#E8F0E3" : "var(--surface-3)",
                    color: c.status === "active" ? "var(--sage-text)" : "var(--muted)",
                  }}
                >
                  {c.status}
                </span>
                {(c.status === "active" || c.status === "paused") && (
                  <button
                    onClick={() => togglePause(c)}
                    disabled={busy === c.id}
                    className="rounded-full px-3.5 py-1.5 text-sm font-semibold transition hover:brightness-95 disabled:opacity-50"
                    style={{ background: "var(--surface-3)", color: "var(--ink-strong)" }}
                  >
                    {c.status === "paused" ? "Resume" : "Pause"}
                  </button>
                )}
                <button
                  onClick={() => generate(c)}
                  disabled={busy === c.id || !ready}
                  className="rounded-full px-3.5 py-1.5 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-40"
                  style={{ background: "var(--accent)" }}
                >
                  {busy === c.id ? "Writing…" : c.post_count ? "Regenerate drafts" : "Generate drafts"}
                </button>
              </div>
            </div>

            {c.status === "paused" && (
              <p className="mt-3 text-xs" style={{ color: "var(--muted-2)" }}>
                Paused — approved posts from this campaign won't publish until you resume.
              </p>
            )}
            {c.last_error && (
              <p className="mt-3 text-xs" style={{ color: "var(--accent-dark)" }}>
                Last attempt failed: {c.last_error}
              </p>
            )}

            <ol className="mt-4 flex flex-wrap gap-2">
              {c.slots.slice(0, 8).map((s) => (
                <li
                  key={s.occurrence}
                  className="rounded-xl px-3 py-2 text-xs"
                  style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
                >
                  <div className="font-semibold" style={{ color: "var(--ink)" }}>
                    Week {s.occurrence}
                  </div>
                  <div style={{ color: "var(--muted-2)" }}>{fmt(s.scheduled_for)}</div>
                  <div className="max-w-40 truncate" style={{ color: "var(--muted)" }}>
                    {s.theme}
                  </div>
                </li>
              ))}
              {c.slots.length > 8 && (
                <li className="self-center text-xs" style={{ color: "var(--muted-2)" }}>
                  +{c.slots.length - 8} more
                </li>
              )}
            </ol>
          </article>
        ))}
      </section>

      <section className="space-y-4">
        <h2 className="font-display text-2xl font-bold" style={{ color: "var(--ink)" }}>
          Review queue
        </h2>

        <div className="flex flex-wrap gap-2">
          {QUEUE_FILTERS.map(([key, label]) => (
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
              {label} · {counts[key] ?? 0}
            </button>
          ))}
        </div>

        {visible.length === 0 ? (
          <div className="glass p-6 text-sm" style={{ color: "var(--muted)" }}>
            Nothing here. Generate drafts from a campaign above.
          </div>
        ) : (
          <div className="space-y-3">
            {visible.map((post) => (
              <PostCard
                key={post.id}
                post={post}
                canPublish={Boolean(status?.buffer_configured)}
                onUpdate={(updated) =>
                  setPosts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
                }
                onReload={load}
                onError={setError}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function PostCard({
  post,
  canPublish,
  onUpdate,
  onReload,
  onError,
}: {
  post: SocialPost;
  canPublish: boolean;
  onUpdate: (post: SocialPost) => void;
  onReload: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [reasonFor, setReasonFor] = useState<"revise" | "reject" | null>(null);
  const [override, setOverride] = useState(false);
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);

  const errors = post.editorial?.errors ?? [];
  const warnings = post.editorial?.warnings ?? [];

  const run = async (fn: () => Promise<SocialPost>) => {
    setPending(true);
    try {
      onUpdate(await fn());
      setReasonFor(null);
      setOverride(false);
      setNote("");
    } catch (e) {
      const message = e instanceof Error ? e.message : "That didn't work";
      // A blocked approval is the gate doing its job — offer the override
      // rather than just showing an error.
      if (message.includes("did not pass review")) setOverride(true);
      onError(message);
    } finally {
      setPending(false);
    }
  };

  const publish = async () => {
    setPending(true);
    try {
      const [result] = await social.publish(post.id, "now");
      if (result && !result.ok) onError(result.message);
      setConfirming(false);
      await onReload();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Publish failed");
    } finally {
      setPending(false);
    }
  };

  return (
    <article className="glass p-6">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
          style={{ background: "var(--surface-3)", color: "var(--muted)" }}
        >
          {post.platform}
        </span>
        <span
          className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
          style={
            post.status === "posted" || post.status === "approved"
              ? { background: "#E8F0E3", color: "var(--sage-text)" }
              : post.status === "failed"
                ? { background: "#FBEAE4", color: "var(--accent-dark)" }
                : { background: "var(--surface-3)", color: "var(--muted)" }
          }
        >
          {STATUS_LABEL[post.status]}
        </span>
        {post.campaign_occurrence && (
          <span className="text-xs" style={{ color: "var(--muted-2)" }}>
            week {post.campaign_occurrence}
          </span>
        )}
        {post.generated_by === "fallback" && (
          <span className="text-xs" style={{ color: "var(--muted-2)" }}>
            written from a template
          </span>
        )}
        {post.scheduled_for && (
          <span className="ml-auto text-xs" style={{ color: "var(--muted-2)" }}>
            {fmt(post.scheduled_for)}
          </span>
        )}
      </div>

      <p className="mt-2 text-xs font-semibold" style={{ color: "var(--muted)" }}>
        {post.topic}
      </p>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed" style={{ color: "var(--ink)" }}>
        {post.post_text}
      </p>
      {post.hashtags.length > 0 && (
        <p className="mt-2 text-sm" style={{ color: "var(--accent)" }}>
          {post.hashtags.map((h) => `#${h}`).join(" ")}
        </p>
      )}

      {post.source_summary && (
        <p className="mt-3 text-xs" style={{ color: "var(--muted-2)" }}>
          Based on: {post.source_summary}
        </p>
      )}

      {errors.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs" style={{ color: "var(--accent-dark)" }}>
          {errors.map((e) => (
            <li key={e}>• {e}</li>
          ))}
        </ul>
      )}
      {warnings.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs" style={{ color: "var(--muted-2)" }}>
          {warnings.map((w) => (
            <li key={w}>• {w}</li>
          ))}
        </ul>
      )}

      {post.failure_reason && (
        <p className="mt-3 text-xs" style={{ color: "var(--accent-dark)" }}>
          {post.failure_reason}
        </p>
      )}

      {post.review_history.length > 0 && (
        <p className="mt-3 text-xs" style={{ color: "var(--muted-2)" }}>
          Last decision: {post.review_history[post.review_history.length - 1].decision}
          {post.review_history[post.review_history.length - 1].note
            ? ` — ${post.review_history[post.review_history.length - 1].note}`
            : ""}
        </p>
      )}

      {override && (
        <div className="mt-4">
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            placeholder="Why is this fine to publish anyway?"
            className="w-full rounded-xl px-3 py-2 text-sm"
            style={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--ink)" }}
          />
          <div className="mt-2 flex gap-2">
            <button
              disabled={pending || note.trim().length < 10}
              onClick={() => run(() => social.decidePost(post.id, "approve", "strong_insight", note.trim()))}
              className="rounded-full px-4 py-2 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-40"
              style={{ background: "var(--accent)" }}
            >
              Approve anyway
            </button>
            <button
              onClick={() => setOverride(false)}
              className="rounded-full px-4 py-2 text-sm font-semibold"
              style={{ background: "var(--surface-3)", color: "var(--muted)" }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {reasonFor && (
        <div className="mt-4 flex flex-wrap gap-2">
          {(reasonFor === "revise" ? REVISE_REASONS : REJECT_REASONS).map(([id, label]) => (
            <button
              key={id}
              disabled={pending}
              onClick={() => run(() => social.decidePost(post.id, reasonFor, id))}
              className="rounded-full px-3.5 py-1.5 text-sm font-semibold transition hover:brightness-95"
              style={{ background: "var(--surface-3)", color: "var(--ink-strong)" }}
            >
              {label}
            </button>
          ))}
          <button
            onClick={() => setReasonFor(null)}
            className="rounded-full px-3.5 py-1.5 text-sm"
            style={{ color: "var(--muted-2)" }}
          >
            cancel
          </button>
        </div>
      )}

      {!override && !reasonFor && (
        <div className="mt-4 flex flex-wrap gap-2">
          {post.status === "draft" && (
            <>
              <button
                disabled={pending}
                onClick={() => run(() => social.decidePost(post.id, "approve", "strong_insight"))}
                className="rounded-full px-5 py-2.5 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-50"
                style={{ background: "var(--accent)" }}
              >
                Approve
              </button>
              <button
                onClick={() => setReasonFor("revise")}
                className="rounded-full px-4 py-2.5 text-sm font-semibold transition hover:brightness-95"
                style={{ background: "var(--surface-3)", color: "var(--ink-strong)" }}
              >
                Ask for a rewrite
              </button>
              <button
                onClick={() => setReasonFor("reject")}
                className="rounded-full border px-4 py-2.5 text-sm font-semibold transition hover:brightness-95"
                style={{ borderColor: "var(--border)", color: "var(--muted)" }}
              >
                Reject
              </button>
            </>
          )}

          {post.status === "approved" && canPublish && !confirming && (
            <button
              onClick={() => setConfirming(true)}
              className="rounded-full px-5 py-2.5 text-sm font-semibold text-white transition hover:brightness-95"
              style={{ background: "var(--accent)" }}
            >
              Publish to {post.platform}
            </button>
          )}

          {post.status === "approved" && confirming && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm" style={{ color: "var(--muted)" }}>
                {post.scheduled_for
                  ? `Buffer will schedule this for ${fmt(post.scheduled_for)}.`
                  : "Buffer will publish this right away."}
              </span>
              <button
                disabled={pending}
                onClick={publish}
                className="rounded-full px-4 py-2 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-50"
                style={{ background: "var(--accent)" }}
              >
                {pending ? "Sending…" : "Confirm"}
              </button>
              <button
                onClick={() => setConfirming(false)}
                className="rounded-full px-4 py-2 text-sm"
                style={{ color: "var(--muted-2)" }}
              >
                cancel
              </button>
            </div>
          )}

          {post.published_url && (
            <a
              href={post.published_url}
              target="_blank"
              rel="noreferrer"
              className="self-center text-sm underline"
              style={{ color: "var(--accent)" }}
            >
              View live post
            </a>
          )}
        </div>
      )}
    </article>
  );
}

function NewCampaign({
  onDone,
  onError,
}: {
  onDone: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [name, setName] = useState("");
  const [brief, setBrief] = useState("");
  const [themes, setThemes] = useState("");
  const [linkedin, setLinkedin] = useState(true);
  const [x, setX] = useState(false);
  const [startAt, setStartAt] = useState(nextMondayAt9);
  const [weeks, setWeeks] = useState(6);
  const [interval, setInterval] = useState(1);
  const [saving, setSaving] = useState(false);

  const platforms: SocialPlatform[] = [
    ...(linkedin ? (["linkedin"] as const) : []),
    ...(x ? (["x"] as const) : []),
  ];

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await social.createCampaign({
        name: name.trim(),
        brief: brief.trim(),
        themes: themes.split("\n").map((t) => t.trim()).filter(Boolean),
        platforms,
        // Sent with the browser's offset so the backend keeps the local time
        // across daylight saving, rather than pinning a UTC instant.
        start_at: new Date(startAt).toISOString(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        interval_weeks: interval,
        occurrences: weeks,
      });
      await onDone();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Couldn't create that campaign");
    } finally {
      setSaving(false);
    }
  };

  const style = {
    background: "var(--surface-2)",
    border: "1px solid var(--border)",
    color: "var(--ink)",
  };

  return (
    <form onSubmit={submit} className="glass space-y-4 p-6">
      <h2 className="font-display text-xl font-bold" style={{ color: "var(--ink)" }}>
        New campaign
      </h2>

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-sm" style={{ color: "var(--muted)" }}>
          Name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={100}
            required
            className="mt-1 w-full rounded-xl px-3 py-2 text-sm"
            style={style}
          />
        </label>
        <label className="text-sm" style={{ color: "var(--muted)" }}>
          First post
          <input
            type="datetime-local"
            value={startAt}
            onChange={(e) => setStartAt(e.target.value)}
            required
            className="mt-1 w-full rounded-xl px-3 py-2 text-sm"
            style={style}
          />
        </label>
      </div>

      <label className="block text-sm" style={{ color: "var(--muted)" }}>
        What's this campaign about?
        <textarea
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          rows={2}
          maxLength={500}
          required
          className="mt-1 w-full rounded-xl px-3 py-2 text-sm"
          style={style}
        />
      </label>

      <label className="block text-sm" style={{ color: "var(--muted)" }}>
        Weekly themes <span className="text-xs">(one per line — they repeat if you run out)</span>
        <textarea
          value={themes}
          onChange={(e) => setThemes(e.target.value)}
          rows={3}
          className="mt-1 w-full rounded-xl px-3 py-2 text-sm"
          style={style}
        />
      </label>

      <div className="flex flex-wrap items-end gap-5">
        <div className="text-sm" style={{ color: "var(--muted)" }}>
          <span className="font-semibold">Post to</span>
          <div className="mt-1 flex gap-3">
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={linkedin} onChange={(e) => setLinkedin(e.target.checked)} />
              LinkedIn
            </label>
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={x} onChange={(e) => setX(e.target.checked)} />X
            </label>
          </div>
        </div>

        <label className="text-sm" style={{ color: "var(--muted)" }}>
          For how many weeks
          <input
            type="number"
            min={2}
            max={52}
            value={weeks}
            onChange={(e) => setWeeks(Number(e.target.value))}
            className="mt-1 w-24 rounded-xl px-3 py-2 text-sm"
            style={style}
          />
        </label>

        <label className="text-sm" style={{ color: "var(--muted)" }}>
          Every N weeks
          <input
            type="number"
            min={1}
            max={4}
            value={interval}
            onChange={(e) => setInterval(Number(e.target.value))}
            className="mt-1 w-24 rounded-xl px-3 py-2 text-sm"
            style={style}
          />
        </label>
      </div>

      <p className="text-xs" style={{ color: "var(--muted-2)" }}>
        That's {weeks * platforms.length} drafts, starting {startAt ? fmt(new Date(startAt).toISOString()) : "—"}.
      </p>

      <button
        type="submit"
        disabled={saving || !name.trim() || !brief.trim() || platforms.length === 0}
        className="rounded-full px-5 py-2.5 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-50"
        style={{ background: "var(--accent)" }}
      >
        {saving ? "Creating…" : "Create campaign"}
      </button>
    </form>
  );
}
