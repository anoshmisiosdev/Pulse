import { useMemo, useState } from "react";
import { usePulse } from "../context/PulseContext";
import { relativeDays, type CustomerRisk, type Segment } from "../lib/api";
import { SEGMENTS, SEGMENT_ORDER } from "../lib/segments";
import RiskBadge from "../components/RiskBadge";
import CustomerDrawer from "../components/CustomerDrawer";

type Tab = "all" | Segment;
type Sort = "score" | "value" | "recent";

export default function Customers() {
  const { customers } = usePulse();
  const [tab, setTab] = useState<Tab>("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("score");
  const [selected, setSelected] = useState<CustomerRisk | null>(null);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: customers.length };
    SEGMENT_ORDER.forEach((s) => (c[s] = 0));
    customers.forEach((cust) => (c[cust.segment] += 1));
    return c;
  }, [customers]);

  const rows = useMemo(() => {
    let r = customers;
    if (tab !== "all") r = r.filter((c) => c.segment === tab);
    if (query.trim()) {
      const q = query.toLowerCase();
      r = r.filter(
        (c) =>
          c.name.toLowerCase().includes(q) ||
          (c.email ?? "").toLowerCase().includes(q) ||
          (c.favorite_item ?? "").toLowerCase().includes(q)
      );
    }
    return [...r].sort((a, b) => {
      if (sort === "value") return b.estimated_annual_value - a.estimated_annual_value;
      if (sort === "recent")
        return (b.days_since_last_visit ?? 0) - (a.days_since_last_visit ?? 0);
      return b.score - a.score;
    });
  }, [customers, tab, query, sort]);

  const TABS: { id: Tab; label: string; color?: string }[] = [
    { id: "all", label: "Everyone" },
    ...SEGMENT_ORDER.map((s) => ({ id: s, label: SEGMENTS[s].label, color: SEGMENTS[s].color })),
  ];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="font-display text-4xl font-extrabold tracking-tight">Customer Database</h1>
        <p className="mt-1 text-slate-500">
          {customers.length} customers tracked — tap any row to see details and take action
        </p>
      </div>

      <div className="glass flex items-center gap-2 px-4 py-3">
        <SearchIcon />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name, email, or favorite item…"
          className="w-full bg-transparent text-sm outline-none placeholder:text-slate-400"
        />
      </div>

      <div className="flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-2 rounded-full px-3.5 py-1.5 text-sm font-medium transition ${
              tab === t.id ? "bg-primary text-white" : "glass text-slate-600 hover:text-slate-900"
            }`}
          >
            {t.color && <span className="h-2 w-2 rounded-full" style={{ background: t.color }} />}
            {t.label}
            <span className={`text-xs ${tab === t.id ? "text-white/80" : "text-slate-400"}`}>
              {counts[t.id]}
            </span>
          </button>
        ))}
      </div>

      <div className="glass overflow-hidden">
        <div className="grid grid-cols-[2fr_1fr_1fr_1fr] gap-2 border-b border-slate-100 px-5 py-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
          <span>Name</span>
          <button className="text-left text-cyan-600" onClick={() => setSort("score")}>Health ↕</button>
          <button className="text-left" onClick={() => setSort("value")}>$ at risk ↕</button>
          <button className="text-left" onClick={() => setSort("recent")}>Last seen ↕</button>
        </div>
        <div className="max-h-[60vh] overflow-y-auto scroll-thin">
          {rows.map((c) => (
            <button
              key={c.customer_id}
              onClick={() => setSelected(c)}
              className="grid w-full grid-cols-[2fr_1fr_1fr_1fr] items-center gap-2 border-b border-slate-50 px-5 py-3.5 text-left transition hover:bg-white/60"
            >
              <div className="min-w-0">
                <p className="truncate font-semibold text-slate-900">{c.name}</p>
                <p className="truncate text-xs text-slate-400">{c.email}</p>
              </div>
              <div><RiskBadge segment={c.segment} score={c.score} /></div>
              <div className={`font-semibold ${c.band === "high" ? "text-red-600" : "text-slate-700"}`}>
                {c.estimated_annual_value > 0 ? `$${c.estimated_annual_value.toFixed(0)}` : "—"}
              </div>
              <div className="text-sm text-slate-600">
                {c.last_visit ?? "—"}
                <p className="text-xs text-slate-400">{relativeDays(c.days_since_last_visit)}</p>
              </div>
            </button>
          ))}
          {rows.length === 0 && <p className="px-5 py-8 text-sm text-slate-400">No customers match.</p>}
        </div>
      </div>

      {selected && <CustomerDrawer customer={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function SearchIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" strokeWidth="2">
      <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}
