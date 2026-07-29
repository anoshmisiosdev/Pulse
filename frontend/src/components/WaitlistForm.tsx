import { useId, useState } from "react";
import { EMAIL_RE, waitlist } from "../lib/waitlist";

/**
 * Public waitlist form.
 *
 * Styled for a dark surface — it lives in the espresso band at the foot of the
 * landing page. Validation mirrors the backend so a mistake is caught before a
 * round trip, and the success state replaces the form rather than sitting
 * beside it, so there's nothing left to re-submit.
 */

const VERTICALS = [
  "Café / coffee shop",
  "Salon / barbershop",
  "Gym / fitness studio",
  "Med spa",
  "Yoga / pilates studio",
  "Something else",
];

type Phase = "idle" | "sending" | "done";

export default function WaitlistForm() {
  const uid = useId();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [business, setBusiness] = useState("");
  const [vertical, setVertical] = useState("");
  const [honey, setHoney] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [again, setAgain] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!name.trim()) return setError("Please add your name.");
    if (!EMAIL_RE.test(email.trim())) return setError("Please add an email we can reach you at.");
    // A filled honeypot is a bot. Show the success state without sending —
    // there's nothing to record and nothing to explain.
    if (honey.trim()) return setPhase("done");

    setPhase("sending");
    try {
      const result = await waitlist.join({
        name: name.trim(),
        email: email.trim(),
        business_name: business.trim() || undefined,
        vertical: vertical || undefined,
      });
      setAgain(result.already_joined);
      setPhase("done");
    } catch (err) {
      setPhase("idle");
      setError(err instanceof Error ? err.message : "Network error — please try again.");
    }
  };

  if (phase === "done") {
    return (
      <div className="lp-wl-done" role="status">
        <span className="lp-wl-check" aria-hidden>
          <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M20 6 9 17l-5-5" />
          </svg>
        </span>
        <h3 className="font-display lp-wl-done-h">
          {again ? "You're already on the list." : "You're on the list."}
        </h3>
        <p className="lp-wl-done-p">
          {again
            ? "We've got your details — no need to sign up twice. We'll be in touch as we open seats."
            : `Thanks${name.trim() ? `, ${name.trim().split(" ")[0]}` : ""}. We'll email you as we open up seats for new businesses.`}
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="lp-wl-form" noValidate>
      <div className="lp-wl-grid">
        <label className="lp-wl-field" htmlFor={`${uid}-name`}>
          <span className="lp-wl-label">Your name</span>
          <input
            id={`${uid}-name`}
            className="lp-wl-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={120}
            autoComplete="name"
            placeholder="Dana Okafor"
            required
          />
        </label>

        <label className="lp-wl-field" htmlFor={`${uid}-email`}>
          <span className="lp-wl-label">Email</span>
          <input
            id={`${uid}-email`}
            className="lp-wl-input"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            maxLength={320}
            autoComplete="email"
            placeholder="you@yourshop.com"
            required
          />
        </label>

        <label className="lp-wl-field" htmlFor={`${uid}-business`}>
          <span className="lp-wl-label">
            Business <span className="lp-wl-opt">optional</span>
          </span>
          <input
            id={`${uid}-business`}
            className="lp-wl-input"
            value={business}
            onChange={(e) => setBusiness(e.target.value)}
            maxLength={160}
            autoComplete="organization"
            placeholder="Bluebird Coffee"
          />
        </label>

        <label className="lp-wl-field" htmlFor={`${uid}-vertical`}>
          <span className="lp-wl-label">
            What kind <span className="lp-wl-opt">optional</span>
          </span>
          <select
            id={`${uid}-vertical`}
            className="lp-wl-input lp-wl-select"
            value={vertical}
            onChange={(e) => setVertical(e.target.value)}
          >
            <option value="">Choose one…</option>
            {VERTICALS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* Honeypot: off-screen, not display:none — some bots skip hidden fields. */}
      <input
        className="lp-wl-honey"
        type="text"
        name="website"
        value={honey}
        onChange={(e) => setHoney(e.target.value)}
        tabIndex={-1}
        autoComplete="off"
        aria-hidden
      />

      {error && (
        <p className="lp-wl-error" role="alert">
          {error}
        </p>
      )}

      <div className="lp-wl-actions">
        <button type="submit" className="lp-wl-submit" disabled={phase === "sending"}>
          {phase === "sending" ? "Joining…" : "Join the waitlist"}
          {phase !== "sending" && <span aria-hidden> →</span>}
        </button>
        <span className="lp-wl-fine">No spam. One email when we open a seat for you.</span>
      </div>
    </form>
  );
}
