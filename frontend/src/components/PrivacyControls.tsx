import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  clearOptionalTrackingData,
  effectivePrivacyPreference,
  globalPrivacyControlEnabled,
  onPrivacyPreferenceChange,
  savePrivacyPreference,
  storedPrivacyPreference,
  type AnalyticsPreference,
} from "../lib/privacyPreferences";

export default function PrivacyControls() {
  const [preference, setPreference] = useState(effectivePrivacyPreference);
  const [hasStoredChoice, setHasStoredChoice] = useState(
    () => storedPrivacyPreference() !== null
  );
  const [dialogOpen, setDialogOpen] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const gpc = globalPrivacyControlEnabled();

  useEffect(
    () =>
      onPrivacyPreferenceChange(() => {
        setPreference(effectivePrivacyPreference());
        setHasStoredChoice(storedPrivacyPreference() !== null);
      }),
    []
  );

  useEffect(() => {
    if (gpc) clearOptionalTrackingData();
  }, [gpc]);

  useEffect(() => {
    const open = () => setDialogOpen(true);
    window.addEventListener("churnary:open-privacy-choices", open);
    return () => window.removeEventListener("churnary:open-privacy-choices", open);
  }, []);

  useEffect(() => {
    if (!dialogOpen) return;
    dialogRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDialogOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [dialogOpen]);

  const choose = (analytics: AnalyticsPreference) => {
    setPreference(savePrivacyPreference(analytics));
    setHasStoredChoice(true);
    setDialogOpen(false);
  };

  return (
    <>
      <style>{PRIVACY_CONTROLS_CSS}</style>

      {!hasStoredChoice && (
        <section
          className="privacy-consent"
          aria-label="Privacy choices"
          aria-live="polite"
        >
          <div>
            <strong>{gpc ? "Your Global Privacy Control is honored." : "Your privacy choices"}</strong>
            <p>
              {gpc
                ? "Optional analytics and visitor identification are off. You can keep that choice or explicitly allow them."
                : "We use optional analytics to understand interest in Churnary. With permission, an identity provider may also match U.S. business visitors. Essential site functions work either way."}{" "}
              <Link to="/privacy#tracking">Learn more</Link>
            </p>
          </div>
          <div className="privacy-consent-actions">
            <button type="button" onClick={() => choose("denied")}>
              {gpc ? "Keep essential only" : "Essential only"}
            </button>
            {!gpc && (
              <button
                type="button"
                className="is-primary"
                onClick={() => choose("granted")}
              >
                Allow analytics
              </button>
            )}
          </div>
        </section>
      )}

      {hasStoredChoice && !dialogOpen && (
        <button
          type="button"
          className="privacy-choice-trigger"
          onClick={() => setDialogOpen(true)}
        >
          Privacy choices
        </button>
      )}

      {dialogOpen && (
        <div
          className="privacy-dialog-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setDialogOpen(false);
          }}
        >
          <div
            ref={dialogRef}
            className="privacy-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="privacy-dialog-title"
            tabIndex={-1}
          >
            <div className="privacy-dialog-head">
              <div>
                <span>Privacy controls</span>
                <h2 id="privacy-dialog-title">Choose what Churnary may measure</h2>
              </div>
              <button
                type="button"
                aria-label="Close privacy choices"
                onClick={() => setDialogOpen(false)}
              >
                ×
              </button>
            </div>
            <p>
              Essential storage supports sign-in, security, and your explicit
              preferences. Optional analytics connects meaningful website actions
              across visits. Visitor identification is loaded only after you allow
              analytics and only when Churnary has configured a provider.
            </p>
            {gpc && (
              <div className="privacy-gpc-note">
                Global Privacy Control is active in this browser. Optional tracking
                remains off while that signal is enabled.
              </div>
            )}
            <div className="privacy-dialog-options">
              <button
                type="button"
                className={preference?.analytics === "denied" ? "is-selected" : ""}
                onClick={() => choose("denied")}
              >
                <strong>Essential only</strong>
                <span>No marketing analytics or visitor identification.</span>
              </button>
              <button
                type="button"
                className={preference?.analytics === "granted" ? "is-selected" : ""}
                disabled={gpc}
                onClick={() => choose("granted")}
              >
                <strong>Allow analytics</strong>
                <span>
                  {gpc
                    ? "Unavailable while Global Privacy Control is active."
                    : "Help us measure interest and improve Churnary."}
                </span>
              </button>
            </div>
            <Link to="/privacy#tracking" onClick={() => setDialogOpen(false)}>
              Read the Privacy Policy
            </Link>
          </div>
        </div>
      )}
    </>
  );
}

