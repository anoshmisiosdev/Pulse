import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { usePulse } from "../context/PulseContext";
import { api } from "../lib/api";

export const SETUP_SKIPPED_KEY = "pulse_setup_skipped";

type Provider = "stripe" | "square" | "csv";

const VERTICALS = [
  { id: "cafe", label: "Cafe / coffee shop" },
  { id: "fitness", label: "Fitness studio" },
  { id: "salon", label: "Salon" },
  { id: "med_spa", label: "Med spa" },
  { id: "other", label: "Other" },
];

const PROVIDERS: {
  id: Provider;
  name: string;
  blurb: string;
  badge: string;
}[] = [
  {
    id: "square",
    name: "Square",
    blurb: "Pull customers & payments from your Square POS",
    badge: "Recommended",
  },
  {
    id: "stripe",
    name: "Stripe",
    blurb: "Pull customers & charges from your Stripe account",
    badge: "Popular",
  },
  {
    id: "csv",
    name: "CSV upload",
    blurb: "No POS? Import a customer spreadsheet instead",
    badge: "2 minutes",
  },
];

export default function Setup() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { user } = useAuth();
  const { applyPortfolio, refresh, status } = usePulse();
  const fileRef = useRef<HTMLInputElement>(null);

  const [provider, setProvider] = useState<Provider>("square");
  const [credential, setCredential] = useState("");
  const [vertical, setVertical] = useState("cafe");
  const [businessName, setBusinessName] = useState(user?.business_name ?? "");
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [oauthOk, setOauthOk] = useState<{ stripe: boolean; square: boolean }>({
    stripe: false,
    square: false,
  });
  const [manualOpen, setManualOpen] = useState(false);

  const hasData = status === "ready";
  const oauthAvailable = provider !== "csv" && oauthOk[provider];

  // Which providers have OAuth configured → show "Connect with …" buttons.
  useEffect(() => {
    api.oauthAvailability().then(setOauthOk).catch(() => {});
  }, []);

  // Returning from the provider's consent screen (?connected= / ?error=).
  useEffect(() => {
    const connected = params.get("connected");
    const oauthError = params.get("error");
    if (connected) {
      setParams({}, { replace: true });
      localStorage.removeItem(SETUP_SKIPPED_KEY);
      refresh().then(() => navigate("/", { replace: true }));
    } else if (oauthError) {
      setError(oauthError);
      setParams({}, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleOauth() {
    setError(null);
    setBusy(true);
    setPhase(`Sending you to ${provider === "stripe" ? "Stripe" : "Square"}…`);
    try {
      const url = await api.oauthStart(
        provider as "stripe" | "square",
        vertical,
        businessName.trim()
      );
      window.location.href = url; // full-page redirect to the consent screen
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the connection");
      setPhase(null);
      setBusy(false);
    }
  }

  async function handleConnect() {
    setError(null);
    setBusy(true);
    setPhase(`Connecting to ${provider === "stripe" ? "Stripe" : "Square"}…`);
    try {
      setTimeout(() => setPhase("Pulling your customers & payments…"), 1500);
      const portfolio = await api.connect({
        provider: provider as "stripe" | "square",
        credential: credential.trim(),
        vertical,
        business_name: businessName.trim(),
      });
      setPhase("Scoring churn risk…");
      applyPortfolio(portfolio);
      localStorage.removeItem(SETUP_SKIPPED_KEY);
      navigate("/", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connection failed");
      setPhase(null);
    } finally {
      setBusy(false);
    }
  }

  async function handleCsv(file: File) {
    setError(null);
    setBusy(true);
    setPhase("Importing & scoring your customers…");
    try {
      const portfolio = await api.importCsv(file, vertical, businessName.trim());
      applyPortfolio(portfolio);
      localStorage.removeItem(SETUP_SKIPPED_KEY);
      navigate("/", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
      setPhase(null);
    } finally {
      setBusy(false);
    }
  }

  function skip() {
    localStorage.setItem(SETUP_SKIPPED_KEY, "1");
    navigate("/", { replace: true });
  }

  function LockIcon() {
    return (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="11" width="18" height="11" rx="2" />
        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
      </svg>
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-6">
        <h1 className="font-display text-3xl font-extrabold tracking-tight">
          {hasData ? "Data sources" : "Connect your customer data"}
        </h1>
        <p className="mt-1 text-slate-500">
          Pulse watches your payment system and flags customers who are about to
          slip away. Pick where your customers live.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {PROVIDERS.map((p) => (
          <button
            key={p.id}
            onClick={() => { setProvider(p.id); setError(null); }}
            className={`glass glass-hover relative p-4 text-left transition ${
              provider === p.id ? "ring-2 ring-cyan-500" : ""
            }`}
          >
            <span className="absolute right-3 top-3 rounded-full bg-cyan-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-cyan-700">
              {p.badge}
            </span>
            <p className="font-display text-lg font-bold">{p.name}</p>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">{p.blurb}</p>
          </button>
        ))}
      </div>

      <div className="glass mt-4 space-y-4 p-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="text-sm font-medium text-slate-700">Business name</span>
            <input
              value={businessName}
              onChange={(e) => setBusinessName(e.target.value)}
              placeholder="Hayward Coffee Co."
              className="mt-1 w-full rounded-xl border border-slate-300 bg-white/70 px-3 py-2.5 text-sm outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">Business type</span>
            <select
              value={vertical}
              onChange={(e) => setVertical(e.target.value)}
              className="mt-1 w-full rounded-xl border border-slate-300 bg-white/70 px-3 py-2.5 text-sm outline-none focus:border-cyan-500"
            >
              {VERTICALS.map((v) => (
                <option key={v.id} value={v.id}>{v.label}</option>
              ))}
            </select>
            <span className="mt-1 block text-xs text-slate-400">
              Sets the visit cadence used for churn scoring.
            </span>
          </label>
        </div>

        {provider !== "csv" ? (
          <>
            {oauthAvailable && (
              <>
                <button
                  onClick={handleOauth}
                  disabled={busy}
                  className="flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3.5 text-sm font-semibold text-white disabled:opacity-60"
                  style={{ background: provider === "stripe" ? "#635bff" : "#0f1419" }}
                >
                  {busy ? (
                    phase ?? "Redirecting…"
                  ) : (
                    <>
                      <LockIcon /> Connect with {provider === "stripe" ? "Stripe" : "Square"}
                    </>
                  )}
                </button>
                <p className="text-center text-xs text-slate-400">
                  You'll approve read-only access on {provider === "stripe" ? "Stripe" : "Square"}'s
                  site — no keys to copy. We pull customers &amp; payments and bring you right back.
                </p>
                <button
                  onClick={() => setManualOpen((v) => !v)}
                  className="mx-auto block text-xs font-medium text-slate-400 underline hover:text-slate-600"
                >
                  {manualOpen ? "Hide manual option" : "Or paste an API key manually"}
                </button>
              </>
            )}

            {(!oauthAvailable || manualOpen) && (
              <>
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">
                    {provider === "stripe" ? "Stripe secret key" : "Square access token"}
                  </span>
                  <input
                    type="password"
                    value={credential}
                    onChange={(e) => setCredential(e.target.value)}
                    placeholder={provider === "stripe" ? "sk_live_… or rk_live_…" : "EAAA…"}
                    className="mt-1 w-full rounded-xl border border-slate-300 bg-white/70 px-3 py-2.5 font-mono text-sm outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
                  />
                  <span className="mt-1 block text-xs text-slate-400">
                    {provider === "stripe"
                      ? "Stripe Dashboard → Developers → API keys. A restricted key with read access to Customers and Charges is enough."
                      : "Square Developer Dashboard → your app → Production → Access token."}{" "}
                    Stored encrypted — never shown again.
                  </span>
                </label>
                <button
                  onClick={handleConnect}
                  disabled={busy || !credential.trim()}
                  className="w-full rounded-xl px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
                  style={{ background: "var(--primary)" }}
                >
                  {busy ? phase ?? "Connecting…" : `Connect ${provider === "stripe" ? "Stripe" : "Square"} & pull customers`}
                </button>
              </>
            )}
          </>
        ) : (
          <>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && handleCsv(e.target.files[0])}
            />
            <button
              onClick={() => fileRef.current?.click()}
              disabled={busy}
              className="w-full rounded-xl border-2 border-dashed border-slate-300 px-4 py-6 text-sm font-medium text-slate-600 hover:border-cyan-400 disabled:opacity-50"
            >
              {busy ? phase ?? "Importing…" : "Choose a CSV file (name, email, phone, last visit, total spent)"}
            </button>
            <p className="text-center text-xs text-slate-400">
              Need the format?{" "}
              <a href={api.templateUrl()} className="text-cyan-600 underline">
                Download the template
              </a>
            </p>
          </>
        )}

        {error && (
          <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>
        )}
      </div>

      {!hasData && (
        <p className="mt-5 text-center text-sm text-slate-400">
          Not ready?{" "}
          <button onClick={skip} className="font-semibold text-slate-500 underline hover:text-slate-700">
            Skip for now
          </button>{" "}
          — you can connect any time.
        </p>
      )}
    </div>
  );
}
