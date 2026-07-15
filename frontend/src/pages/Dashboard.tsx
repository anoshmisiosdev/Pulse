import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
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

function useInView<T extends HTMLElement>(rootMargin = "0px 0px -10% 0px") {
  const ref = useRef<T>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || !("IntersectionObserver" in window)) {
      setVisible(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin, threshold: 0.08 }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [rootMargin]);

  return [ref, visible] as const;
}

function Reveal({ children, className = "", delay = 0, style }: {
  children: ReactNode;
  className?: string;
  delay?: number;
  style?: CSSProperties;
}) {
  const [ref, visible] = useInView<HTMLDivElement>();
  return (
    <div
      ref={ref}
      className={`reveal ${visible ? "is-visible" : ""} ${className}`}
      style={{ ...style, "--reveal-delay": `${delay}ms` } as CSSProperties}
    >
      {children}
    </div>
  );
}

function AnimatedNumber({ value, format }: { value: number; format: (n: number) => string }) {
  const [ref, visible] = useInView<HTMLSpanElement>();
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    if (!visible) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setDisplay(value);
      return;
    }

    let raf = 0;
    const started = performance.now();
    const duration = 760;
    const tick = (now: number) => {
      const t = Math.min(1, (now - started) / duration);
      setDisplay(value * (1 - Math.pow(1 - t, 4)));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, visible]);

  return (
    <span ref={ref} aria-label={format(value)}>
      <span aria-hidden="true">{format(display)}</span>
    </span>
  );
}

export default function Dashboard() {
  const { customers, portfolio, revenueRecovered, activity } = usePulse();
  const s = portfolio?.summary;
  const top = customers[0];

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
  const attentionShare = customers.length ? Math.round((needAttention / customers.length) * 100) : 0;
  const revenuePoints = (s?.revenue_series ?? []).slice(-8).map((item) => item.amount);
  const sentToday = activity.filter((item) => item.status === "sent").length;

  return (
    <div className="dashboard-page">
      {top && (
        <HeroCommandCenter
          customer={top}
          customers={customers}
          needAttention={needAttention}
          revenueAtRisk={s?.revenue_at_risk ?? 0}
        />
      )}

      <section className="kpi-grid" aria-label="Retention summary">
        <KpiCard
          delay={0}
          label="Revenue exposure"
          value={s?.revenue_at_risk ?? 0}
          format={formatCurrency}
          meta={`${s?.high_risk ?? 0} high-risk customers`}
          tone="risk"
          points={revenuePoints}
        />
        <KpiCard
          delay={70}
          label="Need attention"
          value={needAttention}
          format={(n) => String(Math.round(n))}
          meta={`${attentionShare}% of your customer base`}
          tone="watch"
          points={visitData.map((item) => item.count)}
        />
        <KpiCard
          delay={140}
          label="Average time away"
          value={s?.avg_days_away ?? 0}
          format={(n) => `${Math.round(n)} days`}
          meta={`Across ${customers.length} tracked customers`}
          tone="neutral"
          points={customers.slice(0, 8).map((item) => item.days_since_last_visit ?? 0).reverse()}
        />
        <KpiCard
          delay={210}
          label="Pulse in action"
          value={revenueRecovered}
          format={formatCurrency}
          meta={revenueRecovered > 0 ? `${sentToday} messages sent today` : `${sentToday} messages working now`}
          tone="healthy"
          points={activity.slice(0, 8).map((_, index) => index + 1)}
        />
      </section>

      {top && <SignalStory customer={top} />}

      <div className="dashboard-grid">
        <Panel className="health-panel" title="Customer health" subtitle="A live view of relationship momentum" delay={0}>
          <HealthDonut data={segData} />
        </Panel>

        <RevenuePanel series={s?.revenue_series ?? []} />

        <Panel className="visit-panel" title="Return cadence" subtitle="Where your visit rhythm is beginning to break" delay={0}>
          <VisitBars data={visitData} />
        </Panel>

        <Panel className="pattern-panel" title="Behavior signals" subtitle="The patterns Pulse is connecting across your customer base" delay={80}>
          <PatternBars data={patternData} />
        </Panel>
      </div>
    </div>
  );
}

