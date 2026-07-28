import { useEffect, useState } from "react";
import {
  social,
  type BrandKit,
  type ContextItem,
  type ContextKind,
  type TypeScale,
} from "../lib/social";

const SCALES: { id: TypeScale; label: string; px: number }[] = [
  { id: "compact", label: "Compact", px: 30 },
  { id: "balanced", label: "Balanced", px: 38 },
  { id: "editorial", label: "Editorial", px: 46 },
];

const KINDS: ContextKind[] = [
  "company",
  "product",
  "customer",
  "founder",
  "market",
  "proof",
  "other",
];

const COLOR_FIELDS = [
  ["primary", "Primary"],
  ["secondary", "Secondary"],
  ["accent", "Accent"],
  ["background", "Background"],
  ["text", "Text"],
] as const;

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block text-sm" style={{ color: "var(--muted)" }}>
      <span className="font-semibold">{label}</span>
      {hint && (
        <span className="ml-1 text-xs" style={{ color: "var(--muted-2)" }}>
          {hint}
        </span>
      )}
      <div className="mt-1">{children}</div>
    </label>
  );
}

const inputStyle = {
  background: "var(--surface-2)",
  border: "1px solid var(--border)",
  color: "var(--ink)",
};

export default function Brand() {
  const [kit, setKit] = useState<BrandKit | null>(null);
  const [context, setContext] = useState<ContextItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setError(null);
    try {
      const [k, c] = await Promise.all([social.getBrandKit(), social.listContext()]);
      setKit(k);
      setContext(c.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load your brand kit");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const patch = (changes: Partial<BrandKit>) =>
    setKit((prev) => (prev ? { ...prev, ...changes } : prev));

  const save = async () => {
    if (!kit) return;
    setSaving(true);
    setError(null);
    try {
      const { version: _v, updated_at: _u, ...payload } = kit;
      setKit(await social.saveBrandKit(payload));
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save your brand kit");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="grid place-items-center py-16" style={{ color: "var(--muted)" }}>
        Loading your brand kit…
      </div>
    );
  }

  // A failed load leaves kit null. Say so and offer a retry — folding this into
  // the loading branch showed a spinner forever and hid the actual error.
  if (!kit) {
    return (
      <div className="glass p-6">
        <h2 className="font-display text-2xl font-bold" style={{ color: "var(--ink)" }}>
          Brand &amp; knowledge
        </h2>
        <p className="mt-2 text-sm" style={{ color: "var(--accent-dark)" }}>
          {error ?? "Couldn't load your brand kit."}
        </p>
        <button
          onClick={() => {
            setLoading(true);
            load();
          }}
          className="mt-4 rounded-full px-5 py-2.5 text-sm font-semibold text-white transition hover:brightness-95"
          style={{ background: "var(--accent)" }}
        >
          Try again
        </button>
      </div>
    );
  }

  const publicCount = context.filter((c) => c.public_safe).length;
  const headingPx = SCALES.find((s) => s.id === kit.typography.scale)?.px ?? 38;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-bold" style={{ color: "var(--ink)" }}>
            Brand &amp; knowledge
          </h1>
          <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
            How Churnary sounds when it writes for you, and the facts it's allowed to use.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span
            className="rounded-full px-3 py-1 text-xs font-semibold"
            style={{ background: "var(--surface-3)", color: "var(--muted)" }}
          >
            {kit.version === 0 ? "Not saved yet" : `Version ${kit.version}`}
          </span>
          <button
            onClick={save}
            disabled={saving}
            className="rounded-full px-5 py-2.5 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-50"
            style={{ background: "var(--accent)" }}
          >
            {saving ? "Saving…" : saved ? "Saved" : "Save brand kit"}
          </button>
        </div>
      </header>

      {kit.version === 0 && (
        <div
          className="rounded-xl px-4 py-2.5 text-sm"
          style={{ background: "#FDF4E7", color: "#8A6224", border: "1px solid #EFD9B4" }}
        >
          Save your brand kit once to unlock post generation. Until then Churnary won't write
          anything on your behalf.
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

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <section className="glass space-y-4 p-6">
          <h2 className="font-display text-xl font-bold" style={{ color: "var(--ink)" }}>
            Voice
          </h2>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Business name">
              <input
                value={kit.name}
                onChange={(e) => patch({ name: e.target.value })}
                maxLength={80}
                className="w-full rounded-xl px-3 py-2 text-sm"
                style={inputStyle}
              />
            </Field>
            <Field label="Tagline">
              <input
                value={kit.tagline}
                onChange={(e) => patch({ tagline: e.target.value })}
                maxLength={160}
                className="w-full rounded-xl px-3 py-2 text-sm"
                style={inputStyle}
              />
            </Field>
          </div>

          <Field label="Who you're talking to" hint="the customers, not the industry">
            <input
              value={kit.audience}
              onChange={(e) => patch({ audience: e.target.value })}
              maxLength={500}
              className="w-full rounded-xl px-3 py-2 text-sm"
              style={inputStyle}
            />
          </Field>

          <Field label="Tone" hint="a few adjectives is plenty">
            <input
              value={kit.tone}
              onChange={(e) => patch({ tone: e.target.value })}
              maxLength={500}
              className="w-full rounded-xl px-3 py-2 text-sm"
              style={inputStyle}
            />
          </Field>

          <Field label="What you do and why it matters">
            <textarea
              value={kit.positioning}
              onChange={(e) => patch({ positioning: e.target.value })}
              rows={3}
              maxLength={500}
              className="w-full rounded-xl px-3 py-2 text-sm"
              style={inputStyle}
            />
          </Field>

          <Field label="Never say" hint="one per line — these block a post from being approved">
            <textarea
              value={kit.avoid.join("\n")}
              onChange={(e) =>
                patch({ avoid: e.target.value.split("\n").map((l) => l.trim()).filter(Boolean) })
              }
              rows={3}
              className="w-full rounded-xl px-3 py-2 text-sm"
              style={inputStyle}
            />
          </Field>

          <h2 className="pt-2 font-display text-xl font-bold" style={{ color: "var(--ink)" }}>
            Look
          </h2>

          <div className="flex flex-wrap gap-3">
            {COLOR_FIELDS.map(([key, label]) => (
              <label key={key} className="text-xs" style={{ color: "var(--muted)" }}>
                <span className="font-semibold">{label}</span>
                <input
                  type="color"
                  value={kit.colors[key]}
                  onChange={(e) => patch({ colors: { ...kit.colors, [key]: e.target.value } })}
                  className="mt-1 block h-9 w-16 cursor-pointer rounded-lg"
                  style={{ border: "1px solid var(--border)", background: "var(--surface-2)" }}
                />
              </label>
            ))}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Heading font">
              <input
                value={kit.typography.heading_family}
                onChange={(e) =>
                  patch({ typography: { ...kit.typography, heading_family: e.target.value } })
                }
                maxLength={80}
                className="w-full rounded-xl px-3 py-2 text-sm"
                style={inputStyle}
              />
            </Field>
            <Field label="Body font">
              <input
                value={kit.typography.body_family}
                onChange={(e) =>
                  patch({ typography: { ...kit.typography, body_family: e.target.value } })
                }
                maxLength={80}
                className="w-full rounded-xl px-3 py-2 text-sm"
                style={inputStyle}
              />
            </Field>
          </div>

          <Field label="Type scale">
            <div className="flex gap-2">
              {SCALES.map((s) => (
                <button
                  key={s.id}
                  onClick={() => patch({ typography: { ...kit.typography, scale: s.id } })}
                  className="rounded-full px-3.5 py-1.5 text-sm transition"
                  style={
                    kit.typography.scale === s.id
                      ? { background: "var(--ink-strong)", color: "var(--cream-text)", fontWeight: 700 }
                      : { background: "var(--surface-2)", color: "var(--muted)", fontWeight: 600 }
                  }
                >
                  {s.label}
                </button>
              ))}
            </div>
          </Field>

          <Field label="Logo URL" hint="optional, must be https">
            <input
              value={kit.logo_url ?? ""}
              onChange={(e) => patch({ logo_url: e.target.value || null })}
              maxLength={500}
              className="w-full rounded-xl px-3 py-2 text-sm"
              style={inputStyle}
            />
          </Field>
        </section>

        <div className="space-y-5">
          <section
            className="rounded-2xl p-6"
            style={{
              background: kit.colors.background,
              border: `1px solid ${kit.colors.accent}`,
            }}
          >
            <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: kit.colors.primary }}>
              Preview
            </p>
            <h3
              className="mt-2 font-bold leading-tight"
              style={{
                fontFamily: `${kit.typography.heading_family}, Georgia, serif`,
                fontWeight: kit.typography.heading_weight,
                fontSize: headingPx,
                color: kit.colors.text,
              }}
            >
              {kit.name || "Your business"}
            </h3>
            <p
              className="mt-2 text-sm"
              style={{
                fontFamily: `${kit.typography.body_family}, system-ui, sans-serif`,
                fontWeight: kit.typography.body_weight,
                color: kit.colors.text,
                opacity: 0.85,
              }}
            >
              {kit.tagline || "Your tagline goes here."}
            </p>
            <div className="mt-4 flex gap-2">
              {COLOR_FIELDS.map(([key]) => (
                <span
                  key={key}
                  className="h-7 w-7 rounded-full"
                  style={{ background: kit.colors[key], border: "1px solid rgba(0,0,0,.08)" }}
                />
              ))}
            </div>
          </section>

          <Brain
            items={context}
            publicCount={publicCount}
            onChange={setContext}
            onError={setError}
          />
        </div>
      </div>
    </div>
  );
}

function Brain({
  items,
  publicCount,
  onChange,
  onError,
}: {
  items: ContextItem[];
  publicCount: number;
  onChange: (items: ContextItem[]) => void;
  onError: (message: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<ContextKind>("company");
  const [summary, setSummary] = useState("");
  const [source, setSource] = useState("");
  const [publicSafe, setPublicSafe] = useState(false);
  const [saving, setSaving] = useState(false);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const created = await social.addContext({
        title: title.trim(),
        kind,
        summary: summary.trim(),
        source: source.trim() || null,
        public_safe: publicSafe,
      });
      onChange([created, ...items]);
      setTitle("");
      setSummary("");
      setSource("");
      setPublicSafe(false);
      setAdding(false);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Couldn't save that");
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (item: ContextItem) => {
    try {
      const updated = await social.setContextPublicSafe(item.id, !item.public_safe);
      onChange(items.map((i) => (i.id === item.id ? updated : i)));
    } catch (err) {
      onError(err instanceof Error ? err.message : "Couldn't update that");
    }
  };

  const remove = async (item: ContextItem) => {
    try {
      await social.deleteContext(item.id);
      onChange(items.filter((i) => i.id !== item.id));
    } catch (err) {
      onError(err instanceof Error ? err.message : "Couldn't delete that");
    }
  };

  return (
    <section className="glass p-6">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-display text-xl font-bold" style={{ color: "var(--ink)" }}>
          What Churnary knows
        </h2>
        <button
          onClick={() => setAdding((v) => !v)}
          className="rounded-full px-3.5 py-1.5 text-sm font-semibold transition hover:brightness-95"
          style={{ background: "var(--surface-3)", color: "var(--ink-strong)" }}
        >
          {adding ? "Cancel" : "Add a fact"}
        </button>
      </div>

      <p className="mt-1.5 text-xs" style={{ color: "var(--muted-2)" }}>
        {publicCount} of {items.length} approved for public use. Only those are ever shown to
        the AI — the rest stay here for your reference.
      </p>

      {adding && (
        <form onSubmit={add} className="mt-4 space-y-3">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Short title"
            maxLength={160}
            required
            className="w-full rounded-xl px-3 py-2 text-sm"
            style={inputStyle}
          />
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as ContextKind)}
            className="w-full rounded-xl px-3 py-2 text-sm"
            style={inputStyle}
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <textarea
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            placeholder="The fact itself, written so it stands on its own."
            rows={3}
            maxLength={4000}
            required
            className="w-full rounded-xl px-3 py-2 text-sm"
            style={inputStyle}
          />
          <input
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="Where it came from (optional)"
            maxLength={500}
            className="w-full rounded-xl px-3 py-2 text-sm"
            style={inputStyle}
          />
          <label className="flex items-center gap-2 text-sm" style={{ color: "var(--muted)" }}>
            <input
              type="checkbox"
              checked={publicSafe}
              onChange={(e) => setPublicSafe(e.target.checked)}
            />
            Approved for public content
          </label>
          <button
            type="submit"
            disabled={saving || !title.trim() || !summary.trim()}
            className="rounded-full px-5 py-2 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-50"
            style={{ background: "var(--accent)" }}
          >
            {saving ? "Saving…" : "Add"}
          </button>
        </form>
      )}

      <ul className="mt-4 space-y-2">
        {items.length === 0 && (
          <li className="text-sm" style={{ color: "var(--muted-2)" }}>
            Nothing yet. Add a few facts about what you offer and Churnary will write from them
            instead of guessing.
          </li>
        )}
        {items.map((item) => (
          <li
            key={item.id}
            className="rounded-xl p-3"
            style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold" style={{ color: "var(--ink)" }}>
                  {item.title}
                </p>
                <p className="mt-0.5 line-clamp-2 text-xs" style={{ color: "var(--muted)" }}>
                  {item.summary}
                </p>
              </div>
              <span
                className="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold"
                style={
                  item.public_safe
                    ? { background: "#E8F0E3", color: "var(--sage-text)" }
                    : { background: "var(--surface-3)", color: "var(--muted-2)" }
                }
              >
                {item.public_safe ? "Public" : "Private"}
              </span>
            </div>
            <div className="mt-2 flex gap-3 text-xs">
              <button
                onClick={() => toggle(item)}
                className="underline"
                style={{ color: "var(--muted)" }}
              >
                {item.public_safe ? "Make private" : "Approve for public use"}
              </button>
              <button
                onClick={() => remove(item)}
                className="underline"
                style={{ color: "var(--muted-2)" }}
              >
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
