import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { CompetitorPriceResearchResponse } from "../lib/api";
import { createSamplePricingPortfolio } from "../lib/pricingSample";
import MarketSummary from "../components/pricing/MarketSummary";
import PricingTable from "../components/pricing/PricingTable";
import { buildCompetitorRows } from "../hooks/useCompetitorPricing";
import {
  Badge,
  DeliveryPrices,
  ProductPricingCard,
  PricingHistory,
  ResearchStats,
  buildPricingCsv,
  deriveTenantPricingDefaults,
  formatPrice,
  getOfferMatchCoverage,
  getMarketPosition,
  mergeTenantBusinessName,
  parseMenuItems,
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
        requestedOffer="Cappuccino"
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
    expect(html).toContain("Matched item");
    expect(html).toContain("Requested: Cappuccino");
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

  it("derives tenant defaults and renders a material price alert", () => {
    const defaults = deriveTenantPricingDefaults({
      businessName: "Northstar Gym",
      vertical: "fitness",
      favoriteItems: ["Monthly membership", "Day pass", "Monthly membership"],
      locationLabel: "Oakland, CA",
    });
    expect(defaults.businessCategory).toBe("Gym");
    expect(defaults.targetOffer).toBe("Monthly membership");
    expect(defaults.city).toBe("Oakland");
    expect(defaults.state).toBe("CA");

    const html = renderToStaticMarkup(
      <PricingHistory
        history={[
          {
            id: "run-1",
            targetOffer: "Monthly membership",
            businessCategory: "Gym",
            generatedAt: "2026-07-12T12:00:00Z",
            priceMedian: 59,
            sampleSize: 3,
            confidence: 0.7,
            changePercent: 7.3,
          },
        ]}
      />
    );
    expect(html).toContain("Pricing trend");
    expect(html).toContain("Alert:");
    expect(html).toContain("+7.3%");
  });

  it("exports source-backed observations as CSV", () => {
    const csv = buildPricingCsv({
      status: "complete",
      query: {
        businessCategory: "Coffee Shop",
        targetOffer: "Cappuccino",
        locationLabel: "Fremont, CA",
        radiusMiles: 5,
      },
      competitors: [
        {
          name: "Hops & Beans",
          address: "Fremont, CA",
          website: null,
          distanceMiles: 1,
          rating: null,
          reviewCount: null,
          confidence: 0.8,
          radiusVerified: true,
          exclusionReasons: [],
          prices: [
            {
              offerName: "Cappuccino",
              normalizedOfferName: "cappuccino",
              priceMin: 4.75,
              priceMax: 4.75,
              currency: "USD",
              priceType: "fixed",
              sourceUrl: "https://example.com/menu",
              sourceTitle: "Menu",
              evidenceText: "Cappuccino $4.75",
              observedAt: "2026-07-12",
              confidence: 0.8,
              confidenceReasons: [],
              matchQuality: "exact",
              priceChannel: "in_store",
              corroborated: true,
              includedInMarketSummary: true,
            },
          ],
        },
      ],
      marketSummary: summary,
      estimateSummary: null,
      channelSummaries: null,
      issues: [],
      quota: null,
      warnings: [],
      metadata: {
        modelsUsed: [],
        groundingUsed: { googleSearch: false, googleMaps: false, urlContext: false },
        generatedAt: "2026-07-12T12:00:00Z",
        cached: false,
        durationMs: 100,
        researchStats: {
          competitorsDiscovered: 1,
          competitorsIncluded: 1,
          sourcesDiscovered: 1,
          sourcesChecked: 1,
          sourcesAccepted: 1,
          corroboratedCompetitors: 1,
        },
        stages: [],
        providerCostUsd: 0,
        pipelineVersion: "v2-test",
      },
    });
    expect(csv).toContain('"Hops & Beans"');
    expect(csv).toContain('"requested_offer"');
    expect(csv).toContain('"matched_offer"');
    expect(csv).toContain('"match_reason"');
    expect(csv).toContain('"4.75"');
    expect(csv).toContain('"https://example.com/menu"');
  });

  it("turns a pasted menu into deduplicated research items", () => {
    expect(
      parseMenuItems(`
        1. Cappuccino — $4.75
        Cold brew, 5.25
        • Blueberry scone
        cappuccino — $4.95
      `)
    ).toEqual([
      { name: "Cappuccino", price: "4.75" },
      { name: "Cold brew", price: "5.25" },
      { name: "Blueberry scone", price: "" },
    ]);
  });

  it("classifies each product's price position against its local median", () => {
    const priced = {
      query: {
        businessCategory: "Coffee Shop",
        targetOffer: "Cappuccino",
        locationLabel: "Fremont, CA",
        radiusMiles: 5,
        currentPrice: 4.5,
      },
      marketSummary: { ...summary, priceMedian: 5 },
    } as CompetitorPriceResearchResponse;

    expect(getMarketPosition(priced)).toMatchObject({ key: "below", label: "10% below" });
  });

  it("builds a full eight-product sample café with chart-ready market history", () => {
    const sample = createSamplePricingPortfolio(new Date("2026-07-15T18:00:00Z"));

    expect(sample.results).toHaveLength(8);
    expect(sample.results.map((item) => item.query.targetOffer)).toEqual([
      "Espresso",
      "Cappuccino",
      "Vanilla Latte",
      "Cold Brew",
      "Matcha Latte",
      "Chai Latte",
      "Avocado Toast",
      "Blueberry Muffin",
    ]);
    expect(sample.results.every((item) => item.competitors.length === 4)).toBe(true);
    expect(sample.results.every((item) => item.query.currentPrice !== null)).toBe(true);
    expect(sample.history).toHaveLength(32);
  });

  it("makes the requested and actual close-match item explicit without mixing benchmarks", () => {
    const sample = createSamplePricingPortfolio(new Date("2026-07-15T18:00:00Z"));
    const blueberry = sample.results.find(
      (item) => item.query.targetOffer === "Blueberry Muffin"
    );
    expect(blueberry).toBeDefined();
    if (!blueberry) return;

    const coverage = getOfferMatchCoverage(blueberry);
    expect(coverage).toMatchObject({ exactBusinesses: 3, closeBusinesses: 1 });
    expect(coverage.closeMatches.map((match) => match.offerName)).toEqual([
      "Mixed Berry Muffin",
    ]);
    expect(blueberry.marketSummary).toMatchObject({ sampleSize: 3, priceMedian: 3.95 });

    const card = renderToStaticMarkup(
      <ProductPricingCard
        result={blueberry}
        history={[]}
        expanded={false}
        loading={false}
        sample
        onToggle={() => undefined}
        onRefresh={() => undefined}
        onExport={() => undefined}
      />
    );
    expect(card).toContain("Close matches shown separately");
    expect(card).toContain("Mixed Berry Muffin");
    expect(card).toContain("never included in the exact market median");

    const table = renderToStaticMarkup(
      <PricingTable result={blueberry} rows={buildCompetitorRows(blueberry)} />
    );
    expect(table).toContain("Matched item");
    expect(table).toContain("Mixed Berry Muffin");
    expect(table).toContain("Requested: Blueberry Muffin");
    expect(table).toContain("Close equivalent");
    expect(table).toContain("55% name match");
    expect(table).toContain("excluded from exact benchmark");
  });

  it("keeps verified-peer estimates visibly separate from exact observations", () => {
    const base = createSamplePricingPortfolio(new Date("2026-07-15T18:00:00Z")).results[0];
    const estimated: CompetitorPriceResearchResponse = {
      ...base,
      status: "partial",
      marketSummary: {
        ...base.marketSummary,
        sampleSize: 1,
        priceLow: null,
        priceMedian: null,
        priceHigh: null,
        priceAverage: null,
        priceIqr: null,
        confidence: 0,
      },
      estimateSummary: {
        method: "verified_peer_distribution",
        sampleSize: 3,
        priceLow: 3.9,
        priceMedian: 4.1,
        priceHigh: 4.3,
        currency: "USD",
        maxAgeDays: 180,
        basis: "close_equivalent",
      },
    };

    const html = renderToStaticMarkup(<MarketSummary result={estimated} />);
    expect(html).toContain("Exact observed benchmark");
    expect(html).toContain("Not established");
    expect(html).toContain("Verified-peer estimate · not an observed price");
    expect(html).toContain("never mixed into the exact market summary");
  });
});
