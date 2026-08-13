import { useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { acquisitionForSignup } from "../lib/acquisition";
import { trackLandingEvent } from "../lib/landingAnalytics";
import { EMAIL_RE, waitlist } from "../lib/waitlist";

const VERTICALS = [
  ["cafe", "Café / coffee shop"],
  ["salon", "Salon / barbershop"],
  ["fitness", "Gym / fitness studio"],
  ["med_spa", "Med spa"],
  ["yoga", "Yoga / pilates studio"],
  ["other", "Something else"],
] as const;

type Phase = "email" | "sending" | "enrich" | "saving" | "done";

interface WaitlistFormProps {
  location: "hero" | "calculator";
  landingVariant: string;
  theme?: "light" | "dark";
}

export default function WaitlistForm({
  location,
  landingVariant,
  theme = "light",
}: WaitlistFormProps) {
  const uid = useId();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [business, setBusiness] = useState("");
  const [vertical, setVertical] = useState("");
  const [honey, setHoney] = useState("");
  const [phase, setPhase] = useState<Phase>("email");
  const [alreadyJoined, setAlreadyJoined] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  const markStarted = () => {
    if (started.current) return;
    started.current = true;
    void trackLandingEvent({ event: "landing_waitlist_started" });
  };

  const submitEmail = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    const normalizedEmail = email.trim().toLowerCase();
    if (!EMAIL_RE.test(normalizedEmail)) {
      void trackLandingEvent({
        event: "landing_waitlist_validation_failed",
        reason: "invalid_email",
      });
      setError("Enter an email we can reach you at.");
      return;
    }
    if (honey.trim()) {
      setPhase("done");
      return;
    }

    void trackLandingEvent({
      event: "landing_cta_clicked",
      cta: "join_waitlist",
      location,
      destination: "waitlist",
    });
    setPhase("sending");
    try {
      const result = await waitlist.join({
        email: normalizedEmail,
        ...acquisitionForSignup(landingVariant),
      });
      setAlreadyJoined(result.already_joined);
      setPhase("enrich");
    } catch (reason) {
      void trackLandingEvent({
        event: "landing_waitlist_submit_failed",
        reason: "request_failed",
      });
      setPhase("email");
      setError(reason instanceof Error ? reason.message : "Network error — please try again.");
    }
  };

  const saveDetails = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim() && !business.trim() && !vertical) {
      setPhase("done");
      return;
    }
    setError(null);
    setPhase("saving");
    try {
      await waitlist.join({
        email: email.trim().toLowerCase(),
        name: name.trim() || undefined,
        business_name: business.trim() || undefined,
        vertical: vertical || undefined,
        ...acquisitionForSignup(landingVariant),
      });
      setPhase("done");
    } catch (reason) {
      setPhase("enrich");
      setError(reason instanceof Error ? reason.message : "We could not save that yet.");
    }
  };

  if (phase === "done") {
    return (
      <div className={`early-form early-form--${theme} early-form__success`} role="status" data-clarity-mask="true">
        <span className="early-form__check" aria-hidden>✓</span>
        <div>
          <strong>{alreadyJoined ? "You’re already on the list." : "You’re all set."}</strong>
          <p>Watch your inbox for a confirmation and the next early-access opening.</p>
        </div>
      </div>
    );
  }

  if (phase === "enrich" || phase === "saving") {
    return (
      <form
        className={`early-form early-form--${theme}`}
        onSubmit={saveDetails}
        aria-label="Optional early access details"
        data-clarity-mask="true"
      >
        <div className="early-form__confirmed" role="status">
          <span aria-hidden>✓</span>
          <div>
            <strong>{alreadyJoined ? "Email confirmed — you’re already in." : "You’re on the early-access list."}</strong>
            <p>Optional: tell us who you are so we can make your first conversation useful.</p>
          </div>
        </div>
        <div className="early-form__details">
          <label htmlFor={`${uid}-name`}>
            Name <span>optional</span>
            <input
              id={`${uid}-name`}
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={120}
              autoComplete="name"
              placeholder="Dana Okafor"
            />
          </label>
          <label htmlFor={`${uid}-business`}>
            Business <span>optional</span>
            <input
              id={`${uid}-business`}
              value={business}
              onChange={(event) => setBusiness(event.target.value)}
              maxLength={160}
              autoComplete="organization"
              placeholder="Bluebird Coffee"
            />
          </label>
          <label htmlFor={`${uid}-vertical`}>
            Business type <span>optional</span>
            <select
              id={`${uid}-vertical`}
              value={vertical}
              onChange={(event) => setVertical(event.target.value)}
            >
              <option value="">Choose one…</option>
              {VERTICALS.map(([value, label]) => (
                <option key={value} value={label}>{label}</option>
              ))}
            </select>
          </label>
        </div>
        {error && <p className="early-form__error" role="alert">{error}</p>}
        <div className="early-form__actions">
          <button type="submit" disabled={phase === "saving"}>
            {phase === "saving" ? "Saving…" : "Save optional details"}
          </button>
          <button type="button" className="is-quiet" onClick={() => setPhase("done")}>Skip for now</button>
        </div>
      </form>
    );
  }

  return (
    <form
      className={`early-form early-form--${theme}`}
      onSubmit={submitEmail}
      onFocusCapture={markStarted}
      aria-label={`Get early access from the ${location}`}
      data-clarity-mask="true"
      noValidate
    >
      <div className="early-form__email-row">
        <label className="sr-only" htmlFor={`${uid}-email`}>Work email</label>
        <input
          id={`${uid}-email`}
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          maxLength={320}
          autoComplete="email"
          inputMode="email"
          placeholder="you@yourbusiness.com"
          aria-describedby={`${uid}-fine`}
          required
        />
        <button type="submit" disabled={phase === "sending"}>
          {phase === "sending" ? "Joining…" : "Get early access"}
          {phase !== "sending" && <span aria-hidden> →</span>}
        </button>
      </div>
      <input
        className="early-form__honey"
        type="text"
        name="website"
        value={honey}
        onChange={(event) => setHoney(event.target.value)}
        tabIndex={-1}
        autoComplete="off"
        aria-hidden
      />
      {error && <p className="early-form__error" role="alert">{error}</p>}
      <p className="early-form__fine" id={`${uid}-fine`}>
        Email first. No card. No spam. <Link to="/privacy">Privacy policy</Link>.
      </p>
    </form>
  );
}
