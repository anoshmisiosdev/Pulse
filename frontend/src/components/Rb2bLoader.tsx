import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import {
  clearRb2bTrackingData,
  hasAnalyticsConsent,
  onPrivacyPreferenceChange,
} from "../lib/privacyPreferences";
import { isMarketingPath } from "../lib/marketingPages";

type Rb2bQueue = Array<unknown> & {
  invoked?: boolean;
  methods?: string[];
  factory?: (method: string) => (...args: unknown[]) => Rb2bQueue;
  identify?: (...args: unknown[]) => Rb2bQueue;
  collect?: (...args: unknown[]) => Rb2bQueue;
  load?: (key: string) => void;
  SNIPPET_VERSION?: string;
};

const SCRIPT_SELECTOR = "script[data-churnary-rb2b]";
const DEFAULT_SCRIPT_URL =
  "https://s3-us-west-2.amazonaws.com/b2bjsstore/b/{key}/reb2b.js.gz";
const ALLOWED_SCRIPT_HOSTS = new Set([
  "s3-us-west-2.amazonaws.com",
  "ddwl4m2hdecbv.cloudfront.net",
]);

export function buildRb2bScriptUrl(key: string, template = ""): string | null {
  const encodedKey = encodeURIComponent(key);
  const candidate = (template.trim() || DEFAULT_SCRIPT_URL).replaceAll(
    "{key}",
    encodedKey
  );
  try {
    const parsed = new URL(candidate);
    if (parsed.protocol !== "https:" || !ALLOWED_SCRIPT_HOSTS.has(parsed.hostname)) {
      return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
}

function unloadRb2b() {
  document.querySelectorAll(SCRIPT_SELECTOR).forEach((node) => node.remove());
  delete (window as Window & { reb2b?: Rb2bQueue }).reb2b;
  clearRb2bTrackingData();
}

function loadRb2b(key: string, scriptTemplate: string) {
  const rbWindow = window as Window & { reb2b?: Rb2bQueue };
  const existing = rbWindow.reb2b;
  if (existing?.invoked) {
    existing.collect?.();
    return;
  }

  const scriptUrl = buildRb2bScriptUrl(key, scriptTemplate);
  if (!scriptUrl) {
    unloadRb2b();
    return;
  }
  const queue = existing ?? ([] as unknown as Rb2bQueue);
  rbWindow.reb2b = queue;
  queue.invoked = true;
  queue.methods = ["identify", "collect"];
  queue.factory = (method: string) =>
    function (...args: unknown[]) {
      queue.push([method, ...args]);
      return queue;
    };
  for (const method of queue.methods) {
    queue[method as "identify" | "collect"] = queue.factory(method);
  }
  queue.load = (accountKey: string) => {
    const script = document.createElement("script");
    script.type = "text/javascript";
    script.async = true;
    script.dataset.churnaryRb2b = "true";
    script.referrerPolicy = "strict-origin-when-cross-origin";
    script.src = buildRb2bScriptUrl(accountKey, scriptTemplate) || scriptUrl;
    script.addEventListener(
      "error",
      () => {
        script.remove();
        delete (window as Window & { reb2b?: Rb2bQueue }).reb2b;
      },
      { once: true }
    );
    document.head.appendChild(script);
  };
  queue.SNIPPET_VERSION = "1.0.1";
  queue.load(key);
}

export default function Rb2bLoader() {
  const location = useLocation();
  const key = String(import.meta.env.VITE_RB2B_KEY ?? "").trim();
  const explicitlyEnabled = String(import.meta.env.VITE_RB2B_ENABLED ?? "").toLowerCase() === "true";
  const scriptTemplate = String(import.meta.env.VITE_RB2B_SCRIPT_URL ?? "").trim();
  const isMarketingPage = isMarketingPath(location.pathname) || location.pathname === "/landing";

  useEffect(() => {
    const reconcile = () => {
      const validKey = /^[A-Za-z0-9_-]{1,160}$/.test(key);
      if (!explicitlyEnabled || !validKey || !isMarketingPage || !hasAnalyticsConsent()) {
        unloadRb2b();
        return;
      }
      loadRb2b(key, scriptTemplate);
    };
    reconcile();
    return onPrivacyPreferenceChange(reconcile);
  }, [explicitlyEnabled, isMarketingPage, key, location.pathname, scriptTemplate]);

  return null;
}
