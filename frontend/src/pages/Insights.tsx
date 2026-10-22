import { useCallback, useEffect, useMemo, useState } from "react";
import { usePulse } from "../context/PulseContext";
import {
  api,
  type Cohorts,
  type ScoreExplanation,
  type SegmentDefinition,
} from "../lib/api";

/** Retention over time, why a score is what it is, and the spreadsheet export.
 *
 * The cohort grid greys out months with too few customers rather than hiding
 * them. A retention curve drawn from four people looks exactly as confident as
 * one drawn from four hundred, and an owner acting on the former is being
 * misled by the chart, not informed by it — so the thin rows stay visible and
 * say so.
 */

export default function Insights() {
  const { customers } = usePulse();
  const [cohorts, setCohorts] = useState<Cohorts | null>(null);
  const [segments, setSegments] = useState<SegmentDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [months, setMonths] = useState(12);

  const [selectedId, setSelectedId] = useState<string>("");
  const [explanation, setExplanation] = useState<ScoreExplanation | null>(null);
  const [explaining, setExplaining] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([api.cohorts(months), api.segments()])
      .then(([c, s]) => {
        setCohorts(c);
        setSegments(s.segments);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load insights"))
      .finally(() => setLoading(false));
  }, [months]);

  useEffect(load, [load]);

  // Only customers with a real database row can be explained — the CSV-preview
  // and demo paths persist nothing, so there's no row to score against.
  const explainable = useMemo(
    () => customers.filter((c) => c.db_customer_id).slice(0, 200),
    [customers]
  );

  useEffect(() => {
    if (!selectedId && explainable.length) {
      setSelectedId(explainable[0].db_customer_id as string);
    }
  }, [explainable, selectedId]);

  useEffect(() => {
    if (!selectedId) return;
    setExplaining(true);
    api
      .explainScore(selectedId)
      .then(setExplanation)
      .catch(() => setExplanation(null))
      .finally(() => setExplaining(false));
  }, [selectedId]);

  return (
    <div className="space-y-7">
      <div className="anim-fade-up">
        <h1 className="text-[38px] font-bold tracking-tight" style={{ color: "var(--ink)" }}>
          Insights
        </h1>
        <p className="mt-1 italic" style={{ color: "var(--muted)", fontSize: "15.5px" }}>
          How well you keep customers, and why any one of them is at risk.
        </p>
      </div>

      {error && (
        <p className="text-sm" style={{ color: "var(--accent-dark)" }}>
          {error}
        </p>
      )}

      <section
        className="anim-fade-up rounded-[20px] border p-6"
        style={{ animationDelay: "0.05s", borderColor: "var(--line)", background: "var(--card)" }}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-display text-[20px] font-bold" style={{ color: "var(--ink)" }}>
              Who sticks around
            </h2>
            <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
              Each row is everyone who first visited that month. The percentages are how
              many were still coming in later.
            </p>
          </div>
          <select
            value={months}
            onChange={(e) => setMonths(Number(e.target.value))}
            className="rounded-xl border px-3 py-1.5 text-sm outline-none"
            style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
          >
            {[6, 12, 24].map((m) => (
              <option key={m} value={m}>
                Last {m} months
              </option>
            ))}
          </select>
        </div>

        {loading && !cohorts ? (
          <p className="mt-4 text-sm" style={{ color: "var(--muted)" }}>
            Loading…
          </p>
        ) : !cohorts || cohorts.cohorts.length === 0 ? (
          <p className="mt-4 text-sm" style={{ color: "var(--muted)" }}>
            Not enough visit history yet. Once you have a few months of data this fills in.
          </p>
        ) : (
          <CohortGrid cohorts={cohorts} />
        )}
      </section>

      <section
        className="anim-fade-up rounded-[20px] border p-6"
        style={{ animationDelay: "0.1s", borderColor: "var(--line)", background: "var(--card)" }}
      >
        <h2 className="font-display text-[20px] font-bold" style={{ color: "var(--ink)" }}>
          Why this score
        </h2>
        <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
          The same arithmetic the score itself uses — so you can see which signal actually
          moved the number.
        </p>

        {explainable.length === 0 ? (
          <p className="mt-4 text-sm" style={{ color: "var(--muted)" }}>
            Connect a data source to score real customers.
          </p>
        ) : (
          <>
            <select
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value)}
              className="mt-4 w-full rounded-xl border px-3 py-2 text-sm outline-none sm:max-w-sm"
              style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
            >
              {explainable.map((c) => (
                <option key={c.db_customer_id} value={c.db_customer_id as string}>
                  {c.name} — score {c.score}
                </option>
              ))}
            </select>

            {explaining && !explanation ? (
              <p className="mt-4 text-sm" style={{ color: "var(--muted)" }}>
                Working it out…
              </p>
            ) : (
              explanation && <ScoreBreakdown explanation={explanation} />
            )}
          </>
        )}
      </section>

      <section
        className="anim-fade-up rounded-[20px] border p-6"
        style={{ animationDelay: "0.15s", borderColor: "var(--line)", background: "var(--card)" }}
      >
        <h2 className="font-display text-[20px] font-bold" style={{ color: "var(--ink)" }}>
          Export to a spreadsheet
        </h2>
        <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
          Names, scores, the reasons behind them, and what we'd suggest doing.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <a
            href={api.csvExportUrl()}
            className="rounded-full px-5 py-2 text-sm font-semibold text-white transition hover:-translate-y-px"
            style={{ background: "var(--accent)" }}
          >
            Everyone
          </a>
          {segments.map((s) => (
            <a
              key={s.key}
              href={api.csvExportUrl(s.key)}
              className="rounded-full px-5 py-2 text-sm font-semibold transition hover:-translate-y-px"
              style={{ background: "var(--surface-2)", color: "var(--muted)" }}
            >
              {s.label} ({s.size})
            </a>
          ))}
        </div>
      </section>
    </div>
  );
}

