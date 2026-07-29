import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  api,
  type CompetitorPrice,
  type CompetitorPriceCompetitor,
  type CompetitorPriceResearchResponse,
} from "../lib/api";
import { usePulse } from "../context/PulseContext";

export type FormState = {
  businessName: string;
  businessCategory: string;
  targetOffer: string;
  address: string;
  city: string;
  state: string;
  zip: string;
  radiusMiles: string;
  currentPrice: string;
};

const DEFAULT_FORM: FormState = {
  businessName: "",
  businessCategory: "Coffee Shop",
  targetOffer: "Cappuccino",
  address: "3602 Thornton Ave",
  city: "Fremont",
  state: "CA",
  zip: "94536",
  radiusMiles: "10",
  currentPrice: "4.00",
};

export type CompetitorTableRow = {
  competitor: CompetitorPriceCompetitor;
  price: CompetitorPrice | null;
};

export function buildCompetitorRows(
  result: CompetitorPriceResearchResponse | null
): CompetitorTableRow[] {
  if (!result) return [];
  return result.competitors.flatMap<CompetitorTableRow>((competitor) => {
    const prices = competitor.prices.filter((price) => price.priceChannel !== "delivery");
    if (prices.length === 0) return [{ competitor, price: null }];
    return prices.map((price) => ({ competitor, price }));
  });
}

export function mergeTenantBusinessName(form: FormState, businessName: string): FormState {
  return form.businessName ? form : { ...form, businessName };
}

export function deriveMenuSuggestions(items: Array<string | null>, limit = 6): string[] {
  const counts = new Map<string, { label: string; count: number }>();
  for (const item of items) {
    const label = item?.trim();
    if (!label) continue;
    const key = label.toLocaleLowerCase();
    const existing = counts.get(key);
    counts.set(key, { label: existing?.label ?? label, count: (existing?.count ?? 0) + 1 });
  }
  return [...counts.values()]
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
    .slice(0, limit)
    .map((item) => item.label);
}

export function deriveTenantPricingDefaults(input: {
  businessName: string;
  vertical: string;
  favoriteItems: Array<string | null>;
  locationLabel: string | null;
}): FormState {
  const categoryByVertical: Record<string, string> = {
    cafe: "Coffee Shop",
    coffee_shop: "Coffee Shop",
    fitness: "Gym",
    gym: "Gym",
    salon: "Hair Salon",
    med_spa: "Med Spa",
    boutique: "Boutique",
  };
  const [city = "", state = ""] = (input.locationLabel ?? "")
    .split(",")
    .map((part) => part.trim());
  return {
    businessName: input.businessName,
    businessCategory: categoryByVertical[input.vertical] ?? "Local Business",
    targetOffer: deriveMenuSuggestions(input.favoriteItems)[0] ?? "",
    address: city && state ? "" : input.locationLabel ?? "",
    city: state ? city : "",
    state,
    zip: "",
    radiusMiles: "10",
    currentPrice: "",
  };
}

export function parseMenuItems(text: string): Array<{ name: string; price: string }> {
  const parsed: Array<{ name: string; price: string }> = [];
  const seen = new Set<string>();
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.replace(/^\s*(?:[-*•]|\d+[.)])\s*/, "").trim();
    if (!line) continue;
    const match = line.match(
      /^(.*?)(?:\s+[—–-]\s+|\s*,\s*|\s+)(?:\$(\d+(?:\.\d{1,2})?)|(\d+\.\d{2}))\s*$/
    );
    const name = (match?.[1] ?? line).trim();
    const price = match?.[2] ?? match?.[3] ?? "";
    const key = name.toLocaleLowerCase();
    if (!name || seen.has(key)) continue;
    seen.add(key);
    parsed.push({ name, price });
  }
  return parsed.slice(0, 12);
}

export function getMarketPosition(result: CompetitorPriceResearchResponse): {
  key: "below" | "market" | "above" | "unknown";
  label: string;
  delta: number | null;
} {
  const current = result.query.currentPrice;
  const median = result.marketSummary.priceMedian;
  if (current === null || current === undefined || median === null || median === 0) {
    return { key: "unknown", label: "Market snapshot", delta: null };
  }
  const delta = ((current - median) / median) * 100;
  if (delta < -5) return { key: "below", label: `${Math.abs(delta).toFixed(0)}% below`, delta };
  if (delta > 5) return { key: "above", label: `${delta.toFixed(0)}% premium`, delta };
  return { key: "market", label: "Right on market", delta };
}

export function buildPricingCsv(result: CompetitorPriceResearchResponse): string {
  const rows = [
    ["competitor", "offer", "price_min", "price_max", "channel", "confidence", "source"],
    ...result.competitors.flatMap((competitor) =>
      competitor.prices.map((price) => [
        competitor.name,
        price.offerName,
        price.priceMin,
        price.priceMax,
        price.priceChannel,
        price.confidence,
        price.sourceUrl,
      ])
    ),
  ];
  return rows
    .map((row) =>
      row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(",")
    )
    .join("\n");
}

/** Form state, research API call, and elapsed-time tracking for the Pricing page. */
export function useCompetitorPricing() {
  const { businessName } = usePulse();
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CompetitorPriceResearchResponse | null>(null);
  const [researchStartedAt, setResearchStartedAt] = useState<number | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [lastDurationMs, setLastDurationMs] = useState<number | null>(null);

  useEffect(() => {
    if (!businessName) return;
    setForm((current) => mergeTenantBusinessName(current, businessName));
  }, [businessName]);

  useEffect(() => {
    if (!loading || researchStartedAt === null) return undefined;

    const updateElapsed = () => setElapsedMs(Date.now() - researchStartedAt);
    updateElapsed();
    const interval = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(interval);
  }, [loading, researchStartedAt]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const startedAt = Date.now();
    setLoading(true);
    setError(null);
    setResearchStartedAt(startedAt);
    setElapsedMs(0);
    setLastDurationMs(null);
    let finalDurationMs: number | null = null;
    try {
      const response = await api.researchCompetitorPrices({
        businessName: form.businessName || businessName,
        businessCategory: form.businessCategory,
        targetOffer: form.targetOffer,
        location: {
          address: form.address || undefined,
          city: form.city || undefined,
          state: form.state || undefined,
          zip: form.zip || undefined,
          country: "US",
        },
        radiusMiles: Number(form.radiusMiles || 5),
        maxCompetitors: 3,
        maxSourcesPerCompetitor: 3,
        currentPrice: form.currentPrice ? Number(form.currentPrice) : null,
      });
      finalDurationMs = response.metadata.durationMs ?? Date.now() - startedAt;
      setResult(response);
    } catch (err) {
      finalDurationMs = Date.now() - startedAt;
      setError(err instanceof Error ? err.message : "Research failed");
    } finally {
      if (finalDurationMs !== null) {
        setElapsedMs(finalDurationMs);
        setLastDurationMs(finalDurationMs);
      }
      setResearchStartedAt(null);
      setLoading(false);
    }
  }

  const competitorRows = useMemo(() => buildCompetitorRows(result), [result]);
  const deliveryRows = useMemo(
    () =>
      result?.competitors.flatMap((competitor) =>
        competitor.prices
          .filter((price) => price.priceChannel === "delivery")
          .map((price) => ({ competitor, price }))
      ) ?? [],
    [result]
  );

  return {
    form,
    setForm,
    loading,
    error,
    result,
    elapsedMs,
    lastDurationMs,
    submit,
    competitorRows,
    deliveryRows,
  };
}
