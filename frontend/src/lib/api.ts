// Typed client for the Pulse API. Mirrors backend/app/schemas/api.py.

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export type Band = "low" | "med" | "high";

export interface CustomerRisk {
  customer_id: string;
  name: string;
  email: string | null;
  phone: string | null;
  score: number;
  band: Band;
  reasons: string[];
  estimated_annual_value: number;
}

export interface PortfolioSummary {
  total_customers: number;
  high_risk: number;
  med_risk: number;
  low_risk: number;
  revenue_at_risk: number;
}

export interface CSVPreview {
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

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  async previewCsv(file: File, vertical: string): Promise<CSVPreview> {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(
      `${BASE}/api/integrations/csv/preview?vertical=${encodeURIComponent(vertical)}`,
      { method: "POST", body: form }
    );
    return asJson<CSVPreview>(res);
  },

  async demo(count = 300): Promise<CSVPreview> {
    const res = await fetch(`${BASE}/api/integrations/demo?count=${count}`, {
      method: "POST",
    });
    return asJson<CSVPreview>(res);
  },

  async generateCampaign(input: {
    business_name: string;
    business_type: string;
    customer_name: string;
    channel: "email" | "sms";
    incentive?: string;
    risk_reasons: string[];
  }): Promise<GeneratedCopy> {
    const res = await fetch(`${BASE}/api/campaigns/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    return asJson<GeneratedCopy>(res);
  },

  templateUrl(): string {
    return `${BASE}/api/integrations/csv/template`;
  },
};

export function formatCurrency(n: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
}
