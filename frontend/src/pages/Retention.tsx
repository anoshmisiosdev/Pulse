import { useMemo, useState } from "react";
import { usePulse } from "../context/PulseContext";
import { relativeDays, type CustomerRisk } from "../lib/api";
import { urgencyOf } from "../lib/segments";
import CustomerDrawer from "../components/CustomerDrawer";

export default function Retention() {
  const { customers } = usePulse();
  const [selected, setSelected] = useState<CustomerRisk | null>(null);

  const { urgent, atRisk, watching } = useMemo(() => {
    const byUrgency = (u: string) =>
      customers
        .filter((c) => urgencyOf(c.segment) === u)
        .sort((a, b) => b.score - a.score);
    return { urgent: byUrgency("urgent"), atRisk: byUrgency("at_risk"), watching: byUrgency("watching") };
  }, [customers]);

  const total = urgent.length + atRisk.length + watching.length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-4xl font-extrabold tracking-tight">Retention</h1>
        <p className="mt-1 text-slate-500">
          Your action plan to win customers back — sorted by who needs you most
        </p>
      </div>

      <div className="glass flex items-center justify-between p-5">
        <div className="flex items-center gap-4">
          <div className="grid h-12 w-12 place-items-center rounded-2xl bg-cyan-50 text-cyan-600">
            <TargetIcon />
          </div>
          <div>
            <p className="font-display text-xl font-bold">{total} customers to reach out to</p>
            <p className="text-sm text-slate-500">Tap a customer below to send them a message and win them back</p>
          </div>
        </div>
        <div className="flex gap-6 text-center">
          <Counter n={urgent.length} label="Urgent" color="#ef4444" />
          <Counter n={atRisk.length} label="At Risk" color="#f59e0b" />
          <Counter n={watching.length} label="Watching" color="#eab308" />
        </div>
      </div>

      {urgent.length > 0 && (
        <Section title="Reach Out Now" note="these customers need you" dot="#ef4444">
          <div className="space-y-3">
            {urgent.map((c, i) => (
              <UrgentRow key={c.customer_id} rank={i + 1} customer={c} onOpen={() => setSelected(c)} />
            ))}
          </div>
        </Section>
      )}

      {(atRisk.length > 0 || watching.length > 0) && (
        <Section title="Keep an Eye On" note="not urgent, but worth watching" dot="#eab308">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {[...atRisk, ...watching].map((c) => (
              <button
                key={c.customer_id}
                onClick={() => setSelected(c)}
                className="glass glass-hover flex items-center justify-between px-4 py-3.5 text-left"
              >
                <div className="flex items-center gap-3">
                  <span className="h-2 w-2 rounded-full bg-amber-400" />
                  <div>
                    <p className="font-semibold text-slate-900">{c.name}</p>
                    <p className="text-xs text-slate-500">
                      {relativeDays(c.days_since_last_visit)}
                      {c.favorite_item && ` · ${c.favorite_item}`}
                    </p>
                  </div>
                </div>
                <ArrowIcon />
              </button>
            ))}
          </div>
        </Section>
      )}

      <div className="glass p-6">
        <div className="mb-3 flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-full bg-indigo-50 text-indigo-500"><SparkIcon /></span>
          <h3 className="font-display text-lg font-bold">Quick Tips</h3>
        </div>
        <ul className="space-y-2 text-sm text-slate-600">
          <Tip><b>Start at the top.</b> The first customer is your most urgent — reach out today.</Tip>
          <Tip><b>Personalize it.</b> Mention their favorite item by name — it shows you care.</Tip>
          <Tip><b>Offer something small.</b> A free drink or 10% off is enough — the gesture matters more than the discount.</Tip>
        </ul>
      </div>

      {selected && <CustomerDrawer customer={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function UrgentRow({ rank, customer, onOpen }: { rank: number; customer: CustomerRisk; onOpen: () => void }) {
  return (
    <div className="glass glass-hover flex items-center justify-between p-4">
      <div className="flex items-center gap-4">
        <span className="grid h-8 w-8 place-items-center rounded-full bg-red-50 font-display font-bold text-red-500">{rank}</span>
        <div>
          <p className="flex items-center gap-2 font-semibold text-slate-900">
            {customer.name}
            <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-600">Urgent</span>
          </p>
          <p className="text-xs text-slate-500">
            Last visited {relativeDays(customer.days_since_last_visit)}
            {customer.favorite_item && ` · Loves ${customer.favorite_item}`}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2 text-cyan-600">
        <IconBtn onClick={onOpen}><MailIcon /></IconBtn>
        <IconBtn onClick={onOpen}><PhoneIcon /></IconBtn>
        <IconBtn onClick={onOpen}><GiftIcon /></IconBtn>
        <button onClick={onOpen} className="ml-1 text-slate-400 hover:text-slate-700"><ArrowIcon /></button>
      </div>
    </div>
  );
}

function Section({ title, note, dot, children }: { title: string; note: string; dot: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-full" style={{ background: dot }} />
        <h2 className="font-display text-lg font-bold">{title}</h2>
        <span className="text-sm text-slate-400">— {note}</span>
      </div>
      {children}
    </div>
  );
}
function Counter({ n, label, color }: { n: number; label: string; color: string }) {
  return (
    <div>
      <p className="font-display text-2xl font-bold" style={{ color }}>{n}</p>
      <p className="text-xs uppercase tracking-wide text-slate-400">{label}</p>
    </div>
  );
}
function IconBtn({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick} className="grid h-9 w-9 place-items-center rounded-full bg-cyan-50 hover:bg-cyan-100">
      {children}
    </button>
  );
}
function Tip({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2">
      <span className="mt-0.5 text-emerald-500">✓</span>
      <span>{children}</span>
    </li>
  );
}

function TargetIcon() { return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1" /></svg>; }
function ArrowIcon() { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" /></svg>; }
function MailIcon() { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="4" width="20" height="16" rx="2" /><path d="m22 7-10 5L2 7" /></svg>; }
function PhoneIcon() { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92Z" /></svg>; }
function GiftIcon() { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="20 12 20 22 4 22 4 12" /><rect x="2" y="7" width="20" height="5" /><line x1="12" y1="22" x2="12" y2="7" /><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z" /><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z" /></svg>; }
function SparkIcon() { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1" /></svg>; }
