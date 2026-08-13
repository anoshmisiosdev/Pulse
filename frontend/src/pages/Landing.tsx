import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import adityaPhoto from "../assets/team/aditya-kolekar.jpg";
import pranjalPhoto from "../assets/team/pranjal-mishra.jpg";
import sohamPhoto from "../assets/team/soham-dogra.jpg";
import ChurnaryMark from "../components/ChurnaryMark";
import WaitlistForm from "../components/WaitlistForm";
import useMountProgress from "../hooks/useMountProgress";
import { landingViewMetric, trackLandingEvent } from "../lib/landingAnalytics";
import {
  hasAnalyticsConsent,
  onPrivacyPreferenceChange,
  openPrivacyChoices,
} from "../lib/privacyPreferences";

/* ─────────────────────────────────────────────────────────────
   Public marketing landing page. Fully self-contained: no data
   dependencies beyond the public waitlist POST.

   Layout follows a drafting-sheet system rather than a stack of
   floating cards: a gutter that grows with the viewport (so wide
   monitors gain content, not margin), full-bleed hairline rules
   between sections, and blocks divided by 1px lines instead of
   gaps. Buttons are crisp, not pills; display type is set at 600
   with tight tracking. Shadows are reserved for things that
   genuinely float (the hero preview), never for flat content.

   Motion is hand-rolled rather than pulled from GSAP: the three
   effects used here (char stagger, scroll-scrubbed word reveal,
   parallax curtain) are a scroll listener and some transforms,
   and CLAUDE.md pins the frontend stack. All are gated on
   prefers-reduced-motion.
   ───────────────────────────────────────────────────────────── */

/** True when the visitor asked the OS to cut animation. */
function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}

/**
 * Module-level scroll scheduler backing useRafScroll below: one "scroll"/
 * "resize" listener and one requestAnimationFrame chain for the whole page,
 * shared by every call site instead of one pair per component instance —
 * that per-instance fan-out (Nav, the hero curtain, 9x ScrubWords headline)
 * was what previously turned a single wheel spin into 11 forced layout
 * passes per frame and froze the tab on a fast scroll.
 */
const rafScrollCallbacks = new Set<() => void>();
let rafScrollHandle = 0;
let rafScrollBound = false;

function runRafScrollCallbacks() {
  rafScrollHandle = 0;
  rafScrollCallbacks.forEach((cb) => cb());
}

function scheduleRafScroll() {
  if (!rafScrollHandle) rafScrollHandle = requestAnimationFrame(runRafScrollCallbacks);
}

/**
 * Add a callback to the shared scroll scheduler, binding the page-wide
 * "scroll"/"resize" listener on first use. Exported (only) so a test can
 * assert the listener fan-out doesn't regress without rendering the page.
 */
export function subscribeRafScroll(cb: () => void): () => void {
  if (!rafScrollBound) {
    rafScrollBound = true;
    window.addEventListener("scroll", scheduleRafScroll, { passive: true });
    window.addEventListener("resize", scheduleRafScroll);
  }
  rafScrollCallbacks.add(cb);
  scheduleRafScroll();
  return () => rafScrollCallbacks.delete(cb);
}

/**
 * Subscribe to scroll, coalesced to one callback per frame.
 *
 * Every scroll-driven effect on this page shares one listener/rAF chain (see
 * the module-level scheduler above) so a fast wheel spin costs one rAF, not
 * one layout pass per listener.
 */
function useRafScroll(onScroll: () => void, enabled = true) {
  const onScrollRef = useRef(onScroll);
  onScrollRef.current = onScroll;

  useEffect(() => {
    if (!enabled) return;
    const cb = () => onScrollRef.current();
    return subscribeRafScroll(cb);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);
}

/** Adds .is-in to every [data-reveal] once it enters the viewport. */
function useRevealOnScroll(reduced: boolean) {
  useEffect(() => {
    const els = Array.from(document.querySelectorAll("[data-reveal]"));
    if (reduced) {
      els.forEach((el) => el.classList.add("is-in"));
      return;
    }
    const io = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("is-in");
            io.unobserve(e.target);
          }
        }),
      { threshold: 0.12, rootMargin: "0px 0px -6% 0px" }
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [reduced]);
}

/** Which nav section is currently under the reader. */
function useActiveSection(ids: string[]): string {
  const [active, setActive] = useState("");
  useEffect(() => {
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) setActive(e.target.id);
      },
      // A tall band across the middle of the viewport: whatever crosses it owns
      // the highlight, which is steadier than "topmost visible".
      { rootMargin: "-45% 0px -50% 0px" }
    );
    ids.forEach((id) => {
      const el = document.getElementById(id);
      if (el) io.observe(el);
    });
    return () => io.disconnect();
  }, [ids]);
  return active;
}

/** Capture the acquisition page once, plus meaningful content reach milestones. */
function useLandingMetrics() {
  const viewed = useRef(false);
  const [enabled, setEnabled] = useState(hasAnalyticsConsent);

  useEffect(
    () => onPrivacyPreferenceChange(() => setEnabled(hasAnalyticsConsent())),
    []
  );

  useEffect(() => {
    if (!enabled || viewed.current) return;
    viewed.current = true;
    void trackLandingEvent(landingViewMetric());
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;
    const seen = new Set<string>();
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting || seen.has(entry.target.id)) return;
          const section = entry.target.id as "demo" | "pricing" | "waitlist";
          seen.add(section);
          void trackLandingEvent({ event: "landing_section_viewed", section });
          io.unobserve(entry.target);
        });
      },
      { threshold: 0.25, rootMargin: "0px 0px -10% 0px" }
    );
    (["demo", "pricing", "waitlist"] as const).forEach((id) => {
      const section = document.getElementById(id);
      if (section) io.observe(section);
    });
    return () => io.disconnect();
  }, [enabled]);
}

/* ── text splitting ──────────────────────────────────────────────────────── */

/**
 * Split into words, marking the ones inside a `*…*` span.
 *
 * Splits on the delimiter first and only then on whitespace: checking each word
 * for a leading and trailing `*` would only ever match single-word spans, and
 * would render `*recovered regular*` with the asterisks still in it.
 */
function tokenize(text: string): { word: string; em: boolean; space: boolean }[] {
  const out: { word: string; em: boolean; space: boolean }[] = [];
  // `space` records whether whitespace actually preceded the token in the
  // source. Rejoining every token with a space instead would push punctuation
  // that follows a closing delimiter off on its own — "*fighting for*." became
  // "fighting for ." with a visible gap before the period.
  let pendingSpace = false;
  text.split("*").forEach((run, i) => {
    const em = i % 2 === 1; // odd runs sat between a pair of delimiters
    for (const part of run.split(/(\s+)/)) {
      if (!part) continue;
      if (/^\s/.test(part)) {
        pendingSpace = true;
        continue;
      }
      out.push({ word: part, em, space: pendingSpace && out.length > 0 });
      pendingSpace = false;
    }
  });
  return out;
}

/**
 * Per-character stagger-in, for the hero headline only.
 *
 * The characters are aria-hidden and the real string is on the heading's
 * aria-label — a screen reader would otherwise read the headline one letter
 * at a time.
 */
function SplitChars({
  text,
  className = "",
  reduced,
  delay = 0,
}: {
  text: string;
  className?: string;
  reduced: boolean;
  delay?: number;
}) {
  const plain = text.replace(/\*/g, "");
  const words = tokenize(text);
  if (reduced) {
    return (
      <h1 className={className}>
        {words.map((t, i) => (
          <span key={i}>
            {t.space ? " " : ""}
            {t.em ? <em className="lp-em">{t.word}</em> : t.word}
          </span>
        ))}
      </h1>
    );
  }
  let n = 0;
  return (
    <h1 className={className} aria-label={plain}>
      {words.map((t, wi) => (
        <span className="lp-word" key={wi} aria-hidden>
          {t.space && <span className="lp-char-space"> </span>}
          {Array.from(t.word).map((ch, ci) => (
            <span
              className={`lp-char${t.em ? " lp-em" : ""}`}
              key={ci}
              style={{ animationDelay: `${delay + n++ * 0.02}s` }}
            >
              {ch}
            </span>
          ))}
        </span>
      ))}
    </h1>
  );
}

/**
 * Headline that lights up word by word as it crosses the viewport — the one
 * borrowed move that carries most of the page's character.
 *
 * Words sit at 16% opacity and are driven to full by scroll position between
 * 84% and 38% of the viewport height. Opacity is written straight to the spans
 * rather than kept in state: this runs on every frame of a scroll and a React
 * re-render per frame would be wasted work.
 */
function ScrubWords({
  text,
  as: Tag = "h2",
  className = "",
  reduced,
}: {
  text: string;
  as?: "h2" | "h3" | "p";
  className?: string;
  reduced: boolean;
}) {
  const ref = useRef<HTMLElement>(null);
  const words = useMemo(() => tokenize(text), [text]);

  useRafScroll(() => {
    const el = ref.current;
    if (!el) return;
    const spans = el.querySelectorAll<HTMLElement>(".lp-scrub-word");
    const vh = window.innerHeight;
    const top = el.getBoundingClientRect().top;
    const start = vh * 0.84;
    const end = vh * 0.38;
    const p = Math.min(1, Math.max(0, (start - top) / (start - end)));
    const n = spans.length;
    spans.forEach((span, i) => {
      // +3 overlap so neighbouring words brighten together instead of
      // resolving one at a time like a ticker.
      const t = Math.min(1, Math.max(0, p * (n + 3) - i));
      span.style.opacity = String(0.16 + 0.84 * t);
    });
  }, !reduced);

  return (
    <Tag ref={ref as never} className={`lp-scrub ${className}`}>
      {words.map((w, i) => (
        <span className="lp-scrub-word" key={i} style={{ opacity: reduced ? 1 : 0.16 }}>
          {w.space ? " " : ""}
          {w.em ? <em className="lp-em">{w.word}</em> : w.word}
        </span>
      ))}
    </Tag>
  );
}

/** Vertically cycling word stack. */
function WordCycle({ words, interval = 1500 }: { words: string[]; interval?: number }) {
  const [i, setI] = useState(0);
  const reduced = useReducedMotion();
  useEffect(() => {
    if (reduced) return;
    const t = setInterval(() => setI((v) => (v + 1) % words.length), interval);
    return () => clearInterval(t);
  }, [words.length, interval, reduced]);
  return (
    <span className="lp-wc" aria-live="polite">
      {words.map((w, idx) => (
        <span key={w} className={`lp-wc-item${idx === i ? " is-on" : ""}`}>
          {w}
        </span>
      ))}
    </span>
  );
}

/**
 * Section header: a full-bleed rule, the kicker on the left rail, the section
 * index on the right. The rule and the index are what stop a section from
 * reading as a lone centred column floating in margin.
 */
function SectionHead({
  kicker,
  index,
  total,
  dark = false,
  children,
}: {
  kicker: string;
  index: number;
  total: number;
  dark?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div className={`lp-head${dark ? " is-dark" : ""}`}>
      <div className="lp-head-bar" data-reveal>
        <span className="lp-kicker">{kicker}</span>
        <span className="lp-head-index">
          {String(index).padStart(2, "0")} <span className="lp-head-slash">/</span>{" "}
          {String(total).padStart(2, "0")}
        </span>
      </div>
      {children}
    </div>
  );
}

/* ── page ────────────────────────────────────────────────────────────────── */

const NAV_LINKS: [string, string][] = [
  ["flow", "How it works"],
  ["demo", "Live demo"],
  ["features", "Features"],
  ["team", "Team"],
  ["pricing", "Pricing"],
];

