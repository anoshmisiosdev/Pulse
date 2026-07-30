import { useEffect, useMemo, useState } from "react";
import {
  api,
  type VisitorDetail,
  type VisitorIdentityLevel,
  type VisitorList,
  type VisitorListItem,
  type VisitorPilotMetrics,
  type VisitorStatus,
} from "../lib/api";

const STATUSES: { value: VisitorStatus; label: string }[] = [
  { value: "new", label: "New" },
  { value: "reviewing", label: "Reviewing" },
  { value: "qualified", label: "Qualified" },
  { value: "contacted", label: "Contacted" },
  { value: "dismissed", label: "Dismissed" },
];

const EVENT_LABELS: Record<string, string> = {
  landing_viewed: "Viewed the landing page",
  landing_section_viewed: "Reached a key section",
  landing_cta_clicked: "Clicked a call to action",
  landing_demo_interacted: "Used the live demo",
  landing_waitlist_started: "Started the waitlist form",
  landing_waitlist_validation_failed: "Had a form validation error",
  landing_waitlist_submit_failed: "Waitlist submission failed",
  waitlist_joined: "Joined the waitlist",
  account_identified: "Signed in to Churnary",
  provider_identified: "Identity provider match",
};

function visitorName(visitor: VisitorListItem): string {
  return visitor.full_name || visitor.company_name || "Anonymous visitor";
}

function initials(visitor: VisitorListItem): string {
  const words = visitorName(visitor).split(/\s+/).filter(Boolean);
  if (visitor.identity_level === "anonymous") return "AN";
  return words.slice(0, 2).map((word) => word[0]).join("").toUpperCase();
}

function relativeTime(value: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  return new Date(value).toLocaleDateString();
}

function intentLabel(score: number): string {
  if (score >= 75) return "High intent";
  if (score >= 40) return "Warm";
  return "Exploring";
}

