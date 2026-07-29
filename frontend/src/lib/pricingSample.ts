import type {
  CompetitorPrice,
  CompetitorPriceCompetitor,
  CompetitorPriceHistoryItem,
  CompetitorPriceMarketSummary,
  CompetitorPriceResearchResponse,
} from "./api";

type SampleProduct = {
  name: string;
  currentPrice: number;
  competitorPrices: [number, number, number, number];
  trend: [number, number, number, number];
  confidence: number;
};

const SAMPLE_PRODUCTS: SampleProduct[] = [
  {
    name: "Espresso",
    currentPrice: 3.5,
    competitorPrices: [3.5, 3.75, 3.75, 4],
    trend: [3.5, 3.55, 3.65, 3.75],
    confidence: 0.91,
  },
  {
    name: "Cappuccino",
    currentPrice: 5.25,
    competitorPrices: [4.85, 5.05, 5.25, 5.45],
    trend: [4.95, 5, 5.1, 5.15],
    confidence: 0.94,
  },
  {
    name: "Vanilla Latte",
    currentPrice: 6.25,
    competitorPrices: [5.5, 5.75, 5.95, 6.25],
    trend: [5.55, 5.65, 5.75, 5.85],
    confidence: 0.88,
  },
  {
    name: "Cold Brew",
    currentPrice: 5,
    competitorPrices: [4.95, 5.25, 5.45, 5.75],
    trend: [5.05, 5.15, 5.2, 5.35],
    confidence: 0.9,
  },
  {
    name: "Matcha Latte",
    currentPrice: 6.5,
    competitorPrices: [5.95, 6.15, 6.35, 6.65],
    trend: [5.95, 6.05, 6.15, 6.25],
    confidence: 0.86,
  },
  {
    name: "Chai Latte",
    currentPrice: 5.75,
    competitorPrices: [5.4, 5.7, 5.9, 6.2],
    trend: [5.5, 5.6, 5.7, 5.8],
    confidence: 0.89,
  },
  {
    name: "Avocado Toast",
    currentPrice: 10.5,
    competitorPrices: [10.5, 11.5, 12, 13],
    trend: [11.25, 11.4, 11.55, 11.75],
    confidence: 0.84,
  },
  {
    name: "Blueberry Muffin",
    currentPrice: 4.25,
    competitorPrices: [3.75, 3.95, 4.15, 4.4],
    trend: [3.85, 3.9, 4, 4.05],
    confidence: 0.87,
  },
];

const SAMPLE_COMPETITORS = [
  { name: "Juniper Café", address: "1428 Hawthorne Blvd, Portland, OR", distance: 0.8 },
  { name: "Cedar & Steam", address: "907 Division St, Portland, OR", distance: 1.4 },
  { name: "North Loop Coffee", address: "611 Belmont St, Portland, OR", distance: 2.1 },
  { name: "The Daily Grind", address: "2384 Burnside St, Portland, OR", distance: 2.7 },
];

export function createSamplePricingPortfolio(now = new Date()): {
  results: CompetitorPriceResearchResponse[];
  history: CompetitorPriceHistoryItem[];
} {
  const results = SAMPLE_PRODUCTS.map((product, productIndex) =>
    buildProductResult(product, productIndex, now)
  );
  const history = SAMPLE_PRODUCTS.flatMap((product, productIndex) =>
    buildProductHistory(product, productIndex, now)
  ).sort((a, b) => new Date(b.generatedAt).getTime() - new Date(a.generatedAt).getTime());
  return { results, history };
}

function buildProductResult(
  product: SampleProduct,
  productIndex: number,
  now: Date
): CompetitorPriceResearchResponse {
  const prices = [...product.competitorPrices];
  const summary = buildSummary(product, prices);
  const generatedAt = new Date(now.getTime() - productIndex * 90_000).toISOString();
  return {
    query: {
      businessCategory: "Coffee Shop",
      targetOffer: product.name,
      locationLabel: "Portland, OR",
      radiusMiles: 5,
      currentPrice: product.currentPrice,
    },
    competitors: SAMPLE_COMPETITORS.map((competitor, competitorIndex) =>
      buildCompetitor(product, productIndex, competitorIndex, competitor, generatedAt)
    ),
    marketSummary: summary,
    channelSummaries: {
      inStore: summary,
      delivery: emptySummary("No delivery marketplace prices were included in this preview."),
    },
    warnings: [],
    metadata: {
      modelsUsed: ["sample-market-model"],
      groundingUsed: {
        googleSearch: true,
        googleMaps: true,
        urlContext: true,
        googlePlaces: true,
        perplexitySearch: true,
      },
      generatedAt,
      cached: false,
      durationMs: 18_400 + productIndex * 730,
      researchStats: {
        competitorsDiscovered: 6,
        competitorsIncluded: 4,
        sourcesDiscovered: 13,
        sourcesChecked: 9,
        sourcesAccepted: 7,
        corroboratedCompetitors: 3,
        pagesFetched: 8,
        pagesParsed: 7,
        deterministicExtractions: 5,
        aiExtractions: 2,
        staleExclusions: 1,
        conflictingExclusions: 0,
      },
      providerStats: {
        googlePlacesRequests: 1,
        googleGeocodingRequests: 1,
        perplexityRequests: 2,
        perplexityModel: "sample",
        perplexityUsage: {},
        pageFetchRequests: 8,
        tokenmartRequests: 0,
        durationMsByProvider: {},
      },
    },
  };
}

