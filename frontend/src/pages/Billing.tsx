import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  api,
  formatCurrency,
  type DeletionScope,
  type DigestPreview,
  type Plans,
  type Subscription,
  type Tier,
  type UsageMeter,
} from "../lib/api";

/** Plan, usage, and the account's data controls.
 *
 * The usage meters here are the visible half of the "nag at 90%, never
 * hard-block" rule: going over a customer limit shows a loud message and an
 * upgrade button, and changes nothing about what the owner can do. The only
 * things a plan actually gates are SMS and hands-off automation, and those are
 * labelled as such rather than mixed in with the volume numbers.
 */

const SCOPE_COPY: Record<DeletionScope, { label: string; detail: string }> = {
  retention: {
    label: "Customer data only",
    detail:
      "Customers, visits, payments, scores and campaign history. Keeps your brand kit, notes and assistant history. Use this to re-import and start the scores over.",
  },
  knowledge: {
    label: "Business notes",
    detail: "The notes you've taught Churnary for personalizing campaigns.",
  },
  assistant: {
    label: "Assistant conversations",
    detail: "Every chat thread with the assistant.",
  },
  social: {
    label: "Social presence",
    detail: "Brand kit, company brain, social campaigns, posts and comments.",
  },
  all: {
    label: "Everything",
    detail:
      "All of the above. Your login and billing plan stay so you can keep using the account — cancel in the billing portal if you want to stop paying.",
  },
};

