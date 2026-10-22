import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  api,
  type AutomationChannel,
  type ReviewSettings,
  type Team,
  type TeamRole,
  type WebhookDelivery,
  type WebhookEndpoint,
} from "../lib/api";

/** Team, review requests, and webhooks.
 *
 * What a staff member sees is decided by the server (`your_role` from
 * GET /team) rather than by the signed-in user object, so the demo tenant and
 * real accounts behave the same. Hiding the owner-only controls here is a
 * courtesy; the backend refuses those calls with a 403 regardless.
 */
export default function Settings() {
  const [team, setTeam] = useState<Team | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadTeam = useCallback(() => {
    api
      .team()
      .then((t) => {
        setTeam(t);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load your team"));
  }, []);

  useEffect(loadTeam, [loadTeam]);

  const isOwner = team?.your_role === "owner";

  return (
    <div className="space-y-7">
      <div className="anim-fade-up">
        <h1 className="text-[38px] font-bold tracking-tight" style={{ color: "var(--ink)" }}>
          Team &amp; settings
        </h1>
        <p className="mt-1 italic" style={{ color: "var(--muted)", fontSize: "15.5px" }}>
          Who can get in, and what Churnary does on its own.
        </p>
      </div>

      {error && <ErrorLine>{error}</ErrorLine>}
      {team && <TeamSection team={team} isOwner={isOwner} onChanged={loadTeam} />}
      {team && <ReviewSection isOwner={isOwner} />}
      {team && (isOwner ? <WebhookSection /> : <OwnerOnlyNote title="Webhooks" />)}
    </div>
  );
}

// -- Team ---------------------------------------------------------------------

function TeamSection({
  team,
  isOwner,
  onChanged,
}: {
  team: Team;
  isOwner: boolean;
  onChanged: () => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<TeamRole>("staff");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sharedLink, setSharedLink] = useState<{ email: string; link: string } | null>(null);
  const [copied, setCopied] = useState(false);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't work");
    } finally {
      setBusy(false);
    }
  }

  async function invite() {
    const target = email.trim();
    if (!target) return;
    await run(async () => {
      const created = await api.inviteTeammate(target, role);
      setEmail("");
      setCopied(false);
      // Email isn't configured yet: the link is the only way in, and this
      // response is the only place it exists (the server keeps a hash).
      setSharedLink(created.emailed ? null : { email: created.invite.email, link: created.link });
    });
  }

  return (
    <Section
      title="Team"
      subtitle={
        isOwner
          ? "Staff can see who's at risk and run campaigns. Only owners can change billing, export or delete data, or manage the team."
          : "You're on this team as staff. Only an owner can invite people or change roles."
      }
    >
      <ul className="divide-y" style={{ borderColor: "var(--line-soft)" }}>
        {team.members.map((m) => (
          <li key={m.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
            <div>
              <p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
                {m.email}
                {m.is_you && (
                  <span className="ml-2 text-xs font-normal" style={{ color: "var(--muted-2)" }}>
                    (you)
                  </span>
                )}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {isOwner && !m.is_you ? (
                <>
                  <select
                    value={m.role}
                    disabled={busy}
                    onChange={(e) =>
                      run(() => api.setTeammateRole(m.id, e.target.value as TeamRole))
                    }
                    className="rounded-lg border px-2 py-1 text-xs outline-none"
                    style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
                  >
                    <option value="staff">Staff</option>
                    <option value="owner">Owner</option>
                  </select>
                  <SmallButton
                    disabled={busy}
                    onClick={() => {
                      if (window.confirm(`Remove ${m.email}? They lose access immediately.`)) {
                        run(() => api.removeTeammate(m.id));
                      }
                    }}
                  >
                    Remove
                  </SmallButton>
                </>
              ) : (
                <RoleBadge role={m.role} />
              )}
            </div>
          </li>
        ))}
      </ul>

      {isOwner && team.invites.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-bold uppercase" style={{ color: "var(--muted-2)" }}>
            Waiting to accept
          </p>
          <ul className="mt-2 space-y-1.5">
            {team.invites.map((i) => (
              <li key={i.id} className="flex items-center justify-between gap-3 text-sm">
                <span style={{ color: "var(--muted)" }}>
                  {i.email} · {i.role} · expires {new Date(i.expires_at).toLocaleDateString()}
                </span>
                <SmallButton disabled={busy} onClick={() => run(() => api.revokeInvite(i.id))}>
                  Cancel
                </SmallButton>
              </li>
            ))}
          </ul>
        </div>
      )}

      {isOwner && (
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && invite()}
            placeholder="teammate@example.com"
            className="min-w-[14rem] flex-1 rounded-xl border px-3 py-2 text-sm outline-none focus:border-[#B4532A]"
            style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
          />
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as TeamRole)}
            className="rounded-xl border px-3 py-2 text-sm outline-none"
            style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
          >
            <option value="staff">as staff</option>
            <option value="owner">as an owner</option>
          </select>
          <PrimaryButton onClick={invite} disabled={busy || !email.trim()}>
            Send invite
          </PrimaryButton>
        </div>
      )}

      {sharedLink && (
        <div
          className="mt-4 rounded-xl border p-4 text-sm"
          style={{ borderColor: "var(--accent)", background: "var(--surface-2)" }}
        >
          <p style={{ color: "var(--ink)" }}>
            Email isn't set up yet, so send {sharedLink.email} this link yourself. It's shown
            once and only works for that address, for 7 days.
          </p>
          <div className="mt-2 flex gap-2">
            <input
              readOnly
              value={sharedLink.link}
              onFocus={(e) => e.target.select()}
              className="flex-1 rounded-lg border px-2 py-1 font-mono text-xs"
              style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
            />
            <SmallButton
              onClick={() => {
                navigator.clipboard?.writeText(sharedLink.link).then(() => setCopied(true));
              }}
            >
              {copied ? "Copied" : "Copy"}
            </SmallButton>
          </div>
        </div>
      )}

      {error && <ErrorLine>{error}</ErrorLine>}
    </Section>
  );
}

