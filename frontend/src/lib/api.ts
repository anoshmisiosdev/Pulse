// Typed client for the Pulse API. Mirrors backend/app/schemas/api.py.

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export type Band = "low" | "med" | "high";
export type Segment =
  | "needs_attention"
  | "slipping_away"
  | "keep_an_eye_on"
  | "regulars"
  | "new";
export type Pattern =
  | "fading_away"
  | "stopped_suddenly"
  | "group_left"
  | "not_enough_data"
  | null;

export interface CustomerRisk {
  customer_id: string;
  name: string;
  email: string | null;
  phone: string | null;
  score: number;
  band: Band;
  reasons: string[];
  estimated_annual_value: number;
  days_since_last_visit: number | null;
  last_visit: string | null;
  visit_count: number;
  total_spend: number;
  segment: Segment;
  pattern: Pattern;
  confidence: string;
  trend_pct: number;
  favorite_item: string | null;
}

export interface PortfolioSummary {
  total_customers: number;
  high_risk: number;
  med_risk: number;
  low_risk: number;
  revenue_at_risk: number;
  avg_days_away: number;
  revenue_series: { month: string; amount: number }[];
}

export interface Connection {
  source: string;
  status: string;
  last_synced_at: string | null;
}

export interface Portfolio {
  business_name: string;
  vertical: string;
  summary: PortfolioSummary;
  customers: CustomerRisk[];
  warnings: string[];
  /** "empty" = no data source connected yet; "ready" = tenant data loaded. */
  status?: "empty" | "ready";
  connections?: Connection[];
  location_label?: string | null;
}

export interface GeneratedCopy {
  channel: string;
  subject: string | null;
  body: string;
  generated_by: "claude" | "fallback";
  model: string | null;
}

export interface AuthUser {
  user_id: string;
  email: string | null;
  business_id: string;
  business_name: string;
  role: string;
}

export interface CompetitorPriceResearchInput {
  businessName?: string;
  businessWebsite?: string;
  businessPhone?: string;
  businessCategory: string;
  targetOffer: string;
  location: {
    address?: string;
    city?: string;
    state?: string;
    zip?: string;
    country?: string;
    latitude?: number;
    longitude?: number;
  };
  radiusMiles?: number;
  maxCompetitors?: number;
  maxSourcesPerCompetitor?: number;
  currentPrice?: number | null;
}

export interface CompetitorPrice {
  offerName: string;
  normalizedOfferName: string;
  priceMin: number | null;
  priceMax: number | null;
  currency: string;
  priceType: string;
  sourceUrl: string;
  sourceTitle: string | null;
  evidenceText: string;
  observedAt: string;
  confidence: number;
  confidenceReasons: string[];
  matchQuality: "exact" | "close" | "weak";
  priceChannel: "in_store" | "delivery" | "unknown";
  corroborated: boolean;
  includedInMarketSummary: boolean;
  sourcePublishedAt?: string | null;
  sourceUpdatedAt?: string | null;
  verifiedAt?: string | null;
  retrievalMethod?: "direct_fetch" | "perplexity_content" | "search_snippet" | "none";
  extractionMethod?: "json_ld" | "visible_text" | "search_snippet" | "sonar" | "tokenmart" | "method_consensus";
  freshnessStatus?: "current" | "stale" | "unknown" | "expired";
  needsReview?: boolean;
}

export interface CompetitorPriceCompetitor {
  name: string;
  address: string | null;
  website: string | null;
  distanceMiles: number | null;
  rating: number | null;
  reviewCount: number | null;
  prices: CompetitorPrice[];
  confidence: number;
  radiusVerified: boolean;
  exclusionReasons: string[];
  placeId?: string | null;
  discoveryProvider?: "google_places" | "perplexity";
}

export interface CompetitorPriceMarketSummary {
  sampleSize: number;
  priceLow: number | null;
  priceMedian: number | null;
  priceHigh: number | null;
  priceAverage: number | null;
  priceIqr: number | null;
  currency: string;
  recommendedPositioning: string;
  confidence: number;
}

