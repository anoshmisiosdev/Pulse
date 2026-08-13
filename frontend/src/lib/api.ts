// Typed client for the Pulse API. Mirrors backend/app/schemas/api.py.

import {
  ANALYTICS_ID_STORAGE_KEY,
  PRIVACY_PREFERENCE_EVENT,
  VISITOR_SESSION_STORAGE_KEY,
  hasAnalyticsConsent,
} from "./privacyPreferences";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";
export const POSTHOG_DISTINCT_ID_HEADER = "X-PostHog-Distinct-Id";
export const VISITOR_SESSION_ID_HEADER = "X-Visitor-Session-Id";

// localStorage flag: owner chose "skip setup" — lives here (not Setup.tsx) so the
// route gate can read it without pulling the lazy-loaded Setup page into the main chunk.
export const SETUP_SKIPPED_KEY = "pulse_setup_skipped";

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

/** What Churnary thinks the owner should actually do next. Deterministic, derived
 * from the customer's own signals — see backend services/activity.recommend_action. */
export type RecommendedAction =
  | "wait"
  | "watch"
  | "welcome"
  | "email"
  | "offer"
  | "owner_call";

export interface CustomerRisk {
  /** Dedupe identity (email/phone). Stable, but NOT a database id. */
  customer_id: string;
  /** The real customers.id row — null on the demo/CSV-preview paths, which
   * persist nothing. Endpoints needing a row (the timeline) require this. */
  db_customer_id: string | null;
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
  /** Explainable inverse of churn risk; not a calibrated probability. */
  return_likelihood: number;
  expected_next_visit: string | null;
  days_overdue: number;
  payment_issue: boolean;
  recommended_action: RecommendedAction;
  action_reason: string;
}

export interface PortfolioSummary {
  total_customers: number;
  high_risk: number;
  med_risk: number;
  low_risk: number;
  revenue_at_risk: number;
  avg_days_away: number;
  revenue_series: { month: string; amount: number }[];
  /** Observed recoveries, attributed server-side. Zero on the demo path. */
  recovered_count: number;
  revenue_recovered: number;
}

export type TimelineKind =
  | "visit"
  | "purchase"
  | "engagement"
  | "risk_change"
  | "outreach"
  | "recovered";

export interface TimelineEntry {
  at: string;
  kind: TimelineKind;
  title: string;
  detail: string | null;
  amount: number | null;
}

export interface CustomerTimeline {
  customer_id: string;
  name: string;
  entries: TimelineEntry[];
}

export interface RecoverySummary {
  recoveries_found: number;
  revenue_recovered: number;
  sends_considered: number;
  skipped: Record<string, number>;
}

export interface Connection {
  source: string;
  status: string;
  last_synced_at: string | null;
  environment: "production" | "sandbox";
  last_error: string | null;
}

