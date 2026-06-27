import { useRef, useState } from "react";
import { api, type CSVPreview } from "../lib/api";

const VERTICALS = [
  { id: "fitness", label: "Fitness studio" },
  { id: "salon", label: "Salon" },
  { id: "med_spa", label: "Med spa" },
  { id: "other", label: "Other" },
];

interface Props {
  vertical: string;
  onVerticalChange: (v: string) => void;
  businessName: string;
  onBusinessNameChange: (v: string) => void;
  onLoaded: (preview: CSVPreview) => void;
}

export default function Onboarding({
  vertical,
  onVerticalChange,
  businessName,
  onBusinessNameChange,
  onLoaded,
}: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [loading, setLoading] = useState<"file" | "demo" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(file: File) {
    setError(null);
    setLoading("file");
    try {
      onLoaded(await api.previewCsv(file, vertical));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setLoading(null);
    }
  }

  async function handleDemo() {
    setError(null);
    setLoading("demo");
    try {
      onVerticalChange("fitness");
      onLoaded(await api.demo(300));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load demo");
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="mx-auto max-w-xl">
      <h1 className="text-3xl font-semibold tracking-tight">Connect your customers</h1>
      <p className="mt-2 text-slate-500">
        Upload a CSV export and Pulse will show who's about to churn — and why — in
        plain English. No data leaves your browser until you ask it to.
      </p>

      <div className="mt-8 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <label className="block text-sm font-medium text-slate-700">Business name</label>
        <input
          value={businessName}
          onChange={(e) => onBusinessNameChange(e.target.value)}
          className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm
                     outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
        />

        <label className="mt-5 block text-sm font-medium text-slate-700">Vertical</label>
        <div className="mt-2 grid grid-cols-2 gap-2">
          {VERTICALS.map((v) => (
            <button
              key={v.id}
              onClick={() => onVerticalChange(v.id)}
              className={`rounded-lg border px-3 py-2 text-sm transition ${
                vertical === v.id
                  ? "border-cyan-600 bg-cyan-50 text-cyan-700"
                  : "border-slate-300 text-slate-600 hover:border-slate-400"
              }`}
            >
              {v.label}
            </button>
          ))}
        </div>
        <p className="mt-1 text-xs text-slate-400">
          Sets the expected visit cadence used for scoring.
        </p>

        <div className="mt-6 rounded-xl border-2 border-dashed border-slate-300 p-6 text-center">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
          />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={loading !== null}
            className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white
                       hover:bg-cyan-700 disabled:opacity-50"
          >
            {loading === "file" ? "Scoring…" : "Upload CSV"}
          </button>
          <div className="mt-3 text-xs text-slate-400">
            Need the format?{" "}
            <a href={api.templateUrl()} className="text-cyan-600 underline">
              Download template
            </a>
          </div>
        </div>

        <div className="mt-4 flex items-center gap-3 text-xs text-slate-400">
          <div className="h-px flex-1 bg-slate-200" /> or{" "}
          <div className="h-px flex-1 bg-slate-200" />
        </div>

        <button
          onClick={handleDemo}
          disabled={loading !== null}
          className="mt-4 w-full rounded-lg border border-slate-300 px-4 py-2 text-sm
                     font-medium text-slate-700 hover:border-slate-400 disabled:opacity-50"
        >
          {loading === "demo" ? "Loading…" : "Try with sample data (300 customers)"}
        </button>

        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      </div>
    </div>
  );
}