export default function Landing() {
  const reduced = useReducedMotion();
  useRevealOnScroll(reduced);
  useLandingMetrics();
  // The shared hook has no enabled flag, so gate its output rather than the
  // call — a hook can't be called conditionally. Under reduced motion the
  // counters jump straight to their final value.
  const progress = useMountProgress(1600);
  const p = reduced ? 1 : progress;

  return (
    <div className="lp-root">
      <style>{LP_CSS}</style>
      <Nav />
      <main>
        <Hero p={p} reduced={reduced} />
        <Marquee />
        <StatBand />
        <Flow reduced={reduced} />
        <Stance reduced={reduced} />
        <RiskDemo reduced={reduced} />
        <Features reduced={reduced} />
        <HowItWorks reduced={reduced} />
        <Guardrails reduced={reduced} />
        <Team reduced={reduced} />
        <Pricing reduced={reduced} />
        <Waitlist reduced={reduced} />
      </main>
      <Footer />
    </div>
  );
}

/* ── Nav — transparent over the dark hero, cream once past it ── */
function Nav() {
  const [solid, setSolid] = useState(false);
  const active = useActiveSection(NAV_LINKS.map(([id]) => id));

  useRafScroll(() => setSolid(window.scrollY > window.innerHeight * 0.7));

  return (
    <header className={`lp-nav${solid ? " is-solid" : ""}`}>
      <div className="lp-nav-inner">
        <a href="#top" className="lp-brand" aria-label="Churnary, top of page">
          {/* Tile only once the nav turns cream — over the dark hero the mark's
              own espresso tile would disappear into the background. */}
          <ChurnaryMark size={30} tile={solid} className="lp-brand-mark" />
          <span className="font-display lp-brand-word">Churnary</span>
        </a>
        <nav className="lp-nav-links" aria-label="Sections">
          {NAV_LINKS.map(([id, label]) => (
            <a
              key={id}
              href={`#${id}`}
              className={active === id ? "is-active" : ""}
              aria-current={active === id ? "true" : undefined}
            >
              {label}
            </a>
          ))}
        </nav>
        <div className="lp-nav-cta">
          <Link
            to="/login"
            className="lp-nav-signin"
            onClick={() =>
              void trackLandingEvent({
                event: "landing_cta_clicked",
                cta: "sign_in",
                location: "navbar",
                destination: "login",
              })
            }
          >
            Sign in
          </Link>
          <a
            href="#waitlist"
            className="lp-btn lp-btn-primary lp-btn-sm"
            onClick={() =>
              void trackLandingEvent({
                event: "landing_cta_clicked",
                cta: "join_waitlist",
                location: "navbar",
                destination: "waitlist",
              })
            }
          >
            Join the waitlist
          </a>
        </div>
      </div>
    </header>
  );
}

