import { useEffect, useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { usePulse } from "../context/PulseContext";
import { useAuth } from "../context/AuthContext";
import { api, formatCurrency } from "../lib/api";
import KnowledgeChat from "./KnowledgeChat";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/customers", label: "Customers" },
  { to: "/retention", label: "Retention" },
  { to: "/automations", label: "Automations" },
  { to: "/pricing", label: "Pricing" },
  { to: "/setup", label: "Data sources" },
];

export default function AppShell({ children }: { children: ReactNode }) {
  const { businessName: dataBusiness } = usePulse();
  const { user, logout, configured } = useAuth();
  const businessName = user?.business_name ?? dataBusiness;
  const [briefing, setBriefing] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="min-h-screen">
      <header
        className="sticky top-0 z-30 border-b"
        style={{
          background: "rgba(251,246,238,.86)",
          backdropFilter: "blur(10px)",
          borderColor: "#E6D8C6",
        }}
      >
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-6 py-3.5">
          <div className="flex items-center gap-7">
            <div className="flex items-center gap-2.5">
              <span
                className="font-logo inline-flex h-[30px] w-[30px] items-center justify-center rounded-full text-[19px]"
                style={{ background: "var(--ink-strong)", color: "var(--cream-text)" }}
              >
                C
              </span>
              <span className="font-display text-[21px] font-bold tracking-tight" style={{ color: "var(--ink)" }}>
                Churnary
              </span>
            </div>
            <nav className="hidden items-center gap-1 md:flex">
              {NAV.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.end}
                  className="rounded-full px-3.5 py-2 text-sm transition"
                  style={({ isActive }) =>
                    isActive
                      ? { background: "var(--surface-3)", color: "var(--ink-strong)", fontWeight: 700 }
                      : { color: "var(--muted)", fontWeight: 600 }
                  }
                >
                  {n.label}
                </NavLink>
              ))}
            </nav>
          </div>

          <div className="flex items-center gap-4">
            <div className="relative">
              <button
                onClick={() => setMenuOpen((v) => !v)}
                className="flex items-center gap-2 rounded-full px-4 py-[7px] text-sm font-semibold transition hover:brightness-95"
                style={{ background: "var(--surface-3)", color: "var(--ink-strong)" }}
              >
                <span className="h-2 w-2 rounded-full" style={{ background: "var(--sage)" }} />
                <span className="max-w-36 truncate">{businessName}</span>
                <span style={{ color: "var(--muted-2)", fontSize: 11 }}>⌄</span>
              </button>
              {menuOpen && (
                <div
                  className="glass-strong absolute right-0 top-11 z-40 w-56 p-3 animate-fade-in"
                  onMouseLeave={() => setMenuOpen(false)}
                >
                  <p className="truncate px-2 text-sm font-semibold" style={{ color: "var(--ink)" }}>
                    {businessName}
                  </p>
                  {user?.email && (
                    <p className="truncate px-2 text-xs" style={{ color: "var(--muted-2)" }}>{user.email}</p>
                  )}
                  <NavLink
                    to="/setup"
                    onClick={() => setMenuOpen(false)}
                    className="mt-2 block rounded-xl px-3 py-2 text-sm font-medium transition hover:brightness-95"
                    style={{ background: "var(--surface-2)", color: "var(--ink-strong)" }}
                  >
                    Connect a data source
                  </NavLink>
                  {configured && (
                    <button
                      onClick={logout}
                      className="mt-2 w-full rounded-xl border px-3 py-2 text-sm font-medium transition hover:brightness-95"
                      style={{ borderColor: "var(--border)", color: "var(--muted)", background: "var(--surface-2)" }}
                    >
                      Sign out
                    </button>
                  )}
                </div>
              )}
            </div>

            <button
              onClick={() => setBriefing(true)}
              className="flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold text-white transition hover:-translate-y-px"
              style={{
                background: "var(--accent)",
                boxShadow: "0 6px 16px -6px rgba(180,83,42,.7)",
              }}
            >
              <SpeakerIcon /> Daily Briefing
            </button>
          </div>
        </div>

        {/* mobile nav */}
        <nav className="flex items-center gap-1 overflow-x-auto px-6 pb-2 md:hidden">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className="whitespace-nowrap rounded-full px-3.5 py-1.5 text-sm"
              style={({ isActive }) =>
                isActive
                  ? { background: "var(--surface-3)", color: "var(--ink-strong)", fontWeight: 700 }
                  : { color: "var(--muted)", fontWeight: 600 }
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-9 pb-20">{children}</main>

      {briefing && <BriefingModal onClose={() => setBriefing(false)} />}
      <KnowledgeChat />
    </div>
  );
}

function BriefingModal({ onClose }: { onClose: () => void }) {
  const { businessName, customers, portfolio, revenueRecovered } = usePulse();
  const s = portfolio?.summary;
  const top = customers[0];
  const [sentToday, setSentToday] = useState(0);

  useEffect(() => {
    const today = new Date().toISOString().slice(0, 10);
    api
      .listSends(100)
      .then((sends) =>
        setSentToday(
          sends.filter(
            (send) =>
              (send.status === "sent" || send.status === "delivered") &&
              send.sent_at?.slice(0, 10) === today
          ).length
        )
      )
      .catch(() => setSentToday(0));
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 animate-fade-in"
      style={{ background: "rgba(42,33,28,.4)" }}
      onClick={onClose}
    >
      <div className="glass-strong w-full max-w-md p-7" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-xl font-bold" style={{ color: "var(--ink)" }}>
            Your daily briefing
          </h2>
          <button onClick={onClose} style={{ color: "var(--muted-2)" }}>✕</button>
        </div>
        <p className="text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
          Good morning! Here's where <strong style={{ color: "var(--ink)" }}>{businessName}</strong> stands today.
          {s && (
            <>
              {" "}You have <strong style={{ color: "var(--accent-dark)" }}>{s.high_risk} customers at high
              risk</strong>, worth about <strong style={{ color: "var(--ink)" }}>{formatCurrency(s.revenue_at_risk)}/year</strong>.
              {top && (
                <>
                  {" "}Your top priority is <strong style={{ color: "var(--ink)" }}>{top.name}</strong> — {top.reasons[0]?.toLowerCase()}.
                </>
              )}
              {" "}Churnary has already sent <strong style={{ color: "var(--ink)" }}>{sentToday} win-back messages</strong> on autopilot,
              and you've recovered <strong style={{ color: "var(--sage-text)" }}>{formatCurrency(revenueRecovered)}</strong> so far.
            </>
          )}
        </p>
        <button
          onClick={onClose}
          className="mt-5 w-full rounded-full px-4 py-2.5 text-sm font-semibold text-white transition hover:brightness-95"
          style={{ background: "var(--accent)" }}
        >
          Let's get to work
        </button>
      </div>
    </div>
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
