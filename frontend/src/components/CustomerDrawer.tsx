import { useState } from "react";
import { api, formatCurrency, relativeDays, type CustomerRisk, type GeneratedCopy } from "../lib/api";
import { SEGMENTS, PATTERNS } from "../lib/segments";
import { usePulse } from "../context/PulseContext";

type Channel = "email" | "phone" | "offer";

const CHURN_NARRATIVE: Record<string, string> = {
  stopped_suddenly:
    "Customer stopped visiting abruptly. This may indicate a negative experience or a major life event.",
  fading_away:
    "Visits have been tapering off gradually — engagement is quietly fading rather than stopping.",
  group_left:
    "Part of a cluster of customers who went quiet around the same time. Worth a personal touch.",
  not_enough_data:
    "Still a new customer — not enough history yet to be confident, but worth an early welcome.",
};

export default function CustomerDrawer({
  customer,
  onClose,
}: {
  customer: CustomerRisk;
  onClose: () => void;
}) {
  const { businessName, vertical, markContacted, markWonBack, contactedIds } = usePulse();
  const [channel, setChannel] = useState<Channel>("email");
  const [copy, setCopy] = useState<GeneratedCopy | null>(null);
  const [loading, setLoading] = useState(false);
  const meta = SEGMENTS[customer.segment];
  const contacted = contactedIds.has(customer.customer_id);
  const firstName = customer.name.split(" ")[0];

  async function generate(c: Channel) {
    setChannel(c);
    setLoading(true);
    setCopy(null);
    const incentiveByChannel =
      c === "offer" ? `a free ${customer.favorite_item ?? "drink"}` : undefined;
    const history = customer.favorite_item
      ? `Loves ${customer.favorite_item}. ${customer.visit_count} visits, last seen ${relativeDays(customer.days_since_last_visit)}.`
      : "";
    try {
      const result = await api.generateCampaign({
        business_name: businessName,
        business_type: vertical === "cafe" ? "coffee shop" : vertical,
        customer_name: customer.name,
        channel: c === "phone" ? "sms" : "email",
        incentive: incentiveByChannel,
        risk_reasons: customer.reasons,
        history_summary: history,
      });
      setCopy(result);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex animate-fade-in" onClick={onClose}>
      <div className="flex-1" style={{ background: "rgba(42,33,28,.4)" }} />
      <aside
        className="flex h-full w-full max-w-[420px] animate-slide-in flex-col overflow-y-auto scroll-thin"
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--surface)",
          boxShadow: "-24px 0 60px -20px rgba(42,33,28,.5)",
        }}
      >
        <div className="flex items-start justify-between border-b px-7 py-6" style={{ borderColor: "var(--border)" }}>
          <div>
            <h2 className="font-display text-2xl font-bold" style={{ color: "var(--ink)" }}>{customer.name}</h2>
            <p className="text-[13.5px]" style={{ color: "var(--muted-2)" }}>{customer.email}</p>
          </div>
          <button
            onClick={onClose}
            className="flex h-[34px] w-[34px] items-center justify-center rounded-full transition hover:brightness-95"
            style={{ background: "var(--border-soft)", color: "var(--muted)" }}
          >
            ✕
          </button>
        </div>

        <div className="flex-1 px-7 py-6">
          <span
            className="inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-[13.5px] font-bold"
            style={{ background: meta.badgeBg, color: meta.badgeText }}
          >
            <span className="h-2 w-2 rounded-full" style={{ background: meta.badgeText }} />
            {meta.health} · risk {customer.score}
          </span>

          <div className="mt-5 grid grid-cols-2 gap-3.5">
            <Tile label="Revenue at risk" value={formatCurrency(customer.estimated_annual_value)} valueColor="#A23B1E" />
            <Tile label="Last seen" value={relativeDays(customer.days_since_last_visit)} />
          </div>

          {customer.favorite_item && (
            <div className="mt-5 rounded-[14px] px-[18px] py-4" style={{ background: "var(--ink-strong)", color: "var(--cream-text)" }}>
              <p className="eyebrow mb-1.5" style={{ color: "var(--on-espresso-accent)", letterSpacing: "0.14em" }}>
                Favorite order
              </p>
              <p className="font-display text-xl font-semibold">{customer.favorite_item}</p>
            </div>
          )}

          {/* Why at risk */}
          <div className="mt-5 rounded-[14px] border-l-4 p-4" style={{ background: "var(--surface-2)", borderColor: "var(--accent)" }}>
            <span
              className="rounded-full px-2 py-0.5 text-xs font-semibold"
              style={{ background: "#F7E3DC", color: "#A23B1E" }}
            >
              Why at risk
            </span>
            <p className="mt-2 text-sm" style={{ color: "var(--ink-strong)" }}>
              {(customer.pattern && CHURN_NARRATIVE[customer.pattern]) ??
                "Visiting on a healthy cadence — keep doing what you're doing."}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {customer.pattern && (
                <Tag bg="#F4EAD1" color="#A9781F">⚡ {PATTERNS[customer.pattern].toLowerCase()}</Tag>
              )}
              <Tag bg="#E6EFDF" color="#4F7A40">{customer.confidence} confidence</Tag>
            </div>
          </div>

          {/* Take action */}
          <p className="eyebrow mt-6 mb-3" style={{ color: "var(--muted-2)", letterSpacing: "0.08em", fontSize: 12 }}>
            Take action
          </p>
          <div className="flex flex-col gap-2.5">
            <ActionBtn primary onClick={() => generate("email")}>
              ✉ Send a win-back message
            </ActionBtn>
            <ActionBtn onClick={() => generate("phone")}>☎ Call {firstName}</ActionBtn>
            <ActionBtn onClick={() => generate("offer")}>
              🎁 Offer a free {customer.favorite_item ?? "drink"}
            </ActionBtn>
          </div>

          {(loading || copy) && (
            <div className="mt-4 rounded-[14px] p-4 text-sm" style={{ background: "var(--surface-2)" }}>
              {loading && (
                <p className="flex items-center gap-2" style={{ color: "var(--muted-2)" }}>
                  <span
                    className="h-3 w-3 animate-spin rounded-full border-2"
                    style={{ borderColor: "var(--border)", borderTopColor: "var(--accent)" }}
                  />
                  Churnary is writing your {channel === "phone" ? "call script" : channel === "offer" ? "offer" : "email"}…
                </p>
              )}
              {copy && (
                <>
                  {copy.subject && (
                    <p className="mb-2 font-semibold" style={{ color: "var(--ink)" }}>Subject: {copy.subject}</p>
                  )}
                  <p className="whitespace-pre-wrap" style={{ color: "var(--ink-strong)" }}>{copy.body}</p>
                  <p className="mt-3 text-xs" style={{ color: "var(--muted-2)" }}>
                    {copy.generated_by === "claude"
                      ? `Generated by ${copy.model}`
                      : "Static fallback — set ANTHROPIC_API_KEY for live AI copy"}
                  </p>
                </>
              )}
            </div>
          )}

          <div className="mt-5 grid grid-cols-2 gap-3">
            <button
              onClick={() => markContacted(customer.customer_id)}
              disabled={contacted}
              className="rounded-full border px-4 py-2.5 text-sm font-semibold transition hover:brightness-95 disabled:opacity-50"
              style={{ borderColor: "var(--border)", color: "var(--ink-strong)", background: "var(--surface-2)" }}
            >
              {contacted ? "✓ Contacted" : "Mark contacted"}
            </button>
            <button
              onClick={() => {
                markWonBack(customer);
                onClose();
              }}
              className="rounded-full px-4 py-2.5 text-sm font-semibold text-white transition hover:brightness-95"
              style={{ background: "var(--sage)" }}
            >
              Won back 🎉
            </button>
          </div>
        </div>
      </aside>
    </div>
  );
}

function Tile({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <div className="rounded-[14px] p-4" style={{ background: "var(--surface-2)" }}>
      <p className="mb-1.5 text-xs" style={{ color: "var(--muted-2)" }}>{label}</p>
      <p className="font-display text-[22px] font-bold" style={{ color: valueColor ?? "var(--ink)" }}>{value}</p>
    </div>
  );
}

function Tag({ children, bg, color }: { children: React.ReactNode; bg: string; color: string }) {
  return (
    <span className="rounded-full px-2 py-0.5 text-xs font-medium" style={{ background: bg, color }}>
      {children}
    </span>
  );
}

function ActionBtn({ children, onClick, primary }: {
  children: React.ReactNode; onClick: () => void; primary?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-3 rounded-xl px-4 py-3.5 text-left text-sm font-semibold transition hover:brightness-95"
      style={
        primary
          ? { background: "var(--accent)", color: "#fff" }
          : { background: "var(--surface)", border: "1px solid var(--border)", color: "var(--ink-strong)" }
      }
    >
      {children}
    </button>
  );
}
