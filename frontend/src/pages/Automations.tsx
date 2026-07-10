import { useState } from "react";
import { usePulse, type ActivityItem, type AutomationRule, type Mode } from "../context/PulseContext";
import { SEGMENTS } from "../lib/segments";

const MODES: { id: Mode; label: string; blurb: string }[] = [
  { id: "suggest", label: "Suggest", blurb: "Churnary flags who to contact. You write & send." },
  { id: "approve", label: "Approve", blurb: "Churnary drafts everything. You tap approve to send." },
  { id: "auto", label: "Autopilot", blurb: "Churnary drafts and sends automatically, within guardrails." },
];

export default function Automations() {
  const { rules, setRuleMode, toggleRule, activity, markContacted } = usePulse();
  const [approved, setApproved] = useState<Record<string, boolean>>({});

  const approvedCount = activity.filter((a) => a.status === "awaiting_approval" && approved[a.id]).length;
  const sent = activity.filter((a) => a.status === "sent").length + approvedCount;
  const awaiting = activity.filter((a) => a.status === "awaiting_approval").length - approvedCount;
  const suggested = activity.filter((a) => a.status === "suggested").length;

  const approve = (a: ActivityItem) => {
    setApproved((m) => ({ ...m, [a.id]: true }));
    markContacted(a.customerId);
  };

  return (
    <div className="space-y-7">
      <div className="anim-fade-up">
        <h1 className="text-[38px] font-bold tracking-tight" style={{ color: "var(--ink)" }}>Automations</h1>
        <p className="mt-1 italic" style={{ color: "var(--muted)", fontSize: "15.5px" }}>
          Set it once — Churnary watches every customer and acts the moment churn risk rises.
        </p>
      </div>

      {/* stat bar */}
      <div className="glass anim-fade-up grid grid-cols-3 p-6" style={{ animationDelay: "0.05s" }}>
        <Metric n={sent} label="Sent on autopilot" color="#5C8A4A" divider />
        <Metric n={awaiting} label="Awaiting your approval" color="#C0632F" divider />
        <Metric n={suggested} label="Suggested for review" color="#A58C74" />
      </div>

      <div>
        <h2 className="font-display mb-4 text-xl font-semibold" style={{ color: "var(--ink)" }}>Rules</h2>
        <div className="flex flex-col gap-4">
          {rules.map((rule) => (
            <RuleCard
              key={rule.id}
              rule={rule}
              onMode={(m) => setRuleMode(rule.id, m)}
              onToggle={() => toggleRule(rule.id)}
            />
          ))}
        </div>
      </div>

      <div>
        <h2 className="font-display mb-4 text-xl font-semibold" style={{ color: "var(--ink)" }}>
          What Churnary did for you
        </h2>
        <div className="glass overflow-hidden">
          {activity.length === 0 && (
            <p className="px-6 py-8 text-sm" style={{ color: "var(--muted-2)" }}>
              No active rules. Turn one on above and Churnary will start working.
            </p>
          )}
          {activity.map((a) => (
            <FeedRow key={a.id} item={a} approved={!!approved[a.id]} onApprove={() => approve(a)} />
          ))}
        </div>
      </div>
    </div>
  );
}

function RuleCard({ rule, onMode, onToggle }: {
  rule: AutomationRule; onMode: (m: Mode) => void; onToggle: () => void;
}) {
  return (
    <div
      className="glass p-6"
      style={{ opacity: rule.enabled ? 1 : 0.62, transition: "opacity .25s ease", borderRadius: 18 }}
    >
      <div className="mb-[18px] flex items-start justify-between gap-4">
        <div>
          <p className="mb-1 text-[17px] font-bold" style={{ color: "var(--ink)" }}>{rule.name}</p>
          <p className="text-[13.5px]" style={{ color: "var(--muted)" }}>
            Targets {rule.segments.map((s) => SEGMENTS[s].label).join(", ")} · via {rule.channel} · offers {rule.incentive}
          </p>
        </div>
        <button
          onClick={onToggle}
          aria-label="Toggle rule"
          className="relative h-[27px] w-[46px] shrink-0 rounded-full"
          style={{ background: rule.enabled ? "var(--sage)" : "#D8C6B0", transition: "background .25s ease" }}
        >
          <span
            className="absolute top-[3px] h-[21px] w-[21px] rounded-full bg-white"
            style={{
              left: rule.enabled ? 22 : 3,
              boxShadow: "0 2px 5px rgba(0,0,0,.2)",
              transition: "left .25s cubic-bezier(.2,.8,.2,1)",
            }}
          />
        </button>
      </div>

      <div className="flex gap-2.5" style={{ pointerEvents: rule.enabled ? "auto" : "none" }}>
        {MODES.map((m) => {
          const active = rule.mode === m.id && rule.enabled;
          return (
            <button
              key={m.id}
              onClick={() => onMode(m.id)}
              className="flex-1 rounded-xl border p-4 text-left"
              style={{
                background: active ? "var(--ink-strong)" : "var(--surface-2)",
                color: active ? "var(--cream-text)" : "var(--ink-strong)",
                borderColor: active ? "var(--ink-strong)" : "var(--border)",
                transition: "all .2s ease",
                cursor: rule.enabled ? "pointer" : "default",
              }}
            >
              <p className="mb-1 text-sm font-bold">{m.label}</p>
              <p className="text-[11.5px] leading-snug" style={{ color: active ? "#CDB9A8" : "var(--muted-2)" }}>
                {m.blurb}
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function FeedRow({ item, approved, onApprove }: {
  item: ActivityItem; approved: boolean; onApprove: () => void;
}) {
  const effective = approved && item.status === "awaiting_approval" ? "sent" : item.status;
  const status = {
    sent: { text: `Sent win-back ${item.channel}`, color: "#4F7A40", dot: "#5C8A4A" },
    awaiting_approval: { text: "Drafted — awaiting approval", color: "#C0632F", dot: "#C0632F" },
    suggested: { text: "Flagged for review", color: "#A9781F", dot: "#D99A4E" },
  }[effective];

  return (
    <div className="flex items-center gap-3.5 border-b px-6 py-4" style={{ borderColor: "var(--border-soft)" }}>
      <span className="h-[9px] w-[9px] shrink-0 rounded-full" style={{ background: status.dot }} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14.5px]">
          <b style={{ color: status.color, fontWeight: 700 }}>{status.text}</b>{" "}
          <span style={{ color: "#6B5647" }}>to {item.name}</span>
        </p>
        <p className="mt-0.5 truncate text-[12.5px]" style={{ color: "var(--muted-2)" }}>{item.reason}</p>
      </div>
      {effective === "awaiting_approval" && (
        <button
          onClick={onApprove}
          className="shrink-0 rounded-full px-4 py-[7px] text-[13px] font-semibold text-white transition hover:brightness-95"
          style={{ background: "var(--accent)" }}
        >
          Approve
        </button>
      )}
      <span className="min-w-[78px] shrink-0 text-right text-[12.5px]" style={{ color: "var(--muted-2)" }}>
        {approved ? "just now" : item.when}
      </span>
    </div>
  );
}

function Metric({ n, label, color, divider }: {
  n: number; label: string; color: string; divider?: boolean;
}) {
  return (
    <div
      className="text-center"
      style={divider ? { borderRight: "1px solid var(--border)" } : undefined}
    >
      <p className="font-display text-[34px] font-bold leading-none" style={{ color }}>{n}</p>
      <p className="mt-1.5 text-[13px]" style={{ color: "var(--muted)" }}>{label}</p>
    </div>
  );
}
