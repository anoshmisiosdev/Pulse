import { formatCurrency, type CompetitorPriceResearchResponse } from "../../lib/api";

export default function MarketSummary({ result }: { result: CompetitorPriceResearchResponse }) {
  const s = result.marketSummary;
  return (
    <div className="glass grid gap-4 p-5 md:grid-cols-[1.3fr_2fr]">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Market summary</p>
        <p className="mt-2 font-display text-3xl font-bold text-slate-900">
          {s.priceMedian === null ? "No median" : formatCurrency(s.priceMedian)}
        </p>
        <p className="mt-1 text-sm text-slate-500">Median in-store price</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-4">
        <MiniStat label="Businesses" value={String(s.sampleSize)} />
        <MiniStat label="Low" value={s.priceLow === null ? "—" : formatCurrency(s.priceLow)} />
        <MiniStat label="High" value={s.priceHigh === null ? "—" : formatCurrency(s.priceHigh)} />
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
    <div className="glass grid gap-3 p-4 sm:grid-cols-4">
      <MiniStat label="Sources discovered" value={String(stats.sourcesDiscovered)} />
      <MiniStat label="Sources checked" value={String(stats.sourcesChecked)} />
      <MiniStat label="Sources accepted" value={String(stats.sourcesAccepted)} />
      <MiniStat label="Corroborated businesses" value={String(stats.corroboratedCompetitors)} />
    </div>
  );
}

export function Warnings({ warnings }: { warnings: string[] }) {
  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50/80 p-4 text-sm text-amber-800">
      <p className="font-semibold">Warnings</p>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {warnings.map((warning) => <li key={warning}>{warning}</li>)}
      </ul>
    </div>
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
