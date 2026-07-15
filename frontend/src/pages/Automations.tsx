import { useEffect, useState } from "react";
import {
  api,
  type AutomationChannel,
  type AutomationMode,
  type AutomationRule,
  type CampaignSend,
  type TriggerBand,
} from "../lib/api";

const MODES: { id: AutomationMode; label: string; blurb: string }[] = [
  { id: "suggest", label: "Suggest", blurb: "Churnary flags who to contact. You write & send." },
  { id: "approve", label: "Approve", blurb: "Churnary drafts everything. You tap approve to send." },
  { id: "auto", label: "Autopilot", blurb: "Churnary drafts and sends automatically, within guardrails." },
];

const BANDS: { id: TriggerBand; label: string }[] = [
  { id: "high", label: "High risk" },
  { id: "med", label: "Medium risk" },
  { id: "low", label: "Low risk" },
];

export default function Automations() {
  const [rules, setRules] = useState<AutomationRule[]>([]);
  const [sends, setSends] = useState<CampaignSend[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddRule, setShowAddRule] = useState(false);
  const [dispatching, setDispatching] = useState(false);

  const load = async () => {
    setError(null);
    try {
      const [r, s] = await Promise.all([api.listAutomationRules(), api.listSends(50)]);
      setRules(r);
      setSends(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load automations");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const sent = sends.filter((s) => s.status === "sent" || s.status === "delivered").length;
  const awaiting = sends.filter((s) => s.status === "pending").length;
  const failed = sends.filter((s) => s.status === "failed").length;

  const patchRule = async (id: string, patch: Partial<AutomationRule>) => {
    setRules((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r))); // optimistic
    try {
      await api.updateAutomationRule(id, patch);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't update rule");
      load(); // reconcile with the server on failure
    }
  };

  const removeRule = async (id: string) => {
    setRules((prev) => prev.filter((r) => r.id !== id));
    try {
      await api.deleteAutomationRule(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't delete rule");
      load();
    }
  };

  const approve = async (send: CampaignSend) => {
    setSends((prev) => prev.map((s) => (s.id === send.id ? { ...s, status: "sent" } : s)));
    try {
      const updated = await api.approveSend(send.id);
      setSends((prev) => prev.map((s) => (s.id === send.id ? updated : s)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't send — check quiet hours");
      load();
    }
  };

  const runNow = async () => {
    setDispatching(true);
    setError(null);
    try {
      await api.triggerDispatch();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Dispatch failed");
    } finally {
      setDispatching(false);
    }
  };

  return (
    <div className="space-y-7">
      <div className="anim-fade-up flex items-start justify-between gap-4">
        <div>
          <h1 className="text-[38px] font-bold tracking-tight" style={{ color: "var(--ink)" }}>Automations</h1>
          <p className="mt-1 italic" style={{ color: "var(--muted)", fontSize: "15.5px" }}>
            Set it once — Churnary watches every customer and acts the moment churn risk rises.
          </p>
        </div>
        <button
          onClick={runNow}
          disabled={dispatching}
          className="shrink-0 rounded-full px-4 py-2 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-50"
          style={{ background: "var(--ink-strong)" }}
        >
          {dispatching ? "Running…" : "Run now"}
        </button>
      </div>

      {error && (
        <p className="rounded-xl px-4 py-2.5 text-sm" style={{ background: "#FBEAEA", color: "#A23B1E" }}>
          {error}
        </p>
      )}

      {/* stat bar */}
      <div className="glass anim-fade-up grid grid-cols-3 p-6" style={{ animationDelay: "0.05s" }}>
        <Metric n={sent} label="Sent" color="#5C8A4A" divider />
        <Metric n={awaiting} label="Awaiting your approval" color="#C0632F" divider />
        <Metric n={failed} label="Failed" color="#A23B1E" />
      </div>

      <div>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-xl font-semibold" style={{ color: "var(--ink)" }}>Rules</h2>
          <button
            onClick={() => setShowAddRule((v) => !v)}
            className="rounded-full px-3.5 py-1.5 text-sm font-semibold transition hover:brightness-95"
            style={{ background: "var(--surface-3)", color: "var(--ink-strong)" }}
          >
            {showAddRule ? "Cancel" : "+ New rule"}
          </button>
        </div>

        {showAddRule && (
          <AddRuleForm
            onCreated={(r) => {
              setRules((prev) => [...prev, r]);
              setShowAddRule(false);
            }}
            onError={setError}
          />
        )}

        {loading ? (
          <p className="text-sm" style={{ color: "var(--muted-2)" }}>Loading…</p>
        ) : rules.length === 0 && !showAddRule ? (
          <p className="glass px-6 py-8 text-sm" style={{ color: "var(--muted-2)" }}>
            No rules yet. Add one to start reaching at-risk customers automatically.
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            {rules.map((rule) => (
              <RuleCard
                key={rule.id}
                rule={rule}
                onMode={(mode) => patchRule(rule.id, { mode })}
                onToggle={() => patchRule(rule.id, { enabled: !rule.enabled })}
                onDelete={() => removeRule(rule.id)}
              />
            ))}
          </div>
        )}
      </div>

      <div>
        <h2 className="font-display mb-4 text-xl font-semibold" style={{ color: "var(--ink)" }}>
          What Churnary did for you
        </h2>
        <div className="glass overflow-hidden">
          {!loading && sends.length === 0 && (
            <p className="px-6 py-8 text-sm" style={{ color: "var(--muted-2)" }}>
              No sends yet. Turn on a rule, or hit "Run now" to check for at-risk customers immediately.
            </p>
          )}
          {sends.map((s) => (
            <FeedRow key={s.id} send={s} onApprove={() => approve(s)} />
          ))}
        </div>
      </div>
    </div>
  );
}

function AddRuleForm({
  onCreated,
  onError,
}: {
  onCreated: (r: AutomationRule) => void;
  onError: (msg: string) => void;
}) {
  const [name, setName] = useState("Win back at-risk customers");
  const [triggerBand, setTriggerBand] = useState<TriggerBand>("high");
  const [channel, setChannel] = useState<AutomationChannel>("sms");
  const [incentive, setIncentive] = useState("10% off their next visit");
  const [mode, setMode] = useState<AutomationMode>("approve");
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    setSaving(true);
    try {
      const rule = await api.createAutomationRule({
        name,
        trigger_band: triggerBand,
        channel,
        incentive,
        mode,
      });
      onCreated(rule);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Couldn't create rule");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="glass mb-4 space-y-3 p-6">
      <label className="block">
        <span className="text-sm font-medium" style={{ color: "var(--ink-strong)" }}>Rule name</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="mt-1 w-full rounded-xl border bg-white/70 px-3 py-2 text-sm outline-none"
          style={{ borderColor: "var(--border)", color: "var(--ink)" }}
        />
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="text-sm font-medium" style={{ color: "var(--ink-strong)" }}>When risk becomes</span>
          <select
            value={triggerBand}
            onChange={(e) => setTriggerBand(e.target.value as TriggerBand)}
            className="mt-1 w-full rounded-xl border bg-white/70 px-3 py-2 text-sm outline-none"
            style={{ borderColor: "var(--border)", color: "var(--ink)" }}
          >
            {BANDS.map((b) => (
              <option key={b.id} value={b.id}>{b.label}</option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-sm font-medium" style={{ color: "var(--ink-strong)" }}>Channel</span>
          <select
            value={channel}
            onChange={(e) => setChannel(e.target.value as AutomationChannel)}
            className="mt-1 w-full rounded-xl border bg-white/70 px-3 py-2 text-sm outline-none"
            style={{ borderColor: "var(--border)", color: "var(--ink)" }}
          >
            <option value="sms">Text (SMS)</option>
            <option value="email">Email</option>
          </select>
        </label>
      </div>
      <label className="block">
        <span className="text-sm font-medium" style={{ color: "var(--ink-strong)" }}>Incentive (optional)</span>
        <input
          value={incentive}
          onChange={(e) => setIncentive(e.target.value)}
          className="mt-1 w-full rounded-xl border bg-white/70 px-3 py-2 text-sm outline-none"
          style={{ borderColor: "var(--border)", color: "var(--ink)" }}
        />
      </label>
      <div className="flex gap-2.5">
        {MODES.map((m) => (
          <button
            key={m.id}
            onClick={() => setMode(m.id)}
            className="flex-1 rounded-xl border p-3 text-left text-sm"
            style={{
              background: mode === m.id ? "var(--ink-strong)" : "var(--surface-2)",
              color: mode === m.id ? "var(--cream-text)" : "var(--ink-strong)",
              borderColor: mode === m.id ? "var(--ink-strong)" : "var(--border)",
            }}
          >
            <b>{m.label}</b>
          </button>
        ))}
      </div>
      <button
        onClick={submit}
        disabled={saving || !name.trim()}
        className="rounded-full px-4 py-2 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-50"
        style={{ background: "var(--accent)" }}
      >
        {saving ? "Creating…" : "Create rule"}
      </button>
    </div>
  );
}

function RuleCard({ rule, onMode, onToggle, onDelete }: {
  rule: AutomationRule; onMode: (m: AutomationMode) => void; onToggle: () => void; onDelete: () => void;
}) {
  const bandLabel = BANDS.find((b) => b.id === rule.trigger_band)?.label ?? rule.trigger_band;
  return (
    <div
      className="glass p-6"
      style={{ opacity: rule.enabled ? 1 : 0.62, transition: "opacity .25s ease", borderRadius: 18 }}
    >
      <div className="mb-[18px] flex items-start justify-between gap-4">
        <div>
          <p className="mb-1 text-[17px] font-bold" style={{ color: "var(--ink)" }}>{rule.name}</p>
          <p className="text-[13.5px]" style={{ color: "var(--muted)" }}>
            Targets {bandLabel} customers · via {rule.channel === "sms" ? "text" : "email"}
            {rule.incentive ? ` · offers ${rule.incentive}` : ""} · {rule.cooldown_days}-day cooldown
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <button
            onClick={onDelete}
            aria-label="Delete rule"
            className="text-sm"
            style={{ color: "var(--muted-2)" }}
          >
            ✕
          </button>
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

function FeedRow({ send, onApprove }: { send: CampaignSend; onApprove: () => void }) {
  const status = {
    sent: { text: `Sent win-back ${send.channel === "sms" ? "text" : "email"}`, color: "#4F7A40", dot: "#5C8A4A" },
    delivered: { text: `Delivered win-back ${send.channel === "sms" ? "text" : "email"}`, color: "#4F7A40", dot: "#5C8A4A" },
    pending: { text: "Drafted — awaiting approval", color: "#C0632F", dot: "#C0632F" },
    approved: { text: "Approved — sending", color: "#C0632F", dot: "#C0632F" },
    failed: { text: `Failed: ${send.failure_reason ?? "unknown error"}`, color: "#A23B1E", dot: "#A23B1E" },
    skipped: { text: "Skipped", color: "#A58C74", dot: "#A58C74" },
  }[send.status];

  return (
    <div className="flex items-center gap-3.5 border-b px-6 py-4" style={{ borderColor: "var(--border-soft)" }}>
      <span className="h-[9px] w-[9px] shrink-0 rounded-full" style={{ background: status.dot }} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14.5px]">
          <b style={{ color: status.color, fontWeight: 700 }}>{status.text}</b>{" "}
          <span style={{ color: "#6B5647" }}>to {send.customer_name}</span>
        </p>
        <p className="mt-0.5 truncate text-[12.5px]" style={{ color: "var(--muted-2)" }}>{send.body}</p>
        {(send.opened || send.clicked || send.replied) && (
          <div className="mt-1 flex gap-1.5">
            {send.replied && <EngagementBadge label="Replied" color="#4F7A40" />}
            {send.clicked && <EngagementBadge label="Clicked" color="#2E6B9E" />}
            {send.opened && <EngagementBadge label="Opened" color="#8A7565" />}
          </div>
        )}
      </div>
      {send.status === "pending" && (
        <button
          onClick={onApprove}
          className="shrink-0 rounded-full px-4 py-[7px] text-[13px] font-semibold text-white transition hover:brightness-95"
          style={{ background: "var(--accent)" }}
        >
          Approve
        </button>
      )}
      <span className="min-w-[78px] shrink-0 text-right text-[12.5px]" style={{ color: "var(--muted-2)" }}>
        {new Date(send.created_at).toLocaleDateString()}
      </span>
    </div>
  );
}

function EngagementBadge({ label, color }: { label: string; color: string }) {
  return (
    <span
      className="rounded-full px-2 py-[1px] text-[10.5px] font-semibold"
      style={{ background: `${color}1A`, color }}
    >
      {label}
    </span>
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
