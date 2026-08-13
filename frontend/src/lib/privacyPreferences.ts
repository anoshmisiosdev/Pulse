export type AnalyticsPreference = "granted" | "denied";

export interface PrivacyPreference {
  version: 1;
  analytics: AnalyticsPreference;
  source: "choice" | "gpc";
  updated_at: string;
}

export const PRIVACY_PREFERENCE_KEY = "churnary_privacy_preferences_v1";
export const PRIVACY_PREFERENCE_EVENT = "churnary:privacy-preferences";
export const ANALYTICS_ID_STORAGE_KEY = "pulse_posthog_distinct_id";
export const VISITOR_SESSION_STORAGE_KEY = "churnary_visitor_session_id";

const RB2B_COOKIES = [
  "_reb2bgeo",
  "_reb2bloaded",
  "_reb2bref",
  "_reb2sessionID",
  "_reb2buid",
  "_reb2bfxf",
  "_reb2btd",
  "_reb2bli",
  "_reb2bresolve",
  "_reb2butk",
];

export function globalPrivacyControlEnabled(): boolean {
  if (typeof navigator === "undefined") return false;
  return Boolean(
    (navigator as Navigator & { globalPrivacyControl?: boolean }).globalPrivacyControl
  );
}

export function storedPrivacyPreference(): PrivacyPreference | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(PRIVACY_PREFERENCE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PrivacyPreference>;
    if (
      parsed.version === 1 &&
      (parsed.analytics === "granted" || parsed.analytics === "denied") &&
      (parsed.source === "choice" || parsed.source === "gpc") &&
      typeof parsed.updated_at === "string"
    ) {
      return parsed as PrivacyPreference;
    }
  } catch {
    // Corrupt or unavailable storage is treated as no choice.
  }
  return null;
}

export function effectivePrivacyPreference(): PrivacyPreference | null {
  const stored = storedPrivacyPreference();
  if (globalPrivacyControlEnabled()) {
    return {
      version: 1,
      analytics: "denied",
      source: "gpc",
      updated_at: stored?.updated_at ?? new Date(0).toISOString(),
    };
  }
  return stored;
}

export function hasAnalyticsConsent(): boolean {
  return effectivePrivacyPreference()?.analytics === "granted";
}

function clearCookie(name: string): void {
  const domains = ["", window.location.hostname, `.${window.location.hostname}`];
  for (const domain of domains) {
    document.cookie = `${name}=; Max-Age=0; path=/; SameSite=Lax${
      domain ? `; domain=${domain}` : ""
    }`;
  }
}

export function clearOptionalTrackingData(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(ANALYTICS_ID_STORAGE_KEY);
    window.sessionStorage.removeItem(VISITOR_SESSION_STORAGE_KEY);
  } catch {
    // Storage may be blocked; cookie cleanup can still proceed.
  }
  clearRb2bTrackingData();
}

export function clearRb2bTrackingData(): void {
  if (typeof window === "undefined") return;
  RB2B_COOKIES.forEach(clearCookie);
}

export function savePrivacyPreference(
  analytics: AnalyticsPreference,
  source: PrivacyPreference["source"] = "choice"
): PrivacyPreference {
  const gpc = globalPrivacyControlEnabled();
  const preference: PrivacyPreference = {
    version: 1,
    analytics: gpc ? "denied" : analytics,
    source: gpc ? "gpc" : source,
    updated_at: new Date().toISOString(),
  };
  try {
    window.localStorage.setItem(PRIVACY_PREFERENCE_KEY, JSON.stringify(preference));
  } catch {
    // The in-page event still applies the choice for this tab.
  }
  if (preference.analytics === "denied") clearOptionalTrackingData();
  window.dispatchEvent(
    new CustomEvent<PrivacyPreference>(PRIVACY_PREFERENCE_EVENT, {
      detail: preference,
    })
  );
  return preference;
}

export function onPrivacyPreferenceChange(listener: () => void): () => void {
  const handle = () => listener();
  window.addEventListener(PRIVACY_PREFERENCE_EVENT, handle);
  window.addEventListener("storage", handle);
  return () => {
    window.removeEventListener(PRIVACY_PREFERENCE_EVENT, handle);
    window.removeEventListener("storage", handle);
  };
}

export function openPrivacyChoices(): void {
  window.dispatchEvent(new CustomEvent("churnary:open-privacy-choices"));
}
