import { Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { PulseProvider, usePulse } from "./context/PulseContext";
import Dashboard from "./pages/Dashboard";
import Customers from "./pages/Customers";
import Retention from "./pages/Retention";
import Automations from "./pages/Automations";
import Onboarding from "./pages/Onboarding";
import Login from "./pages/Login";

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

function DataGate({ children }: { children: React.ReactNode }) {
  const { loading, error } = usePulse();
  if (error) {
    return (
      <div className="grid min-h-[60vh] place-items-center text-center">
        <div className="glass p-8">
          <p className="font-display text-lg font-semibold" style={{ color: "var(--ink)" }}>Couldn't reach Pulse</p>
          <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>{error}</p>
          <p className="mt-2 text-xs" style={{ color: "var(--muted-2)" }}>Is the API running on :8000?</p>
        </div>
      </div>
    );
  }
  if (loading) return <Spinner label="Scoring your customers…" />;
  return <>{children}</>;
}

function AuthedApp() {
  return (
    <PulseProvider>
      <AppShell>
        <DataGate>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/customers" element={<Customers />} />
            <Route path="/retention" element={<Retention />} />
            <Route path="/automations" element={<Automations />} />
            <Route path="/connect" element={<Onboarding />} />
          </Routes>
        </DataGate>
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
