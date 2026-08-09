import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, formatCurrency, POSTHOG_DISTINCT_ID_HEADER } from "./api";
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

describe("formatCurrency", () => {
  it("formats whole dollars with no cents", () => {
    expect(formatCurrency(2100)).toBe("$2,100");
  });

  it("rounds to the nearest dollar", () => {
    expect(formatCurrency(155901.49)).toBe("$155,901");
  });

  it("handles zero", () => {
    expect(formatCurrency(0)).toBe("$0");
  });
});

describe("analytics identity", () => {
  it("sends one stable anonymous ID with API requests", async () => {
    allowAnalytics();
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            business_name: "Test",
            vertical: "other",
            summary: {
              total_customers: 0,
              high_risk: 0,
              med_risk: 0,
              low_risk: 0,
              revenue_at_risk: 0,
              avg_days_away: 0,
              revenue_series: [],
            },
            customers: [],
            warnings: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.demo(1);
    await api.demo(2);

    const firstHeaders = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    const secondHeaders = fetchMock.mock.calls[1][1].headers as Record<string, string>;
    expect(firstHeaders[POSTHOG_DISTINCT_ID_HEADER]).toBeTruthy();
    expect(secondHeaders[POSTHOG_DISTINCT_ID_HEADER]).toBe(
      firstHeaders[POSTHOG_DISTINCT_ID_HEADER]
    );
  });

  it("omits optional identity headers before consent", async () => {
    vi.stubGlobal("window", {
      localStorage: { getItem: () => null },
      sessionStorage: { getItem: () => null },
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "empty" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.demo(1);

    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers[POSTHOG_DISTINCT_ID_HEADER]).toBeUndefined();
  });
});

describe("pricing API failures", () => {
  it("preserves the failed stage and retryability from a structured 503", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            message: "Business address could not be geocoded.",
            errorCode: "PRICING_GEOCODE_NOT_FOUND",
            stage: "geocode",
            retryable: false,
          },
        }),
        { status: 503, headers: { "Content-Type": "application/json" } }
      )
    ));

    const failure = api.researchCompetitorPrices({
      businessCategory: "Coffee Shop",
      targetOffer: "Cappuccino",
      location: { city: "Fremont", state: "CA" },
    });

    await expect(failure).rejects.toBeInstanceOf(ApiError);
    await expect(failure).rejects.toMatchObject({
      status: 503,
      code: "PRICING_GEOCODE_NOT_FOUND",
      stage: "geocode",
      retryable: false,
    });
  });
});
