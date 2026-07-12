import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  formatCurrency,
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

export default function Pricing() {
  const { businessName } = usePulse();
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CompetitorPriceResearchResponse | null>(null);
  const [researchStartedAt, setResearchStartedAt] = useState<number | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [lastDurationMs, setLastDurationMs] = useState<number | null>(null);
  const businessNameEdited = useRef(false);

  useEffect(() => {
    if (!businessName || businessNameEdited.current) return;
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
  const observationCount = useMemo(
    () => result?.competitors.reduce((count, item) => count + item.prices.length, 0) ?? 0,
    [result]
  );
  const deliveryRows = useMemo(
    () =>
      result?.competitors.flatMap((competitor) =>
        competitor.prices
          .filter((price) => price.priceChannel === "delivery")
          .map((price) => ({ competitor, price }))
      ) ?? [],
    [result]
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-4xl font-extrabold tracking-tight">Pricing</h1>
        <p className="mt-1 text-slate-500">
          Research local competitor prices with source-backed evidence.
        </p>
      </div>

      <form onSubmit={submit} className="glass p-5">
        <div className="mb-5 rounded-xl border border-cyan-100 bg-cyan-50/60 p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-cyan-700">
            Product or service being researched
          </p>
          <p className="mt-1 font-display text-xl font-bold text-slate-900">
            {form.targetOffer.trim() || "Choose a product or service"}
          </p>
          <p className="mt-1 text-sm text-slate-500">
            Competitor discovery, source extraction, and your current price comparison all use
            this same item.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          <Field
            label="Product or service to price"
            value={form.targetOffer}
            required
            placeholder="Cappuccino"
            help="This is the exact offer Pulse searches for at nearby competitors."
            onChange={(v) => setForm({ ...form, targetOffer: v })}
          />
          <Field
            label="Your price for this offer"
            type="number"
            value={form.currentPrice}
            min="0"
            placeholder="4.00"
            help="Optional. Used only to say whether you are above, below, or near the market."
            onChange={(v) => setForm({ ...form, currentPrice: v })}
          />
          <Field
            label="Business category"
            value={form.businessCategory}
            required
            placeholder="Coffee Shop"
            onChange={(v) => setForm({ ...form, businessCategory: v })}
          />
          <Field
            label="Business name"
            value={form.businessName}
            placeholder="Suju's Coffee"
            onChange={(v) => {
              businessNameEdited.current = true;
              setForm({ ...form, businessName: v });
            }}
          />
          <Field
            label="Street address"
            value={form.address}
            placeholder="3602 Thornton Ave"
            onChange={(v) => setForm({ ...form, address: v })}
          />
          <Field
            label="City"
            value={form.city}
            required
            placeholder="Fremont"
            onChange={(v) => setForm({ ...form, city: v })}
          />
          <Field
            label="State"
            value={form.state}
            required
            placeholder="CA"
            onChange={(v) => setForm({ ...form, state: v })}
          />
          <Field
            label="ZIP"
            value={form.zip}
            placeholder="94536"
            onChange={(v) => setForm({ ...form, zip: v })}
          />
          <Field
            label="Search radius"
            type="number"
            value={form.radiusMiles}
            min="1"
            max="25"
            help="Miles from the location above."
            onChange={(v) => setForm({ ...form, radiusMiles: v })}
          />
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            <SearchIcon />
            {loading ? "Researching…" : `Research ${form.targetOffer || "offer"} prices`}
          </button>
          {(loading || lastDurationMs !== null) && (
            <TimerBadge
              durationMs={loading ? elapsedMs : lastDurationMs ?? 0}
              label={
                loading
                  ? "Elapsed"
                  : error
                    ? "Stopped after"
                    : result?.metadata.cached
                      ? "Loaded in"
                      : "Completed in"
              }
            />
          )}
          {error && <p className="text-sm font-medium text-red-600">{error}</p>}
        </div>
      </form>

      {result && (
        <>
          <MarketSummary result={result} />
          <ResearchStats result={result} />
          {result.warnings.length > 0 && <Warnings warnings={result.warnings} />}
          <div className="glass overflow-hidden">
            <div className="border-b border-white/60 px-5 py-4">
              <h2 className="font-display text-lg font-bold text-slate-900">
                Competitors researched for {result.query.targetOffer}
              </h2>
              <p className="text-sm text-slate-500">
                {result.competitors.length} found near {result.query.locationLabel};{" "}
                {observationCount} observations found; {result.marketSummary.sampleSize}{" "}
                benchmark-eligible businesses.
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-100 text-left text-sm">
                <thead className="bg-white/40 text-xs uppercase tracking-wide text-slate-400">
                  <tr>
                    <th className="px-5 py-3">Competitor</th>
                    <th className="px-5 py-3">Price</th>
                    <th className="px-5 py-3">Confidence</th>
                    <th className="px-5 py-3">Evidence</th>
                    <th className="px-5 py-3">Source</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {competitorRows.length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-5 py-8 text-center text-slate-400">
                        No competitors were found.
                      </td>
                    </tr>
                  )}
                  {competitorRows.map((row, idx) => (
                    <tr
                      key={`${row.competitor.name}-${row.price?.sourceUrl ?? "no-price"}-${idx}`}
                      className="align-top"
                    >
                      <td className="px-5 py-4">
                        <p className="font-semibold text-slate-800">{row.competitor.name}</p>
                        <p className="max-w-[220px] text-xs text-slate-400">
                          {row.competitor.address || "Address unavailable"}
                        </p>
                        <div className="mt-2 flex flex-wrap gap-1">
                          {row.competitor.discoveryProvider === "google_places" && (
                            <Badge tone="cyan">Google Places</Badge>
                          )}
                          {row.competitor.radiusVerified && row.competitor.distanceMiles !== null ? (
                            <Badge tone="green">
                              {row.competitor.distanceMiles.toFixed(1)} mi verified
                            </Badge>
                          ) : (
                            <Badge tone="amber">Radius unverified</Badge>
                          )}
                        </div>
                        {(row.competitor.rating || row.competitor.reviewCount) && (
                          <p className="mt-1 text-xs text-slate-400">
                            {row.competitor.rating ? `${row.competitor.rating.toFixed(1)} rating` : ""}
                            {row.competitor.rating && row.competitor.reviewCount ? " · " : ""}
                            {row.competitor.reviewCount
                              ? `${row.competitor.reviewCount.toLocaleString()} reviews`
                              : ""}
                          </p>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-5 py-4 font-semibold text-slate-900">
                        {row.price ? formatPrice(row.price) : "No exact price found"}
                        <p className="mt-1 text-xs font-normal text-slate-400">
                          {row.price?.priceType ?? "strict evidence required"}
                        </p>
                        {row.price && (
                          <div className="mt-2 flex flex-wrap gap-1">
                            <Badge tone={row.price.matchQuality === "exact" ? "green" : "amber"}>
                              {row.price.matchQuality}
                            </Badge>
                            {row.price.corroborated && <Badge tone="cyan">Corroborated</Badge>}
                            <Badge
                              tone={
                                row.price.freshnessStatus === "current" ? "green" : "amber"
                              }
                            >
                              {row.price.freshnessStatus ?? "unknown freshness"}
                            </Badge>
                            {row.price.needsReview && <Badge tone="amber">Needs review</Badge>}
                            {row.price.includedInMarketSummary ? (
                              <Badge tone="green">In benchmark</Badge>
                            ) : (
                              <Badge tone="slate">Not benchmarked</Badge>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="px-5 py-4">
                        {row.price ? <Confidence value={row.price.confidence} /> : <span className="text-slate-400">—</span>}
                      </td>
                      <td className="max-w-sm px-5 py-4 text-slate-600">
                        {row.price ? (
                          <>“{row.price.evidenceText}”</>
                        ) : (
                          <span className="text-slate-400">
                            Competitor found, but no explicit numeric price for this offer passed
                            the source-evidence checks.
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-4">
                        {row.price ? (
                          <div>
                            <a
                              href={row.price.sourceUrl}
                              target="_blank"
                              rel="noreferrer"
                              className="font-semibold text-cyan-700 hover:underline"
                            >
                              {row.price.sourceTitle || "Open source"}
                            </a>
                            <p className="mt-1 text-xs text-slate-400">
                              {retrievalLabel(row.price.retrievalMethod)} ·{" "}
                              {extractionLabel(row.price.extractionMethod)}
                            </p>
                            {(row.price.sourceUpdatedAt || row.price.sourcePublishedAt) && (
                              <p className="mt-1 text-xs text-slate-400">
                                Source date: {row.price.sourceUpdatedAt || row.price.sourcePublishedAt}
                              </p>
                            )}
                          </div>
                        ) : row.competitor.website ? (
                          <a
                            href={row.competitor.website}
                            target="_blank"
                            rel="noreferrer"
                            className="font-semibold text-cyan-700 hover:underline"
                          >
                            Open website
                          </a>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          {deliveryRows.length > 0 && (
            <DeliveryPrices
              rows={deliveryRows}
              summary={result.channelSummaries?.delivery ?? null}
            />
          )}
        </>
      )}
    </div>
  );
}

function TimerBadge({ durationMs, label }: { durationMs: number; label: string }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-xl border border-cyan-100 bg-white/70 px-3 py-2 text-sm font-semibold text-slate-700">
      <ClockIcon />
      <span className="text-slate-400">{label}</span>
      <span className="tabular-nums text-slate-900">{formatDuration(durationMs)}</span>
    </span>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  required = false,
  min,
  max,
  placeholder,
  help,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  required?: boolean;
  min?: string;
  max?: string;
  placeholder?: string;
  help?: string;
}) {
  return (
    <label className="block">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</span>
      <input
        type={type}
        required={required}
        value={value}
        min={min}
        max={max}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-xl border border-slate-200 bg-white/70 px-3 py-2.5 text-sm text-slate-800 outline-none transition focus:border-primary"
      />
      {help && <span className="mt-1 block text-xs leading-snug text-slate-400">{help}</span>}
    </label>
  );
}

function MarketSummary({ result }: { result: CompetitorPriceResearchResponse }) {
  const s = result.marketSummary;
  return (
    <div className="glass grid gap-4 p-5 md:grid-cols-[1.3fr_2fr]">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Market summary</p>
        <p className="mt-2 font-display text-3xl font-bold text-slate-900">
          {s.priceMedian === null ? "No median" : formatCurrency(s.priceMedian, true)}
        </p>
        <p className="mt-1 text-sm text-slate-500">Median in-store price</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-4">
        <MiniStat label="Businesses" value={String(s.sampleSize)} />
        <MiniStat label="Low" value={s.priceLow === null ? "—" : formatCurrency(s.priceLow, true)} />
        <MiniStat label="High" value={s.priceHigh === null ? "—" : formatCurrency(s.priceHigh, true)} />
        <MiniStat label="Confidence" value={`${Math.round(s.confidence * 100)}%`} />
        <p className="sm:col-span-4 text-sm text-slate-600">{s.recommendedPositioning}</p>
        <p className="sm:col-span-4 text-xs text-slate-400">
          Sample size counts unique businesses, not source pages. Delivery marketplace prices are
          excluded from this positioning benchmark.
        </p>
      </div>
    </div>
  );
}

export function ResearchStats({ result }: { result: CompetitorPriceResearchResponse }) {
  const stats = result.metadata.researchStats;
  return (
    <div className="glass grid gap-3 p-4 sm:grid-cols-3 lg:grid-cols-6">
      <MiniStat label="Sources discovered" value={String(stats.sourcesDiscovered)} />
      <MiniStat label="Sources checked" value={String(stats.sourcesChecked)} />
      <MiniStat label="Sources accepted" value={String(stats.sourcesAccepted)} />
      <MiniStat label="Corroborated businesses" value={String(stats.corroboratedCompetitors)} />
      <MiniStat label="Pages fetched" value={String(stats.pagesFetched ?? 0)} />
      <MiniStat label="AI fallbacks" value={String(stats.aiExtractions ?? 0)} />
    </div>
  );
}

export function DeliveryPrices({
  rows,
  summary,
}: {
  rows: Array<{ competitor: CompetitorPriceCompetitor; price: CompetitorPrice }>;
  summary: CompetitorPriceResearchResponse["marketSummary"] | null;
}) {
  return (
    <div className="glass p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-bold text-slate-900">
            Delivery marketplace prices
          </h2>
          <p className="text-sm text-slate-500">
            Shown separately because delivery platforms may add channel-specific markups.
          </p>
        </div>
        {summary?.priceMedian !== null && summary?.priceMedian !== undefined && (
          <Badge tone="amber">Median {formatCurrency(summary.priceMedian, true)}</Badge>
        )}
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {rows.map(({ competitor, price }) => (
          <div
            key={`${competitor.name}-${price.sourceUrl}`}
            className="rounded-xl border border-amber-100 bg-amber-50/50 p-4"
          >
            <div className="flex items-center justify-between gap-3">
              <p className="font-semibold text-slate-800">{competitor.name}</p>
              <p className="font-display text-lg font-bold text-slate-900">{formatPrice(price)}</p>
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              <Badge tone={price.freshnessStatus === "current" ? "green" : "amber"}>
                {price.freshnessStatus ?? "unknown freshness"}
              </Badge>
              <Badge tone="cyan">{retrievalLabel(price.retrievalMethod)}</Badge>
              {price.needsReview && <Badge tone="amber">Needs review</Badge>}
            </div>
            <p className="mt-2 text-sm text-slate-600">“{price.evidenceText}”</p>
            <p className="mt-1 text-xs text-slate-400">
              {extractionLabel(price.extractionMethod)}
              {(price.sourceUpdatedAt || price.sourcePublishedAt) &&
                ` · Source date: ${price.sourceUpdatedAt || price.sourcePublishedAt}`}
            </p>
            <a
              href={price.sourceUrl}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-block text-sm font-semibold text-cyan-700 hover:underline"
            >
              {price.sourceTitle || "Open marketplace source"}
            </a>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Badge({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone: "green" | "amber" | "cyan" | "slate";
}) {
  const styles = {
    green: "bg-emerald-50 text-emerald-700",
    amber: "bg-amber-50 text-amber-700",
    cyan: "bg-cyan-50 text-cyan-700",
    slate: "bg-slate-100 text-slate-600",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${styles[tone]}`}>
      {children}
    </span>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/60 bg-white/45 p-3">
      <p className="text-xs text-slate-400">{label}</p>
      <p className="mt-1 font-display text-lg font-bold text-slate-800">{value}</p>
    </div>
  );
}

function Warnings({ warnings }: { warnings: string[] }) {
  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50/80 p-4 text-sm text-amber-800">
      <p className="font-semibold">Warnings</p>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {warnings.map((warning) => <li key={warning}>{warning}</li>)}
      </ul>
    </div>
  );
}

function Confidence({ value }: { value: number }) {
  const color = value >= 0.75 ? "#10b981" : value >= 0.5 ? "#f59e0b" : "#ef4444";
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-white/70 px-2.5 py-1 text-xs font-semibold text-slate-700">
      <span className="h-2 w-2 rounded-full" style={{ background: color }} />
      {Math.round(value * 100)}%
    </span>
  );
}

type CompetitorTableRow = {
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

export function formatPrice(price: CompetitorPrice): string {
  if (price.priceType === "quote_based") return "Quote";
  if (price.priceMin !== null && price.priceMax !== null && price.priceMin !== price.priceMax) {
    return `${formatCurrency(price.priceMin, true)}-${formatCurrency(price.priceMax, true)}`;
  }
  const value = price.priceMin ?? price.priceMax;
  return value === null ? "Unknown" : formatCurrency(value, true);
}

function retrievalLabel(method: CompetitorPrice["retrievalMethod"]): string {
  return method === "direct_fetch" ? "Directly retrieved" : "Search-provided content";
}

function extractionLabel(method: CompetitorPrice["extractionMethod"]): string {
  const labels: Record<string, string> = {
    json_ld: "Structured data",
    visible_text: "Visible text",
    search_snippet: "Search evidence",
    tokenmart: "AI fallback",
    method_consensus: "Method consensus",
  };
  return labels[method ?? ""] ?? "Extraction method unknown";
}

function SearchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </svg>
  );
}

function formatDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds}s`;
  return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
}
