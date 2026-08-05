import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  ApiError,
  api,
  type CompetitorPrice,
  type CompetitorPriceCompetitor,
  type CompetitorPriceHistoryItem,
  type CompetitorPriceQuota,
  type CompetitorPriceResearchInput,
  type CompetitorPriceResearchResponse,
} from "../lib/api";
import { createSamplePricingPortfolio } from "../lib/pricingSample";
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

export type PricingRunError = {
  message: string;
  code: string | null;
  stage: string | null;
  retryable: boolean | null;
  status: number | null;
};

const DEFAULT_FORM: FormState = {
  businessName: "",
  businessCategory: "",
  targetOffer: "",
  address: "",
  city: "",
  state: "",
  zip: "",
  radiusMiles: "10",
  currentPrice: "",
};

export type CompetitorTableRow = {
  competitor: CompetitorPriceCompetitor;
  price: CompetitorPrice | null;
};

export type OfferMatchCoverage = {
  exactBusinesses: number;
  closeBusinesses: number;
  closeMatches: Array<{
    competitorName: string;
    offerName: string;
    score: number | null;
    reason: string | null;
  }>;
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

export function getOfferMatchCoverage(
  result: CompetitorPriceResearchResponse
): OfferMatchCoverage {
  const exactBusinesses = new Set<string>();
  const closeBusinesses = new Set<string>();
  const closeMatches = new Map<string, OfferMatchCoverage["closeMatches"][number]>();

  for (const competitor of result.competitors) {
    const inStorePrices = competitor.prices.filter((price) => price.priceChannel !== "delivery");
    if (
      inStorePrices.some(
        (price) => price.matchQuality === "exact" && price.includedInMarketSummary
      )
    ) {
      exactBusinesses.add(competitor.name);
    }
    for (const price of inStorePrices) {
      if (price.matchQuality !== "close") continue;
      closeBusinesses.add(competitor.name);
      const key = `${competitor.name.toLocaleLowerCase()}|${price.normalizedOfferName}`;
      if (!closeMatches.has(key)) {
        closeMatches.set(key, {
          competitorName: competitor.name,
          offerName: price.offerName,
          score: price.matchScore ?? null,
          reason: price.matchReason ?? null,
        });
      }
    }
  }

  return {
    exactBusinesses: exactBusinesses.size,
    closeBusinesses: closeBusinesses.size,
    closeMatches: [...closeMatches.values()],
  };
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
  return parsed.slice(0, 10);
}

export function getMarketPosition(result: CompetitorPriceResearchResponse): {
  key: "below" | "market" | "above" | "unknown";
  label: string;
  delta: number | null;
} {
  const current = result.query.currentPrice;
  const median = result.marketSummary.priceMedian;
  if (current === null || current === undefined || median === null || median === 0) {
    return { key: "unknown", label: "No exact benchmark", delta: null };
  }
  const delta = ((current - median) / median) * 100;
  if (delta < -5) return { key: "below", label: `${Math.abs(delta).toFixed(0)}% below`, delta };
  if (delta > 5) return { key: "above", label: `${delta.toFixed(0)}% premium`, delta };
  return { key: "market", label: "Right on market", delta };
}

export function buildPricingCsv(result: CompetitorPriceResearchResponse): string {
  const rows = [
    [
      "competitor",
      "requested_offer",
      "matched_offer",
      "match_quality",
      "match_score",
      "match_reason",
      "price_min",
      "price_max",
      "channel",
      "confidence",
      "source",
    ],
    ...result.competitors.flatMap((competitor) =>
      competitor.prices.map((price) => [
        competitor.name,
        result.query.targetOffer,
        price.offerName,
        price.matchQuality,
        price.matchScore,
        price.matchReason,
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

function mergeEmptyFormValues(current: FormState, defaults: FormState): FormState {
  return Object.fromEntries(
    Object.entries(current).map(([key, value]) => [
      key,
      value || defaults[key as keyof FormState],
    ])
  ) as unknown as FormState;
}

function normalizeOffer(value: string): string {
  return value.trim().toLocaleLowerCase();
}

function replacePortfolioResult(
  current: CompetitorPriceResearchResponse[],
  response: CompetitorPriceResearchResponse
): CompetitorPriceResearchResponse[] {
  const key = normalizeOffer(response.query.targetOffer);
  return [response, ...current.filter((item) => normalizeOffer(item.query.targetOffer) !== key)];
}

function toResearchInput(
  form: FormState,
  item: { name: string; price: string },
  tenantBusinessName: string
): CompetitorPriceResearchInput {
  return {
    businessName: form.businessName || tenantBusinessName || undefined,
    businessCategory: form.businessCategory.trim(),
    targetOffer: item.name.trim(),
    location: {
      address: form.address.trim() || undefined,
      city: form.city.trim() || undefined,
      state: form.state.trim() || undefined,
      zip: form.zip.trim() || undefined,
      country: "US",
    },
    radiusMiles: Number(form.radiusMiles || 10),
    maxCompetitors: 4,
    maxSourcesPerCompetitor: 3,
    currentPrice: item.price ? Number(item.price) : null,
  };
}

function toRunError(error: unknown): PricingRunError {
  if (error instanceof ApiError) {
    return {
      message: error.message,
      code: error.code,
      stage: error.stage,
      retryable: error.retryable,
      status: error.status,
    };
  }
  return {
    message: error instanceof Error ? error.message : "Pricing research failed.",
    code: null,
    stage: null,
    retryable: null,
    status: null,
  };
}

export function useCompetitorPricing() {
  const { businessName, vertical, customers, portfolio } = usePulse();
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [menuText, setMenuText] = useState("");
  const [results, setResults] = useState<CompetitorPriceResearchResponse[]>([]);
  const [history, setHistory] = useState<CompetitorPriceHistoryItem[]>([]);
  const [quota, setQuota] = useState<CompetitorPriceQuota | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [loadingOffers, setLoadingOffers] = useState<Set<string>>(new Set());
  const [batchProgress, setBatchProgress] = useState<{ done: number; total: number } | null>(null);
  const [errors, setErrors] = useState<Record<string, PricingRunError>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [lastDurationMs, setLastDurationMs] = useState<number | null>(null);
  const [expandedOffer, setExpandedOffer] = useState<string | null>(null);
  const [sampleMode, setSampleMode] = useState(false);
  const menuSeeded = useRef(false);
  const liveData = useRef<{
    results: CompetitorPriceResearchResponse[];
    history: CompetitorPriceHistoryItem[];
  }>({ results: [], history: [] });

  useEffect(() => {
    const favoriteItems = customers.map((customer) => customer.favorite_item);
    const defaults = deriveTenantPricingDefaults({
      businessName,
      vertical,
      favoriteItems,
      locationLabel: portfolio?.location_label ?? null,
    });
    setForm((current) => mergeEmptyFormValues(current, defaults));
    if (!menuSeeded.current) {
      const suggestions = deriveMenuSuggestions(favoriteItems);
      if (suggestions.length) setMenuText(suggestions.join("\n"));
      menuSeeded.current = true;
    }
  }, [businessName, customers, portfolio?.location_label, vertical]);

  useEffect(() => {
    let active = true;
    async function load() {
      const wantsSample = new URLSearchParams(window.location.search).get("sampleCafe") === "1";
      if (wantsSample) {
        const sample = createSamplePricingPortfolio();
        if (!active) return;
        setSampleMode(true);
        setResults(sample.results);
        setHistory(sample.history);
        setErrors({});
        setNotice("Sample data is illustrative and does not consume your research quota.");
        setInitialLoading(false);
        return;
      }

      let savedResults: CompetitorPriceResearchResponse[] = [];
      try {
        savedResults = await api.competitorPricePortfolio(24);
      } catch (portfolioError) {
        try {
          const latest = await api.latestCompetitorPrices();
          savedResults = latest ? [latest] : [];
        } catch {
          if (active) setErrors({ portfolio: toRunError(portfolioError) });
        }
      }
      const [savedHistory, currentQuota] = await Promise.all([
        api.competitorPriceHistory(50).catch(() => []),
        api.competitorPriceQuota().catch(() => null),
      ]);
      if (!active) return;
      liveData.current = { results: savedResults, history: savedHistory };
      setResults(savedResults);
      setHistory(savedHistory);
      setQuota(currentQuota);
      setInitialLoading(false);
    }
    void load();
    return () => {
      active = false;
    };
    // Loading is intentionally tied to the authenticated tenant, not form edits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const parsedMenu = useMemo(() => parseMenuItems(menuText), [menuText]);
  const portfolioPulse = useMemo(() => {
    const complete = results.filter((result) => result.status === "complete").length;
    const partial = results.filter((result) => result.status === "partial").length;
    const noEvidence = results.filter((result) => result.status === "no_evidence").length;
    const exactPrices = results.reduce(
      (total, result) => total + result.competitors.flatMap((item) => item.prices).filter(
        (price) => price.matchQuality === "exact" && price.includedInMarketSummary
      ).length,
      0
    );
    return { total: results.length, complete, partial, noEvidence, exactPrices };
  }, [results]);

  function showSample() {
    if (!sampleMode) liveData.current = { results, history };
    const sample = createSamplePricingPortfolio();
    setSampleMode(true);
    setResults(sample.results);
    setHistory(sample.history);
    setExpandedOffer(null);
    setErrors({});
    setNotice("Sample data is illustrative and does not consume your research quota.");
    window.history.replaceState({}, "", `${window.location.pathname}?sampleCafe=1`);
  }

  function closeSample() {
    setSampleMode(false);
    setResults(liveData.current.results);
    setHistory(liveData.current.history);
    setExpandedOffer(null);
    setNotice(null);
    window.history.replaceState({}, "", window.location.pathname);
  }

  async function submitBatch(event: FormEvent) {
    event.preventDefault();
    const generalErrors: Record<string, PricingRunError> = {};
    if (!form.businessCategory.trim()) {
      generalErrors.category = toRunError(new Error("Add a business category."));
    }
    if (!form.city.trim() || !form.state.trim()) {
      generalErrors.location = toRunError(new Error("Add a city and state for the local market."));
    }
    if (!parsedMenu.length) {
      generalErrors.menu = toRunError(new Error("Add at least one product or service."));
    }
    if (Object.keys(generalErrors).length) {
      setErrors(generalErrors);
      return;
    }

    const remaining = quota?.remaining ?? 10;
    if (remaining <= 0) {
      setErrors({ quota: toRunError(new Error("Today's 10-item research allowance is used.")) });
      return;
    }
    const queue = parsedMenu.slice(0, Math.min(10, remaining));
    if (queue.length < parsedMenu.length) {
      setNotice(`Researching ${queue.length} item${queue.length === 1 ? "" : "s"}; ${parsedMenu.length - queue.length} exceed today's remaining allowance.`);
    } else {
      setNotice(null);
    }

    const startedAt = Date.now();
    setErrors({});
    setBatchProgress({ done: 0, total: queue.length });
    setLoadingOffers(new Set(queue.map((item) => normalizeOffer(item.name))));
    let cursor = 0;
    async function worker() {
      while (cursor < queue.length) {
        const item = queue[cursor++];
        const key = normalizeOffer(item.name);
        try {
          const response = await api.researchCompetitorPrices(
            toResearchInput(form, item, businessName)
          );
          setResults((current) => {
            const next = replacePortfolioResult(current, response);
            liveData.current = { ...liveData.current, results: next };
            return next;
          });
          if (response.quota) setQuota(response.quota);
          setExpandedOffer((current) => current ?? key);
        } catch (error) {
          setErrors((current) => ({ ...current, [key]: toRunError(error) }));
        } finally {
          setLoadingOffers((current) => {
            const next = new Set(current);
            next.delete(key);
            return next;
          });
          setBatchProgress((current) =>
            current ? { ...current, done: Math.min(current.total, current.done + 1) } : null
          );
        }
      }
    }

    await Promise.all(Array.from({ length: Math.min(2, queue.length) }, () => worker()));
    setLastDurationMs(Date.now() - startedAt);
    setBatchProgress(null);
    const [savedHistory, currentQuota] = await Promise.all([
      api.competitorPriceHistory(50).catch(() => history),
      api.competitorPriceQuota().catch(() => quota),
    ]);
    setHistory(savedHistory);
    setQuota(currentQuota);
    liveData.current = { ...liveData.current, history: savedHistory };
  }

  async function refreshResult(result: CompetitorPriceResearchResponse) {
    const key = normalizeOffer(result.query.targetOffer);
    const [city = form.city, state = form.state] = result.query.locationLabel
      .split(",")
      .map((part) => part.trim());
    const refreshForm = {
      ...form,
      city: form.city || city,
      state: form.state || state,
      businessCategory: result.query.businessCategory,
    };
    setLoadingOffers((current) => new Set(current).add(key));
    setErrors((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });
    try {
      const response = await api.researchCompetitorPrices(
        toResearchInput(refreshForm, {
          name: result.query.targetOffer,
          price: result.query.currentPrice?.toString() ?? "",
        }, businessName)
      );
      setResults((current) => {
        const next = replacePortfolioResult(current, response);
        liveData.current = { ...liveData.current, results: next };
        return next;
      });
      if (response.quota) setQuota(response.quota);
    } catch (error) {
      setErrors((current) => ({ ...current, [key]: toRunError(error) }));
    } finally {
      setLoadingOffers((current) => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
    }
  }

  return {
    form,
    setForm,
    menuText,
    setMenuText,
    parsedMenu,
    results,
    history,
    quota,
    initialLoading,
    loadingOffers,
    batchProgress,
    errors,
    notice,
    lastDurationMs,
    expandedOffer,
    setExpandedOffer,
    sampleMode,
    portfolioPulse,
    submitBatch,
    refreshResult,
    showSample,
    closeSample,
  };
}
