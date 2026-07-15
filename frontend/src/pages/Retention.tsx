import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { usePulse } from "../context/PulseContext";
import { relativeDays, type CustomerRisk } from "../lib/api";
import { urgencyOf } from "../lib/segments";
import CustomerDrawer from "../components/CustomerDrawer";

export default function Retention() {
  const { customers, markContacted } = usePulse();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selected, setSelected] = useState<CustomerRisk | null>(null);
  const [done, setDone] = useState<Record<string, boolean>>({});

  const { urgent, atRisk, watching } = useMemo(() => {
    const byUrgency = (u: string) =>
      customers
        .filter((c) => urgencyOf(c.segment) === u)
        .sort((a, b) => b.score - a.score);
    return { urgent: byUrgency("urgent"), atRisk: byUrgency("at_risk"), watching: byUrgency("watching") };
  }, [customers]);

  const total = urgent.length + atRisk.length + watching.length;
  const doneCount = Object.values(done).filter(Boolean).length;
  const remaining = Math.max(0, total - doneCount);
  const progressPct = total > 0 ? Math.round((doneCount / total) * 100) : 0;
  const requestedCustomerId = searchParams.get("customer");

  useEffect(() => {
    if (!requestedCustomerId) return;
    const requested = customers.find((customer) => customer.customer_id === requestedCustomerId);
    if (requested) setSelected(requested);
  }, [customers, requestedCustomerId]);

  const closeSelected = () => {
    setSelected(null);
    if (!requestedCustomerId) return;
    const next = new URLSearchParams(searchParams);
    next.delete("customer");
    setSearchParams(next, { replace: true });
  };

  const mark = (c: CustomerRisk) => {
    setDone((d) => ({ ...d, [c.customer_id]: true }));
    markContacted(c.customer_id);
  };
  const undo = (id: string) => setDone((d) => ({ ...d, [id]: false }));

  return (
    <div className="space-y-6">
      <div className="anim-fade-up">
        <h1 className="text-[38px] font-bold tracking-tight" style={{ color: "var(--ink)" }}>Retention</h1>
        <p className="mt-1 italic" style={{ color: "var(--muted)", fontSize: "15.5px" }}>
          Your action plan to win customers back — sorted by who needs you most
        </p>
      </div>

      {/* summary */}
      <div
        className="anim-fade-up flex flex-col gap-6 rounded-[20px] p-7 sm:flex-row sm:items-center"
        style={{
          animationDelay: "0.05s",
          background: "linear-gradient(115deg,#3B2A20,#4A3527)",
          color: "var(--cream-text)",
        }}
      >
        <div className="flex-1">
          <p className="font-display text-[26px] font-bold">
            {remaining} customers still need you today
          </p>
          <div className="mt-2.5 h-[9px] overflow-hidden rounded-full" style={{ background: "rgba(244,236,224,.18)" }}>
            <div
              className="h-full rounded-full"
              style={{
                background: "var(--sage)",
                width: `${progressPct}%`,
                transition: "width .5s cubic-bezier(.2,.8,.2,1)",
              }}
            />
          </div>
          <p className="mt-2 text-[13.5px]" style={{ color: "#CDB9A8" }}>
            {doneCount} of {total} reached out today — pick up where you left off
          </p>
        </div>
        <div className="flex shrink-0 gap-7">
          <Counter n={urgent.length} label="Urgent" color="#E88A5A" />
          <Counter n={atRisk.length} label="At Risk" color="#E0A074" />
          <Counter n={watching.length} label="Watching" color="#D9C48A" />
        </div>
      </div>

      {urgent.length > 0 && (
        <Section title="Reach Out Now" note="these customers need you" dot="#A23B1E" delay={0.1}>
          <div className="flex flex-col gap-3">
            {urgent.map((c, i) => (
              <UrgentRow
                key={c.customer_id}
                rank={i + 1}
                customer={c}
                done={!!done[c.customer_id]}
                onAct={() => { mark(c); setSelected(c); }}
                onUndo={() => undo(c.customer_id)}
              />
            ))}
          </div>
        </Section>
      )}

      {(atRisk.length > 0 || watching.length > 0) && (
        <Section title="Keep an Eye On" note="not urgent, but worth watching" dot="#D99A4E" delay={0.15}>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {[...atRisk, ...watching].map((c) => {
              const d = !!done[c.customer_id];
              return (
                <button
                  key={c.customer_id}
                  onClick={() => (d ? undo(c.customer_id) : mark(c))}
                  className="flex items-center gap-3 rounded-[14px] border px-[18px] py-[15px] text-left transition"
                  style={{
                    background: d ? "#EEF3E8" : "var(--surface)",
                    borderColor: d ? "#CFE0C2" : "var(--border)",
                    opacity: d ? 0.72 : 1,
                  }}
                >
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: d ? "var(--sage)" : "var(--amber)" }} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[15px] font-bold" style={{ color: "var(--ink)" }}>{c.name}</p>
                    <p className="truncate text-[12.5px]" style={{ color: "var(--muted)" }}>
                      {relativeDays(c.days_since_last_visit)}
                      {c.favorite_item && ` · ${c.favorite_item}`}
                    </p>
                  </div>
                  <span className="shrink-0 text-[15px] font-bold" style={{ color: d ? "var(--sage)" : "var(--muted-2)" }}>
                    {d ? "✓" : "→"}
                  </span>
                </button>
              );
            })}
          </div>
        </Section>
      )}

      {/* quick tips */}
      <div className="glass p-7">
        <div className="mb-4 flex items-center gap-2.5">
          <span className="text-[17px]">✦</span>
          <h3 className="font-display text-[19px] font-semibold" style={{ color: "var(--ink)" }}>Quick Tips</h3>
        </div>
        <ul className="flex flex-col gap-3 text-sm" style={{ color: "#6B5647" }}>
          <Tip><b style={{ color: "var(--ink)" }}>Start at the top.</b> The first customer is your most urgent — reach out today.</Tip>
          <Tip><b style={{ color: "var(--ink)" }}>Personalize it.</b> Mention their favorite item by name — it shows you care.</Tip>
          <Tip><b style={{ color: "var(--ink)" }}>Offer something small.</b> A free drink or 10% off is enough — the gesture matters more than the discount.</Tip>
        </ul>
      </div>

      {selected && <CustomerDrawer customer={selected} onClose={closeSelected} />}
    </div>
  );
}