const PRIVACY_CONTROLS_CSS = `
  .privacy-consent {
    position: fixed;
    z-index: 100;
    right: clamp(14px, 3vw, 34px);
    bottom: clamp(14px, 3vw, 30px);
    left: clamp(14px, 3vw, 34px);
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: 24px;
    max-width: 980px;
    margin: 0 auto;
    padding: 18px 20px;
    border: 1px solid rgba(234, 221, 204, .9);
    border-radius: 18px;
    background: rgba(36, 26, 20, .97);
    box-shadow: 0 24px 60px rgba(24, 16, 12, .28);
    color: #f7eee3;
  }
  .privacy-consent strong { font-family: var(--font-display); font-size: 17px; }
  .privacy-consent p { max-width: 650px; margin: 4px 0 0; color: rgba(247,238,227,.72); font-size: 13px; line-height: 1.55; }
  .privacy-consent a { color: #e0a074; }
  .privacy-consent-actions { display: flex; gap: 9px; }
  .privacy-consent-actions button {
    min-height: 40px; padding: 0 15px; border: 1px solid rgba(247,238,227,.28);
    border-radius: 9px; background: transparent; color: #f7eee3; font: 700 13px var(--font-body);
    cursor: pointer;
  }
  .privacy-consent-actions button.is-primary { border-color: #d37b4c; background: #b4532a; }
  .privacy-choice-trigger {
    position: fixed; z-index: 80; left: 14px; bottom: 12px;
    border: 1px solid var(--border); border-radius: 999px; background: rgba(251,246,238,.94);
    color: var(--muted); padding: 7px 11px; box-shadow: 0 8px 24px rgba(42,33,28,.1);
    font: 700 11px var(--font-body); cursor: pointer; backdrop-filter: blur(10px);
  }
  .privacy-choice-trigger:hover { color: var(--accent-dark); }
  .privacy-dialog-backdrop {
    position: fixed; z-index: 110; inset: 0; display: grid; place-items: center; padding: 18px;
    background: rgba(30,21,16,.55); backdrop-filter: blur(5px);
  }
  .privacy-dialog {
    width: min(560px, 100%); max-height: min(720px, calc(100vh - 36px)); overflow: auto;
    border: 1px solid var(--border); border-radius: 22px; background: var(--surface);
    box-shadow: 0 28px 90px rgba(30,21,16,.3); padding: 25px; outline: none;
  }
  .privacy-dialog-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
  .privacy-dialog-head span { color: var(--accent); font-size: 10px; font-weight: 800; letter-spacing: .13em; text-transform: uppercase; }
  .privacy-dialog h2 { margin: 5px 0 0; color: var(--ink-strong); font-size: clamp(23px, 5vw, 30px); line-height: 1.08; }
  .privacy-dialog-head > button { border: 0; background: transparent; color: var(--muted); font-size: 27px; cursor: pointer; }
  .privacy-dialog > p { color: var(--muted); font-size: 14px; line-height: 1.65; }
  .privacy-gpc-note { margin: 14px 0; border-left: 3px solid var(--sage); background: rgba(92,138,74,.09); padding: 10px 12px; color: var(--sage-text); font-size: 12px; line-height: 1.5; }
  .privacy-dialog-options { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 18px 0; }
  .privacy-dialog-options button {
    display: flex; min-height: 112px; flex-direction: column; align-items: flex-start; gap: 6px;
    border: 1px solid var(--border); border-radius: 14px; background: var(--surface-2);
    padding: 16px; color: var(--ink); text-align: left; cursor: pointer;
  }
  .privacy-dialog-options button.is-selected { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
  .privacy-dialog-options button:disabled { cursor: not-allowed; opacity: .52; }
  .privacy-dialog-options strong { font: 700 15px var(--font-body); }
  .privacy-dialog-options span { color: var(--muted); font-size: 12px; line-height: 1.45; }
  .privacy-dialog > a { font-size: 13px; font-weight: 700; }
  @media (max-width: 680px) {
    .privacy-consent { grid-template-columns: 1fr; gap: 14px; }
    .privacy-consent-actions { display: grid; grid-template-columns: 1fr 1fr; }
    .privacy-dialog-options { grid-template-columns: 1fr; }
  }
`;
