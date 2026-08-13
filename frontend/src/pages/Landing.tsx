import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import ChurnaryMark from "../components/ChurnaryMark";
import SeoHead from "../components/SeoHead";
import WaitlistForm from "../components/WaitlistForm";
import { rememberAcquisition } from "../lib/acquisition";
import { landingViewMetric, trackLandingEvent } from "../lib/landingAnalytics";
import { getMarketingPage, type MarketingVertical } from "../lib/marketingPages";
import {
  hasAnalyticsConsent,
  onPrivacyPreferenceChange,
  openPrivacyChoices,
} from "../lib/privacyPreferences";
import "./Landing.css";

const VERTICAL_LABELS: Record<MarketingVertical, string> = {
  cafe: "Café / coffee shop",
  salon: "Salon / barbershop",
  fitness: "Gym / fitness studio",
};

const CADENCE_DAYS: Record<MarketingVertical, number> = {
  cafe: 7,
  salon: 35,
  fitness: 5,
};

function useLandingMetrics(pathname: string, variant: string) {
  const viewedPath = useRef("");
  const [enabled, setEnabled] = useState(hasAnalyticsConsent);

  useEffect(
    () => onPrivacyPreferenceChange(() => setEnabled(hasAnalyticsConsent())),
    []
  );

  useEffect(() => {
    if (!enabled || viewedPath.current === pathname) return;
    viewedPath.current = pathname;
    void trackLandingEvent(landingViewMetric());
  }, [enabled, pathname]);

  useEffect(() => {
    rememberAcquisition(variant);
  }, [pathname, variant]);

  useEffect(() => {
    if (!enabled || typeof IntersectionObserver === "undefined") return;
    const seen = new Set<string>();
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting || seen.has(entry.target.id)) return;
          seen.add(entry.target.id);
          const section = entry.target.id as "demo" | "pricing" | "waitlist";
          void trackLandingEvent({ event: "landing_section_viewed", section });
          observer.unobserve(entry.target);
        });
      },
      { threshold: 0.35 }
    );
    (["demo", "pricing", "waitlist"] as const).forEach((id) => {
      const node = document.getElementById(id);
      if (node) observer.observe(node);
    });
    return () => observer.disconnect();
  }, [enabled, pathname]);
}

export default function Landing() {
  const { pathname } = useLocation();
  const page = getMarketingPage(pathname);
  useLandingMetrics(pathname, page.key);

  return (
    <div className="acq-page">
      <SeoHead
        title={page.title}
        description={page.description}
        path={page.path}
        pageType="software"
      />
      <a className="acq-skip" href="#main-content">Skip to content</a>
      <Header />
      <main id="main-content">
        <Hero page={page} />
        <RiskCalculator defaultVertical={page.defaultVertical} landingVariant={page.key} />
        <HowItWorks />
        <TrustControls />
        <TeamAndPricing landingVariant={page.key} audienceLabel={page.audienceLabel} />
      </main>
      <Footer />
    </div>
  );
}

function Header() {
  return (
    <header className="acq-header">
      <a href="#top" className="acq-brand" aria-label="Churnary home">
        <ChurnaryMark size={31} tile />
        <span>Churnary</span>
      </a>
      <nav aria-label="Main navigation">
        <a href="#calculator">Calculator</a>
        <a href="#how-it-works">How it works</a>
        <a href="#trust">Trust</a>
        <Link to="/login" className="acq-sign-in">Sign in</Link>
        <a
          href="#early-access"
          className="acq-button acq-button--small"
          onClick={() => void trackLandingEvent({
            event: "landing_cta_clicked",
            cta: "join_waitlist",
            location: "navbar",
            destination: "waitlist",
          })}
        >
          Get early access
        </a>
      </nav>
    </header>
  );
}

function Hero({ page }: { page: ReturnType<typeof getMarketingPage> }) {
  return (
    <section className="acq-hero" id="top">
      <div className="acq-hero__copy">
        <p className="acq-eyebrow"><span aria-hidden />{page.eyebrow}</p>
        <h1>{page.headline}</h1>
        <p className="acq-hero__lede">{page.lede}</p>
        <div id="early-access" className="acq-hero__form">
          <WaitlistForm location="hero" landingVariant={page.key} />
        </div>
        <ul className="acq-hero__proof" aria-label="Early access details">
          <li>No card required</li>
          <li>Human approval before outreach</li>
          <li>Works with CSV data</li>
        </ul>
      </div>
      <ProductPreview />
    </section>
  );
}

