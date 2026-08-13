import { API_BASE, authHeaders } from "./api";
import { rememberAcquisition } from "./acquisition";
import { getMarketingPage } from "./marketingPages";
import { hasAnalyticsConsent } from "./privacyPreferences";

export type LandingPath =
  | "/"
  | "/landing"
  | "/coffee-shop-customer-retention"
  | "/salon-customer-retention"
  | "/gym-member-retention"
  | "/customer-churn-risk-calculator";

type LandingEvent =
  | {
      event: "landing_viewed";
      path: LandingPath;
      referrer_host?: string;
      utm_source?: string;
      utm_medium?: string;
      utm_campaign?: string;
      utm_content?: string;
      landing_variant?: string;
    }
  | {
      event: "landing_section_viewed";
      section: "demo" | "pricing" | "waitlist";
    }
  | {
      event: "landing_cta_clicked";
      cta: "join_waitlist" | "live_demo" | "sign_in";
      location: "navbar" | "hero" | "calculator" | "pricing" | "waitlist" | "footer";
      destination: "waitlist" | "demo" | "login";
      plan?: "starter" | "growth" | "pro";
    }
  | {
      event: "landing_demo_interacted";
      control: "vertical" | "regulars" | "monthly_value" | "days";
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

export type LandingMetric = LandingEvent & {
  utm_content?: string;
  landing_variant?: string;
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
    path: (window.location.pathname || "/") as LandingPath,
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
    ...(boundedParam(params, "utm_content")
      ? { utm_content: boundedParam(params, "utm_content") }
      : {}),
    landing_variant:
      boundedParam(params, "landing_variant") || getMarketingPage(window.location.pathname).key,
  };
}

/** Fire-and-forget by design: analytics can never block a visitor action. */
export async function trackLandingEvent(metric: LandingMetric): Promise<void> {
  if (!hasAnalyticsConsent()) return;
  try {
    const acquisition = rememberAcquisition(metric.landing_variant);
    const enriched = {
      ...(acquisition.content ? { utm_content: acquisition.content } : {}),
      ...(acquisition.landing_variant
        ? { landing_variant: acquisition.landing_variant }
        : {}),
      ...metric,
    };
    await fetch(`${API_BASE}/api/analytics/landing`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(enriched),
      keepalive: true,
    });
  } catch {
    // PostHog delivery is best-effort and never becomes a landing-page error.
  }
}
