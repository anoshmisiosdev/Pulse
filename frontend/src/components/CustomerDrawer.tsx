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
      <div className="flex-1 bg-slate-900/20" />
      <aside
        className="h-full w-full max-w-md animate-slide-in overflow-y-auto glass-strong scroll-thin p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <div>
            <h2 className="font-display text-2xl font-bold">{customer.name}</h2>
            <p className="text-sm text-slate-500">{customer.email}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>

        <div className="mt-3 flex items-center gap-3">
          <span
            className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${meta.bg}`}
          >
            {meta.health} {customer.score}
          </span>
          <span className="flex items-center gap-1 text-sm text-slate-500">
            <TrendIcon /> {customer.trend_pct < 0 ? `down ${Math.abs(customer.trend_pct)}%` : "steady"}
          </span>
        </div>

        {/* Quick facts */}
        <div className="mt-5 grid grid-cols-3 gap-2 text-center">
          <Fact label="At risk" value={formatCurrency(customer.estimated_annual_value)} />
          <Fact label="Visits" value={String(customer.visit_count)} />
          <Fact label="Last seen" value={relativeDays(customer.days_since_last_visit)} />
        </div>

        {/* Churn agent analysis */}
        <div className="mt-5 rounded-2xl border-l-4 border-red-400 bg-white/60 p-4">
          <span className="rounded-full bg-cyan-50 px-2 py-0.5 text-xs font-semibold text-cyan-700">
            Claude: Churn Agent
          </span>
          <p className="mt-2 text-sm text-slate-700">
            {(customer.pattern && CHURN_NARRATIVE[customer.pattern]) ??
              "Visiting on a healthy cadence — keep doing what you're doing."}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {customer.pattern && (
              <Tag className="bg-amber-100 text-amber-700">
                ⚡ {PATTERNS[customer.pattern].toLowerCase()}
              </Tag>
            )}
            <Tag className="bg-emerald-100 text-emerald-700">{customer.confidence} confidence</Tag>
            {customer.favorite_item && (
              <Tag className="bg-violet-100 text-violet-700">loves {customer.favorite_item}</Tag>
            )}
          </div>
        </div>

        {/* Outreach generation */}
        <div className="mt-5">
          <div className="grid grid-cols-3 gap-2">
            <ChannelBtn active={channel === "email"} onClick={() => generate("email")} label="Email" icon={<MailIcon />} />
            <ChannelBtn active={channel === "phone"} onClick={() => generate("phone")} label="Phone Script" icon={<PhoneIcon />} />
            <ChannelBtn active={channel === "offer"} onClick={() => generate("offer")} label="Special Offer" icon={<GiftIcon />} />
          </div>

          <div className="mt-3 min-h-[120px] rounded-2xl bg-white/60 p-4 text-sm">
            {!copy && !loading && (
              <p className="text-slate-400">Pick a channel and Pulse will draft personalized outreach.</p>
            )}
            {loading && (
              <p className="flex items-center gap-2 text-slate-400">
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-300 border-t-cyan-500" />
                <span className="rounded bg-cyan-50 px-1.5 py-0.5 text-xs text-cyan-700">Churn</span>
                <span className="rounded bg-violet-50 px-1.5 py-0.5 text-xs text-violet-700">Synthesis</span>
                AI writing…
              </p>
            )}
            {copy && (
              <>
                {copy.subject && (
                  <p className="mb-2 font-medium text-slate-800">Subject: {copy.subject}</p>
                )}
                <p className="whitespace-pre-wrap text-slate-700">{copy.body}</p>
                <p className="mt-3 text-xs text-slate-400">
                  {copy.generated_by === "claude"
                    ? `Generated by ${copy.model}`
                    : "Static fallback — set ANTHROPIC_API_KEY for live AI copy"}
                </p>
              </>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="mt-5 grid grid-cols-2 gap-3">
          <button
            onClick={() => markContacted(customer.customer_id)}
            disabled={contacted}
            className="flex items-center justify-center gap-2 rounded-xl border border-cyan-300 px-4 py-2.5 text-sm font-semibold text-cyan-700 hover:bg-cyan-50 disabled:opacity-50"
          >
            <SendIcon /> {contacted ? "Contacted ✓" : "Contacted"}
          </button>
          <button
            onClick={() => {
              markWonBack(customer);
              onClose();
            }}
            className="flex items-center justify-center gap-2 rounded-xl border border-amber-300 px-4 py-2.5 text-sm font-semibold text-amber-700 hover:bg-amber-50"
          >
            <ChatIcon /> Won Back
          </button>
        </div>
      </aside>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-white/60 px-2 py-3">
      <p className="font-display text-base font-bold text-slate-800">{value}</p>
      <p className="text-xs text-slate-500">{label}</p>
    </div>
  );
}
function Tag({ children, className }: { children: React.ReactNode; className: string }) {
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>{children}</span>;
}
function ChannelBtn({
  active, onClick, label, icon,
}: { active: boolean; onClick: () => void; label: string; icon: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`flex flex-col items-center gap-1 rounded-xl border px-2 py-2.5 text-xs font-semibold transition ${
        active ? "border-transparent bg-primary text-white" : "border-slate-200 bg-white/60 text-slate-600 hover:border-slate-300"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

function TrendIcon() {
  return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="22 17 13.5 8.5 8.5 13.5 2 7" /><polyline points="16 17 22 17 22 11" /></svg>;
}
function MailIcon() { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="4" width="20" height="16" rx="2" /><path d="m22 7-10 5L2 7" /></svg>; }
function PhoneIcon() { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92Z" /></svg>; }
function GiftIcon() { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="20 12 20 22 4 22 4 12" /><rect x="2" y="7" width="20" height="5" /><line x1="12" y1="22" x2="12" y2="7" /><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z" /><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z" /></svg>; }
function SendIcon() { return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" /></svg>; }
function ChatIcon() { return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>; }