function UrgentRow({ rank, customer, done, onAct, onUndo }: {
  rank: number; customer: CustomerRisk; done: boolean; onAct: () => void; onUndo: () => void;
}) {
  return (
    <div
      className="flex items-center gap-4 rounded-2xl border px-5 py-4 transition-all"
      style={{
        background: done ? "#EEF3E8" : "var(--surface)",
        borderColor: done ? "#CFE0C2" : "var(--border)",
        borderLeft: `4px solid ${done ? "#5C8A4A" : "#A23B1E"}`,
        opacity: done ? 0.78 : 1,
      }}
    >
      <span
        className="font-display flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[15px] font-extrabold"
        style={done ? { background: "var(--sage)", color: "#fff" } : { background: "#F7E3DC", color: "#A23B1E" }}
      >
        {done ? "✓" : rank}
      </span>
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2.5 text-base font-bold" style={{ color: "var(--ink)" }}>
          <span className="truncate">{customer.name}</span>
          {!done && (
            <span
              className="rounded-full px-2.5 py-0.5 text-[11px] font-bold uppercase"
              style={{ background: "#F7E3DC", color: "#A23B1E", letterSpacing: "0.04em" }}
            >
              Urgent
            </span>
          )}
        </p>
        <p className="mt-0.5 truncate text-[13px]" style={{ color: "var(--muted)" }}>
          Last visited {relativeDays(customer.days_since_last_visit)}
          {customer.favorite_item && ` · Loves ${customer.favorite_item}`}
        </p>
      </div>
      {done ? (
        <div className="flex shrink-0 items-center gap-3">
          <span className="text-sm font-bold" style={{ color: "var(--sage-text)" }}>✓ Reached out</span>
          <button onClick={onUndo} className="text-[13px] underline" style={{ color: "var(--muted-2)" }}>
            Undo
          </button>
        </div>
      ) : (
        <div className="flex shrink-0 gap-2">
          <IconBtn onClick={onAct}><MailIcon /></IconBtn>
          <IconBtn onClick={onAct}><PhoneIcon /></IconBtn>
          <IconBtn onClick={onAct}><GiftIcon /></IconBtn>
        </div>
      )}
    </div>
  );
}

function Section({ title, note, dot, delay, children }: {
  title: string; note: string; dot: string; delay: number; children: React.ReactNode;
}) {
  return (
    <div className="anim-fade-up" style={{ animationDelay: `${delay}s` }}>
      <div className="mb-4 flex items-center gap-2.5">
        <span className="h-[9px] w-[9px] rounded-full" style={{ background: dot }} />
        <h2 className="font-display text-xl font-semibold" style={{ color: "var(--ink)" }}>{title}</h2>
        <span className="text-sm" style={{ color: "var(--muted-2)" }}>— {note}</span>
      </div>
      {children}
    </div>
  );
}

function Counter({ n, label, color }: { n: number; label: string; color: string }) {
  return (
    <div className="text-center">
      <p className="font-display text-[28px] font-bold" style={{ color }}>{n}</p>
      <p className="mt-0.5 text-[11px] uppercase" style={{ color: "#CDB9A8", letterSpacing: "0.1em" }}>{label}</p>
    </div>
  );
}

function IconBtn({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex h-[38px] w-[38px] items-center justify-center rounded-[10px] transition hover:!bg-[#B4532A] hover:!text-white"
      style={{ background: "var(--surface-2)", color: "var(--accent)" }}
    >
      {children}
    </button>
  );
}

function Tip({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2.5">
      <span className="font-bold" style={{ color: "var(--sage)" }}>✓</span>
      <span>{children}</span>
    </li>
  );
}

function MailIcon() { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="4" width="20" height="16" rx="2" /><path d="m22 7-10 5L2 7" /></svg>; }
function PhoneIcon() { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92Z" /></svg>; }
function GiftIcon() { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="20 12 20 22 4 22 4 12" /><rect x="2" y="7" width="20" height="5" /><line x1="12" y1="22" x2="12" y2="7" /><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z" /><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z" /></svg>; }