function CohortGrid({ cohorts }: { cohorts: Cohorts }) {
  // Cap the visible columns: beyond a year the grid stops being readable and
  // the newest cohorts have no data there anyway.
  const columns = Math.min(cohorts.max_offset, 12);
  return (
    <div className="mt-5 overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            <th
              className="sticky left-0 bg-inherit px-2 py-1.5 text-left text-xs font-bold uppercase"
              style={{ color: "var(--muted-2)" }}
            >
              First visited
            </th>
            <th className="px-2 py-1.5 text-right text-xs font-bold uppercase" style={{ color: "var(--muted-2)" }}>
              People
            </th>
            {Array.from({ length: columns + 1 }, (_, i) => (
              <th
                key={i}
                className="px-2 py-1.5 text-center text-xs font-bold"
                style={{ color: "var(--muted-2)" }}
              >
                {i === 0 ? "Month 0" : `+${i}`}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cohorts.cohorts.map((cohort) => (
            <tr key={cohort.cohort_month} style={{ opacity: cohort.meaningful ? 1 : 0.45 }}>
              <td
                className="whitespace-nowrap px-2 py-1.5 font-medium"
                style={{ color: "var(--ink)" }}
              >
                {cohort.cohort_month}
                {!cohort.meaningful && (
                  <span
                    className="ml-1.5 text-[10px]"
                    style={{ color: "var(--muted-2)" }}
                    title={`Fewer than ${cohorts.min_meaningful_size} customers — too few to read anything into`}
                  >
                    too few
                  </span>
                )}
              </td>
              <td className="px-2 py-1.5 text-right" style={{ color: "var(--muted)" }}>
                {cohort.size}
              </td>
              {Array.from({ length: columns + 1 }, (_, i) => {
                const value = cohort.retention[i];
                if (value === undefined) {
                  return <td key={i} className="px-2 py-1.5" />;
                }
                return (
                  <td key={i} className="px-1 py-1">
                    <div
                      className="rounded-md py-1 text-center text-xs font-semibold"
                      style={{
                        // One hue, varying alpha: a sequential measure read as
                        // a single ramp, not a traffic-light palette that would
                        // imply thresholds the data doesn't have.
                        background: `rgba(180,83,42,${Math.max(0.06, value * 0.85).toFixed(3)})`,
                        color: value > 0.55 ? "#fff" : "var(--ink)",
                      }}
                    >
                      {Math.round(value * 100)}%
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ScoreBreakdown({ explanation }: { explanation: ScoreExplanation }) {
  const max = Math.max(1, ...explanation.factors.map((f) => f.points));
  return (
    <div className="mt-5">
      <div className="flex flex-wrap items-baseline gap-3">
        <p className="font-display text-[26px] font-bold" style={{ color: "var(--ink)" }}>
          {explanation.score}
        </p>
        <span
          className="rounded-full px-2.5 py-0.5 text-xs font-bold uppercase"
          style={{
            background: explanation.band === "high" ? "var(--accent)" : "var(--surface-2)",
            color: explanation.band === "high" ? "#fff" : "var(--muted)",
          }}
        >
          {explanation.band === "med" ? "medium" : explanation.band} risk
        </span>
        <span className="text-xs" style={{ color: "var(--muted-2)" }}>
          confidence: {explanation.confidence}
        </span>
      </div>

      {explanation.factors.length === 0 ? (
        <p className="mt-3 text-sm" style={{ color: "var(--muted)" }}>
          Not enough history to break this down yet.
        </p>
      ) : (
        <ul className="mt-4 space-y-3">
          {explanation.factors.map((factor) => (
            <li key={factor.key}>
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="font-medium" style={{ color: "var(--ink)" }}>
                  {factor.label}
                </span>
                <span style={{ color: "var(--muted-2)" }}>
                  +{factor.points.toFixed(1)} points
                </span>
              </div>
              <div
                className="mt-1 h-[8px] overflow-hidden rounded-full"
                style={{ background: "var(--surface-2)" }}
              >
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.round((factor.points / max) * 100)}%`,
                    background: "var(--accent)",
                  }}
                />
              </div>
              <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
                {factor.detail}
              </p>
            </li>
          ))}
        </ul>
      )}

      <div
        className="mt-5 rounded-xl border p-4"
        style={{ borderColor: "var(--line-soft)", background: "var(--surface-2)" }}
      >
        <p className="text-xs font-bold uppercase" style={{ color: "var(--muted-2)" }}>
          What we'd do
        </p>
        <p className="mt-1 text-sm font-semibold capitalize" style={{ color: "var(--ink)" }}>
          {explanation.recommended_action.replace(/_/g, " ")}
        </p>
        <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
          {explanation.action_reason}
        </p>
      </div>

      <ul className="mt-4 space-y-1 text-sm" style={{ color: "var(--muted)" }}>
        {explanation.reasons.map((reason) => (
          <li key={reason}>· {reason}</li>
        ))}
      </ul>
    </div>
  );
}
