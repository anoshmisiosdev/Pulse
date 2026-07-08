import { createClient } from "@supabase/supabase-js";

// Public (anon) client — safe to ship to the browser. Login/session live here;
// the access token is forwarded to the Pulse API, which verifies it server-side.
//
// The Supabase↔Vercel integration injects VITE_PUBLIC_* names; a hand-written
// .env may use VITE_*. Accept either so both setups work without renaming.
const env = import.meta.env as Record<string, string | undefined>;
const url = env.VITE_PUBLIC_SUPABASE_URL || env.VITE_SUPABASE_URL || "";
const anonKey =
  env.VITE_PUBLIC_SUPABASE_ANON_KEY ||
  env.VITE_PUBLIC_SUPABASE_PUBLISHABLE_KEY ||
  env.VITE_SUPABASE_ANON_KEY ||
  env.VITE_SUPABASE_PUBLISHABLE_KEY ||
  "";

export const authConfigured = Boolean(url && anonKey);

export const supabase = createClient(
  url || "https://placeholder.supabase.co",
  anonKey || "public-anon-placeholder",
  { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } },
);
