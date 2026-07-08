import { Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { PulseProvider, usePulse } from "./context/PulseContext";
import Dashboard from "./pages/Dashboard";
import Customers from "./pages/Customers";
import Retention from "./pages/Retention";
import Automations from "./pages/Automations";
import Login from "./pages/Login";

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

function DataGate({ children }: { children: React.ReactNode }) {
  const { loading, error } = usePulse();
  if (error) {
    return (
      <div className="grid min-h-[60vh] place-items-center text-center">
        <div className="glass p-8">
          <p className="font-display text-lg font-semibold text-slate-800">Couldn't reach Pulse</p>
          <p className="mt-1 text-sm text-slate-500">{error}</p>
          <p className="mt-2 text-xs text-slate-400">Is the API running on :8000?</p>
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
