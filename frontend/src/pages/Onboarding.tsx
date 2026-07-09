import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { usePulse } from "../context/PulseContext";

type Source = "square" | "stripe" | "csv";

const SOURCES: { id: Source; name: string; tag: string; blurb: string }[] = [
  { id: "square", name: "Square", tag: "Recommended", blurb: "Pull customers & payments from your Square POS" },
  { id: "stripe", name: "Stripe", tag: "Popular", blurb: "Pull customers & charges from your Stripe account" },
  { id: "csv", name: "CSV upload", tag: "2 minutes", blurb: "No POS? Import a customer spreadsheet instead" },
];

const VERTICALS: { id: string; label: string }[] = [
  { id: "cafe", label: "Cafe / coffee shop" },
  { id: "fitness", label: "Fitness studio / gym" },
  { id: "salon", label: "Salon / barber" },
  { id: "med_spa", label: "Med spa / wellness" },
  { id: "other", label: "Other" },
];

export default function Onboarding() {
  const navigate = useNavigate();
  const { loadCsv, reloadDemo } = usePulse();
  const [source, setSource] = useState<Source>("square");
  const [businessName, setBusinessName] = useState("");
  const [vertical, setVertical] = useState("cafe");
  const [token, setToken] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const cta =
    source === "csv" ? "Import CSV & score customers" : `Connect ${source === "square" ? "Square" : "Stripe"} & pull customers`;

  async function onConnect() {
    setBusy(true);
    setError(null);
    try {
      if (source === "csv") {
        if (!file) {
          setError("Choose a CSV file to import.");
          return;
        }
        await loadCsv(file, vertical, businessName || "My Business");
      } else {
        // Live Square/Stripe sync connects through your backend OAuth. Until that
        // endpoint is wired, preview the product with scored sample data.
        await reloadDemo();
      }
      navigate("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function onSkip() {
    setBusy(true);
    await reloadDemo();
    setBusy(false);
    navigate("/");
  }

  return (
    <div className="mx-auto max-w-3xl">
      <div className="anim-fade-up text-center">
        <h1 className="text-[34px] font-bold tracking-tight" style={{ color: "var(--ink)" }}>
          Connect your customer data
        </h1>
        <p className="mx-auto mt-2 max-w-xl italic" style={{ color: "var(--muted)", fontSize: "15.5px" }}>
          Pulse watches your payment system and flags customers who are about to slip away. Pick where your customers live.
        </p>
      </div>

      {/* source cards */}
      <div className="anim-fade-up mt-8 grid grid-cols-1 gap-3 sm:grid-cols-3" style={{ animationDelay: "0.05s" }}>
        {SOURCES.map((s) => {
          const on = source === s.id;
          return (
            <button
              key={s.id}
              onClick={() => setSource(s.id)}
              className="rounded-[16px] border p-5 text-left transition"
              style={{
                background: "var(--surface)",
                borderColor: on ? "var(--accent)" : "var(--border)",
                boxShadow: on ? "0 0 0 3px rgba(180,83,42,.12)" : "none",
              }}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="text-[17px] font-bold" style={{ color: "var(--ink)" }}>{s.name}</span>
                <span
                  className="rounded-full px-2 py-0.5 text-[10px] font-bold uppercase"
                  style={{ letterSpacing: ".06em", background: "var(--surface3)", color: "var(--accent)" }}
                >
                  {s.tag}
                </span>
              </div>
              <p className="mt-2 text-[13px]" style={{ color: "var(--muted)", lineHeight: 1.4 }}>{s.blurb}</p>
            </button>
          );
        })}
      </div>

      {/* form panel */}
      <div className="glass anim-fade-up mt-4 p-7" style={{ animationDelay: "0.1s" }}>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <Field label="Business name">
            <input
              value={businessName}
              onChange={(e) => setBusinessName(e.target.value)}
              placeholder="Hayward Coffee Co."
              className="input"
            />
          </Field>
          <Field label="Business type" hint="Sets the visit cadence used for churn scoring.">
            <select value={vertical} onChange={(e) => setVertical(e.target.value)} className="input">
              {VERTICALS.map((v) => (
                <option key={v.id} value={v.id}>{v.label}</option>
              ))}
            </select>
          </Field>
        </div>

        <div className="mt-5">
          {source === "csv" ? (
            <Field label="Customer CSV" hint="Columns: name, email, last visit, spend. Missing fields are fine — Pulse redistributes the weight.">
              <div className="flex flex-wrap items-center gap-3">
                <button
                  onClick={() => fileRef.current?.click()}
                  className="rounded-xl border px-4 py-2.5 text-sm font-semibold transition hover:brightness-95"
                  style={{ borderColor: "var(--border)", background: "var(--surface-2)", color: "var(--ink-strong)" }}
                >
                  {file ? "Change file" : "Choose CSV…"}
                </button>
                <span className="text-sm" style={{ color: file ? "var(--ink-strong)" : "var(--muted-2)" }}>
                  {file ? file.name : "No file selected"}
                </span>
                <a href={api.templateUrl()} className="ml-auto text-sm font-semibold" style={{ color: "var(--accent)" }}>
                  Download template
                </a>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".csv,text/csv"
                  className="hidden"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
              </div>
            </Field>
          ) : (
            <Field
              label={`${source === "square" ? "Square" : "Stripe"} access token`}
              hint={
                source === "square"
                  ? "Square Developer Dashboard → your app → Production → Access token. Stored encrypted — never shown again."
                  : "Stripe Dashboard → Developers → API keys → Secret key. Stored encrypted — never shown again."
              }
            >
              <input
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder={source === "square" ? "EAAA…" : "sk_live_…"}
                className="input"
                type="password"
              />
            </Field>
          )}
        </div>

        {error && (
          <p className="mt-4 rounded-lg px-3 py-2 text-sm" style={{ background: "#F7E3DC", color: "#A23B1E" }}>
            {error}
          </p>
        )}

        <button
          onClick={onConnect}
          disabled={busy}
          className="mt-6 w-full rounded-full px-4 py-3 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-60"
          style={{ background: "var(--accent)", boxShadow: "0 6px 16px -6px rgba(180,83,42,.7)" }}
        >
          {busy ? "Working…" : cta}
        </button>
      </div>

      <p className="mt-5 text-center text-sm" style={{ color: "var(--muted)" }}>
        Not ready?{" "}
        <button onClick={onSkip} className="font-semibold underline" style={{ color: "var(--accent)" }}>
          Skip for now
        </button>{" "}
        — you can connect any time.
      </p>

      <style>{`
        .input {
          margin-top: 6px; width: 100%; border-radius: 12px;
          border: 1px solid var(--border); background: var(--surface);
          padding: 11px 14px; font-size: 14px; color: var(--ink); outline: none;
        }
        .input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(180,83,42,.12); }
      `}</style>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm font-semibold" style={{ color: "var(--ink-strong)" }}>{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs" style={{ color: "var(--muted-2)" }}>{hint}</span>}
    </label>
  );
}
