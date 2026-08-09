import {
  formatCurrency,
  type CompetitorPriceIssue,
  type CompetitorPriceResearchResponse,
} from "../../lib/api";

export default function MarketSummary({ result }: { result: CompetitorPriceResearchResponse }) {
  const exact = result.marketSummary;
  const estimate = result.estimateSummary;
  return (
    <div className="glass p-5">
      <div className="grid gap-5 md:grid-cols-[1.2fr_2fr]">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Exact observed benchmark
          </p>
          <p className="mt-2 font-display text-3xl font-bold text-slate-900">
            {exact.priceMedian === null ? "Not established" : formatCurrency(exact.priceMedian, true)}
          </p>
          <p className="mt-1 text-sm text-slate-500">
            {exact.priceMedian === null
              ? "At least two verified businesses are required for an exact market median."
              : `Median across ${exact.sampleSize} verified local businesses.`}
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-4">
          <MiniStat label="Verified businesses" value={String(exact.sampleSize)} />
          <MiniStat label="Low" value={exact.priceLow === null ? "—" : formatCurrency(exact.priceLow, true)} />
          <MiniStat label="High" value={exact.priceHigh === null ? "—" : formatCurrency(exact.priceHigh, true)} />
          <MiniStat label="Confidence" value={`${Math.round(exact.confidence * 100)}%`} />
          <p className="sm:col-span-4 text-sm text-slate-600">{exact.recommendedPositioning}</p>
        </div>
      </div>

      {estimate && (
        <div className="mt-5 grid gap-4 rounded-2xl border border-indigo-100 bg-indigo-50/60 p-4 sm:grid-cols-[1.2fr_2fr]">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-indigo-500">
              Verified-peer estimate · not an observed price
            </p>
            <p className="mt-2 font-display text-2xl font-bold text-indigo-950">
              {formatCurrency(estimate.priceMedian, true)}
            </p>
          </div>
          <p className="self-center text-sm leading-relaxed text-indigo-700">
            Range {formatCurrency(estimate.priceLow, true)}–{formatCurrency(estimate.priceHigh, true)},
            derived from {estimate.sampleSize} source-verified close equivalents observed within the
            last {estimate.maxAgeDays} days. It is never mixed into the exact market summary.
          </p>
        </div>
      )}
    </div>
  );
}

export function ResearchStats({ result }: { result: CompetitorPriceResearchResponse }) {
  const stats = result.metadata.researchStats;
  return (
    <div className="glass grid gap-3 p-4 sm:grid-cols-3 lg:grid-cols-6">
      <MiniStat label="Competitors found" value={String(stats.competitorsDiscovered)} />
      <MiniStat label="Sources discovered" value={String(stats.sourcesDiscovered)} />
      <MiniStat label="Sources checked" value={String(stats.sourcesChecked)} />
      <MiniStat label="Sources accepted" value={String(stats.sourcesAccepted)} />
      <MiniStat label="Deterministic" value={String(stats.deterministicExtractions ?? 0)} />
      <MiniStat label="AI fallbacks" value={String(stats.aiExtractions ?? 0)} />
    </div>
  );
}

export function ResearchStages({ result }: { result: CompetitorPriceResearchResponse }) {
  if (!result.metadata.stages.length) return null;
  return (
    <div className="glass overflow-hidden">
      <div className="border-b border-white/60 px-5 py-4">
        <h2 className="font-display text-lg font-bold text-slate-900">Pipeline stages</h2>
        <p className="text-sm text-slate-500">Each provider handoff is reported independently.</p>
      </div>
      <div className="grid gap-px bg-slate-100 sm:grid-cols-2 lg:grid-cols-3">
        {result.metadata.stages.map((stage) => (
          <div key={stage.stage} className="bg-white/80 p-4">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-semibold capitalize text-slate-800">
                {stage.stage.replaceAll("_", " ")}
              </p>
              <StageBadge status={stage.status} />
            </div>
            <p className="mt-2 text-xs text-slate-500">
              {stage.provider || "No provider"} · {stage.attempts} attempt{stage.attempts === 1 ? "" : "s"} · {stage.durationMs}ms
            </p>
            {stage.code && <code className="mt-2 block text-[10px] text-red-600">{stage.code}</code>}
          </div>
        ))}
      </div>
    </div>
  );
}

export function PricingIssues({ issues }: { issues: CompetitorPriceIssue[] }) {
  return (
    <div className="space-y-2">
      {issues.map((issue, index) => (
        <div
          key={`${issue.code}-${index}`}
          className={`rounded-2xl border p-4 text-sm ${
            issue.severity === "error"
              ? "border-red-200 bg-red-50/80 text-red-800"
              : issue.severity === "warning"
                ? "border-amber-200 bg-amber-50/80 text-amber-800"
                : "border-cyan-200 bg-cyan-50/80 text-cyan-800"
          }`}
        >
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-semibold">{issue.message}</p>
            <span className="rounded-full bg-white/60 px-2 py-0.5 text-[10px] font-semibold capitalize">
              {issue.stage.replaceAll("_", " ")}
            </span>
            {issue.retryable && <span className="text-xs font-semibold">Retryable</span>}
          </div>
          <code className="mt-1 block text-[10px] opacity-70">{issue.code}</code>
        </div>
      ))}
    </div>
  );
}

export function Warnings({ warnings }: { warnings: string[] }) {
  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50/80 p-4 text-sm text-amber-800">
      <p className="font-semibold">Additional warnings</p>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {warnings.map((warning) => <li key={warning}>{warning}</li>)}
      </ul>
    </div>
  );
}

function StageBadge({ status }: { status: CompetitorPriceResearchResponse["metadata"]["stages"][number]["status"] }) {
  const classes = {
    ok: "bg-emerald-50 text-emerald-700",
    degraded: "bg-amber-50 text-amber-700",
    failed: "bg-red-50 text-red-700",
    skipped: "bg-slate-100 text-slate-500",
  }[status];
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${classes}`}>{status}</span>;
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/60 bg-white/45 p-3">
      <p className="text-xs text-slate-400">{label}</p>
      <p className="mt-1 font-display text-lg font-bold text-slate-800">{value}</p>
    </div>
  );
}
