import { Link } from "react-router-dom";
import { usePulse } from "../context/PulseContext";

/** Shown when the tenant has no data yet (they skipped setup). */
export default function EmptyState() {
  const { reloadDemo } = usePulse();

  return (
    <div className="grid min-h-[60vh] place-items-center">
      <div className="glass-strong anim-fade-up max-w-md p-8 text-center">
        <div
          className="mx-auto grid h-14 w-14 place-items-center rounded-2xl"
          style={{ background: "var(--surface-3)" }}
        >
          <PlugIcon />
        </div>
        <h2 className="font-display mt-4 text-2xl font-extrabold tracking-tight" style={{ color: "var(--ink)" }}>
          No customer data yet
        </h2>
        <p className="mt-2 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
          Churnary can't spot at-risk customers until it can see them. Connect your
          Square or Stripe account — or import a CSV — and we'll score everyone in
          under two minutes.
        </p>
        <Link
          to="/setup"
          className="mt-5 block w-full rounded-full px-4 py-3 text-sm font-semibold transition hover:-translate-y-px"
          style={{ background: "var(--accent)", color: "#fff", boxShadow: "0 6px 16px -6px rgba(180,83,42,.7)" }}
        >
          Connect your data
        </Link>
        <button
          onClick={reloadDemo}
          className="mt-2 w-full rounded-full border px-4 py-3 text-sm font-medium transition hover:brightness-95"
          style={{ borderColor: "var(--border)", color: "var(--muted)", background: "var(--surface-2)" }}
        >
          Explore with sample data first
        </button>
      </div>
    </div>
  );
}

function PlugIcon() {
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#B4532A"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22v-5" /><path d="M9 8V2" /><path d="M15 8V2" />
      <path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8z" />
    </svg>
  );
}
