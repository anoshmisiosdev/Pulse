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
