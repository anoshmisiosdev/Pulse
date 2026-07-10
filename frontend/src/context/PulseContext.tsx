import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, type CustomerRisk, type Portfolio, type Segment } from "../lib/api";

export type Mode = "suggest" | "approve" | "auto";

export interface AutomationRule {
  id: string;
  name: string;
  segments: Segment[];
  channel: "email" | "sms";
  incentive: string;
  mode: Mode;
  enabled: boolean;
}

export interface ActivityItem {
  id: string;
  customerId: string;
  name: string;
  favorite: string | null;
  reason: string;
  mode: Mode;
  channel: "email" | "sms";
  when: string;
  status: "sent" | "awaiting_approval" | "suggested";
}

const DEFAULT_RULES: AutomationRule[] = [
  {
    id: "rule-winback",
    name: "Win back fading regulars",
    segments: ["needs_attention", "slipping_away"],
    channel: "email",
    incentive: "a free drink",
    mode: "auto",
    enabled: true,
  },
  {
    id: "rule-watch",
    name: "Nudge customers we're watching",
    segments: ["keep_an_eye_on"],
    channel: "email",
    incentive: "10% off their next visit",
    mode: "approve",
    enabled: true,
  },
];

const RELATIVE_TIMES = [
  "just now", "8 min ago", "26 min ago", "1 hr ago", "2 hrs ago", "3 hrs ago",
  "today, 9:12am", "today, 8:40am", "yesterday", "yesterday", "2 days ago", "2 days ago",
];

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
  rules: AutomationRule[];
  setRuleMode: (id: string, mode: Mode) => void;
  toggleRule: (id: string) => void;
  activity: ActivityItem[];
}

const Ctx = createContext<PulseCtx | null>(null);

export function PulseProvider({ children }: { children: ReactNode }) {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [status, setStatus] = useState<DataStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [wonBackIds, setWonBackIds] = useState<Set<string>>(new Set());
  const [contactedIds, setContactedIds] = useState<Set<string>>(new Set());
  const [revenueRecovered, setRevenueRecovered] = useState(0);
  const [rules, setRules] = useState<AutomationRule[]>(DEFAULT_RULES);

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

  const setRuleMode = useCallback((id: string, mode: Mode) => {
    setRules((prev) => prev.map((r) => (r.id === id ? { ...r, mode } : r)));
  }, []);

  const toggleRule = useCallback((id: string) => {
    setRules((prev) => prev.map((r) => (r.id === id ? { ...r, enabled: !r.enabled } : r)));
  }, []);

  const customers = useMemo(
    () => (portfolio?.customers ?? []).filter((c) => !wonBackIds.has(c.customer_id)),
    [portfolio, wonBackIds]
  );

  // Autopilot feed: what the enabled rules are doing to at-risk customers.
  const activity = useMemo<ActivityItem[]>(() => {
    const items: ActivityItem[] = [];
    let i = 0;
    for (const c of customers) {
      const rule = rules.find((r) => r.enabled && r.segments.includes(c.segment));
      if (!rule) continue;
      items.push({
        id: `act-${c.customer_id}`,
        customerId: c.customer_id,
        name: c.name,
        favorite: c.favorite_item,
        reason: c.reasons[0] ?? "",
        mode: rule.mode,
        channel: rule.channel,
        when: RELATIVE_TIMES[i % RELATIVE_TIMES.length],
        status:
          rule.mode === "auto" ? "sent" : rule.mode === "approve" ? "awaiting_approval" : "suggested",
      });
      i++;
    }
    return items.slice(0, 30);
  }, [customers, rules]);

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
    rules,
    setRuleMode,
    toggleRule,
    activity,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePulse(): PulseCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("usePulse must be used within PulseProvider");
  return ctx;
}
