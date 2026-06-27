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

export interface Portfolio {
  business_name: string;
  vertical: string;
  summary: PortfolioSummary;
  customers: CustomerRisk[];
  warnings: string[];
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

const TOKEN_KEY = "pulse_token";
export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

function authHeaders(): Record<string, string> {
  const t = tokenStore.get();
  return t ? { Authorization: `Bearer ${t}` } : {};
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
  async login(email: string, password: string): Promise<{ token: string; user: AuthUser }> {
    const res = await fetch(`${BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const out = await asJson<{ token: string; user: AuthUser }>(res);
    tokenStore.set(out.token);
    return out;
  },

  async me(): Promise<AuthUser> {
    const res = await fetch(`${BASE}/api/auth/me`, { headers: authHeaders() });
    return asJson<AuthUser>(res);
  },

  logout(): void {
    tokenStore.clear();
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
