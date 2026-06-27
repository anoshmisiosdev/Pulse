import { usePulse, type ActivityItem, type AutomationRule, type Mode } from "../context/PulseContext";
import { SEGMENTS } from "../lib/segments";

const MODES: { id: Mode; label: string; blurb: string }[] = [
  { id: "suggest", label: "Suggest", blurb: "Pulse flags who to contact. You write & send." },
  { id: "approve", label: "Approve", blurb: "Pulse drafts everything. You tap approve to send." },
  { id: "auto", label: "Autopilot", blurb: "Pulse drafts and sends automatically, within guardrails." },
];

export default function Automations() {
  const { rules, setRuleMode, toggleRule, activity, markContacted } = usePulse();

  const sent = activity.filter((a) => a.status === "sent").length;
  const awaiting = activity.filter((a) => a.status === "awaiting_approval").length;
  const suggested = activity.filter((a) => a.status === "suggested").length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-4xl font-extrabold tracking-tight">Automations</h1>
        <p className="mt-1 text-slate-500">
          Set it once — Pulse watches every customer and acts the moment churn risk rises.
        </p>
      </div>

      <div className="glass grid grid-cols-3 gap-4 p-6">
        <Metric n={sent} label="Sent on autopilot" color="#10b981" />
        <Metric n={awaiting} label="Awaiting your approval" color="#f59e0b" />
        <Metric n={suggested} label="Suggested for review" color="#6366f1" />
      </div>

      <div className="space-y-4">
        <h2 className="font-display text-lg font-bold">Rules</h2>
        {rules.map((rule) => (
          <RuleCard
            key={rule.id}
            rule={rule}
            onMode={(m) => setRuleMode(rule.id, m)}
            onToggle={() => toggleRule(rule.id)}
          />
        ))}
      </div>

      <div className="space-y-3">
        <h2 className="font-display text-lg font-bold">What Pulse did for you</h2>
        <div className="glass divide-y divide-slate-100 overflow-hidden">
          {activity.length === 0 && (
            <p className="px-5 py-8 text-sm text-slate-400">
              No active rules. Turn one on above and Pulse will start working.
            </p>
          )}
          {activity.map((a) => (
            <ActivityRow key={a.id} item={a} onApprove={() => markContacted(a.customerId)} />
          ))}
        </div>
      </div>
    </div>
  );
}

function RuleCard({
  rule, onMode, onToggle,
}: { rule: AutomationRule; onMode: (m: Mode) => void; onToggle: () => void }) {
  return (
    <div className={`glass p-5 ${rule.enabled ? "" : "opacity-60"}`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="font-display text-lg font-bold text-slate-900">{rule.name}</p>
          <p className="mt-1 text-sm text-slate-500">
            Targets{" "}
            {rule.segments.map((s, i) => (
              <span key={s}>
                <span className="font-medium" style={{ color: SEGMENTS[s].color }}>{SEGMENTS[s].label}</span>
                {i < rule.segments.length - 1 ? ", " : ""}
              </span>
            ))}{" "}
            · via {rule.channel} · offers {rule.incentive}
          </p>
        </div>
        <button
          onClick={onToggle}
          className={`relative h-6 w-11 shrink-0 rounded-full transition ${rule.enabled ? "bg-emerald-500" : "bg-slate-300"}`}
          aria-label="Toggle rule"
        >
          <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${rule.enabled ? "left-[22px]" : "left-0.5"}`} />
        </button>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2">
        {MODES.map((m) => (
          <button
            key={m.id}
            onClick={() => onMode(m.id)}
            disabled={!rule.enabled}
            className={`rounded-xl border p-3 text-left transition disabled:cursor-not-allowed ${
              rule.mode === m.id
                ? "border-transparent bg-primary text-white shadow-sm"
                : "border-slate-200 bg-white/50 text-slate-600 hover:border-slate-300"
            }`}
          >
            <p className="text-sm font-semibold">{m.label}</p>
            <p className={`mt-0.5 text-xs ${rule.mode === m.id ? "text-white/80" : "text-slate-400"}`}>
              {m.blurb}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
}

function ActivityRow({ item, onApprove }: { item: ActivityItem; onApprove: () => void }) {
  const status = {
    sent: { text: `Sent win-back ${item.channel}`, color: "text-emerald-600", dot: "#10b981" },
    awaiting_approval: { text: "Drafted — awaiting approval", color: "text-amber-600", dot: "#f59e0b" },
    suggested: { text: "Flagged for review", color: "text-indigo-600", dot: "#6366f1" },
  }[item.status];

  return (
    <div className="flex items-center justify-between gap-4 px-5 py-3.5">
      <div className="flex min-w-0 items-center gap-3">
        <span className="mt-1 h-2 w-2 shrink-0 rounded-full" style={{ background: status.dot }} />
        <div className="min-w-0">
          <p className="truncate text-sm">
            <span className={`font-semibold ${status.color}`}>{status.text}</span>{" "}
            <span className="text-slate-700">to {item.name}</span>
          </p>
          <p className="truncate text-xs text-slate-400">{item.reason}</p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        {item.status === "awaiting_approval" && (
          <button onClick={onApprove} className="rounded-lg bg-primary px-3 py-1 text-xs font-semibold text-white">
            Approve
          </button>
        )}
        <span className="text-xs text-slate-400">{item.when}</span>
      </div>
    </div>
  );
}

function Metric({ n, label, color }: { n: number; label: string; color: string }) {
  return (
    <div className="text-center">
      <p className="font-display text-3xl font-bold" style={{ color }}>{n}</p>
      <p className="mt-1 text-xs text-slate-500">{label}</p>
    </div>
  );
}
