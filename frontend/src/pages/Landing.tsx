import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import icon from "../assets/icon.png";
import adityaPhoto from "../assets/team/aditya-kolekar.jpg";
import asimPhoto from "../assets/team/asim-siddiqui.jpg";
import pranjalPhoto from "../assets/team/pranjal-mishra.jpg";
import riyanPhoto from "../assets/team/riyan-anosh.jpg";
import sohamPhoto from "../assets/team/soham-dogra.jpg";
import WaitlistForm from "../components/WaitlistForm";
import { landingViewMetric, trackLandingEvent } from "../lib/landingAnalytics";
import {
  bandAction,
  bandQuote,
  beatVisibility,
  clamp,
  dialDash,
  DIAL_RADIUS,
  driftReach,
  driftState,
  flowLineOpacity,
  flowPath,
  riskBand,
  riskScore,
  sceneProgress,
  SIGNAL_FOCUS,
  signalOpacity,
  VERTICALS,
  type VerticalKey,
} from "../lib/landingScene";
import {
  hasAnalyticsConsent,
  onPrivacyPreferenceChange,
} from "../lib/privacyPreferences";
import { useRafScroll } from "../lib/rafScroll";

/* ─────────────────────────────────────────────────────────────
   Public marketing landing page.

   Ported from the reference build in docs/PORT-NOTES.md. Two
   scroll-driven scenes carry the page:

     • the pinned "flow" scene — 340vh tall, a sticky 100vh child,
       cards drifting in from both sides toward the app icon, then a
       hard hand-off to a second beat;
     • the "signal feed" — a left column of cards driving a sticky
       right-hand panel that fills in line by line.

   Both run off ONE rAF-throttled scroll listener and one paint()
   pass (lib/rafScroll.ts). Deliberately no scroll library and no
   IntersectionObserver for animation: a single pass is what keeps
   the two scenes in step with each other.

   Pre-animation states are set from JS in prime(), never in CSS, so
   the page stays fully readable if the script never runs.

   Colour comes from the landing tokens in index.css — no literal
   hex in this file. Copy is final; it is quoted from the reference
   verbatim, and the compliance block is legal copy, not marketing.
   ───────────────────────────────────────────────────────────── */

/**
 * Media queries, guarded for a window-less render.
 *
 * There is no SSR here, but the test suite renders pages with
 * renderToStaticMarkup, and an unguarded matchMedia would make this page the
 * one component nobody can assert anything about.
 */
function queryMatches(query: string): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia(query).matches;
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => queryMatches(query));
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia(query);
    const on = () => setMatches(mq.matches);
    setMatches(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return matches;
}

/** True when the visitor asked the OS to cut animation. */
function useReducedMotion(): boolean {
  return useMediaQuery("(prefers-reduced-motion: reduce)");
}

/**
 * Consent-gated page + section analytics. The reference build has no
 * instrumentation; this is ours and stays. Section ids match the reference's,
 * so the observer needs no changes.
 *
 * This IntersectionObserver is measurement, not animation — the no-IO rule
 * applies to the scroll scenes, which must share one paint() pass.
 */
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

/* ── content ─────────────────────────────────────────────────────────────── */

const NAV_LINKS: [string, string][] = [
  ["#flow", "How it works"],
  ["#signals", "Signals"],
  ["#demo", "Demo"],
  ["#team", "Team"],
  ["#pricing", "Pricing"],
];

const TRADES = [
  "Cafés",
  "Coffee shops",
  "Salons",
  "Barbershops",
  "Fitness studios",
  "Gyms",
  "Med spas",
  "Juice bars",
  "Bakeries",
  "Yoga studios",
];

const HERO_ROWS: [string, string, string, string][] = [
  ["Isabella Torres", "21 days · 6.9× her usual gap", "Critical · 91", "crit"],
  ["Priya Ferreira", "14 days · 2.8× gap", "At risk · 62", "warm"],
  ["Marcus Silva", "9 days · 1.8× gap", "Watch · 48", "warm"],
  ["Ana Beatriz", "3 days · on rhythm", "Healthy · 12", "calm"],
];

/** Beat A: the three inputs against the three outputs. */
const FLOW_A: { side: "left" | "right"; eyebrow: string; body: string; shadow: string }[] = [
  { side: "left", eyebrow: "Goes in", body: "Square, live", shadow: "ink" },
  { side: "left", eyebrow: "Goes in", body: "Stripe, live", shadow: "terra" },
  { side: "left", eyebrow: "Goes in", body: "customers.csv", shadow: "green" },
  {
    side: "right",
    eyebrow: "Comes out",
    body: "“21 days out, 6.9× her usual gap.”",
    shadow: "ink",
  },
  {
    side: "right",
    eyebrow: "Comes out",
    body: "A drafted win-back, waiting on you",
    shadow: "terra",
  },
  { side: "right", eyebrow: "Comes out", body: "~$640 recovered, attributed", shadow: "green" },
];

/** Beat B: the March draft you rewrote against the August one you approved. */
const FLOW_B: { side: "left" | "right"; eyebrow: string; body: string; shadow: string }[] = [
  {
    side: "left",
    eyebrow: "March · draft 1",
    body: "“Hi Isabella, we've missed you at the shop. Here's 10% off your next order.”",
    shadow: "ink",
  },
  {
    side: "left",
    eyebrow: "You, March",
    body: "Rewrote it. Cut the discount, mentioned the avocado toast.",
    shadow: "terra",
  },
  {
    side: "right",
    eyebrow: "August · draft 1",
    body: "“Isabella — the avocado toast is back on Thursdays. Saved you the corner table.”",
    shadow: "ink",
  },
  { side: "right", eyebrow: "You, August", body: "Approved. Sent as written.", shadow: "green" },
];

const SIGNALS: { source: string; when: string; body: string; trace: string }[] = [
  {
    source: "Square · till",
    when: "Mar 12",
    body: "Isabella Torres last visited 21 days ago. She used to come every three.",
    trace: "→ compiled into the page",
  },
  {
    source: "Spend · trailing 60 days",
    when: "Tue",
    body: "Average ticket down 34% in the two months before she stopped.",
    trace: "→ compiled into the page",
  },
  {
    source: "Basket history",
    when: "Last week",
    body: "Avocado toast and a flat white, eleven visits out of twelve.",
    trace: "→ compiled into the page",
  },
  {
    source: "Churnary · nightly run",
    when: "9:12 AM",
    body: "Re-scored overnight as new visits landed. Draft written, waiting on you.",
    trace: "→ compiled into the page",
  },
  {
    source: "You · approved 9:20 AM",
    when: "Thu",
    body: "Sent. Isabella came back Thursday.",
    trace: "← attributed back to the page",
  },
];

const FEATURES: [string, string][] = [
  [
    "Transparent scoring",
    "Every risk score shows its reasons — visit gap, spend drop, favourite item. Trust it today, not someday with more AI.",
  ],
  [
    "AI drafts, you approve",
    "Claude writes the win-back copy. Suggest, Approve and Autopilot modes keep a human in control; approve-to-send is the default.",
  ],
  [
    "Compliant by design",
    "CAN-SPAM unsubscribe on every email, TCPA quiet hours for SMS, and no medical data ever. Built in, not bolted on.",
  ],
  [
    "Works with your tools",
    "Square and Stripe connect live; CSV covers anything else. Adding a source never means redoing your setup.",
  ],
  [
    "Nightly re-scoring",
    "Every customer is re-scored automatically as new visits land. The dashboard is always this-morning fresh.",
  ],
  [
    "Attribution you can bank",
    "Recovered customers tie back to the exact message that brought them in: “3 customers recovered, ~$640 saved.”",
  ],
];

const STEPS: [string, string, string, string][] = [
  [
    "01",
    "Connect in 2 minutes",
    "Link Square or Stripe, or upload a customer CSV. If you can attach a file to an email, you can set up Churnary.",
    "Square · Stripe · CSV",
  ],
  [
    "02",
    "See who's slipping, and why",
    "Every customer gets a transparent risk score built from their own visit rhythm, with the reason in plain English.",
    "Re-scored nightly",
  ],
  [
    "03",
    "Approve the win-back",
    "Churnary drafts a personal email mentioning their favourite order. You tap approve, it sends, and recovered visits track back to it.",
    "Email today · SMS on Growth",
  ],
];

/** Legal copy. Verbatim in intent from the original page — do not rewrite. */
const GUARDRAILS: [string, string][] = [
  ["CAN-SPAM", "An unsubscribe link in every single email. Not a setting."],
  [
    "TCPA",
    "No SMS before 9am or after 8pm in the customer's own time zone. STOP is honoured instantly.",
  ],
  [
    "HIPAA",
    "No medical or treatment data ingested — only name, contact, visit times and spend.",
  ],
  [
    "Your data",
    "A per-business deletion endpoint, OAuth tokens encrypted at rest. Leaving is one request.",
  ],
];

