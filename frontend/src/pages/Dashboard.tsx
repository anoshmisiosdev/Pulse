import { useMemo, useState } from "react";
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { formatCurrency, type CSVPreview, type CustomerRisk } from "../lib/api";
import RiskBadge from "../components/RiskBadge";
import CampaignModal from "../components/CampaignModal";

type Filter = "all" | "high" | "med" | "low";

const BAND_COLORS = { high: "#dc2626", med: "#f59e0b", low: "#10b981" };

export default function Dashboard({
  preview,
  businessName,
  vertical,
}: {
  preview: CSVPreview;
  businessName: string;
  vertical: string;
}) {
  const { summary, customers } = preview;
  const [filter, setFilter] = useState<Filter>("high");
  const [active, setActive] = useState<CustomerRisk | null>(null);

  const visible = useMemo(
    () => (filter === "all" ? customers : customers.filter((c) => c.band === filter)),
    [customers, filter]
  );

  const pieData = [
    { name: "High", value: summary.high_risk, key: "high" as const },
    { name: "Medium", value: summary.med_risk, key: "med" as const },
    { name: "Low", value: summary.low_risk, key: "low" as const },
  ];

  return (
    <div>
      {/* The money screen */}
      <div className="rounded-2xl bg-gradient-to-br from-cyan-600 to-cyan-700 p-6 text-white shadow-sm">
        <p className="text-sm text-cyan-100">
          {businessName} · {vertical.replace("_", " ")}
        </p>
        <p className="mt-1 text-2xl font-semibold leading-snug">
          We found {summary.high_risk} customers at high risk, worth an estimated{" "}
          {formatCurrency(summary.revenue_at_risk)}/year.
        </p>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-4">
        <Stat label="Customers" value={summary.total_customers.toString()} />
        <Stat label="High risk" value={summary.high_risk.toString()} accent="text-red-600" />
        <Stat label="Medium risk" value={summary.med_risk.toString()} accent="text-amber-600" />
        <Stat
          label="Revenue at risk"
          value={formatCurrency(summary.revenue_at_risk)}
          accent="text-cyan-700"
        />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Risk queue */}
        <div className="lg:col-span-2">
          <div className="mb-3 flex items-center gap-2">
            {(["high", "med", "low", "all"] as Filter[]).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`rounded-full px-3 py-1 text-sm capitalize ${
                  filter === f ? "bg-slate-900 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200"
                }`}
              >
                {f}
              </button>
            ))}
          </div>

          <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
            {visible.length === 0 && (
              <p className="p-6 text-sm text-slate-400">No customers in this band.</p>
            )}
            {visible.slice(0, 50).map((c) => (
              <div
                key={c.customer_id}
                className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4 last:border-0"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-slate-900">{c.name}</span>
                    <RiskBadge band={c.band} />
                  </div>
                  <p className="mt-1 truncate text-sm text-slate-500">{c.reasons[0]}</p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-2">
                  <span className="text-sm font-semibold text-slate-700">
                    {formatCurrency(c.estimated_annual_value)}/yr
                  </span>
                  <button
                    onClick={() => setActive(c)}
                    className="rounded-lg bg-cyan-600 px-3 py-1 text-xs font-medium text-white hover:bg-cyan-700"
                  >
                    Win back
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Distribution */}
        <div className="rounded-2xl border border-slate-200 bg-white p-5">
          <h3 className="text-sm font-medium text-slate-700">Risk distribution</h3>
          <div className="mt-2 h-48">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={pieData} dataKey="value" nameKey="name" innerRadius={45} outerRadius={70}>
                  {pieData.map((d) => (
                    <Cell key={d.key} fill={BAND_COLORS[d.key]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 space-y-1 text-sm">
            {pieData.map((d) => (
              <div key={d.key} className="flex items-center justify-between">
                <span className="flex items-center gap-2 text-slate-600">
                  <span className="h-2 w-2 rounded-full" style={{ background: BAND_COLORS[d.key] }} />
                  {d.name}
                </span>
                <span className="font-medium text-slate-800">{d.value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {active && (
        <CampaignModal customer={active} businessName={businessName} onClose={() => setActive(null)} />
      )}
    </div>
  );
}

function Stat({ label, value, accent = "text-slate-900" }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5">
      <p className="text-sm text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${accent}`}>{value}</p>
    </div>
  );
}
