import { lazy, Suspense } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import EmptyState from "./components/EmptyState";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { PulseProvider, usePulse } from "./context/PulseContext";
import Dashboard from "./pages/Dashboard";
import Customers from "./pages/Customers";
import Retention from "./pages/Retention";
import Automations from "./pages/Automations";
import Login from "./pages/Login";
import Setup, { SETUP_SKIPPED_KEY } from "./pages/Setup";

const Pricing = lazy(() => import("./pages/Pricing"));

function Spinner({ label }: { label: string }) {
  return (
    <div className="grid min-h-[60vh] place-items-center">
      <div className="flex items-center gap-3 text-slate-500">
        <span className="h-5 w-5 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
        {label}
      </div>
    </div>
  );
}

/** Gates data pages: routes empty tenants to setup, shows sample banner, etc. */
function DataGate({ children }: { children: React.ReactNode }) {
  const { status, error } = usePulse();

  if (status === "error") {
    return (
      <div className="grid min-h-[60vh] place-items-center text-center">
        <div className="glass p-8">
          <p className="font-display text-lg font-semibold text-slate-800">Couldn't reach Pulse</p>
          <p className="mt-1 text-sm text-slate-500">{error}</p>
          <p className="mt-2 text-xs text-slate-400">Is the API running?</p>
        </div>
      </div>
    );
  }
  if (status === "loading") return <Spinner label="Loading your customers…" />;

  if (status === "empty") {
    // First visit with no data → take them to setup. If they chose to skip,
    // show the "no data" screen that points back to setup instead.
    if (!localStorage.getItem(SETUP_SKIPPED_KEY)) {
      return <Navigate to="/setup" replace />;
    }
    return <EmptyState />;
  }

  return (
    <>
      {status === "sample" && (
        <div className="mb-4 flex items-center justify-between rounded-xl bg-amber-50 px-4 py-2.5 text-sm text-amber-800 ring-1 ring-amber-200">
          <span>You're exploring <b>sample data</b>.</span>
          <Link to="/setup" className="font-semibold underline">Connect your real data →</Link>
        </div>
      )}
      {children}
    </>
  );
}

function AuthedApp() {
  return (
    <PulseProvider>
      <AppShell>
        <Routes>
          <Route path="/setup" element={<Setup />} />
          <Route path="/" element={<DataGate><Dashboard /></DataGate>} />
          <Route path="/customers" element={<DataGate><Customers /></DataGate>} />
          <Route path="/retention" element={<DataGate><Retention /></DataGate>} />
          <Route path="/automations" element={<DataGate><Automations /></DataGate>} />
          <Route
            path="/pricing"
            element={(
              <Suspense fallback={<Spinner label="Loading pricing intelligence…" />}>
                <Pricing />
              </Suspense>
            )}
          />
        </Routes>
      </AppShell>
    </PulseProvider>
  );
}

function Gate() {
  const { user, loading, configured } = useAuth();
  if (loading) return <Spinner label="Loading…" />;
  // When Supabase auth isn't configured (local dev), skip the wall and use the
  // backend's demo tenant. Once configured, login is required.
  if (configured && !user) return <Login />;
  return <AuthedApp />;
}

export default function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  );
}