function ProductPreview() {
  const people = [
    ["Maya R.", "Visits every 6–8 days", "18 days away", "Needs attention"],
    ["Jordan L.", "Visits every 28–35 days", "42 days away", "Watch"],
    ["Chris A.", "Visits every 4–6 days", "5 days away", "On rhythm"],
  ];
  return (
    <div className="acq-preview" aria-label="Illustrative Churnary product preview">
      <div className="acq-preview__bar">
        <span>Illustrative product demo</span>
        <span aria-hidden>•••</span>
      </div>
      <div className="acq-preview__summary">
        <div>
          <span>Today’s focus</span>
          <strong>3 customers need a look</strong>
        </div>
        <span className="acq-preview__badge">Demo data</span>
      </div>
      <div className="acq-preview__rows">
        {people.map(([name, rhythm, gap, state], index) => (
          <div className="acq-preview__row" key={name}>
            <span className={`acq-preview__avatar is-${index + 1}`} aria-hidden>{name[0]}</span>
            <div><strong>{name}</strong><span>{rhythm}</span></div>
            <span>{gap}</span>
            <b className={`is-state-${index + 1}`}>{state}</b>
          </div>
        ))}
      </div>
      <div className="acq-preview__action">
        <div>
          <span>Why Maya is flagged</span>
          <p>Her current gap is more than twice her usual visit rhythm.</p>
        </div>
        <button type="button" disabled>Review draft</button>
      </div>
    </div>
  );
}

