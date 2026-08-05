import { useState, type ReactNode } from "react";
import MarketSummary, {
  PricingIssues,
  ResearchStages,
  ResearchStats,
  Warnings,
} from "../components/pricing/MarketSummary";
import PricingTable, { Badge, DeliveryPrices, formatPrice } from "../components/pricing/PricingTable";
import {
  buildCompetitorRows,
  buildPricingCsv,
  deriveTenantPricingDefaults,
  getOfferMatchCoverage,
  getMarketPosition,
  mergeTenantBusinessName,
  parseMenuItems,
  useCompetitorPricing,
  type FormState,
  type PricingRunError,
} from "../hooks/useCompetitorPricing";
import {
  formatCurrency,
  type CompetitorPriceHistoryItem,
  type CompetitorPriceQuota,
  type CompetitorPriceResearchResponse,
} from "../lib/api";

// Compatibility exports for existing tests and imports from the former single-file page.
export { Badge, DeliveryPrices, formatPrice, ResearchStats };
export {
  buildPricingCsv,
  deriveTenantPricingDefaults,
  getOfferMatchCoverage,
  getMarketPosition,
  mergeTenantBusinessName,
  parseMenuItems,
  type FormState,
};

export function PricingHistory({ history }: { history: CompetitorPriceHistoryItem[] }) {
  if (!history.length) return null;
  return (
    <div className="glass overflow-hidden">
      <div className="border-b border-white/60 px-5 py-4">
        <h2 className="font-display text-lg font-bold text-slate-900">Pricing trend</h2>
        <p className="text-sm text-slate-500">Recent exact market-median movements.</p>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-100 text-left text-sm">
          <tbody className="divide-y divide-slate-100">
            {history.map((item) => (
              <tr key={item.id}>
                <td className="px-5 py-3">
                  <p className="font-semibold text-slate-800">{item.targetOffer}</p>
                  <p className="text-xs text-slate-400">
                    {new Date(item.generatedAt).toLocaleDateString()}
                  </p>
                </td>
                <td className="px-5 py-3 text-slate-500">
                  {item.priceMedian === null ? "No exact median" : `$${item.priceMedian.toFixed(2)}`}
                </td>
                <td className="px-5 py-3 text-slate-500">
                  {item.changePercent === null || item.changePercent === undefined ? (
                    "No prior comparison"
                  ) : (
                    <span className={Math.abs(item.changePercent) >= 5 ? "font-semibold text-amber-700" : ""}>
                      {Math.abs(item.changePercent) >= 5 && "Alert: "}
                      {item.changePercent > 0 ? "+" : ""}{item.changePercent.toFixed(1)}%
                    </span>
                  )}
                </td>
                <td className="px-5 py-3 text-right text-xs text-slate-400">
                  {item.sampleSize} verified businesses
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function Pricing() {
  const pricing = useCompetitorPricing();
  const [builderOpen, setBuilderOpen] = useState(true);

  return (
    <div className="pricing-page space-y-7">
      <header className="anim-fade-up flex flex-wrap items-end justify-between gap-5">
        <div className="max-w-2xl">
          <p className="eyebrow mb-2" style={{ color: "var(--accent)" }}>Pricing intelligence</p>
          <h1 className="text-[40px] font-bold leading-[1.04] tracking-tight" style={{ color: "var(--ink)" }}>
            Know the market. <span className="pricing-script">Trust the evidence.</span>
          </h1>
          <p className="mt-3 max-w-xl text-[15.5px] leading-relaxed" style={{ color: "var(--muted)" }}>
            Compare a full menu against nearby competitors. Exact published prices stay separate
            from estimates, and every result tells you what worked—or what did not.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <QuotaPill quota={pricing.quota} sample={pricing.sampleMode} />
          {pricing.sampleMode ? (
            <button type="button" onClick={pricing.closeSample} className="pricing-sample-button">
              <ArrowLeftIcon /> Back to live data
            </button>
          ) : (
            <button type="button" onClick={pricing.showSample} className="pricing-sample-button">
              <SparkIcon /> Preview sample café
            </button>
          )}
          {!pricing.sampleMode && (
            <button type="button" onClick={() => setBuilderOpen((open) => !open)} className="pricing-primary-button">
              {builderOpen ? "Close researcher" : "Research your menu"}
            </button>
          )}
        </div>
      </header>

      {pricing.sampleMode && (
        <div className="pricing-sample-notice anim-fade-up">
          <span className="pricing-sample-mark"><SparkIcon /></span>
          <div>
            <p className="font-display text-base font-bold" style={{ color: "var(--ink)" }}>Sample café · Portland market</p>
            <p className="text-xs" style={{ color: "var(--muted)" }}>
              Eight illustrative products with source-shaped evidence. This never changes live data or quota.
            </p>
          </div>
          <Badge tone="cyan">Preview data</Badge>
        </div>
      )}

      {builderOpen && !pricing.sampleMode && (
        <ResearchBuilder
          form={pricing.form}
          setForm={pricing.setForm}
          menuText={pricing.menuText}
          setMenuText={pricing.setMenuText}
          itemCount={pricing.parsedMenu.length}
          quota={pricing.quota}
          progress={pricing.batchProgress}
          onSubmit={pricing.submitBatch}
        />
      )}

      {pricing.notice && (
        <div className="rounded-2xl border border-cyan-200 bg-cyan-50/75 px-4 py-3 text-sm text-cyan-800" role="status">
          {pricing.notice}
        </div>
      )}

      {Object.keys(pricing.errors).length > 0 && <ResearchErrors errors={pricing.errors} />}

      {pricing.initialLoading ? (
        <PricingPortfolioSkeleton />
      ) : pricing.results.length === 0 ? (
        <PricingEmptyState onStart={() => setBuilderOpen(true)} />
      ) : (
        <>
          <PortfolioPulse
            pulse={pricing.portfolioPulse}
            lastDurationMs={pricing.lastDurationMs}
            lastUpdated={pricing.results[0]?.metadata.generatedAt ?? null}
          />
          <div>
            <h2 className="font-display text-[26px] font-bold" style={{ color: "var(--ink)" }}>Your pricing portfolio</h2>
            <p className="text-sm" style={{ color: "var(--muted-2)" }}>
              Open a product to inspect exact evidence, estimates, provider stages, and sources.
            </p>
          </div>
          <div className="pricing-card-grid">
            {pricing.results.map((result, index) => {
              const key = result.query.targetOffer.trim().toLocaleLowerCase();
              return (
                <ProductPricingCard
                  key={key}
                  result={result}
                  history={pricing.history.filter(
                    (item) => item.targetOffer.trim().toLocaleLowerCase() === key
                  )}
                  expanded={pricing.expandedOffer === key}
                  loading={pricing.loadingOffers.has(key)}
                  sample={pricing.sampleMode}
                  onToggle={() => pricing.setExpandedOffer(pricing.expandedOffer === key ? null : key)}
                  onRefresh={() => void pricing.refreshResult(result)}
                  onExport={() => exportPricingCsv(result)}
                  style={{ animationDelay: `${Math.min(index, 6) * 0.05}s` }}
                />
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function ResearchBuilder({
  form,
  setForm,
  menuText,
  setMenuText,
  itemCount,
  quota,
  progress,
  onSubmit,
}: {
  form: FormState;
  setForm: (form: FormState) => void;
  menuText: string;
  setMenuText: (value: string) => void;
  itemCount: number;
  quota: CompetitorPriceQuota | null;
  progress: { done: number; total: number } | null;
  onSubmit: (event: React.FormEvent) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="pricing-builder anim-fade-up">
      <div className="pricing-builder-glow" />
      <div className="relative">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="eyebrow" style={{ color: "var(--on-espresso-accent)" }}>Evidence-first market scan</p>
            <h2 className="mt-1 font-display text-[27px] font-semibold text-white">Paste up to 10 menu items</h2>
            <p className="mt-1 max-w-xl text-sm leading-relaxed" style={{ color: "#D8C6B7" }}>
              One item per line; your current price is optional. Two workers research the queue without exceeding the daily cap.
            </p>
          </div>
          <span className="rounded-full border border-white/15 bg-white/5 px-3 py-2 text-xs font-semibold text-[#E8D8CB]">
            {itemCount}/10 parsed
          </span>
        </div>

        <label className="mt-6 block">
          <span className="eyebrow" style={{ color: "#CDB9A8" }}>Product or service — current price</span>
          <textarea
            value={menuText}
            onChange={(event) => setMenuText(event.target.value)}
            rows={6}
            placeholder={"Cappuccino — $4.75\nCold brew — $5.25\nBlueberry scone"}
            className="pricing-menu-textarea"
          />
        </label>

        <div className="pricing-location-grid">
          <DarkField label="Business name" value={form.businessName} placeholder="Northstar Coffee" onChange={(value) => setForm({ ...form, businessName: value })} />
          <DarkField label="Business category" value={form.businessCategory} required placeholder="Coffee shop" onChange={(value) => setForm({ ...form, businessCategory: value })} />
          <DarkField label="City" value={form.city} required placeholder="Fremont" onChange={(value) => setForm({ ...form, city: value })} />
          <DarkField label="State" value={form.state} required placeholder="CA" onChange={(value) => setForm({ ...form, state: value })} />
          <DarkField label="Street address" value={form.address} placeholder="3602 Thornton Ave" onChange={(value) => setForm({ ...form, address: value })} />
          <DarkField label="ZIP" value={form.zip} placeholder="94536" onChange={(value) => setForm({ ...form, zip: value })} />
          <DarkField label="Radius in miles" type="number" min="1" max="25" value={form.radiusMiles} onChange={(value) => setForm({ ...form, radiusMiles: value })} />
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-between gap-4 border-t pt-5" style={{ borderColor: "rgba(255,255,255,.1)" }}>
          <p className="text-xs" style={{ color: "#BFA999" }}>
            Exact published prices only · estimates require 3+ verified peers · {quota?.remaining ?? 10} runs available today
          </p>
          <button type="submit" disabled={Boolean(progress) || itemCount === 0} className="pricing-cream-button pricing-research-button">
            {progress ? (
              <><SpinnerIcon /> Researching {Math.min(progress.done + 1, progress.total)} of {progress.total}</>
            ) : (
              <>Research {itemCount || "your"} {itemCount === 1 ? "item" : "items"} <ArrowIcon /></>
            )}
          </button>
        </div>
        {progress && (
          <div className="mt-4 h-1.5 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,.1)" }}>
            <div className="h-full rounded-full transition-all duration-500" style={{ width: `${(progress.done / progress.total) * 100}%`, background: "var(--on-espresso-accent)" }} />
          </div>
        )}
      </div>
    </form>
  );
}

export function ProductPricingCard({
  result,
  history,
  expanded,
  loading,
  sample,
  onToggle,
  onRefresh,
  onExport,
  style,
}: {
  result: CompetitorPriceResearchResponse;
  history: CompetitorPriceHistoryItem[];
  expanded: boolean;
  loading: boolean;
  sample: boolean;
  onToggle: () => void;
  onRefresh: () => void;
  onExport: () => void;
  style?: React.CSSProperties;
}) {
  const position = getMarketPosition(result);
  const exact = result.marketSummary;
  const estimate = result.estimateSummary;
  const matchCoverage = getOfferMatchCoverage(result);
  const rows = buildCompetitorRows(result);
  const deliveryRows = result.competitors.flatMap((competitor) =>
    competitor.prices.filter((price) => price.priceChannel === "delivery").map((price) => ({ competitor, price }))
  );
  const failedStage = result.metadata.stages.find((stage) => stage.status === "failed");

  return (
    <article className={`pricing-product-card anim-fade-up ${expanded ? "is-expanded" : ""}`} style={style}>
      {loading && <div className="pricing-card-loading"><SpinnerIcon /> Updating market</div>}
      <div className="pricing-card-summary">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="eyebrow truncate" style={{ color: "var(--muted-2)" }}>{result.query.businessCategory}</p>
            <h3 className="mt-2 line-clamp-2 font-display text-[23px] font-bold leading-tight" style={{ color: "var(--ink)" }}>{result.query.targetOffer}</h3>
          </div>
          <ResearchStatusBadge status={result.status} />
        </div>

        <div className="mt-5 grid grid-cols-2 gap-4">
          <Metric label="Your price" value={result.query.currentPrice == null ? "—" : formatCurrency(result.query.currentPrice, true)} />
          <Metric
            label="Exact market median"
            value={exact.priceMedian === null ? "—" : formatCurrency(exact.priceMedian, true)}
            accent={exact.priceMedian !== null}
          />
        </div>

        {estimate && (
          <div className="mt-4 rounded-xl border border-indigo-100 bg-indigo-50/70 p-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[.12em] text-indigo-500">Verified-peer estimate</p>
                <p className="mt-1 font-display text-xl font-bold text-indigo-900">{formatCurrency(estimate.priceMedian, true)}</p>
              </div>
              <Badge tone="cyan">{estimate.sampleSize} peers</Badge>
            </div>
            <p className="mt-1 text-xs text-indigo-600">{formatCurrency(estimate.priceLow, true)}–{formatCurrency(estimate.priceHigh, true)} · not an observed competitor price</p>
          </div>
        )}

        <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
          <PositionPill position={position} />
          <div className="flex flex-wrap gap-1.5">
            <Badge tone={exact.sampleSize >= 2 ? "green" : "amber"}>
              {matchCoverage.exactBusinesses} exact {matchCoverage.exactBusinesses === 1 ? "price" : "prices"}
            </Badge>
            {matchCoverage.closeBusinesses > 0 && (
              <Badge tone="amber">
                {matchCoverage.closeBusinesses} close {matchCoverage.closeBusinesses === 1 ? "equivalent" : "equivalents"}
              </Badge>
            )}
            {result.metadata.cached && <Badge tone="slate">Cached</Badge>}
          </div>
        </div>
        {matchCoverage.closeMatches.length > 0 && (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/70 p-3">
            <p className="text-[10px] font-bold uppercase tracking-[.12em] text-amber-700">
              Close matches shown separately
            </p>
            <div className="mt-1.5 space-y-1">
              {matchCoverage.closeMatches.slice(0, 2).map((match) => (
                <p
                  key={`${match.competitorName}-${match.offerName}`}
                  className="text-xs text-amber-900"
                >
                  <span className="font-semibold">{match.offerName}</span> at {match.competitorName}
                  {match.score !== null ? ` · ${Math.round(match.score * 100)}% name match` : ""}
                </p>
              ))}
              {matchCoverage.closeMatches.length > 2 && (
                <p className="text-xs text-amber-700">
                  +{matchCoverage.closeMatches.length - 2} more close equivalents
                </p>
              )}
            </div>
            <p className="mt-1.5 text-[11px] text-amber-700">
              These are visible for context but never included in the exact market median.
            </p>
          </div>
        )}
        {failedStage && <p className="mt-3 text-xs font-semibold text-red-700">Stopped at {stageLabel(failedStage.stage)}</p>}
      </div>

      <button type="button" onClick={onToggle} aria-expanded={expanded} className="pricing-card-toggle">
        <span>{expanded ? "Close evidence" : "Inspect evidence"}</span>
        <span className="pricing-toggle-circle"><ChevronIcon open={expanded} /></span>
      </button>

      {expanded && (
        <div className="pricing-card-details space-y-5">
          <MarketSummary result={result} />
          {result.issues.length > 0 && <PricingIssues issues={result.issues} />}
          {result.warnings.length > 0 && <Warnings warnings={result.warnings} />}
          <ResearchStages result={result} />
          <ResearchStats result={result} />
          <PricingTable result={result} rows={rows} />
          {deliveryRows.length > 0 && (
            <DeliveryPrices
              rows={deliveryRows}
              summary={result.channelSummaries?.delivery ?? null}
              requestedOffer={result.query.targetOffer}
            />
          )}
          <PricingHistory history={history} />
          <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4" style={{ borderColor: "var(--border)" }}>
            <p className="text-xs text-slate-500">
              {sample ? "Illustrative preview" : `${result.metadata.pipelineVersion} · ${formatRelativeTime(result.metadata.generatedAt)} · $${result.metadata.providerCostUsd.toFixed(4)} provider cost`}
            </p>
            <div className="flex gap-2">
              {!sample && <button type="button" disabled={loading} onClick={onRefresh} className="pricing-detail-button"><RefreshIcon /> Refresh</button>}
              <button type="button" onClick={onExport} className="pricing-detail-button"><DownloadIcon /> Export CSV</button>
            </div>
          </div>
        </div>
      )}
    </article>
  );
}

function PortfolioPulse({
  pulse,
  lastDurationMs,
  lastUpdated,
}: {
  pulse: { total: number; complete: number; partial: number; noEvidence: number; exactPrices: number };
  lastDurationMs: number | null;
  lastUpdated: string | null;
}) {
  return (
    <section className="pricing-pulse-card anim-fade-up">
      <div className="pricing-pulse-orbit orbit-one" />
      <div className="pricing-pulse-orbit orbit-two" />
      <div className="relative grid gap-6 lg:grid-cols-[1.15fr_2fr] lg:items-center">
        <div>
          <div className="flex items-center gap-2"><span className="pricing-live-dot" /><p className="eyebrow" style={{ color: "#CDAA90" }}>Pipeline health</p></div>
          <p className="mt-3 font-display text-[29px] font-semibold leading-tight text-white">
            {pulse.complete} of {pulse.total} products have a complete scan.
          </p>
          <p className="mt-2 text-sm leading-relaxed" style={{ color: "#CDB9A8" }}>
            A no-evidence result is honest—not a guessed price or a false success.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <PulseStat label="Products" value={String(pulse.total)} />
          <PulseStat label="Complete" value={String(pulse.complete)} accent="#93B684" />
          <PulseStat label="Partial / none" value={String(pulse.partial + pulse.noEvidence)} accent="#E0A074" />
          <PulseStat label="Exact prices" value={String(pulse.exactPrices)} />
        </div>
      </div>
      <div className="relative mt-5 flex flex-wrap gap-x-5 gap-y-1 border-t pt-3 text-[11px]" style={{ borderColor: "rgba(255,255,255,.09)", color: "#A9907D" }}>
        {lastUpdated && <span>Latest scan {formatRelativeTime(lastUpdated)}</span>}
        {lastDurationMs !== null && <span>Last batch completed in {formatDuration(lastDurationMs)}</span>}
        <span>Exact and estimated values never mix</span>
      </div>
    </section>
  );
}

function ResearchErrors({ errors }: { errors: Record<string, PricingRunError> }) {
  return (
    <div className="grid gap-2" role="alert">
      {Object.entries(errors).map(([key, error]) => (
        <div key={key} className="pricing-error flex-wrap">
          <span className="pricing-error-dot" />
          <span className="font-semibold">{titleCase(key)}</span>
          <span style={{ color: "var(--muted)" }}>{error.message}</span>
          {error.stage && <Badge tone="amber">Stage: {stageLabel(error.stage)}</Badge>}
          {error.code && <code className="text-[10px] text-slate-500">{error.code}</code>}
          {error.retryable === true && <span className="text-xs font-semibold">Safe to retry</span>}
        </div>
      ))}
    </div>
  );
}

function ResearchStatusBadge({ status }: { status: CompetitorPriceResearchResponse["status"] }) {
  const config = {
    complete: { label: "Complete", className: "is-below" },
    partial: { label: "Partial", className: "is-market" },
    no_evidence: { label: "No evidence", className: "is-above" },
  }[status];
  return <span className={`pricing-position-badge ${config.className}`}><span />{config.label}</span>;
}

function PositionPill({ position }: { position: ReturnType<typeof getMarketPosition> }) {
  return <span className={`pricing-position-badge is-${position.key}`}><span />{position.label}</span>;
}

function QuotaPill({ quota, sample }: { quota: CompetitorPriceQuota | null; sample: boolean }) {
  if (sample) return <Badge tone="cyan">Quota untouched</Badge>;
  if (!quota) return <Badge tone="slate">Quota loading</Badge>;
  return <Badge tone={quota.remaining > 2 ? "green" : "amber"}>{quota.remaining}/{quota.dailyLimit} runs left today</Badge>;
}

function Metric({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return (
    <div>
      <p className="text-[10px] font-bold uppercase tracking-[.12em]" style={{ color: "var(--muted-2)" }}>{label}</p>
      <p className="stat-number mt-1 text-[29px]" style={{ color: accent ? "var(--accent-dark)" : "var(--ink)" }}>{value}</p>
    </div>
  );
}

function PulseStat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return <div className="pricing-pulse-stat"><p className="stat-number text-[27px]" style={{ color: accent ?? "#FFF9F2" }}>{value}</p><p className="mt-1 text-[11px]" style={{ color: "#BFA999" }}>{label}</p></div>;
}

function PricingPortfolioSkeleton() {
  return (
    <div className="pricing-card-grid" aria-label="Loading saved pricing">
      {[0, 1, 2].map((item) => <div key={item} className="pricing-product-card p-5"><div className="pricing-skeleton-line w-24" /><div className="pricing-skeleton-line mt-5 h-7 w-2/3" /><div className="pricing-skeleton-line mt-7 w-full" /><div className="pricing-skeleton-line mt-3 w-4/5" /></div>)}
    </div>
  );
}

function PricingEmptyState({ onStart }: { onStart: () => void }) {
  return (
    <div className="glass pricing-empty text-center">
      <div className="pricing-empty-illustration" aria-hidden="true">
        <div className="empty-card card-one"><span>Espresso</span><b>$3.75</b></div>
        <div className="empty-card card-two"><span>Cappuccino</span><b>$5.15</b></div>
        <div className="empty-card card-three"><span>Cold brew</span><b>$5.35</b></div>
      </div>
      <div>
        <p className="eyebrow" style={{ color: "var(--accent)" }}>No saved research yet</p>
        <h2 className="mt-2 font-display text-2xl font-bold text-slate-900">Build your first evidence-backed portfolio</h2>
        <p className="mt-2 text-sm leading-relaxed text-slate-500">Paste one product or a full menu. If published evidence is missing, the result will say so clearly.</p>
        <button type="button" onClick={onStart} className="pricing-primary-button mt-5">Research your menu</button>
      </div>
    </div>
  );
}

function DarkField({ label, value, onChange, type = "text", required = false, min, max, placeholder }: { label: string; value: string; onChange: (value: string) => void; type?: string; required?: boolean; min?: string; max?: string; placeholder?: string }) {
  return <label className="block"><span className="eyebrow" style={{ color: "#BFA999" }}>{label}</span><input className="pricing-dark-input" type={type} value={value} required={required} min={min} max={max} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} /></label>;
}

function exportPricingCsv(result: CompetitorPriceResearchResponse) {
  const blob = new Blob([buildPricingCsv(result)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${result.query.targetOffer.toLocaleLowerCase().replace(/[^a-z0-9]+/g, "-")}-pricing.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function stageLabel(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function titleCase(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDuration(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
}

function formatRelativeTime(value: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

function Icon({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <svg className={className} width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>;
}
function SparkIcon() { return <Icon><path d="m12 3 1.4 4.2L18 9l-4.6 1.8L12 15l-1.4-4.2L6 9l4.6-1.8L12 3Z" /><path d="m19 15 .7 2.3L22 18l-2.3.7L19 21l-.7-2.3L16 18l2.3-.7L19 15Z" /></Icon>; }
function ArrowLeftIcon() { return <Icon><path d="m15 18-6-6 6-6" /></Icon>; }
function ArrowIcon() { return <Icon><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></Icon>; }
function RefreshIcon() { return <Icon><path d="M20 11a8.1 8.1 0 0 0-15.5-2M4 5v4h4" /><path d="M4 13a8.1 8.1 0 0 0 15.5 2M20 19v-4h-4" /></Icon>; }
function DownloadIcon() { return <Icon><path d="M12 3v12" /><path d="m7 10 5 5 5-5" /><path d="M5 21h14" /></Icon>; }
function ChevronIcon({ open }: { open: boolean }) { return <Icon className={`transition-transform ${open ? "rotate-180" : ""}`}><path d="m6 9 6 6 6-6" /></Icon>; }
function SpinnerIcon() { return <Icon className="pricing-spinner"><circle cx="12" cy="12" r="9" opacity=".25" /><path d="M21 12a9 9 0 0 0-9-9" /></Icon>; }
