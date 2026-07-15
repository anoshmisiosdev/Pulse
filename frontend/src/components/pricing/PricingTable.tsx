import {
  formatCurrency,
  type CompetitorPrice,
  type CompetitorPriceCompetitor,
  type CompetitorPriceResearchResponse,
} from "../../lib/api";
import type { CompetitorTableRow } from "../../hooks/useCompetitorPricing";

/** In-store competitor prices with evidence and sources. */
export default function PricingTable({
  result,
  rows,
}: {
  result: CompetitorPriceResearchResponse;
  rows: CompetitorTableRow[];
}) {
  return (
    <div className="glass overflow-hidden">
      <div className="border-b border-white/60 px-5 py-4">
        <h2 className="font-display text-lg font-bold text-slate-900">
          Competitors researched for {result.query.targetOffer}
        </h2>
        <p className="text-sm text-slate-500">
          {result.competitors.length} found near {result.query.locationLabel};{" "}
          {result.marketSummary.sampleSize} with source-backed prices.
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
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} className="px-5 py-8 text-center text-slate-400">
                  No competitors were found.
                </td>
              </tr>
            )}
            {rows.map((row, idx) => (
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
                    <a
                      href={row.price.sourceUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="font-semibold text-cyan-700 hover:underline"
                    >
                      {row.price.sourceTitle || "Open source"}
                    </a>
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
          <Badge tone="amber">Median {formatCurrency(summary.priceMedian)}</Badge>
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
            <p className="mt-2 text-sm text-slate-600">“{price.evidenceText}”</p>
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

export function Confidence({ value }: { value: number }) {
  const color = value >= 0.75 ? "#10b981" : value >= 0.5 ? "#f59e0b" : "#ef4444";
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-white/70 px-2.5 py-1 text-xs font-semibold text-slate-700">
      <span className="h-2 w-2 rounded-full" style={{ background: color }} />
      {Math.round(value * 100)}%
    </span>
  );
}

export function formatPrice(price: CompetitorPrice): string {
  if (price.priceType === "quote_based") return "Quote";
  if (price.priceMin !== null && price.priceMax !== null && price.priceMin !== price.priceMax) {
    return `${formatCurrency(price.priceMin)}-${formatCurrency(price.priceMax)}`;
  }
  const value = price.priceMin ?? price.priceMax;
  return value === null ? "Unknown" : formatCurrency(value);
}
