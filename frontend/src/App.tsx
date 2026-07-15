import { Suspense, lazy } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import EmptyState from "./components/EmptyState";
import ErrorBoundary from "./components/ErrorBoundary";
import PageSkeleton from "./components/PageSkeleton";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { PulseProvider, usePulse } from "./context/PulseContext";
import { SETUP_SKIPPED_KEY } from "./lib/api";

// Each page is its own chunk — visitors only download the routes they visit.
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Customers = lazy(() => import("./pages/Customers"));
const Retention = lazy(() => import("./pages/Retention"));
const Automations = lazy(() => import("./pages/Automations"));
const Pricing = lazy(() => import("./pages/Pricing"));
const Landing = lazy(() => import("./pages/Landing"));
const Login = lazy(() => import("./pages/Login"));
const Setup = lazy(() => import("./pages/Setup"));

function Spinner({ label }: { label: string }) {
  return (
    <div className="grid min-h-[60vh] place-items-center">
      <div className="flex items-center gap-3" style={{ color: "var(--muted)" }}>
        <span
          className="h-5 w-5 animate-spin rounded-full border-2"
          style={{ borderColor: "var(--border)", borderTopColor: "var(--accent)" }}
        />
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
          <p className="font-display text-lg font-semibold" style={{ color: "var(--ink)" }}>Couldn't reach Churnary</p>
          <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>{error}</p>
          <p className="mt-2 text-xs" style={{ color: "var(--muted-2)" }}>Is the API running?</p>
        </div>
      </div>
    );
  }
  if (status === "loading") return <PageSkeleton />;

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
      <Routes>
        {/* Marketing page stays reachable in demo mode for local preview */}
        <Route path="/landing" element={<Landing />} />
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route
          path="*"
          element={
            <AppShell>
              <Routes>
                <Route path="/setup" element={<Setup />} />
                <Route path="/connect" element={<Navigate to="/setup" replace />} />
                <Route path="/pricing" element={<Pricing />} />
                <Route path="/" element={<DataGate><Dashboard /></DataGate>} />
                <Route path="/customers" element={<DataGate><Customers /></DataGate>} />
                <Route path="/retention" element={<DataGate><Retention /></DataGate>} />
                <Route path="/automations" element={<DataGate><Automations /></DataGate>} />
              </Routes>
            </AppShell>
          }
        />
      </Routes>
    </PulseProvider>
  );
}

// Public marketing site for signed-out visitors: landing page → login.
function PublicSite() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function Gate() {
  const { user, loading, configured } = useAuth();
  if (loading) return <Spinner label="Loading…" />;
  // When Supabase auth isn't configured (local dev), skip the wall and use the
  // backend's demo tenant. Once configured, the landing page fronts the login.
  if (configured && !user) return <PublicSite />;
  return <AuthedApp />;
}

export default function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <Suspense fallback={<Spinner label="Loading…" />}>
          <Gate />
        </Suspense>
      </AuthProvider>
    </ErrorBoundary>
  );
}
