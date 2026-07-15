import useMountProgress from "../hooks/useMountProgress";
import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { usePulse } from "../context/PulseContext";
import { formatCurrency, type CustomerRisk } from "../lib/api";
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
  const top = customers[0];
  const p = useMountProgress();

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

  const needAttention = customers.filter(
    (c) => c.segment === "needs_attention" || c.segment === "slipping_away"
  ).length;

  return (
    <div className="space-y-6">
      <div className="anim-fade-up">
        <h1 className="text-[38px] font-bold tracking-tight" style={{ color: "var(--ink)" }}>Dashboard</h1>
        <p className="mt-1 italic" style={{ color: "var(--muted)", fontSize: "15.5px" }}>
          Here's how your customers are doing today
        </p>
      </div>

      {top && <HeroAction customer={top} />}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiCard delay={0.1} dot="#A23B1E" label="Revenue at Risk" valueColor="#A23B1E"
          value={formatCurrency((s?.revenue_at_risk ?? 0) * p)} sub="Could lose this year" />
        <KpiCard delay={0.16} dot="#D99A4E" label="Need Attention"
          value={String(Math.round(needAttention * p))} sub="customers may not return" />
        <KpiCard delay={0.22} dot="#8A7565" label="Avg. Days Away"
          value={String(Math.round((s?.avg_days_away ?? 0) * p))} sub="since last visit" />
        <KpiCard delay={0.28} dot="#5C8A4A" label="Retained" valueColor="#5C8A4A"
          value={formatCurrency(revenueRecovered * p)}
          sub={revenueRecovered > 0 ? "recovered so far" : "start reaching out!"} />
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

function HeroAction({ customer }: { customer: CustomerRisk }) {
  return (
    <Link
      to="/retention"
      className="anim-fade-up flex items-center gap-5 rounded-[18px] p-6 transition hover:-translate-y-0.5"
      style={{
        animationDelay: "0.05s",
        background: "linear-gradient(115deg,#3B2A20,#4A3527)",
        color: "var(--cream-text)",
        boxShadow: "0 20px 40px -24px rgba(59,42,32,.8)",
      }}
    >
      <div className="relative h-[50px] w-[50px] shrink-0">
        <span
          className="absolute inset-0 rounded-full"
          style={{ background: "var(--accent)", animation: "pulseFade 2.4s ease-out infinite" }}
        />
        <span
          className="absolute inset-0 flex items-center justify-center rounded-full text-xl text-white"
          style={{ background: "var(--accent)" }}
        >
          ☕
        </span>
      </div>
      <div className="min-w-0 flex-1">
        <p className="eyebrow mb-1" style={{ color: "var(--on-espresso-accent)" }}>Your #1 action today</p>
        <p className="font-display text-[22px] font-semibold">Reach out to {customer.name}</p>
        <p className="mt-0.5 truncate text-sm" style={{ color: "#CDB9A8" }}>
          {customer.reasons[0]}
          {customer.favorite_item && <> · Loves {customer.favorite_item}</>}
        </p>
      </div>
      <span
        className="hidden shrink-0 rounded-full px-5 py-3 text-sm font-bold sm:block"
        style={{ background: "var(--cream-text)", color: "var(--ink-strong)" }}
      >
        Go to Retention →
      </span>
    </Link>
  );
}

function KpiCard({ dot, label, value, sub, valueColor, delay }: {
  dot: string; label: string; value: string; sub: string; valueColor?: string; delay: number;
}) {
  return (
    <div className="glass glass-hover anim-fade-up p-5" style={{ animationDelay: `${delay}s` }}>
      <div className="mb-3.5 flex items-center gap-2">
        <span className="h-2 w-2 rounded-full" style={{ background: dot }} />
        <span className="text-[12.5px] font-semibold" style={{ color: "var(--muted)" }}>{label}</span>
      </div>
      <p className="stat-number text-[32px]" style={{ color: valueColor ?? "var(--ink)" }}>{value}</p>
      <p className="mt-1.5 text-xs" style={{ color: "var(--muted-2)" }}>{sub}</p>
    </div>
  );
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
