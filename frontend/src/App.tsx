import { useState } from "react";
import Onboarding from "./pages/Onboarding";
import Dashboard from "./pages/Dashboard";
import type { CSVPreview } from "./lib/api";

export default function App() {
  const [preview, setPreview] = useState<CSVPreview | null>(null);
  const [vertical, setVertical] = useState("fitness");
  const [businessName, setBusinessName] = useState("Iron Peak Fitness");

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-lg bg-cyan-600" />
            <span className="text-lg font-semibold tracking-tight">Pulse</span>
          </div>
          {preview && (
            <button
              onClick={() => setPreview(null)}
              className="text-sm text-slate-500 hover:text-slate-900"
            >
              ← Start over
            </button>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-10">
        {preview ? (
          <Dashboard
            preview={preview}
            businessName={businessName}
            vertical={vertical}
          />
        ) : (
          <Onboarding
            vertical={vertical}
            onVerticalChange={setVertical}
            businessName={businessName}
            onBusinessNameChange={setBusinessName}
            onLoaded={setPreview}
          />
        )}
      </main>
    </div>
  );
}
