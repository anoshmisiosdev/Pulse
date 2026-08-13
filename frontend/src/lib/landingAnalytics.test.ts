import { afterEach, describe, expect, it, vi } from "vitest";
import { POSTHOG_DISTINCT_ID_HEADER } from "./api";
import {
  landingViewMetric,
  trackLandingEvent,
} from "./landingAnalytics";
import { waitlist } from "./waitlist";
import { PRIVACY_PREFERENCE_KEY } from "./privacyPreferences";

function allowAnalytics() {
  const local = new Map<string, string>([
    [
      PRIVACY_PREFERENCE_KEY,
      JSON.stringify({
        version: 1,
        analytics: "granted",
        source: "choice",
        updated_at: new Date().toISOString(),
      }),
    ],
  ]);
  const session = new Map<string, string>();
  vi.stubGlobal("window", {
    location: { pathname: "/", search: "" },
    localStorage: {
      getItem: (key: string) => local.get(key) ?? null,
      setItem: (key: string, value: string) => local.set(key, value),
      removeItem: (key: string) => local.delete(key),
    },
    sessionStorage: {
      getItem: (key: string) => session.get(key) ?? null,
      setItem: (key: string, value: string) => session.set(key, value),
      removeItem: (key: string) => session.delete(key),
    },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("landing analytics", () => {
  it("keeps only bounded campaign attribution and the referrer host", () => {
    vi.stubGlobal("window", {
      location: {
        pathname: "/landing",
        search:
          "?utm_source=newsletter&utm_medium=email&utm_content=founder_a&utm_campaign=" + "x".repeat(150),
      },
    });
    vi.stubGlobal("document", {
      referrer: "https://search.example/results?q=sensitive-query",
    });

    const metric = landingViewMetric();

    expect(metric).toEqual({
      event: "landing_viewed",
      path: "/landing",
      referrer_host: "search.example",
      utm_source: "newsletter",
      utm_medium: "email",
      utm_campaign: "x".repeat(100),
      utm_content: "founder_a",
      landing_variant: "general",
    });
  });

  it("sends a stable identity header and only the declared metric fields", async () => {
    allowAnalytics();
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await trackLandingEvent({
      event: "landing_demo_interacted",
      control: "monthly_value",
      vertical: "cafe",
      risk_band: "healthy",
    });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = options.headers as Record<string, string>;
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    expect(url).toContain("/api/analytics/landing");
    expect(headers[POSTHOG_DISTINCT_ID_HEADER]).toBeTruthy();
    expect(options.keepalive).toBe(true);
    expect(body).toEqual({
      event: "landing_demo_interacted",
      control: "monthly_value",
      vertical: "cafe",
      risk_band: "healthy",
      landing_variant: "general",
    });
    expect(body.email).toBeUndefined();
    expect(body.name).toBeUndefined();
  });

  it("isolates network failures from visitor actions", async () => {
    allowAnalytics();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));

    await expect(
      trackLandingEvent({
        event: "landing_cta_clicked",
        cta: "join_waitlist",
        location: "hero",
        destination: "waitlist",
      })
    ).resolves.toBeUndefined();
  });

});

describe("waitlist analytics identity", () => {
  it("uses the same anonymous ID on the conversion request", async () => {
    allowAnalytics();
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, already_joined: false }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    await waitlist.join({ name: "Dana", email: "dana@example.com" });

    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers[POSTHOG_DISTINCT_ID_HEADER]).toBeTruthy();
  });
});