export default function Visitors() {
  const [days, setDays] = useState(30);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<VisitorStatus | "">("");
  const [identityFilter, setIdentityFilter] = useState<VisitorIdentityLevel | "">("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [data, setData] = useState<VisitorList | null>(null);
  const [pilot, setPilot] = useState<VisitorPilotMetrics | null>(null);
  const [selected, setSelected] = useState<VisitorDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rb2bKeyConfigured = Boolean(String(import.meta.env.VITE_RB2B_KEY ?? "").trim());

  const filters = useMemo(
    () => ({
      days,
      q: query.trim() || undefined,
      status: statusFilter,
      identity: identityFilter,
      source: sourceFilter,
      limit: 100,
    }),
    [days, identityFilter, query, sourceFilter, statusFilter]
  );

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [visitors, pilotMetrics] = await Promise.all([
        api.listVisitors(filters),
        api.visitorPilot(days),
      ]);
      setData(visitors);
      setPilot(pilotMetrics);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load recent visitors");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), query ? 250 : 0);
    return () => window.clearTimeout(timer);
    // filters is memoized from every visible filter control.
  }, [filters]);

  const openVisitor = async (visitor: VisitorListItem) => {
    setDetailLoading(true);
    setError(null);
    try {
      setSelected(await api.visitorDetail(visitor.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load visitor history");
    } finally {
      setDetailLoading(false);
    }
  };

  const setVisitorStatus = async (visitor: VisitorListItem, next: VisitorStatus) => {
    setData((current) =>
      current
        ? {
            ...current,
            items: current.items.map((item) =>
              item.id === visitor.id ? { ...item, status: next } : item
            ),
          }
        : current
    );
    if (selected?.id === visitor.id) setSelected({ ...selected, status: next });
    try {
      const updated = await api.updateVisitorStatus(visitor.id, next);
      setData((current) =>
        current
          ? {
              ...current,
              items: current.items.map((item) =>
                item.id === visitor.id ? updated : item
              ),
            }
          : current
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not update visitor");
      void load();
    }
  };

  const suppress = async (visitor: VisitorDetail) => {
    const confirmed = window.confirm(
      "Suppress this visitor? Churnary will erase their identity and event history, while retaining only one-way hashes so provider data does not recreate the profile."
    );
    if (!confirmed) return;
    try {
      await api.suppressVisitor(visitor.id);
      setSelected(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not suppress visitor");
    }
  };

  const remove = async (visitor: VisitorDetail) => {
    const confirmed = window.confirm(
      "Permanently delete this visitor record? Unlike suppression, a later provider match can recreate it."
    );
    if (!confirmed) return;
    try {
      await api.deleteVisitor(visitor.id);
      setSelected(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not delete visitor");
    }
  };

  const summary = data?.summary;

  return (
    <div className="visitors-page">
      <style>{VISITORS_CSS}</style>

      <header className="visitors-hero anim-fade-up">
        <div>
          <p className="visitors-overline">First-party demand signals</p>
          <h1>Recent visitors</h1>
          <p>
            See which visits show real buying intent, how people found Churnary,
            and when an explicitly permitted provider resolves a business identity.
          </p>
        </div>
        <label>
          Window
          <select value={days} onChange={(event) => setDays(Number(event.target.value))}>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </label>
      </header>

      {error && (
        <div className="visitors-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => void load()}>Try again</button>
        </div>
      )}

      <section className="visitors-metrics" aria-label="Visitor summary">
        <Metric
          label="Active today"
          value={summary?.active_24h ?? 0}
          note="Consented, first-party visitors"
        />
        <Metric
          label={`Unique · ${days}d`}
          value={summary?.unique_visitors ?? 0}
          note={`${summary?.identified_visitors ?? 0} identities resolved`}
        />
        <Metric
          label="Identification"
          value={`${summary?.identification_rate ?? 0}%`}
          note="Waitlist, account, person, or company"
        />
        <Metric
          label="High intent"
          value={summary?.high_intent ?? 0}
          note={`${summary?.waitlist_conversions ?? 0} waitlist conversions`}
          tone="accent"
        />
      </section>

      <section className="visitor-explainer">
        <div className="visitor-explainer-mark" aria-hidden="true">i</div>
        <div>
          <strong>What this view can—and cannot—tell you</strong>
          <p>
            First-party rows are pseudonymous until someone joins the waitlist or signs in.
            RB2B can add a professional or company match for some consented U.S. visitors,
            but a match is a sales signal, not proof that a specific person performed every
            action. Confidence comes from the source label and timeline together.
          </p>
        </div>
      </section>

      <div className="visitors-layout">
        <section className="visitors-main">
          <div className="visitors-toolbar">
            <div className="visitors-search">
              <span aria-hidden="true">⌕</span>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search name, company, email, or role"
                aria-label="Search visitors"
              />
            </div>
            <select
              value={identityFilter}
              onChange={(event) =>
                setIdentityFilter(event.target.value as VisitorIdentityLevel | "")
              }
              aria-label="Filter by identity"
            >
              <option value="">All identities</option>
              <option value="anonymous">Anonymous</option>
              <option value="company">Company</option>
              <option value="person">Person</option>
              <option value="waitlist">Waitlist</option>
              <option value="account">Account</option>
            </select>
            <select
              value={sourceFilter}
              onChange={(event) => setSourceFilter(event.target.value)}
              aria-label="Filter by source"
            >
              <option value="">All sources</option>
              <option value="first_party">First party</option>
              <option value="rb2b">RB2B</option>
            </select>
            <select
              value={statusFilter}
              onChange={(event) =>
                setStatusFilter(event.target.value as VisitorStatus | "")
              }
              aria-label="Filter by status"
            >
              <option value="">All statuses</option>
              {STATUSES.map((item) => (
                <option value={item.value} key={item.value}>{item.label}</option>
              ))}
            </select>
          </div>

          <div className="visitor-list-head">
            <span>{data?.total ?? 0} visitors</span>
            <small>Ranked by intent, then recency</small>
          </div>

          <div className="visitor-list" aria-busy={loading}>
            {loading && !data ? (
              <VisitorSkeleton />
            ) : data?.items.length ? (
              data.items.map((visitor) => (
                <article
                  className="visitor-row"
                  key={visitor.id}
                  onClick={() => void openVisitor(visitor)}
                >
                  <div className={`visitor-avatar identity-${visitor.identity_level}`}>
                    {initials(visitor)}
                  </div>
                  <div className="visitor-person">
                    <div>
                      <strong>{visitorName(visitor)}</strong>
                      <span className={`visitor-source source-${visitor.source_provider}`}>
                        {visitor.source_provider === "first_party"
                          ? visitor.identity_level
                          : visitor.source_provider.toUpperCase()}
                      </span>
                    </div>
                    <p>
                      {[visitor.job_title, visitor.company_name]
                        .filter(Boolean)
                        .join(" · ") ||
                        visitor.primary_email ||
                        "Pseudonymous first-party activity"}
                    </p>
                    <small>
                      {visitor.last_path || "/"}{" "}
                      {visitor.referrer_host ? `· via ${visitor.referrer_host}` : ""}
                    </small>
                  </div>
                  <div className="visitor-intent">
                    <span>{intentLabel(visitor.intent_score)}</span>
                    <strong>{visitor.intent_score}</strong>
                    <i><b style={{ width: `${visitor.intent_score}%` }} /></i>
                  </div>
                  <div className="visitor-recency">
                    <strong>{relativeTime(visitor.last_seen_at)}</strong>
                    <small>
                      {visitor.visit_count} {visitor.visit_count === 1 ? "visit" : "visits"}
                    </small>
                  </div>
                  <select
                    value={visitor.status}
                    aria-label={`Status for ${visitorName(visitor)}`}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) => {
                      event.stopPropagation();
                      void setVisitorStatus(
                        visitor,
                        event.target.value as VisitorStatus
                      );
                    }}
                  >
                    {STATUSES.map((item) => (
                      <option value={item.value} key={item.value}>{item.label}</option>
                    ))}
                  </select>
                  <button
                    type="button"
                    aria-label={`Open ${visitorName(visitor)}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      void openVisitor(visitor);
                    }}
                  >
                    →
                  </button>
                </article>
              ))
            ) : (
              <div className="visitor-empty">
                <span aria-hidden="true">◎</span>
                <h2>No visitors match these filters</h2>
                <p>
                  Consented landing activity will appear here after the database
                  migration is deployed. Provider identities appear only after the
                  RB2B script and webhook are activated.
                </p>
              </div>
            )}
          </div>
        </section>

        <aside className="visitor-pilot">
          <div className="visitor-pilot-title">
            <div>
              <span>Provider pilot</span>
              <h2>RB2B readiness</h2>
            </div>
            <i className={pilot?.deliveries ? "is-live" : ""}>
              {pilot?.deliveries ? "Receiving" : "Standby"}
            </i>
          </div>

          <div className="visitor-readiness">
            <ReadinessRow
              label="Consent-gated script"
              ready={rb2bKeyConfigured}
              note={rb2bKeyConfigured ? "Key configured" : "Needs VITE_RB2B_KEY"}
            />
            <ReadinessRow
              label="Webhook feed"
              ready={Boolean(pilot?.deliveries)}
              note={
                pilot?.deliveries
                  ? `${pilot.deliveries} deliveries received`
                  : "Awaiting first verified payload"
              }
            />
            <ReadinessRow
              label="Privacy controls"
              ready
              note="Consent, GPC, suppression"
            />
          </div>

          <div className="visitor-pilot-grid">
            <PilotNumber label="Unique matches" value={pilot?.unique_profiles ?? 0} />
            <PilotNumber label="Person matches" value={pilot?.person_matches ?? 0} />
            <PilotNumber label="High intent" value={pilot?.high_intent_matches ?? 0} />
            <PilotNumber
              label="Conversion"
              value={`${pilot?.conversion_rate ?? 0}%`}
            />
          </div>

          <p className="visitor-recommendation">
            {pilot?.recommendation ??
              "The reporting layer is ready. Add credentials to begin the measured pilot."}
          </p>
          {pilot?.monthly_cost_usd ? (
            <div className="visitor-cost">
              <span>Configured monthly cost</span>
              <strong>${pilot.monthly_cost_usd.toFixed(0)}</strong>
              <small>
                {pilot.cost_per_match_usd
                  ? `$${pilot.cost_per_match_usd.toFixed(2)} per unique match`
                  : "Waiting for matches"}
              </small>
            </div>
          ) : (
            <p className="visitor-cost-empty">
              Add <code>RB2B_MONTHLY_COST_USD</code> to track cost per match.
            </p>
          )}
          <a
            href="https://app.rb2b.com/script"
            target="_blank"
            rel="noreferrer"
            className="visitor-provider-link"
          >
            Open RB2B setup <span aria-hidden="true">↗</span>
          </a>
        </aside>
      </div>

      {(selected || detailLoading) && (
        <div
          className="visitor-drawer-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setSelected(null);
          }}
        >
          {selected ? (
            <VisitorDrawer
              visitor={selected}
              onClose={() => setSelected(null)}
              onStatus={(next) => void setVisitorStatus(selected, next)}
              onSuppress={() => void suppress(selected)}
              onDelete={() => void remove(selected)}
            />
          ) : (
            <div className="visitor-drawer visitor-drawer-loading">Loading history…</div>
          )}
        </div>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  note,
  tone = "default",
}: {
  label: string;
  value: number | string;
  note: string;
  tone?: "default" | "accent";
}) {
  return (
    <article className={`visitor-metric ${tone === "accent" ? "is-accent" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}

function ReadinessRow({
  label,
  ready,
  note,
}: {
  label: string;
  ready: boolean;
  note: string;
}) {
  return (
    <div>
      <i className={ready ? "is-ready" : ""} aria-hidden="true">
        {ready ? "✓" : "·"}
      </i>
      <span><strong>{label}</strong><small>{note}</small></span>
    </div>
  );
}

function PilotNumber({ label, value }: { label: string; value: number | string }) {
  return <div><strong>{value}</strong><span>{label}</span></div>;
}

function VisitorSkeleton() {
  return (
    <div className="visitor-skeleton" aria-label="Loading visitors">
      {[0, 1, 2, 3].map((item) => <i key={item} />)}
    </div>
  );
}

function VisitorDrawer({
  visitor,
  onClose,
  onStatus,
  onSuppress,
  onDelete,
}: {
  visitor: VisitorDetail;
  onClose: () => void;
  onStatus: (status: VisitorStatus) => void;
  onSuppress: () => void;
  onDelete: () => void;
}) {
  const location = [visitor.city, visitor.state].filter(Boolean).join(", ");
  return (
    <aside className="visitor-drawer" aria-label={`Visitor details for ${visitorName(visitor)}`}>
      <div className="visitor-drawer-head">
        <span>Visitor profile</span>
        <button type="button" onClick={onClose} aria-label="Close visitor details">×</button>
      </div>
      <div className="visitor-drawer-identity">
        <div className={`visitor-avatar identity-${visitor.identity_level}`}>
          {initials(visitor)}
        </div>
        <div>
          <h2>{visitorName(visitor)}</h2>
          <p>
            {[visitor.job_title, visitor.company_name].filter(Boolean).join(" · ") ||
              "Pseudonymous first-party visitor"}
          </p>
          <div>
            <span className={`visitor-source source-${visitor.source_provider}`}>
              {visitor.source_provider === "first_party"
                ? visitor.identity_level
                : visitor.source_provider.toUpperCase()}
            </span>
            <span>{intentLabel(visitor.intent_score)} · {visitor.intent_score}/100</span>
          </div>
        </div>
      </div>

      <div className="visitor-drawer-actions">
        <label>
          Lead status
          <select
            value={visitor.status}
            onChange={(event) => onStatus(event.target.value as VisitorStatus)}
          >
            {STATUSES.map((item) => (
              <option value={item.value} key={item.value}>{item.label}</option>
            ))}
          </select>
        </label>
        {visitor.linkedin_url && (
          <a href={visitor.linkedin_url} target="_blank" rel="noreferrer">
            LinkedIn ↗
          </a>
        )}
        {visitor.primary_email && <a href={`mailto:${visitor.primary_email}`}>Email</a>}
      </div>

      <dl className="visitor-facts">
        <div><dt>Company</dt><dd>{visitor.company_name || "—"}</dd></div>
        <div><dt>Website</dt><dd>{visitor.company_domain || "—"}</dd></div>
        <div><dt>Location</dt><dd>{location || "—"}</dd></div>
        <div><dt>Company size</dt><dd>{visitor.employee_count || "—"}</dd></div>
        <div><dt>First seen</dt><dd>{new Date(visitor.first_seen_at).toLocaleString()}</dd></div>
        <div><dt>Last seen</dt><dd>{new Date(visitor.last_seen_at).toLocaleString()}</dd></div>
        <div><dt>Visits</dt><dd>{visitor.visit_count}</dd></div>
        <div><dt>Last page</dt><dd>{visitor.last_path || "—"}</dd></div>
      </dl>

      <div className="visitor-timeline">
        <div>
          <span>Activity timeline</span>
          <small>{visitor.events.length} events</small>
        </div>
        {visitor.events.length ? (
          <ol>
            {visitor.events.map((event) => (
              <li key={event.id}>
                <i aria-hidden="true" />
                <div>
                  <strong>{EVENT_LABELS[event.event_name] || event.event_name}</strong>
                  <span>
                    {event.path || "Churnary"} · {relativeTime(event.occurred_at)}
                  </span>
                  {event.provider !== "first_party" && <small>{event.provider.toUpperCase()}</small>}
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p>No retained events.</p>
        )}
      </div>

      <div className="visitor-privacy-actions">
        <div>
          <strong>Privacy controls</strong>
          <p>Suppression erases identity and history but prevents a provider from recreating the profile.</p>
        </div>
        <button type="button" onClick={onSuppress}>Suppress & erase</button>
        <button type="button" className="is-delete" onClick={onDelete}>Delete record</button>
      </div>
    </aside>
  );
}

const VISITORS_CSS = `
  .visitors-page { display: flex; flex-direction: column; gap: 24px; }
  .visitors-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; padding: 10px 0 4px; }
  .visitors-overline { margin: 0 0 8px; color: var(--accent); font-size: 10px; font-weight: 800; letter-spacing: .15em; text-transform: uppercase; }
  .visitors-hero h1 { margin: 0; color: var(--ink-strong); font-size: clamp(38px, 5vw, 58px); letter-spacing: -.035em; line-height: .98; }
  .visitors-hero p:not(.visitors-overline) { max-width: 720px; margin: 12px 0 0; color: var(--muted); font-size: 15px; line-height: 1.55; }
  .visitors-hero label { display: flex; flex-direction: column; gap: 5px; color: var(--muted-2); font-size: 10px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }
  .visitors-hero select, .visitors-toolbar select, .visitor-row select, .visitor-drawer-actions select { border: 1px solid var(--border); border-radius: 10px; background: var(--surface); color: var(--ink-strong); padding: 9px 30px 9px 10px; font: 700 12px var(--font-body); }
  .visitors-error { display: flex; align-items: center; justify-content: space-between; gap: 14px; border: 1px solid #e8b9a8; border-radius: 12px; background: #fbeae4; color: var(--accent-dark); padding: 11px 14px; font-size: 13px; }
  .visitors-error button { border: 0; background: none; color: inherit; font-weight: 800; text-decoration: underline; cursor: pointer; }
  .visitors-metrics { display: grid; grid-template-columns: repeat(4, 1fr); overflow: hidden; border: 1px solid var(--border); border-radius: 18px; background: var(--surface); }
  .visitor-metric { min-width: 0; padding: 19px 20px; border-right: 1px solid var(--border-soft); }
  .visitor-metric:last-child { border-right: 0; }
  .visitor-metric > span { display: block; color: var(--muted-2); font-size: 10px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }
  .visitor-metric > strong { display: block; margin-top: 8px; color: var(--ink-strong); font: 700 32px/1 var(--font-display); }
  .visitor-metric > small { display: block; margin-top: 7px; overflow: hidden; color: var(--muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
  .visitor-metric.is-accent { background: var(--ink-strong); }
  .visitor-metric.is-accent > span, .visitor-metric.is-accent > small { color: rgba(244,236,224,.67); }
  .visitor-metric.is-accent > strong { color: var(--signal); }
  .visitor-explainer { display: flex; align-items: flex-start; gap: 13px; border-left: 3px solid var(--signal-deep); background: rgba(115,226,197,.08); padding: 13px 16px; }
  .visitor-explainer-mark { display: grid; width: 20px; height: 20px; flex: 0 0 auto; place-items: center; border-radius: 50%; background: var(--signal-deep); color: white; font: 800 12px Georgia; }
  .visitor-explainer strong { color: var(--ink-strong); font-size: 13px; }
  .visitor-explainer p { margin: 3px 0 0; color: var(--muted); font-size: 12px; line-height: 1.5; }
  .visitors-layout { display: grid; grid-template-columns: minmax(0, 1fr) 284px; align-items: start; gap: 18px; }
  .visitors-main { min-width: 0; overflow: hidden; border: 1px solid var(--border); border-radius: 18px; background: var(--surface); }
  .visitors-toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) auto auto auto; gap: 8px; padding: 13px; border-bottom: 1px solid var(--border-soft); }
  .visitors-search { display: flex; align-items: center; gap: 8px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-2); padding: 0 10px; }
  .visitors-search span { color: var(--muted-2); font-size: 19px; }
  .visitors-search input { width: 100%; min-width: 0; border: 0; outline: 0; background: transparent; color: var(--ink); padding: 9px 0; font: 500 12px var(--font-body); }
  .visitor-list-head { display: flex; align-items: center; justify-content: space-between; padding: 11px 16px; border-bottom: 1px solid var(--border-soft); color: var(--muted); font-size: 11px; }
  .visitor-list-head span { font-weight: 800; color: var(--ink-strong); }
  .visitor-row { display: grid; grid-template-columns: 40px minmax(170px, 1.5fr) minmax(100px, .7fr) 74px 104px 28px; align-items: center; gap: 12px; padding: 14px 15px; border-bottom: 1px solid var(--border-soft); cursor: pointer; transition: background .18s ease; }
  .visitor-row:last-child { border-bottom: 0; }
  .visitor-row:hover { background: var(--surface-2); }
  .visitor-avatar { display: grid; width: 40px; height: 40px; place-items: center; border-radius: 50%; background: var(--surface-3); color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: .03em; }
  .visitor-avatar.identity-person, .visitor-avatar.identity-waitlist, .visitor-avatar.identity-account { background: rgba(180,83,42,.14); color: var(--accent-dark); }
  .visitor-avatar.identity-company { background: rgba(30,155,125,.12); color: var(--signal-deep); }
  .visitor-person { min-width: 0; }
  .visitor-person > div { display: flex; align-items: center; gap: 7px; min-width: 0; }
  .visitor-person strong { overflow: hidden; color: var(--ink-strong); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
  .visitor-person p, .visitor-person small { overflow: hidden; margin: 2px 0 0; color: var(--muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
  .visitor-person small { display: block; color: var(--muted-2); font-size: 10px; }
  .visitor-source { flex: 0 0 auto; border-radius: 999px; background: var(--surface-3); color: var(--muted); padding: 3px 6px; font-size: 8px; font-weight: 900; letter-spacing: .07em; text-transform: uppercase; }
  .visitor-source.source-rb2b { background: rgba(115,226,197,.15); color: var(--signal-deep); }
  .visitor-intent { display: grid; grid-template-columns: 1fr auto; gap: 3px 6px; }
  .visitor-intent span, .visitor-intent strong { color: var(--muted); font-size: 10px; }
  .visitor-intent strong { color: var(--ink-strong); }
  .visitor-intent i { grid-column: 1 / -1; height: 4px; overflow: hidden; border-radius: 99px; background: var(--surface-3); }
  .visitor-intent b { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--amber), var(--accent)); }
  .visitor-recency { text-align: right; }
  .visitor-recency strong, .visitor-recency small { display: block; color: var(--ink-strong); font-size: 11px; }
  .visitor-recency small { margin-top: 2px; color: var(--muted-2); font-size: 9px; }
  .visitor-row > button { border: 0; background: transparent; color: var(--muted-2); font-size: 18px; cursor: pointer; }
  .visitor-empty { display: grid; min-height: 330px; place-items: center; align-content: center; padding: 30px; text-align: center; }
  .visitor-empty > span { color: var(--muted-2); font-size: 34px; }
  .visitor-empty h2 { margin: 10px 0 0; color: var(--ink-strong); font-size: 21px; }
  .visitor-empty p { max-width: 480px; margin: 7px 0 0; color: var(--muted); font-size: 12px; line-height: 1.55; }
  .visitor-skeleton { display: grid; gap: 1px; background: var(--border-soft); }
  .visitor-skeleton i { height: 70px; background: linear-gradient(90deg, var(--surface) 25%, var(--surface-2) 45%, var(--surface) 65%); background-size: 220% 100%; animation: visitorShimmer 1.3s infinite; }
  @keyframes visitorShimmer { to { background-position: -220% 0; } }
  .visitor-pilot { position: sticky; top: 100px; border: 1px solid var(--border); border-radius: 18px; background: var(--ink-strong); color: var(--cream-text); padding: 18px; }
  .visitor-pilot-title { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
  .visitor-pilot-title span { color: var(--on-espresso-accent); font-size: 9px; font-weight: 900; letter-spacing: .12em; text-transform: uppercase; }
  .visitor-pilot-title h2 { margin: 4px 0 0; font-size: 20px; }
  .visitor-pilot-title > i { border-radius: 99px; background: rgba(244,236,224,.1); color: rgba(244,236,224,.55); padding: 5px 7px; font-size: 8px; font-style: normal; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
  .visitor-pilot-title > i.is-live { background: rgba(115,226,197,.13); color: var(--signal); }
  .visitor-readiness { display: grid; gap: 10px; margin: 18px 0; padding: 15px 0; border-block: 1px solid rgba(244,236,224,.12); }
  .visitor-readiness > div { display: flex; align-items: center; gap: 9px; }
  .visitor-readiness i { display: grid; width: 19px; height: 19px; place-items: center; border-radius: 50%; background: rgba(244,236,224,.08); color: rgba(244,236,224,.45); font-style: normal; font-size: 10px; }
  .visitor-readiness i.is-ready { background: rgba(115,226,197,.13); color: var(--signal); }
  .visitor-readiness span { display: flex; min-width: 0; flex-direction: column; }
  .visitor-readiness strong { font-size: 11px; }
  .visitor-readiness small { margin-top: 1px; overflow: hidden; color: rgba(244,236,224,.5); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
  .visitor-pilot-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .visitor-pilot-grid > div { border-radius: 10px; background: rgba(244,236,224,.06); padding: 10px; }
  .visitor-pilot-grid strong, .visitor-pilot-grid span { display: block; }
  .visitor-pilot-grid strong { color: var(--signal); font: 700 20px var(--font-display); }
  .visitor-pilot-grid span { margin-top: 3px; color: rgba(244,236,224,.5); font-size: 8px; font-weight: 700; text-transform: uppercase; }
  .visitor-recommendation { margin: 15px 0; color: rgba(244,236,224,.68); font-size: 10px; line-height: 1.5; }
  .visitor-cost { display: grid; grid-template-columns: 1fr auto; border-top: 1px solid rgba(244,236,224,.12); padding-top: 12px; }
  .visitor-cost span, .visitor-cost small { color: rgba(244,236,224,.48); font-size: 9px; }
  .visitor-cost strong { color: var(--cream-text); font-size: 14px; }
  .visitor-cost small { grid-column: 1 / -1; margin-top: 2px; }
  .visitor-cost-empty { border-top: 1px solid rgba(244,236,224,.12); padding-top: 12px; color: rgba(244,236,224,.48); font-size: 9px; line-height: 1.5; }
  .visitor-cost-empty code { color: var(--on-espresso-accent); }
  .visitor-provider-link { display: flex; justify-content: space-between; margin-top: 14px; border-radius: 9px; background: var(--accent); color: white !important; padding: 10px 11px; font-size: 10px; font-weight: 800; text-decoration: none; }
  .visitor-drawer-backdrop { position: fixed; z-index: 70; inset: 0; display: flex; justify-content: flex-end; background: rgba(42,33,28,.36); backdrop-filter: blur(3px); }
  .visitor-drawer { width: min(540px, 100%); height: 100%; overflow-y: auto; background: var(--surface); box-shadow: -20px 0 60px rgba(42,33,28,.2); padding: 24px; animation: drawerIn .3s ease both; }
  .visitor-drawer-loading { display: grid; place-items: center; color: var(--muted); }
  .visitor-drawer-head { display: flex; align-items: center; justify-content: space-between; }
  .visitor-drawer-head > span { color: var(--accent); font-size: 9px; font-weight: 900; letter-spacing: .14em; text-transform: uppercase; }
  .visitor-drawer-head button { border: 0; background: none; color: var(--muted); font-size: 28px; cursor: pointer; }
  .visitor-drawer-identity { display: flex; align-items: center; gap: 14px; padding: 23px 0; border-bottom: 1px solid var(--border); }
  .visitor-drawer-identity .visitor-avatar { width: 54px; height: 54px; font-size: 14px; }
  .visitor-drawer-identity h2 { margin: 0; color: var(--ink-strong); font-size: 26px; }
  .visitor-drawer-identity p { margin: 2px 0 7px; color: var(--muted); font-size: 12px; }
  .visitor-drawer-identity > div:last-child > div { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 10px; }
  .visitor-drawer-actions { display: flex; align-items: flex-end; gap: 8px; padding: 16px 0; }
  .visitor-drawer-actions label { display: flex; flex: 1; flex-direction: column; gap: 4px; color: var(--muted-2); font-size: 9px; font-weight: 800; text-transform: uppercase; }
  .visitor-drawer-actions > a { border: 1px solid var(--border); border-radius: 9px; background: var(--surface-2); color: var(--ink-strong); padding: 9px 11px; font-size: 10px; font-weight: 800; text-decoration: none; }
  .visitor-facts { display: grid; grid-template-columns: 1fr 1fr; margin: 0; border: 1px solid var(--border); border-radius: 14px; overflow: hidden; }
  .visitor-facts > div { min-width: 0; padding: 11px 12px; border-right: 1px solid var(--border-soft); border-bottom: 1px solid var(--border-soft); }
  .visitor-facts > div:nth-child(2n) { border-right: 0; }
  .visitor-facts > div:nth-last-child(-n + 2) { border-bottom: 0; }
  .visitor-facts dt { color: var(--muted-2); font-size: 8px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
  .visitor-facts dd { overflow: hidden; margin: 4px 0 0; color: var(--ink-strong); font-size: 11px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
  .visitor-timeline { margin-top: 22px; }
  .visitor-timeline > div { display: flex; align-items: center; justify-content: space-between; }
  .visitor-timeline > div span { color: var(--ink-strong); font: 700 17px var(--font-display); }
  .visitor-timeline > div small { color: var(--muted-2); font-size: 9px; }
  .visitor-timeline ol { margin: 14px 0 0; padding: 0; list-style: none; }
  .visitor-timeline li { position: relative; display: grid; grid-template-columns: 14px 1fr; gap: 9px; padding-bottom: 17px; }
  .visitor-timeline li:not(:last-child)::before { content: ""; position: absolute; top: 10px; bottom: -2px; left: 5px; width: 1px; background: var(--border); }
  .visitor-timeline li > i { z-index: 1; width: 11px; height: 11px; margin-top: 3px; border: 3px solid var(--surface); border-radius: 50%; background: var(--accent); box-shadow: 0 0 0 1px var(--border); }
  .visitor-timeline li strong, .visitor-timeline li span, .visitor-timeline li small { display: block; }
  .visitor-timeline li strong { color: var(--ink-strong); font-size: 11px; }
  .visitor-timeline li span { margin-top: 2px; color: var(--muted); font-size: 10px; }
  .visitor-timeline li small { width: max-content; margin-top: 4px; border-radius: 99px; background: rgba(115,226,197,.13); color: var(--signal-deep); padding: 2px 5px; font-size: 7px; font-weight: 900; }
  .visitor-privacy-actions { margin-top: 10px; border-top: 1px solid var(--border); padding-top: 18px; }
  .visitor-privacy-actions > div strong { color: var(--ink-strong); font-size: 12px; }
  .visitor-privacy-actions > div p { margin: 3px 0 12px; color: var(--muted); font-size: 10px; line-height: 1.45; }
  .visitor-privacy-actions > button { margin-right: 7px; border: 1px solid #e2b69f; border-radius: 8px; background: #f8e7de; color: var(--accent-dark); padding: 8px 10px; font-size: 9px; font-weight: 800; cursor: pointer; }
  .visitor-privacy-actions > button.is-delete { border-color: var(--border); background: transparent; color: var(--muted); }
  @media (max-width: 1040px) {
    .visitors-layout { grid-template-columns: 1fr; }
    .visitor-pilot { position: static; }
    .visitors-toolbar { grid-template-columns: 1fr 1fr; }
    .visitors-search { grid-column: 1 / -1; }
  }
  @media (max-width: 760px) {
    .visitors-hero { align-items: flex-start; flex-direction: column; }
    .visitors-metrics { grid-template-columns: 1fr 1fr; }
    .visitor-metric:nth-child(2) { border-right: 0; }
    .visitor-metric:nth-child(-n + 2) { border-bottom: 1px solid var(--border-soft); }
    .visitor-row { grid-template-columns: 40px minmax(0, 1fr) auto; }
    .visitor-intent, .visitor-recency, .visitor-row > select { grid-column: 2; }
    .visitor-intent { width: min(220px, 100%); }
    .visitor-recency { grid-column: 3; grid-row: 2; }
    .visitor-row > select { width: min(160px, 100%); }
    .visitor-row > button { grid-column: 3; grid-row: 1; }
  }
  @media (max-width: 520px) {
    .visitors-toolbar { grid-template-columns: 1fr; }
    .visitors-search { grid-column: auto; }
    .visitor-facts { grid-template-columns: 1fr; }
    .visitor-facts > div { border-right: 0; }
    .visitor-facts > div:nth-last-child(2) { border-bottom: 1px solid var(--border-soft); }
  }
`;
