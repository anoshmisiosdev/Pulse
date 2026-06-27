import type { Band } from "../lib/api";

const STYLES: Record<Band, string> = {
  high: "bg-red-100 text-red-700 ring-red-600/20",
  med: "bg-amber-100 text-amber-700 ring-amber-600/20",
  low: "bg-emerald-100 text-emerald-700 ring-emerald-600/20",
};

const LABELS: Record<Band, string> = { high: "High", med: "Medium", low: "Low" };

export default function RiskBadge({ band }: { band: Band }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium
                  ring-1 ring-inset ${STYLES[band]}`}
    >
      {LABELS[band]}
    </span>
  );
}
