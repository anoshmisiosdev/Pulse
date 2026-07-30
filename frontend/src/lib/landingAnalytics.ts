import { API_BASE, authHeaders } from "./api";
import { hasAnalyticsConsent } from "./privacyPreferences";

export type LandingMetric =
  | {
      event: "landing_viewed";
      path: "/" | "/landing";
      referrer_host?: string;
      utm_source?: string;
      utm_medium?: string;
      utm_campaign?: string;
    }
  | {
      event: "landing_section_viewed";
      section: "demo" | "pricing" | "waitlist";
    }
  | {
      event: "landing_cta_clicked";
      cta: "join_waitlist" | "live_demo" | "sign_in";
      location: "navbar" | "hero" | "pricing" | "waitlist" | "footer";
      destination: "waitlist" | "demo" | "login";
      plan?: "starter" | "growth" | "pro";
    }
  | {
      event: "landing_demo_interacted";
      control: "vertical" | "days";
      vertical: "cafe" | "fitness" | "salon";
      risk_band: "healthy" | "watch" | "needs_attention";
    }
  | { event: "landing_waitlist_started" }
  | {
      event: "landing_waitlist_validation_failed";
      reason: "missing_name" | "invalid_email";
    }
  | {
      event: "landing_waitlist_submit_failed";
      reason: "request_failed";
    };

function boundedParam(params: URLSearchParams, name: string): string | undefined {
  const value = params.get(name)?.trim();
  return value ? value.slice(0, 100) : undefined;
}

/** Build attribution without sending the full URL or referrer path/query. */
export function landingViewMetric(): Extract<LandingMetric, { event: "landing_viewed" }> {
  const params = new URLSearchParams(window.location.search);
  let referrerHost: string | undefined;
  if (document.referrer) {
    try {
      referrerHost = new URL(document.referrer).hostname.slice(0, 253) || undefined;
    } catch {
      // An invalid referrer should never break page analytics.
    }
  }

  return {
    event: "landing_viewed",
    path: window.location.pathname === "/landing" ? "/landing" : "/",
    ...(referrerHost ? { referrer_host: referrerHost } : {}),
    ...(boundedParam(params, "utm_source")
      ? { utm_source: boundedParam(params, "utm_source") }
      : {}),
    ...(boundedParam(params, "utm_medium")
      ? { utm_medium: boundedParam(params, "utm_medium") }
      : {}),
    ...(boundedParam(params, "utm_campaign")
      ? { utm_campaign: boundedParam(params, "utm_campaign") }
      : {}),
  };
}

/** Fire-and-forget by design: analytics can never block a visitor action. */
export async function trackLandingEvent(metric: LandingMetric): Promise<void> {
  if (!hasAnalyticsConsent()) return;
  try {
    await fetch(`${API_BASE}/api/analytics/landing`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(metric),
      keepalive: true,
    });
  } catch {
    // PostHog delivery is best-effort and never becomes a landing-page error.
  }
}
