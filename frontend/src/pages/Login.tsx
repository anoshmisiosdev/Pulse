import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function Login() {
  const { login, signup, signInWithGoogle } = useAuth();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [businessName, setBusinessName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (mode === "signin") {
        await login(email, password);
      } else {
        const { needsConfirmation } = await signup(email, password, businessName);
        if (needsConfirmation) {
          setNotice("Check your email to confirm your account, then sign in.");
          setMode("signin");
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function onGoogle() {
    setError(null);
    try {
      await signInWithGoogle();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Google sign-in failed");
    }
  }

  const isSignup = mode === "signup";

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-sm">
        <Link to="/" className="mb-6 flex items-center justify-center gap-2">
          <span
            className="font-logo inline-flex h-10 w-10 items-center justify-center rounded-full text-2xl"
            style={{ background: "var(--ink-strong)", color: "var(--cream-text)" }}
          >
            C
          </span>
          <span className="font-display text-2xl font-bold tracking-tight" style={{ color: "var(--ink)" }}>Churnary</span>
        </Link>
        <p className="mb-4 -mt-3 text-center text-xs">
          <Link to="/" className="hover:underline" style={{ color: "var(--muted-2)" }}>← Back to home</Link>
        </p>

        <form onSubmit={onSubmit} className="glass-strong space-y-4 p-7">
          <div>
            <h1 className="font-display text-xl font-bold" style={{ color: "var(--ink)" }}>
              {isSignup ? "Create your account" : "Welcome back"}
            </h1>
            <p className="text-sm" style={{ color: "var(--muted)" }}>
              {isSignup
                ? "Start tracking who's about to churn."
                : "Sign in to your retention dashboard."}
            </p>
          </div>

          <button
            type="button"
            onClick={onGoogle}
            className="flex w-full items-center justify-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium transition hover:brightness-95"
            style={{ borderColor: "var(--border)", background: "var(--surface-2)", color: "var(--ink-strong)" }}
          >
            <GoogleGlyph /> Continue with Google
          </button>

          <div className="flex items-center gap-3 text-xs" style={{ color: "var(--muted-2)" }}>
            <div className="h-px flex-1" style={{ background: "var(--border)" }} /> or <div className="h-px flex-1" style={{ background: "var(--border)" }} />
          </div>

          {isSignup && (
            <label className="block">
              <span className="text-sm font-medium" style={{ color: "var(--ink-strong)" }}>Business name</span>
              <input
                required
                value={businessName}
                onChange={(e) => setBusinessName(e.target.value)}
                className="mt-1 w-full rounded-xl border border-slate-300 bg-white/70 px-3 py-2.5 text-sm outline-none focus:border-[#B4532A] focus:ring-1 focus:ring-[#B4532A]"
                placeholder="Hayward Coffee Co."
              />
            </label>
          )}

          <label className="block">
            <span className="text-sm font-medium" style={{ color: "var(--ink-strong)" }}>Email</span>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-xl border px-3 py-2.5 text-sm outline-none focus:border-[#B4532A] focus:ring-1 focus:ring-[#B4532A]"
              style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--ink)" }}
              placeholder="owner@yourbusiness.com"
              autoComplete="email"
            />
          </label>

          <label className="block">
            <span className="text-sm font-medium" style={{ color: "var(--ink-strong)" }}>Password</span>
            <input
              type="password"
              required
              minLength={6}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-xl border px-3 py-2.5 text-sm outline-none focus:border-[#B4532A] focus:ring-1 focus:ring-[#B4532A]"
              style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--ink)" }}
              placeholder="••••••••"
              autoComplete={isSignup ? "new-password" : "current-password"}
            />
          </label>

          {error && <p className="rounded-lg px-3 py-2 text-sm" style={{ background: "#F7E3DC", color: "#A23B1E" }}>{error}</p>}
          {notice && (
            <p className="rounded-lg px-3 py-2 text-sm" style={{ background: "#E6EFDF", color: "#4F7A40" }}>{notice}</p>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-full px-4 py-2.5 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-60"
            style={{ background: "var(--accent)", boxShadow: "0 6px 16px -6px rgba(180,83,42,.7)" }}
          >
            {busy ? "Please wait…" : isSignup ? "Create account" : "Sign in"}
          </button>

          <p className="text-center text-xs" style={{ color: "var(--muted)" }}>
            {isSignup ? "Already have an account?" : "New to Churnary?"}{" "}
            <button
              type="button"
              onClick={() => {
                setMode(isSignup ? "signin" : "signup");
                setError(null);
                setNotice(null);
              }}
              className="font-semibold hover:underline"
              style={{ color: "var(--accent)" }}
            >
              {isSignup ? "Sign in" : "Create an account"}
            </button>
          </p>
        </form>
      </div>
    </div>
  );
}

function GoogleGlyph() {
  return (
    <svg width="16" height="16" viewBox="0 0 48 48">
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.8-6.8C35.9 2.4 30.4 0 24 0 14.6 0 6.4 5.4 2.6 13.2l7.9 6.1C12.3 13.2 17.6 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.1 24.6c0-1.6-.1-3.1-.4-4.6H24v9.1h12.4c-.5 2.9-2.1 5.3-4.6 7l7.1 5.5c4.1-3.8 6.5-9.4 6.5-16z" />
      <path fill="#FBBC05" d="M10.5 28.3c-.5-1.4-.7-2.9-.7-4.3s.3-3 .7-4.3l-7.9-6.1C1 16.7 0 20.2 0 24s1 7.3 2.6 10.4l7.9-6.1z" />
      <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.1-5.5c-2 1.3-4.5 2.1-8.8 2.1-6.4 0-11.7-3.7-13.5-8.9l-7.9 6.1C6.4 42.6 14.6 48 24 48z" />
    </svg>
  );
}
