import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

/* ─────────────────────────────────────────────────────────────
   Public marketing landing page. Fully self-contained: no data
   dependencies, CTAs route to /login. Coffeehouse Editorial brand.
   ───────────────────────────────────────────────────────────── */

/** 0→1 mount progress, easeOutCubic — drives hero count-ups. */
function useMountProgress(duration = 1400): number {
  const [p, setP] = useState(0);
  useEffect(() => {
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      setP(1 - Math.pow(1 - t, 3));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [duration]);
  return p;
}

/** Adds .lp-visible to .lp-reveal elements as they scroll into view. */
function useScrollReveal() {
  useEffect(() => {
    const els = document.querySelectorAll(".lp-reveal");
    const io = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("lp-visible");
            io.unobserve(e.target);
          }
        }),
      { threshold: 0.15 }
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
}

export default function Landing() {
  useScrollReveal();
  const p = useMountProgress();

  return (
    <div style={{ background: "var(--bg-page)", overflowX: "hidden" }}>
      <style>{LP_CSS}</style>
      <Nav />
      <Hero p={p} />
      <RiskDemo />
      <HowItWorks />
      <Features />
      <Marquee />
      <Pricing />
      <FinalCta />
      <Footer />
    </div>
  );
}

/* ── Nav ── */
function Nav() {
  return (
    <header
      className="sticky top-0 z-40 border-b"
      style={{ background: "rgba(251,246,238,.86)", backdropFilter: "blur(10px)", borderColor: "#E6D8C6" }}
    >
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3.5">
        <div className="flex items-center gap-2.5">
          <span
            className="font-logo inline-flex h-[30px] w-[30px] items-center justify-center rounded-full text-[19px]"
            style={{ background: "var(--ink-strong)", color: "var(--cream-text)" }}
          >
            C
          </span>
          <span className="font-display text-[21px] font-bold tracking-tight" style={{ color: "var(--ink)" }}>
            Churnary
          </span>
        </div>
        <nav className="hidden items-center gap-1 md:flex">
          {[
            ["#demo", "Live demo"],
            ["#how", "How it works"],
            ["#features", "Features"],
            ["#pricing", "Pricing"],
          ].map(([href, label]) => (
            <a
              key={href}
              href={href}
              className="rounded-full px-3.5 py-2 text-sm font-semibold transition hover:bg-[#F0E6D6]"
              style={{ color: "var(--muted)" }}
            >
              {label}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-3">
          <Link
            to="/login"
            className="rounded-full px-4 py-2 text-sm font-semibold transition hover:bg-[#F0E6D6]"
            style={{ color: "var(--ink-strong)" }}
          >
            Sign in
          </Link>
          <Link
            to="/login"
            className="rounded-full px-5 py-2.5 text-sm font-semibold text-white transition hover:-translate-y-px"
            style={{ background: "var(--accent)", boxShadow: "0 6px 16px -6px rgba(180,83,42,.7)" }}
          >
            Start free trial
          </Link>
        </div>
      </div>
    </header>
  );
}

/* ── Hero with cursor spotlight + tilt preview ── */
function Hero({ p }: { p: number }) {
  const ref = useRef<HTMLDivElement>(null);

  const onMove = (e: React.MouseEvent) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${e.clientX - r.left}px`);
    el.style.setProperty("--my", `${e.clientY - r.top}px`);
  };

  const money = (n: number) => "$" + Math.round(n).toLocaleString();

  return (
    <section
      ref={ref}
      onMouseMove={onMove}
      className="relative"
      style={{
        background:
          "radial-gradient(560px 380px at var(--mx, 70%) var(--my, 20%), rgba(180,83,42,.14), transparent 70%), radial-gradient(1200px 600px at 80% -10%, #FBF6EE 0%, #F0E7D8 55%, #EBE0CE 100%)",
      }}
    >
      <div className="mx-auto grid max-w-6xl items-center gap-12 px-6 pb-20 pt-16 lg:grid-cols-[1.1fr_1fr]">
        <div>
          <span
            className="lp-fade-1 inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-[12.5px] font-bold"
            style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--accent)", letterSpacing: ".08em", textTransform: "uppercase" }}
          >
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full rounded-full" style={{ background: "var(--accent)", animation: "pulseFade 2.4s ease-out infinite" }} />
              <span className="relative inline-flex h-2 w-2 rounded-full" style={{ background: "var(--accent)" }} />
            </span>
            AI retention for local business
          </span>

          <h1
            className="lp-fade-2 font-display mt-6 text-[52px] font-bold leading-[1.05] tracking-tight md:text-[64px]"
            style={{ color: "var(--ink)" }}
          >
            Win customers back{" "}
            <em style={{ color: "var(--accent)", fontStyle: "italic" }}>before</em> revenue walks out the door.
          </h1>

          <p className="lp-fade-3 mt-5 max-w-lg text-[17px] leading-relaxed" style={{ color: "var(--muted)" }}>
            Churnary watches your Square, Stripe, or CSV data, flags regulars who are quietly slipping away —
            with the reason in plain English — and drafts the win-back email. You just tap approve.
          </p>

          <div className="lp-fade-4 mt-8 flex flex-wrap items-center gap-4">
            <Link
              to="/login"
              className="rounded-full px-7 py-3.5 text-[15px] font-bold text-white transition hover:-translate-y-0.5"
              style={{ background: "var(--accent)", boxShadow: "0 10px 24px -8px rgba(180,83,42,.8)" }}
            >
              Start your 14-day trial →
            </Link>
            <a
              href="#demo"
              className="rounded-full border px-6 py-3.5 text-[15px] font-semibold transition hover:bg-[#F6ECDD]"
              style={{ borderColor: "var(--border)", color: "var(--ink-strong)", background: "var(--surface)" }}
            >
              Try the live demo
            </a>
          </div>

          <div className="lp-fade-5 mt-10 flex gap-10">
            <HeroStat value={money(5806 * p)} label="revenue at risk, caught at one café" />
            <HeroStat value={`${Math.round(120 * p)} sec`} label="from CSV upload to first insight" />
            <HeroStat value={`${(0.9 * p).toFixed(1)}¢`} label="AI cost per win-back email" />
          </div>
        </div>

        <TiltPreview />
      </div>
    </section>
  );
}

function HeroStat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <p className="font-display text-[30px] font-bold leading-none" style={{ color: "var(--ink)" }}>{value}</p>
      <p className="mt-1.5 max-w-[150px] text-xs leading-snug" style={{ color: "var(--muted-2)" }}>{label}</p>
    </div>
  );
}

/* ── 3D-tilt dashboard preview ── */
function TiltPreview() {
  const ref = useRef<HTMLDivElement>(null);

  const onMove = (e: React.MouseEvent) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5;
    const y = (e.clientY - r.top) / r.height - 0.5;
    el.style.transform = `perspective(1000px) rotateY(${x * 10}deg) rotateX(${-y * 10}deg)`;
  };
  const onLeave = () => {
    if (ref.current) ref.current.style.transform = "perspective(1000px) rotateY(0deg) rotateX(0deg)";
  };

  return (
    <div className="lp-fade-4 hidden lg:block" style={{ perspective: 1000 }}>
      <div
        ref={ref}
        onMouseMove={onMove}
        onMouseLeave={onLeave}
        className="rounded-[20px] border p-5 transition-transform duration-150 ease-out"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border)",
          boxShadow: "0 30px 60px -24px rgba(59,42,32,.45)",
          animation: "lpFloat 6s ease-in-out infinite",
        }}
      >
        {/* hero action row */}
        <div
          className="flex items-center gap-3.5 rounded-xl p-4"
          style={{ background: "linear-gradient(115deg,#3B2A20,#4A3527)", color: "var(--cream-text)" }}
        >
          <span className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-base" style={{ background: "var(--accent)" }}>
            <span className="absolute inset-0 rounded-full" style={{ background: "var(--accent)", animation: "pulseFade 2.4s ease-out infinite" }} />
            ☕
          </span>
          <div className="min-w-0">
            <p className="text-[9.5px] font-bold uppercase" style={{ color: "var(--on-espresso-accent)", letterSpacing: ".14em" }}>Your #1 action today</p>
            <p className="font-display text-[15px] font-semibold">Reach out to Isabella Torres</p>
            <p className="truncate text-[11px]" style={{ color: "#CDB9A8" }}>45 days out · 6.9× her usual gap · Loves Avocado Toast</p>
          </div>
          <span className="ml-auto shrink-0 rounded-full px-3 py-1.5 text-[11px] font-bold" style={{ background: "var(--cream-text)", color: "var(--ink-strong)" }}>Send →</span>
        </div>

        {/* KPIs */}
        <div className="mt-3 grid grid-cols-4 gap-2">
          {[
            ["At Risk", "$5,806", "#A23B1E"],
            ["Attention", "6", "#2A211C"],
            ["Days Away", "8", "#2A211C"],
            ["Recovered", "$640", "#4F7A40"],
          ].map(([l, v, c]) => (
            <div key={l} className="rounded-lg p-2.5" style={{ background: "var(--surface-2)" }}>
              <p className="text-[9.5px]" style={{ color: "var(--muted)" }}>{l}</p>
              <p className="font-display text-[17px] font-bold" style={{ color: c }}>{v}</p>
            </div>
          ))}
        </div>

        {/* risk rows */}
        <div className="mt-3 space-y-1.5">
          {[
            ["Isabella Torres", "Critical 91", "#A23B1E", "#F7E3DC"],
            ["Priya Ferreira", "At Risk 62", "#C0632F", "#F7E6DA"],
            ["Marcus Silva", "Watch 48", "#A9781F", "#F4EAD1"],
          ].map(([name, badge, color, bg]) => (
            <div key={name} className="flex items-center justify-between rounded-lg border px-3 py-2" style={{ borderColor: "var(--border-soft)", background: "var(--surface)" }}>
              <span className="text-[12px] font-bold" style={{ color: "var(--ink)" }}>{name}</span>
              <span className="rounded-full px-2 py-0.5 text-[10px] font-bold" style={{ color, background: bg }}>{badge}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── Interactive risk demo — mirrors the real scoring heuristic ── */
const DEMO_VERTICALS = [
  { id: "cafe", label: "Café", interval: 4, unit: "days" },
  { id: "fitness", label: "Gym", interval: 5, unit: "days" },
  { id: "salon", label: "Salon", interval: 35, unit: "days" },
];

function RiskDemo() {
  const [vertical, setVertical] = useState(DEMO_VERTICALS[0]);
  const [days, setDays] = useState(12);

  const ratio = days / vertical.interval;
  const score = Math.min(97, Math.max(3, Math.round(ratio * 27)));
  const band =
    ratio >= 2.5
      ? { label: "Needs Attention", color: "#A23B1E", bg: "#F7E3DC", action: "Churnary drafts a win-back email — you tap approve." }
      : ratio >= 1.5
      ? { label: "Keep an Eye On", color: "#A9781F", bg: "#F4EAD1", action: "Churnary watches daily and flags them the moment risk rises." }
      : { label: "Healthy Regular", color: "#4F7A40", bg: "#E6EFDF", action: "All good — no outreach needed." };

  const maxDays = vertical.interval * 12;

  return (
    <section id="demo" className="mx-auto max-w-6xl scroll-mt-20 px-6 py-20">
      <div className="lp-reveal">
        <SectionHead
          eyebrow="Try it yourself"
          title="This is the entire product, in one slider."
          sub="Drag the slider — Churnary scores churn risk from each customer's own rhythm, and explains it in plain English."
        />
      </div>

      <div className="lp-reveal mx-auto mt-10 max-w-3xl rounded-[20px] border p-8" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
        {/* vertical picker */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="mr-1 text-sm font-semibold" style={{ color: "var(--muted)" }}>A regular at your…</span>
          {DEMO_VERTICALS.map((v) => (
            <button
              key={v.id}
              onClick={() => { setVertical(v); setDays(Math.min(3 * v.interval, v.interval * 12)); }}
              className="rounded-full border px-4 py-1.5 text-sm font-semibold transition"
              style={
                vertical.id === v.id
                  ? { background: "var(--ink-strong)", borderColor: "var(--ink-strong)", color: "var(--cream-text)" }
                  : { background: "var(--surface)", borderColor: "var(--border)", color: "#6B5647" }
              }
            >
              {v.label}
            </button>
          ))}
          <span className="text-sm" style={{ color: "var(--muted-2)" }}>usually visits every {v_label(vertical)}</span>
        </div>

        {/* slider */}
        <div className="mt-8">
          <div className="flex items-baseline justify-between">
            <label className="text-sm font-semibold" style={{ color: "var(--ink-strong)" }}>
              Days since their last visit
            </label>
            <span className="font-display text-3xl font-bold" style={{ color: band.color }}>{days}</span>
          </div>
          <input
            type="range"
            min={1}
            max={maxDays}
            value={Math.min(days, maxDays)}
            onChange={(e) => setDays(Number(e.target.value))}
            className="lp-slider mt-3 w-full"
            style={{ accentColor: band.color, color: band.color }}
          />
          <div className="mt-1 flex justify-between text-[11px]" style={{ color: "var(--muted-2)" }}>
            <span>just visited</span>
            <span>long gone</span>
          </div>
        </div>

        {/* readout */}
        <div className="mt-8 flex flex-col items-start gap-5 rounded-2xl p-6 sm:flex-row sm:items-center" style={{ background: "var(--surface-2)" }}>
          <ScoreDial score={score} color={band.color} />
          <div className="min-w-0 flex-1">
            <span className="inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-[13.5px] font-bold" style={{ background: band.bg, color: band.color }}>
              <span className="h-2 w-2 rounded-full" style={{ background: band.color }} />
              {band.label} · risk {score}
            </span>
            <p className="mt-3 text-[15px]" style={{ color: "var(--ink-strong)" }}>
              “Usually visits every {vertical.interval} days — it's been <b>{days} days</b>
              {ratio >= 1.2 && <> ({ratio.toFixed(1)}× their rhythm)</>}.”
            </p>
            <p className="mt-1.5 text-sm" style={{ color: "var(--muted)" }}>{band.action}</p>
          </div>
        </div>

        <p className="mt-4 text-center text-xs" style={{ color: "var(--muted-2)" }}>
          Same transparent scoring that runs in the product — no black box, every score shows its reasons.
        </p>
      </div>
    </section>
  );
}

function v_label(v: { interval: number; unit: string }) {
  return `${v.interval} ${v.unit}`;
}

function ScoreDial({ score, color }: { score: number; color: string }) {
  const C = 2 * Math.PI * 42;
  return (
    <div className="relative h-[110px] w-[110px] shrink-0">
      <svg viewBox="0 0 100 100" width={110} height={110}>
        <circle cx="50" cy="50" r="42" fill="none" stroke="#EADDCC" strokeWidth="10" />
        <circle
          cx="50" cy="50" r="42" fill="none" stroke={color} strokeWidth="10" strokeLinecap="round"
          strokeDasharray={`${(score / 100) * C} ${C}`}
          transform="rotate(-90 50 50)"
          style={{ transition: "stroke-dasharray .35s cubic-bezier(.2,.8,.2,1), stroke .35s ease" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-display text-[26px] font-bold leading-none" style={{ color }}>{score}</span>
        <span className="text-[9.5px] uppercase" style={{ color: "var(--muted-2)", letterSpacing: ".1em" }}>risk</span>
      </div>
    </div>
  );
}

/* ── How it works ── */
function HowItWorks() {
  const steps = [
    { n: "01", title: "Connect in 2 minutes", body: "Link Square or Stripe, or just upload a customer CSV. No IT department required — if you can attach a file to an email, you can set up Churnary." },
    { n: "02", title: "See who's slipping — and why", body: "Every customer gets a transparent risk score built from their own visit rhythm, with the reason in plain English. No black-box AI to take on faith." },
    { n: "03", title: "Approve the win-back", body: "Churnary drafts a personalized email mentioning their favorite order. You tap approve, it sends, and recovered visits are tracked back to the message." },
  ];
  return (
    <section id="how" className="scroll-mt-20 py-20" style={{ background: "var(--surface)" }}>
      <div className="mx-auto max-w-6xl px-6">
        <div className="lp-reveal">
          <SectionHead eyebrow="How it works" title="Owner-simple, on purpose." sub="Built for people who run a counter, not a CRM." />
        </div>
        <div className="mt-12 grid gap-6 md:grid-cols-3">
          {steps.map((s, i) => (
            <div
              key={s.n}
              className="lp-reveal rounded-[18px] border p-7 transition hover:-translate-y-1"
              style={{ background: "var(--bg-page)", borderColor: "var(--border)", transitionDelay: `${i * 90}ms` }}
            >
              <span className="font-display text-[28px] font-bold" style={{ color: "var(--accent)" }}>{s.n}</span>
              <h3 className="font-display mt-3 text-xl font-semibold" style={{ color: "var(--ink)" }}>{s.title}</h3>
              <p className="mt-2.5 text-[14.5px] leading-relaxed" style={{ color: "var(--muted)" }}>{s.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── Features ── */
function Features() {
  const items = [
    { icon: "◎", title: "Transparent scoring", body: "Every risk score shows its reasons — visit gap, spend drop, favorite item. Trust it today, not “someday, with more AI.”" },
    { icon: "✎", title: "AI drafts, you approve", body: "Claude writes the win-back copy; Suggest / Approve / Autopilot modes keep a human in control. Approve-to-send is the default." },
    { icon: "⛨", title: "Compliant by design", body: "CAN-SPAM unsubscribe on every email, TCPA quiet hours for SMS, and we never touch medical data. Guardrails built in, not bolted on." },
    { icon: "⇄", title: "Works with your tools", body: "Square and Stripe connect live; CSV upload works with anything else. Adding a source never means re-doing your setup." },
    { icon: "◷", title: "Nightly re-scoring", body: "Every customer is re-scored automatically as new visits land. The dashboard is always this-morning fresh." },
    { icon: "$", title: "Attribution you can bank", body: "Recovered customers are tied back to the exact message that brought them in: “3 customers recovered, ~$640 saved.”" },
  ];
  return (
    <section id="features" className="mx-auto max-w-6xl scroll-mt-20 px-6 py-20">
      <div className="lp-reveal">
        <SectionHead eyebrow="Why owners trust it" title="Automation you can hand the keys to." />
      </div>
      <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((f, i) => (
          <div
            key={f.title}
            className="lp-reveal rounded-[18px] border p-6 transition hover:-translate-y-1"
            style={{ background: "var(--surface)", borderColor: "var(--border)", transitionDelay: `${(i % 3) * 90}ms` }}
          >
            <span className="text-2xl" style={{ color: "var(--accent)" }}>{f.icon}</span>
            <h3 className="font-display mt-3 text-lg font-semibold" style={{ color: "var(--ink)" }}>{f.title}</h3>
            <p className="mt-2 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>{f.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ── Marquee ── */
function Marquee() {
  const words = ["Cafés", "Coffee shops", "Salons", "Barbershops", "Fitness studios", "Gyms", "Med spas", "Juice bars", "Bakeries", "Yoga studios"];
  const row = words.map((w, i) => (
    <span key={i} className="mx-6 inline-flex items-center gap-6 font-display text-2xl font-semibold" style={{ color: "var(--cream-text)" }}>
      {w} <span style={{ color: "var(--on-espresso-accent)" }}>·</span>
    </span>
  ));
  return (
    <div className="overflow-hidden py-8" style={{ background: "var(--ink-strong)" }}>
      <div className="lp-marquee whitespace-nowrap">
        {row}
        {row}
      </div>
    </div>
  );
}

/* ── Pricing ── */
function Pricing() {
  const tiers = [
    { name: "Starter", price: 199, blurb: "1 integration · 1,000 customers · email win-backs", hot: false },
    { name: "Growth", price: 299, blurb: "All integrations · 2,500 customers · email + SMS · automations", hot: true },
    { name: "Pro", price: 499, blurb: "Unlimited customers · multi-location ready", hot: false },
  ];
  return (
    <section id="pricing" className="mx-auto max-w-6xl scroll-mt-20 px-6 py-20">
      <div className="lp-reveal">
        <SectionHead
          eyebrow="Pricing"
          title="Pays for itself on the first save."
          sub="A saved regular is worth ~$970/year. Save three and any plan pays for itself. 14-day free trial on every tier."
        />
      </div>
      <div className="mt-12 grid gap-5 md:grid-cols-3">
        {tiers.map((t, i) => (
          <div
            key={t.name}
            className="lp-reveal relative rounded-[20px] border p-7 transition hover:-translate-y-1"
            style={{
              background: t.hot ? "linear-gradient(135deg,#3B2A20,#4A3527)" : "var(--surface)",
              borderColor: t.hot ? "var(--ink-strong)" : "var(--border)",
              transitionDelay: `${i * 90}ms`,
              boxShadow: t.hot ? "0 24px 48px -20px rgba(59,42,32,.6)" : "none",
            }}
          >
            {t.hot && (
              <span className="absolute -top-3 left-7 rounded-full px-3 py-1 text-[11px] font-bold uppercase text-white" style={{ background: "var(--accent)", letterSpacing: ".06em" }}>
                Most popular
              </span>
            )}
            <h3 className="font-display text-xl font-semibold" style={{ color: t.hot ? "var(--cream-text)" : "var(--ink)" }}>{t.name}</h3>
            <p className="mt-4">
              <span className="font-display text-[44px] font-bold" style={{ color: t.hot ? "var(--on-espresso-accent)" : "var(--ink)" }}>${t.price}</span>
              <span className="text-sm" style={{ color: t.hot ? "#CDB9A8" : "var(--muted-2)" }}>/month</span>
            </p>
            <p className="mt-3 text-sm leading-relaxed" style={{ color: t.hot ? "#CDB9A8" : "var(--muted)" }}>{t.blurb}</p>
            <Link
              to="/login"
              className="mt-6 block rounded-full py-2.5 text-center text-sm font-bold transition hover:brightness-95"
              style={
                t.hot
                  ? { background: "var(--accent)", color: "#fff" }
                  : { background: "var(--surface-2)", color: "var(--ink-strong)", border: "1px solid var(--border)" }
              }
            >
              Start free trial
            </Link>
          </div>
        ))}
      </div>
      <p className="lp-reveal mt-6 text-center text-xs" style={{ color: "var(--muted-2)" }}>
        14-day trial · annual billing = 2 months free · cancel anytime
      </p>
    </section>
  );
}

/* ── Final CTA ── */
function FinalCta() {
  return (
    <section className="px-6 pb-24 pt-4">
      <div
        className="lp-reveal mx-auto max-w-4xl rounded-[24px] px-8 py-14 text-center"
        style={{ background: "linear-gradient(115deg,#3B2A20,#4A3527)", boxShadow: "0 30px 60px -28px rgba(59,42,32,.8)" }}
      >
        <h2 className="font-display text-[34px] font-bold leading-tight md:text-[42px]" style={{ color: "var(--cream-text)" }}>
          Your regulars are worth fighting for.
        </h2>
        <p className="mx-auto mt-3 max-w-xl text-[15.5px]" style={{ color: "#CDB9A8" }}>
          Upload a CSV and see which customers are at risk — and why — in under two minutes. Free for 14 days.
        </p>
        <Link
          to="/login"
          className="mt-8 inline-block rounded-full px-8 py-4 text-[15px] font-bold text-white transition hover:-translate-y-0.5"
          style={{ background: "var(--accent)", boxShadow: "0 12px 28px -8px rgba(180,83,42,.9)" }}
        >
          Get started free →
        </Link>
      </div>
    </section>
  );
}

/* ── Footer ── */
function Footer() {
  return (
    <footer className="border-t py-10" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-6 sm:flex-row">
        <div className="flex items-center gap-2">
          <span className="font-logo inline-flex h-6 w-6 items-center justify-center rounded-full text-[13px]" style={{ background: "var(--ink-strong)", color: "var(--cream-text)" }}>C</span>
          <span className="font-display text-base font-bold" style={{ color: "var(--ink)" }}>Churnary</span>
          <span className="text-xs" style={{ color: "var(--muted-2)" }}>— AI retention for local business</span>
        </div>
        <div className="flex items-center gap-5 text-xs" style={{ color: "var(--muted-2)" }}>
          <a href="#how" className="hover:underline">How it works</a>
          <a href="#pricing" className="hover:underline">Pricing</a>
          <Link to="/login" className="hover:underline">Sign in</Link>
          <span>© 2026 Churnary</span>
        </div>
      </div>
    </footer>
  );
}

/* ── shared bits ── */
function SectionHead({ eyebrow, title, sub }: { eyebrow: string; title: string; sub?: string }) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <p className="eyebrow" style={{ color: "var(--accent)" }}>{eyebrow}</p>
      <h2 className="font-display mt-3 text-[34px] font-bold leading-tight tracking-tight md:text-[40px]" style={{ color: "var(--ink)" }}>
        {title}
      </h2>
      {sub && <p className="mt-3 text-[15.5px]" style={{ color: "var(--muted)" }}>{sub}</p>}
    </div>
  );
}

const LP_CSS = `
  .lp-reveal { opacity: 0; transform: translateY(26px); transition: opacity .7s ease, transform .7s cubic-bezier(.2,.8,.2,1); }
  .lp-reveal.lp-visible { opacity: 1; transform: translateY(0); }

  .lp-fade-1, .lp-fade-2, .lp-fade-3, .lp-fade-4, .lp-fade-5 { animation: fadeUp .7s ease both; }
  .lp-fade-2 { animation-delay: .08s; }
  .lp-fade-3 { animation-delay: .16s; }
  .lp-fade-4 { animation-delay: .24s; }
  .lp-fade-5 { animation-delay: .34s; }

  @keyframes lpFloat {
    0%, 100% { translate: 0 0; }
    50% { translate: 0 -10px; }
  }

  .lp-marquee { display: inline-block; animation: lpMarquee 28s linear infinite; }
  @keyframes lpMarquee {
    from { transform: translateX(0); }
    to   { transform: translateX(-50%); }
  }

  .lp-slider { height: 8px; border-radius: 999px; background: var(--surface-3); appearance: none; -webkit-appearance: none; cursor: pointer; }
  .lp-slider::-webkit-slider-thumb {
    -webkit-appearance: none; appearance: none;
    width: 26px; height: 26px; border-radius: 50%;
    background: var(--surface); border: 3px solid currentColor;
    box-shadow: 0 3px 8px rgba(59,42,32,.3); cursor: grab;
  }
  .lp-slider:active::-webkit-slider-thumb { cursor: grabbing; transform: scale(1.1); }
  .lp-slider::-moz-range-thumb {
    width: 26px; height: 26px; border-radius: 50%;
    background: var(--surface); border: 3px solid currentColor;
    box-shadow: 0 3px 8px rgba(59,42,32,.3); cursor: grab;
  }

  html { scroll-behavior: smooth; }
`;
