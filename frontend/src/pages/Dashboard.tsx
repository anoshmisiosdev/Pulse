import useMountProgress from "../hooks/useMountProgress";
import { useMemo, useRef, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { usePulse } from "../context/PulseContext";
import { formatCurrency, relativeDays, type CustomerRisk } from "../lib/api";
import { PATTERNS, PATTERN_BAR_COLORS, SEGMENTS, SEGMENT_ORDER } from "../lib/segments";

const VISIT_BUCKETS = [
  { label: "< 2 wks", max: 14 },
  { label: "2–4 wks", max: 28 },
  { label: "1–2 mo", max: 60 },
  { label: "2–3 mo", max: 90 },
  { label: "3+ mo", max: Infinity },
];

/** 0→1 mount progress, easeOutCubic over 1s — drives count-ups. */
export default function Dashboard() {
  const { customers, portfolio, revenueRecovered } = usePulse();
  const s = portfolio?.summary;
  const p = useMountProgress();
  const [queueSort, setQueueSort] = useState<"risk" | "value">("risk");
  const [selectedCustomerId, setSelectedCustomerId] = useState(customers[0]?.customer_id ?? "");

  const focusQueue = useMemo(() => {
    const actionable = customers.filter((customer) => customer.band !== "low");
    const candidates = actionable.length ? actionable : customers;

    return [...candidates]
        .sort((a, b) =>
          queueSort === "risk"
            ? b.score - a.score || b.estimated_annual_value - a.estimated_annual_value
            : b.estimated_annual_value - a.estimated_annual_value || b.score - a.score
        )
        .slice(0, 5);
  }, [customers, queueSort]);
  const selectedCustomer =
    focusQueue.find((customer) => customer.customer_id === selectedCustomerId) ?? focusQueue[0];
  const decliningCustomers = customers.filter((customer) => customer.trend_pct < -10).length;
  const latestSync = useMemo(() => {
    const timestamps = (portfolio?.connections ?? [])
      .map((connection) => connection.last_synced_at)
      .filter((value): value is string => Boolean(value))
      .map((value) => new Date(value).getTime())
      .filter(Number.isFinite);
    return timestamps.length ? new Date(Math.max(...timestamps)) : null;
  }, [portfolio?.connections]);

  const segData = useMemo(() => {
    const counts = Object.fromEntries(SEGMENT_ORDER.map((k) => [k, 0])) as Record<string, number>;
    customers.forEach((c) => (counts[c.segment] += 1));
    return SEGMENT_ORDER.map((k) => ({
      key: k, name: SEGMENTS[k].label, value: counts[k], color: SEGMENTS[k].color,
    }));
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

  return (
    <div className="dashboard-page">
      <section className="dashboard-overview anim-fade-up">
        <div>
          <div className="dashboard-overline">Customer health</div>
          <h1>Dashboard</h1>
          <p>A clear view of who needs attention and what to do next.</p>
        </div>
        <div className="dashboard-sync" aria-label={latestSync ? `Last synced ${latestSync.toLocaleString()}` : "Data is current"}>
          <span aria-hidden="true" />
          <div>
            <strong>{latestSync ? "Last synced" : "Data current"}</strong>
            <small>{latestSync ? formatSyncTime(latestSync) : `${customers.length} customers monitored`}</small>
          </div>
        </div>
      </section>

      <section className="dashboard-metrics" aria-label="Customer health summary">
        <MetricCard
          delay={0.06}
          tone="critical"
          label="Revenue at risk"
          value={formatCurrency((s?.revenue_at_risk ?? 0) * p)}
          sub={`Across ${s?.high_risk ?? 0} high-risk customers`}
        />
        <MetricCard
          delay={0.1}
          tone="warning"
          label="High risk"
          value={String(Math.round((s?.high_risk ?? 0) * p))}
          sub={`${decliningCustomers} showing a sharp decline`}
        />
        <MetricCard
          delay={0.14}
          tone="neutral"
          label="Average time away"
          value={`${Math.round((s?.avg_days_away ?? 0) * p)} days`}
          sub="Across the active watchlist"
        />
        <MetricCard
          delay={0.18}
          tone="positive"
          label="Revenue retained"
          value={formatCurrency(revenueRecovered * p)}
          sub={revenueRecovered > 0 ? "Recovered through outreach" : "Ready to start recovering"}
        />
      </section>

      <section className="dashboard-workspace anim-fade-up" style={{ animationDelay: "0.2s" }}>
        <FocusQueue
          customers={focusQueue}
          selectedCustomerId={selectedCustomer?.customer_id ?? ""}
          sort={queueSort}
          onSort={setQueueSort}
          onSelect={setSelectedCustomerId}
        />
        {selectedCustomer && <PriorityPanel customer={selectedCustomer} />}
      </section>

      <div className="dashboard-section-heading anim-fade-up" style={{ animationDelay: "0.26s" }}>
        <div>
          <p className="dashboard-overline">Portfolio signals</p>
          <h2>Patterns behind the queue</h2>
        </div>
        <p>Explore the customer mix, visit gaps, revenue, and churn patterns.</p>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Panel title="Customer Health" subtitle="Hover a segment to focus it" delay={0.3}>
          <HealthDonut data={segData} p={p} />
        </Panel>

        <Panel title="When Did They Last Visit?" subtitle="How long since each customer came in" delay={0.36}>
          <VisitBars data={visitData} />
        </Panel>

        <RevenuePanel series={s?.revenue_series ?? []} p={p} />

        <Panel title="Why They Leave" subtitle="Common patterns in customer behavior" delay={0.48}>
          <PatternBars data={patternData} />
        </Panel>
      </div>
    </div>
  );
}

function FocusQueue({
  customers,
  selectedCustomerId,
  sort,
  onSort,
  onSelect,
}: {
  customers: CustomerRisk[];
  selectedCustomerId: string;
  sort: "risk" | "value";
  onSort: (sort: "risk" | "value") => void;
  onSelect: (customerId: string) => void;
}) {
  return (
    <div className="focus-queue">
      <div className="workspace-heading">
        <div>
          <p className="dashboard-overline">Priority queue</p>
          <h2>Customers to focus on</h2>
          <span>Select a customer to review the recommended action.</span>
        </div>
        <div className="queue-sort" aria-label="Sort priority queue">
          <button
            className={sort === "risk" ? "is-active" : ""}
            aria-pressed={sort === "risk"}
            onClick={() => onSort("risk")}
          >Risk</button>
          <button
            className={sort === "value" ? "is-active" : ""}
            aria-pressed={sort === "value"}
            onClick={() => onSort("value")}
          >Value</button>
        </div>
      </div>
      <div className="queue-list">
        {customers.map((customer, index) => (
          <button
            key={customer.customer_id}
            className={`queue-row ${selectedCustomerId === customer.customer_id ? "is-active" : ""}`}
            onClick={() => onSelect(customer.customer_id)}
            aria-pressed={selectedCustomerId === customer.customer_id}
          >
            <span className="queue-rank">{String(index + 1).padStart(2, "0")}</span>
            <span className="queue-avatar" aria-hidden="true">{initials(customer.name)}</span>
            <span className="queue-customer">
              <strong>{customer.name}</strong>
              <small>{customer.reasons[0] ?? "Customer activity is trending down"}</small>
            </span>
            <span className="queue-reading">
              <strong>{relativeDays(customer.days_since_last_visit)}</strong>
              <small>last visit</small>
            </span>
            <span className="queue-reading queue-value">
              <strong>{formatCurrency(customer.estimated_annual_value)}</strong>
              <small>annual value</small>
            </span>
            <span className={`risk-chip risk-${customer.band}`}>{customer.score}</span>
          </button>
        ))}
      </div>
      <Link className="queue-footer" to="/retention">View the full retention queue <span>→</span></Link>
    </div>
  );
}

function PriorityPanel({ customer }: { customer: CustomerRisk }) {
  const riskDegrees = Math.max(0, Math.min(100, customer.score)) * 3.6;
  return (
    <aside className="priority-panel" key={customer.customer_id}>
      <div className="priority-topline">
        <span>Recommended next step</span>
        <span className={`priority-band band-${customer.band}`}>{customer.band} risk</span>
      </div>
      <div className="priority-person">
        <div className="priority-risk" style={{ "--risk-degrees": `${riskDegrees}deg` } as CSSProperties}>
          <span>{customer.score}</span>
          <small>risk</small>
        </div>
        <div>
          <p>Reach out to</p>
          <h2>{customer.name}</h2>
          <span>{customer.confidence} confidence</span>
        </div>
      </div>
      <div className="priority-reason">
        <span>Why now</span>
        <p>{customer.reasons[0] ?? "Recent behavior suggests this customer may not return."}</p>
      </div>
      <dl className="priority-facts">
        <div><dt>Last visit</dt><dd>{relativeDays(customer.days_since_last_visit)}</dd></div>
        <div><dt>Annual value</dt><dd>{formatCurrency(customer.estimated_annual_value)}</dd></div>
        <div><dt>Favorite</dt><dd>{customer.favorite_item ?? "Not known"}</dd></div>
      </dl>
      <Link className="priority-action" to={`/retention?customer=${encodeURIComponent(customer.customer_id)}`}>
        Open {customer.name.split(" ")[0]}'s retention plan <span>→</span>
      </Link>
    </aside>
  );
}

function MetricCard({ label, value, sub, tone, delay }: {
  label: string;
  value: string;
  sub: string;
  tone: "critical" | "warning" | "neutral" | "positive";
  delay: number;
}) {
  return (
    <div className={`metric-card metric-${tone} anim-fade-up`} style={{ animationDelay: `${delay}s` }}>
      <div className="metric-label"><span aria-hidden="true" />{label}</div>
      <p className="stat-number">{value}</p>
      <small>{sub}</small>
    </div>
  );
}

function initials(name: string): string {
  return name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function formatSyncTime(date: Date): string {
  const minutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60_000));
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function Panel({ title, subtitle, delay, children }: {
  title: string; subtitle: string; delay: number; children: React.ReactNode;
}) {
  return (
    <div className="glass anim-fade-up p-6" style={{ animationDelay: `${delay}s` }}>
      <h3 className="font-display text-xl font-semibold" style={{ color: "var(--ink)" }}>{title}</h3>
      <p className="mb-5 text-[13px]" style={{ color: "var(--muted-2)" }}>{subtitle}</p>
      {children}
    </div>
  );
}

/* ── Donut with legend-hover focus ── */
function HealthDonut({ data, p }: {
  data: { key: string; name: string; value: number; color: string }[]; p: number;
}) {
  const [active, setActive] = useState(-1);
  const total = data.reduce((a, d) => a + d.value, 0) || 1;
  const cx = 70, cy = 70, r = 54, C = 2 * Math.PI * r;

  let acc = -90;
  const circles = data.map((d, i) => {
    const frac = d.value / total;
    const len = frac * C;
    const start = acc;
    acc += frac * 360;
    const isActive = active === i;
    const dim = active !== -1 && !isActive;
    return (
      <circle
        key={d.key} cx={cx} cy={cy} r={r} fill="none" stroke={d.color}
        strokeWidth={isActive ? 21 : 15}
        strokeDasharray={`${Math.max(0, len - 3) * p} ${C}`}
        transform={`rotate(${start} ${cx} ${cy})`}
        opacity={dim ? 0.32 : 1}
        style={{ transition: "stroke-width .2s ease, opacity .2s ease" }}
      />
    );
  });

  const centerNum = active === -1 ? total : data[active].value;
  const centerLabel = active === -1 ? "tracked" : data[active].name;

  return (
    <div className="flex items-center gap-6">
      <div className="relative h-[148px] w-[148px] shrink-0" onMouseLeave={() => setActive(-1)}>
        <svg viewBox="0 0 140 140" width={148} height={148} style={{ transform: `scale(${0.9 + 0.1 * p})` }}>
          {circles}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-display text-[28px] font-bold leading-none" style={{ color: "var(--ink)" }}>
            {centerNum}
          </span>
          <span className="mt-1 max-w-[92px] text-center text-[10.5px] leading-tight" style={{ color: "var(--muted-2)" }}>
            {centerLabel}
          </span>
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-0.5 text-[13.5px]">
        {data.map((d, i) => (
          <div
            key={d.key}
            onMouseEnter={() => setActive(i)}
            className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 transition"
            style={{ background: active === i ? "#F3E9DA" : "transparent" }}
          >
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: d.color }} />
            <span style={{ color: "var(--ink-strong)" }}>{d.name}</span>
            <span className="ml-auto font-display font-bold" style={{ color: "var(--ink)" }}>{d.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Last-visit vertical bars ── */
function VisitBars({ data }: { data: { label: string; count: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  return (
    <div className="flex h-[158px] items-end gap-4">
      {data.map((d, i) => {
        const hPct = d.count === 0 ? 0 : Math.max(6, (d.count / max) * 88);
        return (
          <div key={d.label} className="flex h-full flex-1 flex-col items-center justify-end gap-2">
            <span className="font-display text-xs font-bold" style={{ color: d.count > 0 ? (i === 0 ? "var(--accent)" : "var(--amber)") : "#C9B39A" }}>
              {d.count}
            </span>
            {d.count === 0 ? (
              <div className="w-full max-w-[58px] rounded-[3px]" style={{ height: 3, background: "#E6D8C6" }} />
            ) : (
              <div
                className="w-full max-w-[58px] cursor-pointer rounded-t-lg transition hover:brightness-110"
                style={{
                  height: `${hPct}%`,
                  background: i === 0 ? "linear-gradient(180deg,#C76B3A,#B4532A)" : "var(--amber)",
                  transformOrigin: "bottom",
                  animation: `growUp .8s cubic-bezier(.2,.8,.2,1) ${0.4 + i * 0.09}s both`,
                }}
              />
            )}
            <span className="text-[11px]" style={{ color: "var(--muted)" }}>{d.label}</span>
          </div>
        );
      })}
    </div>
  );
}

/* ── Revenue area chart with scrub + range toggle ── */
function RevenuePanel({ series, p }: { series: { month: string; amount: number }[]; p: number }) {
  const [range, setRange] = useState<6 | 12>(12);
  const [hover, setHover] = useState(-1);
  const wrapRef = useRef<HTMLDivElement>(null);

  const data = range === 6 ? series.slice(-6) : series.slice(-12);
  const n = data.length;
  const W = 520, H = 180, pl = 8, pr = 8, pt = 16, pb = 30;
  const maxV = Math.max(1, ...data.map((d) => d.amount)) * 1.05;
  const x = (i: number) => pl + (W - pl - pr) * (n <= 1 ? 0 : i / (n - 1));
  const y = (v: number) => H - pb - (v / maxV) * (H - pb - pt);

  const pts = data.map((d, i) => [x(i), y(d.amount)] as const);
  const line = pts.map((q, i) => `${i ? "L" : "M"}${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" ");
  const area = n > 0 ? `${line} L${x(n - 1).toFixed(1)},${H - pb} L${x(0).toFixed(1)},${H - pb} Z` : "";

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const rx = ((e.clientX - rect.left) / rect.width) * W;
    let best = 0, bd = Infinity;
    for (let i = 0; i < n; i++) {
      const dd = Math.abs(x(i) - rx);
      if (dd < bd) { bd = dd; best = i; }
    }
    setHover(best);
  };

  const btn = (active: boolean): React.CSSProperties =>
    active
      ? { padding: "6px 16px", borderRadius: 999, fontSize: 13, fontWeight: 600, cursor: "pointer", color: "var(--cream-text)", background: "var(--ink-strong)" }
      : { padding: "6px 16px", borderRadius: 999, fontSize: 13, fontWeight: 600, cursor: "pointer", color: "var(--muted)" };

  return (
    <div className="glass anim-fade-up p-6" style={{ animationDelay: "0.42s" }}>
      <div className="mb-1 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-xl font-semibold" style={{ color: "var(--ink)" }}>Revenue Over Time</h3>
          <p className="text-[13px]" style={{ color: "var(--muted-2)" }}>Scrub the line for monthly totals</p>
        </div>
        <div className="flex shrink-0 gap-0.5 rounded-full p-[3px]" style={{ background: "var(--surface-3)" }}>
          <button style={btn(range === 6)} onClick={() => { setRange(6); setHover(-1); }}>6M</button>
          <button style={btn(range === 12)} onClick={() => { setRange(12); setHover(-1); }}>1Y</button>
        </div>
      </div>

      <div ref={wrapRef} className="relative mt-2 w-full">
        <svg
          viewBox={`0 0 ${W} ${H}`} width="100%" height={180}
          style={{ display: "block", cursor: "crosshair" }}
          onMouseMove={onMove} onMouseLeave={() => setHover(-1)}
        >
          <defs>
            <linearGradient id="revg" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#B4532A" stopOpacity="0.24" />
              <stop offset="1" stopColor="#B4532A" stopOpacity="0" />
            </linearGradient>
          </defs>
          {[0, 0.5, 1].map((g) => (
            <line key={g} x1={pl} x2={W - pr} y1={y(maxV * g)} y2={y(maxV * g)} stroke="#EADDCC" strokeWidth={1} />
          ))}
          {n > 0 && <path d={area} fill="url(#revg)" style={{ opacity: p }} />}
          {n > 0 && (
            <path
              d={line} fill="none" stroke="#B4532A" strokeWidth={2.5}
              strokeLinecap="round" strokeLinejoin="round"
              strokeDasharray={2600} strokeDashoffset={2600 * (1 - p)}
            />
          )}
          {data.map((d, i) =>
            (n <= 6 || i % 2 === 0) ? (
              <text key={i} x={x(i)} y={H - 9} fontSize={10} fill="#A58C74" textAnchor="middle">
                {d.month}
              </text>
            ) : null
          )}
          {hover >= 0 && hover < n && (
            <>
              <line x1={x(hover)} x2={x(hover)} y1={pt} y2={H - pb} stroke="#B4532A" strokeWidth={1} strokeDasharray="3 3" opacity={0.5} />
              <circle cx={x(hover)} cy={y(data[hover].amount)} r={5.5} fill="#B4532A" stroke="#FBF6EE" strokeWidth={2.5} />
            </>
          )}
        </svg>
        {hover >= 0 && hover < n && (
          <div
            className="pointer-events-none absolute whitespace-nowrap rounded-lg px-3 py-1.5 text-[12.5px] font-semibold"
            style={{
              left: `${(x(hover) / W) * 100}%`,
              top: `${(y(data[hover].amount) / H) * 100}%`,
              transform: "translate(-50%,-135%)",
              background: "var(--ink)",
              color: "var(--cream-text)",
              boxShadow: "0 6px 16px -6px rgba(0,0,0,.5)",
            }}
          >
            {data[hover].month} · {formatCurrency(data[hover].amount)}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Why-they-leave horizontal bars ── */
function PatternBars({ data }: { data: { name: string; value: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  if (data.length === 0) {
    return <p className="text-sm" style={{ color: "var(--muted-2)" }}>No churn patterns detected yet.</p>;
  }
  return (
    <div className="flex flex-col gap-4">
      {data.map((d, i) => (
        <div key={d.name} className="flex items-center gap-3">
          <span className="w-[104px] text-right text-[12.5px]" style={{ color: "#6B5647" }}>{d.name}</span>
          <div className="h-[18px] flex-1 overflow-hidden rounded-md" style={{ background: "var(--surface-3)" }}>
            <div
              className="flex h-full items-center justify-end rounded-md pr-2"
              style={{
                width: `${Math.max(10, (d.value / max) * 100)}%`,
                background: PATTERN_BAR_COLORS[Math.min(i, PATTERN_BAR_COLORS.length - 1)],
                transformOrigin: "left",
                animation: `growRight .9s cubic-bezier(.2,.8,.2,1) ${0.5 + i * 0.08}s both`,
              }}
            >
              <span className="text-[11px] font-bold text-white">{d.value}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