// -- Review requests ----------------------------------------------------------

function ReviewSection({ isOwner }: { isOwner: boolean }) {
  const [settings, setSettings] = useState<ReviewSettings | null>(null);
  const [draft, setDraft] = useState<{
    enabled: boolean;
    review_url: string;
    channel: AutomationChannel;
    delay_days: number;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);

  useEffect(() => {
    api
      .reviewSettings()
      .then((s) => {
        setSettings(s);
        setDraft({
          enabled: s.enabled,
          review_url: s.review_url ?? "",
          channel: s.channel,
          delay_days: s.delay_days,
        });
      })
      .catch((e) => setUnavailable(e instanceof Error ? e.message : "Unavailable"));
  }, []);

  async function save() {
    if (!draft) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const saved = await api.saveReviewSettings({
        ...draft,
        review_url: draft.review_url.trim() || null,
      });
      setSettings(saved);
      setNotice(saved.enabled ? "Saved. Review requests are on." : "Saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    } finally {
      setBusy(false);
    }
  }

  async function draftNow() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.queueReviewRequests();
      setNotice(
        result.queued
          ? `Drafted ${result.queued} review request${result.queued === 1 ? "" : "s"} — approve them on the Campaigns screen.`
          : "Nobody new to ask right now."
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't draft them");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section
      title="Review requests"
      subtitle="When someone you'd been losing comes back, ask them for a review — the best moment you'll get. Each one waits for your approval like any campaign."
    >
      {unavailable ? (
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          {unavailable}
        </p>
      ) : !draft || !settings ? (
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          Loading…
        </p>
      ) : (
        <>
          <label className="flex items-center gap-2.5 text-sm" style={{ color: "var(--ink)" }}>
            <input
              type="checkbox"
              checked={draft.enabled}
              disabled={!isOwner}
              onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
            />
            Ask recovered customers for a review
          </label>

          <div className="mt-4 grid gap-4 sm:grid-cols-[1fr_auto_auto]">
            <Field label="Your review link">
              <input
                value={draft.review_url}
                disabled={!isOwner}
                onChange={(e) => setDraft({ ...draft, review_url: e.target.value })}
                placeholder="https://g.page/r/your-business/review"
                className="w-full rounded-xl border px-3 py-2 text-sm outline-none focus:border-[#B4532A]"
                style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
              />
            </Field>
            <Field label="Send by">
              <select
                value={draft.channel}
                disabled={!isOwner}
                onChange={(e) =>
                  setDraft({ ...draft, channel: e.target.value as AutomationChannel })
                }
                className="rounded-xl border px-3 py-2 text-sm outline-none"
                style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
              >
                <option value="email">Email</option>
                <option value="sms">Text</option>
              </select>
            </Field>
            <Field label="Wait">
              <select
                value={draft.delay_days}
                disabled={!isOwner}
                onChange={(e) => setDraft({ ...draft, delay_days: Number(e.target.value) })}
                className="rounded-xl border px-3 py-2 text-sm outline-none"
                style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
              >
                {[0, 1, 2, 3, 5, 7].map((d) => (
                  <option key={d} value={d}>
                    {d === 0 ? "Same day" : `${d} day${d === 1 ? "" : "s"}`}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <p className="mt-3 text-xs" style={{ color: "var(--muted-2)" }}>
            Only customers who came back in the last {settings.lookback_days} days are asked, and
            nobody is asked more than once every {settings.cooldown_days} days — including anyone
            whose request you dropped.
          </p>

          <div className="mt-4 flex flex-wrap gap-2">
            {isOwner && (
              <PrimaryButton onClick={save} disabled={busy}>
                Save
              </PrimaryButton>
            )}
            {settings.enabled && (
              <SmallButton onClick={draftNow} disabled={busy}>
                Draft requests now
              </SmallButton>
            )}
          </div>
          {!isOwner && (
            <p className="mt-2 text-xs" style={{ color: "var(--muted-2)" }}>
              Only an owner can change these settings.
            </p>
          )}
        </>
      )}
      {notice && <p className="mt-3 text-sm" style={{ color: "var(--ink)" }}>{notice}</p>}
      {error && <ErrorLine>{error}</ErrorLine>}
    </Section>
  );
}

// -- Webhooks -----------------------------------------------------------------

function WebhookSection() {
  const [endpoints, setEndpoints] = useState<WebhookEndpoint[]>([]);
  const [events, setEvents] = useState<string[]>([]);
  const [url, setUrl] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [planNote, setPlanNote] = useState<string | null>(null);
  const [secret, setSecret] = useState<{ url: string; value: string } | null>(null);
  const [testResults, setTestResults] = useState<Record<string, string>>({});
  const [openLog, setOpenLog] = useState<string | null>(null);
  const [log, setLog] = useState<WebhookDelivery[]>([]);

  const load = useCallback(() => {
    Promise.all([api.webhooks(), api.webhookEvents()])
      .then(([rows, evts]) => {
        setEndpoints(rows);
        setEvents(evts);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load webhooks"));
  }, []);

  useEffect(load, [load]);

  async function create() {
    setBusy(true);
    setError(null);
    setPlanNote(null);
    try {
      const created = await api.createWebhook({ url: url.trim(), events: chosen });
      setSecret({ url: created.endpoint.url, value: created.secret });
      setUrl("");
      setChosen([]);
      load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 402) setPlanNote(e.message);
      else setError(e instanceof Error ? e.message : "Couldn't add that endpoint");
    } finally {
      setBusy(false);
    }
  }

  async function act(id: string, action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't work");
    } finally {
      setBusy(false);
    }
    return id;
  }

  async function test(id: string) {
    setTestResults((r) => ({ ...r, [id]: "Sending…" }));
    try {
      const result = await api.testWebhook(id);
      setTestResults((r) => ({
        ...r,
        [id]: result.delivered
          ? `Delivered (HTTP ${result.response_status})`
          : `Failed — ${result.error ?? "no response"}`,
      }));
      load();
    } catch (e) {
      setTestResults((r) => ({ ...r, [id]: e instanceof Error ? e.message : "Failed" }));
    }
  }

  async function toggleLog(id: string) {
    if (openLog === id) {
      setOpenLog(null);
      return;
    }
    setOpenLog(id);
    setLog([]);
    try {
      setLog(await api.webhookDeliveries(id));
    } catch {
      setLog([]);
    }
  }

  return (
    <Section
      title="Webhooks"
      subtitle="Send an event to another tool (Zapier, your CRM, a spreadsheet) when a customer comes back or a campaign goes out. Each request is signed so you can verify it came from us."
    >
      {planNote && (
        <p
          className="mb-4 rounded-xl px-4 py-3 text-sm"
          style={{ background: "var(--surface-2)", color: "var(--ink)" }}
        >
          {planNote}
        </p>
      )}

      {secret && (
        <div
          className="mb-4 rounded-xl border p-4 text-sm"
          style={{ borderColor: "var(--accent)", background: "var(--surface-2)" }}
        >
          <p style={{ color: "var(--ink)" }}>
            Signing secret for {secret.url}. <b>Copy it now — it won't be shown again.</b> Verify
            the <code>Churnary-Signature</code> header with it.
          </p>
          <input
            readOnly
            value={secret.value}
            onFocus={(e) => e.target.select()}
            className="mt-2 w-full rounded-lg border px-2 py-1 font-mono text-xs"
            style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
          />
          <SmallButton onClick={() => setSecret(null)}>I've saved it</SmallButton>
        </div>
      )}

      {endpoints.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          No endpoints yet.
        </p>
      ) : (
        <ul className="space-y-3">
          {endpoints.map((ep) => (
            <li
              key={ep.id}
              className="rounded-xl border p-4"
              style={{ borderColor: "var(--line-soft)" }}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-mono text-sm" style={{ color: "var(--ink)" }}>
                    {ep.url}
                  </p>
                  <p className="mt-0.5 text-xs" style={{ color: "var(--muted-2)" }}>
                    {ep.events.length ? ep.events.join(", ") : "All events"}
                    {" · "}
                    {ep.enabled
                      ? "On"
                      : ep.auto_disabled
                        ? `Paused after ${ep.consecutive_failures} failures in a row`
                        : "Paused"}
                    {ep.last_success_at &&
                      ` · last delivered ${new Date(ep.last_success_at).toLocaleString()}`}
                  </p>
                  {testResults[ep.id] && (
                    <p className="mt-1 text-xs" style={{ color: "var(--ink)" }}>
                      {testResults[ep.id]}
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <SmallButton disabled={busy || !ep.enabled} onClick={() => test(ep.id)}>
                    Send test
                  </SmallButton>
                  <SmallButton
                    disabled={busy}
                    onClick={() => act(ep.id, () => api.updateWebhook(ep.id, { enabled: !ep.enabled }))}
                  >
                    {ep.enabled ? "Pause" : "Resume"}
                  </SmallButton>
                  <SmallButton onClick={() => toggleLog(ep.id)}>
                    {openLog === ep.id ? "Hide log" : "Log"}
                  </SmallButton>
                  <SmallButton
                    disabled={busy}
                    onClick={() => {
                      if (window.confirm("Delete this endpoint? Queued deliveries are dropped.")) {
                        act(ep.id, () => api.deleteWebhook(ep.id));
                      }
                    }}
                  >
                    Delete
                  </SmallButton>
                </div>
              </div>

              {openLog === ep.id && (
                <ul className="mt-3 space-y-1 border-t pt-3 text-xs" style={{ borderColor: "var(--line-soft)" }}>
                  {log.length === 0 ? (
                    <li style={{ color: "var(--muted-2)" }}>Nothing sent yet.</li>
                  ) : (
                    log.map((d) => (
                      <li key={d.id} className="flex flex-wrap justify-between gap-2" style={{ color: "var(--muted)" }}>
                        <span>
                          {d.event_type} · {new Date(d.created_at).toLocaleString()}
                        </span>
                        <span>
                          {d.status === "delivered"
                            ? `delivered (${d.response_status})`
                            : d.status === "failed"
                              ? `failed after ${d.attempts} tries — ${d.last_error ?? ""}`
                              : `retrying (${d.attempts} so far) — ${d.last_error ?? "queued"}`}
                        </span>
                      </li>
                    ))
                  )}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-5 border-t pt-5" style={{ borderColor: "var(--line-soft)" }}>
        <Field label="Add an endpoint">
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://hooks.zapier.com/hooks/catch/…"
            className="w-full rounded-xl border px-3 py-2 text-sm outline-none focus:border-[#B4532A]"
            style={{ borderColor: "var(--line)", background: "#fff", color: "var(--ink)" }}
          />
        </Field>
        <div className="mt-3 flex flex-wrap gap-4 text-sm" style={{ color: "var(--ink)" }}>
          {events.map((evt) => (
            <label key={evt} className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={chosen.includes(evt)}
                onChange={(e) =>
                  setChosen((prev) =>
                    e.target.checked ? [...prev, evt] : prev.filter((x) => x !== evt)
                  )
                }
              />
              {evt}
            </label>
          ))}
          <span className="text-xs" style={{ color: "var(--muted-2)" }}>
            (none ticked = all events)
          </span>
        </div>
        <div className="mt-3">
          <PrimaryButton onClick={create} disabled={busy || !url.trim()}>
            Add endpoint
          </PrimaryButton>
        </div>
      </div>

      {error && <ErrorLine>{error}</ErrorLine>}
    </Section>
  );
}

// -- Shared bits --------------------------------------------------------------

function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className="anim-fade-up rounded-[20px] border p-6"
      style={{ borderColor: "var(--line)", background: "var(--card)" }}
    >
      <h2 className="font-display text-[20px] font-bold" style={{ color: "var(--ink)" }}>
        {title}
      </h2>
      <p className="mt-1 mb-5 text-sm" style={{ color: "var(--muted)" }}>
        {subtitle}
      </p>
      {children}
    </section>
  );
}

function OwnerOnlyNote({ title }: { title: string }) {
  return (
    <Section title={title} subtitle="Only the account owner can manage this.">
      <></>
    </Section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span
        className="mb-1.5 block text-xs font-bold uppercase tracking-wide"
        style={{ color: "var(--muted-2)" }}
      >
        {label}
      </span>
      {children}
    </label>
  );
}

function RoleBadge({ role }: { role: string }) {
  return (
    <span
      className="rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize"
      style={{
        background: role === "owner" ? "var(--accent)" : "var(--surface-2)",
        color: role === "owner" ? "#fff" : "var(--muted)",
      }}
    >
      {role}
    </span>
  );
}

function PrimaryButton({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="rounded-full px-5 py-2 text-sm font-semibold text-white transition hover:-translate-y-px disabled:opacity-50"
      style={{ background: "var(--accent)" }}
    >
      {children}
    </button>
  );
}

function SmallButton({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="rounded-full px-3.5 py-1.5 text-xs font-semibold transition disabled:opacity-40"
      style={{ background: "var(--surface-2)", color: "var(--muted)" }}
    >
      {children}
    </button>
  );
}

function ErrorLine({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-3 text-sm" style={{ color: "var(--accent-dark)" }}>
      {children}
    </p>
  );
}
