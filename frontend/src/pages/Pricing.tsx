import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  api,
  formatCurrency,
  type CompetitorPrice,
  type CompetitorPriceCompetitor,
  type CompetitorPriceHistoryItem,
  type CompetitorPriceResearchInput,
  type CompetitorPriceResearchResponse,
  type CompetitorPriceWatch,
} from "../lib/api";
import { createSamplePricingPortfolio } from "../lib/pricingSample";
import { usePulse } from "../context/PulseContext";

export type FormState = {
  businessName: string;
  businessCategory: string;
  targetOffer: string;
  address: string;
  city: string;
  state: string;
  zip: string;
  radiusMiles: string;
  currentPrice: string;
};

export type MenuItemDraft = {
  id: string;
  name: string;
  price: string;
};

type PositionKey = "below" | "market" | "above" | "unknown";
type PortfolioFilter = "all" | PositionKey;

const DEFAULT_FORM: FormState = {
  businessName: "",
  businessCategory: "",
  targetOffer: "",
  address: "",
  city: "",
  state: "",
  zip: "",
  radiusMiles: "10",
  currentPrice: "",
};

const FILTERS: Array<{ value: PortfolioFilter; label: string }> = [
  { value: "all", label: "All products" },
  { value: "below", label: "Room to grow" },
  { value: "market", label: "On market" },
  { value: "above", label: "Premium" },
];

let menuItemId = 0;
function newMenuItem(name = "", price = ""): MenuItemDraft {
  menuItemId += 1;
  return { id: `menu-item-${menuItemId}`, name, price };
}

