import type { Segment } from "../lib/api";
import { SEGMENTS } from "../lib/segments";

export default function RiskBadge({ segment, score }: { segment: Segment; score?: number }) {
  const meta = SEGMENTS[segment];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${meta.bg}`}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: meta.color }} />
      {meta.health}
      {score !== undefined && <span className="opacity-70">{score}</span>}
    </span>
  );
}