function RiskCalculator({
  defaultVertical,
  landingVariant,
}: {
  defaultVertical: MarketingVertical;
  landingVariant: string;
}) {
  const [vertical, setVertical] = useState<MarketingVertical>(defaultVertical);
  const [regulars, setRegulars] = useState(220);
  const [monthlyValue, setMonthlyValue] = useState(46);
  const [daysLate, setDaysLate] = useState(14);

  useEffect(() => setVertical(defaultVertical), [defaultVertical]);

  const estimate = useMemo(() => {
    const cadence = CADENCE_DAYS[vertical];
    const driftRatio = daysLate / cadence;
    const riskRate = Math.min(32, Math.max(4, Math.round(5 + driftRatio * 7)));
    const customers = Math.round(regulars * (riskRate / 100));
    const value = customers * monthlyValue;
    const riskBand = driftRatio < 1 ? "healthy" : driftRatio < 2 ? "watch" : "needs_attention";
    return { cadence, riskRate, customers, value, riskBand } as const;
  }, [daysLate, monthlyValue, regulars, vertical]);

  const trackCalculator = (
    control: "vertical" | "regulars" | "monthly_value" | "days",
    nextVertical = vertical
  ) => {
    void trackLandingEvent({
      event: "landing_demo_interacted",
      control,
      vertical: nextVertical,
      risk_band: estimate.riskBand,
    });
  };

  return (
    <section className="acq-section acq-calculator" id="calculator">
      <div className="acq-section__intro">
        <p className="acq-kicker">Free retention-risk calculator</p>
        <h2>What could customer drift be costing this month?</h2>
        <p>
          Start with a simple estimate. Churnary’s product uses each customer’s own visit history;
          this public calculator intentionally uses a transparent, illustrative formula.
        </p>
      </div>
      <div className="acq-calculator__card" id="demo">
        <div className="acq-calculator__inputs">
          <label>
            Business type
            <select
              value={vertical}
              onChange={(event) => {
                const next = event.target.value as MarketingVertical;
                setVertical(next);
                trackCalculator("vertical", next);
              }}
            >
              {Object.entries(VERTICAL_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          <label>
            Active regular customers <output>{regulars}</output>
            <input
              type="range"
              min="25"
              max="1000"
              step="5"
              value={regulars}
              onChange={(event) => setRegulars(Number(event.target.value))}
              onPointerUp={() => trackCalculator("regulars")}
              onKeyUp={() => trackCalculator("regulars")}
              aria-label="Active regular customers"
            />
          </label>
          <label>
            Average monthly value per regular <output>${monthlyValue}</output>
            <input
              type="range"
              min="10"
              max="250"
              step="2"
              value={monthlyValue}
              onChange={(event) => setMonthlyValue(Number(event.target.value))}
              onPointerUp={() => trackCalculator("monthly_value")}
              onKeyUp={() => trackCalculator("monthly_value")}
              aria-label="Average monthly value per regular"
            />
          </label>
          <label>
            Days beyond a normal visit <output>{daysLate} days</output>
            <input
              type="range"
              min="1"
              max="60"
              value={daysLate}
              onChange={(event) => setDaysLate(Number(event.target.value))}
              onPointerUp={() => trackCalculator("days")}
              onKeyUp={() => trackCalculator("days")}
              aria-label="Days beyond a normal visit"
            />
          </label>
        </div>
        <div className="acq-calculator__result" aria-live="polite">
          <span>Illustrative monthly estimate</span>
          <strong>${estimate.value.toLocaleString()}</strong>
          <p>
            About <b>{estimate.customers} regulars</b> at an estimated {estimate.riskRate}% drift
            rate, using a typical {estimate.cadence}-day rhythm for this example.
          </p>
          <small>Estimate only—not a customer result, forecast, or guarantee.</small>
        </div>
      </div>
      <div className="acq-calculator__conversion" id="waitlist">
        <div>
          <p className="acq-kicker">Turn the estimate into a real risk list</p>
          <h3>See which individual customers need attention.</h3>
          <p>Join early access with your email. Business details are optional after signup.</p>
        </div>
        <WaitlistForm location="calculator" landingVariant={landingVariant} theme="dark" />
      </div>
    </section>
  );
}

function HowItWorks() {
  const steps = [
    ["01", "Connect what you already have", "Link Square or Stripe when available, or start with a customer CSV. No CRM migration required."],
    ["02", "See the signal and the reason", "Churnary compares each customer with their own rhythm and explains meaningful changes in plain language."],
    ["03", "Approve thoughtful outreach", "Review the personal draft, make any edit you want, and decide whether anything is sent."],
  ];
  return (
    <section className="acq-section acq-how" id="how-it-works">
      <div className="acq-section__intro is-centered">
        <p className="acq-kicker">Three steps</p>
        <h2>From visit history to a useful next action.</h2>
      </div>
      <ol>
        {steps.map(([number, title, body]) => (
          <li key={number}>
            <span>{number}</span>
            <h3>{title}</h3>
            <p>{body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function TrustControls() {
  const controls = [
    ["Approval first", "Nothing is sent just because an algorithm produced a score. You review the customer, reason, and draft first."],
    ["Explainable signals", "Risk is grounded in visit and spend patterns you can inspect—not an unexplained black-box label."],
    ["Privacy choices", "Optional analytics and behavior recording stay off until a visitor allows them. Global Privacy Control is honored."],
    ["Your customer data", "Connected business data is used to provide retention workflows, not to train a public advertising profile."],
  ];
  return (
    <section className="acq-section acq-trust" id="trust">
      <div className="acq-section__intro">
        <p className="acq-kicker">Trust and control</p>
        <h2>AI makes the draft. You make the decision.</h2>
        <p>Retention outreach works only when it respects the relationship your business already earned.</p>
      </div>
      <div className="acq-trust__grid">
        {controls.map(([title, body], index) => (
          <article key={title}>
            <span>0{index + 1}</span>
            <h3>{title}</h3>
            <p>{body}</p>
          </article>
        ))}
      </div>
      <div className="acq-trust__links">
        <Link to="/privacy">Read the privacy policy</Link>
        <button type="button" onClick={openPrivacyChoices}>Open privacy choices</button>
      </div>
    </section>
  );
}

function TeamAndPricing({
  landingVariant,
  audienceLabel,
}: {
  landingVariant: string;
  audienceLabel: string;
}) {
  const team = ["Soham Dogra", "Riyan Anosh", "Pranjal Mishra", "Aditya Kolekar"];
  return (
    <section className="acq-section acq-closing" id="pricing">
      <div className="acq-closing__team">
        <p className="acq-kicker">Built by a small team</p>
        <h2>Four longtime builders, focused on one practical problem.</h2>
        <p>
          We are building Churnary with local business owners, one workflow at a time. Early users
          get a direct line to the team and shape what ships next.
        </p>
        <ul>
          {team.map((name) => <li key={name}><span aria-hidden>{name.split(" ").map((part) => part[0]).join("")}</span>{name}</li>)}
        </ul>
      </div>
      <div className="acq-closing__pricing">
        <span>Early-access pricing</span>
        <strong>Free while we learn together.</strong>
        <p>
          No card is required for early access. Churnary is expected to become a paid product;
          final plans and prices are not set yet, and you will always see them before choosing.
        </p>
        <a
          className="acq-button"
          href="#early-access"
          onClick={() => void trackLandingEvent({
            event: "landing_cta_clicked",
            cta: "join_waitlist",
            location: "pricing",
            destination: "waitlist",
          })}
        >
          Get early access <span aria-hidden>→</span>
        </a>
        <small>Best for {audienceLabel}.</small>
        <span className="sr-only">Landing variant: {landingVariant}</span>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="acq-footer">
      <div className="acq-brand">
        <ChurnaryMark size={25} />
        <span>Churnary</span>
      </div>
      <p>Customer retention for repeat-visit local businesses.</p>
      <nav aria-label="Footer navigation">
        <Link to="/coffee-shop-customer-retention">Coffee shops</Link>
        <Link to="/salon-customer-retention">Salons</Link>
        <Link to="/gym-member-retention">Gyms</Link>
        <Link to="/customer-churn-risk-calculator">Calculator</Link>
        <Link to="/privacy">Privacy</Link>
        <button type="button" onClick={openPrivacyChoices}>Privacy choices</button>
      </nav>
      <span>© 2026 Churnary</span>
    </footer>
  );
}