/* ── Hero — dark, full-bleed, parallax curtain + cursor spotlight ── */
function Hero({ p, reduced }: { p: number; reduced: boolean }) {
  const sectionRef = useRef<HTMLElement>(null);
  const bgRef = useRef<HTMLDivElement>(null);

  // Curtain: the background drifts down at a fraction of scroll speed, so the
  // copy and the next section slide up over a near-static image.
  useRafScroll(() => {
    const el = bgRef.current;
    const sec = sectionRef.current;
    if (!el || !sec) return;
    const top = sec.getBoundingClientRect().top;
    if (top > 0) {
      el.style.transform = "translate3d(0,0,0)";
      return;
    }
    el.style.transform = `translate3d(0, ${Math.min(-top * 0.35, window.innerHeight * 0.5)}px, 0)`;
  }, !reduced);

  const onMove = (e: React.MouseEvent) => {
    if (reduced) return;
    const el = sectionRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${e.clientX - r.left}px`);
    el.style.setProperty("--my", `${e.clientY - r.top}px`);
  };

  const money = (n: number) => "$" + Math.round(n).toLocaleString();

  return (
    <section id="top" ref={sectionRef} onMouseMove={onMove} className="lp-hero">
      <div ref={bgRef} className="lp-hero-bg" aria-hidden>
        <DotField />
      </div>
      <div className="lp-hero-veil" aria-hidden />

      <div className="lp-hero-inner">
        <div className="lp-hero-copy">
          <span className="lp-kicker-pill">
            <span className="lp-pulse-dot" aria-hidden />
            AI retention for local business
          </span>

          <p className="lp-hero-eyebrow">
            For{" "}
            <WordCycle
              words={["cafés", "salons", "gyms", "med spas", "barbershops", "studios"]}
              interval={1500}
            />
          </p>

          <SplitChars
            className="font-display lp-h1"
            text="Win regulars back *before* the revenue walks out."
            reduced={reduced}
            delay={0.1}
          />

          <p className="lp-hero-lede">
            Churnary watches your Square, Stripe or CSV data, flags the regulars quietly slipping
            away — with the reason in plain English — and drafts the win-back email. You just tap
            approve.
          </p>

          <div className="lp-hero-actions">
            <a
              href="#waitlist"
              className="lp-btn lp-btn-primary lp-btn-lg"
              onClick={() =>
                void trackLandingEvent({
                  event: "landing_cta_clicked",
                  cta: "join_waitlist",
                  location: "hero",
                  destination: "waitlist",
                })
              }
            >
              Join the waitlist <span aria-hidden>→</span>
            </a>
            <a
              href="#demo"
              className="lp-btn lp-btn-ghost lp-btn-lg"
              onClick={() =>
                void trackLandingEvent({
                  event: "landing_cta_clicked",
                  cta: "live_demo",
                  location: "hero",
                  destination: "demo",
                })
              }
            >
              Try the live demo
            </a>
          </div>

          <dl className="lp-hero-stats" aria-label="What Churnary does">
            <HeroStat value={money(5806 * p)} label="revenue at risk, caught at one café" />
            <HeroStat value={`${Math.round(120 * p)} sec`} label="from CSV upload to first insight" />
            <HeroStat value={`${(0.9 * p).toFixed(1)}¢`} label="AI cost per win-back email" />
          </dl>
        </div>

        <TiltPreview reduced={reduced} />
      </div>

      <a href="#flow" className="lp-scroll-cue" aria-label="Scroll to how it works">
        <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
          <path d="M4 7 L9 12 L14 7" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" />
        </svg>
      </a>
    </section>
  );
}

function HeroStat({ value, label }: { value: string; label: string }) {
  return (
    <div className="lp-hero-stat">
      <dt className="font-display lp-hero-stat-num">{value}</dt>
      <dd className="lp-hero-stat-label">{label}</dd>
    </div>
  );
}

/**
 * Background dot field — one dot per "customer", a handful glowing terracotta.
 * Deterministic positions: a random layout would reshuffle on every re-render.
 */
function DotField() {
  const dots = useMemo(() => {
    const out: { x: number; y: number; hot: boolean; d: number }[] = [];
    const cols = 30;
    const rows = 16;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        // Deterministic pseudo-jitter so the grid reads organic, not graph paper.
        const j = Math.sin(r * 12.9898 + c * 78.233) * 43758.5453;
        const frac = j - Math.floor(j);
        out.push({
          x: (c / (cols - 1)) * 100,
          y: (r / (rows - 1)) * 100,
          hot: frac > 0.955,
          d: frac * 4,
        });
      }
    }
    return out;
  }, []);

  return (
    <svg className="lp-dots" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
      {dots.map((d, i) => (
        <circle
          key={i}
          cx={d.x}
          cy={d.y}
          r={d.hot ? 0.4 : 0.18}
          className={d.hot ? "lp-dot is-hot" : "lp-dot"}
          style={d.hot ? { animationDelay: `${d.d}s` } : undefined}
        />
      ))}
    </svg>
  );
}

/* ── 3D-tilt dashboard preview ── */
function TiltPreview({ reduced }: { reduced: boolean }) {
  const ref = useRef<HTMLDivElement>(null);

  const onMove = (e: React.MouseEvent) => {
    const el = ref.current;
    if (!el || reduced) return;
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5;
    const y = (e.clientY - r.top) / r.height - 0.5;
    el.style.transform = `perspective(1100px) rotateY(${x * 8}deg) rotateX(${-y * 8}deg)`;
  };
  const onLeave = () => {
    if (ref.current) ref.current.style.transform = "perspective(1100px) rotateY(0deg) rotateX(0deg)";
  };

  return (
    <div className="lp-preview-wrap">
      <div
        ref={ref}
        onMouseMove={onMove}
        onMouseLeave={onLeave}
        className={`lp-preview${reduced ? "" : " is-floating"}`}
      >
        <div className="lp-preview-chrome" aria-hidden>
          <span className="lp-preview-tab is-on">Today</span>
          <span className="lp-preview-tab">Customers</span>
          <span className="lp-preview-tab">Campaigns</span>
        </div>

        <div className="lp-preview-action">
          <span className="lp-preview-avatar" aria-hidden>
            <span className="lp-preview-ping" />☕
          </span>
          <div className="lp-preview-action-text">
            <p className="lp-preview-eyebrow">Your #1 action today</p>
            <p className="font-display lp-preview-name">Reach out to Isabella Torres</p>
            <p className="lp-preview-meta">45 days out · 6.9× her usual gap · Loves Avocado Toast</p>
          </div>
          <span className="lp-preview-send">Send →</span>
        </div>

        <div className="lp-preview-kpis">
          {[
            ["At Risk", "$5,806", "var(--accent-dark)"],
            ["Attention", "6", "var(--ink)"],
            ["Days Away", "8", "var(--ink)"],
            ["Recovered", "$640", "var(--sage-text)"],
          ].map(([l, v, c]) => (
            <div key={l} className="lp-preview-kpi">
              <p className="lp-preview-kpi-l">{l}</p>
              <p className="font-display lp-preview-kpi-v" style={{ color: c }}>
                {v}
              </p>
            </div>
          ))}
        </div>

        <div className="lp-preview-rows">
          {[
            ["Isabella Torres", "21 days · 6.9× gap", "Critical 91", "#A23B1E", "#F7E3DC"],
            ["Priya Ferreira", "14 days · 2.8× gap", "At Risk 62", "#C0632F", "#F7E6DA"],
            ["Marcus Silva", "9 days · 1.8× gap", "Watch 48", "#A9781F", "#F4EAD1"],
            ["Ana Beatriz", "3 days · on rhythm", "Healthy 12", "#4F7A40", "#E6EFDF"],
          ].map(([name, why, badge, color, bg]) => (
            <div key={name} className="lp-preview-row">
              <span className="lp-preview-row-name">{name}</span>
              <span className="lp-preview-row-why">{why}</span>
              <span className="lp-preview-row-badge" style={{ color, background: bg }}>
                {badge}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── Marquee of verticals ── */
function Marquee() {
  const words = [
    "Cafés", "Coffee shops", "Salons", "Barbershops", "Fitness studios",
    "Gyms", "Med spas", "Juice bars", "Bakeries", "Yoga studios",
  ];
  const row = (
    <>
      {words.map((w) => (
        <span key={w} className="lp-marquee-item font-display">
          {w}
          <span className="lp-marquee-dot" aria-hidden>·</span>
        </span>
      ))}
    </>
  );
  return (
    <div className="lp-marquee-band">
      <div className="lp-marquee" aria-hidden>
        {row}
        {row}
      </div>
      <span className="lp-sr-only">Built for cafés, salons, barbershops, gyms, med spas and studios.</span>
    </div>
  );
}

/* ── Stat band — full-width, hairline-divided figures ── */
const STATS: [string, string, string][] = [
  ["~$970", "what one saved regular is worth per year", "So three saves cover any plan."],
  ["21 days", "typical gap before a café regular is gone for good", "Churnary flags them at day 8."],
  ["2 min", "from CSV upload to your first risk list", "No onboarding call, no IT."],
  ["0", "emails sent without your approval", "Approve-to-send is the default."],
];

function StatBand() {
  return (
    <section className="lp-statband">
      <dl className="lp-statband-grid">
        {STATS.map(([n, label, note], i) => (
          <div className="lp-statcell" key={label} data-reveal style={{ transitionDelay: `${i * 70}ms` }}>
            <dt className="font-display lp-statcell-n">{n}</dt>
            <dd className="lp-statcell-body">
              <span className="lp-statcell-label">{label}</span>
              <span className="lp-statcell-note">{note}</span>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/* ── Flow diagram — signals in, a recovered regular out ── */
const FLOW_IN = ["Square", "Stripe", "CSV upload"];
const FLOW_OUT = ["Risk score + plain-English reason", "Drafted win-back email", "Recovered revenue, attributed"];

function Flow({ reduced }: { reduced: boolean }) {
  const y = (i: number, n: number) => 170 + (i - (n - 1) / 2) * 62;
  const arrow = "M -6 -5 L 5 0 L -6 5 Z";

  return (
    <section id="flow" className="lp-section lp-alt">
      <SectionHead kicker="How it works" index={1} total={8}>
        <div className="lp-head-split">
          <ScrubWords
            className="font-display lp-h2"
            text="Your data goes in. A *recovered regular* comes out."
            reduced={reduced}
          />
          <div className="lp-head-aside" data-reveal>
            <p>
              No dashboards to learn and no model to take on faith. Every score shows its reasons,
              and nothing sends without you.
            </p>
            <p className="lp-head-aside-note">
              Adding a new data source never changes anything downstream — that's an architectural
              guarantee, not a roadmap promise.
            </p>
          </div>
        </div>
      </SectionHead>

      <figure className="lp-flow" data-reveal>
        {/* viewBox height is cropped to the drawing (chips end at y≈251), not a
            round 340 — the slack was rendering as an empty band under the figure. */}
        <svg viewBox="0 0 900 264" className="lp-flow-svg" role="img" aria-label="Square, Stripe and CSV uploads feed into Churnary's scoring engine, which produces a risk score with a plain-English reason, a drafted win-back email, and attributed recovered revenue.">
          <text x="0" y="24" className="lp-flow-head">WHAT YOU ALREADY HAVE</text>
          <text x="900" y="24" textAnchor="end" className="lp-flow-head">WHAT CHURNARY MAKES</text>

          {FLOW_IN.map((_, i) => (
            <line key={i} x1={222} y1={y(i, FLOW_IN.length)} x2={318} y2={170}
              className="lp-flow-wire" pathLength={1} style={{ animationDelay: `${0.1 + i * 0.08}s` }} />
          ))}
          <circle cx={318} cy={170} r={4} className="lp-flow-hub" />
          <line x1={318} y1={170} x2={366} y2={170} className="lp-flow-wire" pathLength={1} style={{ animationDelay: "0.34s" }} />
          <path d={arrow} className="lp-flow-arrow" transform="translate(370 170)" />

          <rect x={374} y={104} width={152} height={132} rx={14} className="lp-flow-core" />
          <text x={450} y={152} className="font-display lp-flow-core-mark">Churnary</text>
          <text x={450} y={176} className="lp-flow-core-line">TRANSPARENT</text>
          <text x={450} y={192} className="lp-flow-core-line">SCORING ENGINE</text>
          <text x={450} y={214} className="lp-flow-core-sub">+ CLAUDE COPY</text>

          <line x1={534} y1={170} x2={582} y2={170} className="lp-flow-wire" pathLength={1} style={{ animationDelay: "0.42s" }} />
          <circle cx={582} cy={170} r={4} className="lp-flow-hub" />
          {FLOW_OUT.map((_, i) => (
            <line key={i} x1={582} y1={170} x2={654} y2={y(i, FLOW_OUT.length)}
              className="lp-flow-wire" pathLength={1} style={{ animationDelay: `${0.5 + i * 0.08}s` }} />
          ))}
          {FLOW_OUT.map((_, i) => (
            <path key={i} d={arrow} className="lp-flow-arrow" transform={`translate(654 ${y(i, FLOW_OUT.length)})`} />
          ))}

          {FLOW_IN.map((label, i) => (
            <g key={label}>
              <rect x={0} y={y(i, FLOW_IN.length) - 19} width={222} height={38} rx={8} className="lp-flow-chip" />
              <text x={18} y={y(i, FLOW_IN.length) + 5} className="lp-flow-chip-label">{label}</text>
            </g>
          ))}
          {FLOW_OUT.map((label, i) => (
            <g key={label}>
              <rect x={656} y={y(i, FLOW_OUT.length) - 19} width={244} height={38} rx={8} className="lp-flow-chip is-out" />
              <text x={674} y={y(i, FLOW_OUT.length) + 5} className="lp-flow-chip-label is-out">{label}</text>
            </g>
          ))}
        </svg>
      </figure>
    </section>
  );
}

/* ── Stance — the division of labour, as a ruled ledger ── */
const STANCE: [string, string, string][] = [
  [
    "Churnary decides",
    "Who is drifting, and why",
    "It scores every customer nightly against their own visit rhythm, ranks the ones worth a message, and writes a draft that mentions what they actually order.",
  ],
  [
    "You decide",
    "Whether a word of it goes out",
    "Nothing sends on its own. You read the draft, edit it or bin it, and press approve. Autopilot exists, but you have to go and turn it on.",
  ],
];

function Stance({ reduced }: { reduced: boolean }) {
  return (
    <section className="lp-section">
      <SectionHead kicker="Where the line sits" index={2} total={8}>
        <ScrubWords
          className="font-display lp-h2 is-wide"
          text="Churnary proposes. *You* approve."
          reduced={reduced}
        />
      </SectionHead>
      <div className="lp-stance">
        {STANCE.map(([role, title, body], i) => (
          <div className={`lp-stance-col${i === 1 ? " is-you" : ""}`} key={role} data-reveal style={{ transitionDelay: `${i * 90}ms` }}>
            <span className="lp-stance-role">{role}</span>
            <h3 className="font-display lp-stance-h">{title}</h3>
            <p className="lp-stance-body">{body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ── Interactive risk demo — mirrors the real scoring heuristic ── */
const DEMO_VERTICALS = [
  { id: "cafe", label: "Café", interval: 4, unit: "days" },
  { id: "fitness", label: "Gym", interval: 5, unit: "days" },
  { id: "salon", label: "Salon", interval: 35, unit: "days" },
] as const;

type DemoVertical = (typeof DEMO_VERTICALS)[number];

function RiskDemo({ reduced }: { reduced: boolean }) {
  const [vertical, setVertical] = useState<DemoVertical>(DEMO_VERTICALS[0]);
  const [days, setDays] = useState(12);

  const ratio = days / vertical.interval;
  const score = Math.min(97, Math.max(3, Math.round(ratio * 27)));
  const riskBand =
    ratio >= 2.5 ? "needs_attention" : ratio >= 1.5 ? "watch" : "healthy";
  const band =
    ratio >= 2.5
      ? { label: "Needs Attention", color: "#A23B1E", bg: "#F7E3DC", action: "Churnary drafts a win-back email — you tap approve." }
      : ratio >= 1.5
        ? { label: "Keep an Eye On", color: "#A9781F", bg: "#F4EAD1", action: "Churnary watches daily and flags them the moment risk rises." }
        : { label: "Healthy Regular", color: "#4F7A40", bg: "#E6EFDF", action: "All good — no outreach needed." };

  const maxDays = vertical.interval * 12;

  return (
    <section id="demo" className="lp-section lp-alt">
      <SectionHead kicker="Try it yourself" index={3} total={8} />
      <div className="lp-demo">
        <div className="lp-demo-copy">
          <ScrubWords
            className="font-display lp-h2"
            text="The whole product, in *one slider*."
            reduced={reduced}
          />
          <p className="lp-demo-lede" data-reveal>
            Drag it. Churnary scores churn risk from each customer's own rhythm — and says why in a
            sentence you could read aloud to them.
          </p>
          <ul className="lp-demo-points" data-reveal>
            <li>
              <span className="lp-demo-point-k">Per vertical</span>
              A med-spa client returning in five months is normal. A gym member gone three weeks
              is not. The thresholds differ by trade.
            </li>
            <li>
              <span className="lp-demo-point-k">No black box</span>
              This is a transparent weighted heuristic, not a model you have to trust. The same
              maths runs in the product.
            </li>
            <li>
              <span className="lp-demo-point-k">Reasons first</span>
              The sentence under the dial is the actual output shape — reasons are a feature, not
              a debug view.
            </li>
          </ul>
        </div>

        <div className="lp-demo-card" data-reveal>
          <div className="lp-demo-picker">
            <span className="lp-demo-picker-label">A regular at your…</span>
            {DEMO_VERTICALS.map((v) => (
              <button
                key={v.id}
                onClick={() => {
                  setVertical(v);
                  setDays(Math.min(3 * v.interval, v.interval * 12));
                  void trackLandingEvent({
                    event: "landing_demo_interacted",
                    control: "vertical",
                    vertical: v.id,
                    risk_band: "needs_attention",
                  });
                }}
                className={`lp-chip${vertical.id === v.id ? " is-on" : ""}`}
              >
                {v.label}
              </button>
            ))}
          </div>
          <p className="lp-demo-picker-note">
            usually visits every {vertical.interval} {vertical.unit}
          </p>

          <div className="lp-demo-slider">
            <div className="lp-demo-slider-head">
              <label htmlFor="lp-days" className="lp-demo-slider-label">
                Days since their last visit
              </label>
              <span className="font-display lp-demo-days" style={{ color: band.color }}>{days}</span>
            </div>
            <input
              id="lp-days"
              type="range"
              min={1}
              max={maxDays}
              value={Math.min(days, maxDays)}
              onChange={(e) => setDays(Number(e.target.value))}
              onPointerUp={() =>
                void trackLandingEvent({
                  event: "landing_demo_interacted",
                  control: "days",
                  vertical: vertical.id,
                  risk_band: riskBand,
                })
              }
              onKeyUp={() =>
                void trackLandingEvent({
                  event: "landing_demo_interacted",
                  control: "days",
                  vertical: vertical.id,
                  risk_band: riskBand,
                })
              }
              className="lp-slider"
              style={{ accentColor: band.color, color: band.color }}
            />
            <div className="lp-demo-slider-ends">
              <span>just visited</span>
              <span>long gone</span>
            </div>
          </div>

          <div className="lp-demo-readout">
            <ScoreDial score={score} color={band.color} />
            <div className="lp-demo-readout-text">
              <span className="lp-demo-band" style={{ background: band.bg, color: band.color }}>
                <span className="lp-demo-band-dot" style={{ background: band.color }} />
                {band.label} · risk {score}
              </span>
              <p className="lp-demo-quote">
                “Usually visits every {vertical.interval} {vertical.unit} — it's been <b>{days} days</b>
                {ratio >= 1.2 && <> ({ratio.toFixed(1)}× their rhythm)</>}.”
              </p>
              <p className="lp-demo-action">{band.action}</p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function ScoreDial({ score, color }: { score: number; color: string }) {
  const C = 2 * Math.PI * 42;
  return (
    <div className="lp-dial">
      <svg viewBox="0 0 100 100" width={116} height={116}>
        <circle cx="50" cy="50" r="42" fill="none" stroke="var(--border)" strokeWidth="9" />
        <circle
          cx="50" cy="50" r="42" fill="none" stroke={color} strokeWidth="9" strokeLinecap="round"
          strokeDasharray={`${(score / 100) * C} ${C}`}
          transform="rotate(-90 50 50)"
          className="lp-dial-arc"
        />
      </svg>
      <div className="lp-dial-center">
        <span className="font-display lp-dial-num" style={{ color }}>{score}</span>
        <span className="lp-dial-cap">risk</span>
      </div>
    </div>
  );
}

/* ── Features — hairline ledger, no floating cards ── */
function Features({ reduced }: { reduced: boolean }) {
  const items = [
    { title: "Transparent scoring", body: "Every risk score shows its reasons — visit gap, spend drop, favourite item. Trust it today, not “someday, with more AI.”" },
    { title: "AI drafts, you approve", body: "Claude writes the win-back copy; Suggest / Approve / Autopilot modes keep a human in control. Approve-to-send is the default." },
    { title: "Compliant by design", body: "CAN-SPAM unsubscribe on every email, TCPA quiet hours for SMS, and we never touch medical data. Guardrails built in, not bolted on." },
    { title: "Works with your tools", body: "Square and Stripe connect live; CSV upload covers anything else. Adding a source never means redoing your setup." },
    { title: "Nightly re-scoring", body: "Every customer is re-scored automatically as new visits land. The dashboard is always this-morning fresh." },
    { title: "Attribution you can bank", body: "Recovered customers tie back to the exact message that brought them in: “3 customers recovered, ~$640 saved.”" },
  ];
  return (
    <section id="features" className="lp-section">
      <SectionHead kicker="Why owners trust it" index={4} total={8}>
        <div className="lp-head-split">
          <ScrubWords
            className="font-display lp-h2"
            text="Automation you can hand the *keys* to."
            reduced={reduced}
          />
          <div className="lp-head-aside" data-reveal>
            <p>
              Churnary is aimed at people who run a counter, not a marketing team. Everything below
              is either already shipped or a hard guarantee in how it's built.
            </p>
          </div>
        </div>
      </SectionHead>
      <ol className="lp-ledger lp-ledger-3">
        {items.map((f, i) => (
          <li className="lp-ledger-cell" key={f.title} data-reveal style={{ transitionDelay: `${(i % 3) * 70}ms` }}>
            <span className="lp-ledger-n">{String(i + 1).padStart(2, "0")}</span>
            <h3 className="font-display lp-ledger-h">{f.title}</h3>
            <p className="lp-ledger-body">{f.body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

/* ── How it works ── */
function HowItWorks({ reduced }: { reduced: boolean }) {
  const steps = [
    { title: "Connect in 2 minutes", body: "Link Square or Stripe, or upload a customer CSV. If you can attach a file to an email, you can set up Churnary.", foot: "Square · Stripe · CSV" },
    { title: "See who's slipping — and why", body: "Every customer gets a transparent risk score built from their own visit rhythm, with the reason in plain English.", foot: "Re-scored nightly" },
    { title: "Approve the win-back", body: "Churnary drafts a personal email mentioning their favourite order. You tap approve, it sends, and recovered visits are tracked back to it.", foot: "Email today · SMS on Growth" },
  ];
  return (
    <section id="how" className="lp-section lp-alt">
      <SectionHead kicker="Owner-simple, on purpose" index={5} total={8}>
        <ScrubWords
          className="font-display lp-h2 is-wide"
          text="Built for people who run a counter, *not a CRM*."
          reduced={reduced}
        />
      </SectionHead>
      <ol className="lp-steps">
        {steps.map((s, i) => (
          <li className="lp-step" key={s.title} data-reveal style={{ transitionDelay: `${i * 80}ms` }}>
            <span className="lp-step-n">{String(i + 1).padStart(2, "0")}</span>
            <h3 className="font-display lp-step-h">{s.title}</h3>
            <p className="lp-step-body">{s.body}</p>
            <span className="lp-step-foot">{s.foot}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

/* ── Guardrails — the things Churnary refuses to do ── */
const GUARDRAILS: [string, string][] = [
  ["CAN-SPAM", "An unsubscribe link in every single email. Not a setting you can switch off."],
  ["TCPA", "No SMS before 9am or after 8pm in the customer's own time zone. STOP is honoured instantly."],
  ["HIPAA", "We never ingest medical or treatment data — only name, contact, visit times and spend."],
  ["Your data", "A per-business deletion endpoint, and OAuth tokens encrypted at rest. Leaving is one request."],
];

function Guardrails({ reduced }: { reduced: boolean }) {
  return (
    <section className="lp-section lp-dark-section">
      <SectionHead kicker="Guardrails" index={6} total={8} dark>
        <div className="lp-head-split">
          <ScrubWords
            className="font-display lp-h2 is-dark"
            text="The parts we *won't* let you switch off."
            reduced={reduced}
          />
          <div className="lp-head-aside is-dark" data-reveal>
            <p>
              Outreach automation goes wrong in expensive, legally interesting ways. These are wired
              in below the settings screen, so no configuration can turn them off.
            </p>
          </div>
        </div>
      </SectionHead>
      <dl className="lp-ledger lp-ledger-4 is-dark">
        {GUARDRAILS.map(([k, v], i) => (
          <div className="lp-ledger-cell" key={k} data-reveal style={{ transitionDelay: `${i * 70}ms` }}>
            <dt className="font-display lp-ledger-h">{k}</dt>
            <dd className="lp-ledger-body">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/* ── Team ── */
const TEAM_MEMBERS = [
  {
    name: "Soham Dogra",
    education: "CS + Linguistics · San José State",
    bio: "An AI product builder working across strategy, engineering and growth, with experience developing AI infrastructure at Inference.ai.",
    email: "soham@churnary.ai",
    linkedin: "https://www.linkedin.com/in/soham-dogra-b110ab2ab/",
    image: sohamPhoto,
    imagePosition: "center 28%",
  },
  {
    name: "Riyan Anosh",
    education: "Computer Engineering · UC Merced",
    bio: "A hands-on builder with a soft spot for homelabs, hardware and turning ambitious AI ideas into working prototypes.",
    email: "riyan@churnary.ai",
    linkedin: "https://www.linkedin.com/in/riyan-anosh-0aba9434b/",
    image: null,
    imagePosition: "center",
  },
  {
    name: "Pranjal Mishra",
    education: "Aerospace + Mechanical · RPI",
    bio: "An engineer-in-training who pairs flight manufacturing experience with a background in software engineering and applied AI.",
    email: "pranjal@churnary.ai",
    linkedin: "https://www.linkedin.com/in/pranjal-mishra-b622252a6/",
    image: pranjalPhoto,
    imagePosition: "center 32%",
  },
  {
    name: "Aditya Kolekar",
    education: "Artificial Intelligence · UC San Diego",
    bio: "An AI builder and three-time hackathon winner focused on making complex technology feel clear, practical and useful.",
    email: "aditya@churnary.ai",
    linkedin: "https://www.linkedin.com/in/aditkolekar/",
    image: adityaPhoto,
    imagePosition: "center 28%",
  },
] as const;

function Team({ reduced }: { reduced: boolean }) {
  return (
    <section id="team" className="lp-section lp-alt">
      <SectionHead kicker="About the team" index={7} total={8}>
        <div className="lp-head-split">
          <ScrubWords
            className="font-display lp-h2"
            text="Four Fremont friends. One *shared obsession*: build the useful thing."
            reduced={reduced}
          />
          <div className="lp-head-aside" data-reveal>
            <p>
              We met at American High School in Fremont, California, and kept building together.
              Churnary brings our backgrounds in AI, product, computer engineering and aerospace
              systems to one goal: help local businesses keep the customers they worked hard to earn.
            </p>
          </div>
        </div>
      </SectionHead>

      <div className="lp-team-grid">
        {TEAM_MEMBERS.map((member, i) => (
          <article
            className="lp-team-card"
            key={member.name}
            data-reveal
            style={{ transitionDelay: `${i * 70}ms` }}
          >
            <div className="lp-team-photo">
              {member.image ? (
                <img
                  src={member.image}
                  alt={member.name}
                  loading="lazy"
                  decoding="async"
                  style={{ objectPosition: member.imagePosition }}
                />
              ) : (
                <div className="lp-team-placeholder" role="img" aria-label={`${member.name} initials`}>
                  <span>RA</span>
                </div>
              )}
            </div>
            <div className="lp-team-meta">
              <span className="lp-team-role">Co-founder</span>
              <a
                href={member.linkedin}
                target="_blank"
                rel="noreferrer noopener"
                aria-label={`View ${member.name} on LinkedIn`}
              >
                LinkedIn <span aria-hidden>↗</span>
              </a>
            </div>
            <h3 className="font-display lp-team-name">{member.name}</h3>
            <p className="lp-team-education">{member.education}</p>
            <p className="lp-team-bio">{member.bio}</p>
            <a
              className="lp-team-email"
              href={`mailto:${member.email}`}
              aria-label={`Email ${member.name} at ${member.email}`}
            >
              {member.email} <span aria-hidden>↗</span>
            </a>
          </article>
        ))}
      </div>
    </section>
  );
}

/* ── Pricing ── */
function Pricing({ reduced }: { reduced: boolean }) {
  const tiers = [
    { name: "Starter", plan: "starter", price: 199, hot: false, lines: ["1 integration", "1,000 customers", "Email win-backs", "Transparent risk scores"] },
    { name: "Growth", plan: "growth", price: 299, hot: true, lines: ["All integrations", "2,500 customers", "Email + SMS", "Automation rules", "Recovery attribution"] },
    { name: "Pro", plan: "pro", price: 499, hot: false, lines: ["Unlimited customers", "Multi-location ready", "Everything in Growth", "Priority support"] },
  ] as const;
  return (
    <section id="pricing" className="lp-section">
      <SectionHead kicker="Pricing" index={8} total={8}>
        <div className="lp-head-split">
          <ScrubWords
            className="font-display lp-h2"
            text="Pays for itself on the *first save*."
            reduced={reduced}
          />
          <div className="lp-head-aside" data-reveal>
            <p>
              A saved regular is worth roughly $970 a year. Save three and any plan has paid for
              itself. 14-day trial on every tier, annual billing is two months free.
            </p>
          </div>
        </div>
      </SectionHead>
      <div className="lp-tiers">
        {tiers.map((t, i) => (
          <div
            key={t.name}
            className={`lp-tier${t.hot ? " is-hot" : ""}`}
            data-reveal
            style={{ transitionDelay: `${i * 80}ms` }}
          >
            <div className="lp-tier-top">
              <h3 className="font-display lp-tier-name">{t.name}</h3>
              {t.hot && <span className="lp-tier-flag">Most popular</span>}
            </div>
            <p className="lp-tier-price">
              <span className="font-display lp-tier-amount">${t.price}</span>
              <span className="lp-tier-per">/month</span>
            </p>
            <ul className="lp-tier-lines">
              {t.lines.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
            <a
              href="#waitlist"
              className={`lp-btn lp-tier-cta${t.hot ? " lp-btn-primary" : ""}`}
              onClick={() =>
                void trackLandingEvent({
                  event: "landing_cta_clicked",
                  cta: "join_waitlist",
                  location: "pricing",
                  destination: "waitlist",
                  plan: t.plan,
                })
              }
            >
              Join the waitlist
            </a>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ── Waitlist — the dark band that ends the page ── */
function Waitlist({ reduced }: { reduced: boolean }) {
  return (
    <section id="waitlist" className="lp-waitlist">
      <div className="lp-waitlist-grid">
        <div className="lp-waitlist-copy">
          <span className="lp-kicker is-dark" data-reveal>Early access</span>
          <ScrubWords
            className="font-display lp-h2 is-dark"
            text="Your regulars are worth *fighting for*."
            reduced={reduced}
          />
          <p className="lp-waitlist-sub" data-reveal>
            We're onboarding local businesses a handful at a time so each one gets set up properly.
            Tell us where to reach you and we'll open a seat.
          </p>
          <ul className="lp-waitlist-points" data-reveal>
            <li>We'll import your data with you on the first call.</li>
            <li>No card until you've seen your own risk list.</li>
            <li>One email when a seat opens. Nothing else, ever.</li>
          </ul>
        </div>
        <div className="lp-waitlist-card" data-reveal>
          <WaitlistForm />
        </div>
      </div>
      <p className="lp-waitlist-alt">
        Already have an account?{" "}
        <Link
          to="/login"
          onClick={() =>
            void trackLandingEvent({
              event: "landing_cta_clicked",
              cta: "sign_in",
              location: "waitlist",
              destination: "login",
            })
          }
        >
          Sign in
        </Link>
      </p>
    </section>
  );
}

/* ── Footer ── */
function Footer() {
  return (
    <footer className="lp-footer">
      <div className="lp-footer-inner">
        <div className="lp-brand">
          <ChurnaryMark size={24} className="lp-brand-mark" />
          <span className="font-display lp-brand-word is-sm">Churnary</span>
          <span className="lp-footer-tag">— AI retention for local business</span>
        </div>
        <div className="lp-footer-links">
          <a href="#flow">How it works</a>
          <a href="#demo">Live demo</a>
          <a href="#team">Team</a>
          <a href="#pricing">Pricing</a>
          <Link to="/privacy">Privacy</Link>
          <button type="button" onClick={openPrivacyChoices}>
            Privacy choices
          </button>
          <a
            href="#waitlist"
            onClick={() =>
              void trackLandingEvent({
                event: "landing_cta_clicked",
                cta: "join_waitlist",
                location: "footer",
                destination: "waitlist",
              })
            }
          >
            Waitlist
          </a>
          <Link
            to="/login"
            onClick={() =>
              void trackLandingEvent({
                event: "landing_cta_clicked",
                cta: "sign_in",
                location: "footer",
                destination: "login",
              })
            }
          >
            Sign in
          </Link>
          <span>© 2026 Churnary</span>
        </div>
      </div>
    </footer>
  );
}

/* ── styles ───────────────────────────────────────────────────────────────── */

const LP_CSS = `
  .lp-root {
    --lp-espresso: #241A14;
    --lp-espresso-2: #33241B;
    --lp-h1-size: clamp(38px, 6.4vw, 108px);
    --lp-h2-size: clamp(28px, 3.7vw, 60px);
    /* Grows with the viewport instead of parking content at a fixed max-width,
       so a wide monitor gains content rather than margin. */
    --lp-gutter: clamp(20px, 5.4vw, 108px);
    --lp-rule: var(--border);
    background: var(--bg-page);
    overflow-x: clip;
  }
  .lp-root ::selection { background: var(--accent); color: #fff; }

  .lp-sr-only {
    position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
    overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
  }

  /* ── reveal ── */
  [data-reveal] {
    opacity: 0; transform: translateY(20px);
    transition: opacity .7s ease, transform .7s cubic-bezier(.2,.8,.2,1);
  }
  [data-reveal].is-in { opacity: 1; transform: none; }

  /* ── type ── */
  .lp-h1 {
    font-size: var(--lp-h1-size);
    line-height: 1.0;
    letter-spacing: -0.03em;
    font-weight: 600;
    margin: 16px 0 0;
    color: var(--cream-text);
  }
  .lp-h2 {
    font-size: var(--lp-h2-size);
    line-height: 1.05;
    letter-spacing: -0.028em;
    font-weight: 600;
    margin: 0;
    color: var(--ink);
    max-width: 17ch;
  }
  .lp-h2.is-wide { max-width: 26ch; }
  .lp-h2.is-dark { color: var(--cream-text); }
  .lp-em { font-style: italic; font-weight: 500; color: var(--accent-2); }
  .lp-h2 .lp-em { color: var(--accent); }
  .lp-h2.is-dark .lp-em { color: var(--on-espresso-accent); }

  /* Secondary copy runs on one fluid scale rather than a pile of one-off px
     values. --lp-body is the workhorse (ledger cells, list rows, asides);
     --lp-body-lg is for ledes that carry a section. Both are comfortably above
     the 13-14px the first pass used, which was too small to read at arm's
     length — and because the measure caps are in ch, larger text also fills
     more of each column. */
  .lp-root {
    --lp-body: clamp(14.5px, 1.02vw, 16.5px);
    --lp-body-lg: clamp(15.5px, 1.2vw, 18.5px);
    --lp-label: 11.5px;
  }

  .lp-kicker {
    font-size: var(--lp-label); letter-spacing: .15em; text-transform: uppercase;
    font-weight: 700; color: var(--accent); margin: 0;
  }
  .lp-kicker.is-dark { color: var(--on-espresso-accent); }

  /* char stagger */
  .lp-word { display: inline-block; white-space: nowrap; }
  .lp-char { display: inline-block; animation: lpCharIn .8s cubic-bezier(.2,.8,.2,1) both; }
  .lp-char-space { display: inline-block; width: 0.26em; }
  @keyframes lpCharIn {
    from { opacity: 0; transform: translateY(0.45em); }
    to   { opacity: 1; transform: none; }
  }
  .lp-scrub .lp-scrub-word { display: inline; transition: opacity .1s linear; }

  /* ── buttons — crisp, not pills ── */
  .lp-btn {
    display: inline-flex; align-items: center; justify-content: center; gap: .5rem;
    border-radius: 6px; font-weight: 700; white-space: nowrap; border: 1px solid transparent;
    transition: transform .16s cubic-bezier(.23,1,.32,1), background .16s ease,
                color .16s ease, border-color .16s ease;
  }
  .lp-btn:hover { transform: translateY(-1px); }
  .lp-btn-sm { padding: .55rem 1.05rem; font-size: 13.5px; }
  .lp-btn-lg { padding: .9rem 1.6rem; font-size: 15.5px; }
  .lp-btn-primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  .lp-btn-primary:hover { background: var(--accent-dark); border-color: var(--accent-dark); color: #fff; }
  .lp-btn-ghost { border-color: rgba(244,236,224,.32); color: var(--cream-text); background: transparent; }
  .lp-btn-ghost:hover { background: var(--cream-text); border-color: var(--cream-text); color: var(--lp-espresso); }

  /* ── nav ── */
  .lp-nav {
    position: fixed; inset: 0 0 auto; z-index: 50;
    transition: background .3s ease, border-color .3s ease;
    border-bottom: 1px solid transparent;
  }
  .lp-nav.is-solid {
    background: rgba(251,246,238,.9); backdrop-filter: blur(12px);
    border-bottom-color: var(--lp-rule);
  }
  .lp-nav-inner {
    display: flex; align-items: center; justify-content: space-between; gap: 16px;
    padding: 13px var(--lp-gutter);
  }
  .lp-brand { display: inline-flex; align-items: center; gap: 9px; }
  /* Inline SVG (ChurnaryMark) — it carries its own tile and colours, so there's
     nothing to invert between the transparent and cream nav states. */
  .lp-brand-mark { display: block; flex: none; }
  .lp-brand-word {
    font-size: 20px; font-weight: 600; letter-spacing: -0.025em; color: var(--cream-text);
    transition: color .3s ease;
  }
  .lp-nav.is-solid .lp-brand-word { color: var(--ink); }
  .lp-brand-word.is-sm { font-size: 15.5px; color: var(--ink); }

  .lp-nav-links { display: none; align-items: center; gap: 4px; }
  @media (min-width: 920px) { .lp-nav-links { display: flex; } }
  .lp-nav-links a {
    position: relative; padding: 7px 12px; border-radius: 5px;
    font-size: 14px; font-weight: 600; color: rgba(244,236,224,.72);
    transition: color .2s ease, background .2s ease;
  }
  .lp-nav-links a:hover { color: var(--cream-text); background: rgba(244,236,224,.09); }
  .lp-nav-links a.is-active { color: var(--cream-text); }
  .lp-nav-links a.is-active::after {
    content: ''; position: absolute; left: 12px; right: 12px; bottom: 1px;
    height: 1.5px; background: var(--on-espresso-accent);
  }
  .lp-nav.is-solid .lp-nav-links a { color: var(--muted); }
  .lp-nav.is-solid .lp-nav-links a:hover { color: var(--ink); background: var(--surface-2); }
  .lp-nav.is-solid .lp-nav-links a.is-active { color: var(--accent); }
  .lp-nav.is-solid .lp-nav-links a.is-active::after { background: var(--accent); }

  .lp-nav-cta { display: flex; align-items: center; gap: 8px; }
  .lp-nav-signin {
    font-size: 14px; font-weight: 600; color: rgba(244,236,224,.8); padding: 6px 8px;
    transition: color .2s ease;
  }
  .lp-nav-signin:hover { color: var(--cream-text); }
  .lp-nav.is-solid .lp-nav-signin { color: var(--ink-strong); }
  .lp-nav.is-solid .lp-nav-signin:hover { color: var(--accent); }

  /* ── hero ── */
  .lp-hero {
    position: relative; isolation: isolate; overflow: hidden;
    min-height: 100svh; display: flex; align-items: center;
    padding: 124px var(--lp-gutter) 92px;
    background: var(--lp-espresso); color: var(--cream-text);
  }
  .lp-hero-bg {
    position: absolute; inset: -10% 0 0; z-index: 0; will-change: transform;
    background:
      radial-gradient(1000px 560px at 76% 6%, rgba(180,83,42,.30), transparent 68%),
      radial-gradient(760px 520px at 10% 94%, rgba(92,138,74,.13), transparent 70%),
      linear-gradient(150deg, #241A14 0%, #33241B 52%, #1F1610 100%);
  }
  .lp-hero-veil {
    position: absolute; inset: 0; z-index: 1; pointer-events: none;
    background: radial-gradient(540px 400px at var(--mx, 72%) var(--my, 24%), rgba(224,160,116,.16), transparent 72%);
  }
  .lp-dots { position: absolute; inset: 0; width: 100%; height: 100%; opacity: .5; }
  .lp-dot { fill: rgba(244,236,224,.18); }
  .lp-dot.is-hot { fill: var(--accent-2); animation: lpDotPulse 3.4s ease-in-out infinite; }
  /* Opacity only — animating the SVG r geometry property from CSS is not
     reliable across engines, and a brightness pulse reads the same anyway. */
  @keyframes lpDotPulse { 0%,100% { opacity: .3; } 50% { opacity: 1; } }

  .lp-hero-inner {
    position: relative; z-index: 2; width: 100%;
    display: grid; gap: 48px; align-items: center;
  }
  @media (min-width: 1040px) { .lp-hero-inner { grid-template-columns: minmax(0,1fr) minmax(0,.92fr); gap: clamp(36px, 4vw, 76px); } }

  .lp-kicker-pill {
    display: inline-flex; align-items: center; gap: 8px;
    border: 1px solid rgba(244,236,224,.2); border-radius: 5px;
    background: rgba(244,236,224,.07);
    padding: 7px 13px; font-size: var(--lp-label); font-weight: 700;
    letter-spacing: .13em; text-transform: uppercase; color: var(--on-espresso-accent);
    animation: lpFadeUp .7s ease both;
  }
  .lp-pulse-dot {
    position: relative; width: 6px; height: 6px; border-radius: 999px;
    background: var(--accent-2); flex: none;
  }
  .lp-pulse-dot::after {
    content: ''; position: absolute; inset: 0; border-radius: 999px;
    background: var(--accent-2); animation: pulseFade 2.4s ease-out infinite;
  }

  .lp-hero-eyebrow {
    margin: 24px 0 0; font-size: clamp(16px, 1.5vw, 21px);
    font-weight: 600; color: rgba(244,236,224,.62);
    animation: lpFadeUp .7s ease .06s both;
  }
  .lp-wc { display: inline-grid; vertical-align: bottom; height: 1.42em; overflow: hidden; }
  .lp-wc-item {
    grid-area: 1 / 1; color: var(--on-espresso-accent); font-weight: 700;
    opacity: 0; transform: translateY(.55em);
    transition: opacity .42s ease, transform .42s cubic-bezier(.2,.8,.2,1);
  }
  .lp-wc-item.is-on { opacity: 1; transform: none; }

  .lp-hero-lede {
    margin: 20px 0 0; max-width: 50ch;
    font-size: clamp(16px, 1.3vw, 20px); line-height: 1.58;
    color: rgba(244,236,224,.78);
    animation: lpFadeUp .7s ease .2s both;
  }
  .lp-hero-actions {
    margin-top: 30px; display: flex; flex-wrap: wrap; gap: 11px;
    animation: lpFadeUp .7s ease .28s both;
  }
  .lp-hero-stats {
    margin: 40px 0 0; padding: 22px 0 0; display: flex; flex-wrap: wrap; gap: clamp(24px, 3vw, 52px);
    border-top: 1px solid rgba(244,236,224,.16);
    animation: lpFadeUp .7s ease .36s both;
  }
  .lp-hero-stat { margin: 0; }
  .lp-hero-stat-num {
    font-size: clamp(24px, 2.05vw, 34px); font-weight: 600; line-height: 1;
    color: var(--cream-text); font-variant-numeric: tabular-nums; letter-spacing: -0.02em;
  }
  .lp-hero-stat-label {
    margin: 7px 0 0; max-width: 20ch; font-size: 13px; line-height: 1.45;
    color: rgba(244,236,224,.56);
  }
  @keyframes lpFadeUp { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: none; } }

  .lp-scroll-cue {
    position: absolute; left: 50%; bottom: 22px; z-index: 3; translate: -50% 0;
    display: grid; place-items: center; width: 38px; height: 38px;
    border-radius: 6px; border: 1px solid rgba(244,236,224,.3);
    color: var(--cream-text); animation: lpCue 2.6s ease-in-out infinite;
  }
  .lp-scroll-cue:hover { background: rgba(244,236,224,.14); color: var(--cream-text); }
  @keyframes lpCue { 0%,100% { translate: -50% 0; } 50% { translate: -50% 5px; } }

  /* ── hero preview card ── */
  .lp-preview-wrap { display: none; perspective: 1100px; }
  @media (min-width: 1040px) { .lp-preview-wrap { display: block; } }
  .lp-preview {
    border-radius: 12px; border: 1px solid rgba(244,236,224,.13); padding: 0 0 16px;
    background: var(--surface); overflow: hidden;
    box-shadow: 0 40px 80px -30px rgba(0,0,0,.72);
    transition: transform .18s ease-out;
  }
  .lp-preview.is-floating { animation: lpFloat 7s ease-in-out infinite; }
  @keyframes lpFloat { 0%,100% { translate: 0 0; } 50% { translate: 0 -11px; } }
  .lp-preview-chrome {
    display: flex; gap: 4px; padding: 10px 14px;
    border-bottom: 1px solid var(--border); background: var(--surface-2);
  }
  .lp-preview-tab {
    padding: 5px 11px; border-radius: 4px; font-size: 12px; font-weight: 700;
    color: var(--muted-2);
  }
  .lp-preview-tab.is-on { background: var(--ink-strong); color: var(--cream-text); }

  .lp-preview-action {
    display: flex; align-items: center; gap: 12px; margin: 14px; border-radius: 8px; padding: 14px;
    background: linear-gradient(115deg, var(--lp-espresso), var(--lp-espresso-2));
    color: var(--cream-text);
  }
  .lp-preview-avatar {
    position: relative; display: grid; place-items: center; flex: none;
    width: 34px; height: 34px; border-radius: 999px; background: var(--accent); font-size: 15px;
  }
  .lp-preview-ping {
    position: absolute; inset: 0; border-radius: 999px; background: var(--accent);
    animation: pulseFade 2.4s ease-out infinite;
  }
  .lp-preview-action-text { min-width: 0; }
  .lp-preview-eyebrow {
    margin: 0; font-size: 9.5px; font-weight: 700; text-transform: uppercase;
    letter-spacing: .14em; color: var(--on-espresso-accent);
  }
  .lp-preview-name { margin: 3px 0 0; font-size: 16px; font-weight: 600; }
  .lp-preview-meta {
    margin: 3px 0 0; font-size: 11.5px; color: #D5C2B1;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .lp-preview-send {
    margin-left: auto; flex: none; border-radius: 5px; padding: 7px 12px;
    font-size: 11.5px; font-weight: 700; background: var(--cream-text); color: var(--ink-strong);
  }
  .lp-preview-kpis {
    margin: 0 14px; display: grid; grid-template-columns: repeat(4, 1fr);
    border: 1px solid var(--border); border-radius: 8px; overflow: hidden;
  }
  .lp-preview-kpi { padding: 9px 10px; background: var(--surface-2); border-right: 1px solid var(--border); }
  .lp-preview-kpi:last-child { border-right: none; }
  .lp-preview-kpi-l { margin: 0; font-size: 10px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .07em; }
  .lp-preview-kpi-v { margin: 4px 0 0; font-size: 18px; font-weight: 600; }
  .lp-preview-rows { margin: 12px 14px 0; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
  .lp-preview-row {
    display: flex; align-items: center; gap: 10px; padding: 9px 12px;
    border-bottom: 1px solid var(--border-soft); background: var(--surface);
  }
  .lp-preview-row:last-child { border-bottom: none; }
  .lp-preview-row-name { font-size: 13px; font-weight: 700; color: var(--ink); }
  .lp-preview-row-why { font-size: 11.5px; color: var(--muted-2); margin-left: auto; }
  .lp-preview-row-badge { border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: 700; flex: none; }

  /* ── marquee ── */
  .lp-marquee-band { overflow: hidden; padding: 20px 0; background: var(--lp-espresso); border-top: 1px solid rgba(244,236,224,.12); }
  .lp-marquee { display: inline-block; white-space: nowrap; animation: lpMarquee 36s linear infinite; }
  .lp-marquee-item {
    display: inline-flex; align-items: center; gap: 20px; margin: 0 18px;
    font-size: clamp(16px, 1.5vw, 23px); font-weight: 500; color: rgba(244,236,224,.8);
    letter-spacing: -0.01em;
  }
  .lp-marquee-dot { color: var(--on-espresso-accent); }
  @keyframes lpMarquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }

  /* ── stat band ── */
  .lp-statband { background: var(--surface); border-bottom: 1px solid var(--lp-rule); }
  .lp-statband-grid {
    margin: 0; padding: 0; display: grid; grid-template-columns: 1fr;
  }
  @media (min-width: 620px) { .lp-statband-grid { grid-template-columns: 1fr 1fr; } }
  @media (min-width: 1040px) { .lp-statband-grid { grid-template-columns: repeat(4, 1fr); } }
  .lp-statcell {
    padding: clamp(26px, 2.6vw, 40px) clamp(20px, 2.2vw, 38px);
    border-right: 1px solid var(--lp-rule); border-bottom: 1px solid var(--lp-rule);
    transition: opacity .7s ease, transform .7s cubic-bezier(.2,.8,.2,1), background .25s ease;
  }
  .lp-statcell:hover { background: var(--surface-2); }
  .lp-statcell:last-child { border-right: none; }
  .lp-statband-grid > :first-child { padding-left: var(--lp-gutter); }
  .lp-statband-grid > :last-child { padding-right: var(--lp-gutter); }
  .lp-statcell-n {
    font-size: clamp(30px, 3vw, 46px); font-weight: 600; line-height: 1;
    letter-spacing: -0.03em; color: var(--ink); font-variant-numeric: tabular-nums;
  }
  .lp-statcell-body { margin: 13px 0 0; display: block; }
  .lp-statcell-label { display: block; font-size: var(--lp-body); line-height: 1.5; color: var(--muted); max-width: 26ch; }
  .lp-statcell-note { display: block; margin-top: 8px; font-size: 14px; font-weight: 600; color: var(--accent); }

  /* ── section shell ──
     Bottom padding is deliberately much tighter than the top: the last row of
     a ledger/tier grid already carries its own bottom padding, and stacking a
     full section pad on top of it left a dead band above every rule. */
  .lp-section {
    padding: clamp(52px, 5.8vw, 98px) var(--lp-gutter) clamp(26px, 2.6vw, 44px);
    border-bottom: 1px solid var(--lp-rule); scroll-margin-top: 70px;
  }
  .lp-alt { background: var(--surface); }
  .lp-dark-section {
    background: var(--lp-espresso); color: var(--cream-text);
    border-bottom-color: rgba(244,236,224,.14);
  }

  .lp-head-bar {
    display: flex; align-items: baseline; justify-content: space-between; gap: 16px;
    padding-bottom: 13px; margin-bottom: clamp(22px, 2.4vw, 38px);
    border-bottom: 1px solid var(--ink);
  }
  .lp-head.is-dark .lp-head-bar { border-bottom-color: rgba(244,236,224,.5); }
  .lp-head-index {
    font-size: var(--lp-label); font-weight: 700; letter-spacing: .12em; color: var(--muted-2);
    font-variant-numeric: tabular-nums;
  }
  .lp-head.is-dark .lp-head-index { color: rgba(244,236,224,.5); }
  .lp-head-slash { opacity: .5; }
  .lp-head-split { display: grid; gap: clamp(18px, 2.6vw, 52px); align-items: start; }
  @media (min-width: 940px) { .lp-head-split { grid-template-columns: minmax(0,1.35fr) minmax(0,1fr); } }
  .lp-head-aside { padding-top: 6px; }
  .lp-head-aside p {
    margin: 0; font-size: var(--lp-body-lg); line-height: 1.58; color: var(--muted);
    max-width: 44ch;
  }
  .lp-head-aside p + p { margin-top: 13px; }
  .lp-head-aside-note { color: var(--muted-2) !important; }
  .lp-head-aside.is-dark p { color: rgba(244,236,224,.68); }

  /* ── flow diagram ── */
  .lp-flow { margin: clamp(30px, 3.6vw, 60px) 0 0; overflow-x: auto; }
  .lp-flow-svg { display: block; width: 100%; min-width: 780px; height: auto; }
  .lp-flow-head { font-size: 11.5px; font-weight: 700; letter-spacing: .14em; fill: var(--muted-2); }
  .lp-flow-chip { fill: var(--bg-page); stroke: var(--border); stroke-width: 1; }
  .lp-flow-chip.is-out { fill: #F7E9DE; stroke: #E6C6AE; }
  .lp-flow-chip-label { font-size: 14px; font-weight: 600; fill: var(--ink); }
  .lp-flow-chip-label.is-out { fill: var(--accent-dark); }
  .lp-flow-hub { fill: var(--accent); }
  .lp-flow-arrow { fill: var(--accent); }
  .lp-flow-core { fill: var(--lp-espresso); stroke: var(--ink-strong); }
  .lp-flow-core-mark { font-size: 20px; font-weight: 600; fill: var(--cream-text); text-anchor: middle; }
  .lp-flow-core-line { font-size: 10px; font-weight: 700; letter-spacing: .12em; fill: var(--on-espresso-accent); text-anchor: middle; }
  .lp-flow-core-sub { font-size: 9px; font-weight: 600; letter-spacing: .1em; fill: rgba(244,236,224,.52); text-anchor: middle; }
  /* pathLength="1" normalizes each line, so one dasharray works for all of
     them without measuring geometry in JS. */
  .lp-flow-wire { stroke: var(--muted-2); stroke-width: 1.3; fill: none; opacity: .8; stroke-dasharray: 1; stroke-dashoffset: 1; }
  [data-reveal].is-in .lp-flow-wire { animation: lpDraw .55s ease forwards; }
  @keyframes lpDraw { to { stroke-dashoffset: 0; } }
  .lp-flow-arrow, .lp-flow-hub { opacity: 0; }
  [data-reveal].is-in .lp-flow-arrow, [data-reveal].is-in .lp-flow-hub { animation: lpFadeIn .4s ease .55s forwards; }
  @keyframes lpFadeIn { to { opacity: 1; } }

  /* ── stance ── */
  .lp-stance { display: grid; grid-template-columns: 1fr; border-top: 1px solid var(--ink); }
  @media (min-width: 800px) { .lp-stance { grid-template-columns: 1fr 1fr; } }
  .lp-stance-col {
    padding: clamp(22px, 2.2vw, 34px) clamp(22px, 2.4vw, 44px) clamp(24px, 2.4vw, 38px) 0;
    transition: opacity .7s ease, transform .7s cubic-bezier(.2,.8,.2,1);
  }
  .lp-stance-col.is-you { border-top: 1px solid var(--lp-rule); padding-left: 0; }
  @media (min-width: 800px) {
    .lp-stance-col.is-you {
      border-top: none; border-left: 1px solid var(--lp-rule);
      padding-left: clamp(24px, 2.6vw, 48px);
    }
  }
  .lp-stance-role {
    display: block; font-size: var(--lp-label); font-weight: 700; letter-spacing: .14em;
    text-transform: uppercase; color: var(--muted-2); margin-bottom: 12px;
  }
  .lp-stance-col.is-you .lp-stance-role { color: var(--accent); }
  .lp-stance-h {
    margin: 0; font-size: clamp(21px, 2vw, 32px); font-weight: 600;
    letter-spacing: -0.025em; line-height: 1.12; color: var(--ink);
  }
  .lp-stance-body { margin: 13px 0 0; font-size: var(--lp-body-lg); line-height: 1.58; color: var(--muted); max-width: 42ch; }

  /* ── demo ── */
  .lp-demo { display: grid; gap: clamp(28px, 3.4vw, 60px); align-items: start; }
  @media (min-width: 1000px) { .lp-demo { grid-template-columns: minmax(0,.92fr) minmax(0,1.08fr); } }
  .lp-demo-lede { margin: 18px 0 0; font-size: var(--lp-body-lg); line-height: 1.58; color: var(--muted); max-width: 44ch; }
  .lp-demo-points { margin: 26px 0 0; padding: 0; list-style: none; border-top: 1px solid var(--lp-rule); }
  .lp-demo-points li {
    padding: 16px 0; border-bottom: 1px solid var(--lp-rule);
    font-size: var(--lp-body); line-height: 1.58; color: var(--muted);
  }
  .lp-demo-point-k {
    display: block; font-size: var(--lp-label); font-weight: 700; letter-spacing: .12em;
    text-transform: uppercase; color: var(--ink-strong); margin-bottom: 6px;
  }

  .lp-demo-card {
    border: 1px solid var(--lp-rule); border-radius: 12px;
    padding: clamp(20px, 2.2vw, 32px); background: var(--bg-page);
  }
  .lp-alt .lp-demo-card { background: var(--surface); }
  .lp-demo-picker { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; }
  .lp-demo-picker-label { font-size: 14.5px; font-weight: 600; color: var(--muted); margin-right: 3px; }
  .lp-demo-picker-note { margin: 10px 0 0; font-size: 14px; color: var(--muted-2); }
  .lp-chip {
    border: 1px solid var(--border); border-radius: 5px; padding: 7px 14px;
    font-size: 14px; font-weight: 600; background: transparent; color: var(--muted);
    transition: background .16s ease, color .16s ease, border-color .16s ease;
  }
  .lp-chip:hover { border-color: var(--accent); color: var(--accent); }
  .lp-chip.is-on { background: var(--ink-strong); border-color: var(--ink-strong); color: var(--cream-text); }

  .lp-demo-slider { margin-top: 26px; }
  .lp-demo-slider-head { display: flex; align-items: baseline; justify-content: space-between; }
  .lp-demo-slider-label { font-size: 14.5px; font-weight: 600; color: var(--ink-strong); }
  .lp-demo-days { font-size: 32px; font-weight: 600; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
  .lp-demo-slider-ends { margin-top: 6px; display: flex; justify-content: space-between; font-size: 12px; color: var(--muted-2); }
  .lp-slider {
    margin-top: 11px; width: 100%; height: 6px; border-radius: 999px;
    background: var(--surface-3); appearance: none; -webkit-appearance: none; cursor: pointer;
  }
  .lp-slider::-webkit-slider-thumb {
    -webkit-appearance: none; appearance: none; width: 24px; height: 24px; border-radius: 50%;
    background: var(--surface); border: 3px solid currentColor;
    box-shadow: 0 2px 6px rgba(59,42,32,.3); cursor: grab;
  }
  .lp-slider:active::-webkit-slider-thumb { cursor: grabbing; transform: scale(1.08); }
  .lp-slider::-moz-range-thumb {
    width: 24px; height: 24px; border-radius: 50%;
    background: var(--surface); border: 3px solid currentColor;
    box-shadow: 0 2px 6px rgba(59,42,32,.3); cursor: grab;
  }

  .lp-demo-readout {
    margin-top: 26px; border-top: 1px solid var(--lp-rule); padding-top: 24px;
    display: flex; flex-direction: column; align-items: flex-start; gap: 18px;
  }
  @media (min-width: 560px) { .lp-demo-readout { flex-direction: row; align-items: center; } }
  .lp-demo-readout-text { min-width: 0; flex: 1; }
  .lp-dial { position: relative; width: 116px; height: 116px; flex: none; }
  .lp-dial-arc { transition: stroke-dasharray .35s cubic-bezier(.2,.8,.2,1), stroke .35s ease; }
  .lp-dial-center { position: absolute; inset: 0; display: grid; place-content: center; text-align: center; }
  .lp-dial-num { font-size: 28px; font-weight: 600; line-height: 1; letter-spacing: -0.02em; }
  .lp-dial-cap { font-size: 10px; text-transform: uppercase; letter-spacing: .12em; color: var(--muted-2); }
  .lp-demo-band {
    display: inline-flex; align-items: center; gap: 7px; border-radius: 5px;
    padding: 6px 12px; font-size: 13.5px; font-weight: 700;
  }
  .lp-demo-band-dot { width: 7px; height: 7px; border-radius: 999px; }
  .lp-demo-quote { margin: 13px 0 0; font-size: var(--lp-body-lg); line-height: 1.52; color: var(--ink-strong); }
  .lp-demo-action { margin: 7px 0 0; font-size: var(--lp-body); color: var(--muted); }

  /* ── ledger grids (features, guardrails) ── */
  .lp-ledger {
    margin: 0; padding: 0; list-style: none;
    display: grid; grid-template-columns: 1fr; border-top: 1px solid var(--ink);
  }
  .lp-ledger.is-dark { border-top-color: rgba(244,236,224,.5); }
  @media (min-width: 620px) { .lp-ledger-3, .lp-ledger-4 { grid-template-columns: 1fr 1fr; } }
  @media (min-width: 1000px) { .lp-ledger-3 { grid-template-columns: repeat(3, 1fr); } }
  @media (min-width: 1000px) { .lp-ledger-4 { grid-template-columns: repeat(4, 1fr); } }
  .lp-ledger-cell {
    padding: clamp(20px, 2.1vw, 30px) clamp(20px, 2.2vw, 36px) clamp(24px, 2.3vw, 34px) 0;
    border-bottom: 1px solid var(--lp-rule);
    transition: opacity .7s ease, transform .7s cubic-bezier(.2,.8,.2,1);
  }
  .lp-ledger.is-dark .lp-ledger-cell { border-bottom-color: rgba(244,236,224,.16); }
  .lp-ledger-n {
    display: block; font-size: var(--lp-label); font-weight: 700; letter-spacing: .12em;
    color: var(--accent); margin-bottom: 11px; font-variant-numeric: tabular-nums;
  }
  .lp-ledger-h {
    margin: 0; font-size: clamp(18px, 1.55vw, 23px); font-weight: 600;
    letter-spacing: -0.02em; line-height: 1.15; color: var(--ink);
  }
  .lp-ledger.is-dark .lp-ledger-h { color: var(--cream-text); }
  .lp-ledger-body { margin: 10px 0 0; font-size: var(--lp-body); line-height: 1.58; color: var(--muted); max-width: 38ch; }
  .lp-ledger.is-dark .lp-ledger-body { color: rgba(244,236,224,.66); }

  /* vertical hairlines between ledger columns */
  @media (min-width: 620px) {
    .lp-ledger-3 > *, .lp-ledger-4 > * { border-right: 1px solid var(--lp-rule); padding-left: clamp(18px, 1.8vw, 30px); }
    .lp-ledger-3 > :nth-child(2n), .lp-ledger-4 > :nth-child(2n) { border-right: none; }
    .lp-ledger-3 > :nth-child(2n+1), .lp-ledger-4 > :nth-child(2n+1) { padding-left: 0; }
    .lp-ledger.is-dark > * { border-right-color: rgba(244,236,224,.16); }
  }
  @media (min-width: 1000px) {
    .lp-ledger-3 > * { border-right: 1px solid var(--lp-rule); padding-left: clamp(18px, 1.8vw, 30px); }
    .lp-ledger-3 > :nth-child(3n) { border-right: none; }
    .lp-ledger-3 > :nth-child(3n+1) { padding-left: 0; }
    .lp-ledger-4 > * { border-right: 1px solid var(--lp-rule); padding-left: clamp(18px, 1.8vw, 30px); }
    .lp-ledger-4 > :nth-child(4n) { border-right: none; }
    .lp-ledger-4 > :nth-child(4n+1) { padding-left: 0; }
    .lp-ledger.is-dark > * { border-right-color: rgba(244,236,224,.16); }
  }

  /* ── steps ── */
  .lp-steps { margin: 0; padding: 0; list-style: none; display: grid; gap: clamp(24px, 3vw, 60px); }
  @media (min-width: 860px) { .lp-steps { grid-template-columns: repeat(3, 1fr); } }
  .lp-step {
    display: flex; flex-direction: column; border-top: 2px solid var(--accent); padding-top: 18px;
    transition: opacity .7s ease, transform .7s cubic-bezier(.2,.8,.2,1);
  }
  .lp-step-n { font-size: var(--lp-label); font-weight: 700; letter-spacing: .12em; color: var(--accent); margin-bottom: 14px; }
  .lp-step-h { margin: 0; font-size: clamp(20px, 1.75vw, 28px); font-weight: 600; letter-spacing: -0.025em; line-height: 1.14; color: var(--ink); }
  .lp-step-body { margin: 12px 0 0; font-size: var(--lp-body-lg); line-height: 1.56; color: var(--muted); max-width: 33ch; }
  .lp-step-foot {
    margin-top: 17px; font-size: var(--lp-label); font-weight: 700; letter-spacing: .1em;
    text-transform: uppercase; color: var(--muted-2);
  }

  /* ── team ── */
  .lp-team-grid {
    display: grid; grid-template-columns: 1fr;
    margin-top: clamp(34px, 4vw, 64px); border-top: 1px solid var(--ink);
  }
  .lp-team-card {
    display: flex; min-width: 0; flex-direction: column;
    padding: clamp(22px, 2.2vw, 34px) 0 clamp(26px, 2.6vw, 40px);
    border-bottom: 1px solid var(--lp-rule);
    transition: opacity .7s ease, transform .7s cubic-bezier(.2,.8,.2,1);
  }
  @media (min-width: 640px) {
    .lp-team-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .lp-team-card:nth-child(odd) { padding-right: clamp(20px, 2.4vw, 38px); }
    .lp-team-card:nth-child(even) {
      padding-left: clamp(20px, 2.4vw, 38px);
      border-left: 1px solid var(--lp-rule);
    }
  }
  @media (min-width: 1080px) {
    .lp-team-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .lp-team-card,
    .lp-team-card:nth-child(odd),
    .lp-team-card:nth-child(even) {
      padding-left: clamp(18px, 1.7vw, 30px);
      padding-right: clamp(18px, 1.7vw, 30px);
      border-left: 1px solid var(--lp-rule);
    }
    .lp-team-card:first-child { padding-left: 0; border-left: none; }
    .lp-team-card:last-child { padding-right: 0; }
  }
  .lp-team-photo {
    position: relative; overflow: hidden; aspect-ratio: 4 / 3;
    background: var(--surface-3);
  }
  .lp-team-photo img {
    display: block; width: 100%; height: 100%; object-fit: cover;
    filter: saturate(.88) contrast(1.02);
    transition: transform .5s cubic-bezier(.2,.8,.2,1), filter .3s ease;
  }
  .lp-team-card:hover .lp-team-photo img { transform: scale(1.025); filter: saturate(1) contrast(1.02); }
  .lp-team-placeholder {
    position: absolute; inset: 0; display: grid; place-items: center; overflow: hidden;
    color: var(--cream-text);
    background:
      radial-gradient(220px 180px at 72% 18%, rgba(199,107,58,.48), transparent 70%),
      linear-gradient(145deg, var(--lp-espresso-2), var(--lp-espresso));
  }
  .lp-team-placeholder::before {
    content: ''; position: absolute; width: 68%; aspect-ratio: 1; border-radius: 50%;
    border: 1px solid rgba(244,236,224,.18);
    box-shadow: 0 0 0 24px rgba(244,236,224,.035), 0 0 0 48px rgba(244,236,224,.025);
  }
  .lp-team-placeholder span {
    position: relative; font-family: var(--font-display); font-size: clamp(50px, 5vw, 76px);
    font-weight: 500; letter-spacing: -.05em;
  }
  .lp-team-meta {
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
    margin-top: 17px;
  }
  .lp-team-role {
    font-size: var(--lp-label); font-weight: 700; letter-spacing: .13em;
    text-transform: uppercase; color: var(--accent);
  }
  .lp-team-meta a {
    font-size: 12.5px; font-weight: 700; color: var(--muted-2);
    text-decoration: none;
  }
  .lp-team-meta a:hover { color: var(--accent); text-decoration: underline; text-underline-offset: 3px; }
  .lp-team-name {
    margin: 12px 0 0; font-size: clamp(23px, 2vw, 30px); font-weight: 600;
    letter-spacing: -.025em; line-height: 1.08; color: var(--ink);
  }
  .lp-team-education {
    margin: 7px 0 0; min-height: 2.8em; font-size: 13.5px; font-weight: 700;
    line-height: 1.4; color: var(--ink-strong);
  }
  .lp-team-bio {
    margin: 13px 0 0; font-size: var(--lp-body); line-height: 1.58;
    color: var(--muted); max-width: 35ch;
  }
  .lp-team-email {
    align-self: flex-start; margin-top: auto; padding-top: 17px;
    color: var(--muted-2); font-size: 12.5px; font-weight: 700;
    text-decoration: none;
  }
  .lp-team-email:hover {
    color: var(--accent); text-decoration: underline; text-underline-offset: 3px;
  }

  /* ── pricing ── */
  .lp-tiers { display: grid; grid-template-columns: 1fr; border-top: 1px solid var(--ink); }
  @media (min-width: 860px) { .lp-tiers { grid-template-columns: repeat(3, 1fr); } }
  .lp-tier {
    display: flex; flex-direction: column;
    padding: clamp(24px, 2.4vw, 36px) clamp(20px, 2.2vw, 34px) clamp(26px, 2.4vw, 36px) 0;
    border-bottom: 1px solid var(--lp-rule);
    transition: opacity .7s ease, transform .7s cubic-bezier(.2,.8,.2,1), background .25s ease;
  }
  @media (min-width: 860px) {
    .lp-tier { border-right: 1px solid var(--lp-rule); padding-left: clamp(20px, 2.2vw, 34px); }
    .lp-tier:first-child { padding-left: 0; }
    .lp-tier:last-child { border-right: none; }
  }
  /* The highlight has to survive on both section backgrounds, so it leans on a
     top accent bar rather than a tint a shade away from the surface it sits on. */
  .lp-tier.is-hot { background: var(--surface); box-shadow: inset 0 2px 0 var(--accent); }
  .lp-tier-top { display: flex; align-items: center; gap: 10px; }
  .lp-tier-name { margin: 0; font-size: 21px; font-weight: 600; letter-spacing: -0.02em; color: var(--ink); }
  .lp-tier-flag {
    border-radius: 4px; padding: 3.5px 9px; font-size: 10.5px; font-weight: 700;
    text-transform: uppercase; letter-spacing: .09em; background: var(--accent); color: #fff;
  }
  .lp-tier-price { margin: 14px 0 0; }
  .lp-tier-amount { font-size: clamp(38px, 3.3vw, 52px); font-weight: 600; letter-spacing: -0.035em; color: var(--ink); }
  .lp-tier-per { font-size: 14.5px; color: var(--muted-2); }
  .lp-tier-lines { margin: 18px 0 0; padding: 0; list-style: none; flex: 1; }
  .lp-tier-lines li {
    padding: 8px 0 8px 17px; position: relative; font-size: var(--lp-body); line-height: 1.5; color: var(--muted);
  }
  .lp-tier-lines li::before {
    content: ''; position: absolute; left: 0; top: 17px;
    width: 7px; height: 1.5px; background: var(--accent);
  }
  .lp-tier-cta {
    margin-top: 22px; padding: 12px 16px; font-size: 14.5px;
    border-color: var(--border); color: var(--ink-strong); background: transparent;
  }
  .lp-tier-cta:hover { background: var(--ink-strong); border-color: var(--ink-strong); color: var(--cream-text); }

  /* ── waitlist ── */
  .lp-waitlist {
    position: relative; overflow: hidden; scroll-margin-top: 70px;
    padding: clamp(64px, 7.4vw, 128px) var(--lp-gutter) clamp(44px, 4.6vw, 76px);
    background:
      radial-gradient(820px 460px at 14% 6%, rgba(180,83,42,.26), transparent 68%),
      linear-gradient(160deg, var(--lp-espresso) 0%, var(--lp-espresso-2) 62%, #1E1610 100%);
    color: var(--cream-text);
  }
  /* centre, not start: the form card is much shorter than the copy column, and
     top-aligning it left a large void under the card. */
  .lp-waitlist-grid { display: grid; gap: clamp(30px, 3.6vw, 68px); align-items: center; }
  @media (min-width: 980px) { .lp-waitlist-grid { grid-template-columns: minmax(0,.94fr) minmax(0,1.06fr); } }
  .lp-waitlist-copy .lp-h2 { margin-top: 14px; }
  .lp-waitlist-sub {
    margin: 18px 0 0; max-width: 46ch; font-size: var(--lp-body-lg);
    line-height: 1.58; color: rgba(244,236,224,.76);
  }
  .lp-waitlist-points { margin: 24px 0 0; padding: 0; list-style: none; border-top: 1px solid rgba(244,236,224,.18); }
  .lp-waitlist-points li {
    padding: 13px 0 13px 19px; position: relative; border-bottom: 1px solid rgba(244,236,224,.13);
    font-size: var(--lp-body); color: rgba(244,236,224,.74);
  }
  .lp-waitlist-points li::before {
    content: ''; position: absolute; left: 0; top: 21px;
    width: 8px; height: 1.5px; background: var(--on-espresso-accent);
  }
  .lp-waitlist-card {
    border: 1px solid rgba(244,236,224,.16); border-radius: 12px;
    background: rgba(244,236,224,.045);
    padding: clamp(20px, 2.4vw, 32px);
  }
  .lp-waitlist-alt {
    margin: clamp(30px, 3.4vw, 52px) 0 0; padding-top: 20px;
    border-top: 1px solid rgba(244,236,224,.14);
    font-size: 14px; color: rgba(244,236,224,.6);
  }
  .lp-waitlist-alt a { color: var(--on-espresso-accent); text-decoration: underline; }

  /* waitlist form (WaitlistForm.tsx) */
  .lp-wl-grid { display: grid; gap: 14px; }
  @media (min-width: 560px) { .lp-wl-grid { grid-template-columns: repeat(2, 1fr); } }
  .lp-wl-field { display: block; }
  .lp-wl-label {
    display: block; margin-bottom: 7px;
    font-size: 11px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase;
    color: rgba(244,236,224,.64);
  }
  .lp-wl-opt { font-weight: 600; letter-spacing: .06em; color: rgba(244,236,224,.4); }
  .lp-wl-input {
    width: 100%; border-radius: 6px; padding: 12px 14px;
    border: 1px solid rgba(244,236,224,.2); background: rgba(21,15,11,.4);
    color: var(--cream-text); font-family: inherit; font-size: 15.5px;
    transition: border-color .18s ease, background .18s ease;
  }
  .lp-wl-input::placeholder { color: rgba(244,236,224,.32); }
  .lp-wl-input:focus { outline: none; border-color: var(--on-espresso-accent); background: rgba(21,15,11,.58); }
  .lp-wl-select { appearance: none; cursor: pointer; }
  .lp-wl-select option { background: var(--lp-espresso); color: var(--cream-text); }
  .lp-wl-honey { position: absolute; left: -9999px; width: 1px; height: 1px; opacity: 0; }
  .lp-wl-error {
    margin: 14px 0 0; border-radius: 6px; padding: 10px 13px; font-size: 14px;
    background: rgba(162,59,30,.24); border: 1px solid rgba(224,160,116,.4); color: #F6D9C8;
  }
  .lp-wl-actions { margin-top: 21px; display: flex; flex-wrap: wrap; align-items: center; gap: 14px; }
  .lp-wl-submit {
    border-radius: 6px; padding: 13px 24px; font-size: 15.5px; font-weight: 700;
    background: var(--accent); color: #fff; border: 1px solid var(--accent);
    transition: transform .16s ease, background .16s ease;
  }
  .lp-wl-submit:hover:not(:disabled) { transform: translateY(-1px); background: var(--accent-dark); border-color: var(--accent-dark); }
  .lp-wl-submit:disabled { opacity: .6; cursor: default; }
  .lp-wl-fine { font-size: 13px; color: rgba(244,236,224,.54); max-width: 24ch; }

  .lp-wl-done { text-align: center; padding: 12px 0 4px; }
  .lp-wl-check {
    display: grid; place-items: center; width: 42px; height: 42px; margin: 0 auto;
    border-radius: 8px; background: rgba(92,138,74,.24);
    border: 1px solid rgba(140,190,120,.5); color: #B9DCA6;
    animation: lpPop .45s cubic-bezier(.2,1.4,.4,1) both;
  }
  @keyframes lpPop { from { opacity: 0; transform: scale(.6); } to { opacity: 1; transform: none; } }
  .lp-wl-done-h { margin: 15px 0 0; font-size: 25px; font-weight: 600; letter-spacing: -0.02em; color: var(--cream-text); }
  .lp-wl-done-p { margin: 9px auto 0; max-width: 42ch; font-size: var(--lp-body-lg); line-height: 1.58; color: rgba(244,236,224,.76); }

  /* ── footer ── */
  .lp-footer { background: var(--surface); padding: 28px var(--lp-gutter); }
  .lp-footer-inner { display: flex; flex-direction: column; align-items: center; justify-content: space-between; gap: 14px; }
  @media (min-width: 760px) { .lp-footer-inner { flex-direction: row; } }
  .lp-footer-tag { font-size: 13px; color: var(--muted-2); }
  .lp-footer-links { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 17px; font-size: 13px; color: var(--muted-2); }
  .lp-footer-links a { color: var(--muted-2); }
  .lp-footer-links button { border: 0; padding: 0; background: none; color: var(--muted-2); font: inherit; cursor: pointer; }
  .lp-footer-links a:hover, .lp-footer-links button:hover { color: var(--accent); text-decoration: underline; }

  /* Smooth anchor scrolling, but not for people who asked us not to. */
  @media (prefers-reduced-motion: no-preference) { html { scroll-behavior: smooth; } }

  /* ── reduced motion: keep colour and opacity cues, drop the movement ── */
  @media (prefers-reduced-motion: reduce) {
    .lp-root *, .lp-root *::before, .lp-root *::after {
      animation-duration: .001ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: .001ms !important;
    }
    .lp-root [data-reveal] { opacity: 1 !important; transform: none !important; }
    .lp-marquee, .lp-preview.is-floating, .lp-scroll-cue { animation: none !important; }
    .lp-flow-wire { stroke-dashoffset: 0 !important; }
    .lp-flow-arrow, .lp-flow-hub { opacity: 1 !important; }
    .lp-char { animation: none !important; opacity: 1 !important; transform: none !important; }
  }
`;