interface Member {
  name: string;
  study: string;
  bio: string;
  email: string;
  linkedin: string;
  photo?: string;
  initials?: string;
  /** Faces sit high in the frame; nudge the crop so nobody is decapitated. */
  focus?: string;
}

const TEAM: Member[] = [
  {
    name: "Soham Dogra",
    study: "CS + Linguistics · San José State",
    bio: "An AI product builder working across strategy, engineering and growth, with experience developing AI infrastructure at Inference.ai.",
    email: "soham@churnary.ai",
    linkedin: "https://www.linkedin.com/in/soham-dogra-b110ab2ab/",
    photo: sohamPhoto,
    focus: "center 26%",
  },
  {
    name: "Riyan Anosh",
    study: "Computer Engineering · UC Merced",
    bio: "A hands-on builder with a soft spot for homelabs, hardware and turning ambitious AI ideas into working prototypes.",
    email: "riyan@churnary.ai",
    linkedin: "https://www.linkedin.com/in/riyan-anosh-0aba9434b/",
    photo: riyanPhoto,
  },
  {
    name: "Pranjal Mishra",
    study: "Aerospace + Mechanical · RPI",
    bio: "An engineer-in-training who pairs flight manufacturing experience with a background in software engineering and applied AI.",
    email: "pranjal@churnary.ai",
    linkedin: "https://www.linkedin.com/in/pranjal-mishra-b622252a6/",
    photo: pranjalPhoto,
    focus: "center 30%",
  },
  {
    name: "Aditya Kolekar",
    study: "Artificial Intelligence · UC San Diego",
    bio: "An AI builder and three-time hackathon winner focused on making complex technology feel clear, practical and useful.",
    email: "aditya@churnary.ai",
    linkedin: "https://www.linkedin.com/in/aditkolekar/",
    photo: adityaPhoto,
    focus: "center 26%",
  },
  {
    name: "Asim Siddiqui",
    study: "Data Science · San José State",
    bio: "The team's core marketer, pairing go-to-market instincts with hands-on experience building AI software.",
    email: "asim@churnary.ai",
    linkedin: "https://www.linkedin.com/in/asim-siddiqui-5b8385319/",
    photo: asimPhoto,
  },
];

/** Plan names and features only — the monthly figures were removed on purpose. */
const PLANS: { name: string; features: string[]; popular?: boolean }[] = [
  {
    name: "Starter",
    features: ["1 integration", "1,000 customers", "Email win-backs", "Transparent risk scores"],
  },
  {
    name: "Growth",
    features: [
      "All integrations",
      "2,500 customers",
      "Email + SMS",
      "Automation rules",
      "Recovery attribution",
    ],
    popular: true,
  },
  {
    name: "Pro",
    features: [
      "Unlimited customers",
      "Multi-location ready",
      "Everything in Growth",
      "Priority support",
    ],
  },
];

/* ── page ────────────────────────────────────────────────────────────────── */

export default function Landing() {
  const reduced = useReducedMotion();
  /** Below this the pinned scene has nowhere to pin — it becomes a plain list. */
  const narrow = useMediaQuery("(max-width: 1000px)");
  const staticScenes = reduced || narrow;

  useLandingMetrics();

  const rootRef = useRef<HTMLDivElement>(null);
  const els = useRef<{
    nav?: HTMLElement | null;
    flow?: HTMLElement | null;
    wiki?: HTMLElement | null;
    drifts: HTMLElement[];
    beats: HTMLElement[];
    hint?: HTMLElement | null;
    signals: HTMLElement[];
    lines: HTMLElement[];
    reveals: HTMLElement[];
    tilt?: HTMLElement | null;
    flowSvg?: SVGSVGElement | null;
    flowIcon?: HTMLElement | null;
    flowLines: SVGPathElement[];
  }>({ drifts: [], beats: [], signals: [], lines: [], reveals: [], flowLines: [] });
  /** Last stage size the flow-line geometry was measured at. */
  const flowSize = useRef("");

  /** Gather the nodes paint() drives. Re-run when the scene DOM swaps. */
  const collect = useCallback(() => {
    const r = rootRef.current;
    if (!r) return;
    const all = <T extends HTMLElement>(sel: string) =>
      Array.from(r.querySelectorAll<T>(sel));
    els.current = {
      nav: r.querySelector<HTMLElement>("[data-nav]"),
      flow: r.querySelector<HTMLElement>('[data-scene="flow"]'),
      wiki: r.querySelector<HTMLElement>('[data-scene="wiki"]'),
      drifts: all("[data-drift]"),
      beats: all("[data-beat]"),
      hint: r.querySelector<HTMLElement>("[data-hint]"),
      signals: all("[data-signal]"),
      lines: all("[data-line]"),
      reveals: all("[data-reveal]"),
      tilt: r.querySelector<HTMLElement>("[data-tilt]"),
      flowSvg: r.querySelector<SVGSVGElement>("[data-flow-lines]"),
      flowIcon: r.querySelector<HTMLElement>("[data-flow-icon]"),
      flowLines: Array.from(r.querySelectorAll<SVGPathElement>("[data-flow-line]")),
    };

    // The grain is an inline feTurbulence data URI applied from JS: a bundler
    // that sees url(#g) in a stylesheet tries to resolve the filter reference.
    const grain = r.querySelector<HTMLElement>("[data-grain]");
    if (grain && !grain.style.backgroundImage) {
      const hash = String.fromCharCode(35);
      const svg =
        "<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180'>" +
        "<filter id='g'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3'/></filter>" +
        `<rect width='180' height='180' filter='url(${hash}g)'/></svg>`;
      grain.style.backgroundImage = `url("data:image/svg+xml;utf8,${svg.replace(/#/g, "%23")}")`;
    }
  }, []);

  /**
   * Measure the flow-line geometry in stage-local pixels.
   *
   * Uses offsetLeft/offsetTop rather than getBoundingClientRect because those
   * ignore transforms — the cards are mid-drift for most of the scene, and
   * their rects would give wherever they happen to be rather than where they
   * come to rest. Called on mount and whenever the stage changes size, never
   * per frame; the dash travel itself is a CSS animation.
   */
  const layoutFlowLines = useCallback(() => {
    const { flowSvg, flowIcon, flowLines } = els.current;
    const stage = flowSvg?.parentElement;
    if (!flowSvg || !flowIcon || !stage || !flowLines.length) return;

    const w = stage.offsetWidth;
    const h = stage.offsetHeight;
    if (!w || !h) return;
    flowSvg.setAttribute("viewBox", `0 0 ${w} ${h}`);

    // The icon is centred on its offset position by translate(-50%, -50%), so
    // its offset point is its visual centre, not its top-left corner.
    const cx = flowIcon.offsetLeft;
    const cy = flowIcon.offsetTop;
    const edge = flowIcon.offsetWidth / 2;

    flowLines.forEach((path) => {
      const side = path.dataset.flowLine;
      const card = stage.querySelector<HTMLElement>(
        `[data-drift="${side}"][data-group="a"][data-i="${path.dataset.i}"]`
      );
      if (!card) return;
      const cardY = card.offsetTop + card.offsetHeight / 2;
      const from =
        side === "left"
          ? { x: card.offsetLeft + card.offsetWidth, y: cardY }
          : { x: cx + edge, y: cy };
      const to =
        side === "left" ? { x: cx - edge, y: cy } : { x: card.offsetLeft, y: cardY };
      path.setAttribute("d", flowPath(from, to));
    });
  }, []);

  /**
   * Pre-animation state, set from JS once the script is confirmed running.
   *
   * This is the reason the page degrades gracefully: with no JS, nothing is
   * hidden and the whole page reads as a static document. Moving any of these
   * into CSS would blank the page for anyone whose bundle failed to load.
   */
  const prime = useCallback(() => {
    const { reveals, drifts, lines, signals, beats } = els.current;
    if (reduced) return;
    reveals.forEach((el) => {
      el.style.transition =
        "opacity .8s cubic-bezier(.22,1,.36,1), transform .8s cubic-bezier(.22,1,.36,1)";
      el.style.opacity = "0";
      el.style.transform = "translateY(20px)";
    });
    lines.forEach((el) => {
      el.style.transition =
        "opacity .55s ease, transform .55s cubic-bezier(.22,1,.36,1), filter .55s ease";
      el.style.opacity = "0";
      el.style.transform = "translateY(8px)";
    });
    signals.forEach((el) => {
      el.style.transition = "opacity .45s ease, transform .45s ease";
    });
    if (staticScenes) return;
    drifts.forEach((el) => {
      el.style.willChange = "transform, opacity";
    });
    beats.forEach((el) => {
      el.style.transition = "opacity .5s ease, transform .6s cubic-bezier(.22,1,.36,1)";
    });
  }, [reduced, staticScenes]);

  /** One pass over every scroll-driven element on the page. */
  const paint = useCallback(() => {
    const { nav, flow, wiki, drifts, beats, hint, signals, lines, reveals, tilt, flowLines } =
      els.current;
    const vh = window.innerHeight;

    // 1. Nav — tightens and gains a shadow past 40px. The band stays ink.
    if (nav) {
      const on = window.scrollY > 40;
      nav.style.boxShadow = on ? "0 14px 34px -26px rgba(42,33,28,.85)" : "none";
      nav.dataset.tight = on ? "1" : "0";
    }

    if (reduced) return;

    // 2. Reveals.
    reveals.forEach((el) => {
      if (el.getBoundingClientRect().top < vh * 0.86) {
        el.style.opacity = "1";
        el.style.transform = "translateY(0)";
      }
    });

    // 3. Hero tilt — 7° to 0° as it enters.
    if (tilt) {
      const rect = tilt.getBoundingClientRect();
      const seen = clamp((vh - rect.top) / (vh * 0.9), 0, 1);
      tilt.style.transform =
        `perspective(1600px) rotateX(${((1 - seen) * 7).toFixed(2)}deg) ` +
        `scale(${(0.965 + seen * 0.035).toFixed(3)})`;
    }

    // 4. Pinned scene.
    if (flow) {
      const p = sceneProgress(flow.getBoundingClientRect().top, flow.offsetHeight, vh);
      const { pa, pb, visA, visB } = beatVisibility(p);
      const reach = driftReach(window.innerWidth);

      drifts.forEach((el) => {
        const side = el.dataset.drift === "left" ? -1 : 1;
        const group = el.dataset.group;
        const i = Number(el.dataset.i) || 0;
        const vis = group === "a" ? visA : visB;
        const d = driftState(group === "a" ? pa : pb, i, side, reach, vis);
        el.style.opacity = String(d.opacity);
        // Below 0.02 the card is invisible but would still take clicks and be
        // read out by a screen reader, so take it out of the page entirely.
        el.style.visibility = vis < 0.02 ? "hidden" : "visible";
        el.style.pointerEvents = vis > 0.5 ? "auto" : "none";
        el.style.transform =
          `translate3d(${d.x.toFixed(1)}px,${d.y.toFixed(1)}px,0) ` +
          `scale(${d.scale.toFixed(3)}) rotate(${d.rotate.toFixed(2)}deg)`;
      });

      beats.forEach((el) => {
        const isA = el.dataset.beat === "a";
        const vis = isA ? visA : visB;
        el.style.opacity = String(vis);
        el.style.visibility = vis < 0.02 ? "hidden" : "visible";
        el.style.transform = `translateY(${((isA ? -(1 - visA) : 1 - visB) * 26).toFixed(1)}px)`;
      });

      // Flow lines share beat A's easing, so a connector fades in as its own
      // card lands. Re-measure only when the stage has actually resized.
      const stage = flow.querySelector<HTMLElement>(".chn-flow-stage");
      if (stage && flowLines.length) {
        const size = `${stage.offsetWidth}x${stage.offsetHeight}`;
        if (size !== flowSize.current) {
          flowSize.current = size;
          layoutFlowLines();
        }
        flowLines.forEach((path) => {
          const side = path.dataset.flowLine === "left" ? -1 : 1;
          const i = Number(path.dataset.i) || 0;
          const { progress } = driftState(pa, i, side, reach, visA);
          path.style.opacity = String(flowLineOpacity(progress, visA));
        });
      }

      if (hint) hint.style.opacity = String(clamp(1 - (p - 0.86) / 0.12, 0, 1));
    }

    // 5. Signal feed — the card nearest the focus line drives the sticky panel.
    if (wiki && signals.length) {
      const focus = vh * SIGNAL_FOCUS;
      let active = 0;
      let best = Infinity;
      signals.forEach((el, i) => {
        const r = el.getBoundingClientRect();
        const d = Math.abs(r.top + r.height / 2 - focus);
        if (d < best) {
          best = d;
          active = i;
        }
      });
      // Only engage while the section straddles the viewport, so it resets
      // cleanly on both sides instead of freezing on the last active card.
      const r = wiki.getBoundingClientRect();
      const engaged = r.top < vh * 0.6 && r.bottom > vh * 0.4;
      signals.forEach((el, i) => {
        el.style.opacity = String(signalOpacity(i, active, engaged));
        el.style.transform = i === active && engaged ? "scale(1)" : "scale(.985)";
      });
      lines.forEach((el, i) => {
        const on = engaged && i <= active;
        el.style.opacity = on ? "1" : "0";
        el.style.transform = on ? "translateY(0)" : "translateY(8px)";
      });
    }
  }, [reduced, layoutFlowLines]);

  useEffect(() => {
    collect();
    prime();
    layoutFlowLines();
    paint();
  }, [collect, prime, layoutFlowLines, paint]);

  useRafScroll(paint);

  return (
    <div className="chn" ref={rootRef}>
      <style>{LP_CSS}</style>
      <div className="chn-grain" data-grain="1" aria-hidden="true" />

      <Nav />

      <main>
        <Hero />
        <Marquee reduced={reduced} />
        {staticScenes ? <FlowStatic /> : <FlowScene />}
        <Split />
        <Signals />
        <Demo />
        <Features />
        <HowItWorks />
        <Guardrails />
        <Team />
        <Pricing />
        <Waitlist />
      </main>

      <Footer />
    </div>
  );
}

