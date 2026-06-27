import { useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { usePulse } from "../context/PulseContext";
import { useAuth } from "../context/AuthContext";
import { formatCurrency } from "../lib/api";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/customers", label: "Customers" },
  { to: "/retention", label: "Retention" },
  { to: "/automations", label: "Automations" },
];

export default function AppShell({ children }: { children: ReactNode }) {
  const { businessName: dataBusiness } = usePulse();
  const { user, logout } = useAuth();
  const businessName = user?.business_name ?? dataBusiness;
  const [navOpen, setNavOpen] = useState(false);
  const [briefing, setBriefing] = useState(false);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 glass-strong border-b border-white/40">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setNavOpen(true)}
              className="rounded-lg p-1.5 text-slate-600 hover:bg-white/60"
              aria-label="Open menu"
            >
              <MenuIcon />
            </button>
            <div className="flex items-center gap-2">
              <div className="grid h-8 w-8 place-items-center rounded-xl border border-slate-900/10 bg-white/70">
                <PulseGlyph />
              </div>
              <span className="font-display text-xl font-bold tracking-tight">Pulse</span>
            </div>
          </div>

          <div className="hidden items-center gap-2 text-sm font-medium text-slate-600 sm:flex">
            <WaveIcon />
            {businessName}
            <span className="h-2 w-2 rounded-full bg-emerald-400" />
          </div>

          <button
            onClick={() => setBriefing(true)}
            className="flex items-center gap-2 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-dark"
            style={{ background: "var(--primary)" }}
          >
            <SpeakerIcon /> Daily Briefing
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-5 py-8">{children}</main>

      {/* Slide-out nav */}
      {navOpen && (
        <div className="fixed inset-0 z-40 animate-fade-in" onClick={() => setNavOpen(false)}>
          <div className="absolute inset-0 bg-slate-900/30" />
          <nav
            className="absolute left-0 top-0 h-full w-64 glass-strong animate-slide-in p-5"
            onClick={(e) => e.stopPropagation()}
            style={{ animationName: "fadeIn" }}
          >
            <div className="mb-6 flex items-center gap-2">
              <div className="grid h-8 w-8 place-items-center rounded-xl border border-slate-900/10 bg-white/70">
                <PulseGlyph />
              </div>
              <span className="font-display text-lg font-bold">Pulse</span>
            </div>
            <div className="space-y-1">
              {NAV.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.end}
                  onClick={() => setNavOpen(false)}
                  className={({ isActive }) =>
                    `block rounded-xl px-3 py-2.5 text-sm font-medium transition ${
                      isActive
                        ? "bg-primary text-white"
                        : "text-slate-600 hover:bg-white/70"
                    }`
                  }
                >
                  {n.label}
                </NavLink>
              ))}
            </div>

            <div className="absolute inset-x-5 bottom-5 border-t border-white/50 pt-4">
              <p className="truncate text-sm font-medium text-slate-700">{businessName}</p>
              {user?.email && <p className="truncate text-xs text-slate-400">{user.email}</p>}
              <button
                onClick={logout}
                className="mt-3 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm font-medium text-slate-600 hover:bg-white/70"
              >
                Sign out
              </button>
            </div>
          </nav>
        </div>
      )}

      {briefing && <BriefingModal onClose={() => setBriefing(false)} />}
    </div>
  );
}

function BriefingModal({ onClose }: { onClose: () => void }) {
  const { businessName, customers, portfolio, activity, revenueRecovered } = usePulse();
  const s = portfolio?.summary;
  const top = customers[0];
  const sentToday = activity.filter((a) => a.status === "sent").length;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 animate-fade-in"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md glass-strong p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-xl font-bold">Your daily briefing</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>
        <p className="text-sm leading-relaxed text-slate-600">
          Good morning! Here's where <strong>{businessName}</strong> stands today.
          {s && (
            <>
              {" "}You have <strong className="text-red-600">{s.high_risk} customers at high
              risk</strong>, worth about <strong>{formatCurrency(s.revenue_at_risk)}/year</strong>.
              {top && (
                <>
                  {" "}Your top priority is <strong>{top.name}</strong> — {top.reasons[0]?.toLowerCase()}.
                </>
              )}
              {" "}Pulse has already sent <strong>{sentToday} win-back messages</strong> on autopilot,
              and you've recovered <strong>{formatCurrency(revenueRecovered)}</strong> so far.
            </>
          )}
        </p>
        <button
          onClick={onClose}
          className="mt-5 w-full rounded-xl px-4 py-2.5 text-sm font-semibold text-white"
          style={{ background: "var(--primary)" }}
        >
          Let's get to work
        </button>
      </div>
    </div>
  );
}

/* ── inline icons ── */
function MenuIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  );
}
function PulseGlyph() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0891b2" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 12h4l2-7 4 14 2-7h6" />
    </svg>
  );
}
function WaveIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#0891b2" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12h3l2-6 4 12 3-9 2 3h6" />
    </svg>
  );
}
function SpeakerIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7" />
    </svg>
  );
}