export interface Portfolio {
  business_name: string;
  vertical: string;
  currency: string;
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

export type TriggerBand = "low" | "med" | "high";
export type AutomationChannel = "sms" | "email";
export type AutomationMode = "suggest" | "approve" | "auto";

export interface AutomationRule {
  id: string;
  name: string;
  trigger_band: TriggerBand;
  channel: AutomationChannel;
  incentive: string | null;
  mode: AutomationMode;
  cooldown_days: number;
  enabled: boolean;
  created_at: string;
}

export interface AutomationRuleInput {
  name: string;
  trigger_band: TriggerBand;
  channel: AutomationChannel;
  incentive?: string | null;
  mode: AutomationMode;
  cooldown_days?: number;
  enabled?: boolean;
}

export type CampaignSendStatus = "pending" | "approved" | "sent" | "delivered" | "failed" | "skipped";

export interface CampaignSend {
  id: string;
  customer_id: string;
  customer_name: string;
  automation_rule_id: string | null;
  channel: AutomationChannel;
  subject: string | null;
  body: string;
  status: CampaignSendStatus;
  sent_at: string | null;
  failure_reason: string | null;
  created_at: string;
  opened: boolean;
  clicked: boolean;
  replied: boolean;
}

export interface DispatchSummary {
  rules_evaluated: number;
  sends_created: number;
  skipped: Record<string, number>;
}

export type KnowledgeKind = "service" | "brand_voice" | "campaign_example" | "note";

export interface KnowledgeItem {
  id: string;
  kind: KnowledgeKind;
  content: string;
  created_at: string;
}

export interface AuthUser {
  user_id: string;
  email: string | null;
  business_id: string;
  business_name: string;
  role: string;
  can_manage_visitors: boolean;
}

export type VisitorStatus =
  | "new"
  | "reviewing"
  | "qualified"
  | "contacted"
  | "dismissed";
export type VisitorIdentityLevel =
  | "anonymous"
  | "company"
  | "person"
  | "waitlist"
  | "account";

export interface VisitorSummary {
  active_24h: number;
  unique_visitors: number;
  identified_visitors: number;
  identification_rate: number;
  high_intent: number;
  waitlist_conversions: number;
  provider_matches: number;
  window_days: number;
}

export interface VisitorListItem {
  id: string;
  primary_email: string | null;
  full_name: string | null;
  job_title: string | null;
  linkedin_url: string | null;
  company_name: string | null;
  company_domain: string | null;
  company_website: string | null;
  industry: string | null;
  employee_count: string | null;
  estimated_revenue: string | null;
  city: string | null;
  state: string | null;
  zipcode: string | null;
  identity_level: VisitorIdentityLevel;
  source_provider: string;
  status: VisitorStatus;
  intent_score: number;
  first_seen_at: string;
  last_seen_at: string;
  visit_count: number;
  pageview_count: number;
  last_path: string | null;
  referrer_host: string | null;
  utm_source: string | null;
  utm_medium: string | null;
  utm_campaign: string | null;
  tags: string[];
  waitlist_signup_id: string | null;
  authenticated_user_id: string | null;
  suppressed: boolean;
}

export interface VisitorEvent {
  id: string;
  event_name: string;
  occurred_at: string;
  path: string | null;
  referrer: string | null;
  provider: string;
  properties: Record<string, unknown>;
}

export interface VisitorDetail extends VisitorListItem {
  events: VisitorEvent[];
}

export interface VisitorList {
  items: VisitorListItem[];
  total: number;
  limit: number;
  offset: number;
  summary: VisitorSummary;
}

export interface VisitorPilotMetrics {
  provider: string;
  window_days: number;
  deliveries: number;
  unique_profiles: number;
  person_matches: number;
  company_matches: number;
  repeat_visitors: number;
  high_intent_matches: number;
  waitlist_conversions: number;
  conversion_rate: number;
  monthly_cost_usd: number | null;
  cost_per_match_usd: number | null;
  recommendation: string;
}

export interface VisitorIntegrationStatus {
  rb2b_webhook_configured: boolean;
  rb2b_webhook_endpoint: string;
  discord_alerts_configured: boolean;
  discord_commands_configured: boolean;
  discord_interactions_endpoint: string;
  discord_guild_configured: boolean;
  discord_alert_min_intent_score: number;
  discord_includes_email: boolean;
}

export interface DiscordTestResult {
  delivered: boolean;
  transport: string;
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
  matchScore?: number | null;
  matchReason?: string | null;
  priceChannel: "in_store" | "delivery" | "unknown";
  corroborated: boolean;
  includedInMarketSummary: boolean;
  sourcePublishedAt?: string | null;
  sourceUpdatedAt?: string | null;
  verifiedAt?: string | null;
  retrievalMethod?:
    | "direct_fetch"
    | "perplexity_content"
    | "tavily_extract"
    | "exa_contents"
    | "firecrawl_scrape"
    | "search_snippet"
    | "none";
  extractionMethod?:
    | "json_ld"
    | "visible_text"
    | "search_snippet"
    | "sonar"
    | "tokenmart"
    | "bounded_ai"
    | "method_consensus";
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
  discoveryProvider?: "google_places" | "foursquare" | "perplexity";
}

export type CompetitorPriceResearchStatus = "complete" | "partial" | "no_evidence";
export type CompetitorPriceStageName =
  | "geocode"
  | "place_discovery"
  | "source_search"
  | "content_fetch"
  | "price_extraction"
  | "aggregation";

export interface CompetitorPriceEstimateSummary {
  method: "verified_peer_distribution";
  sampleSize: number;
  priceLow: number;
  priceMedian: number;
  priceHigh: number;
  currency: string;
  maxAgeDays: number;
  basis: "close_equivalent";
}

export interface CompetitorPriceIssue {
  code: string;
  stage: CompetitorPriceStageName;
  severity: "info" | "warning" | "error";
  retryable: boolean;
  message: string;
}

export interface CompetitorPriceStageResult {
  stage: CompetitorPriceStageName;
  status: "ok" | "degraded" | "failed" | "skipped";
  provider: string | null;
  attempts: number;
  durationMs: number;
  code: string | null;
}

export interface CompetitorPriceQuota {
  dailyLimit: number;
  used: number;
  remaining: number;
  resetsAt: string | null;
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
  status: CompetitorPriceResearchStatus;
  query: {
    businessCategory: string;
    targetOffer: string;
    locationLabel: string;
    radiusMiles: number;
    currentPrice?: number | null;
  };
  competitors: CompetitorPriceCompetitor[];
  marketSummary: CompetitorPriceMarketSummary;
  estimateSummary: CompetitorPriceEstimateSummary | null;
  channelSummaries: {
    inStore: CompetitorPriceMarketSummary;
    delivery: CompetitorPriceMarketSummary;
  } | null;
  issues: CompetitorPriceIssue[];
  quota: CompetitorPriceQuota | null;
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
    stages: CompetitorPriceStageResult[];
    providerCostUsd: number;
    pipelineVersion: string;
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
let analyticsDistinctId: string | null = null;
let visitorSessionId: string | null = null;

if (typeof window !== "undefined") {
  window.addEventListener(PRIVACY_PREFERENCE_EVENT, () => {
    if (!hasAnalyticsConsent()) {
      analyticsDistinctId = null;
      visitorSessionId = null;
    }
  });
}

export function setAccessToken(t: string | null): void {
  accessToken = t;
}

export function getAnalyticsDistinctId(): string {
  if (analyticsDistinctId) return analyticsDistinctId;

  if (typeof window !== "undefined") {
    try {
      const stored = window.localStorage.getItem(ANALYTICS_ID_STORAGE_KEY);
      if (stored) {
        analyticsDistinctId = stored;
        return stored;
      }
    } catch {
      // Storage can be unavailable in privacy-restricted browser contexts.
    }
  }

  analyticsDistinctId =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `anon-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;

  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(ANALYTICS_ID_STORAGE_KEY, analyticsDistinctId);
    } catch {
      // The in-memory ID still keeps this page load internally consistent.
    }
  }
  return analyticsDistinctId;
}

export function getVisitorSessionId(): string {
  if (visitorSessionId) return visitorSessionId;
  if (typeof window !== "undefined") {
    try {
      const stored = window.sessionStorage.getItem(VISITOR_SESSION_STORAGE_KEY);
      if (stored) {
        visitorSessionId = stored;
        return stored;
      }
    } catch {
      // Session storage can be unavailable in privacy-restricted contexts.
    }
  }
  visitorSessionId =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  if (typeof window !== "undefined") {
    try {
      window.sessionStorage.setItem(VISITOR_SESSION_STORAGE_KEY, visitorSessionId);
    } catch {
      // The in-memory session remains usable for this page load.
    }
  }
  return visitorSessionId;
}

/** Exported so lib/social.ts can share one auth + analytics-header convention. */
export function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  if (hasAnalyticsConsent()) {
    headers[POSTHOG_DISTINCT_ID_HEADER] = getAnalyticsDistinctId();
    headers[VISITOR_SESSION_ID_HEADER] = getVisitorSessionId();
  } else {
    analyticsDistinctId = null;
    visitorSessionId = null;
  }
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  return headers;
}

export const API_BASE = BASE;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly stage: string | null;
  readonly retryable: boolean | null;

  constructor(input: {
    message: string;
    status: number;
    code?: string | null;
    stage?: string | null;
    retryable?: boolean | null;
  }) {
    super(input.message);
    this.name = "ApiError";
    this.status = input.status;
    this.code = input.code ?? null;
    this.stage = input.stage ?? null;
    this.retryable = input.retryable ?? null;
  }
}

export async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    let code: string | null = null;
    let stage: string | null = null;
    let retryable: boolean | null = null;
    try {
      const body = (await res.json()) as {
        detail?: string | {
          errorCode?: string;
          stage?: string;
          retryable?: boolean;
          message?: string;
        };
      };
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (body.detail && typeof body.detail === "object") {
        detail = body.detail.message ?? detail;
        code = body.detail.errorCode ?? null;
        stage = body.detail.stage ?? null;
        retryable = body.detail.retryable ?? null;
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError({ message: detail, status: res.status, code, stage, retryable });
  }
  return res.json() as Promise<T>;
}

/** GET with up to 2 retries on network failure or 5xx. GETs are idempotent, so
 * retrying is safe; writes (POST/PATCH/DELETE) stay single-shot on purpose. */
async function getJson<T>(path: string): Promise<T> {
  let lastError: unknown;
  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt > 0) await new Promise((r) => setTimeout(r, 400 * attempt));
    try {
      const res = await fetch(`${BASE}${path}`, { headers: authHeaders() });
      if (res.status >= 500 && attempt < 2) continue;
      return await asJson<T>(res);
    } catch (err) {
      if (err instanceof TypeError) {
        lastError = err; // network failure — retry
        continue;
      }
      throw err; // HTTP error from asJson — don't retry 4xx
    }
  }
  throw lastError instanceof Error ? lastError : new Error("Request failed");
}

export const api = {
  async me(): Promise<AuthUser> {
    return getJson<AuthUser>("/api/auth/me");
  },

  async listVisitors(filters: {
    days?: number;
    limit?: number;
    offset?: number;
    q?: string;
    status?: VisitorStatus | "";
    identity?: VisitorIdentityLevel | "";
    source?: string;
  } = {}): Promise<VisitorList> {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== "") params.set(key, String(value));
    });
    return getJson<VisitorList>(`/api/visitors?${params}`);
  },

  async visitorDetail(id: string): Promise<VisitorDetail> {
    return getJson<VisitorDetail>(`/api/visitors/${id}`);
  },

  async updateVisitorStatus(
    id: string,
    visitorStatus: VisitorStatus
  ): Promise<VisitorListItem> {
    const res = await fetch(`${BASE}/api/visitors/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ status: visitorStatus }),
    });
    return asJson<VisitorListItem>(res);
  },

  async suppressVisitor(id: string): Promise<void> {
    const res = await fetch(`${BASE}/api/visitors/${id}/suppress`, {
      method: "POST",
      headers: authHeaders(),
    });
    if (!res.ok && res.status !== 204) {
      throw new Error(`Request failed (${res.status})`);
    }
  },

  async deleteVisitor(id: string): Promise<void> {
    const res = await fetch(`${BASE}/api/visitors/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!res.ok && res.status !== 204) {
      throw new Error(`Request failed (${res.status})`);
    }
  },

  async visitorPilot(days = 30, provider = "rb2b"): Promise<VisitorPilotMetrics> {
    const params = new URLSearchParams({ days: String(days), provider });
    return getJson<VisitorPilotMetrics>(`/api/visitors/pilot?${params}`);
  },

  async visitorIntegrationStatus(): Promise<VisitorIntegrationStatus> {
    return getJson<VisitorIntegrationStatus>("/api/visitors/integrations/status");
  },

  async testDiscordIntegration(): Promise<DiscordTestResult> {
    const res = await fetch(`${BASE}/api/visitors/integrations/discord/test`, {
      method: "POST",
      headers: authHeaders(),
    });
    return asJson<DiscordTestResult>(res);
  },

  /** The tenant's persisted dashboard data. status:"empty" → route to /setup. */
  async portfolio(): Promise<Portfolio> {
    return getJson<Portfolio>("/api/portfolio");
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

  /** Import the bundled, attributed CC BY 4.0 UCI transaction sample. */
  async importUciSample(vertical: string, businessName: string): Promise<Portfolio> {
    const qs = new URLSearchParams({
      vertical,
      business_name: businessName || "UCI Online Retail Demo",
    });
    const res = await fetch(
      `${BASE}/api/integrations/samples/uci-online-retail/import?${qs}`,
      { method: "POST", headers: authHeaders() }
    );
    return asJson<Portfolio>(res);
  },

  /** Which providers can show a "Connect with …" button. */
  async oauthAvailability(): Promise<{ stripe: boolean; square: boolean }> {
    return getJson("/api/integrations/oauth/availability");
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
    const data = await getJson<{ url: string }>(
      `/api/integrations/oauth/${provider}/start?${qs}`
    );
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

  async competitorPricePortfolio(limit = 24): Promise<CompetitorPriceResearchResponse[]> {
    const res = await fetch(`${BASE}/api/competitor-prices/portfolio?limit=${limit}`, {
      headers: authHeaders(),
    });
    return asJson<CompetitorPriceResearchResponse[]>(res);
  },

  async competitorPriceHistory(limit = 12): Promise<CompetitorPriceHistoryItem[]> {
    const res = await fetch(`${BASE}/api/competitor-prices/history?limit=${limit}`, {
      headers: authHeaders(),
    });
    return asJson<CompetitorPriceHistoryItem[]>(res);
  },

  async competitorPriceQuota(): Promise<CompetitorPriceQuota> {
    const res = await fetch(`${BASE}/api/competitor-prices/quota`, {
      headers: authHeaders(),
    });
    return asJson<CompetitorPriceQuota>(res);
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

  /** Everything taught so far — retrieved into campaign generation (RAG). */
  async listKnowledge(): Promise<KnowledgeItem[]> {
    return getJson<KnowledgeItem[]>("/api/knowledge");
  },

  /** Add a snippet (service, brand voice, past campaign example, or a general
   * note) that future campaign generations can draw on. */
  async addKnowledge(kind: KnowledgeKind, content: string): Promise<KnowledgeItem> {
    const res = await fetch(`${BASE}/api/knowledge`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ kind, content }),
    });
    return asJson<KnowledgeItem>(res);
  },

  async deleteKnowledge(id: string): Promise<void> {
    const res = await fetch(`${BASE}/api/knowledge/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!res.ok && res.status !== 204) {
      throw new Error(`Request failed (${res.status})`);
    }
  },

  // ── Automations (SMS/email rule engine) ──────────────────────────────────
  async listAutomationRules(): Promise<AutomationRule[]> {
    return getJson<AutomationRule[]>("/api/automations/rules");
  },

  async createAutomationRule(input: AutomationRuleInput): Promise<AutomationRule> {
    const res = await fetch(`${BASE}/api/automations/rules`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(input),
    });
    return asJson<AutomationRule>(res);
  },

  async updateAutomationRule(
    id: string,
    patch: Partial<AutomationRuleInput>
  ): Promise<AutomationRule> {
    const res = await fetch(`${BASE}/api/automations/rules/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(patch),
    });
    return asJson<AutomationRule>(res);
  },

  async deleteAutomationRule(id: string): Promise<void> {
    const res = await fetch(`${BASE}/api/automations/rules/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!res.ok && res.status !== 204) {
      throw new Error(`Request failed (${res.status})`);
    }
  },

  async listSends(limit = 50): Promise<CampaignSend[]> {
    return getJson<CampaignSend[]>(`/api/automations/sends?limit=${limit}`);
  },

  async approveSend(id: string): Promise<CampaignSend> {
    const res = await fetch(`${BASE}/api/automations/sends/${id}/approve`, {
      method: "POST",
      headers: authHeaders(),
    });
    return asJson<CampaignSend>(res);
  },

  async triggerDispatch(): Promise<DispatchSummary> {
    const res = await fetch(`${BASE}/api/automations/dispatch`, {
      method: "POST",
      headers: authHeaders(),
    });
    return asJson<DispatchSummary>(res);
  },

  /** Everything that happened to one customer, newest first. Takes the
   * `db_customer_id` from a CustomerRisk row, not `customer_id`. */
  async customerTimeline(dbCustomerId: string, limit = 100): Promise<CustomerTimeline> {
    return getJson<CustomerTimeline>(
      `/api/customers/${dbCustomerId}/timeline?limit=${limit}`
    );
  },

  /** Run recovery attribution now instead of waiting for the hourly worker tick.
   * Idempotent server-side, so calling it twice can't double-count revenue. */
  async runAttribution(): Promise<RecoverySummary> {
    const res = await fetch(`${BASE}/api/automations/attribute`, {
      method: "POST",
      headers: authHeaders(),
    });
    return asJson<RecoverySummary>(res);
  },
};

export function formatCurrency(n: number, withCents = false, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency.toUpperCase(),
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