/* ── nav ─────────────────────────────────────────────────────────────────── */

function Nav() {
  return (
    <header className="chn-nav" data-nav="1" data-tight="0">
      <a className="chn-nav-brand" href="#top">
        <img src={icon} alt="" aria-hidden="true" width={28} height={28} />
        Churnary
      </a>
      <nav className="chn-nav-links" aria-label="Sections">
        {NAV_LINKS.map(([href, label]) => (
          <a key={href} href={href}>
            {label}
          </a>
        ))}
      </nav>
      <div className="chn-nav-actions">
        <a className="chn-nav-signin" href="/login">
          Sign in
        </a>
        <a className="chn-nav-cta" href="#waitlist">
          Join the waitlist
        </a>
      </div>
    </header>
  );
}

/* ── hero ────────────────────────────────────────────────────────────────── */

function Hero() {
  return (
    <section className="chn-hero" id="top">
      <p className="chn-kicker">
        Your best regulars leave quietly, one skipped week at a time.
      </p>
      <h1 className="chn-h1">Catch them before they're gone.</h1>
      <p className="chn-hero-sub">
        Churnary reads your Square, Stripe or CSV data, flags the regulars slipping away
        with the reason in plain English, and drafts the win-back email. You tap approve.
      </p>
      <div className="chn-hero-cta">
        <a className="chn-btn chn-btn-solid" href="#waitlist">
          Join the waitlist
        </a>
        <a className="chn-btn chn-btn-ghost" href="#demo">
          Try the live demo
        </a>
      </div>

      <div className="chn-preview" data-tilt="1">
        <div className="chn-preview-bar">
          <div className="chn-preview-tabs">
            <span className="is-on">Today</span>
            <span>Customers</span>
            <span>Campaigns</span>
          </div>
          <span className="chn-eyebrow">Live</span>
        </div>
        <div className="chn-preview-stats">
          <div>
            <p className="chn-eyebrow">Revenue at risk</p>
            <p className="chn-figure chn-figure-risk">$5,806</p>
          </div>
          <div>
            <p className="chn-eyebrow">Days away</p>
            <p className="chn-figure">21</p>
          </div>
          <div>
            <p className="chn-eyebrow">Recovered</p>
            <p className="chn-figure">$640</p>
          </div>
        </div>
        <div className="chn-preview-list">
          <p className="chn-eyebrow chn-preview-list-head">Your #1 action today</p>
          {HERO_ROWS.map(([name, detail, band, tone]) => (
            <div className="chn-preview-row" key={name}>
              <span>{name}</span>
              <span className="chn-preview-detail">{detail}</span>
              <span className={`chn-preview-band is-${tone}`}>{band}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── marquee ─────────────────────────────────────────────────────────────── */

function Marquee({ reduced }: { reduced: boolean }) {
  const strip = (
    <span className="chn-marquee-strip">
      {TRADES.map((t) => (
        <span key={t}>
          <span>{t}</span>
          <span aria-hidden="true">·</span>
        </span>
      ))}
    </span>
  );
  return (
    <div className="chn-marquee">
      <div className="chn-marquee-track" data-still={reduced ? "1" : "0"} aria-hidden="true">
        {strip}
        {strip}
      </div>
      {/* The marquee is decorative; this is the text that actually gets read. */}
      <p className="chn-sr">
        Built for cafés, coffee shops, salons, barbershops, fitness studios, gyms, med
        spas, juice bars, bakeries and yoga studios.
      </p>
    </div>
  );
}

/* ── pinned scene ────────────────────────────────────────────────────────── */

function FlowCard({
  card,
  group,
  i,
}: {
  card: { side: "left" | "right"; eyebrow: string; body: string; shadow: string };
  group: "a" | "b";
  i: number;
}) {
  return (
    <div
      className={`chn-drift chn-drift-${card.side} is-${card.shadow} is-${group}${i}`}
      data-drift={card.side}
      data-group={group}
      data-i={i}
    >
      <p className={group === "a" ? "chn-eyebrow" : "chn-drift-meta"}>{card.eyebrow}</p>
      <p className="chn-drift-body">{card.body}</p>
    </div>
  );
}

function FlowScene() {
  return (
    <section className="chn-flow" id="flow" data-scene="flow">
      <div className="chn-flow-stage">
        <div className="chn-flow-heads">
          <div data-beat="a">
            <p className="chn-kicker chn-kicker-sm">Your data goes in.</p>
            <h2 className="chn-h2-big">A recovered regular comes out.</h2>
          </div>
          <div data-beat="b">
            <p className="chn-kicker chn-kicker-sm">Month one, you write the whole thing.</p>
            <h2 className="chn-h2-big">By month six, it writes it for you.</h2>
          </div>
        </div>

        {/* Dashed connectors: inputs flow into the icon, outputs flow out of
            it. Paths are computed in JS from measured layout, so with no
            script they simply never draw — they are decorative. */}
        <svg
          className="chn-flow-lines"
          data-flow-lines="1"
          aria-hidden="true"
          focusable="false"
          preserveAspectRatio="none"
        >
          {FLOW_A.map((card, n) => {
            const i = FLOW_A.slice(0, n).filter((c) => c.side === card.side).length;
            return (
              <path
                key={n}
                className={`is-${card.shadow}`}
                data-flow-line={card.side}
                data-i={i}
                style={{ animationDelay: `${i * 0.16}s` }}
              />
            );
          })}
        </svg>

        <img
          className="chn-flow-icon"
          data-flow-icon="1"
          src={icon}
          alt=""
          aria-hidden="true"
        />

        {(["a", "b"] as const).flatMap((group) => {
          const cards = group === "a" ? FLOW_A : FLOW_B;
          // data-i restarts per side: the stagger is within a column, and the
          // engine reads side and index independently.
          const perSide = { left: 0, right: 0 };
          return cards.map((card, n) => {
            const i = perSide[card.side]++;
            return <FlowCard key={`${group}${n}`} card={card} group={group} i={i} />;
          });
        })}

        <p className="chn-flow-hint" data-hint="1">
          Keep scrolling
        </p>
      </div>
    </section>
  );
}

/**
 * The pinned scene's fallback: same content, no sticky and no drift.
 *
 * Used below 1000px (nothing to pin against) and under prefers-reduced-motion
 * (both beats render as static blocks, per PORT-NOTES §6). Deliberately a
 * different DOM rather than a CSS override — a half-disabled sticky scene is
 * how you get a 340vh column of blank page.
 */
function FlowStatic() {
  return (
    <section className="chn-flow-static" id="flow">
      <div className="chn-flow-static-beat">
        <p className="chn-kicker chn-kicker-sm">Your data goes in.</p>
        <h2 className="chn-h2-big">A recovered regular comes out.</h2>
        <div className="chn-flow-static-cards">
          {FLOW_A.map((card, i) => (
            <div className={`chn-static-card is-${card.shadow}`} key={i}>
              <p className="chn-eyebrow">{card.eyebrow}</p>
              <p className="chn-drift-body">{card.body}</p>
            </div>
          ))}
        </div>
      </div>
      <div className="chn-flow-static-beat">
        <p className="chn-kicker chn-kicker-sm">Month one, you write the whole thing.</p>
        <h2 className="chn-h2-big">By month six, it writes it for you.</h2>
        <div className="chn-flow-static-cards">
          {FLOW_B.map((card, i) => (
            <div className={`chn-static-card is-${card.shadow}`} key={i}>
              <p className="chn-drift-meta">{card.eyebrow}</p>
              <p className="chn-drift-body">{card.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── who decides what ────────────────────────────────────────────────────── */

function Split() {
  return (
    <section className="chn-wrap chn-split-section">
      <div className="chn-split">
        <div data-reveal="1">
          <p className="chn-eyebrow">Churnary decides</p>
          <h3 className="chn-h3-serif">Who is drifting, and why</h3>
          <p className="chn-body">
            It scores every customer nightly against their own visit rhythm, ranks the
            ones worth a message, and writes a draft that mentions what they actually
            order.
          </p>
        </div>
        <div className="chn-split-you" data-reveal="1">
          <p className="chn-eyebrow is-accent">You decide</p>
          <h3 className="chn-h3-serif">Whether a word of it goes out</h3>
          <p className="chn-body">
            Nothing sends on its own. Read the draft, edit it or bin it, then approve.
            Autopilot exists, but you have to go and turn it on.
          </p>
        </div>
      </div>
      <dl className="chn-stats" data-reveal="1">
        <div>
          <dt>~$970</dt>
          <dd>what one saved regular is worth per year</dd>
        </div>
        <div>
          <dt>21 days</dt>
          <dd>
            typical gap before a café regular is gone for good — Churnary flags them at
            day 8
          </dd>
        </div>
        <div>
          <dt>2 min</dt>
          <dd>from CSV upload to your first risk list</dd>
        </div>
        <div>
          <dt>0</dt>
          <dd>emails sent without your approval</dd>
        </div>
      </dl>
    </section>
  );
}

/* ── signal feed ─────────────────────────────────────────────────────────── */

const PANEL_LINES = [
  <>
    Regular since 2023, in every three days.{" "}
    <span className="chn-panel-hot">Now 21 days out — 6.9× her usual gap.</span>
  </>,
  <>Spend fell 34% in the two months before she stopped.</>,
  <>Orders avocado toast and a flat white, almost every visit.</>,
  <>
    Risk <b>91 · Critical</b>. Draft mentions the avocado toast by name.
  </>,
  <>Recovered Thursday. ~$640 attributed to that one email.</>,
];

function Signals() {
  return (
    <section className="chn-signals" id="signals" data-scene="wiki">
      <div className="chn-wrap-wide">
        <h2 className="chn-h2">The customer page that writes itself</h2>
        <p className="chn-body chn-lede">
          Every signal from your own till builds one page. Churnary reads it before it
          writes a word.
        </p>

        <div className="chn-signals-grid">
          <div className="chn-signals-col">
            {SIGNALS.map((s, i) => (
              <div className="chn-signal" data-signal="1" data-i={i} key={i}>
                <div className="chn-signal-head">
                  <span>{s.source}</span>
                  <span>{s.when}</span>
                </div>
                <p className="chn-signal-body">{s.body}</p>
                <p className="chn-signal-trace">{s.trace}</p>
              </div>
            ))}
          </div>

          <div className="chn-panel-col">
            <div className="chn-panel">
              <p className="chn-panel-stamp">Updated just now</p>
              <div className="chn-panel-who">
                <span className="chn-panel-avatar" aria-hidden="true">
                  IT
                </span>
                <p>Isabella Torres</p>
              </div>
              <div className="chn-panel-lines">
                {PANEL_LINES.map((line, i) => (
                  <p data-line="1" data-i={i} key={i} className={i === 4 ? "is-last" : ""}>
                    {line}
                  </p>
                ))}
              </div>
            </div>
            <p className="chn-panel-note">
              Every line traces back to the till receipt that produced it. Reasons are a
              feature, not a debug view.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── live demo ───────────────────────────────────────────────────────────── */

function Demo() {
  const [vertical, setVertical] = useState<VerticalKey>("cafe");
  const [days, setDays] = useState(12);

  const v = VERTICALS[vertical];
  const score = riskScore(days, v.base);
  const band = riskBand(score);
  const ratio = days / v.base;
  const quote = useMemo(() => bandQuote(band.label, days, ratio), [band.label, days, ratio]);

  const pick = (key: VerticalKey) => () => {
    setVertical(key);
    // Clamping keeps the slider honest: 180 days is a lapsed salon client but
    // off the end of the café scale.
    setDays((d) => Math.min(d, VERTICALS[key].max));
  };

  return (
    <section className="chn-wrap chn-demo-section" id="demo">
      <h2 className="chn-h2">The whole product, in one slider</h2>
      <p className="chn-body chn-lede">
        Drag it. Churnary scores risk from each customer's own rhythm, then says why in a
        sentence you could read aloud to them.
      </p>

      <div className="chn-demo">
        <div>
          <p className="chn-demo-label">A regular at your</p>
          <div className="chn-tabs" role="tablist">
            {(Object.keys(VERTICALS) as VerticalKey[]).map((key) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={vertical === key}
                className="chn-tab"
                data-on={vertical === key ? "1" : "0"}
                onClick={pick(key)}
              >
                {VERTICALS[key].label}
              </button>
            ))}
          </div>
          <p className="chn-demo-interval">usually visits every {v.interval}</p>
          <label className="chn-demo-slider-label" htmlFor="chn-days">
            Days since last visit — {days}
          </label>
          <input
            id="chn-days"
            className="chn-range"
            type="range"
            min={1}
            max={v.max}
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          />
          <div className="chn-demo-ends">
            <span>just visited</span>
            <span>long gone</span>
          </div>
        </div>

        <div className="chn-dial-row">
          <div className="chn-dial">
            <svg viewBox="0 0 100 100" width="112" height="112" aria-hidden="true">
              <circle
                cx="50"
                cy="50"
                r={DIAL_RADIUS}
                fill="none"
                stroke="var(--line-soft)"
                strokeWidth="6"
              />
              <circle
                cx="50"
                cy="50"
                r={DIAL_RADIUS}
                fill="none"
                stroke={band.color}
                strokeWidth="6"
                strokeLinecap="round"
                strokeDasharray={dialDash(score)}
                transform="rotate(-90 50 50)"
              />
            </svg>
            <div className="chn-dial-face">
              <span className="chn-dial-num" style={{ color: band.color }}>
                {score}
              </span>
              <span className="chn-dial-unit">risk</span>
            </div>
          </div>
          <div>
            {/* aria-live: the dial is decorative, so the band change has to be
                announced somewhere or a screen-reader user gets nothing. */}
            <p className="chn-dial-band" style={{ color: band.color }} aria-live="polite">
              {band.label} · risk {score}
            </p>
            <p className="chn-dial-quote">{quote}</p>
            <p className="chn-dial-action">{bandAction(band.label)}</p>
          </div>
        </div>
      </div>

      <div className="chn-trio">
        <div data-reveal="1">
          <h3 className="chn-h3-sm">Per vertical</h3>
          <p className="chn-body-sm">
            A med-spa client returning in five months is normal. A gym member gone three
            weeks is not. Thresholds differ by trade.
          </p>
        </div>
        <div data-reveal="1">
          <h3 className="chn-h3-sm">No black box</h3>
          <p className="chn-body-sm">
            A transparent weighted heuristic, not a model you have to trust. The same
            maths runs in the product.
          </p>
        </div>
        <div data-reveal="1">
          <h3 className="chn-h3-sm">Reasons first</h3>
          <p className="chn-body-sm">
            The sentence beside the dial is the real output shape. Every score shows its
            reasons.
          </p>
        </div>
      </div>
    </section>
  );
}

/* ── features ────────────────────────────────────────────────────────────── */

function Features() {
  return (
    <section className="chn-band" id="features">
      <div className="chn-wrap-inner">
        <div className="chn-head-pair">
          <h2 className="chn-h2">Automation you can hand the keys to</h2>
          <p className="chn-body">
            Churnary is aimed at people who run a counter, not a marketing team.
            Everything below is already shipped or a hard guarantee in how it's built.
          </p>
        </div>
        <div className="chn-feature-grid">
          {FEATURES.map(([title, body]) => (
            <div className="chn-feature" data-reveal="1" key={title}>
              <h3 className="chn-h3-xs">{title}</h3>
              <p className="chn-body-sm">{body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── how it works ────────────────────────────────────────────────────────── */

function HowItWorks() {
  return (
    <section className="chn-wrap chn-how" id="how">
      <h2 className="chn-h2 chn-how-head">
        Built for people who run a counter, not a CRM
      </h2>
      <ol className="chn-steps">
        {STEPS.map(([n, title, body, meta]) => (
          <li data-reveal="1" key={n}>
            <span className="chn-step-n">{n}</span>
            <h3 className="chn-h3-step">{title}</h3>
            <p className="chn-body-sm">{body}</p>
            <span className="chn-step-meta">{meta}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

/* ── guardrails (legal copy) ─────────────────────────────────────────────── */

function Guardrails() {
  return (
    <section className="chn-dark">
      <div className="chn-wrap-inner">
        <div className="chn-head-pair">
          <h2 className="chn-h2">The parts we won't let you switch off</h2>
          <p className="chn-body-dark">
            Outreach automation goes wrong in expensive, legally interesting ways. These
            sit below the settings screen, so no configuration can turn them off.
          </p>
        </div>
        <dl className="chn-guardrails">
          {GUARDRAILS.map(([term, def]) => (
            <div data-reveal="1" key={term}>
              <dt>{term}</dt>
              <dd>{def}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}

/* ── team ────────────────────────────────────────────────────────────────── */

function Team() {
  return (
    <section className="chn-wrap chn-team-section" id="team">
      <div className="chn-head-pair">
        <h2 className="chn-h2">Old friends, one shared obsession</h2>
        <p className="chn-body">
          We met at American High School in Fremont, California, and kept building
          together. Churnary brings our backgrounds in AI, product, marketing, computer
          engineering and aerospace systems to one goal: help local businesses keep the customers they
          worked hard to earn.
        </p>
      </div>
      <div className="chn-team">
        {TEAM.map((m) => (
          <article data-reveal="1" key={m.name}>
            <div className="chn-team-frame">
              {m.photo ? (
                <img
                  src={m.photo}
                  alt={m.name}
                  loading="lazy"
                  style={{ objectPosition: m.focus }}
                />
              ) : (
                <span className="chn-team-initials">{m.initials}</span>
              )}
            </div>
            <h3 className="chn-h3-xs">{m.name}</h3>
            <p className="chn-team-study">{m.study}</p>
            <p className="chn-team-bio">{m.bio}</p>
            <div className="chn-team-links">
              <a href={`mailto:${m.email}`}>Email</a>
              <a href={m.linkedin} target="_blank" rel="noreferrer noopener">
                LinkedIn
              </a>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

/* ── pricing ─────────────────────────────────────────────────────────────── */

function Pricing() {
  return (
    <section className="chn-band" id="pricing">
      <div className="chn-wrap-inner">
        <div className="chn-head-pair">
          <h2 className="chn-h2">Pays for itself on the first save</h2>
          <p className="chn-body">
            A saved regular is worth roughly $970 a year. Save three and any plan has paid
            for itself. 14-day trial on every tier; annual billing is two months free.
          </p>
        </div>
        <div className="chn-plans">
          {PLANS.map((plan) => (
            <div
              className={`chn-plan${plan.popular ? " is-popular" : ""}`}
              data-reveal="1"
              key={plan.name}
            >
              <div className="chn-plan-head">
                <h3 className="chn-h3-xs">{plan.name}</h3>
                {plan.popular && <span className="chn-plan-tag">Most popular</span>}
              </div>
              <ul className="chn-plan-features">
                {plan.features.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
              <a className="chn-plan-cta" href="#waitlist">
                Join the waitlist
              </a>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── waitlist ────────────────────────────────────────────────────────────── */

function Waitlist() {
  return (
    <section className="chn-waitlist" id="waitlist">
      <p className="chn-kicker">Early access</p>
      <h2 className="chn-h2-big chn-waitlist-head">Tell us where to reach you.</h2>
      <p className="chn-body chn-waitlist-sub">
        We're onboarding local businesses a handful at a time so each one gets set up
        properly. We'll import your data with you on the first call.
      </p>
      <div className="chn-waitlist-form">
        <WaitlistForm />
      </div>
    </section>
  );
}

/* ── footer ──────────────────────────────────────────────────────────────── */

function Footer() {
  return (
    <footer className="chn-footer">
      <div className="chn-footer-inner">
        <span className="chn-footer-brand">
          <img src={icon} alt="" aria-hidden="true" width={26} height={26} />
          Churnary — AI retention for local business
        </span>
        <div className="chn-footer-links">
          <a href="#demo">Demo</a>
          <a href="#pricing">Pricing</a>
          <a href="#waitlist">Waitlist</a>
          <a href="/privacy">Privacy</a>
          <a href="mailto:soham@churnary.ai">soham@churnary.ai</a>
        </div>
      </div>
    </footer>
  );
}

/* ── styles ──────────────────────────────────────────────────────────────── */

/**
 * Page-scoped stylesheet, kept in the component so the standalone design-review
 * export (npm run preview:export) stays a single file. Every colour is a token
 * from index.css; there are no literal hex values here.
 */
const LP_CSS = `
.chn {
  --font-display: var(--font-serif);
  position: relative;
  background: var(--cream);
  color: var(--ink);
  font-family: var(--font-grotesk);
  -webkit-font-smoothing: antialiased;
  text-wrap: pretty;
  overflow-x: clip;
}
/* :where() keeps this at (0,1,0) so it cannot outrank the single-class link
   rules below. Written as ".chn a" it was (0,1,1) and silently repainted
   .chn-nav-signin, .chn-nav-brand and .chn-btn-solid to ink-on-ink. */
.chn :where(a) { color: var(--ink); text-decoration: none; }
.chn :where(a):hover { color: var(--terracotta); }
.chn ::placeholder { color: var(--faint); }
.chn input, .chn button, .chn select { font: inherit; color: inherit; }
.chn :focus-visible { outline: 1.5px solid var(--terracotta); outline-offset: 3px; }
.chn p, .chn h1, .chn h2, .chn h3, .chn dl, .chn dd, .chn ol, .chn ul { margin: 0; }

.chn-sr {
  position: absolute; width: 1px; height: 1px;
  overflow: hidden; clip-path: inset(50%);
}

.chn-grain {
  position: fixed; inset: 0; z-index: 100; pointer-events: none;
  opacity: .045; mix-blend-mode: multiply;
}

/* ── nav: its own dark band, never a transparent overlay ─────────────── */
.chn-nav {
  position: fixed; top: 0; left: 0; right: 0; z-index: 60;
  display: grid; grid-template-columns: 1fr auto 1fr;
  align-items: center; gap: 24px;
  padding: 10px 34px; background: var(--ink);
  transition: box-shadow .4s ease, padding .4s ease;
}
.chn-nav[data-tight="1"] { padding: 6px 34px; }
.chn-nav-brand {
  display: flex; align-items: center; gap: 10px; justify-self: start;
  font-size: 17px; font-weight: 500; letter-spacing: -.01em;
  color: var(--cream);
}
/* The 512² icon has square white corners; 23% clips them to the mark. */
.chn-nav-brand img, .chn-footer-brand img, /* Dashed connectors from the input cards into the icon, and out of it to the
   output cards. Each path is drawn in its direction of travel, so one keyframe
   moves every dash the right way. The dasharray period (5+11) matches the
   dashoffset travel exactly, or the loop would visibly jump. */
.chn-flow-lines {
  position: absolute; inset: 0; width: 100%; height: 100%;
  pointer-events: none; overflow: visible;
}
.chn-flow-lines path {
  fill: none;
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-dasharray: 5 11;
  animation: chn-flow-dash 1.1s linear infinite;
}
.chn-flow-lines .is-ink { stroke: var(--ink); }
.chn-flow-lines .is-terra { stroke: var(--terracotta); }
.chn-flow-lines .is-green { stroke: var(--green); }
@keyframes chn-flow-dash { from { stroke-dashoffset: 0; } to { stroke-dashoffset: -16; } }

.chn-flow-icon { border-radius: 23%; display: block; }
.chn-nav-brand:hover { color: var(--cream); }
.chn-nav-links { display: flex; gap: 30px; font-size: 14px; }
.chn-nav-links a { color: color-mix(in srgb, var(--cream) 62%, transparent); }
.chn-nav-links a:hover { color: var(--cream); }
.chn-nav-actions { display: flex; align-items: center; justify-content: flex-end; gap: 20px; }
/* Sign in is an action, so it sits at full cream rather than the 62% used for
   section links. Terracotta is the page accent but it is too dark to read on
   the ink band, so the hover uses terracotta-lt, the on-dark accent. */
.chn-nav-signin { font-size: 14px; font-weight: 500; color: var(--cream); }
.chn-nav-signin:hover { color: var(--terracotta-lt); }
.chn-nav-cta {
  padding: 9px 17px; border-radius: 999px;
  background: var(--cream); color: var(--ink); font-size: 14px;
}
.chn-nav-cta:hover { background: var(--terracotta); color: var(--hard-card); }

/* ── shared type ─────────────────────────────────────────────────────── */
.chn-kicker {
  font-family: var(--font-serif); font-style: italic; font-weight: 300;
  font-size: clamp(17px, 1.6vw, 22px); color: var(--muted-body);
}
.chn-kicker-sm { font-size: clamp(16px, 1.5vw, 21px); }
.chn-h1 {
  max-width: 15em; font-size: clamp(46px, 6.4vw, 96px); font-weight: 500;
  line-height: .98; letter-spacing: -.035em;
}
.chn-h2 {
  font-family: var(--font-serif); font-weight: 400;
  font-size: clamp(32px, 3.4vw, 46px); line-height: 1.1; letter-spacing: -.02em;
}
.chn-h2-big {
  margin: 0 auto; max-width: 14em; font-size: clamp(38px, 5vw, 74px);
  font-weight: 500; line-height: 1; letter-spacing: -.035em;
}
.chn-h3-serif {
  margin: 0 0 14px; font-family: var(--font-serif); font-weight: 400;
  font-size: 30px; letter-spacing: -.015em;
}
.chn-h3-step { margin: 14px 0 10px; font-family: var(--font-serif); font-weight: 400; font-size: 24px; }
.chn-h3-sm { margin: 0 0 8px; font-size: 15px; font-weight: 500; }
.chn-h3-xs { font-size: 17px; font-weight: 500; }
.chn-eyebrow {
  font-size: 11px; letter-spacing: .13em; text-transform: uppercase; color: var(--faint);
}
.chn-eyebrow.is-accent { color: var(--terracotta); }
.chn-body { font-size: 16px; line-height: 1.65; color: var(--muted-body); }
.chn-body-sm { font-size: 15px; line-height: 1.6; color: var(--muted-body); }
.chn-body-dark { font-size: 16px; line-height: 1.65; color: color-mix(in srgb, var(--cream) 60%, transparent); }
.chn-lede { margin-top: 16px; max-width: 32em; }
.chn-figure { font-size: 28px; font-weight: 500; letter-spacing: -.02em; }
.chn-figure-risk { color: var(--terracotta); }

.chn-wrap { max-width: 1120px; margin: 0 auto; padding: 120px 40px; }
.chn-wrap-inner { max-width: 1120px; margin: 0 auto; padding: 0 40px; }
.chn-wrap-wide { max-width: 1180px; margin: 0 auto; padding: 0 40px; }
.chn-band { background: var(--cream-alt); padding: 120px 0; }
.chn-dark { background: var(--ink); color: var(--cream); padding: 110px 0; }
.chn-head-pair {
  display: grid; grid-template-columns: 1.05fr .95fr; gap: 70px; align-items: end;
}

.chn-btn { padding: 14px 24px; border-radius: 999px; font-size: 15px; }
.chn-btn-solid { background: var(--ink); color: var(--cream); }
.chn-btn-solid:hover { background: var(--terracotta); color: var(--hard-card); }
.chn-btn-ghost { border: 1px solid var(--line); }
.chn-btn-ghost:hover { border-color: var(--ink); color: var(--ink); }

/* ── hero ────────────────────────────────────────────────────────────── */
.chn-hero {
  min-height: 100vh; display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 150px 32px 60px; text-align: center;
}
.chn-hero .chn-kicker { margin-bottom: 18px; }
.chn-hero-sub { margin-top: 30px; max-width: 34em; font-size: 17px; line-height: 1.6; color: var(--muted-body); }
.chn-hero-cta { display: flex; flex-wrap: wrap; justify-content: center; gap: 12px; margin-top: 34px; }

.chn-preview {
  width: 100%; max-width: 940px; margin-top: 76px; text-align: left;
  border-radius: 14px; background: var(--card);
  box-shadow: 0 40px 80px -56px color-mix(in srgb, var(--ink) 50%, transparent);
  overflow: hidden;
}
.chn-preview-bar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 13px 20px; border-bottom: 1px solid var(--line-soft);
}
.chn-preview-tabs { display: flex; gap: 20px; font-size: 13px; color: var(--faint); }
.chn-preview-tabs .is-on { color: var(--ink); }
.chn-preview-stats { display: grid; grid-template-columns: repeat(3, 1fr); }
.chn-preview-stats > div { padding: 22px 24px; border-right: 1px solid var(--line-soft); }
.chn-preview-stats > div:last-child { border-right: 0; }
.chn-preview-stats .chn-figure { margin-top: 9px; }
.chn-preview-list { display: grid; gap: 2px; padding: 20px 24px 26px; border-top: 1px solid var(--line-soft); }
.chn-preview-list-head { margin-bottom: 14px; }
.chn-preview-row {
  display: grid; grid-template-columns: 1fr auto auto; align-items: center;
  gap: 16px; padding: 13px 0; border-bottom: 1px solid var(--line-soft); font-size: 15px;
}
.chn-preview-row:last-child { border-bottom: 0; }
.chn-preview-detail { font-size: 13px; color: var(--muted-body); }
.chn-preview-band { min-width: 86px; text-align: right; font-size: 13px; }
.chn-preview-band.is-crit { color: var(--terracotta); }
.chn-preview-band.is-warm { color: var(--muted-body); }
.chn-preview-band.is-calm { color: var(--faint); }

/* ── marquee ─────────────────────────────────────────────────────────── */
.chn-marquee { overflow: hidden; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.chn-marquee-track {
  display: flex; width: max-content;
  animation: chn-marquee 52s linear infinite;
  font-family: var(--font-serif); font-size: 16px; color: var(--faint);
}
.chn-marquee-track[data-still="1"] { animation: none; }
.chn-marquee-strip { display: flex; gap: 26px; padding: 15px 13px; }
.chn-marquee-strip > span { display: flex; gap: 26px; }
@keyframes chn-marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }

/* ── pinned scene ────────────────────────────────────────────────────── */
.chn-flow { position: relative; height: 340vh; }
.chn-flow-stage { position: sticky; top: 0; height: 100vh; overflow: hidden; }
.chn-flow-heads { position: absolute; top: 15vh; left: 0; right: 0; text-align: center; padding: 0 32px; }
.chn-flow-heads > div { position: absolute; left: 0; right: 0; padding: 0 32px; }
.chn-flow-heads .chn-kicker { margin-bottom: 10px; }
.chn-flow-icon {
  position: absolute; left: 50%; top: 56%; transform: translate(-50%, -50%);
  width: 62px; height: 62px;
  box-shadow: 0 18px 34px -20px color-mix(in srgb, var(--ink) 70%, transparent);
}
.chn-drift {
  position: absolute; padding: 15px 18px; background: var(--hard-card);
}
.chn-drift-left { left: 5vw; width: 262px; }
.chn-drift-right { right: 5vw; width: 288px; }
.chn-drift.is-ink { box-shadow: 9px 9px 0 var(--ink); }
.chn-drift.is-terra { box-shadow: 9px 9px 0 var(--terracotta); }
.chn-drift.is-green { box-shadow: 9px 9px 0 var(--green); }
/* Rotations are the no-JS resting state; paint() overwrites transform wholesale. */
.chn-drift.is-a0 { transform: rotate(-1.4deg); }
.chn-drift.is-a1 { transform: rotate(.9deg); }
.chn-drift.is-a2 { transform: rotate(-.6deg); }
.chn-drift.is-b0 { transform: rotate(-1deg); }
.chn-drift.is-b1 { transform: rotate(.8deg); }
.chn-drift-left.is-a0 { top: 36%; }
.chn-drift-left.is-a1 { top: 54%; }
.chn-drift-left.is-a2 { top: 72%; }
.chn-drift-right.is-a0 { top: 36%; }
.chn-drift-right.is-a1 { top: 54%; }
.chn-drift-right.is-a2 { top: 72%; }
.chn-drift[data-group="b"] { width: 300px; padding: 16px 18px; }
.chn-drift[data-group="b"].is-b0 { top: 38%; }
.chn-drift[data-group="b"].is-b1 { top: 62%; }
.chn-drift .chn-eyebrow { margin-bottom: 4px; font-size: 10.5px; letter-spacing: .16em; }
.chn-drift-meta { margin-bottom: 7px; font-size: 12.5px; color: var(--faint); }
.chn-drift-body { font-size: 16px; }
.chn-drift[data-group="b"] .chn-drift-body { font-size: 15px; line-height: 1.5; }
.chn-flow-hint {
  position: absolute; left: 0; right: 0; bottom: 5vh; text-align: center;
  font-size: 11px; letter-spacing: .28em; text-transform: uppercase; color: var(--faint);
}

/* pinned-scene fallback */
.chn-flow-static { max-width: 1120px; margin: 0 auto; padding: 100px 40px; display: grid; gap: 90px; }
.chn-flow-static-beat { text-align: center; }
.chn-flow-static-beat .chn-kicker { margin-bottom: 10px; }
.chn-flow-static-cards {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 26px; margin-top: 44px; text-align: left;
}
.chn-static-card { padding: 16px 18px; background: var(--hard-card); }
.chn-static-card.is-ink { box-shadow: 6px 6px 0 var(--ink); }
.chn-static-card.is-terra { box-shadow: 6px 6px 0 var(--terracotta); }
.chn-static-card.is-green { box-shadow: 6px 6px 0 var(--green); }
.chn-static-card .chn-eyebrow { margin-bottom: 4px; font-size: 10.5px; letter-spacing: .16em; }

/* ── who decides ─────────────────────────────────────────────────────── */
.chn-split { display: grid; grid-template-columns: 1fr 1fr; gap: 80px; }
.chn-split .chn-eyebrow { margin-bottom: 12px; letter-spacing: .16em; }
.chn-split-you { padding-left: 34px; border-left: 1px solid var(--terracotta); }
.chn-stats {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 40px;
  margin-top: 100px; padding-top: 34px; border-top: 1px solid var(--line);
}
.chn-stats dt { font-size: 34px; font-weight: 500; letter-spacing: -.03em; }
.chn-stats dd { margin-top: 10px; font-size: 14px; line-height: 1.55; color: var(--muted-body); }

/* ── signal feed ─────────────────────────────────────────────────────── */
.chn-signals { background: var(--cream-alt); padding: 120px 0 140px; }
.chn-signals-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 70px;
  margin-top: 70px; align-items: start;
}
.chn-signals-col { display: grid; gap: 34px; padding-bottom: 30vh; }
.chn-signal {
  padding: 20px 22px; border-radius: 16px; background: var(--card);
  box-shadow: 0 20px 44px -34px color-mix(in srgb, var(--ink) 55%, transparent);
}
.chn-signal-head {
  display: flex; justify-content: space-between; gap: 16px;
  font-size: 13px; color: var(--muted-body);
}
.chn-signal-head span:first-child { font-weight: 500; color: var(--ink); }
.chn-signal-body { margin: 9px 0 12px; font-size: 15.5px; line-height: 1.5; }
.chn-signal-trace { font-size: 13px; color: var(--faint); }
.chn-panel-col { position: sticky; top: 24vh; }
.chn-panel {
  padding: 30px 32px 34px; border-radius: 20px; background: var(--card);
  box-shadow: 0 34px 70px -46px color-mix(in srgb, var(--ink) 60%, transparent);
}
.chn-panel-stamp { margin-bottom: 20px; font-size: 13px; color: var(--faint); }
.chn-panel-who { display: flex; align-items: center; gap: 12px; }
.chn-panel-who p { font-size: 19px; font-weight: 500; }
.chn-panel-avatar {
  width: 32px; height: 32px; border-radius: 50%; background: var(--line-soft);
  display: grid; place-items: center;
  font-family: var(--font-serif); font-size: 14px; color: var(--muted-body);
}
.chn-panel-lines { display: grid; gap: 14px; margin-top: 22px; font-size: 15.5px; line-height: 1.55; }
.chn-panel-lines b { font-weight: 500; }
.chn-panel-hot { color: var(--terracotta); }
.chn-panel-lines .is-last {
  padding-top: 14px; border-top: 1px solid var(--line); color: var(--green);
}
.chn-panel-note { margin: 18px 6px 0; font-size: 13.5px; line-height: 1.55; color: var(--faint); }

/* ── demo ────────────────────────────────────────────────────────────── */
.chn-demo-section { padding: 130px 40px; }
.chn-demo {
  display: grid; grid-template-columns: 1fr 1fr; gap: 70px; align-items: center;
  margin-top: 56px; padding: 40px 44px; border-radius: 20px; background: var(--card);
  box-shadow: 0 34px 70px -52px color-mix(in srgb, var(--ink) 55%, transparent);
}
.chn-demo-label { margin-bottom: 12px; font-size: 13px; color: var(--faint); }
.chn-tabs { display: flex; gap: 8px; }
.chn-tab {
  padding: 9px 16px; border-radius: 999px; cursor: pointer;
  border: 1px solid var(--line); background: transparent;
  color: var(--muted-body); font-size: 14px;
}
.chn-tab[data-on="1"] { border-color: var(--ink); background: var(--ink); color: var(--cream); }
.chn-demo-interval { margin-top: 26px; font-size: 14px; color: var(--muted-body); }
.chn-demo-slider-label { display: block; margin: 26px 0 14px; font-size: 14px; color: var(--muted-body); }
.chn-demo-ends {
  display: flex; justify-content: space-between; margin-top: 10px;
  font-size: 12.5px; color: var(--faint);
}
.chn-range { -webkit-appearance: none; appearance: none; background: transparent; width: 100%; }
.chn-range::-webkit-slider-runnable-track { height: 2px; background: var(--line); }
.chn-range::-webkit-slider-thumb {
  -webkit-appearance: none; width: 18px; height: 18px; margin-top: -8px;
  border-radius: 50%; background: var(--ink); cursor: grab;
}
.chn-range::-moz-range-track { height: 2px; background: var(--line); }
.chn-range::-moz-range-thumb { width: 16px; height: 16px; border: 0; border-radius: 50%; background: var(--ink); }
.chn-dial-row { display: flex; align-items: center; gap: 26px; }
.chn-dial { position: relative; flex: 0 0 auto; }
.chn-dial-face { position: absolute; inset: 0; display: grid; place-content: center; text-align: center; }
.chn-dial-num { font-size: 28px; font-weight: 500; letter-spacing: -.02em; }
.chn-dial-unit { font-size: 10px; letter-spacing: .18em; text-transform: uppercase; color: var(--faint); }
.chn-dial-band { font-size: 11px; letter-spacing: .16em; text-transform: uppercase; }
.chn-dial-quote { margin: 12px 0 8px; font-family: var(--font-serif); font-size: 19px; line-height: 1.45; }
.chn-dial-action { font-size: 14px; color: var(--muted-body); }
.chn-trio { display: grid; grid-template-columns: repeat(3, 1fr); gap: 44px; margin-top: 48px; }
.chn-trio .chn-body-sm { font-size: 14.5px; }

/* ── features ────────────────────────────────────────────────────────── */
/* 1px gaps on a --line ground: the rules between cards are the background. */
.chn-feature-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px;
  margin-top: 70px; background: var(--line);
}
.chn-feature { padding: 32px 30px 38px; background: var(--cream-alt); }
.chn-feature .chn-h3-xs { margin-bottom: 10px; }

/* ── how it works ────────────────────────────────────────────────────── */
.chn-how { padding: 130px 40px; }
.chn-how-head { margin-bottom: 70px; max-width: 15em; }
.chn-steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 50px; list-style: none; padding: 0; }
.chn-steps li { padding-top: 22px; border-top: 1px solid var(--line); }
.chn-step-n { font-size: 13px; color: var(--terracotta); }
.chn-steps .chn-body-sm { margin-bottom: 16px; font-size: 15.5px; }
.chn-step-meta { font-size: 13px; color: var(--faint); }

/* ── guardrails ──────────────────────────────────────────────────────── */
.chn-guardrails { display: grid; grid-template-columns: repeat(4, 1fr); gap: 44px; margin-top: 70px; }
.chn-guardrails dt { font-size: 17px; font-weight: 500; }
.chn-guardrails dd {
  margin-top: 12px; font-size: 14.5px; line-height: 1.6;
  color: color-mix(in srgb, var(--cream) 58%, transparent);
}

/* ── team ────────────────────────────────────────────────────────────── */
.chn-team-section { padding: 130px 40px; }
.chn-team { display: grid; grid-template-columns: repeat(5, 1fr); gap: 30px; margin-top: 70px; }
.chn-team-frame {
  aspect-ratio: 4 / 5; border-radius: 14px; overflow: hidden;
  background: var(--cream-alt); display: grid; place-items: center;
}
.chn-team-frame img { width: 100%; height: 100%; object-fit: cover; }
.chn-team-initials { font-family: var(--font-serif); font-size: 34px; color: color-mix(in srgb, var(--faint) 82%, var(--cream)); }
.chn-team .chn-h3-xs { margin: 18px 0 3px; }
.chn-team-study { margin-bottom: 12px; font-size: 13px; color: var(--faint); }
.chn-team-bio { margin-bottom: 14px; font-size: 14px; line-height: 1.55; color: var(--muted-body); }
.chn-team-links { display: flex; gap: 16px; font-size: 13px; }
.chn-team-links a { color: var(--terracotta); }

/* ── pricing ─────────────────────────────────────────────────────────── */
.chn-plans { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-top: 66px; }
.chn-plan {
  display: flex; flex-direction: column; gap: 20px;
  padding: 32px 30px; border-radius: 18px; background: var(--card);
}
.chn-plan.is-popular { background: var(--ink); color: var(--cream); }
.chn-plan-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.chn-plan-tag { font-size: 11px; letter-spacing: .14em; text-transform: uppercase; color: var(--terracotta-lt); }
.chn-plan-features { display: grid; gap: 10px; list-style: none; padding: 0; font-size: 14.5px; color: var(--muted-body); }
.chn-plan.is-popular .chn-plan-features { color: color-mix(in srgb, var(--cream) 72%, transparent); }
.chn-plan-cta {
  margin-top: auto; padding: 12px 20px; border-radius: 999px;
  border: 1px solid var(--line); text-align: center; font-size: 14.5px;
}
.chn-plan-cta:hover { border-color: var(--ink); color: var(--ink); }
.chn-plan.is-popular .chn-plan-cta { border-color: transparent; background: var(--cream); color: var(--ink); }
.chn-plan.is-popular .chn-plan-cta:hover { background: var(--terracotta-lt); }

/* ── waitlist ────────────────────────────────────────────────────────── */
.chn-waitlist { max-width: 1120px; margin: 0 auto; padding: 140px 40px 120px; text-align: center; }
.chn-waitlist .chn-kicker { margin-bottom: 16px; }
.chn-waitlist-head { max-width: 13em; font-size: clamp(36px, 4.6vw, 64px); line-height: 1.02; }
.chn-waitlist-sub { margin: 24px auto 0; max-width: 34em; }
.chn-waitlist-form { max-width: 620px; margin: 36px auto 0; text-align: left; }

/* The shared WaitlistForm, reskinned for a cream surface — it ships styled
   for the old page's dark band. Markup and logic are untouched. */
.chn .lp-wl-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.chn .lp-wl-field { display: grid; gap: 7px; }
.chn .lp-wl-label { font-size: 12px; letter-spacing: .1em; text-transform: uppercase; color: var(--faint); }
.chn .lp-wl-opt { text-transform: none; letter-spacing: 0; font-size: 11.5px; }
.chn .lp-wl-input {
  width: 100%; padding: 13px 16px; border: 1px solid var(--line);
  border-radius: 12px; background: var(--card); font-size: 15px; color: var(--ink);
}
.chn .lp-wl-input:focus-visible { border-color: var(--terracotta); }
.chn .lp-wl-select { appearance: none; cursor: pointer; }
.chn .lp-wl-honey { position: absolute; left: -9999px; width: 1px; height: 1px; opacity: 0; }
.chn .lp-wl-error { margin-top: 14px; font-size: 14px; color: var(--terracotta); }
.chn .lp-wl-actions {
  display: flex; flex-wrap: wrap; align-items: center; gap: 16px; margin-top: 22px;
}
.chn .lp-wl-submit {
  padding: 14px 26px; border: 0; border-radius: 999px;
  background: var(--ink); color: var(--cream); font-size: 15px; cursor: pointer;
}
.chn .lp-wl-submit:hover:not(:disabled) { background: var(--terracotta); }
.chn .lp-wl-submit:disabled { opacity: .6; cursor: default; }
.chn .lp-wl-fine { font-size: 13px; color: var(--faint); }
.chn .lp-wl-fine a { color: var(--terracotta); }
.chn .lp-wl-done { text-align: center; padding: 8px 0 4px; }
.chn .lp-wl-check {
  display: grid; place-items: center; width: 44px; height: 44px; margin: 0 auto 16px;
  border-radius: 50%; background: var(--green); color: var(--cream);
}
.chn .lp-wl-done-h { font-size: 26px; font-weight: 400; }
.chn .lp-wl-done-p { margin-top: 10px; font-size: 15px; line-height: 1.6; color: var(--muted-body); }

/* ── footer ──────────────────────────────────────────────────────────── */
.chn-footer { border-top: 1px solid var(--line); }
.chn-footer-inner {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: 24px; max-width: 1120px; margin: 0 auto; padding: 34px 40px 44px;
  font-size: 13.5px; color: var(--faint);
}
.chn-footer-brand { display: flex; align-items: center; gap: 10px; color: var(--ink); }
.chn-footer-links { display: flex; flex-wrap: wrap; gap: 26px; }
.chn-footer-links a { color: var(--faint); }

/* ── responsive: the reference is desktop-first ───────────────────────── */
@media (max-width: 1080px) {
  .chn-nav-links { display: none; }
  .chn-nav { grid-template-columns: 1fr auto; }
}
@media (max-width: 1000px) {
  .chn-head-pair, .chn-split { grid-template-columns: 1fr; gap: 34px; }
  .chn-split-you { padding-left: 0; padding-top: 26px; border-left: 0; border-top: 1px solid var(--terracotta); }
  .chn-stats, .chn-guardrails, .chn-team { grid-template-columns: repeat(2, 1fr); gap: 34px; }
  .chn-stats { margin-top: 70px; }
  .chn-signals-grid, .chn-demo { grid-template-columns: 1fr; gap: 40px; }
  .chn-signals-col { padding-bottom: 0; }
  /* Sticky with a single column would pin the panel over its own feed. */
  .chn-panel-col { position: static; }
  .chn-feature-grid, .chn-steps, .chn-trio, .chn-plans { grid-template-columns: 1fr; }
  .chn-feature-grid { gap: 1px; }
  .chn-steps, .chn-trio { gap: 40px; }
  .chn-wrap, .chn-demo-section, .chn-how, .chn-team-section { padding: 90px 28px; }
  .chn-wrap-inner, .chn-wrap-wide { padding: 0 28px; }
  .chn-band, .chn-signals { padding: 90px 0; }
  .chn-dark { padding: 90px 0; }
  .chn-flow-static { padding: 80px 28px; }
}
@media (max-width: 720px) {
  .chn-nav { padding: 10px 20px; gap: 12px; }
  .chn-nav[data-tight="1"] { padding: 6px 20px; }
  .chn-hero { padding: 130px 20px 50px; }
  .chn-preview-stats { grid-template-columns: 1fr; }
  .chn-preview-stats > div { border-right: 0; border-bottom: 1px solid var(--line-soft); }
  .chn-preview-row { grid-template-columns: 1fr auto; }
  .chn-preview-detail { grid-column: 1 / -1; }
  .chn-stats, .chn-guardrails, .chn-team { grid-template-columns: 1fr; }
  .chn-demo { padding: 28px 22px; }
  .chn-dial-row { flex-direction: column; align-items: flex-start; gap: 18px; }
  .chn .lp-wl-grid { grid-template-columns: 1fr; }
  .chn-waitlist { padding: 100px 20px 90px; }
  .chn-footer-inner { padding: 28px 20px 36px; }
}

@media (prefers-reduced-motion: reduce) {
  .chn-marquee-track, .chn-flow-lines path { animation: none; }
  .chn * { transition: none !important; }
}
`;
