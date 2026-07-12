import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, type CustomerRisk, type Portfolio } from "../lib/api";

export type DataStatus = "loading" | "error" | "empty" | "ready" | "sample";

interface PulseCtx {
  loading: boolean;
  error: string | null;
  /** empty = no data source connected yet; sample = exploring demo data. */
  status: DataStatus;
  businessName: string;
  vertical: string;
  portfolio: Portfolio | null;
  customers: CustomerRisk[];
  refresh: () => Promise<void>;
  applyPortfolio: (p: Portfolio) => void;
  reloadDemo: () => Promise<void>;
  loadCsv: (file: File, vertical: string, name: string) => Promise<void>;
  wonBackIds: Set<string>;
  contactedIds: Set<string>;
  markContacted: (id: string) => void;
  markWonBack: (c: CustomerRisk) => void;
  revenueRecovered: number;
  wonBackCount: number;
}

const Ctx = createContext<PulseCtx | null>(null);

export function PulseProvider({ children }: { children: ReactNode }) {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [status, setStatus] = useState<DataStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [wonBackIds, setWonBackIds] = useState<Set<string>>(new Set());
  const [contactedIds, setContactedIds] = useState<Set<string>>(new Set());
  const [revenueRecovered, setRevenueRecovered] = useState(0);

  // Load THIS tenant's persisted data. "empty" routes the owner to /setup.
  const refresh = useCallback(async () => {
    setStatus("loading");
    setError(null);
    try {
      const p = await api.portfolio();
      setPortfolio(p);
      setStatus(p.status === "empty" ? "empty" : "ready");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
      setStatus("error");
    }
  }, []);

  // Used by the setup page after a successful connect/import.
  const applyPortfolio = useCallback((p: Portfolio) => {
    setPortfolio(p);
    setStatus(p.status === "empty" ? "empty" : "ready");
    setWonBackIds(new Set());
    setContactedIds(new Set());
    setRevenueRecovered(0);
  }, []);

  // Ephemeral sample data — lets an owner explore before connecting anything.
  const reloadDemo = useCallback(async () => {
    setStatus("loading");
    setError(null);
    try {
      setPortfolio(await api.demo(50));
      setStatus("sample");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
      setStatus("error");
    }
  }, []);

  const loadCsv = useCallback(async (file: File, vertical: string, name: string) => {
    setStatus("loading");
    setError(null);
    try {
      applyPortfolio(await api.importCsv(file, vertical, name));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
      setStatus("error");
    }
  }, [applyPortfolio]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const markContacted = useCallback((id: string) => {
    setContactedIds((prev) => new Set(prev).add(id));
  }, []);

  const markWonBack = useCallback((c: CustomerRisk) => {
    setWonBackIds((prev) => new Set(prev).add(c.customer_id));
    setRevenueRecovered((prev) => prev + c.estimated_annual_value);
  }, []);

  const customers = useMemo(
    () => (portfolio?.customers ?? []).filter((c) => !wonBackIds.has(c.customer_id)),
    [portfolio, wonBackIds]
  );

  const value: PulseCtx = {
    loading: status === "loading",
    error,
    status,
    businessName: portfolio?.business_name ?? "Churnary",
    vertical: portfolio?.vertical ?? "other",
    portfolio,
    customers,
    refresh,
    applyPortfolio,
    reloadDemo,
    loadCsv,
    wonBackIds,
    contactedIds,
    markContacted,
    markWonBack,
    revenueRecovered,
    wonBackCount: wonBackIds.size,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePulse(): PulseCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("usePulse must be used within PulseProvider");
  return ctx;
}
