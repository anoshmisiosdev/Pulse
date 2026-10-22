import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  api,
  formatCurrency,
  type AutomationChannel,
  type Campaign,
  type CampaignDetail,
  type CampaignSendSummary,
  type ExperimentResult,
  type SegmentDefinition,
} from "../lib/api";

/** The loop from the Definition of Done: see who's at risk, approve an
 * AI-written win-back, watch it send, see what came back.
 *
 * The screen is built around the fact that **creating a campaign sends
 * nothing**. Every message is queued as `pending` and the owner reads it
 * before anyone else does, so the review step is the main event rather than a
 * confirmation dialog on the way out.
 */

const SKIP_REASONS: Record<string, string> = {
  unsubscribed_email: "unsubscribed from email",
  unsubscribed_sms: "opted out of texts",
  do_not_contact: "marked do-not-contact",
  no_email_on_file: "no email address",
  no_phone_on_file: "no phone number",
  not_found: "not in your customer list",
  customer_removed: "customer was deleted",
  no_copy: "no message was written",
  cancelled_by_owner: "you cancelled it",
};

function readableSkip(reason: string): string {
  return SKIP_REASONS[reason] ?? reason.replace(/_/g, " ");
}

export default function Campaigns() {
  const { campaignId } = useParams<{ campaignId?: string }>();
  return campaignId ? <CampaignReview id={campaignId} /> : <CampaignList />;
}

// -- List + builder -----------------------------------------------------------

