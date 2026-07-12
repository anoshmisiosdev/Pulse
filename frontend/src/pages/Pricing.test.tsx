import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { CompetitorPriceResearchResponse } from "../lib/api";
import {
  Badge,
  DeliveryPrices,
  ResearchStats,
  formatPrice,
  mergeTenantBusinessName,
  type FormState,
} from "./Pricing";

const summary = {
  sampleSize: 1,
  priceLow: 6.05,
  priceMedian: 6.05,
  priceHigh: 6.05,
  priceAverage: 6.05,
  priceIqr: null,
  currency: "USD",
  recommendedPositioning: "Delivery summary",
  confidence: 0.35,
};

const result = {
  metadata: {
    researchStats: {
      competitorsDiscovered: 3,
      competitorsIncluded: 1,
      sourcesDiscovered: 26,
      sourcesChecked: 7,
      sourcesAccepted: 2,
      corroboratedCompetitors: 1,
    },
  },
} as CompetitorPriceResearchResponse;

describe("pricing research audit UI", () => {
  it("renders corroboration and source-check audit labels", () => {
    const badge = renderToStaticMarkup(<Badge tone="cyan">Corroborated</Badge>);
    const stats = renderToStaticMarkup(<ResearchStats result={result} />);
    expect(badge).toContain("Corroborated");
    expect(stats).toContain("Sources checked");
    expect(stats).toContain(">7<");
  });

  it("labels delivery prices separately", () => {
    const html = renderToStaticMarkup(
      <DeliveryPrices
        summary={summary}
        rows={[
          {
            competitor: {
              name: "Hops & Beans",
              address: "Fremont, CA",
              website: null,
              distanceMiles: 2,
              rating: null,
              reviewCount: null,
              prices: [],
              confidence: 0.8,
              radiusVerified: true,
              exclusionReasons: [],
            },
            price: {
              offerName: "Cappuccino",
              normalizedOfferName: "cappuccino",
              priceMin: 6.05,
              priceMax: 6.05,
              currency: "USD",
              priceType: "fixed",
              sourceUrl: "https://delivery.example/menu",
              sourceTitle: "Delivery menu",
              evidenceText: "Cappuccino $6.05",
              observedAt: "2026-07-09",
              confidence: 0.7,
              confidenceReasons: [],
              matchQuality: "exact",
              priceChannel: "delivery",
              corroborated: false,
              includedInMarketSummary: true,
              freshnessStatus: "current",
              retrievalMethod: "direct_fetch",
              extractionMethod: "json_ld",
              sourceUpdatedAt: "2026-06-01",
            },
          },
        ]}
      />
    );
    expect(html).toContain("Delivery marketplace prices");
    expect(html).toContain("channel-specific markups");
    expect(html).toContain("$6.05");
    expect(html).toContain("Directly retrieved");
    expect(html).toContain("Structured data");
    expect(html).toContain("2026-06-01");
    expect(formatPrice({
      offerName: "Cappuccino",
      normalizedOfferName: "cappuccino",
      priceMin: 3.5,
      priceMax: 3.5,
      currency: "USD",
      priceType: "fixed",
      sourceUrl: "https://example.com/menu",
      sourceTitle: "Menu",
      evidenceText: "Cappuccino $3.50",
      observedAt: "2026-07-10",
      confidence: 0.8,
      confidenceReasons: [],
      matchQuality: "exact",
      priceChannel: "in_store",
      corroborated: false,
      includedInMarketSummary: true,
    })).toBe("$3.50");
  });

  it("uses the tenant name only when the form has not been customized", () => {
    const form = {
      businessName: "",
      businessCategory: "Coffee Shop",
      targetOffer: "Cappuccino",
      address: "3602 Thornton Ave",
      city: "Fremont",
      state: "CA",
      zip: "94536",
      radiusMiles: "10",
      currentPrice: "4.00",
    } satisfies FormState;
    expect(mergeTenantBusinessName(form, "Hayward Coffee Co").businessName).toBe(
      "Hayward Coffee Co"
    );
    expect(
      mergeTenantBusinessName({ ...form, businessName: "Custom Cafe" }, "Tenant").businessName
    ).toBe("Custom Cafe");
  });
});