export interface CompetitorPriceResearchResponse {
  query: {
    businessCategory: string;
    targetOffer: string;
    locationLabel: string;
    radiusMiles: number;
  };
  competitors: CompetitorPriceCompetitor[];
  marketSummary: CompetitorPriceMarketSummary;
  channelSummaries: {
    inStore: CompetitorPriceMarketSummary;
    delivery: CompetitorPriceMarketSummary;
  } | null;
  warnings: string[];
  metadata: {
    modelsUsed: string[];
    groundingUsed: {
      googleSearch: boolean;
      googleMaps: boolean;
      urlContext: boolean;
      perplexitySearch?: boolean;
      perplexitySonar?: boolean;
      sonarExtraction?: boolean;
      sonarResearch?: boolean;
      deepseekExtraction?: boolean;
      deepseekResearch?: boolean;
      googleGeocoding?: boolean;
      googlePlaces?: boolean;
    };
    generatedAt: string;
    cached: boolean;
    durationMs: number | null;
    researchStats: {
      competitorsDiscovered: number;
      competitorsIncluded: number;
      sourcesDiscovered: number;
      sourcesChecked: number;
      sourcesAccepted: number;
      corroboratedCompetitors: number;
      pagesFetched?: number;
      pagesParsed?: number;
      deterministicExtractions?: number;
      aiExtractions?: number;
      staleExclusions?: number;
      conflictingExclusions?: number;
    };
    providerStats?: {
      googlePlacesRequests: number;
      googleGeocodingRequests: number;
      perplexityRequests: number;
      perplexityModel?: string | null;
      perplexityUsage?: Record<string, number>;
      pageFetchRequests: number;
      tokenmartRequests: number;
      durationMsByProvider: Record<string, number>;
      tokenmartGateway?: string | null;
      tokenmartRequestedModel?: string | null;
      tokenmartReturnedModels?: string[];
      tokenmartUsage?: Record<string, number>;
    };
  };
}

export interface CompetitorPriceHistoryItem {
  id: string;
  targetOffer: string;
  businessCategory: string;
  generatedAt: string;
  priceMedian: number | null;
  sampleSize: number;
  confidence: number;
  changePercent: number | null;
}

export interface CompetitorPriceWatch {
  enabled: boolean;
  intervalHours: number;
  request: CompetitorPriceResearchInput;
  lastRunAt: string | null;
  nextRunAt: string;
}

// The current Supabase access token, kept in sync by AuthContext.
let accessToken: string | null = null;
export function setAccessToken(t: string | null): void {
  accessToken = t;
}