function CampaignList() {
  const navigate = useNavigate();
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [segments, setSegments] = useState<SegmentDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);

  const [name, setName] = useState("");
  const [channel, setChannel] = useState<AutomationChannel>("email");
  const [segmentKey, setSegmentKey] = useState("high_risk");
  const [incentive, setIncentive] = useState("");
  const [abTest, setAbTest] = useState(false);
  const [variantBIncentive, setVariantBIncentive] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([api.listCampaigns(), api.segments()])
      .then(([rows, seg]) => {
        setCampaigns(rows);
        setSegments(seg.segments);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load campaigns"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const selectedSegment = segments.find((s) => s.key === segmentKey);

  async function build() {
    setBuilding(true);
    setError(null);
    try {
      const picked = await api.segment(segmentKey, { channel, limit: 500 });
      if (picked.customer_ids.length === 0) {
        setError(
          "Nobody is in that segment right now, so there's nothing to send. Try a wider one."
        );
        return;
      }
      const detail = await api.createCampaign({
        name: name.trim() || `${selectedSegment?.label ?? "Win-back"} campaign`,
        channel,
        customer_ids: picked.customer_ids,
        incentive: incentive.trim() || undefined,
        ab_test: abTest,
        variant_b_incentive: abTest ? variantBIncentive.trim() || undefined : undefined,
      });
      navigate(`/campaigns/${detail.id}`);
    } catch (e) {
      // A 402 is a plan limit, not a failure — say which plan covers it.
      setError(
        e instanceof ApiError && e.status === 402
          ? e.message
          : e instanceof Error
            ? e.message
            : "Couldn't build that campaign"
      );
    } finally {
      setBuilding(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="anim-fade-up">
        <h1 className="text-[38px] font-bold tracking-tight" style={{ color: "var(--ink)" }}>
          Campaigns
        </h1>
        <p className="mt-1 italic" style={{ color: "var(--muted)", fontSize: "15.5px" }}>
          Churnary writes the message. You read it before anyone else does.
        </p>
      </div>

      <section
        className="anim-fade-up rounded-[20px] border p-6"
        style={{ animationDelay: "0.05s", borderColor: "var(--line)", background: "var(--card)" }}
      >
        <h2 className="font-display text-[20px] font-bold" style={{ color: "var(--ink)" }}>
          New campaign
        </h2>
        <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
          Pick who it's for. Nothing sends until you approve it.
        </p>

        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <Field label="Campaign name">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={`${selectedSegment?.label ?? "Win-back"} campaign`}
              className="w-full rounded-xl border px-3 py-2 text-sm outline-none focus:border-[#B4532A]"
              style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
            />
          </Field>

          <Field label="Who it goes to">
            <select
              value={segmentKey}
              onChange={(e) => setSegmentKey(e.target.value)}
              className="w-full rounded-xl border px-3 py-2 text-sm outline-none"
              style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
            >
              {segments.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label} ({s.size})
                </option>
              ))}
            </select>
            {selectedSegment && (
              <p className="mt-1 text-xs" style={{ color: "var(--muted-2)" }}>
                {selectedSegment.description}
              </p>
            )}
          </Field>

          <Field label="Channel">
            <div className="flex gap-2">
              {(["email", "sms"] as AutomationChannel[]).map((c) => (
                <button
                  key={c}
                  onClick={() => setChannel(c)}
                  className="rounded-full px-4 py-1.5 text-sm font-semibold transition"
                  style={
                    channel === c
                      ? { background: "var(--accent)", color: "#fff" }
                      : { background: "var(--surface-2)", color: "var(--muted)" }
                  }
                >
                  {c === "email" ? "Email" : "Text"}
                </button>
              ))}
            </div>
          </Field>

          <Field label="Offer (optional)">
            <input
              value={incentive}
              onChange={(e) => setIncentive(e.target.value)}
              placeholder="20% off your next visit"
              className="w-full rounded-xl border px-3 py-2 text-sm outline-none focus:border-[#B4532A]"
              style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
            />
          </Field>
        </div>

        <label className="mt-4 flex items-start gap-2.5 text-sm" style={{ color: "var(--ink)" }}>
          <input
            type="checkbox"
            checked={abTest}
            onChange={(e) => setAbTest(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            Test two versions
            <span className="block text-xs" style={{ color: "var(--muted-2)" }}>
              Splits the list evenly and tracks which one actually brought people back.
            </span>
          </span>
        </label>

        {abTest && (
          <div className="mt-3">
            <Field label="Version B's offer (optional)">
              <input
                value={variantBIncentive}
                onChange={(e) => setVariantBIncentive(e.target.value)}
                placeholder="Free coffee on us"
                className="w-full rounded-xl border px-3 py-2 text-sm outline-none focus:border-[#B4532A] sm:max-w-sm"
                style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
              />
              <p className="mt-1 text-xs" style={{ color: "var(--muted-2)" }}>
                Leave blank to test the wording with the same offer.
              </p>
            </Field>
          </div>
        )}

        {error && (
          <p className="mt-4 text-sm" style={{ color: "var(--accent-dark)" }}>
            {error}
          </p>
        )}

        <button
          onClick={build}
          disabled={building || !selectedSegment || selectedSegment.size === 0}
          className="mt-5 rounded-full px-6 py-2.5 text-sm font-semibold text-white transition hover:-translate-y-px disabled:opacity-50"
          style={{ background: "var(--accent)" }}
        >
          {building ? "Writing messages…" : "Write the messages"}
        </button>
      </section>

      <section className="anim-fade-up" style={{ animationDelay: "0.1s" }}>
        <h2 className="font-display text-[20px] font-bold" style={{ color: "var(--ink)" }}>
          Past campaigns
        </h2>
        {loading ? (
          <p className="mt-3 text-sm" style={{ color: "var(--muted)" }}>
            Loading…
          </p>
        ) : campaigns.length === 0 ? (
          <p className="mt-3 text-sm" style={{ color: "var(--muted)" }}>
            No campaigns yet. Build your first one above.
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {campaigns.map((c) => (
              <li key={c.id}>
                <Link
                  to={`/campaigns/${c.id}`}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border px-5 py-4 transition hover:-translate-y-px"
                  style={{ borderColor: "var(--line)", background: "var(--card)" }}
                >
                  <div>
                    <p className="font-semibold" style={{ color: "var(--ink)" }}>
                      {c.name}
                      {c.ab_test && (
                        <span
                          className="ml-2 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase"
                          style={{ background: "var(--surface-2)", color: "var(--muted)" }}
                        >
                          A/B
                        </span>
                      )}
                    </p>
                    <p className="mt-0.5 text-xs" style={{ color: "var(--muted-2)" }}>
                      {c.channel === "email" ? "Email" : "Text"} · {c.status.replace(/_/g, " ")}
                      {c.stats.pending > 0 && ` · ${c.stats.pending} awaiting your approval`}
                    </p>
                  </div>
                  <div className="flex gap-6 text-right text-sm">
                    <Stat label="Sent" value={String(c.stats.sent)} />
                    <Stat label="Opened" value={String(c.stats.opened)} />
                    <Stat
                      label="Came back"
                      value={
                        c.stats.recovered > 0
                          ? `${c.stats.recovered} · ${formatCurrency(c.stats.revenue_recovered)}`
                          : "—"
                      }
                    />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

// -- Review -------------------------------------------------------------------

function CampaignReview({ id }: { id: string }) {
  const [detail, setDetail] = useState<CampaignDetail | null>(null);
  const [experiment, setExperiment] = useState<ExperimentResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api
      .campaign(id)
      .then((d) => {
        setDetail(d);
        setError(null);
        return d.ab_test ? api.campaignExperiment(id).catch(() => null) : null;
      })
      .then(setExperiment)
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load that campaign"))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(load, [load]);

  const pending = useMemo(
    () => detail?.sends.filter((s) => s.status === "pending") ?? [],
    [detail]
  );

  async function approveAll() {
    if (!detail) return;
    setApproving(true);
    setError(null);
    setNotice(null);
    try {
      const summary = await api.approveCampaign(detail.id);
      const parts: string[] = [];
      if (summary.sent) parts.push(`${summary.sent} sent`);
      if (summary.deferred)
        parts.push(
          `${summary.deferred} held until sending hours (texts can't go out before 9am or after 8pm)`
        );
      if (summary.failed) parts.push(`${summary.failed} failed`);
      for (const [reason, count] of Object.entries(summary.skipped)) {
        parts.push(`${count} skipped — ${readableSkip(reason)}`);
      }
      setNotice(parts.join(" · ") || "Nothing was left to send.");
      load();
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 402
          ? e.message
          : e instanceof Error
            ? e.message
            : "Couldn't approve that"
      );
    } finally {
      setApproving(false);
    }
  }

  function replaceSend(updated: CampaignSendSummary) {
    setDetail((prev) =>
      prev
        ? { ...prev, sends: prev.sends.map((s) => (s.id === updated.id ? updated : s)) }
        : prev
    );
  }

  if (loading && !detail) {
    return (
      <p className="text-sm" style={{ color: "var(--muted)" }}>
        Loading…
      </p>
    );
  }
  if (!detail) {
    return (
      <div className="space-y-3">
        <p className="text-sm" style={{ color: "var(--accent-dark)" }}>
          {error ?? "Campaign not found."}
        </p>
        <Link to="/campaigns" className="text-sm underline" style={{ color: "var(--accent)" }}>
          Back to campaigns
        </Link>
      </div>
    );
  }

  const skippedEntries = Object.entries(detail.skipped);
  // Grouped by reason, so "3 unsubscribed from email" reads better than three
  // separate lines naming customers the owner can no longer contact anyway.
  const skippedSummary = Object.entries(
    skippedEntries.reduce<Record<string, number>>((acc, [, reason]) => {
      acc[reason] = (acc[reason] ?? 0) + 1;
      return acc;
    }, {})
  )
    .map(([reason, count]) => `${count} ${readableSkip(reason)}`)
    .join(" · ");

  return (
    <div className="space-y-6">
      <div className="anim-fade-up">
        <Link to="/campaigns" className="text-xs underline" style={{ color: "var(--muted)" }}>
          ← All campaigns
        </Link>
        <h1
          className="mt-2 text-[34px] font-bold tracking-tight"
          style={{ color: "var(--ink)" }}
        >
          {detail.name}
        </h1>
        <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
          {detail.channel === "email" ? "Email" : "Text"} ·{" "}
          {detail.status.replace(/_/g, " ")} · {detail.stats.total} recipient
          {detail.stats.total === 1 ? "" : "s"}
          {detail.incentive && ` · offer: ${detail.incentive}`}
        </p>
      </div>

      <div
        className="anim-fade-up flex flex-wrap gap-7 rounded-[20px] p-6"
        style={{
          animationDelay: "0.05s",
          background: "linear-gradient(115deg,#3B2A20,#4A3527)",
          color: "var(--cream-text)",
        }}
      >
        <Stat label="Awaiting you" value={String(detail.stats.pending)} light />
        <Stat label="Sent" value={String(detail.stats.sent)} light />
        <Stat label="Opened" value={String(detail.stats.opened)} light />
        <Stat label="Clicked" value={String(detail.stats.clicked)} light />
        <Stat label="Came back" value={String(detail.stats.recovered)} light />
        <Stat
          label="Revenue saved"
          value={formatCurrency(detail.stats.revenue_recovered)}
          light
        />
      </div>

      {experiment && (
        <section
          className="anim-fade-up rounded-[20px] border p-6"
          style={{ borderColor: "var(--line)", background: "var(--card)" }}
        >
          <h2 className="font-display text-[18px] font-bold" style={{ color: "var(--ink)" }}>
            A/B result
          </h2>
          <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
            {experiment.verdict}
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {[experiment.a, experiment.b].map((arm) => (
              <div
                key={arm.variant}
                className="rounded-xl border p-4"
                style={{
                  borderColor:
                    experiment.winner === arm.variant ? "var(--accent)" : "var(--line-soft)",
                }}
              >
                <p className="text-xs font-bold uppercase" style={{ color: "var(--muted-2)" }}>
                  Version {arm.variant}
                  {experiment.winner === arm.variant && " · winner"}
                </p>
                <p className="mt-1 text-[22px] font-bold" style={{ color: "var(--ink)" }}>
                  {Math.round(arm.recovery_rate * 100)}%
                </p>
                <p className="text-xs" style={{ color: "var(--muted)" }}>
                  {arm.recovered} of {arm.sent} came back ·{" "}
                  {formatCurrency(arm.revenue_recovered)}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      {skippedEntries.length > 0 && (
        <div
          className="anim-fade-up rounded-2xl border px-5 py-4 text-sm"
          style={{ borderColor: "var(--line)", background: "var(--surface-2)" }}
        >
          <p className="font-semibold" style={{ color: "var(--ink)" }}>
            {skippedEntries.length} {skippedEntries.length === 1 ? "person was" : "people were"}{" "}
            left out
          </p>
          <p className="mt-1" style={{ color: "var(--muted)" }}>
            {skippedSummary}
          </p>
        </div>
      )}

      {notice && (
        <p
          className="rounded-2xl px-5 py-3 text-sm"
          style={{ background: "var(--surface-2)", color: "var(--ink)" }}
        >
          {notice}
        </p>
      )}
      {error && (
        <p className="text-sm" style={{ color: "var(--accent-dark)" }}>
          {error}
        </p>
      )}

      {pending.length > 0 && (
        <div className="anim-fade-up flex flex-wrap items-center gap-3">
          <button
            onClick={approveAll}
            disabled={approving}
            className="rounded-full px-6 py-2.5 text-sm font-semibold text-white transition hover:-translate-y-px disabled:opacity-50"
            style={{ background: "var(--accent)" }}
          >
            {approving
              ? "Sending…"
              : `Approve and send all ${pending.length}`}
          </button>
          <span className="text-xs" style={{ color: "var(--muted-2)" }}>
            Read them first — you can edit or drop any of them below.
          </span>
        </div>
      )}

      <section className="space-y-3">
        {detail.sends.map((send) => (
          <SendCard
            key={send.id}
            send={send}
            channel={detail.channel}
            onChange={replaceSend}
          />
        ))}
      </section>
    </div>
  );
}

function SendCard({
  send,
  channel,
  onChange,
}: {
  send: CampaignSendSummary;
  channel: AutomationChannel;
  onChange: (s: CampaignSendSummary) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState(send.subject ?? "");
  const [body, setBody] = useState(send.body);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const editable = send.status === "pending";

  async function run(action: () => Promise<CampaignSendSummary>) {
    setBusy(true);
    setError(null);
    try {
      const updated = await action();
      onChange(updated);
      setSubject(updated.subject ?? "");
      setBody(updated.body);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't work");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article
      className="rounded-2xl border p-5"
      style={{
        borderColor: "var(--line)",
        background: send.status === "skipped" ? "var(--surface-2)" : "var(--card)",
      }}
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-semibold" style={{ color: "var(--ink)" }}>
            {send.customer_name}
            {send.variant && (
              <span
                className="ml-2 rounded-full px-2 py-0.5 text-[10px] font-bold"
                style={{ background: "var(--surface-2)", color: "var(--muted)" }}
              >
                Version {send.variant}
              </span>
            )}
          </p>
          <p className="mt-0.5 text-xs" style={{ color: "var(--muted-2)" }}>
            {send.status === "pending"
              ? "Waiting for your approval"
              : send.status === "skipped"
                ? `Skipped — ${readableSkip(send.failure_reason ?? "")}`
                : send.status === "failed"
                  ? `Failed — ${send.failure_reason ?? "unknown reason"}`
                  : `Sent${send.opened ? " · opened" : ""}${send.clicked ? " · clicked" : ""}`}
            {send.generated_by === "owner_edited" && " · you edited this"}
            {send.generated_by === "fallback" && " · written from a template"}
          </p>
        </div>
        {editable && (
          <div className="flex gap-2">
            {!editing && (
              <SmallButton onClick={() => setEditing(true)} disabled={busy}>
                Edit
              </SmallButton>
            )}
            <SmallButton
              onClick={() => run(() => api.regenerateCampaignSend(send.id))}
              disabled={busy}
            >
              Rewrite
            </SmallButton>
            <SmallButton
              onClick={() => run(() => api.cancelCampaignSend(send.id))}
              disabled={busy}
            >
              Drop
            </SmallButton>
          </div>
        )}
      </header>

      {editing ? (
        <div className="mt-3 space-y-2">
          {channel === "email" && (
            <input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="Subject"
              className="w-full rounded-xl border px-3 py-2 text-sm outline-none focus:border-[#B4532A]"
              style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
            />
          )}
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={6}
            className="w-full resize-y rounded-xl border px-3 py-2 text-sm outline-none focus:border-[#B4532A]"
            style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
          />
          <div className="flex gap-2">
            <SmallButton
              onClick={() =>
                run(() =>
                  api.editCampaignSend(send.id, {
                    subject: channel === "email" ? subject : undefined,
                    body,
                  })
                )
              }
              disabled={busy || !body.trim()}
              primary
            >
              Save
            </SmallButton>
            <SmallButton
              onClick={() => {
                setEditing(false);
                setSubject(send.subject ?? "");
                setBody(send.body);
              }}
              disabled={busy}
            >
              Cancel
            </SmallButton>
          </div>
        </div>
      ) : (
        <div className="mt-3">
          {send.subject && (
            <p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
              {send.subject}
            </p>
          )}
          <p
            className="mt-1 whitespace-pre-wrap text-sm leading-relaxed"
            style={{ color: "var(--muted-body, var(--muted))" }}
          >
            {send.body || "No message was written for this one."}
          </p>
        </div>
      )}

      {error && (
        <p className="mt-2 text-xs" style={{ color: "var(--accent-dark)" }}>
          {error}
        </p>
      )}
    </article>
  );
}

// -- Small shared bits --------------------------------------------------------

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span
        className="mb-1.5 block text-xs font-bold uppercase tracking-wide"
        style={{ color: "var(--muted-2)" }}
      >
        {label}
      </span>
      {children}
    </label>
  );
}

function Stat({
  label,
  value,
  light,
}: {
  label: string;
  value: string;
  light?: boolean;
}) {
  return (
    <div>
      <p
        className="text-[11px] font-bold uppercase tracking-wide"
        style={{ color: light ? "rgba(244,236,224,.65)" : "var(--muted-2)" }}
      >
        {label}
      </p>
      <p
        className="font-display text-[20px] font-bold"
        style={{ color: light ? "var(--cream-text)" : "var(--ink)" }}
      >
        {value}
      </p>
    </div>
  );
}

function SmallButton({
  onClick,
  disabled,
  primary,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="rounded-full px-3.5 py-1.5 text-xs font-semibold transition disabled:opacity-40"
      style={
        primary
          ? { background: "var(--accent)", color: "#fff" }
          : { background: "var(--surface-2)", color: "var(--muted)" }
      }
    >
      {children}
    </button>
  );
}