export default function Billing() {
  const [params, setParams] = useSearchParams();
  const [plans, setPlans] = useState<Plans | null>(null);
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyTier, setBusyTier] = useState<string | null>(null);
  const [annual, setAnnual] = useState(false);

  const checkoutResult = params.get("checkout");

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([api.plans(), api.subscription()])
      .then(([p, s]) => {
        setPlans(p);
        setSubscription(s);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load billing"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  async function checkout(tier: Tier) {
    setBusyTier(tier.name);
    setError(null);
    try {
      const { url } = await api.startCheckout({ tier: tier.name, annual });
      // Stripe's hosted page — a full navigation, not a popup, so a blocked
      // popup can't silently strand the owner mid-upgrade.
      window.location.assign(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start checkout");
      setBusyTier(null);
    }
  }

  async function openPortal() {
    setBusyTier("portal");
    setError(null);
    try {
      const { url } = await api.billingPortal();
      window.location.assign(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't open the billing portal");
      setBusyTier(null);
    }
  }

  return (
    <div className="space-y-7">
      <div className="anim-fade-up">
        <h1 className="text-[38px] font-bold tracking-tight" style={{ color: "var(--ink)" }}>
          Plan &amp; billing
        </h1>
        <p className="mt-1 italic" style={{ color: "var(--muted)", fontSize: "15.5px" }}>
          What you're on, what you're using, and your data.
        </p>
      </div>

      {checkoutResult === "success" && (
        <Banner tone="good" onDismiss={() => setParams({})}>
          Payment went through. Your plan updates as soon as Stripe confirms it — refresh
          in a moment if it still shows the old one.
        </Banner>
      )}
      {checkoutResult === "canceled" && (
        <Banner tone="neutral" onDismiss={() => setParams({})}>
          Checkout cancelled. Nothing was charged.
        </Banner>
      )}

      {error && (
        <p className="text-sm" style={{ color: "var(--accent-dark)" }}>
          {error}
        </p>
      )}

      {loading && !subscription ? (
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          Loading…
        </p>
      ) : (
        subscription && (
          <>
            <CurrentPlan
              subscription={subscription}
              onPortal={openPortal}
              busy={busyTier === "portal"}
            />

            {!subscription.billing_configured && (
              <Banner tone="neutral">
                Billing isn't connected yet, so checkout is unavailable. Everything else
                works — this needs Stripe keys and price ids in the environment.
              </Banner>
            )}

            {plans && (
              <section className="anim-fade-up">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h2
                    className="font-display text-[22px] font-bold"
                    style={{ color: "var(--ink)" }}
                  >
                    Plans
                  </h2>
                  <label
                    className="flex items-center gap-2 text-sm"
                    style={{ color: "var(--muted)" }}
                  >
                    <input
                      type="checkbox"
                      checked={annual}
                      onChange={(e) => setAnnual(e.target.checked)}
                    />
                    Pay yearly — two months free
                  </label>
                </div>
                <div className="mt-4 grid gap-4 lg:grid-cols-3">
                  {plans.tiers.map((tier) => (
                    <PlanCard
                      key={tier.name}
                      tier={tier}
                      annual={annual}
                      current={tier.name === subscription.tier}
                      trialDays={plans.trial_days}
                      disabled={!subscription.billing_configured}
                      busy={busyTier === tier.name}
                      onChoose={() => checkout(tier)}
                    />
                  ))}
                </div>
              </section>
            )}
          </>
        )
      )}

      <DigestCard />
      <DataControls onChanged={load} />
    </div>
  );
}

function CurrentPlan({
  subscription,
  onPortal,
  busy,
}: {
  subscription: Subscription;
  onPortal: () => void;
  busy: boolean;
}) {
  const statusLabel: Record<string, string> = {
    trialing: subscription.trial_days_left
      ? `Trial — ${subscription.trial_days_left} day${subscription.trial_days_left === 1 ? "" : "s"} left`
      : "Trial",
    active: "Active",
    past_due: "Payment failed",
    canceled: "Cancelled",
    trial_expired: "Trial ended",
  };

  return (
    <section
      className="anim-fade-up rounded-[20px] p-7"
      style={{
        animationDelay: "0.05s",
        background: "linear-gradient(115deg,#3B2A20,#4A3527)",
        color: "var(--cream-text)",
      }}
    >
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div>
          <p
            className="text-[11px] font-bold uppercase tracking-wide"
            style={{ color: "rgba(244,236,224,.65)" }}
          >
            Current plan
          </p>
          <p className="font-display text-[28px] font-bold capitalize">
            {subscription.tier}
          </p>
          <p className="mt-1 text-sm" style={{ color: "rgba(244,236,224,.8)" }}>
            {statusLabel[subscription.status] ?? subscription.status}
            {subscription.current_period_end &&
              ` · renews ${new Date(subscription.current_period_end).toLocaleDateString()}`}
          </p>
        </div>
        {subscription.has_payment_method && (
          <button
            onClick={onPortal}
            disabled={busy}
            className="rounded-full px-5 py-2 text-sm font-semibold transition hover:-translate-y-px disabled:opacity-50"
            style={{ background: "rgba(244,236,224,.15)", color: "var(--cream-text)" }}
          >
            {busy ? "Opening…" : "Manage billing"}
          </button>
        )}
      </div>

      {subscription.status === "past_due" && (
        <p
          className="mt-4 rounded-xl px-4 py-3 text-sm"
          style={{ background: "rgba(244,236,224,.12)" }}
        >
          Your last payment didn't go through. Nothing has been turned off — update your
          card in the billing portal when you get a chance.
        </p>
      )}

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        {subscription.meters.map((meter) => (
          <MeterBar key={meter.key} meter={meter} />
        ))}
      </div>

      <div className="mt-5 flex flex-wrap gap-4 text-xs" style={{ color: "rgba(244,236,224,.75)" }}>
        <span>Email: included</span>
        <span>
          Text messages: {subscription.channels.includes("sms") ? "included" : "not on this plan"}
        </span>
        <span>
          Hands-off automation: {subscription.automation ? "included" : "not on this plan"}
        </span>
      </div>
    </section>
  );
}

function MeterBar({ meter }: { meter: UsageMeter }) {
  const pct =
    meter.limit && meter.limit > 0
      ? Math.min(100, Math.round((meter.used / meter.limit) * 100))
      : 0;
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span style={{ color: "rgba(244,236,224,.8)" }}>{meter.label}</span>
        <span className="font-semibold">
          {meter.used.toLocaleString()}
          {meter.limit === null ? " · unlimited" : ` / ${meter.limit.toLocaleString()}`}
        </span>
      </div>
      {meter.limit !== null && (
        <div
          className="mt-1.5 h-[7px] overflow-hidden rounded-full"
          style={{ background: "rgba(244,236,224,.18)" }}
        >
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${pct}%`,
              background:
                meter.severity === "over"
                  ? "#E08A5F"
                  : meter.severity === "approaching"
                    ? "#D9A14F"
                    : "rgba(244,236,224,.7)",
            }}
          />
        </div>
      )}
      {meter.message && (
        <p className="mt-1.5 text-xs" style={{ color: "rgba(244,236,224,.75)" }}>
          {meter.message}
        </p>
      )}
    </div>
  );
}

function PlanCard({
  tier,
  annual,
  current,
  trialDays,
  disabled,
  busy,
  onChoose,
}: {
  tier: Tier;
  annual: boolean;
  current: boolean;
  trialDays: number;
  disabled: boolean;
  busy: boolean;
  onChoose: () => void;
}) {
  const price = annual ? tier.annual_price_usd : tier.monthly_price_usd;
  return (
    <article
      className="flex flex-col rounded-[20px] border p-6"
      style={{
        borderColor: current ? "var(--accent)" : "var(--line)",
        background: "var(--card)",
      }}
    >
      <p className="font-display text-[20px] font-bold" style={{ color: "var(--ink)" }}>
        {tier.label}
      </p>
      <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
        {tier.blurb}
      </p>
      <p className="mt-4">
        <span className="font-display text-[32px] font-bold" style={{ color: "var(--ink)" }}>
          {formatCurrency(price)}
        </span>
        <span className="text-sm" style={{ color: "var(--muted-2)" }}>
          {annual ? "/year" : "/month"}
        </span>
      </p>
      <ul className="mt-4 flex-1 space-y-1.5 text-sm" style={{ color: "var(--muted)" }}>
        {tier.highlights.map((h) => (
          <li key={h}>· {h}</li>
        ))}
      </ul>
      {current ? (
        <p
          className="mt-5 rounded-full px-5 py-2 text-center text-sm font-semibold"
          style={{ background: "var(--surface-2)", color: "var(--muted)" }}
        >
          Your current plan
        </p>
      ) : (
        <button
          onClick={onChoose}
          disabled={disabled || busy}
          className="mt-5 rounded-full px-5 py-2 text-sm font-semibold text-white transition hover:-translate-y-px disabled:opacity-40"
          style={{ background: "var(--accent)" }}
        >
          {busy ? "Opening Stripe…" : `Choose ${tier.label}`}
        </button>
      )}
      {!current && !disabled && (
        <p className="mt-2 text-center text-xs" style={{ color: "var(--muted-2)" }}>
          {trialDays}-day trial · card required
        </p>
      )}
    </article>
  );
}

function DigestCard() {
  const [preview, setPreview] = useState<DigestPreview | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  async function loadPreview() {
    setOpen(true);
    setBusy(true);
    setNotice(null);
    try {
      setPreview(await api.digestPreview());
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Couldn't build the preview");
    } finally {
      setBusy(false);
    }
  }

  async function sendNow() {
    setBusy(true);
    setNotice(null);
    try {
      const result = await api.sendDigestNow();
      setNotice(result.message);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Couldn't send it");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="anim-fade-up rounded-[20px] border p-6"
      style={{ borderColor: "var(--line)", background: "var(--card)" }}
    >
      <h2 className="font-display text-[20px] font-bold" style={{ color: "var(--ink)" }}>
        Weekly summary email
      </h2>
      <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
        Once a week, what came back and what's at risk — sent to you, never to your
        customers. Quiet weeks don't get an email.
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          onClick={loadPreview}
          disabled={busy}
          className="rounded-full px-5 py-2 text-sm font-semibold transition disabled:opacity-50"
          style={{ background: "var(--surface-2)", color: "var(--muted)" }}
        >
          {busy && !preview ? "Building…" : "Preview this week's"}
        </button>
        <button
          onClick={sendNow}
          disabled={busy}
          className="rounded-full px-5 py-2 text-sm font-semibold text-white transition disabled:opacity-50"
          style={{ background: "var(--accent)" }}
        >
          Send it to me now
        </button>
      </div>

      {notice && (
        <p className="mt-3 text-sm" style={{ color: "var(--ink)" }}>
          {notice}
        </p>
      )}

      {open && preview && (
        <div
          className="mt-4 rounded-xl border p-4"
          style={{ borderColor: "var(--line-soft)", background: "var(--surface-2)" }}
        >
          <p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
            {preview.subject}
          </p>
          <p
            className="mt-2 whitespace-pre-wrap text-sm leading-relaxed"
            style={{ color: "var(--muted)" }}
          >
            {preview.body}
          </p>
          <p className="mt-3 text-xs" style={{ color: "var(--muted-2)" }}>
            {preview.would_send
              ? `Would send to ${preview.recipients.join(", ") || "nobody — no owner email on file"}`
              : "Nothing to report this week, so this wouldn't be sent."}
            {preview.generated_by === "fallback" && " · written from a template"}
          </p>
        </div>
      )}
    </section>
  );
}

function DataControls({ onChanged }: { onChanged: () => void }) {
  const [scope, setScope] = useState<DeletionScope>("retention");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function download() {
    setBusy(true);
    setError(null);
    try {
      const blob = await api.exportData();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "churnary-data-export.json";
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't export your data");
    } finally {
      setBusy(false);
    }
  }

  async function erase() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const report = await api.deleteData(scope, confirm);
      const detail = Object.entries(report.deleted)
        .map(([table, count]) => `${count} ${table.replace(/_/g, " ")}`)
        .join(", ");
      setNotice(
        report.rows_deleted
          ? `Deleted ${report.rows_deleted} records: ${detail}.`
          : "There was nothing to delete."
      );
      setConfirm("");
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't delete that");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="anim-fade-up rounded-[20px] border p-6"
      style={{ borderColor: "var(--line)", background: "var(--card)" }}
    >
      <h2 className="font-display text-[20px] font-bold" style={{ color: "var(--ink)" }}>
        Your data
      </h2>
      <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
        Take a copy whenever you want, and delete it whenever you want.
      </p>

      <button
        onClick={download}
        disabled={busy}
        className="mt-4 rounded-full px-5 py-2 text-sm font-semibold transition disabled:opacity-50"
        style={{ background: "var(--surface-2)", color: "var(--muted)" }}
      >
        Download everything (JSON)
      </button>

      <div className="mt-6 border-t pt-5" style={{ borderColor: "var(--line-soft)" }}>
        <p className="text-sm font-bold" style={{ color: "var(--ink)" }}>
          Delete data
        </p>
        <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
          This can't be undone. There is no restore.
        </p>

        <div className="mt-3 space-y-2">
          {(Object.keys(SCOPE_COPY) as DeletionScope[]).map((key) => (
            <label key={key} className="flex items-start gap-2.5 text-sm">
              <input
                type="radio"
                name="scope"
                checked={scope === key}
                onChange={() => setScope(key)}
                className="mt-1"
              />
              <span>
                <span className="font-semibold" style={{ color: "var(--ink)" }}>
                  {SCOPE_COPY[key].label}
                </span>
                <span className="block text-xs" style={{ color: "var(--muted-2)" }}>
                  {SCOPE_COPY[key].detail}
                </span>
              </span>
            </label>
          ))}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <input
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder='Type "delete" to confirm'
            className="rounded-xl border px-3 py-2 text-sm outline-none focus:border-[#B4532A]"
            style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
          />
          <button
            onClick={erase}
            disabled={busy || confirm.trim().toLowerCase() !== "delete"}
            className="rounded-full px-5 py-2 text-sm font-semibold text-white transition disabled:opacity-40"
            style={{ background: "var(--accent-dark)" }}
          >
            {busy ? "Deleting…" : "Delete permanently"}
          </button>
        </div>

        {notice && (
          <p className="mt-3 text-sm" style={{ color: "var(--ink)" }}>
            {notice}
          </p>
        )}
        {error && (
          <p className="mt-3 text-sm" style={{ color: "var(--accent-dark)" }}>
            {error}
          </p>
        )}
      </div>
    </section>
  );
}

function Banner({
  tone,
  children,
  onDismiss,
}: {
  tone: "good" | "neutral";
  children: React.ReactNode;
  onDismiss?: () => void;
}) {
  return (
    <div
      className="anim-fade-up flex items-start justify-between gap-3 rounded-2xl border px-5 py-4 text-sm"
      style={{
        borderColor: tone === "good" ? "var(--accent)" : "var(--line)",
        background: "var(--surface-2)",
        color: "var(--ink)",
      }}
    >
      <p>{children}</p>
      {onDismiss && (
        <button
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 text-xs"
          style={{ color: "var(--muted-2)" }}
        >
          ✕
        </button>
      )}
    </div>
  );
}
