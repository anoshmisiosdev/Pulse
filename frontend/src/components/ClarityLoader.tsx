import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { isMarketingPath } from "../lib/marketingPages";
import {
  hasAnalyticsConsent,
  onPrivacyPreferenceChange,
} from "../lib/privacyPreferences";

const SCRIPT_SELECTOR = "script[data-churnary-clarity]";

type ClarityWindow = Window & {
  clarity?: (...args: unknown[]) => void;
};

function unloadClarity() {
  document.querySelectorAll(SCRIPT_SELECTOR).forEach((node) => node.remove());
  delete (window as ClarityWindow).clarity;
  ["_clck", "_clsk", "CLID", "ANONCHK", "MR", "MUID", "SM"].forEach((name) => {
    document.cookie = `${name}=; Max-Age=0; path=/; SameSite=Lax`;
  });
}

function loadClarity(projectId: string) {
  if (document.querySelector(SCRIPT_SELECTOR)) return;
  const clarityWindow = window as ClarityWindow;
  clarityWindow.clarity =
    clarityWindow.clarity ||
    function (...args: unknown[]) {
      const queue = (clarityWindow.clarity as { q?: unknown[][] }).q || [];
      queue.push(args);
      (clarityWindow.clarity as { q?: unknown[][] }).q = queue;
    };
  const script = document.createElement("script");
  script.async = true;
  script.dataset.churnaryClarity = "true";
  script.referrerPolicy = "strict-origin-when-cross-origin";
  script.src = `https://www.clarity.ms/tag/${encodeURIComponent(projectId)}`;
  script.addEventListener("error", unloadClarity, { once: true });
  document.head.appendChild(script);
}

/** Load session recordings only on public acquisition pages and after consent. */
export default function ClarityLoader() {
  const { pathname } = useLocation();
  const projectId = String(import.meta.env.VITE_CLARITY_PROJECT_ID || "").trim();

  useEffect(() => {
    const reconcile = () => {
      const validProjectId = /^[a-z0-9]{6,24}$/i.test(projectId);
      if (!validProjectId || !isMarketingPath(pathname) || !hasAnalyticsConsent()) {
        unloadClarity();
        return;
      }
      loadClarity(projectId);
    };
    reconcile();
    return onPrivacyPreferenceChange(reconcile);
  }, [pathname, projectId]);

  return null;
}
