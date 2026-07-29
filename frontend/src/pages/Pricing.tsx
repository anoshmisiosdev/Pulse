import MarketSummary, { ResearchStats, Warnings } from "../components/pricing/MarketSummary";
import PricingTable, { DeliveryPrices } from "../components/pricing/PricingTable";
import { useCompetitorPricing } from "../hooks/useCompetitorPricing";
import type { CompetitorPriceHistoryItem } from "../lib/api";

// Re-exports kept for tests and any external imports of the old single-file page.
export { Badge, formatPrice } from "../components/pricing/PricingTable";
export { ResearchStats, DeliveryPrices };
export {
  buildPricingCsv,
  deriveTenantPricingDefaults,
  getMarketPosition,
  mergeTenantBusinessName,
  parseMenuItems,
  type FormState,
} from "../hooks/useCompetitorPricing";

export function PricingHistory({ history }: { history: CompetitorPriceHistoryItem[] }) {
  if (!history.length) return null;
  return (
    <div className="glass overflow-hidden">
      <div className="border-b border-white/60 px-5 py-4">
        <h2 className="font-display text-lg font-bold text-slate-900">Pricing trend</h2>
        <p className="text-sm text-slate-500">Recent market-median movements.</p>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-100 text-left text-sm">
          <tbody className="divide-y divide-slate-100">
            {history.map((item) => (
              <tr key={item.id}>
                <td className="px-5 py-3 font-semibold text-slate-800">{item.targetOffer}</td>
                <td className="px-5 py-3 text-slate-500">
                  {item.priceMedian === null ? "No median" : `$${item.priceMedian.toFixed(2)}`}
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
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function Pricing() {
  const {
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
  } = useCompetitorPricing();

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
            help="This is the exact offer Churnary searches for at nearby competitors."
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
            onChange={(v) => setForm({ ...form, businessName: v })}
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
          <PricingTable result={result} rows={competitorRows} />
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