function HeroCommandCenter({ customer, customers, needAttention, revenueAtRisk }: {
  customer: CustomerRisk;
  customers: CustomerRisk[];
  needAttention: number;
  revenueAtRisk: number;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const pointerFrame = useRef(0);
  const radarCustomers = useMemo(
    () => customers
      .filter((item) => item.segment === "needs_attention" || item.segment === "slipping_away" || item.segment === "keep_an_eye_on")
      .slice(0, 6),
    [customers]
  );
  const [selectedId, setSelectedId] = useState(customer.customer_id);
  const selectedCustomer = radarCustomers.find((item) => item.customer_id === selectedId) ?? customer;
  const selectedIndex = Math.max(0, radarCustomers.findIndex((item) => item.customer_id === selectedCustomer.customer_id));
  const selectedInitials = selectedCustomer.name.split(" ").map((part) => part[0]).slice(0, 2).join("");
  const selectedFirstName = selectedCustomer.name.split(" ")[0];

  useEffect(() => {
    if (!radarCustomers.some((item) => item.customer_id === selectedId)) {
      setSelectedId(radarCustomers[0]?.customer_id ?? customer.customer_id);
    }
  }, [customer.customer_id, radarCustomers, selectedId]);

  useEffect(() => () => cancelAnimationFrame(pointerFrame.current), []);

  const selectAdjacent = (direction: number) => {
    if (!radarCustomers.length) return;
    const next = (selectedIndex + direction + radarCustomers.length) % radarCustomers.length;
    setSelectedId(radarCustomers[next].customer_id);
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const node = cardRef.current;
    if (event.pointerType === "touch" || !node) return;
    const { clientX, clientY } = event;
    cancelAnimationFrame(pointerFrame.current);
    pointerFrame.current = requestAnimationFrame(() => {
      const rect = node.getBoundingClientRect();
      node.style.setProperty("--pointer-x", `${clientX - rect.left}px`);
      node.style.setProperty("--pointer-y", `${clientY - rect.top}px`);
    });
  };

  return (
    <Reveal className="hero-command-wrap">
      <div ref={cardRef} className="hero-command" onPointerMove={handlePointerMove}>
        <div className="hero-glow" />

        <div className="hero-topbar">
          <div className="hero-date-group">
            <span className="dashboard-date">
              {new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric" }).format(new Date())}
            </span>
            <span className="hero-status"><span /> Pulse is monitoring</span>
          </div>
          <div className="hero-portfolio-summary">
            <span>{needAttention} active {needAttention === 1 ? "signal" : "signals"}</span>
            <strong>{formatCurrency(revenueAtRisk)} exposed</strong>
          </div>
        </div>

        <div className="hero-copy">
          <p className="hero-overline">Retention intelligence, live</p>
          <h1>See the quiet signals <em>before customers disappear.</em></h1>
          <p className="hero-intro">
            Pulse connected the behavior behind {needAttention} customer {needAttention === 1 ? "relationship" : "relationships"}.
            Select a signal to understand what changed and open the exact recovery plan.
          </p>
          <div className="hero-impact-row">
            <div><span>Relationships to recover</span><strong>{needAttention}</strong></div>
            <div><span>Annual value in motion</span><strong>{formatCurrency(revenueAtRisk)}</strong></div>
          </div>
        </div>

        <div className="signal-visual" aria-label={`${needAttention} selectable customer signals, representing ${formatCurrency(revenueAtRisk)} in annual revenue`}>
          <div className="signal-grid" />
          <div className="signal-controls">
            <span>Select a customer signal</span>
            <div>
              <button type="button" aria-label="Previous customer signal" onClick={() => selectAdjacent(-1)}>←</button>
              <span>{selectedIndex + 1} / {radarCustomers.length}</span>
              <button type="button" aria-label="Next customer signal" onClick={() => selectAdjacent(1)}>→</button>
            </div>
          </div>
          <div className="signal-ring ring-one" />
          <div className="signal-ring ring-two" />
          <div className="signal-core">
            <span className="signal-core-ping" />
            <b>{needAttention}</b>
            <small>signals</small>
          </div>
          {radarCustomers.map((item, index) => {
            const positions = [
              [18, 28], [76, 18], [87, 58], [69, 78], [25, 76], [49, 33],
            ];
            const [x, y] = positions[index];
            const initials = item.name.split(" ").map((part) => part[0]).slice(0, 2).join("");
            const isSelected = item.customer_id === selectedCustomer.customer_id;
            return (
              <button
                type="button"
                key={item.customer_id}
                className={`signal-node signal-node-${index + 1} ${isSelected ? "is-active" : ""}`}
                style={{ "--node-x": `${x}%`, "--node-y": `${y}%`, "--node-delay": `${index * 170}ms` } as CSSProperties}
                aria-label={`Inspect ${item.name}, risk score ${item.score}`}
                aria-pressed={isSelected}
                onClick={() => setSelectedId(item.customer_id)}
              >
                <span>{initials}</span>
              </button>
            );
          })}
          <div className="signal-caption">
            <span>Selected signal</span>
            <strong>{selectedCustomer.name} · Risk {selectedCustomer.score}</strong>
          </div>
        </div>

        <div key={selectedCustomer.customer_id} className="hero-action-dock" aria-live="polite">
          <div className="hero-selected-avatar">{selectedInitials}</div>
          <div className="hero-selected-copy">
            <span>Opportunity {selectedIndex + 1} of {radarCustomers.length}</span>
            <h2>Bring {selectedCustomer.name} back into the rhythm.</h2>
            <p>{selectedCustomer.reasons[0]}</p>
          </div>
          <div className="hero-facts">
            <div>
              <span>Value at risk</span>
              <strong>{formatCurrency(selectedCustomer.estimated_annual_value)}</strong>
            </div>
            <div>
              <span>Days away</span>
              <strong>{selectedCustomer.days_since_last_visit ?? "—"}</strong>
            </div>
            <div>
              <span>Confidence</span>
              <strong>{selectedCustomer.confidence}</strong>
            </div>
          </div>
          <Link to={`/retention?customer=${encodeURIComponent(selectedCustomer.customer_id)}`} className="hero-cta">
            Open {selectedFirstName}'s plan <span aria-hidden="true">↗</span>
          </Link>
        </div>
      </div>
    </Reveal>
  );
}

function Sparkline({ points }: { points: number[] }) {
  const safe = points.length > 1 ? points : [0, 0];
  const max = Math.max(...safe);
  const min = Math.min(...safe);
  const range = Math.max(1, max - min);
  const path = safe.map((point, index) => {
    const x = (index / (safe.length - 1)) * 112;
    const y = 30 - ((point - min) / range) * 24;
    return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const lastY = 30 - ((safe[safe.length - 1] - min) / range) * 24;
  return (
    <svg className="kpi-spark" viewBox="0 0 112 36" aria-hidden="true">
      <path d={path} pathLength="1" />
      <circle cx="112" cy={lastY} r="2.5" />
    </svg>
  );
}

function KpiCard({ label, value, meta, tone, delay, points, format }: {
  label: string;
  value: number;
  meta: string;
  tone: "risk" | "watch" | "neutral" | "healthy";
  delay: number;
  points: number[];
  format: (n: number) => string;
}) {
  return (
    <Reveal className={`kpi-card kpi-${tone}`} delay={delay}>
      <div className="kpi-topline">
        <span className="kpi-label"><i /> {label}</span>
        <span className="kpi-live">Live</span>
      </div>
      <div className="kpi-reading">
        <p className="stat-number"><AnimatedNumber value={value} format={format} /></p>
        <Sparkline points={points} />
      </div>
      <p className="kpi-meta">{meta}</p>
    </Reveal>
  );
}

function SignalStory({ customer }: { customer: CustomerRisk }) {
  const cadence = customer.days_since_last_visit && customer.visit_count > 1
    ? `${customer.days_since_last_visit} days since last visit`
    : "Visit rhythm changed";
  return (
    <Reveal className="signal-story">
      <div className="story-heading">
        <span className="eyebrow">How Pulse thinks</span>
        <h2>One quiet change. One clear path back.</h2>
        <p>Pulse turns scattered behavior into a recovery moment your team can act on.</p>
      </div>
      <div className="story-track">
        <div className="story-line"><span /></div>
        <article>
          <span className="story-index">01</span>
          <div className="story-icon">⌁</div>
          <p>Signal noticed</p>
          <strong>{cadence}</strong>
        </article>
        <article>
          <span className="story-index">02</span>
          <div className="story-icon">✦</div>
          <p>Pattern connected</p>
          <strong>{customer.pattern ? PATTERNS[customer.pattern] : "Emerging change"}</strong>
        </article>
        <article>
          <span className="story-index">03</span>
          <div className="story-icon">↗</div>
          <p>Action prepared</p>
          <strong>{customer.favorite_item ? `Personalize with ${customer.favorite_item}` : "Personal win-back ready"}</strong>
        </article>
      </div>
    </Reveal>
  );
}

function Panel({ title, subtitle, delay, children, className = "" }: {
  title: string; subtitle: string; delay: number; children: React.ReactNode; className?: string;
}) {
  return (
    <Reveal className={`dashboard-panel ${className}`} delay={delay}>
      <div className="panel-heading">
        <div>
          <h3>{title}</h3>
          <p>{subtitle}</p>
        </div>
        <span className="panel-signal" aria-hidden="true"><i /><i /><i /></span>
      </div>
      <div className="panel-content">{children}</div>
    </Reveal>
  );
}

/* ── Donut with legend-hover focus ── */
function HealthDonut({ data }: {
  data: { key: string; name: string; value: number; color: string }[];
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
        className="donut-segment"
        strokeWidth={isActive ? 21 : 15}
        strokeDasharray={`${Math.max(0, len - 3)} ${C}`}
        transform={`rotate(${start} ${cx} ${cy})`}
        opacity={dim ? 0.32 : 1}
        style={{ transition: "stroke-width .2s ease, opacity .2s ease", "--segment-length": len } as CSSProperties}
      />
    );
  });

  const centerNum = active === -1 ? total : data[active].value;
  const centerLabel = active === -1 ? "tracked" : data[active].name;

  return (
    <div className="flex items-center gap-6">
      <div className="relative h-[148px] w-[148px] shrink-0" onPointerLeave={() => setActive(-1)}>
        <svg viewBox="0 0 140 140" width={148} height={148}>
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
          <button
            type="button"
            key={d.key}
            onPointerEnter={() => setActive(i)}
            onFocus={() => setActive(i)}
            onClick={() => setActive(active === i ? -1 : i)}
            className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition"
            style={{ background: active === i ? "#F3E9DA" : "transparent" }}
          >
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: d.color }} />
            <span style={{ color: "var(--ink-strong)" }}>{d.name}</span>
            <span className="ml-auto font-display font-bold" style={{ color: "var(--ink)" }}>{d.value}</span>
          </button>
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
                className="chart-bar visit-bar w-full max-w-[58px] cursor-pointer rounded-t-lg transition hover:brightness-110"
                style={{
                  height: `${hPct}%`,
                  background: i === 0 ? "linear-gradient(180deg,#C76B3A,#B4532A)" : "var(--amber)",
                  "--chart-delay": `${160 + i * 80}ms`,
                } as CSSProperties}
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
function RevenuePanel({ series }: { series: { month: string; amount: number }[] }) {
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

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
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
      ? { padding: "6px 16px", borderRadius: 999, fontSize: 13, fontWeight: 600, cursor: "pointer", color: "var(--cream-text)" }
      : { padding: "6px 16px", borderRadius: 999, fontSize: 13, fontWeight: 600, cursor: "pointer", color: "var(--muted)" };

  return (
    <Reveal className="dashboard-panel revenue-panel" delay={70}>
      <div className="panel-heading">
        <div>
          <h3>Revenue momentum</h3>
          <p>Scrub the line to inspect how customer value is moving</p>
        </div>
        <div className="range-toggle">
          <span className={range === 6 ? "range-pill range-left" : "range-pill range-right"} />
          <button aria-pressed={range === 6} style={btn(range === 6)} onClick={() => { setRange(6); setHover(-1); }}>6M</button>
          <button aria-pressed={range === 12} style={btn(range === 12)} onClick={() => { setRange(12); setHover(-1); }}>1Y</button>
        </div>
      </div>

      <div ref={wrapRef} className="relative mt-2 w-full">
        <svg
          viewBox={`0 0 ${W} ${H}`} width="100%" height={180}
          style={{ display: "block", cursor: "crosshair" }}
          onPointerMove={onMove} onPointerLeave={() => setHover(-1)}
          aria-label="Monthly revenue trend. Move across the chart to inspect values."
          role="img"
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
          {n > 0 && <path className="revenue-area" d={area} fill="url(#revg)" />}
          {n > 0 && (
            <path
              className="revenue-line"
              d={line} fill="none" stroke="#B4532A" strokeWidth={2.5}
              strokeLinecap="round" strokeLinejoin="round"
              pathLength="1" strokeDasharray="1" strokeDashoffset="0"
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
    </Reveal>
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
              className="chart-bar pattern-bar flex h-full items-center justify-end rounded-md pr-2"
              style={{
                width: `${Math.max(10, (d.value / max) * 100)}%`,
                background: PATTERN_BAR_COLORS[Math.min(i, PATTERN_BAR_COLORS.length - 1)],
                "--chart-delay": `${180 + i * 80}ms`,
              } as CSSProperties}
            >
              <span className="text-[11px] font-bold text-white">{d.value}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
