import { useMemo, useState } from "react";
import { usePulse } from "../context/PulseContext";
import { relativeDays, type CustomerRisk, type Segment } from "../lib/api";
import { SEGMENTS, SEGMENT_ORDER } from "../lib/segments";
import RiskBadge from "../components/RiskBadge";
import CustomerDrawer from "../components/CustomerDrawer";

type Tab = "all" | Segment;
type SortKey = "health" | "risk" | "seen";
type SortDir = "asc" | "desc";

export default function Customers() {
  const { customers } = usePulse();
  const [tab, setTab] = useState<Tab>("all");
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("health");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
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
    const dir = sortDir === "asc" ? 1 : -1;
    return [...r].sort((a, b) => {
      let av: number, bv: number;
      if (sortKey === "health") { av = a.score; bv = b.score; }
      else if (sortKey === "risk") { av = a.estimated_annual_value; bv = b.estimated_annual_value; }
      else { av = -(a.days_since_last_visit ?? 9999); bv = -(b.days_since_last_visit ?? 9999); }
      return (av - bv) * dir;
    });
  }, [customers, tab, query, sortKey, sortDir]);

  const toggleSort = (k: SortKey) => {
    if (sortKey === k) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else { setSortKey(k); setSortDir("desc"); }
  };
  const arrow = (k: SortKey) => (sortKey === k ? (sortDir === "asc" ? "↑" : "↓") : "↕");

  const TABS: { id: Tab; label: string; color: string }[] = [
    { id: "all", label: "Everyone", color: "#3B2A20" },
    ...SEGMENT_ORDER.map((s) => ({ id: s as Tab, label: SEGMENTS[s].label, color: SEGMENTS[s].color })),
  ];

  return (
    <div className="space-y-4">
      <div className="anim-fade-up">
        <h1 className="text-[38px] font-bold tracking-tight" style={{ color: "var(--ink)" }}>
          Customer Database
        </h1>
        <p className="mt-1 italic" style={{ color: "var(--muted)", fontSize: "15.5px" }}>
          {customers.length} customers tracked — click any row to see details and take action
        </p>
      </div>

      <div
        className="anim-fade-up flex items-center gap-3 rounded-[14px] border px-5 py-3.5 transition focus-within:shadow-[0_0_0_3px_rgba(180,83,42,.12)]"
        style={{ background: "var(--surface)", borderColor: "var(--border)", animationDelay: "0.05s" }}
      >
        <SearchIcon />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name, email, or favorite item…"
          className="w-full bg-transparent text-[15px] outline-none"
          style={{ color: "var(--ink)" }}
        />
      </div>

      <div className="anim-fade-up flex flex-wrap gap-2" style={{ animationDelay: "0.1s" }}>
        {TABS.map((t) => {
          const on = tab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className="flex items-center gap-2 rounded-full border px-4 py-2 text-[13.5px] font-semibold transition"
              style={
                on
                  ? { background: "var(--ink-strong)", borderColor: "var(--ink-strong)", color: "var(--cream-text)" }
                  : { background: "var(--surface)", borderColor: "var(--border)", color: "#6B5647" }
              }
            >
              <span className="h-2 w-2 rounded-full" style={{ background: t.color }} />
              {t.label}
              <span className="font-bold opacity-60">{counts[t.id]}</span>
            </button>
          );
        })}
      </div>

      <div className="glass anim-fade-up overflow-hidden" style={{ animationDelay: "0.15s" }}>
        <div
          className="grid grid-cols-[1fr_150px_120px_150px] gap-4 border-b px-6 py-4"
          style={{ background: "var(--surface-2)", borderColor: "var(--border)" }}
        >
          <HeaderCell>Name</HeaderCell>
          <HeaderCell sortable onClick={() => toggleSort("health")}>Health {arrow("health")}</HeaderCell>
          <HeaderCell sortable onClick={() => toggleSort("risk")}>$ at risk {arrow("risk")}</HeaderCell>
          <HeaderCell sortable onClick={() => toggleSort("seen")}>Last seen {arrow("seen")}</HeaderCell>
        </div>
        <div className="max-h-[620px] overflow-y-auto scroll-thin">
          {rows.map((c) => (
            <button
              key={c.customer_id}
              onClick={() => setSelected(c)}
              className="grid w-full grid-cols-[1fr_150px_120px_150px] items-center gap-4 border-b px-6 py-[15px] text-left transition hover:bg-[#F6ECDD]"
              style={{ borderColor: "var(--border-soft)" }}
            >
              <div className="min-w-0">
                <p className="truncate text-[15px] font-bold" style={{ color: "var(--ink)" }}>{c.name}</p>
                <p className="truncate text-[12.5px]" style={{ color: "var(--muted-2)" }}>{c.email}</p>
              </div>
              <div><RiskBadge segment={c.segment} score={c.score} /></div>
              <div
                className="font-display text-[15px] font-bold"
                style={{ color: c.estimated_annual_value >= 500 ? "#A23B1E" : "var(--ink)" }}
              >
                {c.estimated_annual_value > 0 ? `$${c.estimated_annual_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—"}
              </div>
              <div>
                <p className="text-sm" style={{ color: "var(--ink-strong)" }}>{c.last_visit ?? "—"}</p>
                <p className="text-xs" style={{ color: "var(--muted-2)" }}>{relativeDays(c.days_since_last_visit)}</p>
              </div>
            </button>
          ))}
          {rows.length === 0 && (
            <p className="px-6 py-8 text-sm" style={{ color: "var(--muted-2)" }}>No customers match.</p>
          )}
        </div>
      </div>

      {selected && <CustomerDrawer customer={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function HeaderCell({ children, sortable, onClick }: {
  children: React.ReactNode; sortable?: boolean; onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={!sortable}
      className="select-none text-left text-xs font-bold uppercase"
      style={{
        letterSpacing: "0.08em",
        color: sortable ? "var(--accent)" : "var(--muted-2)",
        cursor: sortable ? "pointer" : "default",
      }}
    >
      {children}
    </button>
  );
}

function SearchIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#A58C74" strokeWidth="2">
      <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}
