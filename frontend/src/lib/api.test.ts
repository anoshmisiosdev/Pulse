import { afterEach, describe, expect, it, vi } from "vitest";
import { api, formatCurrency, POSTHOG_DISTINCT_ID_HEADER } from "./api";

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
});