function buildCompetitor(
  product: SampleProduct,
  productIndex: number,
  competitorIndex: number,
  competitor: (typeof SAMPLE_COMPETITORS)[number],
  observedAt: string
): CompetitorPriceCompetitor {
  const price = product.competitorPrices[competitorIndex];
  const slug = competitor.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
  return {
    name: competitor.name,
    address: competitor.address,
    website: `https://example.com/${slug}`,
    distanceMiles: competitor.distance,
    rating: 4.5 + (competitorIndex % 3) * 0.1,
    reviewCount: 184 + competitorIndex * 137,
    prices: [buildObservation(product, productIndex, competitorIndex, price, slug, observedAt)],
    confidence: 0.84 + (competitorIndex % 3) * 0.04,
    radiusVerified: true,
    exclusionReasons: [],
    placeId: `sample-place-${competitorIndex + 1}`,
    discoveryProvider: "google_places",
  };
}

function buildObservation(
  product: SampleProduct,
  productIndex: number,
  competitorIndex: number,
  price: number,
  competitorSlug: string,
  observedAt: string
): CompetitorPrice {
  const sourceDate = new Date(new Date(observedAt).getTime() - (competitorIndex + 1) * 86_400_000)
    .toISOString()
    .slice(0, 10);
  return {
    offerName: product.name,
    normalizedOfferName: product.name.toLowerCase(),
    priceMin: price,
    priceMax: price,
    currency: "USD",
    priceType: "fixed",
    sourceUrl: `https://example.com/${competitorSlug}/menu#item-${productIndex + 1}`,
    sourceTitle: `${SAMPLE_COMPETITORS[competitorIndex].name} · Current menu`,
    evidenceText: `${product.name} — $${price.toFixed(2)}`,
    observedAt,
    confidence: 0.84 + (competitorIndex % 3) * 0.04,
    confidenceReasons: ["Exact menu item match", "Current first-party menu", "Price shown explicitly"],
    matchQuality: "exact",
    priceChannel: "in_store",
    corroborated: competitorIndex !== 3,
    includedInMarketSummary: true,
    sourceUpdatedAt: sourceDate,
    verifiedAt: observedAt,
    retrievalMethod: "direct_fetch",
    extractionMethod: competitorIndex % 2 === 0 ? "json_ld" : "visible_text",
    freshnessStatus: "current",
    needsReview: false,
  };
}

function buildSummary(
  product: SampleProduct,
  prices: number[]
): CompetitorPriceMarketSummary {
  const ordered = [...prices].sort((a, b) => a - b);
  const median = (ordered[1] + ordered[2]) / 2;
  const delta = (product.currentPrice - median) / median;
  const positioning =
    delta < -0.05
      ? "Your current price is below the observed local median, leaving room for a thoughtful increase."
      : delta > 0.05
        ? "Your current price carries a premium versus the observed local median."
        : "Your current price sits comfortably within the local market range.";
  return {
    sampleSize: prices.length,
    priceLow: ordered[0],
    priceMedian: Number(median.toFixed(2)),
    priceHigh: ordered[ordered.length - 1],
    priceAverage: Number((prices.reduce((total, value) => total + value, 0) / prices.length).toFixed(2)),
    priceIqr: Number((ordered[2] - ordered[1]).toFixed(2)),
    currency: "USD",
    recommendedPositioning: positioning,
    confidence: product.confidence,
  };
}

function emptySummary(message: string): CompetitorPriceMarketSummary {
  return {
    sampleSize: 0,
    priceLow: null,
    priceMedian: null,
    priceHigh: null,
    priceAverage: null,
    priceIqr: null,
    currency: "USD",
    recommendedPositioning: message,
    confidence: 0,
  };
}

function buildProductHistory(
  product: SampleProduct,
  productIndex: number,
  now: Date
): CompetitorPriceHistoryItem[] {
  return product.trend.map((median, trendIndex) => {
    const previous = trendIndex === 0 ? null : product.trend[trendIndex - 1];
    const generatedAt = new Date(
      now.getTime() - (product.trend.length - 1 - trendIndex) * 7 * 86_400_000 - productIndex * 90_000
    ).toISOString();
    return {
      id: `sample-${productIndex + 1}-${trendIndex + 1}`,
      targetOffer: product.name,
      businessCategory: "Coffee Shop",
      generatedAt,
      priceMedian: median,
      sampleSize: 4,
      confidence: Math.max(0.68, product.confidence - (product.trend.length - 1 - trendIndex) * 0.04),
      changePercent: previous === null ? null : Number((((median - previous) / previous) * 100).toFixed(1)),
    };
  });
}
