import { useMemo } from "react";
import { Link } from "react-router-dom";
import {
  Area, AreaChart, Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { usePulse } from "../context/PulseContext";
import { formatCurrency, type CustomerRisk } from "../lib/api";
import { PATTERNS, SEGMENTS, SEGMENT_ORDER } from "../lib/segments";

const VISIT_BUCKETS = [
  { label: "< 2 weeks", max: 14 },
  { label: "2-4 weeks", max: 28 },
  { label: "1-2 months", max: 60 },
  { label: "2-3 months", max: 90 },
  { label: "3+ months", max: Infinity },
];

export default function Dashboard() {
  const { customers, portfolio, revenueRecovered } = usePulse();
  const s = portfolio?.summary;
  const top = customers[0];

  const segData = useMemo(() => {
    const counts = Object.fromEntries(SEGMENT_ORDER.map((k) => [k, 0])) as Record<string, number>;
    customers.forEach((c) => (counts[c.segment] += 1));
    return SEGMENT_ORDER.map((k) => ({ key: k, name: SEGMENTS[k].label, value: counts[k], color: SEGMENTS[k].color }));
  }, [customers]);

  const visitData = useMemo(() => {
    const counts = VISIT_BUCKETS.map((b) => ({ label: b.label, count: 0 }));
    customers.forEach((c) => {
      const d = c.days_since_last_visit ?? 9999;
      const idx = VISIT_BUCKETS.findIndex((b) => d < b.max);
      if (idx >= 0) counts[idx].count += 1;
    });
    return counts;
  }, [customers]);

  const patternData = useMemo(() => {
    const counts: Record<string, number> = {};
    customers.forEach((c) => {
      if (c.pattern) counts[c.pattern] = (counts[c.pattern] ?? 0) + 1;
    });
    return Object.entries(counts)
      .map(([k, v]) => ({ name: PATTERNS[k as keyof typeof PATTERNS], value: v }))
      .sort((a, b) => b.value - a.value);
  }, [customers]);

  const needAttention = customers.filter(
    (c) => c.segment === "needs_attention" || c.segment === "slipping_away"
  ).length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-4xl font-extrabold tracking-tight">Dashboard</h1>
        <p className="mt-1 text-slate-500">Here's how your customers are doing today</p>
      </div>

      {top && <TopAction customer={top} />}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard accent="#ef4444" icon="$" label="Revenue at Risk"
          value={formatCurrency(s?.revenue_at_risk ?? 0)} sub="Could lose this year" />
        <StatCard accent="#f59e0b" icon="!" label="Need Attention"
          value={String(needAttention)} sub="customers may not return" />
        <StatCard accent="#0891b2" icon="◷" label="Avg. Days Away"
          value={String(Math.round(s?.avg_days_away ?? 0))} sub="Since last visit" />
        <StatCard accent="#6366f1" icon="↗" label="Retained"
          value={formatCurrency(revenueRecovered)}
          sub={revenueRecovered > 0 ? "Recovered so far" : "Start reaching out!"} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Panel title="Customer Health" subtitle="How your customers are doing right now">
          <div className="flex items-center gap-4">
            <div className="h-44 w-44 shrink-0">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={segData} dataKey="value" innerRadius={48} outerRadius={75} paddingAngle={2}>
                    {segData.map((d) => <Cell key={d.key} fill={d.color} />)}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="space-y-1.5 text-sm">
              {segData.map((d) => (
                <div key={d.key} className="flex items-center gap-2 text-slate-600">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: d.color }} />
                  {d.name}
                  <span className="ml-auto font-semibold text-slate-800">{d.value}</span>
                </div>
              ))}
            </div>
          </div>
        </Panel>

        <Panel title="When Did They Last Visit?" subtitle="How long since each customer came in">
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={visitData}>
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} axisLine={false} tickLine={false} width={24} />
                <Tooltip cursor={{ fill: "rgba(8,145,178,0.06)" }} />
                <Bar dataKey="count" fill="#0891b2" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Revenue Over Time" subtitle="Total monthly spend from all customers">
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={s?.revenue_series ?? []}>
                <defs>
                  <linearGradient id="rev" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#0891b2" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#0891b2" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="month" tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} axisLine={false} tickLine={false}
                  width={44} tickFormatter={(v) => `$${v}`} />
                <Tooltip formatter={(v: number) => formatCurrency(v)} />
                <Area type="monotone" dataKey="amount" stroke="#0891b2" strokeWidth={2.5} fill="url(#rev)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Why They Leave" subtitle="Common patterns in customer behavior">
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={patternData} layout="vertical" margin={{ left: 20 }}>
                <XAxis type="number" tick={{ fontSize: 11, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="name" width={90}
                  tick={{ fontSize: 11, fill: "#475569" }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: "rgba(99,102,241,0.06)" }} />
                <Bar dataKey="value" fill="#6366f1" radius={[0, 6, 6, 0]} barSize={18} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function TopAction({ customer }: { customer: CustomerRisk }) {
  return (
    <div className="glass glass-hover p-5">
      <div className="flex items-center gap-4">
        <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-red-50 text-red-500">
          <SparkIcon />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Your #1 action today</p>
          <p className="font-display text-xl font-bold text-slate-900">Reach out to {customer.name}</p>
          <p className="mt-0.5 text-sm text-slate-500">
            {customer.reasons[0]}
            {customer.favorite_item && <> · They love {customer.favorite_item}.</>}{" "}
            <Link to="/retention" className="font-semibold text-cyan-600 hover:underline">Go to Retention →</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

function StatCard({ accent, icon, label, value, sub }: {
  accent: string; icon: string; label: string; value: string; sub: string;
}) {
  return (
    <div className="glass glass-hover overflow-hidden p-0">
      <div className="h-1" style={{ background: accent }} />
      <div className="p-5">
        <div className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-full text-sm font-bold"
            style={{ background: `${accent}1a`, color: accent }}>{icon}</span>
          <span className="text-sm text-slate-500">{label}</span>
        </div>
        <p className="stat-number mt-3 text-3xl">{value}</p>
        <p className="mt-1 text-xs text-slate-400">{sub}</p>
      </div>
    </div>
  );
}

function Panel({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="glass p-6">
      <h3 className="font-display text-lg font-bold text-slate-900">{title}</h3>
      <p className="mb-4 text-sm text-slate-500">{subtitle}</p>
      {children}
    </div>
  );
}

function SparkIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v3m0 12v3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1M3 12h3m12 0h3M5.6 18.4l2.1-2.1m8.6-8.6 2.1-2.1" />
    </svg>
  );
}