export default function Pricing() {
  const { businessName, vertical, customers, portfolio } = usePulse();
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [menuItems, setMenuItems] = useState<MenuItemDraft[]>([newMenuItem()]);
  const [results, setResults] = useState<CompetitorPriceResearchResponse[]>([]);
  const [history, setHistory] = useState<CompetitorPriceHistoryItem[]>([]);
  const [watch, setWatch] = useState<CompetitorPriceWatch | null>(null);
  const [watchSavingOffer, setWatchSavingOffer] = useState<string | null>(null);
  const [expandedOffer, setExpandedOffer] = useState<string | null>(null);
  const [builderOpen, setBuilderOpen] = useState(true);
  const [locationOpen, setLocationOpen] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pastedMenu, setPastedMenu] = useState("");
  const [filter, setFilter] = useState<PortfolioFilter>("all");
  const [loadingOffers, setLoadingOffers] = useState<Set<string>>(new Set());
  const [batchProgress, setBatchProgress] = useState<{ done: number; total: number } | null>(null);
  const [lastDurationMs, setLastDurationMs] = useState<number | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [initialLoading, setInitialLoading] = useState(true);
  const [samplePreview, setSamplePreview] = useState(false);
  const businessNameEdited = useRef(false);
  const menuSeeded = useRef(false);
  const samplePreviewRef = useRef(false);
  const livePortfolioRef = useRef<{
    results: CompetitorPriceResearchResponse[];
    history: CompetitorPriceHistoryItem[];
  }>({ results: [], history: [] });

  useEffect(() => {
    if (!businessName || businessNameEdited.current) return;
    setForm((current) => mergeTenantBusinessName(current, businessName));
  }, [businessName]);

  useEffect(() => {
    const favoriteItems = customers.map((customer) => customer.favorite_item);
    const defaults = deriveTenantPricingDefaults({
      businessName,
      vertical,
      favoriteItems,
      locationLabel: portfolio?.location_label ?? null,
    });
    setForm((current) => mergeEmptyFormValues(current, defaults));
    if (!menuSeeded.current) {
      const suggestions = deriveMenuSuggestions(favoriteItems);
      if (suggestions.length) setMenuItems(suggestions.map((name) => newMenuItem(name)));
      menuSeeded.current = true;
    }
  }, [businessName, customers, portfolio?.location_label, vertical]);

  useEffect(() => {
    let active = true;
    async function loadSavedPricing() {
      try {
        const portfolioPromise = api.competitorPricePortfolio().catch(async () => {
          const latest = await api.latestCompetitorPrices();
          return latest ? [latest] : [];
        });
        const [savedResults, savedHistory, savedWatch] = await Promise.all([
          portfolioPromise,
          api.competitorPriceHistory(50),
          api.competitorPriceWatch(),
        ]);
        if (!active) return;
        livePortfolioRef.current = { results: savedResults, history: savedHistory };
        setWatch(savedWatch);
        const wantsSamplePreview =
          new URLSearchParams(window.location.search).get("sampleCafe") === "1";
        if (wantsSamplePreview) {
          const sample = createSamplePricingPortfolio();
          samplePreviewRef.current = true;
          setSamplePreview(true);
          setResults(sample.results);
          setHistory(sample.history);
          setBuilderOpen(false);
          setMenuItems(
            sample.results.map((result) =>
              newMenuItem(result.query.targetOffer, String(result.query.currentPrice ?? ""))
            )
          );
        } else if (!samplePreviewRef.current) {
          setResults(savedResults);
          setHistory(savedHistory);
          setBuilderOpen(savedResults.length === 0);
        }
        if (savedWatch) {
          setForm((current) => mergeEmptyFormValues(current, formFromResearchInput(savedWatch.request)));
        }
      } catch {
        // The menu builder remains fully usable before the first saved research run.
      } finally {
        if (active) setInitialLoading(false);
      }
    }
    void loadSavedPricing();
    const interval = window.setInterval(loadSavedPricing, 2 * 60 * 60 * 1000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  const validMenuItems = useMemo(
    () => dedupeMenuItems(menuItems.filter((item) => item.name.trim())),
    [menuItems]
  );
  const filteredResults = useMemo(
    () =>
      results.filter((result) => {
        if (filter === "all") return true;
        return getMarketPosition(result).key === filter;
      }),
    [filter, results]
  );
  const pendingCards = useMemo(
    () =>
      validMenuItems.filter(
        (item) =>
          loadingOffers.has(normalizeOffer(item.name)) &&
          !results.some((result) => normalizeOffer(result.query.targetOffer) === normalizeOffer(item.name))
      ),
    [loadingOffers, results, validMenuItems]
  );
  const pulse = useMemo(() => buildPortfolioPulse(results), [results]);

  function updateMenuItem(id: string, patch: Partial<MenuItemDraft>) {
    setMenuItems((current) => current.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  }

  function importPastedMenu() {
    const parsed = parseMenuItems(pastedMenu);
    if (!parsed.length) return;
    setMenuItems(parsed.map((item) => newMenuItem(item.name, item.price)));
    setPastedMenu("");
    setPasteOpen(false);
  }

  function showSampleCafe() {
    if (!samplePreviewRef.current) {
      livePortfolioRef.current = { results, history };
    }
    const sample = createSamplePricingPortfolio();
    samplePreviewRef.current = true;
    setSamplePreview(true);
    setResults(sample.results);
    setHistory(sample.history);
    setMenuItems(
      sample.results.map((result) =>
        newMenuItem(result.query.targetOffer, String(result.query.currentPrice ?? ""))
      )
    );
    setForm((current) => ({
      ...current,
      businessCategory: "Coffee Shop",
      city: "Portland",
      state: "OR",
      radiusMiles: "5",
    }));
    setBuilderOpen(false);
    setExpandedOffer(null);
    setFilter("all");
    setErrors({});
    setLastDurationMs(24_300);
    window.history.replaceState({}, "", `${window.location.pathname}?sampleCafe=1`);
  }

  function closeSampleCafe() {
    samplePreviewRef.current = false;
    setSamplePreview(false);
    setResults(livePortfolioRef.current.results);
    setHistory(livePortfolioRef.current.history);
    setBuilderOpen(livePortfolioRef.current.results.length === 0);
    setExpandedOffer(null);
    setFilter("all");
    setLastDurationMs(null);
    window.history.replaceState({}, "", window.location.pathname);
  }

  async function submitMenu(e: FormEvent) {
    e.preventDefault();
    if (!validMenuItems.length) {
      setErrors({ menu: "Add at least one product or service to research." });
      return;
    }
    if (!form.city.trim() || !form.state.trim()) {
      setErrors({ location: "Add a city and state so Pulse knows which local market to research." });
      setLocationOpen(true);
      return;
    }

    const startedAt = Date.now();
    const queue = [...validMenuItems];
    const queueKeys = new Set(queue.map((item) => normalizeOffer(item.name)));
    setLoadingOffers(queueKeys);
    setBatchProgress({ done: 0, total: queue.length });
    setErrors({});
    let cursor = 0;

    async function worker() {
      while (cursor < queue.length) {
        const item = queue[cursor];
        cursor += 1;
        const key = normalizeOffer(item.name);
        try {
          const response = await api.researchCompetitorPrices(
            buildResearchInput(
              { ...form, targetOffer: item.name.trim(), currentPrice: item.price.trim() },
              businessName
            )
          );
          setResults((current) => {
            const next = replacePortfolioResult(current, response);
            livePortfolioRef.current = { ...livePortfolioRef.current, results: next };
            return next;
          });
        } catch (err) {
          setErrors((current) => ({
            ...current,
            [key]: err instanceof Error ? err.message : "Research failed",
          }));
        } finally {
          setLoadingOffers((current) => {
            const next = new Set(current);
            next.delete(key);
            return next;
          });
          setBatchProgress((current) =>
            current ? { ...current, done: Math.min(current.total, current.done + 1) } : null
          );
        }
      }
    }

    await Promise.all(Array.from({ length: Math.min(2, queue.length) }, () => worker()));
    setLastDurationMs(Date.now() - startedAt);
    setBatchProgress(null);
    try {
      const savedHistory = await api.competitorPriceHistory(50);
      livePortfolioRef.current = { ...livePortfolioRef.current, history: savedHistory };
      setHistory(savedHistory);
    } catch {
      // Fresh cards are already available even if the history refresh fails.
    }
    setBuilderOpen(false);
  }

  async function refreshProduct(result: CompetitorPriceResearchResponse) {
    const key = normalizeOffer(result.query.targetOffer);
    setLoadingOffers((current) => new Set(current).add(key));
    setErrors((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });
    try {
      const response = await api.researchCompetitorPrices(
        buildResearchInput(formForResult(form, result), businessName)
      );
      setResults((current) => {
        const next = replacePortfolioResult(current, response);
        livePortfolioRef.current = { ...livePortfolioRef.current, results: next };
        return next;
      });
      const savedHistory = await api.competitorPriceHistory(50);
      livePortfolioRef.current = { ...livePortfolioRef.current, history: savedHistory };
      setHistory(savedHistory);
    } catch (err) {
      setErrors((current) => ({
        ...current,
        [key]: err instanceof Error ? err.message : "Research failed",
      }));
    } finally {
      setLoadingOffers((current) => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
    }
  }

  async function toggleMonitoring(result: CompetitorPriceResearchResponse) {
    const offer = result.query.targetOffer;
    const isCurrentWatch =
      watch?.enabled && normalizeOffer(watch.request.targetOffer) === normalizeOffer(offer);
    setWatchSavingOffer(offer);
    try {
      setWatch(
        await api.saveCompetitorPriceWatch({
          enabled: !isCurrentWatch,
          intervalHours: 2,
          request: isCurrentWatch
            ? watch.request
            : buildResearchInput(formForResult(form, result), businessName),
        })
      );
    } catch (err) {
      setErrors((current) => ({
        ...current,
        [normalizeOffer(offer)]: err instanceof Error ? err.message : "Could not update monitoring",
      }));
    } finally {
      setWatchSavingOffer(null);
    }
  }

  return (
    <div className="pricing-page space-y-7">
      <header className="anim-fade-up flex flex-wrap items-end justify-between gap-5">
        <div className="max-w-2xl">
          <p className="eyebrow mb-2" style={{ color: "var(--accent)" }}>Pricing intelligence</p>
          <h1 className="text-[40px] font-bold leading-[1.04] tracking-tight" style={{ color: "var(--ink)" }}>
            Know the market. <span className="pricing-script">Own your price.</span>
          </h1>
          <p className="mt-3 max-w-xl text-[15.5px] leading-relaxed" style={{ color: "var(--muted)" }}>
            Turn your menu into a living view of what nearby competitors charge—and where every
            product has room to shine.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {samplePreview ? (
            <button type="button" onClick={closeSampleCafe} className="pricing-sample-button">
              <BackIcon /> Back to live data
            </button>
          ) : (
            <button type="button" onClick={showSampleCafe} className="pricing-sample-button">
              <SparkIcon /> Preview sample café
            </button>
          )}
          {!samplePreview && (
            <button
              type="button"
              onClick={() => setBuilderOpen((open) => !open)}
              className="pricing-primary-button"
            >
              {builderOpen ? <CloseIcon /> : <PlusIcon />}
              {builderOpen ? "Close menu builder" : "Research your menu"}
            </button>
          )}
        </div>
      </header>

      {samplePreview && (
        <div className="pricing-sample-notice anim-fade-up">
          <span className="pricing-sample-mark"><CupIcon /></span>
          <div>
            <p className="font-display text-base font-bold" style={{ color: "var(--ink)" }}>Sample café · Portland market</p>
            <p className="text-xs" style={{ color: "var(--muted)" }}>Eight illustrative products, four local competitors, and four weeks of trend data. Nothing here changes your live research.</p>
          </div>
          <Badge tone="cyan">Preview data</Badge>
        </div>
      )}

      {builderOpen && !samplePreview && (
        <MenuBuilder
          form={form}
          setForm={setForm}
          menuItems={menuItems}
          updateItem={updateMenuItem}
          removeItem={(id) => setMenuItems((items) => items.filter((item) => item.id !== id))}
          addItem={() => setMenuItems((items) => [...items, newMenuItem()])}
          onSubmit={submitMenu}
          loading={batchProgress}
          pasteOpen={pasteOpen}
          setPasteOpen={setPasteOpen}
          pastedMenu={pastedMenu}
          setPastedMenu={setPastedMenu}
          importPastedMenu={importPastedMenu}
          locationOpen={locationOpen}
          setLocationOpen={setLocationOpen}
          businessNameEdited={businessNameEdited}
        />
      )}

      {Object.keys(errors).length > 0 && (
        <div className="grid gap-2" role="status">
          {Object.entries(errors).map(([key, message]) => (
            <div key={key} className="pricing-error">
              <span className="pricing-error-dot" />
              <span className="font-semibold">{key === "menu" || key === "location" ? "Almost there" : titleCase(key)}</span>
              <span style={{ color: "var(--muted)" }}>{message}</span>
            </div>
          ))}
        </div>
      )}

      {initialLoading ? (
        <PricingPortfolioSkeleton />
      ) : results.length === 0 && pendingCards.length === 0 ? (
        <PricingEmptyState onStart={() => setBuilderOpen(true)} />
      ) : (
        <>
          <PortfolioPulse
            pulse={pulse}
            lastDurationMs={lastDurationMs}
            lastUpdated={results[0]?.metadata.generatedAt ?? null}
          />

          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="font-display text-[26px] font-bold" style={{ color: "var(--ink)" }}>Your menu</h2>
              <p className="text-sm" style={{ color: "var(--muted-2)" }}>
                Open a card to see the story behind the number.
              </p>
            </div>
            <div className="flex flex-wrap gap-2" aria-label="Filter products">
              {FILTERS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => setFilter(item.value)}
                  className={`pricing-filter ${filter === item.value ? "is-active" : ""}`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          <div className="pricing-card-grid">
            {pendingCards.map((item) => <ResearchingProductCard key={item.id} item={item} />)}
            {filteredResults.map((result, index) => {
              const offerKey = normalizeOffer(result.query.targetOffer);
              const expanded = expandedOffer === offerKey;
              return (
                <ProductPricingCard
                  key={offerKey}
                  result={result}
                  history={history.filter((item) => normalizeOffer(item.targetOffer) === offerKey)}
                  expanded={expanded}
                  loading={loadingOffers.has(offerKey)}
                  style={{ animationDelay: `${Math.min(index, 6) * 0.06}s` }}
                  onToggle={() => setExpandedOffer(expanded ? null : offerKey)}
                  onRefresh={() => void refreshProduct(result)}
                  onExport={() => exportPricingCsv(result)}
                  onToggleMonitoring={() => void toggleMonitoring(result)}
                  monitoring={
                    Boolean(watch?.enabled) &&
                    normalizeOffer(watch?.request.targetOffer ?? "") === offerKey
                  }
                  watchSaving={watchSavingOffer === result.query.targetOffer}
                  sample={samplePreview}
                />
              );
            })}
          </div>

          {filter !== "all" && filteredResults.length === 0 && (
            <div className="glass p-10 text-center">
              <p className="font-display text-xl font-semibold" style={{ color: "var(--ink)" }}>No products in this view</p>
              <button type="button" className="mt-2 text-sm font-bold" style={{ color: "var(--accent)" }} onClick={() => setFilter("all")}>
                Show the whole menu
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function MenuBuilder({
  form,
  setForm,
  menuItems,
  updateItem,
  removeItem,
  addItem,
  onSubmit,
  loading,
  pasteOpen,
  setPasteOpen,
  pastedMenu,
  setPastedMenu,
  importPastedMenu,
  locationOpen,
  setLocationOpen,
  businessNameEdited,
}: {
  form: FormState;
  setForm: (form: FormState) => void;
  menuItems: MenuItemDraft[];
  updateItem: (id: string, patch: Partial<MenuItemDraft>) => void;
  removeItem: (id: string) => void;
  addItem: () => void;
  onSubmit: (e: FormEvent) => void;
  loading: { done: number; total: number } | null;
  pasteOpen: boolean;
  setPasteOpen: (open: boolean) => void;
  pastedMenu: string;
  setPastedMenu: (value: string) => void;
  importPastedMenu: () => void;
  locationOpen: boolean;
  setLocationOpen: (open: boolean) => void;
  businessNameEdited: React.MutableRefObject<boolean>;
}) {
  return (
    <form onSubmit={onSubmit} className="pricing-builder anim-fade-up">
      <div className="pricing-builder-glow" />
      <div className="relative">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="eyebrow" style={{ color: "var(--on-espresso-accent)" }}>A faster market scan</p>
            <h2 className="mt-1 font-display text-[27px] font-semibold text-white">Drop in your menu</h2>
            <p className="mt-1 max-w-lg text-sm leading-relaxed" style={{ color: "#D8C6B7" }}>
              Add products one by one or paste the whole list. Pulse researches each item against
              the same local market and builds a card for it.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setPasteOpen(!pasteOpen)}
            className="pricing-quiet-dark-button"
          >
            <PasteIcon /> {pasteOpen ? "Use item rows" : "Paste a menu"}
          </button>
        </div>

        {pasteOpen ? (
          <div className="mt-6 rounded-2xl border p-4" style={{ borderColor: "rgba(255,255,255,.12)", background: "rgba(255,255,255,.055)" }}>
            <label className="block">
              <span className="eyebrow" style={{ color: "#CDB9A8" }}>One item per line · prices optional</span>
              <textarea
                value={pastedMenu}
                onChange={(e) => setPastedMenu(e.target.value)}
                rows={6}
                autoFocus
                placeholder={"Cappuccino — $4.75\nCold brew — $5.25\nBlueberry scone — $3.95"}
                className="pricing-menu-textarea"
              />
            </label>
            <div className="mt-3 flex justify-end">
              <button type="button" onClick={importPastedMenu} disabled={!pastedMenu.trim()} className="pricing-cream-button">
                Turn into menu cards <ArrowIcon />
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-6 space-y-2.5">
            {menuItems.map((item, index) => (
              <div key={item.id} className="pricing-menu-row">
                <span className="pricing-menu-number">{String(index + 1).padStart(2, "0")}</span>
                <input
                  aria-label={`Product ${index + 1}`}
                  value={item.name}
                  required={index === 0}
                  onChange={(e) => updateItem(item.id, { name: e.target.value })}
                  placeholder={index === 0 ? "Cappuccino" : "Another menu item"}
                  className="pricing-menu-name"
                />
                <label className="pricing-price-input">
                  <span>$</span>
                  <input
                    aria-label={`Your price for product ${index + 1}`}
                    type="number"
                    min="0"
                    step="0.01"
                    value={item.price}
                    onChange={(e) => updateItem(item.id, { price: e.target.value })}
                    placeholder="Your price"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => removeItem(item.id)}
                  disabled={menuItems.length === 1}
                  className="pricing-remove-item"
                  aria-label={`Remove ${item.name || `product ${index + 1}`}`}
                >
                  <CloseIcon />
                </button>
              </div>
            ))}
            {menuItems.length < 12 && (
              <button type="button" onClick={addItem} className="pricing-add-row">
                <PlusIcon /> Add another item
              </button>
            )}
          </div>
        )}

        <button type="button" onClick={() => setLocationOpen(!locationOpen)} className="pricing-location-toggle">
          <PinIcon />
          <span>
            <b>{form.city && form.state ? `${form.city}, ${form.state}` : "Set your local market"}</b>
            <small>{form.radiusMiles || "10"}-mile research radius</small>
          </span>
          <ChevronIcon open={locationOpen} />
        </button>

        {locationOpen && (
          <div className="pricing-location-grid">
            <DarkField label="Business name" value={form.businessName} placeholder="Northstar Coffee" onChange={(value) => {
              businessNameEdited.current = true;
              setForm({ ...form, businessName: value });
            }} />
            <DarkField label="Business category" value={form.businessCategory} required placeholder="Coffee shop" onChange={(value) => setForm({ ...form, businessCategory: value })} />
            <DarkField label="City" value={form.city} required placeholder="Fremont" onChange={(value) => setForm({ ...form, city: value })} />
            <DarkField label="State" value={form.state} required placeholder="CA" onChange={(value) => setForm({ ...form, state: value })} />
            <DarkField label="Street address" value={form.address} placeholder="3602 Thornton Ave" onChange={(value) => setForm({ ...form, address: value })} />
            <DarkField label="ZIP" value={form.zip} placeholder="94536" onChange={(value) => setForm({ ...form, zip: value })} />
            <DarkField label="Radius in miles" type="number" min="1" max="25" value={form.radiusMiles} onChange={(value) => setForm({ ...form, radiusMiles: value })} />
          </div>
        )}

        <div className="mt-6 flex flex-wrap items-center justify-between gap-4 border-t pt-5" style={{ borderColor: "rgba(255,255,255,.1)" }}>
          <p className="flex items-center gap-2 text-xs" style={{ color: "#BFA999" }}>
            <SparkIcon /> Source-backed results · Cached for 2 hours
          </p>
          <button type="submit" disabled={Boolean(loading)} className="pricing-cream-button pricing-research-button">
            {loading ? (
              <>
                <SpinnerIcon /> Researching {loading.done + 1 > loading.total ? loading.total : loading.done + 1} of {loading.total}
              </>
            ) : (
              <>
                Research {menuItems.filter((item) => item.name.trim()).length || "your"} menu {menuItems.filter((item) => item.name.trim()).length === 1 ? "item" : "items"}
                <ArrowIcon />
              </>
            )}
          </button>
        </div>
        {loading && (
          <div className="mt-4 h-1.5 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,.1)" }}>
            <div className="h-full rounded-full transition-all duration-500" style={{ width: `${(loading.done / loading.total) * 100}%`, background: "var(--on-espresso-accent)" }} />
          </div>
        )}
      </div>
    </form>
  );
}

function PortfolioPulse({
  pulse,
  lastDurationMs,
  lastUpdated,
}: {
  pulse: ReturnType<typeof buildPortfolioPulse>;
  lastDurationMs: number | null;
  lastUpdated: string | null;
}) {
  return (
    <section className="pricing-pulse-card anim-fade-up">
      <div className="pricing-pulse-orbit orbit-one" />
      <div className="pricing-pulse-orbit orbit-two" />
      <div className="relative grid gap-6 lg:grid-cols-[1.15fr_2fr] lg:items-center">
        <div>
          <div className="flex items-center gap-2">
            <span className="pricing-live-dot" />
            <p className="eyebrow" style={{ color: "#CDAA90" }}>Your pricing pulse</p>
          </div>
          <p className="mt-3 font-display text-[29px] font-semibold leading-tight text-white">
            {pulse.opportunities > 0
              ? `${pulse.opportunities} ${pulse.opportunities === 1 ? "item has" : "items have"} room to grow.`
              : "Your menu is holding its ground."}
          </p>
          <p className="mt-2 text-sm leading-relaxed" style={{ color: "#CDB9A8" }}>
            {pulse.priced > 0
              ? `${pulse.priced} of ${pulse.total} products have a clear local benchmark.`
              : "Research is building your first reliable local benchmarks."}
          </p>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <PulseStat label="Products tracked" value={String(pulse.total)} />
          <PulseStat label="Below market" value={String(pulse.opportunities)} accent="#E0A074" />
          <PulseStat label="Right on market" value={String(pulse.onMarket)} accent="#93B684" />
          <PulseStat label="Avg. confidence" value={`${pulse.confidence}%`} />
        </div>
      </div>
      <div className="relative mt-5 flex flex-wrap items-center gap-x-5 gap-y-1 border-t pt-3 text-[11px]" style={{ borderColor: "rgba(255,255,255,.09)", color: "#A9907D" }}>
        {lastUpdated && <span>Latest scan {formatRelativeTime(lastUpdated)}</span>}
        {lastDurationMs !== null && <span>Last menu completed in {formatDuration(lastDurationMs)}</span>}
        <span>Local, source-backed evidence</span>
      </div>
    </section>
  );
}

function PulseStat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="pricing-pulse-stat">
      <p className="stat-number text-[27px]" style={{ color: accent ?? "#FFF9F2" }}>{value}</p>
      <p className="mt-1 text-[11px]" style={{ color: "#BFA999" }}>{label}</p>
    </div>
  );
}

export function ProductPricingCard({
  result,
  history,
  expanded,
  loading,
  onToggle,
  onRefresh,
  onExport,
  onToggleMonitoring,
  monitoring,
  watchSaving,
  sample = false,
  style,
}: {
  result: CompetitorPriceResearchResponse;
  history: CompetitorPriceHistoryItem[];
  expanded: boolean;
  loading: boolean;
  onToggle: () => void;
  onRefresh: () => void;
  onExport: () => void;
  onToggleMonitoring: () => void;
  monitoring: boolean;
  watchSaving: boolean;
  sample?: boolean;
  style?: React.CSSProperties;
}) {
  const summary = result.marketSummary;
  const position = getMarketPosition(result);
  const currentPrice = result.query.currentPrice ?? null;
  const rows = buildCompetitorRows(result);
  return (
    <article className={`pricing-product-card anim-fade-up ${expanded ? "is-expanded" : ""}`} style={style}>
      {loading && <div className="pricing-card-loading"><SpinnerIcon /> Updating market</div>}
      <div className="pricing-card-summary">
        <div className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3.5">
            <ProductIcon category={result.query.businessCategory} />
            <p className="eyebrow truncate" style={{ color: "var(--muted-2)" }}>{result.query.businessCategory}</p>
          </div>
          <PositionBadge position={position} />
        </div>
        <h3 className="mt-3 line-clamp-2 font-display text-[23px] font-bold leading-tight" style={{ color: "var(--ink)" }}>{result.query.targetOffer}</h3>

        <div className="mt-5 grid grid-cols-2 gap-4">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[.12em]" style={{ color: "var(--muted-2)" }}>Your price</p>
            <p className="stat-number mt-1 text-[31px]" style={{ color: currentPrice === null ? "var(--muted-2)" : "var(--ink)" }}>
              {currentPrice === null ? "—" : formatCurrency(currentPrice, true)}
            </p>
          </div>
          <div className="border-l pl-4" style={{ borderColor: "var(--border)" }}>
            <p className="text-[11px] font-bold uppercase tracking-[.12em]" style={{ color: "var(--muted-2)" }}>Market median</p>
            <p className="stat-number mt-1 text-[31px]" style={{ color: "var(--accent-dark)" }}>
              {summary.priceMedian === null ? "—" : formatCurrency(summary.priceMedian, true)}
            </p>
          </div>
        </div>

        <MarketMiniRange result={result} />

        <div className="mt-5 flex items-end justify-between gap-4">
          <div className="flex flex-wrap gap-2">
            <MiniPill icon={<StoreIcon />} label={`${summary.sampleSize} local ${summary.sampleSize === 1 ? "spot" : "spots"}`} />
            <MiniPill icon={<ShieldIcon />} label={`${Math.round(summary.confidence * 100)}% confidence`} />
          </div>
          <HistorySparkline history={history} />
        </div>
      </div>

      <button type="button" onClick={onToggle} aria-expanded={expanded} className="pricing-card-toggle">
        <span>{expanded ? "Close market story" : "View market story"}</span>
        <span className="pricing-toggle-circle"><ChevronIcon open={expanded} /></span>
      </button>

      {expanded && (
        <div className="pricing-card-details">
          <ProductAnalytics result={result} history={history} rows={rows} />
          {result.warnings.length > 0 && <Warnings warnings={result.warnings} />}
          <ResearchStats result={result} />
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t pt-5" style={{ borderColor: "var(--border)" }}>
            <p className="text-xs" style={{ color: "var(--muted-2)" }}>
              {sample
                ? "Illustrative preview · not part of your live research"
                : `Researched ${formatRelativeTime(result.metadata.generatedAt)} · ${result.metadata.cached ? "2-hour cache" : "fresh scan"}`}
            </p>
            <div className="flex flex-wrap gap-2">
              {!sample && (
                <>
                  <button type="button" onClick={onToggleMonitoring} disabled={watchSaving} className={`pricing-detail-button ${monitoring ? "is-monitoring" : ""}`}>
                    <RadarIcon /> {watchSaving ? "Saving…" : monitoring ? "Monitoring every 2h" : "Monitor this item"}
                  </button>
                  <button type="button" onClick={onRefresh} disabled={loading} className="pricing-detail-button"><RefreshIcon /> Refresh</button>
                </>
              )}
              <button type="button" onClick={onExport} className="pricing-detail-button"><DownloadIcon /> Export CSV</button>
            </div>
          </div>
        </div>
      )}
    </article>
  );
}

function ProductAnalytics({
  result,
  history,
  rows,
}: {
  result: CompetitorPriceResearchResponse;
  history: CompetitorPriceHistoryItem[];
  rows: CompetitorTableRow[];
}) {
  const comparisonData = buildComparisonData(result);
  const trendData = [...history]
    .reverse()
    .filter((item) => item.priceMedian !== null)
    .map((item) => ({
      date: new Date(item.generatedAt).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      median: item.priceMedian,
    }));
  const deliveryRows = result.competitors.flatMap((competitor) =>
    competitor.prices
      .filter((price) => price.priceChannel === "delivery")
      .map((price) => ({ competitor, price }))
  );

  return (
    <div className="space-y-5">
      <div className="grid gap-4 xl:grid-cols-2">
        <ChartPanel title="How prices stack up" subtitle="In-store prices from verified local sources">
          {comparisonData.length ? (
            <div className="h-[250px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={comparisonData} layout="vertical" margin={{ top: 8, right: 24, bottom: 0, left: 8 }}>
                  <CartesianGrid stroke="#EADDCC" strokeDasharray="3 5" horizontal={false} />
                  <XAxis type="number" tickFormatter={(value) => `$${value}`} axisLine={false} tickLine={false} tick={{ fill: "#8A7565", fontSize: 11 }} />
                  <YAxis dataKey="name" type="category" width={105} axisLine={false} tickLine={false} tick={{ fill: "#5C4638", fontSize: 11 }} />
                  <Tooltip cursor={{ fill: "rgba(234,221,204,.35)" }} formatter={(value) => [formatCurrency(Number(value), true), "Price"]} contentStyle={{ borderRadius: 12, borderColor: "#EADDCC", background: "#FFF9F2" }} />
                  <Bar dataKey="price" radius={[0, 7, 7, 0]} barSize={18}>
                    {comparisonData.map((item) => <Cell key={item.name} fill={item.isYou ? "#B4532A" : "#C9A98D"} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : <ChartEmpty label="No benchmark-ready competitor prices yet" />}
        </ChartPanel>

        <ChartPanel title="Market movement" subtitle="Median price across your saved scans">
          {trendData.length ? (
            <div className="h-[250px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={trendData} margin={{ top: 18, right: 16, bottom: 0, left: 0 }}>
                  <defs>
                    <linearGradient id={`trend-${normalizeOffer(result.query.targetOffer).replace(/[^a-z0-9]/g, "")}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#B4532A" stopOpacity={0.28} />
                      <stop offset="100%" stopColor="#B4532A" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#EADDCC" strokeDasharray="3 5" vertical={false} />
                  <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fill: "#8A7565", fontSize: 11 }} />
                  <YAxis tickFormatter={(value) => `$${value}`} axisLine={false} tickLine={false} width={42} tick={{ fill: "#8A7565", fontSize: 11 }} domain={["dataMin - 1", "dataMax + 1"]} />
                  <Tooltip formatter={(value) => [formatCurrency(Number(value), true), "Market median"]} contentStyle={{ borderRadius: 12, borderColor: "#EADDCC", background: "#FFF9F2" }} />
                  {result.query.currentPrice !== null && result.query.currentPrice !== undefined && (
                    <ReferenceLine y={result.query.currentPrice} stroke="#5C8A4A" strokeDasharray="4 4" label={{ value: "You", fill: "#5C8A4A", fontSize: 11 }} />
                  )}
                  <Area type="monotone" dataKey="median" stroke="#B4532A" strokeWidth={3} fill={`url(#trend-${normalizeOffer(result.query.targetOffer).replace(/[^a-z0-9]/g, "")})`} activeDot={{ r: 5, fill: "#B4532A", stroke: "#FFF9F2", strokeWidth: 2 }} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : <ChartEmpty label="Your first trend point will appear after this scan" />}
        </ChartPanel>
      </div>

      <MarketRangeStory result={result} />

      <div>
        <div className="mb-3 flex items-end justify-between gap-3">
          <div>
            <h4 className="font-display text-xl font-bold" style={{ color: "var(--ink)" }}>The local lineup</h4>
            <p className="text-xs" style={{ color: "var(--muted-2)" }}>Every number links back to its source.</p>
          </div>
          <Badge tone="slate">{rows.length} observations</Badge>
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {rows.length ? rows.slice(0, 9).map((row, index) => (
            <CompetitorEvidenceCard key={`${row.competitor.name}-${row.price?.sourceUrl ?? index}`} row={row} />
          )) : <div className="col-span-full rounded-2xl border border-dashed p-7 text-center text-sm" style={{ borderColor: "var(--border)", color: "var(--muted)" }}>No exact public prices passed the evidence checks yet.</div>}
        </div>
      </div>

      {deliveryRows.length > 0 && <DeliveryPrices rows={deliveryRows} summary={result.channelSummaries?.delivery ?? null} />}
    </div>
  );
}

function ChartPanel({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <section className="pricing-chart-panel">
      <h4 className="font-display text-lg font-bold" style={{ color: "var(--ink)" }}>{title}</h4>
      <p className="text-xs" style={{ color: "var(--muted-2)" }}>{subtitle}</p>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function ChartEmpty({ label }: { label: string }) {
  return (
    <div className="grid h-[250px] place-items-center rounded-xl border border-dashed" style={{ borderColor: "var(--border)" }}>
      <div className="text-center"><TrendIcon /><p className="mt-2 text-sm" style={{ color: "var(--muted)" }}>{label}</p></div>
    </div>
  );
}

function MarketRangeStory({ result }: { result: CompetitorPriceResearchResponse }) {
  const summary = result.marketSummary;
  const values = [summary.priceLow, summary.priceMedian, summary.priceHigh, result.query.currentPrice].filter((value): value is number => value !== null && value !== undefined);
  if (!values.length) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const padding = Math.max((max - min) * 0.18, 0.5);
  const domainMin = Math.max(0, min - padding);
  const domainMax = max + padding;
  const position = (value: number | null | undefined) => value === null || value === undefined ? null : ((value - domainMin) / (domainMax - domainMin || 1)) * 100;
  return (
    <section className="pricing-range-story">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h4 className="font-display text-xl font-bold text-white">Your place in the market</h4>
          <p className="mt-1 max-w-xl text-sm" style={{ color: "#D4C0B0" }}>{summary.recommendedPositioning}</p>
        </div>
        <div className="flex gap-5 text-right">
          <RangeLegend label="Low" value={summary.priceLow} />
          <RangeLegend label="Median" value={summary.priceMedian} />
          <RangeLegend label="High" value={summary.priceHigh} />
        </div>
      </div>
      <div className="relative mb-7 mt-9 h-3 rounded-full" style={{ background: "linear-gradient(90deg,#7EA36F 0%,#D6A255 50%,#C66B48 100%)" }}>
        {[summary.priceLow, summary.priceMedian, summary.priceHigh].map((value, index) => value !== null && (
          <span key={`${value}-${index}`} className="pricing-range-tick" style={{ left: `${position(value)}%` }} />
        ))}
        {result.query.currentPrice !== null && result.query.currentPrice !== undefined && (
          <span className="pricing-you-marker" style={{ left: `${position(result.query.currentPrice)}%` }}>
            <b>You</b><i />
          </span>
        )}
      </div>
    </section>
  );
}

function RangeLegend({ label, value }: { label: string; value: number | null }) {
  return <div><p className="text-[10px] uppercase tracking-widest" style={{ color: "#A9907D" }}>{label}</p><p className="mt-0.5 font-display font-bold text-white">{value === null ? "—" : formatCurrency(value, true)}</p></div>;
}

function CompetitorEvidenceCard({ row }: { row: CompetitorTableRow }) {
  const price = row.price;
  return (
    <article className="pricing-evidence-card">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-semibold" style={{ color: "var(--ink)" }}>{row.competitor.name}</p>
          <p className="mt-0.5 truncate text-[11px]" style={{ color: "var(--muted-2)" }}>{row.competitor.address || "Local competitor"}</p>
        </div>
        <p className="shrink-0 font-display text-lg font-bold" style={{ color: "var(--accent-dark)" }}>{price ? formatPrice(price) : "—"}</p>
      </div>
      {price ? (
        <>
          <p className="mt-3 line-clamp-2 text-xs leading-relaxed" style={{ color: "var(--muted)" }}>“{price.evidenceText}”</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Badge tone={price.matchQuality === "exact" ? "green" : "amber"}>{price.matchQuality} match</Badge>
            {price.corroborated && <Badge tone="cyan">Corroborated</Badge>}
            <Badge tone={price.freshnessStatus === "current" ? "green" : "slate"}>{price.freshnessStatus ?? "unknown"}</Badge>
          </div>
          <div className="mt-3 flex items-center justify-between gap-3 border-t pt-2.5" style={{ borderColor: "var(--border-soft)" }}>
            <span className="text-[11px] font-semibold" style={{ color: "var(--muted-2)" }}>{Math.round(price.confidence * 100)}% confidence</span>
            <a href={price.sourceUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-bold" style={{ color: "var(--accent)" }}>Source <ExternalIcon /></a>
          </div>
        </>
      ) : <p className="mt-3 text-xs leading-relaxed" style={{ color: "var(--muted)" }}>No explicit numeric price passed the source-evidence checks.</p>}
    </article>
  );
}

function MarketMiniRange({ result }: { result: CompetitorPriceResearchResponse }) {
  const { priceLow, priceMedian, priceHigh } = result.marketSummary;
  if (priceLow === null || priceMedian === null || priceHigh === null) {
    return <div className="mt-5 h-2 rounded-full" style={{ background: "var(--surface-3)" }} />;
  }
  const current = result.query.currentPrice;
  const min = Math.min(priceLow, current ?? priceLow);
  const max = Math.max(priceHigh, current ?? priceHigh);
  const span = max - min || 1;
  const pct = (value: number) => ((value - min) / span) * 100;
  return (
    <div className="mt-5">
      <div className="relative h-2 rounded-full" style={{ background: "linear-gradient(90deg,#D7E4D1,#EAD3B0,#E9BBA8)" }}>
        <span className="pricing-median-dot" style={{ left: `${pct(priceMedian)}%` }} />
        {current !== null && current !== undefined && <span className="pricing-current-dot" style={{ left: `${pct(current)}%` }} />}
      </div>
      <div className="mt-2 flex justify-between text-[10px] font-semibold" style={{ color: "var(--muted-2)" }}>
        <span>{formatCurrency(priceLow, true)} low</span>
        <span>{formatCurrency(priceHigh, true)} high</span>
      </div>
    </div>
  );
}

function HistorySparkline({ history }: { history: CompetitorPriceHistoryItem[] }) {
  const values = history.slice(0, 8).map((item) => item.priceMedian).filter((value): value is number => value !== null).reverse();
  if (values.length < 2) return <div className="h-8 w-16 border-b border-dashed" style={{ borderColor: "var(--border)" }} title="Trend starts after another scan" />;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const points = values.map((value, index) => `${(index / (values.length - 1)) * 64},${27 - ((value - min) / (max - min || 1)) * 22}`).join(" ");
  return <svg aria-label="Recent price trend" viewBox="0 0 64 32" className="h-8 w-16"><polyline points={points} fill="none" stroke="#B4532A" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function MiniPill({ icon, label }: { icon: React.ReactNode; label: string }) {
  return <span className="pricing-mini-pill">{icon}{label}</span>;
}

function PositionBadge({ position }: { position: ReturnType<typeof getMarketPosition> }) {
  return <span className={`pricing-position-badge is-${position.key}`}><span />{position.label}</span>;
}

function ProductIcon({ category }: { category: string }) {
  const lower = category.toLowerCase();
  return (
    <span className="pricing-product-icon">
      {lower.includes("coffee") || lower.includes("cafe") ? <CupIcon /> : lower.includes("gym") || lower.includes("fitness") ? <BoltIcon /> : lower.includes("salon") || lower.includes("spa") ? <SparkIcon /> : <TagIcon />}
    </span>
  );
}

function ResearchingProductCard({ item }: { item: MenuItemDraft }) {
  return (
    <article className="pricing-product-card pricing-researching-card anim-fade-up">
      <div className="pricing-card-summary">
        <div className="flex items-center gap-3.5"><span className="pricing-product-icon"><SpinnerIcon /></span><div><p className="eyebrow" style={{ color: "var(--muted-2)" }}>Researching now</p><h3 className="mt-0.5 font-display text-[23px] font-bold" style={{ color: "var(--ink)" }}>{item.name}</h3></div></div>
        <div className="mt-7 space-y-3"><div className="pricing-skeleton-line w-2/3" /><div className="pricing-skeleton-line w-full" /><div className="pricing-skeleton-line w-5/6" /></div>
        <p className="mt-6 text-xs" style={{ color: "var(--muted)" }}>Discovering local competitors and checking menu sources…</p>
      </div>
    </article>
  );
}

function PricingPortfolioSkeleton() {
  return <div className="pricing-card-grid">{[0, 1, 2].map((item) => <div key={item} className="pricing-product-card p-6"><div className="pricing-skeleton-line w-1/3" /><div className="pricing-skeleton-line mt-5 h-9 w-2/3" /><div className="pricing-skeleton-line mt-8 w-full" /><div className="pricing-skeleton-line mt-3 w-5/6" /></div>)}</div>;
}

function PricingEmptyState({ onStart }: { onStart: () => void }) {
  return (
    <section className="pricing-empty glass anim-fade-up">
      <div className="pricing-empty-illustration">
        <span className="empty-card card-one">Latte <b>$—</b></span>
        <span className="empty-card card-two">Cold brew <b>$—</b></span>
        <span className="empty-card card-three">Scone <b>$—</b></span>
      </div>
      <div className="max-w-lg text-center">
        <p className="eyebrow" style={{ color: "var(--accent)" }}>A blank canvas, for now</p>
        <h2 className="mt-2 font-display text-[30px] font-bold" style={{ color: "var(--ink)" }}>Your pricing board is ready</h2>
        <p className="mt-2 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>Add a few menu items and Pulse will turn local competitor research into a card-by-card market story.</p>
        <button type="button" onClick={onStart} className="pricing-primary-button mt-5"><PlusIcon /> Add your first products</button>
      </div>
    </section>
  );
}

function DarkField({ label, value, onChange, type = "text", required = false, min, max, placeholder }: { label: string; value: string; onChange: (value: string) => void; type?: string; required?: boolean; min?: string; max?: string; placeholder?: string }) {
  return <label className="block"><span className="eyebrow" style={{ color: "#A9907D" }}>{label}</span><input type={type} required={required} min={min} max={max} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} className="pricing-dark-input" /></label>;
}

export function PricingHistory({ history }: { history: CompetitorPriceHistoryItem[] }) {
  if (history.length === 0) return null;
  const alert = history.find((item) => item.changePercent !== null && Math.abs(item.changePercent) >= 5);
  return (
    <div className="glass p-5">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-display text-lg font-bold" style={{ color: "var(--ink)" }}>Pricing trend</h2><p className="text-sm" style={{ color: "var(--muted)" }}>Saved market medians from recent research runs.</p></div>{alert && <Badge tone="amber">Alert: {alert.targetOffer} {alert.changePercent! > 0 ? "+" : ""}{alert.changePercent}%</Badge>}</div>
      <div className="mt-4 overflow-x-auto"><table className="min-w-full text-left text-sm"><thead className="text-xs uppercase tracking-wide" style={{ color: "var(--muted-2)" }}><tr><th className="py-2 pr-4">Offer</th><th className="py-2 pr-4">Median</th><th className="py-2 pr-4">Change</th><th className="py-2">Researched</th></tr></thead><tbody>{history.slice(0, 8).map((item) => <tr key={item.id} className="border-t" style={{ borderColor: "var(--border-soft)" }}><td className="py-2.5 pr-4 font-semibold">{item.targetOffer}</td><td className="py-2.5 pr-4">{item.priceMedian === null ? "No median" : formatCurrency(item.priceMedian, true)}</td><td className="py-2.5 pr-4">{item.changePercent === null ? "—" : `${item.changePercent > 0 ? "+" : ""}${item.changePercent}%`}</td><td className="py-2.5" style={{ color: "var(--muted)" }}>{new Date(item.generatedAt).toLocaleString()}</td></tr>)}</tbody></table></div>
    </div>
  );
}

export function ResearchStats({ result }: { result: CompetitorPriceResearchResponse }) {
  const stats = result.metadata.researchStats;
  return (
    <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
      <MiniStat label="Sources discovered" value={String(stats.sourcesDiscovered)} />
      <MiniStat label="Sources checked" value={String(stats.sourcesChecked)} />
      <MiniStat label="Sources accepted" value={String(stats.sourcesAccepted)} />
      <MiniStat label="Corroborated" value={String(stats.corroboratedCompetitors)} />
      <MiniStat label="Pages fetched" value={String(stats.pagesFetched ?? 0)} />
      <MiniStat label="AI fallbacks" value={String(stats.aiExtractions ?? 0)} />
    </div>
  );
}

export function DeliveryPrices({ rows, summary }: { rows: Array<{ competitor: CompetitorPriceCompetitor; price: CompetitorPrice }>; summary: CompetitorPriceResearchResponse["marketSummary"] | null }) {
  return (
    <div className="rounded-2xl border p-5" style={{ borderColor: "#E8D2B5", background: "#FBF1E2" }}>
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-display text-lg font-bold" style={{ color: "var(--ink)" }}>Delivery marketplace prices</h2><p className="text-sm" style={{ color: "var(--muted)" }}>Shown separately because delivery platforms may add channel-specific markups.</p></div>{summary?.priceMedian !== null && summary?.priceMedian !== undefined && <Badge tone="amber">Median {formatCurrency(summary.priceMedian, true)}</Badge>}</div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">{rows.map(({ competitor, price }) => <div key={`${competitor.name}-${price.sourceUrl}`} className="rounded-xl border p-4" style={{ borderColor: "#E8D2B5", background: "rgba(255,255,255,.45)" }}><div className="flex items-center justify-between gap-3"><p className="font-semibold">{competitor.name}</p><p className="font-display text-lg font-bold">{formatPrice(price)}</p></div><div className="mt-2 flex flex-wrap gap-1"><Badge tone={price.freshnessStatus === "current" ? "green" : "amber"}>{price.freshnessStatus ?? "unknown freshness"}</Badge><Badge tone="cyan">{retrievalLabel(price.retrievalMethod)}</Badge>{price.needsReview && <Badge tone="amber">Needs review</Badge>}</div><p className="mt-2 text-sm" style={{ color: "var(--muted)" }}>“{price.evidenceText}”</p><p className="mt-1 text-xs" style={{ color: "var(--muted-2)" }}>{extractionLabel(price.extractionMethod)}{(price.sourceUpdatedAt || price.sourcePublishedAt) && ` · Source date: ${price.sourceUpdatedAt || price.sourcePublishedAt}`}</p><a href={price.sourceUrl} target="_blank" rel="noreferrer" className="mt-2 inline-block text-sm font-semibold" style={{ color: "var(--accent)" }}>{price.sourceTitle || "Open marketplace source"}</a></div>)}</div>
    </div>
  );
}

export function Badge({ children, tone }: { children: React.ReactNode; tone: "green" | "amber" | "cyan" | "slate" }) {
  const styles = { green: { background: "#E7F0E3", color: "#4F7A40" }, amber: { background: "#F6E9D2", color: "#9A6525" }, cyan: { background: "#E1EEEC", color: "#3E746E" }, slate: { background: "#EEE6DC", color: "#796657" } };
  return <span className="rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide" style={styles[tone]}>{children}</span>;
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border p-3" style={{ borderColor: "var(--border)", background: "rgba(255,255,255,.42)" }}><p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--muted-2)" }}>{label}</p><p className="mt-1 font-display text-lg font-bold" style={{ color: "var(--ink)" }}>{value}</p></div>;
}

function Warnings({ warnings }: { warnings: string[] }) {
  return <div className="mt-5 rounded-2xl border p-4 text-sm" style={{ borderColor: "#E8D2B5", background: "#FBF1E2", color: "#8A5C27" }}><p className="font-semibold">A note about this research</p><ul className="mt-2 list-disc space-y-1 pl-5">{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>;
}

type CompetitorTableRow = { competitor: CompetitorPriceCompetitor; price: CompetitorPrice | null };

export function buildCompetitorRows(result: CompetitorPriceResearchResponse | null): CompetitorTableRow[] {
  if (!result) return [];
  return result.competitors.flatMap<CompetitorTableRow>((competitor) => {
    const prices = competitor.prices.filter((price) => price.priceChannel !== "delivery");
    if (prices.length === 0) return [{ competitor, price: null }];
    return prices.map((price) => ({ competitor, price }));
  });
}

function buildComparisonData(result: CompetitorPriceResearchResponse) {
  const byCompetitor = new Map<string, number>();
  for (const row of buildCompetitorRows(result)) {
    if (!row.price?.includedInMarketSummary) continue;
    const value = priceMidpoint(row.price);
    if (value !== null && !byCompetitor.has(row.competitor.name)) byCompetitor.set(row.competitor.name, value);
  }
  const rows = [...byCompetitor.entries()].map(([name, price]) => ({ name: truncate(name, 16), price, isYou: false }));
  if (result.query.currentPrice !== null && result.query.currentPrice !== undefined) rows.push({ name: "Your price", price: result.query.currentPrice, isYou: true });
  return rows.sort((a, b) => b.price - a.price);
}

export function deriveTenantPricingDefaults(input: { businessName: string; vertical: string; favoriteItems: Array<string | null>; locationLabel: string | null }): FormState {
  const categoryByVertical: Record<string, string> = { cafe: "Coffee Shop", coffee_shop: "Coffee Shop", fitness: "Gym", gym: "Gym", salon: "Hair Salon", med_spa: "Med Spa", boutique: "Boutique" };
  const targetOffer = deriveMenuSuggestions(input.favoriteItems)[0] ?? "";
  const locationParts = (input.locationLabel ?? "").split(",").map((part) => part.trim());
  return { ...DEFAULT_FORM, businessName: input.businessName, businessCategory: categoryByVertical[input.vertical] ?? "Local Business", targetOffer, city: locationParts.length >= 2 ? locationParts[0] : "", state: locationParts.length >= 2 ? locationParts[1] : "", address: locationParts.length < 2 ? input.locationLabel ?? "" : "" };
}

export function deriveMenuSuggestions(items: Array<string | null>, limit = 6): string[] {
  const counts = new Map<string, { label: string; count: number }>();
  for (const item of items) {
    const label = item?.trim();
    if (!label) continue;
    const key = normalizeOffer(label);
    const existing = counts.get(key);
    counts.set(key, { label: existing?.label ?? label, count: (existing?.count ?? 0) + 1 });
  }
  return [...counts.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label)).slice(0, limit).map((item) => item.label);
}

export function parseMenuItems(text: string): Array<{ name: string; price: string }> {
  const parsed: Array<{ name: string; price: string }> = [];
  const seen = new Set<string>();
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.replace(/^\s*(?:[-*•]|\d+[.)])\s*/, "").trim();
    if (!line) continue;
    const match = line.match(/^(.*?)(?:\s+[—–-]\s+|\s*,\s*|\s+)(?:\$(\d+(?:\.\d{1,2})?)|(\d+\.\d{2}))\s*$/);
    const name = (match?.[1] ?? line).trim();
    const price = match?.[2] ?? match?.[3] ?? "";
    const key = normalizeOffer(name);
    if (!name || seen.has(key)) continue;
    seen.add(key);
    parsed.push({ name, price });
  }
  return parsed.slice(0, 12);
}

function dedupeMenuItems(items: MenuItemDraft[]): MenuItemDraft[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = normalizeOffer(item.name);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function mergeEmptyFormValues(form: FormState, defaults: FormState): FormState {
  return Object.fromEntries(Object.entries(form).map(([key, value]) => [key, value || defaults[key as keyof FormState]])) as FormState;
}

export function buildResearchInput(form: FormState, tenantBusinessName: string): CompetitorPriceResearchInput {
  return { businessName: form.businessName || tenantBusinessName, businessCategory: form.businessCategory, targetOffer: form.targetOffer, location: { address: form.address || undefined, city: form.city || undefined, state: form.state || undefined, zip: form.zip || undefined, country: "US" }, radiusMiles: Number(form.radiusMiles || 5), maxCompetitors: 3, maxSourcesPerCompetitor: 3, currentPrice: form.currentPrice ? Number(form.currentPrice) : null };
}

export function formFromResearchInput(input: CompetitorPriceResearchInput): FormState {
  return { businessName: input.businessName ?? "", businessCategory: input.businessCategory, targetOffer: input.targetOffer, address: input.location.address ?? "", city: input.location.city ?? "", state: input.location.state ?? "", zip: input.location.zip ?? "", radiusMiles: String(input.radiusMiles ?? 5), currentPrice: input.currentPrice === null || input.currentPrice === undefined ? "" : String(input.currentPrice) };
}

function formForResult(form: FormState, result: CompetitorPriceResearchResponse): FormState {
  const [city = "", state = ""] = result.query.locationLabel.split(",").map((part) => part.trim());
  return { ...form, businessCategory: result.query.businessCategory, targetOffer: result.query.targetOffer, currentPrice: result.query.currentPrice === null || result.query.currentPrice === undefined ? "" : String(result.query.currentPrice), city: form.city || city, state: form.state || state, radiusMiles: String(result.query.radiusMiles || form.radiusMiles) };
}

function replacePortfolioResult(current: CompetitorPriceResearchResponse[], next: CompetitorPriceResearchResponse) {
  const key = normalizeOffer(next.query.targetOffer);
  return [next, ...current.filter((item) => normalizeOffer(item.query.targetOffer) !== key)];
}

function buildPortfolioPulse(results: CompetitorPriceResearchResponse[]) {
  const positions = results.map(getMarketPosition);
  const confidenceValues = results.map((result) => result.marketSummary.confidence);
  return { total: results.length, priced: results.filter((result) => result.marketSummary.priceMedian !== null).length, opportunities: positions.filter((position) => position.key === "below").length, onMarket: positions.filter((position) => position.key === "market").length, confidence: confidenceValues.length ? Math.round((confidenceValues.reduce((sum, value) => sum + value, 0) / confidenceValues.length) * 100) : 0 };
}

export function getMarketPosition(result: CompetitorPriceResearchResponse): { key: PositionKey; label: string; delta: number | null } {
  const current = result.query.currentPrice;
  const median = result.marketSummary.priceMedian;
  if (current === null || current === undefined || median === null || median === 0) return { key: "unknown", label: "Market snapshot", delta: null };
  const delta = ((current - median) / median) * 100;
  if (delta < -5) return { key: "below", label: `${Math.abs(delta).toFixed(0)}% below`, delta };
  if (delta > 5) return { key: "above", label: `${delta.toFixed(0)}% premium`, delta };
  return { key: "market", label: "Right on market", delta };
}

function exportPricingCsv(result: CompetitorPriceResearchResponse) {
  const csv = buildPricingCsv(result);
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  link.download = `pulse-pricing-${result.query.targetOffer.toLowerCase().replaceAll(" ", "-")}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(link.href), 0);
}

export function buildPricingCsv(result: CompetitorPriceResearchResponse): string {
  const rows = [["competitor", "offer", "price_min", "price_max", "channel", "confidence", "source"], ...result.competitors.flatMap((competitor) => competitor.prices.map((price) => [competitor.name, price.offerName, price.priceMin, price.priceMax, price.priceChannel, price.confidence, price.sourceUrl]))];
  return rows.map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(",")).join("\n");
}

export function mergeTenantBusinessName(form: FormState, businessName: string): FormState {
  return form.businessName ? form : { ...form, businessName };
}

export function formatPrice(price: CompetitorPrice): string {
  if (price.priceType === "quote_based") return "Quote";
  if (price.priceMin !== null && price.priceMax !== null && price.priceMin !== price.priceMax) return `${formatCurrency(price.priceMin, true)}-${formatCurrency(price.priceMax, true)}`;
  const value = price.priceMin ?? price.priceMax;
  return value === null ? "Unknown" : formatCurrency(value, true);
}

function priceMidpoint(price: CompetitorPrice): number | null {
  if (price.priceMin !== null && price.priceMax !== null) return (price.priceMin + price.priceMax) / 2;
  return price.priceMin ?? price.priceMax;
}

function normalizeOffer(value: string): string { return value.trim().toLocaleLowerCase(); }
function titleCase(value: string): string { return value.replace(/[-_]/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function truncate(value: string, length: number): string { return value.length > length ? `${value.slice(0, length - 1)}…` : value; }

function retrievalLabel(method: CompetitorPrice["retrievalMethod"]): string { return method === "direct_fetch" ? "Directly retrieved" : "Search-provided content"; }
function extractionLabel(method: CompetitorPrice["extractionMethod"]): string { const labels: Record<string, string> = { json_ld: "Structured data", visible_text: "Visible text", search_snippet: "Search evidence", sonar: "Perplexity Sonar", tokenmart: "AI fallback", method_consensus: "Method consensus" }; return labels[method ?? ""] ?? "Extraction method unknown"; }
function formatRelativeTime(value: string): string { const diff = Date.now() - new Date(value).getTime(); const minutes = Math.max(0, Math.round(diff / 60000)); if (minutes < 1) return "just now"; if (minutes < 60) return `${minutes}m ago`; const hours = Math.round(minutes / 60); if (hours < 24) return `${hours}h ago`; return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" }); }
function formatDuration(ms: number): string { const totalSeconds = Math.max(0, Math.round(ms / 1000)); const minutes = Math.floor(totalSeconds / 60); const seconds = totalSeconds % 60; return minutes === 0 ? `${seconds}s` : `${minutes}m ${seconds.toString().padStart(2, "0")}s`; }

function ChevronIcon({ open }: { open: boolean }) { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" style={{ transform: open ? "rotate(180deg)" : undefined, transition: "transform .25s ease" }}><path d="m6 9 6 6 6-6" /></svg>; }
function PlusIcon() { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M12 5v14M5 12h14" /></svg>; }
function CloseIcon() { return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="m6 6 12 12M18 6 6 18" /></svg>; }
function ArrowIcon() { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M5 12h14m-5-5 5 5-5 5" /></svg>; }
function BackIcon() { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M19 12H5m5 5-5-5 5-5" /></svg>; }
function PasteIcon() { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="5" y="5" width="14" height="16" rx="2"/><path d="M9 5V3h6v2M8 10h8M8 14h6"/></svg>; }
function PinIcon() { return <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></svg>; }
function SparkIcon() { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="m12 3 1.2 4.2L17 9l-3.8 1.8L12 15l-1.2-4.2L7 9l3.8-1.8L12 3ZM5 14l.8 2.2L8 17l-2.2.8L5 20l-.8-2.2L2 17l2.2-.8L5 14Zm14-1 .8 2.2 2.2.8-2.2.8L19 19l-.8-2.2L16 16l2.2-.8L19 13Z"/></svg>; }
function SpinnerIcon() { return <svg className="pricing-spinner" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9" opacity=".25"/><path d="M21 12a9 9 0 0 0-9-9"/></svg>; }
function CupIcon() { return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M5 8h12v7a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4V8Z"/><path d="M17 10h1.5a2.5 2.5 0 0 1 0 5H17M8 4v2m4-2v2"/></svg>; }
function BoltIcon() { return <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"><path d="m13 2-8 12h7l-1 8 8-12h-7l1-8Z"/></svg>; }
function TagIcon() { return <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M20 13 13 20l-9-9V4h7l9 9Z"/><circle cx="8.5" cy="8.5" r="1.5"/></svg>; }
function StoreIcon() { return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 10v10h16V10M3 4h18l-1 6a3 3 0 0 1-5 1 3 3 0 0 1-6 0 3 3 0 0 1-5-1L3 4Z"/></svg>; }
function ShieldIcon() { return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6l-7-3Z"/><path d="m9 12 2 2 4-4"/></svg>; }
function RefreshIcon() { return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 6v6h-6M4 18v-6h6"/><path d="M18.5 9A7 7 0 0 0 6 6.5L4 9m2 6a7 7 0 0 0 12 2.5l2-2.5"/></svg>; }
function DownloadIcon() { return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 3v12m-5-5 5 5 5-5M5 20h14"/></svg>; }
function RadarIcon() { return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 4v8l5 3"/></svg>; }
function ExternalIcon() { return <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 4h6v6M20 4l-9 9"/><path d="M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6"/></svg>; }
function TrendIcon() { return <svg className="mx-auto" width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="#C9A98D" strokeWidth="1.5"><path d="M4 16 9 11l4 3 7-8"/><path d="M15 6h5v5"/></svg>; }