function authHeaders(): Record<string, string> {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  async me(): Promise<AuthUser> {
    const res = await fetch(`${BASE}/api/auth/me`, { headers: authHeaders() });
    return asJson<AuthUser>(res);
  },

  /** The tenant's persisted dashboard data. status:"empty" → route to /setup. */
  async portfolio(): Promise<Portfolio> {
    const res = await fetch(`${BASE}/api/portfolio`, { headers: authHeaders() });
    return asJson<Portfolio>(res);
  },

  /** Connect Stripe/Square, pull all customer data, persist it for this tenant. */
  async connect(input: {
    provider: "stripe" | "square";
    credential: string;
    environment?: "production" | "sandbox";
    vertical: string;
    business_name: string;
  }): Promise<Portfolio> {
    const res = await fetch(`${BASE}/api/integrations/connect`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(input),
    });
    return asJson<Portfolio>(res);
  },

  /** Persisting CSV import (unlike previewCsv, which is in-memory only). */
  async importCsv(file: File, vertical: string, businessName: string): Promise<Portfolio> {
    const form = new FormData();
    form.append("file", file);
    const qs = new URLSearchParams({ vertical, business_name: businessName });
    const res = await fetch(`${BASE}/api/integrations/csv/import?${qs}`, {
      method: "POST",
      body: form,
      headers: authHeaders(),
    });
    return asJson<Portfolio>(res);
  },

  /** Which providers can show a "Connect with …" button. */
  async oauthAvailability(): Promise<{ stripe: boolean; square: boolean }> {
    const res = await fetch(`${BASE}/api/integrations/oauth/availability`);
    return asJson(res);
  },

  /** Get the provider authorize URL, then send the browser there. */
  async oauthStart(
    provider: "stripe" | "square",
    vertical: string,
    businessName: string
  ): Promise<string> {
    const qs = new URLSearchParams({
      vertical,
      business_name: businessName,
      return_to: window.location.origin,
    });
    const res = await fetch(`${BASE}/api/integrations/oauth/${provider}/start?${qs}`, {
      headers: authHeaders(),
    });
    const data = await asJson<{ url: string }>(res);
    return data.url;
  },

  /** Re-pull from every connected provider using the stored token. */
  async resync(): Promise<Portfolio> {
    const res = await fetch(`${BASE}/api/integrations/sync`, {
      method: "POST",
      headers: authHeaders(),
    });
    return asJson<Portfolio>(res);
  },

  async previewCsv(file: File, vertical: string, businessName: string): Promise<Portfolio> {
    const form = new FormData();
    form.append("file", file);
    const qs = new URLSearchParams({ vertical, business_name: businessName });
    const res = await fetch(`${BASE}/api/integrations/csv/preview?${qs}`, {
      method: "POST",
      body: form,
      headers: authHeaders(),
    });
    return asJson<Portfolio>(res);
  },

  async demo(count = 50): Promise<Portfolio> {
    const res = await fetch(`${BASE}/api/integrations/demo?count=${count}`, {
      method: "POST",
      headers: authHeaders(),
    });
    return asJson<Portfolio>(res);
  },

  async generateCampaign(input: {
    business_name: string;
    business_type: string;
    customer_name: string;
    channel: "email" | "sms";
    incentive?: string;
    risk_reasons: string[];
    history_summary?: string;
  }): Promise<GeneratedCopy> {
    const res = await fetch(`${BASE}/api/campaigns/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(input),
    });
    return asJson<GeneratedCopy>(res);
  },

  async researchCompetitorPrices(
    input: CompetitorPriceResearchInput
  ): Promise<CompetitorPriceResearchResponse> {
    const res = await fetch(`${BASE}/api/competitor-prices/research`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(input),
    });
    return asJson<CompetitorPriceResearchResponse>(res);
  },

  async latestCompetitorPrices(): Promise<CompetitorPriceResearchResponse | null> {
    const res = await fetch(`${BASE}/api/competitor-prices/latest`, {
      headers: authHeaders(),
    });
    return asJson<CompetitorPriceResearchResponse | null>(res);
  },

  async competitorPriceHistory(limit = 12): Promise<CompetitorPriceHistoryItem[]> {
    const res = await fetch(`${BASE}/api/competitor-prices/history?limit=${limit}`, {
      headers: authHeaders(),
    });
    return asJson<CompetitorPriceHistoryItem[]>(res);
  },

  async competitorPriceWatch(): Promise<CompetitorPriceWatch | null> {
    const res = await fetch(`${BASE}/api/competitor-prices/watch`, {
      headers: authHeaders(),
    });
    return asJson<CompetitorPriceWatch | null>(res);
  },

  async saveCompetitorPriceWatch(input: {
    enabled: boolean;
    intervalHours: number;
    request: CompetitorPriceResearchInput;
  }): Promise<CompetitorPriceWatch> {
    const res = await fetch(`${BASE}/api/competitor-prices/watch`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(input),
    });
    return asJson<CompetitorPriceWatch>(res);
  },

  templateUrl(): string {
    return `${BASE}/api/integrations/csv/template`;
  },
};

export function formatCurrency(n: number, withCents = false): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: withCents ? 2 : 0,
  }).format(n);
}

export function relativeDays(days: number | null): string {
  if (days === null) return "never";
  if (days <= 1) return "today";
  if (days < 14) return `${days} days ago`;
  if (days < 60) return `${Math.round(days / 7)} weeks ago`;
  return `${Math.round(days / 30)} months ago`;
}
