import { createClient } from "@supabase/supabase-js";

// Public (anon) client — safe to ship to the browser. Login/session live here;
// the access token is forwarded to the Pulse API, which verifies it server-side.
const url = import.meta.env.VITE_SUPABASE_URL || "https://placeholder.supabase.co";
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || "public-anon-placeholder";

export const authConfigured = Boolean(
  import.meta.env.VITE_SUPABASE_URL && import.meta.env.VITE_SUPABASE_ANON_KEY,
);

export const supabase = createClient(url, anonKey, {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
});
